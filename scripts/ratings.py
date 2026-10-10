#!/usr/bin/env python3
"""Tennis rating engine: Elo, Glicko-2, OpenSkill and an ATP-style 52-week points ledger.

Reads TennisMyLife-style (Sackmann-schema) yearly CSVs from a folder and writes one JSON file.

    python3 scripts/ratings.py --raw data/raw --out docs/data/tennis.json --start-year 2015

Design notes
- Skill models (Elo, Glicko-2, OpenSkill) run over tour-level matches since --start-year.
  The early years are burn-in: everybody starts equal, so only recent ratings are shown.
- The ATP-style ledger is NOT a skill model. It sums points by tournament tier and round
  reached over the last 52 weeks (best 19 results). It approximates the official system.
- Official ATP rank/points are read from the rank columns on each player's latest match row.
"""
import argparse
import csv
import glob
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from openskill.models import PlackettLuce

TOUR_LEVELS = {"G", "M", "500", "250", "F"}  # Slams, Masters 1000, 500s, 250s, ATP Finals
ROUND_ORDER = {"RR": 0, "R128": 1, "R64": 2, "R32": 3, "R16": 4, "QF": 5, "SF": 6, "BR": 7, "F": 8}

# Points by round of loss, per tier (ITF 2024 ATP points table). First-round exits are
# handled separately: 10 at Slams/Masters, 0 at 500s/250s.
POINTS = {
    "G": {"W": 2000, "F": 1300, "SF": 800, "QF": 400, "R16": 200, "R32": 100, "R64": 50, "R128": 10},
    "M": {"W": 1000, "F": 650, "SF": 400, "QF": 200, "R16": 100, "R32": 50, "R64": 30, "R128": 10},
    "500": {"W": 500, "F": 330, "SF": 200, "QF": 100, "R16": 50, "R32": 25},
    "250": {"W": 250, "F": 165, "SF": 100, "QF": 50, "R16": 25, "R32": 13},
}
FIRST_ROUND_POINTS = {"G": 10, "M": 10, "500": 0, "250": 0}
BEST_N = 19

ELO_K = 32
G2_TAU = 0.5
G2_SCALE = 173.7178

# Inactivity (the site's default; inactivity=False gives the textbook models, also published). Elo has no uncertainty,
# so only Glicko-2 and OpenSkill change: for every month (Glicko-2) or week (OpenSkill) a player has
# no match, their uncertainty grows, at a rate that would take it from zero back to a newcomer's
# level in INACTIVE_RESET_YEARS. Both rank by a cautious value (rating - 2 RD, mu - 3 sigma), so
# absent players slide down gradually. Uncertainty never goes above a newcomer's.
INACTIVE_RESET_YEARS = 5
G2_PHI_MAX = 350 / G2_SCALE
G2_INACTIVE_C2 = G2_PHI_MAX ** 2 / (12 * INACTIVE_RESET_YEARS)    # added to phi^2 per month without a match
OSK_SIGMA_MAX = 25 / 3
OSK_INACTIVE_TAU2 = OSK_SIGMA_MAX ** 2 / (52 * INACTIVE_RESET_YEARS)  # added to sigma^2 per week without a match


def first_round_label(draw_size):
    n = 1
    while n < draw_size:
        n *= 2
    return f"R{n}"


# ----------------------------------------------------------------------------- loading
def year_of(path):
    m = re.match(r"^(?:tml_)?(\d{4})\.csv$", os.path.basename(path))
    return int(m.group(1)) if m else None


