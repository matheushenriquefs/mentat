"""C3 — `runtime = "host"` opt-out for mentat-container.

Default (unset / `"docker"` / `"container"`): bring-up + run stay containerized.
`runtime = "host"`: `up` skips bring-up, `run` executes the command directly on the
host — after one loud warning (per worktree slug) that ADR-0004 isolation is forfeited.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-container/scripts"
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".agents"))


def _container():
    return load_script(SCRIPTS / "container.py", "container")


class _R:
    returncode = 0
    stdout = ""


def test_run_host_runtime_executes_on_host(tmp_path):
    """With runtime=host, cmd_run runs `bash -lc <cmd>` on the host, not docker exec."""
    container = _container()
    calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _R()

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("lib.config.read_config", return_value={"runtime": "host"}),
        patch.object(container.subprocess, "run", fake_run),
    ):
        rc = container.cmd_run(tmp_path, "echo hi")

    assert rc == 0
    assert calls, "cmd_run made no subprocess call"
    assert calls[0][0] == "bash", f"expected host bash exec, got {calls[0]!r}"
    assert "echo hi" in calls[0][-1]
    assert not any("exec" in str(c) for c in calls), "must not docker-exec in host mode"


def test_run_host_runtime_warns_once(tmp_path, capsys):
    """The isolation-forfeit warning prints once per slug, not on every run."""
    container = _container()

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("lib.config.read_config", return_value={"runtime": "host"}),
        patch.object(container.subprocess, "run", lambda *a, **k: _R()),
    ):
        container.cmd_run(tmp_path, "echo one")
        first = capsys.readouterr().err
        container.cmd_run(tmp_path, "echo two")
        second = capsys.readouterr().err

    assert "ADR-0004" in first
    assert "host" in first.lower()
    assert "isolation" in first.lower()
    assert second.strip() == "", f"warning repeated: {second!r}"


def test_up_host_runtime_skips_bringup(tmp_path):
    """With runtime=host, cmd_up brings nothing up and returns success."""
    container = _container()
    calls: list[object] = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _R()

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("lib.config.read_config", return_value={"runtime": "host"}),
        patch.object(container.subprocess, "run", fake_run),
    ):
        rc = container.cmd_up(tmp_path)

    assert rc == 0
    assert not any("devcontainer" in str(c) for c in calls), "host mode must not run devcontainer up"


def test_down_host_runtime_skips_devcontainer(tmp_path):
    """With runtime=host nothing was brought up, so down is a no-op (returns 0)."""
    container = _container()

    with (
        patch("lib.config.read_config", return_value={"runtime": "host"}),
        patch("lib.devcontainer.down") as mock_down,
    ):
        rc = container.cmd_down(slug="anything")

    assert rc == 0
    mock_down.assert_not_called()


def test_run_default_runtime_requires_container(tmp_path, capsys):
    """No runtime key → containerized path unchanged (no container → exit 69)."""
    container = _container()

    with (
        patch("lib.config.read_config", return_value={}),
        patch.object(container.utils, "container_id_for", return_value=None),
    ):
        rc = container.cmd_run(tmp_path, "echo hi")

    assert rc == 69
    assert "ADR-0004" not in capsys.readouterr().err


def test_docker_value_is_containerized_not_host(tmp_path):
    """`runtime = "docker"` is the container default, NOT the host opt-out."""
    container = _container()

    with (
        patch("lib.config.read_config", return_value={"runtime": "docker"}),
        patch.object(container.utils, "container_id_for", return_value=None),
    ):
        rc = container.cmd_run(tmp_path, "echo hi")

    assert rc == 69  # took the containerized branch, hit no-container guard
