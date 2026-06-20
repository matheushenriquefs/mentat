"""S1 — one canonical session-id std, minted + propagated on every path.

Format: ``<role>-<slug>-<pid>``; ``role`` ∈ {implement, orchestrate}. No
``<epoch>`` segment, no ``mentat-manual-`` / ``auto-`` literals. One helper
mints it; ``ensure_session`` exports ``MENTAT_SESSION`` + ``MENTAT_SESSION_LOG``
before any harness spawn so emitted events and ``session.jsonl`` capture are
keyed correctly from the first event.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / ".agents/skills"

sys.path.insert(0, str(REPO_ROOT / ".agents"))
from lib import session as session_mod  # noqa: E402

CANON = re.compile(r"^(implement|orchestrate)-.+-\d+$")


def test_mint_session_canonical_format() -> None:
    sid = session_mod.mint_session("implement", "my-plan", pid=4242)
    assert sid == "implement-my-plan-4242"
    assert CANON.match(sid)


def test_mint_session_defaults_pid_to_getpid() -> None:
    assert session_mod.mint_session("orchestrate", "batch") == f"orchestrate-batch-{os.getpid()}"


def test_ensure_session_exports_env(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "demo")
    sid = session_mod.ensure_session("implement", "p")
    assert os.environ["MENTAT_SESSION"] == sid == f"implement-p-{os.getpid()}"
    log = Path(os.environ["MENTAT_SESSION_LOG"])
    assert log == tmp_path / "demo" / sid / "session.jsonl"
    assert log.parent.is_dir()


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
