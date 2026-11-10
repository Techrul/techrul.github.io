#!/usr/bin/env python3
"""ATP-style points for CS2: points for final placings at S-, A- and B-tier events, best results of 52 weeks.

    Winner points by tier:  Major 2000 · S-Tier 1000 · A-Tier 500 · B-Tier 250   (Liquipedia tiers 1-3; a Major is
                            Valve's "Major Championship")
    Share of that by place: 1st 100% · 2nd 65% · 3-4 40% · 5-8 20% · 9-16 10% · 17-24 5% · 25-32 2.5%
                            A range counts by where it starts (9-11 and 12-14 are 9-16), and only places in the top
                            half of the field score: bigger events pay deeper, small ones don't pay last place.
                            Majors are the exception: every team in them scores (getting there is hard, and so is a
                            Swiss stage), so a Stage 2 exit (17-24) gets 100 and a Stage 1 exit (25-32) 50.
    Online events:          75% (the ATP has no online events; LAN results count fully)
    Ranking:                the sum of a roster's best BEST_N results from events that ended in the last 52 weeks.

Only the final placing matters, so Swiss stages, groups, upper and lower brackets need no special handling. A Major's
stages are one event on Liquipedia (its matches and placings sit on the Major's page); its RMRs and qualifiers lead
into it and don't score.
Points belong to the roster that played the event (Valve's three-of-five rule, as everywhere on the site): the team
at each placing is matched to the roster it fielded in that event's matches.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

TOP = {"major": 2000, "1": 1000, "2": 500, "3": 250}
BANDS = ((1, 1.0), (2, 0.65), (3, 0.40), (5, 0.20), (9, 0.10), (17, 0.05), (25, 0.025))  # first place of a band -> share
ONLINE = 0.75
BEST_N = 10
WINDOW_DAYS = 364


def share(start):
    """Share of the winner's points for a placing that starts at `start` (25-32 is the last band)."""
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


def _rosters_by_event(data, roster_of_match):
    """{event page: Counter((team name or template, lowercased, roster id) -> matches)} and
    {event page: {roster id: last match time}}, from the event's own matches."""
    by_event, last = defaultdict(Counter), defaultdict(dict)
    for m in data.matches:
        if "rosters" not in m:
            continue
        for i, t in enumerate(m["teams"]):
            rid = roster_of_match(m, i)
            last[m["event"]][rid] = max(last[m["event"]].get(rid, 0), m.get("time") or 0)
            for k in (t.get("template"), t.get("name")):
                if k:
                    by_event[m["event"]][(k.lower(), rid)] += 1
    return by_event, last


def _scoring(t):
    """Winner points for a tournament record, or None if it doesn't score.
    Qualifiers and Valve's RMR events (the regional stage before a Major) don't score: like ATP qualifying, they lead
    into the main event, where the team's placing is counted."""
    if t.get("tiertype") or not t.get("end") or t.get("valve") in ("RMR Event", "Major Qualifier"):
        return None
    return TOP["major"] if t.get("valve") == "Major Championship" else TOP.get(t.get("tier"))


def _counts(start, field, major):
    """Does a placing starting at `start` score? The top half of the field does; at a Major, every team."""
    return bool(field and share(start) and (major or start <= field / 2))


def series_key(page):
    """'Intel_Extreme_Masters/2026/Cologne' -> 'Intel_Extreme_Masters/Cologne', 'ESL/Pro_League/Season_24' ->
    'ESL/Pro_League': editions of the same event across years share a key."""
    return re.sub(r"/(19|20)\d\d(?=/|$)|/Season_\d+", "", page)


