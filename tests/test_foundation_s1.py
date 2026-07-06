"""S1: ADR-0019 code-org + ADR-0020 test-craft + rules layer."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADR_DIR = REPO_ROOT / "docs" / "adr"
RULES_DIR = REPO_ROOT / ".agents" / "rules"


def _rule_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = 1
    while end < len(lines) and lines[end].strip() != "---":
        end += 1
    fm: dict[str, str] = {}
    for line in lines[1:end]:
        if line.startswith("paths:"):
            fm["paths"] = line.split(":", 1)[1].strip()
    return fm


def test_adr_0019_code_organization_present() -> None:
    path = ADR_DIR / "0019-code-organization.md"
    assert path.is_file(), "ADR-0019 missing"
    text = path.read_text()
    for section in ("## Context", "## Decision", "## Consequences"):
        assert section in text
    assert "utils.py" in text
    assert "helpers.py" in text


def test_adr_0020_test_craft_present() -> None:
    path = ADR_DIR / "0020-test-craft.md"
    assert path.is_file(), "ADR-0020 missing"
    text = path.read_text()
    for section in ("## Context", "## Decision", "## Consequences"):
        assert section in text
    assert "filterwarnings" in text
    assert "real_audit_store" in text


def test_adr_readme_index_count_matches_files() -> None:
    adr_files = sorted(p for p in ADR_DIR.glob("*.md") if p.name != "README.md")
    readme = (ADR_DIR / "README.md").read_text()
    rows = [line for line in readme.splitlines() if re.match(r"^\| \[\d{4}\]", line)]
    assert len(rows) == len(adr_files), f"README lists {len(rows)} ADRs, found {len(adr_files)} files"


def test_rules_code_organization_and_testing_load() -> None:
    for name in ("code-organization.md", "testing.md"):
        path = RULES_DIR / name
        assert path.is_file(), f"missing rule file {name}"
        text = path.read_text()
        assert text.startswith("---\n"), f"{name} missing opening frontmatter fence"
        fm = _rule_frontmatter(text)
        assert "paths" in fm, f"{name} missing paths: frontmatter"
        assert "paths:" in text.split("---")[1], f"{name} must declare paths globs"
        body = text.split("---", 2)[-1]
        assert len(body.strip()) > 40, f"{name} body too short"


def test_readme_adr_count_updated() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    assert "0001–0020" in readme or "0001-0020" in readme or "20 architecture" in readme.lower()
