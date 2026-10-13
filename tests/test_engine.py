import numpy as np, pandas as pd, pytest
from rq.backtest.engine import run_backtest, PortfolioConfig, ExitConfig
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


def test_drawdown_ladder_does_not_force_sell_existing_positions():
    p = mini_panel({"A": [100, 100, 80, 80, 80, 80], "B": [100] * 6})
    target = tgt(p, {"A": [1, 1, 1, 1, 1, 1], "B": [0, 0, 1, 1, 1, 1]})
    r = run_backtest(
        p, target,
        cfg(pos_frac=0.5, max_pos={"crypto": 5, "equity": 5},
            risk=RiskConfig(dd_ladder=((0.10, 0.5),))),
    )
    # The existing A position remains open despite the portfolio drawdown.
    assert not any(t["asset"] == "A" and t["reason"] == "signal" for t in r.trades.to_dict("records"))
    assert any(pos["asset"] == "A" for pos in r.open_positions)
    # B is a new entry after the drawdown and must be sized below A's initial notional.
    b = next(pos for pos in r.open_positions if pos["asset"] == "B")
    assert b["entry"] * b["qty"] < 0.5 * 100_000


def test_x3_trailing_exit_records_mfe_mae_and_giveback():
    p = mini_panel({"A": [100, 100, 120, 110, 100, 100, 100]})
    target = tgt(p, {"A": [1, 1, 1, 1, 1, 0, 0]})
    r = run_backtest(p, target, cfg(pos_frac=0.5),
                     exit_config=ExitConfig(variant="X3", trailing_pct=0.05))
    stopped = r.trades[r.trades.reason == "protective_X3"]
    assert len(stopped) == 1
    trade = stopped.iloc[0]
    assert trade.mfe > 0
    assert trade.mae <= 0
    assert trade.giveback == pytest.approx(trade.mfe - trade.pnl_net)
    assert bool(trade.profitable_1atr_loser) == (trade.mfe >= trade.qty * trade.entry_atr and trade.pnl_net < 0)


def test_x6_partial_take_profit_banks_half_and_keeps_a_trailing_remainder():
    p = mini_panel({"A": [100, 100, 110, 110, 110, 100, 100, 100]})
    target = tgt(p, {"A": [1, 1, 1, 1, 1, 0, 0, 0]})
    r = run_backtest(p, target, cfg(pos_frac=0.5),
                     exit_config=ExitConfig(variant="X6", partial_r=1.5, chandelier_k=3.0))
    assert (r.trades.reason == "partial_tp_X6").sum() == 1
    assert (r.trades.reason == "protective_X6").sum() == 1
    assert r.trades.trade_id.is_unique
    partial = r.trades[r.trades.reason == "partial_tp_X6"].iloc[0]
    remainder = r.trades[r.trades.reason == "protective_X6"].iloc[0]
    assert partial.qty == pytest.approx(remainder.qty)
    assert partial.pnl_net > 0


def test_x0_is_identical_to_existing_signal_exit_baseline():
    p = mini_panel({"A": [100, 102, 101, 108, 104, 103, 109]})
    target = tgt(p, {"A": [1, 1, 1, 1, 1, 0, 0]})
    baseline = run_backtest(p, target, cfg(pos_frac=0.5))
    x0 = run_backtest(p, target, cfg(pos_frac=0.5), exit_config=ExitConfig(variant="X0"))
    assert np.allclose(baseline.curve.equity_total, x0.curve.equity_total)
    assert baseline.trades.pnl_net.tolist() == pytest.approx(x0.trades.pnl_net.tolist())
    assert list(baseline.trades.reason) == list(x0.trades.reason)

def test_portfolio_profit_lock_exits_and_requires_signal_reset_before_reentry():
    p = mini_panel({"A": [100, 100, 110, 110, 105, 105, 105, 105, 105, 105, 105, 105, 105, 105]})
    target = tgt(p, {"A": [1, 1, 1, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 1]})
    lock = ExitConfig(
        portfolio_lock_enabled=True,
        portfolio_lock_activation=500,
        portfolio_lock_giveback=0.45,
        portfolio_lock_cooldown_bars=3,
    )

    r = run_backtest(p, target, cfg(pos_frac=1.0), exit_config=lock)

    assert len(r.trades) == 1
    assert r.trades.iloc[0].reason == "portfolio_profit_lock"
    assert r.trades.iloc[0].pnl_net == pytest.approx(5_000.0)
    event_types = [event["event"] for event in r.lock_events]
    assert "activated" in event_types
    assert "triggered" in event_types
    assert "liquidation_complete" in event_types
    assert event_types.index("triggered") < event_types.index("liquidation_complete")
    # The original long signal remains active on bar 5, so the lock must not
    # immediately buy back the position. A signal reset then permits a later entry.
    assert r.curve.n_pos.iloc[5:9].sum() == 0
    assert r.curve.n_pos.iloc[10] == 1
    assert len(r.open_positions) == 1


