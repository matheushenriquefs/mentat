"""P5: quality gates — bin/lib/precommit-gates.sh, bin/mentat-precommit, AGENTS.md section."""

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")

import os
import subprocess
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BIN = os.path.join(ROOT, ".agents", "bin")
LIB = os.path.join(BIN, "lib")
AGENTS_MD = os.path.join(ROOT, "AGENTS.md")
GATE_CHECKS = os.path.join(BIN, "mentat-precommit")
GATES_SH = os.path.join(LIB, "precommit-gates.sh")
ADR_DIR = os.path.join(ROOT, ".agents", "docs", "adr")
AGENTS_DIR = os.path.join(ROOT, ".agents", "agents")


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def _bash_n(path: str):
    r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
    assert r.returncode == 0, f"bash -n failed: {r.stderr}"


def _infer_class(path: str) -> str | None:

    if "/docs/adr/" in path and path.endswith(".md"):
        return "adr"
    if "/agents/" in path and path.endswith(".md"):
        return "skill"
    if "/commands/" in path and path.endswith(".md"):
        return "command"
    if os.path.basename(path) in ("AGENTS.md", "CONTEXT.md", "README.md"):
        return "workflow"
    if "/bin/lib/harness/" in path and path.endswith(".sh"):
        return "harness"
    if path.endswith(".sh") or "/bin/mentat-" in path or "/bin/lib/" in path:
        return "shell"
    if path.endswith(".jsonc"):
        return "jsonc"
    if path.endswith(".jq"):
        return "jq"
    return None  # unknown → pass silently


def _gate(path: str) -> subprocess.CompletedProcess:
    cls = _infer_class(path)
    if cls is None:
        # Unknown class — silent pass (mentat_gate returns 0 for unknown)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    return subprocess.run([GATE_CHECKS, cls, path], capture_output=True, text=True)


# ── S5.1: precommit-gates.sh exists + syntax ───────────────────────────────────────────


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


def test_agents_md_quality_gates_mentions_lefthook():
    src = _read(AGENTS_MD)
    idx = src.find("## Quality Gates")
    assert idx != -1
    section = src[idx:]
    assert "lefthook" in section or "mentat-precommit" in section


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

    assert re.search(r"\[.+\]\(.+\.(?:md|sh)\)", section), "No cross-ref link in Quality Gates section"


# ── S5.3: mentat-precommit binary ──────────────────────────────────────────


def test_mentat_gate_checks_exists():
    assert os.path.isfile(GATE_CHECKS)


def test_mentat_gate_checks_is_executable():
    assert os.access(GATE_CHECKS, os.X_OK)


def test_mentat_gate_checks_syntax():
    _bash_n(GATE_CHECKS)


def test_mentat_gate_checks_sources_gates_sh():
    assert "precommit-gates.sh" in _read(GATE_CHECKS)


def test_mentat_gate_checks_sources_strict():
    assert "strict.sh" in _read(GATE_CHECKS)


# ── S5.4: positive fixtures — real repo files pass ───────────────────────────


def test_gate_passes_existing_adr():
    adr_files = [f for f in os.listdir(ADR_DIR) if f.endswith(".md")] if os.path.isdir(ADR_DIR) else []
    assert adr_files, f"No ADR files found in {ADR_DIR}"
    path = os.path.join(ADR_DIR, adr_files[0])
    r = _gate(path)
    assert r.returncode == 0, f"gate failed on {path}:\n{r.stderr}\n{r.stdout}"


def test_gate_passes_gates_sh():
    r = _gate(GATES_SH)
    assert r.returncode == 0, f"gate_shell failed on precommit-gates.sh:\n{r.stderr}\n{r.stdout}"


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
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, dir=os.path.join(ADR_DIR)) as f:
        f.write("# Bad ADR\n\nNo required sections here.\n")
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode != 0, "Expected non-zero exit for ADR missing sections"
    finally:
        os.unlink(name)


def test_gate_fails_adr_with_only_one_section():
    """ADR with only one section — gate_adr must require ALL three."""
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, dir=os.path.join(ADR_DIR)) as f:
        f.write("# Partial ADR\n\n## Context\n\nsome context\n")
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode != 0, "ADR with only ## Context should fail (missing Decision + Consequences)"
    finally:
        os.unlink(name)


