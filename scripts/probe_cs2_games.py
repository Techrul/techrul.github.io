#!/usr/bin/env python3
"""One-off: fetch ONE recent S-tier match with its per-map data and report which fields Liquipedia fills.
Prints GitHub annotations (readable from the run page). One API request."""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_api  # noqa: E402


def note(title, msg):
    print(f"::notice title={title}::{msg[:3500]}")


def shape(v, depth=0):
    if isinstance(v, dict):
        return {k: shape(x, depth + 1) for k, x in list(v.items())[:40]} if depth < 4 else "{...}"
    if isinstance(v, list):
        return [shape(v[0], depth + 1), f"...{len(v)} items"] if v else []
    return v if not isinstance(v, str) or len(v) < 60 else v[:60] + "…"


c = lp_api.Client("counterstrike", max_requests=1, per_hour=45, max_seconds=240)
rows = c.get("match", conditions="[[liquipediatier::1]] AND [[finished::1]] AND [[date::>2026-10-01]] AND [[liquipediatiertype::!Showmatch]]",
             query="match2id,pagename,date,match2opponents,match2games", order="date DESC", limit=1)
m = rows[0]
names = [o.get("name") for o in m.get("match2opponents") or []]
games = m.get("match2games") or []
note("Match", f"{m.get('pagename')} {m.get('date')}: {' vs '.join(map(str, names))}, {len(games)} games")
if games:
    g = games[0]
    note("Game fields", ", ".join(f"{k}={'(empty)' if v in ('', [], {}, None) else type(v).__name__}" for k, v in g.items()))
    for k in ("extradata", "scores", "opponents", "participants"):
        if g.get(k):
            note(f"game.{k}", json.dumps(shape(g[k]), ensure_ascii=False))
    played = [x for x in games if x.get("winner")]
    filled = Counter(k for x in played for k, v in x.items() if v not in ("", [], {}, None))
    note("Filled across played maps", f"{len(played)} maps: " + ", ".join(f"{k} {n}" for k, n in filled.most_common()))
op = (m.get("match2opponents") or [{}])[0]
pl = (op.get("match2players") or [{}])[0]
note("Opponent player fields", json.dumps(shape(pl), ensure_ascii=False))
note("Opponent extradata", json.dumps(shape(op.get("extradata")), ensure_ascii=False))