def test_portfolio_profit_lock_retries_untradable_exit_and_starts_cooldown_after_flat():
    p0 = mini_panel({"A": [100, 100, 110, 110, 105, 100, 95, 95, 95, 95, 95, 95, 95, 95, 95, 95]})
    tradable = pd.DataFrame(True, index=p0.index, columns=["A"])
    tradable.iloc[4:6] = False
    p = mini_panel(
        {"A": [100, 100, 110, 110, 105, 100, 95, 95, 95, 95, 95, 95, 95, 95, 95, 95]},
        tradable=tradable,
    )
    target = tgt(p, {"A": [1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1]})
    lock = ExitConfig(
        portfolio_lock_enabled=True,
        portfolio_lock_activation=500,
        portfolio_lock_giveback=0.45,
        portfolio_lock_cooldown_bars=3,
    )

    r = run_backtest(p, target, cfg(pos_frac=1.0), exit_config=lock)

    assert len(r.trades) == 1
    assert r.trades.iloc[0].reason == "portfolio_profit_lock"
    # The lock triggers while untradable, but the exit is retried at the first
    # tradable bar. Cooldown begins after that actual liquidation.
    assert r.trades.iloc[0].pnl_net == pytest.approx(-5_000.0)
    event_types = [event["event"] for event in r.lock_events]
    assert "triggered" in event_types
    assert "liquidation_complete" in event_types
    trigger_i = event_types.index("triggered")
    complete_i = event_types.index("liquidation_complete")
    assert r.lock_events[trigger_i]["bar_index"] < r.lock_events[complete_i]["bar_index"]
    assert r.curve.n_pos.iloc[9] == 0
    assert r.curve.n_pos.iloc[10] == 0
    assert r.curve.n_pos.iloc[11] == 1
    assert len(r.open_positions) == 1



def test_x8_exits_when_price_closes_below_a_falling_ema():
    p = mini_panel({"A": [100, 100, 110, 108, 105, 100, 100]})
    target = tgt(p, {"A": [1, 1, 1, 1, 1, 1, 0]})
    r = run_backtest(
        p,
        target,
        cfg(pos_frac=0.5),
        exit_config=ExitConfig(variant="X8", trend_ema_span=2),
    )
    exited = r.trades[r.trades.reason == "ema_trend_failure_X8"]
    assert len(exited) == 1
    assert exited.iloc[0].exit_px == pytest.approx(105.0)


def test_x9_exits_after_configured_holding_period():
    p = mini_panel({"A": [100] * 9})
    target = tgt(p, {"A": [1] * 9})
    r = run_backtest(
        p, target, cfg(pos_frac=0.5),
        exit_config=ExitConfig(variant="X9", max_holding_bars=2),
    )
    exited = r.trades[r.trades.reason == "time_exit_X9"]
    assert len(exited) == 1
    assert exited.iloc[0].bars >= 2


def test_x10_exits_stale_loser_but_keeps_profitable_position():
    losing_panel = mini_panel({"A": [100, 100, 95, 95, 95, 95]})
    losing_target = tgt(losing_panel, {"A": [1, 1, 1, 1, 1, 1]})
    losing_result = run_backtest(
        losing_panel,
        losing_target,
        cfg(pos_frac=0.5, fee=0.001),
        exit_config=ExitConfig(variant="X10", max_holding_bars=2),
    )
    assert (losing_result.trades.reason == "stale_loss_exit_X10").any()

    winning_panel = mini_panel({"A": [100, 100, 105, 110, 115, 120]})
    winning_target = tgt(winning_panel, {"A": [1, 1, 1, 1, 1, 1]})
    winning_result = run_backtest(
        winning_panel,
        winning_target,
        cfg(pos_frac=0.5, fee=0.001),
        exit_config=ExitConfig(variant="X10", max_holding_bars=2),
    )
    if not winning_result.trades.empty and "reason" in winning_result.trades.columns:
        assert not (winning_result.trades["reason"] == "stale_loss_exit_X10").any()
    assert len(winning_result.open_positions) == 1


