"""E2E: mentat-implement journey — in-process seams, no subprocess/docker.

Drives ``implement.py`` across its full reachable surface: the pure/manifest
helpers, the config + checkpoint readers, the frontmatter/summary plumbing, the
AFK wedge + self-answer + gate-block channels of ``run_plan``, the orchestration
wrappers (``_run_and_doctor``, ``_auto_doctor``, ``_auto_summary``, teardown,
prune, worktree preflight, land), the argparse ``build_parser``, and ``main``
dispatch. Every seam that would spawn a real harness, shell a subprocess, touch
docker, or change the real cwd is monkeypatched — the tests exercise only the
in-process-reachable lines.

One test at the bottom keeps the established heavy e2e shape: a real git repo,
a real per-slice ``git commit``, and a real ``pre-commit`` gate hook, with only
the harness boundary faked.
"""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import TEST_CHUNK_ID, init_git_repo, load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
IMPL_PY = REPO_ROOT / ".agents/skills/mentat-implement/scripts/implement.py"


@pytest.fixture
def impl():
    """Fresh implement module. monkeypatch.setattr auto-restores globals."""
    return load_script(IMPL_PY, "impl")


def _fake_result(*, returncode=0, usage_tokens=None, agent_log=None):
    return SimpleNamespace(returncode=returncode, usage_tokens=usage_tokens, agent_log=agent_log)


def _write_plan(path: Path, *, kind="AFK", body="body") -> Path:
    path.write_text(f"---\nid: {path.stem}\nkind: {kind}\n---\n{body}\n")
    return path


@contextmanager
def _recorder(monkeypatch, obj, name):
    """Patch obj.name with a recorder; yield the call list."""
    calls: list = []
    monkeypatch.setattr(obj, name, lambda *a, **k: calls.append((a, k)))
    yield calls


# ── _logs_path ──────────────────────────────────────────────────────────────


