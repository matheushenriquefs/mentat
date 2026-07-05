"""E2E: the canonical session-id + log-path library over a real git + tmp env.

Drives ``.agents/lib/session.py`` (imported as ``from lib import session`` via the
root conftest's ``.agents`` sys.path entry) through every function and branch:
id minting (explicit + default pid), the ``log_root`` env seam, the private
``_repo_root`` common-dir resolver over a REAL git repo and its failure arms
(non-repo cwd, ``OSError``, empty stdout, relative common dir), ``repo_name``'s
env/repo/cwd cascade, ``session_dir`` slug sanitisation, the canonical filenames,
and ``ensure_session``'s mint-and-export plus its idempotent preserve path. Real
subprocess git, real tmp dirs, ``monkeypatch`` for env + cwd — the module under
test is never mocked except where a branch is only reachable by injecting a fake
``subprocess.run`` (OSError / empty-stdout arms).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from lib import session

from tests.conftest import init_git_repo

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── make_agent_id ─────────────────────────────────────────────────────────────


def test_make_agent_id_is_opaque_uuid7():
    import re

    sid = session.make_agent_id("implement", "my-plan", pid=123)
    assert re.fullmatch(r"[0-9a-f]{12}7[0-9a-f]{3}[89ab][0-9a-f]{15}", sid), f"expected uuid7, got {sid!r}"
    assert "implement" not in sid and "my-plan" not in sid


def test_make_agent_id_is_unique_per_call():
    assert session.make_agent_id("orchestrate", "hold") != session.make_agent_id("orchestrate", "hold")


def test_current_branch_inside_real_repo(monkeypatch, tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    init_git_repo(repo, initial_branch="trunk")
    monkeypatch.chdir(repo)
    assert session.current_branch() == "trunk"


def test_current_branch_outside_repo_returns_none(monkeypatch, tmp_path):
    outside = tmp_path / "bare"
    outside.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(outside)
    assert session.current_branch() is None


# ── log_root ─────────────────────────────────────────────────────────────────


def test_log_root_honors_mentat_log_path(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "custom-logs"))
    assert session.log_root() == tmp_path / "custom-logs"


def test_log_root_defaults_to_home_mentat_logs(monkeypatch):
    monkeypatch.delenv("MENTAT_LOG_PATH", raising=False)
    root = session.log_root()
    assert root.parts[-2:] == (".mentat", "logs")


# ── _repo_root ───────────────────────────────────────────────────────────────


def test_repo_root_inside_real_repo_returns_root(monkeypatch, tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    init_git_repo(repo)
    monkeypatch.chdir(repo)
    # resolve-compare: macOS reports /var vs /private/var.
    assert session._repo_root() == repo.resolve()


def test_repo_root_outside_any_repo_returns_none(monkeypatch, tmp_path):
    # GIT_CEILING stops the upward walk so rev-parse fails (rc != 0) → None.
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(outside)
    assert session._repo_root() is None


def test_repo_root_returns_none_when_git_binary_missing(monkeypatch):
    # OSError arm (git not found / not executable) → None.
    def _boom(*_a, **_k):
        raise OSError("no git")

    monkeypatch.setattr(session.subprocess, "run", _boom)
    assert session._repo_root() is None


def test_repo_root_returns_none_on_empty_stdout(monkeypatch):
    # returncode 0 but blank stdout → None (the `not raw` guard).
    class _Result:
        returncode = 0
        stdout = ""

    monkeypatch.setattr(session.subprocess, "run", lambda *_a, **_k: _Result())
    assert session._repo_root() is None


def test_repo_root_resolves_relative_common_dir_to_absolute(monkeypatch, tmp_path):
    # A real repo yields a RELATIVE `.git` common dir from cwd; the resolver must
    # still return an absolute repo root (the `not common.is_absolute()` arm).
    repo = tmp_path / "rel"
    repo.mkdir()
    init_git_repo(repo)
    monkeypatch.chdir(repo)

    root = session._repo_root()
    assert root == repo.resolve()
    assert root.is_absolute()


# ── repo_name ────────────────────────────────────────────────────────────────


def test_repo_name_honors_mentat_repo_env(monkeypatch):
    monkeypatch.setenv("MENTAT_REPO", "frozen-name")
    assert session.repo_name() == "frozen-name"


def test_repo_name_uses_repo_basename_inside_repo(monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_REPO", raising=False)
    repo = tmp_path / "coolrepo"
    repo.mkdir()
    init_git_repo(repo)
    monkeypatch.chdir(repo)
    assert session.repo_name() == "coolrepo"


def test_repo_name_falls_back_to_unknown_outside_repo(monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_REPO", raising=False)
    outside = tmp_path / "loosedir"
    outside.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(outside)
    assert session.repo_name() == "unknown"


# ── session_dir + canonical filenames ────────────────────────────────────────


def test_session_dir_sanitizes_slash_in_session_id(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "r")
    sd = session.session_dir("orchestrate/branch-1")
    assert sd == tmp_path / "logs" / "r" / "orchestrate-branch-1"


def test_summary_file_is_summary_md_under_session_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "r")
    assert session.summary_file("s1") == session.session_dir("s1") / "summary.md"


def test_diagnosis_file_is_diagnosis_md_under_session_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "r")
    assert session.diagnosis_file("s1") == session.session_dir("s1") / "diagnosis.md"


def test_session_log_path_is_transcript_jsonl_under_session_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "r")
    assert session.session_log_path("s1") == session.session_dir("s1") / "transcript.jsonl"


# ── ensure_session ───────────────────────────────────────────────────────────


def test_ensure_session_mints_and_exports_from_clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_AGENT_LOG", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)
    monkeypatch.delenv("MENTAT_REPO", raising=False)
    monkeypatch.delenv("MENTAT_SLUG", raising=False)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))

    repo = tmp_path / "workrepo"
    repo.mkdir()
    init_git_repo(repo)
    monkeypatch.chdir(repo)

    sid = session.ensure_session("implement", "the-plan")

    import re

    assert re.fullmatch(r"[0-9a-f]{12}7[0-9a-f]{3}[89ab][0-9a-f]{15}", sid), f"expected uuid7, got {sid!r}"
    assert os.environ["MENTAT_AGENT"] == sid
    assert os.environ["MENTAT_SESSION"] == sid
    assert os.environ["MENTAT_REPO"] == "workrepo"
    assert os.environ["MENTAT_SLUG"] == "the-plan"
    log = Path(os.environ["MENTAT_AGENT_LOG"])
    assert log.name == "transcript.jsonl"
    assert log.parent.is_dir()


def test_ensure_session_preserves_preset_session(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_SESSION", "preexisting-id")
    monkeypatch.setenv("MENTAT_REPO", "frozen")
    monkeypatch.setenv("MENTAT_AGENT_LOG", str(tmp_path / "already.jsonl"))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))

    sid = session.ensure_session("implement", "ignored-slug")

    assert sid == "preexisting-id"
    assert os.environ["MENTAT_AGENT"] == "preexisting-id"
    assert os.environ["MENTAT_SESSION"] == "preexisting-id"


def test_ensure_session_preserves_preset_repo(monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)
    monkeypatch.setenv("MENTAT_REPO", "already-frozen")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))

    repo = tmp_path / "otherrepo"
    repo.mkdir()
    init_git_repo(repo)
    monkeypatch.chdir(repo)

    session.ensure_session("orchestrate", "hold")

    # The pre-set MENTAT_REPO is not overwritten by the repo basename.
    assert os.environ["MENTAT_REPO"] == "already-frozen"


def test_ensure_session_preserves_preset_agent_log(monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_REPO", raising=False)
    preset_log = tmp_path / "pinned" / "transcript.jsonl"
    monkeypatch.setenv("MENTAT_AGENT_LOG", str(preset_log))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))

    repo = tmp_path / "logrepo"
    repo.mkdir()
    init_git_repo(repo)
    monkeypatch.chdir(repo)

    session.ensure_session("implement", "plan")

    # Pre-set log path is preserved; no new dir is minted for it.
    assert os.environ["MENTAT_AGENT_LOG"] == str(preset_log)
    assert os.environ["MENTAT_SESSION_LOG"] == str(preset_log)
    assert not preset_log.parent.exists()
