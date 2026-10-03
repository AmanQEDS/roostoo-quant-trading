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
