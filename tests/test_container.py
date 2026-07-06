"""Tests for mentat-container skill."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import compose_render
import container
import container_ops as utils
import pytest
from lib import devcontainer as _dc_mod

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-container/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _ok(stdout: str = "", returncode: int = 0) -> MagicMock:
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = ""
    return r


def _doctor_capture(container_mod, wt: Path) -> str:
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        container_mod.cmd_doctor(wt)
    return buf.getvalue()


_CID = "0" * 32


def _cs(slug: str) -> str:
    return f"{_CID}/{slug}"


def _override_dcj(wt: Path, slug: str) -> Path:
    from lib.chunk import override_config_dir

    repo = container._repo_root_for_wt(wt)
    return override_config_dir(repo, _cs(slug)) / "devcontainer.json"


# ── utils ───────────────────────────────────────────────────────────────────


def test_slug_for_cwd_from_worktree(tmp_path, monkeypatch):
    utils = load_module("container_ops")
    monkeypatch.chdir(tmp_path)

    def fake_run(cmd, **kwargs):
        class R:
            stdout = str(tmp_path) + "\n"
            returncode = 0

        return R()

    with patch("subprocess.run", fake_run):
        slug = utils.slug_for_cwd()
    assert slug == tmp_path.name


def test_workspace_folder_for_ignores_devcontainer_json(tmp_path):
    utils = load_module("container_ops")
    dcj_dir = tmp_path / ".devcontainer"
    dcj_dir.mkdir()
    (dcj_dir / "devcontainer.json").write_text(json.dumps({"name": "test", "workspaceFolder": "/workspaces/custom"}))
    result = utils.workspace_folder_for(tmp_path)
    assert result == f"/workspaces/{tmp_path.name}"


def test_resolve_workspace_folder_delegates_to_workspace_folder_for(tmp_path):
    utils = load_module("container_ops")
    result = utils.resolve_workspace_folder(tmp_path)
    assert result == f"/workspaces/{tmp_path.name}"


def test_resolve_workspace_folder_git_file_worktree_uses_name(tmp_path):
    ops = load_module("container_ops")
    (tmp_path / ".git").write_text("gitdir: ../main/.git/worktrees/wt")
    result = ops.resolve_workspace_folder(tmp_path)
    assert result == f"/workspaces/{tmp_path.name}"


def test_slug_for_cwd_git_fails_returns_cwd_name(tmp_path, monkeypatch):
    ops = load_module("container_ops")
    monkeypatch.chdir(tmp_path)

    def fake_run(cmd, **kw):
        class R:
            returncode = 1
            stdout = ""

        return R()

    with patch("subprocess.run", fake_run):
        slug = ops.slug_for_cwd()
    assert slug == tmp_path.name


def test_container_id_for_docker_fails_returns_daemon_down():
    ops = load_module("container_ops")

    def fake_run(cmd, **kw):
        class R:
            returncode = 1
            stdout = ""

        return R()

    with patch("subprocess.run", fake_run):
        result = ops.container_id_for("my-slug")
        # DAEMON_DOWN sentinel: falsy but not None — daemon unreachable distinct from no container
        assert not result
        assert result is not None


def test_container_id_for_empty_output_returns_none():
    ops = load_module("container_ops")

    def fake_run(cmd, **kw):
        class R:
            returncode = 0
            stdout = ""

        return R()

    with patch("subprocess.run", fake_run):
        assert ops.container_id_for("my-slug") is None


def test_container_id_for_returns_first_cid():
    ops = load_module("container_ops")

    def fake_run(cmd, **kw):
        class R:
            returncode = 0
            stdout = "abc123\ndef456\n"

        return R()

    with patch("subprocess.run", fake_run):
        assert ops.container_id_for("my-slug") == "abc123"


def test_assert_safe_directory_git_fails_raises_systemexit():
    ops = load_module("container_ops")

    def fake_run(cmd, **kw):
        class R:
            returncode = 1
            stdout = ""

        return R()

    with patch("subprocess.run", fake_run):
        import pytest as _pytest

        with _pytest.raises(SystemExit) as exc_info:
            ops.assert_safe_directory()
        assert exc_info.value.code == 2


def test_assert_safe_directory_git_succeeds_no_exit():
    ops = load_module("container_ops")

    def fake_run(cmd, **kw):
        class R:
            returncode = 0
            stdout = ".git"

        return R()

    with patch("subprocess.run", fake_run):
        ops.assert_safe_directory()  # must not raise


# ── compose_render ────────────────────────────────────────────────────────────


def test_compose_render_pure_returns_string(tmp_path):
    cs = load_module("compose_render")
    compose_yml = tmp_path / "docker-compose.yml"
    compose_yml.write_text("services:\n  app:\n    build: .\n    volumes:\n      - ..:/workspaces/app\n")
    result = cs.synth_spec(tmp_path).devcontainer_json
    assert isinstance(result, str)
    data = json.loads(result)
    assert "workspaceFolder" in data
    assert "service" in data


def test_compose_render_no_side_effects(tmp_path):
    cs = load_module("compose_render")
    compose_yml = tmp_path / "docker-compose.yml"
    compose_yml.write_text("services:\n  app:\n    build: .\n    volumes:\n      - ..:/workspaces/app\n")
    before = set(tmp_path.rglob("*"))
    cs.synth_spec(tmp_path)
    after = set(tmp_path.rglob("*"))
    assert before == after, f"synth_spec created files: {after - before}"


# ── container CLI ─────────────────────────────────────────────────────────


def test_container_run_asserts_up(tmp_path, capsys):
    """run subcommand must fail with informative error when no container running.

    Call cmd_run in-process so the no-container patch actually applies — a prior
    subprocess form left the child reading ambient docker state, which made the
    test pass/fail by environment (e.g. green except inside a live worktree
    container, where the commit gate runs the suite).
    """
    container = load_module("container")

    with patch.object(container.utils, "container_id_for", return_value=None):
        rc = container.cmd_run(tmp_path, "echo hi")

    captured = capsys.readouterr()
    assert rc != 0
    assert "not running" in captured.err.lower() or "container" in captured.err.lower()


def test_doctor_names_missing_path(tmp_path, monkeypatch, capsys):
    """doctor output names a path that is missing."""
    container_mod = load_module("container")

    # Patch container_id_for on the utils module imported by container
    with patch.object(container_mod.utils, "container_id_for", return_value=None):
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                container_mod.cmd_doctor(tmp_path)
            except SystemExit:
                pass
        output = buf.getvalue()

    # Doctor must mention the container is not running
    assert "not running" in output.lower() or "no container" in output.lower() or "container" in output.lower()


# ── S24: doctor 6-section output ──────────────────────────────────────────────


def test_doctor_emits_all_six_sections(tmp_path):
    """cmd_doctor must output all 6 section headers."""
    container_mod = load_module("container")
    import io
    from contextlib import redirect_stdout
    from unittest.mock import MagicMock

    fake_docker_run = MagicMock()
    fake_docker_run.return_value.returncode = 1  # daemon not running → simple path
    fake_docker_run.return_value.stdout = ""

    with patch.object(container_mod.utils, "container_id_for", return_value=None):
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                container_mod.cmd_doctor(tmp_path)
            output = buf.getvalue()

    for section in ("[host]", "[container]", "[harness]", "[companions]", "[mentat state]", "[tests]"):
        assert section in output, f"missing section {section!r} in doctor output"


def test_doctor_arch_shown(tmp_path):
    """Doctor [host] section must show arch."""
    container_mod = load_module("container")
    import io
    from contextlib import redirect_stdout

    with patch.object(container_mod.utils, "container_id_for", return_value=None):
        with patch(
            "subprocess.run",
            return_value=__import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(returncode=1, stdout=""),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                container_mod.cmd_doctor(tmp_path)
            output = buf.getvalue()

    assert "arch" in output


# ── S25: compose render template ──────────────────────────────────────────────


def test_render_template_substitutes_vars(tmp_path):
    """render_template must substitute all three variables deterministically."""
    cr = load_module("compose_render")
    tmpl = tmp_path / "compose.yml.tmpl"
    tmpl.write_text("platform: linux/${arch}\nvolumes:\n  - ..:${workspace_folder}\nimage: ${image_tag}\n")
    result = cr.render_template(tmpl, workspace_folder="/workspaces/slug", arch="amd64", image_tag="latest")
    assert "linux/amd64" in result
    assert "/workspaces/slug" in result
    assert "latest" in result
    assert "${" not in result


def test_render_template_deterministic(tmp_path):
    """render_template returns same output for same inputs."""
    cr = load_module("compose_render")
    tmpl = tmp_path / "compose.yml.tmpl"
    tmpl.write_text("arch: ${arch}\ntag: ${image_tag}\nws: ${workspace_folder}\n")
    r1 = cr.render_template(tmpl, workspace_folder="/ws/x", arch="arm64", image_tag="v1")
    r2 = cr.render_template(tmpl, workspace_folder="/ws/x", arch="arm64", image_tag="v1")
    assert r1 == r2


def test_synth_uses_compose_tmpl_when_present(tmp_path, monkeypatch):
    """synth_spec() picks template path and returns valid devcontainer.json."""
    import json as _json

    cr = load_module("compose_render")
    dc_dir = tmp_path / ".devcontainer"
    dc_dir.mkdir()
    tmpl = dc_dir / "compose.yml.tmpl"
    tmpl.write_text("platform: linux/${arch}\nvolumes:\n  - ..:${workspace_folder}\nimage: ${image_tag}\n")

    with patch(
        "subprocess.run",
        return_value=__import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(returncode=0, stdout="amd64\n"),
    ):
        monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
        result = cr.synth_spec(tmp_path).devcontainer_json

    data = _json.loads(result)
    assert data["name"] == tmp_path.name
    assert "dockerComposeFile" in data


# ── S26: read-only test manifest ──────────────────────────────────────────────


def test_ro_mounts_from_env_warns_when_unset(tmp_path, monkeypatch, capsys):
    """_ro_mounts_from_env logs when MENTAT_RO_MOUNTS is unset."""
    cr = load_module("compose_render")
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    result = cr._ro_mounts_from_env("/workspaces/slug", str(tmp_path))
    assert result == []
    assert "MENTAT_RO_MOUNTS unset" in capsys.readouterr().err


def test_ro_mounts_from_env_returns_mount_strings(tmp_path, monkeypatch):
    """_ro_mounts_from_env returns bind-mount strings for each path."""
    cr = load_module("compose_render")
    import json as _json

    monkeypatch.setenv("MENTAT_RO_MOUNTS", _json.dumps(["tests/test_foo.py"]))
    result = cr._ro_mounts_from_env("/workspaces/slug", str(tmp_path))
    assert len(result) == 1
    assert "tests/test_foo.py" in result[0]
    assert "readonly" in result[0]


# ── devcontainer / worktree tests ─────────────────────────────────────────────

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


class TestWriteOverrideConfig:
    def test_new_file_written_via_synth(self, tmp_path):
        wt = tmp_path / "some-repo"
        wt.mkdir()
        slug = wt.name
        expected = json.dumps({"name": slug, "workspaceFolder": f"/workspaces/{slug}"}, indent=2)

        with patch.object(compose_render, "synth_spec", return_value=compose_render.SynthResult(expected, {})):
            container._write_override_config(wt, _cs(slug))

        override = _override_dcj(wt, slug)
        assert override.read_text() == expected
        assert not (wt / ".devcontainer" / "devcontainer.json").exists()

    def test_idempotent_tracked_file_untouched(self, tmp_path):
        wt = tmp_path / "mentat"
        wt.mkdir()
        slug = wt.name
        data = dict(_MENTAT_DCJ, name=slug, workspaceFolder=f"/workspaces/{slug}")
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(data, indent=2))
        mtime = dcj.stat().st_mtime_ns

        container._write_override_config(wt, _cs(slug))

        assert dcj.stat().st_mtime_ns == mtime

    def test_stale_worktree_workspace_folder_in_override(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        slug = wt.name
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(_MENTAT_DCJ, indent=2))

        container._write_override_config(wt, _cs(slug))

        result = json.loads(_override_dcj(wt, slug).read_text())
        assert result["workspaceFolder"] == f"/workspaces/{slug}"
        assert result["name"] == slug

    def test_stale_worktree_patches_mount_and_commands_in_override(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        slug = wt.name
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(_MENTAT_DCJ, indent=2))

        container._write_override_config(wt, _cs(slug))

        result = json.loads(_override_dcj(wt, slug).read_text())
        assert f"target=/workspaces/{slug}" in result["workspaceMount"]
        assert f"/workspaces/{slug}" in result["postCreateCommand"]

    def test_correct_worktree_tracked_file_not_rewritten(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        slug = wt.name
        data = {"name": slug, "workspaceFolder": f"/workspaces/{slug}"}
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(data, indent=2))
        mtime = dcj.stat().st_mtime_ns

        container._write_override_config(wt, _cs(slug))

        assert dcj.stat().st_mtime_ns == mtime

    def test_synth_value_error_exits(self, tmp_path):
        wt = tmp_path / "no-dockerfile"
        wt.mkdir()
        slug = wt.name

        side = ValueError("no Dockerfile")
        with patch.object(compose_render, "synth_spec", side_effect=side), pytest.raises(SystemExit) as exc_info:
            container._write_override_config(wt, _cs(slug))

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


class TestWriteOverrideConfigGitMount:
    def test_adds_git_mount_when_patching_stale_worktree(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        main_git = str(tmp_path / "main" / ".git")
        (wt / ".git").write_text(f"gitdir: {main_git}/worktrees/my-feature\n")
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(_MENTAT_DCJ, indent=2))

        container._write_override_config(wt, _cs("my-feature"))

        result = json.loads(_override_dcj(wt, "my-feature").read_text())
        expected_mount = f"source={main_git},target={main_git},type=bind"
        assert expected_mount in result.get("mounts", [])

    def test_no_mounts_field_for_main_repo(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        (wt / ".git").mkdir()
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(_MENTAT_DCJ, indent=2))

        container._write_override_config(wt, _cs("my-feature"))

        result = json.loads(_override_dcj(wt, "my-feature").read_text())
        assert "mounts" not in result

    def test_idempotent_when_mount_already_present(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        main_git = str(tmp_path / "main" / ".git")
        (wt / ".git").write_text(f"gitdir: {main_git}/worktrees/my-feature\n")
        expected_mount = f"source={main_git},target={main_git},type=bind"
        data = {
            "name": "my-feature",
            "workspaceFolder": f"/workspaces/{_CID}/my-feature",
            "mounts": [expected_mount],
        }
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(data, indent=2))
        mtime = dcj.stat().st_mtime_ns

        container._write_override_config(wt, _cs("my-feature"))

        assert dcj.stat().st_mtime_ns == mtime

    def test_adds_mount_to_synth_output_for_worktree(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        main_git = str(tmp_path / "main" / ".git")
        (wt / ".git").write_text(f"gitdir: {main_git}/worktrees/my-feature\n")
        slug = wt.name
        synth_out = json.dumps({"name": slug, "workspaceFolder": f"/workspaces/{slug}"})

        with patch.object(compose_render, "synth_spec", return_value=compose_render.SynthResult(synth_out, {})):
            container._write_override_config(wt, _cs(slug))

        result = json.loads(_override_dcj(wt, slug).read_text())
        expected_mount = f"source={main_git},target={main_git},type=bind"
        assert expected_mount in result.get("mounts", [])


class TestCmdDown:
    def test_down_removes_running_container(self, monkeypatch):
        ran: list = []

        def fake_run(cmd, **kw):
            ran.append(cmd)
            r = MagicMock()
            r.returncode = 0
            if len(cmd) > 1 and cmd[1] == "ps" and "status=exited" not in cmd:
                r.stdout = "abc123\n"
            else:
                r.stdout = ""
            return r

        monkeypatch.setattr(container.subprocess, "run", fake_run)
        rc = container.cmd_down(slug="my-feature")
        assert rc == 0
        assert any("rm" in c and "-f" in c and "abc123" in c for c in ran)

    def test_down_removes_stopped_container(self, monkeypatch):
        ran: list = []

        def fake_run(cmd, **kw):
            ran.append(cmd)
            r = MagicMock()
            r.returncode = 0
            if len(cmd) > 1 and cmd[1] == "ps" and "-aq" in cmd:
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
    def test_main_repo_uses_directory_name(self, tmp_path):
        repo = tmp_path / "mentat"
        repo.mkdir()
        (repo / ".git").mkdir()
        dcj = repo / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps({"workspaceFolder": "/workspaces/mentat"}))

        assert utils.workspace_folder_for(repo) == "/workspaces/mentat"

    def test_worktree_uses_slug_not_devcontainer_json(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: /some/repo/.git/worktrees/my-feature\n")
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps({"workspaceFolder": "/workspaces/mentat"}))

        assert utils.workspace_folder_for(wt) == "/workspaces/my-feature"

    def test_chunk_keyed_worktree_uses_chunk_path(self, tmp_path):
        wt = tmp_path / ".mentat" / "worktrees" / "abc" / "some-branch"
        wt.mkdir(parents=True)
        (wt / ".git").write_text("gitdir: /some/repo/.git/worktrees/some-branch\n")

        assert utils.workspace_folder_for(wt) == "/workspaces/abc/some-branch"


class TestPostCreateCommandLefthookInstall:
    def test_post_create_command_runs_lefthook_install(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        slug = wt.name
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(_MENTAT_DCJ, indent=2))

        container._write_override_config(wt, _cs(slug))

        result = json.loads(_override_dcj(wt, slug).read_text())
        assert "lefthook install" in result["postCreateCommand"]

    def test_lefthook_install_path_rewrite(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        slug = wt.name
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps(_MENTAT_DCJ, indent=2))

        container._write_override_config(wt, _cs(slug))

        result = json.loads(_override_dcj(wt, slug).read_text())
        cmd = result["postCreateCommand"]
        assert "lefthook install" in cmd
        cd_pos = cmd.index(f"cd /workspaces/{slug}")
        lefthook_pos = cmd.index("lefthook install")
        assert lefthook_pos > cd_pos, "lefthook install must run after cd into worktree dir"


# ── S2: list/object postCreateCommand form ────────────────────────────────────


def test_write_override_config_list_command_not_replaced(tmp_path):
    """List-form postCreateCommand must not raise and must remain unchanged."""
    wt = tmp_path / "my-feature"
    wt.mkdir()
    slug = wt.name
    dcj = wt / ".devcontainer" / "devcontainer.json"
    dcj.parent.mkdir()
    data = {
        "name": "mentat",
        "workspaceFolder": "/workspaces/mentat",
        "postCreateCommand": ["echo", "hi"],
    }
    dcj.write_text(json.dumps(data, indent=2))

    container._write_override_config(wt, _cs(slug))

    result = json.loads(_override_dcj(wt, slug).read_text())
    assert result["postCreateCommand"] == ["echo", "hi"], "list-form command must not be mutated"
    assert json.loads(dcj.read_text())["postCreateCommand"] == ["echo", "hi"]
    assert result["workspaceFolder"] == f"/workspaces/{slug}"


def test_container_cmd_down_delegates_to_devcontainer(monkeypatch):
    down_calls: list[str] = []
    monkeypatch.setattr(_dc_mod, "down", lambda slug: down_calls.append(slug) or True)
    container.cmd_down(slug="test-slug")
    assert down_calls == ["test-slug"]


# ── CT4: safe .git reads + all containers removed ────────────────────────────


def test_git_mount_for_worktree_degrades_on_non_utf8_git_file(tmp_path):
    """_git_mount_for_worktree must return None on non-UTF-8 .git content, not raise."""
    container_mod = load_module("container")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_bytes(b"\xff\xfe\x00")  # invalid UTF-8

    result = container_mod._git_mount_for_worktree(wt)
    assert result is None, "_git_mount_for_worktree must degrade to None on UnicodeDecodeError"


def test_main_repo_root_for_wt_degrades_on_non_utf8_git_file(tmp_path):
    """_main_repo_root_for_wt must return None on non-UTF-8 .git content, not raise."""
    container_mod = load_module("container")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_bytes(b"\xff\xfe\x00")  # invalid UTF-8

    result = container_mod._main_repo_root_for_wt(wt)
    assert result is None, "_main_repo_root_for_wt must degrade to None on UnicodeDecodeError"


# ── CT2: docker start one ID per arg ─────────────────────────────────────────


def test_cmd_up_starts_multiple_stopped_containers_as_separate_args(tmp_path, monkeypatch):
    """docker start must receive each container ID as a separate argv element, not newline-joined."""
    container_mod = load_module("container")

    docker_start_calls: list[list[str]] = []
    started = [False]

    def fake_cid(slug):
        return "cid1" if started[0] else None

    def fake_run(cmd, **kw):
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        if isinstance(cmd, list) and len(cmd) > 1:
            if cmd[1] == "start":
                docker_start_calls.append(list(cmd))
                started[0] = True
            elif cmd[1] == "ps" and "status=exited" in cmd:
                r.stdout = "cid1\ncid2\n"  # two stopped containers
        return r

    monkeypatch.setattr(container_mod, "_host_runtime", lambda: False)
    monkeypatch.setattr(container_mod.utils, "container_id_for", fake_cid)
    monkeypatch.setattr(container_mod.subprocess, "run", fake_run)

    container_mod.cmd_up(tmp_path)

    assert docker_start_calls, "docker start must be called"
    start_cmd = docker_start_calls[0]
    assert "cid1" in start_cmd, "cid1 must be a distinct argv element in docker start"
    assert "cid2" in start_cmd, "cid2 must be a distinct argv element in docker start"
    assert not any("\n" in arg for arg in start_cmd), "no newline-joined IDs in docker start"


# ── CT1: up must fail when bring-up fails ─────────────────────────────────────


def test_cmd_up_fails_when_bringup_fails_despite_stale_container(tmp_path, monkeypatch):
    """cmd_up must return non-zero when devcontainer up fails, even if a stale container exists."""
    container_mod = load_module("container")

    call_count = [0]

    def fake_cid(slug):
        call_count[0] += 1
        if call_count[0] == 1:
            return None  # first check: no running container
        return "stale-cid"  # subsequent checks: stale container present

    def fake_run(cmd, **kw):
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        if isinstance(cmd, list) and "devcontainer" in cmd:
            r.returncode = 1  # bring-up command fails
        return r

    monkeypatch.setattr(container_mod, "_host_runtime", lambda: False)
    monkeypatch.setattr(container_mod.utils, "container_id_for", fake_cid)
    monkeypatch.setattr(container_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(container_mod, "_write_override_config", lambda wt, slug: None)

    rc = container_mod.cmd_up(tmp_path)
    assert rc != 0, "cmd_up must return non-zero when bring-up command fails"


# ── C1: devcontainer CLI missing ──────────────────────────────────────────────


def test_cmd_up_devcontainer_cli_missing_returns_failure(tmp_path, monkeypatch, capsys):
    """cmd_up must return EX_FAILURE (not traceback) when devcontainer CLI is not on PATH."""
    container_mod = load_module("container")

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and cmd and cmd[0] == "devcontainer":
            raise FileNotFoundError("No such file or directory: 'devcontainer'")
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        return r

    monkeypatch.setattr(container_mod, "_host_runtime", lambda: False)
    monkeypatch.setattr(container_mod.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(container_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(container_mod, "_write_override_config", lambda wt, slug: None)

    rc = container_mod.cmd_up(tmp_path)

    captured = capsys.readouterr()
    assert rc != 0, "cmd_up must return non-zero when devcontainer CLI is absent"
    assert captured.err, "cmd_up must emit an actionable message to stderr"
    assert "devcontainer" in captured.err.lower() or "path" in captured.err.lower()


# ── C2: widened stopped-container detection ───────────────────────────────────


def test_cmd_up_created_container_detected_fails_loud_when_unusable(tmp_path, monkeypatch):
    """created-status containers must be detected; if unusable after start, return non-zero."""
    container_mod = load_module("container")

    def fake_run(cmd, **kw):
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        if not isinstance(cmd, list):
            return r
        # Return a container only when the widened query includes status=created
        if len(cmd) > 1 and cmd[1] == "ps" and any("status=created" in str(a) for a in cmd):
            r.stdout = "cre123\n"
        return r

    monkeypatch.setattr(container_mod, "_host_runtime", lambda: False)
    # container_id_for always None — docker start leaves no usable container
    monkeypatch.setattr(container_mod.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(container_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(container_mod, "_write_override_config", lambda wt, slug: None)

    rc = container_mod.cmd_up(tmp_path)

    assert rc != 0, "cmd_up must not return 0 when created container is unusable after start"


# ── C3: docker start stderr surfaced ──────────────────────────────────────────


def test_cmd_up_docker_start_failure_does_not_raise_and_surfaces_stderr(tmp_path, monkeypatch, capsys):
    """Failed docker start must not raise CalledProcessError — must return non-zero with stderr shown."""
    container_mod = load_module("container")

    import subprocess as _sp

    def fake_run(cmd, **kw):
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        if not isinstance(cmd, list):
            return r
        if len(cmd) > 1 and cmd[1] == "ps":
            r.stdout = "cid_bad\n"
        elif len(cmd) > 1 and cmd[1] == "start":
            r.returncode = 1
            r.stderr = "Error: no such container: cid_bad\n"
            if kw.get("check"):
                raise _sp.CalledProcessError(1, cmd, stderr=r.stderr)
        return r

    monkeypatch.setattr(container_mod, "_host_runtime", lambda: False)
    monkeypatch.setattr(container_mod.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(container_mod.subprocess, "run", fake_run)

    rc = container_mod.cmd_up(tmp_path)

    captured = capsys.readouterr()
    assert rc != 0, "failed docker start must return non-zero"
    assert "Traceback" not in captured.err, "must not leak CalledProcessError traceback"
    assert "no such container" in captured.err or "cid_bad" in captured.err


# ── C4: broken symlink at dst does not raise ──────────────────────────────────


def test_cmd_up_broken_symlink_at_dst_does_not_raise(tmp_path, monkeypatch):
    """Dangling symlink at dst must not raise FileExistsError during cold-start symlink step."""
    container_mod = load_module("container")

    # Main repo with a vendor dir
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    (main_repo / "vendor").mkdir()

    # Worktree with a dangling symlink at vendor
    wt = tmp_path / "wt"
    wt.mkdir()
    broken_link = wt / "vendor"
    broken_link.symlink_to(tmp_path / "nonexistent_target")  # dangling

    def fake_run(cmd, **kw):
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        return r

    monkeypatch.setattr(container_mod, "_host_runtime", lambda: False)
    monkeypatch.setattr(container_mod.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(container_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(container_mod, "_write_override_config", lambda wt, slug: None)
    monkeypatch.setattr(container_mod, "_main_repo_root_for_wt", lambda wt: main_repo)

    # Must not raise FileExistsError — must return an int
    rc = container_mod.cmd_up(wt)
    assert isinstance(rc, int), "cmd_up must return int, not raise on broken symlink"


# ── S1: subprocess timeout bounds ─────────────────────────────────────────────


def test_container_id_for_timeout_returns_daemon_down(monkeypatch):
    """container_id_for must return DAEMON_DOWN (not hang) when docker ps times out."""
    ops = load_module("container_ops")
    import subprocess as _sp

    def fake_run(cmd, **kw):
        raise _sp.TimeoutExpired(cmd, 30)

    with patch("subprocess.run", fake_run):
        result = ops.container_id_for("any-slug")
    # DAEMON_DOWN: falsy but not None — timeout = daemon unreachable
    assert not result
    assert result is not None


def test_cmd_up_ps_aq_timeout_returns_failure(tmp_path, monkeypatch, capsys):
    """cmd_up must return non-zero and not hang when docker ps -aq times out."""
    container_mod = load_module("container")
    import subprocess as _sp

    call_n = [0]

    def fake_run(cmd, **kw):
        call_n[0] += 1
        # First call is container_id_for (via utils); subsequent ps -aq times out
        if isinstance(cmd, list) and cmd[1:3] == ["ps", "-aq"]:
            raise _sp.TimeoutExpired(cmd, 30)
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        return r

    monkeypatch.setattr(container_mod, "_host_runtime", lambda: False)
    monkeypatch.setattr(container_mod.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(container_mod.subprocess, "run", fake_run)

    rc = container_mod.cmd_up(tmp_path)
    assert rc != 0


def test_cmd_up_devcontainer_up_timeout_returns_failure(tmp_path, monkeypatch, capsys):
    """cmd_up must return non-zero and emit message when devcontainer up times out."""
    container_mod = load_module("container")
    import subprocess as _sp

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and cmd and cmd[0] == "devcontainer":
            raise _sp.TimeoutExpired(cmd, 900)
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        return r

    monkeypatch.setattr(container_mod, "_host_runtime", lambda: False)
    monkeypatch.setattr(container_mod.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(container_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(container_mod, "_write_override_config", lambda wt, slug: None)

    rc = container_mod.cmd_up(tmp_path)
    captured = capsys.readouterr()
    assert rc != 0
    assert captured.err, "timeout must emit diagnostic to stderr"


# ── S3: daemon-down distinct from container-absent ────────────────────────────


def test_cmd_run_daemon_down_no_up_first_message(tmp_path, monkeypatch, capsys):
    """When docker ps fails (daemon unreachable), run must NOT say 'run up first'."""
    container_mod = load_module("container")

    monkeypatch.setattr(container_mod, "_host_runtime", lambda: False)
    monkeypatch.setattr(container_mod.utils, "container_id_for", lambda slug: container_mod.utils.DAEMON_DOWN)

    rc = container_mod.cmd_run(tmp_path, "echo hi")

    captured = capsys.readouterr()
    assert rc != 0
    assert "mentat-container up" not in captured.err, "daemon-down path must not say 'run mentat-container up first'"
    assert "daemon" in captured.err.lower() or "docker" in captured.err.lower()


# ── _warn_host_runtime_once OSError suppression ───────────────────────────────


def test_warn_host_runtime_once_swallows_marker_oserror(tmp_path, capsys):
    """A failed marker write is best-effort — it must not raise (lines 61-62)."""
    container = load_module("container")

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("pathlib.Path.mkdir", side_effect=OSError("read-only fs")),
    ):
        container._warn_host_runtime_once("some-slug")  # must not raise

    assert "ADR-0004" in capsys.readouterr().err


# ── _git_root ─────────────────────────────────────────────────────────────────


def test_git_root_returns_toplevel(tmp_path):
    """_git_root returns the rev-parse toplevel (lines 71-79 success branch)."""
    container = load_module("container")

    with patch.object(container.subprocess, "run", return_value=_ok(stdout=f"{tmp_path}\n")):
        result = container._git_root()

    assert result == tmp_path


def test_git_root_not_in_worktree_exits(capsys):
    """_git_root exits when not inside a git worktree (lines 76-78)."""
    container = load_module("container")

    with patch.object(container.subprocess, "run", return_value=_ok(returncode=1)):
        with pytest.raises(SystemExit) as exc:
            container._git_root()

    assert exc.value.code != 0
    assert "git worktree" in capsys.readouterr().err


# ── _git_mount_for_worktree / _main_repo_root_for_wt parsing ──────────────────


def test_git_mount_for_worktree_non_gitdir_content_returns_none(tmp_path):
    """A .git file that is not a gitdir pointer yields None (line 92)."""
    container = load_module("container")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("ref: refs/heads/main\n")

    assert container._git_mount_for_worktree(wt) is None


def test_main_repo_root_for_wt_returns_repo_root(tmp_path):
    """_main_repo_root_for_wt walks up three parents from gitdir (lines 107-110)."""
    container = load_module("container")
    wt = tmp_path / "my-feature"
    wt.mkdir()
    main_git = tmp_path / "main" / ".git"
    (wt / ".git").write_text(f"gitdir: {main_git}/worktrees/my-feature\n")

    result = container._main_repo_root_for_wt(wt)

    assert result == (tmp_path / "main")


def test_main_repo_root_for_wt_non_gitdir_returns_none(tmp_path):
    """Non-gitdir .git content yields None in _main_repo_root_for_wt (line 107)."""
    container = load_module("container")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("ref: refs/heads/main\n")

    assert container._main_repo_root_for_wt(wt) is None


# ── _write_override_config mount-only patch (139->148) ─────────────────────


def test_write_override_config_adds_mount_only_when_ws_ok(tmp_path):
    """workspaceFolder already correct but git mount missing → only mount appended.

    Covers the ws_ok-True / mount_ok-False branch (139->148): the workspaceFolder
    block is skipped, but the git mount is still added.
    """
    container = load_module("container")
    wt = tmp_path / "my-feature"
    wt.mkdir()
    main_git = str(tmp_path / "main" / ".git")
    (wt / ".git").write_text(f"gitdir: {main_git}/worktrees/my-feature\n")
    dcj = wt / ".devcontainer" / "devcontainer.json"
    dcj.parent.mkdir()
    # workspaceFolder already correct, but no mounts key yet.
    dcj.write_text(json.dumps({"name": "my-feature", "workspaceFolder": "/workspaces/my-feature"}, indent=2))

    container._write_override_config(wt, _cs("my-feature"))

    result = json.loads(_override_dcj(wt, "my-feature").read_text())
    expected_mount = f"source={main_git},target={main_git},type=bind"
    assert expected_mount in result.get("mounts", [])
    assert result["workspaceFolder"] == "/workspaces/my-feature"


# ── cmd_up running-container fast path (201-202) ──────────────────────────────


def test_cmd_up_running_container_ensures_safe_dir(tmp_path, monkeypatch):
    """When a container is already running, cmd_up just ensures safe.directory."""
    container = load_module("container")
    safe_calls: list[str] = []

    monkeypatch.setattr(container, "_host_runtime", lambda: False)
    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: "running-cid")
    monkeypatch.setattr(container.utils, "workspace_folder_for", lambda wt: "/workspaces/wt")
    monkeypatch.setattr(container, "_ensure_safe_directory", lambda ws, cid: safe_calls.append(cid))

    rc = container.cmd_up(tmp_path)

    assert rc == 0
    assert safe_calls == ["running-cid"]


# ── docker start timeout (235-237) ────────────────────────────────────────────


def test_cmd_up_docker_start_timeout_returns_unavailable(tmp_path, monkeypatch, capsys):
    """A docker start timeout returns EX_UNAVAILABLE with a diagnostic."""
    container = load_module("container")

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "ps":
            return _ok(stdout="stale-cid\n")
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "start":
            raise subprocess.TimeoutExpired(cmd, 30)
        return _ok()

    monkeypatch.setattr(container, "_host_runtime", lambda: False)
    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(container.utils, "workspace_folder_for", lambda wt: "/workspaces/wt")
    monkeypatch.setattr(container.subprocess, "run", fake_run)

    rc = container.cmd_up(tmp_path)

    assert rc == container.EX_UNAVAILABLE
    assert "docker start timed out" in capsys.readouterr().err


# ── cold-start symlink + .env copy (264, 268) ─────────────────────────────────


def test_cmd_up_cold_start_symlinks_and_copies_env(tmp_path, monkeypatch):
    """Cold start symlinks vendor/node_modules and copies .env from the main repo."""
    container = load_module("container")

    main_repo = tmp_path / "main"
    main_repo.mkdir()
    (main_repo / "vendor").mkdir()
    (main_repo / ".env").write_text("SECRET=1\n")

    wt = tmp_path / "wt"
    wt.mkdir()

    monkeypatch.setattr(container, "_host_runtime", lambda: False)
    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(container.utils, "workspace_folder_for", lambda wt: "/workspaces/wt")
    monkeypatch.setattr(container, "_write_override_config", lambda wt, slug: None)
    monkeypatch.setattr(container, "_main_repo_root_for_wt", lambda wt: main_repo)
    monkeypatch.setattr(container.subprocess, "run", lambda cmd, **kw: _ok())

    rc = container.cmd_up(wt)

    assert rc == 0
    assert (wt / "vendor").is_symlink()
    assert (wt / ".env").read_text() == "SECRET=1\n"


# ── git rev-parse timeout in cold start (279-280) ─────────────────────────────


def test_cmd_up_git_dir_timeout_degrades_to_empty(tmp_path, monkeypatch):
    """A git rev-parse --git-dir timeout leaves git_dir empty (no remote-env args)."""
    container = load_module("container")
    devcontainer_cmds: list[list[str]] = []

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and cmd[:2] == ["git", "rev-parse"]:
            raise subprocess.TimeoutExpired(cmd, 30)
        if isinstance(cmd, list) and cmd and cmd[0] == "devcontainer":
            devcontainer_cmds.append(list(cmd))
        return _ok()

    monkeypatch.setattr(container, "_host_runtime", lambda: False)
    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(container.utils, "workspace_folder_for", lambda wt: "/workspaces/wt")
    monkeypatch.setattr(container, "_write_override_config", lambda wt, slug: tmp_path / "override.json")
    monkeypatch.setattr(container, "_main_repo_root_for_wt", lambda wt: None)
    monkeypatch.setattr(container.subprocess, "run", fake_run)

    rc = container.cmd_up(tmp_path)

    assert rc == 0
    assert devcontainer_cmds, "devcontainer up must be invoked"
    assert "--remote-env" not in devcontainer_cmds[0], "no remote-env when git_dir empty"


# ── git_dir present → remote-env + final safe dir (291-292, 314) ──────────────


def test_cmd_up_cold_start_adds_remote_env_and_final_safe_dir(tmp_path, monkeypatch):
    """git_dir present → --remote-env GIT_DIR/GIT_WORK_TREE; final_cid → safe dir."""
    container = load_module("container")
    devcontainer_cmds: list[list[str]] = []
    safe_calls: list[str] = []
    cid_seq = iter([None, "final-cid"])

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and cmd[:3] == ["git", "rev-parse", "--git-dir"]:
            return _ok(stdout="/repo/.git\n")
        if isinstance(cmd, list) and cmd and cmd[0] == "devcontainer":
            devcontainer_cmds.append(list(cmd))
        return _ok()

    monkeypatch.setattr(container, "_host_runtime", lambda: False)
    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: next(cid_seq))
    monkeypatch.setattr(container.utils, "workspace_folder_for", lambda wt: "/workspaces/wt")
    monkeypatch.setattr(container, "_write_override_config", lambda wt, slug: None)
    monkeypatch.setattr(container, "_main_repo_root_for_wt", lambda wt: None)
    monkeypatch.setattr(container, "_ensure_safe_directory", lambda ws, cid: safe_calls.append(cid))
    monkeypatch.setattr(container.subprocess, "run", fake_run)

    rc = container.cmd_up(tmp_path)

    assert rc == 0
    flat = " ".join(devcontainer_cmds[0])
    assert "GIT_DIR=/repo/.git" in flat
    assert "GIT_WORK_TREE=/workspaces/wt" in flat
    assert safe_calls == ["final-cid"]


# ── _ensure_safe_directory issues a docker exec git config ────────────────────


def test_ensure_safe_directory_runs_git_config(monkeypatch):
    """_ensure_safe_directory execs `git config --global --add safe.directory`."""
    container = load_module("container")
    calls: list[list[str]] = []

    monkeypatch.setattr(container.subprocess, "run", lambda cmd, **kw: calls.append(list(cmd)) or _ok())

    container._ensure_safe_directory("/workspaces/wt", "cid-1")

    assert calls
    flat = " ".join(calls[0])
    assert "safe.directory" in flat
    assert "/workspaces/wt" in flat


# ── cmd_run happy path docker exec (336-351) ──────────────────────────────────


def test_cmd_run_execs_command_in_container(tmp_path, monkeypatch):
    """cmd_run docker-execs the command in the running container and returns its rc."""
    container = load_module("container")
    calls: list[list[str]] = []

    monkeypatch.setattr(container, "_host_runtime", lambda: False)
    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: "run-cid")
    monkeypatch.setattr(container.utils, "workspace_folder_for", lambda wt: "/workspaces/wt")
    monkeypatch.setattr(container.subprocess, "run", lambda cmd, **kw: calls.append(list(cmd)) or _ok(returncode=7))

    rc = container.cmd_run(tmp_path, "echo hi")

    assert rc == 7
    flat = " ".join(calls[0])
    assert "exec" in flat
    assert "run-cid" in flat
    assert "echo hi" in flat


# ── doctor [container] daemon running + emulation (380-409) ───────────────────


def test_doctor_container_running_no_emulation(tmp_path, monkeypatch):
    """Daemon up + container present + matching arch → emulation 'none'."""
    container = load_module("container")

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and cmd[:1] == ["uname"]:
            return _ok(stdout="arm64\n")
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "info":
            return _ok(returncode=0)
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "inspect":
            return _ok(stdout="linux/arm64\n")
        return _ok(returncode=1)

    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: "cid-1")
    monkeypatch.setattr(container.utils, "workspace_folder_for", lambda wt: "/workspaces/wt")
    monkeypatch.setattr(container.subprocess, "run", fake_run)

    output = _doctor_capture(container, tmp_path)

    assert "image platf" in output
    assert "none" in output  # emulation none
    assert "linux/arm64" in output


def test_doctor_container_running_arch_emulation_warns(tmp_path, monkeypatch):
    """Daemon up + arm64 host running an amd64 image → qemu emulation warning."""
    container = load_module("container")

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and cmd[:1] == ["uname"]:
            return _ok(stdout="arm64\n")
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "info":
            return _ok(returncode=0)
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "inspect":
            return _ok(stdout="linux/amd64\n")
        return _ok(returncode=1)

    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: "cid-1")
    monkeypatch.setattr(container.utils, "workspace_folder_for", lambda wt: "/workspaces/wt")
    monkeypatch.setattr(container.subprocess, "run", fake_run)

    rc = container.cmd_doctor(tmp_path)
    output = _doctor_capture(container, tmp_path)

    assert "qemu" in output
    assert rc == container.EX_FAILURE  # arch emulation is a warning → non-zero verdict


def test_doctor_container_inspect_timeout_unknown_platform(tmp_path, monkeypatch):
    """A docker inspect timeout reports image platform 'unknown' (397-398)."""
    container = load_module("container")

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and cmd[:1] == ["uname"]:
            return _ok(stdout="arm64\n")
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "info":
            return _ok(returncode=0)
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "inspect":
            raise subprocess.TimeoutExpired(cmd, 30)
        return _ok(returncode=1)

    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: "cid-1")
    monkeypatch.setattr(container.utils, "workspace_folder_for", lambda wt: "/workspaces/wt")
    monkeypatch.setattr(container.subprocess, "run", fake_run)

    output = _doctor_capture(container, tmp_path)

    assert "unknown" in output


def test_doctor_uname_timeout_arch_unknown(tmp_path, monkeypatch):
    """A uname timeout falls back to host_arch 'unknown' (508-509)."""
    container = load_module("container")

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and cmd[:1] == ["uname"]:
            raise subprocess.TimeoutExpired(cmd, 30)
        return _ok(returncode=1)

    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(container.subprocess, "run", fake_run)

    output = _doctor_capture(container, tmp_path)

    assert "unknown" in output


# ── doctor [harness]/[companions]/[mentat state]/[tests] ──────────────────────


def test_doctor_harness_and_state_present(tmp_path, monkeypatch):
    """Doctor harness/companions/mentat-state branches with everything present."""
    container = load_module("container")

    home = tmp_path / "home"
    # harness: ~/.claude with agents + skills, ~/.cursor present
    claude = home / ".claude"
    (claude / "agents").mkdir(parents=True)
    (claude / "agents" / "mentat-foo").mkdir()
    (claude / "skills").mkdir()
    (claude / "skills" / "mentat-bar").mkdir()
    (home / ".cursor").mkdir(parents=True)
    # companions present
    (claude / "skills" / "diagnose").mkdir()
    (claude / "skills" / "diagnose" / "SKILL.md").write_text("x\n")
    (claude / "plugins" / "marketplaces" / "caveman").mkdir(parents=True)
    # mentat state: ~/.mentat present with logs dir holding a session
    mentat = home / ".mentat"
    (mentat / "logs" / "sess1").mkdir(parents=True)

    plans = home / ".agents" / "plans"
    plans.mkdir(parents=True)
    manifest = {"closed": ["a.py", "b.py"], "open": ["b.py"]}
    (plans / "myplan.tests.json").write_text(json.dumps(manifest))

    monkeypatch.setattr(container.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: None)

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and cmd[:1] == ["uname"]:
            return _ok(stdout="arm64\n")
        if isinstance(cmd, list) and cmd[:2] == ["git", "rev-parse"]:
            return _ok(stdout=str(tmp_path / "repo") + "\n")
        return _ok(returncode=1)

    monkeypatch.setattr(container.subprocess, "run", fake_run)

    output = _doctor_capture(container, tmp_path)

    assert "claude-code" in output
    assert "mentat-* subagents linked" in output
    assert "cursor" in output
    assert "present" in output  # companions present
    assert "1 sessions" in output
    assert "1 ro-mounted, 1 open" in output  # tests manifest parsed


def test_doctor_companions_missing_advisory(tmp_path, monkeypatch):
    """Missing companions add an advisory and missing config a warning (445->447, 461)."""
    container = load_module("container")

    home = tmp_path / "home"
    home.mkdir()  # no .claude, no .cursor, no companions, no .mentat

    monkeypatch.setattr(container.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: None)

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and cmd[:1] == ["uname"]:
            return _ok(stdout="arm64\n")
        if isinstance(cmd, list) and cmd[:2] == ["git", "rev-parse"]:
            return _ok(returncode=1)  # not in a repo → repo config skipped
        return _ok(returncode=1)

    monkeypatch.setattr(container.subprocess, "run", fake_run)

    output = _doctor_capture(container, tmp_path)

    assert "missing — run mentat-install" in output
    assert "advisory" in output
    assert "logs dir" in output and "absent" in output


def test_doctor_manifest_parse_error_and_repo_config(tmp_path, monkeypatch):
    """A malformed test manifest is reported, and the repo config branch runs (467)."""
    container = load_module("container")

    home = tmp_path / "home"
    plans = home / ".agents" / "plans"
    plans.mkdir(parents=True)
    (plans / "broken.tests.json").write_text("not json {{{")

    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr(container.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: None)

    # Force config_status to emit a warning for both global and repo.
    import lib.config as _cfg

    monkeypatch.setattr(_cfg, "config_status", lambda d: ("warn-status", "config drift"))

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and cmd[:1] == ["uname"]:
            return _ok(stdout="arm64\n")
        if isinstance(cmd, list) and cmd[:2] == ["git", "rev-parse"]:
            return _ok(stdout=str(repo_root) + "\n")
        return _ok(returncode=1)

    monkeypatch.setattr(container.subprocess, "run", fake_run)

    rc = container.cmd_doctor(tmp_path)
    output = _doctor_capture(container, tmp_path)

    assert "manifest parse error" in output
    assert "config (repo)" in output
    assert rc == container.EX_FAILURE  # config warnings → non-zero verdict


def test_doctor_no_manifests_no_plans(tmp_path, monkeypatch):
    """Plans dir with no manifests, then with no plans dir at all (495-498)."""
    container = load_module("container")

    home = tmp_path / "home"
    plans = home / ".agents" / "plans"
    plans.mkdir(parents=True)  # exists but empty → "no test manifests"

    monkeypatch.setattr(container.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(
        container.subprocess,
        "run",
        lambda cmd, **kw: _ok(stdout="arm64\n") if cmd[:1] == ["uname"] else _ok(returncode=1),
    )

    output = _doctor_capture(container, tmp_path)
    assert "no test manifests" in output


# ── doctor daemon info raises (380-381) ───────────────────────────────────────


def test_doctor_daemon_info_filenotfound_marks_not_running(tmp_path, monkeypatch, capsys):
    """A docker info FileNotFoundError marks the daemon 'not running' (380-381)."""
    container = load_module("container")

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and cmd[:1] == ["uname"]:
            return _ok(stdout="arm64\n")
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "info":
            raise FileNotFoundError("docker not installed")
        return _ok(returncode=1)

    monkeypatch.setattr(container.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(container.subprocess, "run", fake_run)

    output = _doctor_capture(container, tmp_path)
    assert "not running" in output


# ── main() CLI dispatch (535-558) ─────────────────────────────────────────────


def test_main_dispatches_up(monkeypatch):
    container = load_module("container")
    monkeypatch.setattr("sys.argv", ["container.py", "up"])
    monkeypatch.setattr(container, "_git_root", lambda: Path("/tmp/wt"))
    with patch.object(container, "cmd_up", return_value=0) as mock, pytest.raises(SystemExit) as exc:
        container.main()
    assert exc.value.code == 0
    mock.assert_called_once_with(Path("/tmp/wt"))


def test_main_dispatches_run(monkeypatch):
    container = load_module("container")
    monkeypatch.setattr("sys.argv", ["container.py", "run", "echo", "hi"])
    monkeypatch.setattr(container, "_git_root", lambda: Path("/tmp/wt"))
    with patch.object(container, "cmd_run", return_value=3) as mock, pytest.raises(SystemExit) as exc:
        container.main()
    assert exc.value.code == 3
    mock.assert_called_once_with(Path("/tmp/wt"), "echo hi")


def test_main_dispatches_down_with_slug(monkeypatch):
    container = load_module("container")
    monkeypatch.setattr("sys.argv", ["container.py", "down", "--slug", "my-slug"])
    with patch.object(container, "cmd_down", return_value=0) as mock, pytest.raises(SystemExit) as exc:
        container.main()
    assert exc.value.code == 0
    mock.assert_called_once_with(slug="my-slug")


def test_main_dispatches_down_default_slug(monkeypatch):
    container = load_module("container")
    monkeypatch.setattr("sys.argv", ["container.py", "down"])
    monkeypatch.setattr(container, "_git_root", lambda: Path("/tmp/some-repo"))
    monkeypatch.setattr(container, "_chunk_slug_for_wt", lambda wt: wt.name)
    with patch.object(container, "cmd_down", return_value=0) as mock, pytest.raises(SystemExit) as exc:
        container.main()
    assert exc.value.code == 0
    mock.assert_called_once_with(slug="some-repo")


def test_main_dispatches_doctor(monkeypatch, tmp_path):
    container = load_module("container")
    monkeypatch.setattr("sys.argv", ["container.py", "doctor"])
    monkeypatch.setattr(container.Path, "cwd", classmethod(lambda cls: tmp_path))
    with patch.object(container, "cmd_doctor", return_value=0) as mock, pytest.raises(SystemExit) as exc:
        container.main()
    assert exc.value.code == 0
    mock.assert_called_once_with(tmp_path)


def test_main_unknown_cmd_falls_through(monkeypatch):
    """main() with a cmd matching no branch returns without sys.exit (557->exit)."""
    import argparse

    container = load_script(SCRIPTS / "container.py", "container_falls_through")
    ns = argparse.Namespace(cmd="bogus")
    monkeypatch.setattr(container.argparse.ArgumentParser, "parse_args", lambda self, *a, **k: ns)
    assert container.main() is None
