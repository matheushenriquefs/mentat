"""G3-S2: harness-registry.jsonc populated with 8 adapter rows.

Spec (~/.agents/plans/mentat-architecture-revamp-g3-harness-afk.md S2):
  - One row per existing adapter (aider, amp, claude-code, codex, copilot,
    cursor, gemini, openhands).
  - Mark `supports_afk: true` only for adapters that actually enforce it —
    initially `claude-code` and `cursor` per S5/S6.
  - Verify: `jq . harness-registry.jsonc` parses. Every row has required
    fields. Each name corresponds to an existing `lib/harness/<name>.sh`.

Invariants preserved from S1:
  - `required_fields` list unchanged.
  - `on_unknown` == "refuse".

Blocked-by: S1 (ADR-0012 + stub) — done.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / ".agents" / "bin" / "lib" / "harness-registry.jsonc"
HARNESS_DIR = ROOT / ".agents" / "bin" / "lib" / "harness"

CANONICAL_NAMES = (
    "aider", "amp", "claude-code", "codex", "copilot",
    "cursor", "gemini", "openhands",
)

REQUIRED_FIELDS = (
    "name", "bin", "base_args", "supports_afk",
    "disallowed_tools_arg", "system_prompt_template",
)

AFK_ADAPTERS = ("claude-code", "cursor")


def _strip_jsonc_comments(text: str) -> str:
    return re.sub(r"//.*$", "", text, flags=re.MULTILINE)


def _load() -> dict:
    return json.loads(_strip_jsonc_comments(REGISTRY.read_text()))


# -- Eight rows present -------------------------------------------------------


def test_registry_has_eight_harness_rows():
    parsed = _load()
    rows = parsed["harnesses"]
    assert len(rows) == 8, f"S2: expected 8 rows, got {len(rows)}: {sorted(rows)}"


def test_registry_row_keys_match_canonical_set():
    parsed = _load()
    assert set(parsed["harnesses"]) == set(CANONICAL_NAMES), (
        f"row keys {sorted(parsed['harnesses'])} must equal canonical "
        f"set {sorted(CANONICAL_NAMES)}"
    )


# -- Every row has every required field --------------------------------------


def test_every_row_has_all_required_fields():
    parsed = _load()
    for name, row in parsed["harnesses"].items():
        missing = [f for f in REQUIRED_FIELDS if f not in row]
        assert not missing, f"row {name!r} missing required fields: {missing}"


# -- Field type discipline ---------------------------------------------------


def test_row_name_field_equals_key():
    parsed = _load()
    for key, row in parsed["harnesses"].items():
        assert row["name"] == key, (
            f"row[{key!r}].name == {row['name']!r}, must equal key"
        )


def test_row_bin_is_non_empty_string():
    parsed = _load()
    for name, row in parsed["harnesses"].items():
        assert isinstance(row["bin"], str) and row["bin"], (
            f"row[{name!r}].bin must be non-empty string, got {row['bin']!r}"
        )


def test_row_base_args_is_list_of_strings():
    parsed = _load()
    for name, row in parsed["harnesses"].items():
        ba = row["base_args"]
        assert isinstance(ba, list), f"row[{name!r}].base_args must be list, got {type(ba).__name__}"
        for i, arg in enumerate(ba):
            assert isinstance(arg, str), (
                f"row[{name!r}].base_args[{i}] must be string, got {type(arg).__name__}"
            )


def test_row_supports_afk_is_bool():
    parsed = _load()
    for name, row in parsed["harnesses"].items():
        assert isinstance(row["supports_afk"], bool), (
            f"row[{name!r}].supports_afk must be bool, got {type(row['supports_afk']).__name__}"
        )


def test_row_disallowed_tools_arg_is_string():
    parsed = _load()
    for name, row in parsed["harnesses"].items():
        assert isinstance(row["disallowed_tools_arg"], str), (
            f"row[{name!r}].disallowed_tools_arg must be string"
        )


def test_row_system_prompt_template_is_string():
    parsed = _load()
    for name, row in parsed["harnesses"].items():
        assert isinstance(row["system_prompt_template"], str), (
            f"row[{name!r}].system_prompt_template must be string"
        )


# -- supports_afk binding ----------------------------------------------------


def test_supports_afk_true_only_for_claude_code_and_cursor():
    parsed = _load()
    true_set = {name for name, row in parsed["harnesses"].items() if row["supports_afk"]}
    assert true_set == set(AFK_ADAPTERS), (
        f"supports_afk=true set {sorted(true_set)} must equal {sorted(AFK_ADAPTERS)} "
        f"(per S2 spec — initially claude-code + cursor only)"
    )


# -- Adapter file existence (name <-> file binding) --------------------------


def test_every_row_name_has_adapter_file():
    parsed = _load()
    for name in parsed["harnesses"]:
        adapter = HARNESS_DIR / f"{name}.sh"
        assert adapter.is_file(), (
            f"row[{name!r}] must correspond to {adapter.relative_to(ROOT)} — missing"
        )


# -- AFK-enforcing adapters carry non-empty system prompt clause -------------


def test_afk_adapters_have_system_prompt_clause():
    """S2 + S3 contract: supports_afk=true rows must carry a non-empty
    system_prompt_template (clause forbidding question-asking per ADR-0012
    row contract). The exact text is refined by S3 — S2 just lands the
    initial draft."""
    parsed = _load()
    for name in AFK_ADAPTERS:
        clause = parsed["harnesses"][name]["system_prompt_template"]
        assert clause.strip(), (
            f"row[{name!r}].system_prompt_template must be non-empty for "
            f"supports_afk=true adapter (S3 refines wording later)"
        )


# -- claude-code's disallowed_tools_arg mentions AskUserQuestion -------------


def test_claude_code_disallowed_tools_arg_names_ask_user_question():
    """Per G3-S4 plan: claude-code AFK mode appends
    `--disallowedTools AskUserQuestion`. The argv fragment lives in the row.
    Cursor may have empty disallowed_tools_arg per S6 (no native knob)."""
    parsed = _load()
    arg = parsed["harnesses"]["claude-code"]["disallowed_tools_arg"]
    assert "AskUserQuestion" in arg, (
        f"claude-code disallowed_tools_arg must reference AskUserQuestion "
        f"(per G3-S4 plan), got {arg!r}"
    )


# -- bin names match the actual executables in adapter cmd functions ---------


def test_row_bin_matches_adapter_executable():
    """Sanity-check: registry's `bin` field must match the first token of
    the adapter's `harness_<name>_cmd` function — otherwise the registry
    lies about which executable runs."""
    parsed = _load()
    # Adapter slug -> expected executable name (from `printf '%s\0' <bin> ...`
    # line in each lib/harness/<name>.sh).
    expected_bins = {
        "aider": "aider",
        "amp": "amp",
        "claude-code": "claude",
        "codex": "codex",
        "copilot": "copilot",
        "cursor": "cursor-agent",
        "gemini": "gemini",
        "openhands": "openhands",
    }
    for name, expected in expected_bins.items():
        actual = parsed["harnesses"][name]["bin"]
        assert actual == expected, (
            f"row[{name!r}].bin == {actual!r}, expected {expected!r} "
            f"(must match printf token in lib/harness/{name}.sh)"
        )


# -- S1 invariants preserved (no schema drift) -------------------------------


def test_required_fields_list_unchanged():
    parsed = _load()
    assert set(parsed["required_fields"]) == set(REQUIRED_FIELDS), (
        f"required_fields drifted: {parsed['required_fields']!r}"
    )


def test_on_unknown_still_refuse():
    parsed = _load()
    assert parsed["on_unknown"] == "refuse", (
        f"on_unknown must remain 'refuse' (S1 fail-closed invariant), "
        f"got {parsed['on_unknown']!r}"
    )


# -- Registry still valid JSONC after strip-// --------------------------------


def test_registry_parses_after_comment_strip():
    raw = REGISTRY.read_text()
    parsed = json.loads(_strip_jsonc_comments(raw))
    assert isinstance(parsed, dict)
    assert "harnesses" in parsed and isinstance(parsed["harnesses"], dict)
