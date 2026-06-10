"""G2-S4: mentat-container-run asserts up-invariants via lib/container-state.sh.

Spec (~/.agents/plans/mentat-architecture-revamp-g2-container-quartet.md S4):
  Before exec: call container_id_for($slug) + ensure_workspace_folder. If
  either fails -> exit with explicit error pointing to mentat-container-up.
  No silent "try again with --workdir /".

Verify (from plan):
  - `mentat-container-run 'pwd'` from a worktree where container is up ->
    succeeds, prints worktree path.
  - Same command after `mentat-container-down` -> exits nonzero with
    "container not up: run mentat-container-up".

Design doc (.agents/docs/container-state-design.md): the lib must absorb
mentat-container-run:23,27 (workspaceFolder) and the implicit slug derivation
at line 15. After S4, slug + CID lookup + workspaceFolder presence flow
through the lib helpers; the inline `docker ps -q --filter` block is gone.

Testing strategy mirrors S3 (sister script): static delegation tests +
behavioral end-to-end with PATH-overridden fake docker.
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents" / "bin" / "mentat-container-run"
LIB = ROOT / ".agents" / "bin" / "lib" / "container-state.sh"

# Helpers S4 must invoke. assert_safe_directory is NOT required by the plan
# for -run (only -up handles safe.directory configuration); -run only asserts
# the container exists and the workspaceFolder is present.
LIB_HELPERS_USED_BY_RUN = (
    "container_slug_for_cwd",  # replaces inline `basename "$WT"`
    "container_id_for",  # replaces inline `docker ps -q --filter ...`
    "ensure_workspace_folder",  # asserts target workdir exists pre-exec
)


def _strip_comments(text: str) -> str:
    """Drop full-line comments so source-grep tests cannot be gamed by
    inserting the helper name in a comment without actually calling it."""
    return re.sub(r"^\s*#.*$", "", text, flags=re.MULTILINE)


# -- Static prerequisites ----------------------------------------------------


def test_script_exists_and_executable():
    assert SCRIPT.is_file(), f"script missing: {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"script not executable: {SCRIPT}"


def test_script_bash_syntax_clean():
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, f"bash -n failed:\n{r.stderr}"


def test_lib_exists_as_prerequisite():
    """S4 is blocked-by S2 — the lib must already exist on disk."""
    assert LIB.is_file(), f"S4 cannot delegate to a lib that does not exist: {LIB}"


# -- Delegation: script sources the lib --------------------------------------


def test_script_sources_container_state_lib():
    """S4 core delta: the script must source lib/container-state.sh."""
    text = SCRIPT.read_text()
    pattern = re.compile(r"^\s*(\.|source)\s+.*lib/container-state\.sh\b", re.MULTILINE)
    assert pattern.search(text), "mentat-container-run must source lib/container-state.sh — S4 delegation depends on it"


def test_script_sources_lib_before_first_helper_call():
    """source line must precede any lib-helper call site (excluding
    full-line comments)."""
    text = SCRIPT.read_text()
    lines = text.splitlines()
    source_idx = None
    for i, line in enumerate(lines):
        if re.search(r"^\s*(\.|source)\s+.*lib/container-state\.sh\b", line):
            source_idx = i
            break
    assert source_idx is not None, "no lib source line found"
    for helper in LIB_HELPERS_USED_BY_RUN:
        for j, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(rf"\b{re.escape(helper)}\b", line):
                assert j > source_idx, (
                    f"{helper} called at line {j + 1} before lib sourced (source at line {source_idx + 1})"
                )
                break


# -- Delegation: each helper invoked -----------------------------------------


def test_script_invokes_container_slug_for_cwd():
    """Slug derivation must come from the lib (was: `SLUG=$(basename "$WT")`).
    Comments stripped — doc-mention must not satisfy the assertion."""
    text = _strip_comments(SCRIPT.read_text())
    assert re.search(r"\bcontainer_slug_for_cwd\b", text), (
        "mentat-container-run must derive slug via container_slug_for_cwd"
    )


def test_script_invokes_container_id_for():
    """CID lookup must come from the lib (was: `docker ps -q --filter
    "label=mentat_slug=$SLUG"`)."""
    text = _strip_comments(SCRIPT.read_text())
    assert re.search(r"\bcontainer_id_for\b", text), (
        "mentat-container-run must look up the container via container_id_for"
    )


def test_script_invokes_ensure_workspace_folder():
    """Plan S4 spec: 'Before exec: call container_id_for($slug) +
    ensure_workspace_folder'. Comments stripped."""
    text = _strip_comments(SCRIPT.read_text())
    assert re.search(r"\bensure_workspace_folder\b", text), (
        "mentat-container-run must call ensure_workspace_folder as a pre-flight check (plan S4 spec)"
    )


