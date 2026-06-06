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


def _dev_deps() -> list[str]:
    cfg = _load_pyproject()
    return [d.split(">=")[0].split("==")[0].strip() for d in cfg["dependency-groups"]["dev"]]


def test_pyproject_dev_group_has_ruff():
    assert "ruff" in _dev_deps(), "ruff missing from [dependency-groups].dev"


def test_pyproject_dev_group_has_pyright():
    assert "pyright" in _dev_deps(), "pyright missing from [dependency-groups].dev"


def test_pyproject_dev_group_has_pydantic():
    assert "pydantic" in _dev_deps(), "pydantic missing from [dependency-groups].dev"


def test_pyproject_build_backend_not_broken():
    cfg = _load_pyproject()
    backend = cfg.get("build-system", {}).get("build-backend", "")
    assert backend != "setuptools.backends.legacy:build", (
        "broken build-backend still present"
    )


def test_pyproject_ruff_target_version():
    cfg = _load_pyproject()
    assert cfg["tool"]["ruff"].get("target-version") == "py311"


def test_pyproject_ruff_lint_select():
    cfg = _load_pyproject()
    select = cfg["tool"]["ruff"]["lint"].get("select", [])
    for code in ("E", "F", "W", "I", "UP", "B", "SIM"):
        assert code in select, f"ruff lint missing rule group: {code}"


def test_pyproject_ruff_format_quote_style():
    cfg = _load_pyproject()
    assert cfg["tool"]["ruff"]["format"].get("quote-style") == "double"


def test_pyproject_pyright_includes_evals():
    cfg = _load_pyproject()
    assert "evals/pytest" in cfg["tool"]["pyright"].get("include", [])


def test_pyproject_pyright_python_version():
    cfg = _load_pyproject()
    assert cfg["tool"]["pyright"].get("pythonVersion") == "3.11"


def test_pyproject_pyright_type_checking_mode():
    cfg = _load_pyproject()
    assert cfg["tool"]["pyright"].get("typeCheckingMode") == "standard"


# ── S2: AGENTS.md Python gate rows in Quality Gates table ────────────────────

def _quality_gates_section() -> str:
    """Extract text from ## Quality Gates section only."""
    with open(AGENTS_MD) as f:
        content = f.read()
    start = content.find("## Quality Gates")
    assert start != -1, "## Quality Gates section not found in AGENTS.md"
    # End at next ## section
    end = content.find("\n## ", start + 1)
    return content[start:end] if end != -1 else content[start:]


def test_agents_md_quality_gates_has_ruff_check():
    section = _quality_gates_section()
    assert "ruff check" in section, "Quality Gates table missing ruff check row"


def test_agents_md_quality_gates_has_ruff_format():
    section = _quality_gates_section()
    assert "ruff format" in section, "Quality Gates table missing ruff format row"


def test_agents_md_quality_gates_has_pyright():
    section = _quality_gates_section()
    assert "pyright" in section, "Quality Gates table missing pyright row"


def test_agents_md_quality_gates_uses_container_run():
    section = _quality_gates_section()
    assert "mentat-container-run" in section, (
        "Python gate rows must use mentat-container-run per plan S2"
    )


# ── S3: audit_schema.py pydantic models ──────────────────────────────────────

def _schema_source() -> str:
    with open(AUDIT_SCHEMA) as f:
        return f.read()


def test_audit_schema_file_exists():
    assert os.path.isfile(AUDIT_SCHEMA), f"audit_schema.py not found at {AUDIT_SCHEMA}"


def test_audit_schema_syntax_valid():
    ast.parse(_schema_source())


def test_audit_envelope_fields():
    src = _schema_source()
    assert "class AuditEnvelope" in src
    for field in ("ts:", "agent:", "session:", "event:", "payload:"):
        assert field in src, f"AuditEnvelope missing field: {field}"


def test_chunk_result_payload_fields():
    src = _schema_source()
    assert "class ChunkResultPayload" in src
    for field in ("slug:", "outcome:", "tip:", "reason:"):
        assert field in src, f"ChunkResultPayload missing field: {field}"


def test_review_verdict_payload_fields():
    src = _schema_source()
    assert "class ReviewVerdictPayload" in src
    for field in ("reviewer:", "score: float", "veto: bool", "findings:"):
        assert field in src, f"ReviewVerdictPayload missing field: {field}"


def test_dispatch_payload_routes_land_complete():
    src = _schema_source()
    assert "def dispatch_payload" in src
    assert "land.complete" in src, "dispatch_payload missing land.complete verb mapping"


def test_dispatch_payload_routes_review_final():
    src = _schema_source()
    assert "review.final" in src, "dispatch_payload missing review.final verb mapping"
