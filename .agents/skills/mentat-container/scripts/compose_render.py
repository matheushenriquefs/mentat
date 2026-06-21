"""Pure compose/devcontainer.json renderer. No side effects."""

from __future__ import annotations

import json
import os
import platform
import re
from pathlib import Path
from string import Template
from typing import NamedTuple

_DEV_SERVICE = "mentat-dev"
_OVERLAY_FILENAME = "mentat-dev.compose.yml"
_DEFAULT_IMAGE_TAG = "latest"


def _image_tag() -> str:
    """Image tag for generated dev/app services. ``MENTAT_IMAGE_TAG`` overrides."""
    return os.environ.get("MENTAT_IMAGE_TAG", _DEFAULT_IMAGE_TAG)


_ARCH_MAP = {
    "arm64": "arm64",
    "aarch64": "arm64",
    "x86_64": "amd64",
    "amd64": "amd64",
}


def _resolve_platform() -> str | None:
    """Return docker --platform string (e.g. "linux/arm64") or None when unknown.

    MENTAT_PLATFORM env var wins. Else maps platform.machine() through _ARCH_MAP.
    """
    override = os.environ.get("MENTAT_PLATFORM")
    if override:
        return override
    arch = _ARCH_MAP.get(platform.machine().lower())
    return f"linux/{arch}" if arch else None


class SidecarOnlyCompose(Exception):
    """No service is the workspace — every service is a 3rd-party sidecar.

    A sidecar neither builds nor mounts the source tree (it pulls a published
    image and, at most, binds a single config file). When *all* services are
    sidecars the app itself runs outside this compose; mentat must layer its own
    dev service rather than mis-pick a sidecar. Distinct from the ambiguous-pick
    ``ValueError`` so the caller can branch on it. Carries the parsed service
    names for diagnostics and for the dev-service overlay to attach onto.
    """

    def __init__(self, services: list[str]) -> None:
        self.services = services
        super().__init__(
            "docker-compose.yml defines only sidecar services "
            f"({', '.join(services) or 'none'}); none builds or mounts the source "
            "tree, so the workspace is not containerized by this compose."
        )


_CWD_SOURCE_RE = re.compile(r"(\.|\.\.|\$\{?PWD\}?)/?")


def _is_cwd_source(source: str) -> bool:
    """True iff a mount *source* token is the worktree root itself.

    Worktree-root sources are ``.`` / ``./`` / ``..`` / ``../`` / ``$PWD`` /
    ``${PWD}``. A path *into* the tree (a config file like ``./nitter.conf``) and
    a named volume (``cache-data``) are not the workspace.
    """
    return bool(_CWD_SOURCE_RE.fullmatch(source.strip().strip("'").strip('"')))


def _is_source_tree_mount(volume_entry: str) -> bool:
    """True iff a compose short-syntax volume entry (``src:tgt[:mode]``) binds the
    worktree root. The source is the part before the first ``:``."""
    entry = volume_entry.strip().strip("'").strip('"')
    return _is_cwd_source(entry.split(":", 1)[0])


def _iter_service_blocks(compose_text: str) -> list[tuple[str, list[str]]]:
    """Split a compose file into ``(service_name, body_lines)`` per service.

    Only services nested under the top-level ``services:`` key are returned;
    sibling top-level blocks (``volumes:`` / ``networks:`` / ``secrets:``) and
    their children are skipped — they are not services even though their keys sit
    at the same two-space indent. Both the service-detection and
    workspace-folder-inference scans consume this one tokenizer so the compose
    line grammar lives in a single place.
    """
    blocks: list[tuple[str, list[str]]] = []
    in_services = False
    current: str | None = None
    body: list[str] = []
    for line in compose_text.splitlines():
        top = re.match(r"^([a-zA-Z0-9_-]+):\s*$", line)
        if top:
            if current is not None:
                blocks.append((current, body))
            current, body = None, []
            in_services = top.group(1) == "services"
            continue
        if not in_services:
            continue
        svc = re.match(r"^  ([a-zA-Z0-9._-]+):\s*$", line)
        if svc:
            if current is not None:
                blocks.append((current, body))
            current, body = svc.group(1), []
            continue
        if current is not None:
            body.append(line)
    if current is not None:
        blocks.append((current, body))
    return blocks


def _service_is_workspace(body: list[str]) -> bool:
    """True iff a service's body marks it as the workspace: it ``build``s, or it
    bind-mounts the worktree root. Handles short-syntax (``- ./:/app``) and
    long-syntax (``- type: bind`` / ``source: ./``) volumes and tolerates the
    service's own indentation depth (the ``volumes:`` block ends at the first
    sibling key indented no deeper than it)."""
    vol_indent: int | None = None
    for line in body:
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        is_item = stripped.startswith("-")
        key_m = None if is_item else re.match(r"([a-zA-Z0-9_-]+)\s*:\s*(.*)$", stripped)
        key = key_m.group(1) if key_m else None

        if vol_indent is not None and key is not None and indent <= vol_indent:
            vol_indent = None  # a sibling key closed the volumes block

        if key == "build":
            return True
        if key == "volumes":
            vol_indent = indent
            continue
        if vol_indent is None:
            continue
        if is_item and _is_source_tree_mount(stripped[1:].strip()):
            return True
        if key == "source" and _is_cwd_source(key_m.group(2)):  # long-syntax bind
            return True
    return False


