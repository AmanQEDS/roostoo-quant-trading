"""Live trading loop SKELETON - same signal code as the backtest (rq.signals), Roostoo execution.

STATUS: written against the documented API but NOT yet exercised against the real exchange (no keys / network in the
authoring environment). Test on the General Portfolio key first (`--dry-run`, then small), compare fills with the
backtest cost model, only then switch ROOSTOO_ENV=competition.

Design rules (competition Screen 1): fully autonomous, every request journaled (RoostooClient does that), config changes
only via commits, no manual API calls.
"""
from __future__ import annotations

import json
import logging
import time
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
from .position_exits import position_exit_reason, short_trend_failure
from .regime_filter import f2_regime
from .x18 import completed_bars_held, x18_exit_reason

log = logging.getLogger("bot")
KL = "https://api.binance.com/api/v3/klines"


def should_exit_held(coin, target, mode="run") -> bool:
    """Held positions exit only on explicit flat signal or explicit liquidation mode."""
    return mode == "liquidate" or (coin in target.index and target.get(coin, 0) <= 0)


def update_peak_equity(state: dict, equity: float) -> float:
    """Keep the historical equity high-water mark monotonic across cycles/restarts."""
    peak = max(float(state.get("peak", equity)), float(equity))
    state["peak"] = peak
    return peak


class Feed:
    """Rolling 5m klines per crypto coin from Binance REST."""

    def __init__(self, coins: list[str], warm_bars: int = 9000):
        self.coins, self.warm, self.d = coins, warm_bars, {}

    def _fetch(self, sym, start_ms=None, limit=1000):
        p = {"symbol": sym, "interval": "5m", "limit": limit}
        if start_ms:
            p["startTime"] = start_ms

        r = requests.get(KL, params=p, timeout=15)
        r.raise_for_status()

        df = pd.DataFrame(
            r.json(),
            columns=[
                "t",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "ct",
                "qv",
                "n",
                "taker_buy_base",
                "tbq",
                "ig",
            ],
        )

        df["open_time"] = pd.to_datetime(df.t, unit="ms", utc=True)

        df = df.set_index("open_time")[
            [
                "open",
                "high",
                "low",
                "close",
                "volume",
                "qv",
                "taker_buy_base",
            ]
        ].astype(float)

        return df.rename(columns={"qv": "quote_volume"})

    def update(self):
        now = pd.Timestamp.utcnow()

        for c in list(self.coins):
            sym = f"{c}USDT"

            try:
                if c not in self.d or len(self.d[c]) == 0:
                    start = int(
                        (
                            now - pd.Timedelta(minutes=5 * self.warm)
                        ).timestamp()
                        * 1000
                    )

                    parts = []

                    while True:
                        df = self._fetch(sym, start)
                        parts.append(df)

                        if len(df) < 1000:
                            break

                        start = (
                            int(df.index[-1].timestamp() * 1000) + 1
                        )

                    self.d[c] = pd.concat(parts).drop_duplicates()

                else:
                    df = self._fetch(
                        sym,
                        int(self.d[c].index[-1].timestamp() * 1000) + 1,
                    )

                    self.d[c] = (
                        pd.concat([self.d[c], df])
                        .loc[lambda x: ~x.index.duplicated()]
                        .tail(self.warm)
                    )

                self.d[c] = self.d[c][
                    self.d[c].index
                    <= now - pd.Timedelta(minutes=5)
                ]

            except Exception as e:
                log.warning("feed skip %s: %s", c, e)

                if c in self.d and len(self.d[c]) == 0:
                    self.d.pop(c)


