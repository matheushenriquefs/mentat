"""Drift lint: prose event references and retired wire-term token. Stdlib only."""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import cast

_AGENTS_ROOT = Path(__file__).resolve().parents[2]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.gates._walk import SKIP_DIRS as _SKIP_DIRS  # noqa: E402

_EVENT_TOKEN = re.compile(r"\b(?:slice|agent|chunk|gate|review|batch|task|test)_[a-z][a-z0-9_]*\b")
_DOTTED_EVENT = re.compile(r"\b[a-z][a-z0-9_]*\.[a-z][a-z0-9_]+\b")
_BACKTICK_TOKEN = re.compile(r"`([^`]+)`")
_WIRE_TERM_RE = re.compile(r"\b" + "ses" + "sion" + r"s?\b", re.IGNORECASE)
_MENTAT_WIRE_RE = re.compile("MENTAT_" + "SES" + "SION")
_PROSE_SKIP_PARTS = frozenset({".git", "node_modules", ".venv", "__pycache__"})
_SELF = Path(__file__).resolve()
_EVENT_SUFFIXES = (
    "_scheduled",
    "_blocked",
    "_skipped",
    "_started",
    "_stopped",
    "_reaped",
    "_landed",
    "_ejected",
    "_teardown",
    "_evaluated",
    "_submitted",
    "_reviewed",
    "_created",
    "_claimed",
    "_released",
    "_resolved",
    "_canceled",
    "_requested",
)
_DOTTED_STEMS = frozenset(
    {
        "chunk",
        "slice",
        "agent",
        "task",
        "gate",
        "review",
        "batch",
        "ses" + "sion",
        "scheduler",
        "plan",
    }
)
_EVENT_VERBS = frozenset(
    {
        "started",
        "stopped",
        "landed",
        "ejected",
        "scheduled",
        "blocked",
        "skipped",
        "evaluated",
        "submitted",
        "reviewed",
        "created",
        "claimed",
        "released",
        "resolved",
        "canceled",
        "prune",
        "teardown",
        "reaped",
    }
)
_DOMAIN_IDENTIFIERS = frozenset(
    {
        "agent_id",
        "chunk_id",
        "chunk_slug",
        "chunk_path",
        "slice_id",
        "agent_log_dir",
        "gate_type",
        "gate_pass",
        "gate_failed",
        "chunk_timeout",
        "test_asserts_plan",
        "test_coverage_runner",
    }
)


def _load_catalog() -> frozenset[str]:
    log_path = _AGENTS_ROOT / "skills" / "mentat-log" / "scripts" / "log.py"
    spec = importlib.util.spec_from_file_location("mentat_log_drift", log_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load EVENT_CATALOG from {log_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    catalog = getattr(mod, "EVENT_CATALOG", None)
    if not isinstance(catalog, dict):
        raise RuntimeError("EVENT_CATALOG missing from mentat-log")
    return frozenset(str(k) for k in cast("dict[str, object]", catalog))


def _iter_prose(root: Path) -> Iterator[Path]:
    candidates = [
        root / "CONTEXT.md",
        root / "README.md",
        root / "AGENTS.md",
        root / "docs",
        root / ".agents",
    ]
    for base in candidates:
        if not base.exists():
            continue
        if base.is_file():
            yield base
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".md", ".mdc"}:
                continue
            if any(part in _PROSE_SKIP_PARTS for part in path.parts):
                continue
            yield path


def _iter_runtime_py(root: Path) -> Iterator[Path]:
    for base in (root / ".agents" / "lib", root / ".agents" / "skills"):
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            yield path


def _has_event_suffix(token: str) -> bool:
    return any(token.endswith(suffix) for suffix in _EVENT_SUFFIXES)


def _is_module_reference(text: str, start: int, token: str) -> bool:
    tail = text[start : start + len(token) + 4]
    return tail.startswith(f"{token}.py")


def _is_stale_event_reference(token: str, *, catalog: frozenset[str]) -> bool:
    if token in catalog or token in _DOMAIN_IDENTIFIERS:
        return False
    if not _EVENT_TOKEN.fullmatch(token):
        return False
    if token.startswith("test_") and token.count("_") < 2:
        return False
    stem = token.split("_", 1)[0]
    if stem not in _DOTTED_STEMS:
        return False
    return _has_event_suffix(token) or stem in {"chunk", "slice", "agent", "batch", "gate", "review", "task"}


def _is_dotted_event_reference(token: str) -> bool:
    if "." not in token:
        return False
    if token.endswith((".md", ".py", ".toml", ".json", ".jsonc", ".jsonl")):
        return False
    left, _, right = token.partition(".")
    if left in {"docs", "adr", "skills", "agents", "lib", "tests", "evals"}:
        return False
    if right.endswith("_id"):
        return False
    if right in _EVENT_VERBS:
        return True
    return left in _DOTTED_STEMS and right in _EVENT_VERBS


def lint_prose(root: Path) -> list[str]:
    """Return drift errors for event tokens in prose."""
    catalog = _load_catalog()
    errors: list[str] = []
    for path in _iter_prose(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(root) if path.is_relative_to(root) else path
        seen: set[str] = set()
        for match in _DOTTED_EVENT.finditer(text):
            token = match.group(0)
            if token in seen:
                continue
            if _is_dotted_event_reference(token):
                seen.add(token)
                errors.append(f"{rel}: dotted event token {token!r}")
        for match in _EVENT_TOKEN.finditer(text):
            token = match.group(0)
            if token in seen:
                continue
            if _is_module_reference(text, match.start(), token):
                continue
            if _is_stale_event_reference(token, catalog=catalog):
                seen.add(token)
                errors.append(f"{rel}: unknown event token {token!r}")
        for match in _BACKTICK_TOKEN.finditer(text):
            raw = match.group(1).strip()
            if not raw or " " in raw:
                continue
            token = raw
            if token in seen:
                continue
            if _is_dotted_event_reference(token):
                seen.add(token)
                errors.append(f"{rel}: dotted event token {token!r}")
                continue
            if _is_stale_event_reference(token, catalog=catalog):
                seen.add(token)
                errors.append(f"{rel}: unknown event token {token!r}")
    return errors


def lint_runtime_retired_term(root: Path) -> list[str]:
    """Return drift errors for resurrected retired wire-term token in runtime Python."""
    errors: list[str] = []
    for path in _iter_runtime_py(root):
        if path.resolve() == _SELF:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(root) if path.is_relative_to(root) else path
        if _WIRE_TERM_RE.search(text):
            errors.append(f"{rel}: retired wire-term token in runtime")
        if _MENTAT_WIRE_RE.search(text):
            errors.append(f"{rel}: MENTAT_" + "SES" + "SION in runtime")
    return errors


def run(chunk_path: Path | None) -> tuple[str, str]:
    """Gate entry: block on prose event drift or retired wire-term resurrection."""
    if chunk_path is None:
        return ("block", "drift_lint gate: no chunk path")
    if not chunk_path.exists():
        return ("block", f"drift_lint gate: chunk path missing: {chunk_path}")

    root = chunk_path if chunk_path.is_dir() else chunk_path.parent
    errors = [*lint_prose(root), *lint_runtime_retired_term(root)]
    if errors:
        return ("block", "\n".join(errors))
    return ("pass", "")


class _DriftLintGate:
    id = "drift_lint"
    priority = 5

    def run(self, ctx: object) -> tuple[str, str]:
        chunk_path = getattr(ctx, "chunk_path", None)
        return run(chunk_path)


gate = _DriftLintGate()
