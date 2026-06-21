"""Tests for lib/devcontainer.py — stdlib-only docker CLI wrapper."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / ".agents/lib"

import devcontainer  # noqa: E402


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    r: subprocess.CompletedProcess = subprocess.CompletedProcess.__new__(subprocess.CompletedProcess)
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    r.args = []
    return r


# ── prune ────────────────────────────────────────────────────────────────────


def test_prune_invokes_docker_with_label_filter(monkeypatch):
    captured: list[list[str]] = []

    def fake_run(argv, **kw):
        captured.append(list(argv))
        return _cp(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    devcontainer.prune()

    assert captured, "subprocess.run not called"
    assert captured[0] == [
        "docker",
        "container",
        "prune",
        "-f",
        "--filter",
        "label=mentat_slug",
        "--filter",
        "until=1h",
    ]


def test_prune_parses_reclaimed_bytes(monkeypatch):
    stdout = "Deleted Containers:\nabc\n\nTotal reclaimed space: 12345"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _cp(0, stdout))
    result = devcontainer.prune()

    assert result.reclaimed_bytes == 12345


def test_prune_handles_no_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _cp(0, ""))
    result = devcontainer.prune()

    assert result.reclaimed_bytes is None
    assert result.containers_removed == 0


def test_prune_docker_missing_returns_zero_result(monkeypatch, capsys):
    def raise_fnf(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", raise_fnf)
    result = devcontainer.prune()

    assert result == devcontainer.PruneResult(None, 0)
    captured = capsys.readouterr()
    assert captured.err.strip() != "", "expected one stderr advisory"


# ── list_active_slugs ─────────────────────────────────────────────────────────


def test_list_active_slugs_parses_label_column(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _cp(0, "mentat-1-2-3\nmentat-4-5-6\n"))
    result = devcontainer.list_active_slugs()

    assert result == {"mentat-1-2-3", "mentat-4-5-6"}


# ── container_id_for_slug ─────────────────────────────────────────────────────


def test_container_id_for_slug_returns_first_match(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _cp(0, "abc123\ndef456\n"))
    result = devcontainer.container_id_for_slug("some-slug")

    assert result == "abc123"


def test_container_id_for_slug_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _cp(0, ""))
    result = devcontainer.container_id_for_slug("some-slug")

    assert result is None


# ── run ───────────────────────────────────────────────────────────────────────


def test_run_dispatches_docker_exec(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(list(argv))
        stdout = "abc123\n" if len(argv) > 1 and argv[1] == "ps" else ""
        return _cp(0, stdout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    devcontainer.run("slug-x", "echo hi")

    exec_calls = [c for c in calls if len(c) > 1 and c[1] == "exec"]
    assert exec_calls, "docker exec not called"
    assert exec_calls[0][:2] == ["docker", "exec"]
    assert "echo hi" in exec_calls[0]


# ── down ──────────────────────────────────────────────────────────────────────


def test_down_removes_running_container(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(list(argv))
        if argv[1] == "ps" and "--filter" in argv and "status=exited" not in argv:
            return _cp(0, "cid-abc\n")
        return _cp(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = devcontainer.down("my-slug")

    assert result is True
    rm_calls = [c for c in calls if len(c) > 1 and c[1] == "rm"]
    assert rm_calls, "docker rm not called"
    assert "cid-abc" in rm_calls[0]


def test_down_removes_stopped_container(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(list(argv))
        if argv[1] == "ps" and "-aq" in argv:
            return _cp(0, "stopped-cid\n")
        return _cp(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = devcontainer.down("my-slug")

    assert result is True
    rm_calls = [c for c in calls if len(c) > 1 and c[1] == "rm"]
    assert rm_calls, "docker rm not called for stopped container"


def test_down_returns_true_when_not_running(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _cp(0, ""))
    result = devcontainer.down("nonexistent-slug")
    assert result is True


# ── up ────────────────────────────────────────────────────────────────────────


def test_up_restarts_stopped_container(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(list(argv))
        if argv[1] == "ps" and "status=exited" in argv:
            return _cp(0, "stopped-cid\n")
        if argv[1] == "ps":
            return _cp(0, "abc123\n")  # running after start
        return _cp(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = devcontainer.up("my-slug", tmp_path)

    assert result is True
    start_calls = [c for c in calls if len(c) > 1 and c[1] == "start"]
    assert start_calls, "docker start not called"


def test_up_cold_start_calls_devcontainer_cli(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(list(argv))
        if argv[0] == "docker" and argv[1] == "ps":
            return _cp(0, "")  # no running or stopped container
        return _cp(0, "abc123\n")  # devcontainer up succeeds → container_id check returns a cid

    monkeypatch.setattr(subprocess, "run", fake_run)
    devcontainer.up("my-slug", tmp_path)

    devcontainer_calls = [c for c in calls if c[0] == "devcontainer"]
    assert devcontainer_calls, "devcontainer CLI not called for cold start"
    assert "up" in devcontainer_calls[0]
    assert "--id-label" in devcontainer_calls[0]


# ── stdlib check ──────────────────────────────────────────────────────────────


# ── CT4: down removes all matching containers ─────────────────────────────────


def test_down_removes_all_matching_containers(monkeypatch):
    """Two containers sharing the slug label must both be removed by down()."""
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(list(argv))
        if argv[1] == "ps" and "-aq" in argv and "status=exited" not in argv:
            return _cp(0, "cid1\ncid2\n")
        return _cp(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = devcontainer.down("my-slug")

    assert result is True
    rm_calls = [c for c in calls if len(c) > 1 and c[1] == "rm"]
    removed = {item for rm in rm_calls for item in rm}
    assert "cid1" in removed, "first container must be removed"
    assert "cid2" in removed, "second container must be removed"


# ── stdlib check ──────────────────────────────────────────────────────────────


def test_devcontainer_stdlib_only():
    import ast

    source = (_LIB / "devcontainer.py").read_text()
    tree = ast.parse(source)
    stdlib = sys.stdlib_module_names  # Python 3.10+

    third_party: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in stdlib:
                    third_party.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top not in stdlib:
                third_party.append(node.module)

    assert not third_party, f"non-stdlib imports found: {third_party}"
