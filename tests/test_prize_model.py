"""Tests for scripts/prize_model.py. Run: python3 tests/test_prize_model.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import prize_model as pm  # noqa: E402

TABLE = {"W": 140.0e3, "F": 80.0e3, "SF": 45.0e3, "QF": 25.0e3, "R16": 14.0e3, "R32": 8.0e3}
CACHE = {
    "2025-1": {"name": "Alpha", "year": 2025, "level": "250", "draw": "28", "source": "table",
               "rounds": TABLE, "currency": "USD", "season_total": [1_000_000.0, "USD"]},
    "2025-2": {"name": "Beta", "year": 2025, "level": "250", "draw": "28", "source": "season-total",
               "season_total": [500_000.0, "EUR"], "total": 500_000.0, "currency": "EUR"},
    "2026-1": {"name": "Wrong", "year": 2026, "level": "500", "draw": "32", "source": "total",
               "season_total": [2_500_000.0, "EUR"]},
    "2025-9": {"name": "Gamma", "year": 2025, "level": "250", "draw": "28", "source": "season-total",
               "season_total": [700_000.0, "USD"]},
}
FX = pm.FX({2025: {"USD": 1.2, "GBP": 0.9, "AUD": 1.8}, 2026: {"USD": 1.2, "GBP": 0.9, "AUD": 1.8}})


def test_table_used_as_is():
    m = pm.PrizeModel(CACHE, FX)
    rounds, how = m.round_prizes_usd("2025-1")
    assert how == "table" and rounds["W"] == 140000


def test_totals_split_with_learned_shares_and_converted():
    m = pm.PrizeModel(CACHE, FX)
    rounds, how = m.round_prizes_usd("2025-2")
    assert how.startswith("estimated")
    assert abs(rounds["W"] - 500_000 * 0.14 * 1.2) < 1  # 14% of the pool, EUR -> USD


def test_id_reused_by_another_tournament_is_ignored():
    m = pm.PrizeModel(CACHE, FX)
    rounds, how = m.round_prizes_usd("2026-1", name="Gamma", year=2026, level="250", draw="28")
    assert how == "estimated from 2025 edition"
    assert abs(rounds["W"] - 700_000 * 0.14) < 1


def test_bad_values_dropped():
    cache = dict(CACHE)
    cache["2025-5"] = {"name": "Finals", "year": 2025, "level": "F", "draw": "8", "source": "table",
                       "currency": "USD", "rounds": {"PART": 3.0, "RR": 396500.0, "FW": 2237200.0}}
    m = pm.PrizeModel(cache, FX)
    assert "PART" not in m.events["2025-5"]["rounds"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("pass", name)
