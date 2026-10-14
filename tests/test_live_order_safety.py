import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from rq.live.bot import Bot


def make_bot(tmp_path, response=None, error=None, existing_pending=None):
    bot = object.__new__(Bot)
    bot.dry = False
    bot.state_path = tmp_path / "state" / "ledger.json"
    bot.state = {
        "pool_cash": {"crypto": 10000.0, "equity": 0.0},
        "entries": {},
    }
    if existing_pending is not None:
        bot.state["pending_order"] = existing_pending

    bot.pairs = {
        "BTC/USD": {
            "AssetType": "crypto",
            "CanTrade": True,
            "AmountPrecision": 8,
            "MiniOrder": 5.0,
        }
    }
    bot.cfg = {"pos_frac": 1.0}
    bot._held_quantities = {}
    bot._wallet_free_quantities = {}
    bot.order_context = {
        "equity": None,
        "peak_equity": None,
        "drawdown": None,
        "dd_multiplier": None,
    }
    bot.current_signal_bar = None
    bot.api = SimpleNamespace()
    bot.api.place_order = lambda *args: (
        (_ for _ in ()).throw(error)
        if error is not None
        else response
    )
    return bot


def test_timeout_persists_uncertain_marker_and_blocks_next_order(tmp_path):
    bot = make_bot(tmp_path, error=TimeoutError("simulated timeout"))

    result = bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0, "MinAsk": 100.0}}, "test"
    )

    assert result is False
    assert bot.state["pending_order"]["status"] == "uncertain"
    saved = json.loads(bot.state_path.read_text(encoding="utf-8"))
    assert saved["pending_order"]["status"] == "uncertain"

    def must_not_submit(*args):
        pytest.fail("A second order was submitted while reconciliation is pending")

    bot.api.place_order = must_not_submit
    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0, "MinAsk": 100.0}}, "test"
    ) is False


def test_unknown_submission_without_order_id_stays_blocked_for_manual_reconciliation(tmp_path):
    bot = make_bot(tmp_path)
    bot.state["pending_order"] = {
        "status": "uncertain",
        "symbol": "BTC/USD",
        "side": "BUY",
        "quantity": 1.0,
    }
    bot.api.query_order = lambda **kwargs: pytest.fail("cannot safely query without an order id")

    assert bot._recover_pending_order() is False
    assert bot.state["pending_order"]["status"] == "uncertain"


def test_empty_fill_response_keeps_pending_marker(tmp_path):
    bot = make_bot(
        tmp_path,
        response={
            "OrderID": 103,
            "Status": "PENDING",
            "FilledQuantity": 0,
            "FilledAverPrice": 0,
            "CommissionChargeValue": 0,
        },
    )

    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0, "MinAsk": 100.0}}, "test"
    ) is False
    assert bot.state["pending_order"]["status"] == "reconciliation_required"


def test_partial_fill_keeps_marker_and_records_filled_quantity(tmp_path):
    bot = make_bot(
        tmp_path,
        response={
            "OrderID": 102,
            "Status": "PENDING",
            "FilledQuantity": 0.4,
            "FilledAverPrice": 100.0,
            "CommissionChargeValue": 0.1,
        },
    )

    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0, "MinAsk": 100.0}}, "test"
    ) is False
    assert bot.state["pending_order"]["status"] == "partial_fill"
    assert bot.state["pending_order"]["filled_quantity"] == pytest.approx(0.4)
    assert bot.state["entries"]["BTC"]["entry_price"] == pytest.approx(100.0)

    saved = json.loads(bot.state_path.read_text(encoding="utf-8"))
    assert saved["pending_order"]["status"] == "partial_fill"


def test_full_fill_clears_marker_after_recording_fill(tmp_path):
    bot = make_bot(
        tmp_path,
        response={
            "OrderID": 101,
            "Status": "FILLED",
            "FilledQuantity": 1.0,
            "FilledAverPrice": 100.0,
            "CommissionChargeValue": 0.1,
        },
    )

    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0, "MinAsk": 100.0}}, "test"
    ) is True
    assert "pending_order" not in bot.state
    assert bot.state["entries"]["BTC"]["entry_price"] == pytest.approx(100.0)

    saved = json.loads(bot.state_path.read_text(encoding="utf-8"))
    assert "pending_order" not in saved


def test_confirmed_fill_prevents_duplicate_entry_from_same_bot(tmp_path):
    bot = make_bot(
        tmp_path,
        response={
            "OrderID": 209,
            "Status": "FILLED",
            "FilledQuantity": 1.0,
            "FilledAverPrice": 100.0,
            "CommissionChargeValue": 0.1,
        },
    )
    calls = []
    original_place = bot.api.place_order

    def counted_place(*args):
        calls.append(1)
        return original_place(*args)

    bot.api.place_order = counted_place
    ticker = {"BTC/USD": {"MinAsk": 100.0, "MaxBid": 99.0, "LastPrice": 100.0}}

    assert bot._order("BTC", "BUY", 1.0, ticker, "first") is True
    assert bot._order("BTC", "BUY", 1.0, ticker, "duplicate") is False
    assert len(calls) == 1


