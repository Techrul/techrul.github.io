"""Parser tests for scripts/prize_money.py on hand-written sample pages.

The samples imitate layouts seen on Wikipedia (Indian Wells 2025: rounds across, one row per event;
Monte-Carlo 2025: infobox total only). They are not copies of real pages, so passing them does not
prove real-page coverage; the --dry-run report does that.

    python3 -m pytest tests -q      (or: python3 tests/test_prize_money.py)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import prize_money as pm  # noqa: E402

ROUNDS_ACROSS = """
<table class="infobox"><tr><th>Prize money</th><td>$9,415,725 (men)<br>$9,415,725 (women)</td></tr></table>
<h2>Points and prize money</h2>
<h3>Prize money</h3>
<table class="wikitable">
<tr><th>Event</th><th>W</th><th>F</th><th>SF</th><th>QF</th><th>Round of 16</th><th>Round of 32</th><th>Round of 64</th><th>Round of 128</th><th>Q2</th><th>Q1</th></tr>
<tr><td>Men's singles</td><td>$1,201,125</td><td>$638,750</td><td>$354,850</td><td>$202,000</td><td>$110,250</td><td>$64,500</td><td>$37,650</td><td>$25,375</td><td>$14,730</td><td>$7,640</td></tr>
<tr><td>Women's singles</td><td>$1,201,125</td><td>$638,750</td><td>$354,850</td><td>$202,000</td><td>$110,250</td><td>$64,500</td><td>$37,650</td><td>$25,375</td><td>$14,730</td><td>$7,640</td></tr>
<tr><td>Men's doubles*</td><td>$400,000</td><td>$212,000</td><td>$113,000</td><td>$57,000</td><td>$31,000</td><td>$17,000</td><td></td><td></td><td></td><td></td></tr>
</table>
"""

ROUNDS_DOWN = """
<table class="infobox vevent"><tr><th>Prize money</th><td>€2,522,220</td></tr></table>
<h2>Prize money</h2>
<table class="wikitable">
<tr><th>Round</th><th>Singles</th><th>Doubles<sup>[a]</sup></th></tr>
<tr><th>Winner</th><td>€500,000<sup>[1]</sup></td><td>€150,000</td></tr>
<tr><th>Runner-up</th><td>€269,000</td><td>€80,000</td></tr>
<tr><th>Semifinalists</th><td>€143,000</td><td>€40,000</td></tr>
<tr><th>Quarterfinalists</th><td>€73,000</td><td>€20,000</td></tr>
<tr><th>Round of 16</th><td>€39,000</td><td>€10,000</td></tr>
<tr><th>Round of 32</th><td>€20,800</td><td></td></tr>
</table>
"""

TOTAL_ONLY = """
<table class="infobox"><tr><th>Prize money</th><td>€6,128,940</td></tr><tr><th>Surface</th><td>Clay</td></tr></table>
<h2>Points distribution</h2>
<table class="wikitable"><tr><th>Event</th><th>W</th><th>F</th><th>SF</th><th>QF</th></tr>
<tr><td>Singles</td><td>1000</td><td>650</td><td>400</td><td>200</td></tr></table>
"""

NOTHING = """<table class="infobox"><tr><th>Surface</th><td>Hard</td></tr></table><p>No prize section.</p>"""

AUSSIE = """
<table class="infobox"><tr><th>Prize money</th><td>A$96,500,000</td></tr></table>
<h2>Prize money</h2>
<table class="wikitable"><tr><th>Event</th><th>W</th><th>F</th><th>SF</th><th>QF</th><th>4R</th><th>3R</th><th>2R</th><th>1R</th></tr>
<tr><td>Singles</td><td>A$3,500,000</td><td>A$1,900,000</td><td>A$1,055,000</td><td>A$665,000</td><td>A$420,000</td><td>A$290,000</td><td>A$200,000</td><td>A$150,000</td></tr></table>
"""


def test_rounds_across_mens_row_only():
    r = pm.parse_page(ROUNDS_ACROSS)
    assert r["rounds"]["W"] == 1201125
    assert r["rounds"]["R128"] == 25375
    assert r["rounds"]["Q2"] == 14730
    assert r["currency"] == "USD"
    assert r["total"] == 9415725


def test_rounds_down_with_footnotes_and_euros():
    r = pm.parse_page(ROUNDS_DOWN)
    assert r["rounds"] == {"W": 500000, "F": 269000, "SF": 143000, "QF": 73000, "R16": 39000, "R32": 20800}
    assert r["currency"] == "EUR"
    assert r["total"] == 2522220


def test_points_table_is_not_prize_money():
    r = pm.parse_page(TOTAL_ONLY)
    assert "rounds" not in r
    assert r["total"] == 6128940 and r["total_currency"] == "EUR"


def test_page_without_prize_money():
    assert pm.parse_page(NOTHING) == {}


def test_australian_dollars_and_numbered_rounds():
    r = pm.parse_page(AUSSIE)
    assert r["currency"] == "AUD"
    assert r["rounds"]["R16"] == 420000 and r["rounds"]["R128"] == 150000


def test_amount_formats():
    assert pm.parse_amount("$1,201,125[a]") == 1201125
    assert pm.parse_amount("€6.1 million") == 6100000
    assert pm.parse_amount("£53,550,000") == 53550000
    assert pm.parse_amount("–") is None


def test_round_labels():
    assert pm.round_label("Runner-up") == "F"
    assert pm.round_label("Round of 16") == "R16"
    assert pm.round_label("Quarterfinalists") == "QF"
    assert pm.round_label("Singles") is None


POINTS_UNDER_PRIZE_HEADING = """
<table class="infobox"><tr><th>Prize money</th><td>$2,760,000</td></tr></table>
<h2>Points and prize money</h2>
<table class="wikitable"><tr><th>Event</th><th>W</th><th>F</th><th>SF</th><th>QF</th><th>R16</th><th>R32</th></tr>
<tr><td>Singles</td><td>500</td><td>330</td><td>200</td><td>100</td><td>50</td><td>0</td></tr></table>
"""


def test_points_under_prize_heading_falls_back_to_total():
    r = pm.parse_page(POINTS_UNDER_PRIZE_HEADING)
    assert "rounds" not in r and r["total"] == 2760000


class FakeWiki:
    """Stands in for Wikipedia: search results and pages are given up front."""
    def __init__(self, hits, pages):
        self.hits, self.pages, self.requests = hits, pages, 0

    def search(self, query, limit=6):
        self.requests += 1
        return self.hits.get(query, [])

    def parse(self, title):
        self.requests += 1
        if title not in self.pages:
            raise LookupError("missing")
        return title, self.pages[title]


def test_lookup_skips_draw_pages_and_wrong_tier():
    page = "<p>The 2025 Indian Wells Open was a tennis tournament, an ATP Masters 1000 event.</p>" + ROUNDS_ACROSS
    wiki = FakeWiki(
        {"2025 Indian Wells Masters tennis": ["2025 Indian Wells Open \u2013 Men's singles", "2024 Indian Wells Open",
                                              "2025 BNP Paribas Challenger", "2025 Indian Wells Open"]},
        {"2025 Indian Wells Open \u2013 Men's singles": "<p>tennis ATP Masters 1000 draw</p>",
         "2025 BNP Paribas Challenger": "<p>tennis Challenger Tour event</p>",
         "2025 Indian Wells Open": page})
    rec = pm.lookup(wiki, {"name": "Indian Wells Masters", "year": 2025, "level": "M"})
    assert rec["source"] == "table" and rec["title"] == "2025 Indian Wells Open"
    assert rec["rounds"]["W"] == 1201125 and rec["total"] == 9415725


def test_lookup_reports_unmatched():
    rec = pm.lookup(FakeWiki({}, {}), {"name": "Nowhere Open", "year": 2025, "level": "250"})
    assert rec["source"] == "unmatched"


COMBINED_POINTS_THEN_PRIZE = """
<h2>Points and prize money</h2>
<table class="wikitable">
<tr><th>Event</th><th>W</th><th>F</th><th>SF</th><th>QF</th><th>R16</th><th>R32</th><th>Q</th></tr>
<tr><td>Singles</td><td>500</td><td>330</td><td>200</td><td>100</td><td>50</td><td>0</td><td>25</td></tr>
<tr><th colspan="8">Prize money</th></tr>
<tr><th>Event</th><th>W</th><th>F</th><th>SF</th><th>QF</th><th>R16</th><th>R32</th><th>Q</th></tr>
<tr><td>Singles</td><td>€472,000</td><td>€253,000</td><td>€135,000</td><td>€69,000</td><td>€36,000</td><td>€19,000</td><td>€4,000</td></tr>
</table>
"""


def test_combined_table_picks_the_money_row():
    r = pm.parse_page(COMBINED_POINTS_THEN_PRIZE)
    assert r["rounds"]["W"] == 472000 and r["currency"] == "EUR"


def page(text_html, location="", tier="ATP 500"):
    box = f'<table class="infobox"><tr><th>Location</th><td>{location}</td></tr><tr><th>Category</th><td>{tier}</td></tr></table>'
    return box + f"<p>A men's tennis tournament. {text_html}</p>"


SEASON = """
<table class="wikitable">
<tr><td><a title="2025 Qatar ExxonMobil Open">Qatar ExxonMobil Open</a><br>Doha, Qatar<br>ATP 500<br>Hard – $2,760,000<br>32S/16Q/16D</td>
    <td><a title="Karen Khachanov">Karen Khachanov</a></td></tr>
