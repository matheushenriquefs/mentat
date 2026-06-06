"""P3: devcontainer script hardening — static assertions (no container needed)."""
import os
import re
import stat
import subprocess

BIN = os.path.join(os.path.dirname(__file__), "..", "..", "bin")


def _read(name: str) -> str:
    with open(os.path.join(BIN, name)) as f:
        return f.read()


# S3.1 / S3.2 — no host language toolchain in mentat-container-up or mentat-container-run

def test_devcontainer_up_no_python3():
    src = _read("mentat-container-up")
    non_comment = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "python3" not in non_comment

def test_devcontainer_up_no_asdf_mise():
    src = _read("mentat-container-up")
    non_comment = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "asdf" not in non_comment
    assert "mise" not in non_comment

def test_devcontainer_run_no_python3():
    src = _read("mentat-container-run")
    non_comment = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "python3" not in non_comment

def test_devcontainer_run_no_asdf_mise():
    src = _read("mentat-container-run")
    non_comment = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "asdf" not in non_comment
    assert "mise" not in non_comment


# S3.2 — exit 99 when container is not running (no auto-start)

def test_devcontainer_run_exits_99_when_container_down(tmp_path):
    # Synthesize a fake worktree .git file pointing nowhere — docker will find no container.
    wt = tmp_path / "fake-wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: /nonexistent/.git/worktrees/fake-wt\n")
    result = subprocess.run(
        [os.path.join(BIN, "mentat-container-run"), "true"],
        cwd=str(wt),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 99

def test_devcontainer_run_contains_exit_99():
    src = _read("mentat-container-run")
    assert "exit 99" in src


# S3.3 — mentat-orchestrate: no raw bash/sh/exec -c outside mentat-container-run

def test_to_orchestrate_no_raw_host_shells():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        src = f.read()
    raw_shell_re = re.compile(r'(?:^|\s)(?:bash|sh|exec)\s+-c', re.MULTILINE)
    for line in src.splitlines():
        if raw_shell_re.search(line) and "mentat-container-run" not in line:
            raise AssertionError(f"raw host shell found outside mentat-container-run: {line!r}")


# S3.4 — mentat-container-doctor exists, is executable, checks correct tools

def test_devcontainer_doctor_exists():
    path = os.path.join(BIN, "mentat-container-doctor")
    assert os.path.isfile(path)

def test_devcontainer_doctor_is_executable():
    path = os.path.join(BIN, "mentat-container-doctor")
    assert os.access(path, os.X_OK)

def test_devcontainer_doctor_checks_git():
    src = _read("mentat-container-doctor")
    assert "git" in src

def test_devcontainer_doctor_checks_jq():
    src = _read("mentat-container-doctor")
    assert "jq" in src

def test_devcontainer_doctor_checks_docker_socket():
    src = _read("mentat-container-doctor")
    assert "docker.sock" in src or "docker socket" in src.lower()

def test_devcontainer_doctor_no_language_toolchain_checks():
    src = _read("mentat-container-doctor")
    non_comment = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    for tool in ("python3", "node", "uv", "npm", "ruby", "cargo"):
        assert tool not in non_comment, f"mentat-container-doctor checks language toolchain: {tool!r}"
    # "pip" / "go" need word boundaries to avoid matching "pipefail" / "go " in flags
    assert not re.search(r'\bpip\b', non_comment), "mentat-container-doctor checks pip"
    assert not re.search(r'\bgo\b', non_comment), "mentat-container-doctor checks go"
