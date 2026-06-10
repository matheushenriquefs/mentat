"""G2-S6: mentat-container-doctor delegates to lib/container-state.sh.

Spec (~/.agents/plans/mentat-architecture-revamp-g2-container-quartet.md S6):
  Doctor's diagnostic walk uses `container-state.sh` predicates. Output:
  which invariants hold, which fail, exactly which path is missing.

Verify (from plan):
  - doctor against a broken worktree (e.g. one where `workspaceFolder`
    missing) names the missing path.
  - doctor against a healthy worktree returns clean.

Design (.agents/docs/container-state-design.md): the doctor must surface the
three lib invariants — slug-from-cwd, container-id-for-slug,
workspaceFolder-exists, and safe.directory-set — without re-deriving them.
A `FAIL` line must name the missing path so the user knows what to repair.

Testing strategy mirrors S5: static delegation tests + behavioral end-to-end
with PATH-overridden fake docker.
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents" / "bin" / "mentat-container-doctor"
LIB = ROOT / ".agents" / "bin" / "lib" / "container-state.sh"

# Helpers S6 must invoke. Doctor surfaces all three state invariants —
# slug, CID, workspaceFolder, safe.directory.
LIB_HELPERS_USED_BY_DOCTOR = (
    "container_slug_for_cwd",
    "container_id_for",
    "ensure_workspace_folder",
    "assert_safe_directory",
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
    """S6 is blocked-by S2 — the lib must already exist on disk."""
    assert LIB.is_file(), f"S6 cannot delegate to a lib that does not exist: {LIB}"


# -- Delegation: script sources the lib --------------------------------------


def test_script_sources_container_state_lib():
    """S6 core delta: the script must source lib/container-state.sh."""
    text = SCRIPT.read_text()
    pattern = re.compile(r"^\s*(\.|source)\s+.*lib/container-state\.sh\b", re.MULTILINE)
    assert pattern.search(text), (
        "mentat-container-doctor must source lib/container-state.sh — S6 delegation depends on it"
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
    for helper in LIB_HELPERS_USED_BY_DOCTOR:
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
    """Slug derivation must come from the lib. Comments stripped."""
    text = _strip_comments(SCRIPT.read_text())
    assert re.search(r"\bcontainer_slug_for_cwd\b", text), (
        "mentat-container-doctor must derive slug via container_slug_for_cwd"
    )


def test_script_invokes_container_id_for():
    """Plan S6: doctor walks lib predicates — CID-by-slug is one of them."""
    text = _strip_comments(SCRIPT.read_text())
    assert re.search(r"\bcontainer_id_for\b", text), "mentat-container-doctor must probe CID via container_id_for"


def test_script_invokes_ensure_workspace_folder():
    """Plan S6 verify: 'broken worktree (e.g. one where workspaceFolder
    missing) names the missing path' — only ensure_workspace_folder
    produces that diagnostic."""
    text = _strip_comments(SCRIPT.read_text())
    assert re.search(r"\bensure_workspace_folder\b", text), (
        "mentat-container-doctor must check workspaceFolder via ensure_workspace_folder (plan S6 verify line)"
    )


def test_script_invokes_assert_safe_directory():
    """Plan S6: doctor walks lib predicates — assert_safe_directory is one."""
    text = _strip_comments(SCRIPT.read_text())
    assert re.search(r"\bassert_safe_directory\b", text), (
        "mentat-container-doctor must check safe.directory via assert_safe_directory"
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


def _healthy_docker_body(slug: str, ws: str, log: Path) -> str:
    """Fake docker that reports a running container for `slug`, the
    workspaceFolder `ws` present inside, and `ws` in safe.directory."""
    return textwrap.dedent(f"""\
        #!/bin/bash
        echo "docker $*" >> {log}
        case "$1" in
          ps)
            if [[ "$*" == *"mentat_slug={slug}"* ]]; then
              echo fakecid
            fi
            ;;
          exec)
            # Strip flags until we hit the CID, then read remaining cmd.
            shift  # drop 'exec'
            while [[ "$1" == -* ]]; do shift; done
            shift  # drop CID
            # Now $@ is the inner command.
            if [[ "$1" == "test" && "$2" == "-d" && "$3" == "{ws}" ]]; then
              exit 0  # workspaceFolder exists
            fi
            if [[ "$1" == "git" && "$2" == "config" && "$*" == *"safe.directory"* ]]; then
              echo "{ws}"  # safe.directory contains ws
              exit 0
            fi
            exit 0
            ;;
        esac
        """)


def test_doctor_healthy_worktree_returns_clean(tmp_path):
    """Plan S6 verify: 'Against a healthy worktree returns clean.'

    "Clean" is scoped to the S6 deltas — the four lib state invariants
    (container running, workspaceFolder, safe.directory, slug). The
    pre-existing host-side checks (git/jq/docker socket) are not S6's
    contract; in particular `/var/run/docker.sock` may legitimately be
    absent in the test sandbox. We assert: every state-predicate line
    is OK, never FAIL.
    """
    slug = "healthyslug"
    ws = f"/workspaces/{slug}"
    wt = _fake_worktree(tmp_path, slug)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"

    _make_fake_bin(bin_dir, "git", "#!/bin/bash\nexit 0\n")
    _make_fake_bin(bin_dir, "jq", "#!/bin/bash\nexit 0\n")
    _make_fake_bin(bin_dir, "docker", _healthy_docker_body(slug, ws, log))

    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(
        [str(SCRIPT)],
        cwd=str(wt),
        capture_output=True,
        text=True,
        env=env,
    )
    out = r.stdout + r.stderr
    # Healthy state predicates must surface as OK lines naming the right path.
    assert re.search(r"^OK\s+container running .*" + re.escape(slug), out, re.MULTILINE), (
        f"healthy worktree must show OK container line for slug; got:\n{out}"
    )
    assert re.search(r"^OK\s+workspaceFolder\s+" + re.escape(ws), out, re.MULTILINE), (
        f"healthy worktree must show OK workspaceFolder line; got:\n{out}"
    )
    assert re.search(r"^OK\s+safe\.directory\s+" + re.escape(ws), out, re.MULTILINE), (
        f"healthy worktree must show OK safe.directory line; got:\n{out}"
    )
    # No state-predicate FAILs (slug/container/workspaceFolder/safe.directory).
    fail_lines = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
    state_terms = ("container", "workspaceFolder", "safe.directory", "slug")
    leaking = [ln for ln in fail_lines if any(term in ln for term in state_terms)]
    assert not leaking, f"healthy worktree must have no FAIL on state predicates; got:\n" + "\n".join(leaking)


def test_doctor_missing_workspace_folder_names_path(tmp_path):
    """Plan S6 verify: 'broken worktree (e.g. one where workspaceFolder
    missing) names the missing path.' The exact path /workspaces/<slug>
    must appear in the doctor's output."""
    slug = "brokenwsslug"
    ws = f"/workspaces/{slug}"
    wt = _fake_worktree(tmp_path, slug)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"

    _make_fake_bin(bin_dir, "git", "#!/bin/bash\nexit 0\n")
    _make_fake_bin(bin_dir, "jq", "#!/bin/bash\nexit 0\n")
    # Docker reports container running, but `test -d $ws` FAILS (workspaceFolder
    # missing inside container). safe.directory check we leave passing so the
    # missing-path message is unambiguous.
    _make_fake_bin(
        bin_dir,
        "docker",
        textwrap.dedent(f"""\
        #!/bin/bash
        echo "docker $*" >> {log}
        case "$1" in
          ps)
            if [[ "$*" == *"mentat_slug={slug}"* ]]; then
              echo fakecid
            fi
            ;;
          exec)
            shift
            while [[ "$1" == -* ]]; do shift; done
            shift  # CID
            if [[ "$1" == "test" && "$2" == "-d" ]]; then
              exit 1  # workspaceFolder MISSING
            fi
            if [[ "$1" == "git" && "$*" == *"safe.directory"* ]]; then
              echo "{ws}"  # safe.directory OK
              exit 0
            fi
            exit 0
            ;;
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
    out = r.stdout + r.stderr
    assert r.returncode != 0, (
        f"broken workspaceFolder must yield nonzero rc; got rc=0\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )
    assert ws in out, f"output must name the missing path {ws!r}; got:\n{out}"
    assert "FAIL" in out, f"output must include a FAIL marker for the missing invariant; got:\n{out}"


def test_doctor_no_container_reports_failure(tmp_path):
    """No container running for current slug -> doctor must report it
    and exit nonzero. Output must mention the slug or container so the
    user knows what to bring up."""
    slug = "nocontainerslug"
    wt = _fake_worktree(tmp_path, slug)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"

    _make_fake_bin(bin_dir, "git", "#!/bin/bash\nexit 0\n")
    _make_fake_bin(bin_dir, "jq", "#!/bin/bash\nexit 0\n")
    # Docker `ps` returns empty for any filter -> no container.
    _make_fake_bin(
        bin_dir,
        "docker",
        textwrap.dedent(f"""\
        #!/bin/bash
        echo "docker $*" >> {log}
        case "$1" in
          ps) ;;  # empty stdout
          exec) exit 99 ;;  # should not be reached without a CID
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
    out = r.stdout + r.stderr
    assert r.returncode != 0, (
        f"missing container must yield nonzero rc; got rc=0\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )
    assert "FAIL" in out, f"missing container must surface FAIL; got:\n{out}"
    assert re.search(rf"\b(container|slug|{re.escape(slug)})\b", out), (
        f"FAIL line must name the missing piece (container/slug); got:\n{out}"
    )


def test_doctor_missing_safe_directory_names_path(tmp_path):
    """safe.directory check is one of the three S1 invariants — must surface
    cleanly as a separate FAIL when it's the only broken thing."""
    slug = "brokensafeslug"
    ws = f"/workspaces/{slug}"
    wt = _fake_worktree(tmp_path, slug)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"

    _make_fake_bin(bin_dir, "git", "#!/bin/bash\nexit 0\n")
    _make_fake_bin(bin_dir, "jq", "#!/bin/bash\nexit 0\n")
    # Container running + workspaceFolder present, but safe.directory missing.
    _make_fake_bin(
        bin_dir,
        "docker",
        textwrap.dedent(f"""\
        #!/bin/bash
        echo "docker $*" >> {log}
        case "$1" in
          ps)
            if [[ "$*" == *"mentat_slug={slug}"* ]]; then
              echo fakecid
            fi
            ;;
          exec)
            shift
            while [[ "$1" == -* ]]; do shift; done
            shift  # CID
            if [[ "$1" == "test" && "$2" == "-d" ]]; then
              exit 0  # workspaceFolder OK
            fi
            if [[ "$1" == "git" && "$*" == *"safe.directory"* ]]; then
              # No entries listed -> safe.directory missing for ws.
              exit 0
            fi
            exit 0
            ;;
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
    out = r.stdout + r.stderr
    assert r.returncode != 0, (
        f"missing safe.directory must yield nonzero rc; got rc=0\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )
    assert "FAIL" in out, f"must surface FAIL; got:\n{out}"
    assert "safe.directory" in out, f"FAIL line must name safe.directory; got:\n{out}"


# -- Drift guard --------------------------------------------------------------


def test_all_required_invariants_have_lib_calls():
    """Drift guard — if a future patch reintroduces inline derivation,
    one of these searches goes to zero."""
    text = _strip_comments(SCRIPT.read_text())
    invariants = {
        "slug": r"\bcontainer_slug_for_cwd\b",
        "container-id": r"\bcontainer_id_for\b",
        "workspaceFolder": r"\bensure_workspace_folder\b",
        "safe.directory": r"\bassert_safe_directory\b",
    }
    missing = [name for name, pat in invariants.items() if not re.search(pat, text)]
    assert not missing, f"invariants missing lib-call sites in mentat-container-doctor: {missing}"
