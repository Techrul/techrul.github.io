#!/usr/bin/env python3
"""Offline tests for scripts/fetch_cs2.py and scripts/lp_api.py against a fake Liquipedia API.

    python3 tests/test_fetch_cs2.py
"""
import email.message
import io
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import fetch_cs2  # noqa: E402
import lp_api  # noqa: E402

TODAY = date(2026, 10, 19)


def make_match(i, day):
    ts = int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp()) + i
    team = lambda side: {"name": f"Team{side}", "template": f"team{side}", "type": "team", "score": 2 - side, "status": "S",
                         "match2players": [{"id": k, "name": f"P{side}{k}", "flag": "Denmark"} for k in (5, 4, 3, 2, 1)]}
    return {"objectname": f"1_m{i}", "match2id": f"m{i}", "pagename": "Ev", "parent": f"Ev/{day.year}",
            "tournament": "Ev", "date": f"{day} 12:00:00", "finished": 1, "winner": "1", "walkover": "",
            "liquipediatier": "3", "liquipediatiertype": "", "publishertier": "Tier 2", "type": "Online",
            "extradata": {"timestamp": ts}, "match2opponents": [team(1), team(2)]}


class FakeApi:
    """Answers match/tournament/placement queries from in-memory rows, honouring date windows, limit and offset."""

    def __init__(self, n_per_day=40, start=date(2025, 1, 1)):
        self.matches, d, i = [], start, 0
        while d <= TODAY:
            for _ in range(n_per_day):
                self.matches.append(make_match(i, d))
                i += 1
            d += timedelta(days=1)
        self.tournaments = [{"pagename": f"Ev/{y}-{m:02d}", "name": f"Ev {y}-{m:02d}", "startdate": f"{y}-{m:02d}-01",
                             "enddate": f"{y}-{m:02d}-20", "prizepool": 100000, "type": "Offline",
                             "publishertier": "Tier 2", "liquipediatier": "2", "status": "finished"}
                            for y in (2025, 2026) for m in range(1, 13)]
        self.placements = [{"pagename": t["pagename"], "placement": str(k), "opponentname": f"Team{k}",
                            "prizemoney": 1000 * (5 - k), "date": t["enddate"] + " 00:00:00",
                            "opponentplayers": {"p1": f"P{k}1", "p1flag": "Sweden"}, "extradata": {"playershare": 10}}
                           for t in self.tournaments for k in (1, 2, 3)]
        self.calls = []
        self.fail_429_on = set()

    @staticmethod
    def _in_window(value, cond, field):
        lo = re.search(rf"\[\[{field}::>([0-9-]+)\]\]", cond)
        hi = re.search(rf"\[\[{field}::<([0-9-]+)\]\]", cond)
        v = value[:10]
        return (not lo or v > lo.group(1)) and (not hi or v < hi.group(1))

    def __call__(self, req, timeout=0):
        self.calls.append(req.full_url)
        n = len(self.calls)
        assert req.get_header("Authorization") == "Apikey test-key"
        if n in self.fail_429_on:
            h = email.message.Message()
            h["Retry-After"] = "60"
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", h, io.BytesIO(b"slow down"))
        url = urllib.parse.urlparse(req.full_url)
        q = dict(urllib.parse.parse_qsl(url.query))
        cond, kind = q["conditions"], url.path.rsplit("/", 1)[1]
        if kind == "match":
            rows = [m for m in self.matches if self._in_window(m["date"], cond, "date")]
        elif kind == "tournament":
            rows = [t for t in self.tournaments if self._in_window(t["enddate"], cond, "enddate")
                    and self._in_window(t["startdate"], cond, "startdate")]
        else:
            rows = [p for p in self.placements if self._in_window(p["date"], cond, "date")]
        off, lim = int(q.get("offset", 0)), int(q["limit"])
        body = json.dumps({"result": rows[off:off + lim]}).encode()

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass
        return R(body)


def client(api, **kw):
    clock = {"t": 0.0}

    def sleep(s):
        clock["t"] += s
    return lp_api.Client("counterstrike", key="test-key", contact="", opener=api, sleep=sleep,
                         clock=lambda: clock["t"], log=lambda *a: None, **kw), clock


def count_stored(root):
    n = 0
    for f in os.listdir(os.path.join(root, "matches")):
        with open(os.path.join(root, "matches", f)) as fh:
            n += sum(1 for line in fh if line.strip())
    return n


