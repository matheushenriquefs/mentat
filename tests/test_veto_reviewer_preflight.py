"""VG1 — preflight check that veto reviewers are spawnable (ADR-0003 v5)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_GATES_DIR = Path(__file__).resolve().parents[1] / ".agents/lib/gates"
_IMPL_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts"


def _load_score():
    # Use package import so dataclass can find its module in sys.modules.
    from lib.gates import score  # noqa: PLC0415

    return score


def _load_impl():
    # Register in sys.modules before exec_module so dataclass resolution works.
    path = _IMPL_SCRIPTS / "implement.py"
    key = "implement_vg1"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[key] = mod
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        sys.modules.pop(key, None)
        raise
    return mod


# ── score.VETO_KEYWORDS + score.missing_veto_reviewers ───────────────────────


def test_veto_keywords_constant_present():
    score = _load_score()
    assert hasattr(score, "VETO_KEYWORDS"), "score.py must expose VETO_KEYWORDS"


def test_veto_keywords_excludes_smell():
    score = _load_score()
    assert "smell" not in score.VETO_KEYWORDS, "smell is advisory — must not be in VETO_KEYWORDS"


def test_veto_keywords_includes_required_reviewers():
    score = _load_score()
    for kw in ("plan", "test", "bug", "rules", "context"):
        assert kw in score.VETO_KEYWORDS, f"{kw!r} must be a veto keyword in VETO_KEYWORDS"


def test_missing_veto_reviewer_detected(tmp_path):
    """All veto reviewers absent except four — missing returns the fifth."""
    score = _load_score()
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    for kw in ("plan", "test", "bug", "rules"):
        (agents_dir / f"mentat-{kw}-reviewer.md").write_text("# stub")

    missing = score.missing_veto_reviewers(agents_dir)
    assert "mentat-context-reviewer" in missing


def test_all_veto_reviewers_present_passes(tmp_path):
    score = _load_score()
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    for kw in ("plan", "test", "bug", "rules", "context"):
        (agents_dir / f"mentat-{kw}-reviewer.md").write_text("# stub")

    assert score.missing_veto_reviewers(agents_dir) == []


def test_missing_all_when_dir_absent(tmp_path):
    """Non-existent agents_dir → all veto reviewers reported missing."""
    score = _load_score()
    missing = score.missing_veto_reviewers(tmp_path / "no-such-dir")
    assert len(missing) == len(score.VETO_KEYWORDS)


def test_smell_reviewer_not_reported_missing(tmp_path):
    """smell is advisory — must not appear in missing_veto_reviewers output."""
    score = _load_score()
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    # Only smell reviewer present
    (agents_dir / "mentat-smell-reviewer.md").write_text("# stub")

    missing = score.missing_veto_reviewers(agents_dir)
    assert "mentat-smell-reviewer" not in missing


# ── implement.preflight_veto_reviewers ───────────────────────────────────────


def test_preflight_veto_blocks_on_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    impl = _load_impl()
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "mentat-plan-reviewer.md").write_text("# stub")
    monkeypatch.setattr(impl, "_veto_agents_dir", lambda h: agents_dir)

    rc, missing = impl.preflight_veto_reviewers("claude-code")
    assert rc == 1
    assert len(missing) > 0


def test_preflight_veto_passes_when_all_present(tmp_path, monkeypatch):
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    impl = _load_impl()
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    for kw in ("plan", "test", "bug", "rules", "context"):
        (agents_dir / f"mentat-{kw}-reviewer.md").write_text("# stub")
    monkeypatch.setattr(impl, "_veto_agents_dir", lambda h: agents_dir)

    rc, missing = impl.preflight_veto_reviewers("claude-code")
    assert rc == 0
    assert missing == []


def test_preflight_veto_skipped_when_env_set(monkeypatch):
    monkeypatch.setenv("MENTAT_SKIP_PREFLIGHT", "1")
    impl = _load_impl()

    rc, missing = impl.preflight_veto_reviewers("claude-code")
    assert rc == 0
    assert missing == []
