"""RI2 — run-scoped container identity + override-config."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import lib.chunk as chunk_mod
import lib.devcontainer as devcontainer_mod
import lib.worktrees as worktrees_mod

from tests.conftest import init_git_repo, load_script

_CONTAINER = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-container/scripts/container.py"
_OPS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-container/scripts/client.py"


def test_workspace_folder_for_chunk_keyed_worktree() -> None:
    ops = load_script(_OPS, "client_ri2")
    wt = Path("/repo/.mentat/worktrees/abc123/my-plan")
    assert ops.workspace_folder_for(wt) == "/workspaces/abc123/my-plan"


def test_workspace_folder_for_flat_worktree() -> None:
    ops = load_script(_OPS, "client_ri2b")
    wt = Path("/repo/.mentat/worktrees/legacy-slug")
    assert ops.workspace_folder_for(wt) == "/workspaces/legacy-slug"


def test_override_config_leaves_tracked_devcontainer_pristine(tmp_path: Path) -> None:
    container = load_script(_CONTAINER, "container_ri2")
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    cid = "a" * 32
    slug = "my-plan"
    cs = chunk_mod.chunk_slug(cid, slug)
    wt = repo / ".mentat" / "worktrees" / cid / slug
    wt.parent.mkdir(parents=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", chunk_mod.holding_branch(cs), str(wt), "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    dcj = wt / ".devcontainer"
    dcj.mkdir(parents=True)
    original = '{"name": "mentat", "workspaceFolder": "/workspaces/mentat"}\n'
    (dcj / "devcontainer.json").write_text(original)

    override = container._write_override_config(wt, cs)
    assert override.exists()
    assert (dcj / "devcontainer.json").read_text() == original
    data = json.loads(override.read_text())
    assert data["workspaceFolder"] == f"/workspaces/{cid}/{slug}"


def test_prune_stale_scoped_to_run_chunk_ids(tmp_path: Path, monkeypatch) -> None:
    wt_root = tmp_path / ".mentat" / "worktrees"
    run_a = wt_root / "cid-a" / "plan"
    other = wt_root / "cid-b" / "plan"
    for p in (run_a, other):
        p.parent.mkdir(parents=True)
        p.mkdir()
        (p / ".git").write_text("gitdir: /fake\n")

    import time

    old = time.time() - 7200
    for p in (run_a, other):
        import os

        os.utime(p, (old, old))

    monkeypatch.setattr(worktrees_mod, "is_dirty", lambda _p: False)

    def fake_remove(p: Path) -> bool:
        import shutil

        shutil.rmtree(p, ignore_errors=True)
        return not p.exists()

    monkeypatch.setattr(worktrees_mod, "_remove", fake_remove)

    removed = worktrees_mod.prune_stale(wt_root, scope_chunk_ids={"cid-a"})
    assert not run_a.exists()
    assert other.exists()
    assert removed == 1


def test_down_run_only_touches_given_chunk_slugs(monkeypatch) -> None:
    downed: list[str] = []

    def fake_down(slug: str, *, label: str = "mentat_chunk") -> bool:
        downed.append(slug)
        return True

    monkeypatch.setattr(devcontainer_mod, "down", fake_down)
    assert devcontainer_mod.down_run({"aaa/plan-a", "bbb/plan-b"}) == 2
    assert set(downed) == {"aaa/plan-a", "bbb/plan-b"}


def test_cmd_up_passes_override_config_and_chunk_label(tmp_path: Path, monkeypatch) -> None:
    container = load_script(_CONTAINER, "container_ri2_up")
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    cid = "c" * 32
    slug = "plan"
    cs = chunk_mod.chunk_slug(cid, slug)
    wt = repo / ".mentat" / "worktrees" / cid / slug
    wt.parent.mkdir(parents=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", chunk_mod.holding_branch(cs), str(wt), "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (wt / ".devcontainer").mkdir(parents=True)
    (wt / ".devcontainer" / "devcontainer.json").write_text(
        '{"name": "mentat", "workspaceFolder": "/workspaces/mentat"}'
    )

    load_script(_CONTAINER.parent / "runtime.py", "runtime_ri2_up")
    lifecycle = load_script(_CONTAINER.parent / "lifecycle.py", "lifecycle_ri2_up")
    monkeypatch.setattr(lifecycle.runtime, "_host_runtime", lambda: False)
    monkeypatch.setattr(lifecycle.utils, "container_id_for", lambda _s: None)
    captured: list[list[str]] = []

    def fake_run(cmd, **kw):
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, ".git\n")
        if cmd[0] == lifecycle.utils._docker():
            return subprocess.CompletedProcess(cmd, 0, "")
        if cmd[0] == "devcontainer":
            captured.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(lifecycle, "subprocess", subprocess)
    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)
    assert container.cmd_up(wt) == 0
    assert captured
    assert "--override-config" in captured[0]
    assert any(f"mentat_chunk={cs}" in part for part in captured[0])
