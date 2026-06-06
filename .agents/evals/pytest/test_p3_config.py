"""P3: config loader + harness matrix — static + behavioral assertions."""
import os
import subprocess
import json
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
AGENTS = os.path.join(ROOT, ".agents")
BIN = os.path.join(AGENTS, "bin")
LIB = os.path.join(BIN, "lib")
DOCS = os.path.join(AGENTS, "docs")

HARNESSES = ["claude-code", "cursor", "aider", "codex", "copilot", "gemini", "openhands", "amp"]


def _sh(cmd: str, cwd: str = ROOT, env: dict = None) -> subprocess.CompletedProcess:
    import os as _os
    e = {**_os.environ, **(env or {})}
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, env=e)


# S3.1 — lib/config.sh exists and exports mentat_config()

def test_config_sh_exists():
    assert os.path.isfile(os.path.join(LIB, "config.sh"))


def test_config_sh_syntax_ok():
    r = _sh(f"bash -n {LIB}/config.sh")
    assert r.returncode == 0, r.stderr


def test_config_sh_defines_mentat_config():
    with open(os.path.join(LIB, "config.sh")) as f:
        body = f.read()
    assert "mentat_config()" in body or "mentat_config ()" in body


def test_config_sh_defines_mentat_config_validate():
    with open(os.path.join(LIB, "config.sh")) as f:
        body = f.read()
    assert "mentat_config_validate()" in body or "mentat_config_validate ()" in body


def test_mentat_config_reads_harness_name():
    cfg = '{"harness":{"name":"claude-code","model":"sonnet"},"agents":{"max_concurrent":3},"diff":{"tool":"delta"},"editor":{"name":"cursor"},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(
            f'bash -c \'source {LIB}/config.sh; MENTAT_CONFIG_PATH={cfgpath} mentat_config harness.name\'',
        )
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "claude-code"
    finally:
        os.unlink(cfgpath)


def test_mentat_config_reads_max_concurrent():
    cfg = '{"harness":{"name":"cursor","model":""},"agents":{"max_concurrent":5},"diff":{"tool":""},"editor":{"name":""},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(
            f'bash -c \'source {LIB}/config.sh; MENTAT_CONFIG_PATH={cfgpath} mentat_config agents.max_concurrent\'',
        )
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "5"
    finally:
        os.unlink(cfgpath)


def test_mentat_config_validate_fails_bad_harness():
    cfg = '{"harness":{"name":"badname","model":""},"agents":{"max_concurrent":3},"diff":{"tool":""},"editor":{"name":""},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(
            f'bash -c \'source {LIB}/config.sh; MENTAT_CONFIG_PATH={cfgpath} mentat_config_validate\'',
        )
        assert r.returncode == 2, f"validate must exit 2 for unknown harness, got {r.returncode}"
    finally:
        os.unlink(cfgpath)


def test_mentat_config_validate_fails_bad_max_concurrent_zero():
    cfg = '{"harness":{"name":"cursor","model":""},"agents":{"max_concurrent":0},"diff":{"tool":""},"editor":{"name":""},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(f'bash -c \'source {LIB}/config.sh; MENTAT_CONFIG_PATH={cfgpath} mentat_config_validate\'')
        assert r.returncode == 2, f"validate must exit 2 for max_concurrent=0, got {r.returncode}"
    finally:
        os.unlink(cfgpath)


def test_mentat_config_validate_fails_bad_max_concurrent_over():
    cfg = '{"harness":{"name":"cursor","model":""},"agents":{"max_concurrent":11},"diff":{"tool":""},"editor":{"name":""},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(f'bash -c \'source {LIB}/config.sh; MENTAT_CONFIG_PATH={cfgpath} mentat_config_validate\'')
        assert r.returncode == 2, f"validate must exit 2 for max_concurrent=11, got {r.returncode}"
    finally:
        os.unlink(cfgpath)


def test_mentat_config_validate_fails_bad_max_concurrent_string():
    cfg = '{"harness":{"name":"cursor","model":""},"agents":{"max_concurrent":"three"},"diff":{"tool":""},"editor":{"name":""},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(f'bash -c \'source {LIB}/config.sh; MENTAT_CONFIG_PATH={cfgpath} mentat_config_validate\'')
        assert r.returncode == 2, f"validate must exit 2 for max_concurrent=string, got {r.returncode}"
    finally:
        os.unlink(cfgpath)


def test_mentat_config_validate_fails_diff_tool_not_string():
    cfg = '{"harness":{"name":"cursor","model":""},"agents":{"max_concurrent":3},"diff":{"tool":42},"editor":{"name":""},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(f'bash -c \'source {LIB}/config.sh; MENTAT_CONFIG_PATH={cfgpath} mentat_config_validate\'')
        assert r.returncode == 2, f"validate must exit 2 for non-string diff.tool, got {r.returncode}"
    finally:
        os.unlink(cfgpath)


