#!/usr/bin/env python3
"""Find singles prize money for each ATP tour event on Wikipedia, for the VRS model.

    python3 scripts/prize_money.py --raw data/raw --years 2025 2026 --dry-run

For every tour-level event (Grand Slam, Masters 1000, 500, 250, ATP Finals) in the match files:
  1. find the event's Wikipedia page with the search API ("<year> <tournament name> tennis"),
  2. read the rendered page (action=parse) and look for, in order of preference:
       - a prize money table with a singles row or column, by round  -> source "table"
       - a prize money total in the infobox                          -> source "total"
  3. record the currency (USD, EUR, GBP, AUD) as printed.

Results go to data/prize_money.json (a cache: each event is looked up once; failures are retried
after 30 days). --dry-run prints a coverage report and changes nothing else.

Prize money from Wikipedia is CC BY-SA 4.0: credit Wikipedia on the site.
Only the documented MediaWiki API is used, about one request per second, with a contact User-Agent.
"""
import argparse
import csv
import glob
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime

from bs4 import BeautifulSoup

API = "https://en.wikipedia.org/w/api.php"
TOUR_LEVELS = {"G": "Grand Slam", "M": "Masters 1000", "500": "ATP 500", "250": "ATP 250", "F": "ATP Finals"}
RETRY_DAYS = 30

# Round labels as they appear in Wikipedia table headers -> our labels
ROUND_ALIASES = [
    # ATP Finals tables pay per stage won rather than per round reached
    (r"^(final win|final winner)$", "FW"),
    (r"^(semi[- ]?final win)$", "SFW"),
    (r"^(round[- ]robin.*win.*|.*per round[- ]robin win|rr( match)? win)$", "RR"),
    (r"^(participation( fee)?)$", "PART"),
    (r"^(alternates?)$", "ALT"),
    (r"^(w|winner|champion|champions?)$", "W"),
    (r"^(f|final|finals?|finalist|runner[- ]?up)$", "F"),
    (r"^(sf|semi[- ]?finals?|semifinalists?)$", "SF"),
    (r"^(qf|quarter[- ]?finals?|quarterfinalists?)$", "QF"),
    (r"^(r16|round of 16|4r|fourth round|last 16)$", "R16"),
    (r"^(r32|round of 32|3r|third round)$", "R32"),
    (r"^(r64|round of 64|2r|second round)$", "R64"),
    (r"^(r128|round of 128|1r|first round)$", "R128"),
    (r"^(q|qualifier|qualifiers?|qlfr)$", "Q"),
    (r"^(q3|third qualifying round)$", "Q3"),
    (r"^(q2|second qualifying round)$", "Q2"),
    (r"^(q1|first qualifying round)$", "Q1"),
    (r"^(rr|round robin)$", "RR"),
]
CURRENCY_PATTERNS = [  # checked in order; the first match wins
    (r"A\$|AU\$|AUD", "AUD"),
    (r"US\$|USD", "USD"),
    (r"€|EUR|euro", "EUR"),
    (r"£|GBP", "GBP"),
    (r"CA\$|C\$|CAD", "CAD"),
    (r"CHF", "CHF"),
    (r"\$", "USD"),
]


# ----------------------------------------------------------------------------- parsing helpers
def clean(text):
    text = re.sub(r"\[[^\]]*\]", "", text or "")  # footnote markers like [a] or [1]
    return re.sub(r"\s+", " ", text).strip()


def round_label(text):
    t = clean(text).lower().replace("–", "-").rstrip(":")
    t = re.sub(r"\s*\(.*?\)\s*", "", t).strip()
    for pattern, label in ROUND_ALIASES:
        if re.match(pattern, t):
            return label
    return None


def detect_currency(text):
    for pattern, cur in CURRENCY_PATTERNS:
        if re.search(pattern, text or ""):
            return cur
    return None


def parse_amount(text):
    """'$1,201,125' -> 1201125.0; '€6.1 million' -> 6100000.0; returns None if no number."""
    t = clean(text).replace(" ", " ")
    m = re.search(r"(\d[\d,.]*)\s*(million|m\b)?", t, re.I)
    if not m:
        return None
    num = m.group(1)
    if m.group(2):
        return float(num.replace(",", "")) * 1_000_000
    num = num.replace(",", "")
    if num.count(".") == 1 and len(num.split(".")[1]) == 3:  # 1.201.125 style
        num = num.replace(".", "")
    try:
        return float(num.replace(".", "")) if num.count(".") > 1 else float(num)
    except ValueError:
        return None


