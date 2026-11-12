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
    assert [cp.share(s) for s in (1, 2, 3, 4, 5, 9, 12, 17, 24, 25, 32, 33)] == [1.0, 0.65, 0.4, 0.4, 0.2, 0.1, 0.1, 0.05, 0.05, 0.025, 0.025, 0.0]


def test_event_results_and_ledger():
    tours = {"Big": {"tier": "1", "tiertype": "", "end": "2026-06-21", "teams": 32, "lan": True, "valve": "Tier 1"},
             "Small": {"tier": "1", "tiertype": "", "end": "2026-10-18", "teams": 8, "lan": False, "valve": "Tier 1"},
             "Major": {"tier": "1", "tiertype": "", "end": "2025-06-01", "teams": 32, "lan": True, "valve": "Major Championship"},
             "Qual": {"tier": "1", "tiertype": "Qualifier", "end": "2026-05-01", "teams": 64, "lan": False, "valve": ""}}
    places = {"Big": [{"place": "1", "team": "A"}, {"place": "9-11", "team": "B"}, {"place": "17-19", "team": "C"}],
              "Small": [{"place": "1", "team": "B"}, {"place": "5-6", "team": "A"}],
              "Major": [{"place": "1", "team": "A"}, {"place": "25-27", "team": "C"}],
              "Qual": [{"place": "1", "team": "C"}]}
    matches = [m("Big", "A", "B", 0, 1), m("Big", "C", "A", 2, 0), m("Small", "A", "B", 0, 1), m("Major", "A", "C", 0, 2), m("Qual", "C", "B", 2, 1)]
    data = ad.Data(matches, tours, places, {})
    res = cp.event_results(data, lambda mm, i: f"r{mm['rosters'][i]}")
    got = {(r, page): pts for r, _end, pts, page in res}
    assert got[("r0", "Big")] == 1000 and got[("r1", "Big")] == 100     # 9-11 counts as 9-16
    assert ("r2", "Big") not in got                                       # 17-19 of 32 is the bottom half
    assert got[("r1", "Small")] == 750 and ("r0", "Small") not in got     # online 75%; 5-6 of 8 scores nothing
    assert got[("r0", "Major")] == 2000 and ("r2", "Qual") not in got     # Majors double; qualifiers don't count
    assert got[("r2", "Major")] == 50                                     # at a Major even a Stage 1 exit scores
    # an event with no winner recorded yet (final still to come) scores nothing, not even its finished placings
    tours["Live"] = {"tier": "1", "tiertype": "", "end": "2026-10-25", "teams": 16, "lan": True, "valve": "Tier 1"}
    places["Live"] = [{"place": "3-4", "team": "A"}, {"place": "5-8", "team": "B"}]
    data = ad.Data(matches + [m("Live", "A", "B", 0, 1)], tours, places, {})
    assert not [r for r in cp.event_results(data, lambda mm, i: f"r{mm['rosters'][i]}") if r[3] == "Live"]
    led = cp.ledger(res, "2026-11-01")
    assert led == {"r0": 1000, "r1": 850}                                 # the 2025 Major is outside 52 weeks


def test_live():
    # a 16-team S-Tier LAN, 4 teams left: the 8 who are out keep their places, the 4 still in hold 3rd-4th (40%)
    tours = {"Live": {"tier": "1", "tiertype": "", "start": "2026-11-02", "end": "2026-11-08", "teams": 16, "lan": True, "valve": "Tier 1"}}
    names = "ABCDEFGHIJKL"
    places = {"Live": [{"place": "5-8", "team": n} for n in "EFGH"] + [{"place": "9-12", "team": n} for n in "IJKL"]
              + [{"place": "1", "team": "TBD"}, {"place": "2", "team": "TBD"}]}  # undecided places don't finish it
    matches = [dict(m("Live", names[i], names[i + 1], i, i + 1), time=100 - i) for i in range(0, 12, 2)]
    matches += [dict(m("Live", a, b, names.index(a), names.index(b)), time=200) for a, b in (("A", "B"), ("C", "D"))]
    data = ad.Data(matches, tours, places, {})
    rom = lambda mm, i: f"r{mm['rosters'][i]}"
    assert not cp.event_results(data, rom)                                  # not over: nothing final yet
    res, events = cp.live_results(data, rom, "2026-11-06")
    got = {r: pts for r, _d, pts, _p in res}
    assert events == [{"page": "Live", "name": "Live", "start": "2026-11-02", "left": 4}]
    assert all(got[f"r{i}"] == 400 for i in range(4))                     # A-D still in: sure of 3rd-4th
    assert all(got[f"r{i}"] == 200 for i in range(4, 8))                  # E-H out in 5th-8th
    assert not any(f"r{i}" in got for i in range(8, 12))                  # 9-12 of 16 is the bottom half
    assert not cp.live_results(data, rom, "2026-11-20")[1]                 # long past its end date: not live


