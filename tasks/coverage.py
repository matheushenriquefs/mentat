"""coverage: branch-coverage runner — human report + machine-readable JSON.

Usage:
    python tasks/coverage.py [--source=<sources>] [pytest-args...]

Default sources: .agents/lib,.agents/skills,tasks
Outputs:
    stdout  — coverage report --show-missing
    cwd     — coverage.json  (totals.percent_covered consumed by health runner)
"""

from __future__ import annotations

import subprocess
import sys

DEFAULT_SOURCES = ".agents/lib,.agents/skills,tasks"


def run(sources: str = DEFAULT_SOURCES, pytest_args: list[str] | None = None) -> int:
    args = pytest_args or []
    steps: list[list[str]] = [
        [sys.executable, "-m", "coverage", "run", "--branch", f"--source={sources}", "-m", "pytest", *args],
        [sys.executable, "-m", "coverage", "report", "--show-missing"],
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
    remaining: list[str] = []
    for arg in raw:
        if arg.startswith("--source="):
            sources = arg[len("--source=") :]
        else:
            remaining.append(arg)
    sys.exit(run(sources=sources, pytest_args=remaining))


if __name__ == "__main__":
    main()
