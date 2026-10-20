"use strict";
// Runs Valve's own data loader (unmodified) on a match file and prints, for every match it keeps, the match's
// position in the input file and the roster ids Valve's initTeams gave both sides. Used by test_cs2_adapter.py.
//   node tests/valve_rosters.js <counter-strike_regional_standings> <matchdata.json>
const fs = require("fs");
const os = require("os");
const path = require("path");

const [valveDir, dataFile] = process.argv.slice(2);
const DataLoader = require(path.resolve(valveDir, "model", "data_loader.js"));
const RankingContext = require(path.resolve(valveDir, "model", "ranking_context.js"));

const data = JSON.parse(fs.readFileSync(dataFile));
data.matches.forEach((m, i) => { m._idx = i; });
// Valve's 2023 sample file predates fields its current code reads; fill neutral defaults (code unchanged).
data.events.forEach(e => {
    if (e.finished === undefined) e.finished = true;
    e.prizeDistribution.forEach(p => {
        if (p.qualifiedEvents === undefined) p.qualifiedEvents = [];
        if (p.clubShare === undefined) p.clubShare = 0;
    });
});
const known = new Set(data.events.map(e => e.eventId));
data.matches.forEach(m => {
    if (m.eventId !== undefined && !known.has(m.eventId)) {
        data.events.push({ eventId: m.eventId, eventName: "unknown", prizePool: "$0", lan: false, finished: true, prizeDistribution: [] });
        known.add(m.eventId);
    }
});
const tmp = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "vrs-")), "matchdata.json");
fs.writeFileSync(tmp, JSON.stringify(data));

const loader = new DataLoader(new RankingContext());
loader.loadData(-1, tmp);
const out = loader.matches.map(m => [m._idx, m.team1.rosterId, m.team2.rosterId]);
process.stdout.write(JSON.stringify(out));