# -- De-duplication: inline derivations gone ---------------------------------


def test_inline_slug_basename_derivation_removed():
    """Pre-S4 script had `SLUG=$(basename "$WT")`. After S4, that shape must
    be gone — slug comes from the lib."""
    text = SCRIPT.read_text()
    no_comments = _strip_comments(text)
    bad = re.search(
        r'\bSLUG\s*=\s*"?\$\(basename\s+"\$(?:WT|PWD)"\s*\)',
        no_comments,
    )
    assert bad is None, (
        'inline `SLUG=$(basename "$WT")` must be replaced by '
        "container_slug_for_cwd call "
        f"(found: {bad.group(0) if bad else ''!r})"
    )


def test_inline_docker_ps_filter_lookup_removed():
    """Pre-S4 script had `CID="$(docker ps -q --filter
    "label=mentat_slug=$SLUG")"`. The bare running-container query must be
    lib-mediated."""
    text = SCRIPT.read_text()
    no_comments = _strip_comments(text)
    running_filter_pattern = re.compile(r'docker\s+ps\s+-q\s+--filter\s+"label=mentat_slug=\$SLUG"')
    assert not running_filter_pattern.search(no_comments), (
        "running-container existence check via inline "
        '`docker ps -q --filter "label=mentat_slug=$SLUG"` must be '
        "replaced by container_id_for"
    )


# -- Ordering: pre-flight asserts fire before docker exec --------------------


def test_ensure_workspace_folder_fires_before_exec():
    """Plan S4: 'Before exec: ... ensure_workspace_folder.' The first call
    site of ensure_workspace_folder must precede the `exec docker exec ...`
    line. Otherwise the precheck is a no-op."""
    text = SCRIPT.read_text()
    lines = text.splitlines()
    first_ws = None
    first_exec = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if first_ws is None and re.search(r"\bensure_workspace_folder\b", line):
            first_ws = i
        if first_exec is None and re.search(r"^\s*exec\s+docker\s+exec\b", line):
            first_exec = i
    assert first_ws is not None, "script must call ensure_workspace_folder somewhere"
    assert first_exec is not None, "script must still terminate in `exec docker exec ...` (no behavior change)"
    assert first_ws < first_exec, (
        f"ensure_workspace_folder at line {first_ws + 1} must precede "
        f"`exec docker exec` at line {first_exec + 1} — otherwise the "
        "precheck runs after exec replaces the process"
    )


def test_container_id_for_fires_before_exec():
    """Plan S4: 'Before exec: call container_id_for($slug) ...'."""
    text = SCRIPT.read_text()
    lines = text.splitlines()
    first_cid = None
    first_exec = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if first_cid is None and re.search(r"\bcontainer_id_for\b", line):
            first_cid = i
        if first_exec is None and re.search(r"^\s*exec\s+docker\s+exec\b", line):
            first_exec = i
    assert first_cid is not None, "script must call container_id_for"
    assert first_exec is not None, "script must still exec docker exec"
    assert first_cid < first_exec, (
        f"container_id_for at line {first_cid + 1} must precede `exec docker exec` at line {first_exec + 1}"
    )


# -- No silent fallback / fail-loud contract ---------------------------------


