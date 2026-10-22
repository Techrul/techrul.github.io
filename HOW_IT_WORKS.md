# How it works

A static site that ranks the same ATP match results with Elo, Glicko-2, OpenSkill and Valve's VRS method, next to the official ATP ranking. A GitHub Action rebuilds it every day.

Pages (`site/`, copied into `docs/`). The site root is a small homepage (`site/index.html`); the rankings live under `rankings/`:

| Page | What it shows |
|---|---|
| `index.html` | Techrul's homepage: list of projects |
| `rankings/index.html` | Rankings home: pick a sport; #1 under each system |
| `rankings/tennis/index.html` | Rankings table for each system with the rank strip |
| `rankings/tennis/predict.html?a=...&b=...` | Pick two players: each system's win chance (same formulas as the backtest), ranks, head-to-head record and meetings; plus the table of how well each system predicted the last 12 months |
| `rankings/tennis/player.html?id=...` | Player profile: current rank in each system, titles by tier, rank and Elo charts, record by surface/tier/year, recent matches |
| `rankings/tennis/records.html` | Records under each rating system only (tabs for Elo, Glicko-2, OpenSkill, VRS): weeks at #1, highest ratings, biggest upsets, biggest one-week rises, biggest gaps from the official rank. Each section has its own period: 2 weeks, 1 month, 3 or 6 months, 12 months (default), 2 years, all data |
| `rankings/tennis/tournaments.html` | Season calendar (default): events by start date with champion, in progress or expected, a 'today' line, VRS stakes; per-season, tier and surface filters. Table view: every event's stats side by side, per season or all seasons, sortable by any column. Cards view: grouped by tier in calendar order, or one ranked list when sorted by a stat. A 'Stats by' picker (Elo, Glicko-2, OpenSkill, VRS) sets which system the field, favourite, seed and upsets come from |
| `rankings/tennis/tournament.html?key=...` | One tournament year by year: champion, champion's seed, favourite and whether they won, field strength, upsets, VRS stakes, under the system you pick |

Themes: Black (default), Light and Catppuccin Mocha. Tiers are shown as text labels. The font (Schibsted Grotesk, SIL Open Font License) is hosted with the site in `site/assets/fonts/` with its licence, so pages make no requests to Google or anyone else. Number cells use tabular digits so columns line up, but this font's tabular set also makes full stops, commas and colons as wide as a digit (stray-looking spaces). So `site.js` wraps that punctuation in number cells and sets it back to normal width: digits stay aligned, spacing stays normal. No player photos (see "Ideas" below).

## How it works

```
scripts/fetch_tml.py     match CSVs -> data/raw, weekly rankings -> data/rankings (never committed)
scripts/prize_money.py   Wikipedia prize money per event -> data/prize_money.json (cached; new events only)
scripts/vrs_tennis.py    runs Valve's VRS code on tennis -> docs/rankings/tennis/data/vrs.json
scripts/ratings.py       Elo, Glicko-2, OpenSkill, official -> docs/rankings/tennis/data/rankings.json
scripts/site_data.py     weekly history, profiles, records, tournaments -> docs/rankings/tennis/data/
scripts/trophies.py      trophy photos from Wikimedia Commons (choices in data/trophies.json) -> docs/rankings/tennis/trophies/
scripts/build_site.py    copies site/ pages and assets into docs/
.github/workflows/       runs all of it daily and deploys docs/ to GitHub Pages
```

Run it locally:

