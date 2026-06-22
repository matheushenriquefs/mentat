"""path_setup: shell detection and rc-file routing."""

from __future__ import annotations

import contextlib
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "mentat-install" / "scripts"


def _load(name: str):
    key = f"_mentat_install_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, _SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeTTY:
    def readline(self) -> str:
        return "y\n"


def test_fish_shell_writes_fish_config_not_bashrc(tmp_path, monkeypatch) -> None:
    """$SHELL=fish → fish_add_path in config.fish; ~/.bashrc not written."""
    path_setup = _load("path_setup")

    fish_rc = tmp_path / ".config" / "fish" / "config.fish"
    fish_rc.parent.mkdir(parents=True)
    bash_rc = tmp_path / ".bashrc"
    patched_rc = {
        "zsh": tmp_path / ".zshrc",
        "bash": bash_rc,
        "fish": fish_rc,
    }

    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    monkeypatch.setenv("PATH", "/usr/bin")

    @contextlib.contextmanager
    def _fake_tty():
        yield _FakeTTY()

    with (
        patch.object(path_setup, "_MENTAT_BIN", tmp_path / ".mentat" / "bin"),
        patch.object(path_setup, "_SHELL_RC", patched_rc),
        patch.object(path_setup, "open_tty", _fake_tty),
        patch.object(path_setup, "prompt_yn", return_value=True),
        patch.object(path_setup, "print_step"),
    ):
        path_setup.setup_path(yes=False)

    assert fish_rc.exists(), "fish config.fish must be written"
    content = fish_rc.read_text()
    assert "fish_add_path" in content
    assert "export PATH" not in content
    assert not bash_rc.exists(), "~/.bashrc must NOT be written for fish shell"


def test_unknown_shell_skips_with_manual_instructions(tmp_path, monkeypatch) -> None:
    """$SHELL=ksh (unsupported) → no file written, manual-add message printed."""
    path_setup = _load("path_setup")

    bash_rc = tmp_path / ".bashrc"
    patched_rc = {
        "zsh": tmp_path / ".zshrc",
        "bash": bash_rc,
        "fish": tmp_path / ".config" / "fish" / "config.fish",
    }

    monkeypatch.setenv("SHELL", "/usr/bin/ksh")
    monkeypatch.setenv("PATH", "/usr/bin")

    printed: list[tuple] = []

    with (
        patch.object(path_setup, "_MENTAT_BIN", tmp_path / ".mentat" / "bin"),
        patch.object(path_setup, "_SHELL_RC", patched_rc),
        patch.object(path_setup, "print_step", side_effect=lambda *a, **kw: printed.append(a)),
    ):
        path_setup.setup_path(yes=False)

    assert not bash_rc.exists(), "~/.bashrc must not be written for unsupported shell"
    assert printed, "expected print_step to be called"
    all_text = " ".join(str(s) for step in printed for s in step)
    assert "manually" in all_text, "expected manual-add instructions in output"


def test_setup_path_already_in_path_skips(tmp_path, monkeypatch) -> None:
    """PATH already contains ~/.mentat/bin → print skip immediately."""
    path_setup = _load("path_setup")
    mentat_bin = tmp_path / ".mentat" / "bin"
    mentat_bin.mkdir(parents=True)
    monkeypatch.setenv("PATH", str(mentat_bin) + ":/usr/bin")

    printed: list[tuple] = []
    with (
        patch.object(path_setup, "_MENTAT_BIN", mentat_bin),
        patch.object(path_setup, "print_step", side_effect=lambda *a, **kw: printed.append(a)),
    ):
        path_setup.setup_path(yes=False)

    assert printed
    all_text = " ".join(str(s) for step in printed for s in step)
    assert "already" in all_text


