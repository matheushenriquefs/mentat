"""Bug-reviewer fix: emit_event must surface non-zero exit to stderr.

Was: subprocess.run with capture_output=True swallowed returncode silently.
Is:  non-zero rc → one stderr line `mentat-{impl,orch}: emit '<event>' failed rc=<n>: <last stderr line>`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import load_script

_ORCH = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"
_IMPL = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts"
_AGENTS_ROOT = Path(__file__).resolve().parents[1] / ".agents"
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))


def _load(path: Path, key: str):
    return load_script(path, key)


def _events_mod():
    import lib.events as _m

    return _m


def test_orchestrate_emit_event_surfaces_failure(capsys):
    utils = _load(_ORCH / "utils.py", "orch_utils")
    fake = MagicMock(returncode=2, stderr="log script crashed\nERROR: bad path\n", stdout="")
    with patch.object(_events_mod().subprocess, "run", return_value=fake):
        utils.emit_event("chunk.spawned", {"slug": "x"})
    err = capsys.readouterr().err
    assert "emit 'chunk.spawned' failed rc=2" in err
    assert "ERROR: bad path" in err


def test_orchestrate_emit_event_silent_on_success(capsys):
    utils = _load(_ORCH / "utils.py", "orch_utils_ok")
    fake = MagicMock(returncode=0, stderr="", stdout="")
    with patch.object(_events_mod().subprocess, "run", return_value=fake):
        utils.emit_event("chunk.spawned", {"slug": "x"})
    assert capsys.readouterr().err == ""


def test_implement_emit_event_surfaces_failure(capsys):
    impl = _load(_IMPL / "implement.py", "impl_emit")
    fake = MagicMock(returncode=1, stderr="permission denied\n", stdout="")
    with patch.object(impl.subprocess, "run", return_value=fake):
        impl._emit_event("chunk.ejected", {"slug": "y"})
    err = capsys.readouterr().err
    assert "emit 'chunk.ejected' failed rc=1" in err
    assert "permission denied" in err


def test_implement_emit_event_silent_on_success(capsys):
    impl = _load(_IMPL / "implement.py", "impl_emit_ok")
    fake = MagicMock(returncode=0, stderr="", stdout="")
    with patch.object(impl.subprocess, "run", return_value=fake):
        impl._emit_event("chunk.ejected", {"slug": "y"})
    assert capsys.readouterr().err == ""
