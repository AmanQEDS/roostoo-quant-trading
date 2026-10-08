# Roostoo Quant Trading System

## Quantitative Research, Strategy Development, Portfolio Construction, Backtesting, Validation and Live Execution

**Repository:** `AmanQEDS/roostoo-quant-trading`
**Primary timeframe:** 30-minute bars
**Primary live strategy:** EMA(50/200) + Donchian(24) long-only crypto strategy
**Execution venue:** Roostoo
**Current live configuration:** `config/live.yaml`

---

## 1. Project Overview

This repository contains the complete quantitative trading workflow developed for the Roostoo Quant Trading Competition.

The system is designed as a research-to-production pipeline rather than as a single trading script. It covers:

1. Universe discovery from the Roostoo environment.
2. Historical market-data acquisition and validation.
3. Data-quality and gap auditing.
4. Indicator and signal generation.
5. Strategy research and candidate generation.
6. Backtesting with transaction costs.
7. Walk-forward and out-of-sample evaluation.
8. Risk and sensitivity analysis.
9. Portfolio allocation and position sizing.
10. Strategy selection and freezing.
11. Independent validation/audit.
12. Live signal generation.
13. Live order construction and execution through the Roostoo API.
14. State management and drawdown-based risk controls.
15. Test coverage and reproducibility.

The important design principle is that the same conceptual strategy is carried from research into live execution. The research layer determines the strategy and portfolio rules; the live layer consumes the frozen configuration and translates signals into executable orders.

---

# 2. System Architecture

```text
                         â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                         â”‚        Roostoo API            â”‚
                         â”‚  Market Data / Universe /     â”‚
                         â”‚  Wallet / Orders / Ticker    â”‚
                         â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                        â”‚
                         â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                         â”‚      Data Acquisition         â”‚
                         â”‚ rq/roostoo/client.py          â”‚
                         â”‚ rq/roostoo/universe.py        â”‚
                         â”‚ rq/cli_download.py            â”‚
                         â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                        â”‚
                         â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                         â”‚       Data Validation         â”‚
                         â”‚ data_audit.py                  â”‚
                         â”‚ gap_audit.py                   â”‚
                         â”‚ check-data CLI                 â”‚
                         â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                        â”‚
                         â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                         â”‚      Signal / Indicators      â”‚
                         â”‚ indicators.py                  â”‚
                         â”‚ signals/core.py                â”‚
                         â”‚ signals/families.py            â”‚
                         â”‚ signals/elliott.py             â”‚
                         â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                        â”‚
                         â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                         â”‚        Research Layer         â”‚
                         â”‚ loader.py / grid.py           â”‚
                         â”‚ runner.py / selection.py      â”‚
                         â”‚ walk-forward / sensitivity    â”‚
                         â”‚ benchmark / regime / risk     â”‚
                         â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                        â”‚
                         â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                         â”‚       Backtest Engine          â”‚
                         â”‚ engine.py                      â”‚
                         â”‚ metrics.py                     â”‚
                         â”‚ risk.py                        â”‚
                         â”‚ audit.py                       â”‚
                         â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                        â”‚
                         â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                         â”‚     Portfolio Construction     â”‚
                         â”‚ crypto/equity weights          â”‚
                         â”‚ position fraction              â”‚
                         â”‚ max positions                  â”‚
                         â”‚ drawdown ladder                â”‚
                         â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                        â”‚
                         â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                         â”‚      Independent Validation    â”‚
                         â”‚ validate CLI / audit outputs   â”‚
                         â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                        â”‚
                         â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                         â”‚          Live Bot              â”‚
                         â”‚ rq/live/bot.py                 â”‚
                         â”‚ 30m signal cycle               â”‚
                         â”‚ wallet reconciliation           â”‚
                         â”‚ order construction             â”‚
                         â”‚ risk controls                  â”‚
                         â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                        â”‚
                         â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                         â”‚       Roostoo Orders           â”‚
                         â”‚ Market execution               â”‚
                         â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

---

# 3. Research Philosophy

The project follows a staged research process.

```text
Universe
   â†“
Data
   â†“
Data Quality
   â†“
Signal Research
   â†“
Candidate Strategies
   â†“
Backtest
   â†“
Walk-Forward / Out-of-Sample
   â†“
Cost / Correlation / Risk Sensitivity
   â†“
Allocation Sweep
   â†“
Freeze
   â†“
Independent Validation
   â†“
Dry-Run Live Simulation
   â†“