def table_grid(table):
    """Expand a <table> into a list of rows of cell texts (handles colspan, ignores rowspan)."""
    grid = []
    for tr in table.find_all("tr"):
        row = []
        for cell in tr.find_all(["th", "td"]):
            span = int(cell.get("colspan", 1) or 1)
            row.extend([clean(cell.get_text(" "))] * span)
        if row:
            grid.append(row)
    return grid


def is_mens_singles(label):
    t = label.lower()
    return "singles" in t and "women" not in t and "wheelchair" not in t and "boys" not in t and "girls" not in t


def parse_prize_table(grid):
    """Return ({round: amount}, currency) for men's singles prize money, or (None, None).

    Handles rounds across the top (one row per event; header rows may repeat mid-table, e.g. a
    combined "points" then "prize money" table) and rounds down the first column (one column per
    event). Rows whose values look like ranking points (top value under 10,000) are ignored.
    """
    if len(grid) < 2:
        return None, None
    currency = detect_currency(" ".join(" ".join(r) for r in grid))

    def money(out):
        return len(out) >= 3 and max(out.values()) >= 10_000

    # Layout A: rows of round labels, followed by event rows
    labels = None
    for row in grid:
        row_labels = [round_label(c) for c in row]
        if sum(1 for x in row_labels if x) >= 3:
            labels = row_labels
            continue
        if labels and row and is_mens_singles(row[0]):
            out = {}
            for i, lab in enumerate(labels):
                if lab and i < len(row):
                    amt = parse_amount(row[i])
                    if amt is not None:
                        out.setdefault(lab, amt)
            if money(out):
                return out, detect_currency(" ".join(row)) or currency
    # Layout B: first column holds round labels
    first_col = [round_label(r[0]) if r else None for r in grid]
    if sum(1 for x in first_col if x) >= 3:
        header = grid[0]
        col = next((i for i, c in enumerate(header) if is_mens_singles(c)), None)
        if col is None and len(header) == 2:
            col = 1  # single-event table: "Round | Prize money"
        if col is None:
            col = next((i for i, c in enumerate(header) if c.lower() in ("men's", "men", "atp")), None)
        if col is not None:
            out = {}
            for lab, row in zip(first_col, grid):
                if lab and col < len(row):
                    amt = parse_amount(row[col])
                    if amt is not None:
                        out.setdefault(lab, amt)
            if money(out):
                return out, currency
    return None, None


def describe_tables(html, limit=8):
    """Short text summary of a page's tables, for --debug."""
    soup = BeautifulSoup(html, "html.parser")
    lines = []
    for table in soup.find_all("table")[:limit]:
        heading = table.find_previous(["h2", "h3", "h4"])
        grid = table_grid(table)
        head = " | ".join(grid[0])[:110] if grid else ""
        second = " | ".join(grid[1])[:110] if len(grid) > 1 else ""
        lines.append(f'      [{clean(heading.get_text(" "))[:40] if heading else "-"}] {head}  //  {second}')
    return lines


def parse_page(html):
    """Return dict with any of: rounds, currency, total, total_currency."""
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    # infobox total
    box = soup.find("table", class_=lambda c: c and "infobox" in c)
    if box:
        for tr in box.find_all("tr"):
            th, td = tr.find("th"), tr.find("td")
            if th and td and "prize" in th.get_text(" ").lower():
                text = clean(td.get_text(" "))
                # pages for joint ATP/WTA events can list two totals; prefer the men's / ATP one
                parts = re.split(r"\s(?=\(?(?:men|women|atp|wta))", text, flags=re.I)
                pick = next((p for p in parts if re.search(r"men'?s|atp", p, re.I) and not re.search(r"women|wta", p, re.I)), parts[0])
                amt = parse_amount(pick)
                if amt:
                    result["total"] = amt
                    result["total_currency"] = detect_currency(pick) or detect_currency(text)
                break

    # prize tables: any table that sits under a heading mentioning prize money, or whose own text does
    for table in soup.find_all("table"):
        if box is not None and table is box:
            continue
        heading = table.find_previous(["h2", "h3", "h4"])
        near_prize = heading is not None and "prize" in heading.get_text(" ").lower()
        caption = table.find("caption")
        if not near_prize and not (caption and "prize" in caption.get_text(" ").lower()):
            continue
        rounds, cur = parse_prize_table(table_grid(table))
        if rounds:
            result["rounds"] = rounds
            result["currency"] = cur or result.get("total_currency")
            break
    return result


