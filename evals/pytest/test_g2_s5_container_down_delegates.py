"""G2-S5: mentat-container-down delegates to lib/container-state.sh.

Spec (~/.agents/plans/mentat-architecture-revamp-g2-container-quartet.md S5):
  Replace local container ID lookup with `container_id_for`. Tear-down
  asserts the container belonged to the current slug before removing.

Verify (from plan):
  - `mentat-container-down` from worktree A only stops A's container, not B's.
  - Down on already-down container exits 0 cleanly.

Design doc (.agents/docs/container-state-design.md): the lib must absorb
mentat-container-down's slug derivation (`basename "$PWD"`) and container-ID
lookup (`docker ps -aq --filter "label=mentat_slug=$SLUG"`). The label-filter
itself is the ownership assertion — `docker rm -f` is only ever called on
containers carrying the current slug's label.

Testing strategy mirrors S4: static delegation tests + behavioral end-to-end
with PATH-overridden fake docker.
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents" / "bin" / "mentat-container-down"
LIB = ROOT / ".agents" / "bin" / "lib" / "container-state.sh"

# Helpers S5 must invoke. -down doesn't need ensure_workspace_folder or
# assert_safe_directory — it asserts ownership (slug-label filter) and removes.
LIB_HELPERS_USED_BY_DOWN = (
    "container_slug_for_cwd",  # replaces inline `basename "$PWD"`
    "container_id_for",  # canonical CID/ownership probe
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
    """S5 is blocked-by S2 — the lib must already exist on disk."""
    assert LIB.is_file(), f"S5 cannot delegate to a lib that does not exist: {LIB}"


# -- Delegation: script sources the lib --------------------------------------


def test_script_sources_container_state_lib():
    """S5 core delta: the script must source lib/container-state.sh."""
    text = SCRIPT.read_text()
    pattern = re.compile(r"^\s*(\.|source)\s+.*lib/container-state\.sh\b", re.MULTILINE)
    assert pattern.search(text), (
        "mentat-container-down must source lib/container-state.sh — S5 delegation depends on it"
    )


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
    for helper in LIB_HELPERS_USED_BY_DOWN:
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
    """Slug derivation must come from the lib (was: `SLUG=$(basename "$PWD")`).
    Comments stripped — doc-mention must not satisfy the assertion."""
    text = _strip_comments(SCRIPT.read_text())
    assert re.search(r"\bcontainer_slug_for_cwd\b", text), (
        "mentat-container-down must derive slug via container_slug_for_cwd"
    )


def test_script_invokes_container_id_for():
    """Plan S5 spec: 'Replace local container ID lookup with container_id_for'.
    Comments stripped."""
    text = _strip_comments(SCRIPT.read_text())
    assert re.search(r"\bcontainer_id_for\b", text), (
        "mentat-container-down must look up / probe the container via container_id_for (plan S5 spec)"
    )


# -- De-duplication: inline derivations gone ---------------------------------


def test_inline_slug_basename_derivation_removed():
    """Pre-S5 script had `SLUG=$(basename "$PWD")`. After S5, that shape must
    be gone — slug comes from the lib."""
    text = SCRIPT.read_text()
    no_comments = _strip_comments(text)
    bad = re.search(
        r'\bSLUG\s*=\s*"?\$\(basename\s+"\$(?:WT|PWD)"\s*\)',
        no_comments,
    )
    assert bad is None, (
        'inline `SLUG=$(basename "$PWD")` must be replaced by '
        "container_slug_for_cwd call "
        f"(found: {bad.group(0) if bad else ''!r})"
    )


# -- Ordering: ownership probe fires before rm -------------------------------


def test_container_id_for_fires_before_docker_rm():
    """Plan S5: 'Tear-down asserts the container belonged to the current slug
    before removing.' container_id_for is the ownership probe — its first call
    site must precede the first `docker rm` (or `docker rm -f`)."""
    text = SCRIPT.read_text()
    lines = text.splitlines()
    first_cid = None
    first_rm = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if first_cid is None and re.search(r"\bcontainer_id_for\b", line):
            first_cid = i
        if first_rm is None and re.search(r"\bdocker\s+rm\b", line):
            first_rm = i
    assert first_cid is not None, "script must call container_id_for"
    assert first_rm is not None, "script must still call `docker rm` to tear down"
    assert first_cid < first_rm, (
        f"container_id_for at line {first_cid + 1} must precede `docker rm` "
        f"at line {first_rm + 1} — ownership probe runs before destructive op"
    )


# -- Ownership assertion: slug label gates every docker rm -------------------


def test_docker_rm_calls_are_slug_label_gated():
    """Every `docker rm` invocation must operate on a value derived from a
    slug-labeled query (variable expansion of an ids-from-label-filter list).
    The script must never `docker rm` a bare container name or by image — that
    would risk removing a sibling slug's container. We accept either the
    label-filter list ($ids style) or a `container_id_for "$SLUG"` result.
    """
    text = SCRIPT.read_text()
    no_comments = _strip_comments(text)
    rm_lines = [line for line in no_comments.splitlines() if re.search(r"\bdocker\s+rm\b", line)]
    assert rm_lines, "script must still call docker rm"
    label_filter_assigned = bool(
        re.search(r'docker\s+ps\s+-aq\s+--filter\s+"label=mentat_slug=\$SLUG"', no_comments)
        or re.search(r'docker\s+ps\s+-aq\s+--filter\s+"label=mentat_slug=\$\{?SLUG\}?"', no_comments)
    )
    cid_assigned_via_lib = bool(
        re.search(r'\bCID\s*=\s*"\$\(\s*container_id_for\b', no_comments)
        or re.search(r'\bcid\s*=\s*"\$\(\s*container_id_for\b', no_comments)
    )
    for line in rm_lines:
        looks_slug_gated = (bool(re.search(r"\$\{?ids\}?", line)) and label_filter_assigned) or (
            bool(re.search(r"\$\{?CID\}?|\$\{?cid\}?", line)) and cid_assigned_via_lib
        )
        assert looks_slug_gated, (
            f"docker rm line must operate on slug-label-derived ids OR a "
            f"container_id_for-derived CID; found: {line.strip()!r}"
        )


# -- Idempotency contract: no container -> exit 0 ----------------------------


def test_script_exits_zero_on_already_down(tmp_path):
    """Plan S5 verify: 'Down on already-down container exits 0 cleanly.'

    Fake docker reports empty for both `ps -q` (running) and `ps -aq` (any).
    Script must exit 0 without calling docker rm.
    """
    slug = "downidempotent"
    wt = tmp_path / slug
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: /fake/.git/worktrees/{slug}\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"

    _make_fake_bin(
        bin_dir,
        "docker",
        textwrap.dedent(f"""\
        #!/bin/bash
        echo "docker $*" >> {log}
        case "$1" in
          ps) ;;  # empty stdout — no containers anywhere
          rm) echo "BUG: docker rm called when no container exists" >&2; exit 99 ;;
        esac
        """),
    )

    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(
        [str(SCRIPT)],
        cwd=str(wt),
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, (
        f"already-down must exit 0; got rc={r.returncode}\n"
        f"stdout={r.stdout!r}\nstderr={r.stderr!r}\n"
        f"calls={log.read_text() if log.exists() else '(no log)'}"
    )
    calls = log.read_text() if log.exists() else ""
    assert "rm" not in calls.split("docker ")[1:] if "docker " in calls else True, (
        f"docker rm must not fire when no container exists; calls=\n{calls}"
    )
    # Stronger: assert no `docker rm` line in calls log at all.
    for line in calls.splitlines():
        assert not re.match(r"docker\s+rm\b", line), (
            f"docker rm called on idempotent path: {line!r}\nfull calls:\n{calls}"
        )


# -- Outside-worktree guard preserved ----------------------------------------


def test_script_aborts_outside_worktree(tmp_path):
    """The `[ -f "$PWD/.git" ]` guard must still fire — refactor must not
    re-order it below a lib call that depends on docker."""
    r = subprocess.run(
        [str(SCRIPT)],
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


# -- Behavioral end-to-end ---------------------------------------------------


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


def test_down_only_targets_current_slug_label(tmp_path):
    """Plan S5 verify: 'from worktree A only stops A's container, not B's.'

    Fake docker logs every call. Run down from worktree A. Assert every
    `docker ps -aq` / `docker rm` invocation carries `mentat_slug=A`'s label,
    never sibling slug B's.
    """
    slug_a = "slugA"
    slug_b = "slugB"
    wt_a = _fake_worktree(tmp_path, slug_a)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"

    # Fake docker: returns fake CID for slug A; would return separate CID for
    # slug B (but slug B's filter must never appear in calls).
    _make_fake_bin(
        bin_dir,
        "docker",
        textwrap.dedent(f"""\
        #!/bin/bash
        echo "docker $*" >> {log}
        case "$1" in
          ps)
            if [[ "$*" == *"mentat_slug={slug_a}"* ]]; then
              echo fakecidA
            elif [[ "$*" == *"mentat_slug={slug_b}"* ]]; then
              echo fakecidB
            fi
            ;;
          rm) exit 0 ;;
        esac
        """),
    )

    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(
        [str(SCRIPT)],
        cwd=str(wt_a),
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, (
        f"down on slug A must succeed; got rc={r.returncode}\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )
    calls = log.read_text() if log.exists() else ""
    # Slug A must appear in ps filter (ownership probe and/or cleanup).
    assert f"mentat_slug={slug_a}" in calls, f"ps filter must scope to slug A; got calls:\n{calls}"
    # Slug B must NEVER appear — the script must not probe siblings.
    assert f"mentat_slug={slug_b}" not in calls, f"down on slug A must not query slug B's label; got calls:\n{calls}"
    # rm must have fired against the slug-A-derived CID(s) only.
    rm_lines = [line for line in calls.splitlines() if re.match(r"docker\s+rm\b", line)]
    assert rm_lines, f"docker rm must fire when slug A's container exists; calls=\n{calls}"
    for line in rm_lines:
        assert "fakecidA" in line, (
            f"docker rm line must target slug-A CID (fakecidA); found: {line!r}\nfull calls:\n{calls}"
        )
        assert "fakecidB" not in line, (
            f"docker rm line must not target slug-B CID; found: {line!r}\nfull calls:\n{calls}"
        )


def test_down_running_container_invokes_lib_helpers_end_to_end(tmp_path):
    """Plan S5 verify (composite): the down path actually fires the lib
    helpers, not just mentions them. Closes the gap test-reviewer flags
    ('verify lines not behaviorally exercised').

    Strategy: fake worktree + PATH-overridden fake docker. Slug present in
    container_id_for's `ps -q` response -> ownership probe succeeds -> rm
    fires.
    """
    slug = "endtoendslug"
    wt = _fake_worktree(tmp_path, slug)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"

    _make_fake_bin(
        bin_dir,
        "docker",
        textwrap.dedent(f"""\
        #!/bin/bash
        echo "docker $*" >> {log}
        case "$1" in
          ps)
            if [[ "$*" == *"mentat_slug={slug}"* ]]; then
              echo fakecidE
            fi
            ;;
          rm) exit 0 ;;
        esac
        """),
    )

    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(
        [str(SCRIPT)],
        cwd=str(wt),
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, (
        f"down path must succeed; got rc={r.returncode}\n"
        f"stdout={r.stdout!r}\nstderr={r.stderr!r}\n"
        f"calls={log.read_text() if log.exists() else '(no log)'}"
    )

    calls = log.read_text() if log.exists() else ""
    # container_id_for shape: `docker ps -q --filter label=mentat_slug=<slug>`
    ps_q_lines = [line for line in calls.splitlines() if re.match(r"docker\s+ps\s+-q\b", line)]
    assert ps_q_lines, f"container_id_for must invoke `docker ps -q ...`; got calls:\n{calls}"
    assert any(f"mentat_slug={slug}" in line for line in ps_q_lines), (
        f"`docker ps -q` must carry slug label; got ps -q lines:\n{ps_q_lines}"
    )
    # Removal fires.
    rm_lines = [line for line in calls.splitlines() if re.match(r"docker\s+rm\b", line)]
    assert rm_lines, f"docker rm must fire on running-slug down; calls=\n{calls}"


# -- Lib-coverage drift guard ------------------------------------------------


def test_all_required_invariants_have_lib_calls():
    """Drift guard — if a future patch reintroduces inline derivation,
    one of these searches goes to zero."""
    text = SCRIPT.read_text()
    invariants = {
        "slug": r"\bcontainer_slug_for_cwd\b",
        "container-id": r"\bcontainer_id_for\b",
    }
    missing = [name for name, pat in invariants.items() if not re.search(pat, text)]
    assert not missing, f"invariants missing lib-call sites in mentat-container-down: {missing}"
