from pricing import DEFAULT_PCT, Discounter, apply_discount


def test_default_pct_constant():
    # getter / constant read — no behavior asserted
    assert DEFAULT_PCT == 10


def test_discounter_has_name():
    # attribute read only
    d = Discounter()
    assert d.name == "discounter"


def test_apply_discount_runs():
    # calls the code, asserts nothing about the result
    apply_discount(100.0, 10.0)


def test_apply_discount_returns_float():
    # asserts a stdlib/type fact, not the contract
    assert isinstance(apply_discount(100.0, 10.0), float)
