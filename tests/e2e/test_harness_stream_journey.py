"""E2E: the harness stream-json row helpers — the single owner of the wire shape.

Drives ``lib.harness_stream`` (pure functions over decoded NDJSON rows) through
every branch: type-guards for non-dict / wrong-``type`` rows, the tool_use name
extraction, the AskUserQuestion predicate, assistant text concatenation, and the
tool_result summariser with its three truncation ceilings (200 / 100 / 300).
No I/O, no mocking — the module is pure, so tests pass plain dicts and assert.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lib import harness_stream

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── tool_uses ────────────────────────────────────────────────────────────────


def test_tool_uses_non_dict_row_is_empty():
    assert harness_stream.tool_uses("not a dict") == []


def test_tool_uses_non_assistant_row_is_empty():
    assert harness_stream.tool_uses({"type": "user"}) == []


def test_tool_uses_non_list_content_is_empty():
    assert harness_stream.tool_uses({"type": "assistant", "message": {"content": "nope"}}) == []


def test_tool_uses_returns_string_named_tool_uses_in_order():
    row = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Read"},
                {"type": "text", "text": "thinking"},
                {"type": "tool_use", "name": "Edit"},
                {"type": "tool_use", "name": {"not": "a string"}},
            ]
        },
    }
    assert harness_stream.tool_uses(row) == ["Read", "Edit"]


# ── is_ask_user_question ─────────────────────────────────────────────────────


def test_is_ask_user_question_true_when_name_present():
    row = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "AskUserQuestion"}]}}
    assert harness_stream.is_ask_user_question(row) is True


def test_is_ask_user_question_false_when_absent():
    row = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}}
    assert harness_stream.is_ask_user_question(row) is False


# ── assistant_text ───────────────────────────────────────────────────────────


def test_assistant_text_non_assistant_row_is_empty():
    assert harness_stream.assistant_text({"type": "user"}) == ""


def test_assistant_text_non_list_content_is_empty():
    assert harness_stream.assistant_text({"type": "assistant", "message": {"content": None}}) == ""


def test_assistant_text_concatenates_text_and_ignores_non_string_and_non_text():
    row = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "hello "},
                {"type": "tool_use", "name": "Read"},
                {"type": "text", "text": {"not": "a string"}},
                {"type": "text", "text": "world"},
            ]
        },
    }
    assert harness_stream.assistant_text(row) == "hello world"


# ── tool_result ──────────────────────────────────────────────────────────────


def test_tool_result_non_user_row_is_empty():
    assert harness_stream.tool_result({"type": "assistant"}) == ""


def test_tool_result_non_list_content_is_empty():
    assert harness_stream.tool_result({"type": "user", "message": {"content": "nope"}}) == ""


def test_tool_result_string_inner_truncates_to_200():
    row = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": "x" * 500}]},
    }
    assert harness_stream.tool_result(row) == "x" * 200


def test_tool_result_list_inner_text_truncates_to_100():
    row = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": [{"type": "text", "text": "y" * 500}]}]},
    }
    assert harness_stream.tool_result(row) == "y" * 100


def test_tool_result_overall_truncates_to_300():
    # Two string tool_results of 200 chars each, joined by a space → 401 chars
    # before the outer [:300] ceiling clamps it.
    row = {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "content": "a" * 500},
                {"type": "tool_result", "content": "b" * 500},
            ]
        },
    }
    assert len(harness_stream.tool_result(row)) == 300
