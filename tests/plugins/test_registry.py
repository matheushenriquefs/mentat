"""Tests for plugin registry — ADR-0009."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from plugins import MentatPlugin
from plugins.registry import resolve_slots


class FakeDiff:
    def get_diff(self, worktree: str) -> str:
        return "fake diff"


class FakeHarness:
    name = "fake"

    def invoke(self, cmd: list[str]) -> int:
        return 0


def test_zero_plugins_uses_builtins() -> None:
    builtin_diff = FakeDiff()
    builtin_harness = FakeHarness()
    diff, harness = resolve_slots([], [], builtin_diff, builtin_harness)
    assert diff is builtin_diff
    assert harness is builtin_harness


def test_one_plugin_overrides_diff_builtin() -> None:
    custom_diff = FakeDiff()
    plugin = MentatPlugin(name="my-plugin", diff=custom_diff)
    builtin_diff = FakeDiff()
    builtin_harness = FakeHarness()
    diff, harness = resolve_slots([plugin], [], builtin_diff, builtin_harness)
    assert diff is custom_diff
    assert harness is builtin_harness


def test_two_plugins_both_providing_diff_first_wins() -> None:
    diff_a = FakeDiff()
    diff_b = FakeDiff()
    plugin_a = MentatPlugin(name="plugin-a", diff=diff_a)
    plugin_b = MentatPlugin(name="plugin-b", diff=diff_b)
    builtin_diff = FakeDiff()
    builtin_harness = FakeHarness()
    diff, _ = resolve_slots([plugin_a, plugin_b], [], builtin_diff, builtin_harness)
    assert diff is diff_a


def test_config_order_controls_first_wins() -> None:
    diff_a = FakeDiff()
    diff_b = FakeDiff()
    plugin_a = MentatPlugin(name="plugin-a", diff=diff_a)
    plugin_b = MentatPlugin(name="plugin-b", diff=diff_b)
    builtin_diff = FakeDiff()
    builtin_harness = FakeHarness()
    # Order says plugin-b first
    diff, _ = resolve_slots([plugin_a, plugin_b], ["plugin-b", "plugin-a"], builtin_diff, builtin_harness)
    assert diff is diff_b


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
