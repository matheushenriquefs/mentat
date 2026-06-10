"""P1: lib/ skeleton + comment hygiene — static assertions."""

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")

import os
import subprocess

BIN = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
LIB = os.path.join(BIN, "lib")
AGENTS_MD = os.path.join(os.path.dirname(__file__), "..", "..", "AGENTS.md")


def _read_bin(name: str) -> str:
    with open(os.path.join(BIN, name)) as f:
        return f.read()


def _read_lib(name: str) -> str:
    with open(os.path.join(LIB, name)) as f:
        return f.read()


def _linecount(path: str) -> int:
    with open(path) as f:
        return sum(1 for _ in f)


# S1.1 — lib/strict.sh


def test_strict_sh_exists():
    assert os.path.isfile(os.path.join(LIB, "strict.sh"))


def test_strict_sh_uses_Eeuo():
    assert "set -Eeuo pipefail" in _read_lib("strict.sh")


def test_strict_sh_has_err_trap():
    assert "trap" in _read_lib("strict.sh") and "ERR" in _read_lib("strict.sh")


def test_strict_sh_lte_30_lines():
    assert _linecount(os.path.join(LIB, "strict.sh")) <= 30


# S1.1 — lib/log.sh


def test_log_sh_exists():
    assert os.path.isfile(os.path.join(LIB, "log.sh"))


def test_log_sh_has_log_warn_die():
    src = _read_lib("log.sh")
    assert "log()" in src
    assert "warn()" in src
    assert "die()" in src


def test_log_sh_lte_30_lines():
    assert _linecount(os.path.join(LIB, "log.sh")) <= 30


# S1.1 — lib/here.sh


def test_here_sh_exists():
    assert os.path.isfile(os.path.join(LIB, "here.sh"))


def test_here_sh_uses_BASH_SOURCE():
    """here.sh must resolve path via BASH_SOURCE (not hardcoded)."""
    assert "BASH_SOURCE" in _read_lib("here.sh")


def test_here_sh_sets_HERE():
    assert "HERE=" in _read_lib("here.sh")


def test_here_sh_lte_30_lines():
    assert _linecount(os.path.join(LIB, "here.sh")) <= 30


# S1.2 — AGENTS.md Comment Hygiene section


def test_agents_md_has_comment_hygiene_section():
    with open(AGENTS_MD) as f:
        src = f.read()
    assert "## Comment Hygiene" in src


def test_agents_md_comment_hygiene_rules():
    """Five required rules from the plan must be present."""
    with open(AGENTS_MD) as f:
        src = f.read()
    # why-not-what
    assert "why" in src and "what" in src
    # no commented-out code
    assert "commented-out" in src or "commented out" in src
    # no TODO
    assert "TODO" in src
    # docstring / public entry points only
    assert "public" in src or "entry point" in src
    # no duplicate comment blocks
    assert "duplicate" in src


# S1.3 — mentat-orchestrate sources all three lib/ files


def test_to_orchestrate_sources_strict():
    assert "strict.sh" in _read_bin("mentat-orchestrate")


def test_to_orchestrate_sources_log():
    assert "log.sh" in _read_bin("mentat-orchestrate")


def test_to_orchestrate_sources_here():
    assert "here.sh" in _read_bin("mentat-orchestrate")


def test_to_orchestrate_zero_behavior_change():
    """Key behavioral landmarks must survive the refactor (zero-behavior-change)."""
    src = _read_bin("mentat-orchestrate")
    # flag parsing still present
    assert "--harness=" in src
    assert "--model=" in src
    # core functions still present
    assert "land_chunk()" in src or "land_chunk" in src
    assert "_land_record()" in src or "_land_record" in src
    assert "run_chunk()" in src or "run_chunk" in src
    assert "final_review()" in src or "final_review" in src
    # land outcomes still recorded
    assert '"landed":true' in src or "landed" in src
    assert "rebase-conflict" in src
    assert "gate-fail" in src


def test_to_orchestrate_google_header_lte_6_lines():
    """Leading # block after shebang must be ≤6 lines (Google Shell Style)."""
    lines = _read_bin("mentat-orchestrate").splitlines()
    # skip shebang
    header = [l for l in lines[1:] if l.startswith("#")]
    # count consecutive comment lines from the top (before first non-comment)
    block = 0
    for l in lines[1:]:
        if l.startswith("#"):
            block += 1
        else:
            break
    assert block <= 6, f"Header block is {block} lines, expected ≤6"


def test_to_orchestrate_comment_lt_30():
    src = _read_bin("mentat-orchestrate")
    comment_lines = [l for l in src.splitlines() if l.startswith("#")]
    assert len(comment_lines) < 30


