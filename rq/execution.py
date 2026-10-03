"""Order sizing/rounding shared by live trading and unit tests.  Mirrors the backtest engine's rules:
size = pos_frac x CURRENT pool cash, floor to AmountPrecision, respect MiniOrder, keep fee headroom."""
from __future__ import annotations
import math


def floor_qty(qty: float, amt_prec: int) -> float:
    f = 10 ** amt_prec
    return math.floor(qty * f + 1e-9) / f


def plan_entry(pool_cash: float, pos_frac: float, price: float, amt_prec: int, mini_order: float,
               fee: float, scale: float = 1.0) -> float:
    """Return the quantity to BUY (0.0 if below the minimum order)."""
    notional = min(pos_frac * pool_cash * scale, pool_cash / (1 + fee))
    q = floor_qty(notional / price, amt_prec)
    return q if q * price >= max(mini_order, 1e-12) else 0.0


def plan_exit(free_qty: float, amt_prec: int) -> float:
    return floor_qty(free_qty, amt_prec)
