"""mentat-container doctor: six-section environment diagnostic."""

from __future__ import annotations

import subprocess
from pathlib import Path

import client as utils
from lib.exits import EX_FAILURE, EX_OK


def _col(label: str, value: str) -> str:
    return f"  {label:<14}: {value}"


def _doctor_section_host(host_arch: str, host_os: str) -> tuple[list[str], list[str]]:
    print("[host]")
    print(_col("arch", host_arch))
    print(_col("os", host_os))
    print()
    return [], []


def _doctor_section_container(wt: Path, host_arch: str) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    chunk_slug = utils._chunk_slug_for_wt(wt)
    print("[container]")
    try:
        daemon_ok = subprocess.run([utils._docker(), "info"], capture_output=True, timeout=30).returncode == 0
    except FileNotFoundError, subprocess.TimeoutExpired:
        daemon_ok = False
    if not daemon_ok:
        print(_col("daemon", "not running"))
        warnings.append("docker daemon not running")
    else:
        print(_col("daemon", "running"))
        cid = utils.container_id_for(chunk_slug)
        if cid:
            try:
                inspect = subprocess.run(
                    [utils._docker(), "inspect", "--format", "{{.Platform}}", cid],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                img_platform = inspect.stdout.strip() if inspect.returncode == 0 else "unknown"
            except subprocess.TimeoutExpired:
                img_platform = "unknown"
            print(_col("image platf", img_platform))
            if (host_arch == "arm64" and "amd64" in img_platform) or (
                host_arch in ("x86_64", "amd64") and "arm64" in img_platform
            ):
                print(_col("emulation", "qemu (slow — expect 3-5x perf hit)"))
                warnings.append("arch emulation")
            else:
                print(_col("emulation", "none"))
            ws = utils.workspace_folder_for(wt)
            print(_col("state", "running"))
            print(_col("workspace", ws))
        else:
            print(_col("state", f"no container for chunk={chunk_slug}"))
            warnings.append(f"container not running (chunk={chunk_slug})")
    print()
    return warnings, []


def _doctor_section_harness() -> tuple[list[str], list[str]]:
    print("[harness]")
    claude_dir = Path.home() / ".claude"
    cursor_dir = Path.home() / ".cursor"
    if claude_dir.exists():
        print(_col("claude-code", f"detected at {claude_dir}/"))
        agents_dir = claude_dir / "agents"
        agents_n = len(list(agents_dir.glob("mentat-*"))) if agents_dir.exists() else 0
        skills_n = len(list((claude_dir / "skills").glob("mentat-*"))) if (claude_dir / "skills").exists() else 0
        print(_col("agents link", f"{agents_n} mentat-* subagents linked"))
        print(_col("skills link", f"{skills_n} mentat-* skills linked"))
    else:
        print(_col("claude-code", "not detected"))
    if cursor_dir.exists():
        print(_col("cursor", f"detected at {cursor_dir}/"))
    else:
        print(_col("cursor", "not detected"))
    print()
    return [], []


def _doctor_section_companions() -> tuple[list[str], list[str]]:
    advisories: list[str] = []
    print("[companions]")
    pocock = (Path.home() / ".claude/skills/diagnose/SKILL.md").exists()
    caveman = (Path.home() / ".claude/plugins/marketplaces/caveman").exists()
    print(_col("matt-pocock", "present" if pocock else "missing — run mentat-install"))
    print(_col("julius-caveman", "present" if caveman else "missing — run mentat-install"))
    if not pocock or not caveman:
        advisories.append("companion(s) missing")
    print()
    return [], advisories


def _doctor_section_mentat_state(wt: Path) -> tuple[list[str], list[str]]:
    from lib.config import config_status

    warnings: list[str] = []
    print("[mentat state]")
    mentat_dir = Path.home() / ".mentat"
    print(_col("~/.mentat/", "present" if mentat_dir.exists() else "absent"))
    g_status, g_warn = config_status(mentat_dir)
    print(_col("config (global)", g_status))
    if g_warn:
        warnings.append(g_warn)
    _repo_root_r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if _repo_root_r.returncode == 0:
        r_status, r_warn = config_status(Path(_repo_root_r.stdout.strip()) / ".mentat")
        print(_col("config (repo)", r_status))
        if r_warn:
            warnings.append(f"repo {r_warn}")
    logs_dir = mentat_dir / "logs"
    if logs_dir.exists():
        session_n = sum(1 for _ in logs_dir.iterdir() if _.is_dir())
        print(_col("logs dir", f"{session_n} sessions"))
    else:
        print(_col("logs dir", "absent"))
    print()
    return warnings, []


def _doctor_section_tests() -> tuple[list[str], list[str]]:
    import json as _json

    print("[tests]")
    plans_dir = Path.home() / ".agents" / "plans"
    if plans_dir.exists():
        manifests = list(plans_dir.glob("*.tests.json"))
        if manifests:
            for mf in sorted(manifests):
                try:
                    data = _json.loads(mf.read_text())
                    closed = data.get("closed", [])
                    open_ = data.get("open", [])
                    ro = [p for p in closed if p not in set(open_)]
                    print(_col(mf.stem, f"{len(ro)} ro-mounted, {len(open_)} open"))
                except Exception:
                    print(_col(mf.stem, "manifest parse error"))
        else:
            print("  no test manifests")
    else:
        print("  no plans dir")
    print()
    return [], []


def cmd_doctor(wt: Path) -> int:
    import platform as _platform

    try:
        host_arch = subprocess.run(["uname", "-m"], capture_output=True, text=True, timeout=30).stdout.strip()
    except FileNotFoundError, subprocess.TimeoutExpired:
        host_arch = "unknown"
    host_os = f"{_platform.system().lower()} {_platform.release()}"

    print("\nmentat-container doctor\n")

    all_warnings: list[str] = []
    all_advisories: list[str] = []
    for w, a in [
        _doctor_section_host(host_arch, host_os),
        _doctor_section_container(wt, host_arch),
        _doctor_section_harness(),
        _doctor_section_companions(),
        _doctor_section_mentat_state(wt),
        _doctor_section_tests(),
    ]:
        all_warnings.extend(w)
        all_advisories.extend(a)

    warn_str = f"{len(all_warnings)} warning ({', '.join(all_warnings)})" if all_warnings else "0 warnings"
    adv_str = f"{len(all_advisories)} advisory ({', '.join(all_advisories)})" if all_advisories else "0 advisories"
    print(f"verdict: {warn_str}, {adv_str}")

    return EX_FAILURE if all_warnings else EX_OK