def defending(results, live_events, tournaments):
    """{live event page: page whose points a live ranking drops}: last year's edition of each event being played now. Like the ATP's
    live ranking, a team defending points from it loses them as the new edition starts (and wins back what it earns
    there), instead of when they turn 52 weeks old a few days later.

    Last year's edition is, first, an edition of the same series that ended 40 to 60 weeks before this one began (so a
    league played twice a year keeps its last season); failing that, as the ATP does when a tournament moves city, the
    same organiser's event of the same tier that started within 3 weeks of a year earlier (IEM Chengdu 2025 ->
    IEM Beijing 2026)."""
    pages = {page for _r, _d, _p, page in results}
    out = {}
    for ev in live_events:
        t_ev = tournaments.get(ev["page"]) or {}
        start = datetime.strptime(ev["start"], "%Y-%m-%d")
        lo, hi = (start - timedelta(weeks=60)).strftime("%Y-%m-%d"), (start - timedelta(weeks=40)).strftime("%Y-%m-%d")
        key, org = series_key(ev["page"]), ev["page"].split("/")[0]
        same = [p for p in pages if p != ev["page"] and series_key(p) == key
                and lo <= (tournaments.get(p) or {}).get("end", "") <= hi]
        if not same:
            near = []
            for p in pages:
                t = tournaments.get(p) or {}
                if p.split("/")[0] != org or p == ev["page"] or t.get("tier") != t_ev.get("tier") or not t.get("start"):
                    continue
                off = abs((datetime.strptime(t["start"], "%Y-%m-%d") + timedelta(weeks=52) - start).days)
                if off <= 21:
                    near.append((off, p))
            same = [min(near)[1]] if near else []
        if same:
            out[ev["page"]] = max(same, key=lambda p: tournaments[p]["end"])
    return out


def _decided(rows):
    """Placings with a team in them: Liquipedia keeps "TBD" rows for places not decided yet."""
    return [r for r in rows if (r.get("team") or "").strip().upper() not in ("", "TBD")]


def _roster_for(row, seen):
    for k in (row.get("template"), row.get("team")):
        if k:
            cands = [(n, rid) for (k_, rid), n in seen.items() if k_ == k.lower()]
            if cands:
                return max(cands)[1]
    return None


def event_results(data, roster_of_match):
    """Every scoring placing at finished events as (roster id, end date 'YYYY-MM-DD', points, event page).
    roster_of_match(match, side) -> roster id for that side of a match (as assigned for the ratings)."""
    by_event, _last = _rosters_by_event(data, roster_of_match)
    out = []
    for page, rows in data.placements.items():
        rows = _decided(rows)
        t = data.tournaments.get(page) or {}
        top = _scoring(t)
        if not top:
            continue
        starts = [s for s in (_start(r["place"]) for r in rows) if s]
        # an event scores once it is over: on its end date, and only when the winner is recorded (so a final still
        # being played on the last day never leaves half an event counted)
        if 1 not in starts:
            continue
        field = t.get("teams") or (max(starts) if starts else 0)
        if not field:
            continue
        seen = by_event.get(page, Counter())
        for r in rows:
            s = _start(r["place"])
            if not s or not _counts(s, field, t.get("valve") == "Major Championship"):
                continue
            rid = _roster_for(r, seen)
            if rid is None:
                continue
            pts = top * share(s) * (1.0 if t.get("lan") else ONLINE)
            out.append((rid, t["end"], round(pts, 1), page))
    out.sort(key=lambda x: x[1])
    return out


def prize_money(data, roster_of_match):
    """[(roster id, date 'YYYY-MM-DD', prize in USD, event page)]: every placing with prize money, at any event, matched
    to the roster that played it (as for points). Undecided ("TBD") places are left out."""
    by_event, _last = _rosters_by_event(data, roster_of_match)
    out = []
    for page, rows in data.placements.items():
        seen = by_event.get(page, Counter())
        for r in _decided(rows):
            if not r.get("prize"):
                continue
            rid = _roster_for(r, seen)
            if rid is not None:
                out.append((rid, r.get("date") or (data.tournaments.get(page) or {}).get("end") or "", r["prize"], page))
    return out


