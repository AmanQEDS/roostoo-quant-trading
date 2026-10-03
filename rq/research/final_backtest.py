"""FINAL LOCKED SPEC on 2026 validation. Two runs only: bare vs frozen ladder, identical settings. Reported, never tuned on."""
import pandas as pd
from ..config import load_config
from ..constants import VAL_START
from .loader import get_data
from .grid import build_grid
from . import runner
from ..backtest.risk import RiskConfig
from ..backtest.audit import export_backtest_audit
from ..cli import _pcfg

NAME = "ma_cross(fast=50,kind=ema,slow=200)"

def main(tf="30m"):
    cfg = load_config(); panel, ext = get_data(cfg, tf)
    cfg["portfolio"]["slip_bps"] = {"crypto": 2.0, "equity": 5.0}
    sp = {s.name: s for s in build_grid()}[NAME]
    end = panel.index[-1]
    variants = {
        "bare": RiskConfig(),
        "FROZEN ladder 10/.5 20/.25": RiskConfig(dd_ladder=((0.10, 0.5), (0.20, 0.25))),
    }
    rows = []
    for label, rc in variants.items():
        pc = _pcfg(cfg, cw=1.0, pf=0.10, mp=(5, 10), fee=0.001, risk=rc)
        res, rep = runner.evaluate(panel, sp, ext, pc, VAL_START, end, tf)
        tag = "final_" + ("bare" if label == "bare" else "ladder") + "_2026"
        s, paths = export_backtest_audit(res, pc.capital, rep["n_trades"], tag, reported_max_drawdown=rep["max_dd"])
        rows.append({"variant": label, "ret_%": s["total_return_pct"], "realized_%": s["realized_return_pct"],
                     "unrealized_%": s["unrealized_return_pct"], "sharpe": rep["sharpe"], "sortino": rep["sortino"],
                     "calmar": rep["calmar"], "max_dd_daily_%": s["max_drawdown_pct"],
                     "max_dd_bar_%": s["bar_level_max_drawdown_pct"], "trades": s["completed_trades"],
                     "open_pos": s["open_positions"], "fees_usd": s["total_fees"], "win_%": s["closed_trade_win_rate_pct"],
                     "profit_factor": s["profit_factor"]})
        print(label, "done", flush=True)
    pd.set_option("display.width", 250)
    print(f"\nValidation window: {VAL_START.date()} .. {end.date()}")
    print(pd.DataFrame(rows).round(2).T.to_string())

if __name__ == "__main__":
    main()