```bash
pip install -r requirements.txt
git clone https://github.com/ValveSoftware/counter-strike_regional_standings vendor/vrs
env CONTACT_EMAIL=you@example.com python3 scripts/fetch_tml.py --start-year 2015
env CONTACT_EMAIL=you@example.com python3 scripts/prize_money.py --raw data/raw
python3 scripts/vrs_tennis.py --raw data/raw --prize data/prize_money.json --valve vendor/vrs --out docs/rankings/tennis/data/vrs.json
python3 scripts/ratings.py --raw data/raw --rankings data/rankings --vrs docs/rankings/tennis/data/vrs.json --out docs/rankings/tennis/data/rankings.json --start-year 2015
python3 scripts/site_data.py --raw data/raw --rankings data/rankings --prize data/prize_money.json --valve vendor/vrs --current docs/rankings/tennis/data/rankings.json --out docs/rankings/tennis/data --start-year 2015
python3 scripts/build_site.py --site site --out docs
python3 -m http.server -d docs     # then open http://localhost:8000/rankings/
```

The pages load their data with fetch, so open them through a web server (as above, or GitHub Pages), not as files.

## Data behind the new pages (`scripts/site_data.py`)

- History is weekly and starts one year after the first season in the data (that year only warms the models up).
- Skill-model ranks each week are among players with 20+ tour matches and a match in the last 180 days.
- Official rank history: TML's published weekly rankings, each carried forward until the next one (the ATP publishes none in the December off-season). After the last published file, each week uses the same-date estimate; charts show that part dashed.
- VRS history: Valve's code is rerun for each week once six months of priced events exist (with prize money for 2025-2026, that is from mid-2025).
- Records only cover the data on the site, so they are labelled as such, not as all-time records. Records that don't depend on a rating system (titles, streaks, ages) are left out on purpose.
- Weekly rises use the underlying rating (Glicko-2 rating, OpenSkill mean), not the ranked value, so a shrinking uncertainty is not counted as a rise.
- Tournament stats: VRS stakes = Valve's prize-pool factor, 1/(1+|log10(pool/$1M)|) on the scaled pool (1.00 = the biggest event). Field Elo = mean Elo of the draw's top 8 entrants on the Monday it started (finished editions only). Elo seed = the champion's place by Elo among the entrants. Upset = a win Elo gave under 25%.
- Every player with a tour-level match gets a profile, so every link works (612 profiles, about 5 MB, for 2020-2026).

