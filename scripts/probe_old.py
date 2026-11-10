"""One-off: what does ESPN's ATP scoreboard hold (upcoming matches)? Prints ::notice lines."""
import json, urllib.request
def note(t, s): print(f"::notice title={t}::{s}", flush=True)
def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "techrul.github.io rankings (github.com/Techrul/techrul.github.io)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))
for url in ("https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
            "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard?dates=20261115"):
    try:
        d = get(url)
        evs = d.get("events", [])
        note("scoreboard", f"{url[-30:]}: keys {list(d)}; {len(evs)} events: " + "; ".join(f"{e.get('name')} {e.get('date')} {e.get('status',{}).get('type',{}).get('name')}" for e in evs[:4]))
        for e in evs[:2]:
            grs = e.get("groupings") or []
            note("event", f"{e.get('name')} keys {list(e)}; groupings {len(grs)}: " + "; ".join(f"{g.get('grouping',{}).get('displayName')} {len(g.get('competitions',[]))}" for g in grs[:6]))
            for g in grs[:6]:
                if "Men" in json.dumps(g.get("grouping", {})):
                    cs = g.get("competitions", [])
                    sched = [c for c in cs if (c.get("status", {}).get("type", {}).get("state") == "pre")]
                    note("men's singles", f"{len(cs)} matches, {len(sched)} scheduled; first scheduled: " + json.dumps(sched[:1])[:900])
                    break
    except Exception as e:
        note("scoreboard", f"{url}: failed {e}")
