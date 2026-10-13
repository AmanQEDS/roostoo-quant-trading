"""X18 live exit rules, aligned with rq/backtest/engine.py."""
from __future__ import annotations

import pandas as pd


def net_mark_return(entry_price: float, sell_price: float, fee_rate: float):
    """Backtest-compatible fee-adjusted long return at the executable sell price."""
    entry = float(entry_price or 0)
    sell = float(sell_price or 0)
    fee = float(fee_rate)

    if entry <= 0 or sell <= 0 or fee < 0 or fee >= 1:
        return None

    return (sell * (1.0 - fee) / (entry * (1.0 + fee))) - 1.0


def completed_bars_held(entry_bar_ts, current_bar_ts, timeframe_minutes: int):
    """Return elapsed completed signal bars, or None when timestamps are unknown."""
    if not entry_bar_ts or current_bar_ts is None or timeframe_minutes <= 0:
        return None

    try:
        entry = pd.Timestamp(entry_bar_ts)
        current = pd.Timestamp(current_bar_ts)

        if entry.tzinfo is None:
            entry = entry.tz_localize("UTC")
        else:
            entry = entry.tz_convert("UTC")

        if current.tzinfo is None:
            current = current.tz_localize("UTC")
        else:
            current = current.tz_convert("UTC")

        seconds = (current - entry).total_seconds()
        if seconds < 0:
            return None

        return int(seconds // (int(timeframe_minutes) * 60))
    except (TypeError, ValueError, OverflowError):
        return None


def x18_exit_reason(
    entry_price: float,
    sell_price: float,
    fee_rate: float,
    bars_held,
    hard_stop_net_pct: float = 0.08,
    soft_time_bars: int = 216,
    soft_time_min_net_pct: float = 0.015,
):
    """Return an X18 exit reason, or None if neither X18 rule is triggered."""
    net_return = net_mark_return(entry_price, sell_price, fee_rate)
    if net_return is None:
        return None

    if net_return <= -float(hard_stop_net_pct):
        return "hard_stop_X18"

    if (
        bars_held is not None
        and int(bars_held) >= int(soft_time_bars)
        and net_return < float(soft_time_min_net_pct)
    ):
        return "soft_time_X18"

    return None