Deployment
```

This separation is important because a strong historical backtest alone is not sufficient evidence for deployment.

The system therefore evaluates:

- return,
- Sharpe ratio,
- Sortino ratio,
- Calmar ratio,
- maximum drawdown,
- volatility,
- downside deviation,
- trade count,
- fees,
- final portfolio value,
- rolling 14-day behavior,
- sensitivity to costs,
- sensitivity to correlations,
- allocation sensitivity,
- and live execution behavior.

---

# 4. Repository Structure

The current repository contains the following principal components:

```text
.
â”œâ”€â”€ .env.example
â”œâ”€â”€ .gitignore
â”œâ”€â”€ README.md
â”œâ”€â”€ requirements.txt
â”œâ”€â”€ status.py
â”‚
â”œâ”€â”€ config/
â”‚   â”œâ”€â”€ default.yaml
â”‚   â”œâ”€â”€ live.yaml
â”‚   â””â”€â”€ universe_overrides.yaml
â”‚
â”œâ”€â”€ rq/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ cli.py
â”‚   â”œâ”€â”€ cli_download.py
â”‚   â”œâ”€â”€ config.py
â”‚   â”œâ”€â”€ constants.py
â”‚   â”œâ”€â”€ data_audit.py
â”‚   â”œâ”€â”€ execution.py
â”‚   â”œâ”€â”€ gap_audit.py
â”‚   â”œâ”€â”€ indicators.py
â”‚   â”‚
â”‚   â”œâ”€â”€ backtest/
â”‚   â”‚   â”œâ”€â”€ __init__.py
â”‚   â”‚   â”œâ”€â”€ audit.py
â”‚   â”‚   â”œâ”€â”€ engine.py
â”‚   â”‚   â”œâ”€â”€ metrics.py
â”‚   â”‚   â””â”€â”€ risk.py
â”‚   â”‚
â”‚   â”œâ”€â”€ live/
â”‚   â”‚   â”œâ”€â”€ __init__.py
â”‚   â”‚   â””â”€â”€ bot.py
â”‚   â”‚
â”‚   â”œâ”€â”€ research/
â”‚   â”‚   â”œâ”€â”€ __init__.py
â”‚   â”‚   â”œâ”€â”€ benchmarks.py
â”‚   â”‚   â”œâ”€â”€ combine.py
â”‚   â”‚   â”œâ”€â”€ combo.py
â”‚   â”‚   â”œâ”€â”€ corr_sens.py
â”‚   â”‚   â”œâ”€â”€ cost_sens.py
â”‚   â”‚   â”œâ”€â”€ final_backtest.py
â”‚   â”‚   â”œâ”€â”€ grid.py
â”‚   â”‚   â”œâ”€â”€ loader.py
â”‚   â”‚   â”œâ”€â”€ lock.py
â”‚   â”‚   â”œâ”€â”€ regimes.py
â”‚   â”‚   â”œâ”€â”€ risk_stability.py
â”‚   â”‚   â”œâ”€â”€ risk_test.py
â”‚   â”‚   â”œâ”€â”€ runner.py
â”‚   â”‚   â”œâ”€â”€ selection.py
â”‚   â”‚   â”œâ”€â”€ sizing_dev.py
â”‚   â”‚   â”œâ”€â”€ w14_dist.py
â”‚   â”‚   â””â”€â”€ wf_fixed.py
â”‚   â”‚
â”‚   â”œâ”€â”€ roostoo/
â”‚   â”‚   â”œâ”€â”€ __init__.py
â”‚   â”‚   â”œâ”€â”€ client.py
â”‚   â”‚   â””â”€â”€ universe.py
â”‚   â”‚
â”‚   â””â”€â”€ signals/
â”‚       â”œâ”€â”€ __init__.py
â”‚       â”œâ”€â”€ core.py
â”‚       â”œâ”€â”€ elliott.py
â”‚       â””â”€â”€ families.py
â”‚
â””â”€â”€ tests/
    â”œâ”€â”€ helpers.py
    â””â”€â”€ test_engine.py
