"""Family 10: portfolio / risk-management overlays (configuration + precomputed scalers)."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from .. import indicators as I


@dataclass
class RiskConfig:
    # --- volatility scaling: size *= clip(median_vol_trailing / vol_now, floor, 1)
    vol_scale: bool = False
    vol_floor: float = 0.25
    vol_ref_days: int = 30
    rv_bars: int = 48
    # --- exposure limits (fractions of the relevant equity)
    max_asset_frac: float | None = None       # per-asset notional / class equity
    max_class_exposure: float = 1.0           # invested / class equity
    max_total_exposure: float = 1.0           # invested / total equity
    # --- exits
    stop_loss: float | None = None            # e.g. 0.03 = -3% from entry (checked on close, filled next bar)
    take_profit: float | None = None
    # --- drawdown control: ((dd_threshold, size_multiplier), ...) ascending; new-entry sizing only
    dd_ladder: tuple = ()
    dd_halt: float | None = None              # flatten + pause when portfolio drawdown >= this
    halt_bars: int = 144
    # --- concentration: skip an entry if rolling corr with ANY held position exceeds this
    corr_cap: float | None = None
    corr_win: int = 96


def vol_scale_matrix(panel, rc: RiskConfig) -> np.ndarray | None:
    if not rc.vol_scale:
        return None
    rv = I.realized_vol(panel.close, rc.rv_bars)
    ref_bars = int(rc.vol_ref_days * 1440 / panel.freq_min)
    ref = rv.rolling(ref_bars, min_periods=ref_bars // 4).median()      # trailing -> causal
    s = (ref / rv).clip(lower=rc.vol_floor, upper=1.0).fillna(1.0)
    return s.values
