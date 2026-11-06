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

# ---- where could the official ATP ranking come from now? (TML's weekly files stopped in Jan 2026)
import json as _j, urllib.request as _u
for name, url in (("espn", "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/rankings"),
                  ("espn-core", "https://sports.core.api.espn.com/v2/sports/tennis/leagues/atp/rankings"),
                  ("atptour", "https://www.atptour.com/en/rankings/singles?rankRange=1-200"),
                  ("atp-app", "https://app.atptour.com/api/v2/gateway/rankings/singles?fromRank=1&toRank=200")):
    try:
        req = _u.Request(url, headers={"User-Agent": "techrul.github.io rankings (github.com/Techrul/techrul.github.io)", "Accept": "application/json,text/html"})
        with _u.urlopen(req, timeout=30) as r:
            body = r.read()
        txt = body.decode("utf-8", "replace")
        try:
            d = _j.loads(txt)
            summ = f"JSON keys {list(d)[:8]}; " + txt[:600].replace("\n", " ")
        except ValueError:
            summ = f"HTML {len(txt)} bytes; has 'Sinner': {'Sinner' in txt}; " + txt[:200].replace("\n", " ")
        note(f"source {name}", f"HTTP {r.status}; {summ}")
    except Exception as e:
        note(f"source {name}", f"failed: {e}")
