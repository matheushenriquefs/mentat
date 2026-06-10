"""B1/B2/B3 mentat-diff: script behaviors, flags, audit, orchestrate hook."""

import json
import os
import subprocess
import tempfile
import textwrap

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENTS_BIN = os.path.join(_REPO_ROOT, ".agents", "bin")
MENTAT_DIFF = os.path.join(AGENTS_BIN, "mentat-diff")
WIKI_STUB = os.path.join(_REPO_ROOT, "docs", "wiki", "commands", "mentat-diff.md")


def _make_git_fixture(tmp_path: str) -> tuple[str, str]:
    """Create git repo with main + holding branch with 1 commit. Returns (root, holding)."""
    subprocess.run(["git", "init", "-q", tmp_path], check=True)
    subprocess.run(["git", "-C", tmp_path, "config", "user.email", "test@test.com"], check=True)
    subprocess.run(["git", "-C", tmp_path, "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", tmp_path, "commit", "--allow-empty", "-m", "init"], check=True)
    subprocess.run(["git", "-C", tmp_path, "checkout", "-b", "main"], check=True)
    # base commit on main
    with open(os.path.join(tmp_path, "base.txt"), "w") as f:
        f.write("base\n")
    subprocess.run(["git", "-C", tmp_path, "add", "base.txt"], check=True)
    subprocess.run(["git", "-C", tmp_path, "commit", "-m", "base"], check=True)
    # holding branch with 1 commit
    holding = "branch/test-hook"
    subprocess.run(["git", "-C", tmp_path, "checkout", "-b", holding], check=True)
    with open(os.path.join(tmp_path, "chunk.txt"), "w") as f:
        f.write("chunk\n")
    subprocess.run(["git", "-C", tmp_path, "add", "chunk.txt"], check=True)
    subprocess.run(["git", "-C", tmp_path, "commit", "-m", "chunk1"], check=True)
    subprocess.run(["git", "-C", tmp_path, "checkout", "main"], check=True)
    return tmp_path, holding


def _run_end_of_batch(root: str, holding: str, landed: int, total: int, logdir: str) -> subprocess.CompletedProcess:
    """Run the end-of-batch block logic in isolation via a bash heredoc."""
    # Write rtk stub inline so it's available inside the heredoc's PATH
    rtk_stub = os.path.join(logdir, "_rtk_stub")
    os.makedirs(logdir, exist_ok=True)
    with open(rtk_stub, "w") as f:
        f.write('#!/usr/bin/env bash\nexec "$@"\n')
    os.chmod(rtk_stub, 0o755)
    script = textwrap.dedent(f"""
        #!/usr/bin/env bash
        set -euo pipefail
        PATH="{logdir}:{AGENTS_BIN}:$PATH"
        ln -sf "{rtk_stub}" "{logdir}/rtk" 2>/dev/null || true
        export PATH

        ROOT="{root}"
        HOLDING="{holding}"
        LAND_BASE="$(git -C "$ROOT" merge-base main "$HOLDING")"
        LOGDIR="{logdir}"
        MENTAT_SESSION="test-session"
        HERE="{AGENTS_BIN}"
        LANDED={landed}
        TOTAL={total}

        mkdir -p "$LOGDIR"

        _LIB="{AGENTS_BIN}/lib"
        . "$_LIB/log.sh"
        . "$_LIB/audit.sh"
        _LOG_PREFIX=mentat-orchestrate

        final_review() {{ :; }}  # no-op stub

        EJECTED=$((TOTAL - LANDED))
        if [ "$LANDED" -eq "$TOTAL" ]; then
          log "all $TOTAL chunk(s) landed -> $HOLDING."
          final_review "$LAND_BASE"
          log "--- mentat-diff ---"
          ( cd "$ROOT" && "{MENTAT_DIFF}" "$HOLDING" ) \\
            | tee -a "$LOGDIR/mentat-orchestrate-$MENTAT_SESSION.jsonl" >&2 || true
          log "done. Review end-of-queue findings, then push + PR manually (ADR 0002)."
        else
          log "$LANDED/$TOTAL chunk(s) landed; $EJECTED ejected — repair first."
          log "skipped cumulative diff — $EJECTED eject(s). Run: mentat-diff $HOLDING"
          log "logs: $LOGDIR/  worktrees: $ROOT/.mentat/worktrees/"
        fi
    """)
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
    )


