"""RI3 — honest audit worktree + OOM-honest eject."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import lib.devcontainer as devcontainer_mod

from tests.conftest import TEST_CHUNK_ID, bind_plan, fake_plan, load_script

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"
_FAN_OUT = ORCH_SCRIPTS / "fan_out.py"


def _load_orchestrate():
    spec = importlib.util.spec_from_file_location("orchestrate_ri3", ORCH_SCRIPTS / "orchestrate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["orchestrate_ri3"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_fan_out_spawned_records_child_worktree(tmp_path: Path, monkeypatch) -> None:
    fan_out = load_script(_FAN_OUT, "fan_out_ri3")
    wt = tmp_path / "wt"
    wt.mkdir()
    plan = fake_plan(tmp_path / "p.md", "p")

    monkeypatch.setattr(
        fan_out,
        "_prepare_chunk_spawn",
        lambda *a, **k: ("sess", ["true"], {}, wt),
    )
    monkeypatch.setattr(
        fan_out.subprocess,
        "Popen",
        lambda *a, **k: SimpleNamespace(pid=1),
    )
    emitted: list[tuple] = []

    def capture(event, payload):
        emitted.append((event, payload))

    monkeypatch.setattr(fan_out, "_emit_event", capture)
    fan_out.spawn_with_proc(plan)
    assert emitted[0][0] == "chunk_started"
    assert emitted[0][1]["worktree"] == str(wt)


def test_container_oom_killed_reads_inspect_flag(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_docker(argv, **kw):
        calls.append(argv)
        if "inspect" in argv:
            return SimpleNamespace(returncode=0, stdout="true\n")
        return SimpleNamespace(returncode=0, stdout="cid123\n")

    monkeypatch.setattr(devcontainer_mod, "_run_docker", fake_docker)
    assert devcontainer_mod.container_oom_killed("abc/plan") is True
    assert any("OOMKilled" in " ".join(c) for c in calls)


def test_partition_marks_oom_as_transient_killed_by(monkeypatch, tmp_path: Path) -> None:
    orch = _load_orchestrate()
    from lib.exits import EX_UNAVAILABLE

    bind_plan("p", TEST_CHUNK_ID)
    wt = tmp_path / "wt"
    wt.mkdir()
    plan = fake_plan(tmp_path / "p.md", "p")

    monkeypatch.setattr(orch, "_worktree_for_slug", lambda _s: wt)
    monkeypatch.setattr(orch._devcontainer, "container_oom_killed", lambda _cs: True)
    emitted: list[tuple] = []
    monkeypatch.setattr(orch, "_emit_event", lambda e, p: emitted.append((e, p)))
    monkeypatch.setattr(orch, "_teardown_ejected", lambda _s: None)

    results = [(plan, EX_UNAVAILABLE, "/logs", None)]
    chunks, hitl, transient = orch.partition_by_outcome(results, mark_ejected=lambda s: [])
    assert "p" in transient
    eject = next(p for e, p in emitted if e == "chunk_ejected")
    assert eject["reason"] == orch.CONTAINER_OOM
    assert "killed_by" not in eject


def test_mentat_chunk_memory_unset_by_default(tmp_path: Path) -> None:
    container = load_script(
        Path(__file__).resolve().parents[1] / ".agents/skills/mentat-container/scripts/container.py",
        "container_ri3_mem",
    )
    from tests.conftest import init_git_repo

    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    cid = "d" * 32
    slug = "plan"
    cs = f"{cid}/{slug}"
    wt = repo / ".mentat" / "worktrees" / cid / slug
    (wt / ".devcontainer").mkdir(parents=True)
    (wt / ".devcontainer" / "devcontainer.json").write_text('{"workspaceFolder": "/workspaces/x"}')
    wt.mkdir(parents=True, exist_ok=True)

    override = container._write_override_config(wt, cs)
    data = __import__("json").loads(override.read_text())
    run_args = data.get("runArgs") or []
    assert not any(a == "--memory" for a in run_args)


def test_mentat_chunk_memory_injected_when_set(tmp_path: Path, monkeypatch) -> None:
    container = load_script(
        Path(__file__).resolve().parents[1] / ".agents/skills/mentat-container/scripts/container.py",
        "container_ri3_mem2",
    )
    from tests.conftest import init_git_repo

    monkeypatch.setenv("MENTAT_CHUNK_MEMORY", "256m")
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    cid = "e" * 32
    slug = "plan"
    cs = f"{cid}/{slug}"
    wt = repo / ".mentat" / "worktrees" / cid / slug
    wt.mkdir(parents=True)
    (wt / ".devcontainer").mkdir(parents=True)
    (wt / ".devcontainer" / "devcontainer.json").write_text('{"workspaceFolder": "/workspaces/x"}')

    override = container._write_override_config(wt, cs)
    data = __import__("json").loads(override.read_text())
    run_args = data.get("runArgs") or []
    assert "--memory" in run_args
    assert "256m" in run_args
