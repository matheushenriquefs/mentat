"""Spawn a plan in a headless worktree and return session ID."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parents[3]
_LOG_SCRIPT = _SKILL_ROOT / "skills/mentat-log/scripts/log.py"
_IMPLEMENT_SCRIPT = _SKILL_ROOT / "skills/mentat-implement/scripts/implement.py"
_CONTAINER_SCRIPT = _SKILL_ROOT / "skills/mentat-container/scripts/container.py"

import importlib.util as _ilu


def _load_sibling(name: str):
    here = Path(__file__).parent
    key = f"{here.parent.name}.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = _ilu.spec_from_file_location(key, here / f"{name}.py")
    mod = _ilu.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_utils = _load_sibling("utils")


def _log_dir_for(session_id: str) -> Path:
    """Per-session log dir. Honors MENTAT_LOG_PATH (default ~/.mentat/logs) and
    MENTAT_REPO (default cwd basename)."""
    base = Path(os.environ.get("MENTAT_LOG_PATH", str(Path.home() / ".mentat" / "logs")))
    repo = os.environ.get("MENTAT_REPO", Path.cwd().name)
    return base / repo / session_id


def _spawn_worktree_subprocess(
    plan_path: Path, *, harness: str | None = None, model: str | None = None
) -> tuple[str, subprocess.Popen]:
    """Spawn a headless mentat-implement in a new worktree.

    Generates a deterministic session id, creates ~/.mentat/logs/<repo>/<sid>/
    with mode 0o700, and exports MENTAT_SESSION + MENTAT_SESSION_LOG to the
    child so the harness adapter can redirect stream-json into the log file.

    Returns (session_id, Popen). The caller may use the Popen to throttle
    concurrent spawns via Popen.poll().
    """
    session_id = f"auto-{plan_path.stem}-{os.getpid()}"
    log_dir = _log_dir_for(session_id)
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(log_dir, 0o700)
    session_log = log_dir / "session.jsonl"

    cmd = ["python3", str(_IMPLEMENT_SCRIPT), str(plan_path)]
    if harness:
        cmd += ["--harness", harness]
    if model:
        cmd += ["--model", model]
    env = {
        **os.environ,
        "MENTAT_SESSION": session_id,
        "MENTAT_SESSION_LOG": str(session_log),
    }
    proc = subprocess.Popen(cmd, env=env)
    return session_id, proc


def _emit_event(event: str, payload: dict) -> None:
    _utils.emit_event(event, payload)


def spawn_with_proc(plan, *, harness: str | None = None, model: str | None = None) -> tuple[str, subprocess.Popen]:
    """Spawn plan headless. Print track command immediately. Return (session_id, Popen)."""
    session_id, proc = _spawn_worktree_subprocess(plan.path, harness=harness, model=model)
    _emit_event(
        "chunk.spawned",
        {
            "slug": plan.slug,
            "plan": str(plan.path),
            "harness": harness or "default",
            "worktree": str(Path.cwd()),
        },
    )
    print(f"python3 ~/.agents/skills/mentat-session/scripts/session.py track {session_id}")
    print(session_id)
    return session_id, proc


def spawn(plan, *, harness: str | None = None, model: str | None = None) -> str:
    """Spawn plan headless. Discards Popen handle. Returns session ID."""
    session_id, _proc = spawn_with_proc(plan, harness=harness, model=model)
    return session_id
