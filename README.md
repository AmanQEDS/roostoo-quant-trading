# Roostoo Quant Trading System

### Quantitative Research, Strategy Development, Backtesting, Validation and Live Execution

| | |
|---|---|
| **Repository** | `AmanQEDS/roostoo-quant-trading` |
| **Competition** | Roostoo Quant Trading Competition |
| **Primary timeframe** | 30-minute bars |
| **Execution venue** | Roostoo |
| **Production strategy** | EMA(50/200) + Donchian(24), long-only crypto |
| **Live configuration** | `config/live.yaml` |
| **Live entry point** | `python -m rq.cli live` (`rq/live/bot.py`) |
| **Production branch** | `main` |
| **Language** | Python 3 |

> **Status:** The production strategy is **EMA(50/200) + Donchian(24)**. The earlier **EMA(50/200)-only** strategy is retained throughout this document as the **historical baseline** and is *not* the production strategy.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Quick Start](#2-quick-start)
3. [Current Production Strategy](#3-current-production-strategy)
4. [Research Results](#4-research-results)
5. [System Architecture](#5-system-architecture)
6. [Repository Structure](#6-repository-structure)
7. [Configuration Reference](#7-configuration-reference)
8. [Data Layer](#8-data-layer)
9. [Universe Handling](#9-universe-handling)
10. [Indicators and Signals](#10-indicators-and-signals)
11. [Backtest Engine](#11-backtest-engine)
12. [Performance Metrics](#12-performance-metrics)
13. [Portfolio Construction](#13-portfolio-construction)
14. [Risk Management](#14-risk-management)
15. [Research Infrastructure](#15-research-infrastructure)
16. [Research Methodology](#16-research-methodology)
17. [Independent Validation](#17-independent-validation)
18. [Live Bot](#18-live-bot)
19. [Execution Safety](#19-execution-safety)
20. [State Management](#20-state-management)
21. [Daily Trading Tracker](#21-daily-trading-tracker)
22. [Testing](#22-testing)
23. [Setup and Deployment](#23-setup-and-deployment)
24. [Operations Runbook](#24-operations-runbook)
25. [Complete CLI Reference](#25-complete-cli-reference)
26. [Research vs Production Separation](#26-research-vs-production-separation)
27. [Change-Control Policy](#27-change-control-policy)
28. [Troubleshooting](#28-troubleshooting)
29. [Historical Baseline Research](#29-historical-baseline-research)
30. [Limitations and Disclaimer](#30-limitations-and-disclaimer)
31. [Glossary](#31-glossary)
32. [FAQ](#32-faq)
33. [Current Production Snapshot](#33-current-production-snapshot)

---

## 1. Overview

This repository contains the complete quantitative trading workflow built for the Roostoo Quant Trading Competition. It is a **research-to-production pipeline**, not a single trading script.

### 1.1 What the system does

| # | Stage | Purpose |
|---|---|---|
| 1 | Universe discovery | Ask Roostoo which instruments actually exist and are tradable |
| 2 | Data acquisition | Download historical bars into a research panel |
| 3 | Data-quality audit | Detect gaps, missing bars and inconsistent data |
| 4 | Indicator generation | Compute EMAs, Donchian channels and other features |
| 5 | Signal research | Compare strategy families under one framework |
| 6 | Backtesting | Simulate portfolio behavior with transaction costs |
| 7 | Out-of-sample testing | Walk-forward and validation-period evaluation |
| 8 | Sensitivity analysis | Cost, correlation, allocation and parameter sensitivity |
| 9 | Portfolio construction | Position sizing, concentration limits, allocation |
| 10 | Strategy freeze | Lock the selected configuration |
| 11 | Independent validation | Re-derive trade and P&L accounting separately |
| 12 | Live signal generation | Build the latest 30-minute bar and signals |
| 13 | Wallet reconciliation | Treat the exchange wallet as ground truth |
| 14 | Order execution | Construct and submit orders through Roostoo |
| 15 | Risk overlay | Drawdown-based exposure reduction |
| 16 | Regression tests | Automated checks before deployment |
| 17 | Daily reporting | Parse logs into dated Markdown reports |

### 1.2 Core design principle

The same conceptual strategy is carried from research into live execution.

- The **research layer** decides the strategy and portfolio rules.
- The **live layer** consumes the frozen configuration and translates signals into orders.
- Experimental research is kept separate from production code so that it cannot silently alter live behavior.

### 1.3 Design goals

| Goal | How it is addressed |
|---|---|
| Reproducibility | Explicit YAML configuration; frozen live config; test suite |
| Transparency | Simple, inspectable signal logic |
| Safety | Dry-run mode, `--confirm` gate, crypto-only order guard, dust filter |
| Realism | Transaction costs in backtests; independent accounting audit |
| Separation of concerns | Research, portfolio, risk, accounting and execution are distinct layers |
| Operability | Daily tracker, clear logging, runbook |

---

## 2. Quick Start

```bash
# 1. Clone
git clone https://github.com/AmanQEDS/roostoo-quant-trading.git
cd roostoo-quant-trading

# 2. Environment
python -m venv .venv
source .venv/bin/activate            # Linux / macOS
# .venv\Scripts\Activate.ps1         # Windows PowerShell

# 3. Dependencies
pip install -r requirements.txt

# 4. Credentials (never commit this file)
cp .env.example .env
# edit .env and add Roostoo API credentials

# 5. Verify
python -m pytest -q                   # expect: 11 passed

# 6. Dry run (no orders submitted)
python -m rq.cli live --dry-run

# 7. Live (real orders)
python -m rq.cli live --confirm
```

---

## 3. Current Production Strategy

### 3.1 Summary

```text
==================================================
Strategy:        EMA(50/200) + Donchian(24)
Builder:         ema_donchian
Timeframe:       30 minutes
Direction:       Long only
Asset class:     Crypto only
==================================================
```

### 3.2 Signal definition

A crypto asset becomes a **long candidate** when both conditions hold on the latest completed 30-minute bar:

```text
EMA(50) > EMA(200)              trend filter
        AND
Close > Donchian High(24)       breakout confirmation
        ↓
Long candidate
```

The position is **exited** when the trend condition reverses:

```text
EMA(50) < EMA(200)
        ↓
Exit / no long signal
```

Shorting is disabled. When no long signal exists, capital stays in cash.

### 3.3 Component roles

| Component | Definition | Role |
|---|---|---|
| **EMA(50)** | 50-period exponential moving average of close | Fast trend estimate |
| **EMA(200)** | 200-period exponential moving average of close | Slow trend estimate |
| **Trend filter** | EMA(50) > EMA(200) | Identifies a bullish regime |
| **Donchian High(24)** | Highest high over the prior 24 bars (12 hours at 30-minute resolution) | Defines the breakout level |
| **Breakout condition** | Close > Donchian High(24) | Requires fresh upside momentum, not merely being inside a trend |
| **Long-only** | No short positions | Holds cash when no signal |

<!-- VERIFY: confirm whether the Donchian high is computed on the prior 24 bars (shifted) or includes the current bar, and whether the exit rule is exactly EMA(50) < EMA(200) in rq/signals/families.py. -->

### 3.4 Why Donchian was added

The original production baseline was EMA(50/200). A Donchian breakout filter was tested as an additional trend-confirmation condition. In the 2026 validation it improved return and risk-adjusted performance, slightly reduced maximum drawdown, and reduced the number of trades.

### 3.5 Live parameters

| Parameter | Value |
|---|---|
| Strategy builder | `ema_donchian` |
| Fast EMA | 50 |
| Slow EMA | 200 |
| Donchian window | 24 |
| Timeframe | 30 minutes |
| Crypto weight | 100% (`crypto_weight: 1.0`) |
| Base position fraction | 10% (`pos_frac: 0.10`) |
| Maximum crypto positions | 5 |
| Maximum equity positions | 0 |
| Shorting | Disabled |
| Execution | Market orders |
| Risk overlay | Drawdown ladder (10% → 0.50×, 20% → 0.25×) |

---

## 4. Research Results

All figures are **historical model results under the tested assumptions**. They are not guarantees of future performance (see [Section 30](#30-limitations-and-disclaimer)).

### 4.1 Primary validation: baseline vs. production

- Command: `python -m rq.cli validate --freq 30m`
- Period: `2026-01-01 → 2026-10-02`
- Starting capital: `$100,000`

| Metric | EMA 50/200 (baseline) | EMA 50/200 + Donchian(24) (production) |
|---|---:|---:|
| Total return | +17.14% | **+23.97%** |
| Sharpe ratio | 0.81 | **1.06** |
| Sortino ratio | 1.29 | **1.72** |
| Maximum drawdown | -19.38% | **-18.79%** |
| Completed trades | 340 | **304** |

```text
Return:    +17.14%  →  +23.97%   (+6.83 percentage points)
Sharpe:      0.81   →    1.06
Sortino:     1.29   →    1.72
Max DD:    -19.38%  →  -18.79%
Trades:       340   →     304
```

### 4.2 Broader 2026 comparison

| Metric | EMA 50/200 | EMA 50/200 + Donchian(24) |
|---|---:|---:|
| Total return | +25.83% | **+30.45%** |
| Sharpe ratio | 1.118 | **1.272** |
| Sortino ratio | 1.874 | **2.127** |
| Maximum drawdown | -15.96% | **-15.41%** |
| Trades | 349 | **307** |

The two comparisons use different evaluation setups, so absolute figures differ. The *direction* of improvement is consistent across both.

### 4.3 Donchian window sweep

| Donchian N | Return | Sharpe | Sortino | Max DD | Trades |
|---:|---:|---:|---:|---:|---:|
| 12 | +27.28% | 1.162 | 1.933 | -17.28% | 324 |
| **24** | **+30.45%** | **1.272** | **2.127** | **-15.41%** | **307** |
| 48 | +28.40% | 1.207 | 2.028 | -16.93% | 306 |
| 96 | +29.62% | 1.264 | 2.114 | -15.28% | 293 |

N = 24 delivered the strongest overall return and risk-adjusted performance and was frozen for production. Neighboring windows (48, 96) are close, which suggests the improvement is not confined to one narrowly tuned value. It remains a single-sample comparison.

### 4.4 Reading the results

- The improvement appears in return **and** risk-adjusted metrics.
- Drawdowns remain substantial (roughly -15% to -19% in tested samples).
- Trend-following commonly has a low win rate offset by larger winners. The baseline's closed-trade win rate was 30.88% with a profit factor of 1.213.
- Short-horizon performance is uneven (see [Section 29.5](#295-14-day-return-distribution-baseline)).

---

## 5. System Architecture

### 5.1 Layered architecture

```text
                     ┌───────────────────────────┐
                     │        Roostoo API        │
                     │ Universe / Market Data /  │
                     │ Wallet / Orders / Ticker  │
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │     Data Acquisition      │
                     │ rq/roostoo/client.py      │
                     │ rq/roostoo/universe.py    │
                     │ rq/cli_download.py        │
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │      Data Validation      │
                     │ rq/data_audit.py          │
                     │ rq/gap_audit.py           │
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │   Indicators & Signals    │
                     │ rq/indicators.py          │
                     │ rq/signals/core.py        │
                     │ rq/signals/families.py    │
                     │ rq/signals/elliott.py     │
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │      Research Layer       │
                     │ loader / grid / runner    │
                     │ selection / lock          │
                     │ walk-forward / sensitivity│
                     │ benchmarks / regimes      │
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │      Backtest Engine      │
                     │ engine / metrics /        │
                     │ risk / audit              │
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │   Portfolio Construction  │
                     │ weights / position size / │
                     │ max positions / DD ladder │
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │   Independent Validation  │
                     │ rq.cli validate           │
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │         Live Bot          │
                     │ rq/live/bot.py            │
                     │ 30m signal cycle          │
                     │ wallet reconciliation     │
                     │ order construction        │
                     │ risk controls             │
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │      Roostoo Orders       │
                     │      Market execution     │
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │   Daily Trading Tracker   │
                     │ tracker/daily_tracker.py  │
                     └───────────────────────────┘
```

### 5.2 Live decision flow

```text
Roostoo market data
        ↓
Data-quality checks
        ↓
Indicators (EMA 50, EMA 200, Donchian 24)
        ↓
EMA 50/200 + Donchian(24) signal
        ↓
Candidate ranking
        ↓
Portfolio constraints (max positions, position size)
        ↓
Drawdown risk ladder
        ↓
Order construction
        ↓
Crypto-only order safety check
        ↓
Roostoo execution
        ↓
Wallet reconciliation
        ↓
Daily trading report
```

### 5.3 Layer responsibilities

| Layer | Responsibility | Must not |
|---|---|---|
| Data | Acquire and validate bars | Contain strategy logic |
| Signals | Convert bars into long/flat decisions | Know about wallet or orders |
| Backtest | Simulate portfolio from signals | Depend on live exchange state |
| Portfolio | Size and select positions | Generate signals |
| Risk | Scale exposure with drawdown | Predict returns |
| Execution | Convert target positions into orders | Change strategy parameters |
| Reporting | Summarize logs | Modify trading state |

### 5.4 Data flow: research vs live

```text
RESEARCH                                LIVE
────────                                ────
download → panel (loader.py)            ticker / market data (client.py)
        ↓                                       ↓
indicators + signals                    indicators + signals (same logic)
        ↓                                       ↓
backtest engine (simulated fills)       order construction (real fills)
        ↓                                       ↓
metrics / audit                         wallet reconciliation / tracker
```

---

## 6. Repository Structure

```text
.
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── status.py
│
├── config/
│   ├── default.yaml              # research / backtest defaults
│   ├── live.yaml                 # frozen live configuration
│   └── universe_overrides.yaml   # controlled universe overrides
│
├── rq/
│   ├── __init__.py
│   ├── cli.py                    # main command-line interface
│   ├── cli_download.py           # historical data download commands
│   ├── config.py                 # YAML configuration loading
│   ├── constants.py              # project-wide constants
│   ├── execution.py              # shared execution abstractions
│   ├── indicators.py             # technical indicators
│   ├── data_audit.py             # data-quality checks
│   ├── gap_audit.py              # missing-bar / discontinuity checks
│   │
│   ├── backtest/
│   │   ├── __init__.py
│   │   ├── engine.py             # portfolio / backtest engine
│   │   ├── metrics.py            # performance statistics
│   │   ├── risk.py               # drawdown ladder and risk controls
│   │   └── audit.py              # independent accounting audit
│   │
│   ├── live/
│   │   ├── __init__.py
│   │   └── bot.py                # production execution component
│   │
│   ├── research/
│   │   ├── __init__.py
│   │   ├── benchmarks.py         # reference comparisons
│   │   ├── combine.py            # combine research outputs
│   │   ├── combo.py              # strategy / portfolio combinations
│   │   ├── corr_sens.py          # correlation sensitivity
│   │   ├── cost_sens.py          # transaction-cost sensitivity
│   │   ├── final_backtest.py     # final standardized backtest
│   │   ├── grid.py               # strategy search space
│   │   ├── loader.py             # research data panel
│   │   ├── lock.py               # configuration freezing
│   │   ├── regimes.py            # market-regime analysis
│   │   ├── risk_stability.py     # stability of risk characteristics
│   │   ├── risk_test.py          # targeted risk tests
│   │   ├── runner.py             # research execution layer
│   │   ├── selection.py          # candidate selection
│   │   ├── sizing_dev.py         # position-sizing research
│   │   ├── w14_dist.py           # 14-day return distribution
│   │   └── wf_fixed.py           # fixed walk-forward implementation
│   │
│   ├── roostoo/
│   │   ├── __init__.py
│   │   ├── client.py             # exchange / API client
│   │   └── universe.py           # exchange universe discovery
│   │
│   └── signals/
│       ├── __init__.py
│       ├── core.py               # core signal interfaces
│       ├── elliott.py            # Elliott-wave research signals
│       └── families.py           # strategy families (incl. ema_donchian)
│
├── tests/
│   ├── helpers.py
│   ├── test_engine.py
│   └── test_daily_tracker.py
│
└── tracker/
    ├── daily_tracker.py          # log parser / daily report generator
    └── reports/                  # generated daily reports
```

> **Note:** `rq/research/wf_fixed.py` is a Python research module. There is **no** `wf-fixed` CLI command. Use `python -m rq.cli walkforward` for walk-forward from the CLI.

### 6.1 File-by-file reference

#### Top level

| File | Purpose |
|---|---|
| `README.md` | This document |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for credentials; copy to `.env` and fill in |
| `.gitignore` | Excludes secrets, virtual environments and generated artifacts |
| `status.py` | Status helper script <!-- VERIFY: confirm what status.py prints --> |

#### `config/`

| File | Purpose |
|---|---|
| `default.yaml` | Baseline research/backtest parameters (portfolio, costs, strategy settings) |
| `live.yaml` | Frozen live execution configuration |
| `universe_overrides.yaml` | Explicit overrides for the trading universe |

#### `rq/` core

| File | Purpose |
|---|---|
| `cli.py` | Operational entry point for research and live execution |
| `cli_download.py` | Download-side command functionality for historical Roostoo data |
| `config.py` | Loads and interprets YAML; bridges config files and Python components |
| `constants.py` | Central research windows and fixed values, preventing inconsistent dates across scripts |
| `execution.py` | Execution abstractions shared by the trading workflow |
| `indicators.py` | Reusable technical indicators |
| `data_audit.py` | Data-quality checks before data contaminates results |
| `gap_audit.py` | Missing bars and discontinuities |

#### `rq/backtest/`

| File | Purpose |
|---|---|
| `engine.py` | Progresses the portfolio through time: signals, positions, cash, fills, fees, mark-to-market |
| `metrics.py` | Computes return, Sharpe, Sortino, Calmar, drawdown, volatility and trade statistics |
| `risk.py` | Drawdown ladder and portfolio risk controls |
| `audit.py` | Independent accounting; separates realized from unrealized P&L |

#### `rq/live/`

| File | Purpose |
|---|---|
| `bot.py` | Live loop: config, market data, signals, wallet, risk, orders, reconciliation |

#### `rq/roostoo/`

| File | Purpose |
|---|---|
| `client.py` | API client for market data, ticker, balance, wallet and orders |
| `universe.py` | Discovers and represents the actual Roostoo trading universe |

#### `rq/signals/`

| File | Purpose |
|---|---|
| `core.py` | Core signal-building functionality and shared interfaces |
| `families.py` | Signal/strategy families used in research, including the production `ema_donchian` builder |
| `elliott.py` | Elliott-wave research signals (research only) |

#### `rq/research/`

| File | Purpose |
|---|---|
| `loader.py` | Loads the research data panel and extended data |
| `grid.py` | Defines the strategy search space |
| `runner.py` | Connects data → strategy → portfolio config → backtest → metrics |
| `selection.py` | Reduces a large candidate set to a shortlist using documented criteria |
| `lock.py` | Freezes selected configurations |
| `final_backtest.py` | Standardized final backtest of the selected configuration |
| `benchmarks.py` | Reference comparisons |
| `combine.py` / `combo.py` | Combination logic for strategies and portfolios |
| `corr_sens.py` | Correlation sensitivity |
| `cost_sens.py` | Transaction-cost sensitivity |
| `regimes.py` | Market-regime analysis |
| `risk_stability.py` | Stability of risk characteristics |
| `risk_test.py` | Targeted risk tests |
| `sizing_dev.py` | Position-sizing development, separate from production |
| `w14_dist.py` | Forward 14-day return distribution |
| `wf_fixed.py` | Fixed walk-forward implementation |

#### `tests/` and `tracker/`

| File | Purpose |
|---|---|
| `tests/helpers.py` | Shared test helpers |
| `tests/test_engine.py` | Backtest engine and related behavior |
| `tests/test_daily_tracker.py` | Daily tracker parsing |
| `tracker/daily_tracker.py` | Generates dated Markdown reports from logs |
| `tracker/reports/` | Output directory for generated reports |

---

## 7. Configuration Reference

### 7.1 `config/live.yaml`

The live configuration is deliberately explicit so that deployment does not depend on hidden Python defaults.

```yaml
timeframe: 30m
crypto_weight: 1.0
pos_frac: 0.10
max_pos: {crypto: 5, equity: 0}
allow_short: false
exec_mode: market
limit_timeout_s: 90

strategies:
  crypto:
    builder: ema_donchian
    params:
      fast: 50
      slow: 200
      n: 24
  equity: null

mode: run

dd_ladder:
  - [0.10, 0.5]
  - [0.20, 0.25]

start_utc: "2026-10-03 00:00"
```

### 7.2 Parameter reference

| Key | Value | Type | Meaning |
|---|---|---|---|
| `timeframe` | `30m` | string | Signal bar frequency |
| `crypto_weight` | `1.0` | float | Fraction of portfolio allocated to the crypto sleeve (100%) |
| `pos_frac` | `0.10` | float | Base fraction of portfolio used to size one position (10%) |
| `max_pos.crypto` | `5` | int | Maximum simultaneous crypto positions |
| `max_pos.equity` | `0` | int | Equity positions disabled |
| `allow_short` | `false` | bool | Long-only |
| `exec_mode` | `market` | string | Market-order execution |
| `limit_timeout_s` | `90` | int | Timeout in seconds for limit-order mode; relevant only if limit execution is selected |
| `strategies.crypto.builder` | `ema_donchian` | string | Strategy builder name |
| `strategies.crypto.params.fast` | `50` | int | Fast EMA period |
| `strategies.crypto.params.slow` | `200` | int | Slow EMA period |
| `strategies.crypto.params.n` | `24` | int | Donchian window |
| `strategies.equity` | `null` | — | No equity strategy |
| `mode` | `run` | string | Live execution mode |
| `dd_ladder` | see below | list | Drawdown thresholds and exposure multipliers |
| `start_utc` | `"2026-10-03 00:00"` | string | Start gate (UTC) |

### 7.3 Interaction of sizing parameters

```text
crypto_weight   → how much of the portfolio the crypto sleeve may use
pos_frac        → base size of ONE position
max_pos.crypto  → cap on the number of simultaneous positions
dd_ladder       → multiplier applied on top of base sizing after drawdowns
```

At full exposure with 5 positions at 10% each, the portfolio would hold up to 50% of equity in crypto, scaled down by the drawdown multiplier when the ladder is active. <!-- VERIFY: confirm that the 10% base is applied to total equity and that the multiplier scales new position sizes. -->

### 7.4 `config/default.yaml`

Baseline research and backtest parameters: portfolio settings, transaction-cost assumptions and strategy-related defaults. It provides a reproducible baseline so research parameters are not scattered through Python files. It is **not** used to drive live trading.

### 7.5 `config/universe_overrides.yaml`

Controlled overrides for the trading universe. Use it when the live exchange universe differs from the research universe or when specific instruments need explicit handling.

### 7.6 Environment variables

Credentials live in a local `.env` file created from `.env.example`.

| Rule | Detail |
|---|---|
| Never commit `.env` | It must remain in `.gitignore` |
| Never print keys in logs | Logs are parsed by the tracker and may be shared |
| Rotate on exposure | If a key is ever committed or pasted publicly, revoke and regenerate it |

<!-- VERIFY: list the exact variable names from .env.example here. -->

### 7.7 Changing configuration safely

1. Edit the configuration on a branch.
2. Run `python -m pytest -q`.
3. Run `python -m rq.cli live --dry-run` and review output.
4. For strategy or risk changes, repeat the validation cycle ([Section 17](#17-independent-validation)).
5. Commit the configuration change separately from code changes.

---

## 8. Data Layer

### 8.1 Components

| Component | File | Role |
|---|---|---|
| Client | `rq/roostoo/client.py` | API access |
| Universe | `rq/roostoo/universe.py` | Discover tradable instruments |
| Download | `rq/cli_download.py` | Historical acquisition |
| Panel loader | `rq/research/loader.py` | Load data for research |
| Data audit | `rq/data_audit.py` | Quality checks |
| Gap audit | `rq/gap_audit.py` | Missing bars |

### 8.2 Why data quality matters at 30 minutes

A 30-minute strategy depends on continuous bars. A missing bar can:

- shift the effective lookback of EMA(200) and Donchian(24),
- produce artificial crosses or breakouts,
- distort realized trade durations,
- bias performance metrics.

The gap audit therefore checks specifically for missing bars and discontinuities before research results are trusted.

### 8.3 Data workflow

```bash
python -m rq.cli discover      # enumerate the Roostoo universe
python -m rq.cli download      # acquire historical bars
python -m rq.cli check-data    # audit data quality and gaps
```

### 8.4 Warm-up requirement

EMA(200) on 30-minute bars needs at least 200 bars (about 100 hours) of history before it is meaningful; in practice more history is needed for the exponential average to settle. The live bot must therefore load enough history before generating signals. <!-- VERIFY: confirm the number of bars the live bot fetches for warm-up. -->

---

## 9. Universe Handling

The live system does not assume that a research ticker list matches the live exchange universe.

### 9.1 Classification

- The universe is discovered from Roostoo.
- The **authoritative `AssetType`** supplied by Roostoo is used for classification.
- The exchange universe was classified as **67 crypto** and **21 stock** instruments at the time of documentation.

### 9.2 Filtering

Eligible crypto assets are filtered using:

| Filter | Purpose |
|---|---|
| Tradability | Exclude instruments that cannot currently be traded |
| Spread | Exclude instruments with excessive bid/ask spread |
| Minimum 24-hour trading value | Exclude illiquid instruments |
| Asset type = crypto | Keep the crypto-only constraint |
| Liquidity ranking | Order the remaining instruments |

Up to the top 40 eligible crypto assets are used for signal generation. <!-- VERIFY: top-40 cap, spread threshold and minimum 24h value threshold. -->

### 9.3 Equity exclusion

Equity instruments are excluded from normal strategy entries. This prevents stock instruments from entering a crypto-only strategy. Existing equity holdings are handled by a dedicated liquidation path ([Section 18.4](#184-existing-portfolio-handling)).

### 9.4 Overrides

`config/universe_overrides.yaml` allows explicit handling of specific instruments without changing code.

---

## 10. Indicators and Signals

### 10.1 Exponential moving average

An EMA gives more weight to recent observations. For period *N*:

```text
alpha = 2 / (N + 1)
EMA_t = alpha * Close_t + (1 - alpha) * EMA_{t-1}
```

The production strategy uses N = 50 (fast) and N = 200 (slow). The exact smoothing/initialization convention follows `rq/indicators.py`.

### 10.2 Donchian channel

For window *n*:

```text
DonchianHigh_t(n) = max(High over the n bars used by the implementation)
DonchianLow_t(n)  = min(Low over the n bars used by the implementation)
```

The production strategy uses n = 24 on 30-minute bars (12 hours). Only the upper band is used: the signal requires `Close > DonchianHigh(24)`.

<!-- VERIFY: whether the high is shifted by one bar to avoid including the current bar, and whether it uses High or Close values. -->

### 10.3 Signal evaluation

On each completed 30-minute bar, per asset:

```text
trend      = EMA(50) > EMA(200)
breakout   = Close > DonchianHigh(24)
long_signal = trend AND breakout
```

### 10.4 Signal state and exits

```text
Flat  ──(trend AND breakout)──▶ Long
Long  ──(EMA50 < EMA200)──────▶ Flat
```

A held position is not closed merely because the breakout condition stops being true on a later bar; it is closed when the trend condition reverses. <!-- VERIFY: confirm this exit semantics against families.py. -->

### 10.5 Candidate ranking

When more candidates exist than free position slots, candidates are ranked by the strategy score and the top candidates are selected subject to portfolio constraints.

<!-- VERIFY: document the exact score used to rank ema_donchian candidates. -->

### 10.6 Other signal families (research only)

| Family | Description | Status |
|---|---|---|
| `ma_cross` | EMA/SMA crossover (baseline: EMA 50/200) | Historical baseline |
| `ema_donchian` | EMA trend + Donchian breakout | **Production** |
| `fng_momentum` | Fear & Greed change over a horizon | Research candidate |
| `fng_contrarian` | Fear & Greed contrarian entries | Research candidate; not positive in validation |
| Elliott-wave signals | `rq/signals/elliott.py` | Research only |

---

## 11. Backtest Engine

### 11.1 Purpose

`rq/backtest/engine.py` turns historical signals into simulated portfolio behavior. Returns are produced by simulated trading — positions, cash, fills and fees — rather than by multiplying a signal column by future returns.

### 11.2 What the engine tracks

| Quantity | Description |
|---|---|
| Signals | Per-asset long/flat decisions |
| Positions | Quantity held per asset |
| Cash | Uninvested capital |
| Portfolio value | Cash plus mark-to-market positions |
| Fills | Simulated order executions |
| Transaction effects | Fees applied on each trade |
| Position changes | Entries, exits, resizing |
| Mark-to-market | Valuation at each bar |

### 11.3 Principles

| Principle | Rationale |
|---|---|
| Costs included | Strategies with many trades can look profitable before fees and weak after |
| Portfolio-level simulation | Concentration limits and sizing affect results |
| Drawdown ladder applied | Backtest risk behavior matches live behavior |
| Audit available | Headline metrics can be cross-checked |

### 11.4 Avoiding look-ahead bias

Signals computed on a completed bar must only influence trades after that bar. Any change to the engine, signal timing or fill assumptions should be reviewed specifically for look-ahead bias and then covered by a test. <!-- VERIFY: document the exact fill convention (next-bar open vs current close). -->

### 11.5 Open positions at period end

The validation reports realized and unrealized P&L separately. At the end of the baseline validation period, the baseline strategy held 5 open positions, so part of the final value was unrealized (see [Section 29.1](#291-baseline-validation-detail)).

---

## 12. Performance Metrics

`rq/backtest/metrics.py` computes statistics used consistently across research and validation.

| Metric | Meaning |
|---|---|
| Total return | Final value relative to starting capital |
| Sharpe ratio | Return per unit of total volatility |
| Sortino ratio | Return per unit of downside volatility |
| Calmar ratio | Return relative to maximum drawdown |
| Maximum drawdown | Largest peak-to-trough decline in portfolio value |
| Volatility | Standard deviation of returns |
| Downside deviation | Standard deviation of negative returns |
| Trade count | Number of completed trades |
| Fees | Total transaction fees paid |
| Final value | Ending portfolio value |
| Win rate | Share of closed trades with positive net P&L |
| Profit factor | Gross profit divided by gross loss |
| Average trade P&L | Mean net P&L per closed trade |
| Median holding period | Median trade duration |

### 12.1 Two drawdown measures

Validation reports both:

| Measure | Description |
|---|---|
| Daily max drawdown | Computed on daily portfolio values |
| Bar-level max drawdown | Computed on 30-minute portfolio values; typically deeper |

Bar-level drawdown is more conservative because it captures intraday troughs.

### 12.2 Interpreting a low win rate

```text
many small losing trades
        +
fewer large winning trades
        =
positive aggregate P&L
```

A win rate near 30% is consistent with a profit factor above 1 for trend-following strategies.

### 12.3 Composite score

Research sweeps also report a composite score combining several metrics for ranking configurations. <!-- VERIFY: document the composite formula from selection.py. -->

---

## 13. Portfolio Construction

### 13.1 Production portfolio

```text
Asset class:          Crypto only
Crypto allocation:    100%
Equity allocation:    0%
Base position size:   10%
Maximum positions:    5
Direction:            Long only
Execution:            Market
```

### 13.2 Parameter roles

| Parameter | Role |
|---|---|
| `crypto_weight` | Share of the portfolio belonging to the crypto sleeve |
| `pos_frac` | Base fraction used to size an individual position |
| `max_pos.crypto` | Concentration limit |

### 13.3 Selection procedure

1. Compute the signal for each eligible asset.
2. Collect long candidates.
3. Rank candidates by strategy score.
4. Keep currently held positions that remain valid.
5. Fill remaining slots (up to 5) with top-ranked new candidates.
6. Size each new position using `pos_frac` and the drawdown multiplier.
7. Construct orders for the difference between target and current holdings.

### 13.4 Sizing trade-offs from research

Allocation and position size materially change the risk profile even when the signal is identical (see [Section 29.4](#294-allocation-sweep-baseline)). Higher crypto weight and larger position fractions raised both return and drawdown in the baseline sweep.

### 13.5 Dust

Residual balances worth less than about $5 are ignored when counting positions ([Section 19](#19-execution-safety)).

---

## 14. Risk Management

### 14.1 Drawdown ladder

| Portfolio drawdown | Exposure multiplier |
|---|---:|
| < 10% | 1.00 |
| ≥ 10% | 0.50 |
| ≥ 20% | 0.25 |

Configured as:

```yaml
dd_ladder:
  - [0.10, 0.5]
  - [0.20, 0.25]
```

### 14.2 Behavior

```text
Normal state:              multiplier = 1.00
Drawdown reaches 10%:      multiplier = 0.50
Drawdown reaches 20%:      multiplier = 0.25
```

Drawdown is measured relative to peak equity, which the bot tracks. The ladder does not generate signals and does not predict returns; it controls exposure after losses.

<!-- VERIFY: confirm whether the multiplier applies only to new entries or also resizes existing positions, and whether it resets when equity recovers. -->

### 14.3 Structural controls

| Control | Value |
|---|---|
| Direction | Long only |
| Maximum positions | 5 |
| Base position size | 10% |
| Asset type | Crypto only |
| Dust filter | ~$5 |
| Dry-run gate | `--dry-run` |
| Live confirmation | `--confirm` |

### 14.4 Observed risk in testing

| Sample | Max drawdown |
|---|---:|
| Primary validation, production strategy | -18.79% |
| Primary validation, baseline (daily) | -19.38% |
| Primary validation, baseline (bar-level) | -21.09% |
| Broader 2026 comparison, production strategy | -15.41% |

Live drawdowns may exceed tested values.

---

## 15. Research Infrastructure

### 15.1 Research pipeline

```text
Data
  ↓
Strategy specification (grid.py)
  ↓
Portfolio configuration
  ↓
Backtest (runner.py → engine.py)
  ↓
Metrics (metrics.py)
  ↓
Selection (selection.py)
  ↓
Lock (lock.py)
```

### 15.2 Module roles

| Module | Question it answers |
|---|---|
| `grid.py` | Which strategy specifications should be evaluated? |
| `runner.py` | What are the results for each specification under a portfolio config? |
| `selection.py` | Which candidates survive documented performance and stability criteria? |
| `lock.py` | How is the chosen configuration frozen? |
| `final_backtest.py` | What is the clean final result after exploration? |
| `benchmarks.py` | Is the strategy better than simple reference approaches? |
| `cost_sens.py` | Does the edge survive higher fees? |
| `corr_sens.py` | Do results depend on a particular correlation assumption? |
| `regimes.py` | How does behavior change across market environments? |
| `risk_stability.py` | Are risk characteristics stable over time? |
| `risk_test.py` | Do targeted risk scenarios behave acceptably? |
| `sizing_dev.py` | How does sizing change the risk profile? |
| `w14_dist.py` | What is the distribution of 14-day outcomes? |
| `wf_fixed.py` | Does performance persist in fixed walk-forward windows? |
| `combine.py`, `combo.py` | How do strategies/portfolios combine? |

### 15.3 Running research

```bash
python -m rq.cli stage-a
python -m rq.cli report
python -m rq.cli walkforward --help
python -m rq.cli alloc-sweep --help
python -m rq.cli freeze --help
python -m rq.cli baselines --help
python -m rq.research.w14_dist
```

### 15.4 Allocation sweep example

```bash
python -m rq.cli alloc-sweep \
  --crypto "ma_cross(fast=50,kind=ema,slow=200)" \
  --freq 30m
```

The `--crypto` argument takes a strategy specification string. Run `python -m rq.cli alloc-sweep --help` for the full argument list.

<!-- VERIFY: add the specification string for ema_donchian, e.g. ema_donchian(fast=50,slow=200,n=24), if that is the accepted syntax. -->

---

## 16. Research Methodology

### 16.1 Staged process

```text
Universe
   ↓
Historical Data
   ↓
Data Quality
   ↓
Signal Research
   ↓
Candidate Strategies
   ↓
Backtest (with transaction costs)
   ↓
Walk-Forward / Out-of-Sample Testing
   ↓
Cost / Correlation / Risk Sensitivity
   ↓
Allocation Sweep
   ↓
Freeze
   ↓
Independent Validation
   ↓
Dry-Run Live Simulation
   ↓
Deployment
```

A strong historical backtest alone is not considered sufficient evidence for deployment.

### 16.2 Evaluation criteria

- Total return, Sharpe, Sortino, Calmar
- Maximum drawdown, volatility, downside deviation
- Trade count and fees
- Portfolio exposure
- Rolling 14-day behavior
- Sensitivity to costs, correlations and allocation
- Parameter sensitivity (e.g. Donchian window sweep)
- Walk-forward persistence
- Live dry-run behavior

### 16.3 Why a simple strategy

| Advantage | Explanation |
|---|---|
| Transparent | Signal logic is easy to inspect |
| Low complexity | Fewer parameters, less overfitting risk |
| Debuggable | Failures are easy to trace |
| Verifiable live | Live output can be compared with research |
| Few fragile dependencies | No reliance on unstable external features |
| Backtest/live parity | One concept, two environments |
| Interpretable risk | Easy to reason about drawdown sources |

### 16.4 Parameter selection discipline

The Donchian window was chosen from a sweep over {12, 24, 48, 96}. Results for 24, 48 and 96 are close, which suggests moderate parameter robustness. Because the selection was made on the same 2026 sample used to report results, some selection bias remains possible ([Section 30](#30-limitations-and-disclaimer)).

### 16.5 Transaction costs

Fees are included in research and backtests. In the primary validation the production strategy also traded less than the baseline (304 vs 340 trades), consistent with the Donchian breakout acting as an additional confirmation filter.

---

## 17. Independent Validation

### 17.1 Command

```bash
python -m rq.cli validate --freq 30m
```

### 17.2 What it does

`rq/backtest/audit.py` and the `validate` command reconstruct portfolio and trade statistics independently of headline backtest metrics. They:

- report **realized** and **unrealized** P&L separately,
- check accounting for positions still open at period end,
- report daily and bar-level drawdown,
- report win rate, profit factor, average trade P&L and holding periods.

### 17.3 Why it exists

When a strategy ends the period with open positions, headline return mixes realized trades and mark-to-market gains. Reconstructing the accounting separately confirms that:

```text
final value = starting capital + realized P&L + unrealized P&L
```

### 17.4 Validation checklist before a strategy change

| Step | Check |
|---|---|
| 1 | Run `python -m pytest -q` |
| 2 | Run `python -m rq.cli validate --freq 30m` |
| 3 | Compare return, Sharpe, Sortino, drawdown, trades with the previous baseline |
| 4 | Confirm realized + unrealized reconciles to final value |
| 5 | Run `python -m rq.cli live --dry-run` |
| 6 | Review dry-run orders for sanity |

---

## 18. Live Bot

### 18.1 Component

`rq/live/bot.py` is the production execution component.

### 18.2 Responsibilities

1. Load the live configuration
2. Connect to Roostoo
3. Discover and filter the crypto universe
4. Fetch market data and build the latest 30-minute signal bar
5. Generate strategy signals and rank candidates
6. Read the wallet and reconcile existing positions
7. Apply portfolio and risk constraints
8. Construct and submit orders
9. Re-check portfolio state after execution
10. Maintain peak equity, drawdown and risk-multiplier state

### 18.3 Cycle

```text
              ┌──────────────────────────────┐
              │  Wait for next 30-minute bar │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │  start_utc reached?          │──no──▶ remain idle
              └──────────────┬───────────────┘
                             │ yes
                             ▼
              ┌──────────────────────────────┐
              │  Refresh universe + prices   │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │  Read wallet (source of      │
              │  truth) and reconcile        │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │  Compute signals and rank    │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │  Update peak equity,         │
              │  drawdown, multiplier        │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │  Build target positions      │
              │  and orders                  │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │  Safety checks               │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │  Submit (live) or print      │
              │  (dry-run)                   │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │  Re-read wallet, log state   │
              └──────────────────────────────┘
```

### 18.4 Existing portfolio handling

The bot does not assume the account starts empty. At startup it reads the current Roostoo wallet and reconciles existing holdings.

| Holding type | Handling |
|---|---|
| Existing **crypto** | Handled by normal portfolio-management logic |
| Existing **equity** | Handled by a dedicated liquidation path, because the production strategy is crypto-only |
| Dust | Ignored below the ~$5 marked-value threshold |

After liquidation, the wallet is refreshed so subsequent crypto position sizing uses the updated balance. This lets the crypto strategy take over an existing competition portfolio.

### 18.5 Wallet reconciliation

The wallet is the **source of truth** for available cash and holdings. Local state is reconciled against the exchange, which reduces divergence after:

- partial fills,
- rejected orders,
- process restarts,
- external account changes.

### 18.6 Start gate

`start_utc` acts as a start gate. The bot can be launched before the configured start time; it stays idle until then and begins trading afterward. This allows the process to be started and verified ahead of the competition start.

### 18.7 Dry-run mode

```bash
python -m rq.cli live --dry-run
```

Runs the full signal, ranking and order-construction path **without submitting orders**. During testing the dry run:

- read market data,
- calculated signals,
- ranked candidates,
- constructed simulated BUY orders,
- observed that rankings shift slightly between consecutive bars while portfolio and risk state stay stable.

### 18.8 Live mode

```bash
python -m rq.cli live --confirm
```

`--confirm` is required to submit real orders. Without it, the CLI does not place live trades.

<!-- VERIFY: confirm that omitting --confirm (and --dry-run) causes the CLI to refuse or default to dry-run. -->

### 18.9 Pre-live dry-run checklist

| Check | Expected |
|---|---|
| Signal bars advance | Timestamps move every 30 minutes |
| Symbols valid | All pairs exist on Roostoo |
| Wallet readable | Balances load without error |
| Equity reasonable | Matches the account |
| Ranking sensible | Candidates ordered by strategy score |
| Quantities sensible | Respect position fraction and exchange precision |
| No unexpected positions | Wallet matches expectation |
| No pathological orders | No repeated or oversized orders |

---

## 19. Execution Safety

| Safeguard | Description |
|---|---|
| **Crypto-only order guard** | Before submission, the bot verifies the Roostoo pair is classified as crypto. Non-crypto orders are blocked by the final order safety check |
| **Dust handling** | Balances with marked value below ~$5 are ignored when counting meaningful positions. Unknown prices are treated conservatively rather than assumed dust |
| **Wallet reconciliation** | Holdings and cash come from the exchange, not inferred locally |
| **Explicit live confirmation** | Real orders require `--confirm` |
| **Dry-run mode** | `--dry-run` exercises the full path without orders |
| **Position limits** | Max 5 crypto positions; 10% base size |
| **Authoritative asset typing** | Classification uses Roostoo's `AssetType` |
| **Start gate** | No trading before `start_utc` |
| **Long-only** | No short exposure |

### 19.1 Dust logic

```text
asset quantity > 0
        +
known market price
        +
position value >= ~$5
        ↓
counts as a held position
```

Tiny residual balances therefore do not consume position slots. If the price is unknown, the asset is *not* automatically classified as dust.

### 19.2 Order construction

Orders are constructed from the difference between target and current holdings. Each order passes the final safety check before submission. Quantities must respect exchange precision and minimum sizes. <!-- VERIFY: describe quantity-step rounding in bot.py / execution.py. -->

### 19.3 Execution mode

The production mode is `market`. Market orders execute immediately at available prices and may incur slippage, especially in thinner markets. `limit_timeout_s` exists in the configuration for limit-order mode but is not used by the production market mode.

---

## 20. State Management

### 20.1 What the bot tracks

| State | Description |
|---|---|
| Cash | From the wallet |
| Positions | From the wallet, reconciled with local state |
| Peak equity | Highest equity observed |
| Drawdown | Current decline from peak |
| Risk multiplier | From the drawdown ladder |
| Strategy state | Per-asset signal state |

### 20.2 Separation of concerns

Live state is kept separate from research output. Exchange state and local state can diverge after partial fills, rejections or restarts, so the wallet is treated as authoritative.

### 20.3 Restart behavior

On restart, the bot re-reads the wallet and reconciles. It does not assume the account is empty.

<!-- VERIFY: document where peak-equity state is persisted (file path) and what happens if that file is lost. -->

---

## 21. Daily Trading Tracker

### 21.1 Purpose

`tracker/daily_tracker.py` parses live trading logs and writes a dated Markdown report to `tracker/reports/`.

### 21.2 Report contents

| Section | Content |
|---|---|
| Fills | Filled BUY orders, filled SELL orders, total fills |
| Costs | Fees and turnover |
| Equity | Equity, peak equity |
| Risk | Current drawdown, drawdown multiplier |
| Signals | Signal observations |
| Orders | Dry-run orders |
| Diagnostics | Warnings and errors |
| Universe | Selected-universe information |

### 21.3 Usage

```bash
python tracker/daily_tracker.py --date YYYY-MM-DD
```

Example:

```bash
python tracker/daily_tracker.py --date 2026-10-03
```

### 21.4 Tests

`tests/test_daily_tracker.py` covers tracker parsing so that log-format changes do not silently break reporting.

---

## 22. Testing

### 22.1 Running

```bash
python -m pytest -q
```

**Current result: `11 passed`.**

### 22.2 Coverage

| Test file | Covers |
|---|---|
| `tests/test_engine.py` | Core backtest-engine behavior and live-trading logic |
| `tests/test_daily_tracker.py` | Daily tracker log parsing |
| `tests/helpers.py` | Shared fixtures |

The suite is a regression check against accidental changes to backtest behavior, execution logic, signal logic, live-bot behavior and tracker parsing.

### 22.3 Compile check

```bash
python -m py_compile \
    rq/live/bot.py \
    rq/research/grid.py \
    rq/roostoo/universe.py \
    rq/signals/families.py \
    tracker/daily_tracker.py
```

### 22.4 What is not covered

Tests do not replace a dry run. Real exchange behavior (fills, precision, rejections, latency) is only observable in dry-run and live operation.

### 22.5 When tests are required

| Change | Tests required |
|---|---|
| Signal logic | Yes |
| Position sizing | Yes |
| Universe selection | Yes |
| Execution | Yes |
| Accounting | Yes |
| Risk management | Yes |
| Documentation only | No |

---

## 23. Setup and Deployment

### 23.1 Requirements

| Requirement | Detail |
|---|---|
| Python | 3.x <!-- VERIFY: minimum version --> |
| Dependencies | `requirements.txt` |
| Credentials | Roostoo API credentials in `.env` |
| Network | Outbound access to the Roostoo API |
| Process manager | Any mechanism that keeps a long-running process alive (e.g. `tmux`, `screen`, `systemd`) |

> No specific cloud deployment is implemented or claimed by this repository. Any VM or cloud setup is the operator's responsibility.

### 23.2 Install

```bash
git clone https://github.com/AmanQEDS/roostoo-quant-trading.git
cd roostoo-quant-trading

python -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -r requirements.txt
```

### 23.3 Credentials

```bash
cp .env.example .env
# edit .env with your Roostoo credentials
```

> **Never commit API keys or secrets.**

### 23.4 Pre-deployment checklist

```bash
# 1. Tests
python -m pytest -q
# expect: 11 passed

# 2. Config check
python -c "import yaml; print(yaml.safe_load(open('config/live.yaml')))"
# expect: builder ema_donchian, fast=50, slow=200, n=24, timeframe=30m

# 3. Compile check
python -m py_compile rq/live/bot.py rq/roostoo/universe.py rq/signals/families.py

# 4. Dry run
python -m rq.cli live --dry-run

# 5. Live
python -m rq.cli live --confirm
```

### 23.5 Keeping the process alive

Example using `tmux`:

```bash
tmux new -s roostoo
source .venv/bin/activate
python -m rq.cli live --confirm
# detach: Ctrl+B then D
# reattach: tmux attach -t roostoo
```

Example using `nohup`:

```bash
nohup python -m rq.cli live --confirm > live.log 2>&1 &
```

<!-- VERIFY: confirm the bot's own log location so the tracker can find it. -->

### 23.6 Updating a running deployment

```bash
git pull
python -m pytest -q
python -m rq.cli live --dry-run
# then stop and restart the live process
```

Do not update a running deployment without a dry run.

---

## 24. Operations Runbook

### 24.1 Before start

- [ ] Tests pass (`11 passed`)
- [ ] `config/live.yaml` matches the intended frozen configuration
- [ ] `.env` credentials present and not committed
- [ ] Dry run reviewed
- [ ] `start_utc` is correct (UTC)
- [ ] Existing wallet holdings understood

### 24.2 During operation

| Layer | What to monitor |
|---|---|
| Market / data | Timestamp freshness, missing bars, stale prices, unexpected symbols |
| Strategy | Number of long candidates, ranking changes, signal consistency between bars |
| Portfolio | Equity, cash, number of positions, largest position, drawdown, risk multiplier |
| Execution | Submitted orders, fills, rejections, partial fills, API errors, wallet reconciliation |
| Risk | Current drawdown, peak equity, ladder state, exposure |

### 24.3 Daily routine

1. Check the process is running.
2. Check the latest bar timestamp is current.
3. Generate the daily report: `python tracker/daily_tracker.py --date YYYY-MM-DD`.
4. Review warnings, errors and rejected orders.
5. Confirm position count ≤ 5 and no non-crypto holdings remain.
6. Record equity, peak equity and drawdown.

### 24.4 Stopping

Stop the process (e.g. `Ctrl+C` or terminate the tmux session). Open positions remain on the exchange. The bot does not assume the account is empty on restart and will reconcile on the next start.

### 24.5 Incident response

| Situation | Action |
|---|---|
| API errors repeating | Stop the bot, check credentials and connectivity, run a dry run |
| Unexpected position | Compare wallet with bot output; verify the asset's `AssetType` |
| Repeated identical orders | Stop immediately; investigate sizing, precision and reconciliation |
| Stale bars | Check data feed and clock; do not trade on stale data |
| Credentials exposed | Revoke and regenerate keys immediately |
| Drawdown ladder active | Do not override; it is part of the production design |

---

## 25. Complete CLI Reference

All commands are run from the repository root.

### 25.1 Command summary

| Command | Purpose |
|---|---|
| `discover` | Discover the Roostoo universe |
| `download` | Download historical data |
| `check-data` | Audit data quality and gaps |
| `stage-a` | Stage-A research run |
| `report` | Generate research report |
| `walkforward` | Walk-forward evaluation |
| `alloc-sweep` | Allocation and sizing sweep |
| `freeze` | Freeze selected configuration |
| `validate` | Independent validation |
| `baselines` | Baseline comparisons |
| `live` | Live trading (dry-run or confirmed) |

Use `--help` on any command for its complete argument list:

```bash
python -m rq.cli --help
python -m rq.cli <command> --help
```

### 25.2 Data

```bash
python -m rq.cli discover
python -m rq.cli download
python -m rq.cli check-data
```

### 25.3 Research

```bash
python -m rq.cli stage-a
python -m rq.cli report
python -m rq.cli walkforward --help
python -m rq.cli alloc-sweep --help
python -m rq.cli freeze --help
python -m rq.cli baselines --help
```

### 25.4 Allocation sweep

```bash
python -m rq.cli alloc-sweep \
  --crypto "ma_cross(fast=50,kind=ema,slow=200)" \
  --freq 30m
```

### 25.5 Validation

```bash
python -m rq.cli validate --freq 30m
```

### 25.6 Research modules run directly

```bash
python -m rq.research.w14_dist
```

### 25.7 Live

```bash
python -m rq.cli live --dry-run     # simulate; no orders submitted
python -m rq.cli live --confirm     # live execution
```

> The older form `python -m rq.cli live` (no flag) is outdated. Use `--dry-run` or `--confirm`.

### 25.8 Tests and reporting

```bash
python -m pytest -q
python tracker/daily_tracker.py --date YYYY-MM-DD
```

### 25.9 Utility

```bash
python status.py
python -c "import yaml; print(yaml.safe_load(open('config/live.yaml')))"
python -m py_compile rq/live/bot.py rq/research/grid.py rq/roostoo/universe.py rq/signals/families.py tracker/daily_tracker.py
```

### 25.10 Command-name pitfalls

| Wrong | Right |
|---|---|
| `python -m rq.cli wf-fixed` | `python -m rq.cli walkforward` |
| `python -m rq.cli live` | `python -m rq.cli live --dry-run` or `--confirm` |

---

## 26. Research vs Production Separation

```text
RESEARCH                              PRODUCTION
├── strategy grids                    ├── config/live.yaml
├── walk-forward analysis             ├── rq/live/bot.py
├── benchmarks                        ├── rq/roostoo/client.py
├── cost sensitivity                  ├── rq/roostoo/universe.py
├── correlation sensitivity           ├── rq/signals/
├── regime analysis                   ├── execution
├── risk testing                      └── portfolio / risk state
├── sizing research
└── return-distribution analysis
```

### 26.1 Rules

1. Research files are not modified casually once the live configuration is frozen.
2. Live code is not changed merely to improve a historical backtest.
3. Sizing experiments live in `sizing_dev.py`, not in the live bot.
4. Production parameters come from `config/live.yaml`, not hidden defaults.

### 26.2 Production principles

| # | Principle |
|---|---|
| 1 | **Do not optimize on short-term live P&L.** Short-term results should not trigger parameter changes |
| 2 | **Keep research and production separate** |
| 3 | **Treat exchange state as authoritative** |
| 4 | **Preserve risk controls** — position limits, long-only and the drawdown ladder are part of the strategy |
| 5 | **Test before changing production** |

---

## 27. Change-Control Policy

### 27.1 Categories

| Category | Examples | Required process |
|---|---|---|
| Documentation | README edits | Commit directly |
| Tooling | Tracker format, logging | Tests + review |
| Execution | Order construction, reconciliation | Tests + dry run |
| Risk | Ladder thresholds, sizing | Tests + validation + dry run |
| Strategy | Signal logic, parameters | Full validation cycle + dry run |

### 27.2 Commit hygiene

- Commit strategy parameter changes separately.
- Commit risk-setting changes separately.
- Commit execution-logic changes separately.
- Commit accounting changes separately.
- Do not mix these in one commit.

### 27.3 Release record

| Field | Value |
|---|---|
| Branch | `main` |
| Strategy | EMA(50/200) + Donchian(24) |
| Latest recorded commit | `f9fb60a` |
| Commit message | Upgrade live trading strategy and execution |
| Tests at commit | 11 passed |

<!-- VERIFY: update the commit hash after any later commit. -->

### 27.4 Revalidation triggers

A new validation cycle is required if any of these change: EMA periods, Donchian window, timeframe, universe rules, position fraction, maximum positions, drawdown ladder, execution mode, or fee assumptions.

---

## 28. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `ModuleNotFoundError` | Dependencies missing or venv inactive | Activate venv; `pip install -r requirements.txt` |
| Authentication failure | Missing or wrong credentials | Check `.env` against `.env.example` |
| Bot idle after start | `start_utc` in the future | Confirm `start_utc` and UTC time |
| No candidates | No asset has EMA(50) > EMA(200) and a Donchian breakout | Normal in weak or range-bound markets |
| Fewer than 5 positions | Fewer candidates than slots, or dust ignored | Review candidate count |
| Order rejected | Quantity precision, minimum size or balance | Inspect rejection message; check exchange precision |
| Non-crypto order blocked | Safety guard triggered | Verify asset's `AssetType`; this is expected protection |
| Equity holdings persist | Liquidation path not completed | Review logs; confirm wallet refresh |
| Unknown-price asset | Ticker missing | Treated conservatively, not as dust |
| Tests fail after change | Regression | Fix before deploying |
| Tracker report empty | Log path or date mismatch | Check `--date` and log location |
| `wf-fixed` not found | Not a CLI command | Use `walkforward` |
| `live` does nothing/refuses | Missing flag | Use `--dry-run` or `--confirm` |

### 28.1 Diagnostic commands

```bash
python -m pytest -q
python -m rq.cli check-data
python -m rq.cli live --dry-run
python status.py
```

---

## 29. Historical Baseline Research

> This section documents **historical research on the EMA 50/200-only baseline and other candidates**. It is retained for context and comparison. **None of it describes the current production strategy.**

### 29.1 Baseline validation detail

EMA 50/200, `2026-01-01 → 2026-10-02`, starting capital $100,000.

| Metric | Value |
|---|---:|
| Ending portfolio value | $117,142.75 |
| Total return | +17.14% |
| Realized P&L | +$16,009.63 |
| Unrealized P&L | +$1,133.11 |
| Total fees | $4,998.70 |
| Completed trades | 340 |
| Open positions at end | 5 |
| Closed-trade win rate | 30.88% |
| Profit factor | 1.213 |
| Average trade net P&L | $47.09 |
| Median holding period | 56.25 hours |
| Sharpe / Sortino / Calmar | 0.81 / 1.29 / 1.09 |
| Realized return | +16.01% |
| Unrealized return | +1.13% |
| Daily max drawdown | -19.38% |
| Bar-level max drawdown | -21.09% |

Reconciliation:

```text
$100,000 + $16,009.63 + $1,133.11 ≈ $117,142.74
```

The small difference from the reported $117,142.75 is display rounding.

### 29.2 Other validated candidates

Same period, $100,000 start:

| Strategy | Return | Sharpe | Sortino | Calmar | Daily Max DD | Trades | Win rate | Profit factor |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `fng_contrarian(exit_at=50, low=25)` | -2.00% | -0.08 | -0.12 | -0.21 | -16.09% | 15 | 46.67% | 0.803 |
| `fng_momentum(n_days=7, thr=5)` | +8.08% | 0.77 | 1.34 | 0.89 | -12.31% | 90 | 43.33% | 1.392 |
| `ma_cross(fast=50, slow=200, kind=ema)` | +17.14% | 0.81 | 1.29 | 1.09 | -19.38% | 340 | 30.88% | 1.213 |

Additional detail:

| Strategy | Ending value | Realized P&L | Fees | Open positions | Median holding |
|---|---:|---:|---:|---:|---:|
| `fng_contrarian` | $97,995.29 | -$2,004.71 | $244.39 | 0 | 2,232 h |
| `fng_momentum` | $108,081.31 | +$8,081.31 | $1,416.42 | 0 | 108 h |
| `ma_cross` (EMA) | $117,142.75 | +$16,009.63 | $4,998.70 | 5 | 56.25 h |

The Fear & Greed momentum strategy showed smaller drawdowns but lower raw return than the EMA baseline. The contrarian variant was not positive in validation.

### 29.3 Candidate comparison summary

| Strategy | Role in the project |
|---|---|
| EMA 50/200 | Historical baseline |
| EMA 50/200 + Donchian(24) | Production |
| `fng_momentum(7, 5)` | Lower-return, lower-drawdown research alternative |
| `fng_contrarian` | Rejected |

### 29.4 Allocation sweep (baseline)

EMA 50/200, median over the sizing grid:

| Crypto weight | Return | Sharpe | Sortino | Calmar | Max DD | Composite |
|---:|---:|---:|---:|---:|---:|---:|
| 20% | 24.2% | 0.699 | 1.146 | 0.394 | -19.0% | 0.784 |
| 30% | 36.4% | 0.749 | 1.237 | 0.441 | -24.7% | 0.851 |
| 40% | 48.5% | 0.792 | 1.314 | 0.489 | -29.0% | 0.909 |
| 50% | 60.6% | 0.830 | 1.378 | 0.537 | -32.4% | 0.961 |

```text
More crypto exposure
        ↓
Higher return in this sample
        +
Higher drawdown / volatility
```

Representative sizing configuration (50% crypto weight, 5% position fraction, 5 max positions):

| Metric | Value |
|---|---:|
| Total return | +33.2% |
| Sharpe | 0.933 |
| Sortino | 1.589 |
| Calmar | 0.614 |
| Max drawdown | -16.3% |
| Volatility | 10.9% |
| Downside deviation | 6.4% |
| Trades | 1,354 |
| Fees | $8,546 |
| Final value | $133,156 |
| Composite | 1.100 |

Raising the position fraction to 10% lifted return to roughly 42.1% in the tested configuration but deepened maximum drawdown to roughly -22.9%.

Fear & Greed momentum allocation (`fng_momentum(n_days=7, thr=5)`), median over the sizing grid:

| Crypto weight | Return | Sharpe | Sortino | Calmar | Max DD | Composite |
|---:|---:|---:|---:|---:|---:|---:|
| 20% | 9.7% | 0.765 | 1.188 | 0.412 | -7.9% | 0.828 |
| 30% | 14.6% | 0.775 | 1.208 | 0.422 | -11.3% | 0.842 |
| 40% | 19.4% | 0.786 | 1.227 | 0.432 | -14.4% | 0.856 |
| 50% | 24.3% | 0.795 | 1.246 | 0.442 | -17.3% | 0.869 |

Its strongest tested configuration (50% weight, 5% position fraction, 5 max positions): +14.3% return, Sharpe 1.046, Sortino 1.670, Calmar 0.627, max drawdown -7.3%, volatility 4.4%, 355 trades, $1,771 fees, final value $114,312, composite 1.170.

Takeaway: strategy selection cannot rest on return alone, and sizing changes the risk profile independently of the signal.

> These sweep results were produced for the baseline strategies, not for the production Donchian strategy.

### 29.5 14-day return distribution (baseline)

Produced by `python -m rq.research.w14_dist` on the EMA baseline development sample.

| Statistic | Value |
|---|---:|
| Windows | 1,082 |
| Total return | +96.3% |
| Max drawdown | -24.3% |
| Average exposure | 20% |
| Mean 14-day return | +0.95% |
| Median 14-day return | -0.40% |

| Percentile | 14-day return |
|---:|---:|
| 5th | -4.84% |
| 10th | -3.50% |
| 25th | -1.93% |
| 50th | -0.40% |
| 75th | +1.98% |
| 90th | +5.76% |
| 95th | +11.29% |

Outcome frequencies:

| Outcome | Frequency |
|---|---:|
| 14-day return > 0% | 45% |
| 14-day return > +5% | 12% |
| 14-day return > +10% | 6% |
| 14-day return < -5% | 5% |
| 14-day return < -10% | 0% |

Interpretation:

- The median is slightly negative while the mean is positive, so the distribution is positively skewed.
- Long-run results come from a minority of strong windows, not from winning every two weeks.
- In this development sample the left tail was smaller than the right tail, but the system should not be expected to be positive every fortnight.

### 29.6 Early live dry-run observation (baseline era)

An early dry run produced `14 long / 0 short` and ranked candidates including WLD, AAVE, LTC, ICP, UNI, AVNT, SOL and SUI, alongside several instruments later excluded by the crypto-only `AssetType` filter. This observation motivated the authoritative crypto classification, the equity-liquidation path and the final order safety guard now in the production bot.

### 29.7 Dust fix history

A live-execution issue was identified with tiny residual balances being counted as positions. The bot now ignores positions below roughly $5 of marked value while treating unknown prices conservatively.

---

## 30. Limitations and Disclaimer

| Limitation | Detail |
|---|---|
| **Not a guarantee** | Historical performance does not guarantee future results; all figures are model results under tested assumptions |
| **Single-period evidence** | Headline comparisons rely on a 2026 sample |
| **Selection bias** | The Donchian window was selected on the same sample used to report results, even though neighboring windows performed similarly |
| **Material drawdown** | Tested drawdowns were roughly -15% to -19% (deeper at bar level); live drawdowns may be larger |
| **Uneven short-horizon returns** | Baseline research showed a negative median 14-day return |
| **Execution differences** | Live fills, slippage, spreads, latency and partial fills may differ from backtest assumptions |
| **Market orders** | Immediate execution at available prices; slippage risk in less liquid assets |
| **Regime dependence** | Trend-following can underperform in range-bound or choppy markets |
| **Exchange dependence** | Relies on Roostoo data and API availability |
| **Different evaluation setups** | The two 2026 comparisons use different setups; absolute numbers should not be compared across them |
| **Baseline-only studies** | Allocation sweeps and the 14-day distribution were run on baseline strategies, not on the Donchian production strategy |

This repository is a competition and research project. Nothing in it is financial advice.

---

## 31. Glossary

| Term | Definition |
|---|---|
| **AssetType** | Roostoo's authoritative classification of an instrument (e.g. crypto vs stock) |
| **Bar** | One 30-minute OHLCV observation |
| **Baseline** | The EMA(50/200)-only strategy used for comparison |
| **Calmar ratio** | Return relative to maximum drawdown |
| **Dry run** | Execution path that builds orders without submitting them |
| **Donchian high** | Highest high over a lookback window |
| **Drawdown** | Decline from peak portfolio value |
| **Drawdown ladder** | Rule set that reduces exposure as drawdown deepens |
| **Dust** | Residual balance too small to count as a position (~$5 threshold) |
| **EMA** | Exponential moving average |
| **Freeze / lock** | Recording the selected configuration so it cannot drift |
| **Long-only** | No short positions |
| **Mark-to-market** | Valuing open positions at current prices |
| **Profit factor** | Gross profit divided by gross loss |
| **Realized P&L** | Profit or loss on closed trades |
| **Sharpe ratio** | Return per unit of total volatility |
| **Sortino ratio** | Return per unit of downside volatility |
| **Start gate** | `start_utc` setting preventing trading before a set time |
| **Unrealized P&L** | Mark-to-market gain or loss on open positions |
| **Walk-forward** | Repeated out-of-sample evaluation over successive windows |

---

## 32. FAQ

**Is EMA 50/200 still the live strategy?**
No. The live strategy is EMA(50/200) + Donchian(24). EMA-only is the historical baseline.

**Why add Donchian?**
It adds a breakout confirmation. In the 2026 validation it improved return and risk-adjusted metrics, slightly reduced drawdown, and cut trade count.

**Why N = 24?**
It had the strongest overall return and risk-adjusted results in the tested sweep of 12, 24, 48 and 96.

**Does the bot short?**
No. `allow_short: false`.

**Does the bot trade stocks?**
No. Equity trading is disabled, and existing equity holdings are liquidated through a dedicated path.

**What command starts live trading?**
`python -m rq.cli live --confirm`. Use `--dry-run` first.

**Can I start the bot before the competition starts?**
Yes. It stays idle until `start_utc`.

**Does the bot assume an empty account?**
No. It reads the wallet and reconciles existing holdings.

**What happens during a drawdown?**
Exposure is scaled to 0.50× at 10% drawdown and 0.25× at 20%.

**How do I produce a daily report?**
`python tracker/daily_tracker.py --date YYYY-MM-DD`.

**Why is the win rate so low?**
Trend-following wins a minority of trades but with larger average winners; the baseline had a ~31% win rate with a profit factor above 1.

**Should I tune parameters after a bad week?**
No. See the production principles in [Section 26.2](#262-production-principles).

**Is this financial advice?**
No.

---

## 33. Current Production Snapshot

```text
==================================================
Strategy:             EMA(50/200) + Donchian(24)
Builder:              ema_donchian
Timeframe:            30 minutes
Universe:             Roostoo crypto (AssetType-classified)
Direction:            Long only
Shorting:             Disabled

Crypto allocation:    100%
Base position size:   10%
Maximum positions:    5
Execution:            Market
Risk overlay:         Drawdown ladder (10% → 0.50x, 20% → 0.25x)

EMA fast / slow:      50 / 200
Donchian window:      24
Start gate:           2026-10-03 00:00 UTC

Validation (2026):    +23.97% return | Sharpe 1.06 | Sortino 1.72
                      Max DD -18.79% | 304 trades
Baseline (EMA only):  +17.14% return | Sharpe 0.81 | Sortino 1.29
                      Max DD -19.38% | 340 trades

Live commands:        python -m rq.cli live --dry-run
                      python -m rq.cli live --confirm
Tests:                11 passed
Branch:               main
Commit:               f9fb60a — Upgrade live trading strategy and execution
==================================================
```

> Freeze the validated strategy and risk configuration, deploy the exact tested version, and avoid changing parameters based solely on short-term live performance.
