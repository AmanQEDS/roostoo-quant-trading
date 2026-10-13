"""Causal BTC volatility gate for new live entries."""
from __future__ import annotations

import numpy as np
import pandas as pd


def f2_regime(
    close: pd.DataFrame,
    reference_symbol: str = "BTC",
    window_days: int = 14,
    bars_per_day: int = 48,
) -> dict:
    """Match the research F2 definition; unknown regime fails closed.

    Realized volatility is rolling standard deviation of log returns.
    High volatility is realized volatility above its expanding median.
    The classification is shifted one bar so the decision uses prior-bar data.
    """
    if window_days < 1 or bars_per_day < 1:
        raise ValueError("window_days and bars_per_day must be positive")

    window = int(window_days) * int(bars_per_day)
    unknown = {
        "allowed": False,
        "high_vol": None,
        "rv": None,
        "median": None,
        "reason": "unknown_regime",
    }

    if reference_symbol not in close.columns or close.empty:
        return {**unknown, "reason": "missing_reference"}

    prices = pd.to_numeric(close[reference_symbol], errors="coerce")
    prices = prices.where(np.isfinite(prices) & (prices > 0))
    log_returns = np.log(prices / prices.shift(1))
    rv = log_returns.rolling(window, min_periods=window).std()
    expanding_median = rv.expanding(min_periods=window).median()

    high_vol = (rv > expanding_median).where(
        rv.notna() & expanding_median.notna()
    ).shift(1)

    label = high_vol.iloc[-1]
    previous_rv = rv.shift(1).iloc[-1]
    previous_median = expanding_median.shift(1).iloc[-1]

    if pd.isna(label):
        return {
            **unknown,
            "rv": float(previous_rv) if pd.notna(previous_rv) else None,
            "median": (
                float(previous_median) if pd.notna(previous_median) else None
            ),
        }

    is_high = bool(label)
    return {
        "allowed": not is_high,
        "high_vol": is_high,
        "rv": float(previous_rv) if pd.notna(previous_rv) else None,
        "median": float(previous_median) if pd.notna(previous_median) else None,
        "reason": "high_volatility" if is_high else "normal_volatility",
    }
