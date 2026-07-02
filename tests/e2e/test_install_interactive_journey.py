"""E2E: the interactive install stack — companion installer + PATH setup.

Drives ``companions.py`` and ``path_setup.py`` through real journeys: a fake TTY
feeds prompt answers, real subprocesses run the (stubbed) companion install
commands, and a real shell rc file is appended on disk. A pty-backed subprocess
covers the spinner + colored-output branches that only fire when stdout is a
real terminal.
"""

from __future__ import annotations

import os
import pty
import subprocess
import sys
import textwrap
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPANIONS_PY = REPO_ROOT / ".agents/skills/mentat-install/scripts/companions.py"
PATH_SETUP_PY = REPO_ROOT / ".agents/skills/mentat-install/scripts/path_setup.py"
TUI_PY = REPO_ROOT / ".agents/lib/tui.py"


class FakeTTY:
    """A readable stand-in for /dev/tty: hands back queued answer lines."""

    def __init__(self, *lines: str) -> None:
        self._lines = list(lines)

    def readline(self) -> str:
        return self._lines.pop(0) if self._lines else ""


@contextmanager
def _yield(value: object):
    yield value


# ── companions.py ─────────────────────────────────────────────────────────────


def test_install_one_skips_when_already_installed(capsys):
    companions = load_script(COMPANIONS_PY, "companions_skip")
    companion = {"name": "foo", "docs": "http://x", "install_cmd": ["true"]}
    companions.install_one(companion, tty=FakeTTY("y\n"))
    out = capsys.readouterr().out
    assert "skipped — already installed" in out


def test_install_one_runs_command_and_reports_success(capsys):
    companions = load_script(COMPANIONS_PY, "companions_ok")
    companion = {"name": "bar", "docs": "http://x", "install_cmd": ["true"]}
    # not-installed → accept default cmd → confirm run.
    companions.install_one(companion, tty=FakeTTY("n\n", "\n", "y\n"))
    assert "bar installed" in capsys.readouterr().out


def test_install_one_reports_failure_on_nonzero_exit(capsys):
    companions = load_script(COMPANIONS_PY, "companions_fail")
    companion = {"name": "baz", "docs": "http://x", "install_cmd": ["false"]}
    companions.install_one(companion, tty=FakeTTY("n\n", "false\n", "y\n"))
    assert "baz failed" in capsys.readouterr().out


def test_install_one_skips_when_user_declines_run(capsys):
    companions = load_script(COMPANIONS_PY, "companions_decline")
    companion = {"name": "qux", "docs": "http://x", "install_cmd": ["true"]}
    companions.install_one(companion, tty=FakeTTY("n\n", "\n", "n\n"))
    assert "skipped — user declined" in capsys.readouterr().out


def test_install_all_yes_is_noop():
    companions = load_script(COMPANIONS_PY, "companions_yes")
    assert companions.install_all(yes=True) == 0


def test_install_all_no_tty_is_noop(monkeypatch):
    companions = load_script(COMPANIONS_PY, "companions_notty")
    monkeypatch.setattr(companions, "open_tty", lambda: _yield(None))
    assert companions.install_all(yes=False) == 0


def test_install_all_drives_every_companion(monkeypatch, capsys):
    companions = load_script(COMPANIONS_PY, "companions_all")
    # Two companions, each answered "already installed" (one line apiece).
    fake = FakeTTY(*["y\n"] * len(companions.COMPANIONS))
    monkeypatch.setattr(companions, "open_tty", lambda: _yield(fake))
    assert companions.install_all(yes=False) == 0
    out = capsys.readouterr().out
    assert "mentat installer" in out
    assert out.count("skipped — already installed") == len(companions.COMPANIONS)


