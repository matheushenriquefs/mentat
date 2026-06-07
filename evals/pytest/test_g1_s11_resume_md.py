"""G1-S11: rebase-conflict eject drops RESUME.md at worktree root.

Spec (~/.agents/plans/mentat-architecture-revamp-g1-audit-substrate.md S11):
  - After rebase-conflict eject, write RESUME.md to worktree root containing:
      * conflicted files list
      * the exact resume command (`cd <wt> && git rebase --continue`)
      * one-line "what was being rebased" pointer
        (chunk slug, source branch, holding tip SHA)
  - Operator can `cat RESUME.md && git rebase --continue` without consulting
    other docs.

Blocked-by: S10 (done). Negative case: gate-fail/not-ff ejects must NOT drop
RESUME.md (no rebase to resume).
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAND_QUEUE = ROOT / ".agents" / "bin" / "mentat-land-queue"
HARNESS_DIR = ROOT / ".agents" / "bin" / "lib" / "harness"


# -- Source-level assertions --------------------------------------------------


def test_land_queue_references_resume_md():
    src = LAND_QUEUE.read_text()
    assert "RESUME.md" in src, "mentat-land-queue must write RESUME.md on rebase-conflict eject (S11)"


def test_land_queue_cites_s11():
    src = LAND_QUEUE.read_text()
    assert "S11" in src or "RESUME.md" in src, "mentat-land-queue must signpost S11 contract"


# -- Behavior smoke -----------------------------------------------------------


def _install_stub_harness(harness_dir: Path) -> Path:
    """Stub harness — green by default, $STUB_EXIT controls re-gate verdict.
    Removed in fixture teardown to preserve 8-harness invariant
    (test_p2_rename::test_harness_subdir_has_8_files)."""
    stub = harness_dir / "stub.sh"
    stub.write_text(
        textwrap.dedent("""\
        #!/bin/bash
        harness_stub_cmd() {
          printf '%s\\0' bash -c "echo '{\\"type\\":\\"text\\",\\"line\\":\\"stub ok\\"}'; exit ${STUB_EXIT:-0}"
        }
        harness_stub_output_format() { printf 'stub\\n'; }
        harness_stub_normalize() {
          jq -c --arg agent stub --arg sess "${MENTAT_SESSION:-unknown}" \\
            '{ts:(now|todate), agent:$agent, session:$sess, event:(.type // "unknown"), payload:(del(.type))}'
        }
    """)
    )
    return stub


def _install_container_run_stub(fake_bin: Path) -> None:
    cr = fake_bin / "mentat-container-run"
    cr.write_text('#!/usr/bin/env bash\nexec bash -c "$1"\n')
    cr.chmod(0o755)


@pytest.fixture
def stub_env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "base.txt").write_text("base\n")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    fake_home = tmp_path / "home"
    fake_bin = fake_home / ".agents" / "bin"
    fake_bin.mkdir(parents=True)
    cu = fake_bin / "mentat-container-up"
    cu.write_text("#!/usr/bin/env bash\necho 'stub container-up' >&2\n")
    cu.chmod(0o755)
    _install_container_run_stub(fake_bin)

    stub_file = _install_stub_harness(HARNESS_DIR)

    cfg = tmp_path / ".mentat.jsonc"
    cfg.write_text(
        json.dumps(
            {
                "harness": {"name": "stub", "model": ""},
                "agents": {"max_concurrent": 3},
                "diff": {"tool": "git"},
                "editor": {"name": "vi"},
                "plugins": [],
            }
        )
    )

    log_root = tmp_path / "logs"
    log_root.mkdir()
    session = "1700000000-31337"
    try:
        yield {
            "tmp": tmp_path,
            "repo": repo,
            "home": fake_home,
            "config": cfg,
            "log_root": log_root,
            "session": session,
        }
    finally:
        stub_file.unlink(missing_ok=True)


def _spawn_conflicting_chunk(repo: Path, slug: str) -> Path:
    wt = repo / ".mentat" / "worktrees" / slug
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "worktree", "add", "-b", slug, str(wt), "main"], cwd=repo, check=True)
    (wt / "base.txt").write_text("chunk-side\n")
    subprocess.run(["git", "add", "base.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"chunk {slug}"], cwd=wt, check=True)
    (repo / "base.txt").write_text("main-side\n")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "main divergent"], cwd=repo, check=True)
    return wt


def _run_land_queue(stub_env, *, stdin: str, holding: str = "main", stub_exit: int = 0):
    env = {
        **os.environ,
        "HOME": str(stub_env["home"]),
        "MENTAT_CONFIG_PATH": str(stub_env["config"]),
        "MENTAT_LOG_PATH": str(stub_env["log_root"]),
        "MENTAT_SESSION": stub_env["session"],
        "MENTAT_REPO": "repo",
        "STUB_EXIT": str(stub_exit),
    }
    return subprocess.run(
        ["bash", str(LAND_QUEUE), holding],
        cwd=str(stub_env["repo"]),
        input=stdin,
        text=True,
        capture_output=True,
        timeout=60,
        env=env,
    )


def _read_audit_rows(stub_env) -> list[dict]:
    logdir = stub_env["log_root"] / "repo" / stub_env["session"]
    rows: list[dict] = []
    if not logdir.exists():
        return rows
    for jl in sorted(logdir.glob("*.jsonl")):
        for line in jl.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _parse_verdicts(stdout: str) -> list[dict]:
    out = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# -- RESUME.md drop -----------------------------------------------------------


def test_rebase_conflict_drops_resume_md_at_worktree_root(stub_env):
    slug = "mentat-s11-drop"
    wt = _spawn_conflicting_chunk(stub_env["repo"], slug)
    proc = _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    assert proc.returncode == 1, f"eject must exit 1; stderr={proc.stderr!r}"
    resume = wt / "RESUME.md"
    assert resume.is_file(), f"RESUME.md missing at {resume}; wt listing={list(wt.iterdir())}"


def test_resume_md_lists_conflicted_files(stub_env):
    slug = "mentat-s11-conflicted-files"
    wt = _spawn_conflicting_chunk(stub_env["repo"], slug)
    _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    body = (wt / "RESUME.md").read_text()
    assert "base.txt" in body, f"RESUME.md must list conflicted base.txt; got:\n{body}"


def test_resume_md_contains_resume_cmd(stub_env):
    slug = "mentat-s11-cmd"
    wt = _spawn_conflicting_chunk(stub_env["repo"], slug)
    _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    body = (wt / "RESUME.md").read_text()
    assert "git rebase --continue" in body, f"RESUME.md must contain `git rebase --continue`:\n{body}"
    assert f"cd {wt}" in body or str(wt) in body, f"RESUME.md must reference the worktree path:\n{body}"


def test_resume_md_contains_chunk_slug(stub_env):
    slug = "mentat-s11-slug-id"
    wt = _spawn_conflicting_chunk(stub_env["repo"], slug)
    _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    body = (wt / "RESUME.md").read_text()
    assert slug in body, f"RESUME.md must contain chunk slug `{slug}`:\n{body}"


def test_resume_md_contains_holding_branch(stub_env):
    slug = "mentat-s11-holding"
    wt = _spawn_conflicting_chunk(stub_env["repo"], slug)
    _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    body = (wt / "RESUME.md").read_text()
    assert "main" in body, f"RESUME.md must reference holding branch `main`:\n{body}"


def test_resume_md_contains_holding_tip_sha(stub_env):
    slug = "mentat-s11-tipsha"
    wt = _spawn_conflicting_chunk(stub_env["repo"], slug)
    # Capture the pre-rebase holding tip SHA (post-divergent-commit on main).
    onto = subprocess.run(
        ["git", "-C", str(stub_env["repo"]), "rev-parse", "--short", "main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    body = (wt / "RESUME.md").read_text()
    assert onto in body, f"RESUME.md must contain holding tip short SHA `{onto}`:\n{body}"


def test_resume_md_content_matches_audit_row(stub_env):
    """RESUME.md fields must agree with the audit payload — single source of
    truth for conflict triage."""
    slug = "mentat-s11-audit-parity"
    wt = _spawn_conflicting_chunk(stub_env["repo"], slug)
    _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    body = (wt / "RESUME.md").read_text()

    rows = _read_audit_rows(stub_env)
    landed = [r for r in rows if r.get("event") == "land.complete"]
    assert landed, "land.complete audit row missing"
    p = landed[-1]["payload"]
    for f in p.get("conflicted_files", []):
        assert f in body, f"RESUME.md missing conflicted file {f!r} from audit payload"
    cmd = p.get("resume_cmd", "")
    assert cmd and cmd in body, f"RESUME.md must contain audit resume_cmd `{cmd}`; body:\n{body}"


# -- Negative cases -----------------------------------------------------------


def test_gate_fail_eject_does_not_drop_resume_md(stub_env):
    """RESUME.md is rebase-conflict-only — gate-fail leaves no rebase to resume."""
    slug = "mentat-s11-gatefail-no-resume"
    wt = stub_env["repo"] / ".mentat" / "worktrees" / slug
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", slug, str(wt), "main"],
        cwd=stub_env["repo"],
        check=True,
    )
    (wt / "feature.txt").write_text("ok\n")
    subprocess.run(["git", "add", "feature.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "feat"], cwd=wt, check=True)

    proc = _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main", stub_exit=9)
    assert proc.returncode == 1
    assert not (wt / "RESUME.md").exists(), "gate-fail eject must NOT drop RESUME.md"


def test_resume_md_first_line_pointer(stub_env):
    """One-line 'what was being rebased' pointer — slug + holding + tip SHA all
    must appear within the first few lines so `cat RESUME.md` is glanceable."""
    slug = "mentat-s11-pointer"
    wt = _spawn_conflicting_chunk(stub_env["repo"], slug)
    onto = subprocess.run(
        ["git", "-C", str(stub_env["repo"]), "rev-parse", "--short", "main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    head = "\n".join((wt / "RESUME.md").read_text().splitlines()[:5])
    assert slug in head, f"first 5 lines must contain slug `{slug}`:\n{head}"
    assert "main" in head, f"first 5 lines must contain holding `main`:\n{head}"
    assert onto in head, f"first 5 lines must contain tip sha `{onto}`:\n{head}"
