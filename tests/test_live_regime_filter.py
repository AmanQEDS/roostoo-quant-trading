import numpy as np
import pandas as pd

from rq.live.regime_filter import f2_regime


def make_close(returns):
    prices = 100.0 * np.exp(np.cumsum(returns))
    return pd.DataFrame({"BTC": prices})


def test_f2_blocks_when_reference_is_missing():
    result = f2_regime(pd.DataFrame({"ETH": np.arange(2000) + 100.0}))
    assert result["allowed"] is False
    assert result["reason"] == "missing_reference"


def test_f2_blocks_when_history_is_too_short():
    close = make_close(np.full(500, 0.001))
    result = f2_regime(close)
    assert result["allowed"] is False
    assert result["reason"] == "unknown_regime"


def test_f2_allows_a_declining_volatility_regime():
    n = 1600
    x = np.arange(n)
    returns = 0.01 * np.exp(-x / 350.0) * np.sin(x * 0.17)
    result = f2_regime(make_close(returns))
    assert result["reason"] == "normal_volatility"
    assert result["allowed"] is True
    assert result["high_vol"] is False


def test_f2_blocks_a_recent_high_volatility_regime():
    n = 1600
    x = np.arange(n)
    returns = 0.0005 * np.sin(x * 0.17)
    returns[-120:] = 0.025 * np.sin(x[-120:] * 0.17)
    result = f2_regime(make_close(returns))
    assert result["reason"] == "high_volatility"
    assert result["allowed"] is False
    assert result["high_vol"] is True


def test_f2_uses_only_prior_bar_classification():
    n = 1600
    x = np.arange(n)
    returns = 0.0005 * np.sin(x * 0.17)
    returns[-120:] = 0.025 * np.sin(x[-120:] * 0.17)
    close = make_close(returns)
    result = f2_regime(close)

    log_returns = np.log(close["BTC"] / close["BTC"].shift(1))
    rv = log_returns.rolling(14 * 48).std()
    median = rv.expanding(min_periods=14 * 48).median()
    expected = (rv > median).where(rv.notna() & median.notna()).shift(1).iloc[-1]

    assert result["high_vol"] == bool(expected)
