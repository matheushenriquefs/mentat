"""mutation: advisory mutmut runner scoped to the diff's shipped-source files.

Mutation testing is advisory (ADR-0016): a mutant that survives on a changed line
means a test executed that line but asserted nothing the mutation broke — the gap
line coverage cannot see. It NEVER gates (mutation is expensive and only partly
deterministic; Just et al. FSE 2014 validate it for test hardening, not as a
code-gen gate).

Usage:
    python tasks/mutation.py [--changed] [--base=<ref>]

`--changed` restricts mutation to shipped-source files touched since <base>
(default `main`). The shipped-source set is read from `[tool.coverage.run] source`
in pyproject.toml, so the surface the coverage gate omits is excluded here too.
Test order is pinned and per-mutant timeouts are bounded via `[tool.mutmut]` in
pyproject.toml. Output is a compact `file:line` list of surviving mutants, or a
clean marker.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "main"
TEST_PREFIX = "tests/"
CLASS_NAME_SEPARATOR = "ǁ"  # mutmut's method-key separator (ǁ)
_SURVIVOR_RE = re.compile(r"^\s*(?P<key>\S+):\s*survived\s*$")
_MUTANT_SUFFIX_RE = re.compile(r"__mutmut_\d+$")


def coverage_source_prefixes(pyproject_text: str) -> tuple[str, ...]:
    """Read the shipped-source dirs from `[tool.coverage.run] source`.

    Each is normalised to a directory prefix (trailing slash) so a changed file
    path can be tested with `str.startswith`. The coverage gate's source list is
    the single source of truth for what "shipped runtime" means, so mutation and
    coverage agree on the exempt surface.
    """
    data = tomllib.loads(pyproject_text)
    sources = data.get("tool", {}).get("coverage", {}).get("run", {}).get("source", [])
    return tuple(f"{s.rstrip('/')}/" for s in sources)


def select_targets(changed: list[str], prefixes: tuple[str, ...]) -> list[str]:
    """Keep the changed `.py` files under a shipped-source prefix, dropping tests.

    Returns a sorted, de-duplicated list — stable across two runs on one diff.
    """
    kept = {
        path
        for path in changed
        if path.endswith(".py") and not path.startswith(TEST_PREFIX) and any(path.startswith(p) for p in prefixes)
    }
    return sorted(kept)


def module_of(path: str) -> str:
    """The dotted module name mutmut derives from a source file path."""
    stem = path[: -len(".py")] if path.endswith(".py") else path
    module = stem.replace("/", ".")
    return module.removeprefix("src.")


def mutant_patterns(targets: list[str]) -> list[str]:
    """fnmatch patterns that select every mutant belonging to the target files."""
    return [f"{module_of(t)}.*" for t in targets]


def survivor_keys(results_text: str) -> list[str]:
    """Parse `mutmut results` output into the keys of surviving mutants."""
    keys = [m.group("key") for line in results_text.splitlines() if (m := _SURVIVOR_RE.match(line))]
    return sorted(set(keys))


def _func_name(mangled: str) -> str:
    """Recover the source function name from a mutmut mangled method name."""
    if CLASS_NAME_SEPARATOR in mangled:
        return mangled.split(CLASS_NAME_SEPARATOR)[-1]
    return mangled.removeprefix("x_")


def _def_line(func_name: str, lines: list[str]) -> int:
    """1-based line of `def func_name`, or 0 if not found."""
    pattern = re.compile(rf"^\s*(?:async\s+)?def\s+{re.escape(func_name)}\b")
    for index, line in enumerate(lines, start=1):
        if pattern.match(line):
            return index
    return 0


def key_to_location(key: str, targets: list[str], *, lines_of: Callable[[str], list[str]]) -> str:
    """Map a mutmut mutant key to a `file:line` location on one of the targets.

    Falls back to `file:?` when the def line cannot be resolved, and to the bare
    key when no target module is a prefix of the key.
    """
    for target in targets:
        prefix = f"{module_of(target)}."
        if not key.startswith(prefix):
            continue
        mangled = _MUTANT_SUFFIX_RE.sub("", key[len(prefix) :])
        line = _def_line(_func_name(mangled), lines_of(target))
        return f"{target}:{line}" if line else f"{target}:?"
    return key


def locate_survivors(keys: list[str], targets: list[str], *, lines_of: Callable[[str], list[str]]) -> list[str]:
    """Map surviving-mutant keys to a sorted, de-duplicated `file:line` list."""
    return sorted({key_to_location(key, targets, lines_of=lines_of) for key in keys})


def format_report(locations: list[str]) -> str:
    """A compact human report of surviving mutants (advisory)."""
    if not locations:
        return "mutation: no surviving mutants on changed files"
    body = "\n".join(f"  {loc}" for loc in locations)
    return f"mutation: {len(locations)} surviving mutant(s) on changed files (advisory)\n{body}"


def changed_files(base: str) -> list[str]:
    """Files changed since `base` (three-dot: since the merge-base)."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _run_mutmut(patterns: list[str]) -> None:
    subprocess.run([sys.executable, "-m", "mutmut", "run", *patterns], cwd=ROOT)


def _mutmut_results() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "mutmut", "results"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return result.stdout


def _lines_of(path: str) -> list[str]:
    return (ROOT / path).read_text(encoding="utf-8").splitlines()


def run(*, changed_only: bool, base: str) -> int:
    prefixes = coverage_source_prefixes((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    changed = changed_files(base) if changed_only else []
    targets = select_targets(changed, prefixes) if changed_only else []
    if changed_only and not targets:
        print("mutation: no changed shipped-source files — nothing to mutate")
        return 0
    _run_mutmut(mutant_patterns(targets))
    keys = survivor_keys(_mutmut_results())
    locations = locate_survivors(keys, targets, lines_of=_lines_of)
    print(format_report(locations))
    return 0


def main() -> None:
    changed_only = False
    base = DEFAULT_BASE
    for arg in sys.argv[1:]:
        if arg == "--changed":
            changed_only = True
        elif arg.startswith("--base="):
            base = arg[len("--base=") :]
    sys.exit(run(changed_only=changed_only, base=base))


if __name__ == "__main__":
    main()
