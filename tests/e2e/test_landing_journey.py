"""E2E: the serial land queue draining real git worktrees, incl. an eject cascade.

Real git throughout: a holding branch and per-chunk worktrees each with one real commit.
``drain`` rebases + ff-merges each chunk onto the live holding tip for real; the two
non-hermetic seams are stubbed — the gate verdict (so one chunk deterministically blocks)
and the docker teardown. Asserts a clean chunk lands and advances holding, a blocked
chunk is ejected without touching holding, and a dependency-ordered drain cascades the
ejection to downstream chunks. Real chunk_landed / chunk_ejected audit rows throughout.
"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.conftest import events_by_kind, load_script

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
    """A holding branch + one worktree per slug, each with a distinct committed file."""
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


def _configure_env(monkeypatch, tmp_path: Path, main_repo: Path) -> str:
    log_root = tmp_path / "logs"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    session = "orchestrate-holding-1"
    monkeypatch.setenv("MENTAT_AGENT", session)
    monkeypatch.setenv("MENTAT_SESSION", session)
    monkeypatch.chdir(main_repo)
    return session


def _events(session_id: str, name: str) -> list[dict]:
    return events_by_kind(session_id, name)


def test_drain_lands_clean_and_ejects_blocked(tmp_path, monkeypatch):
    lq = load_script(SCRIPTS / "landing.py", "e2e_lq")
    main_repo, wts = _setup(tmp_path, ["good", "bad"])
    session = _configure_env(monkeypatch, tmp_path, main_repo)

    before = int(_git(["rev-list", "--count", "refs/heads/holding"], cwd=main_repo))

    chunks = [lq.Chunk("good", wts["good"]), lq.Chunk("bad", wts["bad"])]

    # Gate blocks exactly the "bad" chunk; teardown is a no-op (no docker).
    def gate(chunk):
        return ("block", "smells found") if chunk.slug == "bad" else ("pass", "")

    with _patch_attr(lq, "_run_gates", gate), _patch_attr(lq, "_teardown_container", lambda slug: None):
        results = lq.drain(chunks, holding="holding")

    by_slug = {r["slug"]: r for r in results}
    assert by_slug["good"]["status"] == "success"
    assert by_slug["bad"]["status"] == "eject"
    assert by_slug["bad"]["reason"] == lq.GATE_FAILED

    # Only the clean chunk advanced holding.
    after = int(_git(["rev-list", "--count", "refs/heads/holding"], cwd=main_repo))
    assert after == before + 1, "only the clean chunk ff-merges onto holding"
    tree = _git(["ls-tree", "-r", "--name-only", "refs/heads/holding"], cwd=main_repo).splitlines()
    assert "good.txt" in tree
    assert "bad.txt" not in tree, "a blocked chunk must not land"

    # Real audit rows: one landing, one ejection.
    assert {e["payload"]["slug"] for e in _events(session, "chunk_landed")} == {"good"}
    assert {e["payload"]["slug"] for e in _events(session, "chunk_ejected")} == {"bad"}


def test_drain_cascades_ejection_to_dependents(tmp_path, monkeypatch):
    lq = load_script(SCRIPTS / "landing.py", "e2e_lq_cascade")
    main_repo, wts = _setup(tmp_path, ["root", "child"])
    session = _configure_env(monkeypatch, tmp_path, main_repo)

    chunks = [lq.Chunk("root", wts["root"]), lq.Chunk("child", wts["child"])]

    # root blocks; child depends on root and must cascade-eject without a gate run.
    def gate(chunk):
        return ("block", "root failed") if chunk.slug == "root" else ("pass", "")

    order = ["root", "child"]

    def list_ready_slices(pending):
        slug = next((s for s in order if s in pending), None)
        return [slug] if slug else []

    def on_ejected(slug):
        return ["child"] if slug == "root" else []

    with _patch_attr(lq, "_run_gates", gate), _patch_attr(lq, "_teardown_container", lambda slug: None):
        results = lq.drain(chunks, holding="holding", on_ejected=on_ejected, list_ready_slices=list_ready_slices)

    by_slug = {r["slug"]: r for r in results}
    assert by_slug["root"]["reason"] == lq.GATE_FAILED
    assert by_slug["child"]["status"] == "eject"
    assert by_slug["child"]["reason"] == lq.UPSTREAM_EJECTED
    assert by_slug["child"]["upstream"] == "root"

    # holding never advanced — nothing landed.
    assert int(_git(["rev-list", "--count", "refs/heads/holding"], cwd=main_repo)) == 1

    ejects = {e["payload"]["slug"]: e["payload"] for e in _events(session, "chunk_ejected")}
    assert ejects["root"]["reason"] == lq.GATE_FAILED
    assert ejects["child"]["reason"] == lq.UPSTREAM_EJECTED
    assert ejects["child"]["upstream"] == "root"


def test_drain_stalls_when_no_chunk_ready(tmp_path, monkeypatch):
    lq = load_script(SCRIPTS / "landing.py", "e2e_lq_stall")
    main_repo, wts = _setup(tmp_path, ["blocked"])
    _configure_env(monkeypatch, tmp_path, main_repo)

    chunks = [lq.Chunk("blocked", wts["blocked"])]

    # An unmet dependency: next_ready never returns the pending chunk → stalled verdict.
    with _patch_attr(lq, "_teardown_container", lambda slug: None):
        results = lq.drain(chunks, holding="holding", list_ready_slices=lambda pending: [])

    assert results[-1]["status"] == "stalled"
    assert results[-1]["pending"] == ["blocked"]
