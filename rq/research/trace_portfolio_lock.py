"""Trace portfolio-lock state under different slippage assumptions.

Research only; this script never places orders and does not modify live config.
Run from the repository root:
    python -m rq.research.trace_portfolio_lock
"""
from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd

from ..backtest.engine import ExitConfig
from ..cli import _pcfg
from ..config import load_config
from ..constants import VAL_START
from .grid import build_grid
from .loader import get_data
from . import runner


def main() -> None:
    cfg = load_config()
    panel, ext = get_data(cfg, "30m")
    spec = next(
        s for s in build_grid()
        if s.builder == "ema_donchian"
        and s.p == {"fast": 50, "slow": 200, "n": 24}
    )
    start = VAL_START
    end = min(panel.index[-1], pd.Timestamp("2026-10-02 23:59:59", tz="UTC"))
    if end <= start:
        raise ValueError(f"validation data ends before the research period: {end}")

    lock = ExitConfig(
        variant="X0",
        portfolio_lock_enabled=True,
        portfolio_lock_activation=500.0,
        portfolio_lock_giveback=0.45,
        portfolio_lock_cooldown_bars=6,
    )
    out_dir = Path("results")
    out_dir.mkdir(exist_ok=True)

    for slip in (2.0, 5.0):
        cost_cfg = copy.deepcopy(cfg)
        cost_cfg["portfolio"]["slip_bps"] = {
            "crypto": slip,
            "equity": 5.0,
        }
        pcfg = _pcfg(cost_cfg, fee=0.0015)
        res, rep = runner.evaluate(
            panel, spec, ext, pcfg, start, end, "30m", exit_config=lock
        )

        events = pd.DataFrame(res.lock_events)
        path = out_dir / f"portfolio_lock_trace_slip_{int(slip)}bps.csv"
        events.to_csv(path, index=False)

        print(f"\\n{'=' * 20} SLIPPAGE {slip:g} BPS {'=' * 20}")
        print(
            f"return={rep['total_return']:+.2%}; Sharpe={rep['sharpe']:.3f}; "
            f"maxDD={rep['max_dd']:.2%}; trades={rep['n_trades']}; "
            f"lock events={len(events)}; trace={path}"
        )
        if events.empty:
            print("No portfolio-lock events recorded.")
            continue

        lifecycle = events[events["event"] != "armed_observation"]
        cols = [
            "event", "bar_index", "timestamp", "equity",
            "net_liquidation_equity", "lock_cycle_base", "lock_cycle_peak",
            "peak_profit", "lock_floor", "open_positions",
        ]
        print("\nLock lifecycle:")
        print(lifecycle[cols].to_string(index=False))

        first_trigger = events.index[events["event"].eq("triggered")]
        if len(first_trigger):
            trigger_idx = first_trigger[0]
            trigger_bar = int(events.loc[trigger_idx, "bar_index"])
            previous_activation = events[
                (events["event"] == "activated")
                & (events["bar_index"] <= trigger_bar)
            ]
            activation_bar = (
                int(previous_activation.iloc[-1]["bar_index"])
                if not previous_activation.empty else trigger_bar
            )
            window = events[
                (events["bar_index"] >= activation_bar)
                & (events["bar_index"] <= trigger_bar)
            ]
            print("\nFirst activation-to-trigger trace:")
            print(window[cols].to_string(index=False))


if __name__ == "__main__":
    main()
