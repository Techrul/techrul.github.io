#!/usr/bin/env python3
"""The official ATP singles ranking (top 150 with points), from ESPN's public ranking feed.

    python3 scripts/fetch_atp_espn.py --out data/atp_rankings

Tennismylife's weekly ranking files stopped updating in January 2026; this takes their place from then on.
Each new ranking is saved as <out>/YYYY-MM-DD.csv (date,rank,name,espn_id,ioc,points), dated the Monday it was
published. The feed has no publication date of its own, so a ranking is dated the Monday on or before the day it is
first seen; a feed that hasn't changed since the last saved ranking is not saved again (so a Monday run that comes
before ESPN's update simply waits for a later run). ratings.py matches the names to player ids.
"""
import argparse
import csv
import glob
import io
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/rankings"
COLUMNS = ["date", "rank", "name", "espn_id", "ioc", "points"]


def parse(data):
    """ESPN's JSON -> [(rank, name, espn id, ioc, points)] for the ATP singles ranking."""
    for rk in data.get("rankings") or []:
        if (rk.get("type") or "").lower() != "atp" and (rk.get("shortName") or "") != "ATP":
            continue
        out = []
        for e in rk.get("ranks") or []:
            a = e.get("athlete") or {}
            if e.get("current") and a.get("displayName"):
                out.append((int(e["current"]), a["displayName"], str(a.get("id") or ""), a.get("citizenshipCountry") or "",
                            int(e.get("points") or 0)))
        return sorted(out)
    return []


def latest_saved(folder):
    files = sorted(glob.glob(os.path.join(folder, "*.csv")))
    if not files:
        return None, None
    with open(files[-1], newline="", encoding="utf-8") as fh:
        rows = [(int(r["rank"]), r["name"], r["espn_id"], r["ioc"], int(r["points"])) for r in csv.DictReader(fh)]
    return os.path.basename(files[-1])[:10], rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/atp_rankings")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    req = urllib.request.Request(URL, headers={"User-Agent": "techrul.github.io rankings (https://github.com/Techrul/techrul.github.io)"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = parse(json.loads(r.read().decode("utf-8")))
    except Exception as e:  # the site falls back to its estimate
        sys.exit(f"ESPN ranking: {e}")
    if len(rows) < 50:
        sys.exit(f"ESPN ranking: only {len(rows)} rows, not saved")
    today = datetime.now(timezone.utc).date()
    monday = (today - timedelta(days=today.weekday())).isoformat()
    last_day, last_rows = latest_saved(args.out)
    if last_rows == rows:
        msg = f"unchanged since the ranking of {last_day}"
    elif last_day and last_day >= monday:
        msg = f"changed again this week; the ranking of {monday} is updated"
    else:
        msg = f"new ranking saved as {monday}"
    if last_rows != rows:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(COLUMNS)
        w.writerows([monday, *r] for r in rows)
        with open(os.path.join(args.out, f"{monday}.csv"), "w", encoding="utf-8") as fh:
            fh.write(buf.getvalue())
    top = ", ".join(f"{r[0]} {r[1]} {r[4]}" for r in rows[:3])
    print(f"ESPN ranking: {len(rows)} players; {msg}; top: {top}")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::notice title=ATP ranking (ESPN)::{len(rows)} players; {msg}; top: {top}")


if __name__ == "__main__":
    main()