def test_logs_path_lands_under_agent_dir(impl, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_AGENT", "implement-x-1")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    p = impl._logs_path()
    assert p.endswith("implement-x-1")
    assert str(tmp_path / "logs") in p


# ── _plans_dir ──────────────────────────────────────────────────────────────


def test_plans_dir_is_home_agents_plans(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl.Path, "home", classmethod(lambda cls: tmp_path))
    assert impl._plans_dir() == tmp_path / ".agents" / "plans"


# ── read_tests_manifest ───────────────────────────────────────────────────────


def test_read_tests_manifest_absent_returns_empties(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl, "_plans_dir", lambda: tmp_path)
    assert impl.read_tests_manifest("slug") == ([], [])


def test_read_tests_manifest_parses_closed_and_open(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl, "_plans_dir", lambda: tmp_path)
    (tmp_path / "slug.tests.json").write_text(json.dumps({"closed": ["a", "b"], "open": ["b"]}))
    assert impl.read_tests_manifest("slug") == (["a", "b"], ["b"])


# ── compute_ro_mounts ─────────────────────────────────────────────────────────


def test_compute_ro_mounts_is_closed_minus_open(impl):
    assert impl.compute_ro_mounts(["a", "b", "c"], ["b"]) == ["a", "c"]


# ── mark_test_writable ─────────────────────────────────────────────────────────


def test_mark_test_writable_no_manifest_reports_and_returns(impl, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(impl, "_plans_dir", lambda: tmp_path)
    impl.mark_test_writable("slug", "a")
    assert "no manifest" in capsys.readouterr().err


def test_mark_test_writable_path_not_in_closed_reports(impl, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(impl, "_plans_dir", lambda: tmp_path)
    (tmp_path / "slug.tests.json").write_text(json.dumps({"closed": ["a"], "open": []}))
    impl.mark_test_writable("slug", "z")
    assert "not in closed" in capsys.readouterr().err


def test_mark_test_writable_happy_moves_path_and_emits(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl, "_plans_dir", lambda: tmp_path)
    manifest = tmp_path / "slug.tests.json"
    manifest.write_text(json.dumps({"closed": ["a"], "open": []}))
    events: list = []
    monkeypatch.setattr(impl, "_emit_event", lambda ev, payload: events.append((ev, payload)))
    impl.mark_test_writable("slug", "a")
    assert json.loads(manifest.read_text())["open"] == ["a"]
    assert events == [("test_writable_requested", {"slug": "slug", "path": "a"})]


def test_mark_test_writable_already_open_no_dup(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl, "_plans_dir", lambda: tmp_path)
    manifest = tmp_path / "slug.tests.json"
    manifest.write_text(json.dumps({"closed": ["a"], "open": ["a"]}))
    monkeypatch.setattr(impl, "_emit_event", lambda ev, payload: None)
    impl.mark_test_writable("slug", "a")
    assert json.loads(manifest.read_text())["open"] == ["a"]


# ── resolve_plan_path ─────────────────────────────────────────────────────────


def test_resolve_plan_path_ends_in_ref_md(impl):
    assert impl.resolve_plan_path("my-slug").name == "my-slug.md"


# ── parse_frontmatter ─────────────────────────────────────────────────────────


def test_parse_frontmatter_reads_class(impl, tmp_path):
    plan = _write_plan(tmp_path / "p.md", kind="AFK")
    assert impl.parse_frontmatter(plan).get("kind") == "AFK"


# ── _compaction_threshold ─────────────────────────────────────────────────────


def test_compaction_threshold_none_when_no_config(impl, monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_CONFIG", raising=False)
    monkeypatch.setattr(impl.Path, "home", classmethod(lambda cls: tmp_path))
    assert impl._compaction_threshold() is None


def test_compaction_threshold_reads_value(impl, monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("compaction_threshold_tokens = 5000\n")
    monkeypatch.setenv("MENTAT_CONFIG", str(cfg))
    assert impl._compaction_threshold() == 5000


def test_compaction_threshold_key_absent_is_none(impl, monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("harness = 'claude-code'\n")
    monkeypatch.setenv("MENTAT_CONFIG", str(cfg))
    assert impl._compaction_threshold() is None


def test_compaction_threshold_non_int_raises(impl, monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('compaction_threshold_tokens = "abc"\n')
    monkeypatch.setenv("MENTAT_CONFIG", str(cfg))
    with pytest.raises(ValueError, match="invalid compaction_threshold_tokens"):
        impl._compaction_threshold()


# ── _checkpoint_if_needed ──────────────────────────────────────────────────────


def test_checkpoint_none_threshold_is_noop(impl, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_AGENT", "s")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    impl._checkpoint_if_needed(_fake_result(usage_tokens=99), slug="s", threshold=None)
    from lib.agent import summary_file

    assert not summary_file("s").exists()


def test_checkpoint_below_threshold_is_noop(impl, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_AGENT", "s")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    impl._checkpoint_if_needed(_fake_result(usage_tokens=10), slug="s", threshold=5000)
    from lib.agent import summary_file

    assert not summary_file("s").exists()


def test_checkpoint_at_threshold_writes_summary(impl, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_AGENT", "s")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    impl._checkpoint_if_needed(_fake_result(usage_tokens=6000), slug="s", threshold=5000)
    from lib.agent import summary_file

    body = summary_file("s").read_text()
    assert "Token checkpoint" in body
    assert "6000 tokens used" in body


# ── _strip_frontmatter ─────────────────────────────────────────────────────────


def test_strip_frontmatter_no_leading_dashes_unchanged(impl):
    assert impl._strip_frontmatter("hello\nworld") == "hello\nworld"


def test_strip_frontmatter_removes_block(impl):
    assert impl._strip_frontmatter("---\nid: x\n---\nbody here\n") == "body here\n"


def test_strip_frontmatter_no_closing_dashes_unchanged(impl):
    text = "---\nid: x\nno closing"
    assert impl._strip_frontmatter(text) == text


# ── _veto_agents_dir ───────────────────────────────────────────────────────────


def test_veto_agents_dir_claude(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl.Path, "home", classmethod(lambda cls: tmp_path))
    assert impl._veto_agents_dir("claude-code") == tmp_path / ".claude" / "agents"


def test_veto_agents_dir_cursor(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl.Path, "home", classmethod(lambda cls: tmp_path))
    assert impl._veto_agents_dir("cursor") == tmp_path / ".cursor" / "agents"


def test_veto_agents_dir_unknown_defaults_claude(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl.Path, "home", classmethod(lambda cls: tmp_path))
    assert impl._veto_agents_dir("mystery") == tmp_path / ".claude" / "agents"


# ── preflight_veto_reviewers ───────────────────────────────────────────────────


def test_preflight_veto_skipped_when_env_set(impl, monkeypatch):
    monkeypatch.setenv("MENTAT_SKIP_PREFLIGHT", "1")
    assert impl.preflight_veto_reviewers("claude-code") == (0, [])


def test_preflight_veto_all_present(impl, monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    from lib.gates.score import VETO_KEYWORDS

    agents = tmp_path / "agents"
    agents.mkdir()
    for kw in VETO_KEYWORDS:
        (agents / f"mentat-{kw}-reviewer.md").write_text("x")
    monkeypatch.setattr(impl, "_veto_agents_dir", lambda h: agents)
    assert impl.preflight_veto_reviewers("claude-code") == (0, [])


def test_preflight_veto_missing_reports_names(impl, monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    agents = tmp_path / "agents"
    agents.mkdir()
    monkeypatch.setattr(impl, "_veto_agents_dir", lambda h: agents)
    rc, missing = impl.preflight_veto_reviewers("claude-code")
    assert rc == 1
    assert missing  # every reviewer absent


# ── _blocked_summary_path ──────────────────────────────────────────────────────


def test_blocked_summary_path_none_without_session(impl, monkeypatch):
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    assert impl._blocked_summary_path() is None


def test_blocked_summary_path_set_returns_summary_file(impl, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_AGENT", "s")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    assert impl._blocked_summary_path().name == "summary.md"


# ── _read_summary_at ───────────────────────────────────────────────────────────


def test_read_summary_at_absent_none(impl, tmp_path):
    assert impl._read_summary_at(tmp_path / "nope.md") is None


def test_read_summary_at_blocked_returns_body(impl, tmp_path):
    p = tmp_path / "summary.md"
    p.write_text("---\nstatus: blocked\n---\nthe blocker body\n")
    assert impl._read_summary_at(p) == "the blocker body"


def test_read_summary_at_other_status_none(impl, tmp_path):
    p = tmp_path / "summary.md"
    p.write_text("---\nstatus: succeeded\n---\nall good\n")
    assert impl._read_summary_at(p) is None


def test_read_summary_at_unreadable_none(impl, tmp_path):
    d = tmp_path / "a-dir"
    d.mkdir()
    # Reading a directory raises OSError → swallowed to None.
    assert impl._read_summary_at(d) is None


# ── _read_blocked_summary ──────────────────────────────────────────────────────


def test_read_blocked_summary_from_agent_seam(impl, monkeypatch, tmp_path):
    seam = tmp_path / "summary.md"
    seam.write_text("---\nstatus: blocked\n---\nagent blocker\n")
    monkeypatch.setattr(impl, "_blocked_summary_path", lambda: seam)
    assert impl._read_blocked_summary(tmp_path / "wt") == "agent blocker"


def test_read_blocked_summary_worktree_fallback(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl, "_blocked_summary_path", lambda: None)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / impl.SUMMARY_FILE).write_text("---\nstatus: blocked\n---\nwt blocker\n")
    assert impl._read_blocked_summary(wt) == "wt blocker"


def test_read_blocked_summary_neither_none(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl, "_blocked_summary_path", lambda: None)
    wt = tmp_path / "wt"
    wt.mkdir()
    assert impl._read_blocked_summary(wt) is None


# ── _promote_blocked_summary ───────────────────────────────────────────────────


def test_promote_blocked_summary_writes_file(impl, monkeypatch, tmp_path):
    seam = tmp_path / "logs" / "summary.md"
    monkeypatch.setattr(impl, "_blocked_summary_path", lambda: seam)
    impl._promote_blocked_summary("the body")
    body = seam.read_text()
    assert "status: blocked" in body
    assert "the body" in body


def test_promote_blocked_summary_oserror_surfaces(impl, monkeypatch):
    class _FakePath:
        @property
        def parent(self):
            return self

        def mkdir(self, *a, **k):
            raise OSError("nope")

        def write_text(self, *a, **k):
            raise OSError("nope")

    monkeypatch.setattr(impl, "_blocked_summary_path", lambda: _FakePath())
    with pytest.raises(OSError, match="nope"):
        impl._promote_blocked_summary("body")


# ── _detect_self_answer ────────────────────────────────────────────────────────


def test_detect_self_answer_none_log_false(impl):
    assert impl._detect_self_answer(_fake_result(agent_log=None)) is False


def test_detect_self_answer_delegates(impl, monkeypatch):
    monkeypatch.setattr(impl._utils, "detect_self_answer", lambda p: True)
    assert impl._detect_self_answer(_fake_result(agent_log="/x")) is True
    monkeypatch.setattr(impl._utils, "detect_self_answer", lambda p: False)
    assert impl._detect_self_answer(_fake_result(agent_log="/x")) is False


# ── run_plan ───────────────────────────────────────────────────────────────────


def _wire_run_plan(impl, monkeypatch, *, harness="claude-code"):
    monkeypatch.setattr(impl._utils, "default_harness", lambda: harness)
    events: list = []
    monkeypatch.setattr(impl, "_emit_event", lambda ev, payload: events.append((ev, payload)))
    return events


def test_run_plan_hitl_emits_spawned_returns_zero(impl, monkeypatch, tmp_path):
    events = _wire_run_plan(impl, monkeypatch)
    invoked: list = []
    monkeypatch.setattr(impl, "_invoke_harness", lambda *a, **k: invoked.append(a) or _fake_result())
    plan = _write_plan(tmp_path / "hitl.md", kind="HITL")
    monkeypatch.chdir(tmp_path)
    assert impl.run_plan(plan) == 0
    assert invoked == []  # no harness spawn on HITL
    assert events[0][0] == "chunk_started"
    assert events[0][1]["harness"] == impl.HITL_IN_AGENT


def test_run_plan_afk_clean_result_returns_zero(impl, monkeypatch, tmp_path):
    _wire_run_plan(impl, monkeypatch)
    monkeypatch.setattr(impl, "_invoke_harness", lambda *a, **k: _fake_result(returncode=0))
    monkeypatch.setattr(impl, "_read_blocked_summary", lambda wt: None)
    monkeypatch.setattr(impl, "_detect_self_answer", lambda r: False)
    monkeypatch.setattr(impl, "_compaction_threshold", lambda: None)
    plan = _write_plan(tmp_path / "afk.md", kind="AFK")
    monkeypatch.chdir(tmp_path)
    assert impl.run_plan(plan) == 0


def test_run_plan_afk_wedge_via_blocked_summary(impl, monkeypatch, tmp_path):
    events = _wire_run_plan(impl, monkeypatch)
    monkeypatch.setattr(impl, "_invoke_harness", lambda *a, **k: _fake_result(returncode=0))
    monkeypatch.setattr(impl, "_read_blocked_summary", lambda wt: "blocker text")
    monkeypatch.setattr(impl, "_promote_blocked_summary", lambda body: None)
    plan = _write_plan(tmp_path / "afk.md", kind="AFK")
    monkeypatch.chdir(tmp_path)
    assert impl.run_plan(plan) == impl.EX_HITL_REQUIRED
    ejected = [p for ev, p in events if ev == "chunk_ejected"]
    assert ejected and ejected[0]["reason"] == impl.HITL_REQUIRED
    assert ejected[0]["summary"] == "blocker text"


def test_run_plan_afk_self_answer(impl, monkeypatch, tmp_path):
    events = _wire_run_plan(impl, monkeypatch)
    monkeypatch.setattr(impl, "_invoke_harness", lambda *a, **k: _fake_result(returncode=0))
    monkeypatch.setattr(impl, "_read_blocked_summary", lambda wt: None)
    monkeypatch.setattr(impl, "_detect_self_answer", lambda r: True)
    monkeypatch.setattr(impl, "_promote_blocked_summary", lambda body: None)
    plan = _write_plan(tmp_path / "afk.md", kind="AFK")
    monkeypatch.chdir(tmp_path)
    assert impl.run_plan(plan) == impl.EX_HITL_REQUIRED
    reasons = [p["reason"] for ev, p in events if ev == "chunk_ejected"]
    assert impl.HITL_REQUIRED in reasons


def test_run_plan_afk_nonzero_return_is_implement_failed(impl, monkeypatch, tmp_path):
    events = _wire_run_plan(impl, monkeypatch)
    monkeypatch.setattr(impl, "_invoke_harness", lambda *a, **k: _fake_result(returncode=3))
    monkeypatch.setattr(impl, "_read_blocked_summary", lambda wt: None)
    monkeypatch.setattr(impl, "_detect_self_answer", lambda r: False)
    plan = _write_plan(tmp_path / "afk.md", kind="AFK")
    monkeypatch.chdir(tmp_path)
    assert impl.run_plan(plan) == 1
    reasons = [p["reason"] for ev, p in events if ev == "chunk_ejected"]
    assert reasons == [impl.IMPLEMENT_FAILED]


def test_run_plan_afk_sets_ro_mounts_from_manifest(impl, monkeypatch, tmp_path):
    _wire_run_plan(impl, monkeypatch)
    monkeypatch.setattr(impl, "read_tests_manifest", lambda slug: (["tests/a_test.py"], []))
    monkeypatch.setattr(impl, "_invoke_harness", lambda *a, **k: _fake_result(returncode=0))
    monkeypatch.setattr(impl, "_read_blocked_summary", lambda wt: None)
    monkeypatch.setattr(impl, "_detect_self_answer", lambda r: False)
    monkeypatch.setattr(impl, "_compaction_threshold", lambda: None)
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    plan = _write_plan(tmp_path / "afk.md", kind="AFK")
    monkeypatch.chdir(tmp_path)
    assert impl.run_plan(plan) == 0
    assert json.loads(impl.os.environ["MENTAT_RO_MOUNTS"]) == ["tests/a_test.py"]


# ── _run_and_doctor ────────────────────────────────────────────────────────────


def test_run_and_doctor_doctors_on_diagnosable_code(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl, "run_plan", lambda *a, **k: 1)
    with _recorder(monkeypatch, impl, "_auto_doctor") as doctored:
        with _recorder(monkeypatch, impl, "_auto_summary") as summarized:
            plan = _write_plan(tmp_path / "afk.md", kind="AFK")
            assert impl._run_and_doctor(plan) == 1
    assert len(doctored) == 1
    assert summarized == []


def test_run_and_doctor_summary_on_ok_afk(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl, "run_plan", lambda *a, **k: impl.EX_OK)
    with _recorder(monkeypatch, impl, "_auto_summary") as summarized:
        with _recorder(monkeypatch, impl, "_auto_doctor") as doctored:
            plan = _write_plan(tmp_path / "afk.md", kind="AFK")
            assert impl._run_and_doctor(plan) == impl.EX_OK
    assert len(summarized) == 1
    assert doctored == []


def test_run_and_doctor_ok_hitl_no_summary_no_doctor(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl, "run_plan", lambda *a, **k: impl.EX_OK)
    with _recorder(monkeypatch, impl, "_auto_summary") as summarized:
        with _recorder(monkeypatch, impl, "_auto_doctor") as doctored:
            plan = _write_plan(tmp_path / "hitl.md", kind="HITL")
            assert impl._run_and_doctor(plan) == impl.EX_OK
    assert summarized == []
    assert doctored == []


# ── _run_agent_cmd ───────────────────────────────────────────────────────────


def test_run_agent_cmd_missing_script_no_spawn(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(impl, "_AGENT_SCRIPT", tmp_path / "nope.py")
    with _recorder(monkeypatch, impl.subprocess, "run") as ran:
        impl._run_agent_cmd("doctor")
    assert ran == []


def test_run_agent_cmd_present_appends_agent_id(impl, monkeypatch, tmp_path):
    script = tmp_path / "agent.py"
    script.write_text("# stub\n")
    monkeypatch.setattr(impl, "_AGENT_SCRIPT", script)
    monkeypatch.setenv("MENTAT_AGENT", "sess-9")
    captured: list = []
    monkeypatch.setattr(impl.subprocess, "run", lambda cmd, **k: captured.append(cmd))
    impl._run_agent_cmd("report")
    assert captured[0][-2:] == ["report", "sess-9"]


# ── _auto_doctor / _auto_summary ───────────────────────────────────────────────


def test_auto_doctor_no_editor_just_doctors(impl, monkeypatch):
    monkeypatch.delenv("EDITOR", raising=False)
    seen: list = []
    monkeypatch.setattr(impl, "_run_agent_cmd", lambda sub: seen.append(sub))
    with _recorder(monkeypatch, impl.subprocess, "run") as ran:
        impl._auto_doctor()
    assert seen == ["doctor"]
    assert ran == []


def test_auto_summary_runs_report(impl, monkeypatch):
    seen: list = []
    monkeypatch.setattr(impl, "_run_agent_cmd", lambda sub: seen.append(sub))
    impl._auto_summary()
    assert seen == ["report"]


# ── _teardown_worktree ─────────────────────────────────────────────────────────


def test_teardown_worktree_clean_removes(impl, monkeypatch, tmp_path, capsys):
    from lib import devcontainer, worktrees

    repo = tmp_path / "repo"
    init_git_repo(repo)
    wt = repo / ".mentat" / "worktrees" / TEST_CHUNK_ID / "slug"
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", f"mentat/{TEST_CHUNK_ID}/slug", str(wt), "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(devcontainer, "down", lambda name: None)
    monkeypatch.setattr(worktrees, "teardown", lambda target: True)
    impl._teardown_worktree(wt)
    assert "removed clean" in capsys.readouterr().err


def test_teardown_worktree_dirty_preserves(impl, monkeypatch, tmp_path, capsys):
    from lib import devcontainer, worktrees

    repo = tmp_path / "repo"
    init_git_repo(repo)
    wt = repo / ".mentat" / "worktrees" / TEST_CHUNK_ID / "slug"
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", f"mentat/{TEST_CHUNK_ID}/slug", str(wt), "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(devcontainer, "down", lambda name: None)
    monkeypatch.setattr(worktrees, "teardown", lambda target: False)
    impl._teardown_worktree(wt)
    assert "preserving dirty" in capsys.readouterr().err


# ── _prune_worktrees_preflight ─────────────────────────────────────────────────


def test_prune_worktrees_preflight_runs(impl, monkeypatch, tmp_path):
    from lib import devcontainer, worktrees

    from tests.conftest import TEST_CHUNK_ID

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MENTAT_CHUNK_ID", TEST_CHUNK_ID)
    monkeypatch.setattr(devcontainer, "list_active_slugs", lambda: {"a"})
    seen: dict = {}

    def _prune(root, active_slugs, scope_chunk_ids=None):
        seen.update(active=active_slugs, scope=scope_chunk_ids)

    monkeypatch.setattr(worktrees, "prune_stale", _prune)
    impl._prune_worktrees_preflight()
    assert seen["active"] == {"a"}
    assert seen["scope"] == {TEST_CHUNK_ID}


# ── _repo_root_from_worktree ───────────────────────────────────────────────────


def test_repo_root_from_worktree_uses_common_dir(impl, monkeypatch, tmp_path):
    common = tmp_path / "repo" / ".git"
    monkeypatch.setattr(
        impl.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=str(common) + "\n"),
    )
    assert impl._repo_root_from_worktree(tmp_path / "wt") == tmp_path / "repo"


def test_repo_root_from_worktree_falls_back_on_error(impl, monkeypatch, tmp_path):
    monkeypatch.setattr(
        impl.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=""),
    )
    wt = tmp_path / "a" / "b" / "c" / "d"
    assert impl._repo_root_from_worktree(wt) == wt.parents[2]


# ── _is_main_worktree ──────────────────────────────────────────────────────────


def test_is_main_worktree_true(impl, monkeypatch, tmp_path):
    wt_py = tmp_path / "worktree.py"
    wt_py.write_text("def is_main_worktree(cwd):\n    return True\n")
    monkeypatch.setattr(impl, "_GIT_WORKTREE_PY", wt_py)
    assert impl._is_main_worktree(Path.cwd()) is True


def test_is_main_worktree_load_failure_returns_false(impl, monkeypatch, tmp_path, capsys):
    wt_py = tmp_path / "worktree.py"
    wt_py.write_text("def is_main_worktree(cwd):\n    this is a syntax error\n")
    monkeypatch.setattr(impl, "_GIT_WORKTREE_PY", wt_py)
    assert impl._is_main_worktree(Path.cwd()) is False
    assert "load failed" in capsys.readouterr().err


def test_is_main_worktree_bogus_spec_returns_false(impl, monkeypatch, tmp_path):
    # A path with no importable loader → spec_from_file_location returns None.
    monkeypatch.setattr(impl, "_GIT_WORKTREE_PY", tmp_path / "nofile.txtnope")
    assert impl._is_main_worktree(Path.cwd()) is False


# ── _in_shared_main_tree ───────────────────────────────────────────────────────


def test_in_shared_main_tree_skip_env_false(impl, monkeypatch):
    monkeypatch.setenv("MENTAT_SKIP_PREFLIGHT", "1")
    assert impl._in_shared_main_tree() is False


def test_in_shared_main_tree_not_in_repo_false(impl, monkeypatch):
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    monkeypatch.setattr(impl.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
    assert impl._in_shared_main_tree() is False


def test_in_shared_main_tree_delegates_to_is_main(impl, monkeypatch):
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    monkeypatch.setattr(impl.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="true\n"))
    monkeypatch.setattr(impl, "_is_main_worktree", lambda cwd: True)
    assert impl._in_shared_main_tree() is True


# ── preflight_worktree ─────────────────────────────────────────────────────────


def test_preflight_worktree_skip_env(impl, monkeypatch):
    monkeypatch.setenv("MENTAT_SKIP_PREFLIGHT", "1")
    assert impl.preflight_worktree("slug") == (0, None)


def test_preflight_worktree_missing_git_script(impl, monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    monkeypatch.setattr(impl, "_GIT_SCRIPT", tmp_path / "nope.py")
    assert impl.preflight_worktree("slug") == (0, None)


def test_preflight_worktree_not_shared_main(impl, monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    script = tmp_path / "git.py"
    script.write_text("# stub\n")
    monkeypatch.setattr(impl, "_GIT_SCRIPT", script)
    monkeypatch.setattr(impl, "_in_shared_main_tree", lambda reuse_worktree=False: False)
    assert impl.preflight_worktree("slug") == (0, None)


def test_preflight_worktree_create_nonzero(impl, monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    script = tmp_path / "git.py"
    script.write_text("# stub\n")
    monkeypatch.setattr(impl, "_GIT_SCRIPT", script)
    monkeypatch.setattr(impl, "_in_shared_main_tree", lambda reuse_worktree=False: True)
    monkeypatch.setattr(impl.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=65, stdout=""))
    assert impl.preflight_worktree("slug") == (65, None)


def test_preflight_worktree_success_returns_target(impl, monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    script = tmp_path / "git.py"
    script.write_text("# stub\n")
    monkeypatch.setattr(impl, "_GIT_SCRIPT", script)
    monkeypatch.setattr(impl, "_in_shared_main_tree", lambda reuse_worktree=False: True)
    target = tmp_path / "wt"
    target.mkdir()
    monkeypatch.setattr(
        impl.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=f"noise line\n{target}\n"),
    )
    assert impl.preflight_worktree("slug") == (0, target)


def test_preflight_worktree_empty_stdout_is_software(impl, monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    script = tmp_path / "git.py"
    script.write_text("# stub\n")
    monkeypatch.setattr(impl, "_GIT_SCRIPT", script)
    monkeypatch.setattr(impl, "_in_shared_main_tree", lambda reuse_worktree=False: True)
    monkeypatch.setattr(impl.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="   "))
    assert impl.preflight_worktree("slug") == (impl.EX_SOFTWARE, None)


def test_preflight_worktree_non_dir_path_is_software(impl, monkeypatch, tmp_path):
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    script = tmp_path / "git.py"
    script.write_text("# stub\n")
    monkeypatch.setattr(impl, "_GIT_SCRIPT", script)
    monkeypatch.setattr(impl, "_in_shared_main_tree", lambda reuse_worktree=False: True)
    monkeypatch.setattr(
        impl.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=str(tmp_path / "does-not-exist") + "\n"),
    )
    assert impl.preflight_worktree("slug") == (impl.EX_SOFTWARE, None)


# ── _do_land / _land_and_review ────────────────────────────────────────────────


def test_land_and_review_returns_verdict(impl, monkeypatch, tmp_path):
    fake_land_queue = SimpleNamespace(
        Chunk=lambda slug, worktree, chunk_id="": SimpleNamespace(slug=slug, worktree=worktree, chunk_id=chunk_id),
        land=lambda chunk, holding: {"status": "landed", "tip": "abc123"},
    )
    monkeypatch.setattr(impl, "_load_mod", lambda key, path: fake_land_queue)
    out = impl._land_and_review("slug", tmp_path / "wt", "main")
    assert out == {"status": "landed", "tip": "abc123", "holding": "main"}


# ── build_parser ──────────────────────────────────────────────────────────────


def testbuild_parser_run_namespace(impl):
    args = impl.build_parser().parse_args(
        ["run", "plan1", "--harness", "h", "--model", "m", "--land", "--holding", "hb"]
    )
    assert args.command == "run"
    assert args.plan_refs == ["plan1"]
    assert args.harness == "h"
    assert args.model == "m"
    assert args.land is True
    assert args.holding == "hb"


def testbuild_parser_mark_test_writable(impl):
    args = impl.build_parser().parse_args(["mark-test-writable", "slug", "path/x_test.py"])
    assert args.command == "mark-test-writable"
    assert args.slug == "slug"
    assert args.path == "path/x_test.py"


def testbuild_parser_run_minimal(impl):
    args = impl.build_parser().parse_args(["run", "p"])
    assert args.plan_refs == ["p"]


def testbuild_parser_requires_subcommand(impl):
    with pytest.raises(SystemExit):
        impl.build_parser().parse_args([])


# ── main ───────────────────────────────────────────────────────────────────────


def _wire_main(impl, monkeypatch):
    """Neutralize every seam main() touches so tests set only what they assert."""
    monkeypatch.setattr(impl.os, "chdir", lambda *a, **k: None)
    monkeypatch.setattr(impl, "ensure_agent", lambda role, slug: "sess")
    monkeypatch.setattr(impl, "_prune_worktrees_preflight", lambda: None)
    monkeypatch.setattr(impl._utils, "default_harness", lambda: "claude-code")
    monkeypatch.setattr(impl, "preflight_veto_reviewers", lambda h, reuse_worktree=False: (0, []))
    monkeypatch.setattr(impl, "preflight_worktree", lambda slug, reuse_worktree=False: (0, None))
    monkeypatch.setattr(impl, "_in_shared_main_tree", lambda reuse_worktree=False: False)
    monkeypatch.setattr(impl, "_run_and_doctor", lambda *a, **k: 0)
    monkeypatch.setattr(impl, "_land_and_review", lambda *a, **k: {})
    monkeypatch.setattr(impl, "_teardown_worktree", lambda t: None)
    monkeypatch.setattr(impl, "_repo_root_from_worktree", lambda t: Path("/repo"))
    events: list = []
    monkeypatch.setattr(impl, "_emit_event", lambda ev, payload: events.append((ev, payload)))
    return events


def test_main_mark_test_writable_dispatch(impl, monkeypatch):
    _wire_main(impl, monkeypatch)
    seen: list = []
    monkeypatch.setattr(impl, "mark_test_writable", lambda slug, path: seen.append((slug, path)))
    monkeypatch.setattr(impl.sys, "argv", ["i", "mark-test-writable", "slug", "p.py"])
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == impl.EX_OK
    assert seen == [("slug", "p.py")]


def test_main_default_run_insertion(impl, monkeypatch, tmp_path):
    _wire_main(impl, monkeypatch)
    plan = _write_plan(tmp_path / "p.md", kind="HITL")
    monkeypatch.setattr(impl, "resolve_plan_path", lambda ref: plan)
    monkeypatch.setattr(impl.sys, "argv", ["i", "p"])  # no subcommand
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == 0


def test_main_multiple_plans_refused(impl, monkeypatch, capsys):
    _wire_main(impl, monkeypatch)
    monkeypatch.setattr(impl.sys, "argv", ["i", "run", "a", "b"])
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == 1
    assert "one plan at a time" in capsys.readouterr().err


def test_main_plan_not_found(impl, monkeypatch, tmp_path, capsys):
    _wire_main(impl, monkeypatch)
    monkeypatch.setattr(impl, "resolve_plan_path", lambda ref: tmp_path / "ghost.md")
    monkeypatch.setattr(impl.sys, "argv", ["i", "run", "ghost"])
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == 1
    assert "plan not found" in capsys.readouterr().err


def test_main_veto_preflight_fail(impl, monkeypatch, tmp_path, capsys):
    _wire_main(impl, monkeypatch)
    plan = _write_plan(tmp_path / "p.md", kind="AFK")
    monkeypatch.setattr(impl, "resolve_plan_path", lambda ref: plan)
    monkeypatch.setattr(impl, "preflight_veto_reviewers", lambda h, reuse_worktree=False: (1, ["mentat-plan-reviewer"]))
    monkeypatch.setattr(impl.sys, "argv", ["i", "run", "p"])
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == 1
    assert "PREFLIGHT FAILED" in capsys.readouterr().err


def test_main_preflight_worktree_fail_emits_and_exits(impl, monkeypatch, tmp_path):
    events = _wire_main(impl, monkeypatch)
    plan = _write_plan(tmp_path / "p.md", kind="AFK")
    monkeypatch.setattr(impl, "resolve_plan_path", lambda ref: plan)
    monkeypatch.setattr(impl, "preflight_worktree", lambda slug, reuse_worktree=False: (65, None))
    monkeypatch.setattr(impl.sys, "argv", ["i", "run", "p"])
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == 65
    reasons = [p["reason"] for ev, p in events if ev == "chunk_ejected"]
    assert reasons == [impl.PREFLIGHT_WORKTREE_FAILED]


def test_main_main_tree_refused(impl, monkeypatch, tmp_path):
    events = _wire_main(impl, monkeypatch)
    plan = _write_plan(tmp_path / "p.md", kind="AFK")
    monkeypatch.setattr(impl, "resolve_plan_path", lambda ref: plan)
    monkeypatch.setattr(impl, "preflight_worktree", lambda slug, reuse_worktree=False: (0, None))
    monkeypatch.setattr(impl, "_in_shared_main_tree", lambda reuse_worktree=False: True)
    monkeypatch.setattr(impl.sys, "argv", ["i", "run", "p"])
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == impl.EX_USAGE
    reasons = [p["reason"] for ev, p in events if ev == "chunk_ejected"]
    assert reasons == [impl.MAIN_TREE_REFUSED]


def test_main_success_no_land_reviews_diff(impl, monkeypatch, tmp_path, capsys):
    _wire_main(impl, monkeypatch)
    plan = _write_plan(tmp_path / "p.md", kind="AFK")
    monkeypatch.setattr(impl, "resolve_plan_path", lambda ref: plan)
    monkeypatch.setattr(impl, "preflight_worktree", lambda slug, reuse_worktree=False: (0, tmp_path / "wt"))
    landed: list = []
    monkeypatch.setattr(impl, "_land_and_review", lambda *a, **k: landed.append(a))
    monkeypatch.setattr(impl.sys, "argv", ["i", "run", "p"])
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == 0
    assert "review the diff" in capsys.readouterr().err
    assert landed == []  # no --land


def test_main_success_with_land_calls_land_and_review(impl, monkeypatch, tmp_path):
    _wire_main(impl, monkeypatch)
    plan = _write_plan(tmp_path / "p.md", kind="AFK")
    monkeypatch.setattr(impl, "resolve_plan_path", lambda ref: plan)
    target = tmp_path / "wt"
    monkeypatch.setattr(impl, "preflight_worktree", lambda slug, reuse_worktree=False: (0, target))
    landed: list = []
    monkeypatch.setattr(impl, "_land_and_review", lambda slug, wt, holding: landed.append((slug, wt, holding)))
    monkeypatch.setattr(impl.sys, "argv", ["i", "run", "p", "--land", "--holding", "hb"])
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == 0
    assert landed == [("p", target, "hb")]


def test_main_failure_tears_down_worktree(impl, monkeypatch, tmp_path):
    _wire_main(impl, monkeypatch)
    plan = _write_plan(tmp_path / "p.md", kind="AFK")
    monkeypatch.setattr(impl, "resolve_plan_path", lambda ref: plan)
    target = tmp_path / "wt"
    monkeypatch.setattr(impl, "preflight_worktree", lambda slug, reuse_worktree=False: (0, target))
    monkeypatch.setattr(impl, "_run_and_doctor", lambda *a, **k: 1)
    torn: list = []
    monkeypatch.setattr(impl, "_teardown_worktree", lambda t: torn.append(t))
    monkeypatch.setattr(impl.sys, "argv", ["i", "run", "p"])
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == 1
    assert torn == [target]


# ── heavy e2e: real repo, real commit, real pre-commit gate hook ───────────────
# The only seam stubbed is the harness boundary — the agent that in production is
# ``claude --headless``. Everything downstream (implement's gate step, the success
# report-back) and the per-slice ``git commit`` runs for real.

_PRE_COMMIT_HOOK = """#!/bin/sh
echo ran >> "$(git rev-parse --git-dir)/gate-ran"
"""


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _init_repo(repo):
    repo.mkdir()
    _git(["init", "-b", "main"], cwd=repo)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _git(["config", k, v], cwd=repo)
    (repo / "README.md").write_text("seed\n")
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", "init"], cwd=repo)
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text(_PRE_COMMIT_HOOK)
    hook.chmod(0o755)


def _fake_agent(repo):
    def invoke(harness, prompt, *, afk, model=None, seed_summary=None):
        (repo / "feature.py").write_text("def feature():\n    return 42\n")
        _git(["add", "feature.py"], cwd=repo)
        _git(["commit", "-m", "feat(core): add feature module"], cwd=repo)
        return SimpleNamespace(returncode=0, usage_tokens=None, agent_log=None)

    return invoke


def test_implement_one_slice_commits_via_pre_commit_hook(impl, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    plan = _write_plan(tmp_path / "tiny-slice.md", kind="AFK", body="# Tiny slice\nAdd a feature module.")

    monkeypatch.setenv("MENTAT_SKIP_PREFLIGHT", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    monkeypatch.setenv("MENTAT_AGENT", "implement-tiny-slice-1")
    monkeypatch.chdir(repo)

    before = _git(["rev-list", "--count", "HEAD"], cwd=repo)

    monkeypatch.setattr(impl, "_invoke_harness", _fake_agent(repo))

    rc = impl._run_and_doctor(plan)
    assert rc == 0

    after = _git(["rev-list", "--count", "HEAD"], cwd=repo)
    assert int(after) == int(before) + 1
    assert _git(["log", "-1", "--format=%s"], cwd=repo) == "feat(core): add feature module"
    assert "feature.py" in _git(["ls-tree", "--name-only", "HEAD"], cwd=repo)
    assert (repo / ".git/gate-ran").exists()
