"""Bulk crypto history from data.binance.vision (Roostoo prices track Binance spot).

We pull 5m klines and aggregate to 10m / 30m ourselves (Binance has no 10m interval).
Kline columns include taker-buy volume, which gives a *true* buy/sell imbalance proxy
for the supply/demand family.

Timestamp gotcha: from 2025-01-01 Binance Vision spot files use MICROsecond open_time.
We normalise by magnitude so both eras load correctly.
"""
from __future__ import annotations
import io, zipfile, datetime as dt
from pathlib import Path
import pandas as pd
import requests

BASE = "https://data.binance.vision/data/spot"
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
        "n_trades", "taker_buy_base", "taker_buy_quote", "ignore"]


def _to_ms(x: pd.Series) -> pd.Series:
    x = x.astype("int64")
    return x.where(x < 10**14, x // 1000)           # µs -> ms


def _read_zip(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        df = pd.read_csv(z.open(z.namelist()[0]), header=None, names=COLS)
    if df.empty:
        return df
    if not str(df.iloc[0, 0]).isdigit():            # header row in some archives
        df = df.iloc[1:]
    df["open_time"] = pd.to_datetime(_to_ms(df["open_time"]), unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "n_trades"]:
        df[c] = pd.to_numeric(df[c])
    return df[["open_time", "open", "high", "low", "close", "volume", "quote_volume", "n_trades", "taker_buy_base"]]


def _get(url: str) -> bytes | None:
    r = requests.get(url, timeout=60)
    return r.content if r.status_code == 200 else None


def download_symbol(symbol: str, start: str, end: str | None = None, interval: str = "5m",
                    out_dir: str | Path = "data/raw/crypto") -> Path:
    """Monthly zips for complete months, daily zips for the current month."""
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    path = out / f"{symbol}_{interval}.parquet"
    s = pd.Timestamp(start); e = pd.Timestamp(end) if end else pd.Timestamp.utcnow().tz_localize(None)
    frames, cur = [], pd.Timestamp(s.year, s.month, 1)
    while cur <= e:
        month_end = cur + pd.offsets.MonthEnd(0)
        if month_end < pd.Timestamp.utcnow().tz_localize(None).normalize().replace(day=1):
            b = _get(f"{BASE}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{cur:%Y-%m}.zip")
            if b:
                frames.append(_read_zip(b))
        else:                                       # current (incomplete) month -> daily files
            for d in pd.date_range(cur, min(e, pd.Timestamp.utcnow().tz_localize(None).normalize() - pd.Timedelta(days=1))):
                b = _get(f"{BASE}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{d:%Y-%m-%d}.zip")
                if b:
                    frames.append(_read_zip(b))
        cur = cur + pd.offsets.MonthBegin(1)
    if not frames:
        raise RuntimeError(f"no data for {symbol} (not listed on Binance spot?)")
    df = pd.concat(frames).drop_duplicates("open_time").sort_values("open_time").set_index("open_time")
    df.to_parquet(path)
    return path


def load_symbol(symbol: str, interval: str = "5m", root: str | Path = "data/raw/crypto") -> pd.DataFrame:
    return pd.read_parquet(Path(root) / f"{symbol}_{interval}.parquet")
