#!/usr/bin/env python3
"""Tests for scripts/fetch_atp_espn.py (parsing) and ratings.load_espn_rankings (matching names to players)."""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import fetch_atp_espn as fe  # noqa: E402
import ratings  # noqa: E402


def test_parse():
    data = {"rankings": [{"id": "1", "name": "ATP", "shortName": "ATP", "type": "atp", "ranks": [
        {"current": 2, "previous": 1, "points": 9450.0, "athlete": {"id": "3623", "displayName": "Jannik Sinner", "citizenshipCountry": "ITA"}},
        {"current": 1, "previous": 2, "points": 9550.0, "athlete": {"id": "2375", "displayName": "Alexander Zverev", "citizenshipCountry": "GER"}}]}]}
    assert fe.parse(data) == [(1, "Alexander Zverev", "2375", "GER", 9550), (2, "Jannik Sinner", "3623", "ITA", 9450)]


def test_names_matched():
    d = datetime(2026, 10, 1)
    rows = [{"_date": d, "winner_id": "Z1", "winner_name": "Alexander Zverev", "loser_id": "F1", "loser_name": "Félix Auger-Aliassime"},
            {"_date": d, "winner_id": "M1", "winner_name": "Alex de Minaur", "loser_id": "J1", "loser_name": "Rafael Jodar"},
            {"_date": d, "winner_id": "W1", "winner_name": "Yibing Wu", "loser_id": "C1", "loser_name": "Coleman Wong"}]
    with tempfile.TemporaryDirectory() as root:
        with open(os.path.join(root, "2026-11-02.csv"), "w") as fh:
            fh.write("date,rank,name,espn_id,ioc,points\n"
                     "2026-11-02,1,Alexander Zverev,2375,GER,9550\n"
                     "2026-11-02,9,Alex De Minaur,1,AUS,3410\n"
                     "2026-11-02,10,Rafa Jodar,2,ESP,3209\n"          # shortened first name: same initial and surname
                     "2026-11-02,13,Felix Auger Aliassime,3,CAN,2875\n"
                     "2026-11-02,60,Wu Yibing,4,CHN,800\n"
                     "2026-11-02,61,Chak Lam Coleman Wong,5,HKG,790\n"
                     "2026-11-02,99,Nobody Here,77,USA,500\n")
        got = ratings.load_espn_rankings(root, rows)[datetime(2026, 11, 2)]
    assert [(rk, pid) for rk, pid, _n, _p in got] == [(1, "Z1"), (9, "M1"), (10, "J1"), (13, "F1"), (60, "W1"), (61, "C1"), (99, "espn:77")]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
