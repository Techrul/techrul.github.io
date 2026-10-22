"""CS2 data (data/cs2/, from fetch_cs2.py) -> rosters, the common match format, and Valve's VRS input format.

Team identity follows Valve's code (counter-strike_regional_standings, model/data_loader.js initTeams and
model/team.js sharesRoster) exactly, so a "team" means the same thing for Elo, Glicko-2, OpenSkill and VRS:
- matches are walked newest first, so a team is anchored on its most recent five;
- an older lineup belongs to the first team created (i.e. the most recent one) that shares 3 of its 5 players;
  otherwise it starts a new team;
- a team first seen in a forfeit stays a placeholder: the next real match that joins it replaces its name and
  players (Valve's isPendingUpdate).
tests/test_cs2_adapter.py checks this against Valve's own JavaScript on Valve's sample data.

Common match format (what the rating engines see; tennis and chess produce the same shape):
    {"id", "time", "date", "event", "sides": [[entity], [entity]], "winner": 0 | 1, "walkover": bool, ...}
For CS2 an entity is a roster id ("r12"), one per side.
"""
import glob
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

import countries

OVERLAP = 3  # Valve's TEAM_OVERLAP_TO_SHARE_ROSTER


# ----------------------------------------------------------------------------- loading
class Data:
    def __init__(self, matches, tournaments, placements, flags):
        self.matches, self.tournaments, self.placements, self.flags = matches, tournaments, placements, flags


def load(data_dir="data/cs2"):
    matches = []
    for path in sorted(glob.glob(os.path.join(data_dir, "matches", "*.jsonl"))):
        with open(path, encoding="utf-8") as fh:
            matches.extend(json.loads(line) for line in fh if line.strip())
    matches.sort(key=lambda m: (m["time"], m["id"]))

    def read(name):
        with open(os.path.join(data_dir, name), encoding="utf-8") as fh:
            return json.load(fh)
    return Data(matches, read("tournaments.json"), read("placements.json"), read("players.json"))


def usable(m):
    """Two teams of exactly five players and a winner (Valve's code also needs 5 + 5)."""
    t = m.get("teams") or []
    return (len(t) == 2 and len(t[0]["players"]) == 5 and len(t[1]["players"]) == 5
            and m.get("winner") in (1, 2))


# ----------------------------------------------------------------------------- rosters
class Roster:
    __slots__ = ("id", "name", "players", "pending", "last_time", "matches", "names_seen")

    def __init__(self, rid, name, players, pending):
        self.id, self.name, self.players, self.pending = rid, name, list(players), pending
        self.last_time, self.matches, self.names_seen = 0, 0, {}


class Rosters:
    """Valve's initTeams, with an index from player to rosters so 80,000 matches take seconds, not hours."""

    def __init__(self):
        self.list = []
        self._by_player = defaultdict(set)  # player -> ids of rosters whose current `players` include them

    def _find(self, players):
        counts = defaultdict(int)
        for p in players:
            for rid in self._by_player.get(p, ()):
                counts[rid] += 1
        hits = [rid for rid, c in counts.items() if c >= OVERLAP]
        return self.list[min(hits)] if hits else None  # Valve: teams.find() -> first created

    def insert(self, name, players, forfeit):
        r = self._find(players)
        if r is not None:
            if r.pending:  # placeholder from a forfeit: take this lineup (and name) instead
                for p in r.players:
                    self._by_player[p].discard(r.id)
                r.name, r.players, r.pending = name, list(players), forfeit
                for p in r.players:
                    self._by_player[p].add(r.id)
            return r
        r = Roster(len(self.list), name, players, forfeit)
        self.list.append(r)
        for p in players:
            self._by_player[p].add(r.id)
        return r


