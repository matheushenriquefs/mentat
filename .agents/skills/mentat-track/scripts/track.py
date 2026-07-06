#!/usr/bin/env python3
"""mentat-track — track / list / doctor / diagnose."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import store as _store
from lib.loader import load_sibling  # noqa: E402
from lib.agent import agent_dir as _agent_dir_fn  # noqa: E402
from lib.agent import log_root as _log_root  # noqa: E402
from lib.agent import repo_name as _repo
from lib.agent import resolve_agent_dir as _resolve_agent_dir

_registry = load_sibling(__file__, "registry")
_render = load_sibling(__file__, "render")
_panes = load_sibling(__file__, "panes")
_agent = load_sibling(__file__, "agent")
_diagnose = load_sibling(__file__, "diagnose")


_humanize_age = _registry._humanize_age


def cmd_track(agent_id: str | None, all_agents: bool = False) -> int:
    repo = _repo()
    repo_dir = _log_root() / repo
    if agent_id is None:
        return _panes.navigate(repo_dir, repo=repo, active_only=not all_agents)
    agent = _store.get_agent(agent_id)
    if agent is None:
        print(f"mentat-track: agent not found: {agent_id}", file=sys.stderr)
        return 1
    ad = _resolve_agent_dir(agent_id) or _agent_dir_fn(agent_id)
    ad.mkdir(parents=True, exist_ok=True)
    _render.view_agent(ad)
    return 0


def cmd_doctor(agent_id: str | None) -> int:
    ad = _agent._resolve_agent(agent_id)
    if isinstance(ad, int):
        return ad
    print(_diagnose.build_verdict(ad))
    return 0


def cmd_report(agent_id: str | None) -> int:
    """Render the success-side report-back summary. Operator sees what an AFK
    agent implemented without asking the main harness."""
    ad = _agent._resolve_agent(agent_id)
    if isinstance(ad, int):
        return ad
    summary = _diagnose.write_summary(ad)
    print(summary.read_text())
    return 0


# Age humanizer lives in the registry lib so cmd_list and the navigator share one
# impl; re-exported here under the name test_track.py and cmd_list reach for.
_humanize_age = _registry._humanize_age


# ASCII status markers (no emoji — shares the tui.py vocabulary).
_STATUS_MARK = {"waiting": "◆", "idle": "✓", "?": "?", "working": "•"}


def cmd_list(all_agents: bool = False) -> int:
    """Repo-wide agent registry from the canonical store."""
    repo = _repo()
    rows = _store.list_track_entries(repo, active_only=not all_agents)
    if not rows:
        print(f"mentat-track: no agents for {repo}")
        return 0
    width = max(len(r["agent"]) for r in rows)
    for r in rows:
        mark = _STATUS_MARK.get(r["status"], "?")
        last = r["last_event"] or "-"
        print(f"{mark} {r['status']:<8} {r['agent']:<{width}}  {_humanize_age(r['age']):>9}  {last}")
    return 0


def cmd_diagnose(agent_id: str | None) -> int:
    ad = _agent._resolve_agent(agent_id)
    if isinstance(ad, int):
        return ad
    _diagnose.run_diagnose(ad)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-track")
    sub = p.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list", help="Repo-wide agent registry (attention-ordered)")
    list_p.add_argument("--all", dest="all_agents", action="store_true", default=False, help="Show all agents")

    track_p = sub.add_parser("track", help="Stream live events")
    track_p.add_argument("agent", nargs="?", default=None)
    track_p.add_argument("--all", dest="all_agents", action="store_true", default=False, help="Show all agents")

    doctor_p = sub.add_parser("doctor", help="Build verdict markdown")
    doctor_p.add_argument("agent", nargs="?", default=None)

    report_p = sub.add_parser("report", help="Render the success-side report-back summary")
    report_p.add_argument("agent", nargs="?", default=None)

    diag_p = sub.add_parser("diagnose", help="Doctor-first diagnose loop")
    diag_p.add_argument("agent", nargs="?", default=None)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    agent = getattr(args, "agent", None)
    all_agents = getattr(args, "all_agents", False)
    dispatch = {
        "list": lambda: cmd_list(all_agents),
        "track": lambda: cmd_track(agent, all_agents),
        "doctor": lambda: cmd_doctor(agent),
        "report": lambda: cmd_report(agent),
        "diagnose": lambda: cmd_diagnose(agent),
    }
    sys.exit(dispatch[args.cmd]())


if __name__ == "__main__":
    main()
