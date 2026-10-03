"""Correlation-control sensitivity on DEVELOPMENT data only (2023-2025)."""
import pandas as pd

from ..config import load_config
from ..constants import TRAIN_START, TRAIN_END
from .loader import get_data
from .grid import build_grid
from . import runner
from ..backtest.risk import RiskConfig
from ..cli import _pcfg


def main(tf="30m"):
    cfg = load_config()
    panel, ext = get_data(cfg, tf)

    # Match the current production/backtest cost assumptions.
    cfg["portfolio"]["slip_bps"] = {
        "crypto": 2.0,
        "equity": 5.0,
    }

    specs = {
        s.name: s for s in build_grid()
    }

    strategy = specs["ma_cross(fast=50,kind=ema,slow=200)"]

    variants = {
        "baseline (corr off)": RiskConfig(
            corr_cap=None,
            corr_win=96,
        ),
        "corr cap 0.80": RiskConfig(
            corr_cap=0.80,
            corr_win=96,
        ),
        "corr cap 0.70": RiskConfig(
            corr_cap=0.70,
            corr_win=96,
        ),
        "corr cap 0.60": RiskConfig(
            corr_cap=0.60,
            corr_win=96,
        ),
    }

    rows = []

    for name, rc in variants.items():
        pc = _pcfg(
            cfg,
            cw=1.0,
            pf=0.10,
            mp=(5, 10),
            fee=0.001,
            risk=rc,
        )

        _, rep = runner.evaluate(
            panel,
            strategy,
            ext,
            pc,
            TRAIN_START,
            TRAIN_END,
            tf,
        )

        corr_skips = rep.get("skipped", {}).get("corr", None)

        row = {
            "variant": name,
            "corr_cap": rc.corr_cap,
            "corr_win_bars": rc.corr_win,
            "ret_%": rep["total_return"] * 100,
            "sharpe": rep["sharpe"],
            "sortino": rep["sortino"],
            "calmar": rep["calmar"],
            "max_dd_%": rep["max_dd"] * 100,
            "worst_14d_%": rep["w14_ret_worst"] * 100,
            "trades": rep["n_trades"],
            "fees_usd": rep["fees_paid"],
            "corr_skips": corr_skips,
        }

        rows.append(row)
        print(
            f"{name:24s} "
            f"ret={row['ret_%']:+.2f}% "
            f"Sharpe={row['sharpe']:.2f} "
            f"Sortino={row['sortino']:.2f} "
            f"Calmar={row['calmar']:.2f} "
            f"maxDD={row['max_dd_%']:.2f}% "
            f"trades={row['trades']} "
            f"corr_skips={row['corr_skips']}",
            flush=True,
        )

    df = pd.DataFrame(rows)

    print("\n=== CORRELATION CONTROL — DEVELOPMENT 2023-2025 ===")
    print(
        df.round(3).to_string(index=False)
    )

    df.to_csv(
        "results/correlation_sensitivity.csv",
        index=False,
    )

    print(
        "\nSaved: results/correlation_sensitivity.csv"
    )


if __name__ == "__main__":
    main()
