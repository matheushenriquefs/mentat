"""G1-S8: mentat-final-review — extract end-of-queue ADR-0003 review pass.

Spec (~/.agents/plans/mentat-architecture-revamp-g1-audit-substrate.md):
  - File: .agents/bin/mentat-final-review (new).
  - Extract orchestrate:186-216 region.
  - Input: holding tip SHA (plus base SHA per ADR-0011 explicit two-arg).
  - Run ADR-0003 reviewers, emit `review.final` audit row with score breakdown.
  - Verify: invoke against a known holding tip -> review row written,
    no raw subprocess output in `.jsonl`.

ADR-0011 (orchestrate decomposition):
  - `mentat-final-review <base-sha> <tip-sha>` — positional argv (no stdin).
  - Stdout: single JSONL verdict line:
    {reviewer, score, veto, findings, base, tip, stdout?, stderr_path?}
  - Stdout (subprocess) trimmed via `tail -c 4000` into audit `stdout` field.
  - Subprocess stderr -> `$LOGDIR/.stderr/mentat-final-review.stderr` sidecar.
  - Exit: 0 = tool ran (review is advisory, never rolls back the landed ref);
    >=2 = tool-level failure (bad argv, missing config).
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FINAL_REVIEW = ROOT / ".agents" / "bin" / "mentat-final-review"
HARNESS_DIR = ROOT / ".agents" / "bin" / "lib" / "harness"


# -- Source-level assertions --------------------------------------------------


def test_final_review_exists_and_executable():
    assert FINAL_REVIEW.exists(), f"{FINAL_REVIEW} missing — S8 extraction not landed"
    assert os.access(FINAL_REVIEW, os.X_OK), f"{FINAL_REVIEW} not executable"


def test_final_review_references_adr_0011():
    src = FINAL_REVIEW.read_text()
    assert "ADR-0011" in src or "0011" in src, "mentat-final-review must cite ADR-0011"


def test_final_review_emits_review_final():
    src = FINAL_REVIEW.read_text()
    assert "review.final" in src, "mentat-final-review must emit review.final audit verb"


def test_final_review_uses_stderr_sidecar():
    """ADR-0011 + ADR-0009: subprocess stderr goes to sidecar, not .jsonl."""
    src = FINAL_REVIEW.read_text()
    assert ".stderr" in src, "must route subprocess stderr to sidecar dir"
    assert "mentat-final-review.stderr" in src, "sidecar path must be mentat-final-review.stderr"


def test_final_review_trims_stdout_field():
    """ADR-0011: captured stdout trimmed via tail -c 4000 before audit emit."""
    src = FINAL_REVIEW.read_text()
    assert "tail -c 4000" in src, "captured stdout must be trimmed to 4000 bytes"


def test_final_review_takes_two_positional_args():
    """ADR-0011: `mentat-final-review <base-sha> <tip-sha>` — explicit, no infer."""
    src = FINAL_REVIEW.read_text()
    # Heuristic: positional capture into BASE / TIP (or similar names).
    assert "BASE=" in src or 'BASE="$1"' in src, "must capture <base-sha> positional"
    assert "TIP=" in src or 'TIP="$2"' in src or "HOLDING" in src, "must capture <tip-sha> positional"


def test_final_review_emits_jsonl_verdict_stdout():
    """ADR-0011: stdout = single JSONL verdict line."""
    src = FINAL_REVIEW.read_text()
    assert "jq -cn" in src, "verdict must be emitted via jq -cn (compact JSONL)"


def test_final_review_does_not_read_stdin():
    """ADR-0011: nothing on stdin (positional args carry both refs)."""
    src = FINAL_REVIEW.read_text()
    # Heuristic: no `while IFS= read -r` ingesting stdin (compare S6/S7 which do).
    assert "while IFS= read -r _line" not in src, "must not consume stdin"


# -- Behavior smoke: subprocess invocation with stubbed env -------------------


def _install_stub_harness(harness_dir: Path) -> Path:
    """Drop a `stub` harness under .agents/bin/lib/harness/ for one test.
    Removed in fixture teardown to keep the 8-harness invariant
    (test_p2_rename::test_harness_subdir_has_8_files).
    """
    stub = harness_dir / "stub.sh"
    stub.write_text(
        textwrap.dedent("""\
        #!/bin/bash
        harness_stub_cmd() {
          printf '%s\\0' bash -c "echo 'reviewer-out:line1'; echo 'reviewer-out:line2'; \
echo 'noisy reviewer stderr blob' >&2; exit ${STUB_EXIT:-0}"
        }
        harness_stub_output_format() { printf 'stub\\n'; }
        harness_stub_normalize() {
          jq -c --arg agent stub --arg sess "${MENTAT_SESSION:-unknown}" \\
            '{ts:(now|todate), agent:$agent, session:$sess, event:(.type // "unknown"), payload:(del(.type))}'
        }
    """)
    )
    return stub


def _install_container_up_stub(fake_bin: Path) -> None:
    """Stub `mentat-container-up` so tests don't depend on docker."""
    cu = fake_bin / "mentat-container-up"
    cu.write_text("#!/usr/bin/env bash\necho 'stub container-up'\n")
    cu.chmod(0o755)


