#!/usr/bin/env python3
"""mentat-implement — atomic single-plan executor."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parents[2]
_LOG_SCRIPT = _SKILL_ROOT / ".agents/skills/mentat-log/scripts/log.py"
_GATES_CODE = _SKILL_ROOT / ".agents/lib/gates/code"


def _load_sibling(name: str):
    here = Path(__file__).parent
    key = f"{here.parent.name}.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, here / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_utils = _load_sibling("utils")


# ── public helpers (patchable in tests) ─────────────────────────────────────


def _plans_dir() -> Path:
    return Path.home() / ".agents" / "plans"


def read_tests_manifest(slug: str) -> tuple[list[str], list[str]]:
    """Return (closed, open) from ~/.agents/plans/<slug>.tests.json. Returns ([], []) if absent."""
    manifest = _plans_dir() / f"{slug}.tests.json"
    if not manifest.exists():
        return [], []
    data = json.loads(manifest.read_text())
    return data.get("closed", []), data.get("open", [])


def compute_ro_mounts(closed: list[str], open_: list[str]) -> list[str]:
    """Paths that must be mounted read-only = closed minus open."""
    open_set = set(open_)
    return [p for p in closed if p not in open_set]


def mark_test_writable(slug: str, path: str) -> None:
    """Move path from closed to open in the tests manifest. Emits test.writable.requested."""
    manifest = _plans_dir() / f"{slug}.tests.json"
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
    _emit_event("test.writable.requested", {"slug": slug, "path": path})


def resolve_plan_path(ref: str) -> Path:
    if "/" in ref or ref.endswith(".md"):
        return Path(ref).expanduser().resolve()
    return Path.home() / ".agents" / "plans" / f"{ref}.md"


def parse_frontmatter(plan_path: Path) -> dict[str, str]:
    text = plan_path.read_text()
    fm: dict[str, str] = {}
    in_fm = False
    for line in text.splitlines():
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            else:
                break
        if in_fm:
            m = re.match(r"^(\w+):\s*(.+)$", line)
            if m:
                fm[m.group(1)] = m.group(2).strip()
    return fm


def _emit_event(event: str, payload: dict) -> None:
    subprocess.run(
        ["python3", str(_LOG_SCRIPT), "emit", "mentat-implement", event, __import__("json").dumps(payload)],
        capture_output=True,
    )


def _invoke_harness(harness: str, prompt: str, *, afk: bool, model: str | None = None) -> Any:
    harness_dir = _SCRIPTS / "harness"
    adapter_name = harness.replace("-", "_")
    adapter_path = harness_dir / f"{adapter_name}.py"
    if not adapter_path.exists():
        adapter_path = harness_dir / "claude_code.py"
    spec = importlib.util.spec_from_file_location(adapter_name, adapter_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.invoke(prompt, afk=afk, model=model)


def _detect_self_answer(result: Any) -> bool:
    session_log = getattr(result, "session_log", None)
    if session_log is None:
        return False
    return _utils.detect_self_answer(Path(session_log))


def _run_gates(chunk_path: Path | None) -> tuple[str, str]:
    """Run deterministic code gates. Returns (verdict, message)."""
    if not _GATES_CODE.exists():
        return ("pass", "")
    for gate_file in sorted(_GATES_CODE.glob("*.py")):
        if gate_file.stem == "__init__":
            continue
        spec = importlib.util.spec_from_file_location(gate_file.stem, gate_file)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        if hasattr(mod, "run"):
            verdict, message = mod.run(chunk_path)
            if verdict == "block":
                return ("block", message)
    return ("pass", "")


def run_plan(plan_path: Path, *, harness: str | None = None, model: str | None = None) -> int:
    if not harness:
        harness = _utils.default_harness()

    fm = parse_frontmatter(plan_path)
    plan_class = fm.get("class", "HITL")
    afk = plan_class == "AFK"

    # Inject read-only test mounts before container-up (ADR-0010)
    slug = plan_path.stem
    closed, open_ = read_tests_manifest(slug)
    ro = compute_ro_mounts(closed, open_)
    if ro:
        os.environ["MENTAT_RO_MOUNTS"] = json.dumps(ro)

    plan_body = plan_path.read_text()
    result = _invoke_harness(harness, plan_body, afk=afk, model=model)

    if result.returncode != 0:
        slug = plan_path.stem
        _emit_event(
            "chunk.ejected",
            {
                "slug": slug,
                "reason": "implement-failed",
                "where": str(plan_path.parent),
            },
        )
        return 1

    if afk and _detect_self_answer(result):
        slug = plan_path.stem
        _emit_event(
            "chunk.ejected",
            {
                "slug": slug,
                "reason": "hitl-required",
                "where": str(plan_path.parent),
            },
        )
        return 42

    verdict, message = _run_gates(None)
    if verdict == "block":
        slug = plan_path.stem
        _emit_event(
            "chunk.ejected",
            {
                "slug": slug,
                "reason": "gate-failed",
                "where": str(plan_path.parent),
            },
        )
        return 1

    return 0


def main() -> None:
    # Support both: `mentat-implement <plan>` and `mentat-implement run <plan>`
    argv = sys.argv[1:]
    if argv and argv[0] == "mark-test-writable":
        if len(argv) < 3:
            print("usage: mentat-implement mark-test-writable <slug> <path>", file=sys.stderr)
            sys.exit(64)
        mark_test_writable(slug=argv[1], path=argv[2])
        sys.exit(0)

    parser = argparse.ArgumentParser(prog="mentat-implement", description="Atomic plan executor")
    parser.add_argument("plan_refs", nargs="+", metavar="plan-ref")
    parser.add_argument("--harness", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)

    if len(args.plan_refs) > 1:
        print(
            "mentat-implement: accepts one plan at a time. Use mentat-orchestrate for multi-plan runs.",
            file=sys.stderr,
        )
        sys.exit(1)

    plan_path = resolve_plan_path(args.plan_refs[0])
    if not plan_path.exists():
        print(f"mentat-implement: plan not found: {plan_path}", file=sys.stderr)
        sys.exit(1)

    sys.exit(run_plan(plan_path, harness=args.harness, model=args.model))


if __name__ == "__main__":
    main()
