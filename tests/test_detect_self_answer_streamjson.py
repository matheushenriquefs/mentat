"""detect_self_answer parses stream-json schema (the format the AFK adapter
writes to MENTAT_SESSION_LOG)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

IMPL_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, IMPL_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"impl_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_log(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_detect_self_answer_streamjson_positive(tmp_path):
    utils = _load("harness_utils")
    log = tmp_path / "session.jsonl"
    _write_log(
        log,
        [
            {"type": "system", "subtype": "init", "session_id": "x"},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Should I use port 8080?"},
                        {
                            "type": "tool_use",
                            "name": "AskUserQuestion",
                            "input": {"questions": [{"question": "..."}]},
                        },
                    ]
                },
            },
        ],
    )
    assert utils.detect_self_answer(log) is True


def test_detect_self_answer_streamjson_negative(tmp_path):
    utils = _load("harness_utils")
    log = tmp_path / "session.jsonl"
    _write_log(
        log,
        [
            {"type": "system", "subtype": "init"},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Just running."},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                    ]
                },
            },
        ],
    )
    assert utils.detect_self_answer(log) is False


def test_detect_self_answer_missing_log_returns_false(tmp_path):
    utils = _load("harness_utils")
    assert utils.detect_self_answer(tmp_path / "nope.jsonl") is False


def test_detect_self_answer_malformed_rows_ignored(tmp_path):
    utils = _load("harness_utils")
    log = tmp_path / "session.jsonl"
    log.write_text('not json\n{}\n{"type":"junk"}\n')
    assert utils.detect_self_answer(log) is False


def test_detect_self_answer_falsy_path_returns_false():
    utils = _load("harness_utils")
    assert utils.detect_self_answer(None) is False
    assert utils.detect_self_answer("") is False


def test_detect_self_answer_skips_blank_lines(tmp_path):
    utils = _load("harness_utils")
    log = tmp_path / "session.jsonl"
    log.write_text('\n\n{"type":"system"}\n\n')
    assert utils.detect_self_answer(log) is False


# ── lib.harness_stream: assistant_text + tool_result wire-shape edges ─────────

import harness_stream as _hs  # noqa: E402


def test_assistant_text_concatenates_and_ignores_nonstring_text():
    row = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "hello "},
                {"type": "text", "text": 123},  # non-str text → skipped
                {"type": "text", "text": "world"},
            ]
        },
    }
    assert _hs.assistant_text(row) == "hello world"


def test_assistant_text_non_list_content_returns_empty():
    assert _hs.assistant_text({"type": "assistant", "message": {"content": "nope"}}) == ""


def test_tool_result_non_list_content_returns_empty():
    assert _hs.tool_result({"type": "user", "message": {"content": "nope"}}) == ""


def test_tool_result_handles_string_and_nested_list_inner():
    row = {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "content": "short string result"},
                {"type": "tool_result", "content": 42},  # neither str nor list → skipped
                {
                    "type": "tool_result",
                    "content": [
                        {"type": "text", "text": "nested text"},
                        {"type": "text", "text": 999},  # non-str text → skipped
                        {"type": "image"},  # non-text inner block → skipped
                    ],
                },
            ]
        },
    }
    out = _hs.tool_result(row)
    assert "short string result" in out
    assert "nested text" in out
