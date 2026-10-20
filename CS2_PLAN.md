# CS2 plan (work in progress, `cs2` branch)

Goal: add Counter-Strike 2 to "Different sports, different rankings": the same matches ranked by Elo, Glicko-2,
OpenSkill and Valve's VRS method, next to Valve's own published standings. Built so a third game (chess first)
needs one new adapter, not a rewrite.

Nothing here goes live until it is merged into `main`. The workflow only deploys from `main`
(`deploy: if: github.ref == 'refs/heads/main'`), and pushes only start it on `main`. The branch can still be
built by hand from the Actions tab ("Run workflow", branch `cs2`) to check it; that run never replaces the site.

## What we know

### Liquipedia API (LiquipediaDB v3)

- Access: free plan, Counter-Strike wiki (`wiki=counterstrike`). Approved Oct 2026. Other wikis would need asking.
- Base URL `https://api.liquipedia.net/api/v3/<datapoint>`. Key sent as `Authorization: Apikey <key>`, with
  `Accept-Encoding: gzip` and a User-Agent naming the project. (Taken from a third-party client, `liquipydia`;
  confirm against the official docs after logging in.)
- Datapoints used: `match` (match2 records), `tournament`, `placement`. Parameters: `wiki`, `conditions`
  (`[[field::value]] AND ...`, with `>`/`<`/`!` prefixes), `query` (fields to return), `limit`, `offset`, `order`.
- Rate limit from the API terms: **60 requests per hour** on LiquipediaDB, and "reuse or cache results for as
  long as possible". Scraping pages is not allowed and gets the IP banned.
- Licence: CC BY-SA 3.0. Credit Liquipedia next to the data with a link, and send them the link once live.

match2 fields (Module:Match on Liquipedia Commons): `match2id, date, dateexact, finished, winner, resulttype,
walkover, bestof, tournament, parent, liquipediatier, liquipediatiertype, publishertier, type, extradata, ...`;
each opponent has `name, template, score, status, placement` and a player list (`name, displayname, flag`);
each game has `map, winner, scores, ...`.

### Valve's VRS code (counter-strike_regional_standings, pinned commit eec4853, 5 Oct 2026)

- Input: `{matches, events}`, the format `vrs_tennis.py` already writes. For CS it is the native format, so no
  tricks: a team is its five players, an event has a prize pool, `lan` flag, `finished` flag and a prize
  distribution (placement, prize, team).
- Rules in the code that matter for us:
  - a match is dropped unless **both sides list exactly 5 players**;
  - from 1 Jan 2025 a match is dropped unless it has **`valveRanked: true`**;
  - matches from unfinished events and showmatches are dropped; pools are capped at $1M;
  - two rosters are the same team when they share **3 of 5 players**;
  - rosters with no wins are left out of the standings.
- Valve publishes its **official standings** in the same repo, monthly (first Monday): `live/<year>/
  standings_global_<date>.md` (rank, points, team, roster) plus regional files. These are the CS2 "official
  ranking", the way the ATP ranking is for tennis.

## How it fits together

```
scripts/lp_api.py         small Liquipedia client: key from LIQUIPEDIA_API_KEY, gzip, User-Agent, 429 back-off,
                          hard cap on requests per run, every response saved to the cache
scripts/fetch_cs2.py      cache -> data/cs2/ (matches, tournaments, placements); only asks for what changed
scripts/cs2_adapter.py    Liquipedia records -> common match format + Valve's input format
scripts/engines.py        Elo / Glicko-2 / OpenSkill moved out of ratings.py, game-agnostic (tennis unchanged)
scripts/cs2_ratings.py    runs the engines, Valve's code (vrs_runner.js, as for tennis) and reads Valve's standings
scripts/cs2_site_data.py  history, team pages, records, events -> docs/rankings/cs2/data/
site/rankings/cs2/        pages (copied by build_site.py like the tennis ones)
```

### The common match format (the part chess reuses)

```
{ "id", "date", "event", "tier", "sides": [[player ids], [player ids]], "winner": 0|1, "forfeit": bool,
  "names": [side 0 name, side 1 name] }
```

