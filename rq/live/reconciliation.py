"""Reconcile exchange-held crypto balances with verified execution metadata."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UNKNOWN_TIME_POLICY = "disable_time_exit_until_verified_timestamp"
_RECONCILABLE_REASONS = {
    "missing_verified_entry_cost_basis",
    "missing_entry_timestamp",
    "exchange_local_quantity_mismatch",
    "execution_history_quantity_mismatch",
}
_MANUAL_CLEARABLE_REASONS = _RECONCILABLE_REASONS | {
    "execution_history_basis_mismatch",
}


def _balance_quantity(balance: dict[str, Any]) -> float:
    free = float(balance.get("Free", 0) or 0)
    locked = float(balance.get("Lock", 0) or 0)
    quantity = free + locked
    if not math.isfinite(quantity) or quantity < 0:
        raise ValueError(f"invalid exchange balance quantity: {quantity!r}")
    return quantity


def execution_journal_scope(api_key: str) -> str:
    """Return a stable, non-secret account identifier for journal isolation."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _valid_entry_price(meta: Any) -> bool:
    if not isinstance(meta, dict):
        return False
    try:
        value = float(meta.get("entry_price") or 0)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value > 0


def _aware_timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp.astimezone(timezone.utc).isoformat()


def _quantity_tolerance(quantity: float, pair_info: dict[str, Any]) -> float:
    try:
        precision = int(pair_info.get("AmountPrecision", 8))
    except (TypeError, ValueError):
        precision = 8
    if precision < 0 or precision > 12:
        raise ValueError(f"invalid exchange amount precision: {precision}")
    return max(1e-12, 0.5 * 10 ** (-precision), abs(quantity) * 1e-10)


