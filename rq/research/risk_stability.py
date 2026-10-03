"""Phase 6b: dd-ladder neighbour stability + per-year split. DEVELOPMENT data only (2023-2025)."""
import pandas as pd
from ..config import load_config
from ..constants import TRAIN_START, TRAIN_END
from .loader import get_data
from .grid import build_grid
from . import runner
from ..backtest.risk import RiskConfig
from ..cli import _pcfg

def main(tf="30m"):
    assert TRAIN_END < pd.Timestamp("2026-01-01", tz="UTC")
    cfg = load_config(); panel, ext = get_data(cfg, tf)
    cfg["portfolio"]["slip_bps"] = {"crypto": 2.0, "equity": 5.0}
    sp = {s.name: s for s in build_grid()}["ma_cross(fast=50,kind=ema,slow=200)"]
    V = {
        "none": RiskConfig(),
        "base 10/.5 20/.25": RiskConfig(dd_ladder=((0.10, 0.5), (0.20, 0.25))),
        "earlier 5/.5 10/.25": RiskConfig(dd_ladder=((0.05, 0.5), (0.10, 0.25))),
        "earlier 8/.5 16/.25": RiskConfig(dd_ladder=((0.08, 0.5), (0.16, 0.25))),
        "later 12/.5 25/.25": RiskConfig(dd_ladder=((0.12, 0.5), (0.25, 0.25))),
        "softer 10/.75 20/.5": RiskConfig(dd_ladder=((0.10, 0.75), (0.20, 0.5))),
        "harder 10/.5 20/.0": RiskConfig(dd_ladder=((0.10, 0.5), (0.20, 0.0))),
    }
    years = [(str(y), pd.Timestamp(f"{y}-01-01", tz="UTC"), pd.Timestamp(f"{y}-12-31 23:59:59", tz="UTC")) for y in (2023, 2024, 2025)]
    rows = []
    for name, rc in V.items():
        pc = _pcfg(cfg, cw=1.0, pf=0.10, mp=(5, 10), fee=0.001, risk=rc)
        _, r = runner.evaluate(panel, sp, ext, pc, TRAIN_START, TRAIN_END, tf)
        row = {"variant": name, "ret_%": r["total_return"] * 100, "sortino": r["sortino"], "calmar": r["calmar"],
               "max_dd_%": r["max_dd"] * 100, "worst_14d_%": r["w14_ret_worst"] * 100, "fees_usd": r["fees_paid"]}
        for lab, s, e in years:
            _, ry = runner.evaluate(panel, sp, ext, pc, s, e, tf)
            row["ret_" + lab] = ry["total_return"] * 100
        rows.append(row); print(name, "done", flush=True)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).round(2).to_string(index=False))

if __name__ == "__main__":
    main()
