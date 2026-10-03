import numpy as np, pandas as pd, pytest
from rq.backtest.engine import run_backtest, PortfolioConfig
from rq.backtest.audit import export_backtest_audit
from rq.backtest.metrics import perf_report
from rq.backtest.risk import RiskConfig
from helpers import mini_panel, tgt

def cfg(**kw):
    base = dict(capital=100_000, crypto_weight=1.0, pos_frac=1.0, fee=0.0, slip_bps={"crypto": 0, "equity": 0}, max_pos={"crypto": 10, "equity": 10})
    base.update(kw); return PortfolioConfig(**base)

def test_buy_and_hold_tracks_price():
    p = mini_panel({"A": [100, 101, 103, 102, 110, 120]})
    r = run_backtest(p, tgt(p, {"A": [1, 1, 1, 1, 1, 1]}), cfg())
    assert r.curve.equity_total.iloc[-1] == pytest.approx(100_000 * 120 / 100, rel=1e-9)   # filled at close[0]=100

def test_fees_conserve_cash():
    p = mini_panel({"A": [100, 110, 120, 90, 95, 100]})
    r = run_backtest(p, tgt(p, {"A": [1, 1, 0, 0, 0, 0]}), cfg(fee=0.001))
    assert r.open_positions == []
    assert r.curve.equity_total.iloc[-1] - 100_000 == pytest.approx(r.trades.pnl_net.sum(), rel=1e-9)
    assert r.fees == pytest.approx(r.trades.fees.sum(), rel=1e-9) and r.fees > 0

def test_sequential_allocation_uses_remaining_cash():
    p = mini_panel({"A": [100] * 5, "B": [100] * 5, "C": [100] * 5})
    r = run_backtest(p, tgt(p, {"A": [1, 1, 1, 0, 0], "B": [1, 1, 1, 0, 0], "C": [1, 1, 1, 0, 0]}), cfg(pos_frac=0.10))
    n = sorted((r.trades.qty * r.trades.entry_px).round(4))
    assert n == [8_100.0, 9_000.0, 10_000.0]          # 10% of 100k, then 10% of 90k, then 10% of 81k

def test_max_positions_cap():
    p = mini_panel({k: [100] * 4 for k in "ABC"})
    r = run_backtest(p, tgt(p, {k: [1, 1, 0, 0] for k in "ABC"}), cfg(pos_frac=0.1, max_pos={"crypto": 2, "equity": 2}))
    assert len(r.trades) == 2 and r.skipped["cap_pos"] >= 1

def test_pools_are_separate():
    p = mini_panel({"A": [100] * 4, "E": [100] * 4}, classes={"A": "crypto", "E": "equity"})
    r = run_backtest(p, tgt(p, {"A": [1, 1, 0, 0], "E": [1, 1, 0, 0]}), cfg(crypto_weight=0.3, pos_frac=0.5))
    t = r.trades.set_index("asset")
    assert t.loc["A", "qty"] * 100 == pytest.approx(0.5 * 30_000) and t.loc["E", "qty"] * 100 == pytest.approx(0.5 * 70_000)

def test_short_profit_and_capped_loss():
    p = mini_panel({"A": [100, 100, 90, 90]})
    r = run_backtest(p, tgt(p, {"A": [-1, -1, 0, 0]}), cfg(pos_frac=0.5, allow_short=True))
    assert r.trades.pnl_net.iloc[0] == pytest.approx(0.5 * 100_000 * 0.10, rel=1e-9)
    p = mini_panel({"A": [100, 100, 300, 300]})
    r = run_backtest(p, tgt(p, {"A": [-1, -1, 0, 0]}), cfg(pos_frac=0.5, allow_short=True))
    assert r.trades.pnl_net.iloc[0] == pytest.approx(-0.5 * 100_000, rel=1e-9)      # loss capped at collateral

def test_no_fill_when_not_tradable():
    p0 = mini_panel({"A": [100] * 6})
    tr = pd.DataFrame(False, index=p0.index, columns=["A"]); tr.iloc[3:] = True
    p = mini_panel({"A": [100] * 6}, tradable=tr)
    r = run_backtest(p, tgt(p, {"A": [1, 1, 1, 1, 1, 1]}), cfg())
    assert r.curve.exposure.iloc[:4].sum() == 0 and r.curve.exposure.iloc[4] > 0     # first fill only when tradable

def test_stop_loss_blocks_reentry_until_signal_resets():
    p = mini_panel({"A": [100, 100, 95, 95, 95, 95, 96, 96]})
    t = tgt(p, {"A": [1, 1, 1, 1, 1, 0, 1, 1]})
    r = run_backtest(p, t, cfg(pos_frac=0.5, risk=RiskConfig(stop_loss=0.03)))
    assert list(r.trades.reason)[0] == "stop"
    # signal stays long on bars 3-4 but the position must stay OUT (blocked) until the signal resets at bar 5
    assert r.curve.exposure.iloc[3:7].sum() == 0
    assert len(r.open_positions) == 1 and r.curve.exposure.iloc[-1] > 0     # re-entered after the reset (bar 6)

def test_dd_halt_flattens_and_pauses():
    p = mini_panel({"A": [100, 100, 80, 80, 80, 80, 80, 80]})
    r = run_backtest(p, tgt(p, {"A": [1] * 8}), cfg(pos_frac=1.0, risk=RiskConfig(dd_halt=0.10, halt_bars=3)))
    assert (r.trades.reason == "halt").any()

def test_audit_exports_reconcile_completed_and_open_positions(tmp_path):
    p = mini_panel({"A": [100, 100, 110, 110, 120, 120], "B": [50, 50, 50, 50, 55, 60]})
    target = tgt(p, {"A": [1, 1, 0, 0, 0, 0], "B": [0, 0, 0, 1, 1, 1]})
    result = run_backtest(p, target, cfg(pos_frac=0.5, fee=0.001))
    report = perf_report(result, p.freq_min, 100_000)
    reported_max_drawdown = -0.123

    summary, paths = export_backtest_audit(
        result, 100_000, report["n_trades"], "audit_test", tmp_path,
        reported_max_drawdown=reported_max_drawdown,
    )
    trades = pd.read_csv(paths["trades"])
    equity = pd.read_csv(paths["equity"])
    open_positions = pd.read_csv(paths["open_positions"])

    assert summary["completed_trades"] == report["n_trades"] == len(trades) == 1
    assert summary["open_positions"] == len(open_positions) == 1
    assert summary["max_drawdown_pct"] == pytest.approx(reported_max_drawdown * 100)
    assert trades.trade_id.is_unique
    assert set(trades.trade_id).isdisjoint(set(open_positions.trade_id))
    assert {"gross_pnl", "fees", "net_pnl", "holding_period_hours"} <= set(trades.columns)
    assert {"cash", "gross_exposure", "net_exposure", "realized_pnl", "unrealized_pnl", "total_pnl", "drawdown"} <= set(equity.columns)
    assert np.isclose(trades.fees.sum() + open_positions.entry_fee.sum(), result.fees)
    assert np.isclose(trades.net_pnl.sum() + open_positions.unrealized_pnl.sum(), equity.total_pnl.iloc[-1])
    assert equity.timestamp.is_monotonic_increasing

    with pytest.raises(ValueError, match="trade count"):
        export_backtest_audit(result, 100_000, report["n_trades"] + 1, "bad_count", tmp_path)
