"""Strategy families 1-9 (family 10, risk overlays, lives in backtest/risk.py).

Every builder has the signature  f(panel, ext, **params) -> Cond  and
  * works on whatever columns the panel passed in (the runner hands it one asset class),
  * only reads rows <= t,
  * takes `ext` = dict of external series ALREADY aligned to panel.index by availability time.
Parameter grids are deliberately tiny (research/grid.py) - see brief section 20.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .. import indicators as I
from .core import Cond, MissingData, and_, filter_, switch, bc, _b


def _ma(close, n, kind="sma"):
    return I.ema(close, n) if kind == "ema" else I.sma(close, n)


def market_index(panel) -> pd.Series:
    """Equal-weight market proxy of the columns in the panel (causal cumulative log-return)."""
    return I.log_ret(panel.close).mean(axis=1).fillna(0).cumsum().pipe(np.exp)


def _need(ext, key):
    if key not in ext or ext[key] is None or ext[key].dropna().empty:
        raise MissingData(key)
    return ext[key]

# =============================================================== 1. MOMENTUM
def tsmom(p, ext, n=48, thr=0.0):
    r = I.roc(p.close, n)
    return Cond(r > thr, r < 0, r < -thr, r > 0, score=r)

def xsmom(p, ext, n=96, top=0.3, hold=0.6):
    r = I.roc(p.close, n); rk = I.cs_rank(r)
    return Cond((rk >= 1 - top) & (r > 0), (rk < 1 - hold) | (r < 0),
                (rk <= top) & (r < 0), (rk > hold) | (r > 0), score=r)

# =============================================================== 2. TREND FOLLOWING
def price_ma(p, ext, n=50, kind="ema", band=0.002):
    ma = _ma(p.close, n, kind)
    return Cond(p.close > ma * (1 + band), p.close < ma * (1 - band),
                p.close < ma * (1 - band), p.close > ma * (1 + band), score=p.close / ma - 1)

def ma_cross(p, ext, fast=20, slow=50, kind="ema"):
    f, s = _ma(p.close, fast, kind), _ma(p.close, slow, kind)
    return Cond(f > s, f < s, f < s, f > s, score=f / s - 1)

def macd_sig(p, ext, fast=12, slow=26, sig=9):
    line, sg, h = I.macd(p.close, fast, slow, sig)
    return Cond(line > sg, line < sg, line < sg, line > sg, score=h / p.close)

def adx_trend(p, ext, fast=20, slow=50, adx_n=14, thr=25):
    f, s = I.ema(p.close, fast), I.ema(p.close, slow)
    a, pdi, mdi = I.adx(p.high, p.low, p.close, adx_n)
    return Cond((f > s) & (a > thr), f < s, (f < s) & (a > thr), f > s, score=a)

# =============================================================== 3. MEAN REVERSION
def rsi_mr(p, ext, n=14, x=30, y=55):
    r = I.rsi(p.close, n)
    return Cond(r < x, r > y, r > 100 - x, r < 100 - y, score=-r)

def boll_mr(p, ext, n=20, k=2.0, exit="mid"):
    mid, up, lo, pb = I.bollinger(p.close, n, k)
    tgt = mid if exit == "mid" else up
    return Cond(p.close < lo, p.close > tgt, p.close > up, p.close < mid, score=-pb)

def zscore_mr(p, ext, n=48, z_in=2.0, z_out=0.0):
    z = I.zscore(p.close, n)
    return Cond(z < -z_in, z > z_out, z > z_in, z < -z_out, score=-z)

def ma_dist_mr(p, ext, n=50, d_in=0.03):
    d = I.ma_distance(p.close, n)
    return Cond(d < -d_in, d > 0, d > d_in, d < 0, score=-d)

# =============================================================== 4. BREAKOUT
def donchian_bo(p, ext, n=48, exit_n=24):
    hi, lo = I.donchian(p.high, p.low, n)
    ehi, elo = I.donchian(p.high, p.low, exit_n)
    return Cond(p.close > hi, p.close < elo, p.close < lo, p.close > ehi, score=p.close / hi - 1)

# =============================================================== 5. VOLATILITY-BASED
def vol_breakout(p, ext, ma_n=48, atr_n=14, mult=1.5):
    ma = I.ema(p.close, ma_n); a = I.atr(p.high, p.low, p.close, atr_n)
    return Cond(p.close > ma + mult * a, p.close < ma, p.close < ma - mult * a, p.close > ma, score=(p.close - ma) / a)

def vol_ok(p, win=2880, lo=0.0, hi=0.8, rv_n=48):
    """Boolean filter: trailing-percentile of realised vol inside [lo, hi]."""
    pct = I.vol_percentile(I.realized_vol(p.close, rv_n), win)
    return (pct >= lo) & (pct <= hi)

def vol_filtered_trend(p, ext, fast=20, slow=50, hi=0.8, win=2880):
    return filter_(ma_cross(p, ext, fast, slow), vol_ok(p, win, 0.0, hi))

def vix_gate(p, ext, fast=20, slow=50, vix_max=25.0):
    """Trend only while the equity-implied vol index is calm (risk-off gate)."""
    v = bc(_need(ext, "vix"), p.close)
    return filter_(ma_cross(p, ext, fast, slow), v < vix_max)

def dvol_gate(p, ext, fast=20, slow=50, pct_max=0.8, win_days=180):
    d = _need(ext, "dvol")
    bars = int(win_days * 1440 / p.freq_min)
    pct = d.rolling(bars, min_periods=bars // 4).rank(pct=True)
    return filter_(ma_cross(p, ext, fast, slow), bc(pct < pct_max, p.close))

# =============================================================== 6. SENTIMENT (Fear & Greed)
def fng_contrarian(p, ext, low=25, exit_at=50):
    f = bc(_need(ext, "fng"), p.close)
    return Cond(f <= low, f >= exit_at)

def fng_greed_gate(p, ext, fast=20, slow=50, greed=75):
    f = bc(_need(ext, "fng"), p.close)
    return filter_(ma_cross(p, ext, fast, slow), f < greed)

def fng_momentum(p, ext, n_days=7, thr=5):
    f = _need(ext, "fng")
    chg = f - f.shift(int(n_days * 1440 / p.freq_min))
    c = bc(chg, p.close)
    return Cond(c > thr, c < 0)

# =============================================================== 7. SUPPLY / DEMAND PROXIES
def flow_trend(p, ext, n=24, thr=0.03, ma_n=48):
    imb = I.ema(I.taker_imbalance(p.taker_buy, p.volume), n)
    up = p.close > I.ema(p.close, ma_n)
    return Cond((imb > thr) & up, imb < 0, (imb < -thr) & ~up, imb > 0, score=imb)

def volume_capitulation(p, ext, vz_n=96, vz=2.5, ret_atr=1.5, exit_n=24):
    a = I.atr(p.high, p.low, p.close, 14)
    drop = (p.close - p.open) < -ret_atr * a
    spike = I.volume_z(p.volume, vz_n) > vz
    return Cond(spike & drop, p.close > I.ema(p.close, exit_n), score=I.volume_z(p.volume, vz_n))

def absorption(p, ext, vz_n=96, vz=2.0, rng_atr=0.8, trend_n=96):
    """High volume + small range near lows = supply being absorbed (demand zone proxy)."""
    a = I.atr(p.high, p.low, p.close, 14)
    small = (p.high - p.low) < rng_atr * a
    near_low = p.close < I.sma(p.close, trend_n)
    return Cond((I.volume_z(p.volume, vz_n) > vz) & small & near_low, p.close > I.sma(p.close, trend_n))

# =============================================================== 8. MULTI-INDICATOR
def rsi_boll(p, ext, rsi_n=14, x=30, boll_n=20, k=2.0):
    a, b = rsi_mr(p, ext, rsi_n, x, 55), boll_mr(p, ext, boll_n, k, "mid")
    # entry needs BOTH oversold + below band; exit when EITHER says mean reverted
    return and_(a, b)

def macd_trend(p, ext, fast=12, slow=26, sig=9, ma_n=200):
    return filter_(macd_sig(p, ext, fast, slow, sig), p.close > I.sma(p.close, ma_n), exit_on_fail=False)

def rsi_macd_boll(p, ext, x=35, k=2.0, turn_win=6):
    """RSI oversold AND below lower band AND MACD histogram has turned up within `turn_win` bars.
    (Requiring the histogram to rise on the *same* bar as a band-pierce almost never happens - tested.)"""
    h = I.macd(p.close)[2]
    turned = (h.diff() > 0).astype(float).rolling(turn_win, min_periods=1).max() > 0
    base = and_(rsi_mr(p, ext, 14, x, 55), boll_mr(p, ext, 20, k, "mid"))
    return filter_(base, turned, exit_on_fail=False)

def tech_sentiment(p, ext, fast=20, slow=50, fng_max=75):
    return fng_greed_gate(p, ext, fast, slow, fng_max)

def tech_vol_sent(p, ext, fast=20, slow=50, hi=0.8, fng_max=75):
    f = bc(_need(ext, "fng"), p.close)
    return filter_(ma_cross(p, ext, fast, slow), vol_ok(p, 2880, 0.0, hi) & (f < fng_max))

# =============================================================== 9. REGIME SWITCHING
def regime_switch(p, ext, trend_n=480, vol_hi=0.85, rsi_n=14, panic_rsi=30, use_fng=True):
    """Regimes (all causal, market-wide):
         0 DEFENSIVE : market vol percentile > vol_hi            -> flat
         1 TREND     : market > its MA and calm vol              -> trend-follow (EMA cross)
         2 PANIC     : market RSI < panic_rsi (and F&G<=30 if available) -> mean-revert (RSI)
         3 NEUTRAL   : everything else                           -> flat
    """
    m = market_index(p)
    mv = I.vol_percentile(np.log(m / m.shift(1)).rolling(48, min_periods=48).std(ddof=0), 2880)
    up = m > I.sma(m, trend_n)
    mr = I.rsi(m.to_frame("m"), rsi_n)["m"]
    panic = mr < panic_rsi
    if use_fng and "fng" in ext and not ext["fng"].dropna().empty:
        panic = panic & (ext["fng"] <= 30)
    reg = pd.Series(3, index=p.index)
    reg[up & (mv <= vol_hi)] = 1
    reg[panic & (mv <= 1.0)] = 2
    reg[mv > vol_hi] = 0
    R = bc(reg, p.close)
    return switch(R, {0: None, 1: ma_cross(p, ext, 20, 50), 2: rsi_mr(p, ext, rsi_n, 30, 50), 3: None})

BUILDERS = {f.__name__: f for f in [
    tsmom, xsmom, price_ma, ma_cross, macd_sig, adx_trend, rsi_mr, boll_mr, zscore_mr, ma_dist_mr,
    donchian_bo, vol_breakout, vol_filtered_trend, vix_gate, dvol_gate, fng_contrarian, fng_greed_gate,
    fng_momentum, flow_trend, volume_capitulation, absorption, rsi_boll, macd_trend, rsi_macd_boll,
    tech_sentiment, tech_vol_sent, regime_switch]}

FAMILY = {
    "momentum": ["tsmom", "xsmom"],
    "trend": ["price_ma", "ma_cross", "macd_sig", "adx_trend"],
    "mean_reversion": ["rsi_mr", "boll_mr", "zscore_mr", "ma_dist_mr"],
    "breakout": ["donchian_bo"],
    "volatility": ["vol_breakout", "vol_filtered_trend", "vix_gate", "dvol_gate"],
    "sentiment": ["fng_contrarian", "fng_greed_gate", "fng_momentum"],
    "supply_demand": ["flow_trend", "volume_capitulation", "absorption"],
    "multi_indicator": ["rsi_boll", "macd_trend", "rsi_macd_boll", "tech_sentiment", "tech_vol_sent"],
    "regime": ["regime_switch"],
}
