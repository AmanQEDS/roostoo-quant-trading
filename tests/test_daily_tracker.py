from pathlib import Path
from tracker.daily_tracker import generate


def test_daily_tracker_parses_fills_and_equity():
    lines = [
        "2026-10-03 10:00:00,000 INFO filled BUY 2 BTC/USD @ 100 fee=0.20",
        "2026-10-03 10:01:00,000 INFO filled SELL 2 BTC/USD @ 105 fee=0.21",
        "2026-10-03 10:02:00,000 INFO equity 1000 peak 1010 dd 1.0% ladder_mult 1.00",
        "2026-10-03 10:03:00,000 INFO signal bar 2026-10-03 10:00:00+00:00: 5 long / 0 short",
        "2026-10-03 10:04:00,000 WARNING feed skip BTC: test",
    ]

    report = generate(lines, "2026-10-03")

    assert "Filled BUY orders: **1**" in report
    assert "Filled SELL orders: **1**" in report
    assert "Total fills: **2**" in report
    assert "Fees: **0.41**" in report
    assert "Current drawdown: **1.00%**" in report
    assert "Warnings: **1**" in report
    assert "Errors: **0**" in report
