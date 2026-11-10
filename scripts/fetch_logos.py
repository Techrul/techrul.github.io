#!/usr/bin/env python3
"""Team logos for the CS2 pages, from Liquipedia: small copies kept in data/cs2/logos/ and served with the site.

    python3 scripts/fetch_logos.py --data data/cs2 [--max-requests 10] [--max-downloads 300]

1. Which organisations: every team name in the match data, most active in the last two years first.
2. Their logo files: Liquipedia's API ("team" datapoint), 40 names per request, within a small request budget of its
   own; names asked about are remembered, and asked again after 30 days (logos change now and then).
3. The images: the icon-only ("textless") logo, light and dark versions, as 64px thumbnails from Liquipedia's file
   server, one a second, at most --max-downloads a run. A logo is downloaded again only when its file changes.

Logos are the teams' trademarks; Liquipedia hosts them under fair use and the site shows them, small, to identify
teams, with Liquipedia credited. index.json: {org slug: {"name", "light": file, "dark": file or null, "src": url,
"checked": date}}; light and dark are the same file when a logo has one version for both.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_api  # noqa: E402
from cs2_adapter import org_slug  # noqa: E402

WIKI = "counterstrike"
SIZE = 64
TIER_WEIGHT = {"1": 20, "2": 8, "3": 3}
BATCH = 40
RECHECK_DAYS = 30
UA = "techrul.github.io rankings (https://github.com/Techrul/techrul.github.io)"


def thumb(url, size=SIZE):
    """A Liquipedia thumbnail URL at another width: .../thumb/a/ab/File.png/400px-File.png -> .../64px-File.png"""
    return re.sub(r"/\d+px-([^/]+)$", rf"/{size}px-\1", url or "") if url else None


def wanted_names(data_dir, today, min_matches=15):
    """Team names with min_matches+ in the match files: busiest at big events in the last two years first."""
    recent, ever = Counter(), Counter()
    since = (today - timedelta(days=730)).isoformat()
    for path in sorted(glob.glob(os.path.join(data_dir, "matches", "*.jsonl"))):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                m = json.loads(line)
                w = TIER_WEIGHT.get(m.get("tier"), 1)  # bigger events first: their teams are the ones people look at
                for t in m.get("teams", []):
                    n = t.get("name")
                    if n and n.upper() != "TBD":
                        ever[n] += 1
                        if m.get("date", "") >= since:
                            recent[n] += w
    return sorted((n for n in ever if ever[n] >= min_matches), key=lambda n: (-recent[n], -ever[n], n))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cs2")
    ap.add_argument("--max-requests", type=int, default=10)
    ap.add_argument("--max-downloads", type=int, default=300)
    ap.add_argument("--min-matches", type=int, default=15, help="skip teams with fewer matches in the data")
    args = ap.parse_args()
    out = os.path.join(args.data, "logos")
    os.makedirs(out, exist_ok=True)
    idx_path, asked_path = os.path.join(out, "index.json"), os.path.join(out, "asked.json")
    index = json.load(open(idx_path)) if os.path.exists(idx_path) else {}
    asked = json.load(open(asked_path)) if os.path.exists(asked_path) else {}  # name -> date last asked
    today = datetime.now(timezone.utc).date()
    stale = (today - timedelta(days=RECHECK_DAYS)).isoformat()

    names = [n for n in wanted_names(args.data, today, args.min_matches) if not re.search(r"[\[\]|{}]", n)]
    todo = [n for n in names if asked.get(n, "") < stale]
    client = lp_api.Client(WIKI, max_requests=args.max_requests, per_hour=45, max_seconds=240)
    found = 0
    try:
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            cond = " OR ".join(f"[[name::{n}]]" for n in batch)
            rows = client.get("team", conditions=cond, limit=BATCH * 2,
                              query="name,pagename,textlesslogourl,textlesslogodarkurl,logourl,logodarkurl")
            for r in rows:
                light = r.get("textlesslogourl") or r.get("logourl")
                dark = r.get("textlesslogodarkurl") or r.get("logodarkurl") or light
                if not light:
                    continue
                slug = org_slug(r["name"])
                old = index.get(slug, {})
                index[slug] = {**old, "name": r["name"], "src": light, "src_dark": dark}
                found += 1
            for n in batch:
                asked[n] = today.isoformat()
    except (lp_api.BudgetUsed, lp_api.StopRun) as e:
        print(f"logos: stopped asking ({e}); the next run carries on")

    # download what's new or changed, most active teams first
    order = {org_slug(n): k for k, n in enumerate(names)}
    need = [s for s in sorted(index, key=lambda s: order.get(s, 1e9))
            if index[s].get("got") != index[s]["src"] + "|" + index[s]["src_dark"]]
    n_dl = 0
    for slug in need:
        if n_dl >= args.max_downloads:
            break
        e = index[slug]
        files = {}
        try:
            for kind, url in (("light", e["src"]), ("dark", e["src_dark"])):
                if kind == "dark" and url == e["src"]:
                    files["dark"] = files["light"]
                    continue
                req = urllib.request.Request(thumb(url), headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read()
                n_dl += 1
                time.sleep(1)
                fname = f"{slug}{'' if kind == 'light' else '-dark'}.png"
                with open(os.path.join(out, fname), "wb") as fh:
                    fh.write(body)
                files[kind] = fname
        except Exception as ex:  # one missing logo shouldn't stop the rest
            print(f"  logo for {e['name']}: {ex}")
            continue
        e.update({"light": files["light"], "dark": files["dark"] if files["dark"] != files["light"] else None,
                  "got": e["src"] + "|" + e["src_dark"], "checked": today.isoformat()})
    with open(idx_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=0, sort_keys=True)
    with open(asked_path, "w", encoding="utf-8") as fh:
        json.dump(asked, fh, ensure_ascii=False, indent=0, sort_keys=True)
    have = sum(1 for e in index.values() if e.get("light"))
    msg = (f"{client.sent} requests, {found} logos found, {n_dl} images downloaded; {have} teams have a logo, "
           f"{len([n for n in names if asked.get(n, '') < stale])} names still to ask about")
    print("logos:", msg)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::notice title=Team logos::{msg}")


if __name__ == "__main__":
    main()
