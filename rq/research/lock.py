"""Anti-overfitting guard for Stage B (brief section 7).

* `freeze` writes the shortlist (<= max_n strategies) with a hash and timestamp BEFORE any 2026 data is touched.
* `guard` refuses to evaluate anything on the validation window that is not in the frozen shortlist, and
  records every validation evaluation in an append-only ledger that goes into the repo for the judges.
"""
from __future__ import annotations
import hashlib, json, time
from pathlib import Path

SHORTLIST = Path("results/shortlist.json")
LEDGER = Path("results/validation_ledger.jsonl")


def freeze(names: list[str], max_n: int = 8, note: str = "") -> dict:
    if SHORTLIST.exists():
        raise RuntimeError("shortlist already frozen - create a NEW file/branch if you really must (and document why)")
    if len(names) > max_n:
        raise ValueError(f"shortlist too large ({len(names)} > {max_n}) - that's selection on the validation set")
    d = {"frozen_at": time.strftime("%Y-%m-%d %H:%M:%S"), "names": sorted(names), "note": note}
    d["sha1"] = hashlib.sha1(json.dumps(d["names"]).encode()).hexdigest()
    SHORTLIST.parent.mkdir(parents=True, exist_ok=True)
    SHORTLIST.write_text(json.dumps(d, indent=1))
    return d


def guard(spec_name: str, tf: str, pcfg_tag: str) -> None:
    if not SHORTLIST.exists():
        raise RuntimeError("no frozen shortlist: run `freeze` after Stage A/C and before any validation run")
    d = json.loads(SHORTLIST.read_text())
    if spec_name not in d["names"]:
        raise PermissionError(f"{spec_name} is not in the frozen shortlist -> refusing to look at validation data")
    with open(LEDGER, "a") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "strategy": spec_name, "tf": tf, "sizing": pcfg_tag,
                            "shortlist_sha1": d["sha1"]}) + "\n")
