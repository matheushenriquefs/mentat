"""P4: vendor namespace, credits gen, vendir lock, release exclude list."""
import os
import subprocess
import tempfile

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENTS = os.path.join(ROOT, ".agents")
BIN = os.path.join(AGENTS, "bin")
SKILLS = os.path.join(AGENTS, "skills")
VENDOR = os.path.join(SKILLS, "vendor")
GITIGNORE = os.path.join(ROOT, ".gitignore")
VENDIR_YML = os.path.join(ROOT, "vendir.yml")


def _sh(cmd: str, cwd: str = ROOT, env: dict = None) -> subprocess.CompletedProcess:
    import os as _os
    e = {**_os.environ, **(env or {})}
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, env=e)


def _parse_vendir() -> list:
    with open(VENDIR_YML) as f:
        cfg = yaml.safe_load(f)
    entries = []
    for d in cfg.get("directories", []):
        for c in d.get("contents", []):
            entries.append({"path": c["path"], "dir": d["path"]})
    return entries


# ── C1: vendir.yml + vendor/ namespace ───────────────────────────────────────

def test_vendir_yml_exists():
    assert os.path.isfile(VENDIR_YML), f"vendir.yml not found at {VENDIR_YML}"


def test_vendir_yml_parseable():
    entries = _parse_vendir()
    assert len(entries) > 0, "vendir.yml must declare at least one upstream"


def test_gitignore_excludes_vendor():
    with open(GITIGNORE) as f:
        gi = f.read()
    assert ".agents/skills/vendor/" in gi, ".gitignore must exclude .agents/skills/vendor/"


def test_upstreams_jsonc_absent():
    assert not os.path.isfile(os.path.join(ROOT, "upstreams.jsonc")), (
        "upstreams.jsonc must be deleted — replaced by vendir.yml"
    )


def test_setup_matt_pocock_not_directly_under_skills():
    direct = os.path.join(SKILLS, "setup-matt-pocock-skills")
    assert not os.path.isdir(direct), (
        "setup-matt-pocock-skills must not sit directly in skills/ — lives in vendor/mattpocock/skills/"
    )


# ── C2: CREDITS.md ───────────────────────────────────────────────────────────

def test_credits_md_exists():
    path = os.path.join(ROOT, "CREDITS.md")
    assert os.path.isfile(path), "CREDITS.md must exist"


def test_credits_md_has_vendored_section():
    with open(os.path.join(ROOT, "CREDITS.md")) as f:
        content = f.read()
    assert "## Vendored" in content, "CREDITS.md must have ## Vendored section"


def test_credits_md_has_inspired_by_section():
    with open(os.path.join(ROOT, "CREDITS.md")) as f:
        content = f.read()
    assert "## Inspired by" in content, "CREDITS.md must have ## Inspired by section"


def test_credits_md_has_runtime_deps_section():
    with open(os.path.join(ROOT, "CREDITS.md")) as f:
        content = f.read()
    assert "## Runtime tool dependencies" in content


def test_mentat_credits_gen_absent():
    p = os.path.join(BIN, "mentat-credits-gen")
    assert not os.path.isfile(p), "bin/mentat-credits-gen must be deleted — superseded by mentat-update"


# ── C3: mentat-update (replaces mentat-sync-upstream + mentat-sync-check) ────

def test_mentat_update_exists():
    p = os.path.join(BIN, "mentat-update")
    assert os.path.isfile(p), "bin/mentat-update not found"


def test_mentat_update_executable():
    p = os.path.join(BIN, "mentat-update")
    assert os.access(p, os.X_OK), "bin/mentat-update must be executable"


def test_mentat_update_syntax():
    p = os.path.join(BIN, "mentat-update")
    r = _sh(f"bash -n {p}")
    assert r.returncode == 0, r.stderr


def test_mentat_update_offline_flag_requires_lockfile():
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_vendir = os.path.join(tmpdir, "vendir.yml")
        with open(fake_vendir, "w") as f:
            f.write("apiVersion: vendir.k14s.io/v1alpha1\nkind: Config\ndirectories: []\n")
        r = _sh(f"VENDIR_YML={fake_vendir} {BIN}/mentat-update --offline", cwd=tmpdir)
    assert r.returncode != 0, "--offline without lockfile must exit non-zero"


def test_mentat_sync_upstream_absent():
    p = os.path.join(BIN, "mentat-sync-upstream")
    assert not os.path.isfile(p), "bin/mentat-sync-upstream must be deleted — superseded by mentat-update"


def test_mentat_sync_check_absent():
    p = os.path.join(BIN, "mentat-sync-check")
    assert not os.path.isfile(p), "bin/mentat-sync-check must be deleted — use vendir sync --diff"


# ── C4: mentat-release / mentat-setup exclude list ───────────────────────────

def _setup_dry_run_output() -> str:
    with tempfile.TemporaryDirectory() as dest:
        env = {**os.environ, "HOME": dest}
        r = subprocess.run(
            [os.path.join(BIN, "mentat-setup"), "--dry-run", "--yes"],
            capture_output=True, text=True, cwd=ROOT, env=env,
        )
    return r.stdout + r.stderr


def test_setup_dry_run_excludes_sync_upstream():
    out = _setup_dry_run_output()
    assert "mentat-sync-upstream" not in out


def test_setup_dry_run_excludes_upstreams_jsonc():
    out = _setup_dry_run_output()
    assert "upstreams.jsonc" not in out


def test_setup_dry_run_excludes_credits_gen():
    out = _setup_dry_run_output()
    assert "mentat-credits-gen" not in out


def test_setup_dry_run_excludes_sync_check():
    out = _setup_dry_run_output()
    assert "mentat-sync-check" not in out
