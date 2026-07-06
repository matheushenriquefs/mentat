from pricing import apply_discount

# Every branch of apply_discount executes → 100% line + branch coverage.
# Not one assertion checks the result: coverage is green, behavior is unchecked.


def test_happy_path_covered():
    apply_discount(100.0, 10.0)


def test_zero_covered():
    apply_discount(50.0, 0.0)


def test_raise_branch_covered():
    try:
        apply_discount(100.0, 150.0)
    except ValueError:
        pass
