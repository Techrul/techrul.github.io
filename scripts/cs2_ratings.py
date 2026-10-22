#!/usr/bin/env python3
"""CS2 rankings: Elo, Glicko-2, OpenSkill (scripts/engines.py, same code as tennis), VRS (Valve's code on
Liquipedia data) and Valve's official standings, for the same rosters.

    python3 scripts/cs2_ratings.py --data data/cs2 --valve vendor/vrs --out docs/rankings/cs2/data/rankings.json

- A team is a roster under Valve's rule (scripts/cs2_adapter.py): the latest five, plus earlier lineups that
  share 3 of them. All systems rank the same rosters.
- Skill models: every finished match with five players a side and a winner (Liquipedia tiers 1-4, ranked by
  Valve or not; showmatches are never fetched), walkovers left out. Glicko-2 rating periods are weeks.
  History starts Jan 2023; 2023 only warms the models up.
- Listed: rosters with --min-matches matches and one in the last --active-days days, plus any roster in the top
  100 of our VRS or of Valve's standings.
- Official: Valve's latest published global standings (its repository, live/<year>/standings_global_<date>.md),
  matched to our rosters by 3 of 5 players (names compared case-insensitively).

Match data: Liquipedia (https://liquipedia.net/counterstrike/), CC BY-SA 3.0. The output is shared under the
same licence.
"""
import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cs2_adapter as ad  # noqa: E402
import cs2_vrs  # noqa: E402
import engines  # noqa: E402
from engines import G2_SCALE, INACTIVE_RESET_YEARS  # noqa: E402

MIN_MATCHES, ACTIVE_DAYS = 15, 90  # listed: this many matches and one in the last ACTIVE_DAYS days (also cs2_site_data.py)
PERIODS_PER_YEAR = 52               # Glicko-2 rating periods are weeks for CS2

CREDIT = {"source": "Liquipedia", "url": "https://liquipedia.net/counterstrike/",
          "licence": "CC BY-SA 3.0", "licence_url": "https://liquipedia.net/commons/Liquipedia:Copyrights"}


