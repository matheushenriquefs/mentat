"""E2E: the devcontainer docker-CLI wrapper.

Drives every function in ``lib.devcontainer`` by monkeypatching the single
subprocess seam (``devcontainer.subprocess.run``) with an argv-branching
recorder. Docker is NEVER really invoked — the recorder returns fake
``CompletedProcess`` objects (or raises ``FileNotFoundError`` /
``subprocess.TimeoutExpired``) so the parsing, restart, cold-start, and
error branches are all exercised on the host.
"""

from __future__ import annotations

import subprocess
import types
from pathlib import Path

import pytest
from lib import devcontainer

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> types.SimpleNamespace:
    """A stand-in for subprocess.CompletedProcess (only the fields we read)."""
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class Recorder:
    """Captures every argv it is called with and replays a scripted result.

    ``responder`` receives the argv and returns a fake CompletedProcess, or
    raises to simulate a missing/hung binary.
    """

    def __init__(self, responder) -> None:
        self.responder = responder
        self.calls: list[dict] = []

    def __call__(self, cmd, *args, **kwargs):  # noqa: D401 - subprocess.run shim
        self.calls.append({"cmd": cmd, "args": args, "kwargs": kwargs})
        return self.responder(cmd)


# ── _docker_bin ───────────────────────────────────────────────────────────────


def test_docker_bin_defaults_to_docker(monkeypatch):
    monkeypatch.delenv("MENTAT_DOCKER", raising=False)
    assert devcontainer._docker_bin() == "docker"


def test_docker_bin_honors_mentat_docker_env(monkeypatch):
    monkeypatch.setenv("MENTAT_DOCKER", "/opt/podman")
    assert devcontainer._docker_bin() == "/opt/podman"


# ── _run_docker ───────────────────────────────────────────────────────────────


def test_run_docker_returns_completed_process(monkeypatch):
    rec = Recorder(lambda cmd: _cp(0, "ok"))
    monkeypatch.setattr(devcontainer.subprocess, "run", rec)
    r = devcontainer._run_docker(["docker", "ps"])
    assert r is not None
    assert r.stdout == "ok"


def test_run_docker_substitutes_the_docker_bin(monkeypatch):
    monkeypatch.setenv("MENTAT_DOCKER", "podman")
    rec = Recorder(lambda cmd: _cp(0))
    monkeypatch.setattr(devcontainer.subprocess, "run", rec)
    devcontainer._run_docker(["docker", "ps", "-a"])
    # argv[0] replaced by _docker_bin(); the rest of argv[1:] preserved.
    assert rec.calls[0]["cmd"] == ["podman", "ps", "-a"]


def test_run_docker_missing_binary_prints_and_returns_none(monkeypatch, capsys):
    def boom(cmd):
        raise FileNotFoundError

    monkeypatch.setattr(devcontainer.subprocess, "run", Recorder(boom))
    r = devcontainer._run_docker(["docker", "ps"])
    assert r is None
    assert "docker not on PATH" in capsys.readouterr().err


def test_run_docker_timeout_prints_and_returns_none(monkeypatch, capsys):
    def boom(cmd):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=30)

    monkeypatch.setattr(devcontainer.subprocess, "run", Recorder(boom))
    r = devcontainer._run_docker(["docker", "ps"])
    assert r is None
    assert "timed out" in capsys.readouterr().err


# ── prune ─────────────────────────────────────────────────────────────────────


def test_prune_returns_empty_when_run_docker_none(monkeypatch):
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: None)
    assert devcontainer.prune() == devcontainer.PruneResult(None, 0)


def test_prune_returns_empty_on_nonzero_returncode(monkeypatch):
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: _cp(1, "boom"))
    assert devcontainer.prune() == devcontainer.PruneResult(None, 0)


