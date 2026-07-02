"""E2E: mentat-implement's harness helpers over real config + session logs.

Drives ``.agents/skills/mentat-implement/scripts/harness_utils.py`` end to end:
``default_harness`` resolves through the REAL layered ``lib.config.read_config``
(a real ``~/.mentat/config.toml`` on tmp_path, resolved via a redirected
``Path.home`` and a non-repo cwd so no repo layer applies), and
``detect_self_answer`` scans REAL NDJSON session-log files through the real
``lib.harness_stream`` wire-shape parser. No mocking of the module under test.

The script does a ``sys.path`` bootstrap and ``from lib import ...`` at import
time; ``load_script`` runs that bootstrap fine (the conftest already puts
``.agents`` on ``sys.path``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_UTILS_PY = REPO_ROOT / ".agents/skills/mentat-implement/scripts/harness_utils.py"


@pytest.fixture
def harness_utils():
    return load_script(HARNESS_UTILS_PY, "harness_utils")


# ── default_harness ──────────────────────────────────────────────────────────
# read_config reads ~/.mentat/config.toml (global) + repo .mentat (repo wins).
# We redirect config.Path.home into tmp and chdir to a non-repo dir so only the
# global tmp layer contributes.


def _isolate_config(monkeypatch, home: Path, cwd: Path) -> None:
    from lib import config

    home.mkdir(parents=True, exist_ok=True)
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(cwd)


def test_default_harness_reads_configured_harness(harness_utils, tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    mentat_dir = home / ".mentat"
    mentat_dir.mkdir(parents=True)
    (mentat_dir / "config.toml").write_text('harness = "cursor"\n')
    _isolate_config(monkeypatch, home, tmp_path / "loose")
    assert harness_utils.default_harness() == "cursor"


def test_default_harness_defaults_when_no_config(harness_utils, tmp_path: Path, monkeypatch):
    # No ~/.mentat/config.toml and cwd is not a git repo → read_config() == {}.
    _isolate_config(monkeypatch, tmp_path / "home", tmp_path / "loose")
    assert harness_utils.default_harness() == "claude-code"


# ── detect_self_answer ───────────────────────────────────────────────────────


def test_detect_self_answer_false_for_none(harness_utils):
    assert harness_utils.detect_self_answer(None) is False


def test_detect_self_answer_false_for_missing_path(harness_utils, tmp_path: Path):
    assert harness_utils.detect_self_answer(tmp_path / "no-such.ndjson") is False


def test_detect_self_answer_true_on_ask_user_question_row(harness_utils, tmp_path: Path):
    log = tmp_path / "session.ndjson"
    log.write_text('{"type":"assistant","message":{"content":[{"type":"tool_use","name":"AskUserQuestion"}]}}\n')
    assert harness_utils.detect_self_answer(log) is True


def test_detect_self_answer_false_when_no_ask_and_malformed_line_skipped(harness_utils, tmp_path: Path):
    log = tmp_path / "session.ndjson"
    log.write_text(
        '{"type":"assistant","message":{"content":['
        '{"type":"tool_use","name":"Bash"}]}}\n'
        "\n"  # blank line → continue
        "{not valid json\n"  # JSONDecodeError → continue
    )
    assert harness_utils.detect_self_answer(log) is False
