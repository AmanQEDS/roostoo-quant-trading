"""Reconcile exchange-held crypto balances with persisted entry metadata."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _balance_quantity(balance: dict[str, Any]) -> float:
    free = float(balance.get("Free", 0) or 0)
    locked = float(balance.get("Lock", 0) or 0)
    quantity = free + locked
    if not math.isfinite(quantity) or quantity < 0:
        raise ValueError(f"invalid exchange balance quantity: {quantity!r}")
    return quantity


def _valid_entry_price(meta: Any) -> bool:
    if not isinstance(meta, dict):
        return False
    try:
        value = float(meta.get("entry_price") or 0)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value > 0


def reconcile_crypto_holdings(
    wallet: dict[str, Any],
    pairs: dict[str, Any],
    entries: dict[str, Any],
    reconciliation_required: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[dict[str, float], list[str]]:
    """Return held crypto quantities and mark any unverifiable positions.

    Missing basis is deliberately never inferred from ticker prices. Untracked
    holdings are retained for explicit manual reconciliation and must not be
    silently treated as new strategy entries.
    """
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

        meta["remaining_quantity"] = quantity
        reconciliation_required.pop(coin, None)

    for coin in list(entries):
        if coin not in held:
            entries.pop(coin, None)
    for coin in list(reconciliation_required):
        if coin not in wallet_assets:
            reconciliation_required.pop(coin, None)

    return held, unresolved