def test_prune_parses_reclaimed_bytes_and_counts_only_ids(monkeypatch):
    stdout = "Deleted Containers:\nabc123\ndef456\n\nTotal reclaimed space: 1234\n"
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: _cp(0, stdout))
    result = devcontainer.prune()
    assert result.reclaimed_bytes == 1234
    # header + Total line + blank line excluded; only the two id lines counted.
    assert result.containers_removed == 2


# ── list_active_slugs ─────────────────────────────────────────────────────────


def test_list_active_slugs_empty_when_none(monkeypatch):
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: None)
    assert devcontainer.list_active_slugs() == set()


def test_list_active_slugs_empty_on_nonzero(monkeypatch):
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: _cp(1))
    assert devcontainer.list_active_slugs() == set()


def test_list_active_slugs_returns_stripped_nonblank_set(monkeypatch):
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: _cp(0, "alpha\n\n beta \n"))
    assert devcontainer.list_active_slugs() == {"alpha", "beta"}


# ── container_id_for_slug ─────────────────────────────────────────────────────


def test_container_id_none_when_run_docker_none(monkeypatch):
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: None)
    assert devcontainer.container_id_for_slug("s") is None


def test_container_id_none_on_nonzero(monkeypatch):
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: _cp(1))
    assert devcontainer.container_id_for_slug("s") is None


def test_container_id_returns_first_id(monkeypatch):
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: _cp(0, "cid1\ncid2\n"))
    assert devcontainer.container_id_for_slug("s") == "cid1"


def test_container_id_none_when_stdout_empty(monkeypatch):
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: _cp(0, "\n \n"))
    assert devcontainer.container_id_for_slug("s") is None


# ── down ──────────────────────────────────────────────────────────────────────


def test_down_false_when_ps_none(monkeypatch):
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: None)
    assert devcontainer.down("s") is False


def test_down_false_when_ps_nonzero(monkeypatch):
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: _cp(1))
    assert devcontainer.down("s") is False


def test_down_true_when_no_containers(monkeypatch):
    monkeypatch.setattr(devcontainer, "_run_docker", lambda argv, **kw: _cp(0, "\n"))
    assert devcontainer.down("s") is True


def test_down_removes_each_container_and_returns_true(monkeypatch):
    def responder(cmd):
        # cmd is the raw argv passed to _run_docker (argv[1] is the subcommand).
        if cmd[1] == "ps":
            return _cp(0, "cid1\ncid2\n")
        return _cp(0)  # docker rm -f

    rec = Recorder(responder)
    monkeypatch.setattr(devcontainer, "_run_docker", rec)
    assert devcontainer.down("s") is True
    rm_cmds = [c["cmd"] for c in rec.calls if c["cmd"][1] == "rm"]
    assert rm_cmds == [["docker", "rm", "-f", "cid1"], ["docker", "rm", "-f", "cid2"]]


def test_down_false_when_a_remove_fails(monkeypatch):
    def responder(cmd):
        if cmd[1] == "ps":
            return _cp(0, "cid1\ncid2\n")
        if cmd[3] == "cid2":
            return None  # this rm fails
        return _cp(0)

    monkeypatch.setattr(devcontainer, "_run_docker", Recorder(responder))
    assert devcontainer.down("s") is False


# ── up ────────────────────────────────────────────────────────────────────────


def test_up_restart_path_returns_true(monkeypatch, tmp_path):
    """Exited container found → docker start → container_id present → True."""

    def responder(cmd):
        assert cmd[0] == "docker"
        if "status=exited" in cmd:
            return _cp(0, "stopcid\n")  # a stopped container exists
        if cmd[1] == "start":
            return _cp(0)
        if cmd[1] == "ps":  # container_id_for_slug lookup
            return _cp(0, "runcid\n")
        raise AssertionError(cmd)

    rec = Recorder(responder)
    monkeypatch.setattr(devcontainer.subprocess, "run", rec)
    assert devcontainer.up("s", tmp_path) is True
    start_cmds = [c["cmd"] for c in rec.calls if c["cmd"][1] == "start"]
    assert start_cmds == [["docker", "start", "stopcid"]]