def test_x11_exits_stale_loser_only_when_trend_weakens():
    losing_panel = mini_panel({"A": [100, 100, 95, 94, 93, 92, 91]})
    losing_target = tgt(losing_panel, {"A": [1, 1, 1, 1, 1, 1, 1]})
    losing_result = run_backtest(
        losing_panel,
        losing_target,
        cfg(pos_frac=0.5, fee=0.001),
        exit_config=ExitConfig(
            variant="X11",
            max_holding_bars=2,
            trend_ema_span=2,
        ),
    )
    assert (
        not losing_result.trades.empty
        and "reason" in losing_result.trades.columns
        and (losing_result.trades["reason"] == "stale_loss_trend_exit_X11").any()
    )

    winning_panel = mini_panel({"A": [100, 100, 105, 110, 115, 120, 125]})
    winning_target = tgt(winning_panel, {"A": [1, 1, 1, 1, 1, 1, 1]})
    winning_result = run_backtest(
        winning_panel,
        winning_target,
        cfg(pos_frac=0.5, fee=0.001),
        exit_config=ExitConfig(
            variant="X11",
            max_holding_bars=2,
            trend_ema_span=2,
        ),
    )
    if not winning_result.trades.empty and "reason" in winning_result.trades.columns:
        assert not (
            winning_result.trades["reason"] == "stale_loss_trend_exit_X11"
        ).any()
    assert len(winning_result.open_positions) == 1


def test_x12_ema20_exit_closes_below_ema_and_keeps_uptrend():
    falling_panel = mini_panel({"A": [100, 100, 95, 94, 93, 92, 91]})
    falling_target = tgt(falling_panel, {"A": [1] * 7})
    falling_result = run_backtest(
        falling_panel,
        falling_target,
        cfg(pos_frac=0.5, fee=0.001),
        exit_config=ExitConfig(variant="X12", ema_exit_span=2),
    )
    assert (
        not falling_result.trades.empty
        and "reason" in falling_result.trades.columns
        and (falling_result.trades["reason"] == "ema20_exit_X12").any()
    )

    rising_panel = mini_panel({"A": [100, 100, 105, 110, 115, 120, 125]})
    rising_target = tgt(rising_panel, {"A": [1] * 7})
    rising_result = run_backtest(
        rising_panel,
        rising_target,
        cfg(pos_frac=0.5, fee=0.001),
        exit_config=ExitConfig(variant="X12", ema_exit_span=2),
    )
    if not rising_result.trades.empty and "reason" in rising_result.trades.columns:
        assert not (rising_result.trades["reason"] == "ema20_exit_X12").any()
    assert len(rising_result.open_positions) == 1


def test_x13_exits_on_negative_momentum_cross():
    falling_panel = mini_panel({"A": [100, 100, 105, 106, 104, 102, 100, 98]})
    falling_target = tgt(falling_panel, {"A": [1] * 8})
    falling_result = run_backtest(
        falling_panel,
        falling_target,
        cfg(pos_frac=0.5, fee=0.001),
        exit_config=ExitConfig(variant="X13", momentum_lookback=2),
    )
    assert (
        not falling_result.trades.empty
        and "reason" in falling_result.trades.columns
        and (falling_result.trades["reason"] == "momentum_reversal_X13").any()
    )

    rising_panel = mini_panel({"A": [100, 100, 102, 104, 106, 108, 110, 112]})
    rising_target = tgt(rising_panel, {"A": [1] * 8})
    rising_result = run_backtest(
        rising_panel,
        rising_target,
        cfg(pos_frac=0.5, fee=0.001),
        exit_config=ExitConfig(variant="X13", momentum_lookback=2),
    )
    if not rising_result.trades.empty and "reason" in rising_result.trades.columns:
        assert not (
            rising_result.trades["reason"] == "momentum_reversal_X13"
        ).any()
    assert len(rising_result.open_positions) == 1


def test_x14_exits_when_ema_and_momentum_are_bearish():
    falling_panel = mini_panel({"A": [100, 100, 105, 106, 104, 102, 100, 98]})
    falling_target = tgt(falling_panel, {"A": [1] * 8})
    falling_result = run_backtest(
        falling_panel,
        falling_target,
        cfg(pos_frac=0.5, fee=0.001),
        exit_config=ExitConfig(variant="X14", momentum_lookback=2),
    )
    assert (
        not falling_result.trades.empty
        and "reason" in falling_result.trades.columns
        and (falling_result.trades["reason"] == "ema_momentum_exit_X14").any()
    )

    rising_panel = mini_panel({"A": [100, 100, 102, 104, 106, 108, 110, 112]})
    rising_target = tgt(rising_panel, {"A": [1] * 8})
    rising_result = run_backtest(
        rising_panel,
        rising_target,
        cfg(pos_frac=0.5, fee=0.001),
        exit_config=ExitConfig(variant="X14", momentum_lookback=2),
    )
    if not rising_result.trades.empty and "reason" in rising_result.trades.columns:
        assert not (
            rising_result.trades["reason"] == "ema_momentum_exit_X14"
        ).any()
    assert len(rising_result.open_positions) == 1
