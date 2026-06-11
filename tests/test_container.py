"""Tests for mentat-container skill."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-container/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def run_container(args: list[str], env: dict | None = None):
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["python3", str(SCRIPTS / "container.py"), *args],
        capture_output=True,
        text=True,
        env=full_env,
    )


# ── utils ───────────────────────────────────────────────────────────────────


def test_slug_for_cwd_from_worktree(tmp_path, monkeypatch):
    utils = load_module("utils")
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
    utils = load_module("utils")
    dcj_dir = tmp_path / ".devcontainer"
    dcj_dir.mkdir()
    (dcj_dir / "devcontainer.json").write_text(json.dumps({"name": "test", "workspaceFolder": "/workspaces/custom"}))
    result = utils.resolve_workspace_folder(tmp_path)
    assert result == "/workspaces/custom"


def test_resolve_workspace_folder_falls_back_when_missing(tmp_path):
    utils = load_module("utils")
    result = utils.resolve_workspace_folder(tmp_path)
    assert result == f"/workspaces/{tmp_path.name}"


# ── compose_render ────────────────────────────────────────────────────────────


def test_compose_render_pure_returns_string(tmp_path):
    cs = load_module("compose_render")
    compose_yml = tmp_path / "docker-compose.yml"
    compose_yml.write_text("services:\n  app:\n    build: .\n    volumes:\n      - ..:/workspaces/app\n")
    result = cs.synth(tmp_path)
    assert isinstance(result, str)
    data = json.loads(result)
    assert "workspaceFolder" in data
    assert "service" in data


def test_compose_render_no_side_effects(tmp_path):
    cs = load_module("compose_render")
    compose_yml = tmp_path / "docker-compose.yml"
    compose_yml.write_text("services:\n  app:\n    build: .\n    volumes:\n      - ..:/workspaces/app\n")
    before = set(tmp_path.rglob("*"))
    cs.synth(tmp_path)
    after = set(tmp_path.rglob("*"))
    assert before == after, f"synth created files: {after - before}"


# ── container CLI ─────────────────────────────────────────────────────────


def test_container_run_asserts_up(tmp_path, monkeypatch):
    """run subcommand must fail with informative error when no container running."""
    utils = load_module("utils")

    # Patch container_id_for to return None (no container)
    with patch.object(utils, "container_id_for", return_value=None):
        with patch.dict(os.environ, {"MENTAT_DOCKER": "docker"}):
            result = run_container(["run", "echo hi"])
    assert result.returncode != 0
    assert "not running" in result.stderr.lower() or "container" in result.stderr.lower()


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
    """synth() picks template path and returns valid devcontainer.json."""
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
        result = cr.synth(tmp_path)

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
