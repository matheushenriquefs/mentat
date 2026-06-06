"""P5: quality gates — bin/lib/gates.sh, bin/mentat-gate, AGENTS.md section."""
import os
import stat
import subprocess
import tempfile

BIN = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
LIB = os.path.join(BIN, "lib")
AGENTS_MD = os.path.join(os.path.dirname(__file__), "..", "..", "AGENTS.md")
MENTAT_GATE = os.path.join(BIN, "mentat-gate")
GATES_SH = os.path.join(LIB, "gates.sh")
ADR_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "adr")
AGENTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "agents")


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def _bash_n(path: str):
    r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
    assert r.returncode == 0, f"bash -n failed: {r.stderr}"


def _gate(path: str) -> subprocess.CompletedProcess:
    return subprocess.run([MENTAT_GATE, path], capture_output=True, text=True)


# ── S5.1: gates.sh exists + syntax ───────────────────────────────────────────

def test_gates_sh_exists():
    assert os.path.isfile(GATES_SH)


def test_gates_sh_syntax():
    _bash_n(GATES_SH)


def test_gates_sh_has_gate_adr():
    assert "gate_adr()" in _read(GATES_SH)


def test_gates_sh_has_gate_skill():
    assert "gate_skill()" in _read(GATES_SH)


def test_gates_sh_has_gate_command():
    assert "gate_command()" in _read(GATES_SH)


def test_gates_sh_has_gate_workflow():
    assert "gate_workflow()" in _read(GATES_SH)


def test_gates_sh_has_gate_shell():
    assert "gate_shell()" in _read(GATES_SH)


def test_gates_sh_has_gate_jsonc():
    assert "gate_jsonc()" in _read(GATES_SH)


def test_gates_sh_has_mentat_gate_dispatcher():
    assert "mentat_gate()" in _read(GATES_SH)


def test_gate_adr_uses_three_greps():
    """gate_adr must check ALL three sections — not BRE alternation (any-one match)."""
    src = _read(GATES_SH)
    assert src.count("## Context") >= 1
    assert src.count("## Decision") >= 1
    assert src.count("## Consequences") >= 1


# ── S5.2: AGENTS.md Quality Gates section ────────────────────────────────────

def test_agents_md_has_quality_gates_section():
    assert "## Quality Gates" in _read(AGENTS_MD)


def test_agents_md_quality_gates_mentions_mentat_gate():
    src = _read(AGENTS_MD)
    idx = src.find("## Quality Gates")
    assert idx != -1
    section = src[idx:]
    assert "mentat-gate" in section


def test_agents_md_quality_gates_has_table():
    src = _read(AGENTS_MD)
    idx = src.find("## Quality Gates")
    assert idx != -1
    section = src[idx:]
    assert "| ADR" in section or "|ADR" in section


def test_agents_md_quality_gates_cross_ref_links():
    """Section itself must contain a cross-ref link (gate_workflow passes on AGENTS.md)."""
    src = _read(AGENTS_MD)
    idx = src.find("## Quality Gates")
    assert idx != -1
    section = src[idx:]
    import re
    assert re.search(r'\[.+\]\(.+\.(?:md|sh)\)', section), "No cross-ref link in Quality Gates section"


# ── S5.3: mentat-gate binary ─────────────────────────────────────────────────

def test_mentat_gate_exists():
    assert os.path.isfile(MENTAT_GATE)


def test_mentat_gate_is_executable():
    assert os.access(MENTAT_GATE, os.X_OK)


def test_mentat_gate_syntax():
    _bash_n(MENTAT_GATE)


def test_mentat_gate_sources_gates_sh():
    assert "gates.sh" in _read(MENTAT_GATE)


def test_mentat_gate_sources_strict():
    assert "strict.sh" in _read(MENTAT_GATE)


# ── S5.4: positive fixtures — real repo files pass ───────────────────────────

def test_gate_passes_existing_adr():
    adr_files = [f for f in os.listdir(ADR_DIR) if f.endswith(".md")] if os.path.isdir(ADR_DIR) else []
    assert adr_files, f"No ADR files found in {ADR_DIR}"
    path = os.path.join(ADR_DIR, adr_files[0])
    r = _gate(path)
    assert r.returncode == 0, f"gate failed on {path}:\n{r.stderr}\n{r.stdout}"


def test_gate_passes_gates_sh():
    r = _gate(GATES_SH)
    assert r.returncode == 0, f"gate_shell failed on gates.sh:\n{r.stderr}\n{r.stdout}"


def test_gate_passes_mentat_gate():
    r = _gate(MENTAT_GATE)
    assert r.returncode == 0, f"gate_shell failed on mentat-gate:\n{r.stderr}\n{r.stdout}"


def test_gate_passes_unknown_extension():
    """Unknown file class — silent pass, exit 0."""
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
        f.write("some content\n")
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode == 0, f"Unknown file should exit 0:\n{r.stderr}"
    finally:
        os.unlink(name)


# ── S5.4: negative fixtures — bad files fail ─────────────────────────────────

def test_gate_fails_adr_missing_sections():
    """ADR without required sections → exit 1."""
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False,
                                     dir=os.path.join(ADR_DIR)) as f:
        f.write("# Bad ADR\n\nNo required sections here.\n")
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode != 0, "Expected non-zero exit for ADR missing sections"
    finally:
        os.unlink(name)


def test_gate_fails_adr_with_only_one_section():
    """ADR with only one section — gate_adr must require ALL three."""
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False,
                                     dir=os.path.join(ADR_DIR)) as f:
        f.write("# Partial ADR\n\n## Context\n\nsome context\n")
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode != 0, "ADR with only ## Context should fail (missing Decision + Consequences)"
    finally:
        os.unlink(name)


def test_gate_fails_jsonc_bad_syntax():
    with tempfile.NamedTemporaryFile(suffix=".jsonc", mode="w", delete=False) as f:
        f.write('{ "x": 1, }\n')   # trailing comma — invalid JSON
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode != 0, "Expected non-zero exit for malformed JSONC"
    finally:
        os.unlink(name)


def test_gate_fails_shell_syntax_error():
    with tempfile.NamedTemporaryFile(suffix=".sh", mode="w", delete=False,
                                     dir=LIB) as f:
        f.write("#!/usr/bin/env bash\nif then fi\n")   # intentional syntax error
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode != 0, "Expected non-zero exit for bash syntax error"
    finally:
        os.unlink(name)


# ── S5.3: orchestrate wire-in ─────────────────────────────────────────────────

def test_orchestrate_references_mentat_gate():
    """mentat-orchestrate must call mentat-gate as pre-land step."""
    src = _read(os.path.join(BIN, "mentat-orchestrate"))
    assert "mentat-gate" in src or "mentat_gate" in src
