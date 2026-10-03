"""Run a Spec through the two-pool engine, log everything, never overwrite history."""
from __future__ import annotations
import hashlib, json, time
from pathlib import Path
import numpy as np
import pandas as pd
from ..constants import TRAIN_START, TRAIN_END, VAL_START
from ..signals.families import BUILDERS
from ..signals.elliott import elliott
from ..signals.core import to_target, MissingData, Cond
from ..backtest.engine import run_backtest, PortfolioConfig
from ..backtest.metrics import perf_report, rolling_window_report
from .grid import Spec, RULES

ALL_BUILDERS = {**BUILDERS, "elliott": elliott}
LOG = Path("results/experiment_log.csv")


def build_targets(panel, spec: Spec, ext: dict, allow_short: bool, classes_override=None):
    """Signals for each class the spec applies to; classes not covered stay flat."""
    parts_t, parts_s = [], []
    for k in (classes_override or spec.classes):
        cols = panel.cols(k)
        if not cols:
            continue
        sub = panel.subset(cols)
        cond = ALL_BUILDERS[spec.builder](sub, ext, **spec.p)
        parts_t.append(to_target(cond, allow_short))
        parts_s.append(cond.score if cond.score is not None else pd.DataFrame(np.nan, index=sub.index, columns=cols))
    if not parts_t:
        raise MissingData("no assets for classes " + str(spec.classes))
    t = pd.concat(parts_t, axis=1).reindex(columns=panel.columns).fillna(0).astype("int8")
    s = pd.concat(parts_s, axis=1).reindex(columns=panel.columns)
    return t, s


def evaluate(panel_full, spec: Spec, ext: dict, pcfg: PortfolioConfig, start, end, tf: str):
    """Signals on history <= end (causal), engine on [start, end]."""
    p_end = panel_full.slice(None, end)
    t, s = build_targets(p_end, spec, ext, pcfg.allow_short)
    pw = p_end.slice(start, end)
    res = run_backtest(pw, t.loc[pw.index], pcfg, s.loc[pw.index])
    rep = perf_report(res, panel_full.freq_min, pcfg.capital)
    rep.update(rolling_window_report(res.curve["equity_total"], 14))
    return res, rep


def _key(stage, spec, tf, pcfg, start, end) -> str:
    return hashlib.sha1(f"{stage}|{spec.name}|{spec.classes}|{tf}|{pcfg.tag()}|{pcfg.risk}|{start}|{end}".encode()).hexdigest()[:16]


def log_experiment(stage: str, spec: Spec, tf: str, pcfg: PortfolioConfig, start, end, rep: dict, note: str = "") -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    ent, ex = RULES.get(spec.builder, ("", ""))
    row = {"exp_id": _key(stage, spec, tf, pcfg, start, end), "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "stage": stage,
           "strategy": spec.name, "family": family_of(spec.builder), "timeframe": tf, "assets": "+".join(spec.classes),
           "indicators": spec.builder, "params": json.dumps(spec.p), "entry_rule": ent, "exit_rule": ex,
           "sizing": pcfg.tag(), "risk": json.dumps({k: v for k, v in vars(pcfg.risk).items() if v not in (None, False, ())}),
           "fee": pcfg.fee, "period": f"{pd.Timestamp(start).date()}..{pd.Timestamp(end).date()}", "note": note, **rep}
    df = pd.DataFrame([row])
    df.to_csv(LOG, mode="a", header=not LOG.exists(), index=False)


def already_done(stage, spec, tf, pcfg, start, end) -> bool:
    if not LOG.exists():
        return False
    return _key(stage, spec, tf, pcfg, start, end) in set(pd.read_csv(LOG, usecols=["exp_id"])["exp_id"])


def family_of(builder: str) -> str:
    from ..signals.families import FAMILY
    for f, bs in FAMILY.items():
        if builder in bs:
            return f
    return "elliott" if builder == "elliott" else "other"


_G: dict = {}


def _init_worker(panel, ext, pcfg, start, end, tf):
    _G.update(panel=panel, ext=ext, pcfg=pcfg, start=start, end=end, tf=tf)


def _work(sp):
    try:
        _, rep = evaluate(_G["panel"], sp, _G["ext"], _G["pcfg"], _G["start"], _G["end"], _G["tf"])
        return sp, rep
    except MissingData:
        return sp, None


def run_stage_a(panel_full, ext, grid, pcfg, tf, start=TRAIN_START, end=TRAIN_END, resume=True, verbose=True, jobs=1):
    """Stage A: development period only. Never touches >= 2026-01-01."""
    assert pd.Timestamp(end) <= TRAIN_END, "Stage A must not use validation data"
    todo = [sp for sp in grid
            if not any(k not in ext or ext[k].dropna().empty for k in sp.needs)
            and not (resume and already_done("A", sp, tf, pcfg, start, end))]
    _G.update(panel=panel_full, ext=ext, pcfg=pcfg, start=start, end=end, tf=tf)
    if jobs > 1:
        import multiprocessing as mp
        method = "fork" if "fork" in mp.get_all_start_methods() else "spawn"
        with mp.get_context(method).Pool(
            jobs, initializer=_init_worker, initargs=(panel_full, ext, pcfg, start, end, tf)
        ) as pool:
            it = pool.imap_unordered(_work, todo, chunksize=1)
            results = it
            n = _consume(results, stage="A", tf=tf, pcfg=pcfg, start=start, end=end, verbose=verbose)
    else:
        n = _consume(map(_work, todo), stage="A", tf=tf, pcfg=pcfg, start=start, end=end, verbose=verbose)
    return n


def _consume(results, stage, tf, pcfg, start, end, verbose):
    n = 0
    for sp, rep in results:
        if rep is None:
            continue
        log_experiment(stage, sp, tf, pcfg, start, end, rep); n += 1       # single writer -> no CSV races
        if verbose:
            print(f"[{stage} {tf}] {sp.name:62s} ret={rep['total_return']:+.1%} sortino={rep['sortino']:.2f} mdd={rep['max_dd']:.1%} trades={rep['n_trades']}", flush=True)
    return n


def pair_spec(spec_c: Spec | None, spec_e: Spec | None) -> Spec:
    return Spec("pair", (("crypto", spec_c.name if spec_c else "cash"), ("equity", spec_e.name if spec_e else "cash")),
                ("crypto", "equity"))


def evaluate_pair(panel_full, spec_c: Spec | None, spec_e: Spec | None, ext: dict, pcfg: PortfolioConfig, start, end):
    """Different strategy per pool (architecture in README section 3)."""
    p_end = panel_full.slice(None, end)
    t = pd.DataFrame(0, index=p_end.index, columns=p_end.columns, dtype="int8")
    s = pd.DataFrame(np.nan, index=p_end.index, columns=p_end.columns)
    for sp, k in ((spec_c, "crypto"), (spec_e, "equity")):
        if sp is not None and p_end.cols(k):
            tk, sk = build_targets(p_end, sp, ext, pcfg.allow_short, (k,))
            t = t + tk; s = s.fillna(sk)
    pw = p_end.slice(start, end)
    res = run_backtest(pw, t.loc[pw.index].astype("int8"), pcfg, s.loc[pw.index])
    rep = perf_report(res, panel_full.freq_min, pcfg.capital)
    rep.update(rolling_window_report(res.curve["equity_total"], 14))
    return res, rep
