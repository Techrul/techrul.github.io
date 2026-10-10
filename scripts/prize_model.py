#!/usr/bin/env python3
"""Turn data/prize_money.json into per-round singles prize money in US dollars, for every event.

    python3 scripts/prize_model.py --cache data/prize_money.json --report

Rules
- Event pool: the total printed in Wikipedia's '<year> ATP Tour' schedule (ATP-only, so comparable
  across events). If missing and the event has a round table, the pool is implied from the table's
  singles payout. Infobox totals come last: for joint events they often include the WTA draw (the
  2025 US Open infobox says $90M; its ATP schedule total is $40.4M).
- Per-round amounts: the event's own table when Wikipedia has one. Otherwise pool x share, where the
  share of each round is learned from table events of the same tier and draw size (28/32, 48/56, 96,
  128 are treated as one size each). Nothing is typed in by hand.
- Missing pool: the same tournament's pool in the nearest year, else the median pool of its tier.
- Currency: converted to USD with yearly average ECB rates (fetched; fallback values are the ECB
  2025 averages published by the Bank of Finland).
- Values under 1,000 are treated as parsing errors and dropped.
"""
import argparse
import csv
import io
import json
import statistics
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
# Units per 1 EUR, 2025 annual averages (ECB via Bank of Finland). Used when the ECB file is unreachable.
FALLBACK_PER_EUR = {"USD": 1.1300, "GBP": 0.85687, "AUD": 1.7517, "CAD": 1.5800, "CHF": 0.9370}
MAIN_ROUNDS = ("W", "F", "SF", "QF", "R16", "R32", "R64", "R128")
LOSERS = {"W": 1, "F": 1, "SF": 2, "QF": 4, "R16": 8, "R32": 16, "R64": 32, "R128": 64}  # players paid per round
FINALS_KEYS = ("PART", "RR", "SFW", "FW")


def draw_bucket(level, draw):
    try:
        d = int(draw)
    except (TypeError, ValueError):
        d = 0
    if level == "F":
        return 8
    for size in (32, 56, 96, 128):
        if d <= size:
            return size
    return 128


# ----------------------------------------------------------------------------- exchange rates
def ecb_yearly_rates(timeout=30):
    """{year: {currency: units per EUR}} from the ECB history file, or {} if unreachable."""
    try:
        with urllib.request.urlopen(ECB_URL, timeout=timeout) as resp:
            blob = resp.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            text = zf.read(zf.namelist()[0]).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - network or format trouble; fall back
        print(f"WARN ECB rates unavailable ({exc}); using 2025 averages", file=sys.stderr)
        return {}
    sums = defaultdict(lambda: defaultdict(float))
    counts = defaultdict(lambda: defaultdict(int))
    for row in csv.DictReader(io.StringIO(text)):
        year = int(row["Date"][:4])
        for cur in FALLBACK_PER_EUR:
            v = (row.get(cur) or "").strip()
            if v and v != "N/A":
                sums[year][cur] += float(v)
                counts[year][cur] += 1
    return {y: {c: sums[y][c] / counts[y][c] for c in sums[y]} for y in sums}


class FX:
    def __init__(self, yearly=None):
        self.yearly = yearly or {}
        self.used_fallback = set()

    def to_usd(self, amount, currency, year):
        if currency in (None, "USD"):
            return amount
        rates = self.yearly.get(year) or self.yearly.get(max(self.yearly)) if self.yearly else None
        if not rates or "USD" not in rates or (currency != "EUR" and currency not in rates):  # rates are per EUR
            rates = FALLBACK_PER_EUR
            self.used_fallback.add(year)
        per_eur_usd, per_eur_cur = rates["USD"], (1.0 if currency == "EUR" else rates[currency])
        return amount / per_eur_cur * per_eur_usd


