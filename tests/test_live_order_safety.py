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

    bot.pairs = {"BTC/USD": {"AssetType": "crypto"}}
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
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0}}, "test"
    )

    assert result is False
    assert bot.state["pending_order"]["status"] == "uncertain"
    saved = json.loads(bot.state_path.read_text(encoding="utf-8"))
    assert saved["pending_order"]["status"] == "uncertain"

    def must_not_submit(*args):
        pytest.fail("A second order was submitted while reconciliation is pending")

    bot.api.place_order = must_not_submit
    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0}}, "test"
    ) is False


def test_empty_fill_response_keeps_pending_marker(tmp_path):
    bot = make_bot(
        tmp_path,
        response={
            "FilledQuantity": 0,
            "FilledAverPrice": 0,
            "CommissionChargeValue": 0,
        },
    )

    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0}}, "test"
    ) is False
    assert bot.state["pending_order"]["status"] == "uncertain"


def test_partial_fill_keeps_marker_and_records_filled_quantity(tmp_path):
    bot = make_bot(
        tmp_path,
        response={
            "FilledQuantity": 0.4,
            "FilledAverPrice": 100.0,
            "CommissionChargeValue": 0.1,
        },
    )

    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0}}, "test"
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
            "FilledQuantity": 1.0,
            "FilledAverPrice": 100.0,
            "CommissionChargeValue": 0.1,
        },
    )

    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0}}, "test"
    ) is True
    assert "pending_order" not in bot.state
    assert bot.state["entries"]["BTC"]["entry_price"] == pytest.approx(100.0)

    saved = json.loads(bot.state_path.read_text(encoding="utf-8"))
    assert "pending_order" not in saved


def test_existing_pending_marker_blocks_without_api_call(tmp_path):
    bot = make_bot(
        tmp_path,
        existing_pending={"status": "uncertain", "symbol": "BTC/USD"},
    )

    def must_not_submit(*args):
        pytest.fail("API called despite an existing pending marker")

    bot.api.place_order = must_not_submit

    assert bot._order(
        "BTC", "BUY", 1.0, {"BTC/USD": {"LastPrice": 100.0}}, "test"
    ) is False
    assert bot.state["pending_order"]["status"] == "uncertain"


def test_save_creates_parent_and_replaces_ledger_atomically(tmp_path):
    bot = make_bot(tmp_path)
    bot.state["sample"] = "persisted"

    bot.save()

    assert json.loads(bot.state_path.read_text(encoding="utf-8"))["sample"] == "persisted"
    assert not bot.state_path.with_suffix(".json.tmp").exists()