def assign_rosters(matches, players_of=lambda m, i: m["teams"][i]["players"],
                   name_of=lambda m, i: m["teams"][i]["name"], forfeit_of=lambda m: bool(m.get("walkover"))):
    """Sets m["rosters"] = (roster id of side 1, roster id of side 2) on every match; returns the Rosters.
    `matches` should be in Valve's input order (we use time, then id); they are walked newest first with a
    stable sort, as Valve's sortMatches does."""
    rosters = Rosters()
    for m in sorted(matches, key=lambda m: -m["time"]):  # stable: ties keep input order, like Valve's sort
        f = forfeit_of(m)
        r1 = rosters.insert(name_of(m, 0), players_of(m, 0), f)
        r2 = rosters.insert(name_of(m, 1), players_of(m, 1), f)
        m["rosters"] = (r1.id, r2.id)
        for r, i in ((r1, 0), (r2, 1)):
            r.matches += 1
            r.last_time = max(r.last_time, m["time"])
            nm = name_of(m, i)
            r.names_seen[nm] = r.names_seen.get(nm, 0) + 1
    return rosters


# ----------------------------------------------------------------------------- common format
def to_common(matches):
    """Usable matches with rosters assigned -> engine input, oldest first."""
    out = []
    for m in matches:
        if not usable(m) or "rosters" not in m:
            continue
        r1, r2 = m["rosters"]
        out.append({"id": m["id"], "time": m["time"], "date": m["date"], "event": m["event"],
                    "sides": [[f"r{r1}"], [f"r{r2}"]], "winner": m["winner"] - 1, "walkover": bool(m["walkover"]),
                    "lan": m["lan"], "tier": m["tier"], "valve": m["valve"]})
    out.sort(key=lambda c: (c["time"], c["id"]))
    return out


# ----------------------------------------------------------------------------- Valve's input format
def _place(p):
    try:
        return int(str(p).split("-")[0])
    except ValueError:
        return 99


def valve_input(data, as_of, window_days=200):
    """Valve's matchdata format for a ranking as of `as_of` (a UTC datetime): usable matches from the
    `window_days` before it (Valve's code then keeps its own 6-month window), their events with prize pool,
    LAN flag, finished flag and per-team prize money.

    - valveRanked = the match's Valve tier (Liquipedia's publishertier) is not blank. Valve's code only checks
      it from 1 Jan 2025.
    - An event is finished when its end date is before `as_of` (or, without a tournament record, when its last
      match is over two weeks before `as_of`). Valve's code drops matches of unfinished events.
    - Team ids within an event: the team template when the prize table uses it, else the name, so prize money
      reaches the right team."""
    cutoff = int(as_of.timestamp())
    start = cutoff - window_days * 86400
    picked = [m for m in data.matches if start <= m["time"] <= cutoff and usable(m)]
    as_of_date = as_of.strftime("%Y-%m-%d")

    last_match = defaultdict(int)
    for m in picked:
        last_match[m["event"]] = max(last_match[m["event"]], m["time"])

    events, team_ids = [], {}
    for ev in sorted(last_match):
        t = data.tournaments.get(ev)
        rows = data.placements.get(ev, [])
        by_tpl = {r["template"]: r for r in rows if r["template"]}
        by_name = {r["team"]: r for r in rows if r["team"]}
        team_ids[ev] = (by_tpl, by_name)
        if t:
            finished = bool(t["end"]) and t["end"] < as_of_date
            pool, lan, name = t["pool"], t["lan"], t["name"]
        else:
            finished = last_match[ev] < cutoff - 14 * 86400
            pool, lan, name = 0, None, ev.replace("_", " ")
        dist = [{"placement": _place(r["place"]), "teamId": r["template"] or r["team"], "prize": r["prize"],
                 "clubShare": 0, "shared": "-" in r["place"], "qualifiedEvents": []}
                for r in rows if r["team"] and r["team"].upper() != "TBD"]
        events.append({"eventId": ev, "eventName": name, "prizePool": f"${int(pool or 0)}",
                       "lan": bool(lan), "finished": finished, "prizeDistribution": dist})
    lan_of = {e["eventId"]: e["lan"] for e in events}

    def team_id(ev, team):
        by_tpl, by_name = team_ids[ev]
        if team["template"] in by_tpl:
            return team["template"]
        if team["name"] in by_name:
            r = by_name[team["name"]]
            return r["template"] or r["team"]
        return team["template"] or team["name"]

    def players(team):
        return [{"playerId": p, "nick": p, "country": data.flags.get(p, ""), "countryIso": countries.iso(data.flags.get(p))}
                for p in team["players"]]

    out = []
    for m in picked:
        a, b = m["teams"]
        if data.tournaments.get(m["event"]) is None and m["lan"]:
            lan_of[m["event"]] = True  # no tournament record: trust the match's own Offline flag
        out.append({"matchStartTime": m["time"], "eventId": m["event"],
                    "team1Id": team_id(m["event"], a), "team1Name": a["name"], "team1Players": players(a),
                    "team2Id": team_id(m["event"], b), "team2Name": b["name"], "team2Players": players(b),
                    "winningTeam": m["winner"], "forfeited": bool(m["walkover"]), "valveRanked": bool(m["valve"]),
                    "maps": [], "lpId": m["id"]})
    for e in events:
        e["lan"] = lan_of[e["eventId"]]
    return {"matches": out, "events": events}


