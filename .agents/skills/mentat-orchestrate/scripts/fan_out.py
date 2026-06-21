"""Spawn a plan in a headless worktree and return session ID."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import paths  # noqa: E402
from lib.events import bind, spawned_payload  # noqa: E402
from lib.loader import load_sibling  # noqa: E402
from lib.session import mint_session  # noqa: E402
from lib.session import session_dir as _session_dir_fn

_IMPLEMENT_SCRIPT = paths.SKILLS_DIR / "mentat-implement/scripts/implement.py"
_CONTAINER_SCRIPT = paths.CONTAINER_SCRIPT

_utils = load_sibling(__file__, "utils")


def _log_dir_for(session_id: str) -> Path:
    """Per-session log dir. Delegates to the lib.session seam (F0)."""
    return _session_dir_fn(session_id)


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
    # The child is an implement run — mint a fresh implement session per child
    # (overriding any inherited orchestrate id in the child env below).
    session_id = mint_session("implement", plan_path.stem)
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


_emit_event = bind("mentat-orchestrate")


def spawn_with_proc(plan, *, harness: str | None = None, model: str | None = None) -> tuple[str, subprocess.Popen]:
    """Spawn plan headless. Print track command immediately. Return (session_id, Popen)."""
    session_id, proc = _spawn_worktree_subprocess(plan.path, harness=harness, model=model)
    _emit_event(
        "chunk.spawned",
        spawned_payload(plan.slug, str(plan.path), harness=harness or "default", worktree=str(Path.cwd())),
    )
    print(f"python3 ~/.agents/skills/mentat-session/scripts/session.py track {session_id}")
    print(session_id)
    return session_id, proc


def spawn(plan, *, harness: str | None = None, model: str | None = None) -> str:
    """Spawn plan headless. Discards Popen handle. Returns session ID."""
    session_id, _proc = spawn_with_proc(plan, harness=harness, model=model)
    return session_id