# ----------------------------------------------------------------------------- Wikipedia access
class Wiki:
    def __init__(self, contact, delay=1.0):
        self.ua = f"tennis-rankings-site/0.1 (non-commercial, open source; contact: {contact})"
        self.delay = delay
        self.requests = 0

    def get(self, **params):
        params.update({"format": "json", "formatversion": "2", "maxlag": "5"})
        url = API + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": self.ua})
        time.sleep(self.delay)
        self.requests += 1
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def search(self, query, limit=6):
        data = self.get(action="query", list="search", srsearch=query, srlimit=str(limit), srnamespace="0")
        return [hit["title"] for hit in data.get("query", {}).get("search", [])]

    def parse(self, title):
        data = self.get(action="parse", page=title, prop="text", redirects="1")
        if "error" in data:
            raise LookupError(data["error"].get("info", "parse error"))
        return data["parse"]["title"], data["parse"]["text"]


LEVEL_WORDS = {
    "G": ("grand slam",),
    "M": ("masters 1000", "atp masters", "masters series"),
    "500": ("atp 500", "atp tour 500", "500 series"),
    "250": ("atp 250", "atp tour 250", "250 series"),
    "F": ("atp finals", "tour finals"),
}
NAME_STOPWORDS = {"masters", "open", "club", "championships", "championship", "cup", "tour", "atp", "the", "de",
                  "s", "tennis", "international", "tournament"}
# TML names that share no word with the Wikipedia title or the city. Event identities, so they rarely change.
NAME_ALIASES = {
    "roland garros": ["french open"],
    "canada masters": ["canadian open", "national bank open", "toronto", "montreal"],
    "marrakech": ["marrakesh"],
}
BAD_TITLE = re.compile(r"\u2013| - |ATP Tour$|Challenger|WTA|season|Next Gen|\(page does not exist\)", re.I)


