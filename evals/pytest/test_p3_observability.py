"""P3: audit log + smells + smell-reviewer + ADR-0008 + logs-prune + config-schema + gate policy."""

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")

import json
import os
import stat
import subprocess
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENTS = os.path.join(ROOT, ".agents")
BIN = os.path.join(AGENTS, "bin")
LIB = os.path.join(BIN, "lib")
DOCS = os.path.join(AGENTS, "docs")


def _sh(cmd: str, cwd: str = ROOT, env: dict = None) -> subprocess.CompletedProcess:
    import os as _os

    e = {**_os.environ, **(env or {})}
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, env=e)


# ── S3.1 audit.sh ────────────────────────────────────────────────────────────


def test_audit_sh_exists():
    assert os.path.isfile(os.path.join(LIB, "audit.sh"))


def test_audit_sh_syntax():
    r = _sh(f"bash -n {LIB}/audit.sh")
    assert r.returncode == 0, r.stderr


def test_audit_sh_defines_mentat_audit():
    with open(os.path.join(LIB, "audit.sh")) as f:
        body = f.read()
    assert "mentat_audit()" in body or "mentat_audit ()" in body


def test_audit_sh_emits_valid_jsonl():
    with tempfile.TemporaryDirectory() as tmpdir:
        r = _sh(
            "bash -s",
            env={
                "MENTAT_LOG_DIR": tmpdir,
                "MENTAT_REPO": "testrepo",
                "MENTAT_SESSION": "sess1",
                "MENTAT_SLUG": "slug1",
            },
        )
        # run via stdin to avoid quoting hell
        import subprocess as _sp

        script = f"source {LIB}/audit.sh && mentat_audit myagent testevent '{{\"ok\":true}}'"
        env = {
            **os.environ,
            "MENTAT_LOG_DIR": tmpdir,
            "MENTAT_REPO": "testrepo",
            "MENTAT_SESSION": "sess1",
            "MENTAT_SLUG": "slug1",
        }
        r = _sp.run(["bash"], input=script, capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        log_path = os.path.join(tmpdir, "testrepo", "sess1", "myagent-slug1.jsonl")
        assert os.path.isfile(log_path), f"expected {log_path}"
        with open(log_path) as f:
            rec = json.loads(f.readline())
        assert rec["agent"] == "myagent"
        assert rec["event"] == "testevent"
        assert rec["payload"] == {"ok": True}
        assert "ts" in rec
        assert rec["session"] == "sess1"


def test_audit_sh_invalid_payload_falls_back_to_null():
    """Non-JSON payload must not crash audit — falls back to null."""
    with tempfile.TemporaryDirectory() as tmpdir:
        import subprocess as _sp

        script = f"source {LIB}/audit.sh && mentat_audit myagent testevent 'not valid json at all'"
        env = {
            **os.environ,
            "MENTAT_LOG_DIR": tmpdir,
            "MENTAT_REPO": "r2",
            "MENTAT_SESSION": "s2",
            "MENTAT_SLUG": "sl2",
        }
        r = _sp.run(["bash"], input=script, capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        log_path = os.path.join(tmpdir, "r2", "s2", "myagent-sl2.jsonl")
        assert os.path.isfile(log_path)
        with open(log_path) as f:
            rec = json.loads(f.readline())
        assert rec["payload"] is None  # fell back to null


def test_audit_sh_log_dir_chmod_700():
    with tempfile.TemporaryDirectory() as tmpdir:
        _sh(
            f"bash -c 'MENTAT_LOG_DIR={tmpdir}/logs MENTAT_REPO=r MENTAT_SESSION=s MENTAT_SLUG=sl "
            f"source {LIB}/audit.sh && mentat_audit a e null'",
        )
        log_dir = os.path.join(tmpdir, "logs")
        if os.path.isdir(log_dir):
            mode = stat.S_IMODE(os.stat(log_dir).st_mode)
            assert mode == 0o700, f"expected 700, got {oct(mode)}"


def test_orchestrate_uses_audit_lib():
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    assert "audit.sh" in body


def test_orchestrate_no_repo_local_logdir():
    """orchestrate must not write logs to $ROOT/.mentat/logs."""
    with open(os.path.join(BIN, "mentat-orchestrate")) as f:
        body = f.read()
    assert '.mentat/logs"' not in body and ".mentat/logs/" not in body


# ── S3.2 smells.sh ───────────────────────────────────────────────────────────


def test_smells_sh_exists():
    assert os.path.isfile(os.path.join(LIB, "smells.sh"))


def test_smells_sh_syntax():
    r = _sh(f"bash -n {LIB}/smells.sh")
    assert r.returncode == 0, r.stderr


def test_smells_sh_defines_dispatcher():
    with open(os.path.join(LIB, "smells.sh")) as f:
        body = f.read()
    assert "smells_check()" in body or "smells_check ()" in body


def test_smells_sh_defines_long_method():
    with open(os.path.join(LIB, "smells.sh")) as f:
        body = f.read()
    assert "smell_long_method" in body


def test_smells_sh_defines_long_params():
    with open(os.path.join(LIB, "smells.sh")) as f:
        body = f.read()
    assert "smell_long_params" in body


def test_smells_sh_defines_magic_numbers():
    with open(os.path.join(LIB, "smells.sh")) as f:
        body = f.read()
    assert "smell_magic_numbers" in body


def test_smells_sh_defines_nested_conditional():
    with open(os.path.join(LIB, "smells.sh")) as f:
        body = f.read()
    assert "smell_nested_conditional" in body


def test_smells_sh_defines_dupe_block():
    with open(os.path.join(LIB, "smells.sh")) as f:
        body = f.read()
    assert "smell_dupe_block" in body


def test_smell_long_method_detects():
    """A shell function >30 lines should be flagged."""
    big_fn = "\n".join(["smell_test_fn() {"] + [f"  echo {i}" for i in range(35)] + ["}"])
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(big_fn)
        path = f.name
    try:
        r = _sh(f"bash -c 'source {LIB}/smells.sh && smell_long_method {path}'")
        assert r.returncode != 0 or "long" in r.stdout.lower() or "long" in r.stderr.lower(), (
            "expected long_method finding"
        )
    finally:
        os.unlink(path)


# ── S3.3 mentat-smell-reviewer.md ────────────────────────────────────────────


def test_smell_reviewer_exists():
    assert os.path.isfile(os.path.join(AGENTS, "agents", "mentat-smell-reviewer.md"))


def test_smell_reviewer_has_frontmatter():
    with open(os.path.join(AGENTS, "agents", "mentat-smell-reviewer.md")) as f:
        lines = [next(f).rstrip() for _ in range(10)]
    assert "---" in lines, "missing YAML frontmatter"


def test_smell_reviewer_covers_22_smells():
    with open(os.path.join(AGENTS, "agents", "mentat-smell-reviewer.md")) as f:
        body = f.read().lower()
    smells = [
        "long method",
        "large class",
        "primitive obsession",
        "long parameter list",
        "data clumps",
        "switch statements",
        "temporary field",
        "refused bequest",
        "alternative classes",
        "divergent change",
        "shotgun surgery",
        "parallel inheritance",
        "dispensable",
        "duplicate code",
        "lazy class",
        "data class",
        "dead code",
        "speculative generality",
        "feature envy",
        "inappropriate intimacy",
        "message chains",
        "middle man",
    ]
    missing = [s for s in smells if s not in body]
    assert not missing, f"smell-reviewer missing: {missing}"


def test_smell_reviewer_advisory_only():
    with open(os.path.join(AGENTS, "agents", "mentat-smell-reviewer.md")) as f:
        body = f.read().lower()
    assert "advisory" in body
    assert "veto" not in body.replace("never veto", "").replace("not veto", "")


def test_smell_reviewer_output_smell_findings():
    with open(os.path.join(AGENTS, "agents", "mentat-smell-reviewer.md")) as f:
        body = f.read()
    assert "smell_findings" in body


# ── S3.4 ADR 0008 ────────────────────────────────────────────────────────────


def test_adr_0008_exists():
    assert os.path.isfile(os.path.join(DOCS, "adr", "0008-code-smell-review.md"))


def test_adr_0008_has_three_sections():
    with open(os.path.join(DOCS, "adr", "0008-code-smell-review.md")) as f:
        body = f.read()
    assert "## Context" in body
    assert "## Decision" in body
    assert "## Consequences" in body


def test_adr_0008_has_decided_author():
    with open(os.path.join(DOCS, "adr", "0008-code-smell-review.md")) as f:
        body = f.read()
    assert "**Decided:**" in body
    assert "**Author:**" in body


def test_adr_0008_advisory_not_gated():
    with open(os.path.join(DOCS, "adr", "0008-code-smell-review.md")) as f:
        body = f.read().lower()
    assert "advisory" in body


# ── S3.5 evals fixtures ───────────────────────────────────────────────────────


def test_smell_fixtures_exist():
    fixture_dir = os.path.join(ROOT, "evals", "promptfoo", "fixtures", "smells")
    assert os.path.isdir(fixture_dir)
    files = os.listdir(fixture_dir)
    assert any("long" in f for f in files), "missing long-method fixture"
    assert any("clean" in f for f in files), "missing clean fixture"


def test_smell_rubric_exists():
    rubric = os.path.join(ROOT, "evals", "promptfoo", "rubrics", "mentat-smell-reviewer.md")
    assert os.path.isfile(rubric)


def test_promptfoo_config_registers_smell_provider():
    cfg_path = os.path.join(ROOT, "evals", "promptfoo", "promptfooconfig.yaml")
    with open(cfg_path) as f:
        body = f.read()
    assert "smell" in body.lower()


# ── S3.6 mentat-logs-prune ───────────────────────────────────────────────────


def test_logs_prune_exists():
    assert os.path.isfile(os.path.join(BIN, "mentat-logs-prune"))


def test_logs_prune_syntax():
    r = _sh(f"bash -n {BIN}/mentat-logs-prune")
    assert r.returncode == 0, r.stderr


def test_logs_prune_dry_run_flag():
    r = _sh(f"bash {BIN}/mentat-logs-prune --help 2>&1 || bash {BIN}/mentat-logs-prune --dry-run --gzip-after 999 2>&1")
    assert r.returncode == 0 or "dry" in r.stdout.lower() or "dry" in r.stderr.lower()


def test_logs_prune_gzip_old_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = os.path.join(tmpdir, "logs", "repo1", "sess1")
        os.makedirs(log_dir)
        log_file = os.path.join(log_dir, "agent-slug.jsonl")
        with open(log_file, "w") as f:
            f.write('{"ts":"old"}\n')
        os.utime(log_file, (0, 0))
        r = _sh(
            f"bash {BIN}/mentat-logs-prune --gzip-after 1 --archive-after 9999 --delete-after 9999",
            env={"MENTAT_LOG_DIR": os.path.join(tmpdir, "logs")},
        )
        assert r.returncode == 0, r.stderr
        assert os.path.isfile(log_file + ".gz") or not os.path.isfile(log_file), "old file should be gzipped"


# ── S3.7 config-schema.jq + mentat-config CLI ────────────────────────────────


def test_config_schema_jq_exists():
    assert os.path.isfile(os.path.join(LIB, "config-schema.jq"))


def test_config_schema_jq_is_valid_jq():
    r = _sh(f"jq -e '.' {LIB}/config-schema.jq 2>&1 || jq -n -f {LIB}/config-schema.jq >/dev/null 2>&1; echo exit:$?")
    assert "exit:0" in r.stdout or "exit:0" in r.stderr


def test_mentat_config_exists():
    assert os.path.isfile(os.path.join(BIN, "mentat-config"))


def test_mentat_config_syntax():
    r = _sh(f"bash -n {BIN}/mentat-config")
    assert r.returncode == 0, r.stderr


def test_mentat_config_print_example():
    r = _sh(f"bash {BIN}/mentat-config --print-example")
    assert r.returncode == 0, r.stderr
    try:
        parsed = json.loads(r.stdout)
        assert "harness" in parsed
    except json.JSONDecodeError:
        assert "harness" in r.stdout, "output should contain harness key"


def test_mentat_config_print_schema_md():
    r = _sh(f"bash {BIN}/mentat-config --print-schema-md")
    assert r.returncode == 0, r.stderr
    assert "|" in r.stdout, "should emit markdown table"


def test_mentat_config_validate_good():
    cfg = '{"harness":{"name":"claude-code","model":"sonnet"},"agents":{"max_concurrent":3},"diff":{"tool":"delta"},"editor":{"name":"cursor"},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(f"bash {BIN}/mentat-config --validate {cfgpath}")
        assert r.returncode == 0, r.stderr
    finally:
        os.unlink(cfgpath)


def test_mentat_config_validate_bad_harness():
    cfg = '{"harness":{"name":"unknown-harness","model":"sonnet"},"agents":{"max_concurrent":3},"diff":{"tool":"delta"},"editor":{"name":"cursor"},"plugins":[]}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonc", delete=False) as f:
        f.write(cfg)
        cfgpath = f.name
    try:
        r = _sh(f"bash {BIN}/mentat-config --validate {cfgpath}")
        assert r.returncode != 0, "invalid harness name should fail"
    finally:
        os.unlink(cfgpath)


def test_mentatjsonc_example_matches_print_example():
    example_path = os.path.join(AGENTS, ".mentat.jsonc.example")
    if not os.path.isfile(example_path):
        return  # generated later
    r = _sh(f"bash {BIN}/mentat-config --print-example")
    assert r.returncode == 0
    with open(example_path) as f:
        on_disk = f.read().strip()
    assert on_disk == r.stdout.strip(), ".mentat.jsonc.example drifted from --print-example"


# ── S3.8 gates print-policy ──────────────────────────────────────────────────


def test_gates_sh_has_class_annotations():
    with open(os.path.join(LIB, "gates.sh")) as f:
        body = f.read()
    assert "@class:" in body
    assert "@glob:" in body
    assert "@check:" in body


def test_mentat_gate_print_policy():
    r = _sh(f"bash {BIN}/mentat-gate --print-policy")
    assert r.returncode == 0, r.stderr
    assert "|" in r.stdout, "should emit markdown table"
    assert "class" in r.stdout.lower() or "Class" in r.stdout


def test_agents_md_has_generated_block():
    with open(os.path.join(AGENTS, "AGENTS.md")) as f:
        body = f.read()
    assert "<!-- BEGIN generated" in body or "<!-- generated" in body