def _make_rtk_stub(bin_dir: str) -> None:
    """Write a minimal rtk stub that passes through to git (drops the 'rtk' prefix)."""
    stub = os.path.join(bin_dir, "rtk")
    with open(stub, "w") as f:
        f.write('#!/usr/bin/env bash\nexec "$@"\n')
    os.chmod(stub, 0o755)


def _run_mentat_diff(
    root: str, holding: str, *extra_args: str, session: str = "pytest-$$"
) -> subprocess.CompletedProcess:
    """Run mentat-diff against a git fixture. Returns CompletedProcess."""
    with tempfile.TemporaryDirectory() as stub_dir:
        _make_rtk_stub(stub_dir)
        env = os.environ.copy()
        env["PATH"] = stub_dir + ":" + AGENTS_BIN + ":" + env.get("PATH", "")
        env["MENTAT_SESSION"] = session
        env["MENTAT_REPO"] = "mentat-diff-test"
        return subprocess.run(
            ["bash", MENTAT_DIFF, *extra_args, holding],
            capture_output=True,
            text=True,
            cwd=root,
            env=env,
        )


# --- B3: wiki stub ---


def test_wiki_stub_exists():
    """docs/wiki/commands/mentat-diff.md stub must exist."""
    assert os.path.isfile(WIKI_STUB), f"wiki stub not found: {WIKI_STUB}"


def test_wiki_stub_documents_flags():
    """Wiki stub must document --stat-only, --name-only, --since flags."""
    content = open(WIKI_STUB).read()
    for flag in ("--stat-only", "--name-only", "--since"):
        assert flag in content, f"wiki stub missing flag documentation: {flag}"


# --- B1: script behaviors ---


def test_b1_branch_resolve_and_header():
    """mentat-diff resolves holding branch, prints header with branch/base/tip/files."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        result = _run_mentat_diff(root, holding)
        assert result.returncode == 0, f"mentat-diff failed:\n{result.stderr}"
        out = result.stdout
        assert "--- mentat-diff ---" in out, f"missing header:\n{out}"
        assert f"branch : {holding}" in out, f"missing branch line:\n{out}"
        assert "base   :" in out, f"missing base line:\n{out}"
        assert "tip    :" in out, f"missing tip line:\n{out}"
        assert "files  : 1" in out, f"missing files count:\n{out}"


def test_b1_default_emits_stat_and_diff():
    """mentat-diff default mode emits stat block and diff body."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        result = _run_mentat_diff(root, holding)
        assert result.returncode == 0, f"mentat-diff failed:\n{result.stderr}"
        out = result.stdout
        assert "chunk.txt" in out, f"expected changed file in output:\n{out}"
        assert "insertion" in out, f"expected insertion count in stat:\n{out}"


def test_b1_stat_only_flag():
    """--stat-only prints stat block only (no diff hunks)."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        result = _run_mentat_diff(root, holding, "--stat-only")
        assert result.returncode == 0, f"failed:\n{result.stderr}"
        out = result.stdout
        assert "chunk.txt" in out, f"stat missing changed file:\n{out}"
        assert "@@" not in out, f"--stat-only should not emit diff hunks:\n{out}"


def test_b1_name_only_flag():
    """--name-only prints file names only (no diff hunks, no stat numbers)."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        result = _run_mentat_diff(root, holding, "--name-only")
        assert result.returncode == 0, f"failed:\n{result.stderr}"
        out = result.stdout
        assert "chunk.txt" in out, f"--name-only missing filename:\n{out}"
        assert "insertion" not in out, f"--name-only should not emit stat numbers:\n{out}"


