"""mentat-tasks — Python CLI for the markdown task store."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_AGENTS_DIR = _SCRIPTS.parents[2]  # .agents/

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from lib import frontmatter  # noqa: E402
from lib.events import bind  # noqa: E402


def _load_sibling(name: str) -> object:
    key = f"mentat_tasks_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_utils = _load_sibling("utils")

emit = bind("mentat-tasks")


def cmd_next_id(_args: argparse.Namespace) -> int:
    import types

    u = _utils
    assert isinstance(u, types.ModuleType)
    td: Path = u.tasks_dir()
    if not td.exists():
        print("T001")
        return 0
    print(u.next_id(td))
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    import types

    u = _utils
    assert isinstance(u, types.ModuleType)
    td: Path = u.tasks_dir()
    td.mkdir(parents=True, exist_ok=True)

    slug: str = args.slug
    existing = list(td.glob(f"T*-{slug}.md"))
    if existing:
        print(f"tasks: slug '{slug}' already exists: {existing[0].name}", file=sys.stderr)
        return 1

    tid: str = u.next_id(td)
    target = td / f"{tid}-{slug}.md"
    body = sys.stdin.read()
    fm: dict[str, str] = {
        "id": tid,
        "status": "todo",
        "class": "",
        "claimed_by": "",
        "claim_expires_at": "",
        "created_at": u.now_rfc3339(),
    }
    target.write_text(frontmatter.encode(fm, body), encoding="utf-8")
    emit("task.created", {"id": tid, "slug": slug})
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tasks")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("next-id")

    create_p = sub.add_parser("create")
    create_p.add_argument("slug")

    args = parser.parse_args(argv)

    if args.cmd == "next-id":
        rc = cmd_next_id(args)
    elif args.cmd == "create":
        rc = cmd_create(args)
    else:
        parser.print_help(sys.stderr)
        rc = 64
    if rc != 0:
        sys.exit(rc)


if __name__ == "__main__":
    main()
