"""Combine shortlisted strategies into one portfolio and test whether it improves Sharpe/Sortino/Calmar/DD."""
from __future__ import annotations
import numpy as np
import pandas as pd
from ..backtest.metrics import ratios


def combine(curves: dict[str, pd.Series], weights: dict[str, float] | None = None, initial: float = 100_000.0):
    daily = pd.DataFrame({k: v.resample("1D").last().pct_change() for k, v in curves.items()}).dropna()
    w = pd.Series(weights or {k: 1 / len(curves) for k in curves})
    w = w / w.sum()
    r = (daily * w).sum(axis=1)                        # daily-rebalanced sleeves
    eq = initial * (1 + r).cumprod()
    span = (eq.index[-1] - eq.index[0]).days or 1
    rep = ratios(r, eq, span)
    rep["total_return"] = eq.iloc[-1] / initial - 1
    singles = pd.DataFrame({k: ratios(daily[k], initial * (1 + daily[k]).cumprod(), span) for k in curves}).T
    return eq, daily.corr(), rep, singles
