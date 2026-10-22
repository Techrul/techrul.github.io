#!/usr/bin/env python3
"""Fetch CS2 matches, tournaments and prize money from Liquipedia's API into data/cs2/ (see CS2_PLAN.md).

    env LIQUIPEDIA_API_KEY=... CONTACT_EMAIL=you@example.com python3 scripts/fetch_cs2.py --max-requests 40

Each run:
1. refresh: matches from the last REFRESH_MATCH_DAYS days, tournaments and prize money from the last
   REFRESH_EVENT_DAYS days (results get corrected, events finish);
2. backfill: whole months, newest first, back to --start, for anything not fetched yet. A month counts as done
   once it has been fetched SETTLE_DAYS after it ended; it is never fetched again after that.

Everything is saved after each step, so a run that stops (request budget used, or Liquipedia rate limiting us)
loses nothing and the next run carries on. Stopping early is normal and exits 0; real errors exit 1.

Data from Liquipedia is CC BY-SA 3.0 (see data/cs2/README.md). Showmatches are not fetched.
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_api  # noqa: E402

WIKI = "counterstrike"
REFRESH_MATCH_DAYS = 21
REFRESH_EVENT_DAYS = 60
SETTLE_DAYS = 21

MATCH_FIELDS = ("objectname,match2id,pagename,parent,tournament,date,finished,winner,walkover,resulttype,bestof,"
                "liquipediatier,liquipediatiertype,publishertier,type,extradata,match2opponents")
TOURNAMENT_FIELDS = ("pagename,name,shortname,startdate,enddate,prizepool,type,publishertier,liquipediatier,"
                     "liquipediatiertype,status,participantsnumber")
PLACEMENT_FIELDS = ("objectname,pagename,parent,tournament,date,placement,opponentname,opponenttemplate,opponenttype,"
                    "opponentplayers,prizemoney,publishertier,liquipediatier,qualifier,qualifierpage,extradata")
NOT_SHOWMATCH = "[[liquipediatiertype::!Showmatch]]"


# ----------------------------------------------------------------------------- record shapes
def _int(v, default=None):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def compact_match(m, flags):
    """A match2 record -> our compact form. Player nationalities go into `flags` (name -> country)."""
    ext = m.get("extradata") if isinstance(m.get("extradata"), dict) else {}
    ts = _int(ext.get("timestamp"))
    if ts is None:
        ts = int(datetime.strptime(m["date"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    teams = []
    for o in m.get("match2opponents") or []:
        players = sorted(o.get("match2players") or [], key=lambda p: _int(p.get("id"), 99))
        for p in players:
            if p.get("name") and p.get("flag"):
                flags[p["name"]] = p["flag"]
        teams.append({"name": o.get("name") or "", "template": o.get("template") or "", "type": o.get("type") or "",
                      "score": o.get("score"), "status": o.get("status") or "",
                      "players": [p["name"] for p in players if p.get("name")]})
    return {"id": m.get("objectname") or f'{m.get("pagename")}_{m.get("match2id")}',
            "time": ts, "date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"),
            "event": m.get("parent") or m.get("pagename") or "", "event_name": m.get("tournament") or "",
            "tier": m.get("liquipediatier") or "", "tiertype": m.get("liquipediatiertype") or "",
            "valve": m.get("publishertier") or "", "lan": (m.get("type") or "").lower() == "offline",
            "winner": _int(m.get("winner"), 0), "walkover": m.get("walkover") or "",
            "resulttype": m.get("resulttype") or "", "bestof": _int(m.get("bestof")), "teams": teams}


def compact_tournament(t):
    return {"name": t.get("name") or "", "start": (t.get("startdate") or "")[:10], "end": (t.get("enddate") or "")[:10],
            "pool": _int(t.get("prizepool"), 0), "lan": (t.get("type") or "").lower() == "offline",
            "type": t.get("type") or "", "valve": t.get("publishertier") or "", "tier": t.get("liquipediatier") or "",
            "tiertype": t.get("liquipediatiertype") or "", "status": t.get("status") or "",
            "teams": _int(t.get("participantsnumber"))}


def compact_placement(p, flags):
    op = p.get("opponentplayers") if isinstance(p.get("opponentplayers"), dict) else {}
    players = [op[f"p{i}"] for i in range(1, 11) if op.get(f"p{i}")]
    for i in range(1, 11):
        if op.get(f"p{i}") and op.get(f"p{i}flag"):
            flags.setdefault(op[f"p{i}"], op[f"p{i}flag"])
    ext = p.get("extradata") if isinstance(p.get("extradata"), dict) else {}
    return {"place": str(p.get("placement") or ""), "team": p.get("opponentname") or "",
            "template": p.get("opponenttemplate") or "", "type": p.get("opponenttype") or "",
            "prize": _int(p.get("prizemoney"), 0), "player_share": _int(ext.get("playershare")),
            "players": players, "date": (p.get("date") or "")[:10], "valve": p.get("publishertier") or "",
            "tier": p.get("liquipediatier") or "", "qualifier": p.get("qualifier") or "",
            "qualifier_page": p.get("qualifierpage") or ""}


# ----------------------------------------------------------------------------- storage
class Store:
    """data/cs2/: matches/YYYY-MM.jsonl (one match per line), tournaments.json, placements.json,
    players.json (name -> country), state.json (what has been fetched when)."""

    def __init__(self, root):
        self.root = root
        os.makedirs(os.path.join(root, "matches"), exist_ok=True)
        self.state = self._load("state.json", {"months": {}})
        self.tournaments = self._load("tournaments.json", {})
        self.placements = self._load("placements.json", {})
        self.flags = self._load("players.json", {})

    def _load(self, name, default):
        path = os.path.join(self.root, name)
        if not os.path.exists(path):
            return default
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def _write(self, name, text):
        path = os.path.join(self.root, name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)

    @staticmethod
    def _lines(d):
        """A dict as JSON with one key per line, sorted: small, readable git diffs."""
        if not d:
            return "{}\n"
        return "{\n" + ",\n".join(f"{json.dumps(k, ensure_ascii=False)}: "
                                  f"{json.dumps(d[k], ensure_ascii=False, separators=(',', ':'))}"
                                  for k in sorted(d)) + "\n}\n"

    def add_matches(self, matches):
        by_month = {}
        for m in matches:
            by_month.setdefault(m["date"][:7], []).append(m)
        for month, ms in by_month.items():
            path = os.path.join(self.root, "matches", f"{month}.jsonl")
            have = {}
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            r = json.loads(line)
                            have[r["id"]] = r
            for m in ms:
                have[m["id"]] = m
            rows = sorted(have.values(), key=lambda r: (r["time"], r["id"]))
            self._write(os.path.join("matches", f"{month}.jsonl"),
                        "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows))
        return len(by_month)

    def add_tournaments(self, rows):
        for t in rows:
            if t.get("pagename"):
                self.tournaments[t["pagename"]] = compact_tournament(t)

    def add_placements(self, rows):
        by_page = {}
        for p in rows:
            if p.get("pagename"):
                by_page.setdefault(p["pagename"], []).append(compact_placement(p, self.flags))
        for page, ps in by_page.items():  # a page's list is replaced whole, so corrections replace old rows
            self.placements[page] = sorted(ps, key=lambda x: (_int(x["place"].split("-")[0], 999), x["team"]))

    def mark(self, month, kind, today):
        self.state["months"].setdefault(month, {})[kind] = today.isoformat()

    def save(self):
        self._write("tournaments.json", self._lines(self.tournaments))
        self._write("placements.json", self._lines(self.placements))
        self._write("players.json", self._lines(self.flags))
        self._write("state.json", json.dumps(self.state, indent=1, sort_keys=True) + "\n")


# ----------------------------------------------------------------------------- windows
def month_bounds(month):
    y, m = map(int, month.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return first, nxt


def months_back(today, start):
    """Months from today's back to `start` (YYYY-MM), newest first."""
    out, y, m = [], today.year, today.month
    while f"{y:04d}-{m:02d}" >= start:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


