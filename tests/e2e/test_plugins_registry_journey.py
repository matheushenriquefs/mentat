"""E2E: drive the plugin registry through real config-file + discovery journeys.

Loaded as a package (``lib.plugins.registry``) because registry.py uses a
relative ``from . import ...``. The root ``conftest.py`` already puts both
``.agents`` and ``.agents/lib`` on ``sys.path``, so ``import lib.plugins...``
resolves; we mirror the load pattern the target module itself relies on.

Covers ``_load_config_order`` against real ``config.toml`` files on disk,
``resolve_slots`` first-wins slot resolution with config ordering, the
``load`` default- and explicit-path branches, and the ``_discover_plugins``
entry-point happy/error branches by monkeypatching the loaded module's
``importlib``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENTS = str(REPO_ROOT / ".agents")
if _AGENTS not in sys.path:
    sys.path.insert(0, _AGENTS)

import lib.plugins.registry as registry  # noqa: E402
from lib.plugins import HarnessProvider, MentatPlugin  # noqa: E402
from lib.plugins.builtin.claude_code import ClaudeCodeHarness  # noqa: E402
from lib.plugins.builtin.cursor import CursorHarness  # noqa: E402

# ── stand-ins ────────────────────────────────────────────────────────────────


class _StubHarness:
    """A minimal HarnessProvider stand-in (matches the runtime Protocol)."""

    def __init__(self, name: str) -> None:
        self.name = name

    def invoke(self, cmd: list[str]) -> int:  # pragma: no cover - never invoked
        return 0


class _FakeEntryPoint:
    """Mimics importlib.metadata.EntryPoint: has .name and .load()."""

    def __init__(self, name: str, factory) -> None:
        self.name = name
        self._factory = factory

    def load(self):
        return self._factory


def _patch_entry_points(monkeypatch: pytest.MonkeyPatch, eps: list) -> None:
    """Force registry's importlib.metadata.entry_points(group=...) to return eps."""

    def _fake_entry_points(*, group: str) -> list:
        assert group == "mentat-plugin"
        return eps

    monkeypatch.setattr(registry.importlib.metadata, "entry_points", _fake_entry_points)


# ── _load_config_order (lines 18-32) ─────────────────────────────────────────


def test_config_order_file_absent_returns_empty(tmp_path: Path) -> None:
    """No config.toml on disk → []. Hits line 20-21 (not exists → return)."""
    assert registry._load_config_order(tmp_path / "nope.toml") == []


def test_config_order_no_plugins_table_returns_empty(tmp_path: Path) -> None:
    """Real file, but no [plugins] table → []. Hits 23-26 (plugins not dict)."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('harness = "cursor"\n')
    assert registry._load_config_order(cfg) == []


def test_config_order_order_not_list_returns_empty(tmp_path: Path) -> None:
    """[plugins] present but order is a scalar → []. Hits 27-29 (order not list)."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[plugins]\norder = "a,b"\n')
    assert registry._load_config_order(cfg) == []


