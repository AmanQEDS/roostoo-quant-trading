"""Cost sensitivity on DEVELOPMENT data only (2023-2025). Never touches 2026."""
import itertools
import pandas as pd
from ..config import load_config
from ..constants import TRAIN_START, TRAIN_END
from .loader import get_data
from .grid import build_grid
from . import runner
from ..cli import _pcfg

STRATS = ["ma_cross(fast=50,kind=ema,slow=200)", "fng_momentum(n_days=7,thr=5)"]
FEES = [0.0005, 0.001, 0.0015]
SLIPS = [0.0, 2.0, 5.0, 10.0]

def main(tf="30m"):
    assert TRAIN_END < pd.Timestamp("2026-01-01", tz="UTC")
    cfg = load_config()
    panel, ext = get_data(cfg, tf)
    G = {s.name: s for s in build_grid()}
    rows = []
    for name, fee, slip in itertools.product(STRATS, FEES, SLIPS):
        cfg["portfolio"]["slip_bps"] = {"crypto": slip, "equity": 5.0}
        pc = _pcfg(cfg, cw=1.0, pf=0.10, mp=(5, 10), fee=fee)
        _, r = runner.evaluate(panel, G[name], ext, pc, TRAIN_START, TRAIN_END, tf)
        rows.append({"strategy": name, "fee_pct": fee * 100, "slip_bp": slip,
                     "ret": r["total_return"], "gross": r["gross_return"], "sharpe": r["sharpe"],
                     "sortino": r["sortino"], "max_dd": r["max_dd"], "trades": r["n_trades"], "fees_usd": r["fees_paid"]})
        print(f"{name[:12]:12s} fee {fee*100:.2f}% slip {slip:>4.1f}bp  ret {r['total_return']:+.1%}  sortino {r['sortino']:.2f}  maxDD {r['max_dd']:.1%}  trades {r['n_trades']}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("results/cost_sensitivity.csv", index=False)
    for name in STRATS:
        print("\n" + name + "  (return, rows = fee %, cols = slippage bp)")
        print(df[df.strategy == name].pivot(index="fee_pct", columns="slip_bp", values="ret").round(3).to_string())

if __name__ == "__main__":
    main()
