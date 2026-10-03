# Roostoo Quant Research and Trading

**Team 187 (IITR) - Roostoo Quant Trading Hackathon**
Repository: <https://github.com/AmanQEDS/roostoo-quant-trading>
Roostoo API docs: <https://github.com/roostoo/Roostoo-API-Documents>

A rule-based crypto research, backtesting and live-execution framework for the Roostoo mock exchange. The final deployed system is a single, simple, long-only trend-following strategy (EMA 50/200 cross on 30-minute bars) chosen through a development / validation protocol, then verified end to end with real fills before the live window.

> **Honest summary.** No candidate passed every pre-set gate. The deployed strategy was the best of a weak family, was profitable on 2023-2025 development data and on the 2026 validation data, but it is a regime-dependent trend follower with a ~31% win rate and large drawdowns. Nothing here is a claim of proven alpha. Over a ~13-day live window the typical outcome is roughly flat; profit comes from a minority of strong-trend windows.

---

## Table of contents

1. [Final strategy specification](#1-final-strategy-specification)
2. [Architecture](#2-architecture)
3. [Data](#3-data)
4. [Research protocol (dev / validation split)](#4-research-protocol)
5. [Results](#5-results)
6. [What was tested and rejected](#6-what-was-tested-and-rejected)
7. [Costs and execution model](#7-costs-and-execution-model)
8. [Risk management](#8-risk-management)
9. [Live bot and operational verification](#9-live-bot-and-operational-verification)
10. [Tokenized-stock finding](#10-tokenized-stock-finding)
11. [Open-position and accounting audit](#11-open-position-and-accounting-audit)
12. [Setup and how to run](#12-setup-and-how-to-run)
13. [Deployment (AWS)](#13-deployment-aws)
14. [Repository map](#14-repository-map)
15. [Limitations and disclosures](#15-limitations-and-disclosures)

---

## 1. Final strategy specification

| Item | Value |
|---|---|
| Strategy | `ma_cross(fast=50, slow=200, kind=ema)` |
| Timeframe | 30-minute bars (built from 5-minute klines) |
| Direction | Long only (`allow_short: false`) |
| Universe | Roostoo-tradable pairs `X/USD` with Binance `XUSDT` history (38 symbols in the research panel) |
| Entry | EMA(50) crosses above EMA(200); exit when it crosses back below |
| Entry ranking | When more signals than free slots, entries are ranked by signal score (highest first) |
| Position sizing | `pos_frac = 0.15` of **remaining** cash per entry (sequential) |
| Max positions | 5 |
| Max theoretical exposure | `1 - (1 - 0.15)^5 = 55.6%` |
| Order type | Market orders, taker fee 0.10% |
| Drawdown ladder | **Off** (`dd_ladder: []`) - failed validation |
| Correlation cap | **Not used** - never validated, not implemented live |
| fng_momentum sleeve | **Not used** - not runnable live |
| Stop-loss / halt / vol-scaling | **Not used** - rejected on development data |
| Start gate | `start_utc: "2026-10-04 12:00"` (live window start, UTC) |
| Kill switch | `mode: liquidate` in `config/live.yaml`, re-read every cycle |

Sizing (`pos_frac`) was chosen on **development data only**, as a risk-appetite decision under a rule set before looking at the table: *the largest sizing whose dev max drawdown stays under about -50% and whose worst 14-day window stays under about -25%.* 0.15 was the largest that passed. It is a scale-up of the same signal, not a new strategy.

Live config (`config/live.yaml`):

```yaml
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
start_utc: "2026-10-04 12:00"
```

---

## 2. Architecture

```text
Roostoo exchangeInfo / ticker ---------+--> universe snapshot + live execution
                                       |
Binance Vision 5m crypto history ------+--> data panel (10m / 30m, close-time indexed)
Yahoo underlying history (optional) ---+    + lagged Fear & Greed / VIX / DVOL
                                             |
                                             v
Indicators -> signal families / Elliott -> target positions (Cond -> to_target)
                                             |
                                             v
Research: train 2023-2025 -> report / walk-forward -> FREEZE shortlist
          -> validate on 2026 (locked, logged) -> metrics + validation ledger
                                             |
Backtest engine: cash pools -> sequential sizing -> risk controls -> fees / slippage
                                             |
Live bot: Binance closed 5m bars -> same signal builders -> Roostoo ticker / balance
          -> order planning -> Roostoo client (HMAC signed) -> API journal
```

Key design points:

- **One signal codebase.** The live bot calls the same builders (`rq.signals`) as the backtest, so live signals and backtest signals cannot diverge.
- **No look-ahead.** Signals use information up to the close of bar *i*; orders fill at bar *i+1* (crypto at next open) plus slippage. External series (Fear & Greed, VIX, DVOL) are lagged by availability time.
- **Roostoo has no history.** `/v3/ticker` is the only market-data endpoint. All research data comes from Binance; Roostoo is used only for the tradable universe, live prices, balances and orders.
- **Sequential allocation.** A new position gets `pos_frac x (cash available right now)`, so sizes shrink geometrically as the pool fills. The live bot overwrites its cash figure from the real wallet USD balance every cycle (the wallet is the source of truth).
- **Auditability.** Every API request and response is appended to `logs/api_journal.jsonl`. Every bot decision is in `logs/bot.log`. Config changes go through commits.

### Live cycle

1. Wake ~15 s after each 30-minute bar boundary.
2. Re-read `config/live.yaml` (kill switch, start gate).
3. Update the Binance feed, compute signals on the newest completed bar, drop stale coins.
4. Read Roostoo ticker and wallet; mark equity = USD + holdings at last price.
5. Exits first (signal off, or `mode: liquidate`). A held coin with **no** signal data is held, never force-sold.
6. Entries ranked by score, up to the position cap, sized from real wallet cash.

---

## 3. Data

| Item | Detail |
|---|---|
| Source | Binance 5-minute klines (Binance Vision for history, REST for live) |
| Research panel | 30-minute bars, 2023-01-01 to 2026-10-02 UTC, 65,761 bars |
| Symbols in panel | 38 (all classified `crypto`; includes PAXG-style and tokenized-stock tickers, see [section 10](#10-tokenized-stock-finding)) |
| Development set | 2023-01-01 to 2025-12-31 |
| Validation set | 2026-01-01 onward (locked) |
| Known data issues | A September 2026 gap from a downloader bug was found and fixed. One harmless 16-bar exchange halt on 2023-03-24 remains. |
| Live feed note | TON stopped trading on Binance on 2026-06-30, so it returns an empty frame and is skipped without crashing. |

Panel symbols: AAVE, ADA, APT, ARB, ASTER, AVAX, BNB, BTC, CRCLB, DOGE, DOT, ENA, ETH, FET, FIL, HBAR, ICP, LINK, LTC, MSTRB, NEAR, ONDO, PENGU, POL, PUMP, SNDKB, SOL, SPCXB, SUI, TAO, TRUMP, TRX, UNI, WLD, XLM, XPL, XRP, ZEC.

---

## 4. Research protocol

1. **Universe discovery** against the real Roostoo `exchangeInfo`/ticker (never assumed).
2. **Strategy grid:** 88 specs across 28 builders (momentum, trend, mean reversion, breakouts, volatility gates, sentiment/Fear-and-Greed, multi-indicator combinations, regime switching, and a mechanical, falsifiable Elliott-wave rule set).
3. **Stage A:** backtest the whole grid on development data (2023-2025) with gates on drawdown, trades per day and minimum trades.
4. **Candidate selection:** *no candidate passed every gate mechanically.* The shortlist therefore involved quantitative judgement.
5. **Shortlist freeze** (`results/shortlist.json`, frozen 2026-10-03 10:26:34, sha1 `88e5b1449619c49323d57b36bafe771650e784cf`):
   - `fng_contrarian(exit_at=50, low=25)`
   - `fng_momentum(n_days=7, thr=5)`
   - `ma_cross(fast=50, kind=ema, slow=200)`
6. **Validation lock:** `rq.research.lock` refuses to evaluate anything not on the frozen list and records every evaluation to `results/validation_ledger.jsonl`.
7. **Robustness studies on development data only** (costs, regimes, half-years, walk-forward, combination, risk overlays, correlation, sizing).
8. **Final specification frozen**, then operational testing with real fills.

Selection-bias disclosure: in Stage A, the `ma_cross` family had a **median development return of -27%** and only **42% of its variants were positive**. 50/200 was the best tail of that family, so its development result is partly selection. The 2026 validation is the more honest number.

---

## 5. Results

### 5.1 Baselines (development 2023-2025, 100% crypto pool)

| Baseline | Return | Sharpe | Sortino | Max DD |
|---|---:|---:|---:|---:|
| Buy and hold, equal weight (all) | +54.3% | 0.55 | 0.80 | -45.5% |
| Buy and hold BTC | +128.8% | 1.13 | 1.74 | -24.5% |
| Simple MA cross 20/50 | +1.2% | 0.09 | 0.14 | -19.0% |
| Simple RSI 14 (30/55) | -11.1% | -0.80 | -0.97 | -14.6% |

BTC buy-and-hold beat the deployed strategy's *risk-adjusted* profile on the development period (no fees applied to buy-and-hold). The deployed strategy is not claimed to beat it.

### 5.2 Locked validation, 2026-01-01 to 2026-10-02 (pos_frac 0.10, max 5, 30m, fee 0.10%, slip 2 bp)

| Strategy | Return | Sharpe | Notes |
|---|---:|---:|---|
| `fng_contrarian(exit_at=50, low=25)` | -2.0% | -0.08 | rejected |
| `fng_momentum(n_days=7, thr=5)` | +8.1% | 0.77 | Sortino 1.34, DD -12.3%; not runnable live |
| **`ma_cross(50, ema, 200)`** | **+17.1%** | **0.81** | Sortino 1.29, Calmar 1.09, daily DD -19.4%, bar-level DD -21.1% |
| BTC buy and hold (2026) | -3.2% | | max DD -40.3% |

`ma_cross` beta to BTC is about 0.36. Validation was run at `pos_frac` 0.10; the live setting of 0.15 is a development-based scale-up that was **not** re-run on 2026.

### 5.3 Development performance of the deployed strategy (2023-2025, fee 0.10%, slip 2 bp)

| pos_frac | Return | Sortino | Calmar | Max DD | Median 14d | Worst 14d | Positive 14d windows |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.10 | +115.8% | 1.70 | 0.76 | -38.3% | -0.5% | -15.0% | 46% |
| **0.15 (deployed)** | **+150.0%** | **1.65** | **0.75** | **-47.3%** | **-0.7%** | **-18.7%** | **46%** |
| 0.20 | +173.0% | 1.61 | 0.74 | -53.5% | -0.8% | -21.3% | 46% |
| 0.25 | +188.5% | 1.58 | 0.73 | -57.9% | -1.0% | -23.0% | 46% |
| 0.30 | +198.6% | 1.56 | 0.72 | -61.2% | -1.1% | -24.2% | 47% |

Sizing behaves almost like pure leverage: Sortino and Calmar barely move while return and drawdown scale together. The typical 14-day window is flat to slightly negative; the return comes from a minority of large trend windows.

### 5.4 Half-year stability (fixed spec, development)

| Half | ma_cross 50/200 | fng_momentum |
|---|---:|---:|
| 2023H1 | +28.3% | +6.2% |
| 2023H2 | +21.3% | +15.0% |
| 2024H1 | +4.3% | +0.4% |
| 2024H2 | +67.7% | -2.5% |
| 2025H1 | -27.6% (DD -33%) | -0.3% |
| 2025H2 | +8.5% | +27.9% |
| Positive halves | 5 of 6 | 4 of 6 |

### 5.5 Walk-forward (pick best on train, test next year)

| Strategy | Test year | Picked | Test return | Grid median |
|---|---|---|---:|---:|
| ma_cross | 2024 | 50/200 | +75.7% | +26.8% |
| ma_cross | 2025 | 50/200 | **-21.3%** | -27.5% |
| fng_momentum | 2024 | 7/5 | -2.1% | +3.0% |
| fng_momentum | 2025 | 7/10 | -0.4% | +13.5% |

### 5.6 Regime behaviour (ma_cross, development)

Regimes: BTC 30-day trailing return > +10% bull, < -10% bear, else sideways; volatility versus an expanding median. Labels are shifted one bar so they are known before the bar's return.

| Regime | Return | Sortino | Max DD | Trades | Win rate |
|---|---:|---:|---:|---:|---:|
| Bull | +134.7% | 3.74 | -21.4% | 327 | 34% |
| Bear | +6.8% | 1.17 | -17.7% | 208 | 25% |
| **Sideways** | **-37.5%** | -1.37 | **-44.7%** | 797 | 26% |
| High vol | +59.3% | 1.61 | -27.2% | 645 | 29% |
| Low vol | -4.0% | 0.04 | -28.6% | 690 | 28% |

`ma_cross` is a classic trend follower: it earns in trends and bleeds through whipsaws in sideways markets. No regime filter was added because any filter would be a new strategy needing its own validation.

---

## 6. What was tested and rejected

### 6.1 Risk overlays (development, ma_cross 50/200, pos_frac 0.10)

| Variant | Return | Sortino | Calmar | Max DD | Worst 14d | Verdict |
|---|---:|---:|---:|---:|---:|---|
| None | 115.8% | 1.70 | 0.76 | -38.3% | -15.0% | baseline |
| Stop-loss 5% | 95.4% | 1.54 | 0.68 | -37.0% | -14.2% | rejected |
| DD ladder 10%->x0.5, 20%->x0.25 | 96.3% | 2.05 | 1.04 | -24.3% | -9.9% | **passed dev, failed validation** |
| DD halt 25% (3-day pause) | 106.8% | 1.62 | 0.70 | -38.9% | -15.0% | rejected |
| Vol scaling | 70.8% | 1.42 | 0.58 | -33.4% | -11.1% | rejected |
| Ladder + halt 30% | 96.3% | 2.05 | 1.04 | -24.3% | -9.9% | identical to ladder |

**Ladder stability (dev):** all neighbouring thresholds beat "none" on Calmar and max DD, so the ladder was not a knife-edge on development data. A variant that drops size to zero (`20/.0`) killed 2024 (+0.9%).

**Ladder on 2026 validation (single go/no-go on the frozen spec, no other settings tried):**

| 2026 | Bare | With ladder |
|---|---:|---:|
| Return | **+17.14%** | +1.93% |
| Realized / unrealized | +16.01% / +1.13% | +0.78% / +1.15% |
| Sharpe / Sortino / Calmar | 0.81 / 1.29 / 1.09 | 0.13 / 0.20 / 0.04 |
| Bar-level max DD | -21.1% | -17.5% |
| Fees | $4,999 | $3,437 |

The ladder cut drawdown by only ~3.5 points while giving up ~15 points of return, and it keeps size small until equity recovers within 10% of its peak - a poor trade in a short, return-ranked window. **It was dropped for that reason.** This decision used 2026 information and is disclosed as such; no other ladder settings were tested on 2026.

### 6.2 Strategy combination (development, daily-rebalanced mix of two equity curves)

Daily-return correlation 0.48 (downside: 0.35 when ma<0, 0.54 when fng<0).

| ma_cross weight | Return | Sharpe | Sortino | Calmar | Max DD | Worst half-year |
|---:|---:|---:|---:|---:|---:|---:|
| 1.00 | 115.8% | 1.00 | 1.70 | 0.76 | -38.3% | -29.6% |
| 0.75 | 101.6% | 1.08 | 1.82 | 0.85 | -31.2% | -23.1% |
| 0.50 | 86.0% | 1.15 | 1.92 | 0.98 | -23.4% | -16.0% |
| 0.25 | 69.4% | 1.18 | 1.92 | 1.07 | -18.0% | -8.4% |
| 0.00 | 52.3% | 1.04 | 1.65 | 0.65 | -23.2% | -2.5% |

Diversification reduces risk, but the screen ranks by **return first**, `fng_momentum` is not runnable live (it needs a Fear-and-Greed fetch in the bot), and adding untested code a day before launch was judged the larger risk. Not adopted.

### 6.3 Correlation cap (development only)

| Cap | Return | Sortino | Calmar | Max DD | Trades |
|---|---:|---:|---:|---:|---:|
| Off | 115.8% | 1.70 | 0.76 | -38.3% | 1354 |
| 0.80 | 133.6% | 1.85 | 0.93 | -35.2% | 1350 |
| 0.70 | 154.6% | 2.05 | 1.08 | -33.7% | 1292 |
| 0.60 | 170.6% | 2.20 | 1.24 | -31.7% | 1201 |

Monotonic improvement looks attractive but is exactly the pattern that invites over-fitting. It was **not frozen before validation, not implemented in the live bot, and cannot be validated without contaminating the 2026 lock**. Not adopted.

---

## 7. Costs and execution model

- **Fee:** 0.10% taker, confirmed on real test fills (fee is exactly 0.1% of notional). Maker 0.05% exists but limit orders are not implemented; the bot uses **market orders only**.
- **Slippage:** 2 bp assumed in backtests.
- **Round trip:** about 0.2% plus slippage. The strategy makes ~1.2 trades/day in backtest, a steady drag in choppy markets.

Cost sensitivity (development, ma_cross 50/200, pos_frac 0.10; return by fee x slippage):

| Fee \ slip | 0 bp | 2 bp | 5 bp | 10 bp |
|---|---:|---:|---:|---:|
| 0.05% | +148.5% | +138.7% | +124.7% | +103.1% |
| **0.10%** | +124.7% | **+115.8%** | +103.2% | +83.7% |
| 0.15% | +103.2% | +95.2% | +83.7% | +66.1% |

Positive in all 12 cells, so costs are not the weakness; the weakness is regime dependence.

---

## 8. Risk management

**Automated (live bot):**

- Hard cap of 5 concurrent positions and sequential position sizing (max ~55.6% exposure).
- Kill switch: `mode: liquidate` is re-read each cycle and sells every holding without buying.
- Held coins are never sold merely because a data feed failed.
- `place_order` is a single attempt (no blind retry), so a timeout cannot double-buy; the next cycle reads the real wallet.

**Not automated (accepted risk):**

- The live bot has **no** drawdown ladder, halt or stop-loss. A bad stretch is stopped only by the operator.
- **Operator rule:** if portfolio equity falls 35% from the starting value, switch `mode` to `liquidate` by committing the change. This is a disaster rule, not a tuned parameter.

Expectations for a ~13-day window (judgement, not a measured forecast): typical outcome about flat; roughly 54% of development 14-day windows lost money; worst development 14-day window at 0.15 sizing was -18.7%.

---

## 9. Live bot and operational verification

Tested with real fills on the General Portfolio key (test wallet $50,000) before switching to the competition key.

| Test | Result |
|---|---|
| Authentication and balance (`SpotWallet` response key) | Pass (client reads `SpotWallet`, falls back to `Wallet`) |
| Real fills | 22 fills in total across the test session |
| Fee on fills | Exactly 0.10% |
| Sequential sizing | Pass (e.g. notionals of roughly $5.0k, $4.5k, $4.0k, $3.6k, $3.3k at 0.10 sizing) |
| Entry ranking by score | Pass (`entry order (score desc)` logged each cycle) |
| Kill switch (`mode: liquidate` across a bar boundary) | **Pass** - at 15:00:35 the bot sold all five holdings and placed no buys |
| Resume (`mode: run`) | **Pass** - five ranked buys on the startup cycle |
| Crash/restart recovery | **Pass** - restart placed no buy or sell for coins already held; position cap respected |
| Duplicate processes | On Windows a venv launcher shows as parent + child process; verified via parent PID |
| Unit tests | 10 of 10 pass (`tests/test_engine.py`) |

Bugs found and fixed during the audit (no strategy changes):

1. Balance key: client expected `Wallet`; the API returns `SpotWallet`.
2. Stale-signal handling: use the newest bar, drop stale coins.
3. Live entries were not ranked by score (backtest ranks); fixed.
4. A held coin missing from the signal frame was force-sold; now held.
5. Permanent removal of a coin from the feed on a single error; now retried each bar.
6. Order retry on timeout could double-buy; `place_order` now makes one attempt.
7. Sizing used a ledger cash figure instead of the wallet; now synced from the wallet each cycle.
8. `logs/` directory created at startup so a fresh clone does not crash.
9. A repeated `SELL BNB` in dry-run was a dry-run artifact (nothing changes the wallet), not an order-state bug.

Monitoring: `python status.py` reads only `logs/bot.log` and `state/ledger.json` (no API calls, so nothing extra appears in the API journal). It reports last heartbeat (flags STALE after 40 minutes), last signal, equity line, fills and errors.

---

## 10. Tokenized-stock finding

The Roostoo universe contains tokenized equities (for example NVDAB, MSTRB, MUB, CRCLB, SNDKB, SPCXB, NBISB, AMDB) alongside crypto and PAXG.

- Their market history only starts around **June 2026**, so there is **no usable multi-year history** and no meaningful crypto-versus-equity split test. The planned equity pool is therefore unusable for research (`equity cols = 0` in the research panel).
- They **trade on weekends**, unlike the underlying stocks.
- Our asset-class heuristic classifies them as `crypto`, and the live bot treats every tradable pair the same way. Several tokenized stocks have appeared in live signals and test fills (NVDAB, MSTRB, NBISB, AMDB).
- Consequence: part of the live universe has far less historical evidence than the crypto assets the strategy was developed on. This is disclosed rather than hidden.

---

## 11. Open-position and accounting audit

A concern was that the 2026 result might be mostly unrealized P&L on open positions. After the data fix, the audit shows it is not.

| 2026 ma_cross (bare, pos_frac 0.10) | Value |
|---|---:|
| Starting capital | $100,000 |
| Ending portfolio value | $117,142.75 |
| Realized P&L | +$16,009.63 (93.4%) |
| Unrealized P&L | +$1,133.11 (6.6%) |
| Fees | $4,998.70 |
| Completed trades | 340 |
| Open positions at end | 5 |
| Win rate | 30.88% |
| Profit factor | 1.213 |
| Average trade net P&L | $47.09 |
| Median holding period | 56.25 hours |

Max drawdown is -19.4% on the daily-sampled metric and -21.1% on the 30-minute audit curve; the difference is sampling frequency, not a strategy change. The audit checks pass: no duplicate trade IDs, chronological timestamps, and trade, equity and open-position ledgers reconcile. Audit files are written to `results/` (`trades_*`, `equity_*`, `open_positions_*`).

---

## 12. Setup and how to run

Python 3.10 or newer. Windows PowerShell shown; use the equivalent on Linux.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` holds credentials and is git-ignored. **Never commit it or paste keys anywhere.**

```text
ROOSTOO_API_KEY=your_api_key_here
ROOSTOO_API_SECRET=your_api_secret_here
# "test" = General Portfolio credentials, "competition" = Competition credentials
ROOSTOO_ENV=test
```

### Research workflow

```powershell
python -m rq.cli discover                    # snapshot the real Roostoo universe
python -m rq.cli download --no-equity        # Binance history
python -m rq.cli check-data
python -m rq.cli stage-a --freq 30m --modes L
python -m rq.cli report --stage A --freq 30m
python -m rq.cli walkforward --builder ma_cross --freq 30m
python -m rq.cli baselines --freq 30m --stage A
python -m rq.cli freeze "<exact name>" "<exact name>"     # one-time lock
python -m rq.cli validate --freq 30m                      # 2026, frozen names only
python -m pytest tests -q
```

### Robustness and final studies (development data unless noted)

```powershell
python -m rq.research.cost_sens
python -m rq.research.regimes
python -m rq.research.wf_fixed
python -m rq.research.combo
python -m rq.research.risk_test
python -m rq.research.risk_stability
python -m rq.research.corr_sens
python -m rq.research.sizing_dev
python -m rq.research.final_backtest        # 2026: bare vs ladder, reported not tuned
```

### Live bot

```powershell
python -m rq.cli live --dry-run     # logs intended orders, sends none
python -m rq.cli live --confirm     # real orders (requires explicit flag)
python status.py                    # read-only monitor
```

Kill switch (commit and apply):

```powershell
(Get-Content config\live.yaml) -replace '^mode:.*','mode: liquidate' | Set-Content config\live.yaml -Encoding ascii
```

Write `config/live.yaml` as ASCII: PowerShell 5 `-Encoding utf8` adds a BOM that breaks YAML parsing.

---

## 13. Deployment (AWS)

- **Region:** Singapore (`ap-southeast-1`), Tokyo or Hong Kong. Binance returns HTTP 451 from US IPs.
- **Instance:** t3.small or t3.micro, Ubuntu 22.04/24.04, SSH only.

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git tmux
timedatectl                                   # expect UTC, clock synchronized
git clone https://github.com/AmanQEDS/roostoo-quant-trading.git
cd roostoo-quant-trading
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
mkdir -p logs state
nano .env && chmod 600 .env                   # competition key, ROOSTOO_ENV=competition
ls state/                                     # must be empty (no ledger.json)
python -m rq.cli live --dry-run               # expect: before start_utc ... idle
tmux new -s bot
python -m rq.cli live --confirm
```

Detach with `Ctrl+B` then `D`; reattach with `tmux attach -t bot`. Do not call the Roostoo API manually with the competition key: judges inspect the journal for manual calls.

---

## 14. Repository map

| Path | Responsibility |
|---|---|
| `rq/roostoo/` | Roostoo REST client (HMAC signing, retries, JSONL journal) and universe discovery |
| `rq/data/` | Downloads, alignment, panel construction |
| `rq/signals/`, `rq/indicators.py` | Strategy families, Elliott rule set, causal indicators, `Cond` / `to_target` plumbing |
| `rq/backtest/` | Engine, risk overlays (`risk.py`), metrics, accounting audit (`audit.py`) |
| `rq/research/` | Grid, runner, selection, lock, and the robustness studies listed above |
| `rq/live/bot.py`, `rq/execution.py` | Live loop and order sizing/rounding |
| `rq/cli.py` | Command-line entry point |
| `config/` | `default.yaml` (research), `live.yaml` (deployed), `universe_overrides.yaml` |
| `tests/` | Deterministic portfolio-accounting unit tests |
| `status.py` | Read-only live monitor |
| `results/` | Experiment log, shortlist, validation ledger, sensitivity tables (git-ignored) |

---

## 15. Limitations and disclosures

- **No claim of proven alpha.** The deployed signal is a trend follower that loses in sideways markets (-37.5% in the dev sideways regime) and lost -27.6% in 2025H1.
- **Selection bias.** 50/200 was the best tail of a family whose median dev variant lost money.
- **Validation used once, then partly informed a decision.** The drawdown ladder was dropped after its 2026 result. Sizing (0.15) was chosen on development data and was not re-run on 2026.
- **Different capital in tests.** Backtests used $100,000; the test wallet was $50,000; the competition wallet should be confirmed from the first `equity` log line. Sizing adapts because cash is read from the wallet each cycle.
- **Thin evidence for tokenized stocks** (about three months of history) inside a universe the strategy was not developed on.
- **Backtest is not a fill guarantee.** Real slippage, market impact and API behaviour can differ; live fills matched the 0.10% fee model.
- **No automated drawdown protection live.** Disaster handling is a manual operator rule.
- **Data dependence.** Live signals use Binance klines; a Binance outage degrades signals (held positions are held, not sold).
- **Short window.** Over about 13 days the median development outcome is roughly flat to slightly negative with about 46% positive windows. Treat results as a draw from a wide distribution, not a forecast.