"""Phase 4+5 on DEVELOPMENT data only (2023-2025). Sleeves = daily-rebalanced mix of two independent equity curves."""
import pandas as pd
from ..config import load_config
from ..constants import TRAIN_START, TRAIN_END
from .loader import get_data
from .grid import build_grid
from . import runner
from .combine import combine
from ..cli import _pcfg

def main(tf="30m"):
    cfg = load_config(); panel, ext = get_data(cfg, tf)
    cfg["portfolio"]["slip_bps"] = {"crypto": 2.0, "equity": 5.0}
    pc = _pcfg(cfg, cw=1.0, pf=0.10, mp=(5, 10), fee=0.001)
    G = {s.name: s for s in build_grid()}
    names = {"ma": "ma_cross(fast=50,kind=ema,slow=200)", "fng": "fng_momentum(n_days=7,thr=5)"}
    curves, fees = {}, {}
    for k, n in names.items():
        res, _ = runner.evaluate(panel, G[n], ext, pc, TRAIN_START, TRAIN_END, tf)
        curves[k] = res.curve.equity_total; fees[k] = res.fees
    d = pd.DataFrame({k: v.resample("1D").last().pct_change() for k, v in curves.items()}).dropna()
    dd = {k: (1 + d[k]).cumprod() / (1 + d[k]).cumprod().cummax() - 1 for k in d}
    print("daily-return correlation: %.2f" % d.ma.corr(d.fng))
    print("downside correlation (days ma<0): %.2f | (days fng<0): %.2f" % (d.fng[d.ma < 0].corr(d.ma[d.ma < 0]), d.ma[d.fng < 0].corr(d.fng[d.fng < 0])))
    print("days in >10%% drawdown: ma %.0f%% | fng %.0f%% | both %.0f%%" % (
        (dd["ma"] < -0.1).mean() * 100, (dd["fng"] < -0.1).mean() * 100, ((dd["ma"] < -0.1) & (dd["fng"] < -0.1)).mean() * 100))
    rows = []
    for w in (1.0, 0.75, 0.5, 0.25, 0.0):
        eq, corr, rep, _ = combine(curves, {"ma": w, "fng": 1 - w})
        h = eq.groupby([eq.index.year, eq.index.month > 6]).agg(["first", "last"])
        hr = (h["last"] / h["first"] - 1) * 100
        rows.append({"ma_w": w, "ret_%": rep["total_return"] * 100, "vol_%": rep["vol"] * 100, "sharpe": rep["sharpe"], "sortino": rep["sortino"],
                     "calmar": rep["calmar"], "max_dd_%": rep["max_dd"] * 100, "worst_half_%": hr.min(), "pos_halves": int((hr > 0).sum()),
                     "fees_usd": w * fees["ma"] + (1 - w) * fees["fng"]})
    pd.set_option("display.width", 220)
    print(pd.DataFrame(rows).round(2).to_string(index=False))

if __name__ == "__main__":
    main()
