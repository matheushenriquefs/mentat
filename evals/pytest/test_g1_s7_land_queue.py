"""G1-S7: mentat-land-queue — extract land-queue from mentat-orchestrate (ADR-0011).

Spec (~/.agents/plans/mentat-architecture-revamp-g1-audit-substrate.md):
  - File: .agents/bin/mentat-land-queue (new).
  - Stdin: newline-delim chunk slugs.
  - Argv: positional <holding-branch>.
  - Stdout: JSONL verdict per chunk:
      {slug, outcome, tip, reason?, conflicted_files?, resume_cmd?, findings?}
      outcome ∈ {"success", "eject"}
      reason  ∈ {"rebase-conflict", "gate-fail", "not-ff", "implement-fail"}
  - Per chunk: rebase onto holding tip → re-gate (cavecrew-builder) →
    merge --ff-only or eject (worktree left intact).
  - Emit land.complete audit row per chunk.

ADR-0011 exit-code contract (hybrid):
  - 0 = tool ran AND every chunk landed.
  - 1 = partial (>=1 eject).
  - >=2 = tool-level failure (bad argv, missing config, schema-unreadable).
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


def test_land_queue_exists_and_executable():
    assert LAND_QUEUE.exists(), f"{LAND_QUEUE} missing — S7 extraction not landed"
    assert os.access(LAND_QUEUE, os.X_OK), f"{LAND_QUEUE} not executable"


def test_land_queue_references_adr_0011():
    src = LAND_QUEUE.read_text()
    assert "0011" in src, "mentat-land-queue must cite ADR-0011 (orchestrate decomposition)"


def test_land_queue_reads_stdin_newline_delim():
    """ADR-0011: stdin = newline-delim chunk slugs."""
    src = LAND_QUEUE.read_text()
    assert "while IFS= read -r" in src and "SLUGS" in src, "land-queue must read slugs from stdin into SLUGS array"


def test_land_queue_emits_land_complete():
    src = LAND_QUEUE.read_text()
    assert "land.complete" in src, "land-queue must emit land.complete audit verb"


def test_land_queue_covers_all_reason_enums():
    """ADR-0011 closed reason enum: rebase-conflict | gate-fail | not-ff | implement-fail.
    S7 owns the first three (implement-fail belongs to fan-out)."""
    src = LAND_QUEUE.read_text()
    for reason in ("rebase-conflict", "gate-fail", "not-ff"):
        assert reason in src, f"land-queue must emit reason={reason}"


def test_land_queue_uses_ff_only_merge():
    """ADR-0002 + ADR-0011: holding-branch advancement is merge --ff-only."""
    src = LAND_QUEUE.read_text()
    assert "merge --ff-only" in src or "--ff-only" in src, "land-queue must use git merge --ff-only (no merge commits)"


def test_land_queue_writes_jsonl_verdicts_to_stdout():
    """ADR-0011: stdout = JSONL verdicts (one JSON object per line)."""
    src = LAND_QUEUE.read_text()
    # Heuristic: jq -cn produces compact JSON; verdict emit goes to stdout (no >>).
    assert "jq -cn" in src, "land-queue must construct JSON verdicts via jq -cn"


def test_land_queue_spawns_re_gate():
    """ADR-0004 invariant: re-gate after rebase. Source must reference cavecrew-builder."""
    src = LAND_QUEUE.read_text()
    assert "cavecrew-builder" in src or "re-gate" in src.lower(), (
        "land-queue must re-gate via cavecrew-builder before ff-merge"
    )


def test_land_queue_takes_holding_argv_positional():
    """ADR-0011: HOLDING is a single ref — positional argv."""
    src = LAND_QUEUE.read_text()
    assert "HOLDING=" in src, "land-queue must capture HOLDING from positional argv"


# -- Behavior smoke: subprocess invocation with stubbed env -------------------


def _install_stub_harness(harness_dir: Path) -> Path:
    """Drop a `stub` harness under .agents/bin/lib/harness/ for the duration of
    one test. Removed in fixture teardown to keep the 8-harness invariant
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
    """Stub `mentat-container-run` so the inner cmd runs on host (no docker).
    Mirrors orchestrate usage: `mentat-container-run "<single shell cmd>"`.
    """
    cr = fake_bin / "mentat-container-run"
    cr.write_text('#!/usr/bin/env bash\nexec bash -c "$1"\n')
    cr.chmod(0o755)


