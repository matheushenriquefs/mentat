"""C1 — sidecar-aware workspace detection in override._parse_compose_service.

A service counts as the workspace only when it has `build` or a *source-tree* mount
(the worktree root: `.`/`./`/`..`/`$PWD`). A bind-mount of a single config file
(`./nitter.conf:/src/nitter.conf`) is not source code and must not count. When no
service is a workspace (all sidecars), detection raises a typed `SidecarOnlyCompose`
signal instead of mis-picking a sidecar or emitting the generic "cannot infer" error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import load_script

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-container/scripts"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def cr():
    return load_script(_SCRIPTS / "override.py", "override")


# --- sidecar-only → typed signal -------------------------------------------------


def test_sidecar_only_fixture_raises_signal(cr):
    """bebop-shaped compose: nitter (config-file mount) + nitter-redis (named vol)."""
    text = (_FIXTURES / "compose_sidecar_only.yml").read_text()
    with pytest.raises(cr.SidecarOnlyCompose):
        cr._parse_compose_service(text)


def test_sidecar_signal_is_not_plain_valueerror(cr):
    """The sidecar-only signal is its own type, distinguishable from the
    ambiguous/cannot-infer ValueError so the caller (C2) can branch on it."""
    assert issubclass(cr.SidecarOnlyCompose, Exception)
    assert not issubclass(cr.SidecarOnlyCompose, ValueError)


def test_sidecar_signal_carries_service_names(cr):
    text = (_FIXTURES / "compose_sidecar_only.yml").read_text()
    with pytest.raises(cr.SidecarOnlyCompose) as exc:
        cr._parse_compose_service(text)
    msg = str(exc.value)
    assert "nitter" in msg and "nitter-redis" in msg


def test_config_file_mount_alone_is_sidecar(cr):
    """A lone service mounting only a config file is not a workspace."""
    text = "services:\n  svc:\n    image: someimage:latest\n    volumes:\n      - ./app.conf:/etc/app.conf:ro\n"
    with pytest.raises(cr.SidecarOnlyCompose):
        cr._parse_compose_service(text)


# --- source-tree mounts → workspace ----------------------------------------------


@pytest.mark.parametrize(
    "source",
    [".", "./", "..", "../", "${PWD}", "$PWD", "${PWD}/"],
)
def test_source_tree_mount_resolves(cr, source):
    """A mount whose source is the worktree root marks the workspace, no build needed."""
    text = f"services:\n  app:\n    image: python:3.11\n    volumes:\n      - {source}:/workspaces/foo\n"
    assert cr._parse_compose_service(text) == "app"


def test_long_form_source_tree_mount_resolves(cr):
    """Long-syntax bind of the worktree root marks the workspace."""
    text = (
        "services:\n"
        "  app:\n"
        "    image: python:3.11\n"
        "    volumes:\n"
        "      - type: bind\n"
        "        source: ./\n"
        "        target: /workspaces/foo\n"
    )
    assert cr._parse_compose_service(text) == "app"


def test_long_form_config_file_is_sidecar(cr):
    """Long-syntax bind of a single config file is not the workspace."""
    text = (
        "services:\n"
        "  svc:\n"
        "    image: someimage:latest\n"
        "    volumes:\n"
        "      - type: bind\n"
        "        source: ./app.conf\n"
        "        target: /etc/app.conf\n"
    )
    with pytest.raises(cr.SidecarOnlyCompose):
        cr._parse_compose_service(text)


def test_workspace_folder_short_form(cr):
    text = "services:\n  app:\n    build: .\n    volumes:\n      - ./:/workspaces/foo\n"
    assert cr._infer_workspace_folder_from_compose(text, "app", "slug") == "/workspaces/foo"


def test_workspace_folder_long_form_target(cr):
    """Long-syntax `target:` (space after colon) resolves, not the slug fallback."""
    text = (
        "services:\n"
        "  app:\n"
        "    image: python:3.11\n"
        "    volumes:\n"
        "      - type: bind\n"
        "        source: ./\n"
        "        target: /workspaces/foo\n"
    )
    assert cr._infer_workspace_folder_from_compose(text, "app", "slug") == "/workspaces/foo"


def test_build_service_still_resolves(cr):
    """Regression: a buildable service remains the workspace."""
    text = "services:\n  app:\n    build: .\n    volumes:\n      - ./:/workspaces/foo\n"
    assert cr._parse_compose_service(text) == "app"


def test_app_plus_sidecar_no_regression(cr):
    """An app (source-tree mount) beside a config-file sidecar resolves to the app."""
    text = (
        "services:\n"
        "  app:\n"
        "    build: .\n"
        "    volumes:\n"
        "      - .:/workspaces/foo\n"
        "  cache:\n"
        "    image: redis:7\n"
        "    volumes:\n"
        "      - ./redis.conf:/etc/redis.conf:ro\n"
    )
    assert cr._parse_compose_service(text) == "app"


def test_two_workspace_candidates_still_ambiguous(cr):
    """Two buildable services remain an ambiguous ValueError (not sidecar-only)."""
    text = "services:\n  a:\n    build: .\n  b:\n    build: ./other\n"
    with pytest.raises(ValueError):
        cr._parse_compose_service(text)


# ── CT3: environment block colons must not be inferred as workspace paths ───────


def test_environment_colon_not_inferred_as_workspace(cr):
    """A colon in an environment value must not be mistaken for a volume-mount target."""
    text = (
        "services:\n"
        "  app:\n"
        "    image: python:3.11\n"
        "    environment:\n"
        "      - PATH=/usr/local/bin:/usr/bin\n"
        "    volumes:\n"
        "      - .:/workspaces/app\n"
    )
    result = cr._infer_workspace_folder_from_compose(text, "app", "slug")
    assert result == "/workspaces/app", (
        f"Expected /workspaces/app, got {result!r} — environment colon must not be inferred as workspace path"
    )


def test_real_volume_mount_still_resolves_with_env_present(cr):
    """When environment: and volumes: both exist, volumes target is used for workspace."""
    text = (
        "services:\n"
        "  app:\n"
        "    build: .\n"
        "    environment:\n"
        "      - DATABASE_URL=postgres://db:5432/app\n"
        "    volumes:\n"
        "      - ./:/workspace/app\n"
    )
    result = cr._infer_workspace_folder_from_compose(text, "app", "slug")
    assert result == "/workspace/app"


# ── _resolve_platform / _service_is_workspace / _infer_workspace_folder edges ──


def test_resolve_platform_env_override(cr, monkeypatch):
    """MENTAT_PLATFORM override wins (override 36-37 covered elsewhere; 130 here)."""
    monkeypatch.setenv("MENTAT_PLATFORM", "linux/custom")
    assert cr._resolve_platform() == "linux/custom"


def test_service_is_workspace_volumes_block_closed_by_sibling_key(cr):
    """A sibling key indented no deeper than `volumes:` closes the block (130, 113->97)."""
    # build under a *second* service guarantees the workspace; the first service's
    # volumes block is closed by the `environment:` sibling key before any mount.
    body = [
        "    volumes:",
        "      - cache:/data",
        "    environment:",
        "      - FOO=bar",
        "      - PATH=/a:/b",
    ]
    # No build, only a named-volume mount + env → not the workspace.
    assert cr._service_is_workspace(body) is False


def test_service_is_workspace_long_syntax_bind_source(cr):
    """Long-syntax `source: .` marks the workspace (line 148 region; exercise 130)."""
    body = [
        "    volumes:",
        "      - type: bind",
        "        source: .",
        "        target: /app",
    ]
    assert cr._service_is_workspace(body) is True


def test_infer_workspace_folder_long_syntax_target(cr):
    """Long-syntax `target:` is returned as the workspace folder (line 213/218 region)."""
    compose_text = (
        "services:\n"
        "  app:\n"
        "    build: .\n"
        "    environment:\n"
        "      - PATH=/a:/b\n"
        "    volumes:\n"
        "      - type: bind\n"
        "        source: .\n"
        "        target: /srv/app\n"
    )
    assert cr._infer_workspace_folder_from_compose(compose_text, "app", "slug") == "/srv/app"


def test_infer_workspace_folder_env_colon_not_mistaken(cr, monkeypatch):
    """Colons in environment values are ignored; volumes block re-opens (191->187, 194, 201)."""
    compose_text = (
        "services:\n  app:\n    environment:\n      - PATH=/usr/bin:/bin\n    volumes:\n      - .:/workspaces/app\n"
    )
    assert cr._infer_workspace_folder_from_compose(compose_text, "app", "slug") == "/workspaces/app"


def test_infer_workspace_folder_falls_back_to_slug(cr):
    """A service with no volume target yields the slug default (return at 218)."""
    compose_text = "services:\n  app:\n    build: .\n    ports:\n      - 8080:8080\n"
    assert cr._infer_workspace_folder_from_compose(compose_text, "app", "myslug") == "/workspaces/myslug"


def test_dcj_json_appends_mounts(cr):
    """_dcj_json appends a non-empty mounts list (line 287)."""
    out = json.loads(cr._dcj_json({"name": "x"}, ["source=a,target=b,type=bind,readonly"]))
    assert out["mounts"] == ["source=a,target=b,type=bind,readonly"]


def test_synth_from_dockerfile_lowercase_then_glob(cr, tmp_path, monkeypatch):
    """Dockerfile detection: glob fallback finds Dockerfile.dev (357-359), WORKDIR parsed."""
    (tmp_path / "Dockerfile.dev").write_text("FROM scratch\nWORKDIR /opt/app\n")
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    monkeypatch.setenv("MENTAT_PLATFORM", "linux/arm64")

    result = cr._synth_from_dockerfile(tmp_path.name, tmp_path)
    data = json.loads(result.devcontainer_json)

    assert data["build"]["dockerfile"] == "../Dockerfile.dev"
    assert data["workspaceFolder"] == "/opt/app"
    assert data["runArgs"] == ["--platform", "linux/arm64"]


def test_synth_from_dockerfile_no_dockerfile_raises(cr, tmp_path):
    """No Dockerfile anywhere raises ValueError (line 362)."""
    with pytest.raises(ValueError, match="no .devcontainer"):
        cr._synth_from_dockerfile(tmp_path.name, tmp_path)


def test_service_is_workspace_skips_blank_body_lines(cr):
    """A blank line in the body is skipped (line 130)."""
    body = ["", "    build: .", ""]
    assert cr._service_is_workspace(body) is True


def test_iter_service_blocks_ignores_stray_line_before_first_service(cr):
    """A non-service line right after `services:` is dropped (113->97 false arc)."""
    # The `# comment` line sits in the services block before any service header,
    # so current is None and it must not be appended to any block.
    compose_text = "services:\n  # a comment before the first service\n  app:\n    build: .\n"
    blocks = dict(cr._iter_service_blocks(compose_text))
    assert "app" in blocks
    assert all("# a comment" not in line for body in blocks.values() for line in body)


def test_infer_workspace_folder_skips_non_target_service_and_blank(cr, monkeypatch):
    """A non-target service is skipped (189) and blank lines in the body too (194)."""
    compose_text = (
        "services:\n"
        "  db:\n"
        "    image: postgres\n"
        "  app:\n"
        "    build: .\n"
        "\n"
        "    volumes:\n"
        "      - named-vol\n"
        "    ports:\n"
        "      - 8080:8080\n"
        "    volumes:\n"
        "      - .:/workspaces/app\n"
    )
    # Target is the *second* service; the first volumes entry has no `:/abs`
    # target, then a sibling `ports:` key closes that block (201) before the
    # second volumes block yields the workspace target.
    assert cr._infer_workspace_folder_from_compose(compose_text, "app", "slug") == "/workspaces/app"


def test_synth_spec_prefers_compose_yaml_extension(cr, tmp_path, monkeypatch):
    """synth_spec finds docker-compose.yaml when .yml is absent (line 404)."""
    (tmp_path / "docker-compose.yaml").write_text(
        "services:\n  app:\n    build: .\n    volumes:\n      - .:/workspaces/app\n"
    )
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)

    result = cr.synth_spec(tmp_path)
    data = json.loads(result.devcontainer_json)

    assert data["service"] == "app"
    assert data["dockerComposeFile"] == ["../docker-compose.yml"]
