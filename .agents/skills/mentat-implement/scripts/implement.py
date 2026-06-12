#!/usr/bin/env python3
"""mentat-implement — atomic single-plan executor."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
_SKILLS_DIR = _SCRIPTS.parents[1]
_AGENTS_DIR = _SCRIPTS.parents[2]
_LOG_SCRIPT = _SKILLS_DIR / "mentat-log/scripts/log.py"
_SESSION_SCRIPT = _SKILLS_DIR / "mentat-session/scripts/session.py"
_GIT_SCRIPT = _SKILLS_DIR / "mentat-git/scripts/git.py"
_GIT_WORKTREE_PY = _SKILLS_DIR / "mentat-git/scripts/worktree.py"
_GATES_CODE = _AGENTS_DIR / "lib/gates/code"


def _load_worktree_module():
    spec = importlib.util.spec_from_file_location("mentat_git_worktree", _GIT_WORKTREE_PY)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # syntax/import error in worktree.py shouldn't crash preflight
        print(f"mentat-implement: worktree.py load failed: {e}", file=sys.stderr)
        return None
    return mod


# Exit codes that trigger auto-doctor: TDD/gate fail, HITL ambiguity, CLI/plan errors,
# container down, unhandled exceptions, missing config. Signal exits (130/143) skipped.
_DOCTOR_EXIT_CODES = frozenset({1, 42, 64, 65, 66, 69, 70, 78})


def _load_sibling(name: str):
    here = Path(__file__).parent
    key = f"{here.parent.name}.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, here / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_utils = _load_sibling("utils")


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
    if "/" in ref or ref.endswith(".md"):
        return Path(ref).expanduser().resolve()
    return Path.home() / ".agents" / "plans" / f"{ref}.md"


def parse_frontmatter(plan_path: Path) -> dict[str, str]:
    text = plan_path.read_text()
    fm: dict[str, str] = {}
    in_fm = False
    for line in text.splitlines():
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            else:
                break
        if in_fm:
            m = re.match(r"^(\w+):\s*(.+)$", line)
            if m:
                fm[m.group(1)] = m.group(2).strip()
    return fm


def _emit_event(event: str, payload: dict) -> None:
    """Fire-and-forget emit. Surfaces non-zero exit to stderr so failures aren't silent."""
    r = subprocess.run(
        ["python3", str(_LOG_SCRIPT), "emit", "mentat-implement", event, json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        err = (r.stderr or "").strip().splitlines()[-1:] or ["(no stderr)"]
        print(f"mentat-implement: emit {event!r} failed rc={r.returncode}: {err[0]}", file=sys.stderr)


def _logs_path() -> str:
    """Dir holding session JSONL + diagnosis.md for the current session."""
    base = Path(os.environ.get("MENTAT_LOG_PATH", str(Path.home() / ".mentat" / "logs")))
    repo = os.environ.get("MENTAT_REPO", Path.cwd().name)
    session = os.environ.get("MENTAT_SESSION", "manual")
    return str(base / repo / session)


def _auto_doctor() -> None:
    """Spawn mentat-session doctor. Honor $EDITOR for the diagnosis if set."""
    session_id = os.environ.get("MENTAT_SESSION")
    if not _SESSION_SCRIPT.exists() or not session_id:
        return
    subprocess.run(
        ["python3", str(_SESSION_SCRIPT), "doctor", session_id],
        capture_output=True,
        check=False,
    )
    editor = os.environ.get("EDITOR")
    if editor:
        diag = Path(_logs_path()) / "diagnosis.md"
        if diag.exists():
            subprocess.run([editor, str(diag)], check=False)


def _is_main_worktree(cwd: Path) -> bool:
    """True iff cwd is inside the main worktree.

    Delegates to mentat-git/worktree.is_main_worktree to keep one source of truth.
    """
    mod = _load_worktree_module()
    if mod is None:
        return False
    return bool(mod.is_main_worktree(cwd))


def preflight_worktree(slug: str) -> tuple[int, Path | None]:
    """Auto-create a worktree for slug if cwd is the main worktree.

    Returns (rc, target). rc=0 → success (target valid or skipped intentionally).
    rc=65 → path conflict. rc=66 → base branch missing. Other → bubble up.

    Skipped (rc=0, target=None) when:
      - MENTAT_SKIP_PREFLIGHT env var is set
      - cwd is not in a git repo (test envs)
      - cwd is already a non-main worktree (we're already inside a slug)
    """
    if os.environ.get("MENTAT_SKIP_PREFLIGHT"):
        return (0, None)
    if not _GIT_SCRIPT.exists():
        return (0, None)
    cwd = Path.cwd()
    in_repo = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if in_repo.returncode != 0:
        return (0, None)
    if not _is_main_worktree(cwd):
        return (0, None)

    result = subprocess.run(
        ["python3", str(_GIT_SCRIPT), "worktree", "create", slug],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return (result.returncode, None)
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    return (0, Path(line) if line else None)


def _run_and_doctor(plan_path: Path, *, harness: str | None = None, model: str | None = None) -> int:
    """Run plan and auto-doctor on diagnosable exit codes (skip 0 and signal exits)."""
    rc = run_plan(plan_path, harness=harness, model=model)
    if rc in _DOCTOR_EXIT_CODES:
        _auto_doctor()
    return rc


def _invoke_harness(harness: str, prompt: str, *, afk: bool, model: str | None = None) -> Any:
    harness_dir = _SCRIPTS / "harness"
    adapter_name = harness.replace("-", "_")
    adapter_path = harness_dir / f"{adapter_name}.py"
    if not adapter_path.exists():
        adapter_path = harness_dir / "claude_code.py"
    spec = importlib.util.spec_from_file_location(adapter_name, adapter_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.invoke(prompt, afk=afk, model=model)


def _detect_self_answer(result: Any) -> bool:
    session_log = getattr(result, "session_log", None)
    if session_log is None:
        return False
    return _utils.detect_self_answer(Path(session_log))


def _run_gates(chunk_path: Path | None) -> tuple[str, str]:
    """Run deterministic code gates. Returns (verdict, message)."""
    if not _GATES_CODE.exists():
        return ("pass", "")
    for gate_file in sorted(_GATES_CODE.glob("*.py")):
        if gate_file.stem == "__init__":
            continue
        spec = importlib.util.spec_from_file_location(gate_file.stem, gate_file)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        if hasattr(mod, "run"):
            verdict, message = mod.run(chunk_path)
            if verdict == "block":
                return ("block", message)
    return ("pass", "")


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


def run_plan(plan_path: Path, *, harness: str | None = None, model: str | None = None) -> int:
    if not harness:
        harness = _utils.default_harness()

    fm = parse_frontmatter(plan_path)
    plan_class = fm.get("class", "HITL")
    afk = plan_class == "AFK"

    slug = plan_path.stem

    # HITL plans run in the calling Claude session — never spawn a sub-claude
    # via the harness adapter (it would shell `claude --headless` and lose
    # AskUserQuestion). Emit chunk.spawned{harness:"hitl-in-session"} and
    # return control to the caller; the calling session reads the audit log
    # and drives the TDD loop itself.
    if not afk:
        _emit_event(
            "chunk.spawned",
            {
                "slug": slug,
                "plan": str(plan_path),
                "harness": "hitl-in-session",
                "worktree": str(Path.cwd()),
            },
        )
        print(
            f"mentat-implement: {slug} is class:HITL — drive in calling Claude session.\nPlan: {plan_path}",
            file=sys.stderr,
        )
        return 0

    # Inject read-only test mounts before container-up (ADR-0010)
    closed, open_ = read_tests_manifest(slug)
    ro = compute_ro_mounts(closed, open_)
    if ro:
        os.environ["MENTAT_RO_MOUNTS"] = json.dumps(ro)

    plan_body = _strip_frontmatter(plan_path.read_text())
    if afk:
        home_agents = str(Path.home()) + "/.agents/"
        cwd_agents = str(Path.cwd()) + "/.agents/"
        if home_agents != cwd_agents:
            plan_body = plan_body.replace(home_agents, cwd_agents)
    prompt = f"{_AFK_COMMIT_CONTRACT}\n\n{plan_body}"
    result = _invoke_harness(harness, prompt, afk=afk, model=model)

    if result.returncode != 0:
        _emit_event(
            "chunk.ejected",
            {
                "slug": slug,
                "reason": "implement-failed",
                "where": str(plan_path.parent),
                "logs_path": _logs_path(),
            },
        )
        return 1

    if afk and _detect_self_answer(result):
        _emit_event(
            "chunk.ejected",
            {
                "slug": slug,
                "reason": "hitl-required",
                "where": str(plan_path.parent),
                "logs_path": _logs_path(),
            },
        )
        return 42

    verdict, message = _run_gates(None)
    if verdict == "block":
        _emit_event(
            "chunk.ejected",
            {
                "slug": slug,
                "reason": "gate-failed",
                "where": str(plan_path.parent),
                "logs_path": _logs_path(),
            },
        )
        return 1

    return 0


def main() -> None:
    # Support both: `mentat-implement <plan>` and `mentat-implement run <plan>`
    argv = sys.argv[1:]
    if argv and argv[0] == "mark-test-writable":
        if len(argv) < 3:
            print("usage: mentat-implement mark-test-writable <slug> <path>", file=sys.stderr)
            sys.exit(64)
        mark_test_writable(slug=argv[1], path=argv[2])
        sys.exit(0)

    parser = argparse.ArgumentParser(prog="mentat-implement", description="Atomic plan executor")
    parser.add_argument("plan_refs", nargs="+", metavar="plan-ref")
    parser.add_argument("--harness", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)

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
    pf_rc, target = preflight_worktree(slug)
    if pf_rc != 0:
        _emit_event(
            "chunk.ejected",
            {
                "slug": slug,
                "reason": "preflight-worktree-failed",
                "where": str(plan_path.parent),
                "logs_path": _logs_path(),
                "preflight_exit": pf_rc,
            },
        )
        print(
            f"mentat-implement: preflight worktree create failed (exit {pf_rc})",
            file=sys.stderr,
        )
        sys.exit(pf_rc)
    if target is not None:
        os.chdir(target)

    sys.exit(_run_and_doctor(plan_path, harness=args.harness, model=args.model))


if __name__ == "__main__":
    main()
