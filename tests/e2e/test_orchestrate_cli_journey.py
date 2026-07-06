"""E2E: mentat-orchestrate CLI journey — in-process seams, no subprocess/docker.

Drives ``orchestrate.py`` through its pure helpers, config/env readers, the
process-kill fallback path, the fan-out result partitioner, the prune sweeps,
the dry-run branch of ``run_orchestrate``, ``build_parser``, and ``main``
dispatch. Every seam that would spawn a subprocess, call docker, or touch real
git is monkeypatched — the tests exercise only the in-process-reachable lines.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_PY = REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts/orchestrate.py"


@pytest.fixture
def orch():
    """Fresh orchestrate module. monkeypatch.setattr auto-restores globals."""
    return load_script(ORCH_PY, "orch")


def _plan(orch, slug, *, kind="AFK", blocked_by=None, path=None):
    return orch._scheduler.Plan(
        slug=slug,
        kind=kind,
        blocked_by=list(blocked_by or []),
        path=path or Path(f"/plans/{slug}.md"),
    )


def _write_plan(dir_path, slug, *, kind="AFK", blocked_by=None, siblings=None, body="body"):
    lines = ["---", f"id: {slug}", f"kind: {kind}"]
    if blocked_by is not None:
        lines.append(f"blocked_by: [{', '.join(blocked_by)}]")
    if siblings is not None:
        lines.append(f"siblings: [{', '.join(siblings)}]")
    lines += ["---", body, ""]
    p = dir_path / f"{slug}.md"
    p.write_text("\n".join(lines))
    return p


# ── _parse_list_field ─────────────────────────────────────────────────────────


def test_parse_list_field_empty_and_bracket_yield_empty(orch):
    assert orch._parse_list_field("") == []
    assert orch._parse_list_field("[]") == []


def test_parse_list_field_splits_on_comma_and_whitespace(orch):
    assert orch._parse_list_field("a, b  c") == ["a", "b", "c"]


def test_parse_list_field_strips_brackets_and_quotes(orch):
    assert orch._parse_list_field("[a, 'b']") == ["a", "b"]


# ── _load_plans ───────────────────────────────────────────────────────────────


def test_load_plans_plain_plan(orch, tmp_path):
    p = _write_plan(tmp_path, "solo", kind="AFK", blocked_by=[])
    plans = orch._load_plans([p])
    assert len(plans) == 1
    assert plans[0].slug == "solo"
    assert plans[0].kind == "AFK"
    assert plans[0].blocked_by == []
    assert plans[0].path == p


def test_load_plans_parent_index_expands_to_siblings(orch, tmp_path):
    _write_plan(tmp_path, "child-a", kind="AFK", blocked_by=[])
    _write_plan(tmp_path, "child-b", kind="AFK", blocked_by=[])
    parent = _write_plan(tmp_path, "parent", siblings=["child-a", "child-b"])
    plans = orch._load_plans([parent])
    assert sorted(p.slug for p in plans) == ["child-a", "child-b"]


def test_load_plans_nested_parent_index_is_dataerr(orch, tmp_path):
    _write_plan(tmp_path, "grandchild", kind="AFK", blocked_by=[])
    _write_plan(tmp_path, "inner", siblings=["grandchild"])
    parent = _write_plan(tmp_path, "outer", siblings=["inner"])
    with pytest.raises(SystemExit) as exc:
        orch._load_plans([parent])
    assert exc.value.code == orch.EX_DATAERR


def test_load_plans_parent_index_with_blocked_by_is_dataerr(orch, tmp_path):
    _write_plan(tmp_path, "child", kind="AFK", blocked_by=[])
    parent = _write_plan(tmp_path, "parent", blocked_by=["dep"], siblings=["child"])
    with pytest.raises(SystemExit) as exc:
        orch._load_plans([parent])
    assert exc.value.code == orch.EX_DATAERR


def test_load_plans_missing_sibling_is_noinput(orch, tmp_path):
    parent = _write_plan(tmp_path, "parent", siblings=["ghost"])
    with pytest.raises(SystemExit) as exc:
        orch._load_plans([parent])
    assert exc.value.code == orch.EX_NOINPUT


def test_load_plans_blocked_on_parent_index_is_dataerr(orch, tmp_path):
    # parent index expands to child-a; a separate plan blocks_by the parent slug.
    _write_plan(tmp_path, "child-a", kind="AFK", blocked_by=[])
    parent = _write_plan(tmp_path, "parent", siblings=["child-a"])
    dependent = _write_plan(tmp_path, "dependent", kind="AFK", blocked_by=["parent"])
    with pytest.raises(SystemExit) as exc:
        orch._load_plans([parent, dependent])
    assert exc.value.code == orch.EX_DATAERR


def test_load_plans_unknown_dep_raises(orch, tmp_path, capsys):
    p = _write_plan(tmp_path, "solo", kind="AFK", blocked_by=["external-thing"])
    with pytest.raises(SystemExit) as exc:
        orch._load_plans([p])
    assert exc.value.code == orch.EX_DATAERR
    err = capsys.readouterr().err
    assert "external-thing" in err


# ── _emit_anchored_chunks ─────────────────────────────────────────────────────


def test_emit_anchored_chunks_emits_spawned_per_plan(orch, monkeypatch):
    events = []
    monkeypatch.setattr(orch._utils, "emit_event", lambda ev, payload: events.append((ev, payload)))
    plans = [_plan(orch, "one"), _plan(orch, "two")]
    slugs = orch._emit_anchored_chunks(plans, harness=None, model=None)
    assert slugs == ["one", "two"]
    assert [e[0] for e in events] == [
        "chunk_started",
        "agent_started",
        "chunk_started",
        "agent_started",
    ]
    assert all(e[1]["harness"] == orch.HITL_IN_AGENT for e in events)


# ── _concurrency_cap ──────────────────────────────────────────────────────────


def test_concurrency_cap_reads_config(orch, monkeypatch):
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": 5})
    monkeypatch.setattr(orch._supervise.os, "cpu_count", lambda: 32)  # headroom above config → no clamp
    assert orch._supervise._concurrency_cap() == 5


def test_concurrency_cap_bad_value_falls_back_to_default(orch, monkeypatch):
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": "bad"})
    monkeypatch.setattr(orch._supervise.os, "cpu_count", lambda: 32)
    assert orch._supervise._concurrency_cap() == 3


def test_concurrency_cap_missing_key_defaults(orch, monkeypatch):
    monkeypatch.setattr(orch._utils, "read_config", lambda: {})
    monkeypatch.setattr(orch._supervise.os, "cpu_count", lambda: 32)
    assert orch._supervise._concurrency_cap() == 3


def test_concurrency_cap_zero_floored_to_one(orch, monkeypatch):
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": 0})
    monkeypatch.setattr(orch._supervise.os, "cpu_count", lambda: 32)
    assert orch._supervise._concurrency_cap() == 1


# ── _chunk_timeout ────────────────────────────────────────────────────────────


def test_chunk_timeout_env_wins(orch, monkeypatch):
    monkeypatch.setenv("MENTAT_CHUNK_TIMEOUT", "600")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"chunk_timeout": 900})
    assert orch._supervise._chunk_timeout() == 600


def test_chunk_timeout_bad_env_falls_through_to_config(orch, monkeypatch):
    monkeypatch.setenv("MENTAT_CHUNK_TIMEOUT", "bad")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"chunk_timeout": 900})
    assert orch._supervise._chunk_timeout() == 900


def test_chunk_timeout_config_bad_defaults(orch, monkeypatch):
    monkeypatch.delenv("MENTAT_CHUNK_TIMEOUT", raising=False)
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"chunk_timeout": "nope"})
    assert orch._supervise._chunk_timeout() == 1800


def test_chunk_timeout_config_missing_defaults(orch, monkeypatch):
    monkeypatch.delenv("MENTAT_CHUNK_TIMEOUT", raising=False)
    monkeypatch.setattr(orch._utils, "read_config", lambda: {})
    assert orch._supervise._chunk_timeout() == 1800


# ── _kill_proc_group ──────────────────────────────────────────────────────────


class _FakeProc:
    """asyncio process double: no real pid, records kill()."""

    def __init__(self, *, pid=None):
        self.pid = pid
        self.returncode = None
        self.killed = False

    def kill(self):
        self.killed = True


def test_kill_proc_group_no_pid_falls_back_to_kill(orch):
    proc = _FakeProc(pid=None)
    orch._supervise._kill_proc_group(proc)
    # No resolvable pgid → fall back to proc.kill().
    assert proc.killed is True


def test_kill_proc_group_signals_group_when_pgid_resolves(orch, monkeypatch):
    proc = _FakeProc(pid=4242)
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(orch._supervise.os, "getpgid", lambda _pid: 4242)
    monkeypatch.setattr(orch._supervise.os, "killpg", lambda pg, sig: calls.append((pg, sig)))
    orch._supervise._kill_proc_group(proc)
    assert calls == [(4242, orch._supervise.signal.SIGKILL)]
    assert proc.killed is False


# ── _read_chunk_seed ──────────────────────────────────────────────────────────


def test_read_chunk_seed_returns_content_when_present(orch, monkeypatch, tmp_path):
    sf = tmp_path / "summary.md"
    sf.write_text("seed content")
    monkeypatch.setattr(orch._supervise, "_summary_file", lambda sid: sf)
    assert orch._supervise._read_chunk_seed("sess-x") == "seed content"


def test_read_chunk_seed_returns_none_when_absent(orch, monkeypatch, tmp_path):
    sf = tmp_path / "missing.md"
    monkeypatch.setattr(orch._supervise, "_summary_file", lambda sid: sf)
    assert orch._supervise._read_chunk_seed("sess-x") is None


# ── partition_by_outcome ─────────────────────────────────────────────────────────


def testpartition_by_outcome_routes_each_returncode(orch, monkeypatch, tmp_path):
    from tests.conftest import TEST_CHUNK_ID, bind_plan

    for slug in ("ok", "sig", "shell-sig", "hitl", "infra", "impl"):
        bind_plan(slug, TEST_CHUNK_ID)

    events = []
    ejected = []
    monkeypatch.setattr(orch._batch, "_emit_event", lambda ev, payload: events.append((ev, payload)))
    monkeypatch.setattr(orch._batch, "_worktree_for_slug", lambda slug: tmp_path / slug)

    results = [
        (_plan(orch, "ok"), 0),
        (_plan(orch, "sig"), -9),
        (_plan(orch, "shell-sig"), 137),
        (_plan(orch, "hitl"), orch._batch.EX_HITL_REQUIRED),
        (_plan(orch, "infra"), orch._batch.EX_UNAVAILABLE),
        (_plan(orch, "impl"), 1),
    ]
    chunks, hitl, transient = orch._batch.partition_by_outcome(results, mark_ejected=lambda s: ejected.append(s))

    # rc == 0 is the only landable chunk.
    assert [c.slug for c in chunks] == ["ok"]
    assert hitl == {"hitl"}

    reasons = {payload["slug"]: payload["reason"] for ev, payload in events if ev == "chunk_ejected"}
    assert reasons["sig"] == orch._batch.WORKER_DIED
    assert reasons["shell-sig"] == orch._batch.WORKER_DIED
    assert reasons["hitl"] == orch._batch.HITL_REQUIRED
    assert reasons["infra"] == orch._batch.WORKER_DIED
    assert reasons["impl"] == orch._batch.IMPLEMENT_FAILED

    # Transient (worker-died) ejects are RETURNED for the recovery engine, not
    # mark_ejected'd inside partition; only terminal ejects are marked.
    assert transient == {"sig", "shell-sig", "infra"}
    assert set(ejected) == {"hitl", "impl"}


# ── _prune_stale_containers ───────────────────────────────────────────────────


def test_prune_stale_containers_warns_dirty_and_emits_reclaimed(orch, monkeypatch, capsys):
    from tests.test_orchestrate_prune import _seed_run_chunks

    events = []
    _seed_run_chunks(orch, "a")
    monkeypatch.setattr(orch._batch._devcontainer, "down_run", lambda slugs: 1)
    monkeypatch.setattr(orch._utils, "emit_event", lambda ev, payload: events.append((ev, payload)))
    orch._batch._prune_stale_containers()
    assert events == [("agent_reaped", {"reclaimed_bytes": None, "containers_removed": 1})]


# ── _prune_stale_worktrees ────────────────────────────────────────────────────


def test_prune_stale_worktrees_folds_preserve_into_active(orch, monkeypatch):
    from tests.conftest import TEST_CHUNK_ID, bind_plan, chunk_label
    from tests.test_orchestrate_prune import _seed_run_chunks

    events = []
    seen = {}
    bind_plan("wedged", TEST_CHUNK_ID)
    _seed_run_chunks(orch, "wedged")

    def _prune_stale(root, active_slugs, scope_chunk_ids=None):
        seen["active"] = active_slugs
        seen["scope"] = scope_chunk_ids
        return 2

    monkeypatch.setattr(orch._batch._worktrees, "prune_stale", _prune_stale)
    monkeypatch.setattr(orch._utils, "emit_event", lambda ev, payload: events.append((ev, payload)))
    orch._batch._prune_stale_worktrees(preserve={"wedged"})
    assert seen["active"] == {chunk_label("wedged")}
    assert events == [("agent_reaped", {"reclaimed_bytes": None, "worktrees_removed": 2})]


# ── _land_all ─────────────────────────────────────────────────────────────────


def test_land_all_without_plans_drains_bare(orch, monkeypatch, tmp_path):
    from tests.conftest import TEST_CHUNK_ID, bind_plan

    bind_plan("a", TEST_CHUNK_ID)
    bind_plan("b", TEST_CHUNK_ID)
    captured = {}
    monkeypatch.setattr(orch._batch, "_worktree_for_slug", lambda s: tmp_path / s)

    def _drain(chunks, *, holding, **kwargs):
        captured["holding"] = holding
        captured["kwargs"] = kwargs
        captured["slugs"] = [c.slug for c in chunks]
        return []

    monkeypatch.setattr(orch._batch._land_queue, "drain", _drain)
    assert orch._batch._land_all(["a", "b"], holding="hold") == []
    assert captured["slugs"] == ["a", "b"]
    assert captured["kwargs"] == {}


def test_land_all_with_plans_passes_scheduler_hooks(orch, monkeypatch, tmp_path):
    from tests.conftest import TEST_CHUNK_ID, bind_plan

    bind_plan("a", TEST_CHUNK_ID)
    captured = {}
    monkeypatch.setattr(orch._batch, "_worktree_for_slug", lambda s: tmp_path / s)

    def _drain(chunks, *, holding, **kwargs):
        captured["kwargs"] = kwargs
        return []

    monkeypatch.setattr(orch._batch._land_queue, "drain", _drain)
    plans = [_plan(orch, "a")]
    orch._batch._land_all(["a"], holding="hold", plans=plans)
    assert set(captured["kwargs"]) == {"on_landed", "on_ejected", "list_ready_slices"}


# ── run_orchestrate (dry-run) ─────────────────────────────────────────────────


def test_run_orchestrate_dry_run(orch, monkeypatch, capsys):
    land_calls = []
    events = []
    monkeypatch.setattr(orch, "ensure_agent", lambda role, holding: "sess-1")
    monkeypatch.setattr(orch, "_load_plans", lambda paths: [_plan(orch, "afk-one", kind="AFK")])
    monkeypatch.setattr(orch._batch, "_land_all", lambda slugs, *, holding: land_calls.append((slugs, holding)) or [])
    monkeypatch.setattr(orch._utils, "emit_event", lambda ev, payload: events.append((ev, payload)))

    rc = orch.run_orchestrate("hold", [Path("p.md")], harness=None, model=None, dry_run=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "[dry-run] would anchor" in out
    assert "[dry-run] would spawn" in out
    assert land_calls == [([], "hold")]
    assert events == [
        (
            "batch_reviewed",
            {"agent": "sess-1", "summary": "batch review for agent sess-1 — advisory"},
        )
    ]


# ── build_parser ──────────────────────────────────────────────────────────────


def test_build_parser_run_namespace(orch):
    args = orch.build_parser().parse_args(["run", "holding", "p1", "p2", "--harness", "h", "--model", "m", "--dry-run"])
    assert args.cmd == "run"
    assert args.holding == "holding"
    assert args.plan_refs == ["p1", "p2"]
    assert args.harness == "h"
    assert args.model == "m"
    assert args.dry_run is True


def test_build_parser_fan_out_namespace(orch):
    args = orch.build_parser().parse_args(["fan-out", "p1"])
    assert args.cmd == "fan-out"
    assert args.plan_refs == ["p1"]


def test_build_parser_land_queue_namespace(orch):
    args = orch.build_parser().parse_args(["land-queue", "holding"])
    assert args.cmd == "land-queue"
    assert args.holding == "holding"


def test_build_parser_batch_review_namespace(orch):
    args = orch.build_parser().parse_args(["batch-review", "sess"])
    assert args.cmd == "batch-review"
    assert args.session == "sess"


def test_build_parser_requires_subcommand(orch):
    with pytest.raises(SystemExit):
        orch.build_parser().parse_args([])


# ── main dispatch ─────────────────────────────────────────────────────────────


def test_main_run_dispatches_to_run_orchestrate(orch, monkeypatch):
    captured = {}

    def _run(holding, plan_paths, *, harness, model, dry_run):
        captured.update(holding=holding, dry_run=dry_run, plan_paths=plan_paths)
        return 0

    monkeypatch.setattr(orch, "run_orchestrate", _run)
    monkeypatch.setattr(orch._utils, "resolve_plan_ref", lambda r: Path(r))
    monkeypatch.setattr(orch.sys, "argv", ["o", "run", "hold", "planA", "--dry-run"])
    with pytest.raises(SystemExit) as exc:
        orch.main()
    assert exc.value.code == 0
    assert captured["holding"] == "hold"
    assert captured["dry_run"] is True
    assert captured["plan_paths"] == [Path("planA")]


def test_main_fan_out_spawns_each_plan(orch, monkeypatch):
    spawned = []
    monkeypatch.setattr(orch._utils, "resolve_plan_ref", lambda r: Path(r))
    monkeypatch.setattr(orch, "_load_plans", lambda paths: [_plan(orch, "p")])
    monkeypatch.setattr(orch._spawn, "spawn", lambda plan: spawned.append(plan.slug))
    monkeypatch.setattr(orch.sys, "argv", ["o", "fan-out", "p"])
    orch.main()  # no sys.exit on this branch
    assert spawned == ["p"]


def test_main_land_queue_prints_json(orch, monkeypatch, tmp_path, capsys):
    existing = tmp_path / "a.md"
    existing.write_text("---\nid: a\nkind: AFK\n---\nbody\n")

    def _resolve(slug):
        return existing if slug == "a" else tmp_path / "b.md"  # b does not exist

    load_calls = []
    monkeypatch.setattr(orch._utils, "resolve_plan_ref", _resolve)
    monkeypatch.setattr(orch, "_load_plans", lambda paths, _expanding=False: load_calls.append(paths) or [])
    monkeypatch.setattr(orch._batch, "_land_all", lambda slugs, *, holding, plans: [{"slug": "a"}])
    monkeypatch.setattr(orch.sys, "stdin", io.StringIO("a\nb\n"))
    monkeypatch.setattr(orch.sys, "argv", ["o", "land-queue", "hold"])
    orch.main()
    out = capsys.readouterr().out
    assert '{"slug": "a"}' in out
    # only the existing path was fed to _load_plans.
    assert load_calls == [[existing]]


def test_main_batch_review_emits_event(orch, monkeypatch):
    events = []
    monkeypatch.setattr(orch._utils, "emit_event", lambda ev, payload: events.append((ev, payload)))
    monkeypatch.setattr(orch.sys, "argv", ["o", "batch-review", "sess-9"])
    orch.main()
    assert events == [
        (
            "batch_reviewed",
            {"agent": "sess-9", "summary": "batch review for agent sess-9 — advisory"},
        )
    ]
