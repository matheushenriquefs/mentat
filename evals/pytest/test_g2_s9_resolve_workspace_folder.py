"""G2-S9 — resolve_workspace_folder lib helper + mentat-container-run integration.

Plan ~/.agents/plans/mentat-architecture-revamp-g2-container-quartet.md §S9:
mentat-container-run must stop slug-deriving WS. Read it from
.devcontainer/devcontainer.json via lib helper instead. Fallback to
/workspaces/<slug> when the field is absent. Closes the S4 carry-forward
where slug != workspaceFolder broke `docker exec --workdir`.

Verify (from plan):
- hand-written devcontainer.json with workspaceFolder=/foo -> helper returns /foo
- absent/null workspaceFolder -> fallback /workspaces/<slug>
- grep `WS="/workspaces/$SLUG"` in mentat-container-run -> 0 hits
- mentat-container-up no longer defines local `workspace_folder()`
- only lib/container-state.sh reads .devcontainer/devcontainer.json
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BIN = REPO / ".agents" / "bin"
LIB = BIN / "lib"
CONTAINER_STATE = LIB / "container-state.sh"
RUN = BIN / "mentat-container-run"
UP = BIN / "mentat-container-up"


def _run_helper(call: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f". {CONTAINER_STATE} && {call}"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _seed_devcontainer(wt: Path, body: str) -> None:
    (wt / ".devcontainer").mkdir(parents=True, exist_ok=True)
    (wt / ".devcontainer" / "devcontainer.json").write_text(body)


# -- lib helper unit tests --------------------------------------------------


def test_resolve_workspace_folder_reads_explicit_field(tmp_path):
    """Hand-written devcontainer.json with workspaceFolder=/foo -> /foo,
    regardless of slug (this is the mentat-repo failure mode)."""
    sub = tmp_path / "dmux-1780833182484"
    sub.mkdir()
    _seed_devcontainer(sub, '{"name":"x","workspaceFolder":"/workspaces/mentat"}')
    res = _run_helper("resolve_workspace_folder", sub)
    assert res.returncode == 0, f"rc={res.returncode} stderr={res.stderr!r}"
    assert res.stdout.strip() == "/workspaces/mentat", (
        f"expected explicit field, got {res.stdout!r}"
    )


def test_resolve_workspace_folder_fallback_to_slug(tmp_path):
    """No devcontainer.json -> fallback /workspaces/<slug>."""
    sub = tmp_path / "myslug"
    sub.mkdir()
    res = _run_helper("resolve_workspace_folder", sub)
    assert res.returncode == 0, f"rc={res.returncode} stderr={res.stderr!r}"
    assert res.stdout.strip() == "/workspaces/myslug", (
        f"expected slug fallback, got {res.stdout!r}"
    )


def test_resolve_workspace_folder_fallback_when_field_absent(tmp_path):
    """devcontainer.json present but .workspaceFolder unset -> fallback."""
    sub = tmp_path / "myslug"
    sub.mkdir()
    _seed_devcontainer(sub, '{"name":"x","build":{"dockerfile":"../Dockerfile"}}')
    res = _run_helper("resolve_workspace_folder", sub)
    assert res.returncode == 0, f"rc={res.returncode} stderr={res.stderr!r}"
    assert res.stdout.strip() == "/workspaces/myslug", (
        f"expected slug fallback, got {res.stdout!r}"
    )


def test_resolve_workspace_folder_tolerates_jsonc_comments(tmp_path):
    """devcontainer.json supports // comments in practice; helper must
    strip them (same shape as mentat-container-up's prior local helper)."""
    sub = tmp_path / "myslug"
    sub.mkdir()
    _seed_devcontainer(sub, '// header comment\n{"workspaceFolder":"/x"}')
    res = _run_helper("resolve_workspace_folder", sub)
    assert res.returncode == 0, f"rc={res.returncode} stderr={res.stderr!r}"
    assert res.stdout.strip() == "/x", f"got {res.stdout!r}"


# -- mentat-container-run delegates to lib (no slug-derived WS) -------------


def test_mentat_container_run_does_not_hardcode_slug_workspace():
    """Plan must-not-exist: no `WS="/workspaces/$SLUG"` literal."""
    src = RUN.read_text()
    assert 'WS="/workspaces/$SLUG"' not in src, (
        "mentat-container-run still slug-derives WS; the hand-written "
        "devcontainer.json case (e.g. mentat repo, workspaceFolder=/workspaces/mentat) "
        "will hit `chdir to /workspaces/<slug>` OCI failures."
    )


def test_mentat_container_run_uses_lib_helper():
    """Positive proof: run calls resolve_workspace_folder."""
    src = RUN.read_text()
    assert "resolve_workspace_folder" in src, (
        "mentat-container-run must call lib helper resolve_workspace_folder"
    )


# -- mentat-container-up's local workspace_folder() collapsed into lib ------


def test_mentat_container_up_drops_local_workspace_folder_function():
    """Plan must-not-exist: no local `workspace_folder()` in up; lib owns it."""
    src = UP.read_text()
    assert "workspace_folder()" not in src, (
        "mentat-container-up still defines a local workspace_folder(); "
        "should call lib helper resolve_workspace_folder instead "
        "(closes C4's four-scripts-re-derive-workspaceFolder tail)."
    )


def test_mentat_container_up_uses_lib_helper():
    src = UP.read_text()
    assert "resolve_workspace_folder" in src


# -- only lib reads devcontainer.json (single source of truth) --------------


def test_only_lib_reads_workspace_folder_field():
    """Plan must-not-exist: no inline `jq` read of `.workspaceFolder` from
    devcontainer.json outside the lib. (devcontainer.json's other fields —
    dockerComposeFile patches, the file's *write* path on cold start — are
    out of S9 scope and may still appear in the scripts.)"""
    for path in (RUN, UP):
        src = path.read_text()
        assert ".workspaceFolder" not in src, (
            f"{path.name} parses `.workspaceFolder` directly; the lib helper "
            f"resolve_workspace_folder is the sole canonical reader."
        )
