"""Panel construction: the place where forward-bias is prevented *by construction*.

CONVENTIONS (read these before trusting any number):
  1. Every bar is indexed by its CLOSE time.  A row labelled t contains information
     that was knowable at t and not before.  Indicators at row t may use rows <= t only.
  2. A decision taken on row i is executed at `exec_px[i]`, a price that belongs to a
     LATER instant than the information used:
        crypto  : exec_px[i] = open[i+1]   (next bar's open == price right after the signal bar closes)
        equity  : exec_px[i] = close[i+1]  (conservative one-bar delay; equity data is coarser/ffilled)
  3. `tradable[i]` says whether an order decided on row i can actually fill at i+1
     (crypto: bar exists; equity: US regular session and a fresh native bar).
  4. Missing bars are forward-filled for marking-to-market only and flagged `stale`.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]


def resample_ohlcv(df: pd.DataFrame, minutes: int, src_minutes: int = 5) -> pd.DataFrame:
    """Aggregate open-time-indexed bars to `minutes`; return CLOSE-time-indexed COMPLETE bars only."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    for c in ("taker_buy_base", "quote_volume", "n_trades"):
        if c in df.columns:
            agg[c] = "sum"
    g = df.resample(f"{minutes}min", label="left", closed="left")
    out = g.agg(agg)
    cnt = g["close"].count()
    out = out[cnt == minutes // src_minutes]            # drop partial bins -> never use incomplete bars
    out = out.dropna(subset=["close"])
    out.index = out.index + pd.Timedelta(minutes=minutes)  # open time -> close time
    out.index.name = "close_time"
    return out


@dataclass
class Panel:
    freq_min: int
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    taker_buy: pd.DataFrame
    stale: pd.DataFrame
    exec_px: pd.DataFrame
    tradable: pd.DataFrame
    classes: dict[str, str]                  # column -> "crypto" | "equity"
    meta: dict[str, dict] = field(default_factory=dict)   # amt_prec, mini_order, slip_bps ...

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.close.index

    @property
    def columns(self) -> list[str]:
        return list(self.close.columns)

    def cols(self, klass: str) -> list[str]:
        return [c for c in self.columns if self.classes[c] == klass]

    def slice(self, start=None, end=None) -> "Panel":
        sl = slice(start, end)
        f = lambda d: d.loc[sl]
        return Panel(self.freq_min, *(f(getattr(self, n)) for n in
                     ["open", "high", "low", "close", "volume", "taker_buy", "stale", "exec_px", "tradable"]),
                     classes=self.classes, meta=self.meta)

    def subset(self, cols: list[str]) -> "Panel":
        g = lambda d: d[cols]
        return Panel(self.freq_min, *(g(getattr(self, n)) for n in
                     ["open", "high", "low", "close", "volume", "taker_buy", "stale", "exec_px", "tradable"]),
                     classes={c: self.classes[c] for c in cols}, meta=self.meta)

    def truncate_at(self, i: int) -> "Panel":
        """Panel as it would have looked at row i (used by the look-ahead tests).
        exec_px/tradable of the LAST row are unknowable at that time -> NaN/False."""
        p = Panel(self.freq_min, *(getattr(self, n).iloc[: i + 1].copy() for n in
                  ["open", "high", "low", "close", "volume", "taker_buy", "stale", "exec_px", "tradable"]),
                  classes=self.classes, meta=self.meta)
        p.exec_px.iloc[-1] = np.nan
        p.tradable.iloc[-1] = False
        return p


def _in_us_session(idx: pd.DatetimeIndex) -> np.ndarray:
    ny = idx.tz_convert("America/New_York")
    mins = ny.hour * 60 + ny.minute
    return ((ny.dayofweek < 5) & (mins > 9 * 60 + 30) & (mins <= 16 * 60)).astype(bool)




def _validate_crypto_gaps(
    crypto: dict[str, pd.DataFrame],
    max_gap_hours: float = 24.0,
) -> None:
    """
    Detect large raw-data outages before constructing the Panel.

    Small historical gaps are allowed and remain represented through
    Panel.stale. Large common outages are reported explicitly because
    forward-filled prices must never be mistaken for real observations.
    """
    problems = []

    for name, df in crypto.items():
        if df.empty or len(df.index) < 2:
            continue

        idx = pd.DatetimeIndex(df.index).sort_values()
        diffs = idx.to_series().diff().dt.total_seconds().div(3600.0)

        bad = diffs[diffs > max_gap_hours]

        for next_bar, gap_hours in bad.items():
            previous_pos = idx.get_loc(next_bar) - 1
            if previous_pos < 0:
                continue

            previous_bar = idx[previous_pos]

            problems.append(
                {
                    "symbol": name,
                    "previous_bar": previous_bar,
                    "next_bar": next_bar,
                    "gap_hours": float(gap_hours),
                }
            )

    if problems:
        print()
        print("=" * 100)
        print("WARNING ? LARGE RAW DATA GAPS DETECTED")
        print("=" * 100)

        for x in problems:
            print(
                f"{x['symbol']:>10} | "
                f"{x['previous_bar']} -> {x['next_bar']} | "
                f"{x['gap_hours']:.2f} hours"
            )

        print()
        print(
            "These gaps will remain stale in the Panel. "
            "They must NOT be treated as real observations by feature/alpha code."
        )
        print("=" * 100)
        print()


def build_panel(crypto: dict[str, pd.DataFrame], equity: dict[str, pd.DataFrame] | None,
                freq_min: int, start: str | pd.Timestamp, end: str | pd.Timestamp,
                meta: dict[str, dict] | None = None, equity_session: bool = True) -> Panel:
    """crypto: {name: 5m open-time-indexed df}; equity: {name: close-time-indexed df with attrs bar_minutes}."""
    equity = equity or {}
    start, end = pd.Timestamp(start, tz="UTC") if pd.Timestamp(start).tzinfo is None else pd.Timestamp(start), \
                 pd.Timestamp(end, tz="UTC") if pd.Timestamp(end).tzinfo is None else pd.Timestamp(end)
    grid = pd.date_range(start, end, freq=f"{freq_min}min", tz="UTC")
    parts: dict[str, dict[str, pd.Series | pd.DataFrame]] = {}
    classes: dict[str, str] = {}
    _validate_crypto_gaps(crypto)

    for name, df5 in crypto.items():
        bars = resample_ohlcv(df5, freq_min)
        classes[name] = "crypto"
        parts[name] = {"bars": bars, "native": freq_min}
    for name, df in equity.items():
        classes[name] = "equity"
        parts[name] = {"bars": df, "native": int(df.attrs.get("bar_minutes", 60))}
    cols = list(parts)
    D = {k: pd.DataFrame(index=grid, columns=cols, dtype=float) for k in
         ["open", "high", "low", "close", "volume", "taker_buy"]}
    stale = pd.DataFrame(True, index=grid, columns=cols)
    age_min = pd.DataFrame(np.inf, index=grid, columns=cols)
    for name in cols:
        bars = parts[name]["bars"]
        present = bars.reindex(grid)
        has = present["close"].notna()
        stale[name] = ~has
        for k in ["open", "high", "low", "close"]:
            D[k][name] = present[k]
        D["volume"][name] = present["volume"].fillna(0.0)
        D["taker_buy"][name] = present["taker_buy_base"].fillna(0.0) if "taker_buy_base" in present else 0.0
        last_t = pd.Series(np.where(has, grid.asi8, np.nan), index=grid).ffill()
        age_min[name] = ((grid.asi8 - last_t) / 6e10).fillna(np.inf)
        first = bars.index.min()
        # fill gaps for MTM only: close ffill; open/high/low collapse to the filled close
        D["close"][name] = D["close"][name].ffill()
        for k in ["open", "high", "low"]:
            D[k][name] = D[k][name].fillna(D["close"][name])
    # warm-up rows before an asset's first bar stay NaN (asset not yet listed)
    exec_px = D["open"].shift(-1)
    tradable = (~stale.shift(-1, fill_value=True)).copy()
    for name in cols:
        if classes[name] == "equity":
            exec_px[name] = D["close"][name].shift(-1)
            sess = pd.Series(_in_us_session(grid), index=grid).shift(-1, fill_value=False) if equity_session \
                else pd.Series(True, index=grid)
            fresh = (age_min[name].shift(-1) <= parts[name]["native"]).fillna(False)
            tradable[name] = sess & fresh
    exec_px.iloc[-1] = np.nan
    tradable.iloc[-1] = False
    tradable = tradable & exec_px.notna()
    return Panel(freq_min, D["open"], D["high"], D["low"], D["close"], D["volume"], D["taker_buy"],
                 stale, exec_px, tradable, classes, meta or {})


