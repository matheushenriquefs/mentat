"""G3-S4: claude-code.sh enforces AFK when MENTAT_INTERACTIVE=0.

Spec (~/.agents/plans/mentat-architecture-revamp-g3-harness-afk.md S4):
  - When MENTAT_INTERACTIVE=0: append `--disallowedTools AskUserQuestion`
    to invocation, prepend system-prompt clause from S3 (ADR-0010).
  - Interactive run unchanged.

Contract source — ADR-0010 four-tuple:
  - signal env: MENTAT_INTERACTIVE=0 (opt-in; default/unset/other = interactive)
  - clause: byte-for-byte match against harness-registry.jsonc claude-code row.

Blocked-by: S3 (ADR-0010) — done.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / ".agents" / "bin" / "lib" / "harness" / "claude-code.sh"
REGISTRY = ROOT / ".agents" / "bin" / "lib" / "harness-registry.jsonc"
ADR_0010 = ROOT / ".agents" / "docs" / "adr" / "0010-hitl-routing.md"

CLAUSE = (
    "AFK mode: do not ask the user questions. "
    "On ambiguity, exit nonzero with a HITL audit reason instead of guessing."
)


def _invoke_cmd(env_overrides: dict, prompt: str = "do thing") -> list[str]:
    """Source claude-code.sh, call harness_claude_code_cmd, return argv list.

    The adapter writes NUL-delimited argv to stdout; we split on NUL and drop
    the trailing empty token left by the final separator.
    """
    env = os.environ.copy()
    for k, v in env_overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    script = f'set -e; source "{HARNESS}"; harness_claude_code_cmd "$1"'
    result = subprocess.run(
        ["bash", "-c", script, "_", prompt],
        env=env, capture_output=True, check=True,
    )
    raw = result.stdout
    tokens = raw.split(b"\x00")
    if tokens and tokens[-1] == b"":
        tokens = tokens[:-1]
    return [t.decode() for t in tokens]


# -- Interactive default (env unset) -----------------------------------------


def test_interactive_default_omits_disallowed_tools():
    argv = _invoke_cmd({"MENTAT_INTERACTIVE": None})
    joined = " ".join(argv)
    assert "AskUserQuestion" not in joined, (
        f"interactive default must NOT add --disallowedTools AskUserQuestion; got {argv}"
    )
    assert "--disallowedTools" not in argv, (
        f"interactive default must not add --disallowedTools flag; got {argv}"
    )


def test_interactive_default_prompt_unchanged():
    argv = _invoke_cmd({"MENTAT_INTERACTIVE": None}, prompt="do thing")
    assert argv[-1] == "do thing", (
        f"interactive default: prompt arg must be verbatim user input, got {argv[-1]!r}"
    )


def test_interactive_explicit_one_omits_disallowed_tools():
    argv = _invoke_cmd({"MENTAT_INTERACTIVE": "1"})
    assert "AskUserQuestion" not in " ".join(argv), (
        "MENTAT_INTERACTIVE=1 (explicit interactive) must not engage AFK"
    )


# -- AFK mode (MENTAT_INTERACTIVE=0) -----------------------------------------


def test_afk_appends_disallowed_tools_askuserquestion():
    argv = _invoke_cmd({"MENTAT_INTERACTIVE": "0"})
    found = False
    for i, tok in enumerate(argv):
        if tok == "--disallowedTools":
            assert i + 1 < len(argv), "--disallowedTools without value"
            assert argv[i + 1] == "AskUserQuestion", (
                f"--disallowedTools value must be `AskUserQuestion`, got {argv[i+1]!r}"
            )
            found = True
            break
    assert found, f"AFK mode missing --disallowedTools AskUserQuestion; argv={argv}"


def test_afk_prepends_system_prompt_clause_to_prompt():
    argv = _invoke_cmd({"MENTAT_INTERACTIVE": "0"}, prompt="do ambiguous thing")
    prompt_arg = argv[-1]
    assert CLAUSE in prompt_arg, (
        f"AFK mode must prepend clause to prompt; got prompt={prompt_arg!r}"
    )
    assert "do ambiguous thing" in prompt_arg, (
        f"AFK mode must preserve user prompt; got {prompt_arg!r}"
    )
    # Clause must come before user prompt (prepend, not append)
    assert prompt_arg.index(CLAUSE) < prompt_arg.index("do ambiguous thing"), (
        "clause must be prepended (before user prompt), not appended"
    )


def test_afk_preserves_base_args():
    argv = _invoke_cmd({"MENTAT_INTERACTIVE": "0"})
    # Base flags from interactive mode must still be present.
    for expected in ("-p", "--output-format", "stream-json", "--permission-mode",
                     "acceptEdits", "--allowedTools"):
        assert expected in argv, (
            f"AFK mode dropped base arg {expected!r}; argv={argv}"
        )


def test_afk_keeps_claude_bin_first():
    argv = _invoke_cmd({"MENTAT_INTERACTIVE": "0"})
    assert argv[0] == "claude", (
        f"AFK mode must keep `claude` as argv[0]; got {argv[0]!r}"
    )


# -- Fail-closed for unrecognized values -------------------------------------


def test_unrecognized_value_treated_as_interactive():
    """ADR-0010 consequence: typo at env-var name fails closed — unrecognized
    value treated as interactive (the default). AFK is never silently engaged."""
    argv = _invoke_cmd({"MENTAT_INTERACTIVE": "maybe"})
    assert "AskUserQuestion" not in " ".join(argv), (
        f"unrecognized MENTAT_INTERACTIVE value `maybe` must NOT engage AFK; got {argv}"
    )


def test_empty_value_treated_as_interactive():
    argv = _invoke_cmd({"MENTAT_INTERACTIVE": ""})
    assert "AskUserQuestion" not in " ".join(argv), (
        "empty MENTAT_INTERACTIVE must not engage AFK"
    )


# -- Contract alignment (no clause drift) ------------------------------------


def test_adapter_clause_matches_registry():
    """harness-registry.jsonc claude-code row carries the canonical clause.
    Adapter must use byte-identical text — any drift breaks the contract."""
    raw = REGISTRY.read_text()
    parsed = json.loads(re.sub(r"//.*$", "", raw, flags=re.MULTILINE))
    registry_clause = parsed["harnesses"]["claude-code"]["system_prompt_template"]
    assert registry_clause == CLAUSE, (
        f"test CLAUSE constant drifted from registry; "
        f"registry={registry_clause!r}, test={CLAUSE!r}"
    )


def test_adapter_clause_matches_adr_0010():
    """ADR-0010 is the canonical source. Test constant must agree."""
    src = ADR_0010.read_text()
    assert CLAUSE in src, (
        f"ADR-0010 must contain the clause verbatim; test constant may have drifted"
    )


def test_afk_prompt_clause_matches_registry_byte_for_byte():
    """End-to-end: argv produced by adapter under AFK must contain the
    registry's clause verbatim. Closes the loop ADR-0010 ↔ registry ↔ adapter."""
    raw = REGISTRY.read_text()
    parsed = json.loads(re.sub(r"//.*$", "", raw, flags=re.MULTILINE))
    registry_clause = parsed["harnesses"]["claude-code"]["system_prompt_template"]
    argv = _invoke_cmd({"MENTAT_INTERACTIVE": "0"}, prompt="X")
    assert registry_clause in argv[-1], (
        f"AFK prompt must carry registry clause verbatim; "
        f"prompt={argv[-1]!r}, expected substring={registry_clause!r}"
    )


# -- disallowed_tools_arg from registry agrees with adapter ------------------


def test_disallowed_tools_arg_matches_registry():
    """ADR-0012 row contract: claude-code.disallowed_tools_arg names the
    argv fragment appended under AFK. Adapter must emit that fragment."""
    raw = REGISTRY.read_text()
    parsed = json.loads(re.sub(r"//.*$", "", raw, flags=re.MULTILINE))
    arg_template = parsed["harnesses"]["claude-code"]["disallowed_tools_arg"]
    # Registry stores it as a single string ("--disallowedTools AskUserQuestion");
    # adapter splits into two argv tokens. Both tokens must appear and be adjacent.
    expected_tokens = arg_template.split()
    argv = _invoke_cmd({"MENTAT_INTERACTIVE": "0"})
    for i in range(len(argv) - len(expected_tokens) + 1):
        if argv[i:i + len(expected_tokens)] == expected_tokens:
            return
    raise AssertionError(
        f"adapter argv does not contain registry disallowed_tools_arg tokens "
        f"{expected_tokens!r} adjacently; argv={argv}"
    )
