"""P6: mentat-release safety (B1-B2) + jq gate (B3) + lefthook migration (B4)."""
import os
import subprocess
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENTS = os.path.join(ROOT, ".agents")
BIN = os.path.join(AGENTS, "bin")
LIB = os.path.join(BIN, "lib")
MENTAT_RELEASE = os.path.join(BIN, "mentat-release")
MENTAT_GATE = os.path.join(BIN, "mentat-gate")
GATES_SH = os.path.join(LIB, "gates.sh")
GATE_CHECKS = os.path.join(BIN, "mentat-gate-checks")
LEFTHOOK_YML = os.path.join(ROOT, "lefthook.yml")
ORCHESTRATE = os.path.join(BIN, "mentat-orchestrate")


def _sh(cmd, cwd=ROOT, env=None):
    import os as _os
    e = {**_os.environ, **(env or {})}
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, env=e)


def _dry_run_output(extra_env=None):
    with tempfile.TemporaryDirectory() as dest:
        env = {**os.environ, "HOME": dest, **(extra_env or {})}
        r = subprocess.run(
            [MENTAT_RELEASE, "--dry-run"],
            capture_output=True, text=True, cwd=ROOT, env=env,
        )
    return r.stdout + r.stderr


# ── B1: user-state exclude list ──────────────────────────────────────────────

def test_dry_run_excludes_plans_dir():
    out = _dry_run_output()
    assert "plans/" not in out, f"--dry-run must not list plans/ for deletion:\n{out}"


def test_dry_run_excludes_mentat_logs_dir():
    out = _dry_run_output()
    assert "mentat/logs/" not in out and "mentat/logs" not in out, (
        f"--dry-run must not list mentat/logs/ for deletion:\n{out}"
    )


def test_dry_run_excludes_skill_lock():
    out = _dry_run_output()
    assert ".skill-lock.json" not in out, (
        f"--dry-run must not list .skill-lock.json for deletion:\n{out}"
    )


# ── B2: flag semantics ───────────────────────────────────────────────────────

