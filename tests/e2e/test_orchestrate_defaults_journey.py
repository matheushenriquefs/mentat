"""E2E: regression guard on the shipped AFK concurrency + deadline defaults.

Ground truth (audit log ``mentat/orchestrate-harden-round2``, 2026-06-30): a batch
spawned 3 heavy ``claude`` implement agents concurrently under the default cap of 3;
two of them starved on CPU, blew the 1800s (30 min) wall-clock deadline, and were
reaped ``worker-died`` at the same instant. The failure was resource contention, not
a code bug — so the *values* of these two defaults are load-bearing:

  - concurrency cap = 3  → how many heavy agents share one devcontainer at once.
  - chunk_timeout = 1800 → the per-chunk wall a starved agent must finish inside.

30 min is deliberate and confirmed reasonable; it must not be lowered by accident, and
the cap must not be silently raised (which is what let 3 agents starve). This test
pins both code defaults AND cross-checks that the shipped config templates document the
same cap, so code and docs cannot drift. Changing any of these should be a conscious
edit here, backed by fresh ground truth — not a silent regression.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_PY = REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts/orchestrate.py"
FILESYSTEM_PY = REPO_ROOT / ".agents/skills/mentat-install/scripts/filesystem.py"
INSTALL_PY = REPO_ROOT / ".agents/skills/mentat-install/scripts/install.py"

_DEFAULT_CONCURRENCY = 3
_DEFAULT_CHUNK_TIMEOUT = 1800  # seconds (30 min)


def _orch(monkeypatch):
    orch = load_script(ORCH_PY, "orch_defaults")
    # Empty config → the code fallbacks are what we are pinning.
    monkeypatch.setattr(orch._utils, "read_config", lambda: {})
    monkeypatch.delenv("MENTAT_CHUNK_TIMEOUT", raising=False)
    return orch


def test_default_concurrency_cap_is_three(monkeypatch):
    """Default AFK concurrency is 3 — raising it silently is what starved the
    round2 batch. A change must be a conscious edit here."""
    orch = _orch(monkeypatch)
    monkeypatch.setattr(orch._supervise.os, "cpu_count", lambda: 32)  # headroom above the default → no clamp
    assert orch._supervise._concurrency_cap() == _DEFAULT_CONCURRENCY


def test_default_chunk_timeout_is_1800_seconds(monkeypatch):
    """Default per-chunk deadline is 30 min. Confirmed reasonable; must not drop
    silently, and any increase should be ground-truthed first."""
    orch = _orch(monkeypatch)
    assert orch._supervise._chunk_timeout() == _DEFAULT_CHUNK_TIMEOUT


def test_chunk_timeout_bad_config_falls_back_to_1800(monkeypatch):
    """A malformed ``chunk_timeout`` must degrade to the 30-min default, never 0/None."""
    orch = load_script(ORCH_PY, "orch_defaults_bad")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"chunk_timeout": "not-an-int"})
    monkeypatch.delenv("MENTAT_CHUNK_TIMEOUT", raising=False)
    assert orch._supervise._chunk_timeout() == _DEFAULT_CHUNK_TIMEOUT


def test_global_config_template_documents_matching_cap():
    """The shipped global config template must document the same cap the code
    defaults to, so operators reading the template see the real default."""
    fs = load_script(FILESYSTEM_PY, "fs_defaults")
    assert f"concurrency = {_DEFAULT_CONCURRENCY}" in fs._GLOBAL_CONFIG_TEMPLATE


def test_repo_config_template_documents_matching_cap():
    """The per-repo config template must document the same cap as the code default."""
    install = load_script(INSTALL_PY, "install_defaults")
    assert f"concurrency = {_DEFAULT_CONCURRENCY}" in install._REPO_CONFIG_TEMPLATE
