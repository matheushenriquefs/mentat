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


def test_harness_map_in_lib():
    assert os.path.isfile(os.path.join(LIB, "harness-map.jq"))


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
