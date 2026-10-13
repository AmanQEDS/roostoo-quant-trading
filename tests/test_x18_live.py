import pytest

from rq.live.x18 import completed_bars_held, net_mark_return, x18_exit_reason


def test_net_mark_return_matches_backtest_fee_formula():
    expected = (95.0 * (1.0 - 0.001) / (100.0 * (1.0 + 0.001))) - 1.0
    assert net_mark_return(100.0, 95.0, 0.001) == pytest.approx(expected)


def test_invalid_prices_do_not_trigger_exit():
    assert net_mark_return(0, 95, 0.001) is None
    assert x18_exit_reason(0, 95, 0.001, 300) is None


def test_x18_hard_stop_uses_net_return():
    assert x18_exit_reason(100, 91.8, 0.001, 1) == "hard_stop_X18"


def test_x18_time_exit_only_after_threshold_and_below_minimum():
    assert x18_exit_reason(100, 100.0, 0.001, 215) is None
    assert x18_exit_reason(100, 100.0, 0.001, 216) == "soft_time_X18"


def test_x18_time_exit_does_not_fire_if_net_return_meets_minimum():
    # With fees included, a price above entry is required to clear +1.5% net.
    assert x18_exit_reason(100, 102.0, 0.001, 216) is None


def test_completed_bar_count_uses_signal_bar_timestamps():
    assert completed_bars_held(
        "2026-10-13T00:00:00Z", "2026-10-13T01:30:00Z", 30
    ) == 3


def test_missing_entry_bar_disables_only_time_based_exit():
    assert completed_bars_held(None, "2026-10-13T01:30:00Z", 30) is None
    assert x18_exit_reason(100, 91.8, 0.001, None) == "hard_stop_X18"
    assert x18_exit_reason(100, 100, 0.001, None) is None
