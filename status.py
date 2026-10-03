"""Read-only monitor: python status.py   (no API calls, files only)"""
import re, json, datetime as dt
from pathlib import Path

lines = Path("logs/bot.log").read_text(errors="ignore").splitlines() if Path("logs/bot.log").exists() else []
ts = lambda l: dt.datetime.strptime(l[:19], "%Y-%m-%d %H:%M:%S")
def last(pat):
    for l in reversed(lines):
        if re.search(pat, l): return l
    return None

now = dt.datetime.now()
hb = last(r"signal bar|before start_utc")
print("now (local)      :", now.strftime("%Y-%m-%d %H:%M:%S"))
if hb:
    age = (now - ts(hb)).total_seconds() / 60
    print("last heartbeat   : %s  (%.0f min ago) %s" % (hb[:19], age, "OK" if age < 40 else "*** STALE - bot may be dead ***"))
else:
    print("last heartbeat   : none")
print("last signal      :", (last(r"signal bar") or "none")[20:])
print("last equity line :", (last(r"INFO equity") or "none")[20:])
print("last entry order :", (last(r"entry order") or "none")[20:])
tail = lines[-400:]
fills = [l for l in tail if " filled " in l]
errs = [l for l in tail if "ERROR" in l or "cycle failed" in l]
warns = [l for l in tail if "WARNING" in l]
print("fills (last 400) : %d | errors: %d | warnings: %d" % (len(fills), len(errs), len(warns)))
for l in fills[-6:]: print("   ", l)
for l in errs[-5:]: print("   !!", l)
p = Path("state/ledger.json")
if p.exists():
    s = json.loads(p.read_text())
    print("ledger pool_cash :", round(s["pool_cash"]["crypto"], 2), "| peak:", s.get("peak"))
