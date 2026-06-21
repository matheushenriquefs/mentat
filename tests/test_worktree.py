"""Tests for worktree.py — auto-detect default branch."""

from __future__ import annotations

import importlib.util as _importlib_util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

_GIT_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-git/scripts"
sys.path.insert(0, str(_GIT_SCRIPTS))

import worktree as wt  # noqa: E402

# Load utils explicitly to bypass sys.modules cache (other test files may have
# cached a different utils.py; mentat-git/scripts/utils is the one we need).
_utils_spec = _importlib_util.spec_from_file_location("mentat_git_utils", _GIT_SCRIPTS / "utils.py")
_utils_mod = _importlib_util.module_from_spec(_utils_spec)
_utils_spec.loader.exec_module(_utils_mod)

from lib import devcontainer as _dc_mod  # noqa: E402


def _cp(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    r: subprocess.CompletedProcess = subprocess.CompletedProcess.__new__(subprocess.CompletedProcess)
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    r.args = []
    return r


def _make_fake_git(tmp_path: Path, *, branch_exists_for: str, detect_responses: list):
    """Return a fake _git function for cmd_worktree_create call sequences.

    detect_responses: list of CompletedProcess for the detection calls
    (symbolic-ref first, then config if needed). Consumed in order.
    """
    detect_iter = iter(detect_responses)

    def fake(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
        joined = " ".join(args)

        if "--git-common-dir" in joined:
            return _cp(0, str(tmp_path / ".git") + "\n")

        if args[:2] == ["worktree", "list"]:
            # Target slug not in list → not an existing worktree
            return _cp(0, f"worktree {tmp_path}\nHEAD abc1234\nbranch refs/heads/main\n\n")

        if args[:2] == ["symbolic-ref", "--short"]:
            return next(detect_iter, _cp(1))

        if args[:2] == ["config", "--get"]:
            return next(detect_iter, _cp(1))

        if args[:3] == ["rev-parse", "--verify", "--quiet"]:
            branch = args[3].replace("refs/heads/", "")
            return _cp(0) if branch == branch_exists_for else _cp(1)

        if args[:2] == ["worktree", "add"]:
            return _cp(0)

        return _cp(1)

    return fake


class TestCmdWorktreeCreate:
    def test_explicit_base_honored(self, tmp_path):
        """explicit --base develop on develop-only repo succeeds."""
        fake = _make_fake_git(tmp_path, branch_exists_for="develop", detect_responses=[])
        with patch.object(wt, "_git", side_effect=fake):
            rc = wt.cmd_worktree_create("my-slug", base="develop", parent=tmp_path)
        assert rc == 0

    def test_omitted_base_resolves_via_origin_head(self, tmp_path):
        """omitted --base resolves via origin/HEAD symbolic-ref."""
        fake = _make_fake_git(
            tmp_path,
            branch_exists_for="develop",
            detect_responses=[_cp(0, "origin/develop\n")],
        )
        with patch.object(wt, "_git", side_effect=fake):
            rc = wt.cmd_worktree_create("my-slug", base=None, parent=tmp_path)
        assert rc == 0

    def test_omitted_base_falls_through_to_init_default_branch(self, tmp_path):
        """omitted --base falls through to init.defaultBranch when no origin."""
        fake = _make_fake_git(
            tmp_path,
            branch_exists_for="develop",
            detect_responses=[_cp(1), _cp(0, "develop\n")],
        )
        with patch.object(wt, "_git", side_effect=fake):
            rc = wt.cmd_worktree_create("my-slug", base=None, parent=tmp_path)
        assert rc == 0

    def test_omitted_base_falls_back_to_main_exits_66_when_missing(self, tmp_path):
        """omitted --base falls back to 'main'; exits 66 when main doesn't exist."""
        fake = _make_fake_git(
            tmp_path,
            branch_exists_for="develop",  # develop exists, main does not
            detect_responses=[_cp(1), _cp(1)],  # both detection steps fail
        )
        with patch.object(wt, "_git", side_effect=fake):
            rc = wt.cmd_worktree_create("my-slug", base=None, parent=tmp_path)
        assert rc == 66

    def test_explicit_base_main_exits_66_on_develop_only_repo(self, tmp_path):
        """explicit --base main on develop-only repo exits 66 — no silent fix-up."""
        fake = _make_fake_git(
            tmp_path,
            branch_exists_for="develop",  # only develop exists
            detect_responses=[],  # detection not called for explicit base
        )
        with patch.object(wt, "_git", side_effect=fake):
            rc = wt.cmd_worktree_create("my-slug", base="main", parent=tmp_path)
        assert rc == 66

    def test_default_parent_is_mentat_worktrees(self, tmp_path):
        """parent=None defaults to <main_root>/.mentat/worktrees/, not main_root.parent."""
        created_targets: list[Path] = []

        def fake(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
            joined = " ".join(args)
            if "--git-common-dir" in joined:
                return _cp(0, str(tmp_path / ".git") + "\n")
            if args[:2] == ["worktree", "list"]:
                return _cp(0, f"worktree {tmp_path}\nHEAD abc1234\nbranch refs/heads/main\n\n")
            if args[:2] == ["symbolic-ref", "--short"]:
                return _cp(1)
            if args[:2] == ["config", "--get"]:
                return _cp(1)
            if args[:3] == ["rev-parse", "--verify", "--quiet"]:
                branch = args[3].replace("refs/heads/", "")
                return _cp(0) if branch == "main" else _cp(1)
            if args[:2] == ["worktree", "add"]:
                # ["worktree", "add", "-b", <branch>, <target-path>, <base>]
                created_targets.append(Path(args[4]))
                return _cp(0)
            return _cp(1)

        with patch.object(wt, "_git", side_effect=fake):
            rc = wt.cmd_worktree_create("my-slug", base=None, parent=None)

        assert rc == 0
        assert created_targets, "worktree add was not called"
        target = created_targets[0]
        assert ".mentat" in target.parts, f"expected .mentat/ in worktree path, got {target}"
        assert "worktrees" in target.parts, f"expected worktrees/ in worktree path, got {target}"
        assert target.parent.parent.parent == tmp_path, f"expected <main_root>/.mentat/worktrees/<slug>, got {target}"


# ── container_id_for_cwd ─────────────────────────────────────────────────────


def test_container_id_for_cwd_delegates(monkeypatch):
    monkeypatch.setattr(_dc_mod, "container_id_for_slug", lambda slug, **kw: "abc123")
    result = _utils_mod.container_id_for_cwd()
    assert result == "abc123"


def test_mentat_git_does_not_call_docker_directly():
    import ast

    scripts_dir = _GIT_SCRIPTS
    source = (scripts_dir / "utils.py").read_text()
    tree = ast.parse(source)

    docker_calls: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in ("run", "Popen")):
            continue
        if not node.args:
            continue
        first_arg = node.args[0]
        if not isinstance(first_arg, ast.List) or not first_arg.elts:
            continue
        first_elem = first_arg.elts[0]
        if isinstance(first_elem, ast.Constant) and first_elem.value == "docker":
            docker_calls.append(node.lineno)

    assert not docker_calls, f"docker called directly via subprocess in utils.py at lines: {docker_calls}"
