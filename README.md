# Different sports, different rankings

## This is in fact vibe-coded but that doesn't affect the accuracy of the rating systems

**[techrul.github.io/rankings](https://techrul.github.io/rankings/)**

I wanted to see what would happen if I ranked the same matches with different ranking systems. Same results, very different number ones. Right now it's only tennis, but CS2 is coming soon.

## Ranking systems

| System | What it is |
|---|---|
| [Elo](https://en.wikipedia.org/wiki/Elo_rating_system) | The classic chess rating. One number per player, which moves after every match. |
| [Glicko-2](https://www.glicko.net/glicko.html) | Elo with a confidence range, by Mark Glickman ([paper](https://www.glicko.net/glicko/glicko2.pdf)). |
| [OpenSkill](https://openskill.me/en/stable/) | A Bayesian rating built for teams, used here one-on-one ([library](https://github.com/vivekjoshy/openskill.py)). |
| [VRS](https://github.com/ValveSoftware/counter-strike_regional_standings) | Valve's CS2 Regional Standings, adjusted to work for tennis. It runs Valve's own code unchanged. |

All of them sit next to the official ATP ranking for comparison.

Glicko-2 and OpenSkill also have a toggle for how they treat players who aren't playing. The textbook versions barely move a player who's out injured, so by default they slowly sink instead.

## What's on the site

- **Rankings:** each system's top players, with a strip showing where every system puts them.
- **Predict:** pick two players and see who each system thinks wins, plus their head-to-head.
- **Tournaments:** the season calendar, plus stats for every event under every system.
- **Records:** weeks at #1, biggest upsets, biggest rises and more, for any time period.
- **Player and tournament pages:** rank history charts, titles and results.

It updates itself every morning through GitHub Actions.

## Data

- Match results: [TennisMyLife](https://stats.tennismylife.org/), built on [Jeff Sackmann's tennis data](https://github.com/JeffSackmann/tennis_atp)
- Prize money (for VRS): Wikipedia
- Trophy photos: Wikimedia Commons, credited on each tournament page

Rankings and stats on the site are shared under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), like the match data they're built from. Official rankings: [atptour.com](https://www.atptour.com/en/rankings/singles).

Not affiliated with the ATP, TennisMyLife or Valve.

Want the technical details? See [HOW_IT_WORKS.md](HOW_IT_WORKS.md).

Built with help from Claude.