<tr><td><a title="2025 China Open (tennis)">China Open</a><br>Beijing, China<br>ATP 500<br>Hard – $4,215,035</td></tr>
<tr><td><a title="2025 French Open">French Open</a><br>Paris, France<br>Grand Slam<br>Clay – €25,621,000</td></tr>
<tr><td><a title="2025 Next Gen ATP Finals">Next Gen ATP Finals</a><br>Jeddah<br>Hard</td></tr>
<tr><td><a title="2025 ATP Finals">ATP Finals</a><br>Turin, Italy<br>ATP Finals<br>Hard (i) – $15,500,000</td></tr>
<tr><td><a title="2025 Sparkle Open (page does not exist)">Sparkle Open</a><br>Nowhere</td></tr>
</table>
"""


def season_wiki(extra_pages, hits=None):
    pages = {"2025 ATP Tour": SEASON}
    pages.update(extra_pages)
    return FakeWiki(hits or {}, pages)


def test_season_schedule_reads_titles_and_totals():
    sched = pm.season_schedule(season_wiki({}), 2025)
    titles = [t for t, _, _ in sched]
    assert "2025 Qatar ExxonMobil Open" in titles and "2025 Sparkle Open (page does not exist)" not in titles
    doha = next(tot for t, _, tot in sched if t == "2025 Qatar ExxonMobil Open")
    assert doha == (2760000.0, "USD")


def test_doha_maps_to_qatar_not_china_and_falls_back_to_season_total():
    wiki = season_wiki({"2025 Qatar ExxonMobil Open": page("No prize table here.", "Doha, Qatar"),
                        "2025 China Open (tennis)": page(ROUNDS_ACROSS, "Beijing, China")})
    sched = pm.season_schedule(wiki, 2025)
    rec = pm.lookup(wiki, {"name": "Doha", "year": 2025, "level": "500"}, sched)
    assert rec["title"] == "2025 Qatar ExxonMobil Open"
    assert rec["source"] == "season-total" and rec["total"] == 2760000


def test_china_open_page_is_rejected_for_doha_even_from_search():
    wiki = FakeWiki({"2025 Doha tennis": ["2025 China Open (tennis)", "2025 ATP Tour"]},
                    {"2025 China Open (tennis)": page(ROUNDS_ACROSS, "Beijing, China"), "2025 ATP Tour": SEASON})
    rec = pm.lookup(wiki, {"name": "Doha", "year": 2025, "level": "500"})
    assert rec["source"] == "unmatched"


def test_roland_garros_alias_and_atp_finals_not_next_gen():
    wiki = season_wiki({"2025 French Open": page(ROUNDS_DOWN, "Paris, France", "Grand Slam"),
                        "2025 ATP Finals": page("Round robin format.", "Turin, Italy", "ATP Finals"),
                        "2025 Next Gen ATP Finals": page("Jeddah event.", "Jeddah", "ATP Finals")})
    sched = pm.season_schedule(wiki, 2025)
    rg = pm.lookup(wiki, {"name": "Roland Garros", "year": 2025, "level": "G"}, sched)
    assert rg["title"] == "2025 French Open" and rg["source"] == "table"
    fin = pm.lookup(wiki, {"name": "ATP Finals", "year": 2025, "level": "F"}, sched)
    assert fin["title"] == "2025 ATP Finals" and fin["total"] == 15500000


def test_name_matching_handles_accents_and_apostrophes():
    assert pm.names_event("Bastad", pm.norm("2025 Nordea Open Båstad, Sweden"))
    assert pm.names_event("'s-Hertogenbosch", pm.norm("2025 Libéma Open 's-Hertogenbosch"))
    assert pm.names_event("Kitzbuhel", pm.norm("2025 Generali Open Kitzbühel"))
    assert not pm.names_event("Indian Wells Masters", pm.norm("2025 Rolex Shanghai Masters Shanghai, China"))


FINALS = """
<h2>Prize money, ranking points and trophies</h2>
<table class="wikitable">
<tr><th>Stage</th><th>Singles</th><th>Doubles</th><th>Points</th></tr>
<tr><td>Final win</td><td>$2,237,200</td><td>$356,800</td><td>500</td></tr>
<tr><td>Semi-final win</td><td>$1,183,200</td><td>$178,000</td><td>400</td></tr>
<tr><td>Round robin win per match</td><td>$396,500</td><td>$97,500</td><td>200</td></tr>
<tr><td>Participation fee</td><td>$331,000</td><td>$165,500</td><td>–</td></tr>
<tr><td>Alternates</td><td>$155,000</td><td>$65,000</td><td>–</td></tr>
</table>
"""


def test_atp_finals_stage_table():
    r = pm.parse_page(FINALS)
    assert r["rounds"] == {"FW": 2237200, "SFW": 1183200, "RR": 396500, "PART": 331000, "ALT": 155000}
    assert r["currency"] == "USD"


def test_season_total_kept_alongside_table():
    wiki = season_wiki({"2025 French Open": page(ROUNDS_DOWN, "Paris, France", "Grand Slam")})
    rec = pm.lookup(wiki, {"name": "Roland Garros", "year": 2025, "level": "G"}, pm.season_schedule(wiki, 2025))
    assert rec["source"] == "table" and rec["season_total"] == [25621000.0, "EUR"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("pass", name)
