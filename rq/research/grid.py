"""Small, economically-motivated parameter grid (brief section 20). Windows are in BARS of the chosen timeframe.
Every entry is (builder_name, params, asset_classes, needs_ext)."""
from __future__ import annotations
from dataclasses import dataclass, field
import itertools

@dataclass(frozen=True)
class Spec:
    builder: str
    params: tuple                      # tuple of (k, v) pairs (hashable)
    classes: tuple = ("crypto",)
    needs: tuple = ()
    @property
    def p(self) -> dict: return dict(self.params)
    @property
    def name(self) -> str:
        return self.builder + "(" + ",".join(f"{k}={v}" for k, v in self.params) + ")"

def S(builder, classes=("crypto",), needs=(), **kw):
    return Spec(builder, tuple(sorted(kw.items())), classes, needs)

def build_grid() -> list[Spec]:
    g: list[Spec] = []
    for n in (24, 48, 96): g.append(S("tsmom", n=n))
    for n in (48, 96, 192): g.append(S("xsmom", n=n, top=0.3, hold=0.6))
    for n, b in itertools.product((50, 100, 200), (0.0, 0.003)): g.append(S("price_ma", n=n, kind="ema", band=b))
    for (f, s), k in itertools.product(((20, 50), (20, 100), (50, 200)), ("ema", "sma")): g.append(S("ma_cross", fast=f, slow=s, kind=k))
    for f, s, sg in ((12, 26, 9), (24, 52, 18)): g.append(S("macd_sig", fast=f, slow=s, sig=sg))
    for thr in (20, 25): g.append(S("adx_trend", fast=20, slow=50, thr=thr))
    for n, (x, y) in itertools.product((14, 21, 28), ((30, 55), (25, 50), (30, 70))): g.append(S("rsi_mr", n=n, x=x, y=y))
    for k, ex in itertools.product((2.0, 2.5), ("mid", "upper")): g.append(S("boll_mr", n=20, k=k, exit=ex))
    for n, z in itertools.product((48, 96), (2.0, 2.5)): g.append(S("zscore_mr", n=n, z_in=z))
    for n, d in itertools.product((50, 100), (0.02, 0.04)): g.append(S("ma_dist_mr", n=n, d_in=d))
    for n, e in ((24, 12), (48, 24), (96, 48)): g.append(S("donchian_bo", n=n, exit_n=e))
    for m in (1.5, 2.5): g.append(S("vol_breakout", ma_n=48, mult=m))
    for hi in (0.7, 0.85): g.append(S("vol_filtered_trend", hi=hi))
    for v in (20, 25, 30): g.append(S("vix_gate", classes=("crypto", "equity"), needs=("vix",), vix_max=float(v)))
    for pc in (0.7, 0.85): g.append(S("dvol_gate", needs=("dvol",), pct_max=pc))
    for lo in (20, 25): g.append(S("fng_contrarian", needs=("fng",), low=lo, exit_at=50))
    for gr in (70, 80): g.append(S("fng_greed_gate", needs=("fng",), greed=gr))
    for thr in (5, 10): g.append(S("fng_momentum", needs=("fng",), n_days=7, thr=thr))
    for t in (0.02, 0.05): g.append(S("flow_trend", thr=t))
    for v in (2.5, 3.5): g.append(S("volume_capitulation", vz=v))
    for v in (2.0, 3.0): g.append(S("absorption", vz=v))
    for x in (25, 30, 35): g.append(S("rsi_boll", x=x))
    for m in (100, 200): g.append(S("macd_trend", ma_n=m))
    for x in (30, 35): g.append(S("rsi_macd_boll", x=x))
    g.append(S("tech_sentiment", needs=("fng",)))
    g.append(S("tech_vol_sent", needs=("fng",)))
    for vh, tn, pr in itertools.product((0.8, 0.9), (240, 480), (25, 30)): g.append(S("regime_switch", vol_hi=vh, trend_n=tn, panic_rsi=pr))
    for k, mb in itertools.product((2.0, 3.0), (120, 240)): g.append(S("elliott", k=k, max_bars=mb))
    # equity-capable subset: the same price-based builders also run on the equity pool
    out = []
    for s in g:
        if s.builder in {"price_ma", "ma_cross", "macd_sig", "rsi_mr", "boll_mr", "zscore_mr", "donchian_bo", "tsmom", "xsmom", "adx_trend", "regime_switch", "vol_filtered_trend"}:
            out.append(Spec(s.builder, s.params, ("crypto", "equity"), s.needs))
        else:
            out.append(s)
    return out

RULES = {   # human-readable entry/exit text saved in the experiment log
 "tsmom": ("ROC_n > thr", "ROC_n < 0"), "xsmom": ("top-30% cross-sectional ROC_n and ROC>0", "falls below top-60% or ROC<0"),
 "price_ma": ("close > MA*(1+band)", "close < MA*(1-band)"), "ma_cross": ("fast MA > slow MA", "fast < slow"),
 "macd_sig": ("MACD > signal", "MACD < signal"), "adx_trend": ("EMA20>EMA50 and ADX>thr", "EMA20<EMA50"),
 "rsi_mr": ("RSI_n < x", "RSI_n > y"), "boll_mr": ("close < lower band", "close > mid/upper band"),
 "zscore_mr": ("z < -z_in", "z > 0"), "ma_dist_mr": ("close < MA by d_in", "close > MA"),
 "donchian_bo": ("close > prior n-bar high", "close < prior exit_n-bar low"), "vol_breakout": ("close > EMA + mult*ATR", "close < EMA"),
 "vol_filtered_trend": ("MA cross AND vol pctile <= hi", "MA cross down OR vol pctile > hi"), "vix_gate": ("MA cross AND VIX < vix_max", "cross down OR VIX >= vix_max"),
 "dvol_gate": ("MA cross AND DVOL pctile < pct_max", "cross down OR DVOL high"), "fng_contrarian": ("F&G <= low", "F&G >= exit_at"),
 "fng_greed_gate": ("MA cross AND F&G < greed", "cross down OR F&G >= greed"), "fng_momentum": ("F&G 7d change > thr", "change < 0"),
 "flow_trend": ("EMA(taker imbalance) > thr AND close > EMA", "imbalance < 0"), "volume_capitulation": ("volume z > vz AND big red candle", "close > EMA24"),
 "absorption": ("volume z > vz, small range, below SMA", "close > SMA"), "rsi_boll": ("RSI<x AND close<lower band", "RSI>55 OR close>mid"),
 "macd_trend": ("MACD>signal AND close>SMA(ma_n)", "MACD<signal"), "rsi_macd_boll": ("RSI<x, below band, MACD hist turned up", "RSI>55 OR close>mid"),
 "tech_sentiment": ("MA cross AND F&G<75", "cross down OR F&G>=75"), "tech_vol_sent": ("MA cross AND calm vol AND F&G<75", "cross down OR vol/greed gate fails"),
 "regime_switch": ("trend-follow in calm uptrend; RSI-revert in panic; flat in high-vol/neutral", "sub-strategy exit or regime change"),
 "elliott": ("confirmed 5-pivot impulse, long at wave-4 low (short mirror)", "invalidation / equal-wave target / time stop"),
}