```

---

# 5. Configuration Layer

## `config/default.yaml`

The default research configuration.

It contains the common parameters used by the research/backtest environment, including portfolio, transaction-cost and strategy-related settings.

The purpose is to provide a reproducible baseline rather than embedding research parameters throughout Python files.

---

## `config/live.yaml`

This is the live execution configuration.

Current configuration:

```yaml
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
```

Interpretation:

| Parameter | Meaning |
|---|---|
| `timeframe` | Signal frequency is 30 minutes |
| `crypto_weight` | 100% of portfolio allocation is assigned to crypto |
| `pos_frac` | Base position fraction is 10% |
| `max_pos.crypto` | Maximum of 5 simultaneous crypto positions |
| `max_pos.equity` | Equity trading is disabled |
| `allow_short` | Short positions are disabled |
| `exec_mode` | Market execution |
| `strategies.crypto` | EMA(50/200) + Donchian(24) |
| `mode` | Live execution mode |
| `dd_ladder` | Position scaling reduces as portfolio drawdown increases |
| `start_utc` | Live strategy start point |

The live configuration is deliberately explicit so that deployment does not depend on hidden Python defaults.

---

## `config/universe_overrides.yaml`

Provides controlled overrides for the trading universe.

This is useful when the live exchange universe differs from the research universe or when specific instruments require explicit handling.

---

# 6. Core Package

## `rq/config.py`

Loads and interprets YAML configuration.

It creates the bridge between configuration files and Python components.

---

## `rq/constants.py`

Contains project-wide constants such as research windows and other fixed configuration values.

Centralizing these values prevents inconsistent dates and parameters across scripts.

---

## `rq/cli.py`

The main command-line interface.

Available commands include:

```text
discover
download
check-data
stage-a
report
walkforward
alloc-sweep
freeze
validate
baselines
live
```

The CLI is the operational entry point for both research and live execution.

Important example:

```bash
python -m rq.cli walkforward --help
```

The actual available command is `walkforward`; there is no `wf-fixed` CLI command.

The fixed walk-forward research implementation exists as a Python research module rather than as a separate CLI command.

---

## `rq/cli_download.py`

Provides the download-side command functionality used to acquire historical Roostoo data.

---

## `rq/execution.py`

Contains execution-related abstractions shared by the trading workflow.

It separates execution behavior from the research logic.

---

## `rq/indicators.py`

Provides technical indicators used by strategies.

The indicator layer exists separately from the portfolio and execution layers so that indicators can be reused by multiple strategy families.

---

## `rq/data_audit.py`

Performs data-quality checks.

The objective is to identify problems in the historical dataset before those problems contaminate strategy results.

---

## `rq/gap_audit.py`

Focuses specifically on missing bars and discontinuities.

This is important for a 30-minute strategy because missing bars can change indicator values and create artificial signals.

---

# 7. Roostoo Integration

## `rq/roostoo/client.py`

The exchange/API client.

It is responsible for communication with Roostoo for functions such as:

- market data,
- ticker information,
- account balance,
- wallet state,
- order placement,
- exchange interaction,
- API request handling.

The live bot uses this layer instead of embedding raw API calls throughout the trading logic.

---

## `rq/roostoo/universe.py`

Discovers and represents the actual Roostoo trading universe.

This distinction matters because the system should not assume that a research ticker list is automatically identical to the live exchange universe.

---

# 8. Signal Architecture

## `rq/signals/core.py`

Contains core signal-building functionality and shared signal interfaces.

---

## `rq/signals/families.py`

Contains the broader collection of signal/strategy families used during research.

This allows the project to compare different signal structures under the same research and backtest infrastructure.

---

## `rq/signals/elliott.py`

Contains Elliott-wave-related signal logic.

It is part of the broader research library and is not the final live strategy.

---

# 9. Backtesting Engine

The backtesting layer is responsible for converting historical signals into simulated portfolio behavior.

## `rq/backtest/engine.py`

The core portfolio/backtest engine.

It handles the progression of the portfolio through time, including:

- signals,
- positions,
- cash,
- portfolio value,
- fills,
- transaction effects,
- position changes,
- mark-to-market behavior.

The purpose is to ensure that strategy returns are generated from simulated trading rather than from simply multiplying signal columns by future returns.

---

## `rq/backtest/metrics.py`

Calculates performance statistics.

Important metrics include:

- Total return
- Sharpe ratio
- Sortino ratio
- Calmar ratio
- Maximum drawdown
- Volatility
- Downside deviation
- Trade count
- Fees
- Final portfolio value

These metrics are used consistently across research and validation.

---

## `rq/backtest/risk.py`

Implements portfolio risk controls.

The live configuration uses a drawdown ladder:

```text
Drawdown < 10%       â†’ 100% risk multiplier
Drawdown â‰¥ 10%       â†’ 50% risk multiplier
Drawdown â‰¥ 20%       â†’ 25% risk multiplier
```

This does not predict returns. It controls exposure after losses increase.

---

## `rq/backtest/audit.py`

Provides independent accounting/audit functionality.

The audit layer checks the resulting portfolio and trade records rather than relying only on the headline backtest metrics.

This was important during the final validation stage because the strategy had open positions and therefore realized and unrealized P&L needed to be separated.

---

# 10. Research Infrastructure

## `rq/research/loader.py`

Loads the research data panel and supporting extended data.

This provides the common data interface used by research runners.

---

## `rq/research/grid.py`

Defines the strategy search space.

It allows multiple strategy specifications to be generated and evaluated consistently.

---

## `rq/research/runner.py`

The research execution layer.

It connects:

```text
Data
  â†“
Strategy Specification
  â†“
Portfolio Configuration
  â†“
Backtest
  â†“
Metrics
```

This keeps the individual research scripts relatively small and reproducible.

---

## `rq/research/selection.py`

Implements candidate selection.

The purpose is to move from a large research set toward a smaller shortlist based on documented performance and stability criteria.

---

## `rq/research/lock.py`

Provides the mechanism for freezing/locking selected research configurations.

The purpose of a lock is to prevent the final deployed configuration from silently changing because of later research experimentation.

---

## `rq/research/final_backtest.py`

Runs the final selected strategy configuration through a standardized backtest.

It is intended to provide a clean final research result after exploratory work.

---

## `rq/research/benchmarks.py`

Provides benchmark/reference comparisons.

This helps distinguish whether a strategy is generating useful behavior relative to simpler reference approaches.

---

## `rq/research/combine.py`

Combines research outputs where multiple strategy or portfolio components need to be evaluated together.

---

## `rq/research/combo.py`

Contains combination logic for strategy research and portfolio combinations.

---

## `rq/research/corr_sens.py`

Performs correlation sensitivity analysis.

The objective is to test whether portfolio results depend excessively on a particular assumed relationship between assets or strategy components.

---

## `rq/research/cost_sens.py`

Performs transaction-cost sensitivity analysis.

This is important because a strategy with many trades can appear profitable before fees but become weak after realistic trading costs.

---

## `rq/research/regimes.py`

Contains market-regime analysis functionality.

It is used to investigate how strategy behavior changes under different market environments.

---

## `rq/research/risk_stability.py`

Examines stability of risk characteristics rather than focusing only on total return.

---

## `rq/research/risk_test.py`

Provides targeted risk tests for candidate strategies/configurations.

---

## `rq/research/sizing_dev.py`

Research/development code for position-sizing behavior.

It is separate from the production live bot so that sizing experiments do not automatically change deployment behavior.

---

## `rq/research/wf_fixed.py`

Contains the fixed walk-forward research implementation.

Important distinction:

```text
wf_fixed.py
    â‰