def load(raw_dir, start_year):
    paths = sorted(glob.glob(os.path.join(raw_dir, "*.csv")))
    year_files = [p for p in paths if year_of(p) is not None]
    other = [p for p in paths if os.path.basename(p) == "ongoing_tourneys.csv"]
    seen = set()
    out = []
    for path in year_files + other:  # year files win over the ongoing-tournament file
        y = year_of(path)
        if y is not None and y < start_year:
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                # match_num is blank for some events, so identify a match by who played whom in which round
                key = (r.get("tourney_id"), r.get("round"), r.get("winner_id"), r.get("loser_id"))
                if key in seen or not r.get("tourney_date") or not r.get("winner_id") or not r.get("loser_id"):
                    continue
                seen.add(key)
                try:
                    r["_date"] = datetime.strptime(r["tourney_date"], "%Y%m%d")
                    r["_mn"] = int(r.get("match_num") or 0)
                except ValueError:
                    continue
                score = (r.get("score") or "").upper()
                r["_walkover"] = "W/O" in score or "DEF" in score
                out.append(r)
    out.sort(key=lambda r: (r["_date"], r["tourney_id"], ROUND_ORDER.get(r["round"], 9), r["_mn"]))
    return out


# ----------------------------------------------------------------------------- Glicko-2
class G2:
    __slots__ = ("mu", "phi", "sigma")

    def __init__(self):
        self.mu, self.phi, self.sigma = 0.0, 350 / G2_SCALE, 0.06


def g_fn(phi):
    return 1 / math.sqrt(1 + 3 * phi * phi / math.pi ** 2)


def g2_update(p, games, extra=0.0):
    """One Glicko-2 rating period. extra: added to phi^2 when the player had no games (inactivity variant)."""
    if not games:
        p.phi = min(math.sqrt(p.phi ** 2 + p.sigma ** 2 + extra), G2_PHI_MAX)
        return
    v_inv = d_sum = 0.0
    for muj, phij, s in games:
        gj = g_fn(phij)
        e = 1 / (1 + math.exp(-gj * (p.mu - muj)))
        v_inv += gj ** 2 * e * (1 - e)
        d_sum += gj * (s - e)
    v = 1 / v_inv
    delta = v * d_sum
    a = math.log(p.sigma ** 2)

    def f(x):
        ex = math.exp(x)
        return (ex * (delta ** 2 - p.phi ** 2 - v - ex)) / (2 * (p.phi ** 2 + v + ex) ** 2) - (x - a) / G2_TAU ** 2

    A = a
    if delta ** 2 > p.phi ** 2 + v:
        B = math.log(delta ** 2 - p.phi ** 2 - v)
    else:
        k = 1
        while f(a - k * G2_TAU) < 0:
            k += 1
        B = a - k * G2_TAU
    fA, fB = f(A), f(B)
    for _ in range(100):
        if abs(B - A) < 1e-6:
            break
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB <= 0:
            A, fA = B, fB
        else:
            fA /= 2
        B, fB = C, fC
    sigma_new = math.exp(A / 2)
    phi_star = math.sqrt(p.phi ** 2 + sigma_new ** 2)
    phi_new = 1 / math.sqrt(1 / phi_star ** 2 + 1 / v)
    p.mu += phi_new ** 2 * d_sum
    p.phi, p.sigma = phi_new, sigma_new


# ----------------------------------------------------------------------------- skill models
def months_between(a, b):
    """'YYYYMM' strings -> number of month steps from a to b."""
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[4:6]) - int(a[4:6])


