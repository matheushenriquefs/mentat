"""Read-only test mount manifest for ADR-0010."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path


def plans_dir() -> Path:
    return Path.home() / ".agents" / "plans"


def read_tests_manifest(
    slug: str,
    *,
    plans_dir_fn: Callable[[], Path] | None = None,
) -> tuple[list[str], list[str]]:
    root = plans_dir_fn() if plans_dir_fn is not None else plans_dir()
    manifest = root / f"{slug}.tests.json"
    if not manifest.exists():
        return [], []
    data = json.loads(manifest.read_text())
    return data.get("closed", []), data.get("open", [])


def compute_ro_mounts(closed: list[str], open_: list[str]) -> list[str]:
    open_set = set(open_)
    return [p for p in closed if p not in open_set]


def mark_test_writable(
    slug: str,
    path: str,
    *,
    emit_event: Callable[[str, dict[str, object]], None],
    plans_dir_fn: Callable[[], Path] | None = None,
) -> None:
    root = plans_dir_fn() if plans_dir_fn is not None else plans_dir()
    manifest = root / f"{slug}.tests.json"
    if not manifest.exists():
        print(f"mentat-implement: no manifest for {slug}", file=sys.stderr)
        return
    data = json.loads(manifest.read_text())
    closed: list[str] = data.get("closed", [])
    open_: list[str] = data.get("open", [])
    if path not in closed:
        print(f"mentat-implement: {path} not in closed list for {slug}", file=sys.stderr)
        return
    if path not in open_:
        open_.append(path)
    data["open"] = open_
    manifest.write_text(json.dumps(data, indent=2))
    emit_event("test_writable_requested", {"slug": slug, "path": path})


def apply_ro_mounts(slug: str) -> None:
    """Set MENTAT_RO_MOUNTS from the plan manifest when closed paths remain."""
    import os

    closed, open_ = read_tests_manifest(slug)
    ro = compute_ro_mounts(closed, open_)
    if ro:
        os.environ["MENTAT_RO_MOUNTS"] = json.dumps(ro)
