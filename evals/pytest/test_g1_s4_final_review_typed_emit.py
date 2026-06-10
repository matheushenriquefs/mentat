"""G1-S4: mentat-orchestrate final_review routes through typed audit emit.

Spec (~/.agents/plans/mentat-architecture-revamp-g1-audit-substrate.md):
  - Replace raw `>> $jsonl` appends with `mentat_audit ... review.final '<json>'`.
  - Subprocess stdout -> captured to variable -> passed as `stdout` field.
  - Subprocess stderr -> tee'd to sidecar `.stderr` file -> path in `stderr_path`.

Verify (plan): simulate failing final_review -> no raw text in `.jsonl`,
stderr appears in sidecar, audit row has `review.final` event with captured
stdout field.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")


import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ORCH = ROOT / ".agents" / "bin" / "mentat-orchestrate"
AUDIT_SH = ROOT / ".agents" / "bin" / "lib" / "audit.sh"


def _final_review_block(src: str) -> str:
    """Extract the final_review() function definition (decl + body + closing })."""
    m = re.search(r"^final_review\(\)\s*\{.*?^\}", src, re.DOTALL | re.MULTILINE)
    assert m, "final_review() function not found in mentat-orchestrate"
    return m.group(0)


# -- Source assertions ---------------------------------------------------------


def test_final_review_no_raw_jsonl_append():
    """S4: final_review must not append raw subprocess output to .jsonl ($logf)."""
    body = _final_review_block(ORCH.read_text())
    matches = re.findall(r'>>\s*"?\$logf"?', body)
    assert matches == [], (
        f"final_review still appends raw output to $logf ({len(matches)} hits); "
        f"S4 requires routing via mentat_audit + sidecar"
    )


def test_final_review_emit_passes_stdout_field():
    """S4: review.final emit must include `stdout` jq arg (captured subprocess stdout)."""
    body = _final_review_block(ORCH.read_text())
    assert "--arg stdout" in body, "review.final emit missing --arg stdout"


def test_final_review_emit_passes_stderr_path_field():
    """S4: review.final emit must include `stderr_path` jq arg (sidecar path)."""
    body = _final_review_block(ORCH.read_text())
    assert "--arg stderr_path" in body, "review.final emit missing --arg stderr_path"


# -- Behavior smoke: stub-driven final_review run -----------------------------

_DRIVER_TEMPLATE = r"""#!/usr/bin/env bash
set -euo pipefail
export LOGDIR=__LOGDIR__
export ROOT=__ROOT__
export HOLDING=main
export HARNESS=stub
export MENTAT_LOG_PATH=__LOGROOT__
export MENTAT_REPO=__REPO__
export MENTAT_SESSION=__SESSION__
export HOME=__HOME__

log() { echo "log: $*"; }
die() { echo "die: $*" >&2; exit 2; }

build_cmd() {
  local _ec=__EXIT__
  printf '%s\0' bash -c "printf 'agent stdout line one\nagent stdout line two\n'; printf 'agent stderr DETAIL\n' >&2; exit $_ec"
}

. __AUDIT_SH__

__FUNC__

final_review HEAD~1
"""


@pytest.fixture
def stub_env(tmp_path):
    repo = "test-repo"
    session = "1700000000-99999"
    log_root = tmp_path / "logs"
    logdir = log_root / repo / session
    logdir.mkdir(parents=True)
    fake_home = tmp_path / "fake-home"
    fake_bin = fake_home / ".agents" / "bin"
    fake_bin.mkdir(parents=True)
    stub = fake_bin / "mentat-container-up"
    stub.write_text("#!/usr/bin/env bash\necho 'container-up: ok'\necho 'container-up: bring-up noise' >&2\n")
    stub.chmod(0o755)
    return {
        "tmp": tmp_path,
        "logdir": logdir,
        "log_root": log_root,
        "repo": repo,
        "session": session,
        "home": fake_home,
    }


def _driver_script(stub_env, *, agent_exits: int) -> str:
    func = _final_review_block(ORCH.read_text())
    return (
        _DRIVER_TEMPLATE.replace("__LOGDIR__", str(stub_env["logdir"]))
        .replace("__LOGROOT__", str(stub_env["log_root"]))
        .replace("__REPO__", stub_env["repo"])
        .replace("__SESSION__", stub_env["session"])
        .replace("__HOME__", str(stub_env["home"]))
        .replace("__ROOT__", str(stub_env["tmp"]))
        .replace("__EXIT__", str(agent_exits))
        .replace("__AUDIT_SH__", str(AUDIT_SH))
        .replace("__FUNC__", func)
    )


def _run_driver(stub_env, *, agent_exits: int) -> subprocess.CompletedProcess:
    driver = stub_env["tmp"] / "driver.sh"
    driver.write_text(_driver_script(stub_env, agent_exits=agent_exits))
    driver.chmod(0o755)
    env = {**os.environ, "PATH": os.environ.get("PATH", "")}
    return subprocess.run(
        ["bash", str(driver)],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _read_rows(stub_env) -> list[dict]:
    rows: list[dict] = []
    for jl in stub_env["logdir"].glob("*.jsonl"):
        for lineno, line in enumerate(jl.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                pytest.fail(f"{jl}:{lineno} not valid JSON: {e!r} -- line={line!r}")
    return rows


def _sidecar(stub_env) -> Path:
    return stub_env["logdir"] / ".stderr" / "mentat-orchestrate-final-review.stderr"


@pytest.mark.parametrize("agent_exits", [0, 1])
def test_jsonl_lines_all_valid_json(stub_env, agent_exits):
    proc = _run_driver(stub_env, agent_exits=agent_exits)
    assert proc.returncode == 0, f"driver failed: stderr={proc.stderr!r}"
    rows = _read_rows(stub_env)
    assert any(r.get("event") == "review.final" for r in rows), (
        f"expected review.final row; got events={[r.get('event') for r in rows]}"
    )


def test_stderr_routed_to_sidecar(stub_env):
    proc = _run_driver(stub_env, agent_exits=1)
    assert proc.returncode == 0, proc.stderr
    sidecar = _sidecar(stub_env)
    assert sidecar.exists(), f"sidecar missing at {sidecar}"
    body = sidecar.read_text()
    assert "agent stderr DETAIL" in body, f"sidecar missing agent stderr: {body!r}"


def test_audit_row_has_stdout_and_stderr_path(stub_env):
    proc = _run_driver(stub_env, agent_exits=0)
    assert proc.returncode == 0, proc.stderr
    rows = _read_rows(stub_env)
    final = [r for r in rows if r.get("event") == "review.final"]
    assert final, f"no review.final row; rows={rows!r}"
    payload = final[-1]["payload"]
    assert "stdout" in payload, f"payload missing stdout: {payload!r}"
    assert "stderr_path" in payload, f"payload missing stderr_path: {payload!r}"
    assert "agent stdout line one" in payload["stdout"], f"captured stdout not preserved: {payload['stdout']!r}"
    assert payload["stderr_path"].endswith(".stderr"), payload["stderr_path"]


def test_audit_row_veto_reflects_agent_exit(stub_env):
    """S4 side-effect: flagged verdict when reviewer subprocess exits nonzero."""
    proc = _run_driver(stub_env, agent_exits=1)
    assert proc.returncode == 0, proc.stderr
    final = [r for r in _read_rows(stub_env) if r.get("event") == "review.final"]
    assert final and final[-1]["payload"]["veto"] is True, f"flagged run must set veto=true; got {final!r}"
