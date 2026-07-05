"""E2E gap-closer: land-queue seams the main journey test leaves uncovered.

Companion to ``test_land_queue_journey.py``. Reaches the un-patched helper
bodies (``_run_gates`` delegating to the plans util, ``_teardown_container``
firing the real teardown audit row), the ff-merge failure eject arm in
``land`` (both not-ff and git-error), and the cascade branch that skips a
downstream slug already gone from the pending set. Git-touching arms use real
worktrees; the docker seam is stubbed — never a real container.
"""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.conftest import TEST_CHUNK_ID, load_script

pytestmark = pytest.mark.e2e

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-orchestrate/scripts"


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@contextmanager
def _patch_attr(obj, name, value):
    saved = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, saved)


def _setup(tmp_path: Path, slugs: list[str]):
    main_repo = tmp_path / "repo"
    main_repo.mkdir()
    _git(["init", "-b", "holding", "."], cwd=main_repo)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _git(["config", k, v], cwd=main_repo)
    (main_repo / "base.txt").write_text("base\n")
    _git(["add", "."], cwd=main_repo)
    _git(["commit", "-m", "init"], cwd=main_repo)

    wt_root = main_repo / ".mentat" / "worktrees"
    wt_root.mkdir(parents=True)
    worktrees: dict[str, Path] = {}
    for slug in slugs:
        wt = wt_root / slug
        _git(["worktree", "add", "-b", slug, str(wt), "holding"], cwd=main_repo)
        (wt / f"{slug}.txt").write_text(f"{slug}\n")
        _git(["add", f"{slug}.txt"], cwd=wt)
        _git(["commit", "-m", f"feat: {slug}"], cwd=wt)
        worktrees[slug] = wt
    return main_repo, worktrees


def _configure_env(monkeypatch, tmp_path: Path, main_repo: Path) -> Path:
    log_root = tmp_path / "logs"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    monkeypatch.setenv("MENTAT_SESSION", "orchestrate-holding-gaps")
    monkeypatch.chdir(main_repo)
    return log_root


def _events(log_root: Path, name: str) -> list[dict]:
    out: list[dict] = []
    for f in log_root.rglob("*.jsonl"):
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, dict) and row.get("event") == name:
                out.append(row)
    return out


# ── _run_gates: the un-patched delegation to the plans util (line 37) ─────────


def test_run_gates_delegates_to_plans_util(tmp_path):
    lq = load_script(SCRIPTS / "land_queue.py", "e2e_lq_gaps_gates")
    captured: dict[str, Path] = {}

    def fake_run_gates(worktree):
        captured["worktree"] = worktree
        return ("advise", "noted")

    wt = tmp_path / "wt"
    wt.mkdir()
    with _patch_attr(lq._utils, "run_gates", fake_run_gates):
        verdict, message = lq._run_gates(lq.Chunk("s1", wt))

    assert (verdict, message) == ("advise", "noted")
    assert captured["worktree"] == wt, "the chunk worktree is forwarded to the util"


# ── _teardown_container: real body → devcontainer.down + audit row (50-53) ────


def test_teardown_container_fires_real_teardown_event(tmp_path, monkeypatch):
    lq = load_script(SCRIPTS / "land_queue.py", "e2e_lq_gaps_teardown")
    log_root = tmp_path / "logs"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    monkeypatch.setenv("MENTAT_SESSION", "orchestrate-teardown-gaps")

    from lib import devcontainer

    with _patch_attr(devcontainer, "down", lambda slug: True):
        lq._teardown_container(lq.Chunk(slug="dead-slug", worktree=tmp_path / "wt", chunk_id=TEST_CHUNK_ID))

    rows = _events(log_root, "chunk.teardown")
    assert any(r["payload"]["slug"] == "dead-slug" and r["payload"]["ok"] is True for r in rows), rows


# ── land: ff-merge failure eject arm — not-ff and git-error (88-93) ───────────


def test_land_ejects_not_ff_when_ff_merge_reports_not_ff(tmp_path, monkeypatch):
    lq = load_script(SCRIPTS / "land_queue.py", "e2e_lq_gaps_notff")
    main_repo, wts = _setup(tmp_path, ["moved"])
    log_root = _configure_env(monkeypatch, tmp_path, main_repo)

    with (
        _patch_attr(lq, "_run_gates", lambda chunk: ("pass", "")),
        _patch_attr(lq, "_ff_merge", lambda chunk, holding: "not-ff"),
        _patch_attr(lq, "_teardown_container", lambda chunk: None),
    ):
        verdict = lq.land(lq.Chunk("moved", wts["moved"]), holding="holding")

    assert verdict["status"] == "eject"
    assert verdict["reason"] == lq.EjectReason.NOT_FF
    ejects = _events(log_root, "chunk.ejected")
    assert {e["payload"]["reason"] for e in ejects} == {lq.EjectReason.NOT_FF}


def test_land_ejects_git_error_when_ff_merge_reports_other_error(tmp_path, monkeypatch):
    lq = load_script(SCRIPTS / "land_queue.py", "e2e_lq_gaps_giterr")
    main_repo, wts = _setup(tmp_path, ["broken"])
    _configure_env(monkeypatch, tmp_path, main_repo)

    with (
        _patch_attr(lq, "_run_gates", lambda chunk: ("pass", "")),
        _patch_attr(lq, "_ff_merge", lambda chunk, holding: "git-error"),
        _patch_attr(lq, "_teardown_container", lambda chunk: None),
    ):
        verdict = lq.land(lq.Chunk("broken", wts["broken"]), holding="holding")

    assert verdict["status"] == "eject"
    assert verdict["reason"] == lq.EjectReason.GIT_ERROR
    # holding never advanced — the merge failed.
    assert int(_git(["rev-list", "--count", "refs/heads/holding"], cwd=main_repo)) == 1


# ── drain cascade: a cascaded slug already gone from pending is skipped (174) ──


def test_drain_cascade_skips_downstream_not_in_pending(tmp_path, monkeypatch):
    lq = load_script(SCRIPTS / "land_queue.py", "e2e_lq_gaps_cascade")
    main_repo, wts = _setup(tmp_path, ["root", "child"])
    log_root = _configure_env(monkeypatch, tmp_path, main_repo)

    chunks = [lq.Chunk("root", wts["root"]), lq.Chunk("child", wts["child"])]

    def gate(chunk):
        return ("block", "root failed") if chunk.slug == "root" else ("pass", "")

    order = ["root", "child"]

    def next_ready(pending):
        return next((s for s in order if s in pending), None)

    # on_ejected names "child" (a real dependent, correctly cascade-ejected) plus
    # "ghost" — a slug never in the chunk set, so it is not in pending and the
    # cascade loop must skip it via the 174 guard rather than KeyError.
    def on_ejected(slug):
        return ["child", "ghost"] if slug == "root" else []

    with _patch_attr(lq, "_run_gates", gate), _patch_attr(lq, "_teardown_container", lambda slug: None):
        results = lq.drain(chunks, holding="holding", on_ejected=on_ejected, next_ready=next_ready)

    by_slug = {r.get("slug"): r for r in results}
    assert by_slug["child"]["reason"] == lq.EjectReason.UPSTREAM_EJECTED
    assert "ghost" not in by_slug, "a cascaded slug not in pending yields no result row"
    # And no chunk.ejected audit row was written for the phantom either.
    ejected_slugs = {e["payload"]["slug"] for e in _events(log_root, "chunk.ejected")}
    assert "ghost" not in ejected_slugs