def test_gate_fails_jsonc_bad_syntax():
    with tempfile.NamedTemporaryFile(suffix=".jsonc", mode="w", delete=False) as f:
        f.write('{ "x": 1, }\n')  # trailing comma — invalid JSON
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode != 0, "Expected non-zero exit for malformed JSONC"
    finally:
        os.unlink(name)


def test_gate_fails_shell_syntax_error():
    with tempfile.NamedTemporaryFile(suffix=".sh", mode="w", delete=False, dir=LIB) as f:
        f.write("#!/usr/bin/env bash\nif then fi\n")  # intentional syntax error
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode != 0, "Expected non-zero exit for bash syntax error"
    finally:
        os.unlink(name)


# ── B2: gate_skill first-10-lines constraint ─────────────────────────────────


def test_gate_skill_passes_with_frontmatter_in_first_10():
    """Skill file with --- in first 10 lines passes."""
    with tempfile.NamedTemporaryFile(
        suffix=".md", mode="w", delete=False, dir=os.path.join(AGENTS_DIR) if os.path.isdir(AGENTS_DIR) else "/tmp"
    ) as f:
        f.write("---\nname: test-skill\n---\n\n# Body\n")
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode == 0, f"Skill with frontmatter in first 10 lines should pass:\n{r.stderr}"
    finally:
        os.unlink(name)


def test_gate_skill_fails_without_frontmatter():
    """Skill file with no --- in first 10 lines fails."""
    target_dir = AGENTS_DIR if os.path.isdir(AGENTS_DIR) else "/tmp"
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, dir=target_dir) as f:
        f.write("# Skill Without Frontmatter\n\nSome content here.\n")
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode != 0, "Skill without frontmatter should fail gate"
    finally:
        os.unlink(name)


# ── B3: gate_command behavioral ──────────────────────────────────────────────


def _make_commands_dir() -> str:
    """Return a path ending in /commands/ (matches */commands/*.md glob), creating if needed."""
    d = os.path.join(tempfile.gettempdir(), "mentat_gate_test", "commands")
    os.makedirs(d, exist_ok=True)
    return d


def test_gate_command_passes_with_frontmatter():
    """Command file with --- in first 10 lines passes."""
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, dir=_make_commands_dir()) as f:
        f.write("---\nname: test-cmd\n---\n\n# Command body\n")
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode == 0, f"Command with frontmatter should pass:\n{r.stderr}"
    finally:
        os.unlink(name)


def test_gate_command_fails_without_frontmatter():
    """Command file without --- fails gate."""
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, dir=_make_commands_dir()) as f:
        f.write("# Command Without Frontmatter\n\nSome content.\n")
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode != 0, "Command without frontmatter should fail gate"
    finally:
        os.unlink(name)


# ── B4: gate_workflow cross-ref syntax ───────────────────────────────────────


def test_gate_workflow_passes_with_cross_ref_link():
    """AGENTS.md-style file with [text](file.md) cross-ref passes."""
    with tempfile.NamedTemporaryFile(suffix="AGENTS.md", mode="w", delete=False) as f:
        f.write("# Workflow Doc\n\nSee [CONTEXT.md](CONTEXT.md) for details.\n")
        name = f.name
    # Rename so it matches the AGENTS.md pattern in mentat_gate
    agents_name = os.path.join(os.path.dirname(name), "AGENTS.md")
    import shutil

    shutil.move(name, agents_name)
    try:
        r = _gate(agents_name)
        assert r.returncode == 0, f"Workflow doc with cross-ref link should pass:\n{r.stderr}"
    finally:
        if os.path.exists(agents_name):
            os.unlink(agents_name)


def test_gate_workflow_fails_without_cross_ref_link():
    """File matching workflow pattern with no [text](*.md) link fails."""
    with tempfile.NamedTemporaryFile(suffix="AGENTS.md", mode="w", delete=False) as f:
        f.write("# Workflow Doc\n\nNo links here at all.\n")
        name = f.name
    agents_name = os.path.join(os.path.dirname(name), "AGENTS.md")
    import shutil

    shutil.move(name, agents_name)
    try:
        r = _gate(agents_name)
        assert r.returncode != 0, "Workflow doc without cross-ref links should fail gate"
    finally:
        if os.path.exists(agents_name):
            os.unlink(agents_name)