def test_up_cold_start_with_git_dir_returns_true(monkeypatch, tmp_path):
    """No stopped container → git rev-parse ok → devcontainer up ok → True."""

    def responder(cmd):
        if cmd[0] == "docker" and "status=exited" in cmd:
            return _cp(0, "")  # no stopped container
        if cmd[0] == "git":
            return _cp(0, ".git\n")
        if cmd[0] == "devcontainer":
            # git dir present → --remote-env flags appended
            assert "--remote-env" in cmd
            return _cp(0)
        raise AssertionError(cmd)

    monkeypatch.setattr(devcontainer.subprocess, "run", Recorder(responder))
    assert devcontainer.up("s", tmp_path) is True


def test_up_cold_start_git_timeout_omits_remote_env(monkeypatch, tmp_path):
    """git rev-parse times out → git_dir="" → devcontainer up has no --remote-env."""

    def responder(cmd):
        if cmd[0] == "docker" and "status=exited" in cmd:
            return _cp(0, "")
        if cmd[0] == "git":
            raise subprocess.TimeoutExpired(cmd="git", timeout=30)
        if cmd[0] == "devcontainer":
            assert "--remote-env" not in cmd
            return _cp(0)
        raise AssertionError(cmd)

    monkeypatch.setattr(devcontainer.subprocess, "run", Recorder(responder))
    assert devcontainer.up("s", tmp_path) is True


def test_up_cold_start_git_nonzero_omits_remote_env(monkeypatch, tmp_path):
    """git rev-parse nonzero → git_dir="" → no --remote-env flags."""

    def responder(cmd):
        if cmd[0] == "docker" and "status=exited" in cmd:
            return _cp(0, "")
        if cmd[0] == "git":
            return _cp(128, "")  # not a git repo
        if cmd[0] == "devcontainer":
            assert "--remote-env" not in cmd
            return _cp(0)
        raise AssertionError(cmd)

    monkeypatch.setattr(devcontainer.subprocess, "run", Recorder(responder))
    assert devcontainer.up("s", tmp_path) is True


def test_up_devcontainer_cli_missing_returns_false(monkeypatch, tmp_path, capsys):
    def responder(cmd):
        if cmd[0] == "docker" and "status=exited" in cmd:
            return _cp(0, "")
        if cmd[0] == "git":
            return _cp(0, ".git\n")
        if cmd[0] == "devcontainer":
            raise FileNotFoundError
        raise AssertionError(cmd)

    monkeypatch.setattr(devcontainer.subprocess, "run", Recorder(responder))
    assert devcontainer.up("s", tmp_path) is False
    assert "devcontainer CLI not on PATH" in capsys.readouterr().err


def test_up_devcontainer_timeout_returns_false(monkeypatch, tmp_path, capsys):
    def responder(cmd):
        if cmd[0] == "docker" and "status=exited" in cmd:
            return _cp(0, "")
        if cmd[0] == "git":
            return _cp(0, ".git\n")
        if cmd[0] == "devcontainer":
            raise subprocess.TimeoutExpired(cmd="devcontainer", timeout=900)
        raise AssertionError(cmd)

    monkeypatch.setattr(devcontainer.subprocess, "run", Recorder(responder))
    assert devcontainer.up("s", tmp_path) is False
    assert "timed out" in capsys.readouterr().err


def test_up_honors_mentat_up_timeout_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_UP_TIMEOUT", "42")

    def responder(cmd):
        if cmd[0] == "docker" and "status=exited" in cmd:
            return _cp(0, "")
        if cmd[0] == "git":
            return _cp(0, ".git\n")
        if cmd[0] == "devcontainer":
            return _cp(0)
        raise AssertionError(cmd)

    rec = Recorder(responder)
    monkeypatch.setattr(devcontainer.subprocess, "run", rec)
    devcontainer.up("s", tmp_path)
    dc_call = next(c for c in rec.calls if c["cmd"][0] == "devcontainer")
    assert dc_call["kwargs"]["timeout"] == 42