def test_force_flag_unknown():
    """--force (old flag) must be rejected — use --force-dirty or --force-gate."""
    r = subprocess.run([MENTAT_RELEASE, "--force"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode != 0, "--force must be rejected after flag rename"


def test_force_dirty_flag_recognized():
    """--force-dirty must be a recognized flag (not cause usage error on its own)."""
    with tempfile.TemporaryDirectory() as dest:
        env = {**os.environ, "HOME": dest}
        r = subprocess.run(
            [MENTAT_RELEASE, "--force-dirty", "--dry-run"],
            capture_output=True, text=True, cwd=ROOT, env=env,
        )
    assert "usage:" not in r.stderr.lower() or r.returncode == 0, (
        f"--force-dirty should be a recognized flag:\n{r.stderr}"
    )


def test_force_gate_flag_recognized():
    """--force-gate must be a recognized flag (not cause usage error on its own)."""
    with tempfile.TemporaryDirectory() as dest:
        env = {**os.environ, "HOME": dest}
        r = subprocess.run(
            [MENTAT_RELEASE, "--force-gate", "--dry-run"],
            capture_output=True, text=True, cwd=ROOT, env=env,
        )
    assert "usage:" not in r.stderr.lower() or r.returncode == 0, (
        f"--force-gate should be a recognized flag:\n{r.stderr}"
    )


# ── B3: jq gate for .jq files ────────────────────────────────────────────────

def test_jq_file_passes_gate():
    """Valid .jq file must pass mentat-gate-checks jq (routed via jq, not bash -n)."""
    config_jq = os.path.join(LIB, "config-schema.jq")
    r = subprocess.run([GATE_CHECKS, "jq", config_jq], capture_output=True, text=True)
    assert r.returncode == 0, (
        f"config-schema.jq must pass gate (valid jq; gate must not run bash -n on it):\n{r.stderr}"
    )


def test_invalid_jq_file_fails_gate():
    """Invalid .jq file must fail mentat-gate-checks jq."""
    with tempfile.NamedTemporaryFile(suffix=".jq", mode="w", delete=False, dir=LIB) as f:
        f.write("{ this is not valid jq }\n")
        name = f.name
    try:
        r = subprocess.run([GATE_CHECKS, "jq", name], capture_output=True, text=True)
        assert r.returncode != 0, "Invalid .jq file must fail gate"
    finally:
        os.unlink(name)


def test_gates_sh_has_gate_jq():
    """gates.sh must have gate_jq() function for .jq files."""
    with open(GATES_SH) as f:
        src = f.read()
    assert "gate_jq()" in src or "gate_jq ()" in src, (
        "gates.sh must define gate_jq() for .jq file class"
    )


# ── B4: lefthook.yml + mentat-gate-checks ───────────────────────────────────

def test_lefthook_yml_exists():
    assert os.path.isfile(LEFTHOOK_YML), f"lefthook.yml must exist at repo root: {LEFTHOOK_YML}"


def test_lefthook_yml_has_pre_commit():
    with open(LEFTHOOK_YML) as f:
        content = f.read()
    assert "pre-commit:" in content, "lefthook.yml must define pre-commit hook"


def test_lefthook_yml_has_adr_job():
    with open(LEFTHOOK_YML) as f:
        content = f.read()
    assert "adr:" in content, "lefthook.yml must include adr job"


def test_lefthook_yml_has_skill_job():
    with open(LEFTHOOK_YML) as f:
        content = f.read()
    assert "skill:" in content, "lefthook.yml must include skill job"


def test_lefthook_yml_has_shell_job():
    with open(LEFTHOOK_YML) as f:
        content = f.read()
    assert "shell:" in content, "lefthook.yml must include shell job"


def test_mentat_gate_checks_exists():
    assert os.path.isfile(GATE_CHECKS), f"bin/mentat-gate-checks must exist: {GATE_CHECKS}"


def test_mentat_gate_checks_executable():
    assert os.access(GATE_CHECKS, os.X_OK), "bin/mentat-gate-checks must be executable"


def test_mentat_gate_checks_syntax():
    r = subprocess.run(["bash", "-n", GATE_CHECKS], capture_output=True, text=True)
    assert r.returncode == 0, f"bin/mentat-gate-checks must be valid bash:\n{r.stderr}"


def test_mentat_gate_checks_adr_pass():
    """mentat-gate-checks adr <valid-adr> exits 0."""
    adr_dir = os.path.join(AGENTS, "docs", "adr")
    if not os.path.isdir(adr_dir):
        return
    files = [f for f in os.listdir(adr_dir) if f.endswith(".md")]
    if not files:
        return
    adr_path = os.path.join(adr_dir, files[0])
    r = subprocess.run([GATE_CHECKS, "adr", adr_path], capture_output=True, text=True)
    assert r.returncode == 0, f"mentat-gate-checks adr <valid-adr> must pass:\n{r.stderr}"


def test_mentat_gate_checks_adr_fail():
    """mentat-gate-checks adr <invalid-adr> exits non-zero."""
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
        f.write("# Invalid ADR\n\nNo required sections here.\n")
        name = f.name
    try:
        r = subprocess.run([GATE_CHECKS, "adr", name], capture_output=True, text=True)
        assert r.returncode != 0, "mentat-gate-checks adr must fail on ADR missing sections"
    finally:
        os.unlink(name)


# ── B4: orchestrate pre-land gate (gates.sh dispatch, not mentat-gate binary) ─

def test_orchestrate_land_chunk_uses_gates_sh():
    """land_chunk must source gates.sh for deterministic file gate — not call mentat-gate binary."""
    with open(ORCHESTRATE) as f:
        src = f.read()
    start = src.find("land_chunk()")
    assert start != -1, "land_chunk() not found in mentat-orchestrate"
    end = src.find("\n}", start)
    body = src[start:end]
    assert "gates.sh" in body or "mentat_gate" in body, (
        "land_chunk() must source gates.sh / call mentat_gate() for pre-land gate"
    )


def test_orchestrate_does_not_call_mentat_gate_binary_in_land_chunk():
    """land_chunk must not call the mentat-gate binary (deleted in B5)."""
    with open(ORCHESTRATE) as f:
        src = f.read()
    start = src.find("land_chunk()")
    assert start != -1
    end = src.find("\n}", start)
    body = src[start:end]
    assert '"$_LIB/../mentat-gate"' not in body and "'mentat-gate'" not in body, (
        "land_chunk() must not call mentat-gate binary directly (it's deleted)"
    )


# ── B1d: confirmation prompt behavior ────────────────────────────────────────

def test_confirmation_prompt_aborts_on_n():
    """Without --yes, mentat-release answers 'n' → exits non-zero (aborted)."""
    with tempfile.TemporaryDirectory() as dest:
        agents_dest = os.path.join(dest, ".agents")
        os.makedirs(agents_dest)
        # Place a file in dest that doesn't exist in source → rsync will want to delete it
        with open(os.path.join(agents_dest, "phantom-file-to-delete.md"), "w") as f:
            f.write("old\n")
        env = {**os.environ, "HOME": dest}
        r = subprocess.run(
            [MENTAT_RELEASE, "--force-dirty"],
            input="n\n",
            capture_output=True, text=True, cwd=ROOT, env=env,
        )
    assert r.returncode != 0, (
        "Answering 'n' to confirmation prompt must abort with non-zero exit"
    )


# ── B2d: gate failure must hard-abort without --force-gate ───────────────────

def test_release_source_gate_fail_exits_without_force_gate():
    """mentat-release source: gate failure path must exit 1 when FORCE_GATE != 1."""
    with open(MENTAT_RELEASE) as f:
        src = f.read()
    # Verify the conditional guard is present and structured correctly
    assert "FORCE_GATE" in src, "FORCE_GATE variable must appear in mentat-release"
    assert "gate check failed" in src, "gate check failed message must be in mentat-release"
    # Verify --force-gate alone does NOT bypass (requires explicit opt-in)
    assert 'FORCE_GATE" -eq 1' in src or "FORCE_GATE -eq 1" in src, (
        "gate bypass must be guarded by FORCE_GATE == 1 check"
    )


# ── B5: mentat-gate binary must not exist ────────────────────────────────────

def test_mentat_gate_binary_deleted():
    """mentat-gate driver must be absent — orchestration moved to lefthook/gates.sh (B5)."""
    assert not os.path.isfile(MENTAT_GATE), (
        f"mentat-gate must be deleted (B5): {MENTAT_GATE} still exists"
    )