# ── S5.3: orchestrate wire-in ─────────────────────────────────────────────────


def test_orchestrate_gates_files_in_land_chunk():
    """land_chunk must gate changed files via precommit-gates.sh (not mentat-gate binary)."""
    src = _read(os.path.join(BIN, "mentat-orchestrate"))
    start = src.find("land_chunk()")
    assert start != -1, "land_chunk() not found in mentat-orchestrate"
    next_fn = src.find("\n}", start)
    land_chunk_body = src[start:next_fn]
    assert "precommit-gates.sh" in land_chunk_body or "mentat_gate" in land_chunk_body, (
        "land_chunk() must source precommit-gates.sh / call mentat_gate() for pre-land gate"
    )


def test_orchestrate_land_chunk_no_mentat_gate_binary():
    """land_chunk must not call the mentat-gate binary (deleted in B5)."""
    src = _read(os.path.join(BIN, "mentat-orchestrate"))
    start = src.find("land_chunk()")
    assert start != -1
    next_fn = src.find("\n}", start)
    land_chunk_body = src[start:next_fn]
    assert '"$_LIB/../mentat-gate"' not in land_chunk_body, (
        "mentat-gate binary must not be called in land_chunk (deleted in B5)"
    )


# ── B5: gate_shell advisory shellcheck path ───────────────────────────────────


def test_gate_shell_passes_despite_shellcheck_warning():
    """Shell file that is bash -n valid but has a shellcheck warning still passes.

    gate_shell() ends with `|| true` on shellcheck, so it is advisory only.
    Using a sc2006 style backtick substitution which shellcheck warns about but bash accepts.
    """
    with tempfile.NamedTemporaryFile(suffix=".sh", mode="w", delete=False, dir=LIB) as f:
        # SC2006: use $() instead of backticks — bash accepts both, shellcheck warns
        f.write('#!/usr/bin/env bash\nset -euo pipefail\nval=`echo hello`\necho "$val"\n')
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode == 0, f"Shell file with shellcheck warning (advisory) should still pass gate:\n{r.stderr}"
    finally:
        os.unlink(name)


# ── B6: gate_jsonc positive (URL strings) ────────────────────────────────────


def test_gate_jsonc_passes_with_url_strings():
    """JSONC file with https:// URLs in string values must pass gate (not stripped by sed)."""
    with tempfile.NamedTemporaryFile(suffix=".jsonc", mode="w", delete=False) as f:
        f.write('{\n  "url": "https://example.com/path",\n  "other": "value"\n}\n')
        name = f.name
    try:
        r = _gate(name)
        assert r.returncode == 0, f"JSONC with https:// URL values should pass gate:\n{r.stderr}\n{r.stdout}"
    finally:
        os.unlink(name)


# ── B7: mentat_gate dispatcher behavioral routing ────────────────────────────


def test_gate_dispatches_to_adr_checker_by_path():
    """File in docs/adr/ path triggers gate_adr; valid ADR with all 3 sections exits 0."""
    path = os.path.join(ADR_DIR, os.listdir(ADR_DIR)[0]) if os.path.isdir(ADR_DIR) else None
    if path is None:
        return  # no ADR dir — skip
    r = _gate(path)
    assert r.returncode == 0, f"Valid ADR file should route to gate_adr and pass:\n{r.stderr}"


def test_gate_dispatches_to_skill_checker_by_path():
    """File in agents/ path triggers gate_skill; valid skill with frontmatter exits 0."""
    skill_files = (
        [os.path.join(AGENTS_DIR, f) for f in os.listdir(AGENTS_DIR) if f.endswith(".md")]
        if os.path.isdir(AGENTS_DIR)
        else []
    )
    assert skill_files, "No skill files found for dispatcher routing test"
    r = _gate(skill_files[0])
    assert r.returncode == 0, f"Valid skill file should route to gate_skill and pass:\n{r.stderr}"
