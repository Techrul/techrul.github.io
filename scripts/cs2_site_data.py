#!/usr/bin/env python3
"""Build the data behind the CS2 team, predict, records and events pages (the CS2 version of site_data.py).

    python3 scripts/cs2_site_data.py --data data/cs2 --valve vendor/vrs \\
        --current docs/rankings/cs2/data/rankings.json --out docs/rankings/cs2/data

Writes into --out:
    teams/<id>.json     one profile per team: ranks over time, Elo over time, titles, record, recent matches
    teams_index.json    id, name, region, current Valve and Elo rank (for search and links)
    records.json        per system and time window: weeks at #1, peaks, upsets, weekly rises, gaps from Valve's list
    events.json         Liquipedia tier 1 and 2 main events, grouped into series: champion, field, favourite,
                        champion's seed and upsets under each system, VRS stakes, prize money
    backtest.json       how well each system predicted the last 12 months
    h2h.json            meetings between listed teams
    history_meta.json   the weekly dates the history arrays refer to

As for tennis: history starts a year after the first match (2023 only warms the models up), records only cover
the data on the site, and "official" is Valve's published standings, each in force until the next one.
Match data: Liquipedia, CC BY-SA 3.0; the output is shared under the same licence.
"""
import argparse
import bisect
import glob
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

UPSET = 0.35  # a win the system gave the winner under 35% counts as an upset

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cs2_adapter as ad  # noqa: E402
import cs2_ratings as cr  # noqa: E402
import engines  # noqa: E402
from engines import G2_SCALE, INACTIVE_RESET_YEARS  # noqa: E402

HISTORY_TOP = 200
EVENT_TIERS = {"1": "S", "2": "A", "3": "B", "4": "C"}  # Liquipedia's tier letters
TRACKED_TIERS = ("1", "2")                              # events page: S- and A-tier main events
TITLE_TIERS = ("1", "2", "3")                           # titles on team pages
G_VRS = 1 / math.sqrt(1 + 3 * (math.log(10) / 400) ** 2 * 75 ** 2 / math.pi ** 2)  # Valve's Glicko, RD fixed at 75
RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vrs_runner.js")


def rank_of(pool, score):
    order = sorted(pool, key=lambda p: (-score[p], p))
    return {p: i + 1 for i, p in enumerate(order)}


def weeks_at_one(series):
    """[(week index, team)] for #1 each week -> {team: (weeks, longest streak, first week, last week)}."""
    out, prev_p, prev_w, run = {}, None, None, 0
    for w, p in series:
        run = run + 1 if (p == prev_p and prev_w is not None and w == prev_w + 1) else 1
        tot, best, first, _ = out.get(p, (0, 0, w, w))
        out[p] = (tot + 1, max(best, run), first, w)
        prev_p, prev_w = p, w
    return out


def series_key(page):
    """'Intel_Extreme_Masters/2026/Cologne' -> 'Intel_Extreme_Masters/Cologne', 'ESL/Pro_League/Season_24' ->
    'ESL/Pro_League': editions of the same event across years share a key."""
    return re.sub(r"/(19|20)\d\d(?=/|$)|/Season_\d+", "", page)


def series_name(name):
    return re.sub(r"\s+", " ", re.sub(r"\b(19|20)\d\d\b|\bSeason \d+\b", "", name)).strip(" :-") or name


def common_name(editions):
    """The name most editions share ('Intel Extreme Masters Cologne', not the one year it was '... Cologne Major');
    on a tie, the most recent. `editions` are oldest first."""
    names = [series_name(e["name"]) for e in editions]
    counts = Counter(names)
    return max(counts, key=lambda n: (counts[n], max(i for i, x in enumerate(names) if x == n)))


def vrs_stakes(pool):
    pool = min(max(float(pool or 0), 1.0), 1_000_000.0)
    return round(1 / (1 + abs(math.log10(pool / 1_000_000))), 3)  # Valve's curveFunction on the event's prize pool


