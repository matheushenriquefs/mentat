"""Tests for lib/tui.py — color, open_tty, prompt_yn branches."""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path
from unittest.mock import patch

_LIB = Path(__file__).resolve().parents[1] / ".agents" / "lib"


def _tui():
    from lib import tui

    return tui


# ── color ─────────────────────────────────────────────────────────────────────


def test_color_tty_returns_ansi_wrapped():
    tui = _tui()
    with patch.object(sys.stdout, "isatty", return_value=True):
        result = tui.color("hello", tui.DIM)
    assert result.startswith("\033[")
    assert "hello" in result
    assert result.endswith("\033[0m")


def test_color_non_tty_returns_plain():
    tui = _tui()
    with patch.object(sys.stdout, "isatty", return_value=False):
        result = tui.color("hello", tui.DIM)
    assert result == "hello"


# ── open_tty ──────────────────────────────────────────────────────────────────


def test_open_tty_stdin_isatty_yields_stdin():
    tui = _tui()
    with patch.object(sys.stdin, "isatty", return_value=True):
        with tui.open_tty() as t:
            assert t is sys.stdin


def test_open_tty_dev_tty_opens_when_stdin_not_tty(tmp_path):
    tui = _tui()
    fake_tty_path = tmp_path / "fake_tty"
    fake_tty_path.write_text("y\n")
    with patch.object(sys.stdin, "isatty", return_value=False):
        with patch("builtins.open", return_value=open(str(fake_tty_path))) as mock_open:
            with tui.open_tty() as t:
                assert t is not None
                line = t.readline()
                assert line.strip() == "y"
    mock_open.assert_called_once_with("/dev/tty")


def test_open_tty_yields_none_when_dev_tty_oserror():
    tui = _tui()
    with patch.object(sys.stdin, "isatty", return_value=False):
        with patch("builtins.open", side_effect=OSError("no tty")):
            with tui.open_tty() as t:
                assert t is None


# ── prompt_yn ─────────────────────────────────────────────────────────────────


def _fake_stdout_context():
    """Context manager that redirects stdout writes to a StringIO."""

    @contextlib.contextmanager
    def _ctx():
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            yield buf

    return _ctx()


def test_prompt_yn_empty_input_returns_default_true():
    tui = _tui()
    fake_tty = io.StringIO("\n")
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        result = tui.prompt_yn("Install?", default=True, tty=fake_tty)
    assert result is True


def test_prompt_yn_empty_input_returns_default_false():
    tui = _tui()
    fake_tty = io.StringIO("\n")
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        result = tui.prompt_yn("Install?", default=False, tty=fake_tty)
    assert result is False


def test_prompt_yn_yes_input_returns_true():
    tui = _tui()
    fake_tty = io.StringIO("y\n")
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        result = tui.prompt_yn("Install?", default=False, tty=fake_tty)
    assert result is True


def test_prompt_yn_no_input_returns_false():
    tui = _tui()
    fake_tty = io.StringIO("n\n")
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        result = tui.prompt_yn("Install?", default=True, tty=fake_tty)
    assert result is False


# ── prompt_text ───────────────────────────────────────────────────────────────


def test_prompt_text_empty_input_returns_default():
    tui = _tui()
    fake_tty = io.StringIO("\n")
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        result = tui.prompt_text("Enter cmd:", default="echo hi", tty=fake_tty)
    assert result == "echo hi"


def test_prompt_text_non_empty_input_overrides_default():
    tui = _tui()
    fake_tty = io.StringIO("custom\n")
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        result = tui.prompt_text("Enter cmd:", default="echo hi", tty=fake_tty)
    assert result == "custom"
