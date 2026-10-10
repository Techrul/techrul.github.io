#!/usr/bin/env python3
"""Two checks for the tennis VRS. Not part of the daily build; run by hand.

1. Prediction backtest (Valve's own way of judging the model): rebuild VRS every Monday using only
   matches before that day, predict the winners of the following week's matches, and compare with
   Elo, Glicko-2, OpenSkill and "higher official rank wins" on exactly the same matches.
2. Prize money sensitivity: multiply every estimated prize amount by a random factor in [0.9, 1.1]
   and see how much the current VRS ranking moves.

    python3 scripts/vrs_backtest.py --raw data/raw --prize data/prize_money.json --valve vendor/vrs \\
        --from 2026-03-02 --to 2026-09-28 --sensitivity-runs 3
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prize_model as pm  # noqa: E402
import ratings  # noqa: E402
import vrs_tennis  # noqa: E402

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vrs_runner.js")
G = 1 / math.sqrt(1 + 3 * (math.log(10) / 400) ** 2 * 75 ** 2 / math.pi ** 2)  # Valve's Glicko, RD fixed at 75


def run_valve(valve, data, tmp):
    infile, outfile = os.path.join(tmp, "in.json"), os.path.join(tmp, "out.json")
    with open(infile, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    subprocess.run(["node", RUNNER, os.path.abspath(valve), infile, outfile], check=True,
                   cwd=os.path.join(os.path.abspath(valve), "model"), stdout=subprocess.DEVNULL)
    with open(outfile, encoding="utf-8") as fh:
        return {p["id"]: p for p in json.load(fh)["players"]}


def snapshot(data, cutoff_ts):
    """Valve input as it would have looked on the cutoff date."""
    matches = [m for m in data["matches"] if m["matchStartTime"] < cutoff_ts]
    last = {}
    for m in matches:
        last[m["eventId"]] = max(last.get(m["eventId"], 0), m["matchStartTime"])
    final_seen = {m["eventId"] for m in matches if m["round"] == "F"}
    events = [dict(e, finished=e["eventId"] in final_seen) for e in data["events"] if e["eventId"] in last]
    return {"matches": matches, "events": events}


def spearman(a, b):
    n = len(a)
    ra = {i: r for r, i in enumerate(sorted(range(n), key=lambda i: a[i]))}
    rb = {i: r for r, i in enumerate(sorted(range(n), key=lambda i: b[i]))}
    return 1 - 6 * sum((ra[i] - rb[i]) ** 2 for i in range(n)) / (n * (n * n - 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--prize", default="data/prize_money.json")
    ap.add_argument("--valve", required=True)
    ap.add_argument("--from", dest="start", default="2026-03-02")
    ap.add_argument("--to", dest="end", default="2026-09-28")
    ap.add_argument("--history-from", type=int, default=2020, help="first year for the skill models' warm-up")
    ap.add_argument("--sensitivity-runs", type=int, default=3)
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    with open(args.prize, encoding="utf-8") as fh:
        cache = json.load(fh)
    fx = pm.FX({} if args.offline else pm.ecb_yearly_rates())
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    data, _ = vrs_tennis.build(args.raw, cache, start.year - 1, fx=fx)

    # skill models' pre-match probabilities for every match since the first cutoff
    rows = [r for r in ratings.load(args.raw, args.history_from) if r["tourney_level"] in ratings.TOUR_LEVELS]
    preds = {}
    ratings.run_skill_models(rows, start.replace(tzinfo=None) - timedelta(days=14), preds, inactivity=False)  # textbook models, as published in HOW_IT_WORKS.md
    official = {}
    for r in rows:
        wr, lr = r.get("winner_rank") or "", r.get("loser_rank") or ""
        if wr.isdigit() and lr.isdigit():
            official[(r["tourney_id"], r["round"], r["winner_id"], r["loser_id"])] = (int(wr), int(lr))

    names = ("vrs", "elo", "glicko", "openskill", "official")
    tot = {n: {"n": 0, "right": 0, "ll": 0.0} for n in names}
    weeks = 0
    with tempfile.TemporaryDirectory() as tmp:
        day = start
        while day <= end:
            cut = int(day.timestamp())
            vrs = run_valve(args.valve, snapshot(data, cut), tmp)
            for m in data["matches"]:
                if not (cut <= m["matchStartTime"] < cut + 7 * 86400):
                    continue
                w, l = m["team1Id"], m["team2Id"]  # team1 is always the winner in our input
                key = (m["eventId"], m["round"], w, l)
                if w not in vrs or l not in vrs or key not in preds or key not in official:
                    continue  # compare on matches every method can predict
                p = {"vrs": 1 / (1 + 10 ** (-G * (vrs[w]["points"] - vrs[l]["points"]) / 400)), **preds[key]}
                wr, lr = official[key]
                p["official"] = 0.5 if wr == lr else (0.65 if wr < lr else 0.35)  # accuracy only; log loss not comparable
                for n in names:
                    q = min(max(p[n], 1e-6), 1 - 1e-6)
                    tot[n]["n"] += 1
                    tot[n]["right"] += 1 if q > 0.5 else (0.5 if q == 0.5 else 0)
                    tot[n]["ll"] += -math.log(q)
            weeks += 1
            print(f"  {day.date()}: VRS ranked {len(vrs)} players", file=sys.stderr)
            day += timedelta(days=7)

    print(f"\nPrediction backtest: {weeks} weekly snapshots, {tot['vrs']['n']} matches predicted by every method")
    for n in names:
        t = tot[n]
        ll = f'{t["ll"] / t["n"]:.3f}' if n != "official" else "  -  "
        print(f"  {n:10} picked the winner {100 * t['right'] / t['n']:.1f}%   log loss {ll}")

    # prize money sensitivity
    if args.sensitivity_runs:
        with tempfile.TemporaryDirectory() as tmp:
            base = run_valve(args.valve, data, tmp)
            top = sorted(base.values(), key=lambda p: p["rank"])[:50]
            print(f"\nPrize money sensitivity: estimated amounts x random [0.9, 1.1], {args.sensitivity_runs} runs")
            for i in range(args.sensitivity_runs):
                rng = random.Random(i)
                factors = {}

                def perturb(tid, how, item):
                    if how == "table":
                        return 1.0  # real figures stay as they are
                    return factors.setdefault((tid, item), rng.uniform(0.9, 1.1))

                noisy, _ = vrs_tennis.build(args.raw, cache, start.year - 1, perturb=perturb, fx=fx)
                alt = run_valve(args.valve, noisy, tmp)
                ids = [p["id"] for p in top if p["id"] in alt]
                rho = spearman([base[x]["rank"] for x in ids], [alt[x]["rank"] for x in ids])
                moves = sorted((abs(base[x]["rank"] - alt[x]["rank"]), base[x]["name"]) for x in ids)
                top10_same = sum(1 for x in ids if base[x]["rank"] <= 10 and alt[x]["rank"] <= 10)
                print(f"  run {i + 1}: top-50 rank correlation {rho:.3f}, top 10 kept {top10_same}/10, "
                      f"median move {moves[len(moves) // 2][0]}, biggest {moves[-1][0]} ({moves[-1][1]})")


if __name__ == "__main__":
    main()
