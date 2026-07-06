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

_SCRIPTS_DIR = Path(__file__).resolve().parent
_AGENTS_ROOT = _SCRIPTS_DIR.parents[2]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.agent import agent_dir as _agent_dir_fn  # noqa: E402
from lib.agent import ensure_agent  # noqa: E402
from lib.chunk import get_chunk_id_from_env  # noqa: E402
from lib.events import (  # noqa: E402
    HITL_IN_AGENT,
    HITL_REQUIRED,
    IMPLEMENT_FAILED,
    MAIN_TREE_REFUSED,
    PREFLIGHT_WORKTREE_FAILED,
    SUMMARY_FILE,
    ejected_payload,
    spawned_payload,
)
from lib.events import bind as _bind  # noqa: E402
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
from lib.support import frontmatter as _frontmatter  # noqa: E402
from lib.support import paths  # noqa: E402

_utils = load_sibling(__file__, "harness_utils")
_emit_event = _bind("mentat-implement")

_GIT_SCRIPT = paths.SKILLS_DIR / "mentat-git/scripts/git.py"
_GIT_WORKTREE_PY = paths.SKILLS_DIR / "mentat-git/scripts/worktree.py"
_AGENT_SCRIPT = paths.SKILLS_DIR / "mentat-track/scripts/agent.py"

_HARNESS_DIR = _SCRIPTS_DIR / "harness"
_HARNESS: dict[str, Path] = {
    "claude-code": _HARNESS_DIR / "claude_code.py",
    "cursor": _HARNESS_DIR / "cursor.py",
}

_SUBCOMMANDS = frozenset({"run", "mark-test-writable"})

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
    "options you see — to `summary.md` in the agent log directory with YAML "
    "frontmatter `---` then `status: blocked` then `---`, and stop immediately. "
    "The agent log directory is the parent of `$MENTAT_AGENT_LOG` "
    "(i.e. `$(dirname $MENTAT_AGENT_LOG)/summary.md`). "
    "That file hands the slice back to the operator cleanly; guessing produces "
    "wrong work that looks finished."
)


def _load_sub(name: str) -> Any:
    path = _SCRIPTS_DIR / "implement" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"mentat_implement_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load implement.{name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_preflight = _load_sub("preflight")
_ro_mounts = _load_sub("ro_mounts")
_wedge = _load_sub("wedge")
_diagnostics = _load_sub("diagnostics")

_PRESERVE_WORKTREE_EXITS = _diagnostics.PRESERVE_WORKTREE_EXITS
_DOCTOR_EXIT_CODES = frozenset(
    {1, EX_HITL_REQUIRED, EX_USAGE, EX_DATAERR, EX_NOINPUT, EX_UNAVAILABLE, EX_SOFTWARE, EX_CONFIG}
)


def _logs_path() -> str:
    return str(_agent_dir_fn(os.environ.get("MENTAT_AGENT", "manual")))


def read_tests_manifest(slug: str) -> tuple[list[str], list[str]]:
    return _ro_mounts.read_tests_manifest(slug, plans_dir_fn=_plans_dir)


def compute_ro_mounts(closed: list[str], open_: list[str]) -> list[str]:
    return _ro_mounts.compute_ro_mounts(closed, open_)


def _plans_dir() -> Path:
    return _ro_mounts.plans_dir()


def mark_test_writable(slug: str, path: str) -> None:
    _ro_mounts.mark_test_writable(slug, path, emit_event=_emit_event, plans_dir_fn=_plans_dir)


def apply_ro_mounts(slug: str) -> None:
    closed, open_ = read_tests_manifest(slug)
    ro = compute_ro_mounts(closed, open_)
    if ro:
        os.environ["MENTAT_RO_MOUNTS"] = json.dumps(ro)


def resolve_plan_path(ref: str) -> Path:
    from lib import plans as _plans

    return _plans.resolve_plan_ref(ref)


def parse_frontmatter(plan_path: Path) -> dict[str, str]:
    return _frontmatter.parse(plan_path.read_text())[0]


def _is_main_worktree(cwd: Path) -> bool:
    return _preflight.is_main_worktree(cwd, git_worktree_py=_GIT_WORKTREE_PY)


