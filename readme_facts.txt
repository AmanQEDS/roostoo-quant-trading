

==================== GIT ====================
da19e9f Freeze sizing: pos_frac 0.15, max 5 (dev-only decision)
57ec51c Initial research and trading framework
origin	https://github.com/AmanQEDS/roostoo-quant-trading.git (fetch)
origin	https://github.com/AmanQEDS/roostoo-quant-trading.git (push)
 M config/live.yaml
 M rq/research/corr_sens.py
?? readme_facts.txt
?? rq/live/bot.py.bak_dedupe
?? rq/live/bot.py.bak_ladder
?? rq/research/w14_dist.py
git : warning: in the working copy of 'config/live.yaml', LF will be replaced by CRLF the next time Git touches it
At line:4 char:78
+ ... git remote -v; git status --short; git --no-pager diff --stat; git -- ...
+                                        ~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (warning: in the... Git touch    es it:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
 
warning: in the working copy of 'rq/research/corr_sens.py', LF will be replaced by CRLF the next time Git touches it
 config/live.yaml | 8 +++-----
 1 file changed, 3 insertions(+), 5 deletions(-)

timeframe: 30m
crypto_weight: 1.0
pos_frac: 0.15
max_pos: {crypto: 5, equity: 0}
allow_short: false
exec_mode: run
limit_timeout_s: 90
strategies:
  crypto: {builder: ma_cross, params: {fast: 50, slow: 200, kind: ema}}
  equity: null
mode: run
dd_ladder: []
start_utc: "2026-10-03 00:00"
dd_ladder: [[0.10, 0.5], [0.20, 0.25]]


==================== ENV ====================
Python 3.14.3

numpy              2.5.3
pandas             3.0.6
pyarrow            25.0.1
pytest             9.1.1
PyYAML             6.0.3
requests           2.34.2
pandas>=2.2
numpy>=1.26
pyyaml>=6.0
requests>=2.31
pyarrow>=15.0
yfinance>=0.2.40      # equity underlyings (daily / 1h history)
pytest>=8.0
matplotlib>=3.8       # optional, plots only




==================== LIVE CONFIG (working copy) ====================
timeframe: 30m
crypto_weight: 1.0
pos_frac: 0.10
max_pos: {crypto: 5, equity: 0}
allow_short: false
exec_mode: market
limit_timeout_s: 90
strategies:
  crypto: {builder: ma_cross, params: {fast: 50, slow: 200, kind: ema}}
  equity: null
mode: run
dd_ladder: [[0.10, 0.5], [0.20, 0.25]]
start_utc: "2026-10-03 00:00"


==================== DEFAULT CONFIG ====================
data:
  start: "2023-01-01"
  crypto_top_n: 40              # top-N Roostoo crypto pairs by 24h USD volume that also exist on Binance spot
  max_spread_bps: 15            # drop pairs whose quoted spread makes market orders too costly
  min_usd_vol_24h: 1000000.0
  equity_interval: "1h"         # free Yahoo depth ~730d at 1h; use a paid source for 10m/30m history
  equity_session: true          # trade equities only inside US regular hours (conservative)
timeframes: ["10m", "30m"]
portfolio:
  capital: 100000
  crypto_weights: [0.2, 0.3, 0.4, 0.5]
  pos_frac: [0.05, 0.10, 0.15, 0.20]
  max_pos_crypto: [3, 5, 10]
  max_pos_equity: [5, 10, 15]
  slip_bps: {crypto: 2.0, equity: 5.0}
gates:
  max_trades_per_day: 12
  max_drawdown: 0.30
  min_trades: 30
live:
  min_active_days: 8            # competition rule: >= 8 active trading days with enough trades
  loop_seconds: 60


==================== UNIVERSE OVERRIDES ====================
# Manual truth for anything the heuristics get wrong. Fill after running `python -m rq.cli discover`.
class: {}          # e.g. {"TSLAX": "equity", "PAXG": "commodity"}
# Map Roostoo equity coin -> Yahoo Finance ticker of the underlying (history proxy).
yahoo_underlying: {}   # e.g. {"TSLAX": "TSLA", "NVDAX": "NVDA"}
# Equity buckets for large-cap vs small/mid-cap baskets (decide AFTER seeing the real list).
equity_baskets:
  large_cap: []
  small_mid_cap: []


==================== CONSTANTS ====================
"""Competition constants and the research calendar. Single source of truth."""
import pandas as pd

TAKER_FEE = 0.001      # 0.1%  market orders   (competition rules)
MAKER_FEE = 0.0005     # 0.05% limit orders    (competition rules)
SHORT_OPEN_FEE = 0.001   # /v6/short_open : 0.1% of position value (API docs)
SHORT_CLOSE_FEE = 0.001  # /v6/short_close: 0.1% of closed value   (API docs)
INITIAL_CAPITAL = 100_000.0   # Luma rules; verify against exchangeInfo.InitialWallet

# Research calendar (see Stage A/B/C in README)
TRAIN_START = pd.Timestamp("2023-01-01", tz="UTC")
TRAIN_END = pd.Timestamp("2025-12-31 23:59:59", tz="UTC")
VAL_START = pd.Timestamp("2026-01-01", tz="UTC")

FREQ_MINUTES = {"10m": 10, "30m": 30}
BASE_KLINE = "5m"            # Binance has no 10m kline: we download 5m and aggregate
MINUTES_PER_YEAR = 365 * 24 * 60

# Composite score used by the organisers (Screen 3)
SCORE_WEIGHTS = {"sortino": 0.4, "sharpe": 0.3, "calmar": 0.3}


==================== FILE TREE ====================
rq\cli.py                                                      16199 bytes
rq\cli.py.bak2                                                 15617 bytes
rq\cli_download.py                                              2021 bytes
rq\config.py                                                     860 bytes
rq\constants.py                                                  957 bytes
rq\data_audit.py                                               13328 bytes
rq\execution.py                                                  877 bytes
rq\gap_audit.py                                                 3959 bytes
rq\indicators.py                                                4615 bytes
rq\__init__.py                                                     0 bytes
rq\backtest\audit.py                                            7010 bytes
rq\backtest\engine.py                                          12538 bytes
rq\backtest\metrics.py                                          5519 bytes
rq\backtest\risk.py                                             1707 bytes
rq\backtest\__init__.py                                            0 bytes
rq\data\binance_vision.py                                       3397 bytes
rq\data\equities.py                                             2133 bytes
rq\data\external.py                                             3454 bytes
rq\data\panel.py                                                9120 bytes
rq\data\panel.py.bak                                            7143 bytes
rq\data\__init__.py                                                0 bytes
rq\live\bot.py                                                  8905 bytes
rq\live\bot.py.bak                                              7150 bytes
rq\live\bot.py.bak2                                             8184 bytes
rq\live\bot.py.bak_dedupe                                       9831 bytes
rq\live\bot.py.bak_ladder                                       8905 bytes
rq\live\__init__.py                                                0 bytes
rq\research\benchmarks.py                                       2799 bytes
rq\research\combine.py                                           931 bytes
rq\research\combo.py                                            2259 bytes
rq\research\corr_sens.py                                        2845 bytes
rq\research\cost_sens.py                                        1758 bytes
rq\research\final_backtest.py                                   2054 bytes
rq\research\grid.py                                             5672 bytes
rq\research\loader.py                                           2777 bytes
rq\research\loader.py.bak                                       2362 bytes
rq\research\lock.py                                             1830 bytes
rq\research\regimes.py                                          3034 bytes
rq\research\risk_stability.py                                   2076 bytes
rq\research\risk_test.py                                        1656 bytes
rq\research\runner.py                                           6606 bytes
rq\research\selection.py                                        4020 bytes
rq\research\sizing_dev.py                                       1483 bytes
rq\research\w14_dist.py                                         1511 bytes
rq\research\wf_fixed.py                                         1886 bytes
rq\research\__init__.py                                            0 bytes
rq\roostoo\client.py                                            8371 bytes
rq\roostoo\client.py.bak2                                       8318 bytes
rq\roostoo\universe.py                                          2877 bytes
rq\roostoo\__init__.py                                             0 bytes
rq\signals\core.py                                              3457 bytes
rq\signals\elliott.py                                           4164 bytes
rq\signals\families.py                                          9706 bytes
rq\signals\__init__.py                                             0 bytes
tests\helpers.py                                                1060 bytes
tests\test_engine.py                                            5621 bytes
config\default.yaml                                              880 bytes
config\live.yaml                                                 317 bytes
config\universe_overrides.yaml                                   464 bytes


==================== MODULE DOCSTRINGS (first 3 lines) ====================
--- cli.py
"""python -m rq.cli <command>   (see README for the full workflow)"""
from __future__ import annotations

--- cli_download.py
"""Data download + QA commands (need internet)."""
from __future__ import annotations
from pathlib import Path
--- config.py
from __future__ import annotations
import os, yaml
from pathlib import Path
--- constants.py
"""Competition constants and the research calendar. Single source of truth."""
import pandas as pd

--- data_audit.py
from pathlib import Path

import numpy as np
--- execution.py
"""Order sizing/rounding shared by live trading and unit tests.  Mirrors the backtest engine's rules:
size = pos_frac x CURRENT pool cash, floor to AmountPrecision, respect MiniOrder, keep fee headroom."""
from __future__ import annotations
--- gap_audit.py
from pathlib import Path

import pandas as pd
--- indicators.py
"""Causal indicators built from trailing windows and per-row data only.

Breakout channels are shifted by one bar so the current bar is compared with prior observations.
--- __init__.py
--- audit.py
"""Export and reconcile trade-level and portfolio-level backtest audit files."""
from __future__ import annotations

--- engine.py
"""Portfolio backtest engine.

Timing (identical for backtest and live design):
--- metrics.py
"""Performance reporting. Primary ratios are computed on DAILY (UTC) equity returns and annualised with
sqrt(365) (crypto trades every day).  The organisers have not published their exact method, so we ALSO
report bar-frequency ratios and, crucially, the distribution over rolling 14-day windows - the live
--- risk.py
"""Family 10: portfolio / risk-management overlays (configuration + precomputed scalers)."""
from __future__ import annotations
from dataclasses import dataclass, field
--- __init__.py
--- binance_vision.py
"""Bulk crypto history from data.binance.vision (Roostoo prices track Binance spot).

We pull 5m klines and aggregate to 10m / 30m ourselves (Binance has no 10m interval).
--- equities.py
"""Equity history for the underlyings of Roostoo's stock instruments.

HONEST LIMITS (decide your equity design around these):
--- external.py
"""External indicators with conservative AVAILABILITY timestamps.

Rule: a value may only be used from the first moment it could really have been known.
--- panel.py
"""Panel construction: the place where forward-bias is prevented *by construction*.

CONVENTIONS (read these before trusting any number):
--- __init__.py
--- bot.py
"""Live trading loop SKELETON - same signal code as the backtest (rq.signals), Roostoo execution.

STATUS: written against the documented API but NOT yet exercised against the real exchange (no keys / network in the
--- __init__.py
--- benchmarks.py
"""Benchmarks (brief section 19): buy&hold, equal-weight, simple MA, simple RSI - same costs, same pools."""
from __future__ import annotations
import numpy as np
--- combine.py
"""Combine shortlisted strategies into one portfolio and test whether it improves Sharpe/Sortino/Calmar/DD."""
from __future__ import annotations
import numpy as np
--- combo.py
"""Phase 4+5 on DEVELOPMENT data only (2023-2025). Sleeves = daily-rebalanced mix of two independent equity curves."""
import pandas as pd
from ..config import load_config
--- corr_sens.py
"""Correlation-control sensitivity on DEVELOPMENT data only (2023-2025)."""
import pandas as pd

--- cost_sens.py
"""Cost sensitivity on DEVELOPMENT data only (2023-2025). Never touches 2026."""
import itertools
import pandas as pd
--- final_backtest.py
"""FINAL LOCKED SPEC on 2026 validation. Two runs only: bare vs frozen ladder, identical settings. Reported, never tuned on."""
import pandas as pd
from ..config import load_config
--- grid.py
"""Small, economically-motivated parameter grid (brief section 20). Windows are in BARS of the chosen timeframe.
Every entry is (builder_name, params, asset_classes, needs_ext)."""
from __future__ import annotations
--- loader.py
"""Turn raw files + the Roostoo universe snapshot into a Panel and aligned external series."""
from __future__ import annotations
import pickle
--- lock.py
"""Anti-overfitting guard for Stage B (brief section 7).

* `freeze` writes the shortlist (<= max_n strategies) with a hash and timestamp BEFORE any 2026 data is touched.
--- regimes.py
"""Regime analysis on DEVELOPMENT data only (2023-2025). Descriptive: definitions are fixed, not tuned."""
import numpy as np, pandas as pd
from ..config import load_config
--- risk_stability.py
"""Phase 6b: dd-ladder neighbour stability + per-year split. DEVELOPMENT data only (2023-2025)."""
import pandas as pd
from ..config import load_config
--- risk_test.py
"""Phase 6: do the engine's risk controls help? DEVELOPMENT data only (2023-2025)."""
import pandas as pd
from ..config import load_config
--- runner.py
"""Run a Spec through the two-pool engine, log everything, never overwrite history."""
from __future__ import annotations
import hashlib, json, time
--- selection.py
"""Stage C: robustness analysis + final selection (brief sections 7, 21, 23)."""
from __future__ import annotations
import numpy as np
--- sizing_dev.py
"""Sizing comparison, ma_cross 50/200, DEVELOPMENT data only (2023-2025). Ladder off. For choosing risk appetite, not alpha."""
import pandas as pd
from ..config import load_config
--- w14_dist.py
"""Distribution of 14-day returns for ma_cross + drawdown ladder. DEVELOPMENT data only."""
import numpy as np, pandas as pd
from ..config import load_config
--- wf_fixed.py
"""Walk-forward on DEVELOPMENT data only (2023-2025)."""
import pandas as pd
from ..config import load_config
--- __init__.py
--- client.py
"""Roostoo REST client (original implementation of the documented API).

Documented behaviour we rely on (github.com/roostoo/Roostoo-API-Documents):
--- universe.py
"""Step 1 of the brief: *verify* the tradable universe, never assume it.

`discover()` calls the public endpoints (no keys needed) and writes a snapshot of
--- __init__.py
--- core.py
"""Signal plumbing.

A strategy returns a `Cond`: four boolean frames saying WHEN to enter/exit each side.
--- elliott.py
"""Elliott-wave family - a *mechanical, falsifiable* approximation (brief section 9).

What we test is NOT 'true' Elliott counting (which is subjective) but a fixed rule-set:
--- families.py
"""Strategy families 1-9 (family 10, risk overlays, lives in backtest/risk.py).

Every builder has the signature  f(panel, ext, **params) -> Cond  and
--- __init__.py


==================== STRATEGY FAMILIES (builder names) ====================
def _ma(close, n, kind="sma"):
def market_index(panel) -> pd.Series:
def _need(ext, key):
def tsmom(p, ext, n=48, thr=0.0):
def xsmom(p, ext, n=96, top=0.3, hold=0.6):
def price_ma(p, ext, n=50, kind="ema", band=0.002):
def ma_cross(p, ext, fast=20, slow=50, kind="ema"):
def macd_sig(p, ext, fast=12, slow=26, sig=9):
def adx_trend(p, ext, fast=20, slow=50, adx_n=14, thr=25):
def rsi_mr(p, ext, n=14, x=30, y=55):
def boll_mr(p, ext, n=20, k=2.0, exit="mid"):
def zscore_mr(p, ext, n=48, z_in=2.0, z_out=0.0):
def ma_dist_mr(p, ext, n=50, d_in=0.03):
def donchian_bo(p, ext, n=48, exit_n=24):
def vol_breakout(p, ext, ma_n=48, atr_n=14, mult=1.5):
def vol_ok(p, win=2880, lo=0.0, hi=0.8, rv_n=48):
def vol_filtered_trend(p, ext, fast=20, slow=50, hi=0.8, win=2880):
def vix_gate(p, ext, fast=20, slow=50, vix_max=25.0):
def dvol_gate(p, ext, fast=20, slow=50, pct_max=0.8, win_days=180):
def fng_contrarian(p, ext, low=25, exit_at=50):
def fng_greed_gate(p, ext, fast=20, slow=50, greed=75):
def fng_momentum(p, ext, n_days=7, thr=5):
def flow_trend(p, ext, n=24, thr=0.03, ma_n=48):
def volume_capitulation(p, ext, vz_n=96, vz=2.5, ret_atr=1.5, exit_n=24):
def absorption(p, ext, vz_n=96, vz=2.0, rng_atr=0.8, trend_n=96):
def rsi_boll(p, ext, rsi_n=14, x=30, boll_n=20, k=2.0):
def macd_trend(p, ext, fast=12, slow=26, sig=9, ma_n=200):
def rsi_macd_boll(p, ext, x=35, k=2.0, turn_win=6):
def tech_sentiment(p, ext, fast=20, slow=50, fng_max=75):
def tech_vol_sent(p, ext, fast=20, slow=50, hi=0.8, fng_max=75):
def regime_switch(p, ext, trend_n=480, vol_hi=0.85, rsi_n=14, panic_rsi=30, use_fng=True):
BUILDERS = {f.__name__: f for f in [


==================== GRID SIZE / FAMILIES ====================
88 specs
Counter({'rsi_mr': 9, 'regime_switch': 8, 'price_ma': 6, 'ma_cross': 6, 'boll_mr': 4, 'zscore_mr': 4, 'ma_dist_mr': 4, 'elliott': 4, 'tsmom': 3, 'xsmom': 3, 'donchian_bo': 3, 'vix_gate': 3, 'rsi_boll': 3, 'macd_sig': 2, 'adx_trend': 2, 'vol_breakout': 2, 'vol_filtered_trend': 2, 'dvol_gate': 2, 'fng_contrarian': 2, 'fng_greed_gate': 2, 'fng_momentum': 2, 'flow_trend': 2, 'volume_capitulation': 2, 'absorption': 2, 'macd_trend': 2, 'rsi_macd_boll': 2, 'tech_sentiment': 1, 'tech_vol_sent': 1})


==================== FROZEN SHORTLIST FILES ====================
A:\Roostoo Quant Trading competition\roostoo-quant\results\shortlist.json
{
 "frozen_at": "2026-10-03 10:26:34",
 "names": [
  "fng_contrarian(exit_at=50,low=25)",
  "fng_momentum(n_days=7,thr=5)",
  "ma_cross(fast=50,kind=ema,slow=200)"
 ],
 "note": "",
 "sha1": "88e5b1449619c49323d57b36bafe771650e784cf"
}


==================== RESULTS FILES ====================

FullName                                                                                                                 Length LastWriteTime      
--------                                                                                                                 ------ -------------      
A:\Roostoo Quant Trading competition\roostoo-quant\results\.gitkeep                                                           0 02-10-2026 21:34:22
A:\Roostoo Quant Trading competition\roostoo-quant\results\alloc_sweep_dev_30m.csv                                        34393 03-10-2026 17:36:44
A:\Roostoo Quant Trading competition\roostoo-quant\results\alloc_sweep_val_30m.csv                                        34618 03-10-2026 11:29:24
A:\Roostoo Quant Trading competition\roostoo-quant\results\correlation_sensitivity.csv                                      753 03-10-2026 14:30:34
A:\Roostoo Quant Trading competition\roostoo-quant\results\cost_sensitivity.csv                                            3982 03-10-2026 14:00:11
A:\Roostoo Quant Trading competition\roostoo-quant\results\equity_final_bare_2026.csv                                   2198736 03-10-2026 14:49:12
A:\Roostoo Quant Trading competition\roostoo-quant\results\equity_final_ladder_2026.csv                                 2202937 03-10-2026 14:49:15
A:\Roostoo Quant Trading competition\roostoo-quant\results\equity_fng_contrarian_exit_at-50low-25_30m_2026.csv          2137145 03-10-2026 16:58:34
A:\Roostoo Quant Trading competition\roostoo-quant\results\equity_fng_momentum_n_days-7thr-5_30m_2026.csv               1934698 03-10-2026 16:58:36
A:\Roostoo Quant Trading competition\roostoo-quant\results\equity_ma_cross_fast-50kind-emaslow-200_30m_2026.csv         2198736 03-10-2026 16:58:38
A:\Roostoo Quant Trading competition\roostoo-quant\results\experiment_log.csv                                           2360124 03-10-2026 17:36:44
A:\Roostoo Quant Trading competition\roostoo-quant\results\gap_localization.csv                                            5352 03-10-2026 00:30:58
A:\Roostoo Quant Trading competition\roostoo-quant\results\open_positions_final_bare_2026.csv                               867 03-10-2026 14:49:12
A:\Roostoo Quant Trading competition\roostoo-quant\results\open_positions_final_ladder_2026.csv                             866 03-10-2026 14:49:15
A:\Roostoo Quant Trading competition\roostoo-quant\results\open_positions_fng_contrarian_exit_at-50low-25_30m_2026.csv      141 03-10-2026 16:58:34
A:\Roostoo Quant Trading competition\roostoo-quant\results\open_positions_fng_momentum_n_days-7thr-5_30m_2026.csv           141 03-10-2026 16:58:36
A:\Roostoo Quant Trading competition\roostoo-quant\results\open_positions_ma_cross_fast-50kind-emaslow-200_30m_2026.csv     867 03-10-2026 16:58:38
A:\Roostoo Quant Trading competition\roostoo-quant\results\regime_analysis.csv                                             2059 03-10-2026 14:02:57
A:\Roostoo Quant Trading competition\roostoo-quant\results\shortlist.json                                                   243 03-10-2026 10:26:34
A:\Roostoo Quant Trading competition\roostoo-quant\results\trades_final_bare_2026.csv                                     95340 03-10-2026 14:49:12
A:\Roostoo Quant Trading competition\roostoo-quant\results\trades_final_ladder_2026.csv                                   95152 03-10-2026 14:49:15
A:\Roostoo Quant Trading competition\roostoo-quant\results\trades_fng_contrarian_exit_at-50low-25_30m_2026.csv             4374 03-10-2026 16:58:34
A:\Roostoo Quant Trading competition\roostoo-quant\results\trades_fng_momentum_n_days-7thr-5_30m_2026.csv                 25257 03-10-2026 16:58:36
A:\Roostoo Quant Trading competition\roostoo-quant\results\trades_ma_cross_fast-50kind-emaslow-200_30m_2026.csv           95340 03-10-2026 16:58:38
A:\Roostoo Quant Trading competition\roostoo-quant\results\validation_ledger.jsonl                                       197249 03-10-2026 16:58:36




==================== COST SENSITIVITY ====================

strategy                            fee_pct slip_bp ret                 gross              sharpe             sortino            max_dd               trades fees_usd          
--------                            ------- ------- ---                 -----              ------             -------            ------               ------ --------          
ma_cross(fast=50,kind=ema,slow=200) 0.05    0.0     1.485082025694957   1.6876147159579968 1.1608349535262354 1.9931147970534937 -0.3640656762775638  1354   20253.269026303944
ma_cross(fast=50,kind=ema,slow=200) 0.05    2.0     1.3868162230430392  1.5847010466945246 1.1152271112528689 1.909687029529493  -0.3694875136864926  1354   19788.48236514854 
ma_cross(fast=50,kind=ema,slow=200) 0.05    5.0     1.2466930040997193  1.4378519629467452 1.0469732299871235 1.7856378473890189 -0.37757651891415733 1354   19115.895884702582
ma_cross(fast=50,kind=ema,slow=200) 0.05    10.0    1.0312824555833298  1.211853378635622  0.9336390309871492 1.581775703422821  -0.39117789281473103 1354   18057.092305229213
ma_cross(fast=50,kind=ema,slow=200) 0.1     0.0     1.2471502945484247  1.6296808283289974 1.0469429308873046 1.7855693803093367 -0.3776854816904155  1354   38253.05337805731 
ma_cross(fast=50,kind=ema,slow=200) 0.1     2.0     1.1583070552031192  1.5321770694437862 1.001543589152808  1.703591503705814  -0.38316432892871843 1354   37387.0014240667  
ma_cross(fast=50,kind=ema,slow=200) 0.1     5.0     1.031629030255028   1.3929646448800899 0.9336103479523311 1.5817133558997236 -0.3912894784928501  1354   36133.56146250623 
ma_cross(fast=50,kind=ema,slow=200) 0.1     10.0    0.8368782617683101  1.1784733953460083 0.8208139695144768 1.3814257611743135 -0.40458889102295936 1354   34159.51335776981 
ma_cross(fast=50,kind=ema,slow=200) 0.15    0.0     1.0319683262029136  1.574261373447995  0.9335773488603911 1.5816417542914851 -0.39140155845143676 1354   54229.304724508154
ma_cross(fast=50,kind=ema,slow=200) 0.15    2.0     0.9516523049683765  1.481837507157104  0.8883940877936566 1.5011025570947931 -0.3967587074433341  1354   53018.52021887275 
ma_cross(fast=50,kind=ema,slow=200) 0.15    5.0     0.8371176949343331  1.3497731637087789 0.8207790673381403 1.3813540518408247 -0.4047035651314552  1354   51265.5468774446  
ma_cross(fast=50,kind=ema,slow=200) 0.15    10.0    0.6610459358375222  1.1460855373843137 0.7085265944720507 1.1845930021884146 -0.41770753883768186 1354   48503.96015467917 
fng_momentum(n_days=7,thr=5)        0.05    0.0     0.5868847725169086  0.6219796251349992 1.1342473207622614 1.8068226466805544 -0.2210943437594286  355    3509.485261809048 
fng_momentum(n_days=7,thr=5)        0.05    2.0     0.5683732551547056  0.6032503622791672 1.1074516677553927 1.7620097186187216 -0.22410981912600159 355    3487.710712446149 
fng_momentum(n_days=7,thr=5)        0.05    5.0     0.5410242459588765  0.575578199914901  1.067235081650369  1.6949416542350009 -0.22860710611680501 355    3455.395395602441 
fng_momentum(n_days=7,thr=5)        0.05    10.0    0.49651690505741697 0.5305410104506725 1.0001288092371028 1.5835316803290442 -0.23604358644025225 355    3402.410539325558 
fng_momentum(n_days=7,thr=5)        0.1     0.0     0.5412450659763612  0.610385407671     1.067219230288976  1.6949083804921905 -0.22869015534458126 355    6914.034169463889 
fng_momentum(n_days=7,thr=5)        0.1     2.0     0.5232705309740879  0.591983951923126  1.0403846727761978 1.650280891596684  -0.23167488236373868 355    6871.342094903801 
fng_momentum(n_days=7,thr=5)        0.1     5.0     0.4967135112524126  0.5647932506105955 1.000112552461413  1.5834953482831302 -0.2361277708865257  355    6807.973935818306 
fng_momentum(n_days=7,thr=5)        0.1     10.0    0.45349117757112833 0.5205320072808539 0.9329215564968611 1.4725639328852362 -0.2434902484036442  355    6704.082970972549 
fng_momentum(n_days=7,thr=5)        0.15    0.0     0.49690933452839037 0.599076138976999  1.0000931340787627 1.5834593007295454 -0.23621263244656332 355    10216.68044486085 
fng_momentum(n_days=7,thr=5)        0.15    2.0     0.47945690095912297 0.580996025746912  0.9732270529999515 1.539029113451667  -0.2391680369914222  355    10153.912478778922
fng_momentum(n_days=7,thr=5)        0.15    5.0     0.45366483032530347 0.5542719522581141 0.9329030676962852 1.4725276399003835 -0.24357698316215226 355    10060.712193281057
fng_momentum(n_days=7,thr=5)        0.15    10.0    0.4116929972893031  0.5107721474792273 0.865648770296201  1.362105050808524  -0.2508665579780135  355    9907.915018992424 




==================== REGIME ANALYSIS ====================

strategy   dim   regime   days               ret_per_30d_%       total_ret_%         sharpe               sortino             max_dd_%            trades
--------   ---   ------   ----               -------------       -----------         ------               -------             --------            ------
ma_cross(f trend bear     128.52083333333334 1.8515913942069935  6.780688491295495   0.8068930604655925   1.1724082048606361  -17.700937212294367 208   
ma_cross(f trend bull     332.2916666666667  8.310089974867617   134.67589362234338  2.6272856975542482   3.736779682595405   -21.437415249884072 327   
ma_cross(f trend sideways 605.1458333333334  -2.0737935540137915 -37.541891210005886 -1.0056823889886828  -1.368810079938401  -44.70770331798584  797   
ma_cross(f vol   high_vol 520.0625           3.1634954899905283  59.26228356613154   1.12724850718802     1.6148090957556325  -27.239338025285598 645   
ma_cross(f vol   low_vol  547.9166666666666  0.05698345415357551 -3.988566815283523  0.026620790758033256 0.03589561116490684 -28.62299457661357  690   
fng_moment trend bear     128.52083333333334 -0.6205337420098316 -2.9537739408024732 -0.5433178230689676  -0.7580310880207518 -8.494393437436488  25    
fng_moment trend bull     332.2916666666667  2.7698949299103286  33.90606348649836   1.8677489821730593   2.5533080177674163  -13.200598604783742 120   
fng_moment trend sideways 605.1458333333334  0.8568961617881433  16.32435217448478   0.6468575298910888   0.8663152577731688  -18.02637430451217  195   
fng_moment vol   high_vol 520.0625           1.1903971387847463  19.93897942044822   0.7801207266336581   1.0869305188901572  -18.490817324789088 195   
fng_moment vol   low_vol  547.9166666666666  1.3361909328800812  25.69819894730816   1.1423442212700936   1.4817144440082823  -14.772256041672371 150   




==================== CORRELATION SENSITIVITY ====================

variant             corr_cap corr_win_bars ret_%              sharpe             sortino            calmar             max_dd_%            worst_14d_%         trades
-------             -------- ------------- -----              ------             -------            ------             --------            -----------         ------
baseline (corr off)          96            115.83070552031191 1.001543589152808  1.703591503705814  0.7621454765497088 -38.316432892871845 -14.959582306024434 1354  
corr cap 0.80       0.8      96            133.61665987006046 1.0783951911729974 1.8524145002557235 0.9276980080918266 -35.20043973223528  -14.673322874177707 1350  
corr cap 0.70       0.7      96            154.56686898508977 1.179637122522372  2.0482005252159383 1.0846433574959256 -33.655611068963545 -14.84812391280551  1292  
corr cap 0.60       0.6      96            170.55134228082886 1.2578236168041363 2.1997711546987597 1.2392952217919129 -31.71244918121854  -15.199179915141148 1201  




==================== AUDIT FILES (2026 validation exports) ====================

FullName                                                                                         Length
--------                                                                                         ------
A:\Roostoo Quant Trading competition\roostoo-quant\results\equity_final_bare_2026.csv           2198736
A:\Roostoo Quant Trading competition\roostoo-quant\results\equity_final_ladder_2026.csv         2202937
A:\Roostoo Quant Trading competition\roostoo-quant\results\open_positions_final_bare_2026.csv       867
A:\Roostoo Quant Trading competition\roostoo-quant\results\open_positions_final_ladder_2026.csv     866
A:\Roostoo Quant Trading competition\roostoo-quant\results\trades_final_bare_2026.csv             95340
A:\Roostoo Quant Trading competition\roostoo-quant\results\trades_final_ladder_2026.csv           95152




==================== FINAL BACKTEST (frozen, 2026) rerun ====================
bare done
FROZEN ladder 10/.5 20/.25 done

Validation window: 2026-01-01 .. 2026-10-02
                     0                           1
variant           bare  FROZEN ladder 10/.5 20/.25
ret_%            17.14                        1.93
realized_%       16.01                        0.78
unrealized_%      1.13                        1.15
sharpe            0.81                        0.13
sortino           1.29                         0.2
calmar            1.09                        0.04
max_dd_daily_%  -19.38                      -17.16
max_dd_bar_%    -21.09                      -17.52
trades             340                         340
open_pos             5                           5
fees_usd        4998.7                      3436.5
win_%            30.88                       30.88
profit_factor     1.21                        1.01


==================== SIZING DEV ====================
pf 0.1 done
pf 0.15 done
pf 0.2 done
pf 0.25 done
pf 0.3 done
 pos_frac  max_pos  max_exposure_%  ret_%  sortino  calmar  max_dd_%  w14_med_%  w14_worst_%  w14_pos_frac  trades  fees_usd
     0.10        5           40.95 115.83     1.70    0.76    -38.32      -0.51       -14.96          0.46    1354  37387.00
     0.15        5           55.63 149.97     1.65    0.75    -47.32      -0.68       -18.73          0.46    1354  57201.55
     0.20        5           67.23 173.04     1.61    0.74    -53.45      -0.84       -21.29          0.46    1354  75001.35
     0.25        5           76.27 188.52     1.58    0.73    -57.86      -1.03       -23.03          0.46    1354  90487.22
     0.30        5           83.19 198.57     1.56    0.72    -61.17      -1.12       -24.19          0.47    1354 103886.22


==================== 13-DAY WINDOW DISTRIBUTION (dev, pos_frac 0.15) ====================
python : A:\Roostoo Quant Trading competition\roostoo-quant\.venv\Scripts\python.exe: No module named rq.research.window13
At line:22 char:57
+ ... DISTRIBUTION (dev, pos_frac 0.15)" { python -m rq.research.window13 }
+                                          ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (A:\Roostoo Quan...search.win    dow13:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
 


==================== BASELINES DEV (buy and hold etc) ====================
                                 total_return  sharpe  sortino  calmar  max_dd   vol  n_trades  fees_paid  composite  w14_ret_med  w14_mdd_worst
buy&hold equal-weight (all)             0.543   0.548    0.797   0.340  -0.455 0.439     0.000     29.970      0.585        0.002         -0.247
buy&hold BTC (crypto pool only)         1.288   1.130    1.743   1.296  -0.245 0.278     0.000     29.970      1.425        0.005         -0.147
simple MA cross 20/50                   0.012   0.091    0.142   0.021  -0.190 0.104  4476.000  23114.171      0.091       -0.004         -0.052
simple RSI 14 (30/55)                  -0.111  -0.801   -0.965  -0.267  -0.146 0.048  4248.000  17412.508     -0.706       -0.001         -0.041


==================== UNIT TESTS ====================
..........                                                               [100%]
10 passed in 0.60s


==================== DATA COVERAGE ====================
index 2023-01-01 00:00:00+00:00 -> 2026-10-02 00:00:00+00:00
bars 65761
crypto cols 38 equity cols 0
['AAVE', 'ADA', 'APT', 'ARB', 'ASTER', 'AVAX', 'BNB', 'BTC', 'CRCLB', 'DOGE', 'DOT', 'ENA', 'ETH', 'FET', 'FIL', 'HBAR', 'ICP', 'LINK', 'LTC', 'MSTRB', 'NEAR', 'ONDO', 'PENGU', 'POL', 'PUMP', 'SNDKB', 'SOL', 'SPCXB', 'SUI', 'TAO', 'TRUMP', 'TRX', 'UNI', 'WLD', 'XLM', 'XPL', 'XRP', 'ZEC']
[]


==================== LIVE LOG SUMMARY (no secrets) ====================
log lines: 111
fills: 22
errors: 2
warnings: 3
2026-10-03 12:19:43,777 INFO filled BUY 41.851 SOL/USD @ 119.47 fee=4.999938
2026-10-03 12:19:44,673 INFO filled BUY 19.212 NVDAB/USD @ 234.2 fee=4.49945
2026-10-03 12:19:45,713 INFO filled BUY 22.599 AAVE/USD @ 179.17 fee=4.049062
2026-10-03 12:19:46,016 INFO filled BUY 15.122 NBISB/USD @ 240.95 fee=3.643645
2026-10-03 12:19:47,031 INFO filled BUY 4.282 BNB/USD @ 765.75 fee=3.278941
2026-10-03 14:56:11,129 INFO filled SELL 4.282 BNB/USD @ 767.25 fee=3.285364
2026-10-03 14:56:11,428 INFO filled BUY 5810.8 WLD/USD @ 0.5645 fee=3.280196
2026-10-03 15:00:36,927 INFO filled SELL 22.599 AAVE/USD @ 180.25 fee=4.073469
2026-10-03 15:00:37,146 INFO filled SELL 15.122 NBISB/USD @ 241.34 fee=3.649543
2026-10-03 15:00:38,321 INFO filled SELL 19.212 NVDAB/USD @ 234.8 fee=4.510977
2026-10-03 15:00:39,157 INFO filled SELL 41.851 SOL/USD @ 119.2 fee=4.988639
2026-10-03 15:00:39,346 INFO filled SELL 5810.8 WLD/USD @ 0.5643 fee=3.279034
2026-10-03 15:27:10,105 INFO filled BUY 27.626 AAVE/USD @ 180.94 fee=4.998648
2026-10-03 15:27:10,703 INFO filled BUY 7874 WLD/USD @ 0.5713 fee=4.498416
2026-10-03 15:27:11,615 INFO filled BUY 6.395 AMDB/USD @ 632.98 fee=4.047907
2026-10-03 15:27:12,545 INFO filled BUY 15.533 NVDAB/USD @ 234.52 fee=3.642799
2026-10-03 15:27:13,467 INFO filled BUY 20.377 MSTRB/USD @ 160.88 fee=3.278251
2026-10-03 15:37:09,022 INFO filled SELL 27.626 AAVE/USD @ 181.25 fee=5.007212
2026-10-03 15:37:09,311 INFO filled SELL 6.395 AMDB/USD @ 632.68 fee=4.045988
2026-10-03 15:37:10,995 INFO filled SELL 20.377 MSTRB/USD @ 160.86 fee=3.277844
2026-10-03 15:37:12,420 INFO filled SELL 15.533 NVDAB/USD @ 234.41 fee=3.64109
2026-10-03 15:37:13,856 INFO filled SELL 7873.9 WLD/USD @ 0.5844 fee=4.601507


==================== API JOURNAL (count only) ====================
journal lines: 96


==================== BOT SOURCE ====================
"""Live trading loop SKELETON - same signal code as the backtest (rq.signals), Roostoo execution.

STATUS: written against the documented API but NOT yet exercised against the real exchange (no keys / network in the
authoring environment). Test on the General Portfolio key first (`--dry-run`, then small), compare fills with the
backtest cost model, only then switch ROOSTOO_ENV=competition.

Design rules (competition Screen 1): fully autonomous, every request journaled (RoostooClient does that), config changes
only via commits, no manual API calls.
"""
from __future__ import annotations
import json, logging, time
from pathlib import Path
import pandas as pd
import requests
import yaml
from ..constants import TAKER_FEE, FREQ_MINUTES
from ..data.panel import build_panel
from ..execution import plan_entry, plan_exit
from ..roostoo.client import RoostooClient
from ..signals.core import to_target
from ..research.runner import ALL_BUILDERS

log = logging.getLogger("bot")
KL = "https://api.binance.com/api/v3/klines"


class Feed:
    """Rolling 5m klines per coin from Binance REST (signals) - Roostoo only provides the live ticker."""
    def __init__(self, coins: list[str], warm_bars: int = 3000):
        self.coins, self.warm, self.d = coins, warm_bars, {}

    def _fetch(self, sym, start_ms=None, limit=1000):
        p = {"symbol": sym, "interval": "5m", "limit": limit}
        if start_ms: p["startTime"] = start_ms
        r = requests.get(KL, params=p, timeout=15); r.raise_for_status()
        df = pd.DataFrame(r.json(), columns=["t", "open", "high", "low", "close", "volume", "ct", "qv", "n", "taker_buy_base", "tbq", "ig"])
        df["open_time"] = pd.to_datetime(df.t, unit="ms", utc=True)
        df = df.set_index("open_time")[["open", "high", "low", "close", "volume", "qv", "taker_buy_base"]].astype(float)
        return df.rename(columns={"qv": "quote_volume"})

    def update(self):
        now = pd.Timestamp.utcnow()
        for c in list(self.coins):
            sym = f"{c}USDT"
            try:
                if c not in self.d or len(self.d[c]) == 0:
                    start = int((now - pd.Timedelta(minutes=5 * self.warm)).timestamp() * 1000)
                    parts = []
                    while True:
                        df = self._fetch(sym, start); parts.append(df)
                        if len(df) < 1000: break
                        start = int(df.index[-1].timestamp() * 1000) + 1
                    self.d[c] = pd.concat(parts).drop_duplicates()
                else:
                    df = self._fetch(sym, int(self.d[c].index[-1].timestamp() * 1000) + 1)
                    self.d[c] = pd.concat([self.d[c], df]).loc[lambda x: ~x.index.duplicated()].tail(self.warm)
                self.d[c] = self.d[c][self.d[c].index <= now - pd.Timedelta(minutes=5)]
            except Exception as e:
                log.warning("feed skip %s: %s", c, e)
                if c in self.d and len(self.d[c]) == 0: self.d.pop(c)   # keep coin, retry next bar


class Bot:
    def __init__(self, cfg_path="config/live.yaml", dry_run=True, state_path="state/ledger.json"):
        self.cfg = yaml.safe_load(open(cfg_path)); self.dry = dry_run
        self.api = RoostooClient(); self.api.sync_clock()
        self.state_path = Path(state_path); self.state_path.parent.mkdir(exist_ok=True)
        info = self.api.exchange_info(); self.pairs = info["TradePairs"]
        cap = float(info.get("InitialWallet", {}).get("USD", 100_000))
        cw = self.cfg["crypto_weight"]
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else \
            {"pool_cash": {"crypto": cap * cw, "equity": cap * (1 - cw)}, "entries": {}}
        self.coins = [p["Coin"] for p in self.pairs.values() if p["CanTrade"] and p["Coin"] not in ("USDT", "USDC")][:40]
        self.feed = Feed(self.coins)
        self.freq = FREQ_MINUTES[self.cfg["timeframe"]]

    def save(self): self.state_path.write_text(json.dumps(self.state, indent=1))

    def signals(self) -> pd.Series:
        self.feed.update()
        good = {c: d for c, d in self.feed.d.items() if len(d) > 1500}
        newest = max(d.index.max() for d in good.values())
        good = {c: d for c, d in good.items() if d.index.max() >= newest - pd.Timedelta(minutes=20)}
        end = (newest + pd.Timedelta(minutes=5)).floor(f"{self.freq}min")
        p = build_panel(good, None, self.freq, end - pd.Timedelta(minutes=5 * 3000), end)
        spec = self.cfg["strategies"]["crypto"]
        cond = ALL_BUILDERS[spec["builder"]](p, {}, **spec["params"])
        t = to_target(cond, self.cfg["allow_short"]).iloc[-1]
        self.score = cond.score.iloc[-1] if cond.score is not None else pd.Series(dtype=float)
        log.info("signal bar %s: %d long / %d short", p.index[-1], (t > 0).sum(), (t < 0).sum())
        return t

    def cycle(self):
        cfgl = yaml.safe_load(open("config/live.yaml"))                       # re-read each cycle (kill switch)
        mode = cfgl.get("mode", "run")
        start = cfgl.get("start_utc")
        if start and pd.Timestamp.utcnow() < pd.Timestamp(str(start), tz="UTC"):
            log.info("before start_utc %s - idle", start); return
        tgt = self.signals()
        tick = self.api.ticker(); wallet = self.api.balance()
        self.state["pool_cash"]["crypto"] = float(wallet.get("USD", {}).get("Free", 0))   # wallet is truth
        fee = TAKER_FEE
        held = {c: v["Free"] + v["Lock"] for c, v in wallet.items() if c != "USD" and v["Free"] + v["Lock"] > 0}
        def _px(c):
            t = tick.get(f"{c}/USD", {})
            return float(t.get("LastPrice") or t.get("MaxBid") or t.get("MinAsk") or 0)
        usd = wallet.get("USD", {})
        eq = usd.get("Free", 0) + usd.get("Lock", 0) + sum((v["Free"] + v["Lock"]) * _px(c) for c, v in wallet.items() if c != "USD")
        peak = max(self.state.get("peak", eq), eq)
        self.state["peak"] = peak
        if not self.dry: self.save()
        dd = 1 - eq / peak if peak > 0 else 0.0
        mult = 1.0
        for th, m in sorted(cfgl.get("dd_ladder", []) or []):
            if dd >= th: mult = m
        log.info("equity %.2f peak %.2f dd %.1f%% ladder_mult %.2f", eq, peak, dd * 100, mult)
        # exits first
        for coin, qty in held.items():
            if mode == "liquidate" or (coin in tgt.index and tgt.get(coin, 0) <= 0):
                self._order(coin, "SELL", plan_exit(wallet[coin]["Free"], self.pairs[f"{coin}/USD"]["AmountPrecision"]), tick)
        if mode != "run":
            return
        # entries, sequential on remaining crypto-pool cash
        if mult <= 0:
            log.info("ladder mult 0 - no new entries"); return
        n_open = len([c for c in held if c not in tgt.index or tgt.get(c, 0) > 0])
        for coin in self._rank([c for c, v in tgt.items() if v > 0 and c not in held]):
            if n_open >= self.cfg["max_pos"]["crypto"]: break
            pair = f"{coin}/USD"; pi = self.pairs[pair]
            q = plan_entry(self.state["pool_cash"]["crypto"], self.cfg["pos_frac"] * mult, tick[pair]["MinAsk"], pi["AmountPrecision"], pi["MiniOrder"], fee)
            if q > 0 and self._order(coin, "BUY", q, tick): n_open += 1

    def _rank(self, cands):
        sc = getattr(self, "score", None)
        def s(c):
            try:
                v = float(sc.get(c)); return v if v == v else 0.0
            except Exception:
                return 0.0
        out = sorted(cands, key=lambda c: -s(c))
        log.info("entry order (score desc): %s", [(c, round(s(c), 4)) for c in out])
        return out

    def _order(self, coin, side, qty, tick) -> bool:
        pair = f"{coin}/USD"
        if qty <= 0: return False
        if self.dry:
            log.info("[dry-run] %s %s %s", side, qty, pair); return True
        try:
            d = self.api.place_order(pair, side, qty)
        except Exception as e:
            log.error("order failed %s %s: %s", side, pair, e); return False
        notional = d.get("FilledQuantity", 0) * d.get("FilledAverPrice", 0)
        fee = d.get("CommissionChargeValue", 0)
        self.state["pool_cash"]["crypto"] += (notional - fee) if side == "SELL" else -(notional + fee)
        self.save(); log.info("filled %s %s %s @ %s fee=%s", side, d.get("FilledQuantity"), pair, d.get("FilledAverPrice"), fee)
        return True

    def run(self):
        while True:
            t0 = time.time()
            try: self.cycle()
            except Exception: log.exception("cycle failed - holding")
            step = self.freq * 60                                  # wake 15 s after the next bar boundary
            time.sleep(max(5, (int(time.time()) // step + 1) * step + 15 - time.time()))


==================== EXECUTION + RISK + ENGINE HEADERS ====================
"""Order sizing/rounding shared by live trading and unit tests.  Mirrors the backtest engine's rules:
size = pos_frac x CURRENT pool cash, floor to AmountPrecision, respect MiniOrder, keep fee headroom."""
from __future__ import annotations
import math


def floor_qty(qty: float, amt_prec: int) -> float:
    f = 10 ** amt_prec
    return math.floor(qty * f + 1e-9) / f


def plan_entry(pool_cash: float, pos_frac: float, price: float, amt_prec: int, mini_order: float,
               fee: float, scale: float = 1.0) -> float:
    """Return the quantity to BUY (0.0 if below the minimum order)."""
    notional = min(pos_frac * pool_cash * scale, pool_cash / (1 + fee))
    q = floor_qty(notional / price, amt_prec)
    return q if q * price >= max(mini_order, 1e-12) else 0.0


def plan_exit(free_qty: float, amt_prec: int) -> float:
    return floor_qty(free_qty, amt_prec)
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


==================== CURRENT README ====================
# Roostoo Quant Research and Trading

A rule-based crypto research and execution framework for the Roostoo mock exchange. Historical strategy research uses external market history; Roostoo is used to inspect the tradable universe, read live prices and balances, and submit orders.

## Architecture

```text
Roostoo exchangeInfo/ticker -----------+--> universe snapshot and live execution
                                       |
Binance Vision 5m crypto history ------+--> data panel (10m / 30m, close-time indexed)
Yahoo underlying history (optional) ---+    + lagged Fear & Greed / VIX / DVOL
                                             |
                                             v
Indicators -> signal families / Elliott -> target positions
                                             |
                                             v
Research: train (2023-2025) -> report / walk-forward -> freeze shortlist
          -> test (2026 onward) -> metrics and validation ledger
                                             |
Backtest engine: separate cash pools -> sizing -> risk controls -> fees / slippage
                                             |
Live bot: Binance closed bars -> same signal builders -> Roostoo ticker / balance
          -> order planning -> Roostoo client -> API journal
```

Roostoo does not provide historical candles. The `discover` command checks its public exchange information and ticker endpoints; it does not supply training data. Crypto history is downloaded from Binance Vision. Optional equity history comes from Yahoo Finance and is only an underlying proxy, not Roostoo token history.

## Portfolio Pools

The backtest keeps two USD cash pools, funded once at the start of a run:

| Pool | Starting balance | Assets |
|---|---:|---|
| Crypto | `capital * crypto_weight` | Crypto-class assets with available history |
| Equity | `capital * (1 - crypto_weight)` | Equity-class assets with configured history |

Pool cash is not transferred or rebalanced between the two sleeves. Each new position is sized as `pos_frac` of the cash currently remaining in its own pool, subject to position and exposure caps. For example, the default `pos_frac: 0.10` invests 10% of available pool cash per entry, so later entries are smaller.

Research Stage A currently runs with 100% crypto allocation. The allocation sweep can compare configured crypto weights when both asset classes are present. The live bot currently implements only crypto entries and exits; the equity allocation is not deployed live. Backtest capital defaults to $100,000, while the current Roostoo `exchangeInfo` response in this workspace reported an initial USD wallet of $50,000. Confirm the competition account's actual starting wallet and align capital before comparing results.

## Strategy and Risk

The parameter grid in `rq/research/grid.py` covers momentum, trend, mean reversion, breakouts, volatility and sentiment filters, multi-indicator combinations, regime rules, and a causal Elliott-wave rule set. These are candidates to evaluate, not claims of proven alpha.

Signals are computed from information available at each bar close. A crypto signal fills at the next bar's open; an equity signal uses the next bar's close. External series are aligned by availability time. Backtests model taker fees and configured slippage. Risk controls include volatility sizing, position and exposure limits, optional correlation limits, stops, drawdown scaling, and drawdown halts.

## Setup (Windows PowerShell)

Python 3.10 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

API credentials are needed only for authenticated live checks and live trading. Put them in `.env`; never commit that file or paste credentials into chat.

## Train and Test

1. Refresh the Roostoo universe and ticker snapshot:

   ```powershell
   python -m rq.cli discover
   ```

2. Download real history and inspect it. This may take a while; Roostoo itself is not the candle source.

   ```powershell
   python -m rq.cli download --no-equity
   python -m rq.cli check-data
   ```

   To include configured Yahoo underlyings, run `python -m rq.cli download` without `--no-equity`.

3. Run the Stage A development search on 2023-01-01 through 2025-12-31. Start with one family if you want a shorter run; remove `--only` and `--limit` for the full grid.

   ```powershell
   python -m rq.cli stage-a --freq 30m --modes L --only ma_cross --limit 10
   python -m rq.cli report --stage A --freq 30m
   python -m rq.cli walkforward --builder ma_cross --freq 30m
   python -m rq.cli baselines --freq 30m --stage A
   ```

4. Choose candidates using the Stage A report and robustness checks. Freeze the shortlist before looking at 2026 results. The shortlist is a one-time lock; validation refuses unlisted strategies and records each evaluation.

   ```powershell
   python -m rq.cli freeze "<exact strategy name from report>" "<another exact strategy name>"
   python -m rq.cli validate --freq 30m
   ```

5. A narrow accounting unit-test command is available; it does not test strategy performance or connect to Roostoo.

   ```powershell
   python -m pytest tests/test_engine.py -q
   ```

`--freq 10m` is also supported. `results/experiment_log.csv` stores research runs, `results/shortlist.json` stores the frozen candidates, and `results/validation_ledger.jsonl` records Stage B evaluations. Local market data and panel caches are not included in the repository.

## Manual Roostoo API Checks

Public connectivity and current tradable instruments (no credentials, no orders):

```powershell
python -m rq.cli discover
```

Authenticated read-only bot check (requires valid Roostoo keys in `.env`). It reads exchange information, market tickers, and account balance and logs intended orders without sending them. It runs continuously; stop it with `Ctrl+C`.

```powershell
python -m rq.cli live --dry-run
```

Do not use `--confirm` for an API connectivity check; that enables real order submission. Replace and review the placeholder strategy in `config/live.yaml` before any live deployment. API requests and responses are journaled under `logs/`.

## Repository Map

| Path | Responsibility |
|---|---|
| `rq/roostoo/` | Roostoo REST client and universe discovery |
| `rq/data/` | External data downloads, alignment, and panel construction |
| `rq/signals/`, `rq/indicators.py` | Signal families and causal indicators |
| `rq/backtest/` | Portfolio simulation, risk, and performance metrics |
| `rq/research/` | Grid search, train/test evaluation, selection, and shortlist lock |
| `rq/live/`, `rq/execution.py` | Live signal loop and order planning |
| `config/` | Research defaults, live strategy, and universe overrides |
| `tests/` | Deterministic portfolio accounting unit tests |

## Important Limits

- Roostoo provides current ticker data, not historical candles. Research results depend on the external downloaded datasets.
- Equity history is an underlying proxy. Equity execution on Roostoo is not implemented in the live bot.
- The live config contains a placeholder strategy and must not be treated as validated.
- A backtest is not a live fill guarantee. Slippage, market impact, API behavior, and account restrictions can differ.

