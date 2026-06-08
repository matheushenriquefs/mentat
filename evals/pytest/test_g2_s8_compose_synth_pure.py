"""G2-S8 — compose-synth.sh becomes a pure callable.

Plan target (~/.agents/plans/mentat-architecture-revamp-g2-container-quartet.md
§S8): synthesize_devcontainer + synthesize_devcontainer_from_dockerfile must
emit the devcontainer.json body on stdout. No filesystem writes. Caller
(container-state.sh::synthesize_compose_if_absent / mentat-container-up)
captures stdout + writes the file.

Verify (per plan §S8):
  - "invoked twice in a row produces identical output" -> deterministic
  - "No filesystem writes from the script itself" -> purity
  - "mentat-container-up still synthesizes the compose file on first up" ->
    caller-side write path still works (covered via synthesize_compose_if_absent).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / ".agents" / "bin" / "lib"
COMPOSE_SYNTH = LIB / "compose-synth.sh"
CONTAINER_STATE = LIB / "container-state.sh"


def _run(call: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Source compose-synth.sh, invoke `call`, capture stdout/stderr/rc."""
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(
        ["bash", "-c", f". {COMPOSE_SYNTH} && {call}"],
        cwd=str(cwd),
        env=e,
        capture_output=True,
        text=True,
    )


def _seed_compose(wt: Path, service: str = "app") -> None:
    """Minimal docker-compose.yml with one build/cwd-mounted service."""
    (wt / "docker-compose.yml").write_text(
        "services:\n"
        f"  {service}:\n"
        "    build: .\n"
        "    volumes:\n"
        "      - .:/srv/app\n"
    )


def _seed_dockerfile(wt: Path, workdir: str = "/srv/app") -> None:
    (wt / "Dockerfile").write_text(
        "FROM alpine:3.20\n"
        f"WORKDIR {workdir}\n"
        "CMD [\"sh\"]\n"
    )


# -- synthesize_devcontainer (compose path) ---------------------------------


def test_synthesize_devcontainer_emits_json_on_stdout(tmp_path):
    """Pure callable: JSON body lands on stdout, valid + structured."""
    _seed_compose(tmp_path)
    res = _run("synthesize_devcontainer", tmp_path, env={"WT": str(tmp_path), "SLUG": "myslug"})
    assert res.returncode == 0, f"rc={res.returncode} stderr={res.stderr!r}"
    body = json.loads(res.stdout)
    assert body["name"] == "myslug"
    assert body["service"] == "app"
    assert body["workspaceFolder"] == "/srv/app"


def test_synthesize_devcontainer_writes_no_file(tmp_path):
    """Pure: no `.devcontainer/devcontainer.json` materialised by the fn."""
    _seed_compose(tmp_path)
    res = _run("synthesize_devcontainer", tmp_path, env={"WT": str(tmp_path), "SLUG": "myslug"})
    assert res.returncode == 0, res.stderr
    assert not (tmp_path / ".devcontainer").exists(), (
        "synthesize_devcontainer must not create .devcontainer/ — caller's job"
    )


def test_synthesize_devcontainer_deterministic(tmp_path):
    """Plan: 'invoked twice in a row produces identical output.'"""
    _seed_compose(tmp_path)
    env = {"WT": str(tmp_path), "SLUG": "myslug"}
    a = _run("synthesize_devcontainer", tmp_path, env=env)
    b = _run("synthesize_devcontainer", tmp_path, env=env)
    assert a.stdout == b.stdout, "non-deterministic: two calls differ"
    assert a.returncode == 0 == b.returncode


# -- synthesize_devcontainer_from_dockerfile (bare Dockerfile path) ---------


def test_synthesize_from_dockerfile_emits_json_on_stdout(tmp_path):
    _seed_dockerfile(tmp_path, workdir="/srv/app")
    res = _run(
        "synthesize_devcontainer_from_dockerfile",
        tmp_path,
        env={"WT": str(tmp_path), "SLUG": "dfslug"},
    )
    assert res.returncode == 0, f"rc={res.returncode} stderr={res.stderr!r}"
    body = json.loads(res.stdout)
    assert body["name"] == "dfslug"
    assert body["build"]["dockerfile"] == "../Dockerfile"
    assert body["workspaceFolder"] == "/srv/app"


def test_synthesize_from_dockerfile_writes_no_file(tmp_path):
    _seed_dockerfile(tmp_path)
    res = _run(
        "synthesize_devcontainer_from_dockerfile",
        tmp_path,
        env={"WT": str(tmp_path), "SLUG": "dfslug"},
    )
    assert res.returncode == 0, res.stderr
    assert not (tmp_path / ".devcontainer").exists(), (
        "synthesize_devcontainer_from_dockerfile must not create .devcontainer/"
    )


def test_synthesize_from_dockerfile_deterministic(tmp_path):
    _seed_dockerfile(tmp_path)
    env = {"WT": str(tmp_path), "SLUG": "dfslug"}
    a = _run("synthesize_devcontainer_from_dockerfile", tmp_path, env=env)
    b = _run("synthesize_devcontainer_from_dockerfile", tmp_path, env=env)
    assert a.stdout == b.stdout, "non-deterministic: two calls differ"
    assert a.returncode == 0 == b.returncode


# -- caller still writes devcontainer.json (compose lib path) ---------------


def test_synthesize_compose_if_absent_writes_devcontainer_json(tmp_path):
    """Plan §S8 verify clause: 'mentat-container-up still synthesizes the
    compose file on first up.' synthesize_compose_if_absent is the lib seam
    that mentat-container-up will delegate through (and where the caller-side
    write lives after S8). With no devcontainer.json present + a docker-compose.yml
    seeded, the helper must materialise .devcontainer/devcontainer.json."""
    _seed_compose(tmp_path)
    res = subprocess.run(
        ["bash", "-c", f". {CONTAINER_STATE} && synthesize_compose_if_absent"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"rc={res.returncode} stderr={res.stderr!r}"
    dcj = tmp_path / ".devcontainer" / "devcontainer.json"
    assert dcj.is_file(), (
        f"synthesize_compose_if_absent must write devcontainer.json; "
        f"stderr={res.stderr!r}"
    )
    body = json.loads(dcj.read_text())
    assert body["service"] == "app"


def test_synthesize_compose_if_absent_does_not_poison_on_exit3(tmp_path):
    """Regression: bash truncates a `> final` redirect BEFORE invoking the
    sourced fn. synthesize_devcontainer `exit 3`s on zero/multiple buildable
    services, so a naked `synthesize_x > final` would leave an empty
    devcontainer.json that the file-exists guard re-greenlights on next run
    (data poisoning, masks the real error). The atomic tmp+mv contract must
    leave the real target ABSENT on failure."""
    (tmp_path / "docker-compose.yml").write_text(
        # Two buildable services -> synthesize_devcontainer cannot pick one,
        # hits `exit 3`.
        "services:\n"
        "  app:\n"
        "    build: .\n"
        "  worker:\n"
        "    build: .\n"
    )
    res = subprocess.run(
        ["bash", "-c", f". {CONTAINER_STATE} && synthesize_compose_if_absent"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0, (
        f"helper must fail when compose has multiple buildable services; "
        f"stderr={res.stderr!r}"
    )
    dcj = tmp_path / ".devcontainer" / "devcontainer.json"
    assert not dcj.exists(), (
        f"poisoned target survived exit-3 — atomic tmp+mv contract broken; "
        f"size={dcj.stat().st_size if dcj.exists() else 'absent'}"
    )
