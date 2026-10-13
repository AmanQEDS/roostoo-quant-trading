import pandas as pd

from rq.live.position_exits import (
    estimated_net_return,
    position_exit_reason,
    short_trend_failure,
)


def test_net_return_accounts_for_both_fees():
    net = estimated_net_return(100.0, 110.0, 0.001)
    assert 0.097 < net < 0.099


def test_hard_stop_fires_independently_of_strategy_signal():
    reason = position_exit_reason(
        entry_price=100, peak_price=101, current_price=96,
        fee_rate=0.001, hard_loss_pct=0.03,
    )
    assert reason == "SELL_HARD_STOP"


def test_trailing_exit_preserves_half_of_peak_net_profit():
    reason = position_exit_reason(
        entry_price=100, peak_price=120, current_price=109,
        fee_rate=0.001, trail_activation_net_pct=0.05,
        giveback_fraction=0.50,
    )
    assert reason == "SELL_PROFIT_TRAIL"


def test_trailing_exit_does_not_activate_before_threshold():
    reason = position_exit_reason(
        entry_price=100, peak_price=103, current_price=102,
        fee_rate=0.001, trail_activation_net_pct=0.05,
    )
    assert reason is None


def test_trend_failure_is_a_separate_exit_reason():
    reason = position_exit_reason(
        entry_price=100, peak_price=101, current_price=100,
        fee_rate=0.001, trend_failure=True,
    )
    assert reason == "SELL_TREND_FAILURE"


def test_hard_stop_has_priority_over_trailing_and_trend():
    reason = position_exit_reason(
        entry_price=100, peak_price=120, current_price=90,
        fee_rate=0.001, trend_failure=True,
    )
    assert reason == "SELL_HARD_STOP"


def test_invalid_prices_do_not_trigger_exit():
    assert position_exit_reason(
        entry_price=0, peak_price=100, current_price=90, fee_rate=0.001
    ) is None


def test_short_trend_failure_requires_close_below_falling_ema():
    idx = pd.date_range("2026-01-01 00:00", periods=72, freq="5min", tz="UTC")
    close = [100 + i * 0.1 for i in range(48)] + [104 - i * 0.5 for i in range(24)]
    frame = pd.DataFrame({"close": close}, index=idx)
    now = pd.Timestamp("2026-01-01 06:00", tz="UTC")
    assert short_trend_failure(frame, timeframe_minutes=30, ema_span=3, now=now)


def test_short_trend_failure_ignores_incomplete_or_insufficient_data():
    idx = pd.date_range("2026-01-01 00:00", periods=6, freq="5min", tz="UTC")
    frame = pd.DataFrame({"close": [100, 99, 98, 97, 96, 95]}, index=idx)
    assert not short_trend_failure(
        frame, timeframe_minutes=30, ema_span=3,
        now=pd.Timestamp("2026-01-01 00:30", tz="UTC"),
    )



def test_fixed_take_profit_uses_net_return_after_fees():
    reason = position_exit_reason(
        entry_price=100, peak_price=112, current_price=110,
        fee_rate=0.001, take_profit_net_pct=0.08,
    )
    assert reason == "SELL_TAKE_PROFIT"


def test_fixed_take_profit_does_not_fire_below_target():
    reason = position_exit_reason(
        entry_price=100, peak_price=106, current_price=105,
        fee_rate=0.001, take_profit_net_pct=0.08,
    )
    assert reason is None


def test_fixed_take_profit_is_disabled_by_default():
    reason = position_exit_reason(
        entry_price=100, peak_price=106, current_price=105,
        fee_rate=0.001,
    )
    assert reason is None