def test_no_silent_fallback_to_workdir_root():
    """Plan S4 forbids: 'No silent "try again with --workdir /"' fallback."""
    text = SCRIPT.read_text()
    no_comments = _strip_comments(text)
    bad = re.search(r'--workdir\s+(?:["\']?/["\'\s]|"/")', no_comments)
    assert bad is None, (
        "introducing `--workdir /` fallback violates plan S4 no-silent-"
        f"fallback rule (matched: {bad.group(0) if bad else ''!r})"
    )


def test_assert_helpers_failures_are_fatal():
    """Lib helpers signal failure via nonzero exit. Calls to
    ensure_workspace_folder / container_id_for must not be swallowed with
    `|| true`. set -euo pipefail (or set -e) must remain."""
    text = SCRIPT.read_text()
    assert re.search(r"set\s+-e[^=]*u[^=]*o\s+pipefail|set\s+-euo\s+pipefail|set\s+-e", text), (
        "script must keep `set -euo pipefail` so lib helper nonzero exits abort the script"
    )
    bad = re.search(
        r"\b(ensure_workspace_folder|container_id_for)\b[^\n]*\|\|\s*true\b",
        text,
    )
    assert bad is None, (
        f"swallowing lib helper failure with `|| true` violates fail-loud "
        f"contract (matched: {bad.group(0) if bad else ''!r})"
    )


# -- Error-message contract: name mentat-container-up ------------------------


def test_error_message_points_to_mentat_container_up():
    """Plan S4 verify: 'exits nonzero with "container not up: run
    mentat-container-up"'. The diagnostic must name the recovery command."""
    text = SCRIPT.read_text()
    # The script itself must contain the recovery hint in an error path
    # (script may also delegate to the lib's error message, which already
    # mentions mentat-container-up). Accept either form.
    assert "mentat-container-up" in text, (
        "script must emit an error message naming mentat-container-up as the recovery action (plan S4 verify)"
    )


# -- Usage guard preserved ---------------------------------------------------