class Bot:
    def __init__(
        self,
        cfg_path="config/live.yaml",
        dry_run=True,
        state_path="state/ledger.json",
    ):
        self.cfg = yaml.safe_load(open(cfg_path))
        self.dry = dry_run

        self.api = RoostooClient()
        self.api.sync_clock()

        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(exist_ok=True)

        info = self.api.exchange_info()
        self.pairs = info["TradePairs"]

        cap = float(
            info.get("InitialWallet", {}).get("USD", 100_000)
        )

        cw = self.cfg["crypto_weight"]

        self.state = (
            json.loads(self.state_path.read_text())
            if self.state_path.exists()
            else {
                "pool_cash": {
                    "crypto": cap * cw,
                    "equity": cap * (1 - cw),
                },
                "entries": {},
            }
        )
        self.state.setdefault("entries", {})
        self.order_context = {
            "equity": None, "peak_equity": None,
            "drawdown": None, "dd_multiplier": None,
        }

        # IMPORTANT:
        # Only Roostoo assets explicitly classified as crypto are
        # passed to the Binance signal feed.
        # Match the research universe:
        # crypto + tradable + spread <= max_spread_bps
        # + 24h USD volume >= min_usd_vol_24h + top-N by volume.
        tick = self.api.ticker()
        max_spread_bps = float(self.cfg.get("max_spread_bps", 15))
        min_usd_vol_24h = float(self.cfg.get("min_usd_vol_24h", 1_000_000))
        crypto_top_n = int(self.cfg.get("crypto_top_n", 40))

        candidates = []

        for pair, p in self.pairs.items():
            if not p.get("CanTrade"):
                continue
            if p.get("AssetType") != "crypto":
                continue

            t = tick.get(pair, {})
            bid = t.get("MaxBid")
            ask = t.get("MinAsk")
            volume = t.get("UnitTradeValue")

            if bid is None or ask is None or volume is None:
                continue

            try:
                bid = float(bid)
                ask = float(ask)
                volume = float(volume)
            except (TypeError, ValueError):
                continue

            if bid <= 0 or ask <= 0:
                continue

            spread_bps = (ask - bid) / ((ask + bid) / 2) * 1e4

            if spread_bps > max_spread_bps or volume < min_usd_vol_24h:
                continue

            candidates.append((p["Coin"], volume, spread_bps))

        candidates.sort(key=lambda x: x[1], reverse=True)

        self.coins = [
            coin for coin, _, _ in candidates[:crypto_top_n]
        ]

        log.info(
            "crypto universe: %d eligible / %d selected",
            len(candidates),
            len(self.coins),
        )
        log.info("selected crypto: %s", self.coins)

        # BTC is also loaded as the F2 market-wide reference. It is not
        # automatically added to the tradable strategy universe.
        self.feed = Feed(list(dict.fromkeys(self.coins + ["BTC"])))
        self.freq = FREQ_MINUTES[self.cfg["timeframe"]]

    def save(self):
        """Persist state atomically so an interrupted write cannot truncate the ledger."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(
            self.state_path.suffix + ".tmp"
        )
        try:
            tmp_path.write_text(
                json.dumps(self.state, indent=1),
                encoding="utf-8",
            )
            tmp_path.replace(self.state_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def signals(self) -> pd.Series:
        self.feed.update()

        good = {
            c: d
            for c, d in self.feed.d.items()
            if len(d) > 1500
        }

        if not good:
            raise RuntimeError("no crypto market data available")

        newest = max(
            d.index.max()
            for d in good.values()
        )

        good = {
            c: d
            for c, d in good.items()
            if d.index.max()
            >= newest - pd.Timedelta(minutes=20)
        }

        end = (
            newest + pd.Timedelta(minutes=5)
        ).floor(f"{self.freq}min")

        p = build_panel(
            good,
            None,
            self.freq,
            end - pd.Timedelta(minutes=5 * self.feed.warm),
            end,
        )

        self.current_signal_bar = p.index[-1]

        spec = self.cfg["strategies"]["crypto"]

        cond = ALL_BUILDERS[
            spec["builder"]
        ](
            p,
            {},
            **spec["params"],
        )

        # Keep target/exit signals unchanged. F2 gates new orders in cycle(),
        # rather than flattening existing positions when volatility rises.
        filter_cfg = self.cfg.get("entry_filter") or {}
        self.entry_allowed = True
        if filter_cfg.get("f2_enabled", False):
            f2 = f2_regime(
                p.close,
                reference_symbol=str(filter_cfg.get("reference_symbol", "BTC")),
                window_days=int(filter_cfg.get("window_days", 14)),
                bars_per_day=1440 // self.freq,
            )
            self.entry_allowed = bool(f2["allowed"])
            log.info(
                "F2 entry gate allowed=%s reason=%s high_vol=%s rv=%s median=%s",
                self.entry_allowed, f2["reason"], f2["high_vol"],
                f2["rv"], f2["median"],
            )

        targets = to_target(cond, self.cfg["allow_short"])
        t = targets.reindex(columns=self.coins).iloc[-1]
        self.score = (
            cond.score.iloc[-1].reindex(self.coins)
            if cond.score is not None
            else pd.Series(dtype=float)
        )

        log.info(
            "signal bar %s: %d long / %d short",
            p.index[-1],
            (t > 0).sum(),
            (t < 0).sum(),
        )

        return t

    def _liquidate_equities(self, wallet, tick):
        """Do not submit stock orders from this crypto-only trading bot."""
        stock_holdings = []

        for coin, value in wallet.items():
            if coin == "USD":
                continue

            pair = f"{coin}/USD"
            info = self.pairs.get(pair)

            if info and info.get("AssetType") == "stock":
                free_qty = float(value.get("Free", 0) or 0)
                if free_qty > 0:
                    stock_holdings.append((pair, free_qty))

        if stock_holdings:
            log.warning(
                "STOCK LIQUIDATION SKIPPED: this bot is crypto-only. "
                "Review these holdings manually: %s",
                stock_holdings,
            )

    def cycle(self):
        # Re-read config every cycle so the kill switch remains effective.
        cfgl = yaml.safe_load(
            open("config/live.yaml")
        )

        mode = cfgl.get("mode", "run")
        start = cfgl.get("start_utc")

        if (
            start
            and pd.Timestamp.utcnow()
            < pd.Timestamp(str(start), tz="UTC")
        ):
            log.info(
                "before start_utc %s - idle",
                start,
            )
            return

        # Fetch wallet/ticker first so existing stock positions can be
        # liquidated immediately on deployment before normal crypto trading.
        tick = self.api.ticker()
        wallet = self.api.balance()

        # An unresolved submission blocks ALL order paths, including
        # the separate equity-liquidation path, until reconciliation.
        if not self.dry and self.state.get("pending_order"):
            log.critical(
                "TRADING HALTED: unresolved order requires exchange reconciliation: %s",
                self.state["pending_order"],
            )
            return

        self._liquidate_equities(wallet, tick)

        # Refresh wallet after liquidation in live mode so subsequent
        # sizing uses the post-liquidation USD balance.
        if not self.dry:
            wallet = self.api.balance()
            tick = self.api.ticker()

        tgt = self.signals()

        self.state["pool_cash"]["crypto"] = float(
            wallet.get("USD", {}).get("Free", 0)
        )

        fee = TAKER_FEE
        exit_cfg = cfgl.get("position_exits") or {}
        position_exits_enabled = bool(exit_cfg.get("enabled", False))
        x18_cfg = cfgl.get("x18") or {}
        x18_enabled = bool(x18_cfg.get("enabled", False))

        def _qv(c, v):
            q = v["Free"] + v["Lock"]

            px = float(
                tick.get(
                    f"{c}/USD",
                    {},
                ).get("LastPrice")
                or 0
            )

            return (
                q > 0
                and (
                    px == 0
                    or q * px >= 5.0
                )
            )

        # IMPORTANT:
        # Only classify and manage assets whose Roostoo
        # AssetType is explicitly crypto.
        crypto_coins = {
            p["Coin"]
            for p in self.pairs.values()
            if p.get("AssetType") == "crypto"
        }

        # Existing equity positions are deliberately excluded.
        held = {
            c: v["Free"] + v["Lock"]
            for c, v in wallet.items()
            if (
                c != "USD"
                and c in crypto_coins
                and _qv(c, v)
            )
        }

        def _px(c):
            t = tick.get(
                f"{c}/USD",
                {},
            )

            return float(
                t.get("LastPrice")
                or t.get("MaxBid")
                or t.get("MinAsk")
                or 0
            )

        usd = wallet.get("USD", {})

        eq = (
            usd.get("Free", 0)
            + usd.get("Lock", 0)
            + sum(
                (v["Free"] + v["Lock"]) * _px(c)
                for c, v in wallet.items()
                if c != "USD"
            )
        )

        peak = update_peak_equity(self.state, eq)

        if not self.dry:
            self.save()

        dd = (
            1 - eq / peak
            if peak > 0
            else 0.0
        )

        mult = 1.0

        for th, m in sorted(
            cfgl.get("dd_ladder", []) or []
        ):
            if dd >= th:
                mult = m

        self.order_context = {
            "equity": float(eq),
            "peak_equity": float(peak),
            "drawdown": float(dd),
            "dd_multiplier": float(mult),
        }

        # Update per-position excursions before any exit order is considered.
        entries = self.state.setdefault("entries", {})
        for coin, qty in held.items():
            meta = entries.get(coin)
            px = _px(coin)
            if not meta or not meta.get("entry_price") or px <= 0:
                continue
            meta["peak_price_since_entry"] = max(float(meta.get("peak_price_since_entry", meta["entry_price"])), px)
            meta["trough_price_since_entry"] = min(float(meta.get("trough_price_since_entry", meta["entry_price"])), px)
            entry_px = float(meta["entry_price"])
            meta["mfe"] = max(float(meta.get("mfe", 0.0)), (meta["peak_price_since_entry"] - entry_px) * float(qty))
            meta["mae"] = min(float(meta.get("mae", 0.0)), (meta["trough_price_since_entry"] - entry_px) * float(qty))
            meta["last_price"] = px
            meta["last_unrealized_pnl"] = (px - entry_px) * float(qty)
        if not self.dry:
            self.save()

        # X18 has priority when explicitly enabled; legacy research exits remain
        # available only when X18 is disabled.
        exit_reasons = {}
        if x18_enabled:
            current_bar = getattr(self, "current_signal_bar", None)
            for coin, qty in held.items():
                meta = entries.get(coin, {})
                entry_px = float(meta.get("entry_price") or 0)
                pair = f"{coin}/USD"
                sell_px = float(
                    tick.get(pair, {}).get("MaxBid")
                    or 0
                )
                if entry_px <= 0 or sell_px <= 0:
                    log.warning(
                        "X18 skipped for %s: missing entry cost basis or executable bid",
                        coin,
                    )
                    continue

                bars_held = completed_bars_held(
                    meta.get("entry_signal_bar_ts") or meta.get("entry_ts"),
                    current_bar,
                    self.freq,
                )
                reason = x18_exit_reason(
                    entry_price=entry_px,
                    sell_price=sell_px,
                    fee_rate=fee,
                    bars_held=bars_held,
                    hard_stop_net_pct=float(x18_cfg.get("hard_stop_net_pct", 0.08)),
                    soft_time_bars=int(x18_cfg.get("soft_time_bars", 216)),
                    soft_time_min_net_pct=float(
                        x18_cfg.get("soft_time_min_net_pct", 0.015)
                    ),
                )
                if reason:
                    exit_reasons[coin] = reason
                    log.warning(
                        "X18_EXIT_TRIGGER %s reason=%s entry=%.8f bid=%.8f "
                        "bars_held=%s",
                        coin, reason, entry_px, sell_px, bars_held,
                    )

        elif position_exits_enabled:
            for coin, qty in held.items():
                meta = entries.get(coin, {})
                entry_px = float(meta.get("entry_price") or 0)
                peak_px = float(meta.get("peak_price_since_entry") or 0)
                pair = f"{coin}/USD"
                sell_px = float(
                    tick.get(pair, {}).get("MaxBid")
                    or _px(coin)
                    or 0
                )
                if entry_px <= 0 or peak_px <= 0 or sell_px <= 0:
                    log.warning(
                        "position exit rules skipped for %s: missing entry/peak/price metadata",
                        coin,
                    )
                    continue
                trend_failed = short_trend_failure(
                    self.feed.d.get(coin),
                    timeframe_minutes=self.freq,
                    ema_span=int(exit_cfg.get("trend_ema_span", 10)),
                )
                reason = position_exit_reason(
                    entry_price=entry_px,
                    peak_price=peak_px,
                    current_price=sell_px,
                    fee_rate=fee,
                    take_profit_net_pct=(
                        float(exit_cfg["take_profit_net_pct"])
                        if exit_cfg.get("take_profit_net_pct") is not None
                        else None
                    ),
                    hard_loss_pct=float(exit_cfg.get("hard_loss_pct", 0.03)),
                    trail_activation_net_pct=float(
                        exit_cfg.get("trail_activation_net_pct", 0.05)
                    ),
                    giveback_fraction=float(exit_cfg.get("giveback_fraction", 0.50)),
                    trend_failure=trend_failed,
                )
                if reason:
                    exit_reasons[coin] = reason
                    log.warning(
                        "POSITION_EXIT_TRIGGER %s reason=%s entry=%.8f peak=%.8f bid=%.8f",
                        coin, reason, entry_px, peak_px, sell_px,
                    )

        log.info(
            "equity %.2f peak %.2f dd %.1f%% ladder_mult %.2f",
            eq,
            peak,
            dd * 100,
            mult,
        )

        # ---------------------------------------------------------
        # EXITS
        # Only crypto positions can be exited by this bot.
        # Existing equity positions are completely ignored.
        # ---------------------------------------------------------
        for coin, qty in held.items():
            triggered_reason = exit_reasons.get(coin)
            if triggered_reason or should_exit_held(coin, tgt, mode):
                pair = f"{coin}/USD"
                if mode == "liquidate":
                    sell_reason = "SELL_OTHER"
                else:
                    sell_reason = triggered_reason or "SELL_SIGNAL_EXIT"

                sold = self._order(
                    coin,
                    "SELL",
                    plan_exit(
                        wallet[coin]["Free"],
                        self.pairs[pair]["AmountPrecision"],
                    ),
                    tick,
                    reason=sell_reason,
                )
                if sold and (
                    (x18_enabled and triggered_reason in {"hard_stop_X18", "soft_time_X18"})
                    or (position_exits_enabled and not x18_enabled)
                ):
                    if x18_enabled:
                        cooldown_bars = max(0, int(x18_cfg.get("cooldown_bars", 3)))
                        current_bar = getattr(self, "current_signal_bar", None)
                        if current_bar is not None:
                            until_bar = pd.Timestamp(current_bar) + pd.Timedelta(
                                minutes=self.freq * cooldown_bars
                            )
                            self.state.setdefault("x18_cooldown_until_bar", {})[coin] = until_bar.isoformat()
                        else:
                            log.warning("X18 cooldown not persisted for %s: signal bar timestamp missing", coin)
                    else:
                        cooldown_bars = max(0, int(exit_cfg.get("cooldown_bars", 2)))
                        expires = pd.Timestamp.now(tz="UTC") + pd.Timedelta(
                            minutes=self.freq * cooldown_bars
                        )
                        self.state.setdefault("exit_cooldowns", {})[coin] = expires.isoformat()
                    self.save()

        if mode != "run":
            return

        # Entries.
        if mult <= 0:
            log.info(
                "ladder mult 0 - no new entries"
            )
            return

        n_open = len(
            [
                c
                for c in held
                if c not in tgt.index
                or tgt.get(c, 0) > 0
            ]
        )

        cooldowns = self.state.setdefault("exit_cooldowns", {})
        cooldown_now = pd.Timestamp.utcnow()

        def _cooldown_active(coin):
            if x18_enabled:
                expiry_raw = self.state.setdefault("x18_cooldown_until_bar", {}).get(coin)
                current_bar = getattr(self, "current_signal_bar", None)
                if not expiry_raw or current_bar is None:
                    return False
                try:
                    expiry = pd.Timestamp(expiry_raw)
                    now_bar = pd.Timestamp(current_bar)
                    if expiry.tzinfo is None:
                        expiry = expiry.tz_localize("UTC")
                    else:
                        expiry = expiry.tz_convert("UTC")
                    if now_bar.tzinfo is None:
                        now_bar = now_bar.tz_localize("UTC")
                    else:
                        now_bar = now_bar.tz_convert("UTC")
                    if now_bar < expiry:
                        return True
                except (TypeError, ValueError):
                    log.warning("invalid X18 bar cooldown for %s; clearing it", coin)
                self.state.setdefault("x18_cooldown_until_bar", {}).pop(coin, None)
                return False
            if not position_exits_enabled:
                return False
            expiry_raw = cooldowns.get(coin)
            if not expiry_raw:
                return False
            try:
                expiry = pd.Timestamp(expiry_raw)
                if expiry.tzinfo is None:
                    expiry = expiry.tz_localize("UTC")
                else:
                    expiry = expiry.tz_convert("UTC")
                if expiry > cooldown_now:
                    return True
            except (TypeError, ValueError):
                log.warning("invalid exit cooldown for %s; clearing it", coin)
            cooldowns.pop(coin, None)
            return False

        for coin in self._rank(
            [
                c
                for c, v in tgt.items()
                if (
                    v > 0
                    and c not in held
                    and c in crypto_coins
                    and getattr(self, "entry_allowed", True)
                    and not _cooldown_active(c)
                )
            ]
        ):
            if (
                n_open
                >= self.cfg["max_pos"]["crypto"]
            ):
                break

            pair = f"{coin}/USD"
            pi = self.pairs[pair]

            q = plan_entry(
                self.state["pool_cash"]["crypto"],
                self.cfg["pos_frac"] * mult,
                tick[pair]["MinAsk"],
                pi["AmountPrecision"],
                pi["MiniOrder"],
                fee,
            )

            if (
                q > 0
                and self._order(
                    coin,
                    "BUY",
                    q,
                    tick,
                    reason="BUY_NEW_ENTRY",
                )
            ):
                n_open += 1

    def _rank(self, cands):
        sc = getattr(
            self,
            "score",
            None,
        )

        def s(c):
            try:
                v = float(sc.get(c))
                return v if v == v else 0.0
            except Exception:
                return 0.0

        out = sorted(
            cands,
            key=lambda c: -s(c),
        )

        log.info(
            "entry order (score desc): %s",
            [
                (c, round(s(c), 4))
                for c in out
            ],
        )

        return out

    def _order(
        self,
        coin,
        side,
        qty,
        tick,
        reason=None,
    ) -> bool:
        # Final safety guard: this bot may only trade crypto.
        pair_info = self.pairs.get(
            f"{coin}/USD"
        )

        if (
            pair_info is None
            or pair_info.get("AssetType") != "crypto"
        ):
            log.warning(
                "BLOCKED non-crypto order: %s %s",
                side,
                coin,
            )
            return False

        pair = f"{coin}/USD"

        if qty <= 0:
            return False

        # Fail closed if a previous live order has not been reconciled.
        if not self.dry and self.state.get("pending_order"):
            pending = self.state["pending_order"]
            log.error(
                "BLOCKED order: unresolved order state exists: %s",
                pending,
            )
            return False

        meta = self.state.setdefault("entries", {}).get(coin, {})
        last_price = float(
            tick.get(pair, {}).get("LastPrice")
            or tick.get(pair, {}).get("MaxBid")
            or tick.get(pair, {}).get("MinAsk")
            or 0
        )
        entry_price = meta.get("entry_price")
        unrealized = (
            (last_price - float(entry_price)) * float(qty)
            if entry_price is not None and side == "SELL"
            else None
        )
        reason = reason or ("BUY_NEW_ENTRY" if side == "BUY" else "SELL_OTHER")
        log.info(
            "ORDER_INTENT %s",
            json.dumps({
                "ts": pd.Timestamp.utcnow().isoformat(),
                "symbol": pair, "side": side, "qty": qty, "reason": reason,
                "entry_price": entry_price, "entry_ts": meta.get("entry_ts"),
                "last_price": last_price or None, "unrealized_pnl": unrealized,
                "peak_price_since_entry": meta.get("peak_price_since_entry"),
                "mfe": meta.get("mfe"), "mae": meta.get("mae"),
                "equity": self.order_context.get("equity"),
                "peak_equity": self.order_context.get("peak_equity"),
                "drawdown": self.order_context.get("drawdown"),
                "dd_multiplier": self.order_context.get("dd_multiplier"),
            }, sort_keys=True),
        )

        if self.dry:
            log.info(
                "[dry-run] %s %s %s",
                side,
                qty,
                pair,
            )
            return True

        # Persist intent BEFORE submitting. A crash or timeout is treated
        # as uncertain until the exchange is reconciled manually.
        self.state["pending_order"] = {
            "status": "submitting",
            "symbol": pair,
            "side": side,
            "quantity": float(qty),
            "reason": reason,
            "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        }
        self.save()

        try:
            d = self.api.place_order(
                pair,
                side,
                qty,
            )
        except Exception as e:
            self.state["pending_order"]["status"] = "uncertain"
            self.state["pending_order"]["error"] = repr(e)
            self.save()
            log.error(
                "ORDER UNCERTAIN %s %s: %s; trading is blocked pending reconciliation",
                side,
                pair,
                e,
            )
            return False

        try:
            filled_qty = float(d.get("FilledQuantity") or 0)
            fill_px = float(d.get("FilledAverPrice") or 0)
            fee = float(d.get("CommissionChargeValue") or 0)
        except (AttributeError, TypeError, ValueError) as e:
            self.state["pending_order"]["status"] = "uncertain"
            self.state["pending_order"]["error"] = (
                "Malformed order response: " + repr(e)
            )
            self.save()
            log.error(
                "ORDER UNCERTAIN %s %s: malformed response; trading is blocked",
                side, pair,
            )
            return False

        if filled_qty <= 0 or fill_px <= 0:
            self.state["pending_order"]["status"] = "uncertain"
            self.state["pending_order"]["response"] = d
            self.save()
            log.error(
                "ORDER UNCERTAIN %s %s: no valid fill; trading is blocked",
                side, pair,
            )
            return False

        notional = filled_qty * fill_px
        self.state["pool_cash"]["crypto"] += (
            (notional - fee)
            if side == "SELL"
            else -(notional + fee)
        )

        if side == "BUY":
            self.state.setdefault("entries", {})[coin] = {
                "entry_price": fill_px,
                "entry_ts": pd.Timestamp.now(tz="UTC").isoformat(),
                "entry_signal_bar_ts": (
                    pd.Timestamp(getattr(self, "current_signal_bar")).isoformat()
                    if getattr(self, "current_signal_bar", None) is not None
                    else None
                ),
                "peak_price_since_entry": fill_px,
                "trough_price_since_entry": fill_px,
                "mfe": 0.0,
                "mae": 0.0,
            }
        elif side == "SELL":
            # Do not discard cost-basis / peak metadata on a partial fill.
            # The next wallet snapshot remains the source of truth for residual qty.
            if filled_qty + max(1e-12, float(qty) * 1e-8) >= float(qty):
                self.state.setdefault("entries", {}).pop(coin, None)
            else:
                log.warning(
                    "partial SELL fill for %s: requested=%s filled=%s; retaining position metadata",
                    pair, qty, filled_qty,
                )

        # Keep trading halted when the exchange reports a partial fill.
        # Reconcile the remaining order before allowing another submission.
        fill_tolerance = max(1e-12, float(qty) * 1e-8)
        if filled_qty + fill_tolerance < float(qty):
            pending = self.state["pending_order"]
            pending["status"] = "partial_fill"
            pending["filled_quantity"] = filled_qty
            pending["average_fill_price"] = fill_px
            pending["response"] = d
            self.save()
            log.critical(
                "PARTIAL FILL: %s requested=%s filled=%s; "
                "trading remains blocked pending reconciliation",
                pair, qty, filled_qty,
            )
            return False

        # Clear only after a full fill has been recorded and saved.
        self.state.pop("pending_order", None)
        self.save()

        log.info(
            "filled %s %s %s @ %s fee=%s",
            side,
            d.get("FilledQuantity"),
            pair,
            d.get("FilledAverPrice"),
            fee,
        )

        return True

    def run(self):
        while True:
            t0 = time.time()

            try:
                self.cycle()
            except Exception:
                log.exception(
                    "cycle failed - holding"
                )

            step = self.freq * 60

            time.sleep(
                max(
                    5,
                    (
                        int(time.time()) // step
                        + 1
                    )
                    * step
                    + 15
                    - time.time(),
                )
            )