def needs_fetch(state, month, kind, today):
    """Not fetched yet, or last fetched before the month had settled and it has settled now."""
    got = (state["months"].get(month) or {}).get(kind)
    if got is None:
        return True
    settle = month_bounds(month)[1] + timedelta(days=SETTLE_DAYS)
    return date.fromisoformat(got) < settle <= today


def window(field, first, nxt):
    # ">" and "<" on dates: one day of overlap at each end is harmless (rows are keyed by id), gaps are not
    return f"[[{field}::>{(first - timedelta(days=1)).isoformat()}]] AND [[{field}::<{nxt.isoformat()}]]"


# ----------------------------------------------------------------------------- fetching
def fetch_matches(client, store, first, nxt):
    rows = client.get_all("match", f"[[finished::1]] AND {NOT_SHOWMATCH} AND {window('date', first, nxt)}",
                          query=MATCH_FIELDS)
    store.add_matches([compact_match(m, store.flags) for m in rows])
    return len(rows)


def fetch_tournaments(client, store, first, nxt, started_by=None):
    cond = window("enddate", first, nxt)
    if started_by:
        cond += f" AND [[startdate::<{started_by.isoformat()}]]"
    rows = client.get_all("tournament", cond, query=TOURNAMENT_FIELDS)
    store.add_tournaments(rows)
    return len(rows)


