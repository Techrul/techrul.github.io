#!/usr/bin/env python3
"""One-off check of what Liquipedia's API returns for CS2, before the real fetcher is built (see CS2_PLAN.md).

    env LIQUIPEDIA_API_KEY=... CONTACT_EMAIL=you@example.com python3 scripts/cs2_probe.py

Makes at most MAX_REQUESTS requests (the LiquipediaDB limit is 60 per hour), saves every response under
data/cs2/probe/ (not committed) and prints answers to the plan's open questions:
  - which fields mark Valve-ranked events (publishertier?),
  - whether matches list five players per side,
  - whether placements carry prize money,
  - how many matches a month each tier has (for the request budget).
"""
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

BASE = "https://api.liquipedia.net/api/v3/"
WIKI = "counterstrike"
MAX_REQUESTS = 6
OUT = os.path.join("data", "cs2", "probe")

_count = 0


def get(datapoint, **params):
    """One API request. Returns the list of records. Stops the script rather than exceed MAX_REQUESTS."""
    global _count
    if _count >= MAX_REQUESTS:
        sys.exit(f"stopped: request cap of {MAX_REQUESTS} reached")
    key = os.environ.get("LIQUIPEDIA_API_KEY")
    if not key:
        sys.exit("set LIQUIPEDIA_API_KEY first")
    contact = os.environ.get("CONTACT_EMAIL", "")
    params = {"wiki": WIKI, **params}
    url = BASE + datapoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Apikey {key}",
        "Accept-Encoding": "gzip",
        "User-Agent": "techrul.github.io rankings (https://github.com/Techrul/techrul.github.io"
                      + (f"; {contact}" if contact else "") + ")",
    })
    _count += 1
    print(f"[{_count}/{MAX_REQUESTS}] {datapoint} {params.get('conditions', '')}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
    except urllib.error.HTTPError as e:
        body = e.read()
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        text = body.decode("utf-8", "replace")
        try:
            text = json.dumps(json.loads(text), indent=1)
        except ValueError:
            pass
        wanted = ("retry-after", "x-ratelimit", "ratelimit", "cf-", "server", "date", "content-type")
        heads = {k: v for k, v in e.headers.items() if k.lower().startswith(wanted)}
        sys.exit(f"HTTP {e.code} from Liquipedia (no retry).\nheaders: {json.dumps(heads, indent=1)}\nbody:\n{text[:3000]}")
    data = json.loads(body)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"{_count:02d}_{datapoint}.json"), "w", encoding="utf-8") as fh:
        json.dump({"url": url, "response": data}, fh, ensure_ascii=False, indent=1)
    if isinstance(data, dict) and data.get("error"):
        sys.exit(f"API error: {data['error']}")
    for w in (data.get("warning") or []) if isinstance(data, dict) else []:
        print("  warning:", w)
    time.sleep(2)  # be gentle even within the cap
    return data.get("result", []) if isinstance(data, dict) else data


def players_per_side(match):
    return [len(o.get("match2players") or []) for o in match.get("match2opponents") or []]


def summarise_matches(matches, label):
    print(f"\n{label}: {len(matches)} matches")
    if not matches:
        return
    sides = Counter(tuple(players_per_side(m)) for m in matches)
    print("  players per side (side A, side B):", dict(sides.most_common(6)))
    full = sum(1 for m in matches if players_per_side(m) == [5, 5])
    print(f"  with exactly 5 + 5 players: {full} of {len(matches)}")
    for field in ("liquipediatier", "liquipediatiertype", "publishertier", "type", "bestof", "resulttype", "walkover"):
        print(f"  {field}: {dict(Counter(str(m.get(field)) for m in matches).most_common(8))}")
    ext = Counter(k for m in matches for k in (m.get("extradata") or {}))
    print("  extradata keys:", dict(ext.most_common(15)))


def main():
    today = datetime.now(timezone.utc).date()
    month_ago = (today - timedelta(days=30)).isoformat()

    # 1. Recent finished tier-1 matches, every field: what does a full record look like?
    top = get("match", conditions=f"[[liquipediatier::1]] AND [[finished::1]] AND [[date::>{month_ago}]]",
              limit=20, order="date DESC")
    summarise_matches(top, "Tier 1, last 30 days (full records)")
    if top:
        print("  match fields:", sorted(top[0].keys()))
        opp = (top[0].get("match2opponents") or [{}])[0]
        print("  opponent fields:", sorted(opp.keys()))
        print("  player fields:", sorted(((opp.get("match2players") or [{}])[0]).keys()))

    # 2. Every finished match in the last 30 days, few fields: volume per tier and lineup coverage.
    recent = get("match", conditions=f"[[finished::1]] AND [[date::>{month_ago}]]",
                 query="match2id,date,liquipediatier,liquipediatiertype,publishertier,type,walkover,match2opponents",
                 limit=1000, order="date DESC")
    summarise_matches(recent, "All tiers, last 30 days")
    if len(recent) == 1000:
        print("  (hit the 1,000 row page size: more than that per month)")
    tiers = Counter((str(m.get("liquipediatier")), str(m.get("liquipediatiertype"))) for m in recent)
    print("  matches per (tier, tier type):", dict(tiers.most_common(20)))

    # 3. Recent tier 1-2 tournaments, every field: prize pool, LAN/online, Valve status.
    # (finished ones only: future events have placeholder pages with no prize pool yet)
    tours = get("tournament", conditions=f"([[liquipediatier::1]] OR [[liquipediatier::2]]) AND [[enddate::>{month_ago}]]"
                                         f" AND [[enddate::<{today.isoformat()}]]",
                limit=20, order="enddate DESC")
    print(f"\nTournaments: {len(tours)}")
    if tours:
        print("  tournament fields:", sorted(tours[0].keys()))
        for t in tours[:8]:
            print(f"  {t.get('name')!s:45} tier {t.get('liquipediatier')} type {t.get('type')} "
                  f"pool {t.get('prizepool')} publishertier {t.get('publishertier')!r}")
        ext = Counter(k for t in tours for k in (t.get("extradata") or {}))
        print("  extradata keys:", dict(ext.most_common(15)))

    # 4. Placements of one finished tournament: prize money per team?
    done = [t for t in tours if t.get("pagename") and str(t.get("enddate", "9999")) < today.isoformat()]
    places = []
    if done:
        page = done[0]["pagename"]
        places = get("placement", conditions=f"[[pagename::{page}]]", limit=50)
        print(f"\nPlacements for {page}: {len(places)}")
        if places:
            print("  placement fields:", sorted(places[0].keys()))
            for p in places[:8]:
                print(f"  {p.get('placement')!s:6} {p.get('opponentname')!s:25} prize {p.get('prizemoney')} "
                      f"players {len(p.get('opponentplayers') or {})}")
            print("  placements with prize money:", sum(1 for p in places if p.get("prizemoney")), "of", len(places))

    # One example of each record type, so the adapter can be written against real data.
    print("\n--- Example records (data from Liquipedia, CC BY-SA 3.0, https://liquipedia.net/) ---")
    if top:
        m = dict(top[0])
        if m.get("match2games"):
            m["match2games"] = m["match2games"][:1] + [f"... {len(top[0]['match2games']) - 1} more games"]
        print("match:", json.dumps(m, ensure_ascii=False, indent=1))
    if tours:
        print("tournament:", json.dumps(tours[0], ensure_ascii=False, indent=1))
    if done and places:
        print("placement:", json.dumps(places[0], ensure_ascii=False, indent=1))

    print(f"\nDone: {_count} requests. Raw responses in {OUT}/")


if __name__ == "__main__":
    main()
