"""F3: drop diff slot, keep harness, add UX suggestions.

Red tracers:
- DiffProvider no longer exported from lib.plugins
- MentatPlugin has no diff field
- resolve_slots takes only builtin_harness (no builtin_diff)
- builtin/git_diff.py does not exist
- implement.py source contains session-track and diff-review suggestions
- orchestrate.py source contains session-track suggestion at start
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROOT = REPO_ROOT / ".agents"
sys.path.insert(0, str(AGENTS_ROOT))

# ── diff slot removed ─────────────────────────────────────────────────────────


def test_diff_provider_not_exported() -> None:
    """F3 tracer: DiffProvider must not be exported from lib.plugins."""
    import lib.plugins as plg

    assert not hasattr(plg, "DiffProvider"), "DiffProvider still exported — remove it"


def test_mentat_plugin_has_no_diff_field() -> None:
    """F3 tracer: MentatPlugin must have no diff field after slot removal."""
    from lib.plugins import MentatPlugin

    p = MentatPlugin(name="x")
    assert not hasattr(p, "diff"), "MentatPlugin still has diff field — remove it"


def test_resolve_slots_has_no_builtin_diff_param() -> None:
    """F3 tracer: resolve_slots must accept only builtin_harness, not builtin_diff."""
    from lib.plugins.registry import resolve_slots

    sig = inspect.signature(resolve_slots)
    assert "builtin_diff" not in sig.parameters, "resolve_slots still has builtin_diff param — remove it"


def test_git_diff_builtin_absent() -> None:
    """F3 tracer: builtin/git_diff.py must be deleted."""
    git_diff = AGENTS_ROOT / "lib" / "plugins" / "builtin" / "git_diff.py"
    assert not git_diff.exists(), f"builtin/git_diff.py still present at {git_diff}"


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