def engine_rows(common):
    for c in common:
        if c["walkover"]:
            continue
        w, lo = c["sides"][c["winner"]][0], c["sides"][1 - c["winner"]][0]
        # whole days, as for tennis: weekly checkpoints then fall on Monday 00:00 and line up with event dates
        yield {"w": w, "l": lo, "date": datetime.strptime(c["date"], "%Y-%m-%d"),
               "period": (c["time"] // 86400 + 3) // 7, "key": c["id"]}  # week number, weeks start on Monday


def latest_valve_standings(valve_dir, as_of):
    files = sorted(glob.glob(os.path.join(valve_dir, "live", "*", "standings_global_*.md")))
    best = None
    for f in files:
        day = os.path.basename(f)[len("standings_global_"):-3].replace("_", "-")
        if day <= as_of.strftime("%Y-%m-%d"):
            best = (day, f)
    return best


def match_roster(players, candidates, need=3):
    """Index of the candidate roster sharing `need`+ players (case-insensitive), most overlap first."""
    ps = {p.lower() for p in players}
    best, best_n = None, need - 1
    for i, c in enumerate(candidates):
        n = len(ps & c)
        if n > best_n:
            best, best_n = i, n
    return best


def rank_map(pool, score):
    order = sorted(pool, key=lambda p: (-score[p], p))
    return {p: i + 1 for i, p in enumerate(order)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cs2")
    ap.add_argument("--valve", default="vendor/vrs", help="clone of ValveSoftware/counter-strike_regional_standings")
    ap.add_argument("--out", default="docs/rankings/cs2/data/rankings.json")
    ap.add_argument("--min-matches", type=int, default=MIN_MATCHES)
    ap.add_argument("--active-days", type=int, default=ACTIVE_DAYS)
    ap.add_argument("--backtest-months", type=int, default=12)
    ap.add_argument("--no-vrs", action="store_true")
    args = ap.parse_args()

    data = ad.load(args.data)
    usable = [m for m in data.matches if ad.usable(m)]
    rosters = ad.assign_rosters(usable)
    common = ad.to_common(usable)
    as_of = datetime.fromtimestamp(max(c["time"] for c in common), timezone.utc)
    as_of_naive = as_of.replace(tzinfo=None)
    backtest_from = as_of_naive - timedelta(days=30 * args.backtest_months)

    # Glicko-2 rating periods are weeks for CS2 (teams play several matches a week; monthly periods left
    # ratings stale within the month: 60.5% vs 62.8% winners picked over the last 12 months)
    elo, g2, osk, last_match, count, bt = engines.run(engine_rows(common), backtest_from, periods_per_year=PERIODS_PER_YEAR)
    _e, g2p, oskp, _l, _c, btp = engines.run(engine_rows(common), backtest_from, inactivity=False, periods_per_year=PERIODS_PER_YEAR)

    g2_score = {p: (g2[p].mu - 2 * g2[p].phi) * G2_SCALE + 1500 for p in g2}
    osk_score = {p: osk[p].ordinal() for p in osk}
    g2p_score = {p: (g2p[p].mu - 2 * g2p[p].phi) * G2_SCALE + 1500 for p in g2p}
    oskp_score = {p: oskp[p].ordinal() for p in oskp}

    roster = {f"r{r.id}": r for r in rosters.list}
    lower_players = {rid: {p.lower() for p in r.players} for rid, r in roster.items()}
    rid_list = list(lower_players)

    # our VRS (Valve's code on Liquipedia data), as of the end of the data
    vrs, vrs_meta = {}, None
    if not args.no_vrs and os.path.isdir(os.path.join(args.valve, "model")):
        try:
            out = cs2_vrs.run_vrs(args.valve, data, as_of + timedelta(seconds=1))
            for v in out["players"]:
                i = match_roster(v.get("players", []), [lower_players[r] for r in rid_list])
                if i is not None and rid_list[i] not in vrs:
                    vrs[rid_list[i]] = v
            vrs_meta = {"as_of": as_of.strftime("%Y-%m-%d"), "teams": len(out["players"]), "matched": len(vrs),
                        "matches_used": out["matches_used"], "input": out["input"]}
        except Exception as e:  # VRS is optional: the page hides it rather than failing the build
            print(f"VRS skipped: {e}")

    # Valve's official standings
    official, official_meta = {}, None
    found = latest_valve_standings(args.valve, as_of)
    if found:
        day, path = found
        rows = ad.parse_valve_standings(path)
        for o in rows:
            i = match_roster(o["roster"], [lower_players[r] for r in rid_list])
            if i is not None and rid_list[i] not in official:
                official[rid_list[i]] = o
        official_meta = {"date": day, "teams": len(rows), "matched": len(official),
                         "source": "https://github.com/ValveSoftware/counter-strike_regional_standings"}

    cutoff = as_of_naive - timedelta(days=args.active_days)
    pool = {p for p in last_match if last_match[p] >= cutoff and count[p] >= args.min_matches}
    rated = set(pool)
    extra = {r for r, v in vrs.items() if v["rank"] <= 100} | {r for r, o in official.items() if o["rank"] <= 100}
    ranks = {
        "elo": rank_map(pool, elo), "glicko": rank_map(pool, g2_score), "openskill": rank_map(pool, osk_score),
        "glicko_pure": rank_map(pool, g2p_score), "openskill_pure": rank_map(pool, oskp_score),
    }
    m12 = defaultdict(int)
    for c in common:
        if c["time"] >= (as_of - timedelta(days=365)).timestamp():
            for s in c["sides"]:
                m12[s[0]] += 1

    try:
        region_table = ad.load_valve_regions(args.valve)
    except OSError:
        region_table = None

    teams = []
    for p in sorted(pool | extra):
        r = roster[p]
        flags = [ad.countries.iso(data.flags.get(x)) for x in r.players]
        # region: Valve's own (from the VRS run, based on the team's recent regulars) when the team is in it,
        # else Valve's plurality rule on the current five
        region = None
        if p in vrs and isinstance(vrs[p].get("region"), list) and 1 in vrs[p]["region"]:
            region = ad.REGIONS[vrs[p]["region"].index(1)]
        elif region_table:
            g = ad.valve_region(flags, region_table)
            region = ad.REGIONS[g] if g is not None else None
        t = {"id": p, "name": r.name, "short": ad.short_name(r.name), "region": region, "players": r.players,
             "flags": flags,
             "liquipedia": "https://liquipedia.net/counterstrike/" + r.name.replace(" ", "_"),
             "matches": count.get(p, 0), "matches_12m": m12[p],
             "last_match": last_match[p].strftime("%Y-%m-%d") if p in last_match else None,
             "rated": p in rated, "ranks": {k: v[p] for k, v in ranks.items() if p in v}}
        if p in elo:
            t.update({"elo": round(elo[p]), "glicko": round(g2_score[p]), "glicko_rd": round(g2[p].phi * G2_SCALE, 1),
                      "openskill": round(osk_score[p], 2), "openskill_sigma": round(osk[p].sigma, 3),
                      "glicko_r": round(g2[p].mu * G2_SCALE + 1500, 1), "glicko_r_pure": round(g2p[p].mu * G2_SCALE + 1500, 1),
                      "openskill_mu": round(osk[p].mu, 3), "openskill_mu_pure": round(oskp[p].mu, 3),
                      "glicko_pure": round(g2p_score[p]), "glicko_rd_pure": round(g2p[p].phi * G2_SCALE, 1),
                      "openskill_pure": round(oskp_score[p], 2), "openskill_sigma_pure": round(oskp[p].sigma, 3)})
        if p in vrs:
            v = vrs[p]
            t["vrs"] = v["points"]
            t["ranks"]["vrs"] = v["rank"]
        if p in official:
            o = official[p]
            t.update({"official_rank": o["rank"], "official_points": o["points"], "official_name": o["name"]})
        teams.append(t)
    teams.sort(key=lambda x: x["ranks"].get("elo", 10 ** 6))

    def bt_summary(b):
        n = b["n"]
        return {"matches": n, "accuracy": round(b["correct"] / n, 4) if n else None,
                "log_loss": round(b["logloss"] / n, 4) if n else None}

    meta = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "data_as_of": as_of.strftime("%Y-%m-%d"),
        "matches_used": sum(1 for c in common if not c["walkover"]),
        "rosters": len(rosters.list), "teams_rated": len(pool), "teams_listed": len(teams),
        "listing": {"min_matches": args.min_matches, "active_days": args.active_days},
        "official": official_meta, "vrs": vrs_meta,
        "backtest": {"window": f"last {args.backtest_months} months",
                     "elo": bt_summary(bt["elo"]), "glicko": bt_summary(bt["glicko"]),
                     "openskill": bt_summary(bt["openskill"]), "glicko_pure": bt_summary(btp["glicko"]),
                     "openskill_pure": bt_summary(btp["openskill"])},
        "inactivity": {"reset_years": INACTIVE_RESET_YEARS},
        "data": CREDIT,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "teams": teams}, fh, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
