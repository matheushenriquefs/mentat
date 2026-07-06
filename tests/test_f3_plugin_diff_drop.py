"""F3: UX suggestions — session-track hint at start, diff-review hint at end.

Red tracers:
- implement.py source contains session-track and diff-review suggestions
- orchestrate.py source contains session-track suggestion at start
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROOT = REPO_ROOT / ".agents"

# ── UX suggestions ────────────────────────────────────────────────────────────

IMPL_SCRIPT = AGENTS_ROOT / "skills" / "mentat-implement" / "scripts" / "implement.py"
ORCH_SCRIPT = AGENTS_ROOT / "skills" / "mentat-orchestrate" / "scripts" / "orchestrate.py"


def test_implement_suggests_session_track_at_start() -> None:
    """F3 tracer: implement.py must print a 'mentat-session track' hint at run start."""
    src = IMPL_SCRIPT.read_text()
    assert "mentat-session track" in src, (
        "implement.py missing 'mentat-session track' suggestion — add it near run start"
    )


def test_implement_suggests_diff_review_at_end() -> None:
    """F3 tracer: implement.py must print a diff-review hint (git diff or diff_tool) at run end."""
    src = IMPL_SCRIPT.read_text()
    assert "diff_tool" in src or "git diff" in src.lower(), "implement.py missing diff-review suggestion at run end"


def test_orchestrate_suggests_session_track_at_start() -> None:
    """F3 tracer: orchestrate.py must print a 'mentat-session track' hint at run start."""
    src = ORCH_SCRIPT.read_text()
    assert "mentat-session track" in src, (
        "orchestrate.py missing 'mentat-session track' suggestion — add it near run start"
    )
