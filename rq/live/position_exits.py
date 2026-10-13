"""Per-position exit rules for the research-only live-bot feature flag.

These functions are pure and do not place orders. The caller owns persistence,
position sizing, order submission, and re-entry cooldowns.
"""
from __future__ import annotations

import pandas as pd


def estimated_net_return(entry_price: float, mark_price: float, fee_rate: float) -> float:
    """Estimate return after entry and exit taker fees, before slippage."""
    entry = float(entry_price)
    mark = float(mark_price)
    fee = float(fee_rate)
    if entry <= 0 or mark <= 0 or not 0 <= fee < 1:
        return float("-inf")
    return (mark * (1.0 - fee)) / (entry * (1.0 + fee)) - 1.0


def position_exit_reason(
    *,
    entry_price: float,
    peak_price: float,
    current_price: float,
    fee_rate: float,
    hard_loss_pct: float = 0.03,
    trail_activation_net_pct: float = 0.05,
    giveback_fraction: float = 0.50,
    trend_failure: bool = False,
) -> str | None:
    """Return an explicit exit reason or None.

    The trailing rule activates after net estimated profit reaches 5% by
    default. A 50% giveback means the position exits when current net profit
    falls to 50% of the peak net profit. The hard stop is a net-return limit.
    """
    entry = float(entry_price)
    peak = float(peak_price)
    current = float(current_price)
    if entry <= 0 or peak <= 0 or current <= 0:
        return None
    if hard_loss_pct < 0:
        raise ValueError("hard_loss_pct must be non-negative")
    if trail_activation_net_pct < 0:
        raise ValueError("trail_activation_net_pct must be non-negative")
    if not 0 <= giveback_fraction <= 1:
        raise ValueError("giveback_fraction must be between 0 and 1")

    current_net = estimated_net_return(entry, current, fee_rate)
    peak_net = estimated_net_return(entry, peak, fee_rate)

    if current_net <= -float(hard_loss_pct):
        return "SELL_HARD_STOP"

    if (
        peak_net >= float(trail_activation_net_pct)
        and current_net <= peak_net * (1.0 - float(giveback_fraction))
    ):
        return "SELL_PROFIT_TRAIL"

    if trend_failure:
        return "SELL_TREND_FAILURE"

    return None


def short_trend_failure(
    frame: pd.DataFrame | None,
    timeframe_minutes: int = 30,
    ema_span: int = 10,
    now: pd.Timestamp | None = None,
) -> bool:
    """Detect a confirmed short-term trend failure using completed bars only.

    Resamples 5-minute feed closes into the configured strategy timeframe.
    A failure requires the latest completed close below its EMA and the EMA
    falling versus the prior completed bar.
    """
    if frame is None or frame.empty or "close" not in frame.columns:
        return False
    if timeframe_minutes <= 0 or ema_span < 2:
        raise ValueError("timeframe_minutes must be positive and ema_span >= 2")

    current_time = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if current_time.tzinfo is None:
        current_time = current_time.tz_localize("UTC")
    else:
        current_time = current_time.tz_convert("UTC")

    rule = f"{int(timeframe_minutes)}min"
    completed_before = current_time.floor(rule)
    closes = frame["close"].astype(float).resample(
        rule, label="right", closed="left"
    ).last().dropna()
    closes = closes.loc[closes.index <= completed_before]
    if len(closes) < ema_span + 1:
        return False

    ema = closes.ewm(span=ema_span, adjust=False).mean()
    return bool(
        closes.iloc[-1] < ema.iloc[-1]
        and ema.iloc[-1] < ema.iloc[-2]
    )
