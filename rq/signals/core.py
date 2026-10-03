"""Signal plumbing.

A strategy returns a `Cond`: four boolean frames saying WHEN to enter/exit each side.
`to_target` latches them (hysteresis) into a desired position in {-1,0,+1} per bar.
Exit beats entry on the same bar (safer).  Everything is evaluated on information up to
and including bar t; the engine executes at t+1 (see data/panel.py).
Combinators let multi-indicator, filter and regime strategies be built from the same atoms.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


class MissingData(RuntimeError):
    """Raised by a builder when an external series it needs (F&G, VIX, DVOL ...) is unavailable."""


@dataclass
class Cond:
    long_on: pd.DataFrame
    long_off: pd.DataFrame
    short_on: pd.DataFrame | None = None
    short_off: pd.DataFrame | None = None
    score: pd.DataFrame | None = None          # priority for sequential capital allocation (higher first)


def _b(x: pd.DataFrame) -> pd.DataFrame:
    return x.fillna(False).astype(bool)


def hyst(on: pd.DataFrame, off: pd.DataFrame) -> pd.DataFrame:
    ev = pd.DataFrame(np.nan, index=on.index, columns=on.columns)
    ev = ev.mask(_b(on), 1.0)
    ev = ev.mask(_b(off), 0.0)                 # exit wins ties
    return ev.ffill().fillna(0.0)


def to_target(c: Cond, allow_short: bool = False) -> pd.DataFrame:
    long = hyst(c.long_on, c.long_off)
    if allow_short and c.short_on is not None:
        short = hyst(c.short_on, c.short_off if c.short_off is not None else ~_b(c.short_on))
        t = long - short
        t = t.where(~((long == 1) & (short == 1)), 0.0)
    else:
        t = long
    return t.astype("int8")


def and_(a: Cond, b: Cond) -> Cond:
    so = sf = None
    if a.short_on is not None and b.short_on is not None:
        so, sf = _b(a.short_on) & _b(b.short_on), _b(a.short_off) | _b(b.short_off)
    return Cond(_b(a.long_on) & _b(b.long_on), _b(a.long_off) | _b(b.long_off), so, sf, a.score if a.score is not None else b.score)


def filter_(base: Cond, ok: pd.DataFrame, exit_on_fail: bool = True, short_ok: pd.DataFrame | None = None) -> Cond:
    """Gate entries by a boolean 'regime ok' frame; optionally force-exit when it turns bad."""
    ok = _b(ok)
    lo, lf = _b(base.long_on) & ok, _b(base.long_off) | (~ok if exit_on_fail else False)
    so = sf = None
    if base.short_on is not None:
        sok = ok if short_ok is None else _b(short_ok)
        so, sf = _b(base.short_on) & sok, _b(base.short_off) | (~sok if exit_on_fail else False)
    return Cond(lo, lf, so, sf, base.score)


def switch(regime: pd.DataFrame, table: dict[int, Cond | None], flatten_on_change: bool = True) -> Cond:
    """Regime-switching: in regime k use table[k] (None = stay flat)."""
    z = pd.DataFrame(False, index=regime.index, columns=regime.columns)
    lo, lf = z.copy(), z.copy()
    for k, c in table.items():
        m = regime == k
        if c is None:
            lf = lf | m
        else:
            lo = lo | (m & _b(c.long_on))
            lf = lf | (m & _b(c.long_off))
    if flatten_on_change:
        lf = lf | (regime != regime.shift(1))
    return Cond(lo, lf)


def bc(series: pd.Series, like: pd.DataFrame) -> pd.DataFrame:
    """Broadcast a market-wide Series to every asset column."""
    return pd.DataFrame(np.repeat(series.reindex(like.index).values[:, None], like.shape[1], axis=1),
                        index=like.index, columns=like.columns)
