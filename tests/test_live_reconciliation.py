import json
from types import SimpleNamespace

import pandas as pd
import pytest

from rq.live.bot import Bot
from rq.live.instance_lock import InstanceLock
from rq.live.reconciliation import (
    UNKNOWN_TIME_POLICY,
    apply_manual_reconciliation,
    execution_journal_scope,
    reconcile_crypto_holdings,
    recover_from_exchange_orders,
    recover_from_execution_journal,
)


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


def test_entry_timestamp_missing_is_unresolved_even_when_basis_and_quantity_match():
    entries = {"BTC": {"entry_price": 100, "remaining_quantity": 0.35}}
    required = {}

    held, unresolved = reconcile_crypto_holdings(
        {"BTC": {"Free": 0.25, "Lock": 0.1}},
        {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}},
        entries,
        required,
    )

    assert held == {"BTC": pytest.approx(0.35)}
    assert unresolved == ["BTC"]
    assert required["BTC"]["reason"] == "missing_entry_timestamp"


def test_reconciliation_flags_exchange_and_ledger_quantity_mismatch():
    entries = {
        "BTC": {
            "entry_price": 100,
            "entry_ts": "2026-10-14T10:00:00Z",
            "remaining_quantity": 0.2,
        }
    }
    required = {}

    held, unresolved = reconcile_crypto_holdings(
        {"BTC": {"Free": 0.25, "Lock": 0.1}},
        {"BTC/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 8}},
        entries,
        required,
    )

    assert held == {"BTC": pytest.approx(0.35)}
    assert unresolved == ["BTC"]
    assert required["BTC"]["reason"] == "exchange_local_quantity_mismatch"
    assert entries["BTC"]["remaining_quantity"] == pytest.approx(0.2)


def test_unsupported_exchange_pair_remains_unresolved():
    entries = {}
    required = {}

    held, unresolved = reconcile_crypto_holdings(
        {"EDEN": {"Free": 10, "Lock": 0}},
        {"EDEN/USD": {"AssetType": "crypto", "CanTrade": False}},
        entries,
        required,
    )

    assert held == {"EDEN": pytest.approx(10)}
    assert unresolved == ["EDEN"]
    assert required["EDEN"]["reason"] == "exchange_pair_not_tradable"


def test_execution_journal_recovers_weighted_basis_partial_fills_and_fifo_age_after_sell(tmp_path):
    journal = tmp_path / "api_journal.jsonl"
    scope = execution_journal_scope("test-key")
    events = [
        {
            "t": 1,
            "account_scope": scope,
            "method": "POST",
            "path": "/v3/place_order",
            "params": {"pair": "BTC/USD", "side": "BUY"},
            "resp": {
                "Success": True,
                "OrderDetail": {
                    "OrderID": 1,
                    "Status": "PARTIAL",
                    "FilledQuantity": 1,
                    "FilledAverPrice": 100,
                    "Side": "BUY",
                    "Pair": "BTC/USD",
                    "FilledTime": "2026-10-01T10:00:00Z",
                },
            },
        },
        {
            "t": 2,
            "account_scope": scope,
            "method": "POST",
            "path": "/v3/query_order",
            "params": {"order_id": "1"},
            "resp": {
                "Success": True,
                "OrderDetail": {
                    "OrderID": 1,
                    "Status": "FILLED",
                    "FilledQuantity": 2,
                    "FilledAverPrice": 100,
                    "Side": "BUY",
                    "Pair": "BTC/USD",
                    "FilledTime": "2026-10-01T10:00:00Z",
                },
            },
        },
        {
            "t": 3,
            "account_scope": scope,
            "method": "POST",
            "path": "/v3/place_order",
            "params": {"pair": "BTC/USD", "side": "BUY"},
            "resp": {
                "Success": True,
                "OrderDetail": {
                    "OrderID": 2,
                    "Status": "FILLED",
                    "FilledQuantity": 0.5,
                    "FilledAverPrice": 120,
                    "Side": "BUY",
                    "Pair": "BTC/USD",
                    "FilledTime": "2026-10-02T10:00:00Z",
                },
            },
        },
        {
            "t": 4,
            "account_scope": scope,
            "method": "POST",
            "path": "/v3/place_order",
            "params": {"pair": "BTC/USD", "side": "SELL"},
            "resp": {
                "Success": True,
                "OrderDetail": {
                    "OrderID": 3,
                    "Status": "FILLED",
                    "FilledQuantity": 0.25,
                    "FilledAverPrice": 130,
                    "Side": "SELL",
                    "Pair": "BTC/USD",
                    "FilledTime": "2026-10-03T10:00:00Z",
                },
            },
        },
    ]
    journal.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    entries = {}
    required = {}
    wallet = {"BTC": {"Free": 2.25, "Lock": 0}}

    recovered = recover_from_execution_journal(
        journal,
        wallet,
        {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}},
        entries,
        required,
        account_scope=scope,
    )

    assert recovered == ["BTC"]
    assert entries["BTC"]["remaining_quantity"] == pytest.approx(2.25)
    assert entries["BTC"]["entry_quantity"] == pytest.approx(2.5)
    assert entries["BTC"]["entry_price"] == pytest.approx(104)
    assert entries["BTC"]["entry_ts"] == "2026-10-01T10:00:00+00:00"
    assert entries["BTC"]["entry_source"]["order_ids"] == ["1", "2", "3"]
    entries["BTC"]["peak_price_since_entry"] = 150
    assert recover_from_execution_journal(
        journal,
        wallet,
        {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}},
        entries,
        required,
        account_scope=scope,
    ) == []
    assert entries["BTC"]["peak_price_since_entry"] == 150


