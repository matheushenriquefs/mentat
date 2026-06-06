"""P9: static doc/shell assertions for S3-S10 (shipfit-trim plan)."""
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
AGENTS_MD = REPO_ROOT / "AGENTS.md"
CONTEXT_MD = REPO_ROOT / "CONTEXT.md"
README_MD = REPO_ROOT / "README.md"
CREDITS_MD = REPO_ROOT / "CREDITS.md"
LEFTHOOK = REPO_ROOT / "lefthook.yml"
ORCHESTRATE = REPO_ROOT / ".agents" / "bin" / "mentat-orchestrate"
IMPLEMENT_CMD = REPO_ROOT / ".agents" / "commands" / "mentat-implement.md"


# --- S3: doc dedup ---

def test_context_md_tagline_removed():
    text = CONTEXT_MD.read_text()
    assert "lean, agnostic" not in text, (
        "CONTEXT.md tagline 'lean, agnostic' must be removed (README is canonical)"
    )


def test_readme_has_link_to_context_not_how_it_works():
    text = README_MD.read_text()
    assert "CONTEXT.md" in text, "README.md must link to CONTEXT.md"
    assert "## How it works" not in text, (
        "README.md must not have '## How it works' (moved to CONTEXT.md)"
    )


# --- S4: CREDITS fix ---

def test_credits_no_runtime_tool_dependencies_section():
    text = CREDITS_MD.read_text()
    assert "## Runtime tool dependencies" not in text, (
        "CREDITS.md must not have Runtime tool dependencies section (dev tools → README)"
    )


def test_readme_has_development_section_with_dev_tools():
    text = README_MD.read_text()
    assert "## Development" in text, "README.md must have ## Development section"
    assert "vendir" in text, "README.md Development section must list vendir"
    assert "lefthook" in text, "README.md Development section must list lefthook"


# --- S5: Test-when-modified folded ---

def test_agents_md_no_test_when_modified_section():
    text = AGENTS_MD.read_text()
    assert "## Test-when-modified" not in text, (
        "AGENTS.md must not have Test-when-modified section (folded into Quality Gates)"
    )


def test_agents_md_quality_gates_has_triggers_column():
    text = AGENTS_MD.read_text()
    assert "## Quality Gates" in text, "AGENTS.md must have ## Quality Gates section"
    assert "Triggers" in text, "Quality Gates table must have Triggers column"


# --- S6: docs-sync ---

def test_lefthook_has_docs_sync_hook():
    text = LEFTHOOK.read_text()
    assert "docs-sync" in text, "lefthook.yml must have docs-sync hook"
    assert "docs-sync.sh" in text, "lefthook docs-sync hook must call docs-sync.sh"


# --- S7: dead-code mentat-logs-prune retained with inbound ref ---

def test_agents_md_references_mentat_logs_prune():
    text = AGENTS_MD.read_text()
    assert "mentat-logs-prune" in text, (
        "AGENTS.md must reference mentat-logs-prune (retention doctrine row)"
    )


# --- S8: worktree preflight in mentat-implement ---

def test_implement_has_worktree_preflight():
    text = IMPLEMENT_CMD.read_text()
    assert "worktree" in text.lower(), "mentat-implement.md must have worktree preflight"
    assert "implement.preflight.fail" in text, (
        "mentat-implement.md must emit implement.preflight.fail on wrong cwd"
    )


def test_implement_preflight_is_step_zero():
    text = IMPLEMENT_CMD.read_text()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "implement.preflight.fail" in line or ("worktree" in line.lower() and "preflight" in line.lower()):
            assert any("0." in l or "step 0" in l.lower() for l in lines[max(0, i-5):i+2]), (
                "worktree preflight must be step 0 in mentat-implement.md"
            )
            break


# --- S9: MENTAT_WORKTREE export in orchestrate ---

def test_orchestrate_exports_mentat_worktree():
    text = ORCHESTRATE.read_text()
    assert "export MENTAT_WORKTREE" in text, (
        "mentat-orchestrate must export MENTAT_WORKTREE in run_chunk"
    )


# --- S10: holding-branch-guard 3-source resolver ---

def test_lefthook_has_holding_branch_guard():
    text = LEFTHOOK.read_text()
    assert "holding-branch-guard" in text, "lefthook.yml must have holding-branch-guard hook"


def test_holding_branch_guard_uses_mentat_config():
    text = LEFTHOOK.read_text()
    assert "mentat-config" in text, (
        "holding-branch-guard must use mentat-config to resolve holding branch"
    )


def test_holding_branch_guard_uses_symbolic_ref_fallback():
    text = LEFTHOOK.read_text()
    assert "symbolic-ref" in text, (
        "holding-branch-guard must fall back to git symbolic-ref for origin HEAD"
    )


def test_holding_branch_guard_no_hardcoded_main():
    text = LEFTHOOK.read_text()
    guard_start = text.find("holding-branch-guard")
    assert guard_start != -1, "holding-branch-guard must be present in lefthook.yml"
    guard_end = text.find("\n    ", guard_start + len("holding-branch-guard") + 50)
    guard_block = text[guard_start:guard_end + 200] if guard_end > 0 else text[guard_start:]
    assert '= "main"' not in guard_block and "= 'main'" not in guard_block, (
        "holding-branch-guard must not hardcode 'main' — use resolver"
    )


def test_holding_branch_guard_has_mentat_release_bypass():
    text = LEFTHOOK.read_text()
    assert "MENTAT_RELEASE" in text, (
        "holding-branch-guard must support MENTAT_RELEASE=1 bypass"
    )
