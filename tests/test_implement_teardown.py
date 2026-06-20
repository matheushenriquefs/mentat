"""S3 — implement owns its worktree teardown on its own failure.

Clean worktree → removed + container down. Dirty worktree → preserved (it holds
un-landed work the operator must finish), container still brought down.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".agents"))
_IMPL = REPO_ROOT / ".agents/skills/mentat-implement/scripts/implement.py"


def _load():
    spec = importlib.util.spec_from_file_location("implement_under_test", _IMPL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["implement_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_teardown_clean_removes_and_downs(monkeypatch, tmp_path) -> None:
    impl = _load()
    from lib import devcontainer, worktrees

    target = tmp_path / ".mentat" / "worktrees" / "implement-p-1"
    target.mkdir(parents=True)

    down_calls: list[str] = []
    monkeypatch.setattr(devcontainer, "down", lambda slug: down_calls.append(slug) or True)
    monkeypatch.setattr(worktrees, "teardown", lambda p: True)  # clean → removed

    impl._teardown_worktree(target)

    assert down_calls == ["implement-p-1"], "container for the worktree slug must be brought down"


def test_teardown_dirty_preserves(monkeypatch, tmp_path) -> None:
    impl = _load()
    from lib import devcontainer, worktrees

    target = tmp_path / ".mentat" / "worktrees" / "implement-p-2"
    target.mkdir(parents=True)

    down_calls: list[str] = []
    monkeypatch.setattr(devcontainer, "down", lambda slug: down_calls.append(slug) or True)
    monkeypatch.setattr(worktrees, "teardown", lambda p: False)  # dirty → preserved

    impl._teardown_worktree(target)

    # dir untouched (teardown stubbed to preserve), container still downed
    assert target.exists()
    assert down_calls == ["implement-p-2"]