def test_b1_since_flag():
    """--since=<sha> uses the given SHA as diff base."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        # main tip = merge-base by definition in this fixture
        base_sha = subprocess.check_output(["git", "-C", root, "rev-parse", "main"], text=True).strip()
        result = _run_mentat_diff(root, holding, f"--since={base_sha}")
        assert result.returncode == 0, f"failed:\n{result.stderr}"
        out = result.stdout
        assert f"base   : {base_sha}" in out, f"--since base not reflected:\n{out}"
        assert "chunk.txt" in out, f"missing file in --since diff:\n{out}"


def test_b1_audit_diff_emit_jsonl():
    """mentat-diff emits diff.emit JSONL with base/tip/branch/files fields."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        session = "pytest-audit-test"
        log_base = os.path.join(os.path.expanduser("~/.agents/mentat/logs"), "mentat-diff-test", session)
        result = _run_mentat_diff(root, holding, session=session)
        assert result.returncode == 0, f"failed:\n{result.stderr}"
        # Find the audit JSONL file written by this session
        import glob

        matches = glob.glob(os.path.join(log_base, "mentat-diff-*.jsonl"))
        assert matches, f"no audit JSONL found in {log_base}"
        events = [json.loads(line) for line in open(matches[0]) if line.strip()]
        emit_events = [e for e in events if e.get("event") == "diff.emit"]
        assert emit_events, "no diff.emit event found in audit log"
        payload = emit_events[0]["payload"]
        for key in ("base", "tip", "branch", "files"):
            assert key in payload, f"audit payload missing key: {key}"
        assert payload["branch"] == holding
        assert payload["files"] == 1


# --- B2: orchestrate hook ---


def test_clean_drain_log_contains_diff_header():
    """LANDED==TOTAL → orchestrate log contains '--- mentat-diff ---' with file count."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        logdir = os.path.join(tmp, "logs")
        result = _run_end_of_batch(root, holding, landed=1, total=1, logdir=logdir)
        assert result.returncode == 0, f"script failed:\n{result.stderr}"
        logfile = os.path.join(logdir, "mentat-orchestrate-test-session.jsonl")
        assert os.path.exists(logfile), "orchestrate log not created"
        content = open(logfile).read()
        assert "--- mentat-diff ---" in content, f"log missing '--- mentat-diff ---':\n{content}"
        assert "files  : 1" in content, f"log missing file count line:\n{content}"


def test_clean_drain_stderr_contains_diff_section():
    """LANDED==TOTAL → stderr log line '--- mentat-diff ---' emitted."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        logdir = os.path.join(tmp, "logs")
        result = _run_end_of_batch(root, holding, landed=1, total=1, logdir=logdir)
        assert result.returncode == 0, f"script failed:\n{result.stderr}"
        assert "--- mentat-diff ---" in result.stderr, f"stderr missing diff header:\n{result.stderr}"


def test_eject_path_log_contains_skip_note():
    """LANDED<TOTAL → stderr log contains skip note pointing at manual mentat-diff run."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        logdir = os.path.join(tmp, "logs")
        result = _run_end_of_batch(root, holding, landed=0, total=1, logdir=logdir)
        combined = result.stdout + result.stderr
        assert "skipped cumulative diff" in combined, f"missing skip note:\n{combined}"
        assert f"mentat-diff {holding}" in combined, f"missing manual-run hint with holding branch:\n{combined}"


def test_eject_path_no_diff_in_log():
    """LANDED<TOTAL → orchestrate log not created (diff skipped entirely)."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        logdir = os.path.join(tmp, "logs")
        _run_end_of_batch(root, holding, landed=0, total=1, logdir=logdir)
        logfile = os.path.join(logdir, "mentat-orchestrate-test-session.jsonl")
        if os.path.exists(logfile):
            content = open(logfile).read()
            assert "--- mentat-diff ---" not in content, f"diff header should not appear on eject path:\n{content}"