def test_execution_journal_basis_conflict_is_not_overwritten(tmp_path):
    journal = tmp_path / "api_journal.jsonl"
    scope = execution_journal_scope("test-key")
    journal.write_text(
        json.dumps(
            {
                "t": 1,
                "account_scope": scope,
                "method": "POST",
                "path": "/v3/place_order",
                "params": {"pair": "BTC/USD", "side": "BUY"},
                "resp": {
                    "Success": True,
                    "OrderDetail": {
                        "OrderID": 1,
                        "Status": "FILLED",
                        "FilledQuantity": 1,
                        "FilledAverPrice": 100,
                        "FilledTime": "2026-10-01T10:00:00Z",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    entries = {
        "BTC": {
            "entry_price": 99,
            "entry_ts": "2026-10-01T10:00:00Z",
            "remaining_quantity": 1,
        }
    }
    required = {}

    assert recover_from_execution_journal(
        journal,
        {"BTC": {"Free": 1, "Lock": 0}},
        {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}},
        entries,
        required,
        account_scope=scope,
    ) == []
    assert entries["BTC"]["entry_price"] == 99
    assert required["BTC"]["reason"] == "execution_history_basis_mismatch"


def test_execution_journal_recovers_verified_time_without_resetting_excursions(tmp_path):
    journal = tmp_path / "api_journal.jsonl"
    scope = execution_journal_scope("test-key")
    journal.write_text(
        json.dumps(
            {
                "t": 1,
                "account_scope": scope,
                "method": "POST",
                "path": "/v3/place_order",
                "params": {"pair": "BTC/USD", "side": "BUY"},
                "resp": {
                    "Success": True,
                    "OrderDetail": {
                        "OrderID": 1,
                        "Status": "FILLED",
                        "FilledQuantity": 1,
                        "FilledAverPrice": 100,
                        "FilledTime": "2026-10-01T10:00:00Z",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    entries = {
        "BTC": {
            "entry_price": 100,
            "remaining_quantity": 1,
            "entry_time_status": "unknown_operator_attested",
            "time_exit_policy": UNKNOWN_TIME_POLICY,
            "peak_price_since_entry": 125,
            "trough_price_since_entry": 90,
            "mfe": 25,
            "mae": -10,
        }
    }

    assert recover_from_execution_journal(
        journal,
        {"BTC": {"Free": 1, "Lock": 0}},
        {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}},
        entries,
        {},
        account_scope=scope,
    ) == ["BTC"]
    assert entries["BTC"]["entry_ts"] == "2026-10-01T10:00:00+00:00"
    assert entries["BTC"]["entry_time_status"] == "verified"
    assert entries["BTC"]["time_exit_policy"] == "verified_timestamp"
    assert entries["BTC"]["peak_price_since_entry"] == 125
    assert entries["BTC"]["mfe"] == 25


def test_execution_journal_does_not_invent_entry_timestamp(tmp_path):
    journal = tmp_path / "api_journal.jsonl"
    scope = execution_journal_scope("test-key")
    journal.write_text(
        json.dumps(
            {
                "t": 1234567890,
                "account_scope": scope,
                "method": "POST",
                "path": "/v3/place_order",
                "params": {"pair": "BTC/USD", "side": "BUY"},
                "resp": {
                    "Success": True,
                    "OrderDetail": {
                        "OrderID": 1,
                        "Status": "FILLED",
                        "FilledQuantity": 1,
                        "FilledAverPrice": 100,
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    entries = {}

    required = {}
    recover_from_execution_journal(
        journal,
        {"BTC": {"Free": 1, "Lock": 0}},
        {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}},
        entries,
        required,
        account_scope=scope,
    )
    held, unresolved = reconcile_crypto_holdings(
        {"BTC": {"Free": 1, "Lock": 0}},
        {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}},
        entries,
        required,
    )

    assert entries["BTC"]["entry_ts"] is None
    assert held == {"BTC": 1}
    assert unresolved == ["BTC"]
    assert required["BTC"]["reason"] == "missing_entry_timestamp"


def test_execution_journal_quantity_mismatch_is_not_adopted(tmp_path):
    journal = tmp_path / "api_journal.jsonl"
    scope = execution_journal_scope("test-key")
    journal.write_text(
        json.dumps(
            {
                "t": 1,
                "account_scope": scope,
                "method": "POST",
                "path": "/v3/place_order",
                "params": {"pair": "BTC/USD", "side": "BUY"},
                "resp": {
                    "Success": True,
                    "OrderDetail": {
                        "OrderID": 1,
                        "Status": "FILLED",
                        "FilledQuantity": 1,
                        "FilledAverPrice": 100,
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    entries = {}
    required = {}

    assert recover_from_execution_journal(
        journal,
        {"BTC": {"Free": 2, "Lock": 0}},
        {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}},
        entries,
        required,
        account_scope=scope,
    ) == []
    assert "BTC" not in entries
    assert required["BTC"]["reason"] == "execution_history_quantity_mismatch"


def test_execution_journal_from_another_account_is_not_used(tmp_path):
    journal = tmp_path / "api_journal.jsonl"
    journal.write_text(
        json.dumps(
            {
                "t": 1,
                "account_scope": execution_journal_scope("different-account"),
                "method": "POST",
                "path": "/v3/place_order",
                "params": {"pair": "BTC/USD", "side": "BUY"},
                "resp": {
                    "Success": True,
                    "OrderDetail": {
                        "OrderID": 1,
                        "Status": "FILLED",
                        "FilledQuantity": 1,
                        "FilledAverPrice": 100,
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    entries = {}
    required = {}

    assert recover_from_execution_journal(
        journal,
        {"BTC": {"Free": 1, "Lock": 0}},
        {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}},
        entries,
        required,
        account_scope=execution_journal_scope("current-account"),
    ) == []
    assert entries == {}
    assert required == {}


def test_manual_reconciliation_validates_and_audits_unknown_timestamp_fallback():
    entries = {}
    required = {"BTC": {"reason": "missing_verified_entry_cost_basis"}}
    audit = []
    wallet = {"BTC": {"Free": 0.35, "Lock": 0}}
    document = {
        "positions": {
            "BTC": {
                "record_id": "review-2026-10-14-btc",
                "operator": "reviewer",
                "source": "Roostoo order history checked; reference order 123",
                "entry_price": 100,
                "remaining_quantity": 0.35,
                "entry_ts": None,
                "entry_timestamp_unknown": True,
                "time_exit_policy": UNKNOWN_TIME_POLICY,
            }
        }
    }
    pairs = {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}}

    applied = apply_manual_reconciliation(
        document,
        wallet,
        pairs,
        entries,
        required,
        audit,
        now=pd.Timestamp("2026-10-14T12:00:00Z").to_pydatetime(),
    )
    held, unresolved = reconcile_crypto_holdings(
        wallet, pairs, entries, required
    )
    duplicate_apply = apply_manual_reconciliation(
        document, wallet, pairs, entries, required, audit
    )
    after_position_closed = apply_manual_reconciliation(
        document, {}, {}, entries, required, audit
    )

    assert applied == ["BTC"]
    assert duplicate_apply == []
    assert after_position_closed == []
    assert len(audit) == 1
    assert held == {"BTC": pytest.approx(0.35)}
    assert unresolved == []
    assert "BTC" not in required
    assert entries["BTC"]["entry_ts"] is None
    assert entries["BTC"]["time_exit_policy"] == UNKNOWN_TIME_POLICY


def test_manual_reconciliation_accepts_only_timezone_aware_verified_timestamp():
    entries = {}
    required = {"BTC": {"reason": "missing_entry_timestamp"}}
    audit = []
    document = {
        "positions": {
            "BTC": {
                "record_id": "review-verified-time",
                "operator": "reviewer",
                "source": "verified exchange fill history",
                "entry_price": 100,
                "remaining_quantity": 1,
                "entry_ts": "2026-10-14T10:00:00-04:00",
            }
        }
    }

    assert apply_manual_reconciliation(
        document,
        {"BTC": {"Free": 1, "Lock": 0}},
        {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}},
        entries,
        required,
        audit,
    ) == ["BTC"]
    assert entries["BTC"]["entry_ts"] == "2026-10-14T14:00:00+00:00"
    assert entries["BTC"]["entry_time_status"] == "verified"
    assert "BTC" not in required


def test_manual_reconciliation_rejects_quantity_mismatch_without_clearing_flag():
    entries = {}
    required = {"BTC": {"reason": "missing_verified_entry_cost_basis"}}
    audit = []
    document = {
        "positions": {
            "BTC": {
                "record_id": "review-1",
                "operator": "reviewer",
                "source": "order history",
                "entry_price": 100,
                "remaining_quantity": 0.5,
                "entry_ts": None,
                "entry_timestamp_unknown": True,
                "time_exit_policy": UNKNOWN_TIME_POLICY,
            }
        }
    }

    with pytest.raises(ValueError, match="does not match exchange quantity"):
        apply_manual_reconciliation(
            document,
            {"BTC": {"Free": 1, "Lock": 0}},
            {"BTC/USD": {"AssetType": "crypto", "CanTrade": True}},
            entries,
            required,
            audit,
        )
    assert entries == {}
    assert "BTC" in required
    assert audit == []


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


def test_manual_reconciliation_dry_cycle_can_manage_position_without_live_submission(tmp_path):
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
    original = {"pool_cash": {"crypto": 1000, "equity": 0}, "entries": {}}
    ledger.write_text(json.dumps(original), encoding="utf-8")
    before = ledger.read_bytes()
    (ledger.parent / "reconciliation_manual.json").write_text(
        json.dumps(
            {
                "positions": {
                    "BTC": {
                        "record_id": "test-btc-20261014",
                        "operator": "test operator",
                        "source": "verified exchange fill record 77",
                        "entry_price": 100,
                        "remaining_quantity": 1,
                        "entry_ts": None,
                        "entry_timestamp_unknown": True,
                        "time_exit_policy": UNKNOWN_TIME_POLICY,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    bot = object.__new__(Bot)
    bot.cfg_path = cfg_path
    bot.cfg = {}
    bot.dry = True
    bot.state_path = ledger
    bot.state = original
    bot.pairs = {
        "BTC/USD": {
            "AssetType": "crypto",
            "CanTrade": True,
            "AmountPrecision": 8,
            "MiniOrder": 5,
        }
    }
    bot.freq = 30
    bot.api = SimpleNamespace(
        ticker=lambda: {"BTC/USD": {"LastPrice": 90, "MaxBid": 90, "MinAsk": 91}},
        balance=lambda: {"USD": {"Free": 1000, "Lock": 0}, "BTC": {"Free": 1, "Lock": 0}},
        place_order=lambda *args: pytest.fail("dry-run must not submit real orders"),
    )
    bot.signals = lambda: (_ for _ in ()).throw(RuntimeError("feed unavailable"))

    bot.cycle()

    assert bot.state["entries"]["BTC"]["entry_price"] == 100
    assert bot.state["entries"]["BTC"]["entry_ts"] is None
    assert bot.state["entries"]["BTC"]["time_exit_policy"] == UNKNOWN_TIME_POLICY
    assert bot.state["reconciliation_audit"][0]["record_id"] == "test-btc-20261014"
    assert bot._held_quantities["BTC"] == pytest.approx(0)
    assert "X18 hold age unavailable" not in bot._entry_freeze_reasons
    assert ledger.read_bytes() == before


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


def test_four_holdings_recovery_from_exchange_order_history():
    """Verify BTC, CAKE, EDEN, and FIL recover from exchange OrderMatched history."""
    wallet = {
        "BTC": {"Free": 0.08992, "Lock": 0},
        "CAKE": {"Free": 3011.12, "Lock": 0},
        "EDEN": {"Free": 111203.6, "Lock": 0},
        "FIL": {"Free": 5786.78, "Lock": 0},
    }
    pairs = {
        "BTC/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 5},
        "CAKE/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 2},
        "EDEN/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 1},
        "FIL/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 2},
    }
    # Millisecond epoch timestamps matching Roostoo exchange responses
    order_matched = [
        {
            "OrderID": 1001,
            "Pair": "BTC/USD",
            "Side": "BUY",
            "Status": "FILLED",
            "FilledQuantity": 0.08992,
            "FilledAverPrice": 62500.0,
            "CreateTimestamp": 1728000000000,
            "FinishTimestamp": 1728000001000,
            "CommissionChargeValue": 5.62,
        },
        {
            "OrderID": 1002,
            "Pair": "CAKE/USD",
            "Side": "BUY",
            "Status": "FILLED",
            "FilledQuantity": 3011.12,
            "FilledAverPrice": 2.15,
            "CreateTimestamp": 1728000100000,
            "FinishTimestamp": 1728000102000,
            "CommissionChargeValue": 6.47,
        },
        {
            "OrderID": 1003,
            "Pair": "EDEN/USD",
            "Side": "BUY",
            "Status": "FILLED",
            "FilledQuantity": 111203.6,
            "FilledAverPrice": 0.085,
            "CreateTimestamp": 1728000200000,
            "FinishTimestamp": 1728000203000,
            "CommissionChargeValue": 9.45,
        },
        {
            "OrderID": 1004,
            "Pair": "FIL/USD",
            "Side": "BUY",
            "Status": "FILLED",
            "FilledQuantity": 5786.78,
            "FilledAverPrice": 3.80,
            "CreateTimestamp": 1728000300000,
            "FinishTimestamp": 1728000304000,
            "CommissionChargeValue": 21.99,
        },
    ]

    entries = {}
    reconciliation_required = {}
    recovered = recover_from_exchange_orders(
        order_matched,
        wallet,
        pairs,
        entries,
        reconciliation_required,
    )
    held, unresolved = reconcile_crypto_holdings(
        wallet, pairs, entries, reconciliation_required
    )

    assert sorted(recovered) == ["BTC", "CAKE", "EDEN", "FIL"]
    assert unresolved == []
    assert reconciliation_required == {}
    assert entries["BTC"]["entry_price"] == pytest.approx(62500.0)
    assert entries["BTC"]["remaining_quantity"] == pytest.approx(0.08992)
    assert entries["BTC"]["entry_ts"].startswith("2024-") or "+00:00" in entries["BTC"]["entry_ts"]
    assert entries["CAKE"]["entry_price"] == pytest.approx(2.15)
    assert entries["EDEN"]["entry_price"] == pytest.approx(0.085)
    assert entries["FIL"]["entry_price"] == pytest.approx(3.80)


def test_four_holdings_partial_fills_and_sells_fifo():
    """Verify multi-order accumulation and FIFO sales across four holdings."""
    wallet = {
        "BTC": {"Free": 0.08992, "Lock": 0},
        "CAKE": {"Free": 3011.12, "Lock": 0},
    }
    pairs = {
        "BTC/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 5},
        "CAKE/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 2},
    }
    orders = [
        # BTC: bought 0.1, sold 0.01008 -> remaining 0.08992
        {
            "OrderID": 1,
            "Pair": "BTC/USD",
            "Side": "BUY",
            "Status": "FILLED",
            "FilledQuantity": 0.1,
            "FilledAverPrice": 60000.0,
            "FinishTimestamp": 1728000000000,
        },
        {
            "OrderID": 2,
            "Pair": "BTC/USD",
            "Side": "SELL",
            "Status": "FILLED",
            "FilledQuantity": 0.01008,
            "FilledAverPrice": 65000.0,
            "FinishTimestamp": 1728001000000,
        },
        # CAKE: bought 2000 @ 2.0, bought 1011.12 @ 2.5 -> total 3011.12 @ VWAP
        {
            "OrderID": 3,
            "Pair": "CAKE/USD",
            "Side": "BUY",
            "Status": "FILLED",
            "FilledQuantity": 2000.0,
            "FilledAverPrice": 2.0,
            "FinishTimestamp": 1728002000000,
        },
        {
            "OrderID": 4,
            "Pair": "CAKE/USD",
            "Side": "BUY",
            "Status": "FILLED",
            "FilledQuantity": 1011.12,
            "FilledAverPrice": 2.5,
            "FinishTimestamp": 1728003000000,
        },
    ]

    entries = {}
    required = {}
    recovered = recover_from_exchange_orders(orders, wallet, pairs, entries, required)

    assert sorted(recovered) == ["BTC", "CAKE"]
    assert entries["BTC"]["remaining_quantity"] == pytest.approx(0.08992)
    assert entries["BTC"]["entry_price"] == pytest.approx(60000.0)
    expected_cake_basis = (2000.0 * 2.0 + 1011.12 * 2.5) / 3011.12
    assert entries["CAKE"]["remaining_quantity"] == pytest.approx(3011.12)
    assert entries["CAKE"]["entry_price"] == pytest.approx(expected_cake_basis)


def test_four_holdings_unavailable_history_blocks_new_entries_and_never_autosells(tmp_path):
    """When order history is missing, holdings are marked unresolved and new entries blocked."""
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
    original = {
        "pool_cash": {"crypto": 67812.17, "equity": 0.0},
        "entries": {},
        "peak": 100597.78934632,
    }
    ledger.write_text(json.dumps(original), encoding="utf-8")
    before = ledger.read_bytes()

    bot = object.__new__(Bot)
    bot.cfg_path = cfg_path
    bot.cfg = {}
    bot.dry = True
    bot.state_path = ledger
    bot.state = json.loads(ledger.read_text(encoding="utf-8"))
    bot.pairs = {
        "BTC/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 5, "MiniOrder": 5},
        "CAKE/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 2, "MiniOrder": 5},
        "EDEN/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 1, "MiniOrder": 5},
        "FIL/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 2, "MiniOrder": 5},
    }
    bot.freq = 30
    bot.api = SimpleNamespace(
        ticker=lambda: {
            "BTC/USD": {"LastPrice": 60000, "MaxBid": 59990, "MinAsk": 60010},
            "CAKE/USD": {"LastPrice": 2.0, "MaxBid": 1.99, "MinAsk": 2.01},
            "EDEN/USD": {"LastPrice": 0.08, "MaxBid": 0.079, "MinAsk": 0.081},
            "FIL/USD": {"LastPrice": 3.5, "MaxBid": 3.49, "MinAsk": 3.51},
        },
        balance=lambda: {
            "USD": {"Free": 67812.17, "Lock": 0},
            "BTC": {"Free": 0.08992, "Lock": 0},
            "CAKE": {"Free": 3011.12, "Lock": 0},
            "EDEN": {"Free": 111203.6, "Lock": 0},
            "FIL": {"Free": 5786.78, "Lock": 0},
        },
        query_order=lambda *args, **kwargs: {"Success": True, "OrderMatched": []},
        journal=None,
        place_order=lambda *args: pytest.fail("unverified holdings must not trigger market sales"),
    )
    bot.signals = lambda: (_ for _ in ()).throw(RuntimeError("feed offline"))

    bot.cycle()

    for coin in ("BTC", "CAKE", "EDEN", "FIL"):
        assert bot.state["reconciliation_required"][coin]["reason"] == "missing_verified_entry_cost_basis"
    assert "unreconciled exchange holdings" in bot._entry_freeze_reasons[0]
    assert ledger.read_bytes() == before


def test_four_holdings_manual_reconciliation_and_restart_persistence(tmp_path):
    """Manual reconciliation survives process restart and disables time exit for attested unknown timestamps."""
    ledger_path = tmp_path / "state" / "ledger.json"
    ledger_path.parent.mkdir()
    original = {
        "pool_cash": {"crypto": 67812.17, "equity": 0.0},
        "entries": {},
        "peak": 100597.78934632,
    }
    ledger_path.write_text(json.dumps(original), encoding="utf-8")

    manual_path = tmp_path / "state" / "reconciliation_manual.json"
    manual_path.write_text(
        json.dumps(
            {
                "positions": {
                    "BTC": {
                        "record_id": "ec2-btc-20261014",
                        "operator": "operator",
                        "source": "exchange order 101",
                        "entry_price": 62500.0,
                        "remaining_quantity": 0.08992,
                        "entry_ts": "2026-10-14T08:30:00Z",
                    },
                    "CAKE": {
                        "record_id": "ec2-cake-20261014",
                        "operator": "operator",
                        "source": "exchange order 102",
                        "entry_price": 2.15,
                        "remaining_quantity": 3011.12,
                        "entry_ts": "2026-10-14T08:35:00Z",
                    },
                    "EDEN": {
                        "record_id": "ec2-eden-20261014",
                        "operator": "operator",
                        "source": "exchange order 103; fill time unavailable",
                        "entry_price": 0.085,
                        "remaining_quantity": 111203.6,
                        "entry_ts": None,
                        "entry_timestamp_unknown": True,
                        "time_exit_policy": UNKNOWN_TIME_POLICY,
                    },
                    "FIL": {
                        "record_id": "ec2-fil-20261014",
                        "operator": "operator",
                        "source": "exchange order 104",
                        "entry_price": 3.80,
                        "remaining_quantity": 5786.78,
                        "entry_ts": "2026-10-14T08:40:00Z",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    pairs = {
        "BTC/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 5, "MiniOrder": 5},
        "CAKE/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 2, "MiniOrder": 5},
        "EDEN/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 1, "MiniOrder": 5},
        "FIL/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 2, "MiniOrder": 5},
    }
    wallet = {
        "USD": {"Free": 67812.17, "Lock": 0},
        "BTC": {"Free": 0.08992, "Lock": 0},
        "CAKE": {"Free": 3011.12, "Lock": 0},
        "EDEN": {"Free": 111203.6, "Lock": 0},
        "FIL": {"Free": 5786.78, "Lock": 0},
    }

    # Step 1: Reconcile and save state
    state = json.loads(ledger_path.read_text(encoding="utf-8"))
    entries = state.setdefault("entries", {})
    audit = state.setdefault("reconciliation_audit", [])
    required = state.setdefault("reconciliation_required", {})

    applied = apply_manual_reconciliation(
        json.loads(manual_path.read_text(encoding="utf-8")),
        wallet,
        pairs,
        entries,
        required,
        audit,
    )
    assert sorted(applied) == ["BTC", "CAKE", "EDEN", "FIL"]
    assert len(audit) == 4

    held, unresolved = reconcile_crypto_holdings(wallet, pairs, entries, required)
    assert unresolved == []
    assert required == {}

    # Persist reconciled state to ledger
    ledger_path.write_text(json.dumps(state, indent=1), encoding="utf-8")

    # Step 2: Restart bot with the saved ledger
    restarted_state = json.loads(ledger_path.read_text(encoding="utf-8"))
    restarted_entries = restarted_state["entries"]
    restarted_required = restarted_state.get("reconciliation_required", {})

    restarted_held, restarted_unresolved = reconcile_crypto_holdings(
        wallet, pairs, restarted_entries, restarted_required
    )
    assert restarted_unresolved == []
    assert restarted_required == {}
    assert restarted_entries["EDEN"]["entry_time_status"] == "unknown_operator_attested"
    assert restarted_entries["EDEN"]["time_exit_policy"] == UNKNOWN_TIME_POLICY
    assert restarted_entries["BTC"]["entry_time_status"] == "verified"


def test_four_holdings_quantity_mismatch_blocks_and_preserves_reconciliation_flag():
    """Manual reconciliation rejects quantity mismatch and preserves entry freeze."""
    wallet = {"BTC": {"Free": 0.08992, "Lock": 0}}
    pairs = {"BTC/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 5}}
    entries = {}
    required = {"BTC": {"reason": "missing_verified_entry_cost_basis"}}
    audit = []
    document = {
        "positions": {
            "BTC": {
                "record_id": "test-mismatch",
                "operator": "reviewer",
                "source": "incorrect source",
                "entry_price": 62500.0,
                "remaining_quantity": 0.05,
                "entry_ts": "2026-10-14T08:30:00Z",
            }
        }
    }

    with pytest.raises(ValueError, match="does not match exchange quantity"):
        apply_manual_reconciliation(document, wallet, pairs, entries, required, audit)

    assert "BTC" not in entries
    assert required["BTC"]["reason"] == "missing_verified_entry_cost_basis"
    assert audit == []


def test_reconcile_cli_command(tmp_path, monkeypatch, capsys):
    from rq.cli import main
    class MockClient:
        journal = None
        key = "test-key"
        def sync_clock(self): return 0
        def exchange_info(self):
            return {
                "TradePairs": {
                    "BTC/USD": {"AssetType": "crypto", "CanTrade": True, "AmountPrecision": 5},
                }
            }
        def balance(self):
            return {"USD": {"Free": 1000, "Lock": 0}, "BTC": {"Free": 0.08992, "Lock": 0}}
        def query_order(self, *args, **kwargs):
            return {
                "Success": True,
                "OrderMatched": [
                    {
                        "OrderID": 999,
                        "Pair": "BTC/USD",
                        "Side": "BUY",
                        "Status": "FILLED",
                        "FilledQuantity": 0.08992,
                        "FilledAverPrice": 62500.0,
                        "FinishTimestamp": 1728000000000,
                    }
                ],
            }

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "live.yaml").write_text("crypto_weight: 1.0\ntimeframes: ['30m']\n", encoding="utf-8")
    monkeypatch.setattr("rq.roostoo.client.RoostooClient", MockClient)

    # Dry-run
    main(["reconcile"])
    out = capsys.readouterr().out
    assert "BTC" in out
    assert "RESOLVED" in out
    assert "$62500.0000" in out
    assert "Dry-run" in out
    assert not (tmp_path / "state" / "ledger.json").exists()

    # Confirm
    main(["reconcile", "--confirm"])
    out2 = capsys.readouterr().out
    assert "[Confirmed]" in out2
    ledger_saved = json.loads((tmp_path / "state" / "ledger.json").read_text(encoding="utf-8"))
    assert ledger_saved["entries"]["BTC"]["entry_price"] == 62500.0
    assert ledger_saved["entries"]["BTC"]["remaining_quantity"] == 0.08992