def test_config_order_valid_list_is_returned(tmp_path: Path) -> None:
    """Valid order list → coerced to list[str]. Hits 22-30 (happy path, line 30)."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[plugins]\norder = ["a", "b"]\n')
    assert registry._load_config_order(cfg) == ["a", "b"]


def test_config_order_malformed_toml_returns_empty(tmp_path: Path) -> None:
    """Malformed TOML → load_config_file returns {} → data.get('plugins') is None → [].

    Exercises the 23-26 path where the parse fails silently upstream.
    """
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is = = not valid toml [[[\n")
    assert registry._load_config_order(cfg) == []


def test_config_order_swallows_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A TypeError raised while reading config is caught → []. Hits 31-32."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("[plugins]\n")

    def _boom(_path):
        raise TypeError("malformed")

    monkeypatch.setattr(registry, "load_config_file", _boom)
    assert registry._load_config_order(cfg) == []


# ── resolve_slots (lines 61-70) ──────────────────────────────────────────────


def test_resolve_slots_empty_falls_back_to_builtin() -> None:
    """No plugins → builtin_harness returned. Hits 61 (sort of []) + 70 fallback."""
    builtin = ClaudeCodeHarness()
    result = registry.resolve_slots([], [], builtin)
    assert result is builtin


def test_resolve_slots_first_with_harness_wins() -> None:
    """First plugin carrying a non-None harness wins. Hits 63-68."""
    harness_a = _StubHarness("a")
    harness_b = _StubHarness("b")
    plugin_a = MentatPlugin(name="plugin-a", harness=harness_a)
    plugin_b = MentatPlugin(name="plugin-b", harness=harness_b)
    result = registry.resolve_slots([plugin_a, plugin_b], [], ClaudeCodeHarness())
    assert result is harness_a


def test_resolve_slots_skips_none_harness_then_takes_next() -> None:
    """A plugin with harness=None is skipped; the next non-None wins. Hits 64-68."""
    real = _StubHarness("real")
    no_harness = MentatPlugin(name="p1")  # harness defaults to None
    with_harness = MentatPlugin(name="p2", harness=real)
    result = registry.resolve_slots([no_harness, with_harness], [], ClaudeCodeHarness())
    assert result is real


def test_resolve_slots_config_order_re_sorts() -> None:
    """Config order re-sorts plugins so a later-listed plugin can win. Hits 61."""
    harness_a = _StubHarness("a")
    harness_b = _StubHarness("b")
    plugin_a = MentatPlugin(name="plugin-a", harness=harness_a)
    plugin_b = MentatPlugin(name="plugin-b", harness=harness_b)
    # Order puts plugin-b first, so its harness wins despite input order.
    result = registry.resolve_slots([plugin_a, plugin_b], ["plugin-b", "plugin-a"], ClaudeCodeHarness())
    assert result is harness_b


def test_resolve_slots_unordered_plugin_sorts_last() -> None:
    """A plugin absent from order is sorted to the end (index == len(order))."""
    harness_known = _StubHarness("known")
    harness_unknown = _StubHarness("unknown")
    known = MentatPlugin(name="known", harness=harness_known)
    unknown = MentatPlugin(name="unknown", harness=harness_unknown)
    # unknown is not in order, so known (in order) sorts first and wins.
    result = registry.resolve_slots([unknown, known], ["known"], ClaudeCodeHarness())
    assert result is harness_known


def test_resolve_slots_accepts_builtin_harness_protocol() -> None:
    """Both builtin adapters satisfy HarnessProvider and flow through as fallback."""
    for builtin in (ClaudeCodeHarness(), CursorHarness()):
        assert isinstance(builtin, HarnessProvider)
        assert registry.resolve_slots([], [], builtin) is builtin


# ── _discover_plugins (lines 37-48) ──────────────────────────────────────────


def test_discover_plugins_no_entry_points_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """No installed entry points → []. Hits 37-38-48 (empty loop)."""
    _patch_entry_points(monkeypatch, [])
    assert registry._discover_plugins() == []


def test_discover_plugins_good_factory_appends(monkeypatch: pytest.MonkeyPatch) -> None:
    """A factory returning a real MentatPlugin is appended + returned. Hits 40-45."""
    good = _FakeEntryPoint("good-plugin", lambda: MentatPlugin(name="good-plugin"))
    _patch_entry_points(monkeypatch, [good])
    plugins = registry._discover_plugins()
    assert [p.name for p in plugins] == ["good-plugin"]
    assert isinstance(plugins[0], MentatPlugin)


def test_discover_plugins_wrong_type_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory returns a non-MentatPlugin → TypeError wrapped in RuntimeError. Hits 43-48."""
    bad = _FakeEntryPoint("wrong-type-plugin", lambda: "not a plugin")
    _patch_entry_points(monkeypatch, [bad])
    with pytest.raises(RuntimeError) as excinfo:
        registry._discover_plugins()
    assert "wrong-type-plugin" in str(excinfo.value)
    # The wrapped cause is the TypeError raised on the isinstance check.
    assert isinstance(excinfo.value.__cause__, TypeError)


def test_discover_plugins_load_failure_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A factory that raises on load() is wrapped in RuntimeError. Hits 46-47."""

    class _Boom:
        name = "broken-plugin"

        def load(self):
            raise ImportError("module not found")

    _patch_entry_points(monkeypatch, [_Boom()])
    with pytest.raises(RuntimeError) as excinfo:
        registry._discover_plugins()
    assert "broken-plugin" in str(excinfo.value)


# ── load (lines 73-82) ───────────────────────────────────────────────────────


def test_load_default_config_path_no_raise(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """config_path=None → derives Path.home()/.mentat/config.toml. Hits 75-76.

    Point HOME at a tmp dir with no config so _load_config_order returns []
    and no plugins are installed → load returns []. Asserts type + no raise.
    """
    monkeypatch.setattr(registry.Path, "home", classmethod(lambda cls: tmp_path))
    _patch_entry_points(monkeypatch, [])
    plugins = registry.load(config_path=None)
    assert isinstance(plugins, list)
    assert plugins == []


def test_load_explicit_path_with_order_sorts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit config with an order list re-sorts discovered plugins. Hits 77-81."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[plugins]\norder = ["plugin-b", "plugin-a"]\n')
    ep_a = _FakeEntryPoint("plugin-a", lambda: MentatPlugin(name="plugin-a"))
    ep_b = _FakeEntryPoint("plugin-b", lambda: MentatPlugin(name="plugin-b"))
    _patch_entry_points(monkeypatch, [ep_a, ep_b])
    plugins = registry.load(config_path=cfg)
    assert [p.name for p in plugins] == ["plugin-b", "plugin-a"]


def test_load_explicit_path_without_order_returns_unsorted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No order list → the discovered plugin list is returned as-is. Hits 80 (falsy)."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('harness = "cursor"\n')  # no [plugins] table
    ep = _FakeEntryPoint("only-plugin", lambda: MentatPlugin(name="only-plugin"))
    _patch_entry_points(monkeypatch, [ep])
    plugins = registry.load(config_path=cfg)
    assert [p.name for p in plugins] == ["only-plugin"]


def test_load_explicit_path_absent_config_no_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit path to a missing file → empty order → plugins unsorted. Hits 78-82."""
    _patch_entry_points(monkeypatch, [])
    plugins = registry.load(config_path=tmp_path / "missing.toml")
    assert plugins == []
