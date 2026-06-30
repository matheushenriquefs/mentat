"""E2E: a tiny one-slice plan driven through mentat-implement end-to-end.

Real git repo, a real per-slice ``git commit``, and a real ``pre-commit`` gate hook
firing on that commit. The only seam stubbed is the harness boundary — the agent
itself (which in production is ``claude --headless``) is replaced by a fake that does
the work the AFK commit contract demands: edit a file, stage it, commit it. Everything
downstream of that — implement's gate step on a green result and the success report-back
— runs for real. Asserts the per-slice commit lands and the gate ran on it. This is the
established mentat e2e shape (the land/deadline e2e tests likewise drive the real
internals in-process and keep a single real subprocess at the boundary).
"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.conftest import load_script


@contextmanager
def _patch_attr(obj, name, value):
    """Swap one attribute on a module for the duration of the block, then restore."""
    saved = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, saved)


pytestmark = pytest.mark.e2e

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-implement/scripts"

# A pre-commit hook standing in for the repo's real gate suite: it must fire on the
# per-slice commit (proving gates run) and it writes a marker the test can observe.
_PRE_COMMIT_HOOK = """#!/bin/sh
echo ran >> "$(git rev-parse --git-dir)/gate-ran"
"""


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(["init", "-b", "main"], cwd=repo)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _git(["config", k, v], cwd=repo)
    (repo / "README.md").write_text("seed\n")
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", "init"], cwd=repo)
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text(_PRE_COMMIT_HOOK)
    hook.chmod(0o755)


def _write_plan(tmp_path: Path) -> Path:
    plan = tmp_path / "tiny-slice.md"
    plan.write_text("---\nid: tiny-slice\nclass: AFK\n---\n# Tiny slice\nAdd a feature module and commit it.\n")
    return plan


def _fake_agent(repo: Path):
    """A harness stand-in that performs one slice's worth of real work in `repo`.

    It honors the AFK commit contract: write the slice's file, stage it, commit it.
    The commit is a real git subprocess, so the real pre-commit gate hook fires.
    """

    def invoke(harness, prompt, *, afk, model=None, seed_summary=None):
        (repo / "feature.py").write_text("def feature():\n    return 42\n")
        _git(["add", "feature.py"], cwd=repo)
        _git(["commit", "-m", "feat(core): add feature module"], cwd=repo)

        class _Result:
            returncode = 0
            usage_tokens = None
            session_log = None

        return _Result()

    return invoke


def test_implement_one_slice_commits_and_runs_gates(tmp_path, monkeypatch):
    impl = load_script(SCRIPTS / "implement.py", "implement")

    repo = tmp_path / "repo"
    _init_repo(repo)
    plan = _write_plan(tmp_path)

    # Hermetic: skip worktree/container preflight, point all session state at tmp,
    # and run directly in the repo (the agent's cwd).
    monkeypatch.setenv("MENTAT_SKIP_PREFLIGHT", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    monkeypatch.setenv("MENTAT_SESSION", "implement-tiny-slice-1")
    monkeypatch.chdir(repo)

    before = _git(["rev-list", "--count", "HEAD"], cwd=repo)

    gate_calls: list[Path | None] = []
    real_gates = impl._run_gates

    def _spy_gates(chunk_path):
        gate_calls.append(chunk_path)
        return real_gates(chunk_path)

    with _patch_attr(impl, "_invoke_harness", _fake_agent(repo)):
        with _patch_attr(impl, "_run_gates", _spy_gates):
            rc = impl._run_and_doctor(plan)

    assert rc == 0, "a green one-slice AFK run must return 0"

    # The per-slice commit landed: exactly one new commit, and it is the slice's.
    after = _git(["rev-list", "--count", "HEAD"], cwd=repo)
    assert int(after) == int(before) + 1, "exactly one per-slice commit must land"
    assert _git(["log", "-1", "--format=%s"], cwd=repo) == "feat(core): add feature module"
    # The slice's file is tracked at the new tip.
    assert "feature.py" in _git(["ls-tree", "--name-only", "HEAD"], cwd=repo)

    # Gates ran: implement's gate step fired on the green result, and the real
    # pre-commit gate hook fired on the per-slice commit.
    assert gate_calls == [None], "implement must run its gate step once on a green result"
    assert (repo / ".git/gate-ran").exists(), "the pre-commit gate hook must fire on the per-slice commit"
