"""Data download + QA commands (need internet)."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import yaml


def run_download(cfg: dict, equity: bool = True):
    from .data import binance_vision as bv, equities, external
    uni = pd.read_csv("data/snapshots/universe_latest.csv")
    d = cfg["data"]
    cu = uni[(uni["class"] == "crypto") & uni.can_trade & (uni.spread_bps <= d["max_spread_bps"]) & (uni.usd_vol_24h >= d["min_usd_vol_24h"])].head(d["crypto_top_n"])
    for coin in cu.coin:
        try:
            p = bv.download_symbol(f"{coin}USDT", d["start"]); print("ok ", p)
        except Exception as e:
            print("skip", coin, e)
    if equity:
        ov = yaml.safe_load(open("config/universe_overrides.yaml")) or {}
        for coin, yt in (ov.get("yahoo_underlying") or {}).items():
            try: equities.fetch_equity(yt, d["equity_interval"], start=(pd.Timestamp.utcnow() - pd.Timedelta(days=725)).strftime("%Y-%m-%d")); print("ok ", yt)
            except Exception as e: print("skip", yt, e)
    for name, fn in (("fng", external.fear_greed), ("vix", external.vix), ("dvol_btc", lambda: external.dvol("BTC"))):
        try: fn(); print("ok ", name)
        except Exception as e: print("skip", name, e)


def check_data():
    """QA: duplicates, monotonic index, gaps, absurd candles, zero-volume share."""
    rows = []
    for f in sorted(Path("data/raw/crypto").glob("*_5m.parquet")):
        df = pd.read_parquet(f)
        gaps = df.index.to_series().diff().dt.total_seconds().div(300).sub(1)
        r = df.close.pct_change().abs()
        rows.append({"file": f.name, "rows": len(df), "start": df.index[0], "end": df.index[-1], "dup": int(df.index.duplicated().sum()),
                     "monotonic": df.index.is_monotonic_increasing, "missing_5m_bars": int(gaps[gaps > 0].sum()),
                     "max_|ret|": round(r.max(), 3), "zero_vol_%": round((df.volume == 0).mean() * 100, 2)})
    print(pd.DataFrame(rows).to_string(index=False))
