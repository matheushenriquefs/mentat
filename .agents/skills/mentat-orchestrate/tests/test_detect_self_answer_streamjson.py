"""slice-3: detect_self_answer parses stream-json schema (the format
slice-2's adapter writes to MENTAT_SESSION_LOG)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

IMPL_SCRIPTS = Path.home() / ".agents" / "skills" / "mentat-implement" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, IMPL_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"impl_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_log(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_detect_self_answer_streamjson_positive(tmp_path):
    utils = _load("utils")
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
    utils = _load("utils")
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
    utils = _load("utils")
    assert utils.detect_self_answer(tmp_path / "nope.jsonl") is False


def test_detect_self_answer_malformed_rows_ignored(tmp_path):
    utils = _load("utils")
    log = tmp_path / "session.jsonl"
    log.write_text('not json\n{}\n{"type":"junk"}\n')
    assert utils.detect_self_answer(log) is False
