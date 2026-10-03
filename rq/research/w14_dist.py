"""Distribution of 14-day returns for ma_cross + drawdown ladder. DEVELOPMENT data only."""
import numpy as np, pandas as pd
from ..config import load_config
from ..constants import TRAIN_START, TRAIN_END
from .loader import get_data
from .grid import build_grid
from . import runner
from ..backtest.risk import RiskConfig
from ..cli import _pcfg

def main(tf="30m"):
    cfg = load_config(); panel, ext = get_data(cfg, tf)
    cfg["portfolio"]["slip_bps"] = {"crypto": 2.0, "equity": 5.0}
    sp = {s.name: s for s in build_grid()}["ma_cross(fast=50,kind=ema,slow=200)"]
    pc = _pcfg(cfg, cw=1.0, pf=0.10, mp=(5, 10), fee=0.001, risk=RiskConfig(dd_ladder=((0.10, 0.5), (0.20, 0.25))))
    res, r = runner.evaluate(panel, sp, ext, pc, TRAIN_START, TRAIN_END, tf)
    eq = res.curve.equity_total.resample("1D").last().dropna()
    w = (eq.shift(-14) / eq - 1).dropna() * 100
    print("windows:", len(w), "| total return %.1f%% | maxDD %.1f%% | avg exposure %.0f%%" % (r["total_return"] * 100, r["max_dd"] * 100, r["avg_exposure"] * 100))
    print("14-day return pct: mean %.2f | median %.2f" % (w.mean(), w.median()))
    print(w.quantile([0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]).round(2).to_string())
    print("share of windows > 0: %.0f%% | > +5%%: %.0f%% | > +10%%: %.0f%% | < -5%%: %.0f%% | < -10%%: %.0f%%" % (
        (w > 0).mean() * 100, (w > 5).mean() * 100, (w > 10).mean() * 100, (w < -5).mean() * 100, (w < -10).mean() * 100))

if __name__ == "__main__":
    main()
