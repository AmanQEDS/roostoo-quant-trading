"""Research portfolio-level profit locks without changing live configuration.

Run from the repository root:
    python -m rq.research.portfolio_profit_lock

This compares the original EMA/Donchian entry signals with portfolio-level
peak-profit locks. It writes research CSVs only and never places orders.
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


def lock_grid() -> list[ExitConfig]:
    """Baseline plus nine portfolio-lock hypotheses."""
    out = [ExitConfig(variant="X0")]
    out.extend(
        ExitConfig(
            variant="X0",
            portfolio_lock_enabled=True,
            portfolio_lock_activation=activation,
            portfolio_lock_giveback=giveback,
            portfolio_lock_cooldown_bars=6,
        )
        for activation in (250.0, 500.0, 750.0)
        for giveback in (0.25, 0.35, 0.45)
    )
    return out


def label(ec: ExitConfig) -> str:
    if not ec.portfolio_lock_enabled:
        return "baseline_X0"
    return (
        f"lock_activation={ec.portfolio_lock_activation:g}"
        f"_giveback={ec.portfolio_lock_giveback:.2f}"
        f"_cooldown={ec.portfolio_lock_cooldown_bars}"
    )


def evaluate_one(panel, ext, spec, pcfg, start, end, config, split):
    res, rep = runner.evaluate(
        panel, spec, ext, pcfg, start, end, "30m", exit_config=config
    )
    curve = res.curve
    lock_exits = (
        res.trades["reason"].eq("portfolio_profit_lock")
        if not res.trades.empty and "reason" in res.trades.columns
        else pd.Series(dtype=bool)
    )
    lock_exit_count = int(lock_exits.sum())
    lock_exit_net_pnl = (
        float(res.trades.loc[lock_exits, "pnl_net"].sum()) if lock_exit_count else 0.0
    )
    row = {
        "split": split,
        "config": label(config),
        "lock_enabled": config.portfolio_lock_enabled,
        "activation_usd": (
            config.portfolio_lock_activation if config.portfolio_lock_enabled else None
        ),
        "giveback_fraction": (
            config.portfolio_lock_giveback if config.portfolio_lock_enabled else None
        ),
        "cooldown_bars": (
            config.portfolio_lock_cooldown_bars if config.portfolio_lock_enabled else 0
        ),
        "start": str(pd.Timestamp(start).date()),
        "end": str(pd.Timestamp(end).date()),
        "total_return": rep.get("total_return"),
        "sharpe": rep.get("sharpe"),
        "sortino": rep.get("sortino"),
        "calmar": rep.get("calmar"),
        "max_dd_daily": rep.get("max_dd"),
        "max_dd_bar": float(curve["drawdown"].min()) if len(curve) else float("nan"),
        "trades": rep.get("n_trades"),
        "portfolio_lock_closed_positions": lock_exit_count,
        "portfolio_lock_exit_net_pnl": lock_exit_net_pnl,
        "fees_paid": rep.get("fees_paid", res.fees),
        "turnover_usd": res.turnover_usd,
        "turnover_to_starting_capital": res.turnover_usd / pcfg.capital,
        "composite": rep.get("composite"),
    }
    return row


def main():
    cfg = load_config()
    panel, ext = get_data(cfg, "30m")
    grid = build_grid()
    spec = next(
        s for s in grid
        if s.builder == "ema_donchian"
        and s.p == {"fast": 50, "slow": 200, "n": 24}
    )
    start = VAL_START
    end = min(panel.index[-1], pd.Timestamp("2026-10-02 23:59:59", tz="UTC"))
    if end <= start:
        raise ValueError(f"validation data ends before the research period: {end}")

    base_pcfg = _pcfg(cfg)
    configs = lock_grid()
    Path("results").mkdir(exist_ok=True)

    # Validation: compare every lock hypothesis against the unchanged baseline.
    validation_rows = [
        evaluate_one(panel, ext, spec, base_pcfg, start, end, ec, "validation")
        for ec in configs
    ]
    validation = pd.DataFrame(validation_rows).sort_values(
        "composite", ascending=False, na_position="last"
    )
    validation.to_csv("results/portfolio_profit_lock_validation.csv", index=False)
    print("\nVALIDATION: portfolio lock vs baseline")
    print(validation.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # Walk-forward: select on training data only, then evaluate only the selected
    # configuration on the following year. This avoids choosing on test results.
    folds = [
        (
            pd.Timestamp("2023-01-01", tz="UTC"),
            pd.Timestamp("2023-12-31 23:59:59", tz="UTC"),
            pd.Timestamp("2024-01-01", tz="UTC"),
            pd.Timestamp("2024-12-31 23:59:59", tz="UTC"),
        ),
        (
            pd.Timestamp("2023-01-01", tz="UTC"),
            pd.Timestamp("2024-12-31 23:59:59", tz="UTC"),
            pd.Timestamp("2025-01-01", tz="UTC"),
            pd.Timestamp("2025-12-31 23:59:59", tz="UTC"),
        ),
    ]
    wf_rows = []
    for train_start, train_end, test_start, test_end in folds:
        train_rows = [
            evaluate_one(
                panel, ext, spec, base_pcfg, train_start, train_end, ec, "train"
            )
            for ec in configs
        ]
        train_df = pd.DataFrame(train_rows)
        train_df["_score"] = pd.to_numeric(
            train_df["composite"], errors="coerce"
        ).fillna(pd.to_numeric(train_df["total_return"], errors="coerce"))
        selected_label = train_df.sort_values("_score", ascending=False).iloc[0]["config"]
        selected = next(ec for ec in configs if label(ec) == selected_label)
        test_row = evaluate_one(
            panel, ext, spec, base_pcfg, test_start, test_end, selected, "walkforward_test"
        )
        test_row["fold"] = f"{train_start.year}_to_{train_end.year}_test_{test_start.year}"
        test_row["selected_on_train"] = selected_label
        wf_rows.append(test_row)
        print(
            f"\n[walk-forward] {test_row['fold']}: selected={selected_label}; "
            f"test_return={test_row['total_return']:+.2%}; "
            f"Sharpe={test_row['sharpe']:.2f}; "
            f"max_dd={test_row['max_dd_daily']:.2%}"
        )
    wf = pd.DataFrame(wf_rows)
    wf.to_csv("results/portfolio_profit_lock_walkforward.csv", index=False)

    # Cost sensitivity: baseline and the two highest-ranked lock configurations
    # are re-evaluated at higher fees/slippage. This is diagnostic, not selection.
    lock_rows = validation[validation["lock_enabled"]].head(2)
    selected_configs = [configs[0]]
    for _, row in lock_rows.iterrows():
        match = next(ec for ec in configs if label(ec) == row["config"])
        if label(match) not in {label(x) for x in selected_configs}:
            selected_configs.append(match)

    cost_rows = []
    for ec in selected_configs:
        for fee, slip in ((0.001, 2.0), (0.001, 5.0), (0.0015, 2.0), (0.0015, 5.0), (0.002, 5.0)):
            cost_cfg = copy.deepcopy(cfg)
            cost_cfg["portfolio"]["slip_bps"] = {"crypto": slip, "equity": 5.0}
            pcfg = _pcfg(cost_cfg, fee=fee)
            row = evaluate_one(panel, ext, spec, pcfg, start, end, ec, "cost_sensitivity")
            row["fee"] = fee
            row["crypto_slip_bps"] = slip
            cost_rows.append(row)
            print(
                f"[cost] {label(ec)} fee={fee:.3%} slip={slip:g}bp "
                f"return={row['total_return']:+.2%}"
            )
    costs = pd.DataFrame(cost_rows)
    costs.to_csv("results/portfolio_profit_lock_cost_sensitivity.csv", index=False)
    print("\nCOST SENSITIVITY")
    print(
        costs[[
            "config", "fee", "crypto_slip_bps", "total_return", "sharpe",
            "max_dd_daily", "trades", "portfolio_lock_closed_positions",
            "portfolio_lock_exit_net_pnl", "fees_paid", "turnover_usd",
            "turnover_to_starting_capital"
        ]].to_string(index=False)
    )


if __name__ == "__main__":
    main()