def reconcile_crypto_holdings(
    wallet: dict[str, Any],
    pairs: dict[str, Any],
    entries: dict[str, Any],
    reconciliation_required: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[dict[str, float], list[str]]:
    """Return held crypto quantities and mark any unverifiable positions."""
    held: dict[str, float] = {}
    unresolved: list[str] = []
    wallet_assets = {
        asset
        for asset, balance in wallet.items()
        if asset != "USD" and _balance_quantity(balance) > 0
    }
    detected_at = (now or datetime.now(timezone.utc)).isoformat()

    for coin, raw_balance in wallet.items():
        if coin == "USD":
            continue
        if not isinstance(raw_balance, dict):
            raise ValueError(f"invalid exchange balance for {coin}")

        quantity = _balance_quantity(raw_balance)
        if quantity <= 0:
            continue

        pair = f"{coin}/USD"
        pair_info = pairs.get(pair)
        if not isinstance(pair_info, dict) or pair_info.get("AssetType") != "crypto":
            reconciliation_required[coin] = {
                "reason": "held_asset_not_in_supported_crypto_pairs",
                "observed_quantity": quantity,
                "first_detected_at": detected_at,
            }
            unresolved.append(coin)
            continue

        held[coin] = quantity
        if not pair_info.get("CanTrade"):
            reconciliation_required[coin] = {
                "reason": "exchange_pair_not_tradable",
                "observed_quantity": quantity,
                "pair": pair,
                "first_detected_at": detected_at,
            }
            unresolved.append(coin)
            continue

        meta = entries.get(coin)
        if not _valid_entry_price(meta):
            if not isinstance(meta, dict):
                meta = {}
                entries[coin] = meta
            marker = reconciliation_required.setdefault(
                coin,
                {
                    "reason": "missing_verified_entry_cost_basis",
                    "first_detected_at": detected_at,
                },
            )
            marker["observed_quantity"] = quantity
            marker["pair"] = pair
            unresolved.append(coin)
            continue

        assert isinstance(meta, dict)
        entry_ts = _aware_timestamp(
            meta.get("entry_signal_bar_ts") or meta.get("entry_ts")
        )
        time_unknown_is_acknowledged = (
            meta.get("entry_time_status") == "unknown_operator_attested"
            and meta.get("time_exit_policy") == UNKNOWN_TIME_POLICY
        )
        if entry_ts is None and not time_unknown_is_acknowledged:
            reconciliation_required[coin] = {
                "reason": "missing_entry_timestamp",
                "observed_quantity": quantity,
                "pair": pair,
                "first_detected_at": detected_at,
            }
            unresolved.append(coin)
            continue

        local_quantity = _finite_positive(meta.get("remaining_quantity"))
        if (
            local_quantity is None
            or abs(local_quantity - quantity)
            > _quantity_tolerance(quantity, pair_info)
        ):
            reconciliation_required[coin] = {
                "reason": "exchange_local_quantity_mismatch",
                "observed_quantity": quantity,
                "ledger_quantity": local_quantity,
                "pair": pair,
                "first_detected_at": detected_at,
            }
            unresolved.append(coin)
            continue

        meta["remaining_quantity"] = quantity
        marker = reconciliation_required.get(coin)
        if (
            not isinstance(marker, dict)
            or marker.get("reason") in _RECONCILABLE_REASONS
        ):
            reconciliation_required.pop(coin, None)
        else:
            unresolved.append(coin)

    for coin in list(entries):
        if coin not in held:
            entries.pop(coin, None)
    for coin in list(reconciliation_required):
        if coin not in wallet_assets:
            reconciliation_required.pop(coin, None)

    return held, unresolved


def _finite_positive(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _absolute_positive(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = abs(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _order_details(response: Any) -> list[dict[str, Any]]:
    """Normalize place-order and documented query-order response shapes."""
    if not isinstance(response, dict) or response.get("Success") is False:
        return []
    detail = response.get("OrderDetail")
    if isinstance(detail, dict):
        return [detail]
    data = response.get("Data")
    if isinstance(data, dict) and isinstance(data.get("OrderDetail"), dict):
        return [data["OrderDetail"]]
    matched = response.get("OrderMatched")
    if isinstance(matched, list):
        return [item for item in matched if isinstance(item, dict)]
    if "Status" in response:
        return [response]
    return []


def _exchange_timestamp(value: Any) -> str | None:
    """Parse an exchange timestamp in ISO-8601 or Roostoo epoch milliseconds."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)) or float(value) <= 0:
            return None
        seconds = float(value) / 1000.0 if float(value) > 100_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return _aware_timestamp(value)


def _detail_create_epoch(detail: dict[str, Any]) -> float | None:
    value = detail.get("CreateTimestamp")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if math.isfinite(numeric) and numeric > 0:
            return numeric / 1000.0 if numeric > 100_000_000_000 else numeric
    return None


def _detail_fill_timestamp(detail: dict[str, Any]) -> str | None:
    for key in ("FilledTime", "LastFilledTime", "TransactTime"):
        timestamp = _exchange_timestamp(detail.get(key))
        if timestamp is not None:
            return timestamp
    # FinishTimestamp is a fill time only when the exchange says the order FILLED.
    if str(detail.get("Status", "")).upper() == "FILLED":
        return _exchange_timestamp(detail.get("FinishTimestamp"))
    return None


def recover_from_execution_journal(
    journal_path: str | Path | None,
    wallet: dict[str, Any],
    pairs: dict[str, Any],
    entries: dict[str, Any],
    reconciliation_required: dict[str, Any],
    *,
    account_scope: str | None,
    additional_events: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Recover positions from account-scoped journal records and exchange history."""
    if not account_scope:
        return []
    orders: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    path = Path(journal_path) if journal_path is not None else None
    if path is not None and path.exists():
        with path.open(encoding="utf-8") as journal:
            for line_number, line in enumerate(journal, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid execution journal JSON at {path}:{line_number}") from exc
                if not isinstance(event, dict):
                    raise ValueError(f"invalid execution journal record at {path}:{line_number}")
                events.append(event)
    events.extend(additional_events or [])

    for event in events:
        if not isinstance(event, dict) or event.get("account_scope") != account_scope:
            continue
        api_path = event.get("path")
        if api_path not in {"/v3/place_order", "/v3/query_order"}:
            continue
        response = event.get("resp")
        details = _order_details(response)
        if not details:
            continue
        params = event.get("params")
        params = params if isinstance(params, dict) else {}
        observed_at = _finite_nonnegative(event.get("t"))
        for detail in details:
            order_id = detail.get("OrderID") or params.get("order_id")
            if order_id is None:
                continue
            order_id = str(order_id)
            create_epoch = _detail_create_epoch(detail)
            order_time = create_epoch if create_epoch is not None else observed_at
            record = orders.setdefault(order_id, {
                "order_id": order_id, "first_seen": order_time, "detail": None,
                "pair": None, "side": None, "submitted": False,
                "first_fill_observed": False, "first_fill_timestamp": None,
                "from_exchange_history": False,
            })
            if order_time is not None:
                record["first_seen"] = order_time if record["first_seen"] is None else min(record["first_seen"], order_time)
            record["pair"] = detail.get("Pair") or params.get("pair") or record["pair"]
            side = detail.get("Side") or params.get("side") or record["side"]
            record["side"] = str(side).upper() if side is not None else None
            # Authenticated query-order responses are proof of an order even if
            # the original place_order predates this local journal.
            record["submitted"] = True
            if api_path == "/v3/query_order" and isinstance(response, dict) and isinstance(response.get("OrderMatched"), list):
                record["from_exchange_history"] = True
            previous_detail = record["detail"]
            record["detail"] = {**previous_detail, **detail} if isinstance(previous_detail, dict) else detail
            cumulative_fill = _finite_nonnegative(detail.get("FilledQuantity"))
            if cumulative_fill is not None and cumulative_fill > 0:
                record["first_fill_observed"] = True
                # Backfill a missing timestamp from exchange data only.
                if record["first_fill_timestamp"] is None:
                    record["first_fill_timestamp"] = _detail_fill_timestamp(detail)

    by_coin: dict[str, list[dict[str, Any]]] = {}
    for record in orders.values():
        pair = record["pair"]
        side = str(record["side"] or "").upper()
        detail = record["detail"]
        if (
            not record["submitted"]
            or not isinstance(pair, str)
            or "/" not in pair
            or side not in {"BUY", "SELL"}
        ):
            continue
        coin = pair.split("/", 1)[0]
        if pair != f"{coin}/USD":
            continue
        if coin not in wallet or _balance_quantity(wallet[coin]) <= 0:
            continue
        if not isinstance(detail, dict):
            continue
        filled = _finite_nonnegative(detail.get("FilledQuantity"))
        price = _finite_positive(detail.get("FilledAverPrice"))
        if filled is None or filled <= 0 or price is None:
            continue
        by_coin.setdefault(coin, []).append(record)

    recovered: list[str] = []
    for coin, coin_orders in by_coin.items():
        pair = f"{coin}/USD"
        pair_info = pairs.get(pair)
        if not isinstance(pair_info, dict) or pair_info.get("AssetType") != "crypto" or not pair_info.get("CanTrade"):
            continue
        current_meta = entries.get(coin)
        if (
            isinstance(current_meta, dict)
            and current_meta.get("manual_reconciliation")
            and _valid_entry_price(current_meta)
        ):
            continue

        lots: list[dict[str, Any]] = []
        total_bought = 0.0
        position_quantity = 0.0
        average_basis = 0.0  # gross weighted fill price used by X18
        average_cost_basis = 0.0  # fee-inclusive quote cost per remaining coin
        entry_fees_quote = 0.0
        entry_fees_base = 0.0
        ambiguous = False
        for record in sorted(
            coin_orders,
            key=lambda item: (
                item["first_seen"] if item["first_seen"] is not None else float("inf"),
                item["order_id"],
            ),
        ):
            detail = record["detail"]
            quantity = _finite_nonnegative(detail.get("FilledQuantity"))
            price = _finite_positive(detail.get("FilledAverPrice"))
            if quantity is None or quantity <= 0 or price is None:
                continue
            fee_amount = _finite_nonnegative(detail.get("CommissionChargeValue"))
            fee_coin = str(detail.get("CommissionCoin") or "").upper()
            if fee_amount is None:
                rate = _finite_positive(detail.get("CommissionPercent"))
                if rate is not None:
                    ambiguous = True
                    break
                fee_amount, fee_coin = 0.0, "USD"
            if fee_amount > 0 and fee_coin not in {"USD", coin}:
                ambiguous = True
                break
            if record["side"] == "BUY":
                acquired_quantity = quantity
                quote_cost = quantity * price
                if fee_amount > 0 and fee_coin == "USD":
                    quote_cost += fee_amount
                elif fee_amount > 0 and fee_coin == coin:
                    coin_delta = _absolute_positive(detail.get("CoinChange"))
                    acquired_quantity = coin_delta if coin_delta is not None else quantity - fee_amount
                if acquired_quantity <= 0:
                    ambiguous = True
                    break
                quote_fee = fee_amount if fee_coin == "USD" else 0.0
                base_fee = fee_amount if fee_coin == coin else 0.0
                total_bought += acquired_quantity
                average_basis = (
                    (position_quantity * average_basis + acquired_quantity * price)
                    / (position_quantity + acquired_quantity)
                )
                average_cost_basis = (
                    (position_quantity * average_cost_basis + quote_cost)
                    / (position_quantity + acquired_quantity)
                )
                entry_fees_quote += quote_fee
                entry_fees_base += base_fee
                position_quantity += acquired_quantity
                lots.append({"quantity": acquired_quantity, "price": price, "timestamp": record["first_fill_timestamp"]})
                continue
            sold_quantity = quantity
            if fee_amount > 0 and fee_coin == coin:
                coin_delta = _absolute_positive(detail.get("CoinChange"))
                sold_quantity = coin_delta if coin_delta is not None else quantity + fee_amount
            remaining_to_sell = sold_quantity
            while remaining_to_sell > 1e-12 and lots:
                consumed = min(remaining_to_sell, lots[0]["quantity"])
                lots[0]["quantity"] -= consumed
                remaining_to_sell -= consumed
                if lots[0]["quantity"] <= 1e-12:
                    lots.pop(0)
            if remaining_to_sell > 1e-12:
                ambiguous = True
                break
            # Average cost is unchanged by partial sales; FIFO tracks the oldest surviving lot.
            position_quantity = max(0.0, position_quantity - sold_quantity)
            if position_quantity <= 1e-12:
                position_quantity = 0.0
                average_basis = 0.0
                average_cost_basis = 0.0
                entry_fees_quote = 0.0
                entry_fees_base = 0.0
                total_bought = 0.0

        wallet_quantity = _balance_quantity(wallet[coin])
        reconstructed_quantity = sum(lot["quantity"] for lot in lots)
        tolerance = _quantity_tolerance(wallet_quantity, pair_info)
        if (
            ambiguous
            or reconstructed_quantity <= 0
            or abs(reconstructed_quantity - wallet_quantity) > tolerance
        ):
            reconciliation_required[coin] = {
                "reason": "execution_history_quantity_mismatch",
                "observed_quantity": wallet_quantity,
                "execution_history_quantity": reconstructed_quantity,
                "pair": pair,
            }
            continue

        basis = average_basis
        oldest_remaining = lots[0]
        entry_ts = oldest_remaining["timestamp"]
        if isinstance(current_meta, dict) and _valid_entry_price(current_meta):
            local_quantity = _finite_positive(current_meta.get("remaining_quantity"))
            quantity_matches = (
                local_quantity is not None
                and abs(local_quantity - wallet_quantity) <= tolerance
            )
            current_timestamp = _aware_timestamp(
                current_meta.get("entry_signal_bar_ts") or current_meta.get("entry_ts")
            )
            basis_matches = math.isclose(
                float(current_meta["entry_price"]),
                basis,
                rel_tol=1e-8,
                abs_tol=1e-8,
            )
            if quantity_matches and not basis_matches:
                reconciliation_required[coin] = {
                    "reason": "execution_history_basis_mismatch",
                    "observed_quantity": wallet_quantity,
                    "ledger_entry_price": float(current_meta["entry_price"]),
                    "execution_history_entry_price": basis,
                    "pair": pair,
                }
                continue
            if quantity_matches and current_timestamp is not None:
                continue
            if quantity_matches and entry_ts is None:
                continue

        recovered_metadata = {
            **(current_meta if isinstance(current_meta, dict) else {}),
            "entry_price": basis,
            "entry_cost_basis": average_cost_basis,
            "entry_fees_quote": entry_fees_quote,
            "entry_fees_base": entry_fees_base,
            "remaining_quantity": wallet_quantity,
            "entry_quantity": total_bought,
            "entry_ts": entry_ts,
            "entry_signal_bar_ts": entry_ts,
            "peak_price_since_entry": basis,
            "trough_price_since_entry": basis,
            "mfe": 0.0,
            "mae": 0.0,
            "entry_source": {
                "type": (
                    "exchange_order_history"
                    if any(record.get("from_exchange_history") for record in coin_orders)
                    else "execution_journal"
                ),
                "order_ids": [record["order_id"] for record in coin_orders],
            },
        }
        if entry_ts is not None:
            recovered_metadata["entry_time_status"] = "verified"
            recovered_metadata["time_exit_policy"] = "verified_timestamp"
        if isinstance(current_meta, dict) and _valid_entry_price(current_meta):
            if _finite_positive(current_meta.get("peak_price_since_entry")):
                recovered_metadata["peak_price_since_entry"] = max(
                    float(current_meta["peak_price_since_entry"]), basis
                )
            if _finite_positive(current_meta.get("trough_price_since_entry")):
                recovered_metadata["trough_price_since_entry"] = min(
                    float(current_meta["trough_price_since_entry"]), basis
                )
            if basis_matches:
                for key in ("mfe", "mae"):
                    metric = current_meta.get(key)
                    if isinstance(metric, (int, float)) and math.isfinite(metric):
                        recovered_metadata[key] = metric
        entries[coin] = recovered_metadata
        recovered.append(coin)
    return recovered


def apply_manual_reconciliation(
    document: dict[str, Any],
    wallet: dict[str, Any],
    pairs: dict[str, Any],
    entries: dict[str, Any],
    reconciliation_required: dict[str, Any],
    audit: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[str]:
    """Apply explicitly sourced operator attestations after strict validation."""
    positions = document.get("positions")
    if not isinstance(positions, dict):
        raise ValueError("manual reconciliation must contain a positions object")
    applied: list[str] = []
    applied_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()

    for coin, record in positions.items():
        if not isinstance(coin, str) or not coin or not isinstance(record, dict):
            raise ValueError("manual reconciliation positions must map symbols to objects")
        record_id = record.get("record_id")
        operator = record.get("operator")
        source = record.get("source")
        if not all(isinstance(value, str) and value.strip() for value in (record_id, operator, source)):
            raise ValueError(f"{coin}: record_id, operator, and evidence source are required")
        entry_price = _finite_positive(record.get("entry_price"))
        quantity = _finite_positive(record.get("remaining_quantity"))
        if entry_price is None or quantity is None:
            raise ValueError(f"{coin}: entry_price and remaining_quantity must be finite positive numbers")

        raw_entry_ts = record.get("entry_ts")
        entry_ts = _aware_timestamp(raw_entry_ts)
        unknown_timestamp = record.get("entry_timestamp_unknown") is True
        if entry_ts is None:
            if raw_entry_ts is not None:
                raise ValueError(f"{coin}: entry_ts must be a timezone-aware ISO timestamp")
            if not unknown_timestamp or record.get("time_exit_policy") != UNKNOWN_TIME_POLICY:
                raise ValueError(
                    f"{coin}: provide a timezone-aware entry_ts or explicitly attest unknown time "
                    f"with time_exit_policy={UNKNOWN_TIME_POLICY!r}"
                )
        elif unknown_timestamp:
            raise ValueError(f"{coin}: entry_ts and entry_timestamp_unknown cannot both be set")

        if "entry_cost_basis" in record:
            entry_cost_basis = _finite_positive(record.get("entry_cost_basis"))
            if entry_cost_basis is None:
                raise ValueError(f"{coin}: entry_cost_basis must be finite and positive")
        else:
            # Backward compatibility for previously documented manual records.
            entry_cost_basis = entry_price
        canonical = {
            "record_id": record_id.strip(),
            "operator": operator.strip(),
            "source": source.strip(),
            "entry_price": entry_price,
            "entry_cost_basis": entry_cost_basis,
            "remaining_quantity": quantity,
            "entry_ts": entry_ts,
            "entry_timestamp_unknown": unknown_timestamp,
            "time_exit_policy": (
                UNKNOWN_TIME_POLICY if unknown_timestamp else "verified_timestamp"
            ),
        }
        prior_audit = [
            item for item in audit if item.get("record_id") == record_id
        ]
        if prior_audit:
            prior_canonical = dict(prior_audit[0]) if len(prior_audit) == 1 else {}
            prior_canonical.setdefault("entry_cost_basis", prior_canonical.get("entry_price"))
            if len(prior_audit) == 1 and prior_audit[0].get("coin") == coin and all(
                prior_canonical.get(key) == value
                for key, value in canonical.items()
            ):
                continue
            raise ValueError(
                f"{coin}: record_id {record_id!r} was already used with different data"
            )

        pair = f"{coin}/USD"
        pair_info = pairs.get(pair)
        if not isinstance(pair_info, dict) or pair_info.get("AssetType") != "crypto" or not pair_info.get("CanTrade"):
            raise ValueError(f"{coin}: manual reconciliation requires a supported tradable crypto pair")
        if coin not in wallet or not isinstance(wallet[coin], dict):
            raise ValueError(f"{coin}: no matching exchange wallet balance")
        observed_quantity = _balance_quantity(wallet[coin])
        if abs(quantity - observed_quantity) > _quantity_tolerance(observed_quantity, pair_info):
            raise ValueError(
                f"{coin}: declared quantity {quantity} does not match exchange quantity {observed_quantity}"
            )

        existing = entries.get(coin, {})
        if isinstance(existing, dict) and existing.get("manual_reconciliation") == canonical:
            audit.append(
                {
                    **canonical,
                    "coin": coin,
                    "applied_at": applied_at,
                    "previous_metadata": {},
                    "audit_repaired": True,
                }
            )
            applied.append(coin)
            continue

        previous_metadata = dict(existing) if isinstance(existing, dict) else {}
        entries[coin] = {
            **previous_metadata,
            "entry_price": entry_price,
            "entry_cost_basis": entry_cost_basis,
            "remaining_quantity": quantity,
            "entry_quantity": max(quantity, _finite_positive(previous_metadata.get("entry_quantity")) or 0),
            "entry_ts": entry_ts,
            "entry_signal_bar_ts": entry_ts,
            "entry_time_status": (
                "unknown_operator_attested" if unknown_timestamp else "verified"
            ),
            "time_exit_policy": (
                UNKNOWN_TIME_POLICY if unknown_timestamp else "verified_timestamp"
            ),
            "entry_source": {"type": "manual_reconciliation", "source": source.strip()},
            "manual_reconciliation": canonical,
            "peak_price_since_entry": _finite_positive(
                previous_metadata.get("peak_price_since_entry")
            ) or entry_price,
            "trough_price_since_entry": _finite_positive(
                previous_metadata.get("trough_price_since_entry")
            ) or entry_price,
            "mfe": _finite_nonnegative(previous_metadata.get("mfe")) or 0.0,
            "mae": previous_metadata.get("mae", 0.0),
        }
        audit.append(
            {
                **canonical,
                "coin": coin,
                "applied_at": applied_at,
                "previous_metadata": previous_metadata,
            }
        )
        marker = reconciliation_required.get(coin)
        if not isinstance(marker, dict) or marker.get("reason") in _MANUAL_CLEARABLE_REASONS:
            reconciliation_required.pop(coin, None)
        applied.append(coin)
    return applied


def _finite_nonnegative(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result >= 0 else None
