"""health — dev-only sonnet sanity sweep + metrics trend.

Usage:
    python tasks/health.py [--db=<path>]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(".mentat/metrics/quality.db")
SONNET = "claude-sonnet-4-6"

MODULE_CLUSTERS = [
    ".agents/lib",
    ".agents/skills/mentat-orchestrate/scripts",
    ".agents/skills/mentat-implement/scripts",
    ".agents/skills/mentat-container/scripts",
    ".agents/skills/mentat-git/scripts",
    "tasks",
]

_SWEEP_PROMPT = """\
Review the Python files listed below for bugs, security issues, and quality problems.

Return ONLY a JSON array (no other text). Each element must be:
{{"file": "<path>", "line": <int>, "severity": "HIGH|MED|LOW",
  "lens": "<bugs|security|perf|style>", "summary": "<one sentence>"}}

Files to review:
{files}

Contents:
{content}
"""


def _db(db_path: Path) -> Any:
    import sqlite_utils  # dev dep — not shipped to runtime

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(db_path)
    if "runs" not in db.table_names():
        db["runs"].create(  # type: ignore[union-attr]
            {
                "id": int,
                "ts": str,
                "git_sha": str,
                "coverage_pct": float,
                "high": int,
                "med": int,
                "low": int,
                "total": int,
            },
            pk="id",
        )
    if "findings" not in db.table_names():
        db["findings"].create(  # type: ignore[union-attr]
            {
                "id": int,
                "run_id": int,
                "file": str,
                "line": int,
                "severity": str,
                "lens": str,
                "summary": str,
            },
            pk="id",
            foreign_keys=[("run_id", "runs", "id")],
        )
    return db


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def record_run(
    coverage_pct: float,
    findings: list[dict[str, Any]],
    *,
    db_path: Path = DEFAULT_DB,
) -> int:
    from datetime import UTC, datetime

    db = _db(db_path)
    high = sum(1 for f in findings if f.get("severity", "").upper() == "HIGH")
    med = sum(1 for f in findings if f.get("severity", "").upper() == "MED")
    low = sum(1 for f in findings if f.get("severity", "").upper() == "LOW")
    row: dict[str, Any] = {
        "ts": datetime.now(tz=UTC).isoformat(),
        "git_sha": _git_sha(),
        "coverage_pct": coverage_pct,
        "high": high,
        "med": med,
        "low": low,
        "total": len(findings),
    }
    result = db["runs"].insert(row)
    run_id = result.last_pk
    for f in findings:
        db["findings"].insert(
            {
                "run_id": run_id,
                "file": f.get("file", ""),
                "line": int(f.get("line", 0)),
                "severity": f.get("severity", ""),
                "lens": f.get("lens", ""),
                "summary": f.get("summary", ""),
            }
        )
    return run_id  # type: ignore[return-value]


def trend(n: int = 2, *, db_path: Path = DEFAULT_DB) -> dict[str, Any] | None:
    db = _db(db_path)
    rows = list(db["runs"].rows_where(order_by="id desc", limit=n))
    if len(rows) < 2:
        return None
    cur, prev = rows[0], rows[1]
    return {
        "coverage": (prev["coverage_pct"], cur["coverage_pct"]),
        "high": (prev["high"], cur["high"]),
        "med": (prev["med"], cur["med"]),
        "low": (prev["low"], cur["low"]),
    }


def format_trend(t: dict[str, Any]) -> str:
    def _arrow(prev: float, cur: float, *, lower_is_better: bool = False) -> str:
        if cur > prev:
            return "▼" if lower_is_better else "▲"
        if cur < prev:
            return "▲" if lower_is_better else "▼"
        return "="

    cov_prev, cov_cur = t["coverage"]
    h_prev, h_cur = t["high"]
    m_prev, m_cur = t["med"]
    l_prev, l_cur = t["low"]
    return " · ".join(
        [
            f"coverage {cov_prev:.1f}%→{cov_cur:.1f}% {_arrow(cov_prev, cov_cur)}",
            f"HIGH {h_prev}→{h_cur} {_arrow(h_prev, h_cur, lower_is_better=True)}",
            f"MED {m_prev}→{m_cur} {_arrow(m_prev, m_cur, lower_is_better=True)}",
            f"LOW {l_prev}→{l_cur} {_arrow(l_prev, l_cur, lower_is_better=True)}",
        ]
    )


def _run_coverage() -> dict[str, Any]:
    subprocess.run(["uv", "run", "python", "tasks/coverage.py"])
    cov_file = Path("coverage.json")
    if not cov_file.exists():
        raise RuntimeError("coverage runner failed — coverage.json not produced")
    with cov_file.open() as f:
        return json.load(f)  # type: ignore[no-any-return]


def _spawn_agent(cluster: str, *, model: str = SONNET) -> list[dict[str, Any]]:
    cluster_path = Path(cluster)
    py_files = sorted(cluster_path.rglob("*.py"))[:10]
    if not py_files:
        return []
    content_parts: list[str] = []
    for pf in py_files:
        try:
            content_parts.append(f"### {pf}\n{pf.read_text()[:3000]}")
        except OSError:
            continue
    if not content_parts:
        return []
    prompt = _SWEEP_PROMPT.format(
        files="\n".join(str(pf) for pf in py_files),
        content="\n\n".join(content_parts),
    )
    result = subprocess.run(
        [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--disallowedTools",
            "AskUserQuestion",
            "--model",
            model,
            prompt,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    text = result.stdout.strip()
    start = text.find("[")
    end = text.rfind("]") + 1
    if start == -1 or end == 0:
        return []
    try:
        return json.loads(text[start:end])  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return []


def sweep(*, db_path: Path = DEFAULT_DB, model: str = SONNET) -> None:
    print("Running coverage...", flush=True)
    cov_data = _run_coverage()
    coverage_pct = float(cov_data["totals"]["percent_covered"])
    print(f"Coverage: {coverage_pct:.1f}%", flush=True)
    print(f"Sweeping {len(MODULE_CLUSTERS)} module clusters with {model}...", flush=True)
    all_findings: list[dict[str, Any]] = []
    for cluster in MODULE_CLUSTERS:
        print(f"  {cluster}...", flush=True)
        all_findings.extend(_spawn_agent(cluster, model=model))
    record_run(coverage_pct, all_findings, db_path=db_path)
    t = trend(n=2, db_path=db_path)
    if t:
        print(format_trend(t))
    else:
        high = sum(1 for f in all_findings if f.get("severity", "").upper() == "HIGH")
        med = sum(1 for f in all_findings if f.get("severity", "").upper() == "MED")
        low = sum(1 for f in all_findings if f.get("severity", "").upper() == "LOW")
        print(f"coverage {coverage_pct:.1f}% · HIGH {high} · MED {med} · LOW {low} (first run — no prior to compare)")


def main() -> None:
    args = sys.argv[1:]
    db_path = DEFAULT_DB
    for a in args:
        if a.startswith("--db="):
            db_path = Path(a[5:])
    sweep(db_path=db_path)


if __name__ == "__main__":
    main()