def run_skill_models(matches, backtest_from, preds=None, weekly=None, inactivity=True):
    """weekly(monday, elo, g2, osk, last_match, count) is called once per week, before that week's matches.
    inactivity=True grows Glicko-2 / OpenSkill uncertainty while a player is not playing (see constants)."""
    elo = defaultdict(lambda: 1500.0)
    g2 = defaultdict(G2)
    model = PlackettLuce()
    osk = {}
    pending = defaultdict(list)
    period = None
    bt = {m: {"n": 0, "correct": 0, "logloss": 0.0} for m in ("elo", "glicko", "openskill")}
    extra = G2_INACTIVE_C2 if inactivity else 0.0

    def flush():
        snap = {k: (v.mu, v.phi) for k, v in g2.items()}
        for k in list(g2):
            g2_update(g2[k], [(snap[o][0], snap[o][1], s) for o, s in pending.get(k, [])], extra)
        pending.clear()

    def record(name, p_winner):
        p = min(max(p_winner, 1e-6), 1 - 1e-6)
        bt[name]["n"] += 1
        bt[name]["correct"] += 1 if p > 0.5 else 0
        bt[name]["logloss"] += -math.log(p)

    last_match = {}
    count = defaultdict(int)
    next_week = None

    def tick(monday):
        # OpenSkill: one week of extra uncertainty for everyone without a match in the week just ended
        if inactivity:
            since = monday - timedelta(days=7)
            for pid, rt in osk.items():
                if last_match.get(pid, since) < since:
                    rt.sigma = min(math.sqrt(rt.sigma ** 2 + OSK_INACTIVE_TAU2), OSK_SIGMA_MAX)
        if weekly is not None:
            weekly(monday, elo, g2, osk, last_match, count)

    for r in matches:
        if r["_walkover"] or r["tourney_level"] not in TOUR_LEVELS:
            continue
        if next_week is None:
            next_week = r["_date"] + timedelta(days=(7 - r["_date"].weekday()) % 7 or 7)
        while next_week <= r["_date"]:
            tick(next_week)
            next_week += timedelta(days=7)
        per = r["tourney_date"][:6]
        if period is None:
            period = per
        if per != period:
            flush()
            # months with no tour matches at all (the December break) are still rating periods
            for _ in range(months_between(period, per) - 1):
                flush()
            period = per
        w, l = r["winner_id"], r["loser_id"]
        if w not in osk:
            osk[w] = model.rating()
        if l not in osk:
            osk[l] = model.rating()
        _ = g2[w], g2[l]

        if r["_date"] >= backtest_from:
            p_elo = 1 / (1 + 10 ** ((elo[l] - elo[w]) / 400))
            record("elo", p_elo)
            phi = math.sqrt(g2[w].phi ** 2 + g2[l].phi ** 2)
            record("glicko", 1 / (1 + math.exp(-g_fn(phi) * (g2[w].mu - g2[l].mu))))
            p_osk = model.predict_win([[osk[w]], [osk[l]]])[0]
            record("openskill", p_osk)
            if preds is not None:  # per-match winner probabilities, for comparisons in other scripts
                p_g2 = 1 / (1 + math.exp(-g_fn(phi) * (g2[w].mu - g2[l].mu)))
                preds[(r["tourney_id"], r["round"], w, l)] = {"elo": p_elo, "glicko": p_g2, "openskill": p_osk}

        e = 1 / (1 + 10 ** ((elo[l] - elo[w]) / 400))
        elo[w] += ELO_K * (1 - e)
        elo[l] -= ELO_K * (1 - e)
        pending[w].append((l, 1.0))
        pending[l].append((w, 0.0))
        (nw,), (nl,) = model.rate([[osk[w]], [osk[l]]], ranks=[0, 1])
        osk[w], osk[l] = nw, nl
        for pid in (w, l):
            last_match[pid] = r["_date"]
            count[pid] += 1
    flush()
    if weekly is not None and last_match:
        weekly(max(last_match.values()), elo, g2, osk, last_match, count)  # state after the latest matches
    return elo, g2, osk, last_match, count, bt


