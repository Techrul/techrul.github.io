# CS2 data

Match results, tournaments, prize money and player nationalities for Counter-Strike, from
[Liquipedia](https://liquipedia.net/counterstrike/) through its API, fetched by `scripts/fetch_cs2.py`.

**Licence:** this folder's data comes from Liquipedia and is licensed under
[CC BY-SA 3.0](https://liquipedia.net/commons/Liquipedia:Copyrights), not under the repository's MIT licence.
Credit: Liquipedia (https://liquipedia.net/). Anything derived from it and published (the CS2 rankings data on
the site) is shared under the same licence.

| File | Contents |
|---|---|
| `matches/YYYY-MM.jsonl` | One finished match per line (no showmatches): time, event, Liquipedia tier, Valve tier (`valve`, Liquipedia's `publishertier`), LAN, winner, walkover, both teams with their five players |
| `tournaments.json` | Event page -> name, dates, prize pool (USD), LAN, Valve tier |
| `placements.json` | Event page -> teams with prize money (USD), players' share, roster |
| `players.json` | Player (Liquipedia page name) -> nationality |
| `state.json` | Which months were fetched when (a month is final once fetched 21 days after it ended) |
| `last_fetch.log` | Output of the latest daily fetch (requests made, anything Liquipedia refused) |
