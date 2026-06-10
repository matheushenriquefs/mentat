"""G2-S2: lib/container-state.sh implementation.

Spec (~/.agents/plans/mentat-architecture-revamp-g2-container-quartet.md S2):
  - Implement the 5 helpers from S1 (signatures locked in
    .agents/docs/container-state-design.md).
  - Each helper sources nothing; pure shell functions reading docker / fs.
  - Fail-loud on any precondition violation (no silent fallback).
  - Convention locked in S1 HITL: values on stdout, success via exit 0,
    failure via nonzero exit + stderr message.

Verify (from plan):
  - `bash -n container-state.sh` clean.
  - Each function callable in isolation.
  - assert_safe_directory on a known-good container returns 0; on broken
    state exits nonzero with the exact missing-config line.

Testing strategy:
  These tests run inside the dev container per AGENTS.md ADR-0002, but
  the lib it tests is a HOST-side wrapper around `docker`. Docker is not
  installed in the container, so we inject `MENTAT_DOCKER=<fake_docker>`
  to drive the lib's logic against scripted responses. Every docker
  invocation is a real subprocess call, so the lib's quoting + arg
  passing is exercised — only the docker binary itself is mocked.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / ".agents" / "bin" / "lib" / "container-state.sh"
DESIGN_DOC = ROOT / ".agents" / "docs" / "container-state-design.md"

HELPERS = (
    "container_id_for",
    "ensure_workspace_folder",
    "assert_safe_directory",
    "synthesize_compose_if_absent",
    "container_slug_for_cwd",
)


def _source_call(call: str, cwd: str | None = None, env: dict | None = None):
    """Source the lib and run `call` in a fresh bash. Returns CompletedProcess."""
    full = f". {LIB}; {call}"
    cmd = ["bash", "-c", full]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, **(env or {})},
    )


def _make_fake_docker(tmp_path: Path, script_body: str) -> Path:
    """Write an executable fake `docker` and return its path. Tests set
    `MENTAT_DOCKER` to this path to override the real CLI."""
    fake = tmp_path / "fake_docker"
    fake.write_text(f"#!/usr/bin/env bash\n{script_body}\n")
    fake.chmod(0o755)
    return fake


# -- File existence + syntactic gate -----------------------------------------


def test_lib_file_exists():
    """Plan S2: file `~/.agents/bin/lib/container-state.sh` is created."""
    assert LIB.is_file(), f"lib missing at {LIB}"


def test_lib_passes_bash_n():
    """Plan S2 verify: `bash -n container-state.sh` clean."""
    res = subprocess.run(["bash", "-n", str(LIB)], capture_output=True, text=True)
    assert res.returncode == 0, f"bash -n failed (rc={res.returncode}):\nstdout={res.stdout!r}\nstderr={res.stderr!r}"


def test_lib_defines_all_five_helpers():
    """Each helper must be defined as a shell function in the lib —
    detected via `declare -F` after sourcing."""
    res = _source_call("declare -F | awk '{print $3}'")
    assert res.returncode == 0, f"sourcing failed: {res.stderr}"
    defined = set(res.stdout.split())
    missing = [h for h in HELPERS if h not in defined]
    assert not missing, f"helpers not defined as functions: {missing}\nsaw: {sorted(defined)}"


def test_lib_source_is_side_effect_free():
    """Sourcing the lib must not run docker, must not write files. The
    helpers are pure functions per design doc § Helpers."""
    res = _source_call(":")
    assert res.returncode == 0, f"source caused failure: {res.stderr}"
    assert res.stdout == "", f"unexpected stdout on source: {res.stdout!r}"


# -- container_slug_for_cwd: always-succeeds contract ------------------------


def test_container_slug_for_cwd_returns_basename(tmp_path):
    """Plan S1 + design doc: `basename "$PWD"`. Sole canonical site."""
    sub = tmp_path / "my-slug-xyz"
    sub.mkdir()
    res = _source_call("container_slug_for_cwd", cwd=str(sub))
    assert res.returncode == 0, f"helper exited nonzero: {res.stderr}"
    assert res.stdout.strip() == "my-slug-xyz", f"got {res.stdout!r}"


def test_container_slug_for_cwd_exit_zero_always():
    """Design doc explicit: 'this is the one helper that cannot fail,
    and S2 tests must lock that.'"""
    res = _source_call("container_slug_for_cwd", cwd="/tmp")
    assert res.returncode == 0
    assert res.stdout.strip() == "tmp"