@pytest.fixture
def stub_env(tmp_path):
    """Isolated git repo + stub bins + stub harness for land-queue subprocess runs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "base.txt").write_text("base\n")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    # Stub HOME with mentat-container-up + mentat-container-run no-ops.
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
    session = "1700000000-99999"
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


def _spawn_chunk(repo: Path, slug: str, *, file: str, content: str) -> str:
    """Create a chunk worktree branching off main with a 1-commit diverge.
    Returns the chunk tip sha."""
    wt = repo / ".mentat" / "worktrees" / slug
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "worktree", "add", "-b", slug, str(wt), "main"], cwd=repo, check=True)
    (wt / file).write_text(content)
    subprocess.run(["git", "add", file], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"chunk {slug}"], cwd=wt, check=True)
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=wt, capture_output=True, text=True, check=True
    ).stdout.strip()


def _run_land_queue(
    stub_env,
    *,
    stdin: str,
    holding: str = "main",
    stub_exit: int = 0,
    extra_argv: list[str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HOME": str(stub_env["home"]),
        "MENTAT_CONFIG_PATH": str(stub_env["config"]),
        "MENTAT_LOG_PATH": str(stub_env["log_root"]),
        "MENTAT_SESSION": stub_env["session"],
        "MENTAT_REPO": "repo",
        "STUB_EXIT": str(stub_exit),
    }
    argv = ["bash", str(LAND_QUEUE)]
    if extra_argv:
        argv += extra_argv
    argv.append(holding)
    return subprocess.run(
        argv,
        cwd=str(cwd or stub_env["repo"]),
        input=stdin,
        text=True,
        capture_output=True,
        timeout=60,
        env=env,
    )


def _logdir(stub_env) -> Path:
    return stub_env["log_root"] / "repo" / stub_env["session"]


def _read_audit_rows(stub_env) -> list[dict]:
    logdir = _logdir(stub_env)
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
    verdicts = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            verdicts.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return verdicts


def test_empty_stdin_no_op_exit_zero(stub_env):
    """ADR-0011: empty stdin -> zero chunks -> exit 0, no stdout verdicts."""
    proc = _run_land_queue(stub_env, stdin="")
    assert proc.returncode == 0, f"empty stdin must exit 0; stderr={proc.stderr!r}"
    assert _parse_verdicts(proc.stdout) == [], f"empty stdin must print no verdicts; got {proc.stdout!r}"


def test_bad_flag_exits_ge_two(stub_env):
    """Tool-level error (unknown flag) -> exit >=2 per ADR-0011."""
    proc = subprocess.run(
        ["bash", str(LAND_QUEUE), "--bogus-flag", "main"],
        cwd=str(stub_env["repo"]),
        text=True,
        capture_output=True,
        timeout=10,
        env={
            **os.environ,
            "HOME": str(stub_env["home"]),
            "MENTAT_CONFIG_PATH": str(stub_env["config"]),
            "MENTAT_LOG_PATH": str(stub_env["log_root"]),
        },
    )
    assert proc.returncode >= 2, f"bad flag must exit >=2; got rc={proc.returncode}, stderr={proc.stderr!r}"


def test_missing_holding_exits_ge_two(stub_env):
    """ADR-0011: HOLDING is a required positional argv. Absent -> tool-level error."""
    proc = subprocess.run(
        ["bash", str(LAND_QUEUE)],
        cwd=str(stub_env["repo"]),
        text=True,
        capture_output=True,
        timeout=10,
        input="some-slug\n",
        env={
            **os.environ,
            "HOME": str(stub_env["home"]),
            "MENTAT_CONFIG_PATH": str(stub_env["config"]),
            "MENTAT_LOG_PATH": str(stub_env["log_root"]),
        },
    )
    assert proc.returncode >= 2, f"missing HOLDING must exit >=2; got rc={proc.returncode}"


def test_clean_chunk_lands_success_verdict(stub_env):
    """Clean rebase + green re-gate + ff merge -> success verdict + audit row."""
    slug = "mentat-test-clean"
    _spawn_chunk(stub_env["repo"], slug, file="feature.txt", content="hello\n")
    proc = _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main", stub_exit=0)
    assert proc.returncode == 0, f"clean land must exit 0; stderr={proc.stderr!r}"
    verdicts = _parse_verdicts(proc.stdout)
    assert len(verdicts) == 1, f"expected 1 verdict, got {verdicts!r}"
    v = verdicts[0]
    assert v["slug"] == slug
    assert v["outcome"] == "success", f"verdict outcome must be success; got {v!r}"
    assert v.get("tip"), f"verdict must include landed tip sha; got {v!r}"

    rows = _read_audit_rows(stub_env)
    landed = [r for r in rows if r.get("event") == "land.complete"]
    assert len(landed) == 1, f"expected 1 land.complete row; events={[r.get('event') for r in rows]}"
    p = landed[0]["payload"]
    assert p["slug"] == slug and p["outcome"] == "success"


def test_rebase_conflict_emits_eject_verdict(stub_env):
    """Conflicting rebase -> eject verdict with reason=rebase-conflict, exit 1, worktree intact."""
    slug = "mentat-test-conflict"
    repo = stub_env["repo"]
    # chunk modifies base.txt
    _spawn_chunk(repo, slug, file="base.txt", content="chunk-side\n")
    # main also modifies base.txt differently
    (repo / "base.txt").write_text("main-side\n")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "main divergent edit"], cwd=repo, check=True)

    proc = _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main", stub_exit=0)
    assert proc.returncode == 1, f"partial-eject must exit 1; got rc={proc.returncode} stderr={proc.stderr!r}"
    verdicts = _parse_verdicts(proc.stdout)
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v["outcome"] == "eject", f"verdict must be eject; got {v!r}"
    assert v.get("reason") == "rebase-conflict", f"reason must be rebase-conflict; got {v!r}"

    # Worktree intact (ADR-0011): ejected chunk leaves the worktree on disk.
    assert (repo / ".mentat" / "worktrees" / slug).exists(), "ejected worktree must remain"

    rows = _read_audit_rows(stub_env)
    landed = [r for r in rows if r.get("event") == "land.complete"]
    assert landed, "land.complete row required even on eject"
    p = landed[-1]["payload"]
    assert p["outcome"] == "eject" and p["reason"] == "rebase-conflict"


def test_re_gate_fail_emits_gate_fail(stub_env):
    """Harness exit nonzero on re-gate -> eject verdict reason=gate-fail."""
    slug = "mentat-test-regate"
    _spawn_chunk(stub_env["repo"], slug, file="feature.txt", content="hi\n")
    proc = _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main", stub_exit=7)
    assert proc.returncode == 1, f"gate-fail eject must exit 1; got rc={proc.returncode} stderr={proc.stderr!r}"
    verdicts = _parse_verdicts(proc.stdout)
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v["outcome"] == "eject" and v.get("reason") == "gate-fail", f"got {v!r}"


def test_not_ff_emits_eject(stub_env):
    """HOLDING not checked out at $ROOT -> eject reason=not-ff."""
    slug = "mentat-test-notff"
    repo = stub_env["repo"]
    _spawn_chunk(repo, slug, file="feature.txt", content="hi\n")
    # Switch off main onto a side branch so ff-target check fails.
    subprocess.run(["git", "checkout", "-q", "-b", "sidebar"], cwd=repo, check=True)

    proc = _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main", stub_exit=0)
    assert proc.returncode == 1, f"not-ff eject must exit 1; got rc={proc.returncode} stderr={proc.stderr!r}"
    verdicts = _parse_verdicts(proc.stdout)
    assert verdicts, "expected verdict"
    v = verdicts[0]
    assert v["outcome"] == "eject" and v.get("reason") == "not-ff", f"got {v!r}"


def test_land_complete_payload_satisfies_schema(stub_env):
    """land.complete required fields: slug, outcome, tip (audit-schema.jsonc)."""
    slug = "mentat-test-schema"
    _spawn_chunk(stub_env["repo"], slug, file="feature.txt", content="x\n")
    proc = _run_land_queue(stub_env, stdin=f"{slug}\n", holding="main", stub_exit=0)
    assert proc.returncode == 0
    rows = _read_audit_rows(stub_env)
    landed = [r for r in rows if r.get("event") == "land.complete"]
    assert landed, "land.complete row missing"
    p = landed[-1]["payload"]
    assert isinstance(p.get("slug"), str)
    assert p.get("outcome") in ("success", "eject")
    assert "tip" in p, "land.complete schema requires `tip` (always present, even on eject)"
