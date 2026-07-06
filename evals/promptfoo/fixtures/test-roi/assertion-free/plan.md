# Plan: discount calculator

Add `apply_discount(price: float, pct: float) -> float`:

- returns `price * (1 - pct/100)`;
- raises `ValueError` when `pct` is outside `0..100`;
- rounds the result to 2 decimals.