def test_spinner_and_color_render_under_real_tty(tmp_path):
    """A pty-backed run: stdout.isatty() is True, so the spinner thread starts and
    tui.color emits ANSI. Covers companions._Spinner._loop + tui tty branches."""
    driver = tmp_path / "driver.py"
    driver.write_text(
        textwrap.dedent(
            f"""
            import importlib.util, pathlib, sys
            path = pathlib.Path({str(COMPANIONS_PY)!r})
            spec = importlib.util.spec_from_file_location("comp_pty", path)
            comp = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(comp)

            class FakeTTY:
                def __init__(self, *lines): self._l = list(lines)
                def readline(self): return self._l.pop(0) if self._l else ""

            companion = {{"name": "spin", "docs": "http://x", "install_cmd": ["sleep", "0.15"]}}
            comp.install_one(companion, tty=FakeTTY("n\\n", "\\n", "y\\n"))
            """
        )
    )
    master, slave = pty.openpty()
    try:
        proc = subprocess.run(
            [sys.executable, str(driver)],
            stdout=slave,
            stderr=slave,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
        os.close(slave)
        chunks = []
        while True:
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
    finally:
        os.close(master)
    assert proc.returncode == 0
    output = b"".join(chunks).decode(errors="replace")
    assert "\033[" in output, "colored ANSI output expected under a real tty"
    assert "spin installed" in output


# ── path_setup.py ─────────────────────────────────────────────────────────────


@pytest.fixture
def path_setup(monkeypatch, tmp_path):
    """Load path_setup with _MENTAT_BIN / _SHELL_RC redirected into tmp and a
    PATH that does not already contain the bin dir."""
    ps = load_script(PATH_SETUP_PY, "path_setup")
    bin_dir = tmp_path / ".mentat" / "bin"
    monkeypatch.setattr(ps, "_MENTAT_BIN", bin_dir)
    monkeypatch.setenv("PATH", "/usr/bin")
    return ps


def test_setup_path_skips_when_already_in_path(path_setup, monkeypatch, capsys):
    monkeypatch.setenv("PATH", f"/usr/bin:{path_setup._MENTAT_BIN}")
    path_setup.setup_path(yes=True)
    assert "already in PATH" in capsys.readouterr().out


def test_setup_path_skips_unsupported_shell(path_setup, monkeypatch, capsys):
    monkeypatch.setenv("SHELL", "/usr/bin/weirdsh")
    path_setup.setup_path(yes=True)
    assert "unsupported shell" in capsys.readouterr().out


def test_setup_path_skips_when_rc_already_has_mentat(path_setup, monkeypatch, tmp_path, capsys):
    rc = tmp_path / ".zshrc"
    rc.write_text('export PATH="$HOME/.mentat/bin:$PATH"\n')
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(path_setup, "_SHELL_RC", {"zsh": rc})
    path_setup.setup_path(yes=True)
    assert "already in" in capsys.readouterr().out
    # rc untouched.
    assert rc.read_text().count(".mentat/bin") == 1


def test_setup_path_yes_flag_prints_manual_hint(path_setup, monkeypatch, tmp_path, capsys):
    rc = tmp_path / ".zshrc"
    rc.write_text("# empty\n")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(path_setup, "_SHELL_RC", {"zsh": rc})
    path_setup.setup_path(yes=True)
    assert "add manually" in capsys.readouterr().out
    assert ".mentat/bin" not in rc.read_text()


def test_setup_path_no_tty_prints_manual_hint(path_setup, monkeypatch, tmp_path, capsys):
    rc = tmp_path / ".zshrc"
    rc.write_text("# empty\n")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(path_setup, "_SHELL_RC", {"zsh": rc})
    monkeypatch.setattr(path_setup, "open_tty", lambda: _yield(None))
    path_setup.setup_path(yes=False)
    assert "add manually" in capsys.readouterr().out


def test_setup_path_writes_export_line_when_confirmed(path_setup, monkeypatch, tmp_path):
    rc = tmp_path / ".zshrc"
    rc.write_text("# empty\n")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(path_setup, "_SHELL_RC", {"zsh": rc})
    monkeypatch.setattr(path_setup, "open_tty", lambda: _yield(FakeTTY("y\n")))
    path_setup.setup_path(yes=False)
    body = rc.read_text()
    assert 'export PATH="$HOME/.mentat/bin:$PATH"' in body
    assert "added by mentat-install" in body


def test_setup_path_declined_leaves_rc_untouched(path_setup, monkeypatch, tmp_path, capsys):
    rc = tmp_path / ".zshrc"
    rc.write_text("# empty\n")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(path_setup, "_SHELL_RC", {"zsh": rc})
    monkeypatch.setattr(path_setup, "open_tty", lambda: _yield(FakeTTY("n\n")))
    path_setup.setup_path(yes=False)
    assert "PATH not updated" in capsys.readouterr().out
    assert ".mentat/bin" not in rc.read_text()


def test_setup_path_fish_uses_fish_add_path(path_setup, monkeypatch, tmp_path):
    rc = tmp_path / "config.fish"
    rc.write_text("# empty\n")
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    monkeypatch.setattr(path_setup, "_SHELL_RC", {"fish": rc})
    monkeypatch.setattr(path_setup, "open_tty", lambda: _yield(FakeTTY("y\n")))
    path_setup.setup_path(yes=False)
    assert "fish_add_path $HOME/.mentat/bin" in rc.read_text()


# ── tui.py direct ─────────────────────────────────────────────────────────────


def test_paint_frame_is_coherent():
    tui = load_script(TUI_PY, "tui_paint")
    frame = tui.paint(["alpha", "beta"], rows=4)
    assert frame.startswith(tui.SYNC_BEGIN + tui.HOME)
    assert frame.endswith(tui.SYNC_END)
    # Two content lines + two erased trailing rows.
    assert frame.count(tui.CLEAR_EOL) == 4
