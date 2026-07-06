"""E2E: the mentat-track CLI wiring — parser, dispatch, and thin helpers.

Loads the real skill script ``.agents/skills/mentat-track/scripts/track.py``
via ``load_script`` (which runs its sys.path bootstrap + ``from lib.agent ...``
+ ``load_sibling`` of agents/doctor/track/diagnose at import). Targets the CLI
seams that the report/registry journeys don't exercise: ``_agent_dir`` path
arithmetic, ``build_parser`` / ``build_bare_parser`` namespace shape, ``main``'s
dispatch table (each lambda + arg threading) via patched ``cmd_*`` recorders over
a monkeypatched ``sys.argv``, and ``cmd_diagnose``'s success + error-code arms
with ``_resolve_agent`` / ``_diagnose.run_diagnose`` stubbed. The cmd_* bodies
that drive track's real TUI are covered elsewhere.
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


# ── _agent_dir ─────────────────────────────────────────────────────────────


def test_agent_dir_composes_log_root_repo_and_id(monkeypatch, tmp_path):
    agent = load_script(REPO_ROOT / ".agents/skills/mentat-track/scripts/agent.py", "e2e_agent")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    got = agent._agent_dir("myrepo", "sess-9")
    assert got == tmp_path / "logs" / "myrepo" / "sess-9"


# ── build_parser ─────────────────────────────────────────────────────────────


def test_build_parser_list_defaults_all_false():
    ns = track_cli.build_parser().parse_args(["list"])
    assert ns.cmd == "list"
    assert ns.all_agents is False


def test_build_parser_list_all_flag_sets_all_true():
    ns = track_cli.build_parser().parse_args(["list", "--all"])
    assert ns.all_agents is True


def test_build_bare_parser_captures_agent_positional():
    ns = track_cli.build_bare_parser().parse_args(["sess-1"])
    assert ns.agent == "sess-1"


def test_build_bare_parser_agent_defaults_none():
    ns = track_cli.build_bare_parser().parse_args([])
    assert ns.agent is None


def test_build_bare_parser_all_flag_sets_all_true():
    ns = track_cli.build_bare_parser().parse_args(["--all"])
    assert ns.all_agents is True


def test_build_parser_doctor_captures_session():
    ns = track_cli.build_parser().parse_args(["doctor", "s"])
    assert ns.cmd == "doctor"
    assert ns.agent == "s"


def test_build_parser_report_captures_session():
    ns = track_cli.build_parser().parse_args(["report", "s"])
    assert ns.cmd == "report"
    assert ns.agent == "s"


def test_build_parser_diagnose_captures_session():
    ns = track_cli.build_parser().parse_args(["diagnose", "s"])
    assert ns.cmd == "diagnose"
    assert ns.agent == "s"


def test_build_parser_requires_a_subcommand():
    with pytest.raises(SystemExit):
        track_cli.build_parser().parse_args([])


# ── main dispatch ────────────────────────────────────────────────────────────


def test_main_dispatches_list_and_exits_with_its_code(monkeypatch):
    monkeypatch.setattr(track_cli, "cmd_list", lambda _all: 7)
    monkeypatch.setattr(sys, "argv", ["agent", "list"])
    with pytest.raises(SystemExit) as exc:
        track_cli.main()
    assert exc.value.code == 7


def test_main_dispatches_bare_track_and_threads_session_and_all(monkeypatch):
    captured = {}

    def _fake_track(agent, all_agents=False):
        captured["args"] = (agent, all_agents)
        return 3

    monkeypatch.setattr(track_cli, "cmd_track", _fake_track)
    monkeypatch.setattr(sys, "argv", ["agent", "abc", "--all"])
    with pytest.raises(SystemExit) as exc:
        track_cli.main()
    assert exc.value.code == 3
    assert captured["args"] == ("abc", True)


def test_main_dispatches_bare_track_with_no_args(monkeypatch):
    captured = {}

    def _fake_track(agent, all_agents=False):
        captured["args"] = (agent, all_agents)
        return 0

    monkeypatch.setattr(track_cli, "cmd_track", _fake_track)
    monkeypatch.setattr(sys, "argv", ["agent"])
    with pytest.raises(SystemExit):
        track_cli.main()
    assert captured["args"] == (None, False)


def test_main_dispatches_doctor_and_exits_with_its_code(monkeypatch):
    monkeypatch.setattr(track_cli, "cmd_doctor", lambda _s: 5)
    monkeypatch.setattr(sys, "argv", ["agent", "doctor", "s"])
    with pytest.raises(SystemExit) as exc:
        track_cli.main()
    assert exc.value.code == 5


def test_main_dispatches_report_and_exits_with_its_code(monkeypatch):
    monkeypatch.setattr(track_cli, "cmd_report", lambda _s: 4)
    monkeypatch.setattr(sys, "argv", ["agent", "report", "s"])
    with pytest.raises(SystemExit) as exc:
        track_cli.main()
    assert exc.value.code == 4


def test_main_dispatches_diagnose_and_exits_with_its_code(monkeypatch):
    monkeypatch.setattr(track_cli, "cmd_diagnose", lambda _s: 6)
    monkeypatch.setattr(sys, "argv", ["agent", "diagnose", "s"])
    with pytest.raises(SystemExit) as exc:
        track_cli.main()
    assert exc.value.code == 6


# ── cmd_diagnose ─────────────────────────────────────────────────────────────


def test_cmd_diagnose_runs_diagnose_on_resolved_dir(monkeypatch, tmp_path):
    sd = tmp_path / "agent-dir"
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
