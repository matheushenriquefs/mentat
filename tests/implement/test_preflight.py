"""FOLLOW-UP #24 — mentat-implement preflight: auto-create worktree via mentat-git."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tests.conftest import init_git_repo, load_script

_SCRIPTS = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-implement/scripts"
_GIT_SKILLS = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-git/scripts"
_CID = "b" * 32


@pytest.fixture(autouse=True)
def _fixed_chunk_id(monkeypatch):
    import lib.chunk as chunk_mod

    monkeypatch.setattr(chunk_mod, "make_chunk_id", lambda: _CID)
    monkeypatch.setenv("MENTAT_CHUNK_ID", _CID)


def _load():
    mod = load_script(_SCRIPTS / "implement.py", "implement_mod")
    # Override home-relative paths to use the repo-local skills dir in container.
    mod._GIT_WORKTREE_PY = _GIT_SKILLS / "worktree.py"
    mod._GIT_SCRIPT = _GIT_SKILLS / "git.py"
    return mod


@pytest.fixture
def main_repo(tmp_path, monkeypatch):
    r = tmp_path / "main"
    r.mkdir()
    init_git_repo(r)
    monkeypatch.chdir(r)
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    return r


def test_is_main_worktree_true_in_main(main_repo):
    impl = _load()
    assert impl._is_main_worktree(main_repo) is True


def test_is_main_worktree_false_in_sibling(main_repo):
    impl = _load()
    sibling = main_repo.parent / "feat-a"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat-a", str(sibling), "main"],
        cwd=main_repo,
        check=True,
        capture_output=True,
    )
    assert impl._is_main_worktree(sibling) is False


def test_is_main_worktree_false_outside_repo(tmp_path):
    impl = _load()
    assert impl._is_main_worktree(tmp_path) is False


def test_preflight_creates_worktree_in_main_repo(main_repo):
    impl = _load()
    rc, target = impl.preflight_worktree("feat-x")
    assert rc == 0
    assert target is not None
    assert target.is_dir()
    assert target.name == "feat-x"


def test_preflight_idempotent_when_already_created(main_repo):
    impl = _load()
    rc1, t1 = impl.preflight_worktree("feat-x")
    rc2, t2 = impl.preflight_worktree("feat-x")
    assert rc1 == 0 and rc2 == 0
    assert t1 == t2


def test_preflight_skips_when_env_set(main_repo, monkeypatch):
    impl = _load()
    monkeypatch.setenv("MENTAT_SKIP_PREFLIGHT", "1")
    rc, target = impl.preflight_worktree("feat-x")
    assert rc == 0
    assert target is None
    assert not (main_repo.parent / "feat-x").exists()


def test_preflight_skips_when_reuse_worktree(main_repo):
    impl = _load()
    rc, target = impl.preflight_worktree("feat-x", reuse_worktree=True)
    assert rc == 0
    assert target is None
    assert not (main_repo.parent / "feat-x").exists()


def test_preflight_skips_when_not_in_repo(tmp_path, monkeypatch):
    impl = _load()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    rc, target = impl.preflight_worktree("feat-x")
    assert rc == 0
    assert target is None


def test_preflight_skips_inside_sibling_worktree(main_repo, monkeypatch):
    impl = _load()
    sibling = main_repo.parent / "feat-a"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat-a", str(sibling), "main"],
        cwd=main_repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(sibling)
    rc, target = impl.preflight_worktree("feat-b")
    assert rc == 0
    assert target is None
    assert not (main_repo.parent / "feat-b").exists()


def test_preflight_returns_65_on_path_conflict(main_repo):
    impl = _load()
    conflict = main_repo / ".mentat" / "worktrees" / _CID / "feat-conflict"
    conflict.mkdir(parents=True)
    rc, target = impl.preflight_worktree("feat-conflict")
    assert rc == 65
    assert target is None


def test_preflight_succeeds_after_default_branch_rename(main_repo):
    """worktree create auto-detects the default branch (FL3); renamed main→trunk still works."""
    impl = _load()
    subprocess.run(["git", "branch", "-m", "main", "trunk"], cwd=main_repo, check=True, capture_output=True)
    rc, target = impl.preflight_worktree("feat-y")
    assert rc == 0
    assert target is not None


def test_main_invokes_preflight_then_chdir(main_repo, tmp_path, monkeypatch):
    """CLI entry: preflight runs, cwd flips to the worktree, then plan execution starts."""
    impl = _load()
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    plan = plan_dir / "feat-cli.md"
    plan.write_text("---\nid: feat-cli\nkind: AFK\n---\n# x\n")

    chdir_targets: list[Path] = []
    real_chdir = impl.os.chdir

    def spy_chdir(p):
        chdir_targets.append(Path(p))
        real_chdir(p)

    with patch.object(impl, "preflight_veto_reviewers", return_value=(0, [])):
        with patch.object(impl.os, "chdir", side_effect=spy_chdir):
            with patch.object(impl, "_run_and_doctor", return_value=0) as mock_run:
                with patch.object(impl.sys, "argv", ["implement.py", str(plan)]):
                    with pytest.raises(SystemExit) as exc:
                        impl.main()

    assert exc.value.code == 0
    assert mock_run.call_count == 1
    expected = (main_repo / ".mentat" / "worktrees" / _CID / "feat-cli").resolve()
    assert expected.is_dir()
    # Verify os.chdir actually fired with the worktree path before run_plan was invoked.
    assert any(p.resolve() == expected for p in chdir_targets), (
        f"chdir never called with worktree target; saw: {chdir_targets}"
    )


# ── S9: own-worktree isolation (branch-leak fix) ─────────────────────────────


def test_in_shared_main_tree_true_in_main(main_repo):
    """In the main worktree of a real repo (no skip), running there is unsafe —
    a branch switch flips HEAD for every concurrent agent sharing the tree."""
    impl = _load()
    assert impl._in_shared_main_tree() is True


def test_in_shared_main_tree_false_when_skip_preflight(main_repo, monkeypatch):
    impl = _load()
    monkeypatch.setenv("MENTAT_SKIP_PREFLIGHT", "1")
    assert impl._in_shared_main_tree() is False


def test_in_shared_main_tree_false_outside_repo(tmp_path, monkeypatch):
    impl = _load()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    assert impl._in_shared_main_tree() is False


def test_in_shared_main_tree_false_in_sibling(main_repo, monkeypatch):
    impl = _load()
    sibling = main_repo.parent / "feat-a"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat-a", str(sibling), "main"],
        cwd=main_repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(sibling)
    assert impl._in_shared_main_tree() is False


def test_main_refuses_when_left_in_main_tree(main_repo, tmp_path, monkeypatch):
    """Fail closed: if preflight does not isolate (returns no worktree) and cwd is
    still the shared main tree, refuse rather than risk the branch leak."""
    impl = _load()
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    plan = plan_dir / "feat-leak.md"
    plan.write_text("---\nid: feat-leak\nkind: AFK\n---\n# x\n")

    emits = []

    def fake_emit(event, payload):
        emits.append((event, payload))

    with patch.object(impl, "preflight_veto_reviewers", return_value=(0, [])):
        with patch.object(impl, "preflight_worktree", return_value=(0, None)):
            with patch.object(impl, "_emit_event", side_effect=fake_emit):
                with patch.object(impl, "_run_and_doctor", return_value=0) as mock_run:
                    with patch.object(impl.sys, "argv", ["implement.py", str(plan)]):
                        with pytest.raises(SystemExit) as exc:
                            impl.main()

    assert exc.value.code == impl.EX_USAGE
    mock_run.assert_not_called()  # refused before any plan execution
    assert any(event == "chunk_ejected" and payload.get("reason") == "main_tree_refused" for event, payload in emits)


def test_main_emits_eject_on_preflight_conflict(main_repo, tmp_path, monkeypatch):
    impl = _load()
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    plan = plan_dir / "feat-conflict.md"
    plan.write_text("---\nid: feat-conflict\nkind: AFK\n---\n# x\n")
    conflict = main_repo / ".mentat" / "worktrees" / _CID / "feat-conflict"
    conflict.mkdir(parents=True)

    emits = []

    def fake_emit(event, payload):
        emits.append((event, payload))

    with patch.object(impl, "preflight_veto_reviewers", return_value=(0, [])):
        with patch.object(impl, "_emit_event", side_effect=fake_emit):
            with patch.object(impl, "_run_and_doctor", return_value=0):
                with patch.object(impl.sys, "argv", ["implement.py", str(plan)]):
                    with pytest.raises(SystemExit) as exc:
                        impl.main()

    assert exc.value.code == 65
    assert any(
        event == "chunk_ejected" and payload.get("reason") == "preflight_worktree_failed" for event, payload in emits
    )


# ── H3: preflight must not crash on garbage last stdout line ─────────────────


def test_preflight_returns_clean_failure_on_garbage_stdout(main_repo):
    """An extra/garbage line after the worktree path in cmd_worktree_create stdout
    must return non-zero, not raise FileNotFoundError from os.chdir."""
    impl = _load()
    fake = MagicMock()
    fake.returncode = 0
    # Real path is NOT the last line — garbage appended so Path(line).is_dir() fails.
    fake.stdout = "/some/valid/path\nextra garbage line\n"

    with patch.object(impl.subprocess, "run", return_value=fake):
        rc, target = impl.preflight_worktree("feat-garbage")

    assert rc != 0, "must return non-zero when parsed path does not exist"
    assert target is None
