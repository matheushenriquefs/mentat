"""mentat-afk-resilience-executor — 4 slice tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import TEST_CHUNK_ID, init_git_repo, load_script

_WT_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-git/scripts"
_IMPL_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts"


def _load_worktree():
    return load_script(_WT_SCRIPTS / "worktree.py", "wt_mod_exec")


def _load_impl():
    mod = load_script(_IMPL_SCRIPTS / "implement.py", "impl_mod_exec")
    mod._GIT_WORKTREE_PY = _WT_SCRIPTS / "worktree.py"
    mod._GIT_SCRIPT = _WT_SCRIPTS / "git.py"
    return mod


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "main"
    r.mkdir()
    init_git_repo(r)
    monkeypatch.chdir(r)
    return r


@pytest.fixture
def main_repo(tmp_path, monkeypatch):
    r = tmp_path / "main"
    r.mkdir()
    init_git_repo(r)
    monkeypatch.chdir(r)
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    return r


# ── Slice 1: prunable record + missing dir → create yields real dir ──────────


def test_worktree_create_prunes_phantom_record_and_reattaches(repo, capsys):
    """Stale admin record (dir deleted) must not cause create to return rc=0 with a missing dir."""
    wt = _load_worktree()
    target = repo / ".mentat" / "worktrees" / TEST_CHUNK_ID / "feat-phantom"

    assert wt.cmd_worktree_create("feat-phantom", chunk_id=TEST_CHUNK_ID) == 0
    assert target.is_dir()
    capsys.readouterr()

    shutil.rmtree(target)
    assert not target.exists()

    rc2 = wt.cmd_worktree_create("feat-phantom", chunk_id=TEST_CHUNK_ID)
    out2 = capsys.readouterr().out.strip()

    assert rc2 == 0, f"re-create after stale record must succeed, got rc={rc2}"
    returned_path = Path(out2.splitlines()[-1]) if out2 else None
    assert returned_path is not None and returned_path.is_dir(), (
        f"rc=0 with missing dir is the bug; returned_path={returned_path!r}"
    )


# ── Slice 2: rc=0 + empty stdout → EX_SOFTWARE ───────────────────────────────


def test_preflight_errors_on_rc0_empty_stdout(main_repo):
    """rc=0 from worktree create with no parseable path must fail, not silently degrade."""
    impl = _load_impl()
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = ""

    with patch.object(impl.subprocess, "run", return_value=fake):
        rc, target = impl.preflight_worktree("feat-empty-stdout")

    assert rc != 0, "rc=0 + empty stdout must return EX_SOFTWARE, not silently return (0, None)"
    assert target is None


# ── Slice 3: path rewrite guarded by .agents/ existence ──────────────────────


def _run_plan_capture_prompt(impl, plan_file):
    captured: list[str] = []

    def fake_invoke(harness, prompt, *, afk, model=None, seed_summary=None):
        captured.append(prompt)
        result = MagicMock()
        result.returncode = 0
        return result

    with (
        patch.object(impl, "_invoke_harness", side_effect=fake_invoke),
        patch.object(impl, "read_tests_manifest", return_value=([], [])),
        patch.object(impl, "_read_blocked_summary", return_value=None),
        patch.object(impl, "_detect_self_answer", return_value=False),
        patch.object(impl, "_checkpoint_if_needed", return_value=None),
    ):
        impl.run_plan(plan_file)

    return captured[0] if captured else None


def test_afk_body_not_rewritten_when_agents_dir_absent(tmp_path, monkeypatch):
    """Plan body with home-agents paths must not be rewritten when cwd has no .agents/."""
    impl = _load_impl()
    monkeypatch.chdir(tmp_path)

    home_agents = str(Path.home()) + "/.agents/"
    plan_body = f"See {home_agents}plans/my-plan.md for implementation details."
    plan_file = tmp_path / "test-plan.md"
    plan_file.write_text(f"---\nid: test-plan\nclass: AFK\n---\n{plan_body}")

    prompt = _run_plan_capture_prompt(impl, plan_file)
    assert prompt is not None

    cwd_agents = str(tmp_path) + "/.agents/"
    assert cwd_agents not in prompt, f"must NOT rewrite to nonexistent {cwd_agents!r}"
    assert home_agents in prompt, "original home_agents reference must remain intact"


def test_afk_body_rewritten_when_agents_dir_exists(tmp_path, monkeypatch):
    """Path rewrite DOES happen when cwd/.agents/ exists."""
    impl = _load_impl()
    (tmp_path / ".agents").mkdir()
    monkeypatch.chdir(tmp_path)

    home_agents = str(Path.home()) + "/.agents/"
    if home_agents == str(tmp_path) + "/.agents/":
        pytest.skip("cwd IS home — rewrite would be identity")

    plan_body = f"See {home_agents}plans/my-plan.md for reference."
    plan_file = tmp_path / "test-plan.md"
    plan_file.write_text(f"---\nid: test-plan\nclass: AFK\n---\n{plan_body}")

    prompt = _run_plan_capture_prompt(impl, plan_file)
    assert prompt is not None

    cwd_agents = str(tmp_path) + "/.agents/"
    assert cwd_agents in prompt, f"must rewrite to {cwd_agents!r} when .agents/ exists"


# ── Slice 4: teardown chdir uses git-derived repo root ───────────────────────


def test_repo_root_from_standard_worktree_depth(repo):
    """_repo_root_from_worktree returns the main repo root at standard depth."""
    impl = _load_impl()
    target = repo / ".mentat" / "worktrees" / "feat-std"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat-std", str(target), "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    result = impl._repo_root_from_worktree(target)
    assert result.resolve() == repo.resolve()


def test_repo_root_from_nonstandard_depth(repo):
    """_repo_root_from_worktree returns the main repo root for non-standard worktree paths."""
    impl = _load_impl()
    custom = repo.parent / "custom" / "slug"
    custom.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", "slug", str(custom), "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    result = impl._repo_root_from_worktree(custom)
    assert result.resolve() == repo.resolve(), f"must return repo root {repo} for non-standard depth, got {result}"


def test_teardown_chdir_uses_repo_root_not_hardcoded_depth(repo, monkeypatch):
    """main() teardown must use _repo_root_from_worktree, not target.parents[2]."""
    impl = _load_impl()
    custom = repo.parent / "custom" / "slug"
    custom.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", "slug", str(custom), "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    chdir_calls: list[Path] = []
    real_chdir = impl.os.chdir

    def spy(p):
        chdir_calls.append(Path(p))
        real_chdir(p)

    monkeypatch.setattr(impl.os, "chdir", spy)

    with patch.object(impl, "_teardown_worktree", return_value=None):
        rc = 1
        target = custom
        if rc != 0 and rc not in impl._PRESERVE_WORKTREE_EXITS and target is not None:
            impl.os.chdir(impl._repo_root_from_worktree(target))
            impl._teardown_worktree(target)

    assert any(p.resolve() == repo.resolve() for p in chdir_calls), (
        f"chdir must go to repo root {repo}; saw {chdir_calls}"
    )
