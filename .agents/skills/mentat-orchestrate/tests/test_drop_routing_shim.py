"""Slice deepen-drop-routing: routing.py shim deleted; orchestrate.py uses scheduler directly."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))


def test_routing_module_does_not_exist():
    from lib import paths

    routing_path = paths.SKILLS_DIR / "mentat-orchestrate" / "scripts" / "routing.py"
    assert not routing_path.exists(), f"routing.py still exists at {routing_path}"


def test_orchestrate_imports_scheduler_directly():
    src = (_SCRIPTS / "orchestrate.py").read_text()
    assert 'load_sibling(__file__, "scheduler")' in src, "orchestrate.py must use load_sibling(__file__, 'scheduler')"
    assert "routing" not in src, "orchestrate.py must not reference 'routing'"
