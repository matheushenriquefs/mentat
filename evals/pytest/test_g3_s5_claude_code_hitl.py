"""G3-S5: claude-code.sh detects HITL wedge → exits 42.

Spec (~/.agents/plans/mentat-architecture-revamp-g3-harness-afk.md S5):
  - Post-invocation: parse session JSONL for self-answered-question pattern
    (no tool calls + assistant text ending with question-mark followed by stop).
  - On match: exit with code 42 (ADR-0010 HITL exit code).
  - Verify: wedge session → HITL exit; audit row carries `hitl-ambiguity`.

Detector contract:
  - Function: `harness_claude_code_detect_hitl <path-to-stream-json>`.
  - Gated by MENTAT_INTERACTIVE=0 (only enforces under AFK).
  - Return 42 iff: AFK mode AND last assistant turn has no tool_use blocks
    AND its concatenated text (whitespace-stripped tail) ends with `?`.
  - Return 0 otherwise (interactive, empty/missing file, real work, non-?).

Blocked-by: S3 (ADR-0010), S4 (cmd-side AFK gate).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / ".agents" / "bin" / "lib" / "harness" / "claude-code.sh"

HITL_EXIT = 42


def _detect(jsonl_path: Path, env_overrides: dict | None = None) -> int:
    """Source claude-code.sh, call detect_hitl, return exit code."""
    env = os.environ.copy()
    overrides = env_overrides or {}
    for k, v in overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    script = f'source "{HARNESS}"; harness_claude_code_detect_hitl "$1"'
    result = subprocess.run(
        ["bash", "-c", script, "_", str(jsonl_path)],
        env=env,
        capture_output=True,
    )
    return result.returncode


def _write_jsonl(path: Path, events: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


def _assistant_text(text: str, stop_reason: str = "end_turn") -> dict:
    return {
        "type": "assistant",
        "message": {
            "id": "msg_x",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "stop_reason": stop_reason,
        },
    }


def _assistant_tool_use(name: str = "Read") -> dict:
    return {
        "type": "assistant",
        "message": {
            "id": "msg_y",
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "tu_1", "name": name, "input": {}}],
            "stop_reason": "tool_use",
        },
    }


# -- Function existence ------------------------------------------------------


def test_detect_function_declared():
    """The detector must be defined as a callable function in the adapter."""
    script = f'source "{HARNESS}"; declare -F harness_claude_code_detect_hitl'
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"harness_claude_code_detect_hitl must be declared (S5 contract); declare -F failed: stderr={result.stderr!r}"
    )
    assert "harness_claude_code_detect_hitl" in result.stdout


# -- AFK gate: only enforce when MENTAT_INTERACTIVE=0 ------------------------


def test_interactive_default_skips_detection(tmp_path):
    """Interactive mode (env unset) must NOT trigger HITL even on wedge."""
    jsonl = _write_jsonl(tmp_path / "s.jsonl", [_assistant_text("Should I proceed?")])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": None}) == 0


def test_interactive_explicit_one_skips_detection(tmp_path):
    jsonl = _write_jsonl(tmp_path / "s.jsonl", [_assistant_text("Should I proceed?")])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "1"}) == 0


def test_empty_value_skips_detection(tmp_path):
    """ADR-0010 §Consequences: typo at env name fails closed — unrecognized
    value treated as interactive. Detection must not engage."""
    jsonl = _write_jsonl(tmp_path / "s.jsonl", [_assistant_text("Should I proceed?")])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": ""}) == 0


def test_unrecognized_value_skips_detection(tmp_path):
    jsonl = _write_jsonl(tmp_path / "s.jsonl", [_assistant_text("Should I proceed?")])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "maybe"}) == 0


# -- Empty / missing input ---------------------------------------------------


def test_missing_file_returns_zero():
    """Missing JSONL path under AFK must not raise — return 0 (no wedge evidence)."""
    assert _detect(Path("/nonexistent/path/session.jsonl"), {"MENTAT_INTERACTIVE": "0"}) == 0


def test_empty_file_returns_zero(tmp_path):
    jsonl = tmp_path / "empty.jsonl"
    jsonl.write_text("")
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


def test_no_assistant_events_returns_zero(tmp_path):
    """System-only stream has no assistant turn → not a wedge."""
    jsonl = _write_jsonl(
        tmp_path / "sys.jsonl",
        [
            {"type": "system", "subtype": "init"},
            {"type": "result", "subtype": "success", "is_error": False},
        ],
    )
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


# -- Positive detection: wedge pattern ---------------------------------------


def test_wedge_text_ending_with_question_mark_exits_42(tmp_path):
    """AFK + last assistant turn = text-only ending in `?` → HITL exit."""
    jsonl = _write_jsonl(
        tmp_path / "wedge.jsonl",
        [
            _assistant_text("Should I use option A or B?"),
        ],
    )
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == HITL_EXIT


def test_exit_code_is_exactly_42(tmp_path):
    """ADR-0010 contract: code is 42 specifically, not generic nonzero."""
    jsonl = _write_jsonl(
        tmp_path / "wedge.jsonl",
        [
            _assistant_text("What should I do?"),
        ],
    )
    code = _detect(jsonl, {"MENTAT_INTERACTIVE": "0"})
    assert code == 42, f"HITL exit must be 42 (ADR-0010); got {code}"


def test_trailing_whitespace_stripped(tmp_path):
    """`?` followed by trailing whitespace/newline still counts as question end."""
    jsonl = _write_jsonl(
        tmp_path / "wedge.jsonl",
        [
            _assistant_text("Should I continue?   \n\n  "),
        ],
    )
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == HITL_EXIT


# -- Negative: not a wedge ---------------------------------------------------


def test_text_ending_with_period_returns_zero(tmp_path):
    """A statement (ending `.`) is not a wedge."""
    jsonl = _write_jsonl(
        tmp_path / "ok.jsonl",
        [
            _assistant_text("Done. Implemented the feature."),
        ],
    )
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


def test_tool_use_in_last_turn_returns_zero(tmp_path):
    """Last assistant turn contains tool_use → real work, not a wedge."""
    jsonl = _write_jsonl(
        tmp_path / "tool.jsonl",
        [
            _assistant_text("Reading file."),
            _assistant_tool_use("Read"),
        ],
    )
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


def test_earlier_tool_use_does_not_save_wedge(tmp_path):
    """Earlier turn had tool_use, but LAST turn is text-only ending in `?` →
    wedge. S5 contract scopes detection to the final assistant turn."""
    jsonl = _write_jsonl(
        tmp_path / "trailing_wedge.jsonl",
        [
            _assistant_tool_use("Read"),
            _assistant_text("Did that help? Should I try something else?"),
        ],
    )
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == HITL_EXIT


def test_question_in_middle_only_returns_zero(tmp_path):
    """A `?` inside the text but not at the end is not a wedge."""
    jsonl = _write_jsonl(
        tmp_path / "mid.jsonl",
        [
            _assistant_text("I considered: should we A? No, B is better. Done."),
        ],
    )
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


def test_empty_text_block_returns_zero(tmp_path):
    """Empty-text assistant turn → not a wedge (nothing to inspect)."""
    jsonl = _write_jsonl(
        tmp_path / "empty_text.jsonl",
        [
            _assistant_text(""),
        ],
    )
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


# -- Multi-block text content -------------------------------------------------


def test_multi_text_blocks_uses_concatenated_tail(tmp_path):
    """If the assistant turn has multiple text blocks, the joined tail
    determines wedge status — last block ends in `?` → wedge."""
    msg = {
        "type": "assistant",
        "message": {
            "id": "msg_multi",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I'll handle this."},
                {"type": "text", "text": "But should I bump the version?"},
            ],
            "stop_reason": "end_turn",
        },
    }
    jsonl = _write_jsonl(tmp_path / "multi.jsonl", [msg])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == HITL_EXIT


def test_multi_text_blocks_last_non_question_returns_zero(tmp_path):
    msg = {
        "type": "assistant",
        "message": {
            "id": "msg_multi",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Should I check?"},
                {"type": "text", "text": "Yes — proceeding."},
            ],
            "stop_reason": "end_turn",
        },
    }
    jsonl = _write_jsonl(tmp_path / "multi_ok.jsonl", [msg])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


# -- Contract back-reference -------------------------------------------------


def test_detector_references_mentat_interactive():
    """Source must reference MENTAT_INTERACTIVE — the AFK gate is mandatory
    per ADR-0010 (HITL only fires inside an AFK chunk)."""
    src = HARNESS.read_text()
    assert "MENTAT_INTERACTIVE" in src, "claude-code.sh must reference MENTAT_INTERACTIVE in detector path"
    assert "detect_hitl" in src, "claude-code.sh must define harness_claude_code_detect_hitl"


def test_detector_uses_exit_code_42():
    """The 42 must appear in the adapter source — the canonical HITL exit
    code from ADR-0010. Drift guard: future renumbering breaks contract."""
    src = HARNESS.read_text()
    # 42 must appear in detector body (return/exit 42).
    assert "42" in src, "claude-code.sh must encode HITL exit code 42 (ADR-0010)"
