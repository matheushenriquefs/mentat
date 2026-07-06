"""Auto-doctor, report-back summary, and token checkpoint for implement runs."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_AGENTS_ROOT = Path(__file__).resolve().parents[4]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.agent import summary_file as _summary_file  # noqa: E402
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

DOCTOR_EXIT_CODES = frozenset(
    {1, EX_HITL_REQUIRED, EX_USAGE, EX_DATAERR, EX_NOINPUT, EX_UNAVAILABLE, EX_SOFTWARE, EX_CONFIG}
)
PRESERVE_WORKTREE_EXITS = frozenset({130, 143, EX_HITL_REQUIRED})

from lib.support import paths  # noqa: E402

_AGENT_SCRIPT = paths.SKILLS_DIR / "mentat-track/scripts/agent.py"


def run_agent_cmd(subcmd: str) -> None:
    if not _AGENT_SCRIPT.exists():
        return
    cmd = ["python3", str(_AGENT_SCRIPT), subcmd]
    agent_id = os.environ.get("MENTAT_AGENT")
    if agent_id:
        cmd.append(agent_id)
    subprocess.run(cmd, capture_output=True, check=False)


def auto_doctor() -> None:
    run_agent_cmd("doctor")


def auto_summary() -> None:
    run_agent_cmd("report")


def compaction_threshold() -> int | None:
    from lib.config import get_config_dir
    from lib.config import load_config_file as _load_cfg

    cfg_path = get_config_dir()
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


def checkpoint_if_needed(result: Any, *, slug: str, threshold: int | None) -> None:
    if threshold is None:
        return
    usage = getattr(result, "usage_tokens", None)
    if usage is None or usage < threshold:
        return
    sid = os.environ.get("MENTAT_AGENT", slug)
    path = _summary_file(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nstatus: succeeded\n---\nToken checkpoint: {usage} tokens used "
        f"(threshold {threshold}). Slug: {slug}. Next spawn can use this as seed_summary.\n"
    )


def run_and_doctor(
    plan_path: Path,
    *,
    harness: str | None,
    model: str | None,
    run_plan: Callable[..., int],
    parse_kind: Callable[[Path], str],
) -> int:
    rc = run_plan(plan_path, harness=harness, model=model)
    if rc in DOCTOR_EXIT_CODES:
        auto_doctor()
        return rc
    if rc == EX_OK and parse_kind(plan_path) == "AFK":
        auto_summary()
    return rc
