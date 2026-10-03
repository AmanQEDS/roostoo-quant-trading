"""Benchmarks (brief section 19): buy&hold, equal-weight, simple MA, simple RSI - same costs, same pools."""
from __future__ import annotations
import numpy as np
import pandas as pd
from ..backtest.engine import BacktestResult, PortfolioConfig
from ..backtest.metrics import perf_report, rolling_window_report
from .grid import S
from .runner import evaluate


def buy_hold_equal_weight(panel, pcfg: PortfolioConfig, only: list[str] | None = None) -> BacktestResult:
    """Equal-weight buy & hold per pool, bought at each asset's first tradable exec price, never rebalanced."""
    cols = only or list(panel.columns)
    w = {"crypto": pcfg.crypto_weight, "equity": 1 - pcfg.crypto_weight}
    n = len(panel.index); ar = np.arange(n)
    eq = np.zeros(n); fees = turn = 0.0
    for k in ("crypto", "equity"):
        kc = [c for c in cols if panel.classes[c] == k and panel.tradable[c].any()]
        pool = pcfg.capital * w[k]
        if not kc:
            eq += pool; continue
        per = pool / len(kc)
        for c in kc:
            i = int(panel.tradable[c].values.argmax())
            px = panel.exec_px[c].iloc[i] * (1 + pcfg.slip_bps[k] / 1e4)
            q = per / (1 + pcfg.fee) / px
            nt = q * px; fees += nt * pcfg.fee; turn += nt
            leftover = per - nt * (1 + pcfg.fee)
            eq += np.where(ar <= i, per, leftover + q * panel.close[c].ffill().fillna(0).values)
        eq += pool - per * len(kc)                      # (zero unless an asset never became tradable)
    curve = pd.DataFrame({"equity_total": eq, "exposure": 1.0, "n_pos": len(cols)}, index=panel.index)
    return BacktestResult(curve, pd.DataFrame(), fees, turn, {}, [])


def baseline_suite(panel_full, ext, pcfg, tf, start, end) -> pd.DataFrame:
    p = panel_full.slice(start, end)
    rows = {}
    rows["buy&hold equal-weight (all)"] = buy_hold_equal_weight(p, pcfg)
    btc = [c for c in p.columns if c.upper().startswith("BTC")]
    if btc:
        rows["buy&hold BTC (crypto pool only)"] = buy_hold_equal_weight(p, pcfg, only=btc)
    out = {}
    for name, res in rows.items():
        r = perf_report(res, panel_full.freq_min, pcfg.capital); r.update(rolling_window_report(res.curve.equity_total))
        out[name] = r
    for name, sp in {"simple MA cross 20/50": S("ma_cross", classes=("crypto", "equity"), fast=20, slow=50, kind="ema"),
                     "simple RSI 14 (30/55)": S("rsi_mr", classes=("crypto", "equity"), n=14, x=30, y=55)}.items():
        _, r = evaluate(panel_full, sp, ext, pcfg, start, end, tf)
        out[name] = r
    cols = ["total_return", "sharpe", "sortino", "calmar", "max_dd", "vol", "n_trades", "fees_paid", "composite", "w14_ret_med", "w14_mdd_worst"]
    return pd.DataFrame(out).T[[c for c in cols if c in pd.DataFrame(out).T.columns]]
