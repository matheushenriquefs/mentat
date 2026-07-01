"""Tests for mentat-install plan.py submodule."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-install/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _fake_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_compute_plan_clone_mode_uses_symlinks(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    clone_root = tmp_path / "clone"
    (clone_root / ".agents" / "skills").mkdir(parents=True)

    ip = plan_mod.compute_plan(home=home, clone_root=clone_root)
    assert any(a.action_type == "symlink" for a in ip.add)


def test_compute_plan_user_mode_uses_copies(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    for action in ip.add:
        assert action.action_type in ("copy", "mkdir", "file-create", "symlink")


def test_compute_plan_detects_claude_code_when_dir_exists(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    (tmp_path / ".claude").mkdir()
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    harnesses = [a.target for a in ip.add if ".claude" in str(a.target)]
    assert harnesses or any(".claude" in str(a.target) for a in ip.update)


def test_compute_plan_detects_cursor_when_dir_exists(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    (tmp_path / ".cursor").mkdir()
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    cursor_items = [a for a in ip.add + ip.update if ".cursor" in str(a.target)]
    assert cursor_items


def test_compute_plan_skips_undetected_harness(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    cursor_items = [a for a in ip.add + ip.update if ".cursor" in str(a.target)]
    claude_items = [a for a in ip.add + ip.update if ".claude" in str(a.target)]
    assert not cursor_items
    assert not claude_items


def test_compute_plan_lists_stale_paths(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    stale = tmp_path / ".agents" / "mentat"
    stale.mkdir(parents=True)
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    assert any("mentat" in str(p) for p in ip.stale)


def test_compute_plan_is_pure_no_side_effects(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    before = set(tmp_path.rglob("*"))
    plan_mod.compute_plan(home=home, clone_root=None)
    after = set(tmp_path.rglob("*"))
    assert before == after


def test_action_repr_round_trips_fields():
    plan_mod = load_module("plan")
    a = plan_mod.Action("symlink", Path("/s"), Path("/t"))
    r = repr(a)
    assert "symlink" in r
    assert "/s" in r
    assert "/t" in r


def test_plan_symlink_updates_when_target_points_elsewhere(tmp_path):
    plan_mod = load_module("plan")
    home = tmp_path / "home"
    clone = tmp_path / "clone"
    (clone / ".agents" / "skills" / "mentat-log").mkdir(parents=True)
    tgt = home / ".agents" / "skills" / "mentat-log"
    tgt.parent.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    tgt.symlink_to(other)  # existing symlink → different source → update
    ip = plan_mod.compute_plan(home=home, clone_root=clone)
    assert any(a.action_type == "symlink" and a.target == tgt for a in ip.update)


def test_compute_plan_clone_less_skips_existing_skill_target(tmp_path):
    plan_mod = load_module("plan")
    home = tmp_path / "home"
    existing = home / ".agents" / "skills" / "mentat-log"
    existing.mkdir(parents=True)  # target exists → no copy action for it
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    copy_targets = {a.target for a in ip.add if a.action_type == "copy"}
    assert existing not in copy_targets


def test_plan_symlink_conflict_on_real_file_at_target(tmp_path):
    plan_mod = load_module("plan")
    home = tmp_path / "home"
    clone = tmp_path / "clone"
    (clone / ".agents" / "skills" / "mentat-log").mkdir(parents=True)
    tgt = home / ".agents" / "skills" / "mentat-log"
    tgt.parent.mkdir(parents=True)
    tgt.write_text("real")  # real file (not symlink) → conflict
    ip = plan_mod.compute_plan(home=home, clone_root=clone)
    assert tgt in ip.conflicts


def test_plan_symlink_no_update_when_target_already_correct(tmp_path):
    plan_mod = load_module("plan")
    home = tmp_path / "home"
    clone = tmp_path / "clone"
    src = clone / ".agents" / "skills" / "mentat-log"
    src.mkdir(parents=True)
    tgt = home / ".agents" / "skills" / "mentat-log"
    tgt.parent.mkdir(parents=True)
    tgt.symlink_to(src)  # already points at the right source → no update
    ip = plan_mod.compute_plan(home=home, clone_root=clone)
    assert not any(a.target == tgt for a in ip.update)


def test_compute_plan_skips_existing_mentat_subdir(tmp_path):
    plan_mod = load_module("plan")
    home = tmp_path / "home"
    (home / ".mentat" / "logs").mkdir(parents=True)  # logs exists → no mkdir action
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    mkdir_targets = {a.target for a in ip.add if a.action_type == "mkdir"}
    assert home / ".mentat" / "logs" not in mkdir_targets


def test_compute_plan_harness_reviewer_symlinks_from_clone(tmp_path):
    plan_mod = load_module("plan")
    home = tmp_path / "home"
    clone = tmp_path / "clone"
    (clone / ".agents" / "skills").mkdir(parents=True)
    (clone / ".agents" / "agents").mkdir(parents=True)
    (clone / ".agents" / "agents" / "mentat-bug-reviewer.md").write_text("")
    (home / ".claude").mkdir(parents=True)  # harness detected → fanout runs reviewer loop
    ip = plan_mod.compute_plan(home=home, clone_root=clone)
    agent_links = [a for a in ip.add + ip.update if "/.claude/agents/" in str(a.target)]
    assert agent_links
