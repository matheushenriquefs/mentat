"""Built-in harness adapters — claude_code + cursor (ADR-0009)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from plugins.builtin.claude_code import ClaudeCodeHarness
from plugins.builtin.cursor import CursorHarness


def test_claude_code_harness_name() -> None:
    assert ClaudeCodeHarness().name == "claude-code"


def test_claude_code_harness_invoke_runs_claude_cli() -> None:
    harness = ClaudeCodeHarness()
    with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
        rc = harness.invoke(["--version"])
    assert rc == 0
    mock_run.assert_called_once_with(["claude", "--version"])


def test_cursor_harness_name() -> None:
    assert CursorHarness().name == "cursor"


def test_cursor_harness_invoke_runs_cursor_cli() -> None:
    harness = CursorHarness()
    with patch("subprocess.run", return_value=MagicMock(returncode=3)) as mock_run:
        rc = harness.invoke(["run", "plan.md"])
    assert rc == 3
    mock_run.assert_called_once_with(["cursor", "run", "plan.md"])
