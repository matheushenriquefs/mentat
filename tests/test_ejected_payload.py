"""S4 — one chunk.ejected payload shape; orchestrate stays thin.

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
_DECLARED_OPTIONAL = {"logs_path", "preflight_exit", "upstream"}


def test_builder_base_shape() -> None:
    p = events.ejected_payload("my-slug", "gate-failed", "/w")
    assert p == {"slug": "my-slug", "reason": "gate-failed", "where": "/w"}


def test_builder_includes_optionals_only_when_set() -> None:
    p = events.ejected_payload("s", "implement-failed", "/w", logs_path="/logs", preflight_exit=66)
    assert p == {
        "slug": "s",
        "reason": "implement-failed",
        "where": "/w",
        "logs_path": "/logs",
        "preflight_exit": 66,
    }
    assert "upstream" not in p


def test_builder_emits_no_undeclared_keys() -> None:
    p = events.ejected_payload("s", "r", "/w", logs_path="/l", preflight_exit=1, upstream="u")
    assert set(p) <= (_BASE | _DECLARED_OPTIONAL)


def test_catalog_declares_optional_fields() -> None:
    sys.path.insert(0, str(SKILLS / "mentat-log/scripts"))
    import log

    assert set(log.EVENT_OPTIONAL_FIELDS["chunk.ejected"]) == _DECLARED_OPTIONAL


def test_ejection_sites_use_shared_builder() -> None:
    for rel in (
        "mentat-implement/scripts/implement.py",
        "mentat-orchestrate/scripts/land_queue.py",
    ):
        text = (SKILLS / rel).read_text()
        assert "ejected_payload" in text, f"{rel} does not use the shared ejected_payload builder"


def test_lifecycle_emit_sites_present() -> None:
    assert "chunk.landed" in (SKILLS / "mentat-orchestrate/scripts/land_queue.py").read_text()
    assert "chunk.spawned" in (SKILLS / "mentat-orchestrate/scripts/fan_out.py").read_text()
