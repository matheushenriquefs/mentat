"""E2E journey: capped exponential backoff with full jitter (lib/backoff.py).

Pure math with an injectable RNG — the recovery engine's respawn spacer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

BACKOFF_PY = Path(__file__).resolve().parents[2] / ".agents/lib/backoff.py"


def _backoff():
    return load_script(BACKOFF_PY, "e2e_backoff")


def test_full_jitter_draws_within_capped_ceiling():
    m = _backoff()
    # rng at its max (→1.0) yields exactly the ceiling; base*2**attempt grows it.
    assert m.full_jitter(0, base=0.5, cap=30.0, rng=lambda: 1.0) == 0.5
    assert m.full_jitter(3, base=0.5, cap=30.0, rng=lambda: 1.0) == 4.0  # 0.5 * 8
    assert m.full_jitter(10, base=0.5, cap=30.0, rng=lambda: 1.0) == 30.0  # clamped to cap


def test_full_jitter_floors_attempt_and_scales_by_rng():
    m = _backoff()
    assert m.full_jitter(-5, base=1.0, cap=30.0, rng=lambda: 1.0) == 1.0  # negative → attempt 0
    assert m.full_jitter(2, base=1.0, cap=30.0, rng=lambda: 0.0) == 0.0  # rng 0 → 0 delay
    assert m.full_jitter(2, base=1.0, cap=30.0, rng=lambda: 0.5) == 2.0  # 0.5 * (1*4)
