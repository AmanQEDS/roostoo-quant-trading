import json
from types import SimpleNamespace

import pandas as pd
import pytest

from rq.live.bot import Bot
from rq.live.instance_lock import InstanceLock
from rq.live.reconciliation import reconcile_crypto_holdings


def test_empty_ledger_marks_exchange_holding_for_manual_basis_reconciliation():
    entries = {}
    required = {}
    wallet = {"USD": {"Free": 1000, "Lock": 0}, "BTC": {"Free": 0.25, "Lock": 0.1}}
    pairs = {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}}

    held, unresolved = reconcile_crypto_holdings(
        wallet,
        pairs,
        entries,
        required,
        now=pd.Timestamp("2026-10-14T12:00:00Z").to_pydatetime(),
    )

    assert held == {"BTC": pytest.approx(0.35)}
    assert unresolved == ["BTC"]
    assert "entry_price" not in entries["BTC"]
    assert required["BTC"]["reason"] == "missing_verified_entry_cost_basis"
    assert required["BTC"]["observed_quantity"] == pytest.approx(0.35)


def test_held_crypto_outside_current_entry_universe_is_still_reconciled():
    entries = {
        "CAKE": {
            "entry_price": 2.5,
            "entry_ts": "2026-10-01T00:00:00Z",
            "remaining_quantity": 3,
        }
    }
    held, unresolved = reconcile_crypto_holdings(
        {"CAKE": {"Free": 2, "Lock": 1}},
        {"CAKE/USD": {"AssetType": "crypto", "CanTrade": True}},
        entries,
        {},
    )

    assert held == {"CAKE": 3}
    assert unresolved == []
    assert entries["CAKE"]["remaining_quantity"] == 3


def test_cycle_with_empty_ledger_never_autosells_or_submits_and_freezes_entries(tmp_path):
    cfg_path = tmp_path / "live.yaml"
    cfg_path.write_text(
        "mode: run\n"
        "crypto_weight: 1.0\n"
        "pos_frac: 0.1\n"
        "max_pos: {crypto: 5, equity: 0}\n"
        "position_reconciliation:\n"
        "  unknown_basis_policy: manual_reconciliation_freeze_entries\n"
        "x18: {enabled: true, hard_stop_net_pct: 0.08, soft_time_bars: 216, "
        "soft_time_min_net_pct: 0.015, cooldown_bars: 3}\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "state" / "ledger.json"
    original = {"pool_cash": {"crypto": 67812.17, "equity": 0.0}, "entries": {}}
    ledger.parent.mkdir()
    ledger.write_text(json.dumps(original), encoding="utf-8")
    persisted_before = ledger.read_bytes()

    bot = object.__new__(Bot)
    bot.cfg_path = cfg_path
    bot.cfg = {}
    bot.dry = True
    bot.state_path = ledger
    bot.state = original
    bot.pairs = {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}}
    bot.freq = 30
    bot.api = SimpleNamespace(
        ticker=lambda: {"BTC/USD": {"LastPrice": 100, "MaxBid": 99, "MinAsk": 101}},
        balance=lambda: {"USD": {"Free": 67812.17, "Lock": 0}, "BTC": {"Free": 1, "Lock": 0}},
        place_order=lambda *args: pytest.fail("orphan holding must not be sold automatically"),
    )
    bot.signals = lambda: (_ for _ in ()).throw(RuntimeError("simulated feed outage"))

    bot.cycle()

    assert bot.state["entries"]["BTC"].get("entry_price") is None
    assert bot.state["reconciliation_required"]["BTC"]["reason"] == "missing_verified_entry_cost_basis"
    assert "unreconciled exchange holdings" in bot._entry_freeze_reasons
    assert ledger.read_bytes() == persisted_before


def test_missing_executable_bid_is_journaled_and_never_triggers_a_sale(tmp_path):
    cfg_path = tmp_path / "live.yaml"
    cfg_path.write_text(
        "mode: run\ncrypto_weight: 1.0\npos_frac: 0.1\n"
        "max_pos: {crypto: 5, equity: 0}\n"
        "position_reconciliation: {unknown_basis_policy: manual_reconciliation_freeze_entries}\n"
        "x18: {enabled: true, hard_stop_net_pct: 0.08, soft_time_bars: 216, "
        "soft_time_min_net_pct: 0.015, cooldown_bars: 3}\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "state" / "ledger.json"
    ledger.parent.mkdir()
    ledger.write_text(
        json.dumps(
            {
                "pool_cash": {"crypto": 1000, "equity": 0},
                "entries": {
                    "BTC": {
                        "entry_price": 100,
                        "entry_ts": "2026-10-14T10:00:00Z",
                        "entry_signal_bar_ts": "2026-10-14T10:00:00Z",
                        "remaining_quantity": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    bot = object.__new__(Bot)
    bot.cfg_path = cfg_path
    bot.cfg = {}
    bot.dry = True
    bot.state_path = ledger
    bot.state = json.loads(ledger.read_text(encoding="utf-8"))
    bot.pairs = {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}}
    bot.freq = 30
    bot.api = SimpleNamespace(
        ticker=lambda: {"BTC/USD": {"LastPrice": 90, "MinAsk": 91}},
        balance=lambda: {"USD": {"Free": 1000, "Lock": 0}, "BTC": {"Free": 1, "Lock": 0}},
        place_order=lambda *args: pytest.fail("a missing-bid holding must not be sold"),
    )
    bot.signals = lambda: (_ for _ in ()).throw(RuntimeError("simulated stale feed"))

    bot.cycle()

    assert bot.state["reconciliation_required"]["BTC"]["reason"] == "missing_executable_bid"
    assert bot._entry_freeze_reasons


def test_second_bot_instance_cannot_acquire_live_lock(tmp_path):
    path = tmp_path / "state" / "ledger.lock"
    first = InstanceLock(path)
    second = InstanceLock(path)

    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="another bot instance"):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()


def test_reported_dry_run_order_respects_cash_fraction_and_precision(tmp_path):
    bot = object.__new__(Bot)
    bot.dry = True
    bot.state_path = tmp_path / "ledger.json"
    bot.state = {"pool_cash": {"crypto": 67812.17}, "entries": {}}
    bot.pairs = {
        "S/USD": {
            "AssetType": "crypto",
            "CanTrade": True,
            "AmountPrecision": 1,
            "MiniOrder": 5.0,
        }
    }
    bot.cfg = {"pos_frac": 0.1}
    bot._held_quantities = {}
    bot._wallet_free_quantities = {}
    bot.order_context = {"equity": 67812.17, "peak_equity": 67812.17, "drawdown": 0, "dd_multiplier": 1}
    bot.api = SimpleNamespace(place_order=lambda *args: pytest.fail("dry-run must not submit"))
    ticker = {"S/USD": {"MinAsk": 0.05733, "LastPrice": 0.05733}}

    quantity = 118283.9
    assert bot._order("S", "BUY", quantity, ticker, "test") is True
    assert quantity * ticker["S/USD"]["MinAsk"] <= 67812.17 * 0.1
    assert bot.state["pool_cash"]["crypto"] == pytest.approx(
        67812.17 - quantity * ticker["S/USD"]["MinAsk"] * 1.001
    )
    assert bot._order("S", "BUY", quantity + 0.1, ticker, "test") is False
    assert not bot.state_path.exists()
