#!/usr/bin/env python3
"""mentat-implement — atomic single-plan executor."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from lib import paths  # noqa: E402

_SESSION_SCRIPT = paths.SKILLS_DIR / "mentat-session/scripts/session.py"
_GIT_SCRIPT = paths.SKILLS_DIR / "mentat-git/scripts/git.py"
_GIT_WORKTREE_PY = paths.SKILLS_DIR / "mentat-git/scripts/worktree.py"

from lib import frontmatter as _frontmatter  # noqa: E402
from lib.exits import (  # noqa: E402
    EX_CONFIG,
    EX_DATAERR,
    EX_HITL_REQUIRED,
    EX_NOINPUT,
    EX_OK,
    EX_SOFTWARE,
    EX_UNAVAILABLE,
    EX_USAGE,
)
from lib.loader import load_sibling  # noqa: E402
from lib.session import ensure_session  # noqa: E402
from lib.session import session_dir as _session_dir_fn


def _logs_path() -> str:
    return str(_session_dir_fn(os.environ.get("MENTAT_SESSION", "manual")))


# Exit codes that trigger auto-doctor: TDD/gate fail, HITL ambiguity, CLI/plan errors,
# container down, unhandled exceptions, missing config. Signal exits (130/143) skipped.
_DOCTOR_EXIT_CODES = frozenset(
    {1, EX_HITL_REQUIRED, EX_USAGE, EX_DATAERR, EX_NOINPUT, EX_UNAVAILABLE, EX_SOFTWARE, EX_CONFIG}
)

# Exit codes whose worktree implement must NOT tear down: the two signal exits
# (interrupted mid-work) and EX_HITL_REQUIRED — a wedged AFK left its worktree
# for the operator to resolve the design call and resume.
_PRESERVE_WORKTREE_EXITS = frozenset({130, 143, EX_HITL_REQUIRED})

# ── AFK ambiguity wedge channel ───────────────────────────────────────────────
# An AFK agent has no human to ask (AskUserQuestion stays disallowed so it cannot
# hang on a prompt). When it hits a decision the plan does not resolve it writes
# the blocker to <worktree>/summary.md with frontmatter `status: blocked` and
# stops, rather than guessing. summary.md (not a bespoke marker) keeps one
# report-back file shared with the success path; `status:` distinguishes a
# clean finish from a blocker, and the agent's cwd (the worktree) is a distinct
# location from the success summary's log dir, so the two never collide. The
# filename is the shared lib.events.SUMMARY_FILE — one cross-skill contract.
_BLOCKED_STATUS = "blocked"


_utils = load_sibling(__file__, "harness_utils")


# ── public helpers (patchable in tests) ─────────────────────────────────────


def _plans_dir() -> Path:
    return Path.home() / ".agents" / "plans"


def read_tests_manifest(slug: str) -> tuple[list[str], list[str]]:
    """Return (closed, open) from ~/.agents/plans/<slug>.tests.json. Returns ([], []) if absent."""
    manifest = _plans_dir() / f"{slug}.tests.json"
    if not manifest.exists():
        return [], []
    data = json.loads(manifest.read_text())
    return data.get("closed", []), data.get("open", [])


def compute_ro_mounts(closed: list[str], open_: list[str]) -> list[str]:
    """Paths that must be mounted read-only = closed minus open."""
    open_set = set(open_)
    return [p for p in closed if p not in open_set]


def mark_test_writable(slug: str, path: str) -> None:
    """Move path from closed to open in the tests manifest. Emits test.writable.requested."""
    manifest = _plans_dir() / f"{slug}.tests.json"
    if not manifest.exists():
        print(f"mentat-implement: no manifest for {slug}", file=sys.stderr)
        return
    data = json.loads(manifest.read_text())
    closed: list[str] = data.get("closed", [])
    open_: list[str] = data.get("open", [])
    if path not in closed:
        print(f"mentat-implement: {path} not in closed list for {slug}", file=sys.stderr)
        return
    if path not in open_:
        open_.append(path)
    data["open"] = open_
    manifest.write_text(json.dumps(data, indent=2))
    _emit_event("test.writable.requested", {"slug": slug, "path": path})


def resolve_plan_path(ref: str) -> Path:
    from lib import plans as _plans

    return _plans.resolve_plan_ref(ref)


def parse_frontmatter(plan_path: Path) -> dict[str, str]:
    return _frontmatter.parse(plan_path.read_text())[0]


from lib.events import (
    HITL_IN_SESSION,
    HITL_REQUIRED,
    IMPLEMENT_FAILED,
    MAIN_TREE_REFUSED,
    PREFLIGHT_WORKTREE_FAILED,
    SUMMARY_FILE,
    ejected_payload,
    spawned_payload,
)  # noqa: E402
from lib.events import bind as _bind  # noqa: E402

_emit_event = _bind("mentat-implement")


def _compaction_threshold() -> int | None:
    """Read compaction_threshold_tokens from config. Returns None if absent or unset."""
    from lib.config import load_config_file as _load_cfg

    cfg_path_env = os.environ.get("MENTAT_CONFIG")
    cfg_path = Path(cfg_path_env) if cfg_path_env else Path.home() / ".mentat" / "config.toml"
    if not cfg_path.exists():
        return None
    data = _load_cfg(cfg_path)
    val = data.get("compaction_threshold_tokens")
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid compaction_threshold_tokens in {cfg_path}: {val!r}") from exc


def _checkpoint_if_needed(result: Any, *, slug: str, threshold: int | None) -> None:
    """Write a checkpoint summary if usage_tokens >= threshold."""
    if threshold is None:
        return
    usage = getattr(result, "usage_tokens", None)
    if usage is None or usage < threshold:
        return
    from lib.session import summary_file as _summary_file

    sid = os.environ.get("MENTAT_SESSION", slug)
    path = _summary_file(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nstatus: succeeded\n---\nToken checkpoint: {usage} tokens used "
        f"(threshold {threshold}). Slug: {slug}. Next spawn can use this as seed_summary.\n"
    )


def _prune_worktrees_preflight() -> None:
    """Sweep clean, inactive, stale worktrees before this run starts.

    Scoped to this implement run's chunk_id only — never touches another run's trees.
    """
    from lib import devcontainer, worktrees

    chunk_id = os.environ.get("MENTAT_CHUNK_ID", "").strip()
    if not chunk_id:
        return
    wt_root = Path.cwd() / ".mentat" / "worktrees"
    worktrees.prune_stale(
        wt_root,
        active_slugs=set(devcontainer.list_active_slugs()),
        scope_chunk_ids={chunk_id},
    )


def _repo_root_from_worktree(worktree: Path) -> Path:
    """Return the main worktree root from any registered worktree path.

    Uses the shared git-common-dir (`.git`) rather than counting path components,
    so it works regardless of worktree depth. Falls back to parents[2] on error.
    """
    r = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        cwd=str(worktree),
    )
    if r.returncode == 0:
        common = Path(r.stdout.strip())
        return common.parent if common.name == ".git" else common
    return worktree.parents[2]


def _teardown_worktree(target: Path) -> None:
    """On implement's own failure: drop a clean worktree + its container,
    preserve a dirty one (it holds un-landed work the operator must finish)."""
    from lib import devcontainer, worktrees
    from lib.chunk import chunk_slug_from_worktree

    root = _repo_root_from_worktree(target)
    try:
        cs = chunk_slug_from_worktree(target, root)
    except ValueError:
        cs = target.name
    devcontainer.down(cs)
    if worktrees.teardown(target):
        print(f"mentat-implement: removed clean worktree {target}", file=sys.stderr)
    else:
        print(f"mentat-implement: preserving dirty worktree {target}", file=sys.stderr)


def _run_session_cmd(subcmd: str) -> None:
    """Run `session.py <subcmd> [<session_id>]`.

    Session id appended only when set; session.py falls back to latest session for
    the repo when absent, so doctor/report always fires on a diagnosable death even
    when MENTAT_SESSION is unset.
    """
    if not _SESSION_SCRIPT.exists():
        return
    cmd = ["python3", str(_SESSION_SCRIPT), subcmd]
    session_id = os.environ.get("MENTAT_SESSION")
    if session_id:
        cmd.append(session_id)
    subprocess.run(cmd, capture_output=True, check=False)


def _auto_doctor() -> None:
    """Spawn mentat-session doctor on death. Open $EDITOR on the diagnosis only when
    attached to a TTY — a headless/AFK child inherits $EDITOR but has no terminal, so
    launching a terminal editor (vim) on a pipe blocks the child until its wall-deadline
    kill. The doctor diagnosis is always written; only the interactive open is gated."""
    _run_session_cmd("doctor")
    editor = os.environ.get("EDITOR")
    if editor and sys.stdout.isatty():
        diag = _session_dir_fn(os.environ.get("MENTAT_SESSION", "manual")) / "diagnosis.md"
        if diag.exists():
            subprocess.run([editor, str(diag)], check=False)


def _auto_summary() -> None:
    """On clean finish, write success-side report-back summary."""
    _run_session_cmd("report")


def _is_main_worktree(cwd: Path) -> bool:
    """True iff cwd is inside the main worktree."""
    spec = importlib.util.spec_from_file_location("mentat_git_worktree", _GIT_WORKTREE_PY)
    if spec is None or spec.loader is None:
        return False
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # syntax/import error in worktree.py must not crash preflight
        print(f"mentat-implement: worktree.py load failed: {e}", file=sys.stderr)
        return False
    return bool(mod.is_main_worktree(cwd))


def _skip_preflight(*, reuse_worktree: bool = False) -> bool:
    return reuse_worktree or bool(os.environ.get("MENTAT_SKIP_PREFLIGHT"))


def _in_shared_main_tree(*, reuse_worktree: bool = False) -> bool:
    """True iff running in the shared main worktree, where a ``git checkout``
    flips HEAD for every concurrent session sharing that working tree — the
    branch-leak risk. Separate worktrees each own their HEAD (git refuses
    cross-worktree branch sharing), so an own-worktree run is leak-proof.

    The one shared predicate for "is cwd the live main tree right now" — both the
    leak guard and ``preflight_worktree``'s create gate route through it, so
    the skip→rev-parse→``_is_main_worktree`` triad lives in exactly one place.

    ``--reuse-worktree`` / ``MENTAT_SKIP_PREFLIGHT`` returns False by design: test /
    recovery isolation escape hatches. A run that sets either and switches branches
    in a tmp main tree is its own private repo with no concurrent sessions to leak
    into — the hatch trades the (vacuous) leak risk for hermetic, worktree-free runs.
    Non-repo cwds likewise have no shared HEAD to leak.
    """
    if _skip_preflight(reuse_worktree=reuse_worktree):
        return False
    cwd = Path.cwd()
    in_repo = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if in_repo.returncode != 0:
        return False
    return _is_main_worktree(cwd)


def preflight_worktree(slug: str, *, reuse_worktree: bool = False) -> tuple[int, Path | None]:
    """Auto-create a chunk-keyed worktree for slug if cwd is the main worktree.

    Returns (rc, target). rc=0 → success (target valid or skipped intentionally).
    rc=65 → path conflict. rc=66 → base branch missing. Other → bubble up.

    Skipped (rc=0, target=None) when:
      - ``--reuse-worktree`` or MENTAT_SKIP_PREFLIGHT is set
      - cwd is not in a git repo (test envs)
      - cwd is already a non-main worktree (we're already inside a slug)
    """
    if _skip_preflight(reuse_worktree=reuse_worktree):
        return (0, None)
    if not _GIT_SCRIPT.exists():
        return (0, None)
    if not _in_shared_main_tree(reuse_worktree=reuse_worktree):
        return (0, None)

    from lib.chunk import bind_plan_chunk, make_chunk_id

    chunk_id = os.environ.get("MENTAT_CHUNK_ID", "").strip() or make_chunk_id()
    os.environ["MENTAT_CHUNK_ID"] = chunk_id
    bind_plan_chunk(slug, chunk_id)

    result = subprocess.run(
        ["python3", str(_GIT_SCRIPT), "worktree", "create", slug, "--chunk-id", chunk_id],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return (result.returncode, None)
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if not line:
        return (EX_SOFTWARE, None)
    target = Path(line)
    if not target.is_dir():
        return (EX_SOFTWARE, None)
    return (0, target)


def _run_and_doctor(plan_path: Path, *, harness: str | None = None, model: str | None = None) -> int:
    """Run plan and auto-doctor on diagnosable exit codes (skip 0 and signal exits)."""
    rc = run_plan(plan_path, harness=harness, model=model)
    if rc in _DOCTOR_EXIT_CODES:
        _auto_doctor()
        return rc
    if rc == EX_OK and parse_frontmatter(plan_path).get("kind", "HITL") == "AFK":
        # Summary only for AFK runs that completed the plan. HITL returns 0 by handing
        # off to the calling session — a success summary there would be premature.
        _auto_summary()
    return rc


def _load_mod(key: str, path: Path) -> Any:
    """Load a .py script by path. Module-level so _land_and_review callers can patch it."""
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {key!r} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_HARNESS_DIR = Path(__file__).resolve().parent / "harness"
_HARNESS: dict[str, Path] = {
    "claude-code": _HARNESS_DIR / "claude_code.py",
    "cursor": _HARNESS_DIR / "cursor.py",
}


def _invoke_harness(
    harness: str,
    prompt: str,
    *,
    afk: bool,
    model: str | None = None,
    seed_summary: str | None = None,
) -> Any:
    adapter_path = _HARNESS.get(harness) or _HARNESS["claude-code"]
    mod = _load_mod(harness, adapter_path)
    env_seed = os.environ.get("MENTAT_SEED_SUMMARY") or seed_summary
    return mod.invoke(prompt, afk=afk, model=model, seed_summary=env_seed)


def _detect_self_answer(result: Any) -> bool:
    session_log = getattr(result, "session_log", None)
    if session_log is None:
        return False
    return _utils.detect_self_answer(Path(session_log))


def _blocked_summary_path() -> Path | None:
    """The canonical summary.md path for the current session, or None if session is unset."""
    sid = os.environ.get("MENTAT_SESSION")
    if not sid:
        return None
    from lib.session import summary_file as _summary_file

    return _summary_file(sid)


def _read_summary_at(path: Path) -> str | None:
    """Read and return body from path if status==blocked, else None."""
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    fm, body_start = _frontmatter.parse(text)
    if str(fm.get("status", "")).strip().lower() != _BLOCKED_STATUS:
        return None
    return "\n".join(text.splitlines()[body_start:]).strip()


def _read_blocked_summary(worktree: Path) -> str | None:
    """The agent's blocker body if it wedged, else None.

    Reads from the session log dir (lib.session.summary_file) — the one
    canonical location the AFK agent writes to via $MENTAT_SESSION_LOG.
    Falls back to the worktree path when $MENTAT_SESSION_LOG is unset.
    """
    seam = _blocked_summary_path()
    if seam is not None:
        result = _read_summary_at(seam)
        if result is not None:
            return result
    # Worktree fallback (MENTAT_SESSION unset)
    return _read_summary_at(worktree / SUMMARY_FILE)


def _promote_blocked_summary(body: str) -> None:
    """Ensure the blocker body is in the session log dir's summary.md so
    ``mentat-session report`` surfaces it. Agent already writes there on a wedge;
    this covers the self-answer case where it never wrote the file."""
    seam = _blocked_summary_path()
    target = seam if seam is not None else _session_dir_fn(os.environ.get("MENTAT_SESSION", "manual")) / SUMMARY_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\nstatus: {_BLOCKED_STATUS}\n---\n{body}\n")


_HARNESS_AGENT_DIRS: dict[str, str] = {
    "claude-code": ".claude",
    "cursor": ".cursor",
}


def _veto_agents_dir(harness: str) -> Path:
    dir_name = _HARNESS_AGENT_DIRS.get(harness, ".claude")
    return Path.home() / dir_name / "agents"


def preflight_veto_reviewers(harness: str, *, reuse_worktree: bool = False) -> tuple[int, list[str]]:
    """Check all veto-tier reviewers are registered in the harness agents dir.

    Returns (0, []) when all present. Returns (1, [missing-names]) when any absent.
    Skipped (0, []) when ``--reuse-worktree`` or MENTAT_SKIP_PREFLIGHT is set.
    """
    if _skip_preflight(reuse_worktree=reuse_worktree):
        return (0, [])
    from lib.gates.score import missing_veto_reviewers as _missing

    agents_dir = _veto_agents_dir(harness)
    missing = _missing(agents_dir)
    return (1, missing) if missing else (0, [])


def _strip_frontmatter(text: str) -> str:
    """Strip YAML frontmatter (---...---) from plan body.

    Prevents argparse in claude/cursor CLIs from treating '---' as an
    unknown option flag when the prompt is passed as a positional argument.
    """
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4 :].lstrip("\n")


_AFK_COMMIT_CONTRACT = (
    "Contract: after implementing each slice, stage the slice's "
    "files and run `git commit -m '<type>(<scope>): <one-line "
    "summary>'`. One commit per slice. Do not squash. Do not skip "
    "hooks. If pre-commit hooks fail, fix the issue and create a "
    "new commit — never `--no-verify`."
)

_AFK_AMBIGUITY_CONTRACT = (
    "AFK contract: no human is available to answer questions. If you hit a "
    "decision the plan does not resolve and cannot resolve it safely yourself, "
    "do NOT guess or fabricate. Write the blocker — the question plus the "
    "options you see — to `summary.md` in the session log directory with YAML "
    "frontmatter `---` then `status: blocked` then `---`, and stop immediately. "
    "The session log directory is the parent of `$MENTAT_SESSION_LOG` "
    "(i.e. `$(dirname $MENTAT_SESSION_LOG)/summary.md`). "
    "That file hands the slice back to the operator cleanly; guessing produces "
    "wrong work that looks finished."
)


def run_plan(plan_path: Path, *, harness: str | None = None, model: str | None = None) -> int:
    if not harness:
        harness = _utils.default_harness()

    fm = parse_frontmatter(plan_path)
    plan_kind = fm.get("kind", "HITL")
    afk = plan_kind == "AFK"

    slug = plan_path.stem

    # HITL plans run in the calling Claude session — never spawn a sub-claude
    # via the harness adapter (it would shell `claude --headless` and lose
    # AskUserQuestion). Emit chunk_started{harness:"hitl-in-session"} and
    # return control to the caller; the calling session reads the audit log
    # and drives the TDD loop itself.
    if not afk:
        _emit_event(
            "chunk_started",
            spawned_payload(slug, str(plan_path), harness=HITL_IN_SESSION, worktree=str(Path.cwd())),
        )
        _emit_event("agent_started", {"harness": HITL_IN_SESSION})
        print(
            f"mentat-implement: {slug} is kind:HITL — drive in calling Claude session.\nPlan: {plan_path}",
            file=sys.stderr,
        )
        return 0

    # Inject read-only test mounts before container-up (ADR-0010)
    closed, open_ = read_tests_manifest(slug)
    ro = compute_ro_mounts(closed, open_)
    if ro:
        os.environ["MENTAT_RO_MOUNTS"] = json.dumps(ro)

    # Reached only on the AFK path — the HITL early-return above guarantees afk.
    plan_body = _strip_frontmatter(plan_path.read_text())
    home_agents = str(Path.home()) + "/.agents/"
    cwd_agents = str(Path.cwd()) + "/.agents/"
    if home_agents != cwd_agents and Path(cwd_agents).is_dir():
        plan_body = plan_body.replace(home_agents, cwd_agents)
    prompt = f"{_AFK_COMMIT_CONTRACT}\n\n{_AFK_AMBIGUITY_CONTRACT}\n\n{plan_body}"
    result = _invoke_harness(harness, prompt, afk=afk, model=model)

    # AFK wedge: the agent hit an unresolvable design call and signaled via
    # summary.md{status: blocked} (preferred, hang-proof) or — defensively — a
    # self-answered AskUserQuestion in the captured stream. Eject hitl_required
    # and preserve the worktree for the operator. Checked before the generic
    # nonzero-exit branch so a wedge is never misreported as implement_failed
    # (the root cause of silent AFK kills reading as plain failures).
    blocker = _read_blocked_summary(Path.cwd())
    if blocker is not None or _detect_self_answer(result):
        summary = blocker or "AFK ambiguity — self-answer detected in the session stream."
        _promote_blocked_summary(summary)
        _emit_event(
            "chunk_ejected",
            ejected_payload(
                slug,
                HITL_REQUIRED,
                str(plan_path.parent),
                logs_path=str(_session_dir_fn(os.environ.get("MENTAT_SESSION", "manual"))),
                summary=summary,
            ),
        )
        return EX_HITL_REQUIRED

    if result.returncode != 0:
        _emit_event(
            "chunk_ejected",
            ejected_payload(
                slug,
                IMPLEMENT_FAILED,
                str(plan_path.parent),
                logs_path=str(_session_dir_fn(os.environ.get("MENTAT_SESSION", "manual"))),
            ),
        )
        return 1

    _checkpoint_if_needed(result, slug=slug, threshold=_compaction_threshold())
    _emit_event("agent_stopped", {"reason": "ok"})
    return 0


def _do_land(chunk: Any, *, holding: str, land_queue: Any) -> dict[str, object]:
    """Thin wrapper around land_queue.land — exists so tests can patch it."""
    return land_queue.land(chunk, holding=holding)


def _land_and_review(slug: str, worktree: Path, holding: str) -> dict[str, object]:
    """Land one chunk onto the holding branch.

    Called after run_plan returns 0 when --land is set. Uses land_queue.land
    for the single-chunk case (no Scheduler needed — drain() with one chunk and
    scheduler=None is equivalent). Returns a dict with status and landed tip sha.
    """
    _land_script = paths.SKILLS_DIR / "mentat-orchestrate/scripts/landing.py"
    land_queue = _load_mod("landing", _land_script)
    chunk_id = os.environ.get("MENTAT_CHUNK_ID", "").strip()
    chunk = land_queue.Chunk(slug=slug, worktree=worktree, chunk_id=chunk_id)
    verdict = _do_land(chunk, holding=holding, land_queue=land_queue)
    return {
        "status": verdict.get("status"),
        "tip": verdict.get("tip"),
        "holding": holding,
    }


_SUBCOMMANDS = frozenset({"run", "mark-test-writable"})


def _build_parser() -> argparse.ArgumentParser:
    """One argparse parser with subparsers for every entrypoint command. The `run`
    subcommand is the default — `mentat-implement <plan>` is sugar for
    `mentat-implement run <plan>`."""
    parser = argparse.ArgumentParser(prog="mentat-implement", description="Atomic plan executor")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Execute a plan (default)")
    run.add_argument("plan_refs", nargs="+", metavar="plan-ref")
    run.add_argument("--harness", default=None)
    run.add_argument("--model", default=None)
    run.add_argument(
        "--land",
        action="store_true",
        default=False,
        help="Land after all slices green and spawn advisory reviewers (self-contained mode)",
    )
    run.add_argument(
        "--holding",
        default=None,
        metavar="BRANCH",
        help="Holding branch to land onto (required with --land; defaults to 'main')",
    )

    run.add_argument(
        "--reuse-worktree",
        action="store_true",
        default=False,
        help="Reuse the cwd worktree (skip worktree create) — recovery respawn contract",
    )

    mark = sub.add_parser("mark-test-writable", help="Flip a closed test path writable for the red step")
    mark.add_argument("slug")
    mark.add_argument("path")
    return parser


def main() -> None:
    # Default to the `run` subcommand when the first token is not an explicit
    # subcommand, so `mentat-implement <plan>` and `mentat-implement run <plan>`
    # are equivalent. This is the canonical argparse idiom for an optional
    # default command — argparse itself owns all arg validation past this point
    # (no raw sys.argv parsing of any command's arguments).
    argv = sys.argv[1:]
    if not argv or argv[0] not in _SUBCOMMANDS:
        argv = ["run", *argv]
    args = _build_parser().parse_args(argv)

    if args.command == "mark-test-writable":
        mark_test_writable(slug=args.slug, path=args.path)
        sys.exit(EX_OK)

    if len(args.plan_refs) > 1:
        print(
            "mentat-implement: accepts one plan at a time. Use mentat-orchestrate for multi-plan runs.",
            file=sys.stderr,
        )
        sys.exit(1)

    plan_path = resolve_plan_path(args.plan_refs[0])
    if not plan_path.exists():
        print(f"mentat-implement: plan not found: {plan_path}", file=sys.stderr)
        sys.exit(1)

    slug = plan_path.stem
    # Mint + export MENTAT_SESSION before any emit (preflight can eject) and
    # before the harness spawn — closes the standalone no-session gap and makes
    # session.jsonl capture happen for standalone runs too. Computed while still
    # in the main worktree so MENTAT_REPO resolves to the repo, not the slug dir.
    ensure_session("implement", slug)
    session_id = os.environ.get("MENTAT_SESSION", slug)
    print(f"mentat-implement: track this run with `mentat-session track {session_id}`", file=sys.stderr)
    _prune_worktrees_preflight()
    harness = _utils.default_harness()
    reuse_worktree = bool(getattr(args, "reuse_worktree", False))
    pf_veto_rc, missing_reviewers = preflight_veto_reviewers(harness, reuse_worktree=reuse_worktree)
    if pf_veto_rc != 0:
        for name in missing_reviewers:
            print(
                f"mentat-implement: PREFLIGHT FAILED — veto reviewer {name!r} is not "
                f"registered in the harness agents dir. Run `mentat-install` to "
                f"(re)create harness symlinks.",
                file=sys.stderr,
            )
        sys.exit(pf_veto_rc)
    pf_rc, target = preflight_worktree(slug, reuse_worktree=reuse_worktree)
    if pf_rc != 0:
        _emit_event(
            "chunk_ejected",
            ejected_payload(
                slug,
                PREFLIGHT_WORKTREE_FAILED,
                str(plan_path.parent),
                logs_path=str(_session_dir_fn(os.environ.get("MENTAT_SESSION", "manual"))),
                preflight_exit=pf_rc,
            ),
        )
        print(
            f"mentat-implement: preflight worktree create failed (exit {pf_rc})",
            file=sys.stderr,
        )
        sys.exit(pf_rc)
    if target is not None:
        os.chdir(target)

    # Fail closed if preflight did not isolate us into our own worktree. A run
    # in the shared main tree leaks branch switches across every concurrent
    # session — refuse rather than risk the leak.
    if _in_shared_main_tree(reuse_worktree=reuse_worktree):
        _emit_event(
            "chunk_ejected",
            ejected_payload(
                slug,
                MAIN_TREE_REFUSED,
                str(Path.cwd()),
                logs_path=str(_session_dir_fn(os.environ.get("MENTAT_SESSION", "manual"))),
            ),
        )
        print(
            "mentat-implement: refusing to run in the shared main worktree — a branch "
            "switch there flips HEAD for every concurrent session. Run inside a "
            ".mentat/worktrees/ worktree (preflight normally creates one).",
            file=sys.stderr,
        )
        sys.exit(EX_USAGE)

    rc = _run_and_doctor(plan_path, harness=args.harness, model=args.model)

    # Own-worktree teardown lives in a finally so it is crash-safe: it runs on a
    # normal failure exit AND if the land/review body below raises. Implement owns
    # the worktree it created — on its own failure it drops a clean one, preserves
    # a dirty one (holds un-landed work). Signal exits and a hitl_required wedge
    # are preserved unconditionally — the wedge worktree holds work the operator
    # must resume once the design call is made. Doctor already ran inside
    # _run_and_doctor and writes to ~/.mentat/logs, so teardown loses nothing.
    try:
        if rc == 0 and getattr(args, "land", False):
            holding = getattr(args, "holding", None) or "main"
            worktree = target if target is not None else Path.cwd()
            _land_and_review(slug, worktree, holding)

        if rc == 0:
            print("mentat-implement: review the diff with `git diff main..HEAD`", file=sys.stderr)
    finally:
        if rc != 0 and rc not in _PRESERVE_WORKTREE_EXITS and target is not None:
            os.chdir(_repo_root_from_worktree(target))
            _teardown_worktree(target)
    sys.exit(rc)


if __name__ == "__main__":
    main()