Checked on 2020-2026 data: all 178 internal links on the main pages load; rank-strip dots sit exactly on the line (0.00 px offset); official rank history matches known history where it can be checked (Djokovic's run at #1 ending Feb 2022, when Medvedev took over).

## Ideas not built yet

- Player photos: Wikimedia Commons has freely licensed photos for many players (through Wikidata). Each needs its own author and licence credit, and quality varies. Loaded lazily from Wikimedia, they would not slow the site down or bloat the repo.
- VRS history before 2025: run `prize_money.py --years 2015 ... 2024` once (about 1,500 Wikipedia requests).

## Set up on GitHub

1. Create a **public** repo and push this folder.
2. Settings, Pages, Source: **GitHub Actions**.
3. Settings, Secrets and variables, Actions: add a repository secret `CONTACT_EMAIL` with your real email. It goes only in the User-Agent of the data requests (TennisMyLife, Wikipedia, Wikimedia Commons), so they can reach you; it is never published.
4. Actions tab, **Update rankings**, **Run workflow** once by hand and check that it goes green.

After that it runs by itself every day at 06:15 UTC (`.github/workflows/update.yml`):

- **Required steps** (match data, ratings, pages, deploy) must succeed. If one fails, the site keeps the last good version and GitHub emails you about the failed run.
- **Optional steps** (prize money, VRS, trophy photos) may fail without stopping the update. Without VRS the site hides the VRS tab and compares the other methods. If a data source is down, the scripts keep their last good copy.
- **60-day rule:** GitHub pauses scheduled workflows in public repos after 60 days without activity. When the repo has been quiet for 45 days, the workflow commits a one-line date file (`.github/keepalive`) so the schedule keeps running.
- **Action versions:** the workflow uses Node 24 versions of GitHub's actions (Node 20 was removed from runners on 23 Sep 2026). When GitHub announces the next change, bump the `@v` numbers.
- **Things that would need you:** a data source changing its file format (fetch_tml.py then keeps the old data and prints a warning), or a new year where TennisMyLife names its files differently.

Checked: the whole pipeline was run as the workflow runs it, offline (all downloads failing) and without Valve's code; both finished and produced a working site.

Self-hosting works too: run the scripts above from cron and serve the `docs/` folder with any web server.

## VRS (Valve Regional Standings) applied to tennis

`scripts/vrs_tennis.py` converts tennis results into the input format of Valve's CS2 ranking code and runs that code unchanged through `scripts/vrs_runner.js`. Valve's repository has no license file, so its code is not copied here: the workflow clones it at a pinned commit (`VALVE_COMMIT` in the workflow; review Valve's changes before moving it).

How tennis maps onto it:
- a player is a "team" listed five times, so Valve's 3-of-5 roster rule always keeps the same player together;
- every tour-level singles match counts (walkovers excluded); events still in progress are dropped by Valve's code;
- each tournament is an event with its prize pool and each player's prize money for the round reached, in USD, scaled so the biggest event pool is $1,000,000 (Valve caps pools there; scaling keeps relative stakes);
- every match counts as LAN; IOC country codes are mapped to ISO codes for Valve's regions.

Checked on real data (Oct 2026): Valve's code ran unmodified, ranked 136 players from 1,401 matches in its 6-month window; rank correlation with the official top 100 is 0.79. VRS reacts strongly to absence: Sinner, #1 officially but without a tour match since Wimbledon, is around #17.

### Is the tennis VRS sensible? (`scripts/vrs_backtest.py`, run by hand)

Prediction backtest, Mar-Sep 2026 (textbook Glicko-2 and OpenSkill): VRS rebuilt every Monday from earlier matches only, predicting the next week's 1,348 matches (same matches for every method):

| Method | Picked the winner | Log loss |
|---|---|---|
| OpenSkill | 64.5% | 0.687 |
| Glicko-2 | 64.2% | 0.643 |
| Elo | 63.2% | 0.643 |
| VRS | 62.1% | 0.831 |
| Higher official rank | 61.4% | - |

VRS picks winners about as well as the official ranking and slightly worse than the skill models (differences of 1-2 points are within noise at this sample size). Its win probabilities are overconfident (high log loss), which Valve's own README also notes for CS.

Prize money sensitivity: multiplying every estimated prize amount by a random 0.9-1.1 left the top-50 VRS order unchanged (rank correlation 1.000, top 10 identical, largest move 1 place) in 3 of 3 runs. The estimates are not what drives the ranking.

### Prize money

`scripts/prize_money.py` finds each event's Wikipedia page through the '<year> ATP Tour' season page and reads a per-round table or a total; results are cached in `data/prize_money.json` (each event is looked up once). `scripts/prize_model.py` turns that into per-round USD for every event:
- event pool = the ATP-only total in the season schedule (infobox totals often include the WTA draw);
- missing rounds = pool x shares learned from events of the same tier and draw size that have tables;
- missing pool = the same tournament's nearest year, else the tier median;
- currencies = yearly average ECB rates (fallback: 2025 averages).

Leave-one-out check (hide an event's table, predict it from its pool): 96-draw Masters within 0-2%, ATP 500 about 4.5%, ATP 250 about 8%, Slams about 9%, 56-draw Masters about 23% (only two examples). 2025-2026 coverage: 33 events with real tables, the rest estimated from schedule totals.

```bash
env CONTACT_EMAIL=you@example.com python3 scripts/prize_money.py --years 2025 2026 --dry-run --debug
python3 scripts/prize_model.py --cache data/prize_money.json --report
```

Known source data errors handled: a 2026 Munich row filed under Rome's tournament id (names are now taken by majority per event), Winston-Salem 2026 labelled as a Masters (its tier and pool are borrowed from 2025), and a broken ATP Finals participation fee (values under 1,000 are dropped). Wikipedia's 2025 ATP Finals table is older than the official figures, so Finals money is a few percent low.

## Prize money finder (details)

`scripts/prize_money.py` finds each tour event's men's singles prize money on Wikipedia: a per-round table when the page has one, otherwise the infobox total. It caches results in `data/prize_money.json` and looks each event up once. `--dry-run` only prints a coverage report.

```bash
env CONTACT_EMAIL=you@example.com .venv/bin/python scripts/prize_money.py --years 2025 --dry-run
```

Parser tests: `python3 tests/test_prize_money.py` (sample pages modelled on real layouts, not copies of real pages). Wikipedia content is CC BY-SA 4.0, so credit it on the site once VRS is live.

## What the models do

| System | Notes |
|---|---|
| Elo | Start 1500, K = 32, no surface or tournament weighting. |
| Glicko-2 | Monthly rating periods (months with no tour matches, like December, count too). Ranked by rating minus 2 x RD. |
| OpenSkill | Plackett-Luce, one-on-one. Ranked by mean minus 3 sigma. |

### Inactive players (toggle on the site)

Textbook Elo and OpenSkill don't change a rating while a player is out, and textbook Glicko-2 barely does (Nadal lost 38 points in two years without a match). So injured or retired players kept their spots: Draper was #7 in Glicko-2 in June 2026 while #173 officially.

The site shows both versions. The toggle appears only where Glicko-2 or OpenSkill is shown (their tabs on the rankings and records pages, and next to their tiles on player pages). The choice is remembered in the browser.
- **Sink while out (default):** for every month (Glicko-2) or week (OpenSkill) without a tour-level match, the player's uncertainty grows. The rate would take it from zero back to a newcomer's level (RD 350, sigma 8.33) in 5 years (`INACTIVE_RESET_YEARS` in `ratings.py`). Both rank by a cautious value, so absent players slide down gradually, unlike VRS, which drops them sharply. Draper, June 2026: #29 instead of #7.
- **Pure models:** the textbook versions (`glicko_pure`, `openskill_pure` in the JSON).
- Elo has no uncertainty, so it is the same in both.

Sinking does not improve predictions (see the table below). It changes what the ranking rewards (being active), not how well it predicts.

### Prediction table (rankings page, `docs/rankings/tennis/data/backtest.json`)

Built daily by `site_data.py`. Every method predicts the same matches: the last 12 months, where VRS ranks both players and both have an ATP rank on the match row. The skill models update after every match. VRS is rebuilt each Monday from earlier matches only and predicts that week's matches. "Higher ATP rank wins" uses the ranks on the match row and gives no probabilities, so it has no log loss.

Oct 2025 to Oct 2026, 1,961 matches:

| Method | Picked the winner | Log loss |
|---|---|---|
| Elo | 65.0% | 0.623 |
| Glicko-2, sink while out | 64.8% | 0.629 |
| Glicko-2, pure | 65.4% | 0.625 |
| OpenSkill, sink while out | 65.1% | 0.678 |
| OpenSkill, pure | 66.1% | 0.656 |
| VRS | 63.2% | 0.786 |
| Higher ATP rank wins | 63.5% | - |

Differences of a point or so are within noise at this sample size.

### Tournament stats under each system

For each event and each system (Elo, Glicko-2 and OpenSkill in both inactivity versions, VRS), `site_data.py` takes the ratings on the Monday of the start week. Field = mean of the 8 best entrants' ranking values (Glicko-2 rating - 2 RD, OpenSkill mu - 3 sigma, VRS points). Favourite = the best entrant; seed = the champion's position. Upsets = wins that system gave under 25%, out of the matches it rated (VRS: matches in weeks with a VRS snapshot, from mid-2025). Values only compare within one system.

### Head-to-head (`h2h.json`)

Every tour-level meeting between players listed in `rankings.json`, compact form (pair -> date, event id, round, winner, score). About 550 KB, about 95 KB gzipped (GitHub Pages compresses it).

### Trophy photos (`scripts/trophies.py`)

Real photos appear only on the tournament page, in a "The real trophy" panel with the photographer's credit.

Freely licensed photos from Wikimedia Commons, credited to their photographers (tooltip on small photos; full credit on each tournament page and at the bottom of the Cards view). The build downloads each photo once (cached in `data/trophy_images/`) and re-checks its licence every time; only public domain, CC0, CC BY and CC BY-SA are used.

Which photo belongs to which tournament is a short list in `data/trophies.json`, checked by eye: Roland Garros (Coupe des Mousquetaires), Wimbledon (Gentlemen's Singles Trophy) and Madrid. Every other event shows its tier label. An automatic search was tried and dropped: Commons file names cannot tell a tennis trophy from a football cup, a war trophy or a flower in the same city, and most automatic picks were wrong (even for the US Open and the ATP Finals).

To look for more: `env CONTACT_EMAIL=you@yourmail.com python3 scripts/trophies.py --find` prints candidates under a strict filter, with links. It changes nothing; add a good one to `data/trophies.json` (`"key": {"name": "...", "file": "File:..."}`; keys are in the page links, `tournament.html?key=540`).

Downloads use Wikimedia's standard thumbnail widths (500, then 330 and 250 px) because other widths can be refused (HTTP 403). If a download still fails, the log names the file and URL, and the rest of the build carries on.

### Calendar

TML only gives each event's start date, so the calendar is ordered by start date. Status comes from the results: finished (has a final), in progress (no final yet and started in the last 3 weeks), or "final not in the data". Events of the current season that have not been played yet are shown faded at last year's dates plus 52 weeks (same weekday). They are labelled as expected because real dates can shift, and new events only appear once they start. The "today" line uses the visitor's own date.

Idea: read the real upcoming dates from Wikipedia's '<year> ATP Tour' page (the prize money step already fetches it), instead of last year's.

The rankings, records and player pages also tag players with "Out X wk" after 4+ weeks without a tour-level match.
| ATP-style points | Not shown on the page. Still computed into the JSON as a check that the data is complete: points by tier and round of exit (ITF 2024 ATP points table), last 52 weeks, best 19 results. Kept for the later CS2 version. |
| Official ATP | Top 150. Preferred source: TML's weekly ranking files (TML-Rankings-Database on GitHub), one published ranking for everyone, no ties. That copy stopped updating in January 2026, so when it is more than 10 days old the site estimates the ranking for a single date instead: each player's last official points from their latest match row, plus ATP-style points earned since, minus points that dropped out. The page says which mode it is in. |

Matches used: Grand Slams, Masters 1000, ATP 500, ATP 250, ATP Finals. Walkovers are skipped for the skill models. Burn-in: the first years only warm the models up. Players need 20 matches and one in the last 180 days to be listed.

The page also reports each model's pre-match prediction accuracy and log loss over the last 12 months.

## Checked and not checked

Checked on test data (2020 to 2025, a local copy of the TML files):
- All three skill models run; predictions pick the winner 62 to 64% of the time.
- The ATP-style check tracks the official ranking closely (rank correlation 0.97 across 101 players).
- The estimate, tested against the real ranking of 17 Nov 2025: top 10 within one place, 67 of the top 100 within two places, median points error 0.7% for the top 50. Lower players drift more because Challenger results are not in the tour files.
- Some TML events have a blank match_num, so matches are identified by event, round, winner and loser. The source also has the odd repeated row, which is skipped.
- The page loads with no script errors, and the tabs and search work.

Not checked:
- `fetch_tml.py` and the workflow have not been run against the live site. The build sandbox could not reach stats.tennismylife.org.
- Whether TML's website files contain matches through early October 2026 (the web page says it does).
- The site's robots.txt blocks /api/, so the fetch script only uses the direct /data/ file links.
- Whether the website history files (before 2020) match the layout of the GitHub copies used in testing.
- The ATP points table is the 2024 table applied to the last 52 weeks only.

## Counter-Strike 2 (`rankings/cs2/`)

The same idea for CS2: every finished match on [Liquipedia](https://liquipedia.net/counterstrike/) since January 2023,
ranked by Elo, Glicko-2, OpenSkill and Valve's VRS code, next to Valve's own published standings. Pages mirror tennis:
Rankings (with a region filter), Team, Predict, Records, Events and Event. The design notes and checks are in
[CS2_PLAN.md](CS2_PLAN.md).

```
scripts/lp_api.py         Liquipedia API client: key, gzip, request cap, 45-an-hour pacing, 429 back-off
scripts/fetch_cs2.py      matches, tournaments, prize money -> data/cs2/ (committed; CC BY-SA 3.0, see its README)
scripts/cs2_adapter.py    rosters under Valve's 3-of-5 rule, the engines' match format, Valve's input format, regions
scripts/engines.py        Elo, Glicko-2, OpenSkill (shared with tennis)
scripts/cs2_ratings.py    every system + Valve's latest standings -> docs/rankings/cs2/data/rankings.json
scripts/cs2_site_data.py  weekly history, weekly VRS, Valve's standings over time, events, team profiles,
                          records, prediction table, head-to-head -> docs/rankings/cs2/data/
scripts/cs2_vrs.py        by hand: VRS on our data for one date, compared with Valve's list for that date
```

Run it locally (needs `LIQUIPEDIA_API_KEY`; the first fetch loads the history over several hours at 45 requests an hour):

```bash
git clone https://github.com/ValveSoftware/counter-strike_regional_standings vendor/vrs
env LIQUIPEDIA_API_KEY=... CONTACT_EMAIL=you@example.com python3 scripts/fetch_cs2.py --max-requests 40
python3 scripts/cs2_ratings.py --valve vendor/vrs --out docs/rankings/cs2/data/rankings.json
python3 scripts/cs2_site_data.py --valve vendor/vrs --current docs/rankings/cs2/data/rankings.json --out docs/rankings/cs2/data
python3 tests/test_fetch_cs2.py && python3 tests/test_cs2_adapter.py vendor/vrs
```

On GitHub: add the repository secret `LIQUIPEDIA_API_KEY`. The daily workflow fetches at most 30 requests (recent weeks,
plus any month not fetched yet), commits `data/cs2/`, and builds the CS2 pages. Every CS2 step may fail without stopping
the tennis update; without fresh CS2 data the CS2 pages say they could not load it. The weekly VRS history takes about
7 minutes (Valve's code runs once per week since January 2024).

How it differs from tennis, and why:
- **A team is a roster**, grouped exactly as Valve's code does (newest lineup first; earlier lineups join it with 3 of 5
  players). Checked against Valve's own JavaScript on Valve's sample data: identical on all 3,766 matches.
- **A match is a series** (Bo1/Bo3/Bo5); map scores are not used, as in Valve's code.
- **Glicko-2 rating periods are weeks**, not months: teams play several times a week, and monthly periods left the
  ratings stale within the month (60.5% vs 62.7% winners picked over 12 months). The inactivity setting works as for
  tennis, per week instead of per month, with the same 5-year rate.
- **Official = Valve's published standings** (first Monday of each month, from Valve's repository), each in force until
  the next, matched to rosters by 3 of 5 players.
- **VRS (live)** is Valve's code on our Liquipedia data. Valve's ranked flag is Liquipedia's `publishertier` (blank =
  not ranked; Valve's code only checks it from 2025). Against Valve's own lists on 9 dates (Mar 2025 to Oct 2026) the top
  50 correlate 0.92 to 0.99 and the #1 always matches.
- **Regions** (Europe, Americas, Asia) are Valve's: from the VRS run, else Valve's plurality rule on the current five.
- **Events page**: Liquipedia S- and A-tier main events (about 35 a season), editions grouped by series. All tiers count
  for the ratings. Upset records only count S-, A- and B-tier events (tennis: tour level only).
