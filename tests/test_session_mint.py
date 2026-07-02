"""S1 — stable uuid session id; env-less emit impossible.

The id is an opaque ``uuid`` — repo/branch/pid are recorded as *fields*, never
encoded into the id, so a ``/``-branch can't nest a dir, a reused pid can't
collide, and no ``orphan-session-`` fallback is reachable. One helper mints it;
``ensure_session`` exports ``MENTAT_SESSION`` + ``MENTAT_SESSION_LOG`` (and the
``MENTAT_SESSION_{ROLE,SLUG,PID,BRANCH}`` fields) before any harness spawn.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / ".agents/skills"

sys.path.insert(0, str(REPO_ROOT / ".agents"))
from lib import session as session_mod  # noqa: E402

UUID_HEX = re.compile(r"^[0-9a-f]{32}$")


def test_mint_session_is_opaque_uuid() -> None:
    sid = session_mod.mint_session("implement", "my-plan", pid=4242)
    assert UUID_HEX.match(sid), f"expected uuid hex, got {sid!r}"
    # role / slug / pid must not leak into the id — the whole point of the rewrite.
    assert "implement" not in sid
    assert "my-plan" not in sid
    assert "4242" not in sid


def test_mint_session_is_unique_per_call() -> None:
    a = session_mod.mint_session("orchestrate", "batch")
    b = session_mod.mint_session("orchestrate", "batch")
    assert a != b
    assert UUID_HEX.match(a) and UUID_HEX.match(b)


def test_mint_session_slash_slug_stays_flat(tmp_path, monkeypatch) -> None:
    """A '/'-bearing slug (branch) never nests the session dir — the id is a uuid."""
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "demo")
    sid = session_mod.mint_session("implement", "feat/x")
    assert "/" not in sid
    sd = session_mod.session_dir(sid)
    assert sd.parent == tmp_path / "demo"  # one canonical dir, not nested under feat/


def test_ensure_session_exports_env(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)
    for k in ("MENTAT_SESSION_ROLE", "MENTAT_SESSION_SLUG", "MENTAT_SESSION_PID", "MENTAT_SESSION_BRANCH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "demo")
    sid = session_mod.ensure_session("implement", "p")
    assert os.environ["MENTAT_SESSION"] == sid
    assert UUID_HEX.match(sid), f"expected uuid, got {sid!r}"
    log = Path(os.environ["MENTAT_SESSION_LOG"])
    assert log == tmp_path / "demo" / sid / "session.jsonl"
    assert log.parent.is_dir()
    # role/slug/pid frozen as fields for the projection to read at emit time.
    assert os.environ["MENTAT_SESSION_ROLE"] == "implement"
    assert os.environ["MENTAT_SESSION_SLUG"] == "p"
    assert os.environ["MENTAT_SESSION_PID"] == str(os.getpid())


def test_emit_without_session_env_mints_uuid_not_orphan(monkeypatch, tmp_path) -> None:
    """A raw emit with MENTAT_SESSION unset lands in a real uuid dir — never orphan-session-*."""
    log_mod = _load_log()
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "demo")
    monkeypatch.setenv("MENTAT_SLUG", "agent")

    args = argparse_ns(agent="agent", event="plan.started", payload=json.dumps({"path": "p.md"}))
    assert log_mod.cmd_emit(args) == 0

    repo_dir = tmp_path / "demo"
    session_dirs = [d for d in repo_dir.iterdir() if d.is_dir()]
    assert len(session_dirs) == 1
    name = session_dirs[0].name
    assert not name.startswith("orphan-session-"), f"orphan fallback reached: {name!r}"
    assert UUID_HEX.match(name), f"expected uuid session dir, got {name!r}"


def test_ensure_session_records_branch_when_resolvable(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_BRANCH", raising=False)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "demo")
    monkeypatch.setattr(session_mod, "current_branch", lambda: "trunk")
    session_mod.ensure_session("orchestrate", "hold")
    assert os.environ["MENTAT_SESSION_BRANCH"] == "trunk"


def test_ensure_session_skips_branch_when_unresolvable(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_BRANCH", raising=False)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "demo")
    monkeypatch.setattr(session_mod, "current_branch", lambda: None)
    session_mod.ensure_session("orchestrate", "hold")
    assert "MENTAT_SESSION_BRANCH" not in os.environ


def test_current_branch_success(monkeypatch) -> None:
    class _R:
        returncode = 0
        stdout = "main\n"

    monkeypatch.setattr(session_mod.subprocess, "run", lambda *a, **k: _R())
    assert session_mod.current_branch() == "main"


def test_current_branch_nonzero_rc_is_none(monkeypatch) -> None:
    class _R:
        returncode = 128
        stdout = ""

    monkeypatch.setattr(session_mod.subprocess, "run", lambda *a, **k: _R())
    assert session_mod.current_branch() is None


def test_current_branch_empty_stdout_is_none(monkeypatch) -> None:
    class _R:
        returncode = 0
        stdout = "\n"

    monkeypatch.setattr(session_mod.subprocess, "run", lambda *a, **k: _R())
    assert session_mod.current_branch() is None


def test_current_branch_oserror_is_none(monkeypatch) -> None:
    def _boom(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(session_mod.subprocess, "run", _boom)
    assert session_mod.current_branch() is None


def _load_log():
    import importlib.util

    spec = importlib.util.spec_from_file_location("log_s1", SKILLS / "mentat-log/scripts/log.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def argparse_ns(**kw):
    import argparse

    return argparse.Namespace(**kw)


def test_ensure_session_preserves_existing(monkeypatch, tmp_path) -> None:
    """A child inheriting orchestrate's id keeps it — not re-minted."""
    monkeypatch.setenv("MENTAT_SESSION", "orchestrate-batch-9")
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "demo")
    assert session_mod.ensure_session("implement", "p") == "orchestrate-batch-9"


# ── source contract: no legacy formats survive at any session-minting site ──

# Pure session-minting sites. orchestrate.py is covered by the shared-minter
# check below; its residual `mentat-manual-` is a worktree-prune name filter
# (re-keyed to path in S3), not a session-minting literal.
_MINT_SITES = [
    "mentat-log/scripts/log.py",
    "mentat-orchestrate/scripts/fan_out.py",
    "mentat-implement/scripts/implement.py",
]
_FORBIDDEN = {
    "mentat-manual- literal": re.compile(r"mentat-manual-"),
    "auto- session literal": re.compile(r"""["']auto-"""),
    "<epoch> segment": re.compile(r"timestamp\(\)"),
}


@pytest.mark.parametrize("rel", _MINT_SITES)
def test_no_legacy_session_literals(rel: str) -> None:
    text = (SKILLS / rel).read_text()
    bad = [name for name, rx in _FORBIDDEN.items() if rx.search(text)]
    assert bad == [], f"{rel} still carries legacy session formats: {bad}"


@pytest.mark.parametrize(
    "rel",
    [
        "mentat-orchestrate/scripts/fan_out.py",
        "mentat-orchestrate/scripts/orchestrate.py",
        "mentat-implement/scripts/implement.py",
    ],
)
def test_entrypoints_use_shared_minter(rel: str) -> None:
    assert "lib.session" in (SKILLS / rel).read_text(), f"{rel} does not import lib.session"
