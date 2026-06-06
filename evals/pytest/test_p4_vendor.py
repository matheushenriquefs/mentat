"""P4: vendor namespace, credits gen, sync freshness gate, release exclude list."""
import json
import os
import subprocess
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENTS = os.path.join(ROOT, ".agents")
BIN = os.path.join(AGENTS, "bin")
SKILLS = os.path.join(AGENTS, "skills")
VENDOR = os.path.join(SKILLS, "vendor")
GITIGNORE = os.path.join(ROOT, ".gitignore")


def _sh(cmd: str, cwd: str = ROOT, env: dict = None) -> subprocess.CompletedProcess:
    import os as _os
    e = {**_os.environ, **(env or {})}
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, env=e)


def _parse_upstreams() -> list:
    manifest = os.path.join(ROOT, "upstreams.jsonc")
    with open(manifest) as f:
        raw = "\n".join(
            line for line in f if not line.strip().startswith("//")
        )
    return json.loads(raw)["upstreams"]


# ── C1: vendor/ namespace ────────────────────────────────────────────────────

def test_vendor_dir_exists():
    assert os.path.isdir(VENDOR), f"Expected .agents/skills/vendor/ at {VENDOR}"


def test_setup_matt_pocock_not_directly_under_skills():
    direct = os.path.join(SKILLS, "setup-matt-pocock-skills")
    assert not os.path.isdir(direct), (
        "setup-matt-pocock-skills must not sit directly in skills/ — move to vendor/matt-pocock/"
    )


def test_upstreams_vendor_paths_use_skills_vendor():
    for up in _parse_upstreams():
        vp = up["vendor_path"]
        assert ".agents/skills/vendor/" in vp, (
            f"upstream '{up['name']}' vendor_path '{vp}' must use .agents/skills/vendor/"
        )


def test_upstreams_no_vendored_path():
    for up in _parse_upstreams():
        vp = up["vendor_path"]
        assert ".agents/vendored/" not in vp, (
            f"upstream '{up['name']}' still uses legacy .agents/vendored/ path"
        )


def test_gitignore_has_vendor_paths_for_non_commit_upstreams():
    with open(GITIGNORE) as f:
        gi = f.read()
    for up in _parse_upstreams():
        if not up.get("commit", True):
            vp = up["vendor_path"]
            assert vp in gi or vp + "/" in gi, (
                f"upstream '{up['name']}' has commit:false but vendor_path '{vp}' not in .gitignore"
            )


# ── C2: CREDITS.md auto-gen ──────────────────────────────────────────────────

def test_mentat_credits_gen_exists():
    p = os.path.join(BIN, "mentat-credits-gen")
    assert os.path.isfile(p), "bin/mentat-credits-gen not found"


def test_mentat_credits_gen_executable():
    p = os.path.join(BIN, "mentat-credits-gen")
    assert os.access(p, os.X_OK), "bin/mentat-credits-gen must be executable"


def test_mentat_credits_gen_syntax():
    p = os.path.join(BIN, "mentat-credits-gen")
    r = _sh(f"bash -n {p}")
    assert r.returncode == 0, r.stderr


def test_mentat_credits_gen_outputs_table():
    r = _sh(f"{BIN}/mentat-credits-gen")
    assert r.returncode == 0, f"mentat-credits-gen failed: {r.stderr}"
    assert "| " in r.stdout, "output must be a Markdown table"
    assert "mattpocock-skills" in r.stdout


def test_mentat_credits_gen_idempotent():
    r1 = _sh(f"{BIN}/mentat-credits-gen")
    r2 = _sh(f"{BIN}/mentat-credits-gen")
    assert r1.stdout == r2.stdout, "mentat-credits-gen must be idempotent"


def test_credits_md_has_autogen_header():
    path = os.path.join(ROOT, "CREDITS.md")
    assert os.path.isfile(path), "CREDITS.md must exist"
    with open(path) as f:
        content = f.read()
    assert "AUTO-GENERATED" in content, "CREDITS.md must contain AUTO-GENERATED marker"
    assert "mentat-credits-gen" in content, "CREDITS.md must reference mentat-credits-gen"