# ----------------------------------------------------------------------------- model
class PrizeModel:
    def __init__(self, cache, fx):
        self.fx = fx
        self.events = {}
        for key, rec in cache.items():
            if rec.get("source") in ("unmatched", "error"):
                continue
            ev = {"id": key, "name": rec.get("name"), "year": rec.get("year"), "level": rec.get("level"),
                  "bucket": draw_bucket(rec.get("level"), rec.get("draw")), "source": rec.get("source")}
            st = rec.get("season_total")
            if st and st[0] and st[0] >= 1000:
                ev["pool"], ev["pool_cur"], ev["pool_from"] = st[0], st[1], "season schedule"
            elif rec.get("total") and rec["total"] >= 1000:
                ev["pool"], ev["pool_cur"], ev["pool_from"] = rec["total"], rec.get("total_currency") or rec.get("currency"), "page total"
            rounds = {k: v for k, v in (rec.get("rounds") or {}).items() if v and v >= 1000}
            if rounds:
                ev["rounds"], ev["cur"] = rounds, rec.get("currency")
            self.events[key] = ev
        self.payout_ratio = self._learn_payout_ratio()
        for ev in self.events.values():  # tables without a schedule total: imply the pool from the table
            if "rounds" in ev and ev.get("pool_from") != "season schedule" and ev["level"] in self.payout_ratio:
                ev["pool"], ev["pool_cur"], ev["pool_from"] = self._payout(ev) / self.payout_ratio[ev["level"]], ev["cur"], "round table"
        self.shares = self._learn_shares()

    def _payout(self, ev):
        return sum(v * LOSERS[r] for r, v in ev["rounds"].items() if r in LOSERS and LOSERS[r] * 2 <= max(ev["bucket"], 2) * 2)

    def _learn_payout_ratio(self):
        """{level: median of singles main-draw payout / schedule pool}, from events that have both."""
        acc = defaultdict(list)
        for ev in self.events.values():
            if "rounds" in ev and ev.get("pool_from") == "season schedule" and ev["cur"] == ev["pool_cur"] and ev["level"] != "F":
                acc[ev["level"]].append(self._payout(ev) / ev["pool"])
        return {lvl: statistics.median(v) for lvl, v in acc.items()}

    def resolve(self, key, name=None, year=None, level=None, draw=None):
        """Event record for key; for events missing from the cache, or with no prize data, borrow
        tier and pool from the same tournament's nearest other year."""
        ev = self.events.get(key)
        if ev is not None and name and ev["name"] != name:
            ev = None  # the cached record is a different tournament under the same id (a source data error)
        if ev is None:
            ev = {"id": key, "name": name, "year": year, "level": level, "bucket": draw_bucket(level, draw), "source": "missing"}
        if "rounds" in ev or "pool" in ev:
            return ev
        same = [e for e in self.events.values() if e["name"] == ev["name"] and e is not ev and ("pool" in e or "rounds" in e)]
        if same:
            near = min(same, key=lambda e: abs(e["year"] - ev["year"]))
            ev = dict(ev, level=near["level"], bucket=near["bucket"])
            if "pool" in near:
                ev.update(pool=near["pool"], pool_cur=near["pool_cur"], pool_from=f'{near["year"]} edition')
        return ev

    def _learn_shares(self, exclude=None):
        """{(level, bucket): {round: median share of pool}} from events with a table and a pool."""
        acc = defaultdict(lambda: defaultdict(list))
        for key, ev in self.events.items():
            if key == exclude or "rounds" not in ev or "pool" not in ev or ev["level"] == "F":
                continue
            if ev["cur"] != ev["pool_cur"]:
                continue
            for r, v in ev["rounds"].items():
                acc[(ev["level"], ev["bucket"])][r].append(v / ev["pool"])
        return {k: {r: statistics.median(vs) for r, vs in d.items()} for k, d in acc.items()}

    def _pool(self, ev):
        if "pool" in ev:
            return ev["pool"], ev["pool_cur"], ev["pool_from"]
        tier = [self.fx.to_usd(e["pool"], e["pool_cur"], e["year"]) for e in self.events.values()
                if e["level"] == ev["level"] and e["bucket"] == ev["bucket"] and "pool" in e]
        if tier:
            return statistics.median(tier), "USD", "tier median"
        return None, None, None

    def round_prizes_usd(self, key, shares=None, **info):
        """({round: USD}, how) for one event. how says where the numbers came from."""
        ev = self.resolve(key, **info)
        if "rounds" in ev and shares is None:
            return {r: self.fx.to_usd(v, ev["cur"], ev["year"]) for r, v in ev["rounds"].items()}, "table"
        shares = shares or self.shares
        share = shares.get((ev["level"], ev["bucket"]))
        if share is None:  # no table event of this exact size: any size in the tier
            sizes = [k for k in shares if k[0] == ev["level"]]
            share = shares[min(sizes, key=lambda k: abs(k[1] - ev["bucket"]))] if sizes else None
        pool, cur, how = self._pool(ev)
        if share is None or pool is None:
            return {}, "no prize data"
        return {r: self.fx.to_usd(pool * s, cur, ev["year"]) for r, s in share.items()}, f"estimated from {how}"

    def pool_usd(self, key, **info):
        ev = self.resolve(key, **info)
        pool, cur, _ = self._pool(ev)
        return self.fx.to_usd(pool, cur, ev["year"]) if pool else None

    def leave_one_out(self):
        """Predict every table event's rounds from its pool with shares learned from the other events."""
        rows = []
        for key, ev in self.events.items():
            if "rounds" not in ev or "pool" not in ev or ev["level"] == "F" or ev["cur"] != ev["pool_cur"]:
                continue
            shares = self._learn_shares(exclude=key)
            share = shares.get((ev["level"], ev["bucket"]))
            if not share:
                continue
            errs = [abs(ev["pool"] * share[r] - v) / v for r, v in ev["rounds"].items() if r in share and r in MAIN_ROUNDS]
            if errs:
                rows.append((ev["level"], ev["bucket"], ev["name"], ev["year"], statistics.median(errs), max(errs)))
        return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="data/prize_money.json")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--offline", action="store_true", help="skip the ECB download and use fallback rates")
    args = ap.parse_args()
    with open(args.cache, encoding="utf-8") as fh:
        cache = json.load(fh)
    fx = FX({} if args.offline else ecb_yearly_rates())
    model = PrizeModel(cache, fx)

    print("Learned shares of the event pool (winner, quarterfinal, first round):")
    for (lvl, b), s in sorted(model.shares.items()):
        first = s.get("R128") or s.get("R64") if b >= 96 else (s.get("R64") if b == 56 else s.get("R32"))
        print(f"  {lvl:>3} draw {b:>3}: W {s.get('W', 0):.3f}  QF {s.get('QF', 0):.4f}  first round {first or 0:.4f}")

    rows = model.leave_one_out()
    print(f"\nLeave-one-out check on {len(rows)} events that have real tables")
    by = defaultdict(list)
    for lvl, b, name, year, med, worst in rows:
        by[(lvl, b)].append((med, worst, name, year))
    for k, vals in sorted(by.items()):
        meds = [v[0] for v in vals]
        worst = max(vals)
        print(f"  {k[0]:>3} draw {k[1]:>3}: {len(vals):2} events, median round error {100 * statistics.median(meds):.1f}%, "
              f"worst event {worst[2]} {worst[3]} ({100 * worst[0]:.1f}% median, {100 * worst[1]:.1f}% max)")
    if args.report:
        how = defaultdict(int)
        for key in model.events:
            how[model.round_prizes_usd(key)[1]] += 1
        print("\nWhere each event's per-round money comes from:", dict(how))
        if fx.used_fallback:
            print("Fallback exchange rates used for:", sorted(fx.used_fallback))


if __name__ == "__main__":
    main()