def _parse_compose_service(compose_text: str) -> str:
    """Return the single workspace service name, or raise.

    Exactly one workspace service (``_service_is_workspace``) → return it. None →
    ``SidecarOnlyCompose`` (all sidecars; caller layers a dev service). More than
    one → ambiguous ``ValueError``.
    """
    services: list[str] = []
    candidates: list[str] = []
    for name, body in _iter_service_blocks(compose_text):
        services.append(name)
        if _service_is_workspace(body):
            candidates.append(name)

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise SidecarOnlyCompose(services)
    raise ValueError(
        f"cannot infer workspace service from docker-compose.yml "
        f"(candidates: {candidates}). "
        "Add a .devcontainer/devcontainer.json naming the `service` + `workspaceFolder`."
    )


def _infer_workspace_folder_from_compose(compose_text: str, service: str, slug: str) -> str:
    """Extract the workspace folder from the named service's volume mounts.

    Shares ``_iter_service_blocks`` with ``_parse_compose_service`` so both read
    the same compose grammar. Returns the first ``:/abs/path`` target in the
    service body, else the slug default.
    """
    for name, body in _iter_service_blocks(compose_text):
        if name != service:
            continue
        for line in body:
            # Long-syntax: an explicit `target: /abs/path` key.
            m = re.match(r"\s*target\s*:\s*(/\S+)", line)
            if m:
                return m.group(1)
            # Short-syntax: the `:/abs/path` half of `- src:/abs/path[:mode]`.
            m = re.search(r":(/[^:\s'\"]+)", line)
            if m:
                return m.group(1)
    return f"/workspaces/{slug}"


def render_template(tmpl_path: Path, workspace_folder: str, arch: str, image_tag: str) -> str:
    """Render a compose.yml.tmpl via stdlib string.Template. Pure — no filesystem writes.

    Substituted variables: $workspace_folder, $arch, $image_tag.
    Use $$ to emit a literal $ in the output.
    """
    return Template(tmpl_path.read_text()).substitute(
        workspace_folder=workspace_folder,
        arch=arch,
        image_tag=image_tag,
    )


def _ro_mounts_from_env(workspace_folder: str, worktree_host: str) -> list[str]:
    """Return devcontainer.json mount strings from MENTAT_RO_MOUNTS env var."""
    raw = os.environ.get("MENTAT_RO_MOUNTS")
    if not raw:
        return []
    paths: list[str] = json.loads(raw)
    return [f"source={worktree_host}/{p},target={workspace_folder}/{p},type=bind,readonly" for p in paths]


def _render_sidecar_overlay(workspace_folder: str, image_tag: str) -> str:
    """Compose overlay defining mentat's dev service for a sidecar-only project.

    Merged onto the project compose via multi-file compose, so the dev service joins
    the project's default network automatically — sidecars resolve by service name
    (e.g. ``nitter:8080``), never ``localhost``; no explicit ``networks:`` block is
    needed. Relative paths resolve against the project directory, which is the first
    compose file's directory (the worktree root), so ``.`` binds the worktree.
    """
    return (
        "# Generated by mentat — dev service layered onto a sidecar-only compose.\n"
        "# Merged via multi-file compose; joins the project default network, so\n"
        "# sidecars resolve by service name (e.g. nitter:8080), not localhost.\n"
        "services:\n"
        f"  {_DEV_SERVICE}:\n"
        f"    image: {image_tag}\n"
        "    volumes:\n"
        f"      - .:{workspace_folder}\n"
        f"    working_dir: {workspace_folder}\n"
        "    command: sleep infinity\n"
    )


class SynthResult(NamedTuple):
    """Pure result of devcontainer synthesis.

    ``devcontainer_json`` is the JSON text for ``.devcontainer/devcontainer.json``.
    ``extra_files`` maps ``.devcontainer/``-relative filenames to the text the caller
    must write alongside it (a rendered compose, a generated dev-service overlay).
    Empty for the plain compose and Dockerfile paths.
    """

    devcontainer_json: str
    extra_files: dict[str, str]


def _dcj_json(fields: dict, mounts: list[str]) -> str:
    """Serialize a devcontainer.json dict, appending non-empty ro-mounts last.

    Every synth branch builds its own field set but shares this tail (the
    ``mounts`` key is added only when ``MENTAT_RO_MOUNTS`` yielded entries), so
    the mount-handling lives in one place.
    """
    if mounts:
        fields = {**fields, "mounts": mounts}
    return json.dumps(fields, indent=2)