# -- container_id_for: lookup by mentat_slug label ---------------------------


def test_container_id_for_missing_slug_exits_nonzero(tmp_path):
    """Plan: 'no running container for slug → exit 1.' Fake docker
    returns nothing — helper must exit nonzero."""
    fake = _make_fake_docker(tmp_path, "exit 0")  # empty stdout
    res = _source_call(
        'container_id_for "any-slug"',
        env={"MENTAT_DOCKER": str(fake)},
    )
    assert res.returncode != 0, f"container_id_for must exit nonzero on miss; got rc=0 stdout={res.stdout!r}"
    assert res.stdout.strip() == "", f"no CID should be printed on miss; got {res.stdout!r}"


def test_container_id_for_hit_returns_cid(tmp_path):
    """Fake docker prints a CID — helper must echo it on stdout and exit 0."""
    body = textwrap.dedent("""\
        if [ "$1" = "ps" ]; then
          echo "abc123def456"
        fi
    """)
    fake = _make_fake_docker(tmp_path, body)
    res = _source_call(
        'container_id_for "any-slug"',
        env={"MENTAT_DOCKER": str(fake)},
    )
    assert res.returncode == 0, f"helper exited nonzero: stderr={res.stderr!r}"
    assert res.stdout.strip() == "abc123def456", f"got {res.stdout!r}"


def test_container_id_for_passes_label_filter(tmp_path):
    """Lib must filter by `label=mentat_slug=<slug>`. Fake docker
    records its argv to a sidecar file; test asserts the filter shape."""
    log = tmp_path / "argv.log"
    body = textwrap.dedent(f'''\
        printf '%s\\n' "$@" >> "{log}"
        echo "deadbeefcafe"
    ''')
    fake = _make_fake_docker(tmp_path, body)
    res = _source_call(
        'container_id_for "the-slug"',
        env={"MENTAT_DOCKER": str(fake)},
    )
    assert res.returncode == 0
    argv = log.read_text().splitlines() if log.exists() else []
    assert "label=mentat_slug=the-slug" in argv, f"docker not invoked with mentat_slug label filter; saw argv={argv!r}"
    assert "ps" in argv, f"docker subcommand must be `ps`; saw {argv!r}"


def test_container_id_for_returns_single_cid_when_multiple(tmp_path):
    """Design doc: 'multiple matches are a separate failure — the lib
    returns the first.' Lock head-1 behaviour."""
    body = textwrap.dedent("""\
        if [ "$1" = "ps" ]; then
          printf 'firstcid\\nsecondcid\\n'
        fi
    """)
    fake = _make_fake_docker(tmp_path, body)
    res = _source_call(
        'container_id_for "any-slug"',
        env={"MENTAT_DOCKER": str(fake)},
    )
    assert res.returncode == 0
    assert res.stdout.strip() == "firstcid", f"expected only first CID on stdout; got {res.stdout!r}"


# -- ensure_workspace_folder: docker exec test -d ----------------------------


