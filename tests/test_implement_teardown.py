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


# ── main() teardown: implement drops its own worktree on non-zero exit ───────

import pytest  # noqa: E402

_SCRIPTS = REPO_ROOT / ".agents/skills/mentat-implement/scripts"


def _write_plan(tmp_path: Path, slug: str = "failme") -> Path:
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nkind: AFK\n---\n# {slug}\n")
    return p


def test_main_tears_down_worktree_on_failure(tmp_path, monkeypatch):
    impl = _load()
    plan = _write_plan(tmp_path)
    target = tmp_path / "wt"
    target.mkdir()

    monkeypatch.setattr(impl.sys, "argv", ["implement.py", "run", str(plan)])
    monkeypatch.setattr(impl, "resolve_plan_path", lambda _ref: plan)
    monkeypatch.setattr(impl, "ensure_session", lambda *a, **k: "sess")
    monkeypatch.setattr(impl, "_prune_worktrees_preflight", lambda: None)
    monkeypatch.setattr(impl._utils, "default_harness", lambda: "claude-code")
    monkeypatch.setattr(impl, "preflight_veto_reviewers", lambda _h, reuse_worktree=False: (0, []))
    monkeypatch.setattr(impl, "preflight_worktree", lambda _slug, reuse_worktree=False: (0, target))
    monkeypatch.setattr(impl.os, "chdir", lambda _p: None)
    monkeypatch.setattr(impl, "_in_shared_main_tree", lambda reuse_worktree=False: False)
    monkeypatch.setattr(impl, "_run_and_doctor", lambda *a, **k: 1)  # non-preserve failure
    monkeypatch.setattr(impl, "_repo_root_from_worktree", lambda _t: tmp_path)

    torn: list = []
    monkeypatch.setattr(impl, "_teardown_worktree", lambda t: torn.append(t))

    with pytest.raises(SystemExit) as exc:
        impl.main()

    assert exc.value.code == 1
    assert torn == [target], "clean-up must tear down the implement-owned worktree on failure"
