"""G1-S6: mentat-fan-out — extract fan-out from mentat-orchestrate (ADR-0011).

Spec (~/.agents/plans/mentat-architecture-revamp-g1-audit-substrate.md):
  - File: .agents/bin/mentat-fan-out (new).
  - Stdin: newline-delim plan paths.
  - Stdout: newline-delim chunk slugs (impl-OK only).
  - Emit chunk.spawn audit row per worktree spawn.
  - Spawn one worktree + devcontainer per path.

ADR-0011 (orchestrate decomposition):
  - Empty stdin -> zero chunks, exit 0 (legitimate no-op).
  - Exit 0 = every chunk impl-OK; exit 1 = partial (>=1 impl-fail);
    exit >=2 = tool-level error (bad argv, missing config).
  - Impl-fail chunks emit land.complete reason=implement-fail (not in stdout).

Verify (plan): feed two plan paths -> two worktrees, two slugs printed,
two chunk.spawn rows in audit log.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FAN_OUT = ROOT / ".agents" / "bin" / "mentat-fan-out"
HARNESS_DIR = ROOT / ".agents" / "bin" / "lib" / "harness"


# -- Source-level assertions --------------------------------------------------


def test_fan_out_exists_and_executable():
    assert FAN_OUT.exists(), f"{FAN_OUT} missing — S6 extraction not landed"
    assert os.access(FAN_OUT, os.X_OK), f"{FAN_OUT} not executable"


def test_fan_out_references_adr_0011():
    src = FAN_OUT.read_text()
    assert "ADR-0011" in src or "0011" in src, "mentat-fan-out must cite ADR-0011 (orchestrate decomposition)"


def test_fan_out_reads_stdin_newline_delim():
    """ADR-0011: stdin = newline-delim plan paths."""
    src = FAN_OUT.read_text()
    # Expect a `while read line` style loop ingesting stdin into a PLANS array.
    assert "while IFS= read -r" in src and "PLANS" in src, "fan-out must read plans from stdin into PLANS array"


def test_fan_out_emits_chunk_spawn():
    src = FAN_OUT.read_text()
    assert "chunk.spawn" in src, "fan-out must emit chunk.spawn audit verb"


def test_fan_out_emits_impl_fail_land_complete():
    """Impl-fail chunks: per ADR-0011 reason enum, emit land.complete reason=implement-fail."""
    src = FAN_OUT.read_text()
    assert "implement-fail" in src, "fan-out must emit land.complete reason=implement-fail for failed implements"
    assert "land.complete" in src, "fan-out must emit land.complete on impl-fail"


def test_fan_out_respects_parallel_cap():
    src = FAN_OUT.read_text()
    assert "PARALLEL_CAP" in src, "fan-out must enforce agents.max_concurrent cap"


def test_fan_out_prints_slugs_to_stdout():
    """ADR-0011: stdout = newline-delim slugs of impl-OK chunks."""
    src = FAN_OUT.read_text()
    # Heuristic: a `printf '%s\n' "${SLUGS[$i]}"` (or similar) outside the audit emit.
    assert "printf '%s\\n'" in src or "echo " in src, "fan-out must print slugs to stdout"


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


@pytest.fixture
def stub_env(tmp_path):
    """Isolated git repo + stub bins + stub harness for fan-out subprocess runs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)

    # Plan files (frontmatter ignored by fan-out; only file existence matters).
    for n in ("plan-a.md", "plan-b.md", "plan-bad.md"):
        (repo / n).write_text(f"# {n}\n")

    # Stub HOME with mentat-container-up no-op (fan-out hardcodes ~/.agents/bin/).
    fake_home = tmp_path / "home"
    fake_bin = fake_home / ".agents" / "bin"
    fake_bin.mkdir(parents=True)
    cu = fake_bin / "mentat-container-up"
    cu.write_text("#!/usr/bin/env bash\necho 'stub container-up'\n")
    cu.chmod(0o755)

    stub_file = _install_stub_harness(HARNESS_DIR)

    # Minimal .mentat.jsonc selecting harness=stub.
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