def test_mentat_config_validate_fails_plugins_not_array():
    cfg = '{"harness":{"name":"cursor","model":""},"agents":{"max_concurrent":3},"diff":{"tool":""},"editor":{"name":""},"plugins":"bad"}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(f'bash -c \'source {LIB}/config.sh; MENTAT_CONFIG_PATH={cfgpath} mentat_config_validate\'')
        assert r.returncode == 2, f"validate must exit 2 for non-array plugins, got {r.returncode}"
    finally:
        os.unlink(cfgpath)


def test_mentat_config_validate_uses_return_not_exit():
    """mentat_config_validate must use 'return' not 'exit' — sourced lib must not kill caller."""
    with open(os.path.join(LIB, "config.sh")) as f:
        body = f.read()
    # exit 2 in a sourced file terminates the calling process before || can fire
    assert "exit 2" not in body, "config.sh must use 'return 2' not 'exit 2' — sourced library"


def test_mentat_config_validate_fails_editor_name_not_string():
    cfg = '{"harness":{"name":"cursor","model":""},"agents":{"max_concurrent":3},"diff":{"tool":""},"editor":{"name":99},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(f'bash -c \'source {LIB}/config.sh; MENTAT_CONFIG_PATH={cfgpath} mentat_config_validate\'')
        assert r.returncode == 2, f"validate must exit 2 for non-string editor.name, got {r.returncode}"
    finally:
        os.unlink(cfgpath)


def test_mentat_config_validate_passes_valid():
    cfg = '{"harness":{"name":"claude-code","model":"sonnet"},"agents":{"max_concurrent":3},"diff":{"tool":"delta"},"editor":{"name":"cursor"},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(
            f'bash -c \'source {LIB}/config.sh; MENTAT_CONFIG_PATH={cfgpath} mentat_config_validate\'',
        )
        assert r.returncode == 0, r.stderr
    finally:
        os.unlink(cfgpath)


# S3.2 — schema example + default config

def test_mentat_jsonc_example_exists():
    assert os.path.isfile(os.path.join(AGENTS, ".mentat.jsonc.example"))


def test_mentat_jsonc_exists():
    assert os.path.isfile(os.path.join(AGENTS, ".mentat.jsonc"))


def test_mentat_jsonc_valid_json_after_comment_strip():
    path = os.path.join(AGENTS, ".mentat.jsonc")
    r = _sh(f"sed 's|//.*||g' {path} | jq -e '.'")
    assert r.returncode == 0, f"jq parse failed: {r.stderr}"


def test_mentat_jsonc_has_required_keys():
    path = os.path.join(AGENTS, ".mentat.jsonc")
    r = _sh(f"sed 's|//.*||g' {path} | jq -r '.harness.name,.agents.max_concurrent,.diff.tool,.editor.name'")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert len(lines) == 4, f"expected 4 lines, got: {lines}"


def test_mentat_jsonc_locked_schema_shape():
    """Verify .mentat.jsonc matches the locked nested schema exactly."""
    path = os.path.join(AGENTS, ".mentat.jsonc")
    r = _sh(f"sed 's|//.*||g' {path} | jq -e '"
            ".harness | has(\"name\") and has(\"model\") | . and "
            "($ENV | . == .) "  # always true — chaining condition
            "'")
    # Check each required nested key exists and has correct type
    checks = [
        ".harness.name | type == \"string\"",
        ".harness.model | type == \"string\"",
        ".agents.max_concurrent | type == \"number\"",
        ".diff.tool | type == \"string\"",
        ".editor.name | type == \"string\"",
        ".plugins | type == \"array\"",
    ]
    for check in checks:
        r = _sh(f"sed 's|//.*||g' {path} | jq -e '{check}'")
        assert r.returncode == 0, f"Schema check failed for '{check}': {r.stderr}"
    # harness.name must be a valid enum value
    r = _sh(f"sed 's|//.*||g' {path} | jq -e '.harness.name | IN(\"claude-code\",\"cursor\",\"aider\",\"codex\",\"copilot\",\"gemini\",\"openhands\",\"amp\")'")
    assert r.returncode == 0, f".harness.name must be a valid harness enum: {r.stderr}"


# S3.3 — mentat-orchestrate reads config; CLI flags override

def test_orchestrate_sources_config_sh():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    assert "config.sh" in body, "mentat-orchestrate must source lib/config.sh"


def test_orchestrate_uses_mentat_config_for_harness():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    assert "mentat_config harness.name" in body


def test_orchestrate_reads_model_from_config():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    assert "mentat_config harness.model" in body


def test_orchestrate_reads_parallel_cap_from_config():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    assert "mentat_config agents.max_concurrent" in body


def test_orchestrate_flag_still_accepted():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    assert "--harness=" in body


def test_orchestrate_parallel_cap_from_config():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    assert "PARALLEL_CAP" in body


def test_orchestrate_calls_mentat_config_validate():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    assert "mentat_config_validate" in body


def test_orchestrate_dry_run_flag_exists():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    assert "--dry-run" in body


