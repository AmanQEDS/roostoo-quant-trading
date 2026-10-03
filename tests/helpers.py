import numpy as np, pandas as pd
from rq.data.panel import Panel


def mini_panel(closes: dict, classes=None, tradable=None, freq=30, meta=None):
    """Hand-built panel: open[t] = close[t-1], so a decision at row i fills at close[i]."""
    T = len(next(iter(closes.values())))
    idx = pd.date_range("2026-01-01", periods=T, freq=f"{freq}min", tz="UTC")
    C = pd.DataFrame(closes, index=idx, dtype=float)
    O = C.shift(1).fillna(C.iloc[0])
    X = O.shift(-1); X.iloc[-1] = np.nan
    tr = pd.DataFrame(True, index=idx, columns=C.columns)
    if tradable is not None:
        tr = tradable.reindex(index=idx, columns=C.columns).fillna(False)
    tr.iloc[-1] = False
    z = pd.DataFrame(0.0, index=idx, columns=C.columns)
    return Panel(freq, O, C, C, C, z + 1, z, pd.DataFrame(False, index=idx, columns=C.columns), X, tr,
                 classes or {c: "crypto" for c in C.columns}, meta or {})


def tgt(panel, rows: dict):
    """rows: {asset: [per-bar target]} -> int8 DataFrame"""
    return pd.DataFrame(rows, index=panel.index).astype("int8")
