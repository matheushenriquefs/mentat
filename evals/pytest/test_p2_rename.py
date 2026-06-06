"""P2: rename + dmux purge — static assertions."""
import os
import subprocess

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
AGENTS = os.path.join(ROOT, ".agents")
BIN = os.path.join(AGENTS, "bin")
LIB = os.path.join(BIN, "lib")
AGENTS_DIR = os.path.join(AGENTS, "agents")
DOCS = os.path.join(AGENTS, "docs")
ADR = os.path.join(DOCS, "adr")


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


# S2.1 — bin/ renames

def test_mentat_orchestrate_exists():
    assert os.path.isfile(os.path.join(BIN, "mentat-orchestrate"))


def test_mentat_track_exists():
    assert os.path.isfile(os.path.join(BIN, "mentat-track"))


def test_mentat_container_up_exists():
    assert os.path.isfile(os.path.join(BIN, "mentat-container-up"))


def test_mentat_container_run_exists():
    assert os.path.isfile(os.path.join(BIN, "mentat-container-run"))


def test_mentat_container_doctor_exists():
    assert os.path.isfile(os.path.join(BIN, "mentat-container-doctor"))


def test_harness_map_deleted():
    assert not os.path.isfile(os.path.join(LIB, "harness-map.jq")), "harness-map.jq must be deleted (S2.1)"


def test_old_bin_names_gone():
    for name in ("to-orchestrate", "to-track-harness", "devcontainer-up",
                 "devcontainer-run", "devcontainer-doctor"):
        assert not os.path.isfile(os.path.join(BIN, name)), f"{name} still present in bin/"


def test_harness_map_not_in_bin_root():
    assert not os.path.isfile(os.path.join(BIN, "harness-map.jq"))


# S2.2 — agents/ renames

def test_mentat_researcher_exists():
    assert os.path.isfile(os.path.join(AGENTS_DIR, "mentat-researcher.md"))


def test_mentat_plan_reviewer_exists():
    assert os.path.isfile(os.path.join(AGENTS_DIR, "mentat-plan-reviewer.md"))


def test_mentat_test_reviewer_exists():
    assert os.path.isfile(os.path.join(AGENTS_DIR, "mentat-test-reviewer.md"))


def test_mentat_bug_reviewer_exists():
    assert os.path.isfile(os.path.join(AGENTS_DIR, "mentat-bug-reviewer.md"))


def test_old_agent_names_gone():
    for name in ("crew-research.md", "crew-review-plan.md",
                 "crew-review-tests.md", "crew-review-bugs.md"):
        assert not os.path.isfile(os.path.join(AGENTS_DIR, name)), f"{name} still in agents/"


# S2.3 — cross-ref sed sweep (old names must not appear outside context/)

def _grep_old_names(pattern: str) -> list:
    result = subprocess.run(
        ["grep", "-rl", "--include=*", "-e", pattern,
         "--exclude-dir=.git", "--exclude-dir=context",
         "--exclude-dir=evals", "--exclude-dir=__pycache__",
         "--exclude-dir=.claude", "--exclude-dir=.pytest_cache",
         "--exclude=*.pyc",
         ROOT],
        capture_output=True, text=True
    )
    return [l for l in result.stdout.splitlines() if l]


def test_no_old_orchestrate_ref():
    hits = _grep_old_names("to-orchestrate")
    assert hits == [], f"to-orchestrate still referenced: {hits}"


def test_no_old_track_harness_ref():
    hits = _grep_old_names("to-track-harness")
    assert hits == [], f"to-track-harness still referenced: {hits}"


def test_no_old_devcontainer_up_ref():
    hits = _grep_old_names("devcontainer-up")
    assert hits == [], f"devcontainer-up still referenced: {hits}"


def test_no_old_devcontainer_run_ref():
    hits = _grep_old_names("devcontainer-run")
    assert hits == [], f"devcontainer-run still referenced: {hits}"


