"""C2 — layer a generated dev service onto a sidecar-only compose.

When every compose service is a 3rd-party sidecar (``SidecarOnlyCompose``), mentat
synthesizes its own dev service and merges it onto the project compose via multi-file
compose. ``synth_spec`` returns the devcontainer.json *plus* the overlay text the caller
must write; ``synth`` stays a thin str-returning wrapper so existing callers are untouched.
The same return shape closes the latent gap where the ``compose.yml.tmpl`` branch rendered
a compose file that the caller then never wrote.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import load_script

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-container/scripts"
_FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/compose_sidecar_only.yml"


def _load_override():
    return load_script(_SCRIPTS / "override.py", "override")


@pytest.fixture
def cr():
    return _load_override()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    monkeypatch.delenv("MENTAT_IMAGE_TAG", raising=False)
    monkeypatch.delenv("MENTAT_PLATFORM", raising=False)


def _sidecar_worktree(tmp_path: Path) -> Path:
    (tmp_path / "docker-compose.yml").write_text(_FIXTURE.read_text())
    return tmp_path


# ── synth_spec contract ───────────────────────────────────────────────────────


def test_synth_spec_returns_json_and_extra_files(cr, tmp_path):
    """synth_spec hands back both the devcontainer.json text and the files to write."""
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  app:\n    build: .\n    volumes:\n      - ..:/workspaces/app\n"
    )
    spec = cr.synth_spec(tmp_path)
    assert isinstance(spec.devcontainer_json, str)
    assert isinstance(spec.extra_files, dict)
    json.loads(spec.devcontainer_json)  # valid JSON


def test_synth_spec_json_is_valid(cr, tmp_path):
    """synth_spec returns a SynthResult whose devcontainer_json is valid JSON."""
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  app:\n    build: .\n    volumes:\n      - ..:/workspaces/app\n"
    )
    spec = cr.synth_spec(tmp_path)
    assert isinstance(spec.devcontainer_json, str)
    json.loads(spec.devcontainer_json)


# ── sidecar-only → layered dev service ─────────────────────────────────────────


def test_sidecar_only_devcontainer_lists_both_compose_files(cr, tmp_path):
    wt = _sidecar_worktree(tmp_path)
    data = json.loads(cr.synth_spec(wt).devcontainer_json)
    assert data["dockerComposeFile"] == ["../docker-compose.yml", "mentat-dev.compose.yml"]
    assert data["service"] == "mentat-dev"
    assert data["workspaceFolder"] == f"/workspaces/{wt.name}"


def test_sidecar_only_emits_overlay_file(cr, tmp_path):
    wt = _sidecar_worktree(tmp_path)
    spec = cr.synth_spec(wt)
    assert "mentat-dev.compose.yml" in spec.extra_files
    overlay = spec.extra_files["mentat-dev.compose.yml"]
    assert "mentat-dev:" in overlay
    # mounts the worktree root at the workspace folder
    assert f":/workspaces/{wt.name}" in overlay
    # stays a long-running dev container
    assert "command:" in overlay


def test_overlay_joins_default_network_not_explicit_block(cr, tmp_path):
    """Multi-file compose merges into one project: the dev service joins the project
    default network automatically. The overlay must NOT pin any network config that
    would break that implicit join, and must define ONLY the dev service (it merges
    onto the sidecar compose rather than redeclaring sidecars)."""
    overlay = cr.synth_spec(_sidecar_worktree(tmp_path)).extra_files["mentat-dev.compose.yml"]
    # Strip comment lines so doc text mentioning "networks"/"localhost" can't mask a real directive.
    directives = "\n".join(ln for ln in overlay.splitlines() if not ln.lstrip().startswith("#"))
    assert "networks:" not in directives  # no explicit network block — joins the project default
    assert "network_mode" not in directives  # nor any override that would break the default join
    # Exactly one service is declared: the dev service. Sidecars come from the project compose.
    assert directives.count("services:") == 1
    import re as _re

    service_names = [m.group(1) for ln in directives.splitlines() if (m := _re.match(r"^  ([a-zA-Z0-9_-]+):\s*$", ln))]
    assert service_names == ["mentat-dev"]


# ── latent-gap fix: tmpl branch now hands back its rendered compose ─────────────


def test_tmpl_branch_returns_rendered_compose_as_extra_file(cr, tmp_path):
    """The compose.yml.tmpl path used to render then discard. It now returns the
    rendered docker-compose.yml as an extra file for the caller to write."""
    dc = tmp_path / ".devcontainer"
    dc.mkdir()
    (dc / "compose.yml.tmpl").write_text(
        "services:\n  app:\n    image: ${image_tag}\n    volumes:\n      - ..:${workspace_folder}\n"
    )
    spec = cr.synth_spec(tmp_path)
    assert "docker-compose.yml" in spec.extra_files
    rendered = spec.extra_files["docker-compose.yml"]
    assert "${" not in rendered  # template fully substituted
    assert f"/workspaces/{tmp_path.name}" in rendered


# ── no regression: normal paths emit no extra files ────────────────────────────


def test_normal_compose_has_no_extra_files(cr, tmp_path):
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  app:\n    build: .\n    volumes:\n      - ..:/workspaces/app\n"
    )
    assert cr.synth_spec(tmp_path).extra_files == {}


def test_dockerfile_path_has_no_extra_files(cr, tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\nWORKDIR /app\n")
    assert cr.synth_spec(tmp_path).extra_files == {}


# ── container.py writes the overlay alongside devcontainer.json ─────────────────


def test_write_override_config_writes_overlay_outside_worktree(tmp_path):
    """_write_override_config writes override devcontainer.json + compose overlay outside the tree."""
    container = load_script(_SCRIPTS / "container.py", "container")
    _sidecar_worktree(tmp_path)
    slug = tmp_path.name
    cs = f"{'0' * 32}/{slug}"

    container._write_override_config(tmp_path, cs)

    from lib.chunk import override_config_dir

    override_dir = override_config_dir(tmp_path, cs)
    dcj = override_dir / "devcontainer.json"
    overlay = override_dir / "mentat-dev.compose.yml"
    assert dcj.exists(), "override devcontainer.json not written"
    assert overlay.exists(), "mentat-dev.compose.yml overlay not written"
    assert not (tmp_path / ".devcontainer" / "devcontainer.json").exists()
    assert "mentat-dev:" in overlay.read_text()