def test_orchestrate_dry_run_exits_zero():
    """--dry-run must print plan info and exit 0 without launching worktrees."""
    cfg_path = os.path.join(AGENTS, ".mentat.jsonc")
    r = _sh(
        f'MENTAT_CONFIG_PATH={cfg_path} {BIN}/mentat-orchestrate --dry-run feat/x /dev/null',
        cwd=ROOT,
    )
    assert r.returncode == 0, f"--dry-run must exit 0: {r.stderr}"
    assert "dry-run" in r.stdout or "dry-run" in r.stderr


def test_orchestrate_dry_run_uses_config_harness():
    """--dry-run output must reflect harness from config, not hardcoded default."""
    cfg = '{"harness":{"name":"aider","model":""},"agents":{"max_concurrent":3},"diff":{"tool":""},"editor":{"name":""},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(
            f'MENTAT_CONFIG_PATH={cfgpath} {BIN}/mentat-orchestrate --dry-run feat/x /dev/null',
            cwd=ROOT,
        )
        assert r.returncode == 0, f"dry-run failed: {r.stderr}"
        combined = r.stdout + r.stderr
        assert "aider" in combined, f"dry-run must show harness=aider from config: {combined}"
    finally:
        os.unlink(cfgpath)


def test_orchestrate_flag_overrides_config_harness():
    """--harness=<name> CLI flag must override .mentat.jsonc harness.name (B9)."""
    cfg = '{"harness":{"name":"aider","model":""},"agents":{"max_concurrent":3},"diff":{"tool":""},"editor":{"name":""},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(
            f'MENTAT_CONFIG_PATH={cfgpath} {BIN}/mentat-orchestrate --harness=codex --dry-run feat/x /dev/null',
            cwd=ROOT,
        )
        assert r.returncode == 0, f"flag override dry-run failed: {r.stderr}"
        combined = r.stdout + r.stderr
        assert "harness=codex" in combined, f"--harness=codex must override config aider; got: {combined}"
    finally:
        os.unlink(cfgpath)


def test_orchestrate_dry_run_shows_parallel_cap_from_config():
    """PARALLEL_CAP read from config must appear in --dry-run output (B8 runtime)."""
    cfg = '{"harness":{"name":"cursor","model":""},"agents":{"max_concurrent":7},"diff":{"tool":""},"editor":{"name":""},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(
            f'MENTAT_CONFIG_PATH={cfgpath} {BIN}/mentat-orchestrate --dry-run feat/x /dev/null',
            cwd=ROOT,
        )
        assert r.returncode == 0, f"dry-run failed: {r.stderr}"
        combined = r.stdout + r.stderr
        assert "7" in combined, f"dry-run must show parallel_cap=7 from config: {combined}"
    finally:
        os.unlink(cfgpath)


def test_orchestrate_validate_called_before_holding_arg():
    """mentat_config_validate must appear before HOLDING assignment in source (B10)."""
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    validate_idx = body.find("mentat_config_validate")
    holding_idx = body.find("HOLDING=")
    assert validate_idx != -1, "mentat_config_validate not found in orchestrate"
    assert holding_idx != -1, "HOLDING= not found in orchestrate"
    assert validate_idx < holding_idx, \
        f"mentat_config_validate (pos {validate_idx}) must appear before HOLDING= (pos {holding_idx})"


# S3.3b — per-harness lib/harness-<name>.sh files

def test_harness_files_exist():
    for h in HARNESSES:
        path = os.path.join(LIB, f"harness-{h}.sh")
        assert os.path.isfile(path), f"Missing: {path}"


def test_harness_files_syntax_ok():
    for h in HARNESSES:
        path = os.path.join(LIB, f"harness-{h}.sh")
        r = _sh(f"bash -n {path}")
        assert r.returncode == 0, f"bash -n failed for harness-{h}.sh: {r.stderr}"


def test_harness_files_define_cmd_function():
    for h in HARNESSES:
        path = os.path.join(LIB, f"harness-{h}.sh")
        with open(path) as f:
            body = f.read()
        fn = f"harness_{h.replace('-', '_')}_cmd"
        assert fn + "()" in body or fn + " ()" in body, f"{path} must define {fn}()"


def test_orchestrate_dispatches_harness_files():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    assert "harness-${HARNESS}.sh" in body or 'harness-"$HARNESS".sh' in body or "harness_${HARNESS}_cmd" in body


# S3.4 — diff/editor knobs wired from config

def test_orchestrate_no_hardcoded_cursor_agent():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    # cursor-agent invocation should now live in harness-cursor.sh, not inlined
    assert "cursor-agent" not in body, "cursor-agent must move to harness-cursor.sh"


def test_orchestrate_no_hardcoded_claude_p():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    assert "claude -p" not in body, "claude -p must move to harness-claude-code.sh"


# S3.5 — harness matrix doc

def test_harness_matrix_doc_exists():
    assert os.path.isfile(os.path.join(DOCS, "harness-matrix.md"))


def test_harness_matrix_covers_all_harnesses():
    path = os.path.join(DOCS, "harness-matrix.md")
    with open(path) as f:
        body = f.read()
    for h in HARNESSES:
        assert h in body, f"harness-matrix.md missing entry for {h}"
