"""coverage: branch-coverage runner — human report + machine-readable JSON.

Usage:
    python tasks/coverage.py [--source=<sources>] [--fail-under=<n>] [pytest-args...]

Default sources: .agents/lib,.agents/skills (shipped runtime; dev tooling in tasks/ is out of the gate)
`--fail-under=<n>` sets the floor for this run. Each gate passes its own value
(unit 100, e2e journey floor) — pyproject sets no shared default, so the two
passes never collide over one config value.
Outputs:
    stdout  — coverage report --show-missing
    cwd     — coverage.json  (machine-readable totals + per-file missing branches)
"""

from __future__ import annotations

import subprocess
import sys

DEFAULT_SOURCES = ".agents/lib,.agents/skills"


def run(sources: str = DEFAULT_SOURCES, pytest_args: list[str] | None = None, *, fail_under: int | None = None) -> int:
    args = pytest_args or []
    report_cmd = [sys.executable, "-m", "coverage", "report", "--show-missing"]
    if fail_under is not None:
        report_cmd.append(f"--fail-under={fail_under}")
    steps: list[list[str]] = [
        [sys.executable, "-m", "coverage", "run", "--branch", f"--source={sources}", "-m", "pytest", *args],
        report_cmd,
        [sys.executable, "-m", "coverage", "json"],
    ]
    for cmd in steps:
        result = subprocess.run(cmd)
        if result.returncode != 0:
            return result.returncode
    return 0


def main() -> None:
    raw = sys.argv[1:]
    sources = DEFAULT_SOURCES
    fail_under: int | None = None
    remaining: list[str] = []
    for arg in raw:
        if arg.startswith("--source="):
            sources = arg[len("--source=") :]
        elif arg.startswith("--fail-under="):
            fail_under = int(arg[len("--fail-under=") :])
        else:
            remaining.append(arg)
    sys.exit(run(sources=sources, pytest_args=remaining, fail_under=fail_under))


if __name__ == "__main__":
    main()
