#!/usr/bin/env python3
"""Freely licensed trophy photos from Wikimedia Commons, with credits.

Every build (the GitHub workflow runs this):

    python3 scripts/trophies.py --out docs/rankings/tennis

  downloads each photo listed in data/trophies.json once (cached in data/trophy_images/), copies it to
  <out>/trophies/ and writes <out>/data/trophies.json with the photographer, licence and source page.

Which photo belongs to which tournament is a fixed list in data/trophies.json, checked by a person.
An automatic search was tried and rejected: Commons file names cannot tell a tennis trophy from a
football cup or a war trophy in the same city, so most automatic picks were wrong.

To look for more (optional), on a machine that can reach Commons:

    env CONTACT_EMAIL=you@yourmail.com python3 scripts/trophies.py --find --tournaments docs/rankings/tennis/data/tournaments.json

  prints candidates (strict filter: the trophy's own name, or a tennis word plus the tournament) and
  their Commons pages. It does not change anything; copy a good one into data/trophies.json by hand.

Only public domain, CC0, CC BY and CC BY-SA photos are used; the licence is re-checked on every build.
"""
import argparse
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
TROPHY_WORDS = ("trophy", "trophies", "cup", "coupe", "trophée", "trophee", "trofeo", "pokal", "troféu", "trofeu")
# women's singles trophies of the Slams, which share search words with the men's
WOMENS = ("women", "ladies", "lady", "venus rosewater", "rosewater dish", "daphne akhurst", "suzanne lenglen", "wta")
# better search terms where the trophy has its own name
QUERIES = {
    "Australian Open": ["Norman Brookes Challenge Cup", "Australian Open trophy"],
    "Roland Garros": ["Coupe des Mousquetaires", "Roland Garros trophy", "French Open trophy"],
    "Wimbledon": ["Wimbledon gentlemen's singles trophy", "Wimbledon trophy"],
    "US Open": ["US Open tennis trophy", "US Open men's singles trophy"],
    "ATP Finals": ["ATP Finals trophy", "ATP World Tour Finals trophy"],
}
STOP = {"masters", "open", "the", "de", "tennis", "atp", "championships", "cup", "international"}


def free_licence(short):
    s = (short or "").strip().lower()
    if not s or "nc" in s.replace("-", " ").split() or "nd" in s.replace("-", " ").split():
        return False
    return s.startswith(("cc0", "public domain", "pd", "cc by", "cc-by", "attribution"))


