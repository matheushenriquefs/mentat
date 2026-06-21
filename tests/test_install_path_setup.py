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