def test_script_usage_guard_preserved():
    """Pre-S4 script aborted with `usage: mentat-container-run '<command>'`
    when called with no args. The refactor must not regress this guard."""
    r = subprocess.run(
        [str(SCRIPT)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert r.returncode != 0, (
        f"script must exit nonzero with no args; got rc=0\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )
    assert "usage" in r.stderr.lower() or "command" in r.stderr.lower(), (
        f"abort msg must name cause; got stderr={r.stderr!r}"
    )


def test_script_aborts_outside_worktree(tmp_path):
    """The `[ -f "$PWD/.git" ]` guard must still fire — refactor must not
    re-order it below a lib call that depends on docker."""
    r = subprocess.run(
        [str(SCRIPT), "echo hi"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert r.returncode != 0, (
        f"script must exit nonzero outside a git worktree; got rc=0\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )
    assert "worktree" in r.stderr.lower() or "git" in r.stderr.lower(), (
        f"abort msg must name cause; got stderr={r.stderr!r}"
    )


# -- Behavioral end-to-end: container up -> exec reached ---------------------


def _make_fake_bin(bin_dir: Path, name: str, body: str) -> Path:
    p = bin_dir / name
    p.write_text(body)
    p.chmod(0o755)
    return p


def _fake_worktree(tmp_path: Path, slug: str) -> Path:
    wt = tmp_path / slug
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: /fake/.git/worktrees/{slug}\n")
    return wt


def test_container_up_path_invokes_lib_helpers_end_to_end(tmp_path):
    """Plan S4 verify line: 'container is up -> succeeds'. Static delegation
    tests prove the helper NAMES land in the script; this proves they
    actually RUN with the expected docker call shapes — closes the gap
    test-reviewer flags ('verify lines not behaviorally exercised').

    Strategy: fake worktree + PATH-overridden fake docker that logs every
    call. Run the script with a dummy command, assert the docker call log
    shows ps-filter + exec-test-d + exec-bash-lc shapes.
    """
    slug = "myslugA"
    wt = _fake_worktree(tmp_path, slug)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"

    # Fake docker: container present, test -d succeeds, final exec records
    # the command and exits 0.
    _make_fake_bin(
        bin_dir,
        "docker",
        textwrap.dedent(f"""\
        #!/bin/bash
        echo "docker $*" >> {log}
        case "$1" in
          ps)
            if [[ "$*" == *"mentat_slug={slug}"* ]]; then
              echo fakecidA
            fi
            ;;
          exec)
            # ensure_workspace_folder: `docker exec <cid> test -d <ws>`
            if [[ "$*" == *"test -d"* ]]; then exit 0; fi
            # final exec: docker exec --workdir ... -u vscode <cid> bash -lc ...
            exit 0
            ;;
        esac
        """),
    )

    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(
        [str(SCRIPT), "echo hello"],
        cwd=str(wt),
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, (
        f"container-up path must succeed; got rc={r.returncode}\n"
        f"stdout={r.stdout!r}\nstderr={r.stderr!r}\n"
        f"calls={log.read_text() if log.exists() else '(no log)'}"
    )

    calls = log.read_text() if log.exists() else ""
    # container_id_for shape:
    assert "ps -q" in calls and f"mentat_slug={slug}" in calls, (
        f"container_id_for must invoke `docker ps -q --filter label=mentat_slug=<slug>`; got calls:\n{calls}"
    )
    # ensure_workspace_folder shape:
    assert "test -d" in calls, (
        f"ensure_workspace_folder must invoke `docker exec <cid> test -d <ws>`; got calls:\n{calls}"
    )
    # Final exec: bash -lc carries the user CMD; --workdir present.
    assert "bash -lc" in calls and "echo hello" in calls, (
        f"final docker exec must carry the user command via bash -lc; got calls:\n{calls}"
    )
    assert "--workdir" in calls, f"final docker exec must specify --workdir <ws>; got calls:\n{calls}"


def test_container_down_path_fails_loud_pointing_to_up(tmp_path):
    """Plan S4 verify: 'after mentat-container-down -> exits nonzero with
    "container not up: run mentat-container-up"'.

    Fake docker returns no CID for the slug -> container_id_for exits 1 ->
    script aborts with the recovery hint pointing to mentat-container-up.
    """
    slug = "myslugB"
    wt = _fake_worktree(tmp_path, slug)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"

    # Fake docker: ps query returns empty (no container) -> container_id_for
    # exits 1.
    _make_fake_bin(
        bin_dir,
        "docker",
        textwrap.dedent(f"""\
        #!/bin/bash
        echo "docker $*" >> {log}
        case "$1" in
          ps) ;;  # empty stdout -> container_id_for returns 1
          exec) exit 0 ;;
        esac
        """),
    )

    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(
        [str(SCRIPT), "echo hi"],
        cwd=str(wt),
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode != 0, (
        f"missing container must produce nonzero exit; got rc={r.returncode}\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )
    # Recovery hint must surface — either via script's own error or lib's
    # diagnostic ("no container for slug=...").
    combined = (r.stderr + r.stdout).lower()
    assert "mentat-container-up" in combined or "container not up" in combined or "no container for slug" in combined, (
        f"error must point user to mentat-container-up; got stderr={r.stderr!r}"
    )
    # ensure_workspace_folder must NOT have been reached (no CID -> abort
    # before workspace probe).
    calls = log.read_text() if log.exists() else ""
    assert "test -d" not in calls, (
        f"ensure_workspace_folder must not fire when container is absent; got calls:\n{calls}"
    )


# -- Lib-coverage drift guard ------------------------------------------------


def test_all_required_invariants_have_lib_calls():
    """Drift guard — if a future patch reintroduces inline derivation,
    one of these searches goes to zero."""
    text = SCRIPT.read_text()
    invariants = {
        "slug": r"\bcontainer_slug_for_cwd\b",
        "container-id": r"\bcontainer_id_for\b",
        "workspaceFolder": r"\bensure_workspace_folder\b",
    }
    missing = [name for name, pat in invariants.items() if not re.search(pat, text)]
    assert not missing, f"invariants missing lib-call sites in mentat-container-run: {missing}"
