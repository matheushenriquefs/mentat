"""Plan resolution seam. Single home for slug-or-path arithmetic. Stdlib only (ADR-0008)."""

from __future__ import annotations

from pathlib import Path


def resolve_plan_ref(ref: str) -> Path:
    """Resolve a plan slug-or-path to a canonical absolute Path.

    A ref containing '/' or ending in '.md' is treated as a filesystem path
    (expanded and resolved). Otherwise it is a slug mapped to
    ``~/.agents/plans/<slug>.md``. Pure path arithmetic — does not stat.
    """
    if "/" in ref or ref.endswith(".md"):
        return Path(ref).expanduser().resolve()
    return Path.home() / ".agents" / "plans" / f"{ref}.md"
