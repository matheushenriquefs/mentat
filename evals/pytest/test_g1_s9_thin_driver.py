"""G1-S9: mentat-orchestrate rewritten as thin driver (ADR-0011).

Spec (~/.agents/plans/mentat-architecture-revamp-g1-audit-substrate.md):
  - File: .agents/bin/mentat-orchestrate (rewritten).
  - Parse args, dispatch to S6/S7/S8 in sequence, propagate exit codes.
  - Body ≤60 LOC of `case` + pipe.
  - Same external behavior (same chunk count, same audit envelope, same
    eject layout) as pre-S9.

ADR-0011 dispatcher contract:
  - `pipe the slice paths into fan-out, pipe the chunk slugs into land-queue,
     pluck the landed tip from the last successful verdict, hand it to
     final-review.`
  - On exit 1 (partial), the dispatcher skips final-review per ADR-0004.
  - Driver does not name a project tool. No concrete responsibility.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATE = ROOT / ".agents" / "bin" / "mentat-orchestrate"
FAN_OUT = ROOT / ".agents" / "bin" / "mentat-fan-out"
LAND_QUEUE = ROOT / ".agents" / "bin" / "mentat-land-queue"
FINAL_REVIEW = ROOT / ".agents" / "bin" / "mentat-final-review"
HARNESS_DIR = ROOT / ".agents" / "bin" / "lib" / "harness"


# -- Source-level assertions --------------------------------------------------


def test_orchestrate_exists_and_executable():
    assert ORCHESTRATE.exists(), f"{ORCHESTRATE} missing"
    assert os.access(ORCHESTRATE, os.X_OK), f"{ORCHESTRATE} not executable"


def test_orchestrate_references_adr_0011():
    src = ORCHESTRATE.read_text()
    assert "0011" in src, "mentat-orchestrate must cite ADR-0011 (orchestrate decomposition)"


def test_orchestrate_body_under_60_loc():
    """ADR-0011: dispatcher ≤60 LOC of case + pipe. Count non-blank, non-comment lines."""
    src = ORCHESTRATE.read_text()
    code_lines = [ln for ln in src.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert len(code_lines) <= 60, (
        f"thin driver target ≤60 code lines; got {len(code_lines)} (per ADR-0011 + plan S9 verify)"
    )


def test_orchestrate_dispatches_to_fan_out():
    src = ORCHESTRATE.read_text()
    assert "mentat-fan-out" in src, "thin driver must dispatch to mentat-fan-out"


def test_orchestrate_dispatches_to_land_queue():
    src = ORCHESTRATE.read_text()
    assert "mentat-land-queue" in src, "thin driver must dispatch to mentat-land-queue"


def test_orchestrate_dispatches_to_final_review():
    src = ORCHESTRATE.read_text()
    assert "mentat-final-review" in src, "thin driver must dispatch to mentat-final-review"


def test_orchestrate_pipes_fan_out_into_land_queue():
    """ADR-0011: 'pipe the slice paths into fan-out, pipe the chunk slugs into land-queue'."""
    src = ORCHESTRATE.read_text()
    # Either explicit pipe with both tools on consecutive lines, or single-line pipe.
    pipe_pattern = re.compile(r"mentat-fan-out[^\n]*\n?\s*\|\s*[^\n]*mentat-land-queue", re.DOTALL)
    assert pipe_pattern.search(src), "thin driver must pipe fan-out output into land-queue stdin"


def test_orchestrate_drops_inline_run_chunk():
    """Pre-S9 orchestrate defined run_chunk() inline (worktree spawn + agent dispatch).
    Thin driver delegates this entirely to mentat-fan-out."""
    src = ORCHESTRATE.read_text()
    assert "run_chunk()" not in src, (
        "thin driver must not define run_chunk() — that responsibility belongs to mentat-fan-out"
    )


def test_orchestrate_drops_inline_land_chunk():
    """Pre-S9 orchestrate defined land_chunk() inline (rebase + re-gate + ff merge).
    Thin driver delegates entirely to mentat-land-queue."""
    src = ORCHESTRATE.read_text()
    assert "land_chunk()" not in src, (
        "thin driver must not define land_chunk() — that responsibility belongs to mentat-land-queue"
    )


def test_orchestrate_drops_inline_final_review_fn():
    """Pre-S9 orchestrate defined final_review() inline. Thin driver delegates."""
    src = ORCHESTRATE.read_text()
    assert "final_review()" not in src, (
        "thin driver must not define final_review() — that responsibility belongs to mentat-final-review"
    )


def test_orchestrate_drops_inline_review_final_emit():
    """Pre-S9 orchestrate emitted review.final audit row from within final_review().
    Thin driver delegates emission entirely to mentat-final-review (one emit-site)."""
    src = ORCHESTRATE.read_text()
    assert "review.final" not in src, "thin driver must not emit review.final — mentat-final-review owns that audit row"


def test_orchestrate_captures_pipestatus():
    """Driver must inspect per-stage rc to decide all-green vs partial vs tool-fail.
    Either PIPESTATUS or temp files; PIPESTATUS is the bash idiom."""
    src = ORCHESTRATE.read_text()
    assert "PIPESTATUS" in src, "thin driver must capture PIPESTATUS to detect partial vs all-green"


def test_orchestrate_skips_final_review_on_partial():
    """ADR-0011: 'On exit 1 (partial), the dispatcher skips final-review.'
    Verify the source guards final-review behind an all-green branch."""
    src = ORCHESTRATE.read_text()
    # Heuristic: final-review must appear inside an `if`/`&&` branch that gates on
    # a zero exit code condition, not as an unconditional statement.
    lines = src.splitlines()
    fr_lines = [i for i, ln in enumerate(lines) if "mentat-final-review" in ln and not ln.lstrip().startswith("#")]
    assert fr_lines, "expected at least one final-review invocation"
    # The lines immediately above must contain an `if` or `&&` gate referencing rc/0.
    found_gate = False
    for i in fr_lines:
        window = "\n".join(lines[max(0, i - 6) : i + 1])
        if re.search(r"\bif\b[^\n]*(-eq\s+0|RC|PIPESTATUS|all-green)", window) or "&& " in window:
            found_gate = True
            break
    assert found_gate, "final-review must be gated behind an all-green check (skip on partial)"


def test_orchestrate_uses_holding_argv_positional():
    src = ORCHESTRATE.read_text()
    assert "HOLDING=" in src, "driver must capture HOLDING from positional argv"


# -- Behavior smoke: subprocess invocation with stubbed env -------------------


def _install_stub_harness(harness_dir: Path) -> Path:
    """Drop a stub harness under .agents/bin/lib/harness/. Removed in teardown
    to preserve the 8-harness invariant (test_p2_rename::test_harness_subdir_has_8_files)."""
    stub = harness_dir / "stub.sh"
    stub.write_text(
        textwrap.dedent("""\
        #!/bin/bash
        harness_stub_cmd() { printf '%s\\0' bash -c "echo stub-ok; exit ${STUB_EXIT:-0}"; }
        harness_stub_output_format() { printf 'stub\\n'; }
        harness_stub_normalize() {
          jq -c --arg agent stub --arg sess "${MENTAT_SESSION:-unknown}" \\
            '{ts:(now|todate), agent:$agent, session:$sess, event:(.type // "unknown"), payload:(del(.type))}'
        }
    """)
    )
    return stub


@pytest.fixture
def stub_env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)

    fake_home = tmp_path / "home"
    fake_bin = fake_home / ".agents" / "bin"
    fake_bin.mkdir(parents=True)
    cu = fake_bin / "mentat-container-up"
    cu.write_text("#!/usr/bin/env bash\necho 'stub container-up' >&2\n")
    cu.chmod(0o755)

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


def _write_plan(repo: Path, name: str, *, klass: str = "AFK", blocked_by: list[str] | None = None) -> Path:
    plan = repo / name
    deps = blocked_by or []
    fm_id = name[:-3] if name.endswith(".md") else name
    body_lines = [
        "---",
        f"id: {fm_id}",
        "status: planned",
        f"class: {klass}",
        f"blocked_by: {json.dumps(deps)}",
        "---",
        f"# {name}",
        "",
    ]
    plan.write_text("\n".join(body_lines))
    return plan


def _run_orchestrate(stub_env, *argv: str, input: str | None = None) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HOME": str(stub_env["home"]),
        "MENTAT_CONFIG_PATH": str(stub_env["config"]),
        "MENTAT_LOG_PATH": str(stub_env["log_root"]),
        "MENTAT_SESSION": stub_env["session"],
        "MENTAT_REPO": "repo",
    }
    return subprocess.run(
        ["bash", str(ORCHESTRATE), *argv],
        cwd=str(stub_env["repo"]),
        text=True,
        capture_output=True,
        timeout=30,
        input=input or "",
        env=env,
    )


def test_bad_flag_exits_ge_two(stub_env):
    """Tool-level error (unknown flag) -> exit >=2."""
    proc = _run_orchestrate(stub_env, "--bogus-flag", "main")
    assert proc.returncode >= 2, f"bad flag must exit >=2; got rc={proc.returncode}, stderr={proc.stderr!r}"


def test_missing_holding_exits_ge_two(stub_env):
    """HOLDING required positional. Absent -> tool-level error."""
    proc = _run_orchestrate(stub_env)  # no argv at all
    assert proc.returncode >= 2, f"missing argv must exit >=2; got rc={proc.returncode} stderr={proc.stderr!r}"


def test_missing_plan_exits_ge_two(stub_env):
    """HOLDING given but no plan paths -> tool-level error."""
    proc = _run_orchestrate(stub_env, "main")
    assert proc.returncode >= 2, f"missing plan must exit >=2; got rc={proc.returncode} stderr={proc.stderr!r}"


def test_dry_run_preserved(stub_env):
    """ADR-0011 verify: same external behavior. --dry-run path stays intact."""
    plan = _write_plan(stub_env["repo"], "plan-a.md")
    proc = _run_orchestrate(stub_env, "--dry-run", "main", str(plan))
    assert proc.returncode == 0, f"dry-run must exit 0; stderr={proc.stderr!r}"
    # No worktree spawned.
    assert not (stub_env["repo"] / ".mentat" / "worktrees").exists(), "dry-run must not spawn worktrees"


def test_rejects_hitl_plan(stub_env):
    """Plan-check (preserved from pre-S9): class != AFK rejected at driver."""
    plan = _write_plan(stub_env["repo"], "plan-hitl.md", klass="HITL")
    proc = _run_orchestrate(stub_env, "main", str(plan))
    assert proc.returncode >= 2, f"HITL plan must be rejected; got rc={proc.returncode} stderr={proc.stderr!r}"
    assert "AFK" in proc.stderr or "class" in proc.stderr.lower(), (
        f"reject message must cite class; stderr={proc.stderr!r}"
    )


def test_rejects_missing_blocked_by_dep(stub_env):
    """Plan-check: blocked_by referring to a missing dep file rejected at driver."""
    plan = _write_plan(stub_env["repo"], "plan-needs-dep.md", blocked_by=["missing-dep"])
    proc = _run_orchestrate(stub_env, "main", str(plan))
    assert proc.returncode >= 2, f"missing dep must reject; got rc={proc.returncode} stderr={proc.stderr!r}"


def test_rejects_blocked_by_non_done_dep(stub_env):
    """Plan-check: blocked_by referring to a not-done dep rejected at driver."""
    _write_plan(stub_env["repo"], "dep-a.md", klass="AFK")  # status: planned (default)
    plan = _write_plan(stub_env["repo"], "plan-b.md", blocked_by=["dep-a"])
    proc = _run_orchestrate(stub_env, "main", str(plan))
    assert proc.returncode >= 2, f"non-done dep must reject; got rc={proc.returncode} stderr={proc.stderr!r}"
