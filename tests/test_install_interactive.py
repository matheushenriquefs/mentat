"""D14 — questionnaire UX: companion iteration, subprocess gating, no-TTY auto-skip."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

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


def test_yes_skips_all_companions_without_subprocess() -> None:
    companions = _load("companions")
    with patch.object(companions.subprocess, "run") as mock_run:
        rc = companions.install_all(yes=True)
    assert rc == 0
    assert mock_run.call_count == 0


def test_no_tty_auto_skips() -> None:
    companions = _load("companions")
    with patch.object(companions.sys.stdin, "isatty", return_value=False):
        with patch.object(companions.subprocess, "run") as mock_run:
            rc = companions.install_all(yes=False)
    assert rc == 0
    assert mock_run.call_count == 0


def test_companions_list_shape() -> None:
    companions = _load("companions")
    names = [c["name"] for c in companions.COMPANIONS]
    assert "matt-pocock-skills" in names
    assert "juliusbrussee-caveman" in names
    for c in companions.COMPANIONS:
        assert c["docs"].startswith("https://")
        assert isinstance(c["install_cmd"], list) and len(c["install_cmd"]) > 0


def test_spinner_context_manager_safe_in_non_tty(capsys: pytest.CaptureFixture[str]) -> None:
    companions = _load("companions")
    with patch.object(companions.sys.stdout, "isatty", return_value=False):
        with companions._Spinner("test label"):
            pass
    # Non-TTY: spinner thread shouldn't have started → no spinner output to clear.


class _FakeTTY:
    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)

    def readline(self) -> str:
        return next(self._responses, "") + "\n"


def test_install_one_no_to_first_prompt_runs_command() -> None:
    companions = _load("companions")
    fake_companion = {
        "name": "test-companion",
        "docs": "https://example.com",
        "install_cmd": ["echo", "hello"],
    }
    # User answers "no" to "have you installed?" (n), "" to edit-cmd (default), "y" to confirm-run
    tty = _FakeTTY(["n", "", "y"])
    with patch.object(companions.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        companions.install_one(fake_companion, yes=False, tty=tty)
    assert mock_run.call_count == 1
    args = mock_run.call_args
    assert args.args[0] == ["echo", "hello"]


def test_install_one_yes_to_first_prompt_skips_subprocess() -> None:
    companions = _load("companions")
    fake_companion = {
        "name": "test-companion",
        "docs": "https://example.com",
        "install_cmd": ["echo", "hello"],
    }
    tty = _FakeTTY(["y"])
    with patch.object(companions.subprocess, "run") as mock_run:
        companions.install_one(fake_companion, yes=False, tty=tty)
    assert mock_run.call_count == 0
