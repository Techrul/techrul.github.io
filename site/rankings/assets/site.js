/* Shared page code: theme, header, helpers, line chart, tier labels. No external libraries. */
(function () {
  "use strict";
  var S = window.Site = {};
  var root = document.documentElement;

  // ---------------------------------------------------------------- theme
  var THEMES = ["black", "light", "mocha"];
  function readTheme() { try { return localStorage.getItem("theme"); } catch (e) { return null; } }
  function setTheme(t) {
    root.setAttribute("data-theme", t);
    document.querySelectorAll(".theme").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.theme === t ? "true" : "false"); });
  }
  var saved = readTheme();
  root.setAttribute("data-theme", THEMES.indexOf(saved) !== -1 ? saved : "black");

  // ---------------------------------------------------------------- helpers
  S.esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  S.flag = function (iso) {
    if (!iso || iso.length !== 2) return "";
    var cp = iso.toUpperCase().split("").map(function (c) { return 0x1F1E6 + c.charCodeAt(0) - 65; });
    return '<span class="flag" aria-hidden="true">' + String.fromCodePoint.apply(null, cp) + "</span>";
  };
  // CS2 players are Liquipedia page names: "Lucky_(French_player)" -> "Lucky"
  S.pname = function (page) { return String(page || "").replace(/_\([^)]*\)$/, "").replace(/_/g, " "); };
  S.plink = function (page) { return "https://liquipedia.net/counterstrike/" + encodeURIComponent(String(page).replace(/ /g, "_")).replace(/%2F/g, "/"); };
  S.hltv = function (q) { return "https://www.hltv.org/search?query=" + encodeURIComponent(q); };  // HLTV's IDs aren't available, so search by name
  S.country = (function () { var dn = null; try { dn = new Intl.DisplayNames(["en"], { type: "region" }); } catch (e) {} return function (iso) { try { return iso && iso.length === 2 && dn ? dn.of(iso.toUpperCase()) : ""; } catch (e) { return ""; } }; })();
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  S.date = function (iso) { if (!iso) return "–"; var p = iso.split("-"); return +p[2] + " " + MONTHS[+p[1] - 1] + " " + p[0]; };
  S.monthYear = function (iso) { var p = iso.split("-"); return MONTHS[+p[1] - 1] + " " + p[0]; };
  S.num = function (n) { return n == null ? "–" : Number(n).toLocaleString("en-US"); };
  S.param = function (k) { return new URLSearchParams(location.search).get(k); };
  S.json = function (path) {
    return fetch(path, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(path + ": " + r.status); return r.json(); });
  };
  S.fail = function (el, err) {
    el.innerHTML = '<div class="empty">This page could not load its data (' + S.esc(err.message) + "). If you opened the file directly, serve the folder instead: python3 -m http.server -d docs</div>";
  };
  S.base = function () { return document.body.dataset.root || ""; };
  S.player = function (p, opts) {
    if (!p) return "–";
    var name = S.esc(p.name || p.id);
    var link = (opts && opts.nolink) ? name : '<a class="plink" href="' + S.base() + 'tennis/player.html?id=' + encodeURIComponent(p.id) + '">' + name + "</a>";
    return S.flag(p.iso) + link;
  };
  // which sport the page belongs to ("tennis", "cs2" or "" on the overview), from the header's data-sport
  S.sport = function () { var h = document.querySelector("header.bar"); return h ? h.dataset.sport || "" : ""; };
  S.team = function (t, opts) {
    if (!t) return "–";
    var name = S.esc(t.name || t.id), title = t.full && t.full !== t.name ? ' title="' + S.esc(t.full) + '"' : "";
    return (opts && opts.nolink) ? "<span" + title + ">" + name + "</span>" :
      '<a class="plink" href="' + S.base() + "cs2/team.html?id=" + encodeURIComponent(t.id) + '"' + title + ">" + name + "</a>";
  };
  // CS2 event tiers: Liquipedia's S/A/B/C (tiers 1-4); Valve's Majors get their own label
  var CS2_TIER = { "1": ["S-Tier", "silver"], "2": ["A-Tier", "bronze"], "3": ["B-Tier", "slate"], "4": ["C-Tier", "slate"] };
  S.cs2tier = function (tier, valve) {
    var major = /major/i.test(valve || "") && !/qualifier/i.test(valve || ""), x = major ? ["Major", "gold"] : CS2_TIER[tier] || ["Other", "slate"];
    return '<span class="tierpill" style="--tc:var(--' + x[1] + ')">' + x[0] + "</span>";
  };
  S.TIERS = { G: "Grand Slam", F: "ATP Finals", M: "Masters 1000", "500": "ATP 500", "250": "ATP 250" };
  S.SURFACE = function (s) {
    var k = (s || "").toLowerCase();
    return '<span class="surface"><i style="background:var(--' + (["hard", "clay", "grass", "carpet"].indexOf(k) >= 0 ? k : "slate") + ')"></i>' + S.esc(s || "") + "</span>";
  };
  S.ROUND = { F: "Final", SF: "Semi-final", QF: "Quarter-final", R16: "Round of 16", R32: "Round of 32", R64: "Round of 64", R128: "Round of 128", RR: "Round robin", BR: "Bronze" };

  // ---------------------------------------------------------------- header
  S.header = function () {
    var el = document.querySelector("header.bar");
    if (!el) return;
    var base = S.base(), page = el.dataset.page, sport = el.dataset.sport;
    var nav = "";
    if (sport === "tennis" || sport === "cs2") {
      nav = [["rankings", "index.html", "Rankings"], ["predict", "predict.html", "Predict"],
        sport === "cs2" ? ["events", "events.html", "Events"] : ["tournaments", "tournaments.html", "Tournaments"], ["records", "records.html", "Records"]]
        .map(function (x) { return '<a href="' + base + sport + "/" + x[1] + '"' + (page === x[0] ? ' aria-current="page"' : "") + ">" + x[2] + "</a>"; }).join("");
    }
    el.innerHTML =
      '<span class="crumbs"><a class="home" href="' + base + '../">Techrul</a><span class="sep" aria-hidden="true">/</span>' +
      '<a class="brand" href="' + base + 'index.html">Ranking models' + (sport ? "<small>" + S.esc(sport === "tennis" ? "Tennis" : sport === "cs2" ? "CS2" : sport) + "</small>" : "") + "</a></span>" +
      (nav ? '<nav class="nav" aria-label="Sections">' + nav + "</nav>" : "") +
      '<span class="spacer"></span>' +
      (sport === "tennis" ? '<input class="find" id="find" placeholder="Find a player" aria-label="Find a player" autocomplete="off" spellcheck="false">' :
       sport === "cs2" ? '<input class="find" id="find" placeholder="Find a team" aria-label="Find a team" autocomplete="off" spellcheck="false">' : "") +
      '<span class="hdr-tools"><div class="themes" role="group" aria-label="Theme">' + THEMES.map(function (t) {
        return '<button class="theme" type="button" data-theme="' + t + '">' + t.charAt(0).toUpperCase() + t.slice(1) + "</button>";
      }).join("") + "</div>" + S.githubLink() + "</span>";
    setTheme(root.getAttribute("data-theme"));
    el.querySelectorAll(".theme").forEach(function (b) {
      b.addEventListener("click", function () { setTheme(b.dataset.theme); try { localStorage.setItem("theme", b.dataset.theme); } catch (e) {} });
    });
    var find = el.querySelector("#find");
    if (find && sport === "cs2") {
      S.json(base + "cs2/data/teams_index.json").then(function (list) {
        // An organisation can have several rosters (Valve's rule: a new core of three is a new team). Ranked ones
        // show their ranks; older ones show when they played and who was in them, so they don't look like duplicates.
        var seen = {};
        S.autocomplete(find, list.map(function (t) {  // the list comes best-ranked first
          var dupe = seen[t.name] = (t.name in seen);
          var ranked = (t.official || t.elo_rank) && !dupe, yrs = t.first && t.last ? (t.first.slice(0, 4) === t.last.slice(0, 4) ? t.last.slice(0, 4) : t.first.slice(0, 4) + "\u2013" + t.last.slice(2, 4)) : "";
          var who = (t.players || []).slice(0, 2).map(S.pname).join(", ");
          return { id: t.id, name: t.name, hint: ranked ? [t.official ? "Valve #" + t.official : null, t.elo_rank ? "Elo #" + t.elo_rank : null, t.region].filter(Boolean).join(" \u00b7 ")
                                                        : [yrs ? yrs + " roster" : "Older roster", who].filter(Boolean).join(" \u00b7 "),
            also: (t.players || []).join(" ") + " " + (t.full || "") };
        }), function (item) { location.href = base + "cs2/team.html?id=" + encodeURIComponent(item.id); }, { empty: "No team or player by that name" });
      }).catch(function () { find.remove(); });
    } else if (find) {
      S.json(base + "tennis/data/players_index.json").then(function (list) {
        S.autocomplete(find, list.map(function (p) {
          return { id: p.id, name: p.name, iso: p.iso, hint: [p.official ? "ATP #" + p.official : null, p.elo_rank ? "Elo #" + p.elo_rank : null].filter(Boolean).join(" \u00b7 ") };
        }), function (item) { location.href = base + "tennis/player.html?id=" + encodeURIComponent(item.id); });
      }).catch(function () { find.remove(); });
    }
  };

  // ---------------------------------------------------------------- search dropdown (the site's own, not the browser's)
  // items: [{id, name, iso, hint}] in the order to suggest when names match equally. onPick(item) on click/Enter.
  function fold(t) { return String(t).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
  S.autocomplete = function (input, items, onPick, opts) {
    opts = opts || {};
    var wrap = document.createElement("div");
    wrap.className = "ac" + (input.className.indexOf("find") >= 0 ? " ac-find" : "");
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var list = document.createElement("div");
    var lid = "ac-" + Math.random().toString(36).slice(2, 8);
    list.className = "ac-list"; list.id = lid; list.setAttribute("role", "listbox"); list.hidden = true;
    wrap.appendChild(list);
    input.setAttribute("role", "combobox"); input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", lid); input.setAttribute("aria-expanded", "false");
    items.forEach(function (it) { it._f = fold(it.name); it._a = it.also ? fold(it.also) : ""; });
    var shown = [], sel = -1;
    function mark(name, q) {
      if (!q) return S.esc(name);
      var i = fold(name).indexOf(q);
      return i < 0 ? S.esc(name) : S.esc(name.slice(0, i)) + "<mark>" + S.esc(name.slice(i, i + q.length)) + "</mark>" + S.esc(name.slice(i + q.length));
    }
    function open() {
      var q = fold(input.value.trim());
      if (!q && !opts.showAll) { close(); return; }
      var scored = [];
      items.forEach(function (it, idx) {
        var i = it._f.indexOf(q);
        if (i < 0) { if (it._a && q && it._a.indexOf(q) >= 0) scored.push([3, idx, it]); return; }  // e.g. a CS2 player's team
        var wordStart = i === 0 || it._f[i - 1] === " " || it._f[i - 1] === "-";
        scored.push([i === 0 ? 0 : wordStart ? 1 : 2, idx, it]);  // name start, then a word start (surname), then anywhere
      });
      scored.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
      shown = scored.slice(0, 8).map(function (x) { return x[2]; });
      sel = shown.length ? 0 : -1;
      list.innerHTML = shown.length ? shown.map(function (it, i) {
        return '<div class="ac-item" role="option" id="' + lid + "-" + i + '" data-i="' + i + '" aria-selected="' + (i === sel ? "true" : "false") + '"><span>' + S.flag(it.iso) + mark(it.name, q) + "</span>" +
          (it.hint ? '<span class="ac-hint">' + S.esc(it.hint) + "</span>" : "") + "</div>";
      }).join("") : '<div class="ac-empty">' + S.esc(opts.empty || "No player by that name") + "</div>";
      list.hidden = false; input.setAttribute("aria-expanded", "true");
      input.setAttribute("aria-activedescendant", sel >= 0 ? lid + "-" + sel : "");
    }
    function close() { list.hidden = true; input.setAttribute("aria-expanded", "false"); sel = -1; }
    function move(d) {
      if (!shown.length) return;
      sel = (sel + d + shown.length) % shown.length;
      list.querySelectorAll(".ac-item").forEach(function (el, i) { el.setAttribute("aria-selected", i === sel ? "true" : "false"); if (i === sel) el.scrollIntoView({ block: "nearest" }); });
      input.setAttribute("aria-activedescendant", lid + "-" + sel);
    }
    function pick(i) { var it = shown[i]; if (!it) return; input.value = it.name; close(); onPick(it); }
    input.addEventListener("input", open);
    input.addEventListener("focus", function () { if (opts.selectOnFocus) input.select(); if (input.value && !opts.selectOnFocus) open(); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); if (list.hidden) open(); else move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Enter") { if (!list.hidden && sel >= 0) { e.preventDefault(); pick(sel); } }
      else if (e.key === "Escape") { close(); }
    });
    list.addEventListener("mousedown", function (e) { e.preventDefault(); });  // keep focus in the input
    list.addEventListener("click", function (e) { var it = e.target.closest(".ac-item"); if (it) pick(+it.dataset.i); });
    input.addEventListener("blur", function () { setTimeout(close, 100); });
  };

  // ---------------------------------------------------------------- trophy photos (Wikimedia Commons, see scripts/trophies.py)
  var trophyData = null;
  S.trophies = function () {
    if (!trophyData) trophyData = S.json(S.base() + "tennis/data/trophies.json").catch(function () { return {}; });
    return trophyData;
  };
  S.trophyCredit = function (t) {
    return 'Photo: <a href="' + S.esc(t.page) + '" rel="noopener">' + S.esc(t.author) + "</a>, " +
      (t.licence_url ? '<a href="' + S.esc(t.licence_url) + '" rel="noopener license">' + S.esc(t.licence) + "</a>" : S.esc(t.licence)) + ", via Wikimedia Commons";
  };

  // ---------------------------------------------------------------- GitHub link
  // GitHub's "mark-github" icon from Primer Octicons (MIT licence)
  var GITHUB_PATH = "M6.766 11.328c-2.063-.25-3.516-1.734-3.516-3.656 0-.781.281-1.625.75-2.188-.203-.515-.172-1.609.063-2.062.625-.078 1.468.25 1.968.703.594-.187 1.219-.281 1.985-.281.765 0 1.39.094 1.953.265.484-.437 1.344-.765 1.969-.687.218.422.25 1.515.046 2.047.5.593.766 1.39.766 2.203 0 1.922-1.453 3.375-3.547 3.64.531.344.89 1.094.89 1.954v1.625c0 .468.391.734.86.547C13.781 14.359 16 11.53 16 8.03 16 3.61 12.406 0 7.984 0 3.563 0 0 3.61 0 8.031a7.88 7.88 0 0 0 5.172 7.422c.422.156.828-.125.828-.547v-1.25c-.219.094-.5.156-.75.156-1.031 0-1.64-.562-2.078-1.609-.172-.422-.36-.672-.719-.719-.187-.015-.25-.093-.25-.187 0-.188.313-.328.625-.328.453 0 .844.281 1.25.86.313.452.64.655 1.031.655s.641-.14 1-.5c.266-.265.47-.5.657-.656";
  S.REPO = "https://github.com/Techrul/techrul.github.io";
  S.githubLink = function () {
    return '<a class="ghlink" href="' + S.REPO + '" target="_blank" rel="noopener" title="Source code on GitHub" aria-label="Source code on GitHub">' +
      '<svg viewBox="0 0 16 16" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="' + GITHUB_PATH + '"/></svg></a>';
  };

  // ---------------------------------------------------------------- inactivity setting
  // "grow" (default): Glicko-2 and OpenSkill grow uncertainty while a player is out. "pure": textbook models.
  S.inactivity = function () { try { return localStorage.getItem("inactivity") === "pure" ? "pure" : "grow"; } catch (e) { return "grow"; } };
  S.sysKey = function (k) { return S.inactivity() === "pure" && (k === "glicko" || k === "openskill") ? k + "_pure" : k; };
  // Only for Glicko-2 and OpenSkill, the two models with an uncertainty that can grow; pages show it only there.
  // show = false keeps the space but hides it, so switching systems does not move the page.
  // Recent-match tables: each system's pre-match chance (older data held only Elo's, as a number)
  S.RSYS = [["elo", "Elo"], ["glicko", "Glicko-2"], ["openskill", "OpenSkill"], ["vrs", "VRS"]];
  // CS2 also has its ATP-style points (the page's sport is only known once the page has loaded)
  S.rsysList = function () { return S.sport() === "cs2" ? S.RSYS.concat([["points", "Points"]]) : S.RSYS; };
  // a pre-match "chance" cell: a percentage, or for Points (rank-based, no probability) who had more points
  S.chanceText = function (v, sys) {
    if (v == null) return "–";
    if (sys === "points") return v === 0.5 ? "Even" : v > 0.5 ? "More points" : "Fewer points";
    return Math.round(v * 100) + "%";
  };
  S.recentSys = function (v) {
    if (v) { try { localStorage.setItem("tsys", v); } catch (e) {} return v; }
    var x; try { x = localStorage.getItem("tsys"); } catch (e) {}
    return S.rsysList().some(function (r) { return r[0] === x; }) ? x : "elo";
  };
  S.chance = function (m, sys) {
    if (typeof m.p === "number") return sys === "elo" ? m.p : null;
    var v = (m.p || {})[S.sysKey(sys)];
    return v == null ? null : v;
  };
  // re-render without the page jumping: keep the element with this id at the same place on screen
  S.keepPlace = function (id, fn) {
    var el = document.getElementById(id), before = el ? el.getBoundingClientRect().top : null;
    fn();
    var now = document.getElementById(id);
    if (before != null && now) window.scrollBy(0, now.getBoundingClientRect().top - before);
  };
  // Rating change: per match for Elo and OpenSkill. Glicko-2 rates a whole period's results at once (CS2: a week,
  // tennis: a month) and VRS is rebuilt each Monday, so for those it is the change over the match's period.
  S.deltaKey = function (sys) { return sys === "elo" || sys === "vrs" ? sys : S.sysKey(sys); };
  S.deltaPeriod = function (sys) { return sys === "vrs" || sys === "points" ? "event" : sys === "glicko" ? (S.sport() === "cs2" ? "week" : "month") : null; };
  // the sentence that explains a period change (Glicko-2: its rating period; VRS: the whole event)
  S.deltaNote = function (sys, nm, who) {
    if (sys === "points") return "Points are earned for the final placing, so the number is what " + who + " earned at the event, shown on " + who + "’s last match there (best 10 results of 52 weeks count).";
    if (sys === "vrs") return "VRS counts a result once the event is over, so its change is " + who + "’s VRS points from the Monday before the event to the Monday after, shown on " + who + "’s last match there.";
    var per = S.deltaPeriod(sys);
    return per ? nm + " rates a whole " + per + "’s results together, so its change covers every match " + who + " played that " + per + "." : "";
  };
  S.delta = function (d, sys) {
    var k = S.deltaKey(sys), v = k && d ? d[k] : null;
    if (v == null) return "";
    var dec = sys === "openskill", r = dec ? Math.round(v * 10) / 10 : Math.round(v), txt = dec ? Math.abs(r).toFixed(1) : String(Math.abs(r));
    return '<span class="dlt ' + (r > 0 ? "up" : r < 0 ? "dn" : "") + '">' + (r > 0 ? "+" : r < 0 ? "\u2212" : "\u00b1") + txt + "</span>";
  };
  S.sysChips = function (id, sel) {
    return '<div class="chips" id="' + id + '" role="group" aria-label="Rating system">' + S.rsysList().map(function (r) {
      return '<button class="chip" type="button" data-v="' + r[0] + '" aria-pressed="' + (r[0] === sel ? "true" : "false") + '">' + r[1] + "</button>";
    }).join("") + "</div>";
  };
  S.inactivityToggle = function (el, onChange, label, show) {
    var cur = S.inactivity();
    el.classList.add("inact");
    el.style.visibility = show === false ? "hidden" : "";
    el.setAttribute("aria-hidden", show === false ? "true" : "false");
    var cs2 = S.sport() === "cs2";
    el.innerHTML = '<span class="lab">' + S.esc(label || (cs2 ? "When a team is out" : "When a player is out")) + '</span><div class="chips" role="group" aria-label="How Glicko-2 and OpenSkill treat ' + (cs2 ? "teams" : "players") + ' who are not playing">' +
      [["grow", "Sink while out"], ["pure", "Pure model"]].map(function (x) {
        return '<button class="chip" type="button" data-v="' + x[0] + '" aria-pressed="' + (cur === x[0] ? "true" : "false") + '"' + (show === false ? ' tabindex="-1"' : "") + ">" + x[1] + "</button>";
      }).join("") + "</div>" + '<span class="hint">' + S.stack(cs2 ? [
        "The model grows less sure of a team each week it doesn\u2019t play, so absent teams slide down.",
        "The textbook model: a rating barely changes while a team is out."] : [
        "The model grows less sure of a player each month they don\u2019t play, so absent players slide down.",
        "The textbook model: a rating barely changes while a player is out."], cur === "grow" ? 0 : 1) + "</span>";
    el.onclick = function (e) {
      var btn = e.target.closest("button"); if (!btn || btn.dataset.v === S.inactivity()) return;
      try { localStorage.setItem("inactivity", btn.dataset.v); } catch (err) {}
      onChange(btn.dataset.v);
    };
  };
  // "Out 9 wk" tag once a player has been without a tour-level match for 4+ weeks
  S.outTag = function (lastIso, asOfIso) {
    if (!lastIso || !asOfIso) return "";
    var days = Math.round((Date.parse(asOfIso) - Date.parse(lastIso)) / 864e5);
    return days >= 28 ? '<span class="out" title="No ' + (S.sport() === "cs2" ? "" : "tour-level ") + "match since " + S.date(lastIso) + '">Out ' + Math.floor(days / 7) + " wk</span>" : "";
  };
  S.outDays = function (days) { return days != null && days >= 28 ? '<span class="out">Out ' + Math.floor(days / 7) + " wk</span>" : ""; };

  // ---------------------------------------------------------------- no-shift text
  // All variants sit in the same grid cell and only one is visible, so the box is always as tall as the
  // longest one and switching between them never moves anything below.
  S.stack = function (variants, active) {
    return '<span class="stackv">' + variants.map(function (v, i) {
      return "<span" + (i === active ? "" : ' class="sv-hide" aria-hidden="true"') + ">" + v + "</span>";
    }).join("") + "</span>";
  };

  // ---------------------------------------------------------------- back link
  // Goes back in history when the visitor came from this site (keeps their filters and scroll),
  // otherwise to the given list page.
  S.back = function (href, label) {
    return '<a class="back" data-back href="' + href + '">\u2190 ' + S.esc(label) + "</a>";
  };
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[data-back]");
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    if (document.referrer && document.referrer.indexOf(location.origin) === 0 && history.length > 1) { e.preventDefault(); history.back(); }
  });

  // ---------------------------------------------------------------- whole rows as links
  // Any element with data-href opens that page when clicked anywhere (links, buttons and inputs inside keep
  // their own behaviour; selecting text does not navigate; Ctrl/Cmd-click opens a new tab).
  document.addEventListener("click", function (e) {
    var row = e.target.closest && e.target.closest("[data-href]");
    if (!row || e.target.closest("a, button, input, select, label, summary")) return;
    if (String(window.getSelection ? window.getSelection() : "").length) return;
    if (e.metaKey || e.ctrlKey) window.open(row.dataset.href, "_blank"); else location.href = row.dataset.href;
  });

  // ---------------------------------------------------------------- tier labels
  var TIER_SHORT = { G: "Grand Slam", F: "Finals", M: "Masters 1000", "500": "500", "250": "250" };
  var TIER_COLOR = { G: "gold", F: "orb", M: "silver", "500": "bronze", "250": "slate" };
  S.tier = function (level, long) {
    var k = TIER_COLOR[level] ? level : "250";
    return '<span class="tierpill" style="--tc:var(--' + TIER_COLOR[k] + ')">' + S.esc(long ? S.TIERS[k] : TIER_SHORT[k]) + "</span>";
  };
  S.pct = function (p) { return p == null ? "–" : p < 0.001 ? "<0.1%" : (p * 100).toFixed(1) + "%"; };

  // ---------------------------------------------------------------- line chart
  // CS2 came out on 27 Sep 2023: events before it were played in CS:GO
  S.CS2_FROM = "2023-09-27";
  S.csgo = function (day) { return !!day && String(day) < S.CS2_FROM; };
  S.csgoTag = function (day) { return S.csgo(day) ? '<span class="badge csgo" title="Played in CS:GO, before CS2 came out in September 2023">CS:GO</span>' : ""; };

  // a stretch drawn dashed (estimated values): from dashFrom, up to dashTo if given
  S.inDash = function (ser, i) { return ser.dashFrom != null && i >= ser.dashFrom && (ser.dashTo == null || i <= ser.dashTo); };
  // opts: { dates: [iso...], series: [{key, label, color, values: [..|null], dashFrom: index, dashTo: index}], scale: "rank"|"linear",
  //         height, fmt(v), mark: {index, label} }
  var RANK_TICKS = [1, 2, 5, 10, 20, 50, 100, 200];
  S.lineChart = function (el, opts) {
    var hidden = {};
    el.classList.add("chart");
    var legend = document.createElement("div");
    legend.className = "legend";
    var box = document.createElement("div");
    box.style.position = "relative";
    el.innerHTML = "";
    if (opts.series.length > 1) el.appendChild(legend);
    el.appendChild(box);
    var tip = document.createElement("div");
    tip.className = "tip"; tip.hidden = true;
    box.appendChild(tip);

    legend.innerHTML = opts.series.map(function (s) {
      var has = s.values.some(function (v) { return v != null; });
      return '<button type="button" data-key="' + s.key + '" aria-pressed="' + (has ? "true" : "false") + '"' + (has ? "" : " disabled") + '><i style="background:var(--' + s.color + ')"></i>' + S.esc(s.label) + (has ? "" : " (no data)") + "</button>";
    }).join("");
    opts.series.forEach(function (s) { if (!s.values.some(function (v) { return v != null; })) hidden[s.key] = true; });
    legend.querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        hidden[b.dataset.key] = !hidden[b.dataset.key];
        b.setAttribute("aria-pressed", hidden[b.dataset.key] ? "false" : "true");
        draw();
      });
    });

    var fmt = opts.fmt || function (v) { return opts.scale === "rank" ? "#" + v : S.num(Math.round(v)); };
    var xs = opts.dates.map(function (d) { return Date.parse(d); });
    var svgEl, geom;

    function draw() {
      var W = Math.max(280, box.clientWidth || el.clientWidth || 600), H = opts.height || 280;
      var m = { l: 44, r: 12, t: 12, b: 26 };
      var vis = opts.series.filter(function (s) { return !hidden[s.key]; });
      var all = [];
      vis.forEach(function (s) { s.values.forEach(function (v) { if (v != null) all.push(v); }); });
      if (!all.length || xs.length < 2) { box.innerHTML = '<div class="empty">No history to show for this selection.</div>'; box.appendChild(tip); return; }
      var x0 = xs[0], x1 = xs[xs.length - 1];
      var X = function (t) { return m.l + (t - x0) / (x1 - x0 || 1) * (W - m.l - m.r); };
      var Y, ticks;
      if (opts.scale === "rank") {
        var maxR = Math.max.apply(null, all);
        var top = RANK_TICKS.filter(function (t) { return t >= maxR; })[0] || 200;
        ticks = RANK_TICKS.filter(function (t) { return t <= top; });
        var lt = Math.log(top);
        Y = function (v) { return m.t + Math.log(v) / lt * (H - m.t - m.b); };
      } else {
        var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all), pad = (hi - lo) * 0.08 || 20;
        lo -= pad; hi += pad;
        // "nice" step from 1, 2, 5 x 10^k giving about five gridlines
        var raw = (hi - lo) / 5, mag = Math.pow(10, Math.floor(Math.log10(raw))), nrm = raw / mag;
        var step = (nrm < 1.5 ? 1 : nrm < 3 ? 2 : nrm < 7 ? 5 : 10) * mag;
        ticks = []; for (var t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t);
        Y = function (v) { return m.t + (hi - v) / (hi - lo) * (H - m.t - m.b); };
      }
      // x ticks: years
      var years = [], y0 = new Date(x0).getUTCFullYear(), y1 = new Date(x1).getUTCFullYear();
      for (var y = y0 + 1; y <= y1; y++) years.push(y);
      if (years.length > 8) years = years.filter(function (y, i) { return i % 2 === 0; });
      if (!years.length) years = [y0];

      var s = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' + S.esc(opts.label || "Chart") + '">';
      s += '<g class="grid axis">' + ticks.map(function (t) { var yy = Y(t); return '<line x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + yy + '" y2="' + yy + '"/><text x="' + (m.l - 8) + '" y="' + (yy + 4) + '" text-anchor="end">' + (opts.scale === "rank" ? "#" + t : S.num(t)) + "</text>"; }).join("") + "</g>";
      s += '<g class="axis">' + years.map(function (y) { var tx = X(Date.UTC(y, 0, 1)); return tx < m.l ? "" : '<text x="' + tx + '" y="' + (H - 6) + '" text-anchor="middle">' + y + "</text>"; }).join("") + "</g>";
      s += '<g class="series">';
      vis.forEach(function (ser) {
        var solid = "", dash = "", pen = false, dpen = false;
        ser.values.forEach(function (v, i) {
          var dashed = S.inDash(ser, i);
          if (v == null) { pen = false; dpen = false; return; }
          var pt = X(xs[i]).toFixed(1) + "," + Y(v).toFixed(1);
          if (!dashed || i === ser.dashFrom || i === ser.dashTo) { solid += (pen ? "L" : "M") + pt; pen = true; } else pen = false;
          if (dashed) { dash += (dpen ? "L" : "M") + pt; dpen = true; }
        });
        s += '<path d="' + solid + '" style="stroke:var(--' + ser.color + ')"/>';
        if (dash) s += '<path d="' + dash + '" style="stroke:var(--' + ser.color + ');stroke-dasharray:5 4"/>';
      });
      s += "</g>";
      if (opts.mark && opts.mark.index != null && opts.series[0].values[opts.mark.index] != null && !hidden[opts.series[0].key]) {
        var mx = X(xs[opts.mark.index]), my = Y(opts.series[0].values[opts.mark.index]);
        s += '<circle class="dot" cx="' + mx + '" cy="' + my + '" r="5" style="fill:var(--' + opts.series[0].color + ')"/><text x="' + mx + '" y="' + (my - 10) + '" text-anchor="middle" style="fill:var(--ink);font-size:12px;font-weight:600">' + S.esc(opts.mark.label) + "</text>";
      }
      s += '<g class="hover" visibility="hidden"><line class="cross" y1="' + m.t + '" y2="' + (H - m.b) + '"/></g>';
      s += '<rect x="' + m.l + '" y="0" width="' + (W - m.l - m.r) + '" height="' + H + '" fill="transparent" style="cursor:crosshair"/></svg>';
      box.innerHTML = s;
      box.appendChild(tip);
      svgEl = box.querySelector("svg");
      geom = { W: W, H: H, X: X, Y: Y, vis: vis, m: m };
      var rect = svgEl.querySelector("rect");
      function move(ev) {
        var r = svgEl.getBoundingClientRect(), px = (ev.clientX - r.left) * (W / r.width);
        var t = x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0);
        var i = 0, best = Infinity;
        for (var k = 0; k < xs.length; k++) { var d = Math.abs(xs[k] - t); if (d < best) { best = d; i = k; } }
        show(i);
      }
      rect.addEventListener("pointermove", move);
      rect.addEventListener("pointerdown", move);
      rect.addEventListener("pointerleave", function () { tip.hidden = true; svgEl.querySelector(".hover").setAttribute("visibility", "hidden"); });
    }

    function show(i) {
      var g = svgEl.querySelector(".hover"), cx = geom.X(xs[i]);
      g.setAttribute("visibility", "visible");
      g.querySelector("line").setAttribute("x1", cx); g.querySelector("line").setAttribute("x2", cx);
      g.querySelectorAll("circle").forEach(function (c) { c.remove(); });
      var rows = "";
      geom.vis.forEach(function (ser) {
        var v = ser.values[i];
        if (v == null) return;
        var c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        c.setAttribute("class", "dot"); c.setAttribute("cx", cx); c.setAttribute("cy", geom.Y(v)); c.setAttribute("r", 4);
        c.style.fill = "var(--" + ser.color + ")";
        g.appendChild(c);
        rows += '<div><span><i style="background:var(--' + ser.color + ')"></i>' + S.esc(ser.label) + (S.inDash(ser, i) ? " (est.)" : "") + "</span><b>" + fmt(v) + "</b></div>";
      });
      if (!rows) { tip.hidden = true; return; }
      tip.innerHTML = "<b>" + S.date(opts.dates[i]) + "</b>" + rows;
      tip.hidden = false;
      var bw = box.clientWidth, left = cx / geom.W * bw + 12;
      if (left + tip.offsetWidth > bw) left = cx / geom.W * bw - tip.offsetWidth - 12;
      tip.style.left = Math.max(0, left) + "px"; tip.style.top = "8px";
    }

    draw();
    if (window.ResizeObserver) { var last = 0; new ResizeObserver(function () { var w = box.clientWidth; if (Math.abs(w - last) > 4) { last = w; draw(); } }).observe(box); }
    return { redraw: draw };
  };

  S.footer = function () {
    var el = document.querySelector("footer.foot[data-auto]");
    if (!el) return;
    var sport = S.sport();
    var cs2 = '<p>CS2 match data: <a href="https://liquipedia.net/counterstrike/" rel="noopener">Liquipedia</a>, licensed <a href="https://liquipedia.net/commons/Liquipedia:Copyrights" rel="noopener license">CC BY-SA 3.0</a>; ' +
      "the CS2 rankings and records derived from it are shared under the same licence. VRS: Valve\u2019s public counter-strike_regional_standings code, run unchanged; Valve\u2019s official standings from the same repository.</p>";
    if (sport === "cs2") {
      el.innerHTML = cs2 + "<p>Non-commercial project, not affiliated with Valve, Liquipedia or HLTV.</p>";
      return;
    }
    el.innerHTML = (sport ? "" : cs2) + "<p>Match data: TennisMyLife (stats.tennismylife.org), built on Jeff Sackmann's Tennis Abstract data (CC BY-NC-SA 4.0). " +
      "Prize money: Wikipedia (CC BY-SA 4.0). Trophy photos: Wikimedia Commons contributors, credited on each tournament page. VRS: Valve's public counter-strike_regional_standings code, run unchanged. " +
      "Derived rankings and records on this site are shared under CC BY-NC-SA 4.0.</p>" +
      "<p>Non-commercial project, not affiliated with the ATP, TennisMyLife or Valve.</p>";
  };
  // ---------------------------------------------------------------- number alignment
  // Columns of numbers need same-width digits (tabular figures) to line up. Schibsted Grotesk's tabular
  // figures also make . , : as wide as a digit, which looks like stray spaces, so inside number cells the
  // digits stay tabular and the punctuation is put back to its normal width.
  var NUM_SEL = ".cn, td.n, .val, .off, .shift, .row .rk, .stk, .tile .big, .tile .v, .stats strong, table.bt td + td";
  function alignNums(root) {
    var els = root.matches && root.matches(NUM_SEL) ? [root] : [];
    if (root.querySelectorAll) els = els.concat(Array.prototype.slice.call(root.querySelectorAll(NUM_SEL)));
    els.forEach(function (el) {
      if (el.dataset.tn) return;
      el.dataset.tn = "1";
      el.classList.add("tn");
      var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(function (t) {
        if (!/[.,:]/.test(t.nodeValue) || (t.parentNode.classList && t.parentNode.classList.contains("p"))) return;
        var frag = document.createDocumentFragment();
        t.nodeValue.split(/([.,:])/).forEach(function (part) {
          if (!part) return;
          if (/^[.,:]$/.test(part)) { var sp = document.createElement("span"); sp.className = "p"; sp.textContent = part; frag.appendChild(sp); }
          else frag.appendChild(document.createTextNode(part));
        });
        t.parentNode.replaceChild(frag, t);
      });
    });
  }
  // ---------------------------------------------------------------- win chances (the Predict page's formulas)
  var G2 = 173.7178, OS_BETA = 25 / 6;
  var VRS_G = 1 / Math.sqrt(1 + 3 * Math.pow(Math.log(10) / 400, 2) * 75 * 75 / (Math.PI * Math.PI));  // Valve's formula, RD 75
  function phiN(x) {
    var t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2), y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x / 2);
    return x >= 0 ? (1 + y) / 2 : (1 - y) / 2;
  }
  // chance that a beats b under a system ("elo", "glicko", "openskill", "vrs"), from ranking entries; null if not rated
  S.winChance = function (key, a, b) {
    var k = S.inactivity() === "pure" ? "_pure" : "";
    if (key === "elo") return a.elo == null || b.elo == null ? null : 1 / (1 + Math.pow(10, (b.elo - a.elo) / 400));
    if (key === "vrs") return a.vrs == null || b.vrs == null ? null : 1 / (1 + Math.pow(10, -VRS_G * (a.vrs - b.vrs) / 400));
    if (key === "glicko") {
      var ra = a["glicko_r" + k], rb = b["glicko_r" + k], da = a["glicko_rd" + k], db = b["glicko_rd" + k];
      if (ra == null || rb == null) return null;
      var phi = Math.sqrt(da * da + db * db) / G2, g = 1 / Math.sqrt(1 + 3 * phi * phi / (Math.PI * Math.PI));
      return 1 / (1 + Math.exp(-g * (ra - rb) / G2));
    }
    if (key === "openskill") {
      var ma = a["openskill_mu" + k], mb = b["openskill_mu" + k], sa = a["openskill_sigma" + k], sb = b["openskill_sigma" + k];
      return ma == null || mb == null ? null : phiN((ma - mb) / Math.sqrt(2 * OS_BETA * OS_BETA + sa * sa + sb * sb));
    }
    return null;
  };

  // ---------------------------------------------------------------- head-to-head widget (ATP-style compare)
  S.money = function (usd) {
    if (usd == null) return "–";
    return usd >= 1e6 ? "$" + (usd / 1e6).toFixed(usd >= 1e7 ? 1 : 2).replace(/\.?0+$/, "") + "M" : usd >= 1e3 ? "$" + Math.round(usd / 1e3) + "k" : "$" + usd;
  };
  function wl(r) { return r && (r[0] + r[1]) ? r[0] + "–" + r[1] + ' <small>' + Math.round(100 * r[0] / (r[0] + r[1])) + "%</small>" : "–"; }
  function wpct(r) { return r && (r[0] + r[1]) ? r[0] / (r[0] + r[1]) : null; }
  function flip(score) { var p = String(score || "").split("–"); return p.length === 2 ? p[1] + "–" + p[0] : score; }
  function signed(n) { return n == null ? "–" : (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n).toLocaleString("en-US"); }
  // the compare rows: (sport, ranking entry A, B, profile file A, B) -> HTML
  S.h2hRows = function (sport, A, B, pa, pb) {
    pa = pa || {}; pb = pb || {};
    var cs2 = sport === "cs2", OFF = cs2 ? "Valve" : "ATP", nm = function (e) { return cs2 ? e.short : e.name; };
      var sa = pa.season || {}, sb = pb.season || {}, y = sa.year || sb.year || "";
      var R = [  // [label, value a, value b, compare a, compare b, higher is better]
        ["Projected win", null, null, null, null, true, "chance"],
        [OFF + " rank", A.official_rank ? "#" + A.official_rank : "–", B.official_rank ? "#" + B.official_rank : "–", A.official_rank, B.official_rank, false],
        [cs2 ? "Points" : "ATP points", S.num(cs2 ? A.points : A.official_points), S.num(cs2 ? B.points : B.official_points), cs2 ? A.points : A.official_points, cs2 ? B.points : B.official_points, true],
        ["Elo", S.num(A.elo), S.num(B.elo), A.elo, B.elo, true],
        [y + " win–loss", wl(sa.record), wl(sb.record), wpct(sa.record), wpct(sb.record), true],
        ["All matches", wl((pa.record || {}).all), wl((pb.record || {}).all), wpct((pa.record || {}).all), wpct((pb.record || {}).all), true],
        [y + " titles", S.num(sa.titles), S.num(sb.titles), sa.titles, sb.titles, true],
        ["Titles", S.num((pa.titles || []).length), S.num((pb.titles || []).length), (pa.titles || []).length, (pb.titles || []).length, true]
      ];
      if (cs2) R.push([y + " prize money", S.money(sa.prize), S.money(sb.prize), sa.prize, sb.prize, true],
                      ["Prize money", S.money(pa.prize), S.money(pb.prize), pa.prize, pb.prize, true]);
      R.push([y + " Elo change", signed(sa.elo), signed(sb.elo), sa.elo, sb.elo, true]);
      if (cs2) R.push([y + " points change", signed(sa.points), signed(sb.points), sa.points, sb.points, true]);
      return R.map(function (r) {
        if (r[6] === "chance") {
          var p = S.winChance("elo", A, B), sys = ["glicko", "openskill"].concat(cs2 || A.vrs != null ? ["vrs"] : []).map(function (k) { return S.winChance(k, A, B); }).filter(function (x) { return x != null; });
          if (p == null) return "";
          var lo = Math.min.apply(null, [p].concat(sys)), hi = Math.max.apply(null, [p].concat(sys));
          var pc = function (x) { return Math.round(x * 100) + "%"; };
          return '<div class="h2hw-row chance"><b class="' + (p > 0.5 ? "best" : "") + '">' + pc(p) + '</b><span><span class="h2hw-bar" role="img" aria-label="Elo: ' + S.esc(nm(A)) + " " + pc(p) + '"><i style="width:' + (p * 100).toFixed(1) + '%"></i></span><small>Elo' +
            (sys.length ? " · other systems " + pc(lo) + "–" + pc(hi) : "") + '</small></span><b class="' + (p < 0.5 ? "best" : "") + '">' + pc(1 - p) + "</b></div>";
        }
        var better = r[3] == null || r[4] == null || r[3] === r[4] ? 0 : (r[3] > r[4]) === r[5] ? 1 : 2;
        return '<div class="h2hw-row"><b class="' + (better === 1 ? "best" : "") + '">' + r[1] + "</b><span>" + r[0] + '</span><b class="' + (better === 2 ? "best" : "") + '">' + r[2] + "</b></div>";
      }).join("");
  };
  // opts: { sport: "cs2"|"tennis", entries: rankings entries, featured: {a, b, event, date, tier}|null, asOf: ISO date }
  S.h2hWidget = function (el, o) {
    var cs2 = o.sport === "cs2", byId = {};
    o.entries.forEach(function (e) { byId[e.id] = e; });
    var order = o.entries.filter(function (e) { return e.official_rank; }).sort(function (a, b) { return a.official_rank - b.official_rank; });
    var f = o.featured || {}, A = byId[f.a] || order[0], B = byId[f.b] || order[1];
    if (!A || !B) { el.hidden = true; return; }
    var featuredPair = A.id + "|" + B.id, cache = {};
    var nm = function (e) { return cs2 ? e.short : e.name; };
    var shardOf = function (e) { return cs2 ? e.org : e.id; };
    var OFF = cs2 ? "Valve" : "ATP";
    function load(e) {
      if (!cache[e.id]) cache[e.id] = Promise.all([
        S.json("data/" + (cs2 ? "teams/" : "players/") + encodeURIComponent(e.id) + ".json").catch(function () { return null; }),
        shardOf(e) ? S.json("data/h2h/" + encodeURIComponent(shardOf(e)) + ".json").catch(function () { return null; }) : Promise.resolve(null)]);
      return cache[e.id];
    }
    var since = new Date(Date.parse(o.asOf) - 730 * 864e5).toISOString().slice(0, 10);
    function meetings(shardA) {
      if (!shardA || !shardA.vs) return null;
      var ms = shardA.vs[shardOf(B)] || [];
      return ms.filter(function (m) { return m[0] >= since; });
    }
    el.innerHTML = '<div class="h2hw-head"><h2>Head to head</h2><span class="h2hw-why" id="h2hw-why"></span></div>' +
      '<div class="h2hw-pick"><input id="h2hw-a" aria-label="' + (cs2 ? "Team" : "Player") + ' 1" autocomplete="off" spellcheck="false"><span class="h2hw-score" id="h2hw-score">–</span>' +
      '<input id="h2hw-b" class="b" aria-label="' + (cs2 ? "Team" : "Player") + ' 2" autocomplete="off" spellcheck="false"></div>' +
      '<div class="h2hw-sub"><span id="h2hw-sa"></span><span id="h2hw-last"></span><span id="h2hw-sb"></span></div>' +
      '<div class="h2hw-rows" id="h2hw-rows"></div>' +
      '<a class="h2hw-more" id="h2hw-more" href="predict.html">Full head-to-head and every system →</a>';
    var ia = el.querySelector("#h2hw-a"), ib = el.querySelector("#h2hw-b");
    var choices = o.entries.filter(function (e) { return e.official_rank || (e.ranks && e.ranks.elo); }).map(function (e) {
      return { id: e.id, name: nm(e), also: cs2 ? (e.players || []).join(" ") + " " + e.name : "",
               hint: [e.official_rank ? OFF + " #" + e.official_rank : null, e.ranks && e.ranks.elo ? "Elo #" + e.ranks.elo : null].filter(Boolean).join(" · ") };
    });
    S.autocomplete(ia, choices, function (it) { A = byId[it.id]; draw(); }, { selectOnFocus: true, empty: "Nobody by that name" });
    S.autocomplete(ib, choices, function (it) { B = byId[it.id]; draw(); }, { selectOnFocus: true, empty: "Nobody by that name" });
    ia.addEventListener("blur", function () { setTimeout(function () { ia.value = nm(A); }, 150); });
    ib.addEventListener("blur", function () { setTimeout(function () { ib.value = nm(B); }, 150); });

    function draw() {
      ia.value = nm(A); ib.value = nm(B);
      var why = el.querySelector("#h2hw-why");
      why.innerHTML = A.id + "|" + B.id !== featuredPair ? "" : f.event ?
        (cs2 ? S.cs2tier(f.tier, "") + " " : "") + "Up next: " + S.esc(f.event) + (f.date ? " · " + S.date(f.date.slice(0, 10)) : "") :
        OFF + " #1 against #2";
      el.querySelector("#h2hw-more").href = "predict.html?a=" + encodeURIComponent(A.id) + "&b=" + encodeURIComponent(B.id);
      var a0 = A, b0 = B;
      Promise.all([load(A), load(B)]).then(function (res) {
        if (a0 !== A || b0 !== B) return;  // changed while loading
        var pa = res[0][0] || {}, pb = res[1][0] || {}, ms = meetings(res[0][1]);
        // a meeting: CS2 [date, event, won, score, ...], tennis [date, event, round, won, score]
        var won = function (m) { return (cs2 ? m[2] : m[3]) === 1; };
        var wa = ms ? ms.filter(won).length : 0;
        var wb = ms ? ms.length - wa : 0;
        el.querySelector("#h2hw-score").innerHTML = ms ? '<b class="' + (wa > wb ? "lead" : "") + '">' + wa + '</b><i>–</i><b class="' + (wb > wa ? "lead" : "") + '">' + wb + "</b>" : "–";
        var last = ms && ms.length ? ms[ms.length - 1] : null, evs = (res[0][1] || {}).events || {};
        el.querySelector("#h2hw-last").innerHTML = (ms ? (ms.length ? "Last 2 years" + (cs2 ? ", every lineup" : "") : "No meetings in the last 2 years") : "") +
          (last ? '<br><small>Last: ' + S.esc((evs[last[1]] || [last[1]])[0]) + ", " + S.date(last[0]) + " · " + S.esc(nm(won(last) ? A : B)) + " won " + S.esc(won(last) ? (cs2 ? last[3] : last[4]) : (cs2 ? flip(last[3]) : last[4])) + "</small>" : "");
        el.querySelector("#h2hw-sa").innerHTML = side(A, pa);
        el.querySelector("#h2hw-sb").innerHTML = side(B, pb);
        rows(pa, pb);
      });
    }
    function side(e, p) {
      if (cs2) return (e.players || []).map(function (n, i) { return S.flag(e.flags && e.flags[i] !== "world" ? e.flags[i] : "") + S.esc(S.pname(n)); }).join(" ");
      return S.flag(e.iso) + [p.age ? Math.floor(p.age) + " yrs" : null, p.height ? p.height + " cm" : null, p.hand === "L" ? "Left-handed" : p.hand === "R" ? "Right-handed" : null].filter(Boolean).join(" · ");
    }
    function rows(pa, pb) { el.querySelector("#h2hw-rows").innerHTML = S.h2hRows(o.sport, A, B, pa, pb); }
    draw();
  };

  S.alignNums = alignNums;
  document.addEventListener("DOMContentLoaded", function () {
    alignNums(document.body);
    new MutationObserver(function (muts) {
      muts.forEach(function (m) { m.addedNodes.forEach(function (n) { if (n.nodeType === 1) alignNums(n); }); });
    }).observe(document.body, { childList: true, subtree: true });
  });
  document.addEventListener("DOMContentLoaded", function () { S.header(); S.footer(); });
})();