def test_up_cold_start_falls_back_to_container_id_when_rc_nonzero(monkeypatch, tmp_path):
    """devcontainer up nonzero but the container is nonetheless running → True."""

    def responder(cmd):
        if cmd[0] == "docker" and "status=exited" in cmd:
            return _cp(0, "")
        if cmd[0] == "git":
            return _cp(0, ".git\n")
        if cmd[0] == "devcontainer":
            return _cp(1)  # nonzero exit
        if cmd[0] == "docker" and cmd[1] == "ps":  # container_id_for_slug
            return _cp(0, "runcid\n")
        raise AssertionError(cmd)

    monkeypatch.setattr(devcontainer.subprocess, "run", Recorder(responder))
    assert devcontainer.up("s", tmp_path) is True


# ── run ───────────────────────────────────────────────────────────────────────


def test_run_returns_none_when_no_container(monkeypatch):
    monkeypatch.setattr(devcontainer, "container_id_for_slug", lambda slug: None)
    assert devcontainer.run("s", "echo hi") is None


def test_run_execs_in_container(monkeypatch):
    monkeypatch.setattr(devcontainer, "container_id_for_slug", lambda slug: "cid")
    rec = Recorder(lambda cmd: _cp(0, "hi"))
    monkeypatch.setattr(devcontainer, "_run_docker", rec)
    r = devcontainer.run("s", "echo hi")
    assert r.stdout == "hi"
    assert rec.calls[0]["cmd"] == ["docker", "exec", "cid", "sh", "-c", "echo hi"]


# ── exec ──────────────────────────────────────────────────────────────────────


def test_exec_returns_none_when_no_container(monkeypatch):
    monkeypatch.setattr(devcontainer, "container_id_for_slug", lambda slug: None)
    assert devcontainer.exec("s", ["ls"]) is None


def test_exec_builds_cmd_with_workdir_user_and_argv(monkeypatch):
    monkeypatch.setenv("MENTAT_DOCKER", "podman")
    monkeypatch.setattr(devcontainer, "container_id_for_slug", lambda slug: "cid")
    rec = Recorder(lambda cmd: _cp(0))
    monkeypatch.setattr(devcontainer.subprocess, "run", rec)
    devcontainer.exec("s", ["ls", "-la"], workdir="/w", user="1000")
    assert rec.calls[0]["cmd"] == [
        "podman",
        "exec",
        "--workdir",
        "/w",
        "-u",
        "1000",
        "cid",
        "ls",
        "-la",
    ]


def test_exec_without_workdir_or_user(monkeypatch):
    monkeypatch.setattr(devcontainer, "container_id_for_slug", lambda slug: "cid")
    rec = Recorder(lambda cmd: _cp(0))
    monkeypatch.setattr(devcontainer.subprocess, "run", rec)
    devcontainer.exec("s", ["true"])
    assert rec.calls[0]["cmd"] == ["docker", "exec", "cid", "true"]


def test_exec_missing_docker_prints_and_returns_none(monkeypatch, capsys):
    monkeypatch.setattr(devcontainer, "container_id_for_slug", lambda slug: "cid")

    def boom(cmd):
        raise FileNotFoundError

    monkeypatch.setattr(devcontainer.subprocess, "run", Recorder(boom))
    assert devcontainer.exec("s", ["ls"]) is None
    assert "docker not on PATH" in capsys.readouterr().err


# ── PruneResult dataclass ─────────────────────────────────────────────────────


def test_prune_result_is_frozen_with_expected_fields():
    pr = devcontainer.PruneResult(reclaimed_bytes=10, containers_removed=2)
    assert (pr.reclaimed_bytes, pr.containers_removed) == (10, 2)
    with pytest.raises(Exception):  # noqa: B017 - FrozenInstanceError is a dataclass detail
        pr.reclaimed_bytes = 99  # type: ignore[misc]
