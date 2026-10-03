"""Step 1 of the brief: *verify* the tradable universe, never assume it.

`discover()` calls the public endpoints (no keys needed) and writes a snapshot of
exchangeInfo + ticker.  `classify()` buckets each pair; anything the heuristics
cannot place is reported as `unknown` for manual review (config/universe_overrides.yaml).
"""
from __future__ import annotations
import json, re, time
from pathlib import Path
import pandas as pd
import yaml
from .client import RoostooClient

STABLES = {"USDT", "USDC", "FDUSD", "TUSD", "DAI", "USDP", "BUSD", "USD1", "PYUSD", "RLUSD", "EUR", "EURI"}
GOLD = {"PAXG", "XAUT"}
EQUITY_HINTS = re.compile(r"(tokenized|xstock|stock|equity|\betf\b|shares)", re.I)


def classify(coin: str, fullname: str, overrides: dict | None = None) -> str:
    ov = (overrides or {}).get("class", {})
    if coin in ov:
        return ov[coin]
    if coin in STABLES:
        return "stable"
    if coin in GOLD:
        return "commodity"
    if EQUITY_HINTS.search(fullname or ""):
        return "equity"
    return "crypto"


def discover(client: RoostooClient | None = None, out_dir: str | Path = "data/snapshots",
             overrides_path: str | Path = "config/universe_overrides.yaml") -> pd.DataFrame:
    c = client or RoostooClient(journal=None)
    info = c.exchange_info()
    tick = c.ticker()
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    (out / f"exchangeInfo_{stamp}.json").write_text(json.dumps(info, indent=1))
    (out / f"ticker_{stamp}.json").write_text(json.dumps(tick, indent=1))
    ov = yaml.safe_load(open(overrides_path)) if Path(overrides_path).exists() else {}
    rows = []
    for pair, p in info.get("TradePairs", {}).items():
        t = tick.get(pair, {})
        bid, ask = t.get("MaxBid"), t.get("MinAsk")
        spread_bps = (ask - bid) / ((ask + bid) / 2) * 1e4 if bid and ask else None
        rows.append({
            "pair": pair, "coin": p["Coin"], "name": p.get("CoinFullName"),
            "class": classify(p["Coin"], p.get("CoinFullName", ""), ov),
            "can_trade": p.get("CanTrade"), "price_prec": p.get("PricePrecision"),
            "amt_prec": p.get("AmountPrecision"), "mini_order": p.get("MiniOrder"),
            "last": t.get("LastPrice"), "spread_bps": spread_bps,
            "usd_vol_24h": t.get("UnitTradeValue"), "chg_24h": t.get("Change"),
        })
    df = pd.DataFrame(rows).sort_values(["class", "usd_vol_24h"], ascending=[True, False])
    df.to_csv(out / "universe_latest.csv", index=False)
    print(f"IsRunning={info.get('IsRunning')}  InitialWallet={info.get('InitialWallet')}")
    print(df.groupby("class").size().to_string())
    unk = df[df["class"] == "unknown"]
    if len(unk):
        print("\nREVIEW MANUALLY (add to config/universe_overrides.yaml):\n", unk[["pair", "name"]].to_string())
    return df