def norm(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", text).strip() + " "


def name_tokens(name):
    return [w for w in norm(name).split() if w not in NAME_STOPWORDS]


def names_event(name, haystack):
    """True if the normalized haystack names this TML tournament (all its key words, or an alias)."""
    toks = name_tokens(name)
    if toks and all(f" {t} " in haystack for t in toks):
        return True
    return any(norm(a) in haystack for a in NAME_ALIASES.get(name.lower(), []))


def page_identity(title, html):
    """Title plus the infobox fields that name the event or its place."""
    soup = BeautifulSoup(html, "html.parser")
    parts = [title]
    box = soup.find("table", class_=lambda c: c and "infobox" in c)
    if box:
        for tr in box.find_all("tr"):
            th, td = tr.find("th"), tr.find("td")
            if th and td and re.search(r"location|venue|city|name|tournament|host", th.get_text(" "), re.I):
                parts.append(td.get_text(" "))
    return norm(" ".join(parts))


def plausible(title, html, year, level, name):
    if not title.startswith(str(year)) or BAD_TITLE.search(title):
        return False
    text = BeautifulSoup(html, "html.parser").get_text(" ")[:6000].lower()
    if "tennis" not in text or not any(w in text for w in LEVEL_WORDS[level]):
        return False
    return names_event(name, page_identity(title, html))


AMOUNT_IN_TEXT = re.compile(r"(A\$|AU\$|US\$|€|£|\$)\s?(\d{1,3}(?:,\d{3})+)")


def season_schedule(wiki, year):
    """Read '<year> ATP Tour' once: [(event page title, normalized cell text, (amount, currency) or None)]."""
    try:
        _, html = wiki.parse(f"{year} ATP Tour")
    except LookupError:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for cell in soup.find_all(["td", "th"]):
        titles = [a.get("title") for a in cell.find_all("a") if a.get("title")]
        events = [t for t in titles if t.startswith(str(year)) and not BAD_TITLE.search(t)]
        if not events or events[0] in seen:
            continue
        seen.add(events[0])
        raw = cell.get_text(" ")
        m = AMOUNT_IN_TEXT.search(raw)
        total = (float(m.group(2).replace(",", "")), detect_currency(m.group(1))) if m else None
        out.append((events[0], norm(raw + " " + events[0]), total))
    return out


def schedule_candidates(schedule, ev):
    """Schedule entries that name this event, most specific first."""
    phrase = norm(ev["name"])
    exact = norm(f'{ev["year"]} {ev["name"]}')
    hits = []
    for title, text, total in schedule:
        if not names_event(ev["name"], text):
            continue
        tier_named = [lvl for lvl, words in LEVEL_WORDS.items() if any(w in text for w in words)]
        if tier_named and ev["level"] not in tier_named:
            continue  # the cell states a different tier
        rank = 0 if norm(title) == exact else (1 if phrase in norm(title) else 2)
        hits.append((rank, title, total))
    return [(t, tot) for _, t, tot in sorted(hits, key=lambda h: h[0])]


# ----------------------------------------------------------------------------- events
def load_events(raw_dir, years):
    events = {}
    for path in sorted(glob.glob(os.path.join(raw_dir, "*.csv"))):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                lvl = r.get("tourney_level")
                d = r.get("tourney_date") or ""
                if lvl not in TOUR_LEVELS or len(d) != 8 or int(d[:4]) not in years:
                    continue
                key = r["tourney_id"]
                ev = events.setdefault(key, {"id": key, "year": int(d[:4]), "date": d, "_votes": Counter()})
                ev["date"] = min(ev["date"], d)
                ev["_votes"][(r["tourney_name"], lvl, r.get("draw_size") or "")] += 1
    for ev in events.values():  # majority vote: a stray row with the wrong id must not rename an event
        ev["name"], ev["level"], ev["draw"] = ev.pop("_votes").most_common(1)[0][0]
    return events


def lookup(wiki, ev, schedule=(), debug=False):
    """Return a cache record for one event."""
    candidates = schedule_candidates(schedule, ev)
    totals = {t: tot for t, tot in candidates if tot}
    titles = [t for t, _ in candidates]
    for q in (f'{ev["year"]} {ev["name"]} tennis', f'{ev["year"]} {ev["name"]} ATP tournament'):
        if len(titles) >= 4:
            break
        titles += [t for t in wiki.search(q, limit=8) if t not in titles]
    tried = []
    for title in titles:
        if len(tried) >= 6:
            break
        if not title.startswith(str(ev["year"])) or BAD_TITLE.search(title):
            continue
        tried.append(title)
        try:
            real_title, html = wiki.parse(title)
        except LookupError:
            continue
        if not plausible(real_title, html, ev["year"], ev["level"], ev["name"]):
            continue
        found = parse_page(html)
        season_total = totals.get(title) or totals.get(real_title)
        rec = {"title": real_title, "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(real_title.replace(" ", "_"))}
        if season_total:
            rec["season_total"] = list(season_total)  # kept on every record; used to learn how totals split by round
        if found.get("rounds"):
            rec.update(source="table", rounds=found["rounds"], currency=found.get("currency"))
            if found.get("total"):
                rec.update(total=found["total"], total_currency=found.get("total_currency"))
        elif found.get("total"):
            rec.update(source="total", total=found["total"], currency=found.get("total_currency"))
        elif season_total:
            rec.update(source="season-total", total=season_total[0], currency=season_total[1])
        else:
            rec.update(source="none", reason="page found, no prize money table or total")
        if debug and rec["source"] != "table":
            rec["_tables"] = describe_tables(html)
        return rec  # only the first page that passes the checks is used
    if candidates and candidates[0][1]:
        title, (amount, cur) = candidates[0]
        return {"source": "season-total", "total": amount, "currency": cur, "title": title,
                "reason": "event page not confirmed; total from the season schedule", "tried": tried}
    return {"source": "unmatched", "reason": "no page passed the name and tier checks", "tried": tried}


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--cache", default="data/prize_money.json")
    ap.add_argument("--years", type=int, nargs="+", default=[date.today().year - 1, date.today().year])
    ap.add_argument("--dry-run", action="store_true", help="look everything up and print a report; do not write the cache")
    ap.add_argument("--limit", type=int, default=0, help="only look up this many events (for a quick test)")
    ap.add_argument("--only", nargs="+", default=None, help="only these tournament names, e.g. --only Halle Shanghai")
    ap.add_argument("--debug", action="store_true", help="for events without a prize table, print the page's tables")
    args = ap.parse_args()

    events = load_events(args.raw, set(args.years))
    if not events:
        sys.exit(f"no tour-level events for {args.years} in {args.raw}. Run fetch_tml.py first.")

    cache = {}
    if os.path.exists(args.cache):
        with open(args.cache, encoding="utf-8") as fh:
            cache = json.load(fh)

    wiki = Wiki(os.environ.get("CONTACT_EMAIL", "set-CONTACT_EMAIL"))
    todo = []
    for key, ev in sorted(events.items(), key=lambda kv: kv[1]["date"]):
        rec = cache.get(key)
        stale = rec and rec.get("source") in ("unmatched", "none", "error") and \
            (date.today() - datetime.strptime(rec.get("checked", "2000-01-01"), "%Y-%m-%d").date()).days >= RETRY_DAYS
        if args.dry_run or rec is None or stale:
            todo.append(ev)
    if args.only:
        wanted = {norm(n) for n in args.only}
        todo = [ev for ev in todo if norm(ev["name"]) in wanted]
    if args.limit:
        todo = todo[:args.limit]
    schedules = {}
    for year in sorted({ev["year"] for ev in todo}):
        try:
            schedules[year] = season_schedule(wiki, year)
        except Exception as exc:
            print(f"WARN could not read the {year} ATP Tour page: {exc}", file=sys.stderr)
            schedules[year] = []
        print(f"{year} ATP Tour schedule: {len(schedules[year])} event links")

    print(f"{len(events)} events for {args.years}; looking up {len(todo)} (about {len(todo) * 3} requests)\n")
    results = {}
    for ev in todo:
        try:
            rec = lookup(wiki, ev, schedules.get(ev["year"], []), args.debug)
        except Exception as exc:  # network trouble: record and move on
            rec = {"source": "error", "reason": str(exc)[:200]}
        rec.update(name=ev["name"], year=ev["year"], level=ev["level"], draw=ev["draw"],
                   checked=date.today().strftime("%Y-%m-%d"))
        results[ev["id"]] = rec
        rounds = rec.get("rounds") or {}
        detail = f'{rec.get("currency") or "?"} W={rounds.get("W", "-")}' if rec["source"] == "table" else \
            (f'{rec.get("currency") or "?"} total={rec.get("total")}' if rec["source"] in ("total", "season-total") else rec.get("reason", ""))
        print(f'{rec["source"]:12} {ev["level"]:>3} {ev["name"][:28]:28} -> {rec.get("title", "")[:45]:45} {detail}')
        for line in rec.pop("_tables", []):
            print(line)

    # report
    print("\nCoverage by tier")
    by = defaultdict(Counter)
    for rec in results.values():
        by[rec["level"]][rec["source"]] += 1
    for lvl in ("G", "M", "500", "250", "F"):
        c = by.get(lvl)
        if c:
            n = sum(c.values())
            print(f'  {TOUR_LEVELS[lvl]:13} {n:3} events: table {c["table"]}, page total {c["total"]}, '
                  f'season total {c["season-total"]}, nothing {c["none"]}, unmatched {c["unmatched"]}, errors {c["error"]}')
    cur = Counter(r.get("currency") for r in results.values() if r["source"] in ("table", "total", "season-total"))
    print("  currencies:", dict(cur))
    print(f"  Wikipedia requests made: {wiki.requests}")

    if args.dry_run:
        print("\nDry run: cache not written.")
        return
    cache.update(results)
    os.makedirs(os.path.dirname(os.path.abspath(args.cache)), exist_ok=True)
    with open(args.cache, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True, ensure_ascii=False)
    print(f"\nwrote {args.cache}")


if __name__ == "__main__":
    main()