def test_full_run_and_resume():
    api = FakeApi()
    with tempfile.TemporaryDirectory() as root:
        # run 1: a small budget stops part way; nothing half-done is marked as fetched
        c, _ = client(api, max_requests=25)
        store = fetch_cs2.Store(root)
        try:
            fetch_cs2.run(c, store, TODAY, "2025-01", log=lambda *a: None)
            raise AssertionError("expected the budget to run out")
        except lp_api.BudgetUsed:
            pass
        store.save()
        assert c.sent == 25
        partial = count_stored(root)
        assert 0 < partial < len(api.matches)
        state = json.load(open(os.path.join(root, "state.json")))["months"]
        assert "2026-10" in state and "2025-01" not in state

        # runs 2+: carry on until done, never refetching a finished month
        for _ in range(10):
            c, _ = client(api, max_requests=25)
            store = fetch_cs2.Store(root)
            try:
                fetch_cs2.run(c, store, TODAY, "2025-01", log=lambda *a: None)
                break
            except lp_api.BudgetUsed:
                store.save()
        else:
            raise AssertionError("never finished")
        assert count_stored(root) == len(api.matches), (count_stored(root), len(api.matches))

        # a later run only refreshes (3 requests: matches, tournaments, placements)
        before = len(api.calls)
        c, _ = client(api, max_requests=25)
        fetch_cs2.run(c, fetch_cs2.Store(root), TODAY, "2025-01", log=lambda *a: None)
        assert len(api.calls) - before == 3, len(api.calls) - before

        # stored shapes
        with open(os.path.join(root, "matches", "2026-03.jsonl")) as fh:
            m = json.loads(fh.readline())
        assert m["teams"][0]["players"] == ["P11", "P12", "P13", "P14", "P15"]  # sorted by Liquipedia's player id
        assert m["valve"] == "Tier 2" and m["winner"] == 1 and m["lan"] is False and m["date"] == "2026-03-01"
        tours = json.load(open(os.path.join(root, "tournaments.json")))
        assert tours["Ev/2026-03"]["pool"] == 100000 and tours["Ev/2026-03"]["lan"] is True
        places = json.load(open(os.path.join(root, "placements.json")))
        assert [p["place"] for p in places["Ev/2026-03"]] == ["1", "2", "3"]
        assert places["Ev/2026-03"][0]["player_share"] == 10
        assert json.load(open(os.path.join(root, "players.json")))["P11"] == "Denmark"


def test_month_settles_later():
    api = FakeApi(n_per_day=2, start=date(2026, 9, 1))
    with tempfile.TemporaryDirectory() as root:
        c, _ = client(api, max_requests=100)
        fetch_cs2.run(c, fetch_cs2.Store(root), TODAY, "2026-09", log=lambda *a: None)
        store = fetch_cs2.Store(root)
        # September ends 1 Oct, settles 22 Oct: fetched on 19 Oct, so it is fetched once more after it settles
        assert not fetch_cs2.needs_fetch(store.state, "2026-09", "matches", TODAY)
        assert fetch_cs2.needs_fetch(store.state, "2026-09", "matches", date(2026, 10, 22))
        store.mark("2026-09", "matches", date(2026, 10, 22))
        assert not fetch_cs2.needs_fetch(store.state, "2026-09", "matches", date(2027, 5, 1))


def test_paging():
    api = FakeApi(n_per_day=60, start=date(2026, 3, 1))  # 1,860 matches in March: two pages
    c, _ = client(api, max_requests=10)
    rows = c.get_all("match", "[[date::>2026-02-28]] AND [[date::<2026-04-01]]")
    assert len(rows) == 31 * 60 and c.sent == 2
    assert len({r["objectname"] for r in rows}) == len(rows)


def test_429_waits_then_stops():
    api = FakeApi(n_per_day=1, start=date(2026, 10, 1))
    api.fail_429_on = {1}
    c, clock = client(api, max_requests=10)
    c.get("match", conditions="[[date::>2026-10-01]]", limit=10)  # one 429, then fine after waiting
    assert c.sent == 2 and clock["t"] >= 60
    api.fail_429_on = {3, 4, 5}
    try:
        c.get("match", conditions="[[date::>2026-10-01]]", limit=10)
        raise AssertionError("expected RateLimited")
    except lp_api.RateLimited:
        pass


def test_hourly_pacing():
    api = FakeApi(n_per_day=1, start=date(2026, 10, 1))
    c, clock = client(api, max_requests=100, per_hour=5)
    for _ in range(6):
        c.get("match", conditions="[[date::>2026-10-01]]", limit=1)
    assert clock["t"] >= 3600  # the 6th request waited for the hour to roll over


def test_time_limit_stops_instead_of_waiting():
    api = FakeApi(n_per_day=1, start=date(2026, 10, 1))
    c, clock = client(api, max_requests=100, per_hour=5, max_seconds=1800)
    for _ in range(5):
        c.get("match", conditions="[[date::>2026-10-01]]", limit=1)
    try:
        c.get("match", conditions="[[date::>2026-10-01]]", limit=1)  # would need to wait an hour: stop instead
        raise AssertionError("expected BudgetUsed")
    except lp_api.BudgetUsed:
        pass
    assert c.sent == 5 and clock["t"] < 1800


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)} tests passed")