def test_credits_md_lists_all_upstreams():
    path = os.path.join(ROOT, "CREDITS.md")
    with open(path) as f:
        content = f.read()
    for up in _parse_upstreams():
        assert up["name"] in content, f"CREDITS.md missing upstream '{up['name']}'"


# ── C3: sync freshness JSONL log + mentat-sync-check ────────────────────────

def test_mentat_sync_check_exists():
    p = os.path.join(BIN, "mentat-sync-check")
    assert os.path.isfile(p), "bin/mentat-sync-check not found"


def test_mentat_sync_check_executable():
    p = os.path.join(BIN, "mentat-sync-check")
    assert os.access(p, os.X_OK), "bin/mentat-sync-check must be executable"


def test_mentat_sync_check_syntax():
    p = os.path.join(BIN, "mentat-sync-check")
    r = _sh(f"bash -n {p}")
    assert r.returncode == 0, r.stderr


def test_mentat_sync_check_stale_no_log():
    with tempfile.TemporaryDirectory() as tmpdir:
        log = os.path.join(tmpdir, "sync-upstream.jsonl")
        r = _sh(f"{BIN}/mentat-sync-check", env={"MENTAT_SYNC_LOG": log})
    assert r.returncode != 0, "sync-check must exit non-zero when log absent"
    assert "STALE" in r.stdout or "STALE" in r.stderr, "must print STALE when log absent"


def test_mentat_sync_check_stale_old_entry():
    with tempfile.TemporaryDirectory() as tmpdir:
        log = os.path.join(tmpdir, "sync-upstream.jsonl")
        old_ts = "2000-01-01T00:00:00Z"
        with open(log, "w") as f:
            for up in _parse_upstreams():
                f.write(json.dumps({"ts": old_ts, "upstream": up["name"], "sha": "abc", "status": "ok"}) + "\n")
        r = _sh(f"{BIN}/mentat-sync-check", env={"MENTAT_SYNC_LOG": log})
    assert r.returncode != 0, "sync-check must exit non-zero for old entries"
    assert "STALE" in r.stdout or "STALE" in r.stderr


def test_mentat_sync_check_fresh():
    with tempfile.TemporaryDirectory() as tmpdir:
        log = os.path.join(tmpdir, "sync-upstream.jsonl")
        fresh_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(log, "w") as f:
            for up in _parse_upstreams():
                f.write(json.dumps({"ts": fresh_ts, "upstream": up["name"], "sha": "abc", "status": "ok"}) + "\n")
        r = _sh(f"{BIN}/mentat-sync-check", env={"MENTAT_SYNC_LOG": log})
    assert r.returncode == 0, f"sync-check must exit 0 for fresh log: {r.stdout}{r.stderr}"


# ── C4: mentat-release exclude list ─────────────────────────────────────────

def _dry_run_output() -> str:
    with tempfile.TemporaryDirectory() as dest:
        env = {**os.environ, "HOME": dest}
        r = subprocess.run(
            [os.path.join(BIN, "mentat-release"), "--dry-run"],
            capture_output=True, text=True, cwd=ROOT, env=env,
        )
    # rsync --dry-run output: lines like "sending incremental file list"
    # then file paths — filter out diagnostic mentat-release: prefix lines
    return "\n".join(
        l for l in (r.stdout + r.stderr).splitlines()
        if not l.startswith("mentat-release:")
    )


def test_mentat_release_dry_run_excludes_sync_upstream():
    out = _dry_run_output()
    assert "mentat-sync-upstream" not in out, (
        f"mentat-release --dry-run must not transfer mentat-sync-upstream:\n{out}"
    )


def test_mentat_release_dry_run_excludes_upstreams_jsonc():
    out = _dry_run_output()
    assert "upstreams.jsonc" not in out, (
        f"mentat-release --dry-run must not transfer upstreams.jsonc:\n{out}"
    )


def test_mentat_release_dry_run_excludes_credits_gen():
    out = _dry_run_output()
    assert "mentat-credits-gen" not in out, (
        f"mentat-release --dry-run must not transfer mentat-credits-gen:\n{out}"
    )


def test_mentat_release_dry_run_excludes_sync_check():
    out = _dry_run_output()
    assert "mentat-sync-check" not in out, (
        f"mentat-release --dry-run must not transfer mentat-sync-check:\n{out}"
    )
