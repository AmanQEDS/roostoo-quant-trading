"""Live trading loop SKELETON - same signal code as the backtest (rq.signals), Roostoo execution.

STATUS: written against the documented API but NOT yet exercised against the real exchange (no keys / network in the
authoring environment). Test on the General Portfolio key first (`--dry-run`, then small), compare fills with the
backtest cost model, only then switch ROOSTOO_ENV=competition.

Design rules (competition Screen 1): fully autonomous, every request journaled (RoostooClient does that), config changes
only via commits, no manual API calls.
"""
from __future__ import annotations
import json, logging, time
from pathlib import Path
import pandas as pd
import requests
import yaml
from ..constants import TAKER_FEE, FREQ_MINUTES
from ..data.panel import build_panel
from ..execution import plan_entry, plan_exit
from ..roostoo.client import RoostooClient
from ..signals.core import to_target
from ..research.runner import ALL_BUILDERS

log = logging.getLogger("bot")
KL = "https://api.binance.com/api/v3/klines"


class Feed:
    """Rolling 5m klines per coin from Binance REST (signals) - Roostoo only provides the live ticker."""
    def __init__(self, coins: list[str], warm_bars: int = 3000):
        self.coins, self.warm, self.d = coins, warm_bars, {}

    def _fetch(self, sym, start_ms=None, limit=1000):
        p = {"symbol": sym, "interval": "5m", "limit": limit}
        if start_ms: p["startTime"] = start_ms
        r = requests.get(KL, params=p, timeout=15); r.raise_for_status()
        df = pd.DataFrame(r.json(), columns=["t", "open", "high", "low", "close", "volume", "ct", "qv", "n", "taker_buy_base", "tbq", "ig"])
        df["open_time"] = pd.to_datetime(df.t, unit="ms", utc=True)
        df = df.set_index("open_time")[["open", "high", "low", "close", "volume", "qv", "taker_buy_base"]].astype(float)
        return df.rename(columns={"qv": "quote_volume"})

    def update(self):
        now = pd.Timestamp.utcnow()
        for c in list(self.coins):
            sym = f"{c}USDT"
            try:
                if c not in self.d or len(self.d[c]) == 0:
                    start = int((now - pd.Timedelta(minutes=5 * self.warm)).timestamp() * 1000)
                    parts = []
                    while True:
                        df = self._fetch(sym, start); parts.append(df)
                        if len(df) < 1000: break
                        start = int(df.index[-1].timestamp() * 1000) + 1
                    self.d[c] = pd.concat(parts).drop_duplicates()
                else:
                    df = self._fetch(sym, int(self.d[c].index[-1].timestamp() * 1000) + 1)
                    self.d[c] = pd.concat([self.d[c], df]).loc[lambda x: ~x.index.duplicated()].tail(self.warm)
                self.d[c] = self.d[c][self.d[c].index <= now - pd.Timedelta(minutes=5)]
            except Exception as e:
                log.warning("feed skip %s: %s", c, e)
                if c in self.d and len(self.d[c]) == 0: self.d.pop(c)   # keep coin, retry next bar


