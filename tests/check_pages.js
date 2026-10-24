"use strict";
// Syntax-checks every inline <script> in site/**/*.html and the shared assets. Exit 1 on the first broken file.
//   node tests/check_pages.js [site]
const fs = require("fs"), path = require("path"), vm = require("vm");
const root = process.argv[2] || "site";
let bad = 0, n = 0;
function check(code, where) {
  n++;
  try { new vm.Script(code, { filename: where }); } catch (e) { bad++; console.error(`${where}: ${e.message}`); }
}
(function walk(d) {
  for (const f of fs.readdirSync(d)) {
    const p = path.join(d, f);
    if (fs.statSync(p).isDirectory()) walk(p);
    else if (f.endsWith(".js")) check(fs.readFileSync(p, "utf8"), p);
    else if (f.endsWith(".html")) {
      const html = fs.readFileSync(p, "utf8"), re = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g;
      let m, i = 0;
      while ((m = re.exec(html))) check(m[1], `${p} (script ${++i})`);
    }
  }
})(root);
console.log(`${n} scripts checked, ${bad} broken`);
process.exit(bad ? 1 : 0);
