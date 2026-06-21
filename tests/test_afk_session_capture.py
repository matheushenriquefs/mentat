"""AFK fan-out generates session_id, creates log dir 0o700, exports
MENTAT_SESSION + MENTAT_SESSION_LOG to the child. Adapter invokes claude with
--session-id + --output-format stream-json, redirects stdout into the log
file, and populates Result.session_log.
"""

from __future__ import annotations

import importlib.util
import stat
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ORCH_SCRIPTS = _HERE.parent / ".agents/skills/mentat-orchestrate/scripts"
IMPL_SCRIPTS = _HERE.parent / ".agents/skills/mentat-implement/scripts"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_plan(tmp_path: Path, slug: str) -> Path:
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n# {slug}\n")
    return p


class _FakeProc:
    def __init__(self) -> None:
        self.returncode = 0

    def poll(self):
        return 0


def test_fan_out_creates_log_dir_and_exports_env(tmp_path, monkeypatch):
    fan_out = _load(ORCH_SCRIPTS / "fan_out.py", "fan_out")
    plan_path = _write_plan(tmp_path, "afk-plan")

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "fake-repo")

    captured_env: dict[str, str] = {}

    def fake_popen(cmd, *, env, **kw):
        captured_env.update(env)
        return _FakeProc()

    monkeypatch.setattr(fan_out.subprocess, "Popen", fake_popen)

    session_id, proc = fan_out._spawn_worktree_subprocess(plan_path)

    assert session_id.startswith("implement-afk-plan-")
    expected_dir = tmp_path / "logs" / "fake-repo" / session_id
    assert expected_dir.is_dir(), f"log dir not created: {expected_dir}"
    mode = stat.S_IMODE(expected_dir.stat().st_mode)
    assert mode == 0o700, f"log dir mode {oct(mode)} != 0o700"

    assert captured_env.get("MENTAT_SESSION") == session_id
    assert captured_env.get("MENTAT_SESSION_LOG") == str(expected_dir / "session.jsonl")


def test_claude_code_adapter_passes_session_id_and_stream_json(tmp_path, monkeypatch):
    adapter = _load(IMPL_SCRIPTS / "harness" / "claude_code.py", "claude_code_adapter")

    log_path = tmp_path / "session.jsonl"
    monkeypatch.setenv("MENTAT_SESSION", "auto-test-123")
    monkeypatch.setenv("MENTAT_SESSION_LOG", str(log_path))

    captured: dict = {}

    class _R:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(cmd, **kw):
        captured["cmd"] = list(cmd)
        captured["stdout"] = kw.get("stdout")
        if hasattr(kw.get("stdout"), "write"):
            kw["stdout"].write(b"")
        return _R()

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)

    result = adapter.invoke("hello", afk=True, model=None)

    cmd = captured["cmd"]
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in cmd, f"--verbose required by claude when --output-format stream-json: {cmd}"
    assert "--session-id" not in cmd, f"--session-id must not be in cmd (not a UUID): {cmd}"

    stdout = captured["stdout"]
    assert hasattr(stdout, "write"), f"stdout not a file handle: {stdout!r}"

    assert result.session_log == log_path, f"session_log mismatch: {result.session_log}"
    assert log_path.exists()


def test_adapter_session_log_none_when_env_unset(tmp_path, monkeypatch):
    adapter = _load(IMPL_SCRIPTS / "harness" / "claude_code.py", "claude_code_adapter_2")
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)
    monkeypatch.delenv("MENTAT_SESSION", raising=False)

    class _R:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr(adapter.subprocess, "run", lambda cmd, **kw: _R())
    result = adapter.invoke("hello", afk=False, model=None)
    assert result.session_log is None
