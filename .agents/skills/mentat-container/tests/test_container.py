import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import compose_render  # noqa: E402
import container  # noqa: E402
import utils  # noqa: E402

# Mirrors the committed mentat devcontainer.json — what every new worktree inherits
_MENTAT_DCJ = {
    "name": "mentat",
    "build": {"dockerfile": "Dockerfile"},
    "onCreateCommand": "sudo apt-get update",
    "postCreateCommand": "cd /workspaces/mentat && uv sync && lefthook install",
    "workspaceMount": "source=${localWorkspaceFolder},target=/workspaces/mentat,type=bind,consistency=cached",
    "workspaceFolder": "/workspaces/mentat",
    "runArgs": ["--init"],
    "remoteUser": "vscode",
}


class TestEnsureDevcontainerJson:
    def test_new_file_written_via_synth(self, tmp_path):
        """No existing devcontainer.json → synth called, file created with synth output."""
        wt = tmp_path / "some-repo"
        wt.mkdir()
        slug = wt.name
        expected = json.dumps({"name": slug, "workspaceFolder": f"/workspaces/{slug}"}, indent=2)
        dcj = wt / ".devcontainer" / "devcontainer.json"

        with patch.object(compose_render, "synth", return_value=expected):
            container._ensure_devcontainer_json(wt, slug)

        assert dcj.read_text() == expected

    def test_idempotent_correct_file(self, tmp_path):
        """File with correct workspaceFolder is not rewritten (mtime preserved)."""
        wt = tmp_path / "mentat"
        wt.mkdir()
        slug = wt.name
        data = dict(_MENTAT_DCJ, name=slug, workspaceFolder=f"/workspaces/{slug}")
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(data, indent=2))
        mtime = dcj.stat().st_mtime_ns

        container._ensure_devcontainer_json(wt, slug)

        assert dcj.stat().st_mtime_ns == mtime

    def test_stale_worktree_workspace_folder_patched(self, tmp_path):
        """Inherited devcontainer.json with wrong workspaceFolder gets workspaceFolder fixed."""
        wt = tmp_path / "my-feature"
        wt.mkdir()
        slug = wt.name
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(_MENTAT_DCJ, indent=2))

        container._ensure_devcontainer_json(wt, slug)

        result = json.loads(dcj.read_text())
        assert result["workspaceFolder"] == f"/workspaces/{slug}"
        assert result["name"] == slug

    def test_stale_worktree_patches_mount_and_commands(self, tmp_path):
        """workspaceMount target and lifecycle command paths updated when patching."""
        wt = tmp_path / "my-feature"
        wt.mkdir()
        slug = wt.name
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(_MENTAT_DCJ, indent=2))

        container._ensure_devcontainer_json(wt, slug)

        result = json.loads(dcj.read_text())
        assert f"target=/workspaces/{slug}" in result["workspaceMount"]
        assert f"/workspaces/{slug}" in result["postCreateCommand"]

    def test_correct_worktree_not_rewritten(self, tmp_path):
        """Existing correct worktree file is not touched (mtime preserved)."""
        wt = tmp_path / "my-feature"
        wt.mkdir()
        slug = wt.name
        data = {"name": slug, "workspaceFolder": f"/workspaces/{slug}"}
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(data, indent=2))
        mtime = dcj.stat().st_mtime_ns

        container._ensure_devcontainer_json(wt, slug)

        assert dcj.stat().st_mtime_ns == mtime

    def test_synth_value_error_exits(self, tmp_path):
        """synth raising ValueError when no file exists propagates as SystemExit(1)."""
        wt = tmp_path / "no-dockerfile"
        wt.mkdir()
        slug = wt.name

        side = ValueError("no Dockerfile")
        with patch.object(compose_render, "synth", side_effect=side), pytest.raises(SystemExit) as exc_info:
            container._ensure_devcontainer_json(wt, slug)

        assert exc_info.value.code == 1


