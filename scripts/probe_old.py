"""One-off: per-map data in Liquipedia's match2games (rounds, halves, sides). Prints ::notice lines."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_api, fetch_cs2 as f
def note(t, s): print(f"::notice title={t}::{s}", flush=True)
c = lp_api.Client(f.WIKI, max_requests=3, per_hour=45, max_seconds=240)
for when, label in (("[[date::>2026-11-01]] AND [[date::<2026-11-11]]", "2026"), ("[[date::>2018-09-20]] AND [[date::<2018-09-24]]", "2018")):
    try:
        rows = c.get("match", conditions=f"[[finished::1]] AND [[liquipediatier::1]] AND {when}", limit=2,
                     query="match2id,date,tournament,match2opponents,match2games")
        m = rows[0]
        names = [o.get("name") for o in m.get("match2opponents", [])]
        g = (m.get("match2games") or [{}])[0]
        note(f"{label} match", f"{m.get('tournament')} {m.get('date')} {names}; games {len(m.get('match2games') or [])}; game keys {sorted(g)}")
        note(f"{label} game", json.dumps({k: g.get(k) for k in ("map", "scores", "winner", "opponents", "extradata", "length", "mode")})[:1500])
    except Exception as e:
        note(label, f"failed: {e}")
note("requests", str(c.sent))
