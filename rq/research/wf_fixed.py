"""Walk-forward on DEVELOPMENT data only (2023-2025)."""
import pandas as pd
from ..config import load_config
from ..constants import TRAIN_END
from .loader import get_data
from .grid import build_grid
from . import runner, selection
from ..cli import _pcfg

STRATS = ["ma_cross(fast=50,kind=ema,slow=200)", "fng_momentum(n_days=7,thr=5)"]

def main(tf="30m"):
    cfg = load_config(); panel, ext = get_data(cfg, tf)
    cfg["portfolio"]["slip_bps"] = {"crypto": 2.0, "equity": 5.0}
    pc = _pcfg(cfg, cw=1.0, pf=0.10, mp=(5, 10), fee=0.001)
    G = {s.name: s for s in build_grid()}
    periods = [(f"{y}H{h}", pd.Timestamp(f"{y}-{a}", tz="UTC"), pd.Timestamp(f"{y}-{b}", tz="UTC"))
               for y in (2023, 2024, 2025) for h, a, b in ((1, "01-01", "06-30 23:59:59"), (2, "07-01", "12-31 23:59:59"))]
    assert periods[-1][2] <= TRAIN_END
    pd.set_option("display.width", 220)
    for name in STRATS:
        rows = []
        for label, s, e in periods:
            _, r = runner.evaluate(panel, G[name], ext, pc, s, e, tf)
            rows.append({"period": label, "ret_%": r["total_return"] * 100, "sharpe": r["sharpe"], "sortino": r["sortino"],
                         "max_dd_%": r["max_dd"] * 100, "trades": r["n_trades"], "win_rate_%": r["win_rate"] * 100})
        d = pd.DataFrame(rows)
        print(f"\n=== {name} : fixed spec by half-year ===")
        print(d.round(2).to_string(index=False))
        print(f"positive periods: {(d['ret_%'] > 0).sum()} of {len(d)} | worst {d['ret_%'].min():.1f}% | best {d['ret_%'].max():.1f}%")
    for b in ("ma_cross", "fng_momentum"):
        specs = [s for s in build_grid() if s.builder == b]
        print(f"\n=== existing walk-forward (pick best on train, test next year): {b} ===")
        print(selection.walk_forward(panel, ext, specs, pc, tf).round(3).to_string(index=False))

if __name__ == "__main__":
    main()
