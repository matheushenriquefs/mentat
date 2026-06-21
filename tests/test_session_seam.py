"""F0: session-log-path seam — all callers resolve to the same dir for a given session id."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / ".agents/lib"
_AGENTS_ROOT = Path(__file__).resolve().parents[1] / ".agents"
_SKILLS = _AGENTS_ROOT / "skills"

# ── helpers ──────────────────────────────────────────────────────────────────


def _load(key: str, path: Path):
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_session():
    return _load("lib.session", _LIB / "session.py")


def _load_fan_out():
    return _load("mentat_orchestrate.fan_out", _SKILLS / "mentat-orchestrate/scripts/fan_out.py")


def _load_log():
    return _load("mentat_log.log", _SKILLS / "mentat-log/scripts/log.py")


def _load_mentat_session_py():
    return _load("mentat_session.session", _SKILLS / "mentat-session/scripts/session.py")


# ── seam existence ────────────────────────────────────────────────────────────


def test_seam_exports_log_root():
    """lib.session must export log_root()."""
    session = _load_session()
    assert callable(getattr(session, "log_root", None)), "lib.session missing log_root()"


def test_seam_exports_repo_name():
    """lib.session must export repo_name()."""
    session = _load_session()
    assert callable(getattr(session, "repo_name", None)), "lib.session missing repo_name()"


def test_seam_exports_session_dir():
    """lib.session must export session_dir(sid)."""
    session = _load_session()
    assert callable(getattr(session, "session_dir", None)), "lib.session missing session_dir()"


def test_seam_exports_summary_file():
    """lib.session must export summary_file(sid)."""
    session = _load_session()
    assert callable(getattr(session, "summary_file", None)), "lib.session missing summary_file()"


def test_seam_exports_diagnosis_file():
    """lib.session must export diagnosis_file(sid)."""
    session = _load_session()
    assert callable(getattr(session, "diagnosis_file", None)), "lib.session missing diagnosis_file()"


# ── seam correctness ──────────────────────────────────────────────────────────


def test_session_dir_uses_env_vars(tmp_path, monkeypatch):
    """session_dir respects MENTAT_LOG_PATH and MENTAT_REPO."""
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    # Force reimport so env is picked up at call time
    if "lib.session" in sys.modules:
        del sys.modules["lib.session"]
    session = _load_session()
    result = session.session_dir("implement-myplan-1234")
    assert result == tmp_path / "myrepo" / "implement-myplan-1234"


def test_summary_file_under_session_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    if "lib.session" in sys.modules:
        del sys.modules["lib.session"]
    session = _load_session()
    sid = "implement-myplan-1234"
    assert session.summary_file(sid) == session.session_dir(sid) / "summary.md"


def test_diagnosis_file_under_session_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    if "lib.session" in sys.modules:
        del sys.modules["lib.session"]
    session = _load_session()
    sid = "implement-myplan-1234"
    assert session.diagnosis_file(sid) == session.session_dir(sid) / "diagnosis.md"


# ── cross-caller convergence ──────────────────────────────────────────────────


def test_all_callers_resolve_same_dir(tmp_path, monkeypatch):
    """The seam and all five callers must produce the same dir for a given session id.

    Callers tested:
      - lib.session.session_dir (the seam itself)
      - fan_out._log_dir_for
      - log.py _session_dir (via _log_root + _repo)
      - mentat-session/session.py _session_dir (via _log_root + _repo)
    implement._logs_path is tested separately below (needs MENTAT_SESSION env).
    """
    base = str(tmp_path)
    repo = "myrepo"
    sid = "implement-myplan-1234"

    monkeypatch.setenv("MENTAT_LOG_PATH", base)
    monkeypatch.setenv("MENTAT_REPO", repo)

    # Clear cached modules to pick up fresh env
    for key in ["lib.session", "mentat_orchestrate.fan_out", "mentat_log.log", "mentat_session.session"]:
        sys.modules.pop(key, None)

    session_mod = _load_session()
    expected = session_mod.session_dir(sid)

    # fan_out._log_dir_for
    fan_out_mod = _load_fan_out()
    assert fan_out_mod._log_dir_for(sid) == expected, "fan_out._log_dir_for diverges from seam"

    # log.py _session_dir (call with same base/repo/session args)
    log_mod = _load_log()
    assert log_mod._session_dir(tmp_path, repo, sid) == expected, "log._session_dir diverges from seam"

    # mentat-session/session.py _session_dir
    mss = _load_mentat_session_py()
    assert mss._session_dir(repo, sid) == expected, "mentat-session/session._session_dir diverges from seam"


def test_session_dir_slash_is_flattened(tmp_path, monkeypatch):
    """session_dir('a/b') must land in ONE flat dir (no nested subdir from the slash)."""
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    sys.modules.pop("lib.session", None)
    session = _load_session()
    result = session.session_dir("orchestrate-branch/guidelines-revamp-81212")
    assert result.parent == tmp_path / "myrepo"
    assert "/" not in result.name
    assert "branch" in result.name and "guidelines" in result.name


def test_implement_logs_path_matches_seam(tmp_path, monkeypatch):
    """implement._logs_path must equal seam.session_dir for the current MENTAT_SESSION."""
    base = str(tmp_path)
    repo = "myrepo"
    sid = "implement-myplan-1234"

    monkeypatch.setenv("MENTAT_LOG_PATH", base)
    monkeypatch.setenv("MENTAT_REPO", repo)
    monkeypatch.setenv("MENTAT_SESSION", sid)

    for key in ["lib.session", "mentat_implement.implement"]:
        sys.modules.pop(key, None)

    session_mod = _load_session()
    expected = session_mod.session_dir(sid)

    impl = _load("mentat_implement.implement", _SKILLS / "mentat-implement/scripts/implement.py")
    assert Path(impl._logs_path()) == expected, "implement._logs_path diverges from seam"
