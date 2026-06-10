"""Spawn a plan in a headless worktree and return session ID."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parents[3]
_LOG_SCRIPT = _SKILL_ROOT / ".agents/skills/mentat-log/scripts/log.py"
_IMPLEMENT_SCRIPT = _SKILL_ROOT / ".agents/skills/mentat-implement/scripts/implement.py"
_CONTAINER_SCRIPT = _SKILL_ROOT / ".agents/skills/mentat-container/scripts/container.py"

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


def _spawn_worktree_subprocess(plan_path: Path, *, harness: str | None = None, model: str | None = None) -> str:
    """Spawn a headless mentat-implement in a new worktree. Returns session ID."""
    session_id = f"auto-{plan_path.stem}-{os.getpid()}"
    cmd = ["python3", str(_IMPLEMENT_SCRIPT), str(plan_path)]
    if harness:
        cmd += ["--harness", harness]
    if model:
        cmd += ["--model", model]
    subprocess.Popen(cmd, env={**os.environ, "MENTAT_SESSION": session_id})
    return session_id


def _emit_event(event: str, payload: dict) -> None:
    _utils.emit_event(event, payload)


def spawn(plan, *, harness: str | None = None, model: str | None = None) -> str:
    """Spawn plan headless. Print track command immediately. Return session ID."""
    session_id = _spawn_worktree_subprocess(plan.path, harness=harness, model=model)
    _emit_event(
        "chunk.spawned",
        {
            "slug": plan.slug,
            "plan": str(plan.path),
            "harness": harness or "default",
            "worktree": str(plan.path.parent),
        },
    )
    print(f"python3 ~/.agents/skills/mentat-session/scripts/session.py track {session_id}")
    print(session_id)
    return session_id