CLI command "wf-fixed"
```

The CLI currently exposes:

```bash
python -m rq.cli walkforward ...
```

rather than:

```bash
python -m rq.cli wf-fixed ...
```

This distinction prevented an incorrect command from being used during the final research phase.

---

## `rq/research/w14_dist.py`

Calculates the distribution of forward 14-day returns for the selected strategy and risk configuration.

The final run produced:

```text
windows: 1082
total return: 96.3%
max drawdown: -24.3%
average exposure: 20%

14-day return:
mean     0.95%
median  -0.40%

5%       -4.84%
10%      -3.50%
25%      -1.93%
50%      -0.40%
75%       1.98%
90%       5.76%
95%      11.29%
```

Frequency of outcomes:

```text
14-day return > 0%      : 45%
14-day return > +5%     : 12%
14-day return > +10%    : 6%
14-day return < -5%     : 5%
14-day return < -10%    : 0%
```

### Interpretation

The distribution is not uniformly positive.

The median 14-day return is negative at `-0.40%`, while the mean is positive at `+0.95%`.

This indicates positive outcomes are skewing the average upward.

The left tail is materially smaller than the right tail over this development sample:

- only 5% of 14-day windows lost more than 5%;
- no sampled 14-day window lost more than 10%;
- 12% gained more than 5%;
- 6% gained more than 10%.

The result therefore supports the existence of favorable return windows but also shows that positive performance is not constant over every 14-day period.

---

# 11. Strategy Development

The research process evaluated multiple signal families.

Two important crypto candidates reached the final comparison stage:

### A. EMA 50/200 Moving-Average Cross

```text
ma_cross(
    fast=50,
    slow=200,
    kind=ema
)
```

Logic:

- calculate a 50-period exponential moving average;
- calculate a 200-period exponential moving average;
- bullish regime when the fast EMA is above the slow EMA;
- bearish/flat condition when the relationship reverses;
- final live implementation is long-only.

The strategy is deliberately simple and robust.

---

### B. 7-Day Fear & Greed Momentum

```text
fng_momentum(
    n_days=7,
    thr=5
)
```

This strategy uses changes in the Fear & Greed signal over a seven-day horizon.

It demonstrated better risk-adjusted behavior in the allocation sweep than the EMA strategy in some configurations, but the EMA strategy remained the selected deployment configuration based on the broader research/freeze process and final live configuration.

---

# 12. Allocation Sweep Results

The allocation sweep tested how crypto portfolio weight interacted with position sizing.

## EMA 50/200

The median-over-sizing-grid results were:

| Crypto Weight | Return | Sharpe | Sortino | Calmar | Max DD | Composite |
|---:|---:|---:|---:|---:|---:|---:|
| 20% | 24.2% | 0.699 | 1.146 | 0.394 | -19.0% | 0.784 |
| 30% | 36.4% | 0.749 | 1.237 | 0.441 | -24.7% | 0.851 |
| 40% | 48.5% | 0.792 | 1.314 | 0.489 | -29.0% | 0.909 |
| 50% | 60.6% | 0.830 | 1.378 | 0.537 | -32.4% | 0.961 |

Increasing crypto weight increased both return and drawdown.

The sweep therefore demonstrated a fundamental portfolio trade-off:

```text
More crypto exposure
        â†“
Higher expected portfolio return in this sample
        +