def _synth_from_tmpl(tmpl: Path, slug: str, worktree_path: Path) -> SynthResult:
    """Render a user ``compose.yml.tmpl`` and hand back the rendered compose text.

    The caller writes it to ``.devcontainer/docker-compose.yml`` (the path the
    devcontainer references); ``synth_spec`` stays pure.
    """
    platform_str = _resolve_platform()
    arch = platform_str.split("/", 1)[1] if platform_str else "amd64"
    ws = f"/workspaces/{slug}"
    rendered = render_template(tmpl, workspace_folder=ws, arch=arch, image_tag=_image_tag())
    mounts = _ro_mounts_from_env(ws, str(worktree_path))
    dcj = {
        "name": slug,
        "dockerComposeFile": ["docker-compose.yml"],
        "service": "app",
        "workspaceFolder": ws,
    }
    return SynthResult(_dcj_json(dcj, mounts), {"docker-compose.yml": rendered})


def _synth_sidecar_overlay(slug: str, worktree_path: Path) -> SynthResult:
    """Layer a generated dev service onto a sidecar-only compose (C2 / ADR-0011).

    The devcontainer points at both the project compose and the generated overlay;
    the dev service is the workspace. The overlay is returned as an extra file for
    the caller to write — ``synth_spec`` stays pure.
    """
    ws = f"/workspaces/{slug}"
    mounts = _ro_mounts_from_env(ws, str(worktree_path))
    dcj = {
        "name": slug,
        "dockerComposeFile": ["../docker-compose.yml", _OVERLAY_FILENAME],
        "service": _DEV_SERVICE,
        "workspaceFolder": ws,
    }
    overlay = _render_sidecar_overlay(ws, _image_tag())
    return SynthResult(_dcj_json(dcj, mounts), {_OVERLAY_FILENAME: overlay})


def _synth_from_compose(compose_yml: Path, slug: str, worktree_path: Path) -> SynthResult:
    """Wrap an existing project ``docker-compose.yml``; layer a dev service when
    every service is a sidecar (``SidecarOnlyCompose``)."""
    text = compose_yml.read_text()
    try:
        service = _parse_compose_service(text)
    except SidecarOnlyCompose:
        return _synth_sidecar_overlay(slug, worktree_path)
    ws = _infer_workspace_folder_from_compose(text, service, slug)
    mounts = _ro_mounts_from_env(ws, str(worktree_path))
    dcj = {
        "name": slug,
        "dockerComposeFile": ["../docker-compose.yml"],
        "service": service,
        "workspaceFolder": ws,
    }
    return SynthResult(_dcj_json(dcj, mounts), {})


def _synth_from_dockerfile(slug: str, worktree_path: Path) -> SynthResult:
    """Build the workspace image from a worktree ``Dockerfile``; pin --platform."""
    dockerfile: str | None = None
    for cand in ("Dockerfile", "dockerfile"):
        if (worktree_path / cand).exists():
            dockerfile = cand
            break
    if dockerfile is None:
        for p in sorted(worktree_path.glob("Dockerfile*")):
            dockerfile = p.name
            break

    if dockerfile is None:
        raise ValueError(
            f"mentat-container: no .devcontainer/, no docker-compose.yml, no Dockerfile in {worktree_path}"
        )

    ws = f"/workspaces/{slug}"
    df_text = (worktree_path / dockerfile).read_text()
    for line in reversed(df_text.splitlines()):
        m = re.match(r"^\s*WORKDIR\s+(/\S+)", line, re.IGNORECASE)
        if m:
            ws = m.group(1)
            break

    dcj = {
        "name": slug,
        "build": {"dockerfile": f"../{dockerfile}", "context": ".."},
        "workspaceFolder": ws,
        "workspaceMount": f"source=${{localWorkspaceFolder}},target={ws},type=bind",
    }
    platform_str = _resolve_platform()
    if platform_str:
        dcj["runArgs"] = ["--platform", platform_str]
    return SynthResult(_dcj_json(dcj, _ro_mounts_from_env(ws, str(worktree_path))), {})


def synth_spec(worktree_path: Path) -> SynthResult:
    """Return the devcontainer.json plus any extra ``.devcontainer/`` files to write.

    Pure — no filesystem writes. The caller (container.py) writes both the
    devcontainer.json and every entry of ``extra_files``. Detection order: a user
    ``compose.yml.tmpl`` wins, then a project ``docker-compose.yml`` (``.yaml``),
    then a worktree ``Dockerfile``.
    """
    slug = worktree_path.name

    tmpl = worktree_path / ".devcontainer" / "compose.yml.tmpl"
    if tmpl.exists():
        return _synth_from_tmpl(tmpl, slug, worktree_path)

    compose_yml = worktree_path / "docker-compose.yml"
    if not compose_yml.exists():
        compose_yaml = worktree_path / "docker-compose.yaml"
        if compose_yaml.exists():
            compose_yml = compose_yaml
    if compose_yml.exists():
        return _synth_from_compose(compose_yml, slug, worktree_path)

    return _synth_from_dockerfile(slug, worktree_path)


def synth(worktree_path: Path) -> str:
    """Return the devcontainer.json string for ``worktree_path``. Pure.

    Thin wrapper over :func:`synth_spec` for callers that only need the
    devcontainer.json and write no auxiliary compose files.
    """
    return synth_spec(worktree_path).devcontainer_json
