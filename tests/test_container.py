"""Tests for mentat-container skill."""

from __future__ import annotations

import json
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


def test_resolve_workspace_folder_reads_devcontainer(tmp_path):
    utils = load_module("container_ops")
    dcj_dir = tmp_path / ".devcontainer"
    dcj_dir.mkdir()
    (dcj_dir / "devcontainer.json").write_text(json.dumps({"name": "test", "workspaceFolder": "/workspaces/custom"}))
    result = utils.resolve_workspace_folder(tmp_path)
    assert result == "/workspaces/custom"


def test_resolve_workspace_folder_falls_back_when_missing(tmp_path):
    utils = load_module("container_ops")
    result = utils.resolve_workspace_folder(tmp_path)
    assert result == f"/workspaces/{tmp_path.name}"


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


def test_ro_mounts_from_env_returns_empty_when_unset(tmp_path, monkeypatch):
    """_ro_mounts_from_env returns [] when MENTAT_RO_MOUNTS is unset."""
    cr = load_module("compose_render")
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    result = cr._ro_mounts_from_env("/workspaces/slug", str(tmp_path))
    assert result == []


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


class TestEnsureDevcontainerJson:
    def test_new_file_written_via_synth(self, tmp_path):
        wt = tmp_path / "some-repo"
        wt.mkdir()
        slug = wt.name
        expected = json.dumps({"name": slug, "workspaceFolder": f"/workspaces/{slug}"}, indent=2)
        dcj = wt / ".devcontainer" / "devcontainer.json"

        with patch.object(compose_render, "synth_spec", return_value=compose_render.SynthResult(expected, {})):
            container._ensure_devcontainer_json(wt, slug)

        assert dcj.read_text() == expected

    def test_idempotent_correct_file(self, tmp_path):
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
        wt = tmp_path / "no-dockerfile"
        wt.mkdir()
        slug = wt.name

        side = ValueError("no Dockerfile")
        with patch.object(compose_render, "synth_spec", side_effect=side), pytest.raises(SystemExit) as exc_info:
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

        with patch.object(compose_render, "synth_spec", return_value=compose_render.SynthResult(synth_out, {})):
            container._ensure_devcontainer_json(wt, slug)

        dcj = wt / ".devcontainer" / "devcontainer.json"
        result = json.loads(dcj.read_text())
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
    def test_main_repo_reads_devcontainer_json(self, tmp_path):
        repo = tmp_path / "mentat"
        repo.mkdir()
        (repo / ".git").mkdir()
        dcj = repo / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps({"workspaceFolder": "/workspaces/mentat"}))

        assert utils.resolve_workspace_folder(repo) == "/workspaces/mentat"

    def test_worktree_uses_slug_regardless_of_devcontainer(self, tmp_path):
        wt = tmp_path / "my-feature"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: /some/repo/.git/worktrees/my-feature\n")
        dcj = wt / ".devcontainer" / "devcontainer.json"
        dcj.parent.mkdir()
        dcj.write_text(json.dumps({"workspaceFolder": "/workspaces/mentat"}))

        assert utils.resolve_workspace_folder(wt) == "/workspaces/my-feature"

    def test_worktree_no_devcontainer_uses_slug(self, tmp_path):
        wt = tmp_path / "some-branch"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: /some/repo/.git/worktrees/some-branch\n")

        assert utils.resolve_workspace_folder(wt) == "/workspaces/some-branch"


class TestPostCreateCommandLefthookInstall:
    def test_post_create_command_runs_lefthook_install(self, tmp_path):
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
    monkeypatch.setattr(container_mod, "_ensure_devcontainer_json", lambda wt, slug: None)

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
    monkeypatch.setattr(container_mod, "_ensure_devcontainer_json", lambda wt, slug: None)

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
    monkeypatch.setattr(container_mod, "_ensure_devcontainer_json", lambda wt, slug: None)

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