class Bot:
    def __init__(self, cfg_path="config/live.yaml", dry_run=True, state_path="state/ledger.json"):
        self.cfg = yaml.safe_load(open(cfg_path)); self.dry = dry_run
        self.api = RoostooClient(); self.api.sync_clock()
        self.state_path = Path(state_path); self.state_path.parent.mkdir(exist_ok=True)
        info = self.api.exchange_info(); self.pairs = info["TradePairs"]
        cap = float(info.get("InitialWallet", {}).get("USD", 100_000))
        cw = self.cfg["crypto_weight"]
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else \
            {"pool_cash": {"crypto": cap * cw, "equity": cap * (1 - cw)}, "entries": {}}
        self.coins = [p["Coin"] for p in self.pairs.values() if p["CanTrade"] and p["Coin"] not in ("USDT", "USDC")][:40]
        self.feed = Feed(self.coins)
        self.freq = FREQ_MINUTES[self.cfg["timeframe"]]

    def save(self): self.state_path.write_text(json.dumps(self.state, indent=1))

    def signals(self) -> pd.Series:
        self.feed.update()
        good = {c: d for c, d in self.feed.d.items() if len(d) > 1500}
        newest = max(d.index.max() for d in good.values())
        good = {c: d for c, d in good.items() if d.index.max() >= newest - pd.Timedelta(minutes=20)}
        end = (newest + pd.Timedelta(minutes=5)).floor(f"{self.freq}min")
        p = build_panel(good, None, self.freq, end - pd.Timedelta(minutes=5 * 3000), end)
        spec = self.cfg["strategies"]["crypto"]
        cond = ALL_BUILDERS[spec["builder"]](p, {}, **spec["params"])
        t = to_target(cond, self.cfg["allow_short"]).iloc[-1]
        self.score = cond.score.iloc[-1] if cond.score is not None else pd.Series(dtype=float)
        log.info("signal bar %s: %d long / %d short", p.index[-1], (t > 0).sum(), (t < 0).sum())
        return t

    def cycle(self):
        cfgl = yaml.safe_load(open("config/live.yaml"))                       # re-read each cycle (kill switch)
        mode = cfgl.get("mode", "run")
        start = cfgl.get("start_utc")
        if start and pd.Timestamp.utcnow() < pd.Timestamp(str(start), tz="UTC"):
            log.info("before start_utc %s - idle", start); return
        tgt = self.signals()
        tick = self.api.ticker(); wallet = self.api.balance()
        self.state["pool_cash"]["crypto"] = float(wallet.get("USD", {}).get("Free", 0))   # wallet is truth
        fee = TAKER_FEE
        held = {c: v["Free"] + v["Lock"] for c, v in wallet.items() if c != "USD" and v["Free"] + v["Lock"] > 0}
        def _px(c):
            t = tick.get(f"{c}/USD", {})
            return float(t.get("LastPrice") or t.get("MaxBid") or t.get("MinAsk") or 0)
        usd = wallet.get("USD", {})
        eq = usd.get("Free", 0) + usd.get("Lock", 0) + sum((v["Free"] + v["Lock"]) * _px(c) for c, v in wallet.items() if c != "USD")
        peak = max(self.state.get("peak", eq), eq)
        self.state["peak"] = peak
        if not self.dry: self.save()
        dd = 1 - eq / peak if peak > 0 else 0.0
        mult = 1.0
        for th, m in sorted(cfgl.get("dd_ladder", []) or []):
            if dd >= th: mult = m
        log.info("equity %.2f peak %.2f dd %.1f%% ladder_mult %.2f", eq, peak, dd * 100, mult)
        # exits first
        for coin, qty in held.items():
            if mode == "liquidate" or (coin in tgt.index and tgt.get(coin, 0) <= 0):
                self._order(coin, "SELL", plan_exit(wallet[coin]["Free"], self.pairs[f"{coin}/USD"]["AmountPrecision"]), tick)
        if mode != "run":
            return
        # entries, sequential on remaining crypto-pool cash
        if mult <= 0:
            log.info("ladder mult 0 - no new entries"); return
        n_open = len([c for c in held if c not in tgt.index or tgt.get(c, 0) > 0])
        for coin in self._rank([c for c, v in tgt.items() if v > 0 and c not in held]):
            if n_open >= self.cfg["max_pos"]["crypto"]: break
            pair = f"{coin}/USD"; pi = self.pairs[pair]
            q = plan_entry(self.state["pool_cash"]["crypto"], self.cfg["pos_frac"] * mult, tick[pair]["MinAsk"], pi["AmountPrecision"], pi["MiniOrder"], fee)
            if q > 0 and self._order(coin, "BUY", q, tick): n_open += 1

    def _rank(self, cands):
        sc = getattr(self, "score", None)
        def s(c):
            try:
                v = float(sc.get(c)); return v if v == v else 0.0
            except Exception:
                return 0.0
        out = sorted(cands, key=lambda c: -s(c))
        log.info("entry order (score desc): %s", [(c, round(s(c), 4)) for c in out])
        return out

    def _order(self, coin, side, qty, tick) -> bool:
        pair = f"{coin}/USD"
        if qty <= 0: return False
        if self.dry:
            log.info("[dry-run] %s %s %s", side, qty, pair); return True
        try:
            d = self.api.place_order(pair, side, qty)
        except Exception as e:
            log.error("order failed %s %s: %s", side, pair, e); return False
        notional = d.get("FilledQuantity", 0) * d.get("FilledAverPrice", 0)
        fee = d.get("CommissionChargeValue", 0)
        self.state["pool_cash"]["crypto"] += (notional - fee) if side == "SELL" else -(notional + fee)
        self.save(); log.info("filled %s %s %s @ %s fee=%s", side, d.get("FilledQuantity"), pair, d.get("FilledAverPrice"), fee)
        return True

    def run(self):
        while True:
            t0 = time.time()
            try: self.cycle()
            except Exception: log.exception("cycle failed - holding")
            step = self.freq * 60                                  # wake 15 s after the next bar boundary
            time.sleep(max(5, (int(time.time()) // step + 1) * step + 15 - time.time()))