# ----------------------------------------------------------------------------- points ledger
def ledger(matches, as_of, include_as_of_week=True):
    """Return {player_id: points} using the best BEST_N results in the last 52 weeks.

    include_as_of_week=False gives the ranking as published on the Monday of as_of: last year's
    results from that week have dropped out, and this week's results do not count yet.
    """
    window_start = as_of - timedelta(days=364)
    results = {}  # (pid, tourney_id) -> (date, points)
    finals_wins = defaultdict(lambda: [0, 0, 0])  # rr wins, sf win, f win

    for r in matches:
        lvl = r["tourney_level"]
        in_window = window_start < r["_date"] <= as_of if include_as_of_week else window_start < r["_date"] < as_of
        if lvl not in TOUR_LEVELS or not in_window:
            continue
        tid, rd = r["tourney_id"], r["round"]
        if lvl == "F":
            slot = {"RR": 0, "SF": 1, "F": 2}.get(rd)
            if slot is not None:
                finals_wins[(r["winner_id"], tid)][slot] += 1
                results.setdefault((r["winner_id"], tid), (r["_date"], 0))
                results.setdefault((r["loser_id"], tid), (r["_date"], 0))
            continue
        table = POINTS[lvl]
        draw = int(r.get("draw_size") or 0) or 32
        if rd == first_round_label(draw):
            loser_pts = FIRST_ROUND_POINTS[lvl]
        else:
            loser_pts = table.get(rd, 0)
        key = (r["loser_id"], tid)
        old = results.get(key, (r["_date"], 0))[1]
        results[key] = (r["_date"], max(old, loser_pts))
        if rd == "F":
            wkey = (r["winner_id"], tid)
            results[wkey] = (r["_date"], table["W"])

    for (pid, tid), (rr, sf, f) in finals_wins.items():
        pts = 200 * rr + 400 * min(sf, 1) + 500 * min(f, 1)
        results[(pid, tid)] = (results[(pid, tid)][0], pts)

    per_player = defaultdict(list)
    for (pid, _tid), (_d, pts) in results.items():
        per_player[pid].append(pts)
    return {pid: sum(sorted(v, reverse=True)[:BEST_N]) for pid, v in per_player.items()}


# ----------------------------------------------------------------------------- official ranking
def load_weekly_rankings(folder):
    """Read TML weekly ranking CSVs (date,rank,name,id,points) into {date: [(rank, id, name, points)]}."""
    out = defaultdict(list)
    if not folder or not os.path.isdir(folder):
        return {}
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                d, rk, pts = r.get("date") or "", r.get("rank") or "", r.get("points") or ""
                if not (d.isdigit() and rk.isdigit()):
                    continue  # the source files contain the odd repeated header row
                out[datetime.strptime(d, "%Y%m%d")].append((int(rk), r["id"], r["name"], int(pts) if pts.isdigit() else None))
    return dict(out)


def official_ranking(all_rows, weekly, as_of, mode="auto", max_age_days=10, top_n=150, ledger_cache=None):
    """Return (info, {player_id: (rank, points, name)}).

    weekly:    use the newest weekly ATP ranking snapshot (exact, one date for everyone).
    estimated: when no recent snapshot exists. Each player's last known official points (from the
               rank columns of their latest match), plus ATP-style points earned since, minus points
               that dropped out of the 52-week window since. Everyone is moved to the same date.
    """
    if mode in ("auto", "weekly") and weekly:
        usable = [d for d in weekly if d <= as_of + timedelta(days=10)]
        if usable:
            d = max(usable)
            if mode == "weekly" or abs((as_of - d).days) <= max_age_days:
                snap = sorted(weekly[d])[:top_n]
                return ({"mode": "weekly", "date": d.strftime("%Y-%m-%d")},
                        {pid: (rk, pts, name) for rk, pid, name, pts in snap})

    latest = {}  # pid -> (date, points, name); rows are in date order
    for r in all_rows:
        for side in ("winner", "loser"):
            pts = r.get(f"{side}_rank_points") or ""
            if pts.isdigit():
                latest[r[f"{side}_id"]] = (r["_date"], int(pts), r[f"{side}_name"])
    cache = ledger_cache if ledger_cache is not None else {}  # ledger at a date never changes; share it across calls

    def led(d):
        if d not in cache:
            cache[d] = ledger(all_rows, d, include_as_of_week=False)
        return cache[d]

    now = ledger(all_rows, as_of)
    est = {}
    for pid, (d0, p0, name) in latest.items():
        if (as_of - d0).days > 364:
            continue
        # the points printed on a match row are the ranking of that week, before that event counts
        before = led(d0).get(pid, 0)
        est[pid] = (max(p0 + now.get(pid, 0) - before, 0), name)
    order = sorted(est, key=lambda p: (-est[p][0], est[p][1]))[:top_n]
    return ({"mode": "estimated", "date": as_of.strftime("%Y-%m-%d")},
            {pid: (i + 1, est[pid][0], est[pid][1]) for i, pid in enumerate(order)})


