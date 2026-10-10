#!/usr/bin/env python3
"""Build the data behind the player, records and tournament pages.

    python3 scripts/site_data.py --raw data/raw --rankings data/rankings --prize data/prize_money.json \\
        --valve vendor/vrs --current docs/tennis/data/rankings.json --out docs/tennis/data --start-year 2015

Writes into --out:
    players/<id>.json   one profile per player: ranks over time, Elo over time, titles, record, recent matches
    players_index.json  id, name, country, current official rank (for search and links)
    records.json        per system: weeks at #1, peaks, upsets, weekly rises, gaps from the official rank
    tournaments.json    every tour event by year: champion, field Elo, Elo favourite, upsets, VRS stakes
    history_meta.json   the weekly dates the history arrays refer to

History starts one year after --start-year: the first year only warms the rating models up.
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ratings  # noqa: E402

TOUR = ratings.TOUR_LEVELS
TIER_ORDER = {"G": 0, "F": 1, "M": 2, "500": 3, "250": 4}
ACTIVE_DAYS, MIN_MATCHES, HISTORY_TOP = 180, 20, 200


def iso_of(ioc):
    import vrs_tennis  # same folder; already on sys.path
    return vrs_tennis.IOC_TO_ISO.get((ioc or "").upper())


def rank_of(pool, score):
    order = sorted(pool, key=lambda p: -score[p])
    return {p: i + 1 for i, p in enumerate(order)}


def weeks_at_one(series):
    """series: list of (week_index, player) for #1 each week -> {player: (weeks, longest streak, first, last)}."""
    out = {}
    prev_p, prev_w, run = None, None, 0
    for w, p in series:
        run = run + 1 if (p == prev_p and prev_w is not None and w == prev_w + 1) else 1
        tot, best, first, _ = out.get(p, (0, 0, w, w))
        out[p] = (tot + 1, max(best, run), first, w)
        prev_p, prev_w = p, w
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--rankings", default="data/rankings")
    ap.add_argument("--prize", default="data/prize_money.json")
    ap.add_argument("--valve", default=None)
    ap.add_argument("--current", default="docs/tennis/data/rankings.json")
    ap.add_argument("--out", default="docs/tennis/data")
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--offline", action="store_true", help="no ECB download for VRS history")
    args = ap.parse_args()

    rows = ratings.load(args.raw, args.start_year)
    tour = [r for r in rows if r["tourney_level"] in TOUR and not r["_walkover"]]
    history_from = tour[0]["_date"] + timedelta(days=365)

    # ---------------------------------------------------------------- players' basic facts
    facts = {}
    for r in rows:
        for side in ("winner", "loser"):
            pid = r[f"{side}_id"]
            f = facts.setdefault(pid, {})
            f["name"] = r[f"{side}_name"]
            for k in ("ioc", "hand", "ht"):
                v = r.get(f"{side}_{k}")
                if v:
                    f[k] = v
            age = r.get(f"{side}_age")
            if age:
                try:
                    f["birth"] = r["_date"] - timedelta(days=float(age) * 365.25)
                except ValueError:
                    pass

    # ---------------------------------------------------------------- tournament stats under each system
    # For every event: field strength (mean of the 8 best entrants), favourite and the champion's seed, as each
    # system saw the draw on the Monday of the event's start week. Filled in during the weekly runs below.
    events_by_monday = defaultdict(list)  # Monday -> [(tid, entrants, champion)]
    _by_ev = defaultdict(list)
    for r in tour:
        _by_ev[r["tourney_id"]].append(r)
    for tid, ms in _by_ev.items():
        start = ms[0]["_date"]
        final = next((m for m in ms if m["round"] == "F"), None)
        events_by_monday[start - timedelta(days=start.weekday())].append(
            (tid, {m["winner_id"] for m in ms} | {m["loser_id"] for m in ms}, final["winner_id"] if final else None))
    ev_stats = defaultdict(dict)  # tid -> system -> {"field", "fav", "seed"}

    def event_stats(day, scorer, systems):
        for tid, entrants, champ in events_by_monday.get(day, []):
            for system in systems:
                sc = sorted(((scorer(system, p_), p_) for p_ in entrants), reverse=True)
                ev_stats[tid][system] = {"field": sum(v for v, _ in sc[:8]) / min(8, len(sc)), "fav": sc[0][1],
                                         "seed": next((i + 1 for i, (_v, p_) in enumerate(sc) if p_ == champ), None)}

    # ---------------------------------------------------------------- skill models, weekly
    # Two runs: the site's default (uncertainty grows while a player is out) and the textbook models.
    # Glicko-2 and OpenSkill results from the textbook run are stored under "glicko_pure" / "openskill_pure".
    # Elo is the same in both, so it comes from the first run only.
    SKILL = ("elo", "glicko", "openskill", "glicko_pure", "openskill_pure")
    weeks, hist = [], defaultdict(dict)  # hist[pid][week] = {system: rank, "elo_rating": x}
    number_one = defaultdict(list)       # system -> [(week, pid)]
    # Records are kept for several windows so the page can show recent ones, not only the oldest
    last_day = tour[-1]["_date"]
    WINDOWS = {"2w": last_day - timedelta(days=14), "1m": last_day - timedelta(days=30), "3m": last_day - timedelta(days=91),
               "6m": last_day - timedelta(days=182), "1y": last_day - timedelta(days=365), "2y": last_day - timedelta(days=730),
               "all": history_from}
    peaks = {win: {s_: {} for s_ in SKILL + ("vrs",)} for win in WINDOWS}  # window -> system -> pid -> (value, day)
    rises = {win: {s_: {} for s_ in SKILL} for win in WINDOWS}  # window -> system -> pid -> (gain, week date)

    def keep_max(store, system, pid, v, day):
        for win, start in WINDOWS.items():
            if day >= start:
                cur = store[win][system].get(pid)
                if cur is None or v > cur[0]:
                    store[win][system][pid] = (v, day)
    prev_scores = {}

    def make_on_week(suffix):
        def on_week(day, elo, g2, osk, last_match, count):
            if day < history_from:
                return
            pool = [p for p, d in last_match.items() if (day - d).days <= ACTIVE_DAYS and count[p] >= MIN_MATCHES]
            if not pool:
                return
            if suffix:
                w = week_index_of.get(day.strftime("%Y-%m-%d"))
                if w is None:
                    return
            else:
                w = len(weeks)
                weeks.append(day.strftime("%Y-%m-%d"))
            g_score = {p: (g2[p].mu - 2 * g2[p].phi) * ratings.G2_SCALE + 1500 for p in pool}
            o_score = {p: osk[p].ordinal() for p in pool}
            scores = {"glicko" + suffix: g_score, "openskill" + suffix: o_score}
            # weekly rises use each system's underlying rating, not the cautious "rating minus uncertainty"
            # figure used for ranking, which also moves when the system grows more or less sure of a player
            raw = {"glicko" + suffix: {p: g2[p].mu * ratings.G2_SCALE + 1500 for p in pool},
                   "openskill" + suffix: {p: osk[p].mu for p in pool}}
            if not suffix:
                e_score = {p: elo[p] for p in pool}
                scores["elo"], raw["elo"] = e_score, e_score
            ranks = {system: rank_of(pool, sc) for system, sc in scores.items()}
            if day.weekday() == 0 and day in events_by_monday:
                def scorer(system, p_):
                    if system == "elo":
                        return elo.get(p_, 1500.0)
                    if system.startswith("glicko"):
                        g = g2.get(p_)
                        return (g.mu - 2 * g.phi) * ratings.G2_SCALE + 1500 if g else 800.0  # newcomer: 1500 - 2 x 350
                    o = osk.get(p_)
                    return o.ordinal() if o else 0.0
                event_stats(day, scorer, (["elo"] if not suffix else []) + ["glicko" + suffix, "openskill" + suffix])
            for system, rk in ranks.items():
                if day.weekday() == 0:  # the extra end-of-data snapshot is not a ranking week
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

    week_index_of = {}
    preds, preds_pure = {}, {}
    ratings.run_skill_models(tour, tour[0]["_date"], preds, make_on_week(""), inactivity=True)
    week_index_of = {d: i for i, d in enumerate(weeks)}
    ratings.run_skill_models(tour, tour[0]["_date"], preds_pure, make_on_week("_pure"), inactivity=False)
    for key, pr in preds_pure.items():
        if key in preds:
            preds[key]["glicko_pure"], preds[key]["openskill_pure"] = pr["glicko"], pr["openskill"]
    # keep history rows only for players near the top of some system that week
    for p in list(hist):
        for w in list(hist[p]):
            if min(v for k, v in hist[p][w].items() if k != "elo_rating") > HISTORY_TOP:
                del hist[p][w]
        if not hist[p]:
            del hist[p]
    week_index = week_index_of
    print(f"history: {len(weeks)} weeks from {weeks[0]} to {weeks[-1]}")

    # ---------------------------------------------------------------- official ranking, weekly
    # Published weekly rankings where available. A ranking stays in force until the next one is
    # published (the ATP publishes none in the December off-season), so it is carried forward.
    # After the last published file, the same-date estimate from ratings.official_ranking is used.
    official_hist = defaultdict(dict)  # pid -> week -> rank
    weekly = ratings.load_weekly_rankings(args.rankings)
    published = sorted(d for d in weekly if d >= history_from - timedelta(days=7))
    last_published = published[-1] if published else None
    from datetime import datetime as _dt
    week_dates = [_dt.strptime(d, "%Y-%m-%d") for d in weeks]
    estimated_from = None
    ledger_cache = {}
    j = -1
    for w, day in enumerate(week_dates):
        while j + 1 < len(published) and published[j + 1] <= day:
            j += 1
        if last_published and day <= last_published + timedelta(days=7) and j >= 0:
            snap = sorted(weekly[published[j]])
            entries = [(rk, pid) for rk, pid, _n, _p in snap]
        else:
            if estimated_from is None:
                estimated_from = w
            _, est = ratings.official_ranking(rows, {}, day, "estimated", top_n=HISTORY_TOP, ledger_cache=ledger_cache)
            entries = sorted((rk, pid) for pid, (rk, _pts, _n) in est.items())
        if not entries:
            continue
        if day.weekday() == 0:
            number_one["official"].append((w, entries[0][1]))
        for rk, pid in entries:
            if rk <= HISTORY_TOP:
                official_hist[pid][w] = rk

    # ---------------------------------------------------------------- VRS, weekly (where prize data exists)
    vrs_hist = defaultdict(dict)
    vrs_weight = {}  # filled below
    as_of_day = week_dates[-1]
    bt_from = as_of_day - timedelta(days=365)       # prediction table window: the last 12 months
    bt_matches = []                                   # (match key, P(winner) by VRS) for that window
    vrs_pred = {}                                     # match key -> P(winner) by that Monday's VRS, every VRS week  # event id -> Valve's stakes factor for that event's prize pool (0-1)
    if args.valve and not os.path.isdir(os.path.join(args.valve, "model")):
        print(f"WARN no Valve VRS code in {args.valve}; skipping VRS history this run", file=sys.stderr)
    elif args.valve and os.path.exists(args.prize):
        import tempfile
        import prize_model as pm
        import vrs_backtest
        import vrs_tennis
        with open(args.prize, encoding="utf-8") as fh:
            cache = json.load(fh)
        years = sorted({rec.get("year") for rec in cache.values() if rec.get("year")})
        if years:
            fx = pm.FX({} if args.offline else pm.ecb_yearly_rates())
            data, _ = vrs_tennis.build(args.raw, cache, years[0], fx=fx)
            import math
            for e in data["events"]:
                pool = min(max(float(e["prizePool"].strip("$") or 0), 1.0), 1_000_000.0)
                vrs_weight[e["eventId"]] = round(1 / (1 + abs(math.log10(pool / 1_000_000))), 3)  # Valve's curveFunction
            first_ts = min(m["matchStartTime"] for m in data["matches"])
            start = first_ts + 182 * 86400  # a full 6-month window of priced events
            with tempfile.TemporaryDirectory() as tmp:
                for day in weeks:
                    from datetime import datetime, timezone
                    ts = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
                    if ts < start:
                        continue
                    res = vrs_backtest.run_valve(args.valve, vrs_backtest.snapshot(data, ts), tmp)
                    w = week_index[day]
                    # this Monday's VRS (built from earlier matches only) predicts the coming week's matches
                    for m in data["matches"]:
                        if ts <= m["matchStartTime"] < ts + 7 * 86400:
                            a, b = m["team1Id"], m["team2Id"]  # team1 is the winner in our input
                            if a in res and b in res:
                                gap = res[a]["points"] - res[b]["points"]
                                key_ = (m["eventId"], m["round"], a, b)
                                vrs_pred[key_] = 1 / (1 + 10 ** (-vrs_backtest.G * gap / 400))
                                if week_dates[w] >= bt_from:
                                    bt_matches.append((key_, vrs_pred[key_]))
                    if week_dates[w] in events_by_monday:
                        event_stats(week_dates[w], lambda _s, p_: res[p_]["points"] if p_ in res else 0.0, ["vrs"])
                    best = min(res.values(), key=lambda p: p["rank"]) if res else None
                    if best and week_dates[w].weekday() == 0:
                        number_one["vrs"].append((w, best["id"]))
                    for pid, p in res.items():
                        if p["rank"] <= HISTORY_TOP:
                            vrs_hist[pid][w] = p["rank"]
                        keep_max(peaks, "vrs", pid, p["points"], week_dates[w])
            print(f"VRS history: {len(number_one['vrs'])} weeks")

    # ---------------------------------------------------------------- per-match facts
    events = {}
    by_event = defaultdict(list)
    for r in tour:
        by_event[r["tourney_id"]].append(r)
    for tid, ms in by_event.items():
        name, level, surface = Counter((m["tourney_name"], m["tourney_level"], m["surface"]) for m in ms).most_common(1)[0][0]
        final = next((m for m in ms if m["round"] == "F"), None)
        events[tid] = {"tid": tid, "key": tid.split("-", 1)[1], "year": int(tid[:4]), "date": ms[0]["_date"].strftime("%Y-%m-%d"),
                       "name": name, "level": level, "surface": surface, "draw": ms[0].get("draw_size"),
                       "champion": final["winner_id"] if final else None, "runner_up": final["loser_id"] if final else None,
                       "score": final["score"] if final else None}
        # each system's view of the draw (from the weekly runs) plus its upsets: wins it gave under 25%
        sysd = {}
        for system, st in ev_stats.get(tid, {}).items():
            keys_ = [(tid, m["round"], m["winner_id"], m["loser_id"]) for m in ms]
            ps = [vrs_pred.get(k_) if system == "vrs" else preds.get(k_, {}).get(system) for k_ in keys_]
            ps = [x for x in ps if x is not None]
            sysd[system] = {"field": round(st["field"], 1 if system.startswith("openskill") else 0), "fav": st["fav"],
                            "seed": st["seed"], "upsets": sum(1 for x in ps if x < 0.25), "predicted": len(ps)}
        events[tid]["sys"] = sysd
        events[tid]["matches"] = len(ms)
        if "elo" in sysd:  # Elo figures also kept at the top level (older pages read these)
            e_ = sysd["elo"]
            events[tid].update(field=e_["field"], favourite=e_["fav"], champ_elo_rank=e_["seed"], upsets=e_["upsets"])

    record = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # pid -> bucket -> [w, l]
    recent = defaultdict(list)
    prior = Counter()
    upsets = {s_: [] for s_ in SKILL}
    for r in tour:
        w, l = r["winner_id"], r["loser_id"]
        ev = events[r["tourney_id"]]
        key = (r["tourney_id"], r["round"], w, l)
        pr = preds.get(key, {})
        p = pr.get("elo")
        for pid, won in ((w, True), (l, False)):
            rec = record[pid]
            for bucket in ("all", f"surface:{r['surface']}", f"level:{ev['level']}", f"year:{r['_date'].year}"):
                rec[bucket][0 if won else 1] += 1
            opp = l if won else w
            recent[pid].append({"date": r["_date"].strftime("%Y-%m-%d"), "event": ev["name"], "tid": r["tourney_id"],
                                "level": ev["level"], "round": r["round"], "opp": opp, "opp_name": facts[opp]["name"],
                                "won": won, "score": r["score"], "p": round(p if won else 1 - p, 3) if p is not None else None})
            if len(recent[pid]) > 30:
                recent[pid].pop(0)
        if pr and prior[w] >= MIN_MATCHES and prior[l] >= MIN_MATCHES and r["_date"] >= history_from:
            for system in SKILL:
                if system in pr:
                    upsets[system].append((pr[system], key, r))
        prior[w] += 1
        prior[l] += 1

    match_days = defaultdict(list)  # pid -> sorted match dates (ISO)
    for r in tour:
        d = r["_date"].strftime("%Y-%m-%d")
        for pid in (r["winner_id"], r["loser_id"]):
            match_days[pid].append(d)
    last_played = {pid: ds[-1] for pid, ds in match_days.items()}

    def _date(iso):
        from datetime import datetime
        return datetime.strptime(iso, "%Y-%m-%d")

    def person(pid):
        f = facts.get(pid, {})
        return {"id": pid, "name": f.get("name", pid), "iso": iso_of(f.get("ioc"))}

    # ---------------------------------------------------------------- prediction table
    # Every method predicts the same matches: the last 12 months, where VRS (rebuilt each Monday from
    # earlier matches) ranks both players and both have an official rank on the match row.
    import math as _math
    off_rank = {}
    for r in tour:
        wr, lr = r.get("winner_rank") or "", r.get("loser_rank") or ""
        if wr.isdigit() and lr.isdigit():
            off_rank[(r["tourney_id"], r["round"], r["winner_id"], r["loser_id"])] = (int(wr), int(lr))
    methods = ["elo", "glicko", "glicko_pure", "openskill", "openskill_pure", "vrs", "official"]
    tot = {m_: [0, 0.0, 0.0] for m_ in methods}  # n, right, log loss
    used = 0
    if not bt_matches:  # no VRS this run (e.g. Valve's code unavailable): compare the other methods on their own
        methods = [m_ for m_ in methods if m_ != "vrs"]
        bt_matches = [((r["tourney_id"], r["round"], r["winner_id"], r["loser_id"]), None) for r in tour if r["_date"] >= bt_from]
        tot.pop("vrs", None)
        print("prediction table: no VRS predictions this run; comparing the other methods only")
    for key, p_vrs in bt_matches:
        if key not in preds or key not in off_rank or "glicko_pure" not in preds[key]:
            continue
        used += 1
        wr, lr = off_rank[key]
        probs = {**{m_: preds[key][m_] for m_ in ("elo", "glicko", "glicko_pure", "openskill", "openskill_pure")}, "vrs": p_vrs,
                 "official": 0.5 if wr == lr else (1.0 if wr < lr else 0.0)}
        for m_ in methods:
            q = probs[m_]
            t = tot[m_]
            t[0] += 1
            t[1] += 1 if q > 0.5 else (0.5 if q == 0.5 else 0)
            if m_ != "official":
                t[2] += -_math.log(min(max(q, 1e-6), 1 - 1e-6))
    backtest = {"from": bt_from.strftime("%Y-%m-%d"), "to": as_of_day.strftime("%Y-%m-%d"), "matches": used,
                "methods": {m_: {"accuracy": round(t[1] / t[0], 4) if t[0] else None,
                                 "log_loss": round(t[2] / t[0], 4) if t[0] and m_ != "official" else None}
                            for m_, t in tot.items()}}
    print("prediction table:", used, "matches", {m_: v["accuracy"] for m_, v in backtest["methods"].items()})

    # ---------------------------------------------------------------- tournaments
    tours = defaultdict(list)
    for ev in events.values():
        tours[ev["key"]].append(ev)
    tournaments = []
    for key, eds in tours.items():
        eds.sort(key=lambda e: e["year"])
        level = Counter(e["level"] for e in eds).most_common(1)[0][0]  # majority across editions fixes stray labels
        latest = eds[-1]
        tournaments.append({
            "key": key, "name": latest["name"], "level": level, "surface": latest["surface"],
            "month": int(latest["date"][5:7]),
            "editions": [{"year": e["year"], "date": e["date"], "name": e["name"], "surface": e["surface"],
                          "champion": person(e["champion"]) if e["champion"] else None,
                          "runner_up": person(e["runner_up"]) if e["runner_up"] else None,
                          "score": e["score"], "field": e.get("field"),
                          "favourite": person(e["favourite"]) if e.get("favourite") else None,
                          "favourite_won": bool(e.get("favourite") and e["favourite"] == e["champion"]),
                          "champ_elo_rank": e.get("champ_elo_rank"), "upsets": e.get("upsets"), "matches": e.get("matches"),
                          "vrs_weight": vrs_weight.get(e["tid"]),
                          "sys": {k_: {"field": v_["field"], "favourite": person(v_["fav"]), "favourite_won": v_["fav"] == e["champion"],
                                       "seed": v_["seed"], "upsets": v_["upsets"], "predicted": v_["predicted"]}
                                  for k_, v_ in e.get("sys", {}).items()},
                          # finished, live (no final yet, started in the last 3 weeks), or no_final (final missing from the data)
                          "status": "finished" if e["champion"] else
                                    ("live" if (last_day - _date(e["date"])).days <= 21 else "no_final")} for e in reversed(eds)],
        })
    tournaments.sort(key=lambda t: (TIER_ORDER.get(t["level"], 9), t["month"], t["name"]))

    # ---------------------------------------------------------------- titles per player
    titles = defaultdict(list)
    finals_lost = defaultdict(list)
    for ev in events.values():
        if ev["champion"]:
            item = {"year": ev["year"], "date": ev["date"], "name": ev["name"], "level": ev["level"],
                    "surface": ev["surface"], "key": ev["key"]}
            titles[ev["champion"]].append(item)
            finals_lost[ev["runner_up"]].append(item)

    # ---------------------------------------------------------------- current ranks
    current = {}
    if os.path.exists(args.current):
        with open(args.current, encoding="utf-8") as fh:
            for p in json.load(fh)["players"]:
                current[p["id"]] = p

    # ---------------------------------------------------------------- profiles
    os.makedirs(os.path.join(args.out, "players"), exist_ok=True)
    profile_ids = {p for p in prior if prior[p] >= 1}  # everyone with a tour-level match, so every link works
    index = []
    for pid in profile_ids:
        f = facts.get(pid, {})
        allw = sorted(set(hist[pid]) | set(official_hist[pid]) | set(vrs_hist[pid]))
        def hrow(w):
            h = hist[pid].get(w, {})
            return [w, h.get("elo"), h.get("glicko"), h.get("openskill"), h.get("elo_rating"), vrs_hist[pid].get(w),
                    official_hist[pid].get(w), h.get("glicko_pure"), h.get("openskill_pure")]
        series = [hrow(w) for w in allw]
        cur = current.get(pid, {})
        peak = peaks["all"]["elo"].get(pid)
        best = {s: min((row[i] for row in series if row[i]), default=None)
                for s, i in (("elo", 1), ("glicko", 2), ("openskill", 3), ("vrs", 5), ("official", 6),
                             ("glicko_pure", 7), ("openskill_pure", 8))}
        prof = {
            **person(pid), "ioc": f.get("ioc"), "hand": f.get("hand"), "height": f.get("ht"),
            "age": round((tour[-1]["_date"] - f["birth"]).days / 365.25, 1) if f.get("birth") else None,
            "current": {k: cur.get(k) for k in ("elo", "glicko", "glicko_rd", "openskill", "openskill_sigma", "vrs",
                                                 "glicko_pure", "glicko_rd_pure", "openskill_pure", "openskill_sigma_pure",
                                                 "official_rank", "official_points", "ranks", "last_match")},
            "last_match": last_played.get(pid),
            "peak_elo": {"value": round(peak[0]), "date": peak[1].strftime("%Y-%m-%d")} if peak else None,
            "best_rank": best,
            # [week, elo_rank, glicko_rank, openskill_rank, elo_rating, vrs_rank, official_rank, glicko_pure_rank, openskill_pure_rank]
            "history": series,
            "titles": sorted(titles[pid], key=lambda t: t["date"], reverse=True),
            "finals_lost": len(finals_lost[pid]),
            "record": {k: v for k, v in record[pid].items()},
            "recent": list(reversed(recent[pid][-20:])),
        }
        with open(os.path.join(args.out, "players", f"{pid}.json"), "w", encoding="utf-8") as fh:
            json.dump(prof, fh, ensure_ascii=False, separators=(",", ":"))
        index.append({**person(pid), "official": cur.get("official_rank"), "elo_rank": (cur.get("ranks") or {}).get("elo"),
                      "titles": len(titles[pid])})
    index.sort(key=lambda p: (p["official"] or 9999, p["elo_rank"] or 9999, p["name"]))

    # ---------------------------------------------------------------- records, per window
    def days_out(pid, w):
        """days since the player's previous tour-level match, as of that week's Monday"""
        day = weeks[w]
        prev = [d for d in match_days[pid] if d < day]
        return (_date(day) - _date(prev[-1])).days if prev else None

    def records_for(win, start):
        first_w = next((i for i, d in enumerate(week_dates) if d >= start), len(weeks))

        def top_peaks(system, n=15):
            rows_ = sorted(peaks[win][system].items(), key=lambda kv: -kv[1][0])[:n]
            return [{**person(p), "value": round(v, 1 if system.startswith("openskill") else None), "date": d.strftime("%Y-%m-%d")}
                    for p, (v, d) in rows_]

        no1 = {}
        for system, series in number_one.items():
            if system == "official":
                continue
            stats = weeks_at_one(sorted(x for x in series if x[0] >= first_w))
            rows_ = sorted(stats.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))[:10]
            if rows_:
                no1[system] = [{**person(p), "weeks": t, "longest": b_, "from": weeks[a_], "to": weeks[z]}
                               for p, (t, b_, a_, z) in rows_]

        def upset_rows(system):
            rows_ = sorted((u for u in upsets[system] if u[2]["_date"] >= start), key=lambda u: u[0])[:20]
            return [{"winner": person(k[2]), "loser": person(k[3]), "p": round(p, 3), "date": r["_date"].strftime("%Y-%m-%d"),
                     "event": events[k[0]]["name"], "level": events[k[0]]["level"], "round": k[1], "score": r["score"]}
                    for p, k, r in rows_]

        def rise_rows(system, n=15):
            rows_ = sorted(rises[win][system].items(), key=lambda kv: -kv[1][0])[:n]
            return [{**person(p), "gain": round(g, 1 if system.startswith("openskill") else 0), "week": d.strftime("%Y-%m-%d")}
                    for p, (g, d) in rows_]

        # where a system and the official ranking disagree most, among players in either's top 10
        gaps = {s_: {} for s_ in SKILL + ("vrs",)}
        for pid in set(hist) | set(vrs_hist):
            for w, off in official_hist[pid].items():
                if w < first_w:
                    continue
                h = hist[pid].get(w, {})
                sys_ranks = {s_: h.get(s_) for s_ in SKILL}
                sys_ranks["vrs"] = vrs_hist[pid].get(w)
                for system, rk in sys_ranks.items():
                    if rk is None or min(rk, off) > 10:
                        continue
                    gap = off - rk
                    if pid not in gaps[system] or abs(gap) > abs(gaps[system][pid][0]):
                        gaps[system][pid] = (gap, rk, off, w)
        gap_rows = {system: [{**person(p), "system_rank": rk, "official_rank": off, "week": weeks[w], "days_out": days_out(p, w)}
                             for p, (g, rk, off, w) in sorted(d.items(), key=lambda kv: -abs(kv[1][0]))[:15]]
                    for system, d in gaps.items() if d}
        return {
            "from": weeks[first_w] if first_w < len(weeks) else None,
            "weeks_at_1": no1,
            "peaks": {s_: top_peaks(s_) for s_ in SKILL + ("vrs",) if peaks[win][s_]},
            "upsets": {s_: upset_rows(s_) for s_ in SKILL},
            "rises": {s_: rise_rows(s_) for s_ in SKILL},
            "disagreements": gap_rows,
        }

    records = {
        "period": {"matches_from": tour[0]["_date"].strftime("%Y-%m-%d"), "history_from": weeks[0], "to": weeks[-1],
                   "vrs_from": weeks[min(number_one["vrs"])[0]] if number_one.get("vrs") else None},
        "inactivity": {"reset_years": ratings.INACTIVE_RESET_YEARS},
        "windows": {win: records_for(win, start) for win, start in WINDOWS.items()},
    }

    def dump(name, obj):
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))

    dump("players_index.json", index)
    dump("records.json", records)
    dump("tournaments.json", {"as_of": last_day.strftime("%Y-%m-%d"), "tournaments": tournaments})
    dump("history_meta.json", {"weeks": weeks, "official_estimated_from": estimated_from,
                               # coverage of the match data, shown on player pages so title counts are not mistaken for career totals
                               "matches_from": tour[0]["_date"].strftime("%Y-%m-%d"), "matches_to": tour[-1]["_date"].strftime("%Y-%m-%d")})
    dump("backtest.json", backtest)
    # head-to-head meetings between players listed in rankings.json (the Predict page's choices)
    # compact: pairs "idA|idB" (ids sorted) -> [[date, event id, round, 0 if idA won else 1, score]], events -> [name, tier, key]
    listed = set(current)
    pairs, ev_names = defaultdict(list), {}
    for r in tour:
        w, l = r["winner_id"], r["loser_id"]
        if w in listed and l in listed:
            ev = events[r["tourney_id"]]
            a_, b_ = sorted((w, l))
            pairs[a_ + "|" + b_].append([r["_date"].strftime("%Y-%m-%d"), r["tourney_id"], r["round"], 0 if w == a_ else 1, r["score"]])
            ev_names[r["tourney_id"]] = [ev["name"], ev["level"], ev["key"]]
    dump("h2h.json", {"events": ev_names, "pairs": pairs})
    print(f"h2h: {len(pairs)} pairs, {sum(len(v) for v in pairs.values())} meetings")
    print(f"profiles {len(index)}, tournaments {len(tournaments)}")


if __name__ == "__main__":
    main()
