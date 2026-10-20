#!/usr/bin/env python3
"""Tests for scripts/cs2_adapter.py.

    python3 tests/test_cs2_adapter.py [path to counter-strike_regional_standings]

With Valve's repository (default: vendor/vrs) and node available, the roster grouping is checked against
Valve's own JavaScript on Valve's sample data: every match must get the same roster ids on both sides.
Without them that test is skipped and the small synthetic tests still run.
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import cs2_adapter as ad  # noqa: E402


def match(t, a, b, winner=1, walkover="", event="Ev", valve="Tier 2", names=("A", "B")):
    return {"id": f"m{t}", "time": t, "date": "2026-01-01", "event": event, "valve": valve, "lan": False,
            "winner": winner, "walkover": walkover, "tier": "3",
            "teams": [{"name": names[0], "template": names[0].lower(), "players": a},
                      {"name": names[1], "template": names[1].lower(), "players": b}]}


def test_roster_rules():
    A = ["a1", "a2", "a3", "a4", "a5"]
    B = ["b1", "b2", "b3", "b4", "b5"]
    ms = [
        match(1, ["a1", "a2", "x1", "x2", "x3"], B),  # oldest: only 2 of today's A -> a different team
        match(2, ["a1", "a2", "a3", "y1", "y2"], B),  # 3 of today's A -> same team as A
        match(3, A, B),                                # newest: anchors both teams
    ]
    rs = ad.assign_rosters(ms)
    assert ms[2]["rosters"] == (0, 1)
    assert ms[1]["rosters"] == (0, 1)
    assert ms[0]["rosters"][0] == 2 and ms[0]["rosters"][1] == 1
    assert rs.list[0].players == A and rs.list[0].matches == 2


def test_forfeit_placeholder_is_replaced():
    A = ["a1", "a2", "a3", "a4", "a5"]
    ms = [match(1, A, ["b1", "b2", "b3", "b4", "b5"], names=("A", "B real")),
          match(2, A, ["b1", "b2", "b3", "t1", "t2"], walkover="ff", names=("A", "B forfeit"))]
    rs = ad.assign_rosters(ms)
    b = rs.list[ms[1]["rosters"][1]]
    assert ms[0]["rosters"][1] == b.id
    assert b.name == "B real" and b.players == ["b1", "b2", "b3", "b4", "b5"] and not b.pending


def test_common_format_and_valve_input():
    A = ["a1", "a2", "a3", "a4", "a5"]
    B = ["b1", "b2", "b3", "b4", "b5"]
    t0 = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp())
    ms = [match(t0, A, B, winner=2, event="Cup"), match(t0 + 60, A, B[:4], event="Cup")]  # 2nd: only 4 players
    data = ad.Data(ms, {"Cup": {"name": "The Cup", "start": "2026-02-28", "end": "2026-03-02", "pool": 50000,
                                "lan": True, "valve": "Tier 2"}},
                   {"Cup": [{"place": "1", "team": "B", "template": "b", "prize": 30000},
                            {"place": "3-4", "team": "A", "template": "a", "prize": 5000},
                            {"place": "5-8", "team": "TBD", "template": "tbd", "prize": 1000}]},
                   {p: "Turkey" for p in A + B})
    ad.assign_rosters(ms)
    common = ad.to_common(ms)
    assert len(common) == 1 and common[0]["sides"] == [["r0"], ["r1"]] and common[0]["winner"] == 1
    vi = ad.valve_input(data, datetime(2026, 3, 10, tzinfo=timezone.utc))
    assert len(vi["matches"]) == 1
    m = vi["matches"][0]
    assert m["team1Id"] == "a" and m["team2Id"] == "b" and m["winningTeam"] == 2 and m["valveRanked"] is True
    assert m["team1Players"][0] == {"playerId": "a1", "nick": "a1", "country": "Turkey", "countryIso": "tr"}
    ev = vi["events"][0]
    assert ev["prizePool"] == "$50000" and ev["lan"] is True and ev["finished"] is True
    assert [(d["teamId"], d["placement"], d["shared"]) for d in ev["prizeDistribution"]] == [("b", 1, False), ("a", 3, True)]
    # not finished yet on its last day
    assert ad.valve_input(data, datetime(2026, 3, 2, 12, tzinfo=timezone.utc))["events"][0]["finished"] is False


def test_short_names():
    cases = {"Team Vitality": "Vitality", "G2 Esports": "G2", "FaZe Clan": "FaZe", "BetBoom Team": "BetBoom",
             "Aimclub (Romanian team)": "Aimclub", "KUUSAMO.gg": "KUUSAMO", "DENDELE CS": "DENDELE",
             "Natus Vincere": "Natus Vincere", "Team A": "Team A", "33": "33", "Team Spirit Academy": "Spirit Academy"}
    for full, short in cases.items():
        assert ad.short_name(full) == short, (full, ad.short_name(full), short)


def test_regions_follow_valve_rule():
    table = {"ru": 0, "fr": 0, "br": 1, "us": 1, "cn": 2, "au": 2, "za": -1}  # Valve's groups (see load_valve_regions)
    assert ad.valve_region(["ru"] * 5, table) == 0
    assert ad.valve_region(["br", "br", "fr", "fr", "cn"], table) == 0      # tie Europe/Americas -> Europe
    assert ad.valve_region(["br", "br", "fr", "fr", "za"], table) == 1      # Africa joins the lowest-priority region present
    assert ad.valve_region(["za"] * 5, table) == 2                          # only Africa -> Asia (Valve's default)
    assert ad.valve_region(["world"] * 5, table) is None


def test_matches_valve_on_sample(valve_dir):
    sample = os.path.join(valve_dir, "data", "matchdata_sample_20230829.json")
    if not (os.path.exists(sample) and shutil.which("node")):
        print("  skipped: needs Valve's repository and node")
        return
    out = subprocess.run(["node", os.path.join(HERE, "valve_rosters.js"), os.path.abspath(valve_dir), sample],
                         check=True, capture_output=True, text=True, cwd=os.path.join(valve_dir, "model")).stdout
    valve = {idx: (r1, r2) for idx, r1, r2 in json.loads(out)}
    with open(sample, encoding="utf-8") as fh:
        raw = json.load(fh)["matches"]
    kept = [dict(raw[i], _idx=i, time=raw[i]["matchStartTime"]) for i in range(len(raw)) if i in valve]  # input order
    ad.assign_rosters(kept,
                      players_of=lambda m, i: [p["playerId"] for p in m[f"team{i + 1}Players"]],
                      name_of=lambda m, i: m[f"team{i + 1}Name"],
                      forfeit_of=lambda m: bool(m.get("forfeited")))
    diff = [(m["_idx"], valve[m["_idx"]], m["rosters"]) for m in kept if tuple(m["rosters"]) != tuple(valve[m["_idx"]])]
    assert not diff, f"{len(diff)} of {len(kept)} matches differ, e.g. {diff[:5]}"
    print(f"  {len(kept)} matches, {len({r for m in kept for r in m['rosters']})} rosters: identical to Valve's code")


if __name__ == "__main__":
    valve_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "vendor", "vrs")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(valve_dir) if name == "test_matches_valve_on_sample" else fn()
            print("ok", name)