def plain(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


class Commons:
    def __init__(self, contact, delay=1.0):
        self.ua = f"tennis-rankings-site/0.1 (non-commercial, open source; contact: {contact})"
        self.delay = delay

    def get(self, **params):
        params.update({"format": "json", "formatversion": "2", "maxlag": "5"})
        req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": self.ua})
        time.sleep(self.delay)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def search(self, query, limit=20):
        data = self.get(action="query", list="search", srsearch=query + " filetype:bitmap", srnamespace="6", srlimit=str(limit))
        return [h["title"] for h in data.get("query", {}).get("search", [])]

    def info(self, titles, width=500):
        """File title -> {url, thumb, page, licence, licence_url, author, width}; files that do not exist are left out."""
        out = {}
        for i in range(0, len(titles), 40):
            data = self.get(action="query", titles="|".join(titles[i:i + 40]), prop="imageinfo",
                            iiprop="url|extmetadata|size|mime", iiurlwidth=str(width))
            for page in data.get("query", {}).get("pages", []):
                ii = (page.get("imageinfo") or [None])[0]
                if not ii:
                    continue
                meta = ii.get("extmetadata", {})
                out[page["title"]] = {
                    "url": ii.get("url"), "thumb": ii.get("thumburl") or ii.get("url"), "page": ii.get("descriptionurl"),
                    "mime": ii.get("mime"), "width": ii.get("width", 0), "bytes": ii.get("size", 0),
                    "licence": plain(meta.get("LicenseShortName", {}).get("value")),
                    "licence_url": meta.get("LicenseUrl", {}).get("value"),
                    "author": plain(meta.get("Artist", {}).get("value")) or plain(meta.get("Credit", {}).get("value")) or "Unknown author",
                }
        return out


# Words that mean a file is about another sport or something else entirely
OTHER = ("football", "soccer", "rally", "grand prix", "formula", "badminton", "golf", "cricket", "rugby", "hockey", "racing",
         "motor", "basketball", "baseball", "cycling", "horse", "equestrian", "chio", "regatta", "war", "military", "museum",
         "overwatch", "owl", "esports", "fc ", "f.c.", "ballon", "league", "star of tomorrow", "hydrangea", "fernando alonso")
# The trophy's own name, where it has one: enough on its own
NAMED = {"Australian Open": ["norman brookes"], "Roland Garros": ["coupe des mousquetaires"],
         "Wimbledon": ["gentlemen's singles trophy", "wimbledon trophy"], "US Open": ["us open trophy", "u.s. open tennis"],
         "ATP Finals": ["atp finals trophy"]}


def score(title, tournament):
    """None = not clearly this tournament's men's singles trophy. Strict on purpose: candidates are only shown
    to a person, who picks; a missing photo is better than a wrong one."""
    t = title.lower()
    if not any(w in t for w in TROPHY_WORDS) or any(w in t for w in WOMENS) or any(w in t for w in OTHER):
        return None
    if any(n in t for n in NAMED.get(tournament, [])):
        return 10
    words = [w for w in re.findall(r"[a-z]+", tournament.lower()) if w not in STOP and len(w) > 2]
    if words and all(w in t for w in words) and ("tennis" in t or "atp" in t or "masters" in t or " open" in t):
        return 5 + ("singles" in t)
    return None


def find(client, tournaments, limit=None):
    """Candidates per tournament: {key: {"name", "candidates": [{"file", "licence", "author", "page"}]}}."""
    out = {}
    for t in tournaments[:limit]:
        key, name = t["key"], t["name"]
        seen, cands = set(), []
        for q in QUERIES.get(name, [f"{name} tennis trophy", f"{name} open trophy"]):
            for title in client.search(q):
                if title not in seen:
                    seen.add(title)
                    sc = score(title, name)
                    if sc is not None:
                        cands.append((sc, title))
        cands.sort(key=lambda x: -x[0])
        info = client.info([c[1] for c in cands[:10]]) if cands else {}
        good = [title for _, title in cands[:10] if title in info and free_licence(info[title]["licence"])
                and (info[title]["mime"] or "").startswith("image/") and info[title]["width"] >= 300]
        out[key] = {"name": name, "candidates": [{"file": x, "licence": info[x]["licence"], "author": info[x]["author"], "page": info[x]["page"]}
                                                  for x in good[:5]]}
    return out


def thumb_urls(meta):
    """Thumbnail URLs to try, largest first. Wikimedia serves a set of standard widths (500, 330, 250 px...)
    reliably; other widths can be refused (HTTP 403/429) for scripts."""
    thumb = meta["thumb"]
    urls = [thumb]
    m = re.search(r"/(\d+)px-", thumb or "")
    if m:
        urls += [thumb.replace(f"/{m.group(1)}px-", f"/{w}px-") for w in (330, 250) if str(w) != m.group(1)]
    if meta.get("bytes") and meta["bytes"] <= 1_500_000 and meta.get("url"):
        urls.append(meta["url"])  # small originals are fine too
    return urls


def build(client, chosen, cache_dir, out_dir, fetch):
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "trophies"), exist_ok=True)
    picks = {k: v["file"] for k, v in chosen.items() if isinstance(v, dict) and v.get("file")}
    info = client.info(sorted(set(picks.values()))) if picks else {}
    credits = {}
    for key, title in picks.items():
        meta = info.get(title)
        if not meta or not free_licence(meta["licence"]):
            print(f"skip {key}: {title} missing or not freely licensed ({meta and meta['licence']})", file=sys.stderr)
            continue
        fname = re.sub(r"[^a-z0-9-]", "-", key.lower()) + ".jpg"
        cached = os.path.join(cache_dir, fname)
        stamp = cached + ".src"
        if not (os.path.exists(cached) and os.path.exists(stamp) and open(stamp).read() == title):
            errors = []
            for url in thumb_urls(meta):
                try:
                    fetch(url, cached)
                    break
                except Exception as exc:  # try the next size
                    errors.append(f"{exc} for {url}")
            else:
                print(f"skip {key}: could not download {title}: " + "; ".join(errors), file=sys.stderr)
                continue
            with open(stamp, "w") as fh:
                fh.write(title)
        shutil.copyfile(cached, os.path.join(out_dir, "trophies", fname))
        credits[key] = {"src": "trophies/" + fname, "author": meta["author"], "licence": meta["licence"],
                        "licence_url": meta["licence_url"], "page": meta["page"], "file": title}
    os.makedirs(os.path.join(out_dir, "data"), exist_ok=True)
    with open(os.path.join(out_dir, "data", "trophies.json"), "w", encoding="utf-8") as fh:
        json.dump(credits, fh, ensure_ascii=False, indent=1)
    print(f"trophy photos: {len(credits)} of {len(picks)} listed")
    return credits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", action="store_true", help="print candidate photos per tournament (changes nothing)")
    ap.add_argument("--choices", default="data/trophies.json")
    ap.add_argument("--tournaments", default="docs/rankings/tennis/data/tournaments.json")
    ap.add_argument("--cache", default="data/trophy_images")
    ap.add_argument("--out", default="docs/rankings/tennis")
    args = ap.parse_args()
    client = Commons(os.environ.get("CONTACT_EMAIL", "set-CONTACT_EMAIL"))
    choices = {}
    if os.path.exists(args.choices):
        with open(args.choices, encoding="utf-8") as fh:
            choices = json.load(fh)
    if args.find:
        with open(args.tournaments, encoding="utf-8") as fh:
            data = json.load(fh)
        tours = data["tournaments"] if isinstance(data, dict) else data
        for key, r in find(client, tours).items():
            mark = " (already in trophies.json)" if key in choices else ""
            if r["candidates"]:
                print(f'"{key}"  {r["name"]}{mark}')
                for c in r["candidates"]:
                    print(f'      {c["file"]}   [{c["licence"]}, {c["author"]}]  {c["page"]}')
        print("Nothing was changed. Open the pages above; copy a good file into data/trophies.json by hand.")
        return

    def fetch(url, dest):
        req = urllib.request.Request(url, headers={"User-Agent": client.ua})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest + ".part", "wb") as fh:
            fh.write(resp.read())
        os.replace(dest + ".part", dest)
        time.sleep(client.delay)

    try:
        build(client, choices, args.cache, args.out, fetch)
    except Exception as exc:  # never break the site build over photos
        print(f"WARN trophy photos skipped: {exc}", file=sys.stderr)
        os.makedirs(os.path.join(args.out, "data"), exist_ok=True)
        path = os.path.join(args.out, "data", "trophies.json")
        if not os.path.exists(path):
            with open(path, "w") as fh:
                fh.write("{}")


if __name__ == "__main__":
    main()
