"""Sizing comparison, ma_cross 50/200, DEVELOPMENT data only (2023-2025). Ladder off. For choosing risk appetite, not alpha."""
import pandas as pd
from ..config import load_config
from ..constants import TRAIN_START, TRAIN_END
from .loader import get_data
from .grid import build_grid
from . import runner
from ..cli import _pcfg

def main(tf="30m"):
    assert TRAIN_END < pd.Timestamp("2026-01-01", tz="UTC")
    cfg = load_config(); panel, ext = get_data(cfg, tf)
    cfg["portfolio"]["slip_bps"] = {"crypto": 2.0, "equity": 5.0}
    sp = {s.name: s for s in build_grid()}["ma_cross(fast=50,kind=ema,slow=200)"]
    rows = []
    for pf, mp in [(0.10, 5), (0.15, 5), (0.20, 5), (0.25, 5), (0.30, 5)]:
        _, r = runner.evaluate(panel, sp, ext, _pcfg(cfg, cw=1.0, pf=pf, mp=(mp, 10), fee=0.001), TRAIN_START, TRAIN_END, tf)
        rows.append({"pos_frac": pf, "max_pos": mp, "max_exposure_%": (1 - (1 - pf) ** mp) * 100,
                     "ret_%": r["total_return"] * 100, "sortino": r["sortino"], "calmar": r["calmar"],
                     "max_dd_%": r["max_dd"] * 100, "w14_med_%": r["w14_ret_med"] * 100,
                     "w14_worst_%": r["w14_ret_worst"] * 100, "w14_pos_frac": r.get("w14_pos_frac"),
                     "trades": r["n_trades"], "fees_usd": r["fees_paid"]})
        print("pf", pf, "done", flush=True)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).round(2).to_string(index=False))

if __name__ == "__main__":
    main()
