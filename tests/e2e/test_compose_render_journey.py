"""E2E: the pure compose/devcontainer.json renderer.

Drives ``override.py`` end to end through real worktree directories under
``tmp_path`` (a real Dockerfile / docker-compose.yml / compose.yml.tmpl on disk)
and monkeypatched env vars for the env-driven branches. The module is a pure
renderer — no docker, no filesystem writes — so each test loads a *fresh* module
instance via ``load_script`` (monkeypatched module globals must not leak between
tests) and asserts on the returned ``SynthResult`` / helper output, parsing
``devcontainer_json`` with ``json.loads`` wherever the assertion is structural.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_RENDER_PY = REPO_ROOT / ".agents/skills/mentat-container/scripts/override.py"


def _fresh():
    """A fresh override module instance (monkeypatched globals never leak)."""
    return load_script(COMPOSE_RENDER_PY, "override")


# ── _image_tag ──────────────────────────────────────────────────────────────


def test_image_tag_defaults_to_latest(monkeypatch):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_IMAGE_TAG", raising=False)
    assert cr._image_tag() == "latest"


def test_image_tag_env_override_wins(monkeypatch):
    cr = _fresh()
    monkeypatch.setenv("MENTAT_IMAGE_TAG", "sha-abc123")
    assert cr._image_tag() == "sha-abc123"


# ── _resolve_platform ───────────────────────────────────────────────────────


def test_resolve_platform_env_override_wins(monkeypatch):
    cr = _fresh()
    monkeypatch.setenv("MENTAT_PLATFORM", "linux/riscv64")
    assert cr._resolve_platform() == "linux/riscv64"


def test_resolve_platform_maps_arm64_machine(monkeypatch):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_PLATFORM", raising=False)
    monkeypatch.setattr(cr.platform, "machine", lambda: "arm64")
    assert cr._resolve_platform() == "linux/arm64"


def test_resolve_platform_maps_x86_64_machine(monkeypatch):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_PLATFORM", raising=False)
    monkeypatch.setattr(cr.platform, "machine", lambda: "x86_64")
    assert cr._resolve_platform() == "linux/amd64"


def test_resolve_platform_unknown_machine_is_none(monkeypatch):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_PLATFORM", raising=False)
    monkeypatch.setattr(cr.platform, "machine", lambda: "sparc")
    assert cr._resolve_platform() is None


# ── _is_cwd_source ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "source",
    [".", "./", "..", "../", "$PWD", "${PWD}", "'.'", '"./"', "'$PWD'", '"${PWD}"'],
)
def test_is_cwd_source_true_for_worktree_root_tokens(source):
    cr = _fresh()
    assert cr._is_cwd_source(source) is True


@pytest.mark.parametrize("source", ["./nitter.conf", "cache-data"])
def test_is_cwd_source_false_for_config_file_and_named_volume(source):
    cr = _fresh()
    assert cr._is_cwd_source(source) is False


# ── _is_source_tree_mount ───────────────────────────────────────────────────


def test_is_source_tree_mount_true_for_root_bind():
    cr = _fresh()
    assert cr._is_source_tree_mount("./:/app") is True


def test_is_source_tree_mount_false_for_named_volume():
    cr = _fresh()
    assert cr._is_source_tree_mount("cache-data:/data") is False


# ── _iter_service_blocks ────────────────────────────────────────────────────


def test_iter_service_blocks_skips_sibling_top_level_blocks():
    cr = _fresh()
    compose = (
        "services:\n"
        "  web:\n"
        "    build: .\n"
        "  worker:\n"
        "    image: worker:latest\n"
        "volumes:\n"
        "  cache-data:\n"
        "    driver: local\n"
        "networks:\n"
        "  default:\n"
        "    driver: bridge\n"
    )
    names = [name for name, _ in cr._iter_service_blocks(compose)]
    assert names == ["web", "worker"]


# ── _service_is_workspace ───────────────────────────────────────────────────


def test_service_is_workspace_true_for_build():
    cr = _fresh()
    assert cr._service_is_workspace(["    build: ."]) is True


def test_service_is_workspace_true_for_short_syntax_root_bind():
    cr = _fresh()
    body = ["    volumes:", "      - ./:/app"]
    assert cr._service_is_workspace(body) is True


def test_service_is_workspace_true_for_long_syntax_bind():
    cr = _fresh()
    body = [
        "    volumes:",
        "      - type: bind",
        "        source: ./",
        "        target: /app",
    ]
    assert cr._service_is_workspace(body) is True


def test_service_is_workspace_false_for_sidecar_with_config_bind_and_named_volume():
    cr = _fresh()
    # A named volume + a single config-file bind, then a sibling `environment:`
    # key at the same indent as `volumes:` closes the volumes block.
    body = [
        "    image: zedeus/nitter:latest",
        "    volumes:",
        "      - ./nitter.conf:/etc/nitter.conf:ro",
        "      - cache-data:/cache",
        "    environment:",
        "      - REDIS_HOST=redis",
    ]
    assert cr._service_is_workspace(body) is False


# ── _parse_compose_service ──────────────────────────────────────────────────


def test_parse_compose_service_returns_single_workspace():
    cr = _fresh()
    compose = "services:\n  app:\n    build: .\n  db:\n    image: postgres:16\n"
    assert cr._parse_compose_service(compose) == "app"


def test_parse_compose_service_raises_sidecar_only_with_names():
    cr = _fresh()
    compose = "services:\n  nitter:\n    image: zedeus/nitter:latest\n  redis:\n    image: redis:7\n"
    with pytest.raises(cr.SidecarOnlyCompose) as exc:
        cr._parse_compose_service(compose)
    assert exc.value.services == ["nitter", "redis"]


def test_parse_compose_service_raises_valueerror_on_ambiguous():
    cr = _fresh()
    compose = "services:\n  a:\n    build: .\n  b:\n    build: .\n"
    with pytest.raises(ValueError):
        cr._parse_compose_service(compose)


# ── SidecarOnlyCompose.__init__ ─────────────────────────────────────────────


def test_sidecar_only_compose_message_lists_names():
    cr = _fresh()
    exc = cr.SidecarOnlyCompose(["nitter", "redis"])
    assert "nitter, redis" in str(exc)


def test_sidecar_only_compose_message_empty_says_none():
    cr = _fresh()
    exc = cr.SidecarOnlyCompose([])
    assert "none" in str(exc)


# ── _infer_workspace_folder_from_compose ────────────────────────────────────


def test_infer_workspace_folder_short_syntax_target():
    cr = _fresh()
    compose = "services:\n  app:\n    volumes:\n      - .:/workspaces/app\n"
    assert cr._infer_workspace_folder_from_compose(compose, "app", "slug") == "/workspaces/app"


def test_infer_workspace_folder_long_syntax_target():
    cr = _fresh()
    compose = "services:\n  app:\n    volumes:\n      - type: bind\n        source: ./\n        target: /srv/app\n"
    assert cr._infer_workspace_folder_from_compose(compose, "app", "slug") == "/srv/app"


def test_infer_workspace_folder_falls_back_to_slug_when_no_target():
    cr = _fresh()
    # An `environment:` colon (PATH=/a:/b) sits outside any volumes block, so it
    # must not be mis-detected as a mount target; no volume target → slug default.
    compose = "services:\n  app:\n    image: app:latest\n    environment:\n      - PATH=/a:/b\n"
    assert cr._infer_workspace_folder_from_compose(compose, "app", "myslug") == "/workspaces/myslug"


# ── render_template ─────────────────────────────────────────────────────────


def test_render_template_substitutes_and_keeps_literal_dollar(tmp_path):
    cr = _fresh()
    tmpl = tmp_path / "compose.yml.tmpl"
    tmpl.write_text("ws=$workspace_folder arch=$arch tag=$image_tag lit=$$HOME\n")
    out = cr.render_template(tmpl, workspace_folder="/workspaces/x", arch="arm64", image_tag="v1")
    assert out == "ws=/workspaces/x arch=arm64 tag=v1 lit=$HOME\n"


# ── _ro_mounts_from_env ─────────────────────────────────────────────────────


def test_ro_mounts_empty_when_env_unset(monkeypatch, capsys):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    assert cr._ro_mounts_from_env("/workspaces/x", "/host/wt") == []
    assert "MENTAT_RO_MOUNTS unset" in capsys.readouterr().err


def test_ro_mounts_from_json_list(monkeypatch):
    cr = _fresh()
    monkeypatch.setenv("MENTAT_RO_MOUNTS", json.dumps([".env", "secrets/key"]))
    mounts = cr._ro_mounts_from_env("/workspaces/x", "/host/wt")
    assert mounts == [
        "source=/host/wt/.env,target=/workspaces/x/.env,type=bind,readonly",
        "source=/host/wt/secrets/key,target=/workspaces/x/secrets/key,type=bind,readonly",
    ]


# ── synth_spec: compose.yml.tmpl branch (_synth_from_tmpl) ───────────────────


def _worktree(tmp_path: Path, name: str) -> Path:
    wt = tmp_path / name
    wt.mkdir()
    return wt


def test_synth_spec_from_tmpl_renders_compose_and_devcontainer(tmp_path, monkeypatch):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    monkeypatch.setenv("MENTAT_PLATFORM", "linux/arm64")
    wt = _worktree(tmp_path, "proj")
    dc = wt / ".devcontainer"
    dc.mkdir()
    (dc / "compose.yml.tmpl").write_text(
        "services:\n  app:\n    image: base:$image_tag\n    platform: linux/$arch\n    working_dir: $workspace_folder\n"
    )
    result = cr.synth_spec(wt)
    assert "docker-compose.yml" in result.extra_files
    rendered = result.extra_files["docker-compose.yml"]
    assert "linux/arm64" in rendered
    assert "/workspaces/proj" in rendered
    dcj = json.loads(result.devcontainer_json)
    assert dcj["service"] == "app"
    assert dcj["name"] == "proj"
    assert dcj["workspaceFolder"] == "/workspaces/proj"
    assert "mounts" not in dcj


def test_synth_spec_from_tmpl_includes_mounts_when_env_set(tmp_path, monkeypatch):
    cr = _fresh()
    monkeypatch.setenv("MENTAT_RO_MOUNTS", json.dumps([".netrc"]))
    monkeypatch.delenv("MENTAT_PLATFORM", raising=False)
    monkeypatch.setattr(cr.platform, "machine", lambda: "x86_64")
    wt = _worktree(tmp_path, "proj2")
    dc = wt / ".devcontainer"
    dc.mkdir()
    (dc / "compose.yml.tmpl").write_text("services:\n  app:\n    image: base:$image_tag\n")
    result = cr.synth_spec(wt)
    dcj = json.loads(result.devcontainer_json)
    assert dcj["mounts"] == [f"source={wt}/.netrc,target=/workspaces/proj2/.netrc,type=bind,readonly"]


# ── synth_spec: docker-compose.yml single-workspace (_synth_from_compose) ────


def test_synth_spec_from_compose_single_workspace(tmp_path, monkeypatch):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    wt = _worktree(tmp_path, "web-proj")
    (wt / "docker-compose.yml").write_text(
        "services:\n  web:\n    build: .\n    volumes:\n      - .:/code\n  db:\n    image: postgres:16\n"
    )
    result = cr.synth_spec(wt)
    assert result.extra_files == {}
    dcj = json.loads(result.devcontainer_json)
    assert dcj["service"] == "web"
    assert dcj["dockerComposeFile"] == ["../docker-compose.yml"]
    assert dcj["workspaceFolder"] == "/code"


# ── synth_spec: sidecar-only compose (_synth_sidecar_overlay) ────────────────


def test_synth_spec_sidecar_only_layers_dev_overlay(tmp_path, monkeypatch):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    monkeypatch.delenv("MENTAT_IMAGE_TAG", raising=False)
    wt = _worktree(tmp_path, "sidecars")
    (wt / "docker-compose.yml").write_text(
        "services:\n"
        "  nitter:\n"
        "    image: zedeus/nitter:latest\n"
        "    volumes:\n"
        "      - ./nitter.conf:/etc/nitter.conf:ro\n"
        "  redis:\n"
        "    image: redis:7\n"
    )
    result = cr.synth_spec(wt)
    assert "mentat-dev.compose.yml" in result.extra_files
    overlay = result.extra_files["mentat-dev.compose.yml"]
    assert "mentat-dev:" in overlay
    assert "sleep infinity" in overlay
    dcj = json.loads(result.devcontainer_json)
    assert dcj["service"] == "mentat-dev"
    assert dcj["dockerComposeFile"] == ["../docker-compose.yml", "mentat-dev.compose.yml"]
    assert dcj["workspaceFolder"] == "/workspaces/sidecars"


# ── synth_spec: docker-compose.yaml extension (_synth_from_compose) ──────────


def test_synth_spec_handles_yaml_extension(tmp_path, monkeypatch):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    wt = _worktree(tmp_path, "yaml-proj")
    (wt / "docker-compose.yaml").write_text("services:\n  app:\n    build: .\n")
    result = cr.synth_spec(wt)
    dcj = json.loads(result.devcontainer_json)
    assert dcj["service"] == "app"


# ── synth_spec: Dockerfile branch (_synth_from_dockerfile) ───────────────────


def test_synth_spec_from_dockerfile_with_workdir_and_platform(tmp_path, monkeypatch):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    monkeypatch.setenv("MENTAT_PLATFORM", "linux/arm64")
    wt = _worktree(tmp_path, "df-proj")
    (wt / "Dockerfile").write_text("FROM python:3.12\nWORKDIR /srv\nCOPY . .\n")
    result = cr.synth_spec(wt)
    assert result.extra_files == {}
    dcj = json.loads(result.devcontainer_json)
    assert dcj["workspaceFolder"] == "/srv"
    assert dcj["build"]["dockerfile"] == "../Dockerfile"
    assert dcj["runArgs"] == ["--platform", "linux/arm64"]


def test_synth_spec_from_dockerfile_default_workspace_no_platform(tmp_path, monkeypatch):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    monkeypatch.delenv("MENTAT_PLATFORM", raising=False)
    monkeypatch.setattr(cr.platform, "machine", lambda: "sparc")
    wt = _worktree(tmp_path, "df-nowork")
    (wt / "Dockerfile").write_text("FROM python:3.12\nCOPY . .\n")
    result = cr.synth_spec(wt)
    dcj = json.loads(result.devcontainer_json)
    assert dcj["workspaceFolder"] == "/workspaces/df-nowork"
    assert "runArgs" not in dcj


def test_synth_spec_from_lowercase_dockerfile(tmp_path, monkeypatch):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    monkeypatch.delenv("MENTAT_PLATFORM", raising=False)
    monkeypatch.setattr(cr.platform, "machine", lambda: "sparc")
    wt = _worktree(tmp_path, "df-lower")
    (wt / "dockerfile").write_text("FROM alpine\nWORKDIR /app\n")
    result = cr.synth_spec(wt)
    dcj = json.loads(result.devcontainer_json)
    assert dcj["build"]["dockerfile"] == "../dockerfile"
    assert dcj["workspaceFolder"] == "/app"


def test_synth_spec_from_dockerfile_glob_fallback(tmp_path, monkeypatch):
    cr = _fresh()
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    monkeypatch.delenv("MENTAT_PLATFORM", raising=False)
    monkeypatch.setattr(cr.platform, "machine", lambda: "sparc")
    wt = _worktree(tmp_path, "df-glob")
    (wt / "Dockerfile.dev").write_text("FROM node:20\nWORKDIR /opt/app\n")
    result = cr.synth_spec(wt)
    dcj = json.loads(result.devcontainer_json)
    assert dcj["build"]["dockerfile"] == "../Dockerfile.dev"
    assert dcj["workspaceFolder"] == "/opt/app"


def test_synth_spec_empty_worktree_raises_valueerror(tmp_path):
    cr = _fresh()
    wt = _worktree(tmp_path, "empty")
    with pytest.raises(ValueError, match="no .devcontainer"):
        cr.synth_spec(wt)
