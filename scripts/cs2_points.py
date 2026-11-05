#!/usr/bin/env python3
"""ATP-style points for CS2: points for final placings at S-, A- and B-tier events, best results of 52 weeks.

    Winner points by tier:  Major 2000 · S-Tier 1000 · A-Tier 500 · B-Tier 250   (Liquipedia tiers 1-3; a Major is
                            Valve's "Major Championship")
    Share of that by place: 1st 100% · 2nd 65% · 3-4 40% · 5-8 20% · 9-16 10% · 17-32 5%
                            A range counts by where it starts (9-11 and 12-14 are 9-16), and only places in the top
                            half of the field score: bigger events pay deeper, small ones don't pay last place.
    Online events:          75% (the ATP has no online events; LAN results count fully)
    Ranking:                the sum of a roster's best BEST_N results from events that ended in the last 52 weeks.

Only the final placing matters, so Swiss stages, groups, upper and lower brackets need no special handling. A Major's
stages are one event on Liquipedia (its matches and placings sit on the Major's page); its RMRs and qualifiers lead
into it and don't score.
Points belong to the roster that played the event (Valve's three-of-five rule, as everywhere on the site): the team
at each placing is matched to the roster it fielded in that event's matches.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

TOP = {"major": 2000, "1": 1000, "2": 500, "3": 250}
BANDS = ((1, 1.0), (2, 0.65), (3, 0.40), (5, 0.20), (9, 0.10), (17, 0.05))  # first place of a band -> share
ONLINE = 0.75
BEST_N = 10
WINDOW_DAYS = 364


def share(start):
    """Share of the winner's points for a placing that starts at `start` (17-32 is the last band)."""
    if start > 32:
        return 0.0
    out = 0.0
    for first, s in BANDS:
        if start >= first:
            out = s
    return out


def _start(place):
    try:
        return int(str(place).split("-")[0])
    except ValueError:
        return None


def event_results(data, roster_of_match):
    """Every scoring placing as (roster id, end date 'YYYY-MM-DD', points, event page).
    roster_of_match(match, side) -> roster id for that side of a match (as assigned for the ratings)."""
    # which roster each team name / template was at each event, from the event's own matches
    by_event = defaultdict(Counter)
    for m in data.matches:
        if "rosters" not in m:
            continue
        for i, t in enumerate(m["teams"]):
            rid = roster_of_match(m, i)
            for k in (t.get("template"), t.get("name")):
                if k:
                    by_event[m["event"]][(k.lower(), rid)] += 1
    out = []
    for page, rows in data.placements.items():
        t = data.tournaments.get(page) or {}
        # qualifiers and Valve's RMR events (the regional stage before a Major) don't score: like ATP qualifying,
        # they lead into the main event, where the team's placing is counted
        if t.get("tiertype") or not t.get("end") or t.get("valve") in ("RMR Event", "Major Qualifier"):
            continue
        top = TOP["major"] if t.get("valve") == "Major Championship" else TOP.get(t.get("tier"))
        if not top:
            continue
        starts = [s for s in (_start(r["place"]) for r in rows) if s]
        field = t.get("teams") or (max(starts) if starts else 0)
        if not field:
            continue
        seen = by_event.get(page, Counter())
        for r in rows:
            s = _start(r["place"])
            if not s or s > field / 2 or not share(s):
                continue
            rid = None
            for k in (r.get("template"), r.get("team")):
                if k and rid is None:
                    cands = [(n, rid_) for (k_, rid_), n in seen.items() if k_ == k.lower()]
                    if cands:
                        rid = max(cands)[1]
            if rid is None:
                continue
            pts = top * share(s) * (1.0 if t.get("lan") else ONLINE)
            out.append((rid, t["end"], round(pts, 1), page))
    out.sort(key=lambda x: x[1])
    return out


def ledger(results, as_of):
    """{roster: points} as of `as_of` (a 'YYYY-MM-DD' string or a datetime): best BEST_N results from events that
    ended in the 52 weeks up to and including that day."""
    day = as_of if isinstance(as_of, str) else as_of.strftime("%Y-%m-%d")
    start = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    per = defaultdict(list)
    for rid, end, pts, _page in results:
        if start < end <= day:
            per[rid].append(pts)
    return {rid: round(sum(sorted(v, reverse=True)[:BEST_N])) for rid, v in per.items()}


def ranks(points):
    order = sorted(points, key=lambda r: (-points[r], r))
    return {r: i + 1 for i, r in enumerate(order)}