class Lineups:
    """Which of our rosters a five-player lineup belongs to, around a given time: the roster whose matches in the
    preceding window share the most matches with 3+ of these players (names compared case-insensitively)."""

    def __init__(self, matches):
        self.by_player = defaultdict(list)  # player (lower) -> [(time, match no, roster id)]
        self.exact = {}                      # frozenset(lineup) -> [(time, roster id)]
        for i, m in enumerate(matches):
            for side in (0, 1):
                rid = m["rid"][side]
                lineup = frozenset(p.lower() for p in m["teams"][side]["players"])
                for p in lineup:
                    self.by_player[p].append((m["time"], i * 2 + side, rid))
                self.exact.setdefault(lineup, []).append((m["time"], rid))
        self.times = {p: [x[0] for x in v] for p, v in self.by_player.items()}

    def find(self, players, before, window_days=200):
        key = frozenset(p.lower() for p in players)
        hits = [r for t, r in self.exact.get(key, []) if before - window_days * 86400 <= t <= before]
        if hits:
            return hits[-1]
        per_match, rid_of = Counter(), {}
        for p in key:
            lst, ts = self.by_player.get(p, []), self.times.get(p, [])
            for t, mid, rid in lst[bisect.bisect_left(ts, before - window_days * 86400):bisect.bisect_right(ts, before)]:
                per_match[mid] += 1
                rid_of[mid] = (rid, t)
        votes = Counter()
        latest = {}
        for mid, n in per_match.items():
            if n >= ad.OVERLAP:
                rid, t = rid_of[mid]
                votes[rid] += 1
                latest[rid] = max(latest.get(rid, 0), t)
        if not votes:
            return None
        return max(votes, key=lambda r: (votes[r], latest[r]))