def test_partial_exit_preserves_residual_basis_and_updates_quantity(tmp_path):
    bot = make_bot(
        tmp_path,
        response={
            "OrderID": 210,
            "Status": "FILLED",
            "FilledQuantity": 0.5,
            "FilledAverPrice": 90.0,
            "CommissionChargeValue": 0.045,
        },
    )
    bot.state["entries"]["BTC"] = {
        "entry_price": 80.0,
        "entry_quantity": 1.0,
        "remaining_quantity": 1.0,
        "entry_ts": "2026-10-14T10:00:00Z",
    }
    bot._held_quantities["BTC"] = 1.0
    bot._wallet_free_quantities["BTC"] = 0.5
    ticker = {"BTC/USD": {"MaxBid": 90.0, "LastPrice": 90.0}}

    assert bot._order("BTC", "SELL", 0.5, ticker, "partial-exit") is True
    assert bot.state["entries"]["BTC"]["entry_price"] == pytest.approx(80.0)
    assert bot.state["entries"]["BTC"]["remaining_quantity"] == pytest.approx(0.5)
    assert bot._held_quantities["BTC"] == pytest.approx(0.5)
    assert bot._wallet_free_quantities["BTC"] == pytest.approx(0)


def test_existing_pending_marker_blocks_without_api_call(tmp_path):
    bot = make_bot(
        tmp_path,
        existing_pending={"status": "uncertain", "symbol": "BTC/USD"},
    )

    def must_not_submit(*args):
        pytest.fail("API called despite an existing pending marker")

    bot.api.place_order = must_not_submit

    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0, "MinAsk": 100.0}}, "test"
    ) is False
    assert bot.state["pending_order"]["status"] == "uncertain"


def test_save_creates_parent_and_replaces_ledger_atomically(tmp_path):
    bot = make_bot(tmp_path)
    bot.state["sample"] = "persisted"

    bot.save()

    assert json.loads(bot.state_path.read_text(encoding="utf-8"))["sample"] == "persisted"
    assert not bot.state_path.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize("status", ["PENDING", "UNKNOWN"])
def test_non_filled_status_never_clears_pending_marker(tmp_path, status):
    bot = make_bot(
        tmp_path,
        response={
            "OrderID": 204,
            "Status": status,
            "FilledQuantity": 1.0,
            "FilledAverPrice": 100.0,
            "CommissionChargeValue": 0.1,
        },
    )

    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0, "MinAsk": 100.0}}, "test"
    ) is False
    assert bot.state["pending_order"]["order_id"] == 204
    assert bot.state["pending_order"]["exchange_status"] == status
    assert bot.state["pending_order"]["status"] == "partial_fill"

    saved = json.loads(bot.state_path.read_text(encoding="utf-8"))
    assert saved["pending_order"]["order_id"] == 204


def test_cancelled_partial_order_is_booked_once_and_releases_submission_lock(tmp_path):
    bot = make_bot(
        tmp_path,
        response={
            "OrderID": 206,
            "Status": "CANCELED",
            "FilledQuantity": 0.4,
            "FilledAverPrice": 100.0,
            "CommissionChargeValue": 0.04,
        },
    )

    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0, "MinAsk": 100.0}}, "test"
    ) is True
    assert "pending_order" not in bot.state
    assert bot.state["entries"]["BTC"]["remaining_quantity"] == pytest.approx(0.4)
    assert bot.state["pool_cash"]["crypto"] == pytest.approx(9959.96)


def test_explicit_rejection_clears_order_intent_without_creating_position(tmp_path):
    bot = make_bot(
        tmp_path,
        response={
            "OrderID": 208,
            "Status": "REJECTED",
            "FilledQuantity": 0,
            "FilledAverPrice": 0,
            "CommissionChargeValue": 0,
        },
    )

    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"MinAsk": 100.0}}, "test"
    ) is False
    assert "pending_order" not in bot.state
    assert "BTC" not in bot.state["entries"]
    assert bot.state["pool_cash"]["crypto"] == pytest.approx(10000.0)


def test_confirmed_full_fill_persists_order_id_in_response_before_clear(tmp_path):
    bot = make_bot(
        tmp_path,
        response={
            "OrderID": 205,
            "Status": "FILLED",
            "FilledQuantity": 1.0,
            "FilledAverPrice": 100.0,
            "CommissionChargeValue": 0.1,
        },
    )

    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0, "MinAsk": 100.0}}, "test"
    ) is True
    assert "pending_order" not in bot.state
    assert bot.state["entries"]["BTC"]["entry_price"] == pytest.approx(100.0)
    assert bot.state["entries"]["BTC"]["entry_quantity"] == pytest.approx(1.0)
    assert bot.state["entries"]["BTC"]["remaining_quantity"] == pytest.approx(1.0)

