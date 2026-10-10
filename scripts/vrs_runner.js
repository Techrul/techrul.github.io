"use strict";
// Runs Valve's own ranking code (unmodified, from a separate clone) on a match file and writes the result.
//   node scripts/vrs_runner.js <path to counter-strike_regional_standings> <matchdata.json> <out.json>
const fs = require("fs");
const path = require("path");

const [valveDir, dataFile, outFile] = process.argv.slice(2);
if (!valveDir || !dataFile || !outFile) {
    console.error("usage: node vrs_runner.js <valve repo> <matchdata.json> <out.json>");
    process.exit(2);
}
const Ranking = require(path.resolve(valveDir, "model", "ranking.js"));
const [matches, teams] = Ranking.generateRanking(-1, path.resolve(dataFile));

const out = teams
    .filter(t => t.globalRank !== undefined && t.globalRank > 0)
    .map(t => ({
        id: t.players[0].playerId,
        name: t.name,
        rank: t.globalRank,
        points: Math.round(t.rankValue),
        seed_points: Math.round(t.rankValueSeed),
        regional_rank: t.regionalRank,
        region: t.region,
        matches: t.matchesPlayed,
        modifiers: t.modifiers,
    }))
    .sort((a, b) => a.rank - b.rank);

fs.writeFileSync(outFile, JSON.stringify({ matches_used: matches.length, players: out }));
console.log(`VRS: ${matches.length} matches, ${out.length} ranked players`);
