"""E2E: the stdlib frontmatter codec — parse + encode + atomic mutate.

Drives ``lib.support.frontmatter`` through the full round trip on real tmp files: the
parse guard clauses (empty / no leading ``---``), the continuation-line skip and
non-matching-line drop, ``encode`` order + trailing newline, an on-disk
``mutate`` that preserves the body, and the ``_write_atomic`` failure path — a
monkeypatched ``os.replace`` raising OSError must trigger the ``except`` cleanup
so the temp ``.tmp`` file is unlinked and the error re-raised.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lib.support import frontmatter

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── parse ────────────────────────────────────────────────────────────────────


def test_parse_empty_string_returns_empty_and_zero():
    assert frontmatter.parse("") == ({}, 0)


def test_parse_missing_leading_fence_returns_empty_and_zero():
    assert frontmatter.parse("not a fence\nkey: value\n") == ({}, 0)


def test_parse_rejects_indented_continuation_line():
    text = "---\nstatus: open\n    continuation line\n---\nbody\n"
    with pytest.raises(frontmatter.FrontmatterError, match="nested/indented"):
        frontmatter.parse(text)


def test_parse_rejects_non_key_line():
    text = "---\nstatus: open\nnot a fm line\n---\nbody here\n"
    with pytest.raises(frontmatter.FrontmatterError, match="unsupported frontmatter"):
        frontmatter.parse(text)


# ── encode ───────────────────────────────────────────────────────────────────


def test_encode_round_trips_order_and_ends_with_newline():
    fm = {"slug": "alpha", "status": "open"}
    out = frontmatter.encode(fm, "the body\n")
    assert out == "---\nslug: alpha\nstatus: open\n---\nthe body\n"
    assert out.endswith("\n")


# ── mutate ───────────────────────────────────────────────────────────────────


def test_mutate_changes_field_and_preserves_body(tmp_path: Path):
    path = tmp_path / "plan.md"
    path.write_text("---\nslug: alpha\nstatus: open\n---\nbody line one\nbody line two\n")
    frontmatter.mutate(path, status="done")
    fm, body_start = frontmatter.parse(path.read_text())
    assert fm["status"] == "done"
    assert fm["slug"] == "alpha"
    body = "\n".join(path.read_text().splitlines()[body_start:])
    assert "body line one" in body
    assert "body line two" in body


# ── _write_atomic failure path ───────────────────────────────────────────────


def test_write_atomic_cleans_up_tmp_and_reraises_on_failure(tmp_path: Path, monkeypatch):
    target = tmp_path / "out.md"

    def _boom(*_args, **_kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(frontmatter.os, "replace", _boom)

    with pytest.raises(OSError):
        frontmatter._write_atomic(target, {"slug": "x"}, "body")

    # The except branch unlinked the temp file — no ``.tmp`` residue left behind.
    assert not list(tmp_path.glob("*.tmp"))
