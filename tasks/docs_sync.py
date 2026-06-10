"""Docs sync: check renamed/deleted files have no stale references in docs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DOCS = ["README.md", "AGENTS.md", "CONTEXT.md", "CREDITS.md"]


def staged_deleted() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-status"],
        capture_output=True,
        text=True,
        check=True,
    )
    deleted: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 1)
        if parts[0].startswith("D") and len(parts) == 2:
            deleted.append(parts[1])
    return deleted


def check(staged: list[str]) -> int:
    fail = 0
    for path_str in staged:
        p = Path(path_str)
        if p.exists():
            continue
        base = p.name
        for doc in DOCS:
            doc_path = Path(doc)
            if not doc_path.exists():
                continue
            text = doc_path.read_text()
            import re

            hits = len(re.findall(rf"\b{re.escape(base)}\b", text))
            if hits > 0:
                print(f"docs-sync: {base!r} removed but still in {doc} ({hits} hit(s))", file=sys.stderr)
                fail = 1
    return fail


def main() -> None:
    staged = sys.argv[1:] if len(sys.argv) > 1 else staged_deleted()
    sys.exit(check(staged))


if __name__ == "__main__":
    main()