def _in_shared_main_tree(*, reuse_worktree: bool = False) -> bool:
    return _preflight.in_shared_main_tree(reuse_worktree=reuse_worktree, git_worktree_py=_GIT_WORKTREE_PY)


def _prune_worktrees_preflight() -> None:
    _preflight.prune_worktrees_preflight()


def preflight_worktree(slug: str, *, reuse_worktree: bool = False) -> tuple[int, Path | None]:
    return _preflight.preflight_worktree(
        slug,
        reuse_worktree=reuse_worktree,
        git_script=_GIT_SCRIPT,
        git_worktree_py=_GIT_WORKTREE_PY,
        subprocess_mod=subprocess,
        in_shared_main_tree_fn=_in_shared_main_tree,
    )


def preflight_veto_reviewers(harness: str, *, reuse_worktree: bool = False) -> tuple[int, list[str]]:
    return _preflight.preflight_veto_reviewers(
        harness,
        reuse_worktree=reuse_worktree,
        veto_agents_dir_fn=_veto_agents_dir,
    )


def _repo_root_from_worktree(worktree: Path) -> Path:
    return _preflight.repo_root_from_worktree(worktree)


def _teardown_worktree(target: Path) -> None:
    _preflight.teardown_worktree(target)


def _read_blocked_summary(worktree: Path) -> str | None:
    seam = _blocked_summary_path()
    if seam is not None:
        result = _read_summary_at(seam)
        if result is not None:
            return result
    return _read_summary_at(worktree / SUMMARY_FILE)


def _promote_blocked_summary(body: str) -> None:
    seam = _blocked_summary_path()
    target = seam if seam is not None else _agent_dir_fn(os.environ.get("MENTAT_AGENT", "manual")) / SUMMARY_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\nstatus: blocked\n---\n{body}\n")


def _detect_self_answer(result: Any) -> bool:
    return _wedge.detect_self_answer(result, detect_fn=_utils.detect_self_answer)


def _auto_doctor() -> None:
    _run_agent_cmd("doctor")


def _auto_summary() -> None:
    _run_agent_cmd("report")


def _compaction_threshold() -> int | None:
    return _diagnostics.compaction_threshold()


def _checkpoint_if_needed(result: Any, *, slug: str, threshold: int | None) -> None:
    _diagnostics.checkpoint_if_needed(result, slug=slug, threshold=threshold)


def _run_agent_cmd(subcmd: str) -> None:
    if not _AGENT_SCRIPT.exists():
        return
    cmd = ["python3", str(_AGENT_SCRIPT), subcmd]
    agent_id = os.environ.get("MENTAT_AGENT")
    if agent_id:
        cmd.append(agent_id)
    subprocess.run(cmd, capture_output=True, check=False)


def _blocked_summary_path() -> Path | None:
    return _wedge.blocked_summary_path()


def _read_summary_at(path: Path) -> str | None:
    return _wedge.read_summary_at(path)


def _veto_agents_dir(harness: str) -> Path:
    return _preflight.veto_agents_dir(harness)


def _run_and_doctor(plan_path: Path, *, harness: str | None = None, model: str | None = None) -> int:
    rc = run_plan(plan_path, harness=harness, model=model)
    if rc in _diagnostics.DOCTOR_EXIT_CODES:
        _auto_doctor()
        return rc
    if rc == EX_OK and parse_frontmatter(plan_path).get("kind", "HITL") == "AFK":
        _auto_summary()
    return rc


def _load_mod(key: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {key!r} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


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


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4 :].lstrip("\n")


