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
import math
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml

from ..constants import TAKER_FEE, FREQ_MINUTES
from ..data.panel import build_panel
from ..execution import floor_qty, plan_entry, plan_exit
from ..roostoo.client import RoostooClient
from ..signals.core import to_target
from ..research.runner import ALL_BUILDERS
from .instance_lock import InstanceLock
from .position_exits import position_exit_reason, short_trend_failure
from .reconciliation import (
    UNKNOWN_TIME_POLICY,
    apply_manual_reconciliation,
    execution_journal_scope,
    reconcile_crypto_holdings,
    recover_from_execution_journal,
)
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


def _finite_float(value, default=0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


class Feed:
    """Rolling 5m klines per crypto coin from Binance REST."""

    interval_ms = 5 * 60 * 1000

    def __init__(
        self,
        coins: list[str],
        warm_bars: int = 9000,
        max_retries: int = 3,
        timeout: float = 15.0,
    ):
        if warm_bars <= 0 or max_retries < 1 or timeout <= 0:
            raise ValueError("warm_bars, max_retries and timeout must be positive")
        self.coins, self.warm, self.d = coins, warm_bars, {}
        self.max_retries, self.timeout = max_retries, timeout

    def _fetch(self, sym, start_ms=None, limit=1000):
        p = {"symbol": sym, "interval": "5m", "limit": limit}
        if start_ms is not None:
            p["startTime"] = start_ms

        response = None
        for attempt in range(self.max_retries):
            try:
                response = requests.get(KL, params=p, timeout=self.timeout)
                if response.status_code in (418, 429):
                    if attempt + 1 == self.max_retries:
                        response.raise_for_status()
                    try:
                        retry_after = float(response.headers.get("Retry-After", 0))
                    except (TypeError, ValueError):
                        retry_after = 0.0
                    delay = min(max(retry_after, min(2**attempt, 8)), 30)
                    log.warning(
                        "Binance rate limited %s batch; retry %d/%d in %.1fs",
                        sym, attempt + 1, self.max_retries - 1, delay,
                    )
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and 400 <= status < 500 and status not in (418, 429):
                    raise
                if attempt + 1 == self.max_retries:
                    raise
                delay = min(2**attempt, 8)
                log.warning(
                    "Binance request failed for %s batch; retry %d/%d in %.1fs",
                    sym, attempt + 1, self.max_retries - 1, delay,
                    exc_info=True,
                )
                time.sleep(delay)

        if response is None:
            raise RuntimeError(f"Binance returned no response for {sym}")

        payload = response.json()
        columns = [
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
        ]
        if not payload:
            empty = pd.DataFrame(
                columns=["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base"],
                index=pd.DatetimeIndex([], tz="UTC", name="open_time"),
            )
            return empty
        if not isinstance(payload, list) or any(
            not isinstance(row, (list, tuple)) or len(row) < len(columns)
            for row in payload
        ):
            raise ValueError(f"Malformed Binance kline response for {sym}")

        df = pd.DataFrame(payload, columns=columns)

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

        return df.rename(columns={"qv": "quote_volume"}).sort_index()

    def update(self):
        now = pd.Timestamp.now(tz="UTC")
        update_started = time.perf_counter()
        total_requests = 0

        for symbol_index, c in enumerate(list(self.coins), start=1):
            sym = f"{c}USDT"
            symbol_started = time.perf_counter()
            symbol_requests = 0

            try:
                if c not in self.d or len(self.d[c]) == 0:
                    start = int(
                        (
                            now - pd.Timedelta(minutes=5 * self.warm)
                        ).timestamp()
                        * 1000
                    )

                    parts = []
                    requested_bars = 0
                    max_pages = max(1, (self.warm + 999) // 1000)

                    for page_index in range(1, max_pages + 1):
                        limit = min(1000, self.warm - requested_bars)
                        if limit <= 0:
                            break
                        request_started = time.perf_counter()
                        df = self._fetch(sym, start, limit=limit)
                        latency = time.perf_counter() - request_started
                        symbol_requests += 1
                        total_requests += 1
                        parts.append(df)
                        log.info(
                            "feed batch symbol=%s batch=%d/%d rows=%d latency=%.3fs",
                            sym, page_index, max_pages, len(df), latency,
                        )
                        if df.empty:
                            log.error(
                                "feed pagination stopped for %s after %d/%d bars: empty batch",
                                sym, requested_bars, self.warm,
                            )
                            break

                        last_ms = int(df.index[-1].timestamp() * 1000)
                        next_start = last_ms + self.interval_ms
                        requested_bars += len(df)
                        if next_start <= start:
                            log.error(
                                "feed pagination stopped for %s: non-advancing startTime %s",
                                sym, next_start,
                            )
                            break
                        if len(df) < limit:
                            break
                        start = next_start

                    if parts:
                        self.d[c] = (
                            pd.concat(parts)
                            .loc[lambda frame: ~frame.index.duplicated(keep="last")]
                            .sort_index()
                            .tail(self.warm)
                        )
                    else:
                        self.d[c] = pd.DataFrame(
                            columns=[
                                "open", "high", "low", "close", "volume",
                                "quote_volume", "taker_buy_base",
                            ],
                            index=pd.DatetimeIndex([], tz="UTC", name="open_time"),
                        )

                else:
                    start = int(self.d[c].index[-1].timestamp() * 1000) + self.interval_ms
                    request_started = time.perf_counter()
                    df = self._fetch(sym, start, limit=min(1000, self.warm))
                    latency = time.perf_counter() - request_started
                    symbol_requests += 1
                    total_requests += 1
                    log.info(
                        "feed batch symbol=%s batch=1/1 rows=%d latency=%.3fs",
                        sym, len(df), latency,
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

                log.info(
                    "feed symbol %d/%d complete: %s rows=%d requests=%d elapsed=%.2fs",
                    symbol_index, len(self.coins), sym, len(self.d[c]),
                    symbol_requests, time.perf_counter() - symbol_started,
                )
            except Exception as e:
                log.error(
                    "feed failed for symbol %d/%d %s after %d requests: %s",
                    symbol_index, len(self.coins), sym, symbol_requests, e,
                    exc_info=True,
                )

                if c in self.d and len(self.d[c]) == 0:
                    self.d.pop(c)
        log.info(
            "feed update complete: symbols=%d requests=%d elapsed=%.2fs",
            len(self.coins), total_requests, time.perf_counter() - update_started,
        )


class Bot:
    def __init__(
        self,
        cfg_path="config/live.yaml",
        dry_run=True,
        state_path="state/ledger.json",
    ):
        self.cfg_path = Path(cfg_path)
        self.cfg = yaml.safe_load(self.cfg_path.read_text(encoding="utf-8"))
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
        self._held_quantities: dict[str, float] = {}
        self._wallet_free_quantities: dict[str, float] = {}
        self._valuation_complete = True
        self._entry_freeze_reasons: list[str] = []

    def save(self):
        """Persist state atomically; dry runs must never write the ledger."""
        if self.dry:
            log.info("DRY_RUN_STATE_WRITE_BLOCKED path=%s", self.state_path)
            return

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
        staleness = pd.Timestamp.now(tz="UTC") - newest
        if staleness > pd.Timedelta(minutes=self.freq + 10):
            raise RuntimeError(
                f"market feed is stale by {staleness}; refusing to generate live signals"
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
        if getattr(self, "_instance_lock_held", False):
            return self._cycle()
        lock_path = self.state_path.with_suffix(".lock")
        with InstanceLock(lock_path):
            return self._cycle()

    def _cycle(self):
        # Re-read config every cycle so the kill switch remains effective.
        cfgl = yaml.safe_load(self.cfg_path.read_text(encoding="utf-8"))
        self.cfg = cfgl

        mode = cfgl.get("mode", "run")
        reconciliation_policy = (
            cfgl.get("position_reconciliation") or {}
        ).get("unknown_basis_policy", "manual_reconciliation_freeze_entries")
        if reconciliation_policy != "manual_reconciliation_freeze_entries":
            raise ValueError(
                "unsupported position reconciliation policy: "
                f"{reconciliation_policy!r}"
            )
        start = cfgl.get("start_utc")

        if (
            start
            and pd.Timestamp.now(tz="UTC")
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
        if self.state.get("pending_order"):
            if self.dry:
                log.critical(
                    "DRY-RUN HALTED: persisted pending order requires exchange reconciliation; "
                    "no simulated orders will be generated"
                )
                return
            self._recover_pending_order()
            if self.state.get("pending_order"):
                log.critical(
                    "TRADING HALTED: unresolved order requires exchange reconciliation: %s",
                    self.state.get("pending_order"),
                )
                return
            log.warning("previous pending order reconciled; refreshing balances before this cycle")
            tick = self.api.ticker()
            wallet = self.api.balance()

        self._liquidate_equities(wallet, tick)

        # Refresh wallet after liquidation in live mode so subsequent
        # sizing uses the post-liquidation USD balance.
        if not self.dry:
            wallet = self.api.balance()
            tick = self.api.ticker()

        self.state.setdefault("pool_cash", {"crypto": 0.0, "equity": 0.0})
        cash_free = _finite_float(wallet.get("USD", {}).get("Free"))
        cash_locked = _finite_float(wallet.get("USD", {}).get("Lock"))
        crypto_weight = _finite_float(cfgl.get("crypto_weight"), -1)
        if not 0 <= crypto_weight <= 1:
            raise ValueError("config crypto_weight must be between 0 and 1")
        self.state["pool_cash"]["crypto"] = cash_free * crypto_weight
        self.state["pool_cash"]["equity"] = cash_free * (1.0 - crypto_weight)

        fee = TAKER_FEE
        exit_cfg = cfgl.get("position_exits") or {}
        position_exits_enabled = bool(exit_cfg.get("enabled", False))
        x18_cfg = cfgl.get("x18") or {}
        x18_enabled = bool(x18_cfg.get("enabled", False))
        crypto_coins = {
            pair.rsplit("/", 1)[0]
            for pair, pair_info in self.pairs.items()
            if "/" in pair and pair_info.get("AssetType") == "crypto"
        }
        reconciliation_required = self.state.setdefault(
            "reconciliation_required", {}
        )
        entries = self.state.setdefault("entries", {})
        audit = self.state.setdefault("reconciliation_audit", [])
        if not isinstance(audit, list):
            raise ValueError("ledger reconciliation_audit must be a list")
        account_scope = execution_journal_scope(getattr(self.api, "key", ""))
        history_events: list[dict[str, Any]] = []
        history_diagnostics = self.state.setdefault("reconciliation_history", {})
        history_lookup = getattr(self.api, "query_order_history", None)
        for coin, raw_balance in wallet.items():
            if coin == "USD" or not isinstance(raw_balance, dict):
                continue
            quantity = _finite_float(raw_balance.get("Free")) + _finite_float(raw_balance.get("Lock"))
            if quantity <= 0:
                continue
            pair = f"{coin}/USD"
            pair_info = self.pairs.get(pair)
            if not isinstance(pair_info, dict) or pair_info.get("AssetType") != "crypto" or not pair_info.get("CanTrade"):
                continue
            meta = entries.get(coin, {})
            if not isinstance(meta, dict):
                meta = {}
            entry_price = _finite_float(meta.get("entry_price"))
            local_quantity = _finite_float(meta.get("remaining_quantity"))
            entry_ts_raw = meta.get("entry_signal_bar_ts") or meta.get("entry_ts")
            timestamp_ok = False
            if entry_ts_raw:
                try:
                    parsed_ts = pd.Timestamp(entry_ts_raw)
                    timestamp_ok = parsed_ts.tzinfo is not None and not pd.isna(parsed_ts) and parsed_ts <= pd.Timestamp.now(tz="UTC")
                except (TypeError, ValueError, OverflowError):
                    timestamp_ok = False
            unknown_time_ok = (
                meta.get("entry_time_status") == "unknown_operator_attested"
                and meta.get("time_exit_policy") == UNKNOWN_TIME_POLICY
                and entry_ts_raw in (None, "")
            )
            try:
                tolerance = max(1e-12, 0.5 * 10 ** (-int(pair_info.get("AmountPrecision", 8))), quantity * 1e-10)
            except (TypeError, ValueError, OverflowError):
                tolerance = 0.0
            marker = reconciliation_required.get(coin)
            needs_history = (
                entry_price <= 0
                or (not timestamp_ok and not unknown_time_ok)
                or local_quantity <= 0
                or abs(local_quantity - quantity) > tolerance
                or (
                    isinstance(marker, dict)
                    and marker.get("reason") in {
                        "missing_verified_entry_cost_basis", "missing_entry_timestamp",
                        "exchange_local_quantity_mismatch", "execution_history_quantity_mismatch",
                        "execution_history_basis_mismatch",
                    }
                )
            )
            if not needs_history:
                continue
            if not callable(history_lookup):
                history_diagnostics[coin] = {
                    "status": "unavailable", "reason": "client_missing_query_order_history",
                    "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
                }
                log.warning("EXCHANGE ORDER HISTORY UNAVAILABLE for %s; position remains unresolved", coin)
                continue
            try:
                order_details = history_lookup(pair=pair)
                if not isinstance(order_details, list):
                    raise ValueError("history client did not return a list")
                history_diagnostics[coin] = {
                    "status": "queried", "order_count": len(order_details),
                    "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
                }
                for detail in order_details:
                    if not isinstance(detail, dict) or detail.get("Pair") != pair or str(detail.get("Side", "")).upper() not in {"BUY", "SELL"}:
                        continue
                    history_events.append({
                        "t": time.time(), "account_scope": account_scope,
                        "method": "POST", "path": "/v3/query_order",
                        "params": {"pair": pair, "pending_only": "FALSE"},
                        "resp": {"Success": True, "OrderMatched": [detail]},
                    })
                if not order_details:
                    log.warning("EXCHANGE ORDER HISTORY EMPTY for %s; manual evidence may be required", coin)
            except Exception as exc:
                history_diagnostics[coin] = {
                    "status": "unavailable", "error": str(exc)[:300],
                    "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
                }
                log.exception("EXCHANGE ORDER HISTORY LOOKUP FAILED for %s; position remains unresolved", coin)

        recovered = recover_from_execution_journal(
            getattr(self.api, "journal", None), wallet, self.pairs, entries,
            reconciliation_required, account_scope=account_scope,
            additional_events=history_events,
        )
        if recovered:
            recovered_at = pd.Timestamp.now(tz="UTC").isoformat()
            for coin in recovered:
                meta = entries.get(coin, {})
                audit.append({
                    "action": "automatic_position_recovery", "coin": coin,
                    "recorded_at": recovered_at, "source": meta.get("entry_source"),
                    "entry_price": meta.get("entry_price"),
                    "remaining_quantity": meta.get("remaining_quantity"),
                    "entry_ts": meta.get("entry_ts"),
                })
                # Dry-run intentionally does not persist ledger mutations, so
                # emit the verified recovered metadata for operator review.
                log.info("POSITION RECOVERY DETAIL %s", json.dumps({
                    "coin": coin,
                    "entry_price": meta.get("entry_price"),
                    "entry_cost_basis": meta.get("entry_cost_basis"),
                    "remaining_quantity": meta.get("remaining_quantity"),
                    "entry_ts": meta.get("entry_ts"),
                    "entry_fees_quote": meta.get("entry_fees_quote"),
                    "entry_fees_base": meta.get("entry_fees_base"),
                    "entry_source": meta.get("entry_source"),
                }, sort_keys=True))
            log.warning(
                "POSITION HISTORY RECOVERED from persisted/exchange order records: %s",
                ", ".join(sorted(recovered)),
            )
        manual_path = self.state_path.with_name("reconciliation_manual.json")
        if manual_path.exists():
            manual_document = json.loads(manual_path.read_text(encoding="utf-8"))
            if not isinstance(manual_document, dict):
                raise ValueError(
                    f"manual reconciliation file must contain a JSON object: {manual_path}"
                )
            manually_reconciled = apply_manual_reconciliation(
                manual_document,
                wallet,
                self.pairs,
                entries,
                reconciliation_required,
                audit,
            )
            if manually_reconciled:
                log.warning(
                    "POSITION HISTORY MANUALLY RECONCILED with audited operator evidence: %s",
                    ", ".join(sorted(manually_reconciled)),
                )
        held, unresolved = reconcile_crypto_holdings(
            wallet,
            self.pairs,
            entries,
            reconciliation_required,
        )
        self._held_quantities = held
        self._wallet_free_quantities = {
            coin: float(balance.get("Free", 0) or 0)
            for coin, balance in wallet.items()
            if coin != "USD"
        }
        self._entry_freeze_reasons = []
        if unresolved:
            self._entry_freeze_reasons.append("unreconciled exchange holdings")
            log.critical(
                "ENTRY FREEZE: exchange holdings require manual reconciliation: %s",
                ", ".join(sorted(unresolved)),
            )
            for coin in unresolved:
                marker = reconciliation_required.get(coin, {})
                diagnostic = history_diagnostics.get(coin, {})
                log.critical("RECONCILIATION REQUIRED DETAIL %s", json.dumps({
                    "coin": coin,
                    "reason": marker.get("reason") if isinstance(marker, dict) else "unknown",
                    "observed_quantity": marker.get("observed_quantity") if isinstance(marker, dict) else None,
                    "ledger_quantity": (
                        entries.get(coin, {}).get("remaining_quantity")
                        if isinstance(entries.get(coin), dict) else None
                    ),
                    "history": diagnostic,
                }, sort_keys=True))

        for coin in held:
            meta = entries.get(coin, {})
            if not (meta.get("entry_signal_bar_ts") or meta.get("entry_ts")):
                if (
                    meta.get("entry_time_status") == "unknown_operator_attested"
                    and meta.get("time_exit_policy") == UNKNOWN_TIME_POLICY
                ):
                    log.critical(
                        "TIME EXIT DISABLED by explicit reconciliation for %s: "
                        "original entry timestamp is unknown; hard-stop and signal exits remain enabled",
                        coin,
                    )
                    continue
                marker = reconciliation_required.setdefault(
                    coin,
                    {
                        "reason": "missing_entry_timestamp",
                        "first_detected_at": pd.Timestamp.now(tz="UTC").isoformat(),
                    },
                )
                marker["observed_quantity"] = held[coin]
                if coin not in self._entry_freeze_reasons:
                    self._entry_freeze_reasons.append("missing entry timestamps")
                log.critical(
                    "POSITION REQUIRES RECONCILIATION: %s has no verified entry timestamp; "
                    "X18 time exit is unavailable",
                    coin,
                )

        if reconciliation_required and not self._entry_freeze_reasons:
            self._entry_freeze_reasons.append("unreconciled exchange holdings")

        def _px(c):
            ticker = tick.get(f"{c}/USD", {})
            for key in ("LastPrice", "MaxBid", "MinAsk"):
                try:
                    value = float(ticker.get(key) or 0)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    return value
            return 0.0

        self._valuation_complete = True
        unpriced_assets = []
        for coin, value in wallet.items():
            if coin == "USD":
                continue
            qty = float(value.get("Free", 0) or 0) + float(value.get("Lock", 0) or 0)
            if qty > 0 and _px(coin) <= 0:
                self._valuation_complete = False
                unpriced_assets.append(coin)
        if unpriced_assets:
            self._entry_freeze_reasons.append("wallet contains unpriced assets")
            log.critical(
                "EQUITY VALUATION INCOMPLETE; entries frozen until ticker prices are available: %s",
                ", ".join(sorted(unpriced_assets)),
            )

        usd = wallet.get("USD", {})

        eq = (
            cash_free
            + cash_locked
            + sum(
                (float(v.get("Free", 0) or 0) + float(v.get("Lock", 0) or 0)) * _px(c)
                for c, v in wallet.items()
                if c != "USD" and _px(c) > 0
            )
        )
        log.info(
            "wallet reconciliation: USD free=%.2f locked=%.2f crypto_pool=%.2f "
            "equity_pool=%.2f crypto_holdings=%d valuation_complete=%s equity=%.2f",
            cash_free, cash_locked, self.state["pool_cash"]["crypto"],
            self.state["pool_cash"]["equity"], len(held),
            self._valuation_complete, eq,
        )

        peak = update_peak_equity(self.state, eq)

        if not self.dry:
            self.save()

        dd = (
            1 - eq / peak
            if peak > 0
            else 0.0
        )

        mult = 1.0 if self._valuation_complete else 0.0

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

        for coin in held:
            pair = f"{coin}/USD"
            ticker = tick.get(pair, {})
            executable_bid = _finite_float(ticker.get("MaxBid"))
            if executable_bid <= 0:
                reconciliation_required.setdefault(
                    coin,
                    {
                        "reason": "ticker_pair_missing" if pair not in tick else "missing_executable_bid",
                        "first_detected_at": pd.Timestamp.now(tz="UTC").isoformat(),
                    },
                )
                if "missing executable bid" not in self._entry_freeze_reasons:
                    self._entry_freeze_reasons.append("missing executable bid")
                log.critical(
                    "POSITION REQUIRES RECONCILIATION: %s has no executable MaxBid "
                    "(ticker_pair_present=%s); no automatic sale will be attempted",
                    coin, pair in tick,
                )

        if reconciliation_required and not self._entry_freeze_reasons:
            self._entry_freeze_reasons.append("unreconciled exchange holdings")

        if not self.dry:
            self.save()

        self.current_signal_bar = None
        try:
            tgt = self.signals()
        except Exception:
            log.exception(
                "signal/feed unavailable; X18 hard stops remain active, time exits and new entries are disabled"
            )
            tgt = pd.Series(dtype=float)
            self._entry_freeze_reasons.append("signal/feed unavailable")

        # X18 has priority when explicitly enabled; legacy research exits remain
        # available only when X18 is disabled.
        exit_reasons = {}
        if x18_enabled:
            current_bar = getattr(self, "current_signal_bar", None)
            unresolved_set = set(unresolved)
            for coin, qty in held.items():
                if coin in unresolved_set or coin in reconciliation_required:
                    log.critical(
                        "AUTOMATIC EXIT SUPPRESSED for unresolved %s; verified basis, timestamp, "
                        "quantity and executable bid must reconcile first",
                        coin,
                    )
                    continue
                meta = entries.get(coin, {})
                entry_px = _finite_float(meta.get("entry_price"))
                pair = f"{coin}/USD"
                sell_px = _finite_float(tick.get(pair, {}).get("MaxBid"))
                if entry_px <= 0:
                    log.critical(
                        "X18 REQUIRES MANUAL RECONCILIATION for %s: verified entry cost basis is absent; "
                        "position retained and new entries frozen",
                        coin,
                    )
                    continue
                if sell_px <= 0:
                    log.critical(
                        "X18 REQUIRES MANUAL RECONCILIATION for %s: executable MaxBid is unavailable; "
                        "position retained and new entries frozen",
                        coin,
                    )
                    continue
                if not (meta.get("entry_signal_bar_ts") or meta.get("entry_ts")) or current_bar is None:
                    log.critical(
                        "X18 time exit unavailable for %s: verified entry/current completed-bar timestamp missing; "
                        "hard-stop evaluation remains active",
                        coin,
                    )

                time_exit_disabled = (
                    meta.get("entry_time_status") == "unknown_operator_attested"
                    and meta.get("time_exit_policy") == UNKNOWN_TIME_POLICY
                    and not (
                        meta.get("entry_signal_bar_ts") or meta.get("entry_ts")
                    )
                )
                if time_exit_disabled:
                    bars_held = None
                else:
                    bars_held = completed_bars_held(
                        meta.get("entry_signal_bar_ts") or meta.get("entry_ts"),
                        current_bar,
                        self.freq,
                    )
                    if bars_held is None:
                        self._entry_freeze_reasons.append("X18 hold age unavailable")
                        log.critical(
                            "X18 TIME EXIT UNAVAILABLE for %s: timestamps are missing, invalid, "
                            "future-dated, or no completed signal bar is available; hard stop remains active",
                            coin,
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
                entry_px = _finite_float(meta.get("entry_price"))
                peak_px = _finite_float(meta.get("peak_price_since_entry"))
                pair = f"{coin}/USD"
                sell_px = _finite_float(tick.get(pair, {}).get("MaxBid"))
                if entry_px <= 0 or peak_px <= 0 or sell_px <= 0:
                    log.critical(
                        "POSITION EXIT REQUIRES RECONCILIATION for %s: "
                        "verified entry/peak or executable bid is unavailable",
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
        # Never liquidate a legacy/orphan holding using an invented basis.
        # ---------------------------------------------------------
        for coin, qty in held.items():
            if coin in reconciliation_required:
                marker = reconciliation_required[coin]
                reason = marker.get("reason") if isinstance(marker, dict) else None
                if reason == "missing_entry_timestamp" and _finite_float(
                    entries.get(coin, {}).get("entry_price")
                ) > 0:
                    pass
                else:
                    log.critical(
                        "MANUAL POSITION RECONCILIATION REQUIRED: retaining %s quantity=%s; "
                        "automatic exit is disabled until basis/market data are verified",
                        coin, held[coin],
                    )
                    continue
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

        if self._entry_freeze_reasons:
            log.critical(
                "NEW ENTRIES BLOCKED: %s",
                "; ".join(sorted(set(self._entry_freeze_reasons))),
            )
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
        cooldown_now = pd.Timestamp.now(tz="UTC")

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
            pi = self.pairs.get(pair)
            ask = _finite_float(tick.get(pair, {}).get("MinAsk"))
            if (
                not pi
                or pi.get("AssetType") != "crypto"
                or pi.get("CanTrade") is False
                or ask <= 0
            ):
                log.error(
                    "ENTRY SKIPPED %s: pair is unsupported, non-tradable, or lacks a valid MinAsk",
                    pair,
                )
                continue

            q = plan_entry(
                self.state["pool_cash"]["crypto"],
                self.cfg["pos_frac"] * mult,
                ask,
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

    @staticmethod
    def _order_detail(response):
        if not isinstance(response, dict):
            raise TypeError("Order response is not a dictionary")
        if isinstance(response.get("OrderDetail"), dict):
            return response["OrderDetail"]
        data = response.get("Data")
        if isinstance(data, dict) and isinstance(data.get("OrderDetail"), dict):
            return data["OrderDetail"]
        if "Status" in response:
            return response
        raise ValueError("Order response does not contain a recognized order detail")

    def _record_order_update(self, response) -> bool:
        pending = self.state.get("pending_order")
        if not isinstance(pending, dict):
            raise RuntimeError("Cannot record an order update without a pending order")
        previous_response = pending.get("response")
        detail = self._order_detail(response)
        status = str(detail.get("Status") or "").upper()
        pending["order_id"] = detail.get("OrderID", pending.get("order_id"))
        pending["exchange_status"] = status or None
        pending["response"] = response

        try:
            filled_qty = float(detail.get("FilledQuantity") or 0)
            fill_price = float(detail.get("FilledAverPrice") or 0)
            if filled_qty > 0 and "CommissionChargeValue" not in detail:
                raise ValueError("filled order response is missing CommissionChargeValue")
            if filled_qty > 0 and detail.get("CommissionChargeValue") is None:
                raise ValueError("filled order response has an empty CommissionChargeValue")
            cumulative_fee = float(detail.get("CommissionChargeValue") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Malformed order fill values: {exc}") from exc

        if (
            not math.isfinite(filled_qty)
            or not math.isfinite(fill_price)
            or not math.isfinite(cumulative_fee)
            or filled_qty < 0
            or cumulative_fee < 0
            or (filled_qty > 0 and fill_price <= 0)
        ):
            raise ValueError("Order response contains invalid cumulative fill values")

        legacy_accounted_fills = False
        if "accounted_filled_quantity" in pending:
            accounted_qty = _finite_float(pending["accounted_filled_quantity"], -1)
            accounted_notional = _finite_float(pending.get("accounted_notional", 0), -1)
            accounted_fee = _finite_float(pending.get("accounted_fee", 0), -1)
        elif "filled_quantity" in pending:
            # Older ledger versions applied this response's cumulative fill
            # before persisting these fields.
            legacy_accounted_fills = True
            accounted_qty = _finite_float(pending["filled_quantity"], -1)
            accounted_notional = accounted_qty * _finite_float(
                pending.get("average_fill_price")
            )
            prior_response = previous_response
            if isinstance(prior_response, dict):
                try:
                    prior_detail = self._order_detail(prior_response)
                    accounted_fee = _finite_float(
                        prior_detail.get("CommissionChargeValue"),
                        cumulative_fee,
                    )
                except (TypeError, ValueError):
                    accounted_fee = cumulative_fee
            else:
                accounted_fee = cumulative_fee
        else:
            accounted_qty = accounted_notional = accounted_fee = 0.0

        if min(accounted_qty, accounted_notional, accounted_fee) < 0:
            raise ValueError("Persisted pending-order fill accounting is invalid")
        if filled_qty + 1e-12 < accounted_qty or cumulative_fee + 1e-12 < accounted_fee:
            raise ValueError("Exchange cumulative fill values moved backwards")
        cumulative_notional = filled_qty * fill_price
        if not math.isfinite(cumulative_notional):
            raise ValueError("Order fill notional is not finite")
        delta_qty = filled_qty - accounted_qty
        delta_notional = cumulative_notional - accounted_notional
        delta_fee = cumulative_fee - accounted_fee
        if delta_notional < -max(1e-8, accounted_notional * 1e-10):
            raise ValueError("Exchange cumulative fill notional moved backwards")

        side = str(pending["side"]).upper()
        coin = str(pending["symbol"]).split("/", 1)[0]
        if delta_qty > 1e-12 or abs(delta_notional) > 1e-8 or delta_fee > 1e-12:
            pool_cash = self.state.setdefault("pool_cash", {})
            pool_cash.setdefault("crypto", 0.0)
            if side == "BUY":
                entries = self.state.setdefault("entries", {})
                meta = entries.get(coin)
                if not isinstance(meta, dict) or _finite_float(meta.get("entry_price")) <= 0:
                    meta = {}
                    entries[coin] = meta
                old_qty = _finite_float(meta.get("remaining_quantity"))
                if legacy_accounted_fills and "remaining_quantity" not in meta:
                    old_qty = accounted_qty
                old_price = _finite_float(meta.get("entry_price"))
                new_qty = old_qty + delta_qty
                if new_qty > 0:
                    new_cost = old_qty * old_price + delta_notional
                    new_price = new_cost / new_qty
                    if not math.isfinite(new_price) or new_price <= 0:
                        raise ValueError("Unable to derive a positive average entry cost from confirmed fills")
                    commission_coin = str(detail.get("CommissionCoin") or "USD").upper()
                    quote_fee_delta = delta_fee if commission_coin == "USD" else 0.0
                    base_fee_delta = delta_fee if commission_coin == coin else 0.0
                    old_cost_basis = _finite_float(meta.get("entry_cost_basis"), old_price)
                    new_cost_basis = (
                        old_qty * old_cost_basis + delta_notional + quote_fee_delta
                    ) / new_qty
                    pool_cash["crypto"] -= delta_notional + delta_fee
                    meta.update(
                        {
                            "entry_price": new_price,
                            "entry_cost_basis": new_cost_basis,
                            "entry_fees_quote": _finite_float(meta.get("entry_fees_quote")) + quote_fee_delta,
                            "entry_fees_base": _finite_float(meta.get("entry_fees_base")) + base_fee_delta,
                            "remaining_quantity": new_qty,
                            "entry_quantity": _finite_float(
                                meta.get("entry_quantity"), old_qty
                            ) + delta_qty,
                            "entry_ts": meta.get("entry_ts") or pd.Timestamp.now(tz="UTC").isoformat(),
                            "entry_signal_bar_ts": (
                                meta.get("entry_signal_bar_ts")
                                or (
                                    pd.Timestamp(self.current_signal_bar).isoformat()
                                    if getattr(self, "current_signal_bar", None) is not None
                                    else None
                                )
                            ),
                            "peak_price_since_entry": max(
                                float(meta.get("peak_price_since_entry", 0) or 0),
                                fill_price,
                            ),
                            "trough_price_since_entry": min(
                                float(meta.get("trough_price_since_entry") or fill_price),
                                fill_price,
                            ),
                        }
                    )
                    meta.setdefault("mfe", 0.0)
                    meta.setdefault("mae", 0.0)
                    self.state.setdefault("reconciliation_required", {}).pop(coin, None)
                    held_qtys = getattr(self, "_held_quantities", None)
                    if held_qtys is None:
                        held_qtys = self._held_quantities = {}
                    held_qtys[coin] = _finite_float(held_qtys.get(coin)) + delta_qty
                    free_qtys = getattr(self, "_wallet_free_quantities", None)
                    if free_qtys is not None:
                        free_qtys[coin] = _finite_float(free_qtys.get(coin)) + delta_qty
            elif side == "SELL":
                pool_cash["crypto"] += delta_notional - delta_fee
                meta = self.state.setdefault("entries", {}).get(coin)
                if isinstance(meta, dict):
                    remaining = max(
                        0.0,
                        _finite_float(meta.get("remaining_quantity")) - delta_qty,
                    )
                    meta["remaining_quantity"] = remaining
                    if remaining == 0:
                        self.state["entries"].pop(coin, None)
                held_qtys = getattr(self, "_held_quantities", None)
                if held_qtys is not None:
                    held_qtys[coin] = max(
                        0.0,
                        _finite_float(held_qtys.get(coin)) - delta_qty,
                    )
                free_qtys = getattr(self, "_wallet_free_quantities", None)
                if free_qtys is not None:
                    free_qtys[coin] = max(
                        0.0,
                        _finite_float(free_qtys.get(coin)) - delta_qty,
                    )
                else:
                    self.state.setdefault("reconciliation_required", {})[coin] = {
                        "reason": "confirmed_sell_fill_without_entry_metadata",
                        "observed_quantity": None,
                        "first_detected_at": pd.Timestamp.now(tz="UTC").isoformat(),
                    }
            else:
                raise ValueError(f"Unsupported pending order side: {side}")

        pending["accounted_filled_quantity"] = filled_qty
        pending["accounted_notional"] = cumulative_notional
        pending["accounted_fee"] = cumulative_fee
        pending["filled_quantity"] = filled_qty
        pending["average_fill_price"] = fill_price
        self.save()

        requested_qty = float(pending["quantity"])
        fill_tolerance = max(1e-12, requested_qty * 1e-8)
        fully_filled = status == "FILLED" and filled_qty + fill_tolerance >= requested_qty
        overfilled = filled_qty > requested_qty + fill_tolerance
        terminal_statuses = {"FILLED", "REJECTED", "CANCELED", "CANCELLED", "EXPIRED"}
        if status in terminal_statuses and not overfilled and not (
            status == "FILLED" and not fully_filled
        ):
            self.state.pop("pending_order", None)
            self.save()
            if filled_qty:
                log.info(
                    "order terminal status=%s symbol=%s cumulative_fill=%s @ %s fee=%s",
                    status, pending["symbol"], filled_qty, fill_price, cumulative_fee,
                )
            else:
                log.warning("order terminal without fill status=%s symbol=%s", status, pending["symbol"])
            return fully_filled or (side == "BUY" and filled_qty > 0)

        pending["status"] = "partial_fill" if filled_qty > 0 else "reconciliation_required"
        self.save()
        log.critical(
            "ORDER NOT CONFIRMED COMPLETE: %s status=%s requested=%s filled=%s; "
            "submission remains journaled and new orders are blocked",
            pending["symbol"], status or "UNKNOWN", requested_qty, filled_qty,
        )
        return False

    def _recover_pending_order(self) -> bool:
        pending = self.state.get("pending_order")
        if not isinstance(pending, dict):
            return True
        order_id = pending.get("order_id")
        if not order_id:
            log.critical(
                "PENDING ORDER REQUIRES MANUAL RECONCILIATION: exchange order id is unknown; "
                "no retry will be submitted",
            )
            return False
        try:
            response = self.api.query_order(order_id=str(order_id))
            return self._record_order_update(response)
        except Exception:
            log.exception(
                "PENDING ORDER RECONCILIATION FAILED for order_id=%s; trading remains blocked",
                order_id,
            )
            return False

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
            or not pair_info.get("CanTrade")
        ):
            log.warning(
                "BLOCKED non-crypto order: %s %s",
                side,
                coin,
            )
            return False

        pair = f"{coin}/USD"
        side = str(side).upper()

        if side not in {"BUY", "SELL"}:
            return False
        try:
            qty = float(qty)
            precision = int(pair_info.get("AmountPrecision", 8))
            normalized_qty = floor_qty(qty, precision)
            minimum_order = _finite_float(pair_info.get("MiniOrder", 0), -1)
        except (TypeError, ValueError, OverflowError):
            log.error("BLOCKED order with invalid quantity or exchange precision: %s %s", side, pair)
            return False
        if not math.isfinite(qty) or qty <= 0 or precision < 0 or precision > 10 or minimum_order < 0:
            log.error("BLOCKED order with invalid exchange constraints: %s %s", side, pair)
            return False
        if not math.isfinite(qty) or normalized_qty <= 0 or abs(qty - normalized_qty) > max(1e-12, qty * 1e-10):
            log.error(
                "BLOCKED order quantity violates exchange precision: %s %s qty=%s precision=%s",
                side, pair, qty, precision,
            )
            return False

        ticker = tick.get(pair, {})
        price_field = "MinAsk" if side == "BUY" else "MaxBid"
        try:
            reference_price = float(ticker.get(price_field) or 0)
        except (TypeError, ValueError):
            reference_price = 0.0
        if not math.isfinite(reference_price) or reference_price <= 0:
            log.critical(
                "BLOCKED %s %s: executable reference %s is unavailable",
                side, pair, price_field,
            )
            return False
        notional = qty * reference_price
        if notional < minimum_order:
            log.error(
                "BLOCKED order below exchange minimum: %s %s notional=%.8f minimum=%.8f",
                side, pair, notional, minimum_order,
            )
            return False

        if side == "SELL":
            free_qty = getattr(self, "_wallet_free_quantities", {}).get(coin)
            if free_qty is not None and qty > free_qty + max(1e-12, free_qty * 1e-10):
                log.error(
                    "BLOCKED sell exceeds exchange free balance: %s requested=%s free=%s",
                    pair, qty, free_qty,
                )
                return False
        else:
            if self._held_quantities.get(coin, 0) > 0:
                log.error("BLOCKED duplicate entry for already-held asset %s", pair)
                return False
            cash = _finite_float(self.state.get("pool_cash", {}).get("crypto", 0))
            configured_fraction = _finite_float(
                getattr(self, "cfg", {}).get("pos_frac", 1.0), -1
            )
            multiplier = _finite_float(
                getattr(self, "order_context", {}).get("dd_multiplier"), 1.0
            )
            if not 0 <= configured_fraction <= 1 or multiplier < 0:
                log.error("BLOCKED buy due to invalid configured sizing/risk multiplier")
                return False
            cash_limit = min(
                max(0.0, cash / (1.0 + TAKER_FEE)),
                max(0.0, cash * configured_fraction * multiplier),
            )
            if notional > cash_limit + max(1e-8, cash_limit * 1e-10):
                log.error(
                    "BLOCKED buy exceeds available allocation: %s notional=%.8f limit=%.8f cash=%.8f",
                    pair, notional, cash_limit, cash,
                )
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
                "ts": pd.Timestamp.now(tz='UTC').isoformat(),
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
            if side == "BUY":
                self.state["pool_cash"]["crypto"] = max(
                    0.0,
                    _finite_float(self.state.get("pool_cash", {}).get("crypto"))
                    - notional * (1.0 + TAKER_FEE),
                )
                self._held_quantities[coin] = (
                    self._held_quantities.get(coin, 0.0) + qty
                )
                if coin in self._wallet_free_quantities:
                    self._wallet_free_quantities[coin] += qty
            else:
                self.state["pool_cash"]["crypto"] = (
                    _finite_float(self.state.get("pool_cash", {}).get("crypto"))
                    + notional * (1.0 - TAKER_FEE)
                )
                self._held_quantities[coin] = max(
                    0.0,
                    self._held_quantities.get(coin, 0.0) - qty,
                )
                if coin in self._wallet_free_quantities:
                    self._wallet_free_quantities[coin] = max(
                        0.0,
                        self._wallet_free_quantities[coin] - qty,
                    )
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
            return self._record_order_update(d)
        except (AttributeError, TypeError, ValueError, RuntimeError) as e:
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

    def run(self):
        lock_path = self.state_path.with_suffix(".lock")
        with InstanceLock(lock_path):
            self._instance_lock_held = True
            if self.state_path.exists():
                self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
                self.state.setdefault("entries", {})
                self.state.setdefault("pool_cash", {"crypto": 0.0, "equity": 0.0})
            log.info("single bot instance lock acquired: %s", lock_path)
            try:
                while True:
                    try:
                        self.cycle()
                    except Exception:
                        log.exception("cycle failed - holding")

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
            finally:
                self._instance_lock_held = False