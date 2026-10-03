"""Stage C: robustness analysis + final selection (brief sections 7, 21, 23)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .runner import evaluate, LOG
from ..constants import TRAIN_START, TRAIN_END


def rank_pct(s: pd.Series) -> pd.Series:
    return s.rank(pct=True)


def candidate_table(stage: str = "A", tf: str | None = None, max_tpd: float = 12.0, max_dd: float = 0.30,
                    min_trades: int = 30, min_net_over_gross: float = 0.5, log=LOG) -> pd.DataFrame:
    df = pd.read_csv(log)
    df = df[df.stage == stage]
    if tf:
        df = df[df.timeframe == tf]
    gates = (
        (df.total_return > 0) & (df.n_trades >= min_trades) & (df.trades_per_day <= max_tpd) & (df.max_dd >= -max_dd)
        & (df.w14_pos_frac >= 0.5) & (df.composite > 0)
        & ((df.gross_return <= 0) | (df.total_return / df.gross_return >= min_net_over_gross))     # fees must not eat >half the edge
    )
    df = df.assign(passed=gates)
    df["score"] = 0.5 * rank_pct(df.composite) + 0.3 * rank_pct(df.w14_comp_med) + 0.2 * rank_pct(-df.fee_drag_pct)
    return df.sort_values(["passed", "score"], ascending=False)


def parameter_stability(df: pd.DataFrame) -> pd.DataFrame:
    """A strategy FAMILY is robust if most of its neighbouring parameter sets also work."""
    g = df.groupby(["indicators", "timeframe", "assets", "sizing"])
    out = g.agg(n_params=("composite", "size"), frac_positive=("total_return", lambda x: (x > 0).mean()),
                med_composite=("composite", "median"), best_composite=("composite", "max"),
                med_mdd=("max_dd", "median"))
    out["median_to_best"] = out.med_composite / out.best_composite.replace(0, np.nan)
    return out.sort_values("med_composite", ascending=False)


def yearly_consistency(panel_full, ext, spec, pcfg, tf, years=(2023, 2024, 2025)) -> pd.DataFrame:
    rows = []
    for y in years:
        s, e = pd.Timestamp(f"{y}-01-01", tz="UTC"), pd.Timestamp(f"{y}-12-31 23:59:59", tz="UTC")
        if e > TRAIN_END:
            continue
        try:
            _, r = evaluate(panel_full, spec, ext, pcfg, s, e, tf)
        except Exception:
            continue
        rows.append({"year": y, "ret": r["total_return"], "sharpe": r["sharpe"], "sortino": r["sortino"],
                     "max_dd": r["max_dd"], "composite": r["composite"], "trades": r["n_trades"]})
    d = pd.DataFrame(rows)
    return d


def walk_forward(panel_full, ext, specs, pcfg, tf, folds=((("2023", "2023"), ("2024", "2024")),
                                                         (("2023", "2024"), ("2025", "2025")))) -> pd.DataFrame:
    """For each fold pick the grid member with the best TRAIN composite and report its TEST result next to
    the median TEST result of the whole grid (tells you whether picking on train adds anything)."""
    def rng(a, b):
        return pd.Timestamp(f"{a}-01-01", tz="UTC"), pd.Timestamp(f"{b}-12-31 23:59:59", tz="UTC")
    out = []
    for (tr, te) in folds:
        (ts, tend), (vs, vend) = rng(*tr), rng(*te)
        assert vend <= TRAIN_END, "walk-forward folds here must stay inside the development period"
        tab = []
        for sp in specs:
            try:
                _, a = evaluate(panel_full, sp, ext, pcfg, ts, tend, tf)
                _, b = evaluate(panel_full, sp, ext, pcfg, vs, vend, tf)
            except Exception:
                continue
            tab.append((sp.name, a["composite"], b["composite"], b["total_return"]))
        t = pd.DataFrame(tab, columns=["spec", "train_comp", "test_comp", "test_ret"])
        if t.empty:
            continue
        best = t.loc[t.train_comp.idxmax()]
        out.append({"train": "-".join(tr), "test": "-".join(te), "picked": best.spec, "train_comp": best.train_comp,
                    "test_comp_picked": best.test_comp, "test_ret_picked": best.test_ret,
                    "test_comp_grid_median": t.test_comp.median(), "test_ret_grid_median": t.test_ret.median()})
    return pd.DataFrame(out)
