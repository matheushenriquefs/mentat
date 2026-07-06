"""S4 — one chunk_ejected payload shape; orchestrate stays thin.

Every ejection (implement-failed, hitl-required, preflight-worktree-failed,
rebase-conflicted, gate-failed, not-ff, upstream-ejected) emits the same base
shape {slug, reason, where} via one shared builder. logs_path, preflight_exit
and upstream are optional payload extensions, declared in the catalog — not a
new event type (the 9-event catalog is unchanged).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / ".agents/skills"
sys.path.insert(0, str(REPO_ROOT / ".agents"))
from lib import events  # noqa: E402

_BASE = {"slug", "reason", "where"}
_DECLARED_OPTIONAL = {"logs_path", "preflight_exit", "upstream", "summary", "killed_by", "timed_out"}


def test_builder_base_shape() -> None:
    p = events.ejected_payload("my-slug", "gate_failed", "/w")
    assert p == {"slug": "my-slug", "reason": "gate_failed", "where": "/w"}


def test_builder_includes_optionals_only_when_set() -> None:
    p = events.ejected_payload("s", "implement_failed", "/w", logs_path="/logs", preflight_exit=66)
    assert p == {
        "slug": "s",
        "reason": "implement_failed",
        "where": "/w",
        "logs_path": "/logs",
        "preflight_exit": 66,
    }
    assert "upstream" not in p


def test_builder_emits_no_undeclared_keys() -> None:
    p = events.ejected_payload("s", "r", "/w", logs_path="/l", preflight_exit=1, upstream="u", summary="blocked")
    assert set(p) <= (_BASE | _DECLARED_OPTIONAL)


def test_builder_includes_summary_only_when_set() -> None:
    assert "summary" not in events.ejected_payload("s", "gate_failed", "/w")
    p = events.ejected_payload("s", "hitl_required", "/w", summary="OAuth or SAML?")
    assert p["summary"] == "OAuth or SAML?"


def test_builder_includes_timed_out_and_killed_by_only_when_set() -> None:
    assert "timed_out" not in events.ejected_payload("s", "worker_died", "/w")
    assert "killed_by" not in events.ejected_payload("s", "worker_died", "/w")
    p = events.ejected_payload("s", "worker_died", "/w", timed_out=True, killed_by="container-down")
    assert p["timed_out"] is True
    assert p["killed_by"] == "container-down"


def test_transient_reasons_are_environment_failures() -> None:
    """Transient reasons are retryable environment failures; gate/hitl/implement are terminal."""
    for transient in (
        events.WORKER_DIED,
        events.NOT_FF,
        events.PREFLIGHT_WORKTREE_FAILED,
        events.CONTAINER_OOM,
    ):
        assert events.is_transient_eject(transient), f"{transient} must be transient"
    for terminal in (
        events.GATE_FAILED,
        events.HITL_REQUIRED,
        events.IMPLEMENT_FAILED,
        events.MAIN_TREE_REFUSED,
        events.GIT_ERROR,
        events.REBASE_CONFLICTED,
        events.UPSTREAM_EJECTED,
    ):
        assert not events.is_transient_eject(terminal), f"{terminal} must be terminal"


def test_transient_set_is_subset_of_all_reasons() -> None:
    assert events.TRANSIENT_EJECT_REASONS <= events.EJECT_REASONS


def test_catalog_declares_optional_fields() -> None:
    sys.path.insert(0, str(SKILLS / "mentat-log/scripts"))
    import log

    assert set(log.EVENT_OPTIONAL_FIELDS["chunk_ejected"]) == _DECLARED_OPTIONAL


def test_ejection_sites_use_shared_builder() -> None:
    for rel in (
        "mentat-implement/scripts/implement.py",
        "mentat-orchestrate/scripts/landing.py",
    ):
        text = (SKILLS / rel).read_text()
        assert "ejected_payload" in text, f"{rel} does not use the shared ejected_payload builder"


def test_lifecycle_emit_sites_present() -> None:
    assert "chunk_landed" in (SKILLS / "mentat-orchestrate/scripts/landing.py").read_text()
    assert "chunk_started" in (SKILLS / "mentat-orchestrate/scripts/spawn.py").read_text()
