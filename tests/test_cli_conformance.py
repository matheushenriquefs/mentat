"""CLI surface conformance — plan-ref term, bare track, drift_lint CLI gate."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / ".agents"

_CLI_SKILLS = (
    AGENTS / "skills/mentat-plan/SKILL.md",
    AGENTS / "skills/mentat-git/SKILL.md",
    AGENTS / "skills/mentat-tasks/SKILL.md",
)


def _drift():
    import sys

    sys.path.insert(0, str(AGENTS))
    from lib.gates import drift_lint

    return drift_lint


def test_cli_skill_invoke_tables_use_plan_ref_not_slug() -> None:
    for path in _CLI_SKILLS:
        text = path.read_text()
        assert "<slug>" not in text, f"{path.name} still uses <slug> in CLI docs"


def test_drift_lint_cli_surface_passes_on_repo() -> None:
    drift = _drift()
    assert drift.lint_cli_argparse(REPO_ROOT) == []
    assert drift.lint_cli_skill_docs(REPO_ROOT) == []


def _seed_cli_scripts(tmp_path: Path, drift_mod) -> None:
    for rel in drift_mod._CLI_SKILL_SCRIPTS:
        src = AGENTS / rel
        dest = tmp_path / ".agents" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text())


def test_drift_lint_blocks_banned_query_subcommand(tmp_path: Path) -> None:
    drift = _drift()
    _seed_cli_scripts(tmp_path, drift)
    script = tmp_path / ".agents/skills/mentat-log/scripts/log.py"
    text = script.read_text()
    script.write_text(
        text.replace(
            'prune_p = sub.add_parser("prune"',
            'sub.add_parser("query", help="deprecated")\n    prune_p = sub.add_parser("prune"',
        )
    )
    errors = drift.lint_cli_argparse(tmp_path)
    assert any("banned subcommand" in e and "query" in e for e in errors)


def test_drift_lint_blocks_deprecated_track_subcommand(tmp_path: Path) -> None:
    drift = _drift()
    _seed_cli_scripts(tmp_path, drift)
    script = tmp_path / ".agents/skills/mentat-track/scripts/track.py"
    text = script.read_text()
    script.write_text(
        text.replace(
            'list_p = sub.add_parser("list", help="Repo-wide agent registry',
            'sub.add_parser("track", help="deprecated")\n    list_p = sub.add_parser("list", help="Repo-wide agent registry',
        )
    )
    errors = drift.lint_cli_argparse(tmp_path)
    assert any("banned subcommand" in e and "track" in e for e in errors)