def test_to_orchestrate_lte_200_lines():
    assert _linecount(os.path.join(BIN, "mentat-orchestrate")) < 200


# S1.4 — mentat-container-up sources lib/


def test_devcontainer_up_sources_strict():
    assert "strict.sh" in _read_bin("mentat-container-up")


def test_devcontainer_up_sources_compose_render():
    assert "compose_render" in _read_bin("mentat-container-up")


def test_compose_render_exists():
    scripts = os.path.join(os.path.dirname(__file__), "..", "..", ".agents", "skills", "mentat-container", "scripts")
    assert os.path.isfile(os.path.join(scripts, "compose_render.py"))


def test_compose_render_has_synth_function():
    scripts = os.path.join(os.path.dirname(__file__), "..", "..", ".agents", "skills", "mentat-container", "scripts")
    src = open(os.path.join(scripts, "compose_render.py")).read()
    assert "def synth(" in src


def test_devcontainer_up_lte_150_lines():
    """Plan target: ~150 lines (from 242)."""
    assert _linecount(os.path.join(BIN, "mentat-container-up")) <= 150


def _google_header_lines(name: str) -> int:
    """Count consecutive leading # lines after the shebang."""
    lines = _read_bin(name).splitlines()
    count = 0
    for l in lines[1:]:
        if l.startswith("#"):
            count += 1
        else:
            break
    return count


def _comment_count(name: str) -> int:
    return sum(1 for l in _read_bin(name).splitlines() if l.startswith("#"))


# S1.5 — mentat-container-run, mentat-container-doctor, mentat-track source lib/


def test_devcontainer_run_sources_strict():
    assert "strict.sh" in _read_bin("mentat-container-run")


def test_devcontainer_run_google_header():
    assert _google_header_lines("mentat-container-run") >= 1, "Missing Google header"
    assert _google_header_lines("mentat-container-run") <= 6, "Header too long (>6 lines)"


def test_devcontainer_run_comment_count():
    assert _comment_count("mentat-container-run") < 15


def test_devcontainer_doctor_sources_strict():
    assert "strict.sh" in _read_bin("mentat-container-doctor")


def test_devcontainer_doctor_google_header():
    assert _google_header_lines("mentat-container-doctor") >= 1
    assert _google_header_lines("mentat-container-doctor") <= 6


def test_devcontainer_doctor_comment_count():
    assert _comment_count("mentat-container-doctor") < 15


def test_to_track_harness_sources_strict():
    assert "strict.sh" in _read_bin("mentat-track")


def test_to_track_harness_google_header():
    assert _google_header_lines("mentat-track") >= 1
    assert _google_header_lines("mentat-track") <= 6


def test_to_track_harness_comment_count():
    assert _comment_count("mentat-track") < 15


# S1.6 — bash -n syntax check on all bin/ and bin/lib/*.sh


def _bash_n(path: str):
    result = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
    assert result.returncode == 0, f"bash -n failed on {path}:\n{result.stderr}"


def test_syntax_devcontainer_doctor():
    _bash_n(os.path.join(BIN, "mentat-container-doctor"))


def test_syntax_devcontainer_run():
    _bash_n(os.path.join(BIN, "mentat-container-run"))


def test_syntax_devcontainer_up():
    _bash_n(os.path.join(BIN, "mentat-container-up"))


def test_syntax_to_orchestrate():
    _bash_n(os.path.join(BIN, "mentat-orchestrate"))


def test_syntax_to_track_harness():
    _bash_n(os.path.join(BIN, "mentat-track"))


def test_syntax_lib_strict():
    _bash_n(os.path.join(LIB, "strict.sh"))


def test_syntax_lib_log():
    _bash_n(os.path.join(LIB, "log.sh"))


def test_syntax_lib_here():
    _bash_n(os.path.join(LIB, "here.sh"))


def test_syntax_lib_compose_render():
    scripts = os.path.join(os.path.dirname(__file__), "..", "..", ".agents", "skills", "mentat-container", "scripts")
    result = subprocess.run(
        ["python3", "-m", "py_compile", os.path.join(scripts, "compose_render.py")], capture_output=True
    )
    assert result.returncode == 0


# S1.6 — no TODO/XXX/FIXME in bin/


def test_no_todo_in_bin():
    for root, _dirs, files in os.walk(BIN):
        for fname in files:
            fpath = os.path.join(root, fname)
            with open(fpath, errors="replace") as f:
                content = f.read()
            for marker in ("TODO", "XXX", "FIXME"):
                assert marker not in content, f"{marker} found in {fpath}"
