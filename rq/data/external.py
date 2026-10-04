"""External indicators with conservative AVAILABILITY timestamps.

Rule: a value may only be used from the first moment it could really have been known.
  * Fear & Greed (alternative.me): the daily value is stamped 00:00 UTC of day d but is a
    summary of d's data -> we make it usable from d+1 00:00 UTC (1-day lag).
  * VIX (^VIX daily close, ~21:00 UTC) -> usable from d+1 00:00 UTC.
  * DVOL (Deribit BTC/ETH implied-vol index, hourly) -> usable at the hour's CLOSE.
The returned Series are indexed by availability time; consumers use `align_asof`.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import requests


def fear_greed(cache: str | Path = "data/raw/external") -> pd.Series:
    p = Path(cache); p.mkdir(parents=True, exist_ok=True)
    r = requests.get("https://api.alternative.me/fng/?limit=0&format=json", timeout=30).json()["data"]
    s = pd.Series({pd.to_datetime(int(x["timestamp"]), unit="s", utc=True): float(x["value"]) for x in r}).sort_index()
    s.index = s.index.normalize() + pd.Timedelta(days=1)       # available next day 00:00 UTC
    s.name = "fng"
    s.to_frame().to_parquet(p / "fng.parquet")
    return s


def vix(start: str = "2022-06-01", cache: str | Path = "data/raw/external") -> pd.Series:
    import yfinance as yf
    p = Path(cache); p.mkdir(parents=True, exist_ok=True)
    df = yf.download("^VIX", start=start, interval="1d", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    s = df["Close"].copy()
    idx = pd.DatetimeIndex(s.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    s.index = idx.normalize() + pd.Timedelta(days=1)
    s.name = "vix"
    s.to_frame().to_parquet(p / "vix.parquet")
    return s


def dvol(currency: str = "BTC", start: str = "2022-06-01", cache: str | Path = "data/raw/external") -> pd.Series:
    """Deribit volatility index (the crypto 'VIX'), hourly, public endpoint."""
    p = Path(cache); p.mkdir(parents=True, exist_ok=True)
    end_ms = int(pd.Timestamp.utcnow().timestamp() * 1000)
    cur = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    rows = []
    while cur < end_ms:
        r = requests.get("https://www.deribit.com/api/v2/public/get_volatility_index_data",
                         params={"currency": currency, "start_timestamp": cur, "end_timestamp": end_ms,
                                 "resolution": 3600}, timeout=30).json()["result"]
        data = r["data"]
        if not data:
            break
        rows += data
        cont = r.get("continuation")
        if not cont:
            break
        end_ms = int(cont)
    df = pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c"]).drop_duplicates("ts").sort_values("ts")
    s = pd.Series(df["c"].values, index=pd.to_datetime(df["ts"], unit="ms", utc=True) + pd.Timedelta(hours=1), name=f"dvol_{currency.lower()}")
    s.to_frame().to_parquet(p / f"dvol_{currency.lower()}.parquet")
    return s


def load_external(name: str, root: str | Path = "data/raw/external") -> pd.Series:
    return pd.read_parquet(Path(root) / f"{name}.parquet").iloc[:, 0]


def align_asof(series: pd.Series, grid: pd.DatetimeIndex) -> pd.Series:
    """Value known at each grid timestamp = last observation with availability <= t."""
    s = series.sort_index()
    out = s.reindex(s.index.union(grid)).ffill().reindex(grid)
    return out
