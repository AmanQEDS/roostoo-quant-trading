"""Export and reconcile trade-level and portfolio-level backtest audit files."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


TRADE_COLUMNS = [
    "trade_id", "symbol", "entry_timestamp", "exit_timestamp", "side", "entry_price",
    "exit_price", "quantity", "gross_pnl", "fees", "net_pnl", "return_pct",
    "holding_period_hours", "entry_fee", "exit_fee", "entry_fill_id", "exit_fill_id",
    "entry_fill_qty", "entry_fill_px", "exit_fill_qty", "exit_fill_px", "reason",
]
OPEN_COLUMNS = [
    "trade_id", "symbol", "side", "entry_timestamp", "entry_price", "quantity",
    "current_price", "entry_fee", "gross_unrealized_pnl", "unrealized_pnl",
    "unrealized_return_pct",
]
PORTFOLIO_COLUMNS = [
    "timestamp", "cash", "gross_exposure", "net_exposure", "portfolio_value",
    "realized_pnl", "unrealized_pnl", "total_pnl", "drawdown",
]


def export_backtest_audit(result, initial_capital: float, expected_trades: int,
                          stem: str, output_dir: str | Path = "results",
                          reported_max_drawdown: float | None = None) -> tuple[dict, dict[str, Path]]:
    """Write audit CSVs after checking trade, fee, P&L, ID, and timestamp reconciliation."""
    raw_trades = result.trades.copy()
    if raw_trades.empty:
        trades = pd.DataFrame(columns=TRADE_COLUMNS)
    else:
        trades = raw_trades.rename(columns={
            "asset": "symbol", "entry_time": "entry_timestamp", "exit_time": "exit_timestamp",
            "entry_px": "entry_price", "exit_px": "exit_price", "qty": "quantity",
            "pnl_net": "net_pnl", "entry_fill_qty": "entry_fill_qty",
        })
        trades["side"] = trades["side"].map({1: "LONG", -1: "SHORT"})
        trades = trades.sort_values(["entry_timestamp", "trade_id"], kind="stable").reset_index(drop=True)
        trades = trades.reindex(columns=TRADE_COLUMNS)

    open_positions = pd.DataFrame(result.open_positions)
    if open_positions.empty:
        open_positions = pd.DataFrame(columns=OPEN_COLUMNS)
    else:
        open_positions = open_positions.rename(columns={
            "asset": "symbol", "entry_time": "entry_timestamp", "entry": "entry_price", "qty": "quantity",
        })
        open_positions["side"] = open_positions["side"].map({1: "LONG", -1: "SHORT"})
        open_positions = open_positions.reindex(columns=OPEN_COLUMNS)

    portfolio = result.curve.copy()
    portfolio.index.name = "timestamp"
    portfolio = portfolio.reset_index().rename(columns={"equity_total": "portfolio_value"})
    portfolio = portfolio.reindex(columns=PORTFOLIO_COLUMNS)

    if len(trades) != expected_trades:
        raise ValueError(f"audit trade count {len(trades)} does not match reported n_trades {expected_trades}")
    if trades["trade_id"].duplicated().any():
        raise ValueError("duplicate trade IDs in completed trade ledger")
    if not trades.empty and (trades["entry_timestamp"] > trades["exit_timestamp"]).any():
        raise ValueError("completed trade has exit before entry")
    if not portfolio["timestamp"].is_monotonic_increasing:
        raise ValueError("portfolio timestamps are not chronological")
    if trades["trade_id"].isin(open_positions["trade_id"]).any():
        raise ValueError("an open position is also listed as a completed trade")

    completed_fees = float(trades["fees"].sum()) if not trades.empty else 0.0
    open_fees = float(open_positions["entry_fee"].sum()) if not open_positions.empty else 0.0
    if not np.isclose(completed_fees + open_fees, result.fees, rtol=1e-9, atol=1e-6):
        raise ValueError("trade and open-position fees do not reconcile with engine total fees")

    realized_pnl = float(portfolio["realized_pnl"].iloc[-1])
    unrealized_pnl = float(portfolio["unrealized_pnl"].iloc[-1])
    total_pnl = float(portfolio["total_pnl"].iloc[-1])
    ledger_pnl = (float(trades["net_pnl"].sum()) if not trades.empty else 0.0) + (
        float(open_positions["unrealized_pnl"].sum()) if not open_positions.empty else 0.0
    )
    if not np.isclose(ledger_pnl, total_pnl, rtol=1e-9, atol=1e-5):
        raise ValueError(f"trade P&L {ledger_pnl} does not reconcile with portfolio P&L {total_pnl}")
    if not np.isclose(realized_pnl, trades["net_pnl"].sum() if not trades.empty else 0.0,
                      rtol=1e-9, atol=1e-5):
        raise ValueError("realized P&L does not reconcile with completed trades")
    if not np.isclose(unrealized_pnl, open_positions["unrealized_pnl"].sum() if not open_positions.empty else 0.0,
                      rtol=1e-9, atol=1e-5):
        raise ValueError("unrealized P&L does not reconcile with ending open positions")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "trades": output / f"trades_{stem}.csv",
        "equity": output / f"equity_{stem}.csv",
        "open_positions": output / f"open_positions_{stem}.csv",
    }
    trades.to_csv(paths["trades"], index=False)
    portfolio.to_csv(paths["equity"], index=False)
    open_positions.to_csv(paths["open_positions"], index=False)

    starting_value = float(initial_capital)
    ending_value = float(portfolio["portfolio_value"].iloc[-1])
    bar_level_max_drawdown_pct = float(portfolio["drawdown"].min() * 100)
    net_trades = trades["net_pnl"] if not trades.empty else pd.Series(dtype=float)
    winners = net_trades[net_trades > 0]
    losers = net_trades[net_trades < 0]
    profit_factor = (float(winners.sum() / abs(losers.sum())) if losers.sum() < 0
                     else (float("inf") if winners.sum() > 0 else float("nan")))
    summary = {
        "starting_capital": starting_value,
        "ending_portfolio_value": ending_value,
        "total_return_pct": (ending_value / starting_value - 1) * 100 if starting_value else float("nan"),
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "realized_return_pct": realized_pnl / starting_value * 100 if starting_value else float("nan"),
        "unrealized_return_pct": unrealized_pnl / starting_value * 100 if starting_value else float("nan"),
        "total_fees": float(result.fees),
        "completed_trades": len(trades),
        "open_positions": len(open_positions),
        "max_drawdown_pct": (float(reported_max_drawdown) * 100 if reported_max_drawdown is not None
                     else bar_level_max_drawdown_pct),
        "bar_level_max_drawdown_pct": bar_level_max_drawdown_pct,
        "closed_trade_win_rate_pct": float((net_trades > 0).mean() * 100) if len(net_trades) else float("nan"),
        "profit_factor": profit_factor,
        "average_trade_net_pnl": float(net_trades.mean()) if len(net_trades) else float("nan"),
        "median_holding_period_hours": float(trades["holding_period_hours"].median()) if len(trades) else float("nan"),
    }
    return summary, paths