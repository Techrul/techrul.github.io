#!/usr/bin/env python3
"""Player photos from Wikidata and Wikimedia Commons, with credits. Runs in the daily workflow:

    python3 scripts/player_photos.py --players docs/tennis/data/players_index.json --out docs/tennis

1. One Wikidata query: every item with an ATP player ID (property P536) and an image (P18). The match
   data uses ATP's own player codes (e.g. S0AG), so photos are matched by ID, never by name.
2. Keeps players who have a profile on the site, and checks each file's licence on Commons: only
   public domain, CC0, CC BY and CC BY-SA.
3. Downloads a small version once (cached in data/player_images/, re-downloaded if Wikidata's photo
   changes) and writes <out>/data/player_photos.json with the photographer, licence and source page.

To hide or swap a photo, add the player to data/player_photos.json in the repo, which always wins:
    {"S0AG": {"file": null}}   or   {"S0AG": {"file": "File:Some other photo.jpg"}}
Never fails the build: on any error the previous photos stay as they were.
NOTE: written without access to Wikidata/Commons from the build sandbox; check the first run's log.
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trophies import Commons, free_licence  # noqa: E402  same Commons client and licence rules

SPARQL = "https://query.wikidata.org/sparql"
QUERY = "SELECT ?atp ?image WHERE { ?item wdt:P536 ?atp ; wdt:P18 ?image . }"


def wikidata_photos(ua):
    """{ATP id (upper case): "File:Name.jpg"} for every person on Wikidata with an ATP ID and an image."""
    url = SPARQL + "?" + urllib.parse.urlencode({"query": QUERY, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return parse_sparql(data)


def parse_sparql(data):
    out = {}
    for row in data.get("results", {}).get("bindings", []):
        atp = row.get("atp", {}).get("value", "").strip().upper()
        img = row.get("image", {}).get("value", "")
        # images come back as http://commons.wikimedia.org/wiki/Special:FilePath/Some%20Name.jpg
        name = urllib.parse.unquote(img.rsplit("/", 1)[-1]).replace("_", " ") if img else ""
        if atp and name and atp not in out:  # first image if a player has several
            out[atp] = "File:" + name
    return out


def build(client, wanted, chosen, cache_dir, out_dir, fetch, limit=250):
    """wanted: {player id: "File:..."}; chosen: overrides from data/player_photos.json."""
    picks = dict(wanted)
    for pid, v in chosen.items():
        if v.get("file"):
            picks[pid] = v["file"]
        else:
            picks.pop(pid, None)
    info = client.info(sorted(set(picks.values())), width=240) if picks else {}
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "players-photos"), exist_ok=True)
    credits, downloads = {}, 0
    for pid in sorted(picks):
        meta = info.get(picks[pid])
        if not meta or not free_licence(meta["licence"]) or not (meta["mime"] or "").startswith("image/"):
            continue
        ext = os.path.splitext(urllib.parse.urlparse(meta["thumb"]).path)[1].lower()
        ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
        fname = pid.lower() + ext
        cached, stamp = os.path.join(cache_dir, fname), os.path.join(cache_dir, fname + ".src")
        fresh = os.path.exists(cached) and os.path.exists(stamp) and open(stamp).read() == meta["thumb"]
        if not fresh:
            if downloads >= limit:
                continue  # the rest next run, to keep each run polite and short
            try:
                fetch(meta["thumb"], cached)
            except Exception as exc:
                print(f"WARN photo for {pid}: {exc}", file=sys.stderr)
                continue
            with open(stamp, "w") as fh:
                fh.write(meta["thumb"])
            downloads += 1
        shutil.copyfile(cached, os.path.join(out_dir, "players-photos", fname))
        credits[pid] = {"src": "players-photos/" + fname, "author": meta["author"], "licence": meta["licence"],
                        "licence_url": meta["licence_url"], "page": meta["page"]}
    os.makedirs(os.path.join(out_dir, "data"), exist_ok=True)
    with open(os.path.join(out_dir, "data", "player_photos.json"), "w", encoding="utf-8") as fh:
        json.dump(credits, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"player photos: {len(credits)} of {len(picks)} players with a Wikidata photo ({downloads} downloaded this run)")
    return credits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", default="docs/tennis/data/players_index.json")
    ap.add_argument("--choices", default="data/player_photos.json")
    ap.add_argument("--cache", default="data/player_images")
    ap.add_argument("--out", default="docs/tennis")
    ap.add_argument("--max-downloads", type=int, default=250)
    args = ap.parse_args()
    client = Commons(os.environ.get("CONTACT_EMAIL", "set-CONTACT_EMAIL"))
    try:
        with open(args.players, encoding="utf-8") as fh:
            ids = {p["id"].upper(): p["id"] for p in json.load(fh)}
        chosen = {}
        if os.path.exists(args.choices):
            with open(args.choices, encoding="utf-8") as fh:
                chosen = {k: v for k, v in json.load(fh).items() if k in ids.values()}
        found = wikidata_photos(client.ua)
        wanted = {ids[atp]: f for atp, f in found.items() if atp in ids}
        print(f"wikidata: {len(found)} people with an ATP ID and a photo, {len(wanted)} of them on this site")

        def fetch(url, dest):
            req = urllib.request.Request(url, headers={"User-Agent": client.ua})
            with urllib.request.urlopen(req, timeout=60) as resp, open(dest + ".part", "wb") as fh:
                fh.write(resp.read())
            os.replace(dest + ".part", dest)
            time.sleep(0.3)

        build(client, wanted, chosen, args.cache, args.out, fetch, args.max_downloads)
    except Exception as exc:
        print(f"WARN player photos skipped: {exc}", file=sys.stderr)
        path = os.path.join(args.out, "data", "player_photos.json")
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write("{}")


if __name__ == "__main__":
    main()
