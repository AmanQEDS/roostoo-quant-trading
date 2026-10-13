import json

from tracker.daily_tracker import generate


def test_tracker_reports_mfe_mae_and_giveback_from_reason_coded_intents():
    buy = {
        "symbol": "BTC/USD", "side": "BUY", "qty": 2,
        "reason": "BUY_NEW_ENTRY", "entry_price": None,
        "peak_price_since_entry": None, "mfe": None, "mae": None,
    }
    sell = {
        "symbol": "BTC/USD", "side": "SELL", "qty": 2,
        "reason": "SELL_SIGNAL_EXIT", "entry_price": 100,
        "peak_price_since_entry": 106, "mfe": 12, "mae": -4,
    }
    lines = [
        f"2026-10-12 10:00:00,000 INFO ORDER_INTENT {json.dumps(buy)}",
        "2026-10-12 10:00:01,000 INFO filled BUY 2 BTC/USD @ 100 fee=0.20",
        f"2026-10-12 11:00:00,000 INFO ORDER_INTENT {json.dumps(sell)}",
        "2026-10-12 11:00:01,000 INFO filled SELL 2 BTC/USD @ 105 fee=0.21",
    ]

    report = generate(lines, "2026-10-12")

    assert "| BTC/USD | 12.00 | -4.00 | 10.00 | 2.00 |" in report


def test_tracker_reconstructs_position_opened_before_report_date():
    sell = {
        "symbol": "ETH/USD", "side": "SELL", "qty": 3,
        "reason": "SELL_SIGNAL_EXIT", "entry_price": 200,
        "peak_price_since_entry": 230, "mfe": 90, "mae": -15,
    }
    lines = [
        f"2026-10-12 11:00:00,000 INFO ORDER_INTENT {json.dumps(sell)}",
        "2026-10-12 11:00:01,000 INFO filled SELL 3 ETH/USD @ 190 fee=0.57",
    ]

    report = generate(lines, "2026-10-12")

    assert "| ETH/USD | 90.00 | -15.00 | -30.00 | 120.00 |" in report
