"""One-off: how complete is Liquipedia's match data for the CS:GO years? Prints ::notice lines."""
import collections, os, sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_api, fetch_cs2 as f

c = lp_api.Client(f.WIKI, max_requests=8, per_hour=45, max_seconds=240)
def note(t, s): print(f"::notice title={t}::{s}", flush=True)
for first, nxt in ((date(2018, 9, 1), date(2018, 10, 1)), (date(2016, 6, 1), date(2016, 7, 1))):
    try:
        rows = c.get_all("match", f"[[finished::1]] AND {f.NOT_SHOWMATCH} AND {f.window('date', first, nxt)}", query=f.MATCH_FIELDS)
    except lp_api.StopRun as e:
        note(f"{first:%Y-%m}", f"stopped: {e}"); break
    ms = [f.compact_match(m, {}) for m in rows]
    tiers = collections.Counter(m["tier"] for m in ms)
    full = collections.Counter()
    for m in ms:
        ok = len(m["teams"]) == 2 and all(len(t["players"]) >= 5 for t in m["teams"])
        full[(m["tier"], ok)] += 1
    by_tier = "; ".join(f"tier {t}: {n} matches, {full[(t, True)]} with 5v5 lineups" for t, n in sorted(tiers.items()))
    note(f"{first:%Y-%m} matches", f"{len(ms)} total ({c.sent} requests so far). {by_tier}")
    ast = [m for m in ms if any(t["name"].lower() == "astralis" for t in m["teams"])]
    sample = "; ".join(f'{m["date"]} {m["event_name"]}: ' + " vs ".join(f'{t["name"]} {t["score"]} [{",".join(t["players"])}]' for t in m["teams"]) for m in ast[:3])
    note(f"{first:%Y-%m} Astralis", f"{len(ast)} matches. {sample}")
    try:
        ps = c.get_all("placement", f"[[prizemoney::>0]] AND {f.window('date', first, nxt)}", query=f.PLACEMENT_FIELDS)
        note(f"{first:%Y-%m} placings", f"{len(ps)} placings with prize money across {len({p['pagename'] for p in ps})} events")
    except lp_api.StopRun as e:
        note(f"{first:%Y-%m}", f"stopped: {e}"); break
note("probe", f"{c.sent} requests used")