def test_setup_path_rc_already_has_mentat_skips(tmp_path, monkeypatch) -> None:
    """rc file already contains .mentat/bin → skip without writing."""
    path_setup = _load("path_setup")
    mentat_bin = tmp_path / ".mentat" / "bin"
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text('export PATH="$HOME/.mentat/bin:$PATH"\n')
    patched_rc = {"zsh": zshrc, "bash": tmp_path / ".bashrc", "fish": tmp_path / ".config/fish/config.fish"}

    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("PATH", "/usr/bin")

    printed: list[tuple] = []
    with (
        patch.object(path_setup, "_MENTAT_BIN", mentat_bin),
        patch.object(path_setup, "_SHELL_RC", patched_rc),
        patch.object(path_setup, "print_step", side_effect=lambda *a, **kw: printed.append(a)),
    ):
        path_setup.setup_path(yes=False)

    assert printed
    all_text = " ".join(str(s) for step in printed for s in step)
    assert "already" in all_text
    assert not (tmp_path / ".bashrc").exists()


def test_setup_path_yes_prints_manual_when_not_in_rc(tmp_path, monkeypatch) -> None:
    """yes=True + not yet in rc → print manual instructions, do not write rc."""
    path_setup = _load("path_setup")
    mentat_bin = tmp_path / ".mentat" / "bin"
    zshrc = tmp_path / ".zshrc"
    patched_rc = {"zsh": zshrc, "bash": tmp_path / ".bashrc", "fish": tmp_path / ".config/fish/config.fish"}

    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("PATH", "/usr/bin")

    printed: list[tuple] = []
    with (
        patch.object(path_setup, "_MENTAT_BIN", mentat_bin),
        patch.object(path_setup, "_SHELL_RC", patched_rc),
        patch.object(path_setup, "print_step", side_effect=lambda *a, **kw: printed.append(a)),
    ):
        path_setup.setup_path(yes=True)

    assert not zshrc.exists(), "rc must not be written when --yes"
    assert printed


def test_setup_path_tty_none_prints_manual(tmp_path, monkeypatch) -> None:
    """open_tty yields None → print manual instructions, do not write rc."""
    import contextlib

    path_setup = _load("path_setup")
    mentat_bin = tmp_path / ".mentat" / "bin"
    zshrc = tmp_path / ".zshrc"
    patched_rc = {"zsh": zshrc, "bash": tmp_path / ".bashrc", "fish": tmp_path / ".config/fish/config.fish"}

    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("PATH", "/usr/bin")

    @contextlib.contextmanager
    def _no_tty():
        yield None

    printed: list[tuple] = []
    with (
        patch.object(path_setup, "_MENTAT_BIN", mentat_bin),
        patch.object(path_setup, "_SHELL_RC", patched_rc),
        patch.object(path_setup, "open_tty", _no_tty),
        patch.object(path_setup, "print_step", side_effect=lambda *a, **kw: printed.append(a)),
    ):
        path_setup.setup_path(yes=False)

    assert not zshrc.exists()
    assert printed


def test_setup_path_user_declines_skips(tmp_path, monkeypatch) -> None:
    """prompt_yn returns False → PATH not updated."""
    import contextlib

    path_setup = _load("path_setup")
    mentat_bin = tmp_path / ".mentat" / "bin"
    zshrc = tmp_path / ".zshrc"
    patched_rc = {"zsh": zshrc, "bash": tmp_path / ".bashrc", "fish": tmp_path / ".config/fish/config.fish"}

    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("PATH", "/usr/bin")

    @contextlib.contextmanager
    def _fake_tty():
        yield object()

    printed: list[tuple] = []
    with (
        patch.object(path_setup, "_MENTAT_BIN", mentat_bin),
        patch.object(path_setup, "_SHELL_RC", patched_rc),
        patch.object(path_setup, "open_tty", _fake_tty),
        patch.object(path_setup, "prompt_yn", return_value=False),
        patch.object(path_setup, "print_step", side_effect=lambda *a, **kw: printed.append(a)),
    ):
        path_setup.setup_path(yes=False)

    assert not zshrc.exists()
    assert printed
    all_text = " ".join(str(s) for step in printed for s in step)
    assert "manually" in all_text or "skip" in all_text.lower() or "not updated" in all_text