# ----------------------------------------------------------------------------- main
def rank_map(pool, score):
    order = sorted(pool, key=lambda p: -score.get(p, -1e18))
    return {p: i + 1 for i, p in enumerate(order)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--min-matches", type=int, default=20)
    ap.add_argument("--active-days", type=int, default=180)
    ap.add_argument("--backtest-months", type=int, default=12)
    ap.add_argument("--rankings", default=None, help="folder with TML weekly ranking CSVs (optional)")
    ap.add_argument("--official-mode", choices=["auto", "weekly", "estimated"], default="auto")
    ap.add_argument("--vrs", default=None, help="output of scripts/vrs_tennis.py (optional)")
    args = ap.parse_args()

    # read every row once for official ranks (any level), then restrict to tour level
    all_rows = load(args.raw, args.start_year)
    if not all_rows:
        sys.exit("no matches loaded")
    tour_dates = [r["_date"] for r in all_rows if r["tourney_level"] in TOUR_LEVELS]
    if not tour_dates:
        sys.exit("no tour-level matches loaded")
    as_of = max(tour_dates)  # start date of the latest tour-level event

    names, iocs = {}, {}
    for r in all_rows:
        for side in ("winner", "loser"):
            names[r[f"{side}_id"]] = r[f"{side}_name"]
            if r.get(f"{side}_ioc"):
                iocs[r[f"{side}_id"]] = r[f"{side}_ioc"]
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from vrs_tennis import IOC_TO_ISO  # country table lives next to this script

    def iso(pid):
        return IOC_TO_ISO.get((iocs.get(pid) or "").upper())
    official_info, official = official_ranking(all_rows, load_weekly_rankings(args.rankings), as_of, args.official_mode)

    matches = [r for r in all_rows if r["tourney_level"] in TOUR_LEVELS]
    backtest_from = as_of - timedelta(days=30 * args.backtest_months)
    elo, g2, osk, last_match, count, bt = run_skill_models(matches, backtest_from)
    _e, g2p, oskp, _l, _c, btp = run_skill_models(matches, backtest_from, inactivity=False)  # textbook versions
    points = ledger(all_rows, as_of)

    cutoff = as_of - timedelta(days=args.active_days)
    pool = [p for p in last_match if last_match[p] >= cutoff and count[p] >= args.min_matches]

    g2_score = {p: (g2[p].mu - 2 * g2[p].phi) * G2_SCALE + 1500 for p in g2}
    osk_score = {p: osk[p].ordinal() for p in osk}
    g2p_score = {p: (g2p[p].mu - 2 * g2p[p].phi) * G2_SCALE + 1500 for p in g2p}
    oskp_score = {p: oskp[p].ordinal() for p in oskp}
    ranks = {
        "elo": rank_map(pool, elo),
        "glicko": rank_map(pool, g2_score),
        "openskill": rank_map(pool, osk_score),
        "glicko_pure": rank_map(pool, g2p_score),
        "openskill_pure": rank_map(pool, oskp_score),
        "ledger": rank_map(pool, points),
    }

    m52 = defaultdict(int)
    for r in matches:
        if r["_date"] > as_of - timedelta(days=364):
            m52[r["winner_id"]] += 1
            m52[r["loser_id"]] += 1

    players = []
    for p in pool:
        off = official.get(p)
        players.append({
            "id": p,
            "name": names[p],
            "iso": iso(p),
            "matches": count[p],
            "matches_52w": m52[p],
            "last_match": last_match[p].strftime("%Y-%m-%d"),
            "elo": round(elo[p]),
            "glicko": round(g2_score[p]),
            "glicko_rd": round(g2[p].phi * G2_SCALE, 1),
            "openskill": round(osk_score[p], 2),
            "openskill_sigma": round(osk[p].sigma, 3),
            # underlying ratings, for head-to-head win chances on the Predict page
            "glicko_r": round(g2[p].mu * G2_SCALE + 1500, 1),
            "glicko_r_pure": round(g2p[p].mu * G2_SCALE + 1500, 1),
            "openskill_mu": round(osk[p].mu, 3),
            "openskill_mu_pure": round(oskp[p].mu, 3),
            "glicko_pure": round(g2p_score[p]),
            "glicko_rd_pure": round(g2p[p].phi * G2_SCALE, 1),
            "openskill_pure": round(oskp_score[p], 2),
            "openskill_sigma_pure": round(oskp[p].sigma, 3),
            "ledger": points.get(p, 0),
            "official_rank": off[0] if off else None,
            "official_points": off[1] if off else None,
            "ranks": {k: v[p] for k, v in ranks.items()},
        })
    # players in the official top list who are not rated (too few tour matches, or inactive)
    in_pool = set(pool)
    for pid, (rk, pts, name) in official.items():
        if pid not in in_pool:
            players.append({"id": pid, "name": name, "iso": iso(pid), "matches_52w": m52[pid], "rated": False,
                            "last_match": last_match[pid].strftime("%Y-%m-%d") if pid in last_match else None,
                            "official_rank": rk, "official_points": pts, "ranks": {}})
    vrs_meta = None
    if args.vrs and os.path.exists(args.vrs):
        with open(args.vrs, encoding="utf-8") as fh:
            vrs = json.load(fh)
        by_id = {v["id"]: v for v in vrs["players"]}
        listed = set()
        for p in players:
            v = by_id.get(p["id"])
            if v:
                p["vrs"], p["ranks"]["vrs"] = v["points"], v["rank"]
                listed.add(p["id"])
        for v in vrs["players"]:  # VRS-ranked players not otherwise listed
            if v["id"] not in listed and v["rank"] <= 150:
                players.append({"id": v["id"], "name": v["name"], "iso": iso(v["id"]), "matches_52w": m52[v["id"]], "rated": False,
                                "official_rank": None, "official_points": None, "vrs": v["points"],
                                "ranks": {"vrs": v["rank"]}})
        m = vrs.get("meta", {})
        vrs_meta = {"players": len(vrs["players"]), "matches_used": vrs.get("matches_used"),
                    "prize_sources": m.get("prize_sources"), "fallback_fx_years": m.get("fallback_fx_years")}
    players.sort(key=lambda x: x["ranks"].get("elo", 10 ** 6))

    def bt_summary(b):
        n = b["n"]
        return {"matches": n, "accuracy": round(b["correct"] / n, 4) if n else None,
                "log_loss": round(b["logloss"] / n, 4) if n else None}

    meta = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "data_as_of": as_of.strftime("%Y-%m-%d"),
        "start_year": args.start_year,
        "matches_used": len(matches),
        "players_rated": len(pool),
        "official": official_info,
        "vrs": vrs_meta,
        "backtest": {
            "window": f"last {args.backtest_months} months",
            "elo": bt_summary(bt["elo"]),
            "glicko": bt_summary(bt["glicko"]),
            "openskill": bt_summary(bt["openskill"]),
            "glicko_pure": bt_summary(btp["glicko"]),
            "openskill_pure": bt_summary(btp["openskill"]),
        },
        "inactivity": {"reset_years": INACTIVE_RESET_YEARS},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "players": players}, fh, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
