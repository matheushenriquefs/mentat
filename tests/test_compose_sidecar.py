"""C1 — sidecar-aware workspace detection in compose_render._parse_compose_service.

A service counts as the workspace only when it has `build` or a *source-tree* mount
(the worktree root: `.`/`./`/`..`/`$PWD`). A bind-mount of a single config file
(`./nitter.conf:/src/nitter.conf`) is not source code and must not count. When no
service is a workspace (all sidecars), detection raises a typed `SidecarOnlyCompose`
signal instead of mis-picking a sidecar or emitting the generic "cannot infer" error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-container/scripts"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def cr():
    return load_script(_SCRIPTS / "compose_render.py", "compose_render")


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
