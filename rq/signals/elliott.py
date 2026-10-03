"""Elliott-wave family - a *mechanical, falsifiable* approximation (brief section 9).

What we test is NOT 'true' Elliott counting (which is subjective) but a fixed rule-set:
  1. Causal ZigZag: a pivot is CONFIRMED only when price reverses by k*ATR from the extreme.
     The pivot is known at the confirmation bar, not at the extreme bar (no repainting).
  2. Bullish impulse after pivots P0(L) P1(H) P2(L) P3(H) P4(L):
        wave-2 does not retrace below P0       (P2 > P0)
        wave-3 is not shorter than wave-1      (P3-P2 >= P1-P0)   [proxy for 'not the shortest']
        wave-4 does not overlap wave-1         (P4 > P1)
        wave-4 retraces 23.6%-61.8% of wave-3  (fib band)
     -> go long at confirmation of P4; invalidation = close < P4; target = P4 + wave-1 length
        (equal-wave projection); time stop after `max_bars`.
  3. Bearish mirror for shorts.
Reproducible (pure function of OHLC), so the three questions in the brief - mechanical?
reproducible? predictive after costs? - are answered by the same backtest as everything else.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .. import indicators as I
from .core import Cond


def _one(high, low, close, atr, k, fib_lo, fib_hi, max_bars):
    n = len(close)
    lon = np.zeros(n, bool); loff = np.zeros(n, bool); son = np.zeros(n, bool); soff = np.zeros(n, bool)
    piv: list[tuple[int, float, str]] = []     # (confirm_idx, price, 'H'/'L')
    direction = 0
    ext_p = ext_i = None
    pos = 0; inval = tgt = 0.0; entry_i = 0
    for i in range(n):
        a = atr[i]
        if np.isnan(a) or np.isnan(close[i]):
            continue
        # ---- manage open pattern trade
        if pos == 1 and (close[i] < inval or close[i] >= tgt or i - entry_i > max_bars):
            loff[i] = True; pos = 0
        elif pos == -1 and (close[i] > inval or close[i] <= tgt or i - entry_i > max_bars):
            soff[i] = True; pos = 0
        # ---- zigzag
        if direction == 0:
            if ext_p is None:
                ext_p, ext_i = high[i], i; lo_p = low[i]
            ext_p = max(ext_p, high[i]); lo_p = min(lo_p, low[i])
            if high[i] - lo_p >= k * a and ext_p - lo_p >= k * a:
                direction = -1; ext_p = low[i]
            continue
        confirmed = None
        if direction == 1:
            if high[i] > ext_p:
                ext_p = high[i]
            elif ext_p - low[i] >= k * a:
                confirmed = (i, ext_p, "H"); direction = -1; ext_p = low[i]
        else:
            if low[i] < ext_p:
                ext_p = low[i]
            elif high[i] - ext_p >= k * a:
                confirmed = (i, ext_p, "L"); direction = 1; ext_p = high[i]
        if confirmed:
            piv.append(confirmed)
            if len(piv) >= 5 and pos == 0:
                (_, p0, t0), (_, p1, _), (_, p2, _), (_, p3, _), (_, p4, t4) = piv[-5:]
                if t4 == "L" and t0 == "L":
                    w1, w3, w4 = p1 - p0, p3 - p2, p3 - p4
                    if w1 > 0 and p2 > p0 and w3 >= w1 and p4 > p1 and fib_lo <= w4 / w3 <= fib_hi:
                        lon[i] = True; pos = 1; inval = p4; tgt = p4 + w1; entry_i = i
                elif t4 == "H" and t0 == "H":
                    w1, w3, w4 = p0 - p1, p2 - p3, p4 - p3
                    if w1 > 0 and p2 < p0 and w3 >= w1 and p4 < p1 and fib_lo <= w4 / w3 <= fib_hi:
                        son[i] = True; pos = -1; inval = p4; tgt = p4 - w1; entry_i = i
    return lon, loff, son, soff


def elliott(p, ext, k=2.5, atr_n=14, fib_lo=0.236, fib_hi=0.618, max_bars=240):
    atr = I.atr(p.high, p.low, p.close, atr_n)
    out = {n: np.zeros(p.close.shape, bool) for n in ("lon", "loff", "son", "soff")}
    H, L, C, A = p.high.values, p.low.values, p.close.values, atr.values
    for j in range(p.close.shape[1]):
        a, b, c, d = _one(H[:, j], L[:, j], C[:, j], A[:, j], k, fib_lo, fib_hi, max_bars)
        out["lon"][:, j], out["loff"][:, j], out["son"][:, j], out["soff"][:, j] = a, b, c, d
    mk = lambda k_: pd.DataFrame(out[k_], index=p.index, columns=p.columns)
    return Cond(mk("lon"), mk("loff"), mk("son"), mk("soff"))
