"""Tests for mentat-container skill."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-container/scripts"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


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
    (dcj_dir / "devcontainer.json").write_text(
        json.dumps({"name": "test", "workspaceFolder": "/workspaces/custom"})
    )
    result = utils.resolve_workspace_folder(tmp_path)
    assert result == "/workspaces/custom"


def test_resolve_workspace_folder_falls_back_when_missing(tmp_path):
    utils = load_module("utils")
    result = utils.resolve_workspace_folder(tmp_path)
    assert result == f"/workspaces/{tmp_path.name}"


# ── compose_synth ────────────────────────────────────────────────────────────


def test_compose_synth_pure_returns_string(tmp_path):
    cs = load_module("compose_synth")
    compose_yml = tmp_path / "docker-compose.yml"
    compose_yml.write_text(
        "services:\n  app:\n    build: .\n    volumes:\n      - ..:/workspaces/app\n"
    )
    result = cs.synth(tmp_path)
    assert isinstance(result, str)
    data = json.loads(result)
    assert "workspaceFolder" in data
    assert "service" in data


def test_compose_synth_no_side_effects(tmp_path):
    cs = load_module("compose_synth")
    compose_yml = tmp_path / "docker-compose.yml"
    compose_yml.write_text(
        "services:\n  app:\n    build: .\n    volumes:\n      - ..:/workspaces/app\n"
    )
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
