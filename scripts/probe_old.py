"""One-off: team logos in Liquipedia's API (team datapoint). Prints ::notice lines."""
import json, os, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_api, fetch_cs2 as f
def note(t, s): print(f"::notice title={t}::{s}", flush=True)
c = lp_api.Client(f.WIKI, max_requests=3, per_hour=45, max_seconds=240)
try:
    rows = c.get("team", conditions="[[name::Team Vitality]] OR [[name::Team Spirit]] OR [[name::Legacy]]", limit=5)
    rows = rows.get("result", rows) if isinstance(rows, dict) else rows
    for r in rows[:3]:
        note("team", json.dumps({k: v for k, v in r.items() if "logo" in k.lower() or k in ("name", "pagename", "template", "textlesslogo")})[:900])
    if rows:
        note("team keys", ", ".join(sorted(rows[0].keys())))
    url = next((r.get(k) for r in rows for k in ("logourl", "logodarkurl") if r.get(k)), None)
    if url:
        req = urllib.request.Request(url, headers={"User-Agent": "techrul.github.io rankings (github.com/Techrul/techrul.github.io)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
        note("image", f"{url}: HTTP {resp.status}, {len(body)} bytes, {resp.headers.get('Content-Type')}")
except Exception as e:
    note("team", f"failed: {e}")
note("requests", str(c.sent))
