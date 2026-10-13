import pandas as pd

from rq.live.bot import should_exit_held


def test_held_position_is_not_exited_when_absent_from_current_universe():
    target = pd.Series({"ETH": 1})
    assert not should_exit_held("BTC", target, "run")


def test_held_position_is_not_exited_by_candidate_ranking():
    # Ranking is applied to entries; a still-long held position remains held.
    target = pd.Series({"BTC": 1, "ETH": 1})
    assert not should_exit_held("BTC", target, "run")


def test_held_position_exits_on_explicit_flat_signal():
    target = pd.Series({"BTC": 0, "ETH": 1})
    assert should_exit_held("BTC", target, "run")


def test_explicit_liquidation_mode_overrides_sticky_hold():
    target = pd.Series({"BTC": 1})
    assert should_exit_held("BTC", target, "liquidate")
