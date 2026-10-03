"""Turn raw files + the Roostoo universe snapshot into a Panel and aligned external series."""
from __future__ import annotations
import pickle
from pathlib import Path
import pandas as pd
import yaml
from ..constants import FREQ_MINUTES
from ..data.panel import build_panel
from ..data.external import align_asof, load_external


def get_data(cfg: dict, tf: str, refresh: bool = False):
    cache = Path("data/cache") / f"panel_{tf}.pkl"
    if cache.exists() and not refresh:
        return pickle.load(open(cache, "rb"))
    fm = FREQ_MINUTES[tf]
    uni = pd.read_csv("data/snapshots/universe_latest.csv")
    ov = yaml.safe_load(open("config/universe_overrides.yaml")) or {}
    d = cfg["data"]
    cu = uni[(uni["class"] == "crypto") & uni.can_trade & (uni.spread_bps <= d["max_spread_bps"]) & (uni.usd_vol_24h >= d["min_usd_vol_24h"])]
    crypto, meta = {}, {}
    for _, r in cu.head(d["crypto_top_n"]).iterrows():
        f = Path("data/raw/crypto") / f"{r.coin}USDT_5m.parquet"
        if f.exists():
            crypto[r.coin] = pd.read_parquet(f); meta[r.coin] = {"amt_prec": int(r.amt_prec), "mini_order": float(r.mini_order)}
    equity = {}
    for coin, yt in (ov.get("yahoo_underlying") or {}).items():
        f = Path("data/raw/equity") / f"{yt}_{d['equity_interval']}.parquet"
        if f.exists():
            df = pd.read_parquet(f); df.attrs["bar_minutes"] = 60 if d["equity_interval"] == "1h" else 1440
            equity[coin] = df
            row = uni[uni.coin == coin]
            if len(row): meta[coin] = {"amt_prec": int(row.amt_prec.iloc[0]), "mini_order": float(row.mini_order.iloc[0])}
    if not crypto:
        raise FileNotFoundError("No crypto history found in data/raw/crypto; run `python -m rq.cli discover` and `python -m rq.cli download` first")
    start = d["start"]

    # Use the latest timestamp common to every selected crypto asset.
    # The Panel uses CLOSE-time indexing, so ceil to the requested
    # panel frequency to include the final complete resampled bar.
    latest_common = min(v.index.max() for v in crypto.values())
    end = latest_common.ceil(f"{fm}min")

    print(
        f"[DATA] Common raw endpoint: {latest_common}"
    )
    print(
        f"[DATA] Panel endpoint:      {end}"
    )
    ext_raw = {}
    for k, fn in (("fng", "fng"), ("vix", "vix"), ("dvol", "dvol_btc")):
        try: ext_raw[k] = load_external(fn)
        except Exception: pass
    panel = build_panel(crypto, equity, fm, start, end, meta, cfg["data"].get("equity_session", True))
    ext = {k: align_asof(v, panel.index) for k, v in ext_raw.items()}
    cache.parent.mkdir(parents=True, exist_ok=True)
    pickle.dump((panel, ext), open(cache, "wb"))
    return panel, ext