@pytest.fixture
def stub_env(tmp_path):
    """Isolated git repo + stub HOME + stub harness for final-review subprocess runs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "base.txt").write_text("base\n")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    (repo / "tip.txt").write_text("tip\n")
    subprocess.run(["git", "add", "tip.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "tip"], cwd=repo, check=True)
    tip_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    fake_home = tmp_path / "home"
    fake_bin = fake_home / ".agents" / "bin"
    fake_bin.mkdir(parents=True)
    _install_container_up_stub(fake_bin)

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
    session = "1700000000-88888"
    try:
        yield {
            "tmp": tmp_path,
            "repo": repo,
            "home": fake_home,
            "config": cfg,
            "log_root": log_root,
            "session": session,
            "base": base_sha,
            "tip": tip_sha,
        }
    finally:
        stub_file.unlink(missing_ok=True)


def _run_final_review(stub_env, *args, stub_exit: int = 0, extra_env=None) -> subprocess.CompletedProcess:
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
        ["bash", str(FINAL_REVIEW), *args],
        cwd=str(stub_env["repo"]),
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


def test_bad_argv_missing_tip_exits_ge_two(stub_env):
    """ADR-0011: tool-level error -> exit >=2."""
    proc = _run_final_review(stub_env, stub_env["base"])  # only base, no tip
    assert proc.returncode >= 2, f"missing <tip-sha> must exit >=2; got rc={proc.returncode}, stderr={proc.stderr!r}"


def test_bad_flag_exits_ge_two(stub_env):
    proc = _run_final_review(stub_env, "--bogus-flag", stub_env["base"], stub_env["tip"])
    assert proc.returncode >= 2, f"bad flag must exit >=2; got rc={proc.returncode}"


def test_clean_review_emits_success_verdict(stub_env):
    """All-green reviewer subprocess -> verdict on stdout, review.final emitted."""
    proc = _run_final_review(stub_env, stub_env["base"], stub_env["tip"], stub_exit=0)
    assert proc.returncode == 0, f"clean review must exit 0; stderr={proc.stderr!r}"

    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected exactly 1 verdict line on stdout; got {lines!r}"
    verdict = json.loads(lines[0])
    for k in ("reviewer", "score", "veto", "findings", "base", "tip"):
        assert k in verdict, f"verdict missing required key {k!r}: {verdict!r}"
    assert verdict["base"] == stub_env["base"]
    assert verdict["tip"] == stub_env["tip"]
    assert verdict["veto"] is False, f"clean review must have veto=false; got {verdict!r}"

    rows = _read_audit_rows(stub_env)
    final_rows = [r for r in rows if r.get("event") == "review.final"]
    assert len(final_rows) == 1, f"expected 1 review.final row; events={[r.get('event') for r in rows]}"
    p = final_rows[0]["payload"]
    for k in ("reviewer", "score", "veto", "findings"):
        assert k in p, f"review.final payload missing required key {k!r}: {p!r}"


def test_flagged_review_emits_veto_true(stub_env):
    """Reviewer subprocess exits non-zero -> veto=true on verdict + audit row."""
    proc = _run_final_review(stub_env, stub_env["base"], stub_env["tip"], stub_exit=7)
    # Tool itself ran to completion; review verdict is advisory -> exit 0 (or 1).
    # ADR-0011 says review never rolls back the landed ref -> tool exit 0.
    assert proc.returncode in (0, 1), f"flagged review tool exit must be 0/1 (advisory); got {proc.returncode}"

    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    assert lines, "no verdict on stdout"
    verdict = json.loads(lines[-1])
    assert verdict["veto"] is True, f"flagged review must have veto=true; got {verdict!r}"


def test_subprocess_stderr_lands_in_sidecar_not_jsonl(stub_env):
    """ADR-0011 + ADR-0009: subprocess stderr must NOT appear in .jsonl rows."""
    proc = _run_final_review(stub_env, stub_env["base"], stub_env["tip"], stub_exit=0)
    assert proc.returncode == 0

    sidecar = _logdir(stub_env) / ".stderr" / "mentat-final-review.stderr"
    assert sidecar.exists(), f"sidecar not written at {sidecar}"
    assert "noisy reviewer stderr blob" in sidecar.read_text(), (
        f"sidecar missing reviewer stderr; content={sidecar.read_text()!r}"
    )

    # Stderr blob must NOT appear in any .jsonl row.
    logdir = _logdir(stub_env)
    for jl in logdir.glob("*.jsonl"):
        body = jl.read_text()
        assert "noisy reviewer stderr blob" not in body, f"raw subprocess stderr leaked into {jl}: {body!r}"


def test_stdout_field_captured_in_audit(stub_env):
    """Reviewer stdout is captured (tail -c 4000) into the audit `stdout` field."""
    proc = _run_final_review(stub_env, stub_env["base"], stub_env["tip"], stub_exit=0)
    assert proc.returncode == 0
    rows = _read_audit_rows(stub_env)
    final = [r for r in rows if r.get("event") == "review.final"]
    assert final, "no review.final row"
    p = final[-1]["payload"]
    assert "stdout" in p, f"audit row missing stdout field: {p!r}"
    assert "reviewer-out:line1" in p["stdout"], f"captured stdout missing reviewer line: {p['stdout']!r}"


def test_review_final_schema_payload_validation(stub_env):
    """Sanity: required keys per audit-schema.jsonc::review.final are present."""
    proc = _run_final_review(stub_env, stub_env["base"], stub_env["tip"], stub_exit=0)
    assert proc.returncode == 0
    rows = _read_audit_rows(stub_env)
    final = [r for r in rows if r.get("event") == "review.final"]
    assert final
    p = final[-1]["payload"]
    # Schema required: reviewer, score, veto, findings
    assert isinstance(p["reviewer"], str)
    assert isinstance(p["score"], (int, float))
    assert isinstance(p["veto"], bool)
    assert isinstance(p["findings"], list)
