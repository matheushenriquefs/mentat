"""B2 orchestrate hook: mentat-diff auto-invocation on clean drain vs eject paths."""
import os
import subprocess
import tempfile
import textwrap

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENTS_BIN = os.path.join(_REPO_ROOT, ".agents", "bin")
MENTAT_DIFF = os.path.join(AGENTS_BIN, "mentat-diff")


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
    script = textwrap.dedent(f"""
        #!/usr/bin/env bash
        set -euo pipefail
        PATH="{AGENTS_BIN}:$PATH"
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
        assert "--- mentat-diff ---" in content, (
            f"log missing '--- mentat-diff ---':\n{content}"
        )
        assert "files" in content, f"log missing file count:\n{content}"


def test_clean_drain_stderr_contains_diff_section():
    """LANDED==TOTAL → stderr log line '--- mentat-diff ---' emitted."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        logdir = os.path.join(tmp, "logs")
        result = _run_end_of_batch(root, holding, landed=1, total=1, logdir=logdir)
        assert result.returncode == 0, f"script failed:\n{result.stderr}"
        assert "--- mentat-diff ---" in result.stderr, (
            f"stderr missing diff header:\n{result.stderr}"
        )


def test_eject_path_log_contains_skip_note():
    """LANDED<TOTAL → stderr log contains skip note pointing at manual mentat-diff run."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        logdir = os.path.join(tmp, "logs")
        result = _run_end_of_batch(root, holding, landed=0, total=1, logdir=logdir)
        combined = result.stdout + result.stderr
        assert "skipped cumulative diff" in combined, (
            f"missing skip note:\n{combined}"
        )
        assert f"mentat-diff {holding}" in combined, (
            f"missing manual-run hint with holding branch:\n{combined}"
        )


def test_eject_path_no_diff_in_log():
    """LANDED<TOTAL → orchestrate log not created (diff skipped entirely)."""
    with tempfile.TemporaryDirectory() as tmp:
        root, holding = _make_git_fixture(tmp)
        logdir = os.path.join(tmp, "logs")
        _run_end_of_batch(root, holding, landed=0, total=1, logdir=logdir)
        logfile = os.path.join(logdir, "mentat-orchestrate-test-session.jsonl")
        if os.path.exists(logfile):
            content = open(logfile).read()
            assert "--- mentat-diff ---" not in content, (
                f"diff header should not appear on eject path:\n{content}"
            )
