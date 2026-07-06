import pytest

from pricing import apply_discount


def test_applies_percentage():
    assert apply_discount(100.0, 10.0) == 90.0


def test_rounds_to_two_decimals():
    assert apply_discount(9.99, 33.0) == 6.69


def test_zero_pct_is_identity():
    assert apply_discount(50.0, 0.0) == 50.0


def test_full_pct_is_zero():
    assert apply_discount(50.0, 100.0) == 0.0


def test_rejects_out_of_range():
    with pytest.raises(ValueError):
        apply_discount(100.0, 150.0)
