"""S3: pane_layout.py is terminal-free; panes.py is the tty shell."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents/skills/mentat-track/scripts"

_BANNED = frozenset({"termios", "tty", "select", "subprocess", "signal", "atexit"})


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def test_pane_layout_has_no_tty_imports() -> None:
    imports = _imports_for(SCRIPTS / "pane_layout.py")
    assert imports.isdisjoint(_BANNED), f"pane_layout imports tty modules: {imports & _BANNED}"


def test_panes_imports_pane_layout() -> None:
    text = (SCRIPTS / "panes.py").read_text()
    assert "import pane_layout" in text or "from pane_layout" in text


def test_headless_list_frame_renders_without_filesystem(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(REPO_ROOT / ".agents"))
    sys.path.insert(0, str(SCRIPTS))
    import pane_layout

    entries = [
        ({"agent": "a", "status": "working", "age": 0.0, "last_event": "-"}, tmp_path / "a"),
    ]
    lines = pane_layout.list_frame(
        entries,
        0,
        "mentat",
        rows=20,
        preview_lines=5,
        tool_names=[],
        humanize_age=lambda s: f"{int(s)}s ago",
    )
    assert any("mentat" in line for line in lines)
    assert any("a" in line for line in lines)
