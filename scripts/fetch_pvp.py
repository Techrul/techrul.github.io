#!/usr/bin/env python3
"""Fetch one player's Minecraft PvP stats from PVPHQ (JSON API) and mcpvp.com (profile page) for the /pvp/ page.

    python3 scripts/fetch_pvp.py --player Techrul --keep data/pvp/techrul.json --out docs/pvp/data.json

About ten requests a run. Neither site publishes an API: PVPHQ's site reads its own /api/v1 JSON (which refuses
cross-site browser requests, so the page can't call it live), and mcpvp renders tiers and matches into the profile
page's HTML. If a site is down or changes shape, that source keeps its last good copy from --keep, so the page
never goes blank. mcpvp tier changes are logged over time in "mcpvp_history".
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "techrul.github.io personal stats page (github.com/Techrul)"
HQ = "https://pvphq.com/api/v1"
MCPVP = "https://www.mcpvp.com"


def get(url, as_json=True):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json" if as_json else "text/html"})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read().decode("utf-8", "replace")
    time.sleep(0.5)  # gentle
    return json.loads(body) if as_json else body


def fetch_pvphq(name):
    p = get(f"{HQ}/players/by-name/{urllib.parse.quote(name)}")
    uid = p["uuid"]
    matches, page = [], 0
    while page < 4:  # up to 200 matches
        m = get(f"{HQ}/players/{uid}/matches?page={page}&size=50")
        matches += m.get("entries", [])
        if not m.get("page", {}).get("hasNext"):
            break
        page += 1
    history, breakdown = {}, {}
    for k in p.get("ranked", []):
        if k.get("gamesPlayed"):
            g = k["gametype"]
            history[g] = get(f"{HQ}/players/{uid}/rating-history/{g}?limit=200").get("points", [])
            if not k.get("unranked"):
                breakdown[g] = get(f"{HQ}/players/{uid}/breakdown/{g}?limit=50").get("vsTier", [])
    rivals = get(f"{HQ}/players/{uid}/rivals?limit=10").get("rivals", [])
    keep = ("rating", "peakRating", "peakTier", "peakTierColor", "rd", "wins", "losses", "gamesPlayed", "winRate", "tier",
            "tierColor", "tierProgress", "trTarget", "nextTier", "nextTierColor", "unranked", "placementGames",
            "placementTarget", "lastPlayedAt", "gametypeName")
    return {
        "uuid": uid, "name": p["name"], "region": p.get("closestRegion"), "stats": p.get("stats", {}),
        "points": p.get("overall", {}).get("points"),
        "kits": {k["gametype"]: {f: k.get(f) for f in keep if f in k} for k in p.get("ranked", [])},
        "best": p.get("best"),
        "history": {g: [[pt["playedAt"], pt["rating"], pt.get("tier"), pt.get("tierColor")] for pt in pts] for g, pts in history.items()},
        "breakdown": breakdown,
        "rivals": [{f: r.get(f) for f in ("name", "wins", "losses", "games")} for r in rivals],
        "matches": [[m["createdAt"], m.get("gametypeName") or m.get("gametype"), m.get("opponentName"), bool(m.get("won")),
                     bool(m.get("ranked"))] for m in matches],
        "url": f"https://pvphq.com/player/{urllib.parse.quote(p['name'])}",
    }


def _text(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).split()


def parse_mcpvp(page, name):
    body = page[page.find("<body"):]
    body = re.sub(r"<script.*?</script>", "", body, flags=re.S)
    kits = []
    for m in re.finditer(r'<button class="ranking-kit"[^>]*data-kit="([^"]+)"[^>]*data-label="([^"]+)".*?data-tier-code="([^"]+)"', body, re.S):
        kits.append({"key": m.group(1), "label": html.unescape(m.group(2)), "tier": m.group(3)})
    overall = re.search(r'class="overall-tier[^"]*"[^>]*data-tier-code="([^"]+)"', body)
    pts = re.search(r'points-value">\s*([\d.]+)\s*</span>\s*/\s*<span class="game-number">\s*([\d.]+)', body)
    matches = []
    grid = body[body.find('class="matches-grid"'):]
    end = grid.find('class="matches-list')  # the list view repeats the same matches
    grid = grid[:end] if end > 0 else grid
    for part in re.split(r'(?=<div class="match-card[ "])', grid)[1:]:
        head = re.match(r'<div class="match-card\s*(win|loss|draw)?[^"]*"(?:\s+data-history-category="([^"]*)")?', part)
        kit = re.search(r'match-card-kit">\s*<img[^>]*alt="([^"]*)"', part)
        where = re.search(r'match-card-map">([^<]*)<', part)
        score = re.search(r'match-card-score">\s*([^<]*?)\s*<', part)
        players = re.findall(r'class="match-card-player[^"]*">([^<]+)</a>', part)
        if not (head and score and players):
            continue
        opp = next((p.strip() for p in players if p.strip().lower() != name.lower()), None)
        sc = score.group(1)
        if players[0].strip().lower() != name.lower() and re.fullmatch(r"\d+\s*-\s*\d+", sc):  # score from my side
            a, b = re.split(r"\s*-\s*", sc)
            sc = f"{b} - {a}"
        matches.append([head.group(1) or "", html.unescape(kit.group(1)) if kit else None,
                        html.unescape(where.group(1).strip()) if where else None, sc, opp, head.group(2) or ""])
    if not kits and not matches:
        raise ValueError("no tiers or matches found on the mcpvp profile page (layout changed?)")
    return {
        "name": name, "overall": overall.group(1) if overall else None,
        "points": [float(pts.group(1)), float(pts.group(2))] if pts else None,
        "kits": kits, "matches": matches[:40], "url": f"https://www.mcpvp.com/@{urllib.parse.quote(name)}",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--player", default="Techrul")
    ap.add_argument("--keep", default="data/pvp/techrul.json", help="last good data (committed on main)")
    ap.add_argument("--out", default="docs/pvp/data.json")
    args = ap.parse_args()
    old = {}
    if os.path.exists(args.keep):
        with open(args.keep) as fh:
            old = json.load(fh)
    now = int(time.time())
    data = {"player": args.player, "updated": old.get("updated", {}), "mcpvp_history": old.get("mcpvp_history", [])}
    ok = 0
    for src, fn in (("pvphq", lambda: fetch_pvphq(args.player)),
                    ("mcpvp", lambda: parse_mcpvp(get(f"{MCPVP}/@{urllib.parse.quote(args.player)}", as_json=False), args.player))):
        try:
            data[src] = fn()
            data["updated"][src] = now
            ok += 1
            print(f"{src}: ok")
        except Exception as e:  # keep the last good copy
            print(f"::warning::{src}: {e!r}; keeping the last good copy", file=sys.stderr)
            if src in old:
                data[src] = old[src]
    mc = data.get("mcpvp")
    if mc and data["updated"].get("mcpvp") == now:
        snap = {"overall": mc["overall"], "points": mc["points"], "kits": {k["label"]: k["tier"] for k in mc["kits"]}}
        hist = data["mcpvp_history"]
        if not hist or {k: hist[-1].get(k) for k in snap} != snap:
            hist.append({"t": now, **snap})
    for path in (args.keep, args.out):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh, separators=(",", ":"))
    hq = data.get("pvphq") or {}
    print(f"::notice::PvP stats: PVPHQ {hq.get('best', {}).get('tier')} {hq.get('best', {}).get('gametypeName')}, "
          f"mcpvp {(mc or {}).get('overall')} ({len((mc or {}).get('kits', []))} kits), {ok}/2 sources fresh")
    return 0 if (data.get("pvphq") or data.get("mcpvp")) else 1


if __name__ == "__main__":
    sys.exit(main())