def run_valve(valve, vi, tmp):
    import subprocess
    infile, outfile = os.path.join(tmp, "in.json"), os.path.join(tmp, "out.json")
    with open(infile, "w", encoding="utf-8") as fh:
        json.dump(vi, fh)
    subprocess.run(["node", RUNNER, os.path.abspath(valve), infile, outfile, "--players"], check=True,
                   cwd=os.path.join(os.path.abspath(valve), "model"), stdout=subprocess.DEVNULL)
    with open(outfile, encoding="utf-8") as fh:
        return json.load(fh)["players"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cs2")
    ap.add_argument("--valve", default="vendor/vrs")
    ap.add_argument("--current", default="docs/rankings/cs2/data/rankings.json")
    ap.add_argument("--out", default="docs/rankings/cs2/data")
    ap.add_argument("--no-vrs", action="store_true", help="skip the weekly VRS history (faster; for testing)")
    args = ap.parse_args()

    data = ad.load(args.data)
    usable = [m for m in data.matches if ad.usable(m)]
    rosters = ad.assign_rosters(usable)  # same input and order as cs2_ratings.py, so the same roster ids
    roster = {f"r{r.id}": r for r in rosters.list}
    for m in usable:
        m["rid"] = (f"r{m['rosters'][0]}", f"r{m['rosters'][1]}")
    common = ad.to_common(usable)
    by_id = {m["id"]: m for m in usable}
    played = [m for m in sorted(usable, key=lambda m: (m["time"], m["id"])) if not m["walkover"]]
    first_day = datetime.fromtimestamp(played[0]["time"], timezone.utc).replace(tzinfo=None)
    last_day = datetime.fromtimestamp(played[-1]["time"], timezone.utc).replace(tzinfo=None)
    history_from = first_day + timedelta(days=365)
    as_of_date = last_day.strftime("%Y-%m-%d")

    current = {}
    if os.path.exists(args.current):
        with open(args.current, encoding="utf-8") as fh:
            current = {t["id"]: t for t in json.load(fh)["teams"]}

    def person(rid):
        r = roster.get(rid)
        c = current.get(rid, {})
        name = r.name if r else rid
        return {"id": rid, "name": ad.short_name(name), "full": name, "region": c.get("region")}

    # ---------------------------------------------------------------- events
    ev_matches = defaultdict(list)
    for m in played:
        ev_matches[m["event"]].append(m)
    events = {}
    for page, ms in ev_matches.items():
        t = data.tournaments.get(page) or {}
        last = ms[-1]
        finished = (t.get("end") and t["end"] < as_of_date) or (not t and last_day - datetime.fromtimestamp(last["time"], timezone.utc).replace(tzinfo=None) > timedelta(days=14))
        w = last["winner"] - 1
        ws, ls = last["teams"][w]["score"], last["teams"][1 - w]["score"]
        events[page] = {
            "page": page, "name": t.get("name") or last.get("event_name") or page.replace("_", " "),
            "tier": last["tier"], "tiertype": last["tiertype"], "valve": t.get("valve") or last["valve"],
            "lan": bool(t.get("lan")) if t else last["lan"], "start": datetime.fromtimestamp(ms[0]["time"], timezone.utc).strftime("%Y-%m-%d"),
            "end": t.get("end") or datetime.fromtimestamp(last["time"], timezone.utc).strftime("%Y-%m-%d"),
            "pool": t.get("pool") or 0, "teams": t.get("teams"),
            "champion": last["rid"][w] if finished else None, "runner_up": last["rid"][1 - w] if finished else None,
            "score": f"{ws}–{ls}" if isinstance(ws, int) and isinstance(ls, int) else "",
            "status": "finished" if finished else "live",
            "entrants": sorted({r for m in ms for r in m["rid"]}), "match_ids": [m["id"] for m in ms],
        }
    tracked = {p for p, e in events.items() if e["tier"] in TRACKED_TIERS and e["tiertype"] == ""}

    events_by_monday = defaultdict(list)
    for p in tracked:
        d = datetime.strptime(events[p]["start"], "%Y-%m-%d")
        events_by_monday[d - timedelta(days=d.weekday())].append(p)
    ev_stats = defaultdict(dict)  # page -> system -> {"field", "fav", "seed"}

    def event_stats(day, scorer, systems):
        for page in events_by_monday.get(day, []):
            e = events[page]
            for system in systems:
                sc = sorted(((scorer(system, r), r) for r in e["entrants"]), key=lambda x: (-x[0], x[1]))
                ev_stats[page][system] = {"field": sum(v for v, _ in sc[:8]) / min(8, len(sc)), "fav": sc[0][1],
                                          "seed": next((i + 1 for i, (_v, r) in enumerate(sc) if r == e["champion"]), None)}

    # ---------------------------------------------------------------- skill models, weekly (sink while out, then pure)
    SKILL = ("elo", "glicko", "openskill", "glicko_pure", "openskill_pure")
    weeks, hist = [], defaultdict(dict)
    number_one = defaultdict(list)
    WINDOWS = {"2w": last_day - timedelta(days=14), "1m": last_day - timedelta(days=30), "3m": last_day - timedelta(days=91),
               "6m": last_day - timedelta(days=182), "1y": last_day - timedelta(days=365), "2y": last_day - timedelta(days=730),
               "all": history_from}
    peaks = {win: {s_: {} for s_ in SKILL + ("vrs",)} for win in WINDOWS}
    rises = {win: {s_: {} for s_ in SKILL} for win in WINDOWS}

    def keep_max(store, system, rid, v, day):
        for win, start in WINDOWS.items():
            if day >= start:
                cur = store[win][system].get(rid)
                if cur is None or v > cur[0]:
                    store[win][system][rid] = (v, day)
    prev_scores = {}
    week_index_of = {}

    def make_on_week(suffix):
        def on_week(day, elo, g2, osk, last_match, count):
            if day < history_from:
                return
            pool = [p for p, d in last_match.items() if (day - d).days <= cr.ACTIVE_DAYS and count[p] >= cr.MIN_MATCHES]
            if not pool:
                return
            if suffix:
                w = week_index_of.get(day.strftime("%Y-%m-%d"))
                if w is None:
                    return
            else:
                w = len(weeks)
                weeks.append(day.strftime("%Y-%m-%d"))
            scores = {"glicko" + suffix: {p: (g2[p].mu - 2 * g2[p].phi) * G2_SCALE + 1500 for p in pool},
                      "openskill" + suffix: {p: osk[p].ordinal() for p in pool}}
            raw = {"glicko" + suffix: {p: g2[p].mu * G2_SCALE + 1500 for p in pool},
                   "openskill" + suffix: {p: osk[p].mu for p in pool}}
            if not suffix:
                scores["elo"] = raw["elo"] = {p: elo[p] for p in pool}
            ranks = {system: rank_of(pool, sc) for system, sc in scores.items()}
            if day.weekday() == 0 and day in events_by_monday:
                def scorer(system, r):
                    if system == "elo":
                        return elo.get(r, 1500.0)
                    if system.startswith("glicko"):
                        g = g2.get(r)
                        return (g.mu - 2 * g.phi) * G2_SCALE + 1500 if g else 800.0
                    o = osk.get(r)
                    return o.ordinal() if o else 0.0
                event_stats(day, scorer, (["elo"] if not suffix else []) + ["glicko" + suffix, "openskill" + suffix])
            for system, rk in ranks.items():
                if day.weekday() == 0:
                    number_one[system].append((w, min(rk, key=rk.get)))
                for p in pool:
                    keep_max(peaks, system, p, scores[system][p], day)
            for system in raw:
                before = prev_scores.get(system, {})
                for p in pool:
                    if p in before:
                        keep_max(rises, system, p, raw[system][p] - before[p], day)
                prev_scores[system] = raw[system]
            for p in pool:
                row = hist[p].setdefault(w, {})
                for system, rk in ranks.items():
                    row[system] = rk[p]
                if not suffix:
                    row["elo_rating"] = round(elo[p])
        return on_week

    preds, preds_pure = {}, {}
    engines.run(cr.engine_rows(common), first_day, preds, make_on_week(""), inactivity=True, periods_per_year=cr.PERIODS_PER_YEAR)
    week_index_of = {d: i for i, d in enumerate(weeks)}
    engines.run(cr.engine_rows(common), first_day, preds_pure, make_on_week("_pure"), inactivity=False, periods_per_year=cr.PERIODS_PER_YEAR)
    for key, pr in preds_pure.items():
        if key in preds:
            preds[key]["glicko_pure"], preds[key]["openskill_pure"] = pr["glicko"], pr["openskill"]
    for p in list(hist):
        for w in list(hist[p]):
            if min(v for k, v in hist[p][w].items() if k != "elo_rating") > HISTORY_TOP:
                del hist[p][w]
        if not hist[p]:
            del hist[p]
    week_dates = [datetime.strptime(d, "%Y-%m-%d") for d in weeks]
    print(f"history: {len(weeks)} weeks from {weeks[0]} to {weeks[-1]}")

    lineups = Lineups(usable)

    # ---------------------------------------------------------------- Valve's official standings, weekly
    # Valve publishes on the first Monday of each month; each list stays in force until the next one.
    official_hist = defaultdict(dict)  # rid -> week -> rank
    official_by_week = {}              # week -> {rid: rank}
    files = []
    for f in glob.glob(os.path.join(args.valve, "live", "*", "standings_global_*.md")):
        files.append((os.path.basename(f)[len("standings_global_"):-3].replace("_", "-"), f))
    files.sort()
    published = []
    for day, f in files:
        ts = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        ranks_ = {}
        for o in ad.parse_valve_standings(f):
            rid = lineups.find(o["roster"], ts)
            if rid and rid not in ranks_:
                ranks_[rid] = o["rank"]
        published.append((datetime.strptime(day, "%Y-%m-%d"), day, ranks_))
    j = -1
    for w, day in enumerate(week_dates):
        while j + 1 < len(published) and published[j + 1][0] <= day:
            j += 1
        if j < 0:
            continue
        ranks_ = published[j][2]
        official_by_week[w] = ranks_
        if day.weekday() == 0 and ranks_:
            number_one["official"].append((w, min(ranks_, key=ranks_.get)))
        for rid, rk in ranks_.items():
            if rk <= HISTORY_TOP:
                official_hist[rid][w] = rk
    official_from = next((d for d, _f in files if datetime.strptime(d, "%Y-%m-%d") <= last_day), None)
    print(f"Valve standings: {len(published)} published lists, first {files[0][0] if files else None}")

    # ---------------------------------------------------------------- VRS, weekly (Valve's code on each Monday's data)
    vrs_hist = defaultdict(dict)
    vrs_pred = {}  # match id -> P(winner) from that week's Monday VRS
    vrs_weeks = 0
    if not args.no_vrs and os.path.isdir(os.path.join(args.valve, "model")):
        with tempfile.TemporaryDirectory() as tmp:
            for w, day in enumerate(week_dates):
                if day.weekday() != 0:
                    continue
                cutoff = day.replace(tzinfo=timezone.utc)
                vi = ad.valve_input(data, cutoff - timedelta(seconds=1))
                out = run_valve(args.valve, vi, tmp)
                ts = int(cutoff.timestamp())
                res = {}
                for v in out:
                    rid = lineups.find(v.get("players", []), ts)
                    if rid and rid not in res:
                        res[rid] = v
                vrs_weeks += 1
                for m in played:
                    if ts <= m["time"] < ts + 7 * 86400:
                        a, b = m["rid"][m["winner"] - 1], m["rid"][2 - m["winner"]]
                        if a in res and b in res:
                            vrs_pred[m["id"]] = 1 / (1 + 10 ** (-G_VRS * (res[a]["points"] - res[b]["points"]) / 400))
                if day in events_by_monday:
                    event_stats(day, lambda _s, r: res[r]["points"] if r in res else 0.0, ["vrs"])
                if res:
                    number_one["vrs"].append((w, min(res, key=lambda r: res[r]["rank"])))
                for rid, v in res.items():
                    if v["rank"] <= HISTORY_TOP:
                        vrs_hist[rid][w] = v["rank"]
                    keep_max(peaks, "vrs", rid, v["points"], day)
        print(f"VRS history: {vrs_weeks} weeks")

    # ---------------------------------------------------------------- records per match, team facts
    record = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    recent = defaultdict(list)
    prior = Counter()
    upsets = {s_: [] for s_ in SKILL}
    match_days = defaultdict(list)
    for m in played:
        wi = m["winner"] - 1
        wr, lr = m["rid"][wi], m["rid"][1 - wi]
        ev = events[m["event"]]
        day = datetime.fromtimestamp(m["time"], timezone.utc).strftime("%Y-%m-%d")
        pr = preds.get(m["id"], {})
        p_elo = pr.get("elo")
        sw, sl = m["teams"][wi]["score"], m["teams"][1 - wi]["score"]
        score = f"{sw}–{sl}" if isinstance(sw, int) and isinstance(sl, int) else ""
        for rid, won in ((wr, True), (lr, False)):
            rec = record[rid]
            for bucket in ("all", "lan:" + ("LAN" if m["lan"] else "Online"), f"tier:{m['tier']}", f"year:{day[:4]}"):
                rec[bucket][0 if won else 1] += 1
            opp = lr if won else wr
            recent[rid].append({"date": day, "event": ev["name"], "page": m["event"], "tier": m["tier"], "opp": opp,
                                "opp_name": ad.short_name(roster[opp].name), "won": won,
                                "score": score if won else (f"{sl}–{sw}" if score else ""),
                                "p": round(p_elo if won else 1 - p_elo, 3) if p_elo is not None else None})
            if len(recent[rid]) > 30:
                recent[rid].pop(0)
            match_days[rid].append(day)
        # upsets: both teams with 20+ earlier matches (as for tennis) at S-, A- or B-tier events (tennis: tour level)
        if pr and prior[wr] >= 20 and prior[lr] >= 20 and m["tier"] in TITLE_TIERS and day >= history_from.strftime("%Y-%m-%d"):
            for system in SKILL:
                if system in pr:
                    upsets[system].append((pr[system], m["id"]))
        prior[wr] += 1
        prior[lr] += 1
    last_played = {rid: ds[-1] for rid, ds in match_days.items()}

    # ---------------------------------------------------------------- prediction table
    bt_from = last_day - timedelta(days=365)
    methods = ["elo", "glicko", "glicko_pure", "openskill", "openskill_pure", "vrs", "official"]
    if not vrs_pred:
        methods.remove("vrs")
        print("prediction table: no VRS predictions this run; comparing the other methods only")
    tot = {m_: [0, 0.0, 0.0] for m_ in methods}
    used = 0
    for m in played:
        day = datetime.fromtimestamp(m["time"], timezone.utc).replace(tzinfo=None)
        if day < bt_from or m["id"] not in preds or "glicko_pure" not in preds[m["id"]]:
            continue
        if vrs_pred and m["id"] not in vrs_pred:
            continue
        w = bisect.bisect_right(week_dates, day) - 1
        offr = official_by_week.get(w, {})
        a, b = m["rid"][m["winner"] - 1], m["rid"][2 - m["winner"]]
        if a not in offr or b not in offr:
            continue
        used += 1
        probs = {k: preds[m["id"]][k] for k in ("elo", "glicko", "glicko_pure", "openskill", "openskill_pure")}
        probs["vrs"] = vrs_pred.get(m["id"])
        probs["official"] = 0.5 if offr[a] == offr[b] else (1.0 if offr[a] < offr[b] else 0.0)
        for m_ in methods:
            q, t = probs[m_], tot[m_]
            t[0] += 1
            t[1] += 1 if q > 0.5 else (0.5 if q == 0.5 else 0)
            if m_ != "official":
                t[2] += -math.log(min(max(q, 1e-6), 1 - 1e-6))
    backtest = {"from": bt_from.strftime("%Y-%m-%d"), "to": as_of_date, "matches": used,
                "methods": {m_: {"accuracy": round(t[1] / t[0], 4) if t[0] else None,
                                 "log_loss": round(t[2] / t[0], 4) if t[0] and m_ != "official" else None}
                            for m_, t in tot.items()}}
    print("prediction table:", used, "matches", {m_: v["accuracy"] for m_, v in backtest["methods"].items()})

    # ---------------------------------------------------------------- events page data
    def ev_sys(page):
        e = events[page]
        out = {}
        for system, st in ev_stats.get(page, {}).items():
            ps = [vrs_pred.get(i) if system == "vrs" else preds.get(i, {}).get(system) for i in e["match_ids"]]
            ps = [x for x in ps if x is not None]
            out[system] = {"field": round(st["field"], 1 if system.startswith("openskill") else 0), "favourite": person(st["fav"]),
                           "favourite_won": st["fav"] == e["champion"], "seed": st["seed"],
                           "upsets": sum(1 for x in ps if x < UPSET), "predicted": len(ps)}
        return out
    groups = defaultdict(list)
    for page in tracked:
        groups[series_key(page)].append(events[page])
    ev_out = []
    for key, eds in groups.items():
        eds.sort(key=lambda e: e["start"])
        latest = eds[-1]
        ev_out.append({
            "key": key, "name": common_name(eds), "tier": Counter(e["tier"] for e in eds).most_common(1)[0][0],
            "month": int(latest["start"][5:7]),
            "editions": [{"page": e["page"], "year": int(e["start"][:4]), "date": e["start"], "end": e["end"], "name": e["name"],
                          "tier": e["tier"], "valve": e["valve"], "lan": e["lan"], "pool": e["pool"], "teams": e["teams"],
                          "champion": person(e["champion"]) if e["champion"] else None,
                          "runner_up": person(e["runner_up"]) if e["runner_up"] else None, "score": e["score"],
                          "vrs_weight": vrs_stakes(e["pool"]) if e["pool"] else None, "status": e["status"],
                          "matches": len(e["match_ids"]), "sys": ev_sys(e["page"]),
                          "prizes": [{"place": x["place"], "team": ad.short_name(x["team"]), "prize": x["prize"]}
                                     for x in data.placements.get(e["page"], [])[:8]],
                          "liquipedia": "https://liquipedia.net/counterstrike/" + e["page"]} for e in reversed(eds)],
        })
    ev_out.sort(key=lambda t: (t["tier"], t["month"], t["name"]))

    # ---------------------------------------------------------------- titles
    titles, finals_lost = defaultdict(list), Counter()
    for page, e in events.items():
        if e["champion"] and e["tier"] in TITLE_TIERS and e["tiertype"] == "":
            item = {"year": int(e["start"][:4]), "date": e["start"], "name": e["name"], "tier": e["tier"], "valve": e["valve"],
                    "key": series_key(page) if page in tracked else None, "page": page}
            titles[e["champion"]].append(item)
            finals_lost[e["runner_up"]] += 1

    # ---------------------------------------------------------------- records, per window
    def days_out(rid, w):
        day = weeks[w]
        prev = [d for d in match_days[rid] if d < day]
        return (datetime.strptime(day, "%Y-%m-%d") - datetime.strptime(prev[-1], "%Y-%m-%d")).days if prev else None

    linked = set(current)

    def P(rid):
        linked.add(rid)
        return person(rid)

    def records_for(win, start):
        first_w = next((i for i, d in enumerate(week_dates) if d >= start), len(weeks))

        def top_peaks(system, n=15):
            rows_ = sorted(peaks[win][system].items(), key=lambda kv: (-kv[1][0], kv[0]))[:n]
            return [{**P(r), "value": round(v, 1 if system.startswith("openskill") else None), "date": d.strftime("%Y-%m-%d")}
                    for r, (v, d) in rows_]

        no1 = {}
        for system, series in number_one.items():
            if system == "official":
                continue
            stats = weeks_at_one(sorted(x for x in series if x[0] >= first_w))
            rows_ = sorted(stats.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:10]
            if rows_:
                no1[system] = [{**P(r), "weeks": t, "longest": b_, "from": weeks[a_], "to": weeks[z]} for r, (t, b_, a_, z) in rows_]

        def upset_rows(system):
            rows_ = sorted((u for u in upsets[system] if datetime.fromtimestamp(by_id[u[1]]["time"], timezone.utc).replace(tzinfo=None) >= start),
                           key=lambda u: (u[0], u[1]))[:20]
            out = []
            for p, mid in rows_:
                m = by_id[mid]
                wi = m["winner"] - 1
                sw, sl = m["teams"][wi]["score"], m["teams"][1 - wi]["score"]
                out.append({"winner": P(m["rid"][wi]), "loser": P(m["rid"][1 - wi]), "p": round(p, 3),
                            "date": datetime.fromtimestamp(m["time"], timezone.utc).strftime("%Y-%m-%d"),
                            "event": events[m["event"]]["name"], "tier": m["tier"],
                            "score": f"{sw}–{sl}" if isinstance(sw, int) and isinstance(sl, int) else ""})
            return out

        def rise_rows(system, n=15):
            rows_ = sorted(rises[win][system].items(), key=lambda kv: (-kv[1][0], kv[0]))[:n]
            return [{**P(r), "gain": round(g, 1 if system.startswith("openskill") else 0), "week": d.strftime("%Y-%m-%d")}
                    for r, (g, d) in rows_]

        gaps = {s_: {} for s_ in SKILL + ("vrs",)}
        for rid in sorted(set(hist) | set(vrs_hist)):
            for w, off in official_hist[rid].items():
                if w < first_w:
                    continue
                h = hist[rid].get(w, {})
                sys_ranks = {s_: h.get(s_) for s_ in SKILL}
                sys_ranks["vrs"] = vrs_hist[rid].get(w)
                for system, rk in sys_ranks.items():
                    if rk is None or min(rk, off) > 10:
                        continue
                    gap = off - rk
                    if rid not in gaps[system] or abs(gap) > abs(gaps[system][rid][0]):
                        gaps[system][rid] = (gap, rk, off, w)
        gap_rows = {system: [{**P(r), "system_rank": rk, "official_rank": off, "week": weeks[w], "days_out": days_out(r, w)}
                             for r, (g, rk, off, w) in sorted(d.items(), key=lambda kv: (-abs(kv[1][0]), kv[0]))[:15]]
                    for system, d in gaps.items() if d}
        return {"from": weeks[first_w] if first_w < len(weeks) else None, "weeks_at_1": no1,
                "peaks": {s_: top_peaks(s_) for s_ in SKILL + ("vrs",) if peaks[win][s_]},
                "upsets": {s_: upset_rows(s_) for s_ in SKILL}, "rises": {s_: rise_rows(s_) for s_ in SKILL},
                "disagreements": gap_rows}

    records = {
        "period": {"matches_from": first_day.strftime("%Y-%m-%d"), "history_from": weeks[0], "to": weeks[-1],
                   "vrs_from": weeks[min(number_one["vrs"])[0]] if number_one.get("vrs") else None,
                   "official_from": official_from},
        "inactivity": {"reset_years": INACTIVE_RESET_YEARS},
        "windows": {win: records_for(win, start) for win, start in WINDOWS.items()},
    }
    for t in ev_out:
        for e in t["editions"]:
            for k in ("champion", "runner_up"):
                if e[k]:
                    linked.add(e[k]["id"])
            for s in e["sys"].values():
                linked.add(s["favourite"]["id"])

    # ---------------------------------------------------------------- profiles
    # every team the site links to, plus every roster with 15+ matches since the history starts
    since = Counter()
    for m in played:
        if datetime.fromtimestamp(m["time"], timezone.utc).replace(tzinfo=None) >= history_from:
            for r in m["rid"]:
                since[r] += 1
    profile_ids = linked | {r for r, n in since.items() if n >= cr.MIN_MATCHES}
    os.makedirs(os.path.join(args.out, "teams"), exist_ok=True)
    for old in glob.glob(os.path.join(args.out, "teams", "*.json")):
        os.remove(old)
    index = []
    for rid in sorted(profile_ids):
        r = roster.get(rid)
        if r is None:
            continue
        allw = sorted(set(hist[rid]) | set(official_hist[rid]) | set(vrs_hist[rid]))

        def hrow(w):
            h = hist[rid].get(w, {})
            return [w, h.get("elo"), h.get("glicko"), h.get("openskill"), h.get("elo_rating"), vrs_hist[rid].get(w),
                    official_hist[rid].get(w), h.get("glicko_pure"), h.get("openskill_pure")]
        series = [hrow(w) for w in allw]
        cur = current.get(rid, {})
        peak = peaks["all"]["elo"].get(rid)
        best = {s: min((row[i] for row in series if row[i]), default=None)
                for s, i in (("elo", 1), ("glicko", 2), ("openskill", 3), ("vrs", 5), ("official", 6), ("glicko_pure", 7), ("openskill_pure", 8))}
        flags = [ad.countries.iso(data.flags.get(x)) for x in r.players]
        names = [n for n, _c in sorted(r.names_seen.items(), key=lambda kv: -kv[1])]
        prof = {
            **person(rid), "players": r.players, "flags": flags, "names": names,
            "liquipedia": "https://liquipedia.net/counterstrike/" + r.name.replace(" ", "_"),
            "current": {k: cur.get(k) for k in ("elo", "glicko", "glicko_rd", "openskill", "openskill_sigma", "vrs",
                                                 "glicko_pure", "glicko_rd_pure", "openskill_pure", "openskill_sigma_pure",
                                                 "official_rank", "official_points", "ranks", "last_match", "region")},
            "last_match": last_played.get(rid), "matches": r.matches,
            "peak_elo": {"value": round(peak[0]), "date": peak[1].strftime("%Y-%m-%d")} if peak else None,
            "best_rank": best,
            # [week, elo_rank, glicko_rank, openskill_rank, elo_rating, vrs_rank, official_rank, glicko_pure_rank, openskill_pure_rank]
            "history": series,
            "titles": sorted(titles[rid], key=lambda t: t["date"], reverse=True), "finals_lost": finals_lost[rid],
            "record": {k: v for k, v in record[rid].items()},
            "recent": list(reversed(recent[rid][-20:])),
        }
        with open(os.path.join(args.out, "teams", f"{rid}.json"), "w", encoding="utf-8") as fh:
            json.dump(prof, fh, ensure_ascii=False, separators=(",", ":"))
        index.append({**person(rid), "official": cur.get("official_rank"), "elo_rank": (cur.get("ranks") or {}).get("elo"),
                      "players": r.players, "titles": len(titles[rid])})
    has_profile = {x["id"] for x in index}
    for rid in list(recent):
        for x in recent[rid]:
            x["opp_link"] = x["opp"] in has_profile
    # rewrite recent-match links now that the profile set is known (opponents without a profile are shown unlinked)
    for x in index:
        path = os.path.join(args.out, "teams", f"{x['id']}.json")
        with open(path, encoding="utf-8") as fh:
            prof = json.load(fh)
        prof["recent"] = list(reversed(recent[x["id"]][-20:]))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(prof, fh, ensure_ascii=False, separators=(",", ":"))
    index.sort(key=lambda p: (p["official"] or 9999, p["elo_rank"] or 9999, p["name"]))

    def dump(name, obj):
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))

    # ---------------------------------------------------------------- every match of each listed edition (event pages)
    # One file per edition, loaded when someone opens that edition: teams as named at the time, linked to the roster's
    # page when it has one, and each system's pre-match chance for the team that won.
    by_id = {m["id"]: m for m in played}
    os.makedirs(os.path.join(args.out, "events"), exist_ok=True)
    for old in glob.glob(os.path.join(args.out, "events", "*.json")):
        os.remove(old)
    n_files = 0
    for series in ev_out:
        for ed in series["editions"]:
            rows = []
            for mid in events[ed["page"]]["match_ids"]:
                m = by_id.get(mid)
                if not m:
                    continue
                probs = {k: round(v, 3) for k, v in (preds.get(mid) or {}).items() if k in SKILL and v is not None}
                if mid in vrs_pred:
                    probs["vrs"] = round(vrs_pred[mid], 3)
                sides = [{"id": rid, "name": ad.short_name(t["name"]) or person(rid)["name"], "score": t["score"],
                          "link": rid in has_profile} for rid, t in zip(m["rid"], m["teams"])]
                rows.append({"time": m["time"], "bo": m["bestof"], "winner": m["winner"], "teams": sides, "p": probs})
            ed["mfile"] = re.sub(r"[^A-Za-z0-9_-]+", "_", ed["page"])
            dump(os.path.join("events", ed["mfile"] + ".json"), {"page": ed["page"], "name": ed["name"], "matches": rows})
            n_files += 1
    print(f"event matches: {n_files} editions")

    dump("teams_index.json", index)
    dump("records.json", records)
    dump("events.json", {"as_of": as_of_date, "series": ev_out})
    dump("history_meta.json", {"weeks": weeks, "matches_from": first_day.strftime("%Y-%m-%d"), "matches_to": as_of_date,
                               "official_from": official_from})
    dump("backtest.json", backtest)
    listed = set(current)
    pairs, ev_names = defaultdict(list), {}
    for m in played:
        wi = m["winner"] - 1
        w_, l_ = m["rid"][wi], m["rid"][1 - wi]
        if w_ in listed and l_ in listed:
            a_, b_ = sorted((w_, l_))
            sw, sl = m["teams"][wi]["score"], m["teams"][1 - wi]["score"]
            pairs[a_ + "|" + b_].append([datetime.fromtimestamp(m["time"], timezone.utc).strftime("%Y-%m-%d"), m["event"],
                                         0 if w_ == a_ else 1, f"{sw}–{sl}" if isinstance(sw, int) and isinstance(sl, int) else ""])
            e = events[m["event"]]
            ev_names[m["event"]] = [e["name"], e["tier"], series_key(m["event"]) if m["event"] in tracked else None]
    dump("h2h.json", {"events": ev_names, "pairs": pairs})
    print(f"h2h: {len(pairs)} pairs, {sum(len(v) for v in pairs.values())} meetings")
    print(f"profiles {len(index)}, event series {len(ev_out)} ({sum(len(t['editions']) for t in ev_out)} editions)")


if __name__ == "__main__":
    main()