class TestGitMountForWorktree:
    def test_returns_none_for_main_repo(self, tmp_path):
        wt = tmp_path / "repo"
        wt.mkdir()
        (wt / ".git").mkdir()
        assert container._git_mount_for_worktree(wt) is None

    def test_returns_bind_mount_for_worktree(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        main_git = str(tmp_path / "main" / ".git")
        gitdir = f"{main_git}/worktrees/my-feature"
        (wt / ".git").write_text(f"gitdir: {gitdir}\n")

        result = container._git_mount_for_worktree(wt)

        assert result == f"source={main_git},target={main_git},type=bind"

    def test_returns_none_when_no_git_file(self, tmp_path):
        wt = tmp_path / "repo"
        wt.mkdir()
        assert container._git_mount_for_worktree(wt) is None


class TestEnsureDevcontainerJsonGitMount:
    def test_adds_git_mount_when_patching_stale_worktree(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        main_git = str(tmp_path / "main" / ".git")
        (wt / ".git").write_text(f"gitdir: {main_git}/worktrees/my-feature\n")
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(_MENTAT_DCJ, indent=2))

        container._ensure_devcontainer_json(wt, "my-feature")

        result = json.loads(dcj.read_text())
        expected_mount = f"source={main_git},target={main_git},type=bind"
        assert expected_mount in result.get("mounts", [])

    def test_no_mounts_field_for_main_repo(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        (wt / ".git").mkdir()
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(_MENTAT_DCJ, indent=2))

        container._ensure_devcontainer_json(wt, "my-feature")

        result = json.loads(dcj.read_text())
        assert "mounts" not in result

    def test_idempotent_when_mount_already_present(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        main_git = str(tmp_path / "main" / ".git")
        (wt / ".git").write_text(f"gitdir: {main_git}/worktrees/my-feature\n")
        expected_mount = f"source={main_git},target={main_git},type=bind"
        data = {"name": "my-feature", "workspaceFolder": "/workspaces/my-feature", "mounts": [expected_mount]}
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(data, indent=2))
        mtime = dcj.stat().st_mtime_ns

        container._ensure_devcontainer_json(wt, "my-feature")

        assert dcj.stat().st_mtime_ns == mtime

    def test_adds_mount_to_synth_output_for_worktree(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        main_git = str(tmp_path / "main" / ".git")
        (wt / ".git").write_text(f"gitdir: {main_git}/worktrees/my-feature\n")
        slug = wt.name
        synth_out = json.dumps({"name": slug, "workspaceFolder": f"/workspaces/{slug}"})

        with patch.object(compose_render, "synth", return_value=synth_out):
            container._ensure_devcontainer_json(wt, slug)

        dcj = wt / ".devcontainer" / "devcontainer.json"
        result = json.loads(dcj.read_text())
        expected_mount = f"source={main_git},target={main_git},type=bind"
        assert expected_mount in result.get("mounts", [])


class TestCmdDown:
    def test_down_removes_running_container(self, monkeypatch):
        monkeypatch.setattr(utils, "container_id_for", lambda slug: "abc123")
        ran: list = []

        def fake_run(cmd, **kw):
            ran.append(cmd)
            r = MagicMock()
            r.returncode = 0
            return r

        monkeypatch.setattr(container.subprocess, "run", fake_run)
        rc = container.cmd_down(slug="my-feature")
        assert rc == 0
        assert any("rm" in c and "-f" in c and "abc123" in c for c in ran)

    def test_down_removes_stopped_container(self, monkeypatch):
        monkeypatch.setattr(utils, "container_id_for", lambda slug: None)
        ran: list = []

        def fake_run(cmd, **kw):
            ran.append(cmd)
            r = MagicMock()
            r.returncode = 0
            # Second call (stopped lookup) returns an id; first two calls return empty
            if "status=exited" in " ".join(cmd):
                r.stdout = "stopped123\n"
            else:
                r.stdout = ""
            return r

        monkeypatch.setattr(container.subprocess, "run", fake_run)
        rc = container.cmd_down(slug="my-feature")
        assert rc == 0
        rm_calls = [c for c in ran if "rm" in c and "-f" in c]
        assert rm_calls, "docker rm -f should be called on stopped container"
        assert "stopped123" in rm_calls[0]

    def test_down_idempotent_when_no_container(self, monkeypatch):
        monkeypatch.setattr(utils, "container_id_for", lambda slug: None)
        ran: list = []

        def fake_run(cmd, **kw):
            ran.append(cmd)
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            return r

        monkeypatch.setattr(container.subprocess, "run", fake_run)
        rc = container.cmd_down(slug="ghost")
        assert rc == 0
        rm_calls = [c for c in ran if "rm" in c]
        assert rm_calls == [], "no docker rm call when container absent"

    def test_down_slug_arg_bypasses_cwd(self, monkeypatch):
        git_root_called = []

        def fake_git_root():
            git_root_called.append(True)
            return Path("/tmp/some-repo")

        monkeypatch.setattr(container, "_git_root", fake_git_root)
        monkeypatch.setattr(utils, "container_id_for", lambda slug: None)

        def fake_run(cmd, **kw):
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            return r

        monkeypatch.setattr(container.subprocess, "run", fake_run)
        container.cmd_down(slug="my-feature")
        assert git_root_called == [], "_git_root must not be called when slug given directly"


class TestResolveWorkspaceFolder:
    def test_main_repo_reads_devcontainer_json(self, tmp_path):
        """Non-worktree: reads workspaceFolder from devcontainer.json."""
        repo = tmp_path / "mentat"
        repo.mkdir()
        (repo / ".git").mkdir()  # real repo → .git is a directory
        dcj = repo / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps({"workspaceFolder": "/workspaces/mentat"}))

        assert utils.resolve_workspace_folder(repo) == "/workspaces/mentat"

    def test_worktree_uses_slug_regardless_of_devcontainer(self, tmp_path):
        """Worktree: returns /workspaces/<slug> even if devcontainer.json says /workspaces/mentat."""
        wt = tmp_path / "my-feature"
        wt.mkdir()
        # Simulate worktree: .git is a file pointer, not a directory
        (wt / ".git").write_text("gitdir: /some/repo/.git/worktrees/my-feature\n")
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        # Canonical (pre-patch) devcontainer.json — would give wrong answer if read blindly
        dcj.write_text(json.dumps({"workspaceFolder": "/workspaces/mentat"}))

        assert utils.resolve_workspace_folder(wt) == "/workspaces/my-feature"

    def test_worktree_no_devcontainer_uses_slug(self, tmp_path):
        """Worktree with no devcontainer.json: still returns /workspaces/<slug>."""
        wt = tmp_path / "some-branch"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: /some/repo/.git/worktrees/some-branch\n")

        assert utils.resolve_workspace_folder(wt) == "/workspaces/some-branch"


class TestPostCreateCommandLefthookInstall:
    def test_post_create_command_runs_lefthook_install(self, tmp_path):
        """Patched postCreateCommand must include lefthook install step."""
        wt = tmp_path / "my-feature"
        wt.mkdir()
        slug = wt.name
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(_MENTAT_DCJ, indent=2))

        container._ensure_devcontainer_json(wt, slug)

        result = json.loads(dcj.read_text())
        assert "lefthook install" in result["postCreateCommand"]

    def test_lefthook_install_path_rewrite(self, tmp_path):
        """lefthook install runs after cd /workspaces/<slug> so it picks up the worktree's lefthook.yml."""
        wt = tmp_path / "my-feature"
        wt.mkdir()
        slug = wt.name
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(_MENTAT_DCJ, indent=2))

        container._ensure_devcontainer_json(wt, slug)

        result = json.loads(dcj.read_text())
        cmd = result["postCreateCommand"]
        assert "lefthook install" in cmd
        cd_pos = cmd.index(f"cd /workspaces/{slug}")
        lefthook_pos = cmd.index("lefthook install")
        assert lefthook_pos > cd_pos, "lefthook install must run after cd into worktree dir"
