#!/usr/bin/env python3
"""Valve Regional Standings (VRS) method applied to ATP tennis.

    python3 scripts/vrs_tennis.py --raw data/raw --prize data/prize_money.json \\
        --valve vendor/counter-strike_regional_standings --out docs/data/vrs.json

Valve's code is not copied into this project. The workflow clones Valve's public repository at a
pinned commit and this script runs it unchanged through scripts/vrs_runner.js. This script only
converts tennis results into the input format Valve's code expects:

- a player is a "team" listed five times, so Valve's 3-of-5 roster rule always matches the same player;
- every tour-level singles match is a ranked match (walkovers are left out);
- every tournament is an event with its prize pool and each player's prize money for the round
  they reached (scripts/prize_model.py), converted to USD and scaled so the largest event pool is
  $1,000,000 (Valve caps pools there; scaling keeps tennis events' relative stakes);
- all tennis is played in person, so every event counts as LAN;
- countries are converted from IOC to ISO codes for Valve's region assignment.

Events still in progress are dropped by Valve's own code, as for CS.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prize_model as pm  # noqa: E402
import ratings  # noqa: E402

TOUR_LEVELS = {"G", "M", "500", "250", "F"}
ROUND_INDEX = {"RR": 0, "R128": 0, "R64": 1, "R32": 2, "R16": 3, "QF": 4, "SF": 5, "F": 6}
PLACEMENT = {"W": 1, "F": 2, "SF": 3, "QF": 5, "R16": 9, "R32": 17, "R64": 33, "R128": 65}

# IOC (Olympic) country codes used by TML -> ISO 3166 alpha-2 used by Valve's region table.
IOC_TO_ISO = {
    "ARG": "ar", "AUS": "au", "AUT": "at", "BEL": "be", "BIH": "ba", "BOL": "bo", "BRA": "br", "BUL": "bg",
    "CAN": "ca", "CHI": "cl", "CHN": "cn", "COL": "co", "CRO": "hr", "CZE": "cz", "DEN": "dk", "ECU": "ec",
    "ESP": "es", "EST": "ee", "FIN": "fi", "FRA": "fr", "GBR": "gb", "GEO": "ge", "GER": "de", "GRE": "gr",
    "HKG": "hk", "HUN": "hu", "IND": "in", "ITA": "it", "JOR": "jo", "JPN": "jp", "KAZ": "kz", "KOR": "kr",
    "LBN": "lb", "LTU": "lt", "LUX": "lu", "MAR": "ma", "MDA": "md", "MEX": "mx", "MON": "mc", "NED": "nl",
    "NOR": "no", "NZL": "nz", "PAR": "py", "PER": "pe", "POL": "pl", "POR": "pt", "PRT": "pt", "QAT": "qa",
    "ROU": "ro", "RSA": "za", "RUS": "ru", "SRB": "rs", "SUI": "ch", "SVK": "sk", "SVN": "si", "SLO": "si",
    "SWE": "se", "THA": "th", "TPE": "tw", "TUN": "tn", "UKR": "ua", "USA": "us", "BLR": "by", "ISR": "il",
    "TUR": "tr", "LAT": "lv", "URU": "uy", "IRL": "ie", "ARM": "am", "CYP": "cy", "EGY": "eg", "MKD": "mk",
    "INA": "id", "PHI": "ph", "VEN": "ve", "DOM": "do", "UZB": "uz", "KSA": "sa", "UAE": "ae", "BAR": "bb",
}


def iso_code(ioc):
    return IOC_TO_ISO.get((ioc or "").upper(), "world")  # 'world' is skipped by Valve's region logic


def build(raw_dir, prize_cache, start_year, perturb=None, fx=None):
    """perturb(event_id, how, item) -> multiplier, for sensitivity tests only."""
    rows = [r for r in ratings.load(raw_dir, start_year) if r["tourney_level"] in TOUR_LEVELS and not r["_walkover"]]
    if not rows:
        sys.exit("no tour-level matches loaded")

    names = defaultdict(Counter)
    for r in rows:
        names[r["tourney_id"]][(r["tourney_name"], r["tourney_level"], r["draw_size"])] += 1
    info = {tid: c.most_common(1)[0][0] for tid, c in names.items()}  # majority vote fixes stray rows

    fx = fx or pm.FX(pm.ecb_yearly_rates())
    model = pm.PrizeModel(prize_cache, fx)

    # who reached what, per event
    dates_per_event = defaultdict(set)
    for r in rows:
        dates_per_event[r["tourney_id"]].add(r["_date"])
    reached = defaultdict(dict)         # tid -> pid -> round label of loss, or "W"
    finals_wins = defaultdict(Counter)  # (tid, pid) -> {"RR": n, "SF": n, "F": n}
    finished, first_date, player_info = set(), {}, {}
    for r in rows:
        tid, rd = r["tourney_id"], r["round"]
        first_date[tid] = min(first_date.get(tid, r["_date"]), r["_date"])
        for side in ("winner", "loser"):
            player_info[r[f"{side}_id"]] = (r[f"{side}_name"], r.get(f"{side}_ioc"))
        if info[tid][1] == "F":
            finals_wins[(tid, r["winner_id"])][rd] += 1
            reached[tid].setdefault(r["loser_id"], "RR")
            reached[tid].setdefault(r["winner_id"], "RR")
        else:
            reached[tid][r["loser_id"]] = rd
        if rd == "F":
            reached[tid][r["winner_id"]] = "W"
            finished.add(tid)

    # prize money and pools in USD
    events_out, pools, prizes, prize_how = [], {}, {}, Counter()
    for tid, (name, level, draw) in info.items():
        year = first_date[tid].year
        rounds, how = model.round_prizes_usd(tid, name=name, year=year, level=level, draw=draw)
        prize_how[how] += 1
        if perturb:
            rounds = {k: v * perturb(tid, how, k) for k, v in rounds.items()}
        if level == "F":
            fee = rounds.get("PART", 0.0)
            pool = 8 * fee + 12 * rounds.get("RR", 0) + 2 * rounds.get("SFW", 0) + rounds.get("FW", 0)
            pools[tid] = pool / model.payout_ratio.get("M", 1.0) if pool else None
            for pid in reached[tid]:
                w = finals_wins[(tid, pid)]
                prizes[(tid, pid)] = fee + w["RR"] * rounds.get("RR", 0) + w["SF"] * rounds.get("SFW", 0) + w["F"] * rounds.get("FW", 0)
        else:
            pools[tid] = model.pool_usd(tid, name=name, year=year, level=level, draw=draw)
            if perturb and pools[tid]:
                pools[tid] *= perturb(tid, how, "pool")
            for pid, rd in reached[tid].items():
                prizes[(tid, pid)] = rounds.get(rd, 0.0)

    biggest = max(p for p in pools.values() if p)
    scale = 1_000_000 / biggest

    for tid, (name, level, draw) in info.items():
        dist = [{"placement": PLACEMENT.get(rd, 99), "teamId": pid, "prize": round(prizes.get((tid, pid), 0.0) * scale, 2),
                 "clubShare": 0, "shared": False, "qualifiedEvents": []} for pid, rd in reached[tid].items()]
        events_out.append({"eventId": tid, "eventName": f"{first_date[tid].year} {name}",
                           "prizePool": f"${int(round((pools.get(tid) or 0) * scale))}", "lan": True,
                           "finished": tid in finished, "prizeDistribution": dist})

    def team(pid):
        name, ioc = player_info[pid]
        player = {"playerId": pid, "nick": name, "country": ioc or "", "countryIso": iso_code(ioc)}
        return [dict(player) for _ in range(5)]

    matches_out = []
    for r in rows:
        # finished events carry only their start date, so spread rounds over the event; events in
        # progress already carry each match's own date
        single_date = len(dates_per_event[r["tourney_id"]]) == 1
        offset_days = ROUND_INDEX.get(r["round"], 0) * (2 if info[r["tourney_id"]][1] == "G" else 1) if single_date else 0
        ts = int(r["_date"].replace(tzinfo=timezone.utc).timestamp()) + offset_days * 86400 + r["_mn"]
        matches_out.append({"matchStartTime": ts, "eventId": r["tourney_id"],
                            "team1Id": r["winner_id"], "team1Name": r["winner_name"], "team1Players": team(r["winner_id"]),
                            "team2Id": r["loser_id"], "team2Name": r["loser_name"], "team2Players": team(r["loser_id"]),
                            "winningTeam": 1, "forfeited": False, "valveRanked": True, "maps": [],
                            "round": r["round"]})  # extra field, ignored by Valve's code; used by the backtest
    unknown = sorted({ioc for _, ioc in player_info.values() if iso_code(ioc) == "world"})
    stats = {"events": len(info), "finished_events": len(finished), "matches": len(matches_out),
             "prize_sources": dict(prize_how), "pool_scale_usd_per_vrs_dollar": round(1 / scale, 2),
             "unknown_countries": unknown, "fallback_fx_years": sorted(fx.used_fallback)}
    return {"matches": matches_out, "events": events_out}, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--prize", default="data/prize_money.json")
    ap.add_argument("--valve", required=True, help="path to a clone of ValveSoftware/counter-strike_regional_standings")
    ap.add_argument("--out", default="docs/data/vrs.json")
    ap.add_argument("--start-year", type=int, default=datetime.now(timezone.utc).year - 1)
    ap.add_argument("--keep-input", default=None, help="also save the generated Valve input file here")
    args = ap.parse_args()

    with open(args.prize, encoding="utf-8") as fh:
        data, stats = build(args.raw, json.load(fh), args.start_year)
    print(json.dumps(stats, indent=2))

    with tempfile.TemporaryDirectory() as tmp:
        infile = args.keep_input or os.path.join(tmp, "matchdata.json")
        with open(infile, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        result = os.path.join(tmp, "vrs.json")
        runner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vrs_runner.js")
        # Valve's code resolves some paths relative to its own folder, so run it from there
        subprocess.run(["node", runner, os.path.abspath(args.valve), os.path.abspath(infile), result],
                       check=True, cwd=os.path.join(os.path.abspath(args.valve), "model"))
        with open(result, encoding="utf-8") as fh:
            vrs = json.load(fh)

    vrs["meta"] = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), **stats}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(vrs, fh, ensure_ascii=False, separators=(",", ":"))
    print(f'wrote {args.out}: {len(vrs["players"])} ranked players')


if __name__ == "__main__":
    main()