Higher drawdown / volatility
```

---

## EMA Selected Sizing Configuration

A representative strong configuration was:

```text
crypto weight = 50%
position fraction = 5%
max crypto positions = 5
```

Result:

```text
total return     +33.2%
Sharpe            0.933
Sortino           1.589
Calmar            0.614
max drawdown     -16.3%
volatility         10.9%
downside dev       6.4%
trades             1,354
fees               $8,546
final value        $133,156
composite          1.100
```

The sweep also showed that increasing position fraction to 10% could raise total return to approximately `42.1%` in the tested configuration, but maximum drawdown increased to approximately `-22.9%`.

Therefore position sizing materially changes the risk profile even when the underlying signal remains identical.

---

# 13. Fear & Greed Momentum Allocation Results

For:

```text
fng_momentum(n_days=7,thr=5)
```

the median-over-sizing-grid results were:

| Crypto Weight | Return | Sharpe | Sortino | Calmar | Max DD | Composite |
|---:|---:|---:|---:|---:|---:|---:|
| 20% | 9.7% | 0.765 | 1.188 | 0.412 | -7.9% | 0.828 |
| 30% | 14.6% | 0.775 | 1.208 | 0.422 | -11.3% | 0.842 |
| 40% | 19.4% | 0.786 | 1.227 | 0.432 | -14.4% | 0.856 |
| 50% | 24.3% | 0.795 | 1.246 | 0.442 | -17.3% | 0.869 |

The strategy generated lower raw returns than the EMA strategy in the tested allocation framework, but its drawdowns were materially smaller.

Its strongest tested configuration included:

```text
crypto weight = 50%
position fraction = 5%
max crypto positions = 5
```

with:

```text
return        +14.3%
Sharpe         1.046
Sortino        1.670
Calmar         0.627
max drawdown  -7.3%
volatility      4.4%
trades          355
fees           $1,771
final value   $114,312
composite       1.170
```

This illustrates why strategy selection cannot be based on return alone.

---

# 14. Independent Validation Results

The final validation command was:

```bash
python -m rq.cli validate --freq 30m
```

The validation period was:

```text
2026-01-01 â†’ 2026-10-02
```

Starting capital:

```text
$100,000
```

---

## Strategy 1 â€” Fear & Greed Contrarian

```text
fng_contrarian(exit_at=50,low=25)
```

Results:

```text
Ending value       $97,995.29
Total return         -2.00%
Realized P&L       -$2,004.71
Unrealized P&L         $0.00
Fees                  $244.39
Completed trades        15
Open positions           0
Daily max DD          -16.09%
Bar-level max DD      -18.40%
Win rate               46.67%
Profit factor           0.803
Average trade P&L   -$133.65
Median holding       2232 hours
Sharpe                 -0.08
Sortino                -0.12
Calmar                 -0.21
```

This candidate did not produce positive validation performance.

---

## Strategy 2 â€” Fear & Greed Momentum

```text
fng_momentum(n_days=7,thr=5)
```

Results:

```text
Ending value       $108,081.31
Total return          +8.08%
Realized P&L        +$8,081.31
Unrealized P&L          $0.00
Fees                $1,416.42
Completed trades        90
Open positions           0
Daily max DD          -12.31%
Bar-level max DD      -14.22%
Win rate               43.33%
Profit factor           1.392
Average trade P&L       $89.79
Median holding         108 hours
Sharpe                   0.77
Sortino                  1.34
Calmar                   0.89
```

This candidate produced positive validation performance with moderate drawdown.

---

## Strategy 3 â€” EMA 50/200

```text
ma_cross(fast=50,kind=ema,slow=200)
```

Results:

```text
Ending portfolio value    $117,142.75
Total return                  +17.14%
Realized P&L                 +$16,009.63
Unrealized P&L                +$1,133.11
Total fees                   $4,998.70
Completed trades                 340
Open positions                     5
Daily max drawdown              -19.38%
Bar-level max drawdown          -21.09%
Realized return                  +16.01%
Unrealized return                 +1.13%
Closed-trade win rate             30.88%
Profit factor                      1.213
Average trade net P&L             $47.09
Median holding period             56.25 hours
Sharpe                              0.81
Sortino                             1.29
Calmar                              1.09
```

The final portfolio value is composed of:

```text
$100,000 starting capital
+
$16,009.63 realized P&L
+
$1,133.11 unrealized P&L
=
$117,142.74 approximately
```

The small rounding difference versus the reported final value is expected from the displayed precision.

---

# 15. How to Interpret the Final EMA Result

The final EMA result should not be described simply as "the bot makes 17%".

The more accurate interpretation is:

> On the specified 30-minute validation period and the implemented portfolio/accounting assumptions, the EMA 50/200 strategy generated a +17.14% portfolio return, with a -19.38% daily maximum drawdown and -21.09% bar-level audited drawdown, while paying approximately $5,000 in fees.

The strategy therefore has meaningful return potential but also meaningful downside risk.

The 30.88% closed-trade win rate is not inherently contradictory to positive returns.

A trend-following strategy can have a low win rate when:

```text
many trades lose small amounts
        +
a smaller number of trades capture large trends
        =
positive aggregate P&L
```

The profit factor of `1.213` confirms that gross profitable trade contribution exceeded gross losing trade contribution, after the implemented trade accounting.

---

# 16. 14-Day Distribution Analysis

The separate distribution analysis produced:

```text
Development windows: 1082

