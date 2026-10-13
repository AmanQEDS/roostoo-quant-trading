"""Profit-giveback exit research; isolated from live execution/configuration.

Run: python -m rq.research.profit_giveback
Uses the same production signal, portfolio sizing, fee defaults, and validation window
as the CLI validation workflow. It never writes config/live.yaml or places orders.
"""
from __future__ import annotations

import itertools
from pathlib import Path

import pandas as pd

from ..backtest.engine import ExitConfig
from ..cli import _pcfg
from ..config import load_config
from ..constants import VAL_START
from .grid import build_grid
from .loader import get_data
from . import runner


def exit_grid() -> list[ExitConfig]:
    out = [ExitConfig(variant="X0")]
    out += [ExitConfig(variant="X1", chandelier_k=k) for k in (2.0, 3.0, 4.0)]
    out += [ExitConfig(variant="X2", breakeven_atr=a) for a in (1.0, 1.5, 2.0)]
    out += [ExitConfig(variant="X3", trailing_pct=g) for g in (0.03, 0.05, 0.08)]
    out += [
        ExitConfig(variant="X4", giveback_trigger_atr=g, giveback_fraction=f)
        for g, f in itertools.product((1.0, 2.0), (0.4, 0.5, 0.6))
    ]
    out += [ExitConfig(variant="X5", donchian_n=n) for n in (24, 48)]
    out += [
        ExitConfig(variant="X6", partial_r=r, chandelier_k=k)
        for r, k in itertools.product((1.5, 2.0), (2.0, 3.0, 4.0))
    ]
    out += [
        ExitConfig(variant="X7", breakeven_atr=a, chandelier_k=k)
        for a, k in itertools.product((1.0, 1.5, 2.0), (2.0, 3.0, 4.0))
    ]
    return out


def label(x: ExitConfig) -> str:
    return (
        f"{x.variant}|atr={x.atr_n}|k={x.chandelier_k:g}|be={x.breakeven_atr:g}"
        f"|trail={x.trailing_pct:g}|G={x.giveback_trigger_atr:g}"
        f"|f={x.giveback_fraction:g}|don={x.donchian_n}|R={x.partial_r:g}"
    )


def row_for(res, rep, config, fee, slip, start, end, split):
    bar_dd = float(res.curve["drawdown"].min()) if len(res.curve) else float("nan")
    return {
        "split": split, "variant": label(config), "exit_variant": config.variant,
        "fee": fee, "crypto_slip_bps": slip,
        "start": str(pd.Timestamp(start).date()), "end": str(pd.Timestamp(end).date()),
        "total_return": rep.get("total_return"), "sharpe": rep.get("sharpe"),
        "sortino": rep.get("sortino"), "calmar": rep.get("calmar"),
        "max_dd_daily": rep.get("max_dd"), "max_dd_bar": bar_dd,
        "trades": rep.get("n_trades"), "fees_paid": rep.get("fees_paid"),
        "win_rate": rep.get("win_rate"), "profit_factor": rep.get("profit_factor"),
        "avg_mfe": rep.get("avg_mfe"), "avg_mae": rep.get("avg_mae"),
        "avg_giveback": rep.get("avg_giveback"),
        "pct_1atr_profit_then_loser": rep.get("pct_1atr_profit_then_loser"),
        "composite": rep.get("composite"),
    }


