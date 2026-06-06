"""P7: pyproject tooling (S1), AGENTS.md gate rows (S2), audit schema (S3)."""
import ast
import os
import tomllib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
AGENTS_MD = os.path.join(ROOT, "AGENTS.md")
AUDIT_SCHEMA = os.path.join(ROOT, ".agents", "lib", "audit_schema.py")


# ── S1: pyproject.toml tooling ────────────────────────────────────────────────

def _load_pyproject() -> dict:
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)


def test_pyproject_dev_group_has_ruff():
    cfg = _load_pyproject()
    deps = [d.split(">=")[0].split("==")[0] for d in cfg["dependency-groups"]["dev"]]
    assert "ruff" in deps, "ruff missing from [dependency-groups].dev"


def test_pyproject_dev_group_has_pyright():
    cfg = _load_pyproject()
    deps = [d.split(">=")[0].split("==")[0] for d in cfg["dependency-groups"]["dev"]]
    assert "pyright" in deps, "pyright missing from [dependency-groups].dev"


def test_pyproject_dev_group_has_pydantic():
    cfg = _load_pyproject()
    deps = [d.split(">=")[0].split("==")[0] for d in cfg["dependency-groups"]["dev"]]
    assert "pydantic" in deps, "pydantic missing from [dependency-groups].dev"


def test_pyproject_build_backend_not_broken():
    cfg = _load_pyproject()
    backend = cfg.get("build-system", {}).get("build-backend", "")
    assert backend != "setuptools.backends.legacy:build", (
        "broken build-backend still present — should be removed or set to setuptools.build_meta"
    )


def test_pyproject_ruff_config_present():
    cfg = _load_pyproject()
    assert "ruff" in cfg.get("tool", {}), "[tool.ruff] section missing from pyproject.toml"


def test_pyproject_pyright_config_present():
    cfg = _load_pyproject()
    assert "pyright" in cfg.get("tool", {}), "[tool.pyright] section missing from pyproject.toml"


def test_pyproject_ruff_target_version():
    cfg = _load_pyproject()
    assert cfg["tool"]["ruff"].get("target-version") == "py311"


def test_pyproject_pyright_includes_evals():
    cfg = _load_pyproject()
    includes = cfg["tool"]["pyright"].get("include", [])
    assert "evals/pytest" in includes


# ── S2: AGENTS.md Python gate rows ───────────────────────────────────────────

def _agents_md() -> str:
    with open(AGENTS_MD) as f:
        return f.read()


def test_agents_md_has_ruff_check_gate():
    content = _agents_md()
    assert "ruff check" in content, "AGENTS.md missing ruff check gate row"


def test_agents_md_has_ruff_format_gate():
    content = _agents_md()
    assert "ruff format" in content, "AGENTS.md missing ruff format gate row"


def test_agents_md_has_pyright_gate():
    content = _agents_md()
    assert "pyright" in content, "AGENTS.md missing pyright gate row"


# ── S3: audit_schema.py ───────────────────────────────────────────────────────

def test_audit_schema_file_exists():
    assert os.path.isfile(AUDIT_SCHEMA), f"audit_schema.py not found at {AUDIT_SCHEMA}"


def test_audit_schema_syntax_valid():
    with open(AUDIT_SCHEMA) as f:
        source = f.read()
    ast.parse(source)  # raises SyntaxError if invalid


def test_audit_schema_has_audit_envelope():
    with open(AUDIT_SCHEMA) as f:
        source = f.read()
    assert "class AuditEnvelope" in source


def test_audit_schema_has_chunk_result_payload():
    with open(AUDIT_SCHEMA) as f:
        source = f.read()
    assert "class ChunkResultPayload" in source


def test_audit_schema_has_review_verdict_payload():
    with open(AUDIT_SCHEMA) as f:
        source = f.read()
    assert "class ReviewVerdictPayload" in source


def test_audit_schema_has_dispatch_payload():
    with open(AUDIT_SCHEMA) as f:
        source = f.read()
    assert "def dispatch_payload" in source


def test_audit_schema_envelope_has_required_fields():
    with open(AUDIT_SCHEMA) as f:
        source = f.read()
    for field in ("ts:", "agent:", "session:", "event:", "payload:"):
        assert field in source, f"AuditEnvelope missing field: {field}"


def test_audit_schema_review_verdict_has_score_veto():
    with open(AUDIT_SCHEMA) as f:
        source = f.read()
    assert "score: float" in source
    assert "veto: bool" in source
