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


@dataclass
class BacktestResult:
    curve: pd.DataFrame            # portfolio value, pools, exposure, cash, and P&L attribution
    trades: pd.DataFrame
    fees: float
    turnover_usd: float
    skipped: dict
    open_positions: list


def run_backtest(panel, target: pd.DataFrame, pcfg: PortfolioConfig, score: pd.DataFrame | None = None) -> BacktestResult:
    cols = list(panel.close.columns)
    N, T = len(cols), len(panel.index)
    cls = np.array([CLS[panel.classes[c]] for c in cols])
    C = panel.close.values.astype(float)
    X = panel.exec_px.values.astype(float)
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
    trade_ids = np.zeros(N, dtype=np.int64)
    next_trade_id = 1
    halt_until = -1
    peak = pcfg.capital
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
        trades.append({"trade_id": int(trade_ids[j]), "asset": cols[j], "class": panel.classes[cols[j]],
                       "side": int(side[j]), "entry_time": idx[e_bar[j]], "exit_time": idx[exit_i],
                       "entry_px": entry[j], "exit_px": price, "qty": q[j], "entry_fee": e_fee[j],
                       "exit_fee": f, "gross_pnl": pnl_gross, "pnl_net": net_pnl,
                       "fees": f + e_fee[j], "return_pct": net_pnl / entry_notional * 100 if entry_notional else np.nan,
                       "holding_period_hours": (idx[exit_i] - idx[e_bar[j]]).total_seconds() / 3600,
                       "entry_fill_id": f"{int(trade_ids[j])}:entry", "exit_fill_id": f"{int(trade_ids[j])}:exit",
                       "entry_fill_qty": q[j], "entry_fill_px": entry[j], "exit_fill_qty": q[j], "exit_fill_px": price,
                       "bars": i + 1 - e_bar[j], "reason": reason})
        q[j] = entry[j] = collat[j] = e_fee[j] = 0.0; side[j] = 0; trade_ids[j] = 0

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
        if i == T - 1:
            break
        peak = max(peak, tot); dd = 1 - tot / peak

        # --- risk exits decided on information at close i
        force = np.zeros(N, bool); reason = np.array([""] * N, dtype=object)
        if (rc.stop_loss or rc.take_profit) and (side != 0).any():
            pnl = np.where(side != 0, side * (px / np.where(entry > 0, entry, np.nan) - 1), 0.0)
            if rc.stop_loss:
                m = (side != 0) & (pnl <= -rc.stop_loss); force |= m; reason[m] = "stop"; blocked[m] = side[m]
            if rc.take_profit:
                m = (side != 0) & (pnl >= rc.take_profit); force |= m; reason[m] = "tp"; blocked[m] = side[m]
        halted = i < halt_until
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
                trade_ids[j] = next_trade_id
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
        openp.append({"trade_id": int(trade_ids[j]), "asset": cols[j], "side": int(side[j]),
                      "entry_time": idx[e_bar[j]], "entry": entry[j], "qty": q[j],
                      "current_price": current_px, "entry_fee": e_fee[j], "gross_unrealized_pnl": gross_pnl,
                      "unrealized_pnl": unrealized_pnl,
                      "unrealized_return_pct": unrealized_pnl / entry_notional * 100 if entry_notional else np.nan})
    return BacktestResult(curve, tdf, fees_total, turnover, skipped, openp)
