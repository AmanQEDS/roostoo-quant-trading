"""Regime analysis on DEVELOPMENT data only (2023-2025). Descriptive: definitions are fixed, not tuned."""
import numpy as np, pandas as pd
from ..config import load_config
from ..constants import TRAIN_START, TRAIN_END
from .loader import get_data
from .grid import build_grid
from . import runner
from ..cli import _pcfg

STRATS = ["ma_cross(fast=50,kind=ema,slow=200)", "fng_momentum(n_days=7,thr=5)"]
BPD = 48            # 30m bars per day
BPY = 365 * BPD

def labels(panel):
    btc = panel.close["BTC"].loc[:TRAIN_END]
    r30 = btc / btc.shift(30 * BPD) - 1
    rv = np.log(btc / btc.shift(1)).rolling(14 * BPD).std()
    med = rv.expanding(min_periods=14 * BPD).median()
    trend = pd.Series(np.select([r30 > 0.10, r30 < -0.10], ["bull", "bear"], "sideways"), index=btc.index).where(r30.notna())
    vol = pd.Series(np.where(rv > med, "high_vol", "low_vol"), index=btc.index).where(rv.notna() & med.notna())
    return trend.shift(1), vol.shift(1), btc          # shift(1): label known BEFORE the bar's return

def stats(ret, trades, lab, name, bret):
    n = len(ret)
    if n < 200:
        return None
    eq = (1 + ret).cumprod()
    sd = ret.std(); dd = np.sqrt((np.minimum(ret, 0) ** 2).mean())
    t = trades[lab.reindex(pd.DatetimeIndex(trades.entry_time)).values == name] if len(trades) else trades
    w = t[t.pnl_net > 0].pnl_net.sum(); l = -t[t.pnl_net <= 0].pnl_net.sum()
    return {"days": n / BPD, "ret_per_30d_%": ret.mean() * BPD * 30 * 100, "total_ret_%": (eq.iloc[-1] - 1) * 100,
            "sharpe": ret.mean() / sd * np.sqrt(BPY) if sd > 0 else np.nan,
            "sortino": ret.mean() / dd * np.sqrt(BPY) if dd > 0 else np.nan,
            "max_dd_%": (eq / eq.cummax() - 1).min() * 100, "trades": len(t),
            "win_rate_%": (t.pnl_net > 0).mean() * 100 if len(t) else np.nan,
            "profit_factor": w / l if l > 0 else np.nan,
            "btc_ret_per_30d_%": bret.mean() * BPD * 30 * 100}

def main(tf="30m"):
    cfg = load_config(); panel, ext = get_data(cfg, tf)
    trend, vol, btc = labels(panel)
    G = {s.name: s for s in build_grid()}
    cfg["portfolio"]["slip_bps"] = {"crypto": 2.0, "equity": 5.0}
    pc = _pcfg(cfg, cw=1.0, pf=0.10, mp=(5, 10), fee=0.001)
    out = []
    for sname in STRATS:
        res, rep = runner.evaluate(panel, G[sname], ext, pc, TRAIN_START, TRAIN_END, tf)
        ret = res.curve.equity_total.pct_change().dropna()
        bret = btc.pct_change().reindex(ret.index)
        for dim, lab in (("trend", trend), ("vol", vol)):
            L = lab.reindex(ret.index)
            for name in sorted(L.dropna().unique()):
                m = (L == name).values
                s = stats(ret[m], res.trades, lab, name, bret[m])
                if s:
                    out.append({"strategy": sname[:10], "dim": dim, "regime": name, **s})
    df = pd.DataFrame(out)
    df.to_csv("results/regime_analysis.csv", index=False)
    pd.set_option("display.width", 250)
    print(df.round(2).to_string(index=False))

if __name__ == "__main__":
    main()
