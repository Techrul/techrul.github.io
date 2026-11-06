#!/usr/bin/env python3
"""Tests for scripts/cs2_points.py: placings to points, top-half rule, online discount, best-N 52-week ledger."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import cs2_adapter as ad  # noqa: E402
import cs2_points as cp  # noqa: E402


def m(event, t1, t2, r1, r2):
    return {"event": event, "teams": [{"name": t1, "template": t1.lower()}, {"name": t2, "template": t2.lower()}], "rosters": (r1, r2)}


def test_shares():
    assert [cp.share(s) for s in (1, 2, 3, 4, 5, 9, 12, 17, 33)] == [1.0, 0.65, 0.4, 0.4, 0.2, 0.1, 0.1, 0.05, 0.0]


def test_event_results_and_ledger():
    tours = {"Big": {"tier": "1", "tiertype": "", "end": "2026-06-21", "teams": 32, "lan": True, "valve": "Tier 1"},
             "Small": {"tier": "1", "tiertype": "", "end": "2026-10-18", "teams": 8, "lan": False, "valve": "Tier 1"},
             "Major": {"tier": "1", "tiertype": "", "end": "2025-06-01", "teams": 32, "lan": True, "valve": "Major Championship"},
             "Qual": {"tier": "1", "tiertype": "Qualifier", "end": "2026-05-01", "teams": 64, "lan": False, "valve": ""}}
    places = {"Big": [{"place": "1", "team": "A"}, {"place": "9-11", "team": "B"}, {"place": "17-19", "team": "C"}],
              "Small": [{"place": "1", "team": "B"}, {"place": "5-6", "team": "A"}],
              "Major": [{"place": "1", "team": "A"}],
              "Qual": [{"place": "1", "team": "C"}]}
    matches = [m("Big", "A", "B", 0, 1), m("Big", "C", "A", 2, 0), m("Small", "A", "B", 0, 1), m("Major", "A", "C", 0, 2), m("Qual", "C", "B", 2, 1)]
    data = ad.Data(matches, tours, places, {})
    res = cp.event_results(data, lambda mm, i: f"r{mm['rosters'][i]}")
    got = {(r, page): pts for r, _end, pts, page in res}
    assert got[("r0", "Big")] == 1000 and got[("r1", "Big")] == 100     # 9-11 counts as 9-16
    assert ("r2", "Big") not in got                                       # 17-19 of 32 is the bottom half
    assert got[("r1", "Small")] == 750 and ("r0", "Small") not in got     # online 75%; 5-6 of 8 scores nothing
    assert got[("r0", "Major")] == 2000 and ("r2", "Qual") not in got     # Majors double; qualifiers don't count
    # an event with no winner recorded yet (final still to come) scores nothing, not even its finished placings
    tours["Live"] = {"tier": "1", "tiertype": "", "end": "2026-10-25", "teams": 16, "lan": True, "valve": "Tier 1"}
    places["Live"] = [{"place": "3-4", "team": "A"}, {"place": "5-8", "team": "B"}]
    data = ad.Data(matches + [m("Live", "A", "B", 0, 1)], tours, places, {})
    assert not [r for r in cp.event_results(data, lambda mm, i: f"r{mm['rosters'][i]}") if r[3] == "Live"]
    led = cp.ledger(res, "2026-11-01")
    assert led == {"r0": 1000, "r1": 850}                                 # the 2025 Major is outside 52 weeks


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
