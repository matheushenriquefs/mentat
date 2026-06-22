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


# ── _load_config_order ───────────────────────────────────────────────────────


def test_load_config_order_absent_returns_empty(tmp_path) -> None:
    from plugins.registry import _load_config_order

    assert _load_config_order(tmp_path / "nonexistent.toml") == []


def test_load_config_order_plugins_not_dict_returns_empty(tmp_path) -> None:
    from plugins.registry import _load_config_order

    cfg = tmp_path / "config.toml"
    cfg.write_text("[plugins]\n")  # plugins key is a table; write as scalar
    # Write as a string value that parses to non-dict
    cfg.write_text('plugins = "cursor"\n')
    assert _load_config_order(cfg) == []


def test_load_config_order_order_not_list_returns_empty(tmp_path) -> None:
    from plugins.registry import _load_config_order

    cfg = tmp_path / "config.toml"
    cfg.write_text('[plugins]\norder = "a,b"\n')
    assert _load_config_order(cfg) == []


def test_load_config_order_valid_returns_list(tmp_path) -> None:
    from plugins.registry import _load_config_order

    cfg = tmp_path / "config.toml"
    cfg.write_text('[plugins]\norder = ["plugin-b", "plugin-a"]\n')
    assert _load_config_order(cfg) == ["plugin-b", "plugin-a"]


# ── load ─────────────────────────────────────────────────────────────────────


def test_load_with_no_config_path_does_not_raise() -> None:
    from plugins.registry import load

    with patch("plugins.registry._discover_plugins", return_value=[]):
        plugins = load(config_path=None)
    assert isinstance(plugins, list)


def test_load_with_order_sorts_by_config(tmp_path) -> None:
    from plugins.registry import load

    cfg = tmp_path / "config.toml"
    cfg.write_text('[plugins]\norder = ["plugin-b", "plugin-a"]\n')
    plugin_a = MentatPlugin(name="plugin-a")
    plugin_b = MentatPlugin(name="plugin-b")
    with patch("plugins.registry._discover_plugins", return_value=[plugin_a, plugin_b]):
        plugins = load(config_path=cfg)
    assert plugins[0].name == "plugin-b"
    assert plugins[1].name == "plugin-a"


def test_load_without_order_returns_unsorted(tmp_path) -> None:
    from plugins.registry import load

    cfg = tmp_path / "config.toml"
    cfg.write_text('harness = "cursor"\n')  # no plugins section
    plugin_a = MentatPlugin(name="plugin-a")
    with patch("plugins.registry._discover_plugins", return_value=[plugin_a]):
        plugins = load(config_path=cfg)
    assert len(plugins) == 1


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


def test_discover_plugins_factory_returns_non_plugin_raises() -> None:
    """Factory callable loads but returns wrong type — TypeError wrapped in RuntimeError."""
    from plugins import registry

    bad_ep = MagicMock()
    bad_ep.name = "wrong-type-plugin"

    def bad_factory() -> str:
        return "not a MentatPlugin"

    bad_ep.load.return_value = bad_factory

    with patch("importlib.metadata.entry_points", return_value=[bad_ep]):
        try:
            registry._discover_plugins()
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "wrong-type-plugin" in str(exc)
