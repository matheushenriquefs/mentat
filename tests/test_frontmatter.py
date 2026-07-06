"""Tests for lib/frontmatter.py — stdlib YAML-flat frontmatter codec."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_LIB = Path(__file__).resolve().parents[1] / ".agents/lib"

import frontmatter  # noqa: E402


def test_parse_returns_dict_and_body_offset():
    text = "---\nname: x\nclass: AFK\n---\n# body\n"
    fm, offset = frontmatter.parse(text)
    assert fm == {"name": "x", "class": "AFK"}
    assert offset == 4  # body starts at line index 4


def test_parse_no_frontmatter_returns_empty():
    text = "# just a body\nno frontmatter here\n"
    fm, offset = frontmatter.parse(text)
    assert fm == {}
    assert offset == 0


def test_parse_rejects_indented_lines():
    text = "---\nname: top\n  nested: x\n---\n# body\n"
    with pytest.raises(frontmatter.FrontmatterError, match="nested"):
        frontmatter.parse(text)


def test_parse_rejects_non_matching_line_inside_block():
    text = "---\nname: x\nthis line has no colon\n---\n# body\n"
    with pytest.raises(frontmatter.FrontmatterError, match="unsupported"):
        frontmatter.parse(text)


def test_encode_roundtrip():
    fm = {"id": "T001", "status": "todo"}
    body = "# body"
    encoded = frontmatter.encode(fm, body)
    assert encoded == "---\nid: T001\nstatus: todo\n---\n# body"
    recovered, offset = frontmatter.parse(encoded)
    assert recovered == fm


def test_encode_preserves_key_order():
    fm = {"id": "T001", "status": "todo", "claimed_by": "agent-x"}
    encoded = frontmatter.encode(fm, "")
    lines = encoded.splitlines()
    keys = [line.split(":")[0] for line in lines if ":" in line and not line.startswith("-")]
    assert keys == ["id", "status", "claimed_by"]


def test_mutate_atomic(tmp_path: Path):
    p = tmp_path / "task.md"
    p.write_text("---\nid: T001\nstatus: todo\n---\n# body\n", encoding="utf-8")
    frontmatter.mutate(p, status="done")
    text = p.read_text(encoding="utf-8")
    fm, _ = frontmatter.parse(text)
    assert fm["status"] == "done"
    assert not list(tmp_path.glob("*.tmp")), "no .tmp file should linger"


def test_mutate_preserves_body(tmp_path: Path):
    body = "# My Task\n\nSome content here.\n"
    p = tmp_path / "task.md"
    p.write_text(f"---\nid: T001\nstatus: todo\n---\n{body}", encoding="utf-8")
    frontmatter.mutate(p, status="done")
    text = p.read_text(encoding="utf-8")
    _, offset = frontmatter.parse(text)
    recovered_body = "\n".join(text.splitlines()[offset:])
    assert recovered_body == body.rstrip("\n")


def test_mutate_quoted_values(tmp_path: Path):
    p = tmp_path / "task.md"
    p.write_text("---\nid: T001\ncreated_at: 2026-06-12T00:00:00Z\n---\n# body\n", encoding="utf-8")
    frontmatter.mutate(p, status="done")
    fm, _ = frontmatter.parse(p.read_text(encoding="utf-8"))
    assert fm["created_at"] == "2026-06-12T00:00:00Z"
    assert fm["status"] == "done"

def test_write_atomic_cleans_up_tmp_on_failure(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    p = tmp_path / "task.md"
    p.write_text("---\nid: T001\n---\n# body\n", encoding="utf-8")

    with patch.object(frontmatter, "encode", side_effect=RuntimeError("boom")):
        try:
            frontmatter.mutate(p, status="done")
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "boom" in str(exc)

    assert not list(tmp_path.glob("*.tmp")), "temp file must be removed on failure"
    # Original file untouched
    assert "T001" in p.read_text(encoding="utf-8")


def test_frontmatter_stdlib_only():
    src = (_LIB / "frontmatter.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    stdlib = sys.stdlib_module_names  # type: ignore[attr-defined]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in stdlib, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            assert top in stdlib or top == "__future__", f"non-stdlib import: {node.module}"