# ----------------------------------------------------------------------------- names and regions
_SUFFIXES = (" Esports Club", " Esport Club", " Esports", " eSports", " esports", " E-Sports", " e-Sports", " Esport",
             " Gaming", " Team", " Clan", " Club", " CS", ".gg")


def short_name(name):
    """Liquipedia's full team name -> the short name Valve and HLTV use: 'Team Vitality' -> 'Vitality',
    'G2 Esports' -> 'G2', 'Aimclub (Romanian team)' -> 'Aimclub'. Leaves at least two characters."""
    s = re.sub(r"\s*\([^)]*\)$", "", (name or "").strip()) or (name or "")  # Liquipedia's disambiguation
    for suf in _SUFFIXES:
        if s.endswith(suf) and len(s) - len(suf) >= 2:
            s = s[:-len(suf)]
            break
    if s.startswith("Team ") and len(s) >= 7:
        s = s[5:]
    return s


REGIONS = ("Europe", "Americas", "Asia")  # Valve's order; ties go to the first (its region priority 3, 2, 1)


def load_valve_regions(valve_dir):
    """Country code -> Valve's region group, read from Valve's own table (model/util/region.js): 0 Europe
    (EU and MENA), 1 Americas (NA and SA), 2 Asia (everything else), -1 Africa (counted with the team's
    lowest-priority region present, as in Valve's setPluralityRegion)."""
    path = os.path.join(valve_dir, "model", "util", "region.js")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    group = {"EU": 0, "MENA": 0, "NA": 1, "SA": 1, "AF": -1}
    return {cc.lower(): group.get(reg, 2) for cc, reg in re.findall(r"countrycode\s*:\s*'(\w+)'\s*,\s*region\s*:\s*'(\w+)'", text)}


def valve_region(isos, table):
    """Valve's plurality rule (team.js setPluralityRegion) on a list of country codes -> 0, 1, 2 or None."""
    priority = (3, 2, 1)
    counts, low = [0, 0, 0], 0
    for cc in isos:
        if not cc or cc == "world" or cc not in table:
            continue
        g = table[cc]
        if g < 0:
            low += 1
        else:
            counts[g] += 1
    if not any(counts) and not low:
        return None
    present = [priority[i] for i in range(3) if counts[i] > 0]
    lowest = min(present) if present else 1  # all low-priority: Valve's default is its lowest priority (Asia)
    counts[priority.index(lowest)] += low
    top = max(counts)
    return max((i for i in range(3) if counts[i] == top), key=lambda i: priority[i])


def parse_valve_standings(path):
    """Valve's published standings markdown (live/<year>/standings_global_<date>.md) -> list of
    {"rank", "points", "name", "roster": [nicknames]}."""
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4 and cells[0].isdigit():
                rows.append({"rank": int(cells[0]), "points": int(cells[1]), "name": cells[2],
                             "roster": [p.strip() for p in cells[3].split(",") if p.strip()]})
    return rows


def utc(day):
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