def test_dry_run_save_never_creates_or_changes_ledger(tmp_path):
    bot = make_bot(tmp_path)
    bot.dry = True
    bot.state_path.parent.mkdir(parents=True, exist_ok=True)
    bot.state_path.write_text('{"sentinel": "preserve"}', encoding="utf-8")
    original = bot.state_path.read_bytes()

    bot.state["sentinel"] = "must-not-persist"
    bot.save()

    assert bot.state_path.read_bytes() == original
    assert not bot.state_path.with_suffix(".json.tmp").exists()


def test_dry_run_save_does_not_create_missing_ledger(tmp_path):
    bot = make_bot(tmp_path)
    bot.dry = True

    bot.save()

    assert not bot.state_path.exists()


def test_dry_run_order_never_submits_or_persists_and_respects_allocation(tmp_path):
    bot = make_bot(tmp_path)
    bot.dry = True
    bot.cfg = {"pos_frac": 0.1}
    bot.state_path.parent.mkdir(parents=True, exist_ok=True)
    bot.state_path.write_text('{"sentinel": "preserve"}', encoding="utf-8")
    original = bot.state_path.read_bytes()
    bot.api.place_order = lambda *args: pytest.fail("dry run submitted a live order")

    result = bot._order(
        "BTC", "BUY", 10.0, {"BTC/USD": {"MinAsk": 100.0}}, "test"
    )

    assert result is True
    assert bot.state["pool_cash"]["crypto"] == pytest.approx(8999.0)
    assert bot.state_path.read_bytes() == original


def test_order_recovery_after_restart_applies_only_incremental_fill(tmp_path):
    initial = make_bot(tmp_path)
    initial.state["pending_order"] = {
        "status": "partial_fill",
        "symbol": "BTC/USD",
        "side": "BUY",
        "quantity": 1.0,
        "order_id": 207,
        "accounted_filled_quantity": 0.4,
        "accounted_notional": 40.0,
        "accounted_fee": 0.04,
    }
    initial.state["entries"]["BTC"] = {
        "entry_price": 100.0,
        "entry_quantity": 0.4,
        "remaining_quantity": 0.4,
        "entry_ts": "2026-10-14T10:00:00Z",
    }
    initial.state["pool_cash"]["crypto"] = 9959.96
    initial.save()

    bot = object.__new__(Bot)
    bot.dry = False
    bot.state_path = initial.state_path
    bot.state = json.loads(bot.state_path.read_text(encoding="utf-8"))
    bot.current_signal_bar = None
    bot.api = SimpleNamespace(query_order=lambda **kwargs: {
        "Success": True,
        "OrderDetail": {
            "OrderID": 207,
            "Status": "FILLED",
            "FilledQuantity": 1.0,
            "FilledAverPrice": 102.0,
            "CommissionChargeValue": 0.102,
        },
    })

    assert bot._recover_pending_order() is True
    assert "pending_order" not in bot.state
    assert bot.state["entries"]["BTC"]["entry_price"] == pytest.approx(102.0)
    assert bot.state["entries"]["BTC"]["remaining_quantity"] == pytest.approx(1.0)
    assert bot.state["pool_cash"]["crypto"] == pytest.approx(9897.898)


def test_recovery_migrates_legacy_partial_fill_accounting_without_double_booking(tmp_path):
    bot = make_bot(tmp_path)
    bot.state["pending_order"] = {
        "status": "partial_fill",
        "symbol": "BTC/USD",
        "side": "BUY",
        "quantity": 1.0,
        "order_id": 211,
        "filled_quantity": 0.4,
        "average_fill_price": 100.0,
        "response": {
            "OrderID": 211,
            "Status": "PENDING",
            "FilledQuantity": 0.4,
            "FilledAverPrice": 100.0,
            "CommissionChargeValue": 0.04,
        },
    }
    bot.state["entries"]["BTC"] = {
        "entry_price": 100.0,
        "entry_ts": "2026-10-14T10:00:00Z",
    }
    bot.state["pool_cash"]["crypto"] = 9959.96
    bot.api.query_order = lambda **kwargs: {
        "Success": True,
        "OrderDetail": {
            "OrderID": 211,
            "Status": "FILLED",
            "FilledQuantity": 1.0,
            "FilledAverPrice": 102.0,
            "CommissionChargeValue": 0.102,
        },
    }

    assert bot._recover_pending_order() is True
    assert bot.state["entries"]["BTC"]["entry_price"] == pytest.approx(102.0)
    assert bot.state["entries"]["BTC"]["remaining_quantity"] == pytest.approx(1.0)
    assert bot.state["pool_cash"]["crypto"] == pytest.approx(9897.898)
