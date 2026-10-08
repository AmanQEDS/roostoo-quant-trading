from __future__ import annotations

import argparse
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


FILL_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO "
    r"filled (?P<side>BUY|SELL) (?P<qty>[\d.]+) (?P<pair>[A-Z0-9]+/USD) "
    r"@ (?P<price>[\d.]+) fee=(?P<fee>[\d.]+)"
)

EQUITY_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO "
    r"equity (?P<equity>[\d.]+) peak (?P<peak>[\d.]+) "
    r"(?:drawdown|dd) (?P<dd>[-\d.]+)%.*?"
    r"(?:ladder_mult (?P<mult>[\d.]+)|entry scale x(?P<scale>[\d.]+))"
)

SIGNAL_RE = re.compile(
    r"signal bar .*?: (?P<long>\d+) long / (?P<short>\d+) short"
)

DRY_RE = re.compile(
    r"\[dry-run\] (?P<side>BUY|SELL) (?P<qty>[\d.]+) (?P<pair>[A-Z0-9]+/USD)"
)

UNIVERSE_RE = re.compile(r"selected crypto: (?P<universe>\[.*\])")

WARNING_RE = re.compile(r"\d+ WARNING ")
ERROR_RE = re.compile(r"\d+ ERROR ")


def parse_args():
    p = argparse.ArgumentParser(description="Generate a daily Roostoo trading report.")
    p.add_argument("--date", help="UTC date YYYY-MM-DD; defaults to latest log date")
    p.add_argument("--log", default="logs/bot.log")
    p.add_argument("--out", default="tracker/reports")
    return p.parse_args()


def load_lines(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def latest_log_date(lines):
    dates = []
    for line in lines:
        m = re.match(r"(\d{4}-\d{2}-\d{2}) ", line)
        if m:
            dates.append(m.group(1))
    if not dates:
        raise ValueError("No dated log entries found.")
    return max(dates)


def money(x):
    return f"{x:,.2f}"


def pct(x):
    return f"{x:+.2f}%"


def generate(lines, date):
    rows = [x for x in lines if x.startswith(date + " ")]

    if not rows:
        raise ValueError(f"No log entries found for {date}.")

    fills = []
    dry_orders = []
    equities = []
    signals = []
    warnings = 0
    errors = 0
    universe = None

    for line in rows:
        m = FILL_RE.search(line)
        if m:
            fills.append({
                "side": m.group("side"),
                "qty": float(m.group("qty")),
                "pair": m.group("pair"),
                "price": float(m.group("price")),
                "fee": float(m.group("fee")),
            })

        m = DRY_RE.search(line)
        if m:
            dry_orders.append({
                "side": m.group("side"),
                "qty": float(m.group("qty")),
                "pair": m.group("pair"),
            })

        m = EQUITY_RE.search(line)
        if m:
            mult = m.group("mult") or m.group("scale") or "1.00"
            equities.append({
                "equity": float(m.group("equity")),
                "peak": float(m.group("peak")),
                "dd": float(m.group("dd")),
                "mult": float(mult),
            })

        m = SIGNAL_RE.search(line)
        if m:
            signals.append((int(m.group("long")), int(m.group("short"))))

        if WARNING_RE.search(line):
            warnings += 1
        if ERROR_RE.search(line):
            errors += 1

        m = UNIVERSE_RE.search(line)
        if m:
            universe = m.group("universe")

    total_fees = sum(x["fee"] for x in fills)
    buys = sum(x["side"] == "BUY" for x in fills)
    sells = sum(x["side"] == "SELL" for x in fills)
    turnover = sum(x["qty"] * x["price"] for x in fills)

    start_equity = equities[0]["equity"] if equities else None
    end_equity = equities[-1]["equity"] if equities else None
    peak = max((x["peak"] for x in equities), default=None)
    dd = equities[-1]["dd"] if equities else None
    mult = equities[-1]["mult"] if equities else None

    intraday_return = None
    if start_equity and end_equity:
        intraday_return = (end_equity / start_equity - 1) * 100

    lines_out = [
        f"# Daily Trading Report - {date}",
        "",
        "> Generated from `logs/bot.log`. No live API/account data is inferred.",
        "",
        "## Portfolio",
        "",
        f"- First observed equity: **{money(start_equity)}**" if start_equity is not None else "- First observed equity: **N/A**",
        f"- Last observed equity: **{money(end_equity)}**" if end_equity is not None else "- Last observed equity: **N/A**",
        f"- Intraday change: **{pct(intraday_return)}**" if intraday_return is not None else "- Intraday change: **N/A**",
        f"- Peak equity observed: **{money(peak)}**" if peak is not None else "- Peak equity observed: **N/A**",
        f"- Current drawdown: **{dd:.2f}%**" if dd is not None else "- Current drawdown: **N/A**",
        f"- Risk multiplier: **{mult:.2f}x**" if mult is not None else "- Risk multiplier: **N/A**",
        "",
        "## Trading Activity",
        "",
        f"- Filled BUY orders: **{buys}**",
        f"- Filled SELL orders: **{sells}**",
        f"- Total fills: **{len(fills)}**",
        f"- Fees: **{money(total_fees)}**",
        f"- Filled turnover: **{money(turnover)}**",
        f"- Dry-run orders: **{len(dry_orders)}**",
        "",
        "## Signals",
        "",
        f"- Signal observations: **{len(signals)}**",
        f"- Latest long signals: **{signals[-1][0]}**" if signals else "- Latest long signals: **N/A**",
        f"- Latest short signals: **{signals[-1][1]}**" if signals else "- Latest short signals: **N/A**",
        "",
        "## Filled Orders",
        "",
    ]

    if fills:
        lines_out += [
            "| Side | Pair | Quantity | Price | Fee |",
            "|---|---|---:|---:|---:|",
        ]
        for x in fills:
            lines_out.append(
                f"| {x['side']} | {x['pair']} | {x['qty']:,.6g} | "
                f"{x['price']:,.6g} | {x['fee']:,.6f} |"
            )
    else:
        lines_out.append("No filled orders recorded.")

    lines_out += [
        "",
        "## Universe",
        "",
        universe if universe else "No selected-universe snapshot recorded.",
        "",
        "## Operational Health",
        "",
        f"- Warnings: **{warnings}**",
        f"- Errors: **{errors}**",
        "",
        "## Strategy",
        "",
        "- Timeframe: **30m**",
        "- Strategy: **EMA(50/200) + Donchian(24)**",
        "- Direction: **Long only**",
        "- Crypto allocation: **100%**",
        "- Maximum positions: **5**",
        "- Position fraction: **10%**",
        "",
    ]

    if dry_orders:
        lines_out += [
            "## Dry-Run Activity",
            "",
            f"**{len(dry_orders)}** dry-run orders were logged. These are not counted as executed trades.",
            "",
        ]

    return "\n".join(lines_out) + "\n"


def main():
    args = parse_args()
    log_path = Path(args.log)
    lines = load_lines(log_path)

    date = args.date or latest_log_date(lines)
    report = generate(lines, date)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date}.md"
    out_path.write_text(report, encoding="utf-8")

    print(f"REPORT: {out_path}")
    print(f"DATE: {date}")


if __name__ == "__main__":
    main()
