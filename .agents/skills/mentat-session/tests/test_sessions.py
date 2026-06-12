"""Tests for sessions.py mentat-manual-* filter."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import sessions


def _make_dirs(tmp_path: Path, names: list[str]) -> Path:
    for name in names:
        (tmp_path / name).mkdir()
    return tmp_path


def test_latest_session_excludes_mentat_manual(tmp_path):
    _make_dirs(tmp_path, ["mentat-manual-123-456", "real-session"])
    result = sessions.latest_session(tmp_path)
    assert result == "real-session"


def test_sessions_for_repo_excludes_mentat_manual(tmp_path):
    _make_dirs(tmp_path, ["mentat-manual-123-456", "real-session"])
    result = sessions.sessions_for_repo(tmp_path)
    assert result == ["real-session"]


def test_returns_none_when_only_manual_present(tmp_path):
    _make_dirs(tmp_path, ["mentat-manual-111-222", "mentat-manual-333-444"])
    assert sessions.latest_session(tmp_path) is None


def test_latest_session_returns_most_recent(tmp_path):
    import time
    a = tmp_path / "session-a"
    a.mkdir()
    time.sleep(0.01)
    b = tmp_path / "session-b"
    b.mkdir()
    assert sessions.latest_session(tmp_path) == "session-b"