def test_ensure_workspace_folder_missing_path_fails_loud(tmp_path):
    """Plan: '<ws> does not exist inside the container → exit nonzero,
    stderr names the missing path.' Fake docker:
      - `ps` returns a CID (so container_id_for upstream succeeds)
      - `exec ... test -d` exits 1 (path missing)"""
    body = textwrap.dedent("""\
        case "$1" in
          ps)   echo "cid123" ;;
          exec) exit 1 ;;
        esac
    """)
    fake = _make_fake_docker(tmp_path, body)
    sub = tmp_path / "slug-here"
    sub.mkdir()
    missing = "/workspaces/__definitely_not_there__"
    res = _source_call(
        f'ensure_workspace_folder "{missing}"',
        cwd=str(sub),
        env={"MENTAT_DOCKER": str(fake)},
    )
    assert res.returncode != 0, f"helper must fail when ws missing in container; rc=0 stderr={res.stderr!r}"
    assert missing in res.stderr, f"stderr must name the exact missing path; got {res.stderr!r}"


def test_ensure_workspace_folder_existing_path_succeeds(tmp_path):
    """Healthy path: container has the dir → helper exits 0."""
    body = textwrap.dedent("""\
        case "$1" in
          ps)   echo "cid123" ;;
          exec) exit 0 ;;
        esac
    """)
    fake = _make_fake_docker(tmp_path, body)
    sub = tmp_path / "slug-here"
    sub.mkdir()
    res = _source_call(
        'ensure_workspace_folder "/workspaces/mentat"',
        cwd=str(sub),
        env={"MENTAT_DOCKER": str(fake)},
    )
    assert res.returncode == 0, f"helper must succeed when ws present; stderr={res.stderr!r}"


def test_ensure_workspace_folder_no_container_fails_loud(tmp_path):
    """If `container_id_for` upstream fails (no container), helper must
    fail loud — don't silently call `docker exec ""`."""
    body = "exit 0"  # ps prints nothing → no CID
    fake = _make_fake_docker(tmp_path, body)
    sub = tmp_path / "orphan-slug"
    sub.mkdir()
    res = _source_call(
        'ensure_workspace_folder "/workspaces/x"',
        cwd=str(sub),
        env={"MENTAT_DOCKER": str(fake)},
    )
    assert res.returncode != 0
    assert res.stderr.strip(), f"must speak when no container; stderr={res.stderr!r}"


# -- assert_safe_directory: git config inspection ----------------------------


def test_assert_safe_directory_missing_entry_fails_loud(tmp_path):
    """Plan: 'safe.directory is unset or does not include <ws> → exit
    nonzero, stderr names <ws>.' Fake docker returns a different set
    of safe.directory entries (none matching the requested path)."""
    body = textwrap.dedent("""\
        case "$1" in
          ps)   echo "cid123" ;;
          exec)
            # Forward to the inner command — for `git config ... --get-all safe.directory`
            # echo lines that do NOT include the requested ws.
            echo "/some/other/path"
            echo "/yet/another"
            ;;
        esac
    """)
    fake = _make_fake_docker(tmp_path, body)
    sub = tmp_path / "slug-here"
    sub.mkdir()
    missing_ws = "/workspaces/__not_in_safedir__"
    res = _source_call(
        f'assert_safe_directory "{missing_ws}"',
        cwd=str(sub),
        env={"MENTAT_DOCKER": str(fake)},
    )
    assert res.returncode != 0, f"helper must fail when ws not in safe.directory; rc=0 stderr={res.stderr!r}"
    assert missing_ws in res.stderr, f"stderr must name {missing_ws!r}; got {res.stderr!r}"


def test_assert_safe_directory_present_entry_succeeds(tmp_path):
    """When safe.directory contains the requested path → exit 0."""
    seed = "/workspaces/seeded"
    body = textwrap.dedent(f'''\
        case "$1" in
          ps)   echo "cid123" ;;
          exec)
            echo "/some/other"
            echo "{seed}"
            ;;
        esac
    ''')
    fake = _make_fake_docker(tmp_path, body)
    sub = tmp_path / "slug-here"
    sub.mkdir()
    res = _source_call(
        f'assert_safe_directory "{seed}"',
        cwd=str(sub),
        env={"MENTAT_DOCKER": str(fake)},
    )
    assert res.returncode == 0, f"helper must succeed when entry present; stderr={res.stderr!r}"


