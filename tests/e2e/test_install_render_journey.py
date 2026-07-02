"""E2E: the install-plan renderer — pure InstallPlan → string.

Drives ``mentat-install/scripts/render.py`` over lightweight ``SimpleNamespace``
stand-ins for the real ``InstallPlan`` (the renderer only reads attributes). Every
section list is populated to hit each header, ``skipped`` carries >3 items to hit
the "… and N more" truncation, both the ``color=True`` ANSI branch and the
``color=False`` plain branch are asserted, the ``color=None`` isatty resolution is
covered by monkeypatching ``sys.stdout.isatty`` True/False, and the empty plan
hits the "Nothing to install." fallback.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_PY = REPO_ROOT / ".agents/skills/mentat-install/scripts/render.py"


def _item(target: str) -> SimpleNamespace:
    return SimpleNamespace(target=target)


def _skipped(parent: str) -> SimpleNamespace:
    return SimpleNamespace(target=SimpleNamespace(parent=Path(parent)))


def _full_plan() -> SimpleNamespace:
    return SimpleNamespace(
        add=[_item("a/one"), _item("a/two")],
        update=[_item("u/one")],
        conflicts=["c/one", "c/two"],
        stale=["s/one"],
        missing_companions=["ripgrep"],
        skipped=[_skipped(f"sk/{i}") for i in range(5)],
    )


def _empty_plan() -> SimpleNamespace:
    return SimpleNamespace(add=[], update=[], conflicts=[], stale=[], missing_companions=[], skipped=[])


def test_render_plain_shows_all_headers_and_truncation():
    render = load_script(RENDER_PY, "install_render_plain")
    out = render.render(_full_plan(), color=False)
    assert "Added:" in out
    assert "Updated:" in out
    assert "Conflicts (real file/dir at target — manual resolution required):" in out
    assert "Stale (manual cleanup recommended):" in out
    assert "Missing companion skills:" in out
    assert "Skipped (harness not detected):" in out
    # 5 skipped items, only 3 rendered → "… and 2 more".
    assert "… and 2 more" in out
    # color=False → no ANSI escapes.
    assert "\033[" not in out


def test_render_color_emits_ansi():
    render = load_script(RENDER_PY, "install_render_color")
    out = render.render(_full_plan(), color=True)
    assert "\033[" in out


def test_render_color_none_resolves_true_under_tty(monkeypatch):
    render = load_script(RENDER_PY, "install_render_tty")
    monkeypatch.setattr(render.sys.stdout, "isatty", lambda: True)
    out = render.render(_full_plan(), color=None)
    assert "\033[" in out


def test_render_color_none_resolves_false_when_not_tty(monkeypatch):
    render = load_script(RENDER_PY, "install_render_notty")
    monkeypatch.setattr(render.sys.stdout, "isatty", lambda: False)
    out = render.render(_full_plan(), color=None)
    assert "\033[" not in out


def test_render_empty_plan_says_nothing_to_install():
    render = load_script(RENDER_PY, "install_render_empty")
    assert render.render(_empty_plan(), color=False) == "Nothing to install.\n"