def test_no_old_devcontainer_doctor_ref():
    hits = _grep_old_names("devcontainer-doctor")
    assert hits == [], f"devcontainer-doctor still referenced: {hits}"


def test_no_old_crew_research_ref():
    hits = _grep_old_names("crew-research")
    assert hits == [], f"crew-research still referenced: {hits}"


def test_no_old_crew_review_plan_ref():
    hits = _grep_old_names("crew-review-plan")
    assert hits == [], f"crew-review-plan still referenced: {hits}"


def test_no_old_crew_review_tests_ref():
    hits = _grep_old_names("crew-review-tests")
    assert hits == [], f"crew-review-tests still referenced: {hits}"


def test_no_old_crew_review_bugs_ref():
    hits = _grep_old_names("crew-review-bugs")
    assert hits == [], f"crew-review-bugs still referenced: {hits}"


# S2.5 — dmux purge

def test_no_dmux_worktrees_path():
    hits = _grep_old_names(r"\.dmux/worktrees")
    assert hits == [], f".dmux/worktrees still referenced: {hits}"


def test_no_dmux_slug_ref():
    hits = _grep_old_names("dmux_slug")
    assert hits == [], f"dmux_slug still referenced: {hits}"


def test_no_dmux_label_ref():
    hits = _grep_old_names("dmux_slug=")
    assert hits == [], f"dmux_slug= still referenced: {hits}"


def test_mentat_worktrees_path_in_orchestrate():
    src = _read(os.path.join(BIN, "mentat-orchestrate"))
    assert ".mentat/worktrees" in src


# S2.6 — deleted dmux dirs/files

def test_no_dmux_hooks_dir():
    assert not os.path.isdir(os.path.join(ROOT, ".dmux-hooks"))


def test_no_dmux_setup_md():
    assert not os.path.isfile(os.path.join(DOCS, "dmux-setup.md"))


def test_no_dmux_cheatsheet_md():
    assert not os.path.isfile(os.path.join(DOCS, "dmux-cheatsheet.md"))


def test_dmux_architecture_renamed():
    assert os.path.isfile(os.path.join(DOCS, "mentat-architecture.md"))
    assert not os.path.isfile(os.path.join(DOCS, "dmux-architecture.md"))


# S2.7 — ADR 0002 + 0005 no dmux-pane language

def test_adr_0002_no_dmux_pane():
    src = _read(os.path.join(ADR, "0002-holding-branch-over-merge.md"))
    assert "dmux pane" not in src.lower()


def test_adr_0005_no_dmux_pane():
    src = _read(os.path.join(ADR, "0005-ubiquitous-lexicon.md"))
    assert "dmux pane" not in src.lower()


# S2.8 — verify counts

def test_mentat_bin_count():
    entries = [f for f in os.listdir(BIN)
               if os.path.isfile(os.path.join(BIN, f)) and f.startswith("mentat-")]
    assert len(entries) >= 5, f"Expected ≥5 mentat-* in bin/, got: {entries}"


def test_mentat_agents_count():
    entries = [f for f in os.listdir(AGENTS_DIR)
               if f.startswith("mentat-") and f.endswith(".md")]
    assert len(entries) == 4, f"Expected 4 mentat-*.md in agents/, got: {entries}"


# Syntax checks on renamed scripts

def _bash_n(path: str):
    result = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
    assert result.returncode == 0, f"bash -n failed on {path}:\n{result.stderr}"


def test_syntax_mentat_orchestrate():   _bash_n(os.path.join(BIN, "mentat-orchestrate"))
def test_syntax_mentat_track():         _bash_n(os.path.join(BIN, "mentat-track"))
def test_syntax_mentat_container_up():  _bash_n(os.path.join(BIN, "mentat-container-up"))
def test_syntax_mentat_container_run(): _bash_n(os.path.join(BIN, "mentat-container-run"))
def test_syntax_mentat_container_doctor(): _bash_n(os.path.join(BIN, "mentat-container-doctor"))