Total return       +96.3%
Max drawdown       -24.3%
Average exposure    20%
```

Forward 14-day return distribution:

| Percentile | Return |
|---:|---:|
| 5th | -4.84% |
| 10th | -3.50% |
| 25th | -1.93% |
| 50th | -0.40% |
| 75th | +1.98% |
| 90th | +5.76% |
| 95th | +11.29% |

The key observation is that the median forward window is slightly negative while the mean is positive.

That means the distribution is asymmetric and the strategy's long-run result is not generated by winning every short horizon.

---

# 17. Live Portfolio Construction

The current live configuration is:

```text
Timeframe:          30 minutes
Asset class:        Crypto only
Crypto allocation:  100%
Equity allocation:    0%
Position fraction:   10%
Maximum positions:    5
Shorting:             Disabled
Execution:            Market
Strategy:             EMA 50/200 + Donchian 24
```

The distinction between `crypto_weight` and `pos_frac` is important.

- `crypto_weight` controls how much of the portfolio belongs to the crypto sleeve.
- `pos_frac` controls the base fraction used when sizing an individual position.

The maximum number of simultaneous crypto positions limits concentration.

---

# 18. Drawdown Ladder

The live configuration includes:

```yaml
dd_ladder:
  - [0.10, 0.5]
  - [0.20, 0.25]
```

Operationally:

```text
Normal state:
    exposure multiplier = 1.00

Drawdown >= 10%:
    exposure multiplier = 0.50

Drawdown >= 20%:
    exposure multiplier = 0.25
```

The objective is to reduce risk after adverse portfolio-level performance.

The drawdown ladder is a risk overlay; it does not create alpha.

---

# 19. Live Bot

## `rq/live/bot.py`

This is the production execution component.

Its responsibilities include:

1. Read the live configuration.
2. Connect to Roostoo.
3. Retrieve current ticker data.
4. Retrieve wallet/account state.
5. Build the current 30-minute signal bar.
6. Determine long candidates.
7. Rank candidates by strategy score.
8. Apply portfolio/risk constraints.
9. Build orders.
10. Submit orders in live mode.
11. Reconcile wallet state.
12. Maintain portfolio state.
13. Apply drawdown risk controls.

---

# 20. Live Dry-Run Verification

The live bot was executed in dry-run mode:

```bash
python -m rq.cli live --dry-run
```

Observed behavior included:

```text
14 long / 0 short
```

and ranked candidates such as:

```text
WLD
AAVE
GLWB
AMDB
NVDAB
MSTRB
NBISB
LTC
ICP
UNI
BIO
AVNT
SOL
SUI
```

The bot generated simulated buy instructions such as:

```text
BUY WLD
BUY AAVE
BUY GLWB
BUY AMDB
BUY NVDAB
```

The signal ranking changed slightly between consecutive 30-minute bars, while the portfolio/risk state remained stable.

This demonstrated that the live loop was:

- reading the market,
- calculating signals,
- ranking assets,
- constructing orders,
- and waiting for the next 30-minute bar.

---

# 21. Wallet Reconciliation and Dust Handling

A live-execution issue was identified around tiny residual asset balances.

The bot was modified to ignore positions whose marked value is below approximately `$5`, while treating unknown prices conservatively.

Conceptually:

```text
asset quantity > 0
        +
known market price
        +
position value >= $5
        â†“
consider as held position
```

Tiny residual balances are therefore prevented from being interpreted as meaningful portfolio positions.

Unknown prices are handled conservatively rather than automatically assuming the asset is dust.

This prevents small exchange leftovers from interfering with maximum-position calculations.

---

# 22. Live State

The live bot maintains state separately from the strategy research output.

The wallet is treated as the source of truth for available cash.

The bot also maintains portfolio state such as:

- cash,
- positions,
- peak equity,
- drawdown,
- risk multiplier,
- strategy state.

This separation is important because exchange state and local state can diverge if an order partially fills, is rejected, or if the process restarts.

---

# 23. Tests

The project was tested with:

```bash
python -m pytest -q
```

Latest result:

```text
10 passed in 0.95s
```

The tests cover core engine behavior and provide a regression check before deployment.

The repository also contains:

```text
tests/helpers.py
tests/test_engine.py
```

The test suite is intentionally kept separate from research scripts.

---

# 24. Git / Reproducibility

The final strategy and live-execution changes are validated locally before the next commit.

Final recorded commit:

```text
ecce954
```

Commit message:

```text
Finalize 30m EMA strategy and live execution
```

The repository should be pushed only after the current validation suite passes:

`AmanQEDS/roostoo-quant-trading`

The repository tree at the documented final commit includes the live bot, research modules, configuration, Roostoo integration, strategy modules and tests.

---

# 25. Deployment Configuration

Before switching from dry-run to actual execution, the production environment must contain the required Roostoo credentials.

The repository provides:

```text
.env.example
```

Secrets should not be committed to Git.

The expected deployment architecture is:

```text
Cloud/VM
   â”‚
   â”œâ”€â”€ Python environment
   â”œâ”€â”€ Repository
   â”œâ”€â”€ Environment variables
   â”‚      â””â”€â”€ Roostoo API credentials
   â”‚
   â””â”€â”€ Live process
          â”‚
          â””â”€â”€ python -m rq.cli live
                  â”‚
                  â”œâ”€â”€ 30m signal cycle
                  â”œâ”€â”€ portfolio/risk state
                  â””â”€â”€ Roostoo orders
