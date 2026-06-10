"""Pure compose/devcontainer.json renderer. No side effects."""

from __future__ import annotations

import json
import re
from pathlib import Path


def _parse_compose_service(compose_text: str) -> str:
    """Extract the single buildable/cwd-mounted service name or raise."""
    candidates: list[str] = []
    current: str | None = None
    has_build = False
    has_cwd = False

    for line in compose_text.splitlines():
        # Top-level service name under `services:`
        svc_match = re.match(r"^  ([a-zA-Z0-9._-]+):\s*$", line)
        if svc_match:
            if current and (has_build or has_cwd):
                candidates.append(current)
            current = svc_match.group(1)
            has_build = False
            has_cwd = False
            continue
        if current:
            if re.search(r"\bbuild\b", line):
                has_build = True
            if re.search(r"\.\.|\.\/|\$\{?PWD\}?", line):
                has_cwd = True

    if current and (has_build or has_cwd):
        candidates.append(current)

    if len(candidates) != 1:
        raise ValueError(
            f"cannot infer workspace service from docker-compose.yml "
            f"(buildable/cwd-mounted: {candidates or 'none'}). "
            "Add a .devcontainer/devcontainer.json naming the `service` + `workspaceFolder`."
        )
    return candidates[0]


def _infer_workspace_folder_from_compose(compose_text: str, service: str, slug: str) -> str:
    """Extract workspace folder from the service's volume mounts."""
    in_svc = False
    for line in compose_text.splitlines():
        if re.match(rf"^  {re.escape(service)}:\s*$", line):
            in_svc = True
            continue
        if in_svc and re.match(r"^  [a-zA-Z0-9]", line):
            in_svc = False
        if in_svc:
            m = re.search(r":(/[^:\s'\"]+)", line)
            if m:
                return m.group(1)
    return f"/workspaces/{slug}"


def synth(worktree_path: Path) -> str:
    """Return devcontainer.json JSON string for worktree_path. Pure — no filesystem writes."""
    slug = worktree_path.name
    compose_yml = worktree_path / "docker-compose.yml"
    if not compose_yml.exists():
        compose_yaml = worktree_path / "docker-compose.yaml"
        if compose_yaml.exists():
            compose_yml = compose_yaml

    if compose_yml.exists():
        text = compose_yml.read_text()
        service = _parse_compose_service(text)
        ws = _infer_workspace_folder_from_compose(text, service, slug)
        return json.dumps({
            "name": slug,
            "dockerComposeFile": ["../docker-compose.yml"],
            "service": service,
            "workspaceFolder": ws,
        }, indent=2)

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

    return json.dumps({
        "name": slug,
        "build": {"dockerfile": f"../{dockerfile}", "context": ".."},
        "workspaceFolder": ws,
        "workspaceMount": f"source=${{localWorkspaceFolder}},target={ws},type=bind",
    }, indent=2)