def test_defending():
    tours = {"IEM/2025/Beijing": {"end": "2025-11-09"}, "IEM/2024/Beijing": {"end": "2024-11-10"},
             "ESL/Pro_League/Season_23": {"end": "2026-03-29"}, "ESL/Pro_League/Season_22": {"end": "2025-10-12"}}
    res = [("r1", "2025-11-09", 1000, "IEM/2025/Beijing"), ("r2", "2024-11-10", 1000, "IEM/2024/Beijing"),
           ("r1", "2026-03-29", 500, "ESL/Pro_League/Season_23"), ("r3", "2025-10-12", 500, "ESL/Pro_League/Season_22")]
    live = [{"page": "IEM/2026/Beijing", "start": "2026-11-02"}, {"page": "ESL/Pro_League/Season_24", "start": "2026-09-28"}]
    # last year's Beijing goes; Pro League runs twice a year, so its last season (6 months ago) stays, but the
    # season a year before is dropped
    assert cp.defending(res, live, tours) == {"IEM/2026/Beijing": "IEM/2025/Beijing", "ESL/Pro_League/Season_24": "ESL/Pro_League/Season_22"}
    # a move to another city: the same organiser and tier, a year earlier to within 3 weeks
    tours = {"IEM/2025/Chengdu": {"tier": "1", "start": "2025-11-03", "end": "2025-11-09"},
             "IEM/2026/Katowice": {"tier": "1", "start": "2026-01-28", "end": "2026-02-08"},
             "IEM/2026/Beijing": {"tier": "1", "start": "2026-11-02", "end": "2026-11-08"}}
    res = [("r1", "2025-11-09", 1000, "IEM/2025/Chengdu"), ("r2", "2026-02-08", 1000, "IEM/2026/Katowice")]
    assert cp.defending(res, [{"page": "IEM/2026/Beijing", "start": "2026-11-02"}], tours) == {"IEM/2026/Beijing": "IEM/2025/Chengdu"}


def test_match_points():
    # an 8-team S-Tier LAN: quarter-finals on day 1, semis day 2, final day 3; A beats E, C and B
    tours = {"Ev": {"tier": "1", "tiertype": "", "start": "2026-10-01", "end": "2026-10-03", "teams": 8, "lan": True, "valve": "Tier 1"}}
    places = {"Ev": [{"place": "1", "team": "A", "date": "2026-10-03"}, {"place": "2", "team": "B", "date": "2026-10-03"},
                     {"place": "3-4", "team": "C", "date": "2026-10-02"}, {"place": "3-4", "team": "D", "date": "2026-10-02"}]
                    + [{"place": "5-8", "team": n, "date": "2026-10-01"} for n in "EFGH"]}
    names = "ABCDEFGH"
    def mm(k, a, b, day, winner):
        x = m("Ev", a, b, names.index(a), names.index(b))
        x.update(id=f"m{k}", time=int(__import__("datetime").datetime(2026, 10, day, 12 + k % 4).timestamp()), winner=winner)
        return x
    matches = [mm(0, "A", "E", 1, 1), mm(1, "B", "F", 1, 1), mm(2, "C", "G", 1, 1), mm(3, "D", "H", 1, 1),
               mm(4, "A", "C", 2, 1), mm(5, "B", "D", 2, 1), mm(6, "A", "B", 3, 1)]
    got = cp.match_points(ad.Data(matches, tours, places, {}), lambda x, i: f"r{x['rosters'][i]}", "2026-10-10")
    # A: a quarter-final win makes it sure of 3rd-4th (400), the semi of 2nd (+250), the final the rest (+350)
    assert (got[("m0", "r0")], got[("m4", "r0")], got[("m6", "r0")]) == (400, 250, 350)
    assert got[("m1", "r1")] + got[("m5", "r1")] + got[("m6", "r1")] == 650 and got[("m6", "r1")] == 0
    assert got[("m2", "r2")] + got[("m4", "r2")] == 400 and got[("m4", "r2")] == 0  # C: all of it with the quarter win
    assert ("m0", "r4") not in got or got[("m0", "r4")] == 200                       # E: 5th-8th, on its only match


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
