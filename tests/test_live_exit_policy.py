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


def test_cycle_routes_take_profit_to_dry_run_order(monkeypatch):
    from types import SimpleNamespace
    import rq.live.bot as live_bot_module

    bot = object.__new__(Bot)
    tick = {
        "BTC/USD": {
            "LastPrice": 110.0,
            "MaxBid": 110.0,
            "MinAsk": 111.0,
        }
    }
    wallet = {
        "USD": {"Free": 100.0, "Lock": 0.0},
        "BTC": {"Free": 1.0, "Lock": 0.0},
    }
    config = {
        "mode": "test",
        "position_exits": {
            "enabled": True,
            "take_profit_net_pct": 0.08,
        },
    }

    monkeypatch.setattr(
        live_bot_module.yaml, "safe_load", lambda _: config
    )
    monkeypatch.setattr(
        live_bot_module, "short_trend_failure", lambda *a, **k: False
    )

    bot.dry = True
    bot.api = SimpleNamespace(
        ticker=lambda: tick,
        balance=lambda: wallet,
    )
    bot.pairs = {
        "BTC/USD": {
            "Coin": "BTC",
            "AssetType": "crypto",
            "AmountPrecision": 6,
        }
    }
    bot.state = {
        "pool_cash": {"crypto": 100.0, "equity": 0.0},
        "entries": {
            "BTC": {
                "entry_price": 100.0,
                "peak_price_since_entry": 112.0,
                "trough_price_since_entry": 100.0,
                "mfe": 12.0,
                "mae": 0.0,
            }
        },
    }
    bot.order_context = {
        "equity": None,
        "peak_equity": None,
        "drawdown": None,
        "dd_multiplier": None,
    }
    bot.freq = 30
    bot.feed = SimpleNamespace(d={})
    bot._liquidate_equities = lambda wallet, tick: None
    bot.signals = lambda: pd.Series(dtype=float)
    bot.save = lambda: None

    orders = []

    def fake_order(coin, side, qty, tick, reason=None):
        orders.append((coin, side, qty, reason))
        return True

    bot._order = fake_order

    Bot.cycle(bot)

    assert len(orders) == 1
    assert orders[0][0] == "BTC"
    assert orders[0][1] == "SELL"
    assert orders[0][2] > 0
    assert orders[0][3] == "SELL_TAKE_PROFIT"