Tennis: one player per side. CS2: five. Chess: one. The engines only see sides and a winner. Everything
game-specific (tiers, prize money, rosters, rounds) stays in that game's adapter.

### Team identity

All four systems use Valve's rule, so "a team" means the same thing in every column: each match's five players
are matched to an existing roster sharing 3 of 5, otherwise a new roster starts. Elo, Glicko-2 and OpenSkill
rate the roster; the name shown is the latest one used. One Python function copies Valve's `sharesRoster`
logic, with a test that it groups the sample data in Valve's repo the same way Valve's code does.

Later option: a player-level OpenSkill (OpenSkill is built for teams of individuals), shown as an extra.

### What counts as a match

- A match is a series (Bo1/Bo3/Bo5), as in Valve's code. Map-level Elo can be an extra later.
- Forfeits and walkovers are skipped by the skill models, as in tennis; Valve's code handles its own.
- Tiers: Liquipedia tiers 1-3 plus their qualifiers to start with (see open questions).
- LAN = tournament `type` Offline (or Hybrid with an offline stage).

### Daily request budget (60 per hour)

- Normal day: matches from the last 14 days that changed (a few requests at up to 1,000 rows each), new
  tournaments and placements (a few more). Target: under 15 requests.
- Backfill (first run, or after the Actions cache is lost): capped per run, e.g. 40 requests, continuing the
  next day where it stopped. Nothing is ever re-fetched while it is cached.
- Decided: the fetched data is committed to the repo (`data/cs2/`, one file per month, CC BY-SA 3.0 with its
  own README), not kept in the Actions cache, which is dropped after 7 days unused. Finished months never
  change, so daily commits only touch the current month and the event files.

## Pages (mirroring tennis)

| Page | Notes |
|---|---|
| `rankings/cs2/index.html` | Table per system (Elo, Glicko-2, OpenSkill, VRS ours, Valve official), rank strip |
| `rankings/cs2/team.html?id=` | Roster history, rank in each system, recent matches, link to the team's Liquipedia page |
| `rankings/cs2/predict.html` | Two teams, each system's win chance, head-to-head, backtest table |
| `rankings/cs2/records.html` | Same sections as tennis, per system |
| `rankings/cs2/events.html` | Events with field strength, favourite, upsets, VRS stakes |

