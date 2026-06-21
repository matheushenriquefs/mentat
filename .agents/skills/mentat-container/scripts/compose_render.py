"""Pure compose/devcontainer.json renderer. No side effects."""

from __future__ import annotations

import json
import os
import platform
import re
from pathlib import Path
from string import Template

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


def synth(worktree_path: Path) -> str:
    """Return devcontainer.json JSON string for worktree_path. Pure — no filesystem writes."""
    slug = worktree_path.name

    # Template path takes priority over auto-detection
    tmpl = worktree_path / ".devcontainer" / "compose.yml.tmpl"
    if tmpl.exists():
        platform_str = _resolve_platform()
        arch = platform_str.split("/", 1)[1] if platform_str else "amd64"
        image_tag = os.environ.get("MENTAT_IMAGE_TAG", "latest")
        ws = f"/workspaces/{slug}"
        # Render but don't write; caller writes to .devcontainer/docker-compose.yml
        _ = render_template(tmpl, workspace_folder=ws, arch=arch, image_tag=image_tag)
        mounts = _ro_mounts_from_env(ws, str(worktree_path))
        dcj: dict = {
            "name": slug,
            "dockerComposeFile": ["docker-compose.yml"],
            "service": "app",
            "workspaceFolder": ws,
        }
        if mounts:
            dcj["mounts"] = mounts
        return json.dumps(dcj, indent=2)

    compose_yml = worktree_path / "docker-compose.yml"
    if not compose_yml.exists():
        compose_yaml = worktree_path / "docker-compose.yaml"
        if compose_yaml.exists():
            compose_yml = compose_yaml

    if compose_yml.exists():
        text = compose_yml.read_text()
        service = _parse_compose_service(text)
        ws = _infer_workspace_folder_from_compose(text, service, slug)
        mounts = _ro_mounts_from_env(ws, str(worktree_path))
        dcj = {
            "name": slug,
            "dockerComposeFile": ["../docker-compose.yml"],
            "service": service,
            "workspaceFolder": ws,
        }
        if mounts:
            dcj["mounts"] = mounts
        return json.dumps(dcj, indent=2)

    # Dockerfile path
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

    mounts = _ro_mounts_from_env(ws, str(worktree_path))
    dcj = {
        "name": slug,
        "build": {"dockerfile": f"../{dockerfile}", "context": ".."},
        "workspaceFolder": ws,
        "workspaceMount": f"source=${{localWorkspaceFolder}},target={ws},type=bind",
    }
    platform_str = _resolve_platform()
    if platform_str:
        dcj["runArgs"] = ["--platform", platform_str]
    if mounts:
        dcj["mounts"] = mounts
    return json.dumps(dcj, indent=2)
