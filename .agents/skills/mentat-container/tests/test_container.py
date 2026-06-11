import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import compose_render  # noqa: E402
import container  # noqa: E402

# Mirrors the committed mentat devcontainer.json — what every new worktree inherits
_MENTAT_DCJ = {
    "name": "mentat",
    "build": {"dockerfile": "Dockerfile"},
    "onCreateCommand": "sudo apt-get update",
    "postCreateCommand": "cd /workspaces/mentat && uv sync",
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
