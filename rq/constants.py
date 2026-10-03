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