```

---

# 26. Production Startup Procedure

A production deployment should follow this order.

## Step 1 â€” Pull the final repository

```bash
git clone https://github.com/AmanQEDS/roostoo-quant-trading.git
cd roostoo-quant-trading
```

Or, for an existing deployment:

```bash
git pull
```

---

## Step 2 â€” Create the environment

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Linux:

```bash
source .venv/bin/activate
```

---

## Step 3 â€” Install dependencies

```bash
pip install -r requirements.txt
```

---

## Step 4 â€” Configure credentials

Create the local environment configuration from `.env.example`.

Never commit the actual API key.

---

## Step 5 â€” Verify the repository

```bash
python -m pytest -q
```

Expected:

```text
10 passed
```

---

## Step 6 â€” Verify live configuration

```bash
python -c "import yaml; print(yaml.safe_load(open('config/live.yaml')))"
```

Expected strategy:

```text
ma_cross
fast=50
slow=200
kind=ema
timeframe=30m
```

---

## Step 7 â€” Perform a dry run

```bash
python -m rq.cli live --dry-run
```

Confirm:

- signal bars are advancing;
- symbols are valid;
- wallet is readable;
- equity is reasonable;
- positions are ranked correctly;
- order quantities are sensible;
- no unexpected positions are detected;
- no repeated pathological orders are produced.

---

## Step 8 â€” Start production execution

Once credentials and exchange permissions are verified:

```bash
python -m rq.cli live
```

The bot then runs continuously and evaluates the strategy on the 30-minute schedule.

---

# 27. Operational Monitoring

During live execution, monitor:

### Market/data layer

- timestamp freshness;
- missing bars;
- stale prices;
- unexpected symbols.

### Strategy layer

- number of long signals;
- number of short signals;
- ranking changes;
- signal consistency between bars.

### Portfolio layer

- equity;
- cash;
- number of positions;
- largest position;
- portfolio drawdown;
- risk multiplier.

### Execution layer

- submitted orders;
- fills;
- rejected orders;
- partial fills;
- API errors;
- wallet reconciliation.

### Risk layer

- current drawdown;
- peak equity;
- drawdown ladder state;
- exposure.

---

# 28. Important Research Findings

The research process established several practical conclusions.

## 28.1 Return and risk move together

Higher crypto allocation increased return but also materially increased drawdown.

Therefore allocation cannot be chosen using return alone.

---

## 28.2 Position sizing matters

The EMA sweep demonstrated that increasing the position fraction can significantly increase total return while simultaneously increasing drawdown.

The signal and sizing layers therefore need to be evaluated separately.

---

## 28.3 Transaction costs matter

The EMA strategy generated thousands of trades in some portfolio configurations and paid substantial fees.

For example:

```text
1,354 trades
â‰ˆ $8,546 fees
```

in the representative allocation sweep.

Therefore gross strategy performance without costs would be misleading.

---

## 28.4 A low win rate does not automatically invalidate trend following

The final EMA validation showed:

```text
Win rate = 30.88%
Profit factor = 1.213
Total return = +17.14%
```

The strategy relies on asymmetric payoff from successful trends rather than a high percentage of winning trades.

---

## 28.5 Short-horizon performance is uneven

The 14-day distribution had:

```text
median = -0.40%
mean   = +0.95%
```

Therefore the system should not be expected to produce positive returns every two weeks.

---

## 28.6 Risk controls are essential

The final EMA validation experienced approximately:

```text
-19.38% daily maximum drawdown
-21.09% bar-level audited maximum drawdown
```

This is substantial.

The drawdown ladder exists specifically to reduce portfolio exposure after losses.

---

# 29. Current Production Strategy

The current live strategy is:

```text
==================================================
Strategy:             EMA 50/200 + Donchian(24)
Frequency:      30 minutes
Universe:       Roostoo crypto universe
Direction:      Long only
Shorting:       Disabled
Crypto weight:  100%
Position size:  10%
Max positions:  5
Execution:      Market
Risk overlay:   Drawdown ladder
==================================================
```

Signal concept:

```text
EMA(50) > EMA(200)
        â†“
        Long candidate

EMA(50) <= EMA(200)
        â†“
        No long signal
```

The final live portfolio then ranks active candidates and selects positions subject to the position and risk constraints.

---

# 30. Research vs Production Separation

The repository intentionally contains both experimental and production-oriented code.

```text
RESEARCH
â”œâ”€â”€ grid search
â”œâ”€â”€ walk-forward
â”œâ”€â”€ benchmarks
â”œâ”€â”€ cost sensitivity
â”œâ”€â”€ correlation sensitivity
â”œâ”€â”€ regime analysis
â”œâ”€â”€ risk tests
â”œâ”€â”€ sizing development
â””â”€â”€ distribution analysis

