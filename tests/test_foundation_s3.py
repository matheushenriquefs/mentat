"""S3: drift-lint gate + filterwarnings=error."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / ".agents"

sys_path_inserted = False


def _drift():
    import sys

    sys.path.insert(0, str(AGENTS))
    from lib.gates import drift_lint

    return drift_lint


def _engine():
    import sys

    sys.path.insert(0, str(AGENTS))
    from lib.gates import engine

    return engine


def test_drift_lint_blocks_stale_event_token(tmp_path: Path) -> None:
    drift = _drift()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale.md").write_text("Emit `chunk_spawned` after fan-out.\n")
    verdict, msg = drift.run(tmp_path)
    assert verdict == "block"
    assert "chunk_spawned" in msg


def test_drift_lint_blocks_dotted_event_token(tmp_path: Path) -> None:
    drift = _drift()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "dotted.md").write_text("Never emit chunk.started at the boundary.\n")
    verdict, msg = drift.run(tmp_path)
    assert verdict == "block"
    assert "chunk.started" in msg


def test_drift_lint_blocks_resurrected_wire_term_in_runtime(tmp_path: Path) -> None:
    drift = _drift()
    lib = tmp_path / ".agents" / "lib"
    lib.mkdir(parents=True)
    wire = "ses" + "sion"
    (lib / "bad.py").write_text(f'TERM = "{wire}"\n')
    verdict, msg = drift.run(tmp_path)
    assert verdict == "block"
    assert "bad.py" in msg


def test_engine_wires_drift_lint_gate() -> None:
    engine = _engine()
    ids = [g.id for g in engine._GATES]
    assert ids[0] == "drift_lint"


def test_filterwarnings_is_error(pytestconfig: pytest.Config) -> None:
    ini = pytestconfig.getini("filterwarnings")
    assert "error" in ini


def test_uncaught_warning_fails() -> None:
    with pytest.raises(Warning):
        warnings.warn("foundation s3 intentional warning", UserWarning, stacklevel=1)
