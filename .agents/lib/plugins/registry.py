"""Plugin registry — entry-point discovery, config-ordered loading, first-wins slots."""

from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path

from . import DiffProvider, HarnessProvider, MentatPlugin


def _load_config_order(config_path: Path) -> list[str]:
    """Read plugin order from ~/.mentat/config.jsonc. Returns [] if absent or malformed."""
    if not config_path.exists():
        return []
    try:
        text = config_path.read_text()
        # strip // line comments (JSONC)
        lines = [ln for ln in text.splitlines() if not ln.strip().startswith("//")]
        data = json.loads("\n".join(lines))
        return list(data.get("plugins", {}).get("order", []))
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def _discover_plugins() -> list[MentatPlugin]:
    """Load plugins from 'mentat-plugin' entry-point group."""
    plugins: list[MentatPlugin] = []
    eps = importlib.metadata.entry_points(group="mentat-plugin")
    for ep in eps:
        try:
            factory = ep.load()
            plugin = factory()
            if not isinstance(plugin, MentatPlugin):
                raise TypeError(f"entry-point {ep.name!r} factory returned {type(plugin)!r}, not MentatPlugin")
            plugins.append(plugin)
        except Exception as exc:
            raise RuntimeError(f"mentat-plugin: failed to load entry-point {ep.name!r}: {exc}") from exc
    return plugins


def resolve_slots(
    plugins: list[MentatPlugin],
    order: list[str],
    builtin_diff: DiffProvider,
    builtin_harness: HarnessProvider,
) -> tuple[DiffProvider, HarnessProvider]:
    """Apply first-wins slot resolution with config ordering.

    Returns (diff_provider, harness_provider).
    Built-ins act as last-resort fallback.
    """
    # Reorder by config-specified order; unknown names appended at end
    ordered = sorted(plugins, key=lambda p: order.index(p.name) if p.name in order else len(order))

    diff: DiffProvider | None = None
    harness: HarnessProvider | None = None

    for plugin in ordered:
        if diff is None and plugin.diff is not None:
            diff = plugin.diff
        if harness is None and plugin.harness is not None:
            harness = plugin.harness
        if diff is not None and harness is not None:
            break

    return (diff or builtin_diff, harness or builtin_harness)


def load(config_path: Path | None = None) -> list[MentatPlugin]:
    """Discover all installed plugins. Raises on load failure."""
    if config_path is None:
        config_path = Path.home() / ".mentat" / "config.jsonc"
    plugins = _discover_plugins()
    order = _load_config_order(config_path)
    # Re-sort by config order if provided
    if order:
        plugins.sort(key=lambda p: order.index(p.name) if p.name in order else len(order))
    return plugins
