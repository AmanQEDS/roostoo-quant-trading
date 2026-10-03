"""python -m rq.cli <command>   (see README for the full workflow)"""
from __future__ import annotations

import argparse, itertools, json, logging
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .config import load_config, load_env
from .constants import TRAIN_START, TRAIN_END, VAL_START
from .backtest.engine import PortfolioConfig
from .backtest.risk import RiskConfig
from .research import runner, selection, lock
from .research.grid import build_grid, S, Spec
from .research.loader import get_data


pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)


def _pcfg(cfg, cw=None, pf=0.10, mp=(5, 10), short=False, fee=None, risk=None):
    from .constants import TAKER_FEE

    return PortfolioConfig(
        capital=cfg["portfolio"]["capital"],
        crypto_weight=1.0 if cw is None else cw,
        pos_frac=pf,
        max_pos={"crypto": mp[0], "equity": mp[1]},
        fee=TAKER_FEE if fee is None else fee,
        slip_bps=cfg["portfolio"]["slip_bps"],
        allow_short=short,
        risk=risk or RiskConfig(),
    )


def _grid(args, ext):
    g = build_grid()

    if getattr(args, "only", None):
        g = [s for s in g if s.builder in args.only]

    if getattr(args, "limit", None):
        g = g[: args.limit]

    return g


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rq")
    ap.add_argument("--config", default=None)

    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "discover",
        help="Step 1: snapshot the REAL Roostoo universe"
    )

    d = sub.add_parser("download")
    d.add_argument("--no-equity", action="store_true")

    sub.add_parser("check-data")

    a = sub.add_parser("stage-a")
    a.add_argument("--freq", nargs="+", default=None)
    a.add_argument("--modes", nargs="+", default=["L", "LS"])
    a.add_argument("--only", nargs="*")
    a.add_argument("--limit", type=int)
    a.add_argument("--no-resume", action="store_true")
    a.add_argument("--jobs", type=int, default=1)

    r = sub.add_parser("report")
    r.add_argument("--stage", default="A")
    r.add_argument("--freq")
    r.add_argument("--top", type=int, default=25)

    w = sub.add_parser("walkforward")
    w.add_argument("--builder", required=True)
    w.add_argument("--freq", default="30m")
    w.add_argument("--mode", default="L")

    al = sub.add_parser("alloc-sweep")
    al.add_argument(
        "--crypto",
        required=True,
        help="spec name from the log"
    )
    al.add_argument("--equity", default=None)
    al.add_argument("--freq", default="30m")
    al.add_argument("--validate", action="store_true")

    f = sub.add_parser("freeze")
    f.add_argument("names", nargs="+")

    v = sub.add_parser("validate")
    v.add_argument("--freq", default=None)
    v.add_argument("--only", nargs="+", help="validate only these exact names from the frozen shortlist")

    bm = sub.add_parser("baselines")
    bm.add_argument("--freq", default="30m")
    bm.add_argument("--stage", default="A")

    lv = sub.add_parser("live")
    lv.add_argument("--dry-run", action="store_true")
    lv.add_argument("--confirm", action="store_true")

    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    load_env()

    freqs = getattr(args, "freq", None)
    freqs = [freqs] if isinstance(freqs, str) else (
        freqs or cfg["timeframes"]
    )

    if args.cmd == "discover":
        from .roostoo.universe import discover
        discover()
        return

    if args.cmd == "download":
        from .cli_download import run_download
        run_download(cfg, equity=not args.no_equity)
        return

    if args.cmd == "check-data":
        from .cli_download import check_data
        check_data()
        return

    if args.cmd == "freeze":
        print(json.dumps(lock.freeze(args.names), indent=1))
        return

    if args.cmd == "live":
        from .live.bot import Bot
        Path("logs").mkdir(exist_ok=True)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler("logs/bot.log"),
            ],
        )

        if not args.dry_run and not args.confirm:
            raise SystemExit(
                "refusing to trade: pass --dry-run or --confirm"
            )

        Bot(dry_run=args.dry_run).run()
        return

    if args.cmd == "stage-a":
        for tf in freqs:
            panel, ext = get_data(cfg, tf)
            grid = _grid(args, ext)

            for mode in args.modes:
                for cw in (
                    [1.0]
                    if not panel.cols("equity")
                    else [1.0]
                ):
                    # sleeve research: single-class pools at 100%
                    pc = _pcfg(
                        cfg,
                        short=(mode == "LS")
                    )

                    print(
                        f"\n=== Stage A | {tf} | mode={mode} | "
                        f"{len(grid)} specs | "
                        f"{TRAIN_START.date()}..{TRAIN_END.date()} ==="
                    )

                    runner.run_stage_a(
                        panel,
                        ext,
                        grid,
                        pc,
                        tf,
                        resume=not args.no_resume,
                        jobs=args.jobs,
                    )

        return

    if args.cmd == "report":
        t = selection.candidate_table(
            args.stage,
            args.freq,
            cfg["gates"]["max_trades_per_day"],
            cfg["gates"]["max_drawdown"],
            cfg["gates"]["min_trades"],
        )

        cols = [
            "strategy",
            "timeframe",
            "sizing",
            "passed",
            "score",
            "total_return",
            "sharpe",
            "sortino",
            "calmar",
            "max_dd",
            "n_trades",
            "trades_per_day",
            "fee_drag_pct",
            "w14_ret_med",
            "w14_pos_frac",
        ]

        print(
            t[cols]
            .head(args.top)
            .to_string(
                index=False,
                float_format=lambda x: f"{x:.3f}"
            )
        )

        print(
            "\nPARAMETER STABILITY (family level)\n",
            selection.parameter_stability(t)
            .head(15)
            .to_string(
                float_format=lambda x: f"{x:.3f}"
            ),
        )

        return

    if args.cmd == "walkforward":
        panel, ext = get_data(cfg, freqs[0])

        specs = [
            s
            for s in build_grid()
            if s.builder == args.builder
        ]

        print(
            selection.walk_forward(
                panel,
                ext,
                specs,
                _pcfg(
                    cfg,
                    short=args.mode == "LS"
                ),
                freqs[0],
            ).to_string(
                index=False,
                float_format=lambda x: f"{x:.3f}"
            )
        )

        return

    if args.cmd == "baselines":
        from .research.benchmarks import baseline_suite

        panel, ext = get_data(cfg, freqs[0])

        s, e = (
            (TRAIN_START, TRAIN_END)
            if args.stage == "A"
            else (VAL_START, panel.index[-1])
        )

        print(
            baseline_suite(
                panel,
                ext,
                _pcfg(cfg, cw=0.3),
                freqs[0],
                s,
                e,
            ).to_string(
                float_format=lambda x: f"{x:.3f}"
            )
        )

        return

    if args.cmd == "alloc-sweep":
        tf = freqs[0]
        panel, ext = get_data(cfg, tf)

        by_name = {
            s.name: s
            for s in build_grid()
        }

        sc = by_name[args.crypto]

        se = (
            by_name[args.equity]
            if args.equity
            else None
        )

        start, end = (
            (VAL_START, panel.index[-1])
            if args.validate
            else (TRAIN_START, TRAIN_END)
        )

        rows = []

        for cw, pf, mpc, mpe in itertools.product(
            cfg["portfolio"]["crypto_weights"],
            cfg["portfolio"]["pos_frac"],
            cfg["portfolio"]["max_pos_crypto"],
            cfg["portfolio"]["max_pos_equity"],
        ):
            pc = _pcfg(
                cfg,
                cw=cw,
                pf=pf,
                mp=(mpc, mpe),
            )

            if args.validate:
                # ---------------------------------------------------------
                # VALIDATION LOCK
                #
                # The frozen shortlist contains individual strategy names.
                # Therefore:
                #
                #   crypto-only -> guard crypto strategy
                #   crypto+equity -> guard BOTH strategies individually
                #
                # Do NOT construct crypto|equity here because that pair
                # does not exist in the frozen shortlist.
                # ---------------------------------------------------------

                lock.guard(
                    sc.name,
                    tf,
                    pc.tag(),
                )

                if se is not None:
                    lock.guard(
                        se.name,
                        tf,
                        pc.tag(),
                    )

            _, rep = runner.evaluate_pair(
                panel,
                sc,
                se,
                ext,
                pc,
                start,
                end,
            )

            runner.log_experiment(
                "B-alloc" if args.validate else "A-alloc",
                runner.pair_spec(sc, se),
                tf,
                pc,
                start,
                end,
                rep,
            )

            rows.append(
                {
                    "cw": cw,
                    "pos_frac": pf,
                    "max_c": mpc,
                    "max_e": mpe,
                    **{
                        k: rep[k]
                        for k in [
                            "total_return",
                            "sharpe",
                            "sortino",
                            "calmar",
                            "max_dd",
                            "vol",
                            "downside_dev",
                            "n_trades",
                            "fees_paid",
                            "final_value",
                            "composite",
                            "w14_ret_med",
                            "w14_mdd_worst",
                        ]
                    },
                }
            )

        df = pd.DataFrame(rows).sort_values(
            "composite",
            ascending=False,
        )

        Path("results").mkdir(
            exist_ok=True
        )

        df.to_csv(
            f"results/alloc_sweep_"
            f"{'val' if args.validate else 'dev'}_"
            f"{tf}.csv",
            index=False,
        )

        print(
            df.head(20).to_string(
                index=False,
                float_format=lambda x: f"{x:.3f}",
            )
        )

        print(
            "\nBy crypto weight (median over sizing grid):\n",
            df.groupby("cw")[
                [
                    "total_return",
                    "sharpe",
                    "sortino",
                    "calmar",
                    "max_dd",
                    "composite",
                ]
            ].median().to_string(
                float_format=lambda x: f"{x:.3f}"
            ),
        )

        return

    if args.cmd == "validate":
        sl = json.loads(
            Path(lock.SHORTLIST).read_text()
        )["names"]
        selected = args.only or sl
        unknown = sorted(set(selected) - set(sl))
        if unknown:
            raise SystemExit(f"refusing validation: not in frozen shortlist: {unknown}")

        for tf in freqs:
            panel, ext = get_data(cfg, tf)

            by_name = {
                s.name: s
                for s in build_grid()
            }

            for name in selected:
                sp = by_name[name]
                pc = _pcfg(cfg)

                lock.guard(
                    name,
                    tf,
                    pc.tag(),
                )

                res, rep = runner.evaluate(
                    panel,
                    sp,
                    ext,
                    pc,
                    VAL_START,
                    panel.index[-1],
                    tf,
                )

                runner.log_experiment(
                    "B",
                    sp,
                    tf,
                    pc,
                    VAL_START,
                    panel.index[-1],
                    rep,
                )

                from .backtest.audit import export_backtest_audit

                summary, paths = export_backtest_audit(
                    res,
                    pc.capital,
                    rep["n_trades"],
                    f"{sp.name.replace('(', '_').replace(')', '').replace(',', '').replace('=', '-')}_{tf}_2026",
                    reported_max_drawdown=rep["max_dd"],
                )

                print("AUDIT SUMMARY")
                print(f"Strategy: {name}")
                print(f"Validation period: {VAL_START.date()}..{panel.index[-1].date()}")
                print(f"Starting capital: ${summary['starting_capital']:,.2f}")
                print(f"Ending portfolio value: ${summary['ending_portfolio_value']:,.2f}")
                print(f"Total return: {summary['total_return_pct']:+.2f}%")
                print(f"Realized P&L: ${summary['realized_pnl']:,.2f}")
                print(f"Unrealized P&L: ${summary['unrealized_pnl']:,.2f}")
                print(f"Total fees: ${summary['total_fees']:,.2f}")
                print(f"Completed trades: {summary['completed_trades']}")
                print(f"Open positions: {summary['open_positions']}")
                print(f"Max drawdown (existing daily metric): {summary['max_drawdown_pct']:.2f}%")
                print(f"Max drawdown (bar-level audit): {summary['bar_level_max_drawdown_pct']:.2f}%")
                print(f"Realized return: {summary['realized_return_pct']:+.2f}%")
                print(f"Unrealized return: {summary['unrealized_return_pct']:+.2f}%")
                print(f"Closed-trade win rate: {summary['closed_trade_win_rate_pct']:.2f}%")
                print(f"Profit factor: {summary['profit_factor']:.3f}")
                print(f"Average trade net P&L: ${summary['average_trade_net_pnl']:,.2f}")
                print(f"Median holding period: {summary['median_holding_period_hours']:.2f} hours")
                print("Audit files:")
                for path in paths.values():
                    print(f"  {path}")

                print(
                    f"[B {tf}] "
                    f"{name:60s} "
                    f"ret={rep['total_return']:+.1%}"
                    f"sharpe={rep['sharpe']:.2f} "
                    f"sortino={rep['sortino']:.2f} "
                    f"calmar={rep['calmar']:.2f} "
                    f"mdd={rep['max_dd']:.1%} "
                    f"trades={rep['n_trades']}"
                )


if __name__ == "__main__":
    main()