# S2.1 — harness subdir + output_format contract

HARNESS_DIR = os.path.join(LIB, "harness")
HARNESS_NAMES = ["aider", "amp", "claude-code", "codex", "copilot", "cursor", "gemini", "openhands"]


def test_harness_subdir_has_8_files():
    files = [f for f in os.listdir(HARNESS_DIR) if f.endswith(".sh")]
    assert len(files) == 8, f"Expected 8 harness/*.sh, got: {files}"


def test_harness_files_in_subdir_not_flat():
    for name in HARNESS_NAMES:
        assert not os.path.isfile(os.path.join(LIB, f"harness-{name}.sh")), \
            f"harness-{name}.sh still in lib/ flat (must be in lib/harness/)"
        assert os.path.isfile(os.path.join(HARNESS_DIR, f"{name}.sh")), \
            f"lib/harness/{name}.sh missing"


def test_each_harness_exposes_output_format():
    for name in HARNESS_NAMES:
        fn_name = "harness_" + name.replace("-", "_") + "_output_format"
        path = os.path.join(HARNESS_DIR, f"{name}.sh")
        src = _read(path)
        assert fn_name in src, f"{name}.sh missing {fn_name}"


def test_each_harness_exposes_cmd():
    for name in HARNESS_NAMES:
        fn_name = "harness_" + name.replace("-", "_") + "_cmd"
        path = os.path.join(HARNESS_DIR, f"{name}.sh")
        src = _read(path)
        assert fn_name in src, f"{name}.sh missing {fn_name}"


def test_gate_harness_in_gates():
    src = _read(os.path.join(LIB, "gates.sh"))
    assert "gate_harness" in src, "gate_harness missing from gates.sh"
    assert "declare -f" in src, "gate_harness must use declare -f for structural contract check"
    assert "output_format" in src, "gate_harness must check for output_format function"


def test_gate_harness_rejects_missing_output_format(tmp_path):
    stub = tmp_path / "fake.sh"
    stub.write_text("#!/bin/bash\nharness_fake_cmd() { printf 'fake\\0'; }\n")
    gates = os.path.join(LIB, "gates.sh")
    result = subprocess.run(
        ["bash", "-c", f"source {gates} && gate_harness {stub}"],
        capture_output=True, text=True
    )
    assert result.returncode != 0, "gate_harness must fail when output_format function is missing"


def test_orchestrate_uses_harness_subdir():
    src = _read(os.path.join(BIN, "mentat-orchestrate"))
    assert "harness/${HARNESS}" in src or 'harness/"$HARNESS"' in src or "lib/harness/" in src, \
        "mentat-orchestrate must source from lib/harness/ subdir"
    assert "harness-${HARNESS}" not in src, \
        "mentat-orchestrate still uses old flat harness-${HARNESS} path"


# S2.2 — evals promoted to repo root

def test_evals_at_repo_root():
    assert os.path.isdir(os.path.join(ROOT, "evals", "pytest")), "evals/pytest must be at repo root"
    assert os.path.isdir(os.path.join(ROOT, "evals", "promptfoo")), "evals/promptfoo must be at repo root"


def test_agents_evals_gone():
    assert not os.path.isdir(os.path.join(AGENTS, "evals")), ".agents/evals must be deleted (moved to evals/)"


def test_pyproject_testpaths_updated():
    src = _read(os.path.join(ROOT, "pyproject.toml"))
    assert '"evals/pytest"' in src or "'evals/pytest'" in src or "evals/pytest" in src, \
        "pyproject.toml testpaths must point to evals/pytest"
    assert ".agents/evals" not in src, "pyproject.toml still references .agents/evals"


def test_package_json_eval_script_updated():
    src = _read(os.path.join(ROOT, "package.json"))
    assert "evals/promptfoo/promptfooconfig.yaml" in src, \
        "package.json eval script must reference evals/promptfoo/promptfooconfig.yaml"
    assert ".agents/evals" not in src, "package.json still references .agents/evals"
