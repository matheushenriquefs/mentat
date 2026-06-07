"""G3-S6: cursor.sh mirrors AFK enforcement + HITL detection (ADR-0010).

Spec (~/.agents/plans/mentat-architecture-revamp-g3-harness-afk.md S6):
  - Second adapter implementing the same contract — proves the seam is real.
  - Cursor lacks a --disallowedTools equivalent (registry row stores
    disallowed_tools_arg="") so AFK is enforced via system-prompt clause only.
  - Adapter must emit a warning to stderr when AFK is engaged without a
    CLI-flag enforcement path, so operators know enforcement is prompt-bound.
  - Detector contract identical to claude-code (G3-S5): last assistant turn
    has no tool_use AND text-tail ends `?` → exit 42 under AFK.

Blocked-by: S3 (ADR-0010), S4/S5 (shape mirrored).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / ".agents" / "bin" / "lib" / "harness" / "cursor.sh"
REGISTRY = ROOT / ".agents" / "bin" / "lib" / "harness-registry.jsonc"
ADR_0010 = ROOT / ".agents" / "docs" / "adr" / "0010-hitl-routing.md"

CLAUSE = (
    "AFK mode: do not ask the user questions. "
    "On ambiguity, exit nonzero with a HITL audit reason instead of guessing."
)

HITL_EXIT = 42


# -- helpers -----------------------------------------------------------------


def _invoke_cmd(env_overrides: dict, prompt: str = "do thing"):
    """Source cursor.sh, call harness_cursor_cmd, return (argv, stderr)."""
    env = os.environ.copy()
    for k, v in env_overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    script = f'set -e; source "{HARNESS}"; harness_cursor_cmd "$1"'
    result = subprocess.run(
        ["bash", "-c", script, "_", prompt],
        env=env, capture_output=True, check=True,
    )
    tokens = result.stdout.split(b"\x00")
    if tokens and tokens[-1] == b"":
        tokens = tokens[:-1]
    return [t.decode() for t in tokens], result.stderr.decode()


def _detect(jsonl_path: Path, env_overrides: dict | None = None) -> int:
    env = os.environ.copy()
    overrides = env_overrides or {}
    for k, v in overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    script = f'source "{HARNESS}"; harness_cursor_detect_hitl "$1"'
    result = subprocess.run(
        ["bash", "-c", script, "_", str(jsonl_path)],
        env=env, capture_output=True,
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


# -- harness_cursor_cmd: interactive default ---------------------------------


def test_interactive_default_prompt_unchanged():
    argv, _ = _invoke_cmd({"MENTAT_INTERACTIVE": None}, prompt="do thing")
    assert argv[-1] == "do thing", (
        f"interactive default: prompt must be verbatim user input; got {argv[-1]!r}"
    )
    assert CLAUSE not in " ".join(argv), (
        "interactive default must NOT prepend the AFK clause"
    )


def test_interactive_default_no_stderr_warning():
    _, stderr = _invoke_cmd({"MENTAT_INTERACTIVE": None})
    assert "AFK" not in stderr and "disallowedTools" not in stderr, (
        f"interactive default must not emit AFK warning; stderr={stderr!r}"
    )


def test_interactive_explicit_one_unchanged():
    argv, stderr = _invoke_cmd({"MENTAT_INTERACTIVE": "1"})
    assert CLAUSE not in " ".join(argv)
    assert "AFK" not in stderr


def test_unrecognized_value_treated_as_interactive():
    """Fail-closed: typo at env-var value must NOT silently engage AFK."""
    argv, _ = _invoke_cmd({"MENTAT_INTERACTIVE": "maybe"})
    assert CLAUSE not in " ".join(argv)


def test_empty_value_treated_as_interactive():
    argv, _ = _invoke_cmd({"MENTAT_INTERACTIVE": ""})
    assert CLAUSE not in " ".join(argv)


# -- harness_cursor_cmd: AFK mode --------------------------------------------


def test_afk_prepends_clause_to_prompt():
    argv, _ = _invoke_cmd({"MENTAT_INTERACTIVE": "0"}, prompt="do ambiguous thing")
    prompt_arg = argv[-1]
    assert CLAUSE in prompt_arg, (
        f"AFK mode must prepend clause to prompt; got prompt={prompt_arg!r}"
    )
    assert "do ambiguous thing" in prompt_arg
    assert prompt_arg.index(CLAUSE) < prompt_arg.index("do ambiguous thing"), (
        "clause must be prepended (before user prompt), not appended"
    )


def test_afk_emits_stderr_warning_about_no_disallowed_tools():
    """Cursor lacks a --disallowedTools equivalent; adapter must warn so
    operators know enforcement is prompt-bound, not CLI-bound."""
    _, stderr = _invoke_cmd({"MENTAT_INTERACTIVE": "0"})
    assert stderr, "AFK mode must emit a warning to stderr"
    low = stderr.lower()
    assert "cursor" in low, f"warning must name cursor; stderr={stderr!r}"
    # Warning must mention prompt-only enforcement (no CLI tool-restriction).
    assert "prompt" in low or "disallowedtools" in low or "system prompt" in low, (
        f"warning must explain that enforcement is via system prompt; stderr={stderr!r}"
    )


def test_afk_keeps_base_args():
    """Base args (-p, --output-format stream-json, --force) must survive AFK."""
    argv, _ = _invoke_cmd({"MENTAT_INTERACTIVE": "0"})
    for expected in ("-p", "--output-format", "stream-json", "--force"):
        assert expected in argv, (
            f"AFK mode dropped base arg {expected!r}; argv={argv}"
        )


def test_afk_keeps_cursor_bin_first():
    argv, _ = _invoke_cmd({"MENTAT_INTERACTIVE": "0"})
    assert argv[0] == "cursor-agent", (
        f"AFK mode must keep `cursor-agent` as argv[0]; got {argv[0]!r}"
    )


def test_afk_does_not_append_cli_disallowed_flag():
    """Cursor has no --disallowedTools — adapter must NOT fabricate one."""
    argv, _ = _invoke_cmd({"MENTAT_INTERACTIVE": "0"})
    joined = " ".join(argv)
    assert "--disallowedTools" not in joined, (
        f"cursor lacks --disallowedTools; adapter must not append it; argv={argv}"
    )
    assert "AskUserQuestion" not in joined, (
        f"cursor has no tool-restriction flag; AskUserQuestion must not appear; argv={argv}"
    )


# -- HITL detector contract --------------------------------------------------


def test_detect_function_declared():
    script = f'source "{HARNESS}"; declare -F harness_cursor_detect_hitl'
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, (
        f"harness_cursor_detect_hitl must be declared; stderr={result.stderr!r}"
    )
    assert "harness_cursor_detect_hitl" in result.stdout


def test_interactive_default_skips_detection(tmp_path):
    jsonl = _write_jsonl(tmp_path / "s.jsonl", [_assistant_text("Should I proceed?")])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": None}) == 0


def test_interactive_explicit_one_skips_detection(tmp_path):
    jsonl = _write_jsonl(tmp_path / "s.jsonl", [_assistant_text("Should I proceed?")])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "1"}) == 0


def test_unrecognized_value_skips_detection(tmp_path):
    jsonl = _write_jsonl(tmp_path / "s.jsonl", [_assistant_text("Should I proceed?")])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "maybe"}) == 0


def test_missing_file_returns_zero():
    assert _detect(Path("/nonexistent/path/session.jsonl"),
                   {"MENTAT_INTERACTIVE": "0"}) == 0


def test_empty_file_returns_zero(tmp_path):
    jsonl = tmp_path / "empty.jsonl"
    jsonl.write_text("")
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


def test_no_assistant_events_returns_zero(tmp_path):
    jsonl = _write_jsonl(tmp_path / "sys.jsonl", [
        {"type": "system", "subtype": "init"},
        {"type": "result", "subtype": "success", "is_error": False},
    ])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


def test_wedge_text_ending_with_question_mark_exits_42(tmp_path):
    jsonl = _write_jsonl(tmp_path / "wedge.jsonl", [
        _assistant_text("Should I use option A or B?"),
    ])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == HITL_EXIT


def test_exit_code_is_exactly_42(tmp_path):
    """Contract: identical exit code to claude-code (ADR-0010 §HITL)."""
    jsonl = _write_jsonl(tmp_path / "wedge.jsonl", [
        _assistant_text("What should I do?"),
    ])
    code = _detect(jsonl, {"MENTAT_INTERACTIVE": "0"})
    assert code == 42, f"HITL exit must be 42 (ADR-0010); got {code}"


def test_trailing_whitespace_stripped(tmp_path):
    jsonl = _write_jsonl(tmp_path / "wedge.jsonl", [
        _assistant_text("Should I continue?   \n\n  "),
    ])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == HITL_EXIT


def test_text_ending_with_period_returns_zero(tmp_path):
    jsonl = _write_jsonl(tmp_path / "ok.jsonl", [
        _assistant_text("Done. Implemented the feature."),
    ])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


def test_tool_use_in_last_turn_returns_zero(tmp_path):
    jsonl = _write_jsonl(tmp_path / "tool.jsonl", [
        _assistant_text("Reading file."),
        _assistant_tool_use("Read"),
    ])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


def test_earlier_tool_use_does_not_save_wedge(tmp_path):
    """Earlier tool_use; last turn is text-only ending `?` → wedge."""
    jsonl = _write_jsonl(tmp_path / "trailing_wedge.jsonl", [
        _assistant_tool_use("Read"),
        _assistant_text("Did that help? Should I try something else?"),
    ])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == HITL_EXIT


def test_question_in_middle_only_returns_zero(tmp_path):
    jsonl = _write_jsonl(tmp_path / "mid.jsonl", [
        _assistant_text("I considered: should we A? No, B is better. Done."),
    ])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


def test_empty_text_block_returns_zero(tmp_path):
    jsonl = _write_jsonl(tmp_path / "empty_text.jsonl", [_assistant_text("")])
    assert _detect(jsonl, {"MENTAT_INTERACTIVE": "0"}) == 0


def test_multi_text_blocks_uses_concatenated_tail(tmp_path):
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


# -- Contract back-references (drift guards) ---------------------------------


def test_detector_references_mentat_interactive():
    """AFK gate must be present in source — required by ADR-0010."""
    src = HARNESS.read_text()
    assert "MENTAT_INTERACTIVE" in src
    assert "detect_hitl" in src


def test_detector_uses_exit_code_42():
    """HITL exit code 42 must appear in cursor adapter — ADR-0010 contract."""
    src = HARNESS.read_text()
    assert re.search(r"\b42\b", src), (
        "cursor.sh must encode HITL exit code 42 (ADR-0010)"
    )


def test_cursor_clause_matches_registry():
    """Adapter uses byte-identical clause text from registry row."""
    raw = REGISTRY.read_text()
    parsed = json.loads(re.sub(r"//.*$", "", raw, flags=re.MULTILINE))
    registry_clause = parsed["harnesses"]["cursor"]["system_prompt_template"]
    assert registry_clause == CLAUSE, (
        f"registry clause drifted; got {registry_clause!r}"
    )
    argv, _ = _invoke_cmd({"MENTAT_INTERACTIVE": "0"}, prompt="X")
    assert registry_clause in argv[-1], (
        f"AFK prompt must carry registry clause verbatim; prompt={argv[-1]!r}"
    )


def test_registry_disallowed_tools_arg_is_empty():
    """Pre-condition for S6: cursor row has no CLI-flag enforcement path.
    Adapter behavior (prompt-only + warning) is correct iff this stays empty."""
    raw = REGISTRY.read_text()
    parsed = json.loads(re.sub(r"//.*$", "", raw, flags=re.MULTILINE))
    arg = parsed["harnesses"]["cursor"]["disallowed_tools_arg"]
    assert arg == "", (
        f"cursor's disallowed_tools_arg must be empty (S6 contract); got {arg!r}. "
        "If cursor later grows a tool-restriction flag, this test (and the "
        "adapter) must change together."
    )
