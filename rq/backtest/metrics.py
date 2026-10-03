"""Performance reporting. Primary ratios are computed on DAILY (UTC) equity returns and annualised with
sqrt(365) (crypto trades every day).  The organisers have not published their exact method, so we ALSO
report bar-frequency ratios and, crucially, the distribution over rolling 14-day windows - the live
competition is a single 14-day window, so the median/worst window matters more than a 3-year Sharpe.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from ..constants import SCORE_WEIGHTS

ANN = 365


def _dd_series(eq: pd.Series) -> pd.Series:
    return eq / eq.cummax() - 1.0


def ratios(daily_ret: pd.Series, eq_daily: pd.Series, span_days: float) -> dict:
    r = daily_ret.dropna()
    if len(r) < 3 or eq_daily.iloc[0] <= 0:
        return {k: np.nan for k in ["vol", "downside_dev", "sharpe", "sortino", "calmar", "cagr", "max_dd", "avg_dd", "composite"]}
    mu, sd = r.mean(), r.std(ddof=1)
    dd_dev = np.sqrt((np.minimum(r, 0) ** 2).mean())
    total = eq_daily.iloc[-1] / eq_daily.iloc[0] - 1
    cagr = (1 + total) ** (365 / max(span_days, 1)) - 1 if total > -1 else -1.0
    dd = _dd_series(eq_daily)
    mdd = dd.min()
    sharpe = mu / sd * np.sqrt(ANN) if sd > 0 else np.nan
    sortino = mu / dd_dev * np.sqrt(ANN) if dd_dev > 0 else np.nan
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    comp = np.nansum([SCORE_WEIGHTS["sortino"] * sortino, SCORE_WEIGHTS["sharpe"] * sharpe, SCORE_WEIGHTS["calmar"] * calmar]) \
        if not np.isnan([sortino, sharpe, calmar]).all() else np.nan
    return {"vol": sd * np.sqrt(ANN), "downside_dev": dd_dev * np.sqrt(ANN), "sharpe": sharpe, "sortino": sortino,
            "calmar": calmar, "cagr": cagr, "max_dd": mdd, "avg_dd": dd.mean(), "composite": comp}


def trade_stats(trades: pd.DataFrame, span_days: float, freq_min: int, avg_equity: float, turnover: float) -> dict:
    if trades is None or trades.empty:
        return {"n_trades": 0, "win_rate": np.nan, "avg_win": np.nan, "avg_loss": np.nan, "profit_factor": np.nan,
                "trades_per_day": 0.0, "avg_hold_h": np.nan, "turnover_x": 0.0}
    w, l = trades[trades.pnl_net > 0].pnl_net, trades[trades.pnl_net <= 0].pnl_net
    return {"n_trades": len(trades), "win_rate": len(w) / len(trades), "avg_win": w.mean() if len(w) else 0.0,
            "avg_loss": l.mean() if len(l) else 0.0,
            "profit_factor": w.sum() / abs(l.sum()) if l.sum() < 0 else np.inf,
            "trades_per_day": len(trades) / max(span_days, 1), "avg_hold_h": trades.bars.mean() * freq_min / 60,
            "turnover_x": turnover / avg_equity if avg_equity else np.nan}


def perf_report(res, freq_min: int, initial: float) -> dict:
    eq = res.curve["equity_total"]
    if len(eq) < 3:
        return {}
    eqd = eq.resample("1D").last().dropna()
    rd = eqd.pct_change()
    span = (eq.index[-1] - eq.index[0]).total_seconds() / 86400
    out = {"initial": initial, "final_value": eq.iloc[-1], "total_return": eq.iloc[-1] / initial - 1,
           "fees_paid": res.fees, "fee_drag_pct": res.fees / initial, "gross_return": (eq.iloc[-1] + res.fees) / initial - 1,
           "span_days": span, "avg_exposure": res.curve["exposure"].mean()}
    out.update(ratios(rd, eqd, span))
    out.update(trade_stats(res.trades, span, freq_min, eq.mean(), res.turnover_usd))
    # bar-frequency cross-check
    rb = eq.pct_change().dropna(); ppy = 525600 / freq_min
    out["sharpe_bar"] = rb.mean() / rb.std() * np.sqrt(ppy) if rb.std() > 0 else np.nan
    return out


def monthly_returns(eq: pd.Series) -> pd.Series:
    m = eq.resample("1ME").last()
    first = eq.iloc[0]
    return m.pct_change().fillna(m.iloc[0] / first - 1) if len(m) else m


def rolling_window_report(eq: pd.Series, days: int = 14, step_days: int = 1) -> dict:
    """Distribution of outcomes over every `days`-day window (the live contest is exactly one such window)."""
    eqd = eq.resample("1D").last().dropna()
    if len(eqd) < days + 2:
        return {}
    rows = []
    for s in range(0, len(eqd) - days, step_days):
        w = eqd.iloc[s:s + days + 1]
        r = w.pct_change().dropna()
        ret = w.iloc[-1] / w.iloc[0] - 1
        mdd = _dd_series(w).min()
        sd = r.std(ddof=1); dd_dev = np.sqrt((np.minimum(r, 0) ** 2).mean())
        sh = r.mean() / sd * np.sqrt(ANN) if sd > 0 else np.nan
        so = r.mean() / dd_dev * np.sqrt(ANN) if dd_dev > 0 else (np.nan if r.mean() <= 0 else 10.0)
        ca = (ret * ANN / days) / abs(mdd) if mdd < 0 else (np.nan if ret <= 0 else 10.0)
        rows.append((ret, mdd, sh, so, ca))
    d = pd.DataFrame(rows, columns=["ret", "mdd", "sharpe", "sortino", "calmar"])
    d["composite"] = (SCORE_WEIGHTS["sortino"] * d.sortino.clip(-10, 10) + SCORE_WEIGHTS["sharpe"] * d.sharpe.clip(-10, 10)
                      + SCORE_WEIGHTS["calmar"] * d.calmar.clip(-10, 10))
    return {"w14_n": len(d), "w14_ret_med": d.ret.median(), "w14_ret_p10": d.ret.quantile(0.1), "w14_ret_worst": d.ret.min(),
            "w14_pos_frac": (d.ret > 0).mean(), "w14_mdd_med": d.mdd.median(), "w14_mdd_worst": d.mdd.min(),
            "w14_comp_med": d.composite.median(), "w14_comp_p10": d.composite.quantile(0.1)}


def by_asset(trades: pd.DataFrame) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame()
    return trades.groupby("asset").agg(n=("pnl_net", "size"), pnl=("pnl_net", "sum"),
                                       win=("pnl_net", lambda x: (x > 0).mean()), fees=("fees", "sum")).sort_values("pnl")
