"""Release management: show status or create a git tag."""

from __future__ import annotations

import argparse
import subprocess


def show_status() -> None:
    last = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0"],
        capture_output=True,
        text=True,
    )
    if last.returncode != 0:
        print("No tags found.")
        return
    tag = last.stdout.strip()
    log = subprocess.run(
        ["git", "log", f"{tag}..HEAD", "--oneline"],
        capture_output=True,
        text=True,
        check=True,
    )
    commits = log.stdout.strip().splitlines()
    print(f"Last tag: {tag}")
    print(f"Commits since: {len(commits)}")
    for c in commits:
        print(f"  {c}")


def create_tag(tag: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] would create tag {tag!r}")
        return
    subprocess.run(["git", "tag", tag], check=True)
    subprocess.run(["git", "push", "origin", tag], check=True)
    print(f"Tagged and pushed: {tag}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mentat release management")
    parser.add_argument("--tag", metavar="VERSION", help="Create and push git tag")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.tag:
        create_tag(args.tag, dry_run=args.dry_run)
    else:
        show_status()


if __name__ == "__main__":
    main()
