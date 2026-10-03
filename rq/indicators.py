"""Causal indicators built from trailing windows and per-row data only.

Breakout channels are shifted by one bar so the current bar is compared with prior observations.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------- trend / momentum
def sma(x, n):  return x.rolling(n, min_periods=n).mean()
def ema(x, n):  return x.ewm(span=n, adjust=False, min_periods=n).mean()
def roc(x, n):  return x / x.shift(n) - 1.0
def log_ret(close): return np.log(close / close.shift(1))

def macd(close, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig

# ----------------------------------------------------------------------------- mean reversion
def rsi(close, n=14):
    d = close.diff()
    up, dn = d.clip(lower=0), (-d).clip(lower=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(ad != 0, 100.0).where(au.notna())

def bollinger(close, n=20, k=2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    up, lo = mid + k * sd, mid - k * sd
    pctb = (close - lo) / (up - lo).replace(0, np.nan)
    return mid, up, lo, pctb

def zscore(x, n):
    m, s = x.rolling(n, min_periods=n).mean(), x.rolling(n, min_periods=n).std(ddof=0)
    return (x - m) / s.replace(0, np.nan)

def ma_distance(close, n):
    return close / sma(close, n) - 1.0

# ----------------------------------------------------------------------------- volatility
def true_range(high, low, close):
    pc = close.shift(1)
    return np.maximum(np.maximum(high - low, (high - pc).abs()), (low - pc).abs())

def atr(high, low, close, n=14):
    return true_range(high, low, close).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()

def realized_vol(close, n):
    """Rolling std of log returns per bar (NOT annualised)."""
    return log_ret(close).rolling(n, min_periods=n).std(ddof=0)

def vol_percentile(rv, n):
    """Causal percentile rank of the current vol vs the trailing n bars (includes current)."""
    return rv.rolling(n, min_periods=max(10, n // 4)).rank(pct=True)

# ----------------------------------------------------------------------------- volume / flow
def obv(close, volume):
    return (np.sign(close.diff()).fillna(0) * volume).cumsum()

def volume_z(volume, n):
    return zscore(volume, n)

def volume_change(volume, n):
    return volume / volume.rolling(n, min_periods=n).mean() - 1.0

def taker_imbalance(taker_buy, volume):
    """(buy - sell)/total using Binance taker-buy volume: a real order-flow proxy in [-1,1]."""
    return ((2 * taker_buy - volume) / volume.replace(0, np.nan)).clip(-1, 1)

# ----------------------------------------------------------------------------- breakout / strength
def donchian(high, low, n):
    """Prior-n-bar channel (shifted: excludes the current bar)."""
    return high.rolling(n, min_periods=n).max().shift(1), low.rolling(n, min_periods=n).min().shift(1)

def adx(high, low, close, n=14):
    up, dn = high.diff(), -low.diff()
    plus = ((up > dn) & (up > 0)) * up
    minus = ((dn > up) & (dn > 0)) * dn
    tr = true_range(high, low, close)
    a = 1 / n
    trs = tr.ewm(alpha=a, adjust=False, min_periods=n).mean()
    pdi = 100 * plus.ewm(alpha=a, adjust=False, min_periods=n).mean() / trs
    mdi = 100 * minus.ewm(alpha=a, adjust=False, min_periods=n).mean() / trs
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=a, adjust=False, min_periods=n).mean(), pdi, mdi

# ----------------------------------------------------------------------------- price structure
def candle_features(open_, high, low, close):
    rng = (high - low).replace(0, np.nan)
    body = (close - open_) / rng
    upper = (high - np.maximum(open_, close)) / rng
    lower = (np.minimum(open_, close) - low) / rng
    return body, upper, lower

# ----------------------------------------------------------------------------- cross-section / market
def cs_rank(x):
    """Cross-sectional percentile rank per row (uses same-row info only)."""
    return x.rank(axis=1, pct=True)

def market_return(close, cols=None, n=1):
    r = roc(close[cols] if cols else close, n)
    return r.mean(axis=1)

def rolling_corr_to_market(close, n):
    r = log_ret(close)
    m = r.mean(axis=1)
    return r.rolling(n, min_periods=n).corr(m)
