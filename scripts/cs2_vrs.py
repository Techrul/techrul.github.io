#!/usr/bin/env python3
"""Valve's VRS code (unchanged, run through vrs_runner.js) on Liquipedia's CS2 data, and a comparison with
Valve's published standings for the same date.

    python3 scripts/cs2_vrs.py --valve vendor/vrs --as-of 2026-10-05 --out vrs_cs2.json \\
        --compare vendor/vrs/live/2026/standings_global_2026_10_05.md

Valve's standings are published in its repository on the first Monday of each month. The comparison matches
teams by roster (3 of 5 players, names compared case-insensitively) and reports rank correlation and the
biggest differences: this checks our data (Liquipedia) against Valve's own.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cs2_adapter as ad  # noqa: E402


def run_vrs(valve_dir, data, as_of):
    vi = ad.valve_input(data, as_of)
    with tempfile.TemporaryDirectory() as tmp:
        infile, outfile = os.path.join(tmp, "matchdata.json"), os.path.join(tmp, "vrs.json")
        with open(infile, "w", encoding="utf-8") as fh:
            json.dump(vi, fh)
        runner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vrs_runner.js")
        subprocess.run(["node", runner, os.path.abspath(valve_dir), infile, outfile, "--players"], check=True,
                       cwd=os.path.join(os.path.abspath(valve_dir), "model"), stdout=subprocess.DEVNULL)
        with open(outfile, encoding="utf-8") as fh:
            vrs = json.load(fh)
    vrs["input"] = {"matches": len(vi["matches"]), "events": len(vi["events"]),
                    "ranked_matches": sum(m["valveRanked"] for m in vi["matches"]),
                    "finished_events": sum(e["finished"] for e in vi["events"])}
    return vrs


def spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy) if vx and vy else float("nan")


def compare(ours, official, top=50):
    """Match teams by roster overlap (3+ of 5, case-insensitive) -> report."""
    mine = [(t, {p.lower() for p in t.get("players", [])}) for t in ours["players"]]
    rows, missing = [], []
    for o in official[:top]:
        names = {p.lower() for p in o["roster"]}
        hit = next((t for t, ps in mine if len(ps & names) >= 3), None)
        if hit is None:
            missing.append(o)
        else:
            rows.append((o, hit))
    rho = spearman([o["rank"] for o, _ in rows], [t["rank"] for _, t in rows]) if len(rows) > 2 else float("nan")
    lines = [f"official top {top}: {len(rows)} found in ours, {len(missing)} not found",
             f"rank correlation (Spearman) over the found teams: {rho:.3f}",
             f"same team at #1: {bool(rows and rows[0][0]['rank'] == 1 and rows[0][1]['rank'] == 1)}",
             f"within 3 places: {sum(abs(o['rank'] - t['rank']) <= 3 for o, t in rows)}, "
             f"within 10: {sum(abs(o['rank'] - t['rank']) <= 10 for o, t in rows)}",
             "", f"{'off':>4} {'ours':>5} {'pts':>5} {'ours':>5}  team"]
    for o, t in rows:
        flag = "  <-" if abs(o["rank"] - t["rank"]) > 10 else ""
        lines.append(f"{o['rank']:>4} {t['rank']:>5} {o['points']:>5} {t['points']:>5}  {o['name']} / {t['name']}{flag}")
    for o in missing:
        lines.append(f"{o['rank']:>4}     -  {o['points']:>4}     -  {o['name']} ({', '.join(o['roster'])}) not ranked in ours")
    return {"found": len(rows), "missing": len(missing), "spearman": rho}, "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cs2")
    ap.add_argument("--valve", required=True)
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD (UTC midnight)")
    ap.add_argument("--out")
    ap.add_argument("--compare", help="Valve's standings_global_<date>.md")
    ap.add_argument("--top", type=int, default=50)
    args = ap.parse_args()

    data = ad.load(args.data)
    as_of = ad.utc(args.as_of)
    vrs = run_vrs(args.valve, data, as_of)
    print(f"VRS as of {args.as_of}: {vrs['matches_used']} matches used, {len(vrs['players'])} rosters ranked; input {vrs['input']}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(vrs, fh, ensure_ascii=False)
    if args.compare:
        stats, report = compare(vrs, ad.parse_valve_standings(args.compare), args.top)
        print(report)


if __name__ == "__main__":
    main()