Credit on every CS2 page, next to the data: "Match data from Liquipedia (CC BY-SA 3.0)" with links to Liquipedia
and its copyright page; team pages also link to the team's Liquipedia page. The published CS2 data files are
CC BY-SA 3.0 (they are derived from Liquipedia's); the code stays MIT.

## Checks before merging

1. Our VRS (Valve's code on Liquipedia data) vs Valve's published standings for the same date: rank correlation
   for the top 50, and which teams differ and why. This is the CS2 version of tennis's ATP-style check.
2. Roster grouping matches Valve's code on Valve's sample data.
3. Backtest table (last 12 months) for every system, as for tennis.
4. A run with the API unreachable keeps the last good data, and tennis still builds and deploys.
5. Request count per run logged and under budget.

## Steps

1. **Probe** (`scripts/cs2_probe.py`, 4 requests, hard cap 6): confirm the fields below on real data. Nothing
   else is built until this answers the open questions. Run it with
   `env LIQUIPEDIA_API_KEY=... CONTACT_EMAIL=... python3 scripts/cs2_probe.py`; responses are saved to
   `data/cs2/probe/` (git-ignored). Checked offline against a fake API only so far.
2. Client + fetcher with caching and the request cap. **Built:** `scripts/lp_api.py`, `scripts/fetch_cs2.py`,
   offline tests in `tests/test_fetch_cs2.py` (paging, request cap and resume, 429 back-off, hourly pacing,
   time limit, months settling). History from Jan 2023 (2023 = burn-in, rankings shown from 2024).
   On this branch `.github/workflows/cs2-fetch.yml` runs it when the fetcher changes and commits the data.
   **First load (19-20 Oct 2026):** 206 requests over about 4.5 hours, no errors. 83,131 matches (Jan 2023 to
   Oct 2026, about 1,800 a month, no duplicates), 5,709 tournaments, 3,488 events with prize money, 28,049
   players. `data/cs2/` is 52 MB on disk (about 7x smaller compressed in git).
   - Lineups: 93-95% of matches have exactly 5 + 5 players every year; walkovers 4-8% (`ff`, a few `dq`).
   - Valve tier (`publishertier`): blank for 98% of 2023-2024 matches, 50% tagged in 2025, 78% in 2026. That
     fits Valve's code, which only checks the ranked flag from 1 Jan 2025: before that every match counts.
     Values also include `Major`, `RMR Event`, `Major Qualifier` (older Valve events).
   - Every match's event has a tournament record except 9 matches (7 small events from 2022-23).
   - 1,191 Valve-ranked events since 2025: 641 have a prize pool, 638 have per-team prize money (the rest are
     zero-prize cups and qualifiers).
   - 350 matches have no winner (winner 0): skipped.
3. Adapter + roster identity + tests.
4. Move the engines into `engines.py`; tennis output must stay byte-identical.
5. CS2 ratings, VRS run, Valve standings reader, check 1.
6. Pages, credits, workflow steps (`continue-on-error`, so CS2 trouble never stops tennis).
7. Merge, then send Liquipedia the link.

## Probe results (19 Oct 2026, from GitHub Actions, `CS2_PROBE_RESULT.txt` on this branch)

- **Valve-ranked flag: `publishertier`, very likely.** Values seen: `Major Championship`, `Tier 1`, `Tier 2`,
  `Tier 1 Qualifier`, `Tier 2 Qualifier`, `Wildcard`, and blank (25% of last month's matches). It is Valve's own
  classification, not Liquipedia's tier: XSE Pro League is Liquipedia tier 2 but publisher `Tier 1`, ESL Pro
  League is tier 1 but `Wildcard`. Plan: `valveRanked = publishertier != ""`, confirmed by check 1.
- **Lineups: yes.** 947 of 1,000 recent matches list exactly 5 + 5 players (all 20 recent tier-1 matches do).
  Most of the rest are forfeits (`walkover`: 75 `ff`, 1 `dq`). Player ids: the `name` field (Liquipedia page
  name, e.g. `KSCERATO`), shown with `displayname`; nationality as a country name in `flag`.
- **Prize money per team: yes.** `placement` records carry `prizemoney` (USD) per team, plus
  `extradata.playershare` (the players' part; Valve's input splits prize and club share, and adds them back
  together) and the five players (`opponentplayers.p1..p5`). Tournaments have `prizepool` (USD) and `type`
  (Offline/Online). Placements even link the Valve standings a team qualified through.
- **Volume:** a month of finished matches is more than one 1,000-row page (tier 4 63%, tier 3 33%, tier 1 3%;
  a third are qualifiers; 22 showmatches). Budget: a few requests a day; history over several runs.
- **Matches:** `winner` "1"/"2", series `bestof`, per-map scores in `match2games`, start time as a Unix
  `extradata.timestamp`, opponent `status` "S" for a played score. Future events exist as placeholder pages
  (prize pool 0), so anything unfinished is skipped.
- **Rate limit:** the first request ever returned HTTP 429; the same request a minute later worked. The fetcher
  treats 429 as "stop for this run, keep what we have, continue tomorrow", never as an error that fails the build.

## Open questions

- How far back? CS2 came out 27 Sep 2023. Suggestion: fetch from Jan 2023, use 2023 as burn-in, show from 2024.
- Which tiers? More tiers bring VRS closer to Valve's (Valve ranks a few hundred teams) but cost requests.
  Start with 1-3 and widen if check 1 shows big gaps at the lower end.
- Does the free plan have its own limit beyond the 60 per hour in the terms? And how long does free access last
  (the API page says usually for a limited time)?

## Sources

- Liquipedia API terms: https://liquipedia.net/api-terms-of-use
- Liquipedia API plans and free access: https://liquipedia.net/api
- match2 fields: https://liquipedia.net/commons/Module:Match
- Valve's code and standings: https://github.com/ValveSoftware/counter-strike_regional_standings
