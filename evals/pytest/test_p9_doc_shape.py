"""P9: static doc/shell assertions for S3-S10 (shipfit-trim plan) + S7b/S8/S10/S12 (shipfit-trim-v2)."""
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
AGENTS_MD = REPO_ROOT / "AGENTS.md"
CONTEXT_MD = REPO_ROOT / "CONTEXT.md"
README_MD = REPO_ROOT / "README.md"
CREDITS_MD = REPO_ROOT / "CREDITS.md"
LEFTHOOK = REPO_ROOT / "lefthook.yml"
ORCHESTRATE = REPO_ROOT / ".agents" / "bin" / "mentat-orchestrate"
IMPLEMENT_CMD = REPO_ROOT / ".agents" / "commands" / "mentat-implement.md"
SMELL_REVIEWER = REPO_ROOT / ".agents" / "agents" / "mentat-smell-reviewer.md"
DOCTOR = REPO_ROOT / ".agents" / "bin" / "mentat-doctor"
INSTALL = REPO_ROOT / ".agents" / "bin" / "mentat-install"


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


# --- S7b (v2): Magic Numbers as 23rd smell ---

def test_smell_reviewer_covers_magic_numbers():
    text = SMELL_REVIEWER.read_text().lower()
    assert "magic numbers" in text or "magic number" in text, (
        "mentat-smell-reviewer.md must include Magic Numbers as a smell"
    )


def test_implement_preflight_agnostic_regex():
    text = IMPLEMENT_CMD.read_text()
    assert "worktrees/" in text, (
        "mentat-implement.md preflight must use agnostic worktrees/<slug> pattern"
    )
    assert ".dmux/worktrees" not in text, (
        "mentat-implement.md must not hardcode .dmux/worktrees (use agnostic regex)"
    )
    assert "MENTAT_WORKTREE" in text, (
        "mentat-implement.md preflight must check $MENTAT_WORKTREE env var first"
    )


# --- S8 (v2): mentat-doctor bin ---

def test_doctor_bin_exists():
    assert DOCTOR.exists(), "mentat-doctor bin must exist at .agents/bin/mentat-doctor"


def test_doctor_bin_is_executable():
    import stat as _stat
    mode = DOCTOR.stat().st_mode
    assert mode & _stat.S_IXUSR, "mentat-doctor must be executable"


def test_doctor_has_v1_schema_sections():
    text = DOCTOR.read_text()
    for section in ("Tool versions", "System", "Repro", "Regression", "Non-determinism"):
        assert section in text, f"mentat-doctor must have '{section}' section"


def test_doctor_sanitizes_secrets():
    text = DOCTOR.read_text()
    assert "redacted" in text.lower(), "mentat-doctor must have secret-sanitization (redact)"
    assert "KEY" in text and "TOKEN" in text and "SECRET" in text, (
        "mentat-doctor sanitization must cover KEY, TOKEN, SECRET"
    )


def test_doctor_nondet_disclosure():
    text = DOCTOR.read_text()
    assert "non_deterministic_inference" in text, (
        "mentat-doctor must set determinism_warnings: [non_deterministic_inference]"
    )


# --- S10 (v2): orchestrate doctor hook ---

def test_orchestrate_spawns_doctor_on_chunk_failure():
    text = ORCHESTRATE.read_text()
    assert "mentat-doctor" in text, (
        "mentat-orchestrate must spawn mentat-doctor on failure"
    )
    assert "|| true" in text, (
        "mentat-doctor spawn in orchestrate must be non-fatal (|| true)"
    )
    assert "agent-exit-nonzero" in text or "reason=" in text, (
        "mentat-doctor spawn must pass a --reason arg"
    )


def test_orchestrate_spawns_doctor_on_land_failure():
    text = ORCHESTRATE.read_text()
    assert "land-fail" in text, (
        "mentat-orchestrate must spawn mentat-doctor with reason=land-fail on land failure"
    )


# --- S12 (v2): rsync no --delete ---

def test_install_rsync_no_delete():
    text = INSTALL.read_text()
    assert "--delete" not in text, (
        "mentat-install must not use rsync --delete (merge-only install)"
    )


def test_install_orphan_advisory():
    text = INSTALL.read_text()
    assert "orphan" in text.lower(), (
        "mentat-install must print orphan advisory after install"
    )


def test_install_no_credits_gen_exclude():
    text = INSTALL.read_text()
    assert "credits-gen" not in text, (
        "mentat-install must not exclude deleted mentat-credits-gen bin"
    )


# --- S3 (v2): lefthook stale-ref pattern refresh ---

def _lefthook_rg_line():
    text = LEFTHOOK.read_text()
    return next((l for l in text.splitlines() if "rg -n" in l and "mentat" in l.lower()), "")


def test_lefthook_stale_ref_drops_mentat_setup():
    rg_line = _lefthook_rg_line()
    assert r"\bmentat-setup\b" not in rg_line, (
        r"lefthook stale-ref pattern must drop \bmentat-setup\b (renamed to mentat-install)"
    )


def test_lefthook_stale_ref_drops_mentat_sync_upstream():
    rg_line = _lefthook_rg_line()
    assert r"\bmentat-sync-upstream\b" not in rg_line, (
        r"lefthook stale-ref pattern must drop \bmentat-sync-upstream\b (renamed to mentat-update)"
    )


def test_lefthook_stale_ref_adds_current_names():
    rg_line = _lefthook_rg_line()
    assert "mentat-install" in rg_line or "mentat-update" in rg_line, (
        "lefthook stale-ref pattern must include current bin names (mentat-install or mentat-update)"
    )


# --- S7 (v2): 22-smell comprehensive coverage ---

def test_smell_reviewer_covers_all_22_refactoring_guru_smells():
    text = SMELL_REVIEWER.read_text().lower()
    all_22 = [
        "long method", "large class", "primitive obsession", "long parameter list", "data clumps",
        "switch statements", "temporary field", "refused bequest", "alternative classes",
        "divergent change", "shotgun surgery", "parallel inheritance",
        "comments", "duplicate code", "lazy class", "data class", "dead code", "speculative generality",
        "feature envy", "inappropriate intimacy", "message chains", "middle man",
    ]
    missing = [s for s in all_22 if s not in text]
    assert not missing, f"smell-reviewer missing refactoring.guru smells: {missing}"