def _run_fan_out(stub_env, *, stdin: str, stub_exit: int = 0, extra_env=None) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HOME": str(stub_env["home"]),
        "MENTAT_CONFIG_PATH": str(stub_env["config"]),
        "MENTAT_LOG_PATH": str(stub_env["log_root"]),
        "MENTAT_SESSION": stub_env["session"],
        "MENTAT_REPO": "repo",
        "STUB_EXIT": str(stub_exit),
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(FAN_OUT)],
        cwd=str(stub_env["repo"]),
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


def test_empty_stdin_no_op_exit_zero(stub_env):
    """ADR-0011: empty stdin -> zero chunks -> exit 0, no stdout slugs."""
    proc = _run_fan_out(stub_env, stdin="")
    assert proc.returncode == 0, f"empty stdin must exit 0; stderr={proc.stderr!r}"
    assert proc.stdout.strip() == "", f"empty stdin must print no slugs; got {proc.stdout!r}"


def test_two_plans_spawn_two_slugs(stub_env):
    """Two impl-OK plans -> two slugs on stdout, two chunk.spawn rows."""
    proc = _run_fan_out(stub_env, stdin="plan-a.md\nplan-b.md\n", stub_exit=0)
    assert proc.returncode == 0, f"all-OK must exit 0; stderr={proc.stderr!r}"
    slugs = [s for s in proc.stdout.strip().splitlines() if s]
    assert len(slugs) == 2, f"expected 2 slugs on stdout, got {slugs!r}"

    rows = _read_audit_rows(stub_env)
    spawn_rows = [r for r in rows if r.get("event") == "chunk.spawn"]
    assert len(spawn_rows) == 2, f"expected 2 chunk.spawn rows; got {[r.get('event') for r in rows]!r}"
    for r in spawn_rows:
        assert "slug" in r["payload"] and "plan" in r["payload"], (
            f"chunk.spawn payload missing required slug/plan: {r!r}"
        )


def test_impl_fail_emits_land_complete_and_skips_slug(stub_env):
    """Failed implement -> land.complete reason=implement-fail, slug NOT in stdout, exit 1."""
    proc = _run_fan_out(stub_env, stdin="plan-a.md\n", stub_exit=7)
    assert proc.returncode == 1, f"partial-fail must exit 1; got rc={proc.returncode} stderr={proc.stderr!r}"
    assert proc.stdout.strip() == "", f"impl-fail slug must NOT appear in stdout; got {proc.stdout!r}"

    rows = _read_audit_rows(stub_env)
    landed = [r for r in rows if r.get("event") == "land.complete"]
    assert landed, f"expected land.complete row; events={[r.get('event') for r in rows]}"
    p = landed[-1]["payload"]
    assert p.get("outcome") == "eject" and p.get("reason") == "implement-fail", (
        f"impl-fail land.complete must be eject/implement-fail; got {p!r}"
    )


def test_bad_flag_exits_ge_two(stub_env):
    """Tool-level error (unknown flag) -> exit >=2 per ADR-0011."""
    env = {
        **os.environ,
        "HOME": str(stub_env["home"]),
        "MENTAT_CONFIG_PATH": str(stub_env["config"]),
        "MENTAT_LOG_PATH": str(stub_env["log_root"]),
    }
    proc = subprocess.run(
        ["bash", str(FAN_OUT), "--bogus-flag"],
        cwd=str(stub_env["repo"]),
        text=True,
        capture_output=True,
        timeout=10,
        env=env,
    )
    assert proc.returncode >= 2, f"bad flag must exit >=2; got rc={proc.returncode}, stderr={proc.stderr!r}"


def test_chunk_spawn_payload_satisfies_schema(stub_env):
    """chunk.spawn audit row required fields: slug, plan (audit-schema.jsonc)."""
    proc = _run_fan_out(stub_env, stdin="plan-a.md\n", stub_exit=0)
    assert proc.returncode == 0
    rows = _read_audit_rows(stub_env)
    spawn = [r for r in rows if r.get("event") == "chunk.spawn"]
    assert spawn, "no chunk.spawn row emitted"
    p = spawn[-1]["payload"]
    assert isinstance(p.get("slug"), str) and p["slug"].startswith("mentat-")
    assert p.get("plan") == "plan-a.md"
