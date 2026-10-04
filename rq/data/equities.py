"""Equity history for the underlyings of Roostoo's stock instruments.

HONEST LIMITS (decide your equity design around these):
  * Roostoo exposes no history at all - only the live /v3/ticker snapshot.
  * Free Yahoo intraday depth: 1h ~730 days, 30m ~60 days, 1m ~7 days.  So 2023-2025
    at 10m/30m is NOT obtainable for free.  Daily goes back for years.
  * The Roostoo instrument may be a tokenized stock whose own history is only weeks/months
    long -> the underlying is a proxy (basis risk, different trading hours).
Bars are indexed by CLOSE time. Daily bars are stamped 21:00 UTC (after the US close in both
DST regimes), so a daily bar is never visible earlier than it really was.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd


def fetch_equity(ticker: str, interval: str = "1h", start: str | None = None, end: str | None = None,
                 out_dir: str | Path = "data/raw/equity") -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(ticker, start=start, end=end, interval=interval, auto_adjust=True, progress=False)
    if df.empty:
        raise RuntimeError(f"no Yahoo data for {ticker} @ {interval}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    if interval == "1d":
        close_time = idx.normalize() + pd.Timedelta(hours=21)
        df.index = close_time
        df.attrs["bar_minutes"] = 1440
    else:
        mins = {"1h": 60, "30m": 30, "15m": 15, "5m": 5}[interval]
        df.index = idx + pd.Timedelta(minutes=mins)
        df.attrs["bar_minutes"] = mins
    df.index.name = "close_time"
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / f"{ticker}_{interval}.parquet")
    return df


def load_equity(ticker: str, interval: str, root: str | Path = "data/raw/equity") -> pd.DataFrame:
    return pd.read_parquet(Path(root) / f"{ticker}_{interval}.parquet")