def match_points(data, roster_of_match, today):
    """{(match id, roster id): points}: what each match was worth, like rounds in the ATP's live ranking. A win that
    lifts the team's guaranteed placing earns the difference; the rest of the event's points (or, at an event still
    being played, of what the team is sure of so far) come with its last match. So a team's matches at an event add up
    to exactly its points there.

    The guaranteed placing after a match is the worst place still open: with 8 of 16 teams out, 8th. Teams go out on
    the date of their placing, so this goes by day. The top-half rule, the Major rule and online events' 75% apply as
    everywhere."""
    day = today if isinstance(today, str) else today.strftime("%Y-%m-%d")
    by_event, _last = _rosters_by_event(data, roster_of_match)
    ms_by_event = defaultdict(list)
    for m in data.matches:
        if "rosters" in m and m.get("id"):
            ms_by_event[m["event"]].append(m)
    finished = {}
    for rid, _end, pts, page in event_results(data, roster_of_match):
        finished[(page, rid)] = pts
    live, _events = live_results(data, roster_of_match, day)
    so_far = {(page, rid): pts for rid, _d, pts, page in live}
    out = {}
    for page, ms in ms_by_event.items():
        t = data.tournaments.get(page) or {}
        top = _scoring(t)
        field = t.get("teams") or 0
        if not top or not field:
            continue
        major, mult = t.get("valve") == "Major Championship", 1.0 if t.get("lan") else ONLINE
        seen = by_event.get(page, Counter())
        out_on = []  # (date, roster) for each team out, from its placing
        for r in _decided(data.placements.get(page, [])):
            rid = _roster_for(r, seen)
            s = _start(r["place"])
            if rid is not None and s and s > 1 and r.get("date"):
                out_on.append((r["date"][:10], rid))
        def sure(rid, through):  # points the team is sure of once everyone out by `through` (a date) is out
            left = field - sum(1 for d, r in out_on if d <= through and r != rid)
            return top * share(left) * mult if left > 0 and _counts(left, field, major) else 0.0
        ms.sort(key=lambda m: m.get("time") or 0)
        teams = defaultdict(list)
        for m in ms:
            for i in (0, 1):
                teams[roster_of_match(m, i)].append((m, i))
        for rid, played in teams.items():
            total = finished.get((page, rid), so_far.get((page, rid)))
            if total is None:
                continue  # the event doesn't score, or this team scored nothing there
            given, held = 0.0, 0.0
            for k, (m, i) in enumerate(played):
                mday = datetime.fromtimestamp(m["time"], timezone.utc).strftime("%Y-%m-%d") if m.get("time") else m.get("date", "")[:10]
                held = max(held, sure(rid, mday))
                won = m.get("winner") == i + 1
                if k == len(played) - 1:
                    out[(m["id"], rid)] = round(total - given)
                elif won and held - given >= 0.5:
                    out[(m["id"], rid)] = round(held - given)
                    given += round(held - given)
    return out


def live_results(data, roster_of_match, today):
    """Points so far at events still being played, like the ATP's live ranking, as
    ([(roster id, today, points, event page)], [{"page", "name", "left"}]).

    A team that is out has its final placing. A team still in holds what it is sure of: with 8 teams left, at least
    5th-8th. Placings are recorded as teams go out, so the best place handed out so far tells how many are left; those
    are the teams without a placing that played most recently at the event."""
    day = today if isinstance(today, str) else today.strftime("%Y-%m-%d")
    recent = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
    by_event, last = _rosters_by_event(data, roster_of_match)
    out, events = [], []
    for page, t in data.tournaments.items():
        top = _scoring(t)
        rows = _decided(data.placements.get(page, []))
        starts = [s for s in (_start(r["place"]) for r in rows) if s]
        # started, not finished (no winner yet), not long past its end date (a page never completed is not "live")
        if not top or 1 in starts or not (t.get("start") or "9") <= day or t["end"] < recent or page not in last:
            continue
        field = t.get("teams") or 0
        seen, mult = by_event.get(page, Counter()), 1.0 if t.get("lan") else ONLINE
        placed = set()
        for r in rows:
            s = _start(r["place"])
            rid = _roster_for(r, seen)
            if rid is None or not s:
                continue
            placed.add(rid)
            if _counts(s, field, t.get("valve") == "Major Championship"):
                out.append((rid, day, round(top * share(s) * mult, 1), page))
        left = (min(starts) - 1) if starts else field
        alive = sorted((r for r in last[page] if r not in placed), key=lambda r: -last[page][r])[:max(left, 0)]
        # the worst place still open is `left` (e.g. 8 left: 8th, which is in the 5-8 band)
        if left and _counts(left, field, t.get("valve") == "Major Championship"):
            out.extend((rid, day, round(top * share(left) * mult, 1), page) for rid in alive)
        events.append({"page": page, "name": t.get("name") or page, "start": t["start"], "left": left if starts else None})
    return out, events


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
