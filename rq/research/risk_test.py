"""Phase 6: do the engine's risk controls help? DEVELOPMENT data only (2023-2025)."""
import pandas as pd
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
    variants = {
        "none (live today)": RiskConfig(),
        "stop-loss 5%": RiskConfig(stop_loss=0.05),
        "dd ladder 10%->x0.5, 20%->x0.25": RiskConfig(dd_ladder=((0.10, 0.5), (0.20, 0.25))),
        "dd halt 25% (pause 3 days)": RiskConfig(dd_halt=0.25, halt_bars=144),
        "vol scaling": RiskConfig(vol_scale=True),
        "ladder + halt 30%": RiskConfig(dd_ladder=((0.10, 0.5), (0.20, 0.25)), dd_halt=0.30, halt_bars=144),
    }
    rows = []
    for name, rc in variants.items():
        _, r = runner.evaluate(panel, sp, ext, _pcfg(cfg, cw=1.0, pf=0.10, mp=(5, 10), fee=0.001, risk=rc), TRAIN_START, TRAIN_END, tf)
        rows.append({"variant": name, "ret_%": r["total_return"] * 100, "sortino": r["sortino"], "calmar": r["calmar"],
                     "max_dd_%": r["max_dd"] * 100, "worst_14d_%": r["w14_ret_worst"] * 100, "trades": r["n_trades"], "fees_usd": r["fees_paid"]})
        print(rows[-1]["variant"], "done", flush=True)
    pd.set_option("display.width", 220)
    print(pd.DataFrame(rows).round(2).to_string(index=False))

if __name__ == "__main__":
    main()
