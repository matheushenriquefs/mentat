"""Pure rendering of InstallPlan to string."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .plan import InstallPlan

_GREEN = "\033[32m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"


def render(plan: InstallPlan, *, color: bool | None = None) -> str:
    if color is None:
        color = sys.stdout.isatty()

    lines: list[str] = []

    def _c(text: str, ansi: str) -> str:
        return f"{ansi}{text}{_RESET}" if color else text

    if plan.add:
        lines.append("Added:")
        for a in plan.add:
            lines.append(f"  {_c('+', _GREEN)} {a.target}")

    if plan.update:
        lines.append("Updated:")
        for a in plan.update:
            lines.append(f"  {_c('~', _CYAN)} {a.target}")

    if plan.conflicts:
        lines.append("Conflicts (real file/dir at target — D13 abort policy):")
        for p in plan.conflicts:
            lines.append(f"  {_c('✗', _RED)} {p}")

    if plan.stale:
        lines.append("Stale (manual cleanup recommended):")
        for p in plan.stale:
            lines.append(f"  {_c('!', _YELLOW)} {p}")

    if plan.missing_companions:
        lines.append("Missing companion skills:")
        for c in plan.missing_companions:
            lines.append(f"  {_c('?', _RED)} {c}")

    if plan.skipped:
        lines.append("Skipped (harness not detected):")
        for a in plan.skipped[:3]:
            lines.append(f"  {_c('-', _YELLOW)} {a.target.parent} (…)")
        if len(plan.skipped) > 3:
            lines.append(f"  … and {len(plan.skipped) - 3} more")

    if not lines:
        lines.append("Nothing to install.")

    return "\n".join(lines) + "\n"
