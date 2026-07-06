"""E2E: the mentat-track CLI wiring — parser, dispatch, and thin helpers.

Loads the real skill script ``.agents/skills/mentat-track/scripts/track.py``
via ``load_script`` (which runs its sys.path bootstrap + ``from lib.session ...``
+ ``load_sibling`` of sessions/doctor/track/diagnose at import). Targets the CLI
seams that the report/registry journeys don't exercise: ``_session_dir`` path
arithmetic, ``build_parser`` subcommand/namespace shape (including the required
subparser), ``main``'s dispatch table (each lambda + arg threading) via patched
``cmd_*`` recorders over a monkeypatched ``sys.argv``, and ``cmd_diagnose``'s
success + error-code arms with ``_resolve_agent`` / ``_diagnose.run_diagnose``
stubbed. The cmd_* bodies that drive track's real TUI are covered elsewhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACK_CLI_PY = REPO_ROOT / ".agents/skills/mentat-track/scripts/track.py"

track_cli = load_script(TRACK_CLI_PY, "track_cli")


# ── _session_dir ─────────────────────────────────────────────────────────────


def test_agent_dir_composes_log_root_repo_and_id(monkeypatch, tmp_path):
    agent = load_script(REPO_ROOT / ".agents/skills/mentat-track/scripts/agent.py", "e2e_agent")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    got = agent._agent_dir("myrepo", "sess-9")
    assert got == tmp_path / "logs" / "myrepo" / "sess-9"


# ── build_parser ─────────────────────────────────────────────────────────────


def test_build_parser_list_defaults_all_false():
    ns = track_cli.build_parser().parse_args(["list"])
    assert ns.cmd == "list"
    assert ns.all_sessions is False


def test_build_parser_list_all_flag_sets_all_true():
    ns = track_cli.build_parser().parse_args(["list", "--all"])
    assert ns.all_sessions is True


def test_build_parser_track_captures_session_positional():
    ns = track_cli.build_parser().parse_args(["track", "sess-1"])
    assert ns.cmd == "track"
    assert ns.session == "sess-1"


def test_build_parser_track_session_defaults_none():
    ns = track_cli.build_parser().parse_args(["track"])
    assert ns.session is None


def test_build_parser_track_all_flag_sets_all_true():
    ns = track_cli.build_parser().parse_args(["track", "--all"])
    assert ns.all_sessions is True


def test_build_parser_doctor_captures_session():
    ns = track_cli.build_parser().parse_args(["doctor", "s"])
    assert ns.cmd == "doctor"
    assert ns.session == "s"


def test_build_parser_report_captures_session():
    ns = track_cli.build_parser().parse_args(["report", "s"])
    assert ns.cmd == "report"
    assert ns.session == "s"


def test_build_parser_diagnose_captures_session():
    ns = track_cli.build_parser().parse_args(["diagnose", "s"])
    assert ns.cmd == "diagnose"
    assert ns.session == "s"


def test_build_parser_requires_a_subcommand():
    with pytest.raises(SystemExit):
        track_cli.build_parser().parse_args([])


# ── main dispatch ────────────────────────────────────────────────────────────


def test_main_dispatches_list_and_exits_with_its_code(monkeypatch):
    monkeypatch.setattr(track_cli, "cmd_list", lambda _all: 7)
    monkeypatch.setattr(sys, "argv", ["session", "list"])
    with pytest.raises(SystemExit) as exc:
        track_cli.main()
    assert exc.value.code == 7


def test_main_dispatches_track_and_threads_session_and_all(monkeypatch):
    captured = {}

    def _fake_track(session, all_sessions=False):
        captured["args"] = (session, all_sessions)
        return 3

    monkeypatch.setattr(track_cli, "cmd_track", _fake_track)
    monkeypatch.setattr(sys, "argv", ["session", "track", "abc", "--all"])
    with pytest.raises(SystemExit) as exc:
        track_cli.main()
    assert exc.value.code == 3
    assert captured["args"] == ("abc", True)


def test_main_dispatches_doctor_and_exits_with_its_code(monkeypatch):
    monkeypatch.setattr(track_cli, "cmd_doctor", lambda _s: 5)
    monkeypatch.setattr(sys, "argv", ["session", "doctor", "s"])
    with pytest.raises(SystemExit) as exc:
        track_cli.main()
    assert exc.value.code == 5


def test_main_dispatches_report_and_exits_with_its_code(monkeypatch):
    monkeypatch.setattr(track_cli, "cmd_report", lambda _s: 4)
    monkeypatch.setattr(sys, "argv", ["session", "report", "s"])
    with pytest.raises(SystemExit) as exc:
        track_cli.main()
    assert exc.value.code == 4


def test_main_dispatches_diagnose_and_exits_with_its_code(monkeypatch):
    monkeypatch.setattr(track_cli, "cmd_diagnose", lambda _s: 6)
    monkeypatch.setattr(sys, "argv", ["session", "diagnose", "s"])
    with pytest.raises(SystemExit) as exc:
        track_cli.main()
    assert exc.value.code == 6


# ── cmd_diagnose ─────────────────────────────────────────────────────────────


def test_cmd_diagnose_runs_diagnose_on_resolved_dir(monkeypatch, tmp_path):
    sd = tmp_path / "session-dir"
    sd.mkdir()
    monkeypatch.setattr(track_cli._agent, "_resolve_agent", lambda _s: sd)

    seen = {}
    monkeypatch.setattr(track_cli._diagnose, "run_diagnose", lambda d: seen.setdefault("dir", d))

    assert track_cli.cmd_diagnose("some-id") == 0
    assert seen["dir"] == sd


def test_cmd_diagnose_returns_resolve_error_code(monkeypatch):
    # _resolve_agent returned an int (error) → passed straight through.
    monkeypatch.setattr(track_cli._agent, "_resolve_agent", lambda _s: 1)
    assert track_cli.cmd_diagnose("missing") == 1