def main():
    cfg = load_config()
    panel, ext = get_data(cfg, "30m")
    by_name = {s.name: s for s in build_grid()}
    spec = by_name["ema_donchian(fast=50,n=24,slow=200)"] if "ema_donchian(fast=50,n=24,slow=200)" in by_name else next(
        s for s in build_grid() if s.builder == "ema_donchian" and s.p == {"fast": 50, "slow": 200, "n": 24}
    )
    start = VAL_START
    end = min(panel.index[-1], pd.Timestamp("2026-10-02 23:59:59", tz="UTC"))
    if end <= start:
        raise ValueError(f"validation data ends before the research period: {end}")

    base_pcfg = _pcfg(cfg)
    configs = exit_grid()
    Path("results").mkdir(exist_ok=True)

    # Primary grid: exact validation dates/costs used by the CLI validation path.
    primary = []
    for ec in configs:
        res, rep = runner.evaluate(panel, spec, ext, base_pcfg, start, end, "30m", exit_config=ec)
        primary.append(row_for(res, rep, ec, base_pcfg.fee, base_pcfg.slip_bps["crypto"], start, end, "validation"))
        print(f"[validation] {label(ec)} ret={rep.get('total_return', float('nan')):+.2%} "
              f"sharpe={rep.get('sharpe', float('nan')):.2f} "
              f"mdd={rep.get('max_dd', float('nan')):.2%} "
              f"giveback={rep.get('avg_giveback', float('nan')):.2f}", flush=True)
    primary_df = pd.DataFrame(primary).sort_values("composite", ascending=False)
    primary_df.to_csv("results/profit_giveback_validation.csv", index=False)
    print("\nVALIDATION GRID (ranked by composite; inspect giveback and drawdown too)")
    print(primary_df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # Walk-forward: fit/select only on past years, report the next untouched year.
    folds = [
        (pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2023-12-31 23:59:59", tz="UTC"),
         pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-12-31 23:59:59", tz="UTC")),
        (pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2024-12-31 23:59:59", tz="UTC"),
         pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-12-31 23:59:59", tz="UTC")),
    ]
    wf_rows = []
    for train_start, train_end, test_start, test_end in folds:
        candidates = []
        for ec in configs:
            tr, tr_rep = runner.evaluate(panel, spec, ext, base_pcfg, train_start, train_end, "30m", exit_config=ec)
            te, te_rep = runner.evaluate(panel, spec, ext, base_pcfg, test_start, test_end, "30m", exit_config=ec)
            row = row_for(te, te_rep, ec, base_pcfg.fee, base_pcfg.slip_bps["crypto"], test_start, test_end, "walkforward_test")
            row["train_composite"] = tr_rep.get("composite")
            row["train_return"] = tr_rep.get("total_return")
            row["train_avg_giveback"] = tr_rep.get("avg_giveback")
            row["train_max_dd"] = tr_rep.get("max_dd")
            candidates.append(row)
        fold_df = pd.DataFrame(candidates)
        fold_df["selected_on_train"] = fold_df.train_composite.rank(method="min", ascending=False) == 1
        fold_df["fold"] = f"{train_start.year}_to_{train_end.year}_test_{test_start.year}"
        wf_rows.extend(fold_df.to_dict("records"))
        selected = fold_df[fold_df.selected_on_train]
        if not selected.empty:
            print("\nWALK-FORWARD SELECTED ON TRAIN:", selected[["fold", "variant", "train_composite", "total_return", "sharpe", "max_dd_daily", "avg_giveback"]].to_string(index=False))
    wf_df = pd.DataFrame(wf_rows)
    wf_df.to_csv("results/profit_giveback_walkforward.csv", index=False)

    # Cost sensitivity on representative members across every exit family.
    representatives = []
    for variant in ("X0", "X1", "X2", "X3", "X4", "X5", "X6", "X7"):
        choices = [x for x in configs if x.variant == variant]
        representatives.append(choices[0] if variant == "X0" else min(choices, key=lambda x: abs(x.chandelier_k - 3.0) + abs(x.breakeven_atr - 1.5) + abs(x.trailing_pct - 0.05) + abs(x.giveback_trigger_atr - 1.0) + abs(x.giveback_fraction - 0.5) + abs(x.donchian_n - 24) + abs(x.partial_r - 1.5)))
    cost_rows = []
    for ec in representatives:
        for fee, slip in itertools.product((0.001, 0.0015, 0.002), (2.0, 5.0)):
            cfg["portfolio"]["slip_bps"] = {"crypto": slip, "equity": 5.0}
            pc = _pcfg(cfg, fee=fee)
            res, rep = runner.evaluate(panel, spec, ext, pc, start, end, "30m", exit_config=ec)
            cost_rows.append(row_for(res, rep, ec, fee, slip, start, end, "cost_sensitivity"))
            print(f"[cost] {ec.variant} fee={fee:.3%} slip={slip:g}bp ret={rep.get('total_return', float('nan')):+.2%}", flush=True)
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv("results/profit_giveback_cost_sensitivity.csv", index=False)
    print("\nCOST SENSITIVITY")
    print(cost_df[["exit_variant", "fee", "crypto_slip_bps", "total_return", "sharpe", "max_dd_daily", "trades", "fees_paid", "avg_giveback", "pct_1atr_profit_then_loser"]].to_string(index=False))


if __name__ == "__main__":
    main()
