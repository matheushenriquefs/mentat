"""Deterministic smell detector.

Walks Python sources under chunk_path with the stdlib `ast` module.
Advisory only (never blocks): findings surface in the gate.evaluated
audit row so reviewers can flag what ruff misses.

LLM-only smells (Feature Envy, Shotgun Surgery, etc.) live in
mentat-smell-reviewer; this module catches the mechanical ones.

Tunables:
- SMELL_LONG_METHOD_LINES (default 30)
- SMELL_LONG_PARAMS_COUNT (default 5)
- SMELL_NESTED_DEPTH (default 4)
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

_WALK_DIR = Path(__file__).resolve().parents[1]
_AGENTS_ROOT = _WALK_DIR.parents[1]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.gates._walk import SKIP_DIRS as _SKIP_DIRS  # noqa: E402


def _limit(env_var: str, default: int) -> int:
    raw = os.environ.get(env_var)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _long_method(tree: ast.AST, path: Path, limit: int) -> list[str]:
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_lineno = getattr(node, "end_lineno", node.lineno)
            length = end_lineno - node.lineno + 1
            if length > limit:
                findings.append(
                    f"{path}:{node.lineno}: long-method: `{node.name}` is {length} lines "
                    f"(limit {limit}). Extract helpers."
                )
    return findings


def _long_params(tree: ast.AST, path: Path, limit: int) -> list[str]:
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            count = (
                len(args.posonlyargs)
                + len(args.args)
                + len(args.kwonlyargs)
                + (1 if args.vararg else 0)
                + (1 if args.kwarg else 0)
            )
            if count > limit:
                findings.append(
                    f"{path}:{node.lineno}: long-params: `{node.name}` has {count} parameters "
                    f"(limit {limit}). Introduce parameter object."
                )
    return findings


def _nested_conditional(tree: ast.AST, path: Path, limit: int) -> list[str]:
    """Walk control-flow nesting depth per function. Report first crossing."""
    findings: list[str] = []
    blockers = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)

    def descend(node: ast.AST, depth: int, fn_name: str) -> None:
        if depth >= limit:
            findings.append(
                f"{path}:{getattr(node, 'lineno', 0)}: nested-conditional: depth {depth} "
                f"in `{fn_name}` (limit {limit}). Flatten or extract."
            )
            return
        for child in ast.iter_child_nodes(node):
            next_depth = depth + 1 if isinstance(child, blockers) else depth
            descend(child, next_depth, fn_name)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            descend(node, 0, node.name)
    return findings


def _iter_py(root: Path):
    for p in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        yield p


class _SmellsGate:
    id = "smells"
    priority = 20

    def run(self, ctx: object) -> tuple[str, str]:
        chunk_path = getattr(ctx, "chunk_path", None)
        return run(chunk_path)


gate = _SmellsGate()


def run(chunk_path: Path | None) -> tuple[str, str]:
    """Return (verdict, message). Verdict is 'advise' or 'pass' — never blocks."""
    if chunk_path is None or not chunk_path.exists():
        return ("pass", "")

    root = chunk_path if chunk_path.is_dir() else chunk_path.parent
    long_method_limit = _limit("SMELL_LONG_METHOD_LINES", 30)
    long_params_limit = _limit("SMELL_LONG_PARAMS_COUNT", 5)
    nested_limit = _limit("SMELL_NESTED_DEPTH", 4)

    findings: list[str] = []
    for path in _iter_py(root):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except (SyntaxError, OSError):
            continue
        findings += _long_method(tree, path, long_method_limit)
        findings += _long_params(tree, path, long_params_limit)
        findings += _nested_conditional(tree, path, nested_limit)

    if findings:
        return ("advise", "\n".join(findings))
    return ("pass", "")
