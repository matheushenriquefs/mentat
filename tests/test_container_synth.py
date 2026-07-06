"""D16 — arch-aware --platform: resolve_platform helper + Dockerfile runArgs injection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import load_script

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-container/scripts"


def _load_override():
    return load_script(_SCRIPTS / "override.py", "override")


@pytest.fixture
def cr():
    return _load_override()


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("MENTAT_PLATFORM", raising=False)
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)


def test_resolve_platform_env_override_wins(cr, monkeypatch):
    monkeypatch.setenv("MENTAT_PLATFORM", "linux/amd64")
    with patch.object(cr.platform, "machine", return_value="arm64"):
        assert cr._resolve_platform() == "linux/amd64"


def test_resolve_platform_arm64(cr, clean_env):
    with patch.object(cr.platform, "machine", return_value="arm64"):
        assert cr._resolve_platform() == "linux/arm64"


def test_resolve_platform_aarch64(cr, clean_env):
    with patch.object(cr.platform, "machine", return_value="aarch64"):
        assert cr._resolve_platform() == "linux/arm64"


def test_resolve_platform_x86_64(cr, clean_env):
    with patch.object(cr.platform, "machine", return_value="x86_64"):
        assert cr._resolve_platform() == "linux/amd64"


def test_resolve_platform_amd64(cr, clean_env):
    with patch.object(cr.platform, "machine", return_value="amd64"):
        assert cr._resolve_platform() == "linux/amd64"


def test_resolve_platform_unknown_returns_none(cr, clean_env):
    with patch.object(cr.platform, "machine", return_value="riscv64"):
        assert cr._resolve_platform() is None


def test_synth_dockerfile_injects_runargs_arm64(cr, tmp_path, clean_env):
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\nWORKDIR /app\n")
    with patch.object(cr.platform, "machine", return_value="arm64"):
        out = json.loads(cr.synth_spec(tmp_path).devcontainer_json)
    assert out["runArgs"] == ["--platform", "linux/arm64"]
    assert out["workspaceFolder"] == "/app"


def test_synth_dockerfile_injects_runargs_amd64(cr, tmp_path, clean_env):
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\n")
    with patch.object(cr.platform, "machine", return_value="x86_64"):
        out = json.loads(cr.synth_spec(tmp_path).devcontainer_json)
    assert out["runArgs"] == ["--platform", "linux/amd64"]


def test_synth_dockerfile_env_override_wins(cr, tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_PLATFORM", "linux/amd64")
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\n")
    with patch.object(cr.platform, "machine", return_value="arm64"):
        out = json.loads(cr.synth_spec(tmp_path).devcontainer_json)
    assert out["runArgs"] == ["--platform", "linux/amd64"]


def test_synth_dockerfile_unknown_arch_omits_runargs(cr, tmp_path, clean_env):
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\n")
    with patch.object(cr.platform, "machine", return_value="riscv64"):
        out = json.loads(cr.synth_spec(tmp_path).devcontainer_json)
    assert "runArgs" not in out


def test_synth_static_compose_does_not_inject_runargs(cr, tmp_path, clean_env):
    """Static docker-compose.yml is user-owned. Don't mutate platform there."""
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  app:\n    build: .\n    volumes:\n      - ./:/workspaces/foo\n"
    )
    with patch.object(cr.platform, "machine", return_value="arm64"):
        out = json.loads(cr.synth_spec(tmp_path).devcontainer_json)
    assert "runArgs" not in out