def test_assert_safe_directory_exact_match_not_prefix(tmp_path):
    """`grep -Fxq` is the locked match: full-line, fixed-string. Path
    `/foo` must NOT match an entry `/foobar` — prefix matches are bugs."""
    body = textwrap.dedent("""\
        case "$1" in
          ps)   echo "cid123" ;;
          exec) echo "/foobar/extra" ;;
        esac
    """)
    fake = _make_fake_docker(tmp_path, body)
    sub = tmp_path / "slug-here"
    sub.mkdir()
    res = _source_call(
        'assert_safe_directory "/foo"',
        cwd=str(sub),
        env={"MENTAT_DOCKER": str(fake)},
    )
    assert res.returncode != 0, "prefix /foo must NOT match /foobar/extra; got rc=0 (bug)"


# -- synthesize_compose_if_absent --------------------------------------------


def test_synthesize_compose_if_absent_fails_when_nothing_present(tmp_path):
    """Plan: 'worktree has no compose file and no Dockerfile → exit 1,
    stderr names the worktree.'"""
    res = _source_call("synthesize_compose_if_absent", cwd=str(tmp_path))
    assert res.returncode != 0, f"helper must fail in empty dir; rc=0 stderr={res.stderr!r}"
    assert str(tmp_path) in res.stderr or "compose" in res.stderr.lower(), (
        f"stderr must mention worktree path or compose context; got {res.stderr!r}"
    )


def test_synthesize_compose_if_absent_noop_when_devcontainer_exists(tmp_path):
    """If `.devcontainer/devcontainer.json` already exists, helper is a
    no-op and exits 0 — that's the 'absent' guard."""
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer" / "devcontainer.json").write_text('{"name":"t","workspaceFolder":"/workspaces/t"}')
    res = _source_call("synthesize_compose_if_absent", cwd=str(tmp_path))
    assert res.returncode == 0, f"helper must no-op when devcontainer.json exists; stderr={res.stderr!r}"


# -- No silent fallback discipline -------------------------------------------


def test_failing_helpers_speak_on_stderr(tmp_path):
    """Design doc: 'No silent fallback — every failure mode is loud.'
    Each fail-capable helper writes to stderr on its failure path.
    Exception per design doc: container_id_for is silent on miss (caller
    decides fatality). Every other helper must speak."""
    body = "exit 0"  # docker returns nothing — provokes failures.
    fake = _make_fake_docker(tmp_path, body)
    sub = tmp_path / "slug-here"
    sub.mkdir()
    env = {"MENTAT_DOCKER": str(fake)}

    must_speak = [
        ('ensure_workspace_folder "/x"', sub),
        ('assert_safe_directory "/x"', sub),
        ("synthesize_compose_if_absent", tmp_path),
    ]
    for call, cwd in must_speak:
        res = _source_call(call, cwd=str(cwd), env=env)
        assert res.returncode != 0, f"{call!r} should fail but rc=0"
        assert res.stderr.strip(), f"{call!r} failed silently — stderr empty; violates 'no silent fallback'"


# -- Drift guard against design doc ------------------------------------------


def test_lib_implements_every_helper_in_design_doc():
    """If S1 design doc lists a helper, S2 lib must define it. Drift
    guard between the two slices."""
    if not DESIGN_DOC.is_file():
        pytest.skip("design doc missing; S1 not done")
    doc = DESIGN_DOC.read_text()
    doc_helpers = [h for h in HELPERS if h in doc]
    res = _source_call("declare -F | awk '{print $3}'")
    defined = set(res.stdout.split())
    missing = [h for h in doc_helpers if h not in defined]
    assert not missing, f"design doc lists {missing} but lib does not define them"