def fetch_placements(client, store, first, nxt):
    rows = client.get_all("placement", f"[[prizemoney::>0]] AND {window('date', first, nxt)}", query=PLACEMENT_FIELDS)
    store.add_placements(rows)
    return len(rows)


KINDS = (("matches", fetch_matches), ("tournaments", fetch_tournaments), ("placements", fetch_placements))


def run(client, store, today, start, backfill=True, log=print):
    tomorrow = today + timedelta(days=1)
    done = {"refresh": 0, "months": []}

    log(f"refresh: matches since {today - timedelta(days=REFRESH_MATCH_DAYS)}, events since "
        f"{today - timedelta(days=REFRESH_EVENT_DAYS)}")
    n = fetch_matches(client, store, today - timedelta(days=REFRESH_MATCH_DAYS), tomorrow)
    t = fetch_tournaments(client, store, today - timedelta(days=REFRESH_EVENT_DAYS), date(today.year + 3, 1, 1),
                          started_by=tomorrow)
    p = fetch_placements(client, store, today - timedelta(days=REFRESH_EVENT_DAYS), tomorrow)
    store.save()
    done["refresh"] = n
    log(f"  {n} matches, {t} tournaments, {p} prize rows")

    if not backfill:
        return done
    for month in months_back(today, start):
        first, nxt = month_bounds(month)
        for kind, fn in KINDS:
            if not needs_fetch(store.state, month, kind, today):
                continue
            count = fn(client, store, first, nxt)
            store.mark(month, kind, today)
            store.save()
            log(f"  {month} {kind}: {count}")
        done["months"].append(month)
    return done


def summary(store, start, today):
    months = months_back(today, start)
    full = [m for m in months if all(k in (store.state["months"].get(m) or {}) for k, _ in KINDS)]
    n = 0
    for name in os.listdir(os.path.join(store.root, "matches")):
        with open(os.path.join(store.root, "matches", name), encoding="utf-8") as fh:
            n += sum(1 for line in fh if line.strip())
    return (f"{n} matches stored, {len(store.tournaments)} tournaments, {len(store.placements)} events with prize "
            f"money, {len(store.flags)} players; {len(full)} of {len(months)} months fetched "
            f"({start} to {today.strftime('%Y-%m')})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cs2")
    ap.add_argument("--start", default="2023-01", help="first month to fetch (YYYY-MM)")
    ap.add_argument("--max-requests", type=int, default=40, help="hard cap for this run")
    ap.add_argument("--per-hour", type=int, default=45, help="rolling limit (Liquipedia allows 60 per hour)")
    ap.add_argument("--max-minutes", type=float, default=None, help="stop cleanly after this long (incl. waiting)")
    ap.add_argument("--no-backfill", action="store_true", help="only refresh recent weeks")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    store = Store(args.data)
    try:
        client = lp_api.Client(WIKI, max_requests=args.max_requests, per_hour=args.per_hour,
                               max_seconds=args.max_minutes * 60 if args.max_minutes else None)
    except lp_api.ApiError as e:
        sys.exit(f"cs2 fetch: {e}")
    status = 0
    try:
        run(client, store, today, args.start, backfill=not args.no_backfill)
        print("finished: everything up to date")
    except lp_api.StopRun as e:
        print(f"stopped early ({e}); the next run continues from here")
    except lp_api.ApiError as e:
        print(f"error: {e}")
        status = 1
    store.save()
    print(f"requests used: {client.sent}")
    print(summary(store, args.start, today))
    sys.exit(status)


if __name__ == "__main__":
    main()
