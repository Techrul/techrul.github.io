#!/usr/bin/env python3
"""Download TennisMyLife match files into data/raw, with basic safety checks.

    CONTACT_EMAIL=you@example.com python3 scripts/fetch_tml.py --start-year 2015 --raw data/raw

- Only downloads files for the years you ask for, plus ongoing_tourneys.csv.
- Sends a descriptive User-Agent and waits between requests.
- Validates each download before replacing the last good copy. If a check fails, the old
  copy is kept and the script exits 0 so the site still rebuilds from the previous data.
- Writes data/manifest.json (hashes, row counts, newest match date). Never commit data/raw.

NOTE: written against the URLs listed on stats.tennismylife.org; not tested from the
build sandbox, which could not reach that site. Check the first workflow run's log.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

BASE = "https://stats.tennismylife.org/data/"
# Weekly ATP rankings. Only on GitHub; the copy there stopped updating in January 2026, so when it is
# stale ratings.py falls back to an estimate. Re-check occasionally whether it has resumed.
RANKINGS_BASE = "https://raw.githubusercontent.com/Tennismylife/TML-Rankings-Database/main/TML%20Rankings/"
RANKING_COLUMNS = {"date", "rank", "id", "name", "points"}
REQUIRED = {"tourney_id", "tourney_name", "tourney_date", "match_num", "winner_id", "winner_name",
            "loser_id", "loser_name", "round", "tourney_level", "draw_size", "score"}


def download(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def inspect(blob):
    """Return (row_count, newest_date) or raise ValueError."""
    text = blob.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = REQUIRED - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    n, dupes, newest, seen = 0, 0, "", set()
    for r in reader:
        n += 1
        key = (r["tourney_id"], r["round"], r["winner_id"], r["loser_id"])  # match_num can be blank
        if key in seen:
            dupes += 1  # the source has the odd repeated row; ratings.py skips repeats
        seen.add(key)
        newest = max(newest, r["tourney_date"] or "")
    if n == 0:
        raise ValueError("no rows")
    if dupes > max(5, n * 0.01):
        raise ValueError(f"{dupes} repeated match rows out of {n}")
    datetime.strptime(newest, "%Y%m%d")
    return n, newest


def inspect_rankings(blob):
    text = blob.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = RANKING_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    dates = [r["date"] for r in reader if (r.get("date") or "").isdigit()]
    if not dates:
        raise ValueError("no ranking rows")
    return len(dates), max(dates)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--manifest", default="data/manifest.json")
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--rankings", default="data/rankings")
    args = ap.parse_args()

    contact = os.environ.get("CONTACT_EMAIL", "set-CONTACT_EMAIL")
    ua = f"tennis-rankings-site (non-commercial, open source; contact: {contact})"
    os.makedirs(args.raw, exist_ok=True)

    manifest = {}
    if os.path.exists(args.manifest):
        with open(args.manifest, encoding="utf-8") as fh:
            manifest = json.load(fh)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    names = [f"{y}.csv" for y in range(args.start_year, datetime.now(timezone.utc).year + 1)] + ["ongoing_tourneys.csv"]
    current = {f"{datetime.now(timezone.utc).year}.csv", "ongoing_tourneys.csv"}
    problems = 0
    for name in names:
        dest = os.path.join(args.raw, name)
        # The site updates several times a day: past seasons are downloaded at most once a day, only the current
        # season and the ongoing events every run, to go easy on Tennismylife's server.
        if name not in current and os.path.exists(dest) and manifest.get(name, {}).get("fetched") == today:
            continue
        try:
            blob = download(BASE + name, ua)
            rows, newest = inspect(blob)
            old = manifest.get(name, {}).get("rows")
            if old and rows < old * 0.98 and name != "ongoing_tourneys.csv":
                raise ValueError(f"row count fell from {old} to {rows}")
        except Exception as exc:  # keep the last good copy
            problems += 1
            print(f"WARN {name}: {exc}. Keeping previous copy if present.", file=sys.stderr)
            time.sleep(args.delay)
            continue
        with open(dest, "wb") as fh:
            fh.write(blob)
        manifest[name] = {"sha256": hashlib.sha256(blob).hexdigest(), "rows": rows, "newest_match": newest,
                          "fetched": today}
        print(f"ok   {name}: {rows} rows, newest {newest}")
        time.sleep(args.delay)

    # weekly rankings from --start-year (history charts and weeks at #1). Past years rarely change,
    # so they are downloaded once and kept; the last two years are refreshed every run.
    os.makedirs(args.rankings, exist_ok=True)
    this_year = datetime.now(timezone.utc).year
    for year in range(args.start_year, this_year + 1):
        name = f"rankings_{year}.csv"
        if year < this_year - 1 and os.path.exists(os.path.join(args.rankings, f"{year}.csv")):
            continue
        if year < this_year and os.path.exists(os.path.join(args.rankings, f"{year}.csv")) and manifest.get(name, {}).get("fetched") == today:
            continue
        try:
            blob = download(f"{RANKINGS_BASE}{year}.csv", ua)
            rows, newest = inspect_rankings(blob)
        except Exception as exc:
            print(f"WARN {name}: {exc}. Keeping previous copy if present.", file=sys.stderr)
            time.sleep(args.delay)
            continue
        with open(os.path.join(args.rankings, f"{year}.csv"), "wb") as fh:
            fh.write(blob)
        manifest[name] = {"sha256": hashlib.sha256(blob).hexdigest(), "rows": rows, "newest_ranking": newest,
                          "fetched": today}
        print(f"ok   {name}: {rows} rows, newest ranking {newest}")
        time.sleep(args.delay)

    os.makedirs(os.path.dirname(os.path.abspath(args.manifest)), exist_ok=True)
    with open(args.manifest, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    have = [n for n in names if os.path.exists(os.path.join(args.raw, n))]
    if not have:
        sys.exit("no data available at all")
    if problems:
        print(f"{problems} file(s) fell back to older copies", file=sys.stderr)


if __name__ == "__main__":
    main()
