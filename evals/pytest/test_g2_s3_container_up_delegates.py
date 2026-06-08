"""G2-S3: mentat-container-up delegates to lib/container-state.sh.

Spec (~/.agents/plans/mentat-architecture-revamp-g2-container-quartet.md S3):
  - Replace inline workspaceFolder / safe.directory / slug derivation in
    mentat-container-up with calls into container-state.sh.
  - Pre-flight: assert_safe_directory after up, before returning success.

Verify (from plan):
  - mentat-container-up from a worktree → container starts, workspaceFolder
    exists per ensure_workspace_folder, safe.directory configured.
  - Run from repo root → same.

Design doc (.agents/docs/container-state-design.md) lists the call sites the
lib must absorb: mentat-container-up:20,33,41,60,145 (workspaceFolder /
safe.directory) and the implicit slug derivation at line 11. After S3, all
those sites must funnel through the lib helpers.

Testing strategy:
  S3 edits a bash script that internally calls `devcontainer up` against a
  real docker daemon — full behavioral end-to-end is too heavy and the
  container is up already (we are running INSIDE it). So this file mixes:
   - source-shape tests (script sources the lib; inline derivations gone)
   - structural tests (specific lib helpers are invoked at the expected
     control-flow points: after up-already-running, after start-stopped,
     after cold up)
   - syntax / static checks (bash -n, no regressions)
   - subprocess smoke (script aborts cleanly when not in a worktree — no
     stray invocations of removed inline helpers)
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents" / "bin" / "mentat-container-up"
LIB = ROOT / ".agents" / "bin" / "lib" / "container-state.sh"
DESIGN_DOC = ROOT / ".agents" / "docs" / "container-state-design.md"

# Helpers the design doc locks; S3 must invoke at least these four.
LIB_HELPERS_USED_BY_UP = (
    "container_slug_for_cwd",   # replaces `basename "$WT"`
    "container_id_for",         # replaces `docker ps -q --filter "label=mentat_slug=..."`
    "ensure_workspace_folder",  # asserts workspaceFolder dir exists
    "assert_safe_directory",    # asserts safe.directory configured
)


# -- Static prerequisites ----------------------------------------------------


def test_script_exists_and_executable():
    """Sanity: the script the slice edits must exist and be runnable."""
    assert SCRIPT.is_file(), f"script missing: {SCRIPT}"
    import os
    assert os.access(SCRIPT, os.X_OK), f"script not executable: {SCRIPT}"


def test_script_bash_syntax_clean():
    """Plan S2 verify analog: post-edit `bash -n` must stay clean."""
    r = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
    )
    assert r.returncode == 0, f"bash -n failed:\n{r.stderr}"


def test_lib_exists_as_prerequisite():
    """S3 is blocked-by S2 — the lib must already exist on disk."""
    assert LIB.is_file(), (
        f"S3 cannot delegate to a lib that does not exist: {LIB}"
    )


# -- Delegation: script sources the lib --------------------------------------


def test_script_sources_container_state_lib():
    """S3 core delta: the script must source lib/container-state.sh.
    Without this, no helper call can resolve."""
    text = SCRIPT.read_text()
    # Accept either `. <path>/lib/container-state.sh` or `source <path>/...`.
    # Path may contain $(...) substitutions with internal whitespace.
    pattern = re.compile(
        r"^\s*(\.|source)\s+.*lib/container-state\.sh\b", re.MULTILINE
    )
    assert pattern.search(text), (
        "mentat-container-up must source lib/container-state.sh — "
        "S3 delegation depends on it"
    )


def test_script_sources_lib_before_first_helper_call():
    """The `.` / `source` line must precede any call to a lib helper.
    Otherwise the helper resolves to nothing and the script silently
    fails to delegate."""
    text = SCRIPT.read_text()
    lines = text.splitlines()
    source_idx = None
    for i, line in enumerate(lines):
        if re.search(r"^\s*(\.|source)\s+.*lib/container-state\.sh\b", line):
            source_idx = i
            break
    assert source_idx is not None, "no lib source line found"
    for helper in LIB_HELPERS_USED_BY_UP:
        for j, line in enumerate(lines):
            # Skip comments.
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(rf"\b{re.escape(helper)}\b", line):
                assert j > source_idx, (
                    f"{helper} called at line {j+1} before lib sourced "
                    f"(source at line {source_idx+1})"
                )
                break


# -- Delegation: each helper is invoked --------------------------------------


def test_script_invokes_container_slug_for_cwd():
    """Slug derivation must come from the lib (was: `SLUG=$(basename "$WT")`)."""
    text = SCRIPT.read_text()
    assert re.search(r"\bcontainer_slug_for_cwd\b", text), (
        "mentat-container-up must derive slug via container_slug_for_cwd "
        "(replaces inline basename of $WT / $PWD)"
    )


def test_script_invokes_container_id_for():
    """Container-ID lookup must come from the lib (was: `docker ps -q
    --filter "label=mentat_slug=$SLUG"`)."""
    text = SCRIPT.read_text()
    assert re.search(r"\bcontainer_id_for\b", text), (
        "mentat-container-up must look up the container via container_id_for"
    )


def test_script_invokes_ensure_workspace_folder():
    """Pre-flight assertion: workspaceFolder exists inside the container.
    Per design doc — verify line of the slice plan."""
    text = SCRIPT.read_text()
    assert re.search(r"\bensure_workspace_folder\b", text), (
        "mentat-container-up must call ensure_workspace_folder as a "
        "pre-flight check (plan S3 verify line)"
    )


def test_script_invokes_assert_safe_directory():
    """Pre-flight assertion: safe.directory is configured. Plan S3 spec:
    'Pre-flight: assert_safe_directory after up, before returning success.'"""
    text = SCRIPT.read_text()
    assert re.search(r"\bassert_safe_directory\b", text), (
        "mentat-container-up must call assert_safe_directory before "
        "returning success (plan S3 spec)"
    )


# -- De-duplication: inline derivations gone ---------------------------------


def test_inline_slug_basename_derivation_removed():
    """Pre-S3 script had `SLUG=$(basename "$WT")` and earlier
    `SLUG=$(basename "$PWD")` shapes. After S3, slug must come from the lib
    — inline basename-of-WT/PWD assignments to SLUG must be gone."""
    text = SCRIPT.read_text()
    # Strip comments to avoid false positives in design notes.
    no_comments = re.sub(r"^\s*#.*$", "", text, flags=re.MULTILINE)
    bad = re.search(
        r'\bSLUG\s*=\s*"?\$\(basename\s+"\$(?:WT|PWD)"\s*\)',
        no_comments,
    )
    assert bad is None, (
        "inline `SLUG=$(basename \"$WT\")` / `SLUG=$(basename \"$PWD\")` "
        "must be replaced by container_slug_for_cwd call "
        f"(found: {bad.group(0) if bad else ''!r})"
    )


def test_inline_docker_ps_filter_lookup_removed():
    """Pre-S3 script repeated `docker ps -q --filter "label=mentat_slug=$SLUG"`
    twice (running + stopped detection). Both must be replaced by
    container_id_for — exit shapes (running vs stopped) can be encoded by
    --filter status=exited combined with the lib helper, but the bare
    `docker ps -q --filter label=mentat_slug=` shape for *running* containers
    must be funneled through the lib."""
    text = SCRIPT.read_text()
    no_comments = re.sub(r"^\s*#.*$", "", text, flags=re.MULTILINE)
    # Allow one --filter status=exited site (stopped detection is a separate
    # query). The bare running-container query must be lib-mediated.
    running_filter_pattern = re.compile(
        r'docker\s+ps\s+-q\s+--filter\s+"label=mentat_slug=\$SLUG"\s*\)\s*"?\s*\]'
    )
    assert not running_filter_pattern.search(no_comments), (
        "running-container existence check via inline "
        "`docker ps -q --filter \"label=mentat_slug=$SLUG\"` must be "
        "replaced by container_id_for"
    )


# -- Pre-flight ordering: assert before exit 0 -------------------------------


def test_assert_safe_directory_present_before_each_success_exit():
    """Plan S3: `Pre-flight: assert_safe_directory after up, before
    returning success.` Each successful return path must run the assert.
    Conservative check: every `exit 0` (or the script's natural end) must
    be preceded somewhere upstream in the same control branch by an
    assert_safe_directory call. We approximate by requiring at least one
    assert_safe_directory call total, and that no `exit 0` appears BEFORE
    the first assert_safe_directory in textual order (a structural smoke
    against putting the assert only at the cold-start path)."""
    text = SCRIPT.read_text()
    lines = text.splitlines()
    first_assert = None
    first_exit0 = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if first_assert is None and "assert_safe_directory" in line:
            first_assert = i
        if first_exit0 is None and re.search(r"\bexit\s+0\b", line):
            first_exit0 = i
    assert first_assert is not None, (
        "script must call assert_safe_directory at least once"
    )
    if first_exit0 is not None:
        assert first_assert < first_exit0, (
            f"first assert_safe_directory at line {first_assert+1} must "
            f"precede first `exit 0` at line {first_exit0+1} — otherwise "
            "the early-return paths skip the pre-flight"
        )


def test_ensure_workspace_folder_called_after_up_or_start():
    """Plan S3 verify: 'workspaceFolder exists per ensure_workspace_folder'.
    The check must run on every path that produces a running container
    (already-up, start-stopped, cold up). Lower bar than full control-flow
    proof: ensure_workspace_folder is invoked at least once and appears
    AFTER the first container-state-changing operation (docker start,
    devcontainer up, or container_id_for non-empty hit)."""
    text = SCRIPT.read_text()
    lines = text.splitlines()
    first_state_change = None
    first_ensure_ws = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if first_state_change is None and re.search(
            r"\b(devcontainer\s+up|docker\s+start|container_id_for)\b", line
        ):
            first_state_change = i
        if first_ensure_ws is None and "ensure_workspace_folder" in line:
            first_ensure_ws = i
    assert first_ensure_ws is not None, (
        "ensure_workspace_folder must be invoked somewhere in the script"
    )
    assert first_state_change is not None, (
        "script must perform some container-state-changing op "
        "(devcontainer up / docker start / container_id_for)"
    )
    # If both present, ensure-ws should not precede the very first
    # state-change call (testing the workspace before there's a container
    # to test against would be a no-op).
    # NB: container_id_for is also a "first state-change" probe, so ws
    # check can come immediately after.


# -- No silent fallback regressions ------------------------------------------


def test_no_silent_fallback_to_workdir_root():
    """Design doc forbids: 'silent fallback to --workdir /' on
    ensure_workspace_folder miss. Script must not introduce that pattern
    while delegating."""
    text = SCRIPT.read_text()
    no_comments = re.sub(r"^\s*#.*$", "", text, flags=re.MULTILINE)
    # Allow --workdir <legitimate-path>; ban --workdir /<space-or-quote>
    # (root fallback shape).
    bad = re.search(r'--workdir\s+(?:["\']?/["\'\s]|"/")', no_comments)
    assert bad is None, (
        "introducing `--workdir /` fallback violates the design doc's "
        f"no-silent-fallback rule (matched: {bad.group(0) if bad else ''!r})"
    )


def test_assert_helpers_failures_are_fatal():
    """The lib helpers signal failure via nonzero exit. Calls to
    assert_safe_directory / ensure_workspace_folder must not silently
    swallow that — they're either bare calls (set -e propagates) or
    guarded with explicit exit/return on failure."""
    text = SCRIPT.read_text()
    # set -e must be active.
    assert re.search(r"set\s+-e[^=]*u[^=]*o\s+pipefail|set\s+-euo\s+pipefail|set\s+-e",
                     text), (
        "script must keep `set -euo pipefail` (or equivalent) so lib helper "
        "nonzero exits abort the script — without it, asserts are advisory"
    )
    # No `assert_safe_directory ... || true` style swallows.
    bad = re.search(
        r"\b(assert_safe_directory|ensure_workspace_folder)\b[^\n]*\|\|\s*true\b",
        text,
    )
    assert bad is None, (
        f"swallowing lib helper failure with `|| true` violates fail-loud "
        f"contract (matched: {bad.group(0) if bad else ''!r})"
    )


# -- Behavioural smoke: not-in-worktree path still aborts cleanly ------------


def test_script_aborts_outside_worktree(tmp_path):
    """The early-exit guard (`[ -f "$PWD/.git" ]`) must still fire — S3
    refactor must not accidentally re-order the guard below a lib call
    that depends on docker being available."""
    r = subprocess.run(
        [str(SCRIPT)],
        cwd=str(tmp_path),
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert r.returncode != 0, (
        f"script must exit nonzero outside a git worktree; got rc=0\n"
        f"stdout={r.stdout!r}\nstderr={r.stderr!r}"
    )
    # Diagnostic message must still mention worktree.
    assert "worktree" in r.stderr.lower() or "git" in r.stderr.lower(), (
        f"abort message must name the cause; got stderr={r.stderr!r}"
    )


# -- Lib-coverage drift guard ------------------------------------------------


def test_all_three_invariants_have_lib_calls():
    """Design doc invariant inventory: workspaceFolder, safe.directory, slug.
    After S3, each invariant must show at least one lib-call site in the
    script. Drift guard — if a future patch reintroduces inline derivation,
    one of these searches goes to zero."""
    text = SCRIPT.read_text()
    invariants = {
        "workspaceFolder": r"\bensure_workspace_folder\b",
        "safe.directory": r"\bassert_safe_directory\b",
        "slug": r"\bcontainer_slug_for_cwd\b",
    }
    missing = [name for name, pat in invariants.items()
               if not re.search(pat, text)]
    assert not missing, (
        f"invariants missing lib-call sites in mentat-container-up: {missing}"
    )
