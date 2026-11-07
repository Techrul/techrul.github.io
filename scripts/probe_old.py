"""One-off: what does ESPN's ATP ranking feed hold? Prints ::notice lines."""
import json, urllib.request
def note(t, s): print(f"::notice title={t}::{s}", flush=True)
def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "techrul.github.io rankings (github.com/Techrul/techrul.github.io)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")
try:
    d = json.loads(get("https://site.api.espn.com/apis/site/v2/sports/tennis/atp/rankings"))
    for rk in d.get("rankings", [])[:2]:
        ranks = rk.get("ranks", [])
        meta = {k: v for k, v in rk.items() if not isinstance(v, (list, dict))}
        note("espn ranking", f"{meta}; {len(ranks)} entries; keys of an entry {list(ranks[0]) if ranks else None}")
        for e in ranks[:3] + ranks[-1:]:
            a = e.get("athlete", {})
            note("espn entry", json.dumps({k: v for k, v in e.items() if k != "athlete"})[:300] + " | athlete " + json.dumps({k: a.get(k) for k in ("id", "displayName", "citizenshipCountry", "flag")})[:250])
    note("espn available", json.dumps(d.get("availableRankings"))[:500])
except Exception as e:
    note("espn", f"failed: {e}")
try:
    t = get("https://app.atptour.com/api/v2/gateway/rankings/singles?fromRank=1&toRank=200")
    note("atp-app", t[:400])
except Exception as e:
    note("atp-app", f"failed: {e}")
