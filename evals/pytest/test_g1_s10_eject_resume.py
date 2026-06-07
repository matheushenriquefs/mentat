"""G1-S10: mentat-land-queue eject must carry conflicted_files + resume_cmd.

Spec (~/.agents/plans/mentat-architecture-revamp-g1-audit-substrate.md S10):
  - On `git rebase` non-zero: capture `git diff --name-only --diff-filter=U` →
    include in audit row as `conflicted_files` array.
  - Also include the exact `cd <worktree> && git rebase --continue` command
    in the audit row as `resume_cmd`.
  - Eject leaves worktree mid-rebase so operator can `git rebase --continue`.

Blocked-by: S7. Verified-by: trigger rebase conflict → audit row contains
both fields → stdout verdict contains both fields → rebase state persists.
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


def test_land_queue_captures_unmerged_via_diff_filter_u():
    """S10: must use `git diff --name-only --diff-filter=U` to list conflicted files."""
    src = LAND_QUEUE.read_text()
    assert "--diff-filter=U" in src, (
        "mentat-land-queue must capture conflicted files via `git diff --name-only --diff-filter=U` (S10 spec)"
    )


def test_land_queue_emits_resume_cmd_token():
    """S10: source must reference `git rebase --continue` for resume_cmd."""
    src = LAND_QUEUE.read_text()
    assert "git rebase --continue" in src, "mentat-land-queue must build resume_cmd containing `git rebase --continue`"


def test_land_queue_emits_conflicted_files_field():
    src = LAND_QUEUE.read_text()
    assert "conflicted_files" in src, "mentat-land-queue must emit conflicted_files field"


def test_land_queue_emits_resume_cmd_field():
    src = LAND_QUEUE.read_text()
    assert "resume_cmd" in src, "mentat-land-queue must emit resume_cmd field"


def test_land_queue_does_not_abort_rebase_on_conflict():
    """S11 prerequisite: rebase state must persist after eject so operator can
    `git rebase --continue`. Aborting the rebase clears that state."""
    src = LAND_QUEUE.read_text()
    assert "git rebase --abort" not in src, (
        "mentat-land-queue must NOT `git rebase --abort` on conflict — "
        "S10 contract requires worktree left mid-rebase for resume"
    )


def test_land_queue_cites_s10():
    """S10 source-level breadcrumb so future readers find the contract."""
    src = LAND_QUEUE.read_text()
    assert "S10" in src or "conflicted_files" in src, "mentat-land-queue must signpost S10 contract"


# -- Behavior smoke -----------------------------------------------------------


def _install_stub_harness(harness_dir: Path) -> Path:
    """Stub harness — green by default, $STUB_EXIT controls re-gate verdict.
    Removed in fixture teardown to preserve the 8-harness invariant
    (test_p2_rename::test_harness_subdir_has_8_files).
    """
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
    """Create chunk worktree that edits base.txt; then mutate main divergently
    so the rebase will conflict."""
    wt = repo / ".mentat" / "worktrees" / slug
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "worktree", "add", "-b", slug, str(wt), "main"], cwd=repo, check=True)
    (wt / "base.txt").write_text("chunk-side\n")
    subprocess.run(["git", "add", "base.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"chunk {slug}"], cwd=wt, check=True)
    # Divergent main edit forces a conflict on rebase.
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


def test_rebase_conflict_audit_includes_conflicted_files(stub_env):
    """Spec: audit row must contain conflicted_files: [<unmerged paths>]."""
    slug = "mentat-s10-conflict-files"
    _spawn_conflicting_chunk(stub_env["repo"], slug)
    proc = _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    assert proc.returncode == 1, f"eject must exit 1; stderr={proc.stderr!r}"

    rows = _read_audit_rows(stub_env)
    landed = [r for r in rows if r.get("event") == "land.complete"]
    assert landed, f"land.complete row missing; events={[r.get('event') for r in rows]}"
    p = landed[-1]["payload"]
    assert p.get("reason") == "rebase-conflict", f"reason mismatch: {p!r}"
    files = p.get("conflicted_files")
    assert isinstance(files, list) and files, f"conflicted_files must be non-empty list; got {p!r}"
    assert "base.txt" in files, f"conflicted_files must list base.txt; got {files!r}"


def test_rebase_conflict_audit_includes_resume_cmd(stub_env):
    """Spec: audit row must contain resume_cmd of form `cd <wt> && git rebase --continue`."""
    slug = "mentat-s10-resume-cmd"
    wt = _spawn_conflicting_chunk(stub_env["repo"], slug)
    proc = _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    assert proc.returncode == 1, f"eject must exit 1; stderr={proc.stderr!r}"

    rows = _read_audit_rows(stub_env)
    landed = [r for r in rows if r.get("event") == "land.complete"]
    p = landed[-1]["payload"]
    cmd = p.get("resume_cmd")
    assert isinstance(cmd, str) and cmd, f"resume_cmd must be non-empty string; got {p!r}"
    assert "git rebase --continue" in cmd, f"resume_cmd must invoke `git rebase --continue`; got {cmd!r}"
    assert str(wt) in cmd or slug in cmd, f"resume_cmd must reference worktree path/slug; got {cmd!r}"
    assert cmd.startswith("cd "), f"resume_cmd must start with `cd <worktree>`; got {cmd!r}"


def test_rebase_conflict_verdict_includes_conflicted_files(stub_env):
    """Stdout verdict mirrors audit payload — conflicted_files surfaces to caller."""
    slug = "mentat-s10-verdict-files"
    _spawn_conflicting_chunk(stub_env["repo"], slug)
    proc = _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    verdicts = _parse_verdicts(proc.stdout)
    assert verdicts, f"verdict missing; stdout={proc.stdout!r}"
    v = verdicts[-1]
    assert v.get("outcome") == "eject" and v.get("reason") == "rebase-conflict"
    files = v.get("conflicted_files")
    assert isinstance(files, list) and "base.txt" in files, f"verdict conflicted_files mismatch: {v!r}"


def test_rebase_conflict_verdict_includes_resume_cmd(stub_env):
    slug = "mentat-s10-verdict-resume"
    _spawn_conflicting_chunk(stub_env["repo"], slug)
    proc = _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    verdicts = _parse_verdicts(proc.stdout)
    v = verdicts[-1]
    cmd = v.get("resume_cmd")
    assert isinstance(cmd, str) and "git rebase --continue" in cmd, f"verdict resume_cmd mismatch: {v!r}"


def test_rebase_conflict_leaves_rebase_in_progress(stub_env):
    """S10/S11 prerequisite: rebase state must persist so `git rebase --continue`
    actually works for the operator."""
    slug = "mentat-s10-state-persist"
    wt = _spawn_conflicting_chunk(stub_env["repo"], slug)
    proc = _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main")
    assert proc.returncode == 1, f"eject must exit 1; stderr={proc.stderr!r}"

    rebase_path = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "--git-path", "rebase-merge"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if not os.path.isabs(rebase_path):
        rebase_path = str(wt / rebase_path)
    rebase_apply = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "--git-path", "rebase-apply"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if not os.path.isabs(rebase_apply):
        rebase_apply = str(wt / rebase_apply)
    assert os.path.isdir(rebase_path) or os.path.isdir(rebase_apply), (
        f"rebase state must persist for --continue; neither {rebase_path} nor {rebase_apply} exists"
    )


def test_non_conflict_eject_does_not_set_conflicted_files(stub_env):
    """gate-fail / not-ff ejects must NOT populate conflicted_files/resume_cmd
    (those are rebase-conflict-only per audit-schema comment line 59)."""
    slug = "mentat-s10-gatefail-clean"
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
    verdicts = _parse_verdicts(proc.stdout)
    v = verdicts[-1]
    assert v.get("reason") == "gate-fail"
    assert "conflicted_files" not in v or not v.get("conflicted_files"), (
        f"gate-fail eject must not carry conflicted_files; got {v!r}"
    )
    assert "resume_cmd" not in v or not v.get("resume_cmd"), f"gate-fail eject must not carry resume_cmd; got {v!r}"
