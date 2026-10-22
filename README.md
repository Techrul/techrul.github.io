# techrul.github.io

My personal site and a home for my projects. Live at **[techrul.github.io](https://techrul.github.io/)**.

## Projects

### Different sports, different rankings

**[techrul.github.io/rankings](https://techrul.github.io/rankings/)**

I wanted to see what would happen if I ranked the same matches with different ranking systems. Same results, very different number ones. It covers tennis and CS2.

> This is in fact vibe-coded, but that doesn't affect the accuracy of the rating systems.

| System | What it is |
|---|---|
| [Elo](https://en.wikipedia.org/wiki/Elo_rating_system) | The classic chess rating. One number per player, which moves after every match. Can be inaccurate since it doesn't lower inactive players|
| [Glicko-2](https://www.glicko.net/glicko.html) | Elo with a confidence range, by Mark Glickman ([paper](https://www.glicko.net/glicko/glicko2.pdf)). |
| [OpenSkill](https://openskill.me/en/stable/) | A Bayesian rating built for teams, used here one-on-one ([library](https://github.com/vivekjoshy/openskill.py)). |
| [VRS](https://github.com/ValveSoftware/counter-strike_regional_standings) | Valve's CS2 Regional Standings, adjusted to work for tennis. It runs Valve's own code unchanged. A little goofy, probably don't use this as an actual representation of skill.|

All of them sit next to the [official ATP rankings](https://www.atptour.com/en/rankings/singles) for tennis and [Valve's own standings](https://github.com/ValveSoftware/counter-strike_regional_standings) for CS2, where a team is a roster under Valve's three-of-five rule. Glicko-2 and OpenSkill also have a toggle for players who aren't playing: the textbook versions barely move someone who's out injured, so by default they slowly sink instead.

On the site:
- **Rankings:** each system's top players, with a strip showing where every system puts them.
- **Predict:** pick two players and see who each system thinks wins, plus their head-to-head.
- **Tournaments:** the season calendar, plus stats for every event under every system.
- **Records:** weeks at #1, biggest upsets, biggest rises and more, for any time period.
- **Player and tournament pages:** rank history charts, titles and results.

It updates itself every morning. Data: match results from [TennisMyLife](https://stats.tennismylife.org/), built on [Jeff Sackmann's tennis data](https://github.com/JeffSackmann/tennis_atp); prize money from Wikipedia; trophy photos from Wikimedia Commons; CS2 results from [Liquipedia](https://liquipedia.net/counterstrike/) (CC BY-SA 3.0). Technical details are in [HOW_IT_WORKS.md](HOW_IT_WORKS.md).

### More soon

Other projects will show up here.

## What's in this repo

| Path | What it is |
|---|---|
| `site/index.html` | The homepage |
| `site/rankings/` | The rankings site's pages |
| `scripts/` | The data pipeline that fetches results and builds the rankings |
| `.github/workflows/update.yml` | Rebuilds and deploys the whole site every day with GitHub Actions |

# FAQ:

## Q: Why is there a Mocha theme?

A: Cause [Catppuccin Mocha](https://catppuccin.com/) is my favorite theme.

## License

Code: [MIT](LICENSE). Rankings and stats shown on the site: [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), like the match data they're built from.

Not affiliated with the ATP, TennisMyLife or Valve. Built with help from Claude.
