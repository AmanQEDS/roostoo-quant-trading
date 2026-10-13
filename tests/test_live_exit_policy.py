import json

import pandas as pd

from rq.live.bot import Bot, should_exit_held, update_peak_equity


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


def test_peak_equity_is_monotonic_and_saved(tmp_path):
    state = {"peak": 100.0}
    assert update_peak_equity(state, 90.0) == 100.0
    assert update_peak_equity(state, 120.0) == 120.0
    assert update_peak_equity(state, 110.0) == 120.0

    bot = object.__new__(Bot)
    bot.state_path = tmp_path / "ledger.json"
    bot.state = state
    bot.save()
    saved = json.loads(bot.state_path.read_text())
    assert saved["peak"] == 120.0
