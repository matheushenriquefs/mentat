"""Plugin registry — entry-point discovery, config-ordered loading, first-wins slots."""

from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path

from . import HarnessProvider, MentatPlugin

_LIB_ROOT = Path(__file__).resolve().parents[1]
if str(_LIB_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_LIB_ROOT.parent))

from lib.config import load_config_file  # noqa: E402


def _load_config_order(config_path: Path) -> list[str]:
    """Read plugin order from ~/.mentat/config.toml. Returns [] if absent; raises ConfigError if malformed."""
    if not config_path.exists():
        return []
    try:
        data = load_config_file(config_path)
        plugins = data.get("plugins")
        if not isinstance(plugins, dict):
            return []
        order = plugins.get("order")  # type: ignore[union-attr]
        if not isinstance(order, list):
            return []
        return [str(x) for x in order]  # type: ignore[unknown]
    except KeyError, TypeError:
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
    builtin_harness: HarnessProvider,
) -> HarnessProvider:
    """Apply first-wins slot resolution with config ordering.

    Returns harness_provider. Built-in acts as last-resort fallback.
    No diff slot — use raw `git diff <base>..HEAD` in your terminal.
    """
    ordered = sorted(plugins, key=lambda p: order.index(p.name) if p.name in order else len(order))

    harness: HarnessProvider | None = None
    for plugin in ordered:
        if harness is None and plugin.harness is not None:
            harness = plugin.harness
        if harness is not None:
            break

    return harness or builtin_harness


def load(config_path: Path | None = None) -> list[MentatPlugin]:
    """Discover all installed plugins. Raises on load failure."""
    if config_path is None:
        config_path = Path.home() / ".mentat" / "config.toml"
    plugins = _discover_plugins()
    order = _load_config_order(config_path)
    # Re-sort by config order if provided
    if order:
        plugins.sort(key=lambda p: order.index(p.name) if p.name in order else len(order))
    return plugins