def run_plan(plan_path: Path, *, harness: str | None = None, model: str | None = None) -> int:
    if not harness:
        harness = _utils.default_harness()

    fm = parse_frontmatter(plan_path)
    plan_kind = fm.get("kind", "HITL")
    afk = plan_kind == "AFK"
    slug = plan_path.stem

    if not afk:
        _emit_event(
            "chunk_started",
            spawned_payload(slug, str(plan_path), harness=HITL_IN_AGENT, worktree=str(Path.cwd())),
        )
        _emit_event("agent_started", {"harness": HITL_IN_AGENT})
        print(
            f"mentat-implement: {slug} is kind:HITL — drive in calling Claude agent.\nPlan: {plan_path}",
            file=sys.stderr,
        )
        return 0

    apply_ro_mounts(slug)

    plan_body = _strip_frontmatter(plan_path.read_text())
    home_agents = str(Path.home()) + "/.agents/"
    cwd_agents = str(Path.cwd()) + "/.agents/"
    if home_agents != cwd_agents and Path(cwd_agents).is_dir():
        plan_body = plan_body.replace(home_agents, cwd_agents)
    prompt = f"{_AFK_COMMIT_CONTRACT}\n\n{_AFK_AMBIGUITY_CONTRACT}\n\n{plan_body}"
    result = _invoke_harness(harness, prompt, afk=afk, model=model)

    blocker = _read_blocked_summary(Path.cwd())
    if blocker is not None or _detect_self_answer(result):
        summary = blocker or "AFK ambiguity — self-answer detected in the agent stream."
        _promote_blocked_summary(summary)
        _emit_event(
            "chunk_ejected",
            ejected_payload(
                slug,
                HITL_REQUIRED,
                str(plan_path.parent),
                logs_path=str(_agent_dir_fn(os.environ.get("MENTAT_AGENT", "manual"))),
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
                logs_path=str(_agent_dir_fn(os.environ.get("MENTAT_AGENT", "manual"))),
            ),
        )
        return 1

    _checkpoint_if_needed(result, slug=slug, threshold=_compaction_threshold())
    _emit_event("agent_stopped", {"reason": "ok"})
    return 0


def _do_land(chunk: Any, *, holding: str, land_queue: Any) -> dict[str, object]:
    return land_queue.land(chunk, holding=holding)


def _land_and_review(slug: str, worktree: Path, holding: str) -> dict[str, object]:
    _land_script = paths.SKILLS_DIR / "mentat-orchestrate/scripts/landing.py"
    land_queue = _load_mod("landing", _land_script)
    chunk_id = get_chunk_id_from_env()
    chunk = land_queue.Chunk(slug=slug, worktree=worktree, chunk_id=chunk_id)
    verdict = _do_land(chunk, holding=holding, land_queue=land_queue)
    return {
        "status": verdict.get("status"),
        "tip": verdict.get("tip"),
        "holding": holding,
    }


def _build_parser() -> argparse.ArgumentParser:
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
    ensure_agent("implement", slug)
    agent_id = os.environ.get("MENTAT_AGENT", slug)
    print(f"mentat-implement: track this run with `mentat-track track {agent_id}`", file=sys.stderr)
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
                logs_path=str(_agent_dir_fn(os.environ.get("MENTAT_AGENT", "manual"))),
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

    if _in_shared_main_tree(reuse_worktree=reuse_worktree):
        _emit_event(
            "chunk_ejected",
            ejected_payload(
                slug,
                MAIN_TREE_REFUSED,
                str(Path.cwd()),
                logs_path=str(_agent_dir_fn(os.environ.get("MENTAT_AGENT", "manual"))),
            ),
        )
        print(
            "mentat-implement: refusing to run in the shared main worktree — a branch "
            "switch there flips HEAD for every concurrent agent. Run inside a "
            ".mentat/worktrees/ worktree (preflight normally creates one).",
            file=sys.stderr,
        )
        sys.exit(EX_USAGE)

    rc = _run_and_doctor(plan_path, harness=args.harness, model=args.model)

    try:
        if rc == 0 and getattr(args, "land", False):
            holding = getattr(args, "holding", None) or "main"
            worktree = target if target is not None else Path.cwd()
            _land_and_review(slug, worktree, holding)

        if rc == 0:
            print("mentat-implement: review the diff with `git diff main..HEAD`", file=sys.stderr)
    finally:
        if rc != 0 and rc not in _diagnostics.PRESERVE_WORKTREE_EXITS and target is not None:
            os.chdir(_repo_root_from_worktree(target))
            _teardown_worktree(target)
    sys.exit(rc)


if __name__ == "__main__":
    main()
