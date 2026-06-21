"""Tests for plugin registry — ADR-0009. diff slot removed in F3."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from plugins import MentatPlugin
from plugins.registry import resolve_slots


class FakeHarness:
    name = "fake"

    def invoke(self, cmd: list[str]) -> int:
        return 0


def test_zero_plugins_uses_builtin_harness() -> None:
    builtin_harness = FakeHarness()
    harness = resolve_slots([], [], builtin_harness)
    assert harness is builtin_harness


def test_plugin_overrides_harness_builtin() -> None:
    custom_harness = FakeHarness()
    custom_harness.name = "custom"
    plugin = MentatPlugin(name="my-plugin", harness=custom_harness)
    builtin_harness = FakeHarness()
    harness = resolve_slots([plugin], [], builtin_harness)
    assert harness is custom_harness


def test_two_plugins_both_providing_harness_first_wins() -> None:
    harness_a = FakeHarness()
    harness_a.name = "a"
    harness_b = FakeHarness()
    harness_b.name = "b"
    plugin_a = MentatPlugin(name="plugin-a", harness=harness_a)
    plugin_b = MentatPlugin(name="plugin-b", harness=harness_b)
    builtin_harness = FakeHarness()
    harness = resolve_slots([plugin_a, plugin_b], [], builtin_harness)
    assert harness is harness_a


def test_config_order_controls_first_wins() -> None:
    harness_a = FakeHarness()
    harness_a.name = "a"
    harness_b = FakeHarness()
    harness_b.name = "b"
    plugin_a = MentatPlugin(name="plugin-a", harness=harness_a)
    plugin_b = MentatPlugin(name="plugin-b", harness=harness_b)
    builtin_harness = FakeHarness()
    # Order says plugin-b first
    harness = resolve_slots([plugin_a, plugin_b], ["plugin-b", "plugin-a"], builtin_harness)
    assert harness is harness_b


def test_plugin_missing_entry_point_factory_raises() -> None:
    """Simulates a broken entry-point that raises on load."""
    from plugins import registry

    bad_ep = MagicMock()
    bad_ep.name = "broken-plugin"
    bad_ep.load.side_effect = ImportError("module not found")

    with patch("importlib.metadata.entry_points", return_value=[bad_ep]):
        try:
            registry._discover_plugins()
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "broken-plugin" in str(exc)
