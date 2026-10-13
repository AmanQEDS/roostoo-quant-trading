"""Portfolio backtest engine.

Timing (identical for backtest and live design):
    close of bar i -> indicators/signals/risk use rows <= i
    order decided at i  -> filled at panel.exec_px[i] (+ slippage), i.e. strictly AFTER the information.
Accounting:
    * two separate USD pools (crypto / equity) funded ONCE from `crypto_weight` and never rebalanced.
    * SEQUENTIAL ALLOCATION: a new position gets  pos_frac x (pool cash available *right now*)
      (not pos_frac x total equity).  Sizes therefore shrink geometrically as the pool fills:
      with pos_frac=10%, the n-th position is 10% of what is left, max deployed = 1-(1-p)^n.
    * fee on every fill (taker 0.1% default); shorts follow Roostoo's collateral model:
      collateral locked + 0.1% open fee; closed at ask; loss capped at collateral.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from ..constants import TAKER_FEE, INITIAL_CAPITAL
from .risk import RiskConfig, vol_scale_matrix
from .. import indicators as I

CLS = {"crypto": 0, "equity": 1}


@dataclass
class PortfolioConfig:
    capital: float = INITIAL_CAPITAL
    crypto_weight: float = 0.30
    pos_frac: float = 0.10
    max_pos: dict = field(default_factory=lambda: {"crypto": 5, "equity": 10})
    fee: float = TAKER_FEE
    slip_bps: dict = field(default_factory=lambda: {"crypto": 2.0, "equity": 5.0})
    allow_short: bool = False
    min_order_usd: float = 1.0
    risk: RiskConfig = field(default_factory=RiskConfig)

    def tag(self) -> str:
        return (f"cw{int(self.crypto_weight*100)}_pf{int(self.pos_frac*100)}_mp{self.max_pos['crypto']}-{self.max_pos['equity']}"
                f"_{'LS' if self.allow_short else 'L'}_fee{self.fee*1e4:.0f}bp")


@dataclass(frozen=True)
class ExitConfig:
    """Research-only, stateful long-position exit rules; default X0 preserves the signal exit."""
    variant: str = "X0"
    atr_n: int = 14
    chandelier_k: float = 3.0
    breakeven_atr: float = 1.5
    trailing_pct: float = 0.05
    giveback_trigger_atr: float = 1.0
    giveback_fraction: float = 0.5
    donchian_n: int = 24
    partial_r: float = 1.5
    cooldown_bars: int = 6
    # Portfolio-level profit lock is opt-in and research-only by default.
    portfolio_lock_enabled: bool = False
    portfolio_lock_activation: float = 500.0
    portfolio_lock_giveback: float = 0.35
    portfolio_lock_cooldown_bars: int = 6

    def __post_init__(self):
        if self.variant not in {f"X{i}" for i in range(8)}:
            raise ValueError(f"unknown exit variant: {self.variant}")
        if self.atr_n < 1 or self.cooldown_bars < 0:
            raise ValueError("atr_n must be positive and cooldown_bars nonnegative")
        if self.chandelier_k <= 0 or not 0 < self.trailing_pct < 1:
            raise ValueError("invalid trailing-stop parameters")
        if not 0 < self.giveback_fraction < 1 or self.giveback_trigger_atr <= 0:
            raise ValueError("invalid giveback parameters")
        if self.portfolio_lock_activation <= 0:
            raise ValueError("portfolio_lock_activation must be positive")
        if not 0 < self.portfolio_lock_giveback < 1:
            raise ValueError("portfolio_lock_giveback must be between 0 and 1")
        if self.portfolio_lock_cooldown_bars < 1:
            raise ValueError("portfolio_lock_cooldown_bars must be at least 1")


@dataclass
class BacktestResult:
    curve: pd.DataFrame            # portfolio value, pools, exposure, cash, and P&L attribution
    trades: pd.DataFrame
    fees: float
    turnover_usd: float
    skipped: dict
    open_positions: list


def run_backtest(panel, target: pd.DataFrame, pcfg: PortfolioConfig, score: pd.DataFrame | None = None,
                 exit_config: ExitConfig | None = None) -> BacktestResult:
    cols = list(panel.close.columns)
    N, T = len(cols), len(panel.index)
    cls = np.array([CLS[panel.classes[c]] for c in cols])
    C = panel.close.values.astype(float)
    H = panel.high.values.astype(float)
    L = panel.low.values.astype(float)
    X = panel.exec_px.values.astype(float)
    atr_values = I.atr(panel.high, panel.low, panel.close, exit_config.atr_n if exit_config else 14).values
    donchian_lows = {}
    if exit_config and exit_config.variant == "X5":
        for n in {exit_config.donchian_n}:
            donchian_lows[n] = I.donchian(panel.high, panel.low, n)[1].values
    TR = panel.tradable.values.astype(bool)
    TG = target.reindex(index=panel.index, columns=cols).fillna(0).values.astype(np.int8)
    SC = score.reindex(index=panel.index, columns=cols).values if score is not None else None
    rc = pcfg.risk
    VS = vol_scale_matrix(panel, rc)
    R = np.log(np.where(C > 0, C, np.nan)); R = np.vstack([np.full((1, N), np.nan), np.diff(R, axis=0)])
    slip = np.array([pcfg.slip_bps[panel.classes[c]] for c in cols]) / 1e4
    amt_prec = np.array([panel.meta.get(c, {}).get("amt_prec", 8) for c in cols])
    min_ord = np.array([max(pcfg.min_order_usd, panel.meta.get(c, {}).get("mini_order", 0.0)) for c in cols])
    fee = pcfg.fee
    max_pos = np.array([pcfg.max_pos["crypto"], pcfg.max_pos["equity"]])

    has_class = np.array([(cls == k).any() for k in (0, 1)])
    w = np.array([pcfg.crypto_weight, 1 - pcfg.crypto_weight])
    cash = pcfg.capital * w
    q = np.zeros(N); entry = np.zeros(N); collat = np.zeros(N); side = np.zeros(N, dtype=np.int8)
    blocked = np.zeros(N, dtype=np.int8); e_fee = np.zeros(N); e_bar = np.zeros(N, dtype=int)
    peak_high = np.zeros(N); trough_low = np.zeros(N); entry_atr = np.zeros(N)
    trailing_stop = np.full(N, -np.inf)
    partial_taken = np.zeros(N, dtype=bool); cooldown_until = np.full(N, -1, dtype=int)
    trade_ids = np.zeros(N, dtype=np.int64)
    position_ids = np.zeros(N, dtype=np.int64)
    position_initial_qty = np.zeros(N)
    next_trade_id = 1
    halt_until = -1
    peak = pcfg.capital
    # Each lock cycle starts from its own equity baseline. After a lock fires,
    # a fresh activation-sized gain is required before another lock can fire.
    lock_cycle_base = pcfg.capital
    lock_cycle_peak = pcfg.capital
    lock_armed = False
    portfolio_lock_pending = False
    portfolio_lock_cooldown_until = -1
    fees_total = turnover = realized_total = 0.0
    skipped = {"cap_pos": 0, "min_order": 0, "corr": 0, "exposure": 0, "no_cash": 0}
    trades: list[dict] = []
    eq_t = np.zeros(T); eq_c = np.zeros((T, 2)); expo = np.zeros(T); npos = np.zeros(T, dtype=int)
    cash_curve = np.zeros(T); gross_exposure = np.zeros(T); net_exposure = np.zeros(T)
    realized_curve = np.zeros(T); unrealized_curve = np.zeros(T)
    idx = panel.index

    def value(px):
        v = np.zeros(N)
        L, S = side == 1, side == -1
        v[L] = q[L] * px[L]
        v[S] = np.maximum(collat[S] + (entry[S] - px[S]) * q[S], 0.0)
        return v

    def unrealized_net(px):
        pnl = np.zeros(N)
        L, S = side == 1, side == -1
        pnl[L] = q[L] * (px[L] - entry[L])
        pnl[S] = np.maximum(q[S] * (entry[S] - px[S]), -collat[S])
        return pnl.sum() - e_fee[side != 0].sum()

    def close_pos(j, i, price, reason):
        nonlocal fees_total, turnover, realized_total
        c = cls[j]
        notional = q[j] * price
        f = fee * notional
        exit_i = min(i + 1, T - 1)
        if side[j] == 1:
            pnl_gross = q[j] * (price - entry[j]); cash[c] += notional - f
        else:
            pnl_gross = max(q[j] * (entry[j] - price), -collat[j]); cash[c] += collat[j] + pnl_gross - f
        net_pnl = pnl_gross - f - e_fee[j]
        realized_total += net_pnl
        fees_total += f; turnover += notional
        entry_notional = entry[j] * q[j]
        mfe = max(0.0, (peak_high[j] - entry[j]) * q[j]) if side[j] == 1 else 0.0
        mae = min(0.0, (trough_low[j] - entry[j]) * q[j]) if side[j] == 1 else 0.0
        trades.append({"trade_id": int(trade_ids[j]), "asset": cols[j], "class": panel.classes[cols[j]],
                       "side": int(side[j]), "entry_time": idx[e_bar[j]], "exit_time": idx[exit_i],
                       "entry_px": entry[j], "exit_px": price, "qty": q[j], "entry_fee": e_fee[j],
                       "exit_fee": f, "gross_pnl": pnl_gross, "pnl_net": net_pnl,
                       "fees": f + e_fee[j], "return_pct": net_pnl / entry_notional * 100 if entry_notional else np.nan,
                       "holding_period_hours": (idx[exit_i] - idx[e_bar[j]]).total_seconds() / 3600,
                       "entry_fill_id": f"{int(trade_ids[j])}:entry", "exit_fill_id": f"{int(trade_ids[j])}:exit",
                       "entry_fill_qty": q[j], "entry_fill_px": entry[j], "exit_fill_qty": q[j], "exit_fill_px": price,
                       "bars": i + 1 - e_bar[j], "reason": reason,
                       "position_id": int(position_ids[j]), "position_initial_qty": position_initial_qty[j],
                       "mfe": mfe, "mae": mae, "giveback": mfe - net_pnl,
                       "entry_atr": entry_atr[j],
                       "mfe_atr": mfe / (q[j] * entry_atr[j]) if q[j] > 0 and entry_atr[j] > 0 else np.nan,
                       "profitable_1atr_loser": bool(entry_atr[j] > 0 and mfe >= q[j] * entry_atr[j] and net_pnl < 0)})
        q[j] = entry[j] = collat[j] = e_fee[j] = 0.0
        peak_high[j] = trough_low[j] = entry_atr[j] = 0.0
        trailing_stop[j] = -np.inf
        partial_taken[j] = False
        side[j] = 0; trade_ids[j] = 0; position_ids[j] = 0; position_initial_qty[j] = 0.0

    for i in range(T):
        px = np.nan_to_num(C[i])
        v = value(px)
        by_c = np.bincount(cls, weights=v, minlength=2)
        eq_c[i] = cash + by_c
        tot = eq_c[i].sum(); eq_t[i] = tot
        expo[i] = by_c.sum() / tot if tot > 0 else 0; npos[i] = (side != 0).sum()
        cash_curve[i] = cash.sum()
        gross_exposure[i] = np.abs(q * px).sum()
        net_exposure[i] = (side * q * px).sum()
        realized_curve[i] = realized_total
        unrealized_curve[i] = unrealized_net(px)
        # Maintain per-position excursions through the latest completed bar.
        active = side == 1
        peak_high[active] = np.maximum(peak_high[active], H[i, active])
        trough_low[active] = np.minimum(trough_low[active], L[i, active])

        if i == T - 1:
            break
        peak = max(peak, tot); dd = 1 - tot / peak

        # --- optional portfolio-level profit lock (research-only unless explicitly enabled)
        portfolio_lock_trigger = False
        if exit_config and exit_config.portfolio_lock_enabled and not portfolio_lock_pending:
            # Estimate liquidation equity net of closing fee and slippage; the
            # actual fill can still differ when the next execution price gaps.
            estimated_exit_cost = float((np.abs(q * px) * (fee + slip)).sum())
            net_liquidation_equity = float(tot - estimated_exit_cost)
            if not lock_armed:
                if net_liquidation_equity - lock_cycle_base >= exit_config.portfolio_lock_activation:
                    lock_armed = True
                    lock_cycle_peak = net_liquidation_equity
            else:
                lock_cycle_peak = max(lock_cycle_peak, net_liquidation_equity)
                peak_profit = lock_cycle_peak - lock_cycle_base
                lock_floor = lock_cycle_base + peak_profit * (1.0 - exit_config.portfolio_lock_giveback)
                if net_liquidation_equity <= lock_floor:
                    portfolio_lock_trigger = True
                    lock_armed = False
                    portfolio_lock_pending = True

        # --- risk exits decided on information at close i
        force = np.zeros(N, bool); reason = np.array([""] * N, dtype=object)
        if (rc.stop_loss or rc.take_profit) and (side != 0).any():
            pnl = np.where(side != 0, side * (px / np.where(entry > 0, entry, np.nan) - 1), 0.0)
            if rc.stop_loss:
                m = (side != 0) & (pnl <= -rc.stop_loss); force |= m; reason[m] = "stop"; blocked[m] = side[m]
            if rc.take_profit:
                m = (side != 0) & (pnl >= rc.take_profit); force |= m; reason[m] = "tp"; blocked[m] = side[m]
        # Optional research-only stateful exits. Signals remain the original X0 targets.
        if exit_config and exit_config.variant != "X0":
            v = exit_config.variant
            for j in np.flatnonzero(side == 1):
                a = atr_values[i, j]
                a = float(a) if np.isfinite(a) and a > 0 else entry_atr[j]
                stop = -np.inf
                if v in {"X1", "X6", "X7"} and a > 0:
                    trailing_stop[j] = max(trailing_stop[j], peak_high[j] - exit_config.chandelier_k * a)
                    stop = max(stop, trailing_stop[j])
                if v in {"X2", "X7"} and entry_atr[j] > 0:
                    if peak_high[j] - entry[j] >= exit_config.breakeven_atr * entry_atr[j]:
                        stop = max(stop, entry[j] * (1 + 2 * fee))
                if v == "X3" and peak_high[j] > 0:
                    stop = max(stop, peak_high[j] * (1 - exit_config.trailing_pct))
                if v == "X4" and entry_atr[j] > 0:
                    peak_gain = peak_high[j] - entry[j]
                    if peak_gain >= exit_config.giveback_trigger_atr * entry_atr[j]:
                        if C[i, j] - entry[j] <= (1 - exit_config.giveback_fraction) * peak_gain:
                            force[j] = True; reason[j] = "giveback_X4"
                if v == "X5":
                    lo = donchian_lows[exit_config.donchian_n][i, j]
                    if np.isfinite(lo) and C[i, j] < lo:
                        force[j] = True; reason[j] = "donchian_low_X5"
                if v == "X6" and not partial_taken[j] and entry_atr[j] > 0:
                    target_px = entry[j] + exit_config.partial_r * entry_atr[j]
                    if H[i, j] >= target_px and q[j] > 1e-12:
                        partial_qty = np.floor((q[j] / 2) * 10 ** amt_prec[j]) / 10 ** amt_prec[j]
                        if 0 < partial_qty < q[j]:
                            price = X[i, j] * (1 - slip[j])
                            part_fee = fee * partial_qty * price
                            part_entry_fee = e_fee[j] * (partial_qty / q[j])
                            part_pnl_gross = partial_qty * (price - entry[j])
                            cash[cls[j]] += partial_qty * price - part_fee
                            fees_total += part_fee; turnover += partial_qty * price
                            realized_total += part_pnl_gross - part_fee - part_entry_fee
                            trades.append({
                                "trade_id": int(trade_ids[j]), "asset": cols[j], "class": panel.classes[cols[j]],
                                "side": 1, "entry_time": idx[e_bar[j]], "exit_time": idx[min(i + 1, T - 1)],
                                "entry_px": entry[j], "exit_px": price, "qty": partial_qty,
                                "entry_fee": part_entry_fee, "exit_fee": part_fee, "gross_pnl": part_pnl_gross,
                                "pnl_net": part_pnl_gross - part_fee - part_entry_fee,
                                "fees": part_fee + part_entry_fee, "return_pct": (part_pnl_gross - part_fee - part_entry_fee) / (entry[j] * partial_qty) * 100,
                                "holding_period_hours": (idx[min(i + 1, T - 1)] - idx[e_bar[j]]).total_seconds() / 3600,
                                "entry_fill_id": f"{int(trade_ids[j])}:entry-part", "exit_fill_id": f"{int(trade_ids[j])}:partial",
                                "entry_fill_qty": partial_qty, "entry_fill_px": entry[j], "exit_fill_qty": partial_qty, "exit_fill_px": price,
                                "bars": i + 1 - e_bar[j], "reason": "partial_tp_X6",
                                "position_id": int(position_ids[j]), "position_initial_qty": position_initial_qty[j],
                                "mfe": max(0.0, (peak_high[j] - entry[j]) * partial_qty),
                                "mae": min(0.0, (trough_low[j] - entry[j]) * partial_qty),
                                "giveback": max(0.0, (peak_high[j] - entry[j]) * partial_qty) - (part_pnl_gross - part_fee - part_entry_fee),
                                "entry_atr": entry_atr[j],
                                "mfe_atr": max(0.0, (peak_high[j] - entry[j]) * partial_qty) / (partial_qty * entry_atr[j]),
                                "profitable_1atr_loser": bool((peak_high[j] - entry[j]) >= entry_atr[j] and (part_pnl_gross - part_fee - part_entry_fee) < 0),
                            })
                            old_qty = q[j]
                            q[j] -= partial_qty
                            e_fee[j] -= part_entry_fee
                            # Give the remaining tranche its own unique trade id for audit integrity.
                            trade_ids[j] = next_trade_id; next_trade_id += 1
                            partial_taken[j] = True
                if np.isfinite(stop) and C[i, j] <= stop:
                    force[j] = True; reason[j] = f"protective_{v}"
                if force[j]:
                    blocked[j] = side[j]
                    cooldown_until[j] = i + exit_config.cooldown_bars

        # The lock takes priority while liquidation is pending so retries retain
        # the correct reason and every still-open position remains forced flat.
        if portfolio_lock_pending:
            active = side != 0
            force |= active
            reason[active] = "portfolio_profit_lock"
            blocked[active] = side[active]

        halted = (i < halt_until) or (i <= portfolio_lock_cooldown_until) or portfolio_lock_pending
        if rc.dd_halt and dd >= rc.dd_halt and not halted:
            halt_until = i + rc.halt_bars                # pause new entries for halt_bars
            force |= side != 0; reason[side != 0] = "halt"
            halted = True
            peak = tot                                   # reset reference so we don't re-halt instantly

        tgt = TG[i].astype(np.int8)
        blocked = np.where(tgt != blocked, 0, blocked).astype(np.int8)          # unblock once signal changes
        desired = np.where(blocked != 0, 0, tgt)
        if not pcfg.allow_short:
            desired = np.maximum(desired, 0)
        desired = np.where(force, 0, desired)
        if halted:
            desired = np.zeros(N, dtype=desired.dtype)

        need = (desired != side) & TR[i]
        if not need.any():
            continue
        ex = X[i]
        # ---- exits (and the exit leg of flips)
        for j in np.flatnonzero(need & (side != 0)):
            price = ex[j] * (1 - slip[j]) if side[j] == 1 else ex[j] * (1 + slip[j])
            close_pos(j, i, price, reason[j] or "signal")

        # Start the cooldown and the next profit-lock cycle only after every
        # position has actually liquidated. Use realized cash after actual fills,
        # not the trigger-bar estimate, as the next cycle's baseline.
        if portfolio_lock_pending and not (side != 0).any():
            portfolio_lock_pending = False
            lock_cycle_base = float(cash.sum())
            lock_cycle_peak = lock_cycle_base
            lock_armed = False
            portfolio_lock_cooldown_until = max(
                portfolio_lock_cooldown_until,
                i + exit_config.portfolio_lock_cooldown_bars,
            )

        # ---- entries, highest score first, sequential on remaining pool cash
        cand = np.flatnonzero(need & (desired != 0) & (side == 0))
        if len(cand) and not halted:
            if SC is not None:
                s = np.nan_to_num(SC[i, cand], nan=-1e9); cand = cand[np.argsort(-s, kind="stable")]
            dd_mult = 1.0
            for th, m in rc.dd_ladder:
                if dd >= th:
                    dd_mult = m
            val_now = value(px); invested = np.bincount(cls, weights=val_now, minlength=2)
            for j in cand:
                if exit_config and i < cooldown_until[j]:
                    continue
                c = cls[j]
                if dd_mult <= 0:
                    break
                if (side[cls == c] != 0).sum() >= max_pos[c]:
                    skipped["cap_pos"] += 1; continue
                if rc.corr_cap and (side != 0).any() and i >= rc.corr_win:
                    held = np.flatnonzero(side != 0)
                    a = np.nan_to_num(R[i - rc.corr_win + 1:i + 1, j])
                    cmax = max((np.corrcoef(a, np.nan_to_num(R[i - rc.corr_win + 1:i + 1, h]))[0, 1] for h in held), default=0)
                    if np.nan_to_num(cmax) > rc.corr_cap:
                        skipped["corr"] += 1; continue
                notional = pcfg.pos_frac * cash[c] * dd_mult * (VS[i, j] if VS is not None else 1.0)
                eq_class = cash[c] + invested[c]
                if rc.max_asset_frac:
                    notional = min(notional, rc.max_asset_frac * eq_class)
                room_c = rc.max_class_exposure * eq_class - invested[c]
                room_t = rc.max_total_exposure * eq_c[i].sum() - invested.sum()
                if min(room_c, room_t) < notional:
                    notional = max(min(room_c, room_t), 0.0); skipped["exposure"] += 1
                notional = min(notional, cash[c] / (1 + fee))
                if notional < min_ord[j]:
                    skipped["min_order" if cash[c] > min_ord[j] else "no_cash"] += 1; continue
                d = int(desired[j])
                price = ex[j] * (1 + slip[j]) if d == 1 else ex[j] * (1 - slip[j])
                qty = np.floor(notional / price * 10 ** amt_prec[j]) / 10 ** amt_prec[j]
                if qty * price < min_ord[j]:
                    skipped["min_order"] += 1; continue
                nt = qty * price; f = fee * nt
                cash[c] -= nt + f        # long: pay notional+fee; short: lock collateral(=nt) + open fee
                q[j], entry[j], side[j], e_fee[j], e_bar[j] = qty, price, d, f, i + 1
                peak_high[j] = trough_low[j] = price
                entry_atr[j] = float(atr_values[i, j]) if np.isfinite(atr_values[i, j]) and atr_values[i, j] > 0 else price * 0.02
                partial_taken[j] = False
                trade_ids[j] = next_trade_id
                position_ids[j] = next_trade_id
                position_initial_qty[j] = qty
                next_trade_id += 1
                collat[j] = nt if d == -1 else 0.0
                fees_total += f; turnover += nt; invested[c] += nt

    equity = pd.Series(eq_t, index=idx)
    drawdown = equity / equity.cummax().clip(lower=pcfg.capital) - 1.0
    curve = pd.DataFrame({"equity_total": eq_t, "equity_crypto": eq_c[:, 0], "equity_equity": eq_c[:, 1],
                          "exposure": expo, "n_pos": npos, "cash": cash_curve,
                          "gross_exposure": gross_exposure, "net_exposure": net_exposure,
                          "realized_pnl": realized_curve, "unrealized_pnl": unrealized_curve,
                          "total_pnl": eq_t - pcfg.capital, "drawdown": drawdown.values}, index=idx)
    tdf = pd.DataFrame(trades)
    openp = []
    for j in np.flatnonzero(side != 0):
        current_px = C[-1, j]
        current_px = float(current_px) if np.isfinite(current_px) else 0.0
        gross_pnl = (q[j] * (current_px - entry[j]) if side[j] == 1
                     else max(q[j] * (entry[j] - current_px), -collat[j]))
        unrealized_pnl = gross_pnl - e_fee[j]
        entry_notional = entry[j] * q[j]
        openp.append({"trade_id": int(trade_ids[j]), "position_id": int(position_ids[j]), "asset": cols[j], "side": int(side[j]),
                      "entry_time": idx[e_bar[j]], "entry": entry[j], "qty": q[j],
                      "current_price": current_px, "entry_fee": e_fee[j], "gross_unrealized_pnl": gross_pnl,
                      "unrealized_pnl": unrealized_pnl,
                      "unrealized_return_pct": unrealized_pnl / entry_notional * 100 if entry_notional else np.nan,
                      "peak_price_since_entry": peak_high[j], "trough_price_since_entry": trough_low[j],
                      "mfe": max(0.0, (peak_high[j] - entry[j]) * q[j]) if side[j] == 1 else np.nan,
                      "mae": min(0.0, (trough_low[j] - entry[j]) * q[j]) if side[j] == 1 else np.nan})
    return BacktestResult(curve, tdf, fees_total, turnover, skipped, openp)