PRODUCTION
â”œâ”€â”€ config/live.yaml
â”œâ”€â”€ rq/live/bot.py
â”œâ”€â”€ rq/roostoo/client.py
â”œâ”€â”€ rq/roostoo/universe.py
â”œâ”€â”€ execution
â””â”€â”€ state/risk handling
```

Research files should not be modified casually after the live configuration has been frozen.

Similarly, live execution code should not be changed simply to improve a historical backtest.

---

# 31. End-to-End Workflow for the Project

A non-technical description of the system is:

### Stage 1 â€” Find the tradable assets

The system asks Roostoo what assets are actually available.

### Stage 2 â€” Collect historical data

Historical market data is downloaded and organized into a research panel.

### Stage 3 â€” Check the data

Missing bars, gaps and inconsistent data are investigated.

### Stage 4 â€” Generate signals

The system calculates technical indicators and strategy signals.

### Stage 5 â€” Simulate trading

The backtest engine pretends to trade according to the strategy.

### Stage 6 â€” Include realistic costs

Fees and slippage are included so that the results are not artificially optimistic.

### Stage 7 â€” Test outside the development sample

Walk-forward and validation procedures test whether the strategy continues to behave reasonably outside the research selection process.

### Stage 8 â€” Test portfolio sizing

The system checks how much capital should be assigned to crypto and how large individual positions should be.

### Stage 9 â€” Test risk

Drawdown, volatility, downside risk and rolling return distributions are evaluated.

### Stage 10 â€” Freeze the configuration

The chosen strategy and parameters are explicitly recorded.

### Stage 11 â€” Validate independently

The validation layer reconstructs portfolio/trade statistics and reports realized and unrealized P&L separately.

### Stage 12 â€” Dry run

The live bot connects to the exchange but only prints the orders it would send.

### Stage 13 â€” Production execution

The same signal logic is connected to actual Roostoo order execution.

---

# 32. Key Performance Snapshot

## Final validation

| Metric | EMA 50/200 |
|---|---:|
| Validation return | **+17.14%** |
| Ending value | **$117,142.75** |
| Realized P&L | **+$16,009.63** |
| Unrealized P&L | **+$1,133.11** |
| Fees | **$4,998.70** |
| Completed trades | **340** |
| Open positions | **5** |
| Win rate | **30.88%** |
| Profit factor | **1.213** |
| Sharpe | **0.81** |
| Sortino | **1.29** |
| Calmar | **1.09** |
| Daily max DD | **-19.38%** |
| Bar-level max DD | **-21.09%** |

---

# 33. Important Interpretation

The project has progressed beyond the stage of simply finding a profitable historical signal.

The current system contains:

```text
Data
+
Data Quality
+
Signal Generation
+
Backtesting
+
Transaction Costs
+
Portfolio Construction
+
Risk Controls
+
Independent Validation
+
Live API Integration
+
Dry-Run Execution
+
Automated Tests
```

The final EMA strategy has demonstrated positive performance over the documented validation period, but that performance comes with material drawdown and should be treated as a model result under the tested assumptions rather than as a guarantee of future performance.

The most important production principle is therefore:

> Preserve the tested strategy, portfolio rules, accounting logic and risk controls during deployment. Do not optimize the live system based on short-term live P&L.

---

# 34. Quick Command Reference

## Research

```bash
python -m rq.cli discover
python -m rq.cli download
python -m rq.cli check-data
python -m rq.cli stage-a
python -m rq.cli report
python -m rq.cli walkforward --help
```

## Allocation

```bash
python -m rq.cli alloc-sweep --help
```

Example:

```bash
python -m rq.cli alloc-sweep \
  --crypto "ma_cross(fast=50,kind=ema,slow=200)" \
  --freq 30m
```

## Validation

```bash
python -m rq.cli validate --freq 30m
```

## Distribution analysis

```bash
python -m rq.research.w14_dist
```

## Testing

```bash
python -m pytest -q
```

## Live dry run

```bash
python -m rq.cli live --dry-run
```

## Live execution

```bash
python -m rq.cli live
```

---

# 35. Repository Status

The documented production branch is `main`.

The final recorded strategy/live-execution commit is:

```text
ecce954
```

The repository should be treated as a versioned quantitative trading system and pushed only after validation.

The project should be treated as a versioned quantitative trading system: changes to strategy parameters, risk settings, execution logic or accounting should be tested and committed separately rather than mixed into an uncontrolled live deployment.

---

# 36. Closing Architecture

```text
                         ROOSTOO
                            â”‚
                            â–¼
                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                    â”‚ Data + Ticker â”‚
                    â””â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”˜
                            â”‚
                            â–¼
                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                    â”‚ Data Quality  â”‚
                    â””â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”˜
                            â”‚
                            â–¼
                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                    â”‚  Indicators   â”‚
                    â””â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”˜
                            â”‚
                            â–¼
                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                    â”‚ EMA 50 / 200  â”‚
                    â””â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”˜
                            â”‚
                            â–¼
                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                    â”‚ Signal Rankingâ”‚
                    â””â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”˜
                            â”‚
                            â–¼
                 â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                 â”‚ Portfolio Constraintsâ”‚
                 â”‚ max positions / size â”‚
                 â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                            â”‚
                            â–¼
                 â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                 â”‚ Drawdown Risk Ladder â”‚
                 â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                            â”‚
                            â–¼
                 â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                 â”‚ Order Construction   â”‚
                 â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                            â”‚
                            â–¼
                       ROOSTOO API
                            â”‚
                            â–¼
                       LIVE ORDERS
```

This architecture keeps the research process, portfolio construction, risk controls, accounting and exchange execution as separate but connected layers. That separation is the core design choice that makes the project reproducible, testable and deployable.
