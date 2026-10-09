/* Scroll Study prototype: the feed UI. Cards come from pack.js, order from feed.js.
   Vertical drag/wheel/keys move between cards; horizontal swipes answer. Every gesture
   has a button twin (WCAG 2.5.7). window.scrollStudy exposes the same state and actions
   to agents and goal checks (the two-sided rule; A1's SDK replaces this shim). */
window.SS_BOOT.then(async function () {
  "use strict";
  var pack = window.SS_PACK;
  var F = window.SSFeed;
  var GOAL = 20;

  // lucide icons (ISC licence), inlined because the app has no build step
  var ICONS = {
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    left: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    right: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    up: '<path d="m18 15-6-6-6 6"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    book: '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
    help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    bulb: '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/>',
    restart: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    checks: '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>',
    sparkles: '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>',
    file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    steps: '<path d="M10 12h11"/><path d="M10 18h11"/><path d="M10 6h11"/><path d="M4 10h2"/><path d="M4 6h1v4"/><path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    list: '<path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M3 6h.01"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M8 6h13"/>'
  };
  function icon(name, cls) {
    return '<svg class="' + (cls || "") + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + "</svg>";
  }
  function sunMark(cls) {
    return '<svg class="ss-sunmark ' + (cls || "") + '" viewBox="0 0 80 80" aria-hidden="true"><defs><linearGradient id="ss-sun-g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffc455"/><stop offset=".55" stop-color="#f58a2e"/><stop offset="1" stop-color="#e3582a"/></linearGradient></defs>'
      + '<circle cx="40" cy="40" r="20" fill="url(#ss-sun-g)"/>'
      + [0, 45, 90, 135, 180, 225, 270, 315].map(function (a) {
        var r = a * Math.PI / 180, x1 = 40 + Math.cos(r) * 27, y1 = 40 + Math.sin(r) * 27, x2 = 40 + Math.cos(r) * 34, y2 = 40 + Math.sin(r) * 34;
        return '<line x1="' + x1.toFixed(1) + '" y1="' + y1.toFixed(1) + '" x2="' + x2.toFixed(1) + '" y2="' + y2.toFixed(1) + '" stroke="#f39a3d" stroke-width="3" stroke-linecap="round"/>';
      }).join("") + "</svg>";
  }
  function treeMark() {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="16.5" cy="7" r="4" fill="#f5a03a"/><path d="M8 20v-5" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/><path d="M8 4c3 2.5 4.5 5 4.5 7.5a4.5 4.5 0 0 1-9 0C3.5 9 5 6.5 8 4z" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round"/></svg>';
  }

  var FIGURES = {
    product: '<svg class="ss-figure" viewBox="0 0 300 150" role="img" aria-label="A rectangle of sides f and g grows by a strip f-prime times g and a strip f times g-prime">'
      + '<rect x="40" y="20" width="150" height="90" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/>'
      + '<rect x="190" y="20" width="34" height="90" rx="4" fill="none" class="accent" stroke-width="2" stroke-dasharray="4 4"/>'
      + '<rect x="40" y="110" width="150" height="24" rx="4" fill="none" class="accent" stroke-width="2" stroke-dasharray="4 4"/>'
      + '<text x="115" y="70" text-anchor="middle" class="math">f·g</text><text x="207" y="70" text-anchor="middle" class="math">f′g</text><text x="115" y="127" text-anchor="middle" class="math">f g′</text>'
      + '<text x="28" y="70" text-anchor="end" class="math">g</text><text x="115" y="14" text-anchor="middle" class="math">f</text></svg>',
    chain: '<svg class="ss-figure" viewBox="0 0 300 110" role="img" aria-label="x goes into g to make u, u goes into f to make y; the rates g-prime and f-prime multiply">'
      + '<text x="22" y="62" text-anchor="middle" class="math">x</text><text x="150" y="62" text-anchor="middle" class="math">u</text><text x="278" y="62" text-anchor="middle" class="math">y</text>'
      + '<path d="M36 57 H130" stroke="currentColor" stroke-width="1.5" fill="none"/><path d="M124 51 l8 6 -8 6" stroke="currentColor" stroke-width="1.5" fill="none"/>'
      + '<path d="M164 57 H258" stroke="currentColor" stroke-width="1.5" fill="none"/><path d="M252 51 l8 6 -8 6" stroke="currentColor" stroke-width="1.5" fill="none"/>'
      + '<text x="83" y="44" text-anchor="middle" class="math">g′(x)</text><text x="211" y="44" text-anchor="middle" class="math">f′(u)</text>'
      + '<path d="M83 78 Q150 104 211 78" class="accent" stroke-width="2" fill="none" stroke-dasharray="4 4"/><text x="150" y="104" text-anchor="middle">rates multiply</text></svg>',
    tangent: '<svg class="ss-figure" viewBox="0 0 300 160" role="img" aria-label="The parabola y equals x squared with its tangent line touching at one point">'
      + '<path d="M20 140 H290" class="soft" stroke-width="1" fill="none"/><path d="M150 150 V10" class="soft" stroke-width="1" fill="none"/>'
      + '<path d="M60 20 Q150 220 240 20" stroke="currentColor" stroke-width="1.75" fill="none"/>'
      + '<path d="M150 150 L270 30" class="accent" stroke-width="2.25" fill="none"/>'
      + '<circle cx="195" cy="105" r="5" fill="currentColor"/><text x="203" y="124" class="math">(a, f(a))</text><text x="262" y="56" text-anchor="end">slope f′(a)</text></svg>'
  };

  var KINDS = {
    start: ["book", "Today"], fact: ["book", "Idea"], explainer: ["book", "Explainer"], worked: ["steps", "Worked example"], recap: ["repeat", "Recap"],
    truefalse: ["help", "True or false"], mcq: ["help", "Pick one"], flashcard: ["help", "Recall"], cloze: ["help", "Fill the gap"],
    why: ["bulb", "Why?"], order: ["list", "Put in order"], spot: ["search", "Spot the error"], reward: ["sparkles", "Rare card"]
  };

  // ------------------------------------------------------------------ state --
  var S, current = 0, pages = new Map(), fxn = 0, landTimer = 0, exposeTimer = 0, sessionStart = Date.now();
  var navigationReady = Promise.resolve(), resolveNavigation = null;
  var track = document.getElementById("track");
  var viewport = document.getElementById("viewport");
  var reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  function reduce() { return reduceQuery.matches; }
  function conceptName(id) { var c = pack.concepts.filter(function (x) { return x.id === id; })[0]; return c ? c.name : id; }
  function esc(text) { return String(text).replace(/[&<>"]/g, function (ch) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]; }); }

  var store = {
    get: function (key, fallback) { try { var raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : fallback; } catch (e) { return fallback; } },
    set: function (key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* preview without storage */ } }
  };
  function day(offset) { var d = new Date(Date.now() + (offset || 0) * 864e5); return d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate(); }
  function streak() { return store.get("ss.streak", { days: 0, last: null }); }
  function daysText(n) { return n === 1 ? "1 day" : n + " days"; }

  var restored = null;
  var storageError = null;
  try { await window.SSStorage.savePack(pack); restored = await window.SSStorage.load(pack); }
  catch(error) { storageError = "This preview cannot keep IndexedDB progress. Export a backup, or open the app in its own browser window."; }
  var pendingSave = Promise.resolve();
  function persist() {
    pendingSave = pendingSave.then(function(){return window.SSStorage.save(S);}).catch(function(){storageError = "Progress could not be saved. Export a backup before closing.";});
    return pendingSave;
  }
  function boot() {
    S = F.create(pack, { goal: GOAL, seed: 7, ledger: restored && restored.ledger, schedule: restored && restored.schedule });
    S.feed[0] = { id: "start", type: "start" };
    S.log[0] = { index: 0, id: "start", type: "start", reason: "start", exposure: {} };
    S.seen = 0;
    F.plan(S, 0, 3);
    pages.forEach(function (el) { el.remove(); });
    pages.clear();
    current = 0;
    sync();
    go(0, false);
    updateTop();
  }

  // ------------------------------------------------------------------ pages --
  function sync() {
    S.feed.forEach(function (card, i) {
      var el = pages.get(i);
      if (el && el._card === card) return;
      if (el) el.remove();
      el = document.createElement("section");
      el.className = "ss-page";
      el.style.top = (i * 100) + "%";
      el.setAttribute("aria-roledescription", "card");
      el.tabIndex = -1;
      el._card = card;
      el.appendChild(build(card, i));
      track.appendChild(el);
      pages.set(i, el);
    });
    pages.forEach(function (el, i) { if (i >= S.feed.length) { el.remove(); pages.delete(i); } });
    pages.forEach(function (el, i) {
      var hidden = i !== current;
      el.setAttribute("aria-hidden", hidden ? "true" : "false");
      el.inert = hidden;
    });
  }

  function replan() {
    if (current !== S.seen) return;
    F.release(S, current);
    F.plan(S, current, 3);
    sync();
  }

  function kindLine(card, i) {
    var kind = KINDS[card.type] || ["book", ""];
    var concepts = F.conceptsOf(card);
    var reason = S.log[i] && S.log[i].reason;
    var ask = F.isGraded(card);
    var extra = reason === "re-test" ? "again, differently" : reason === "review" ? "review" : reason === "check" ? "quick check" : "";
    return '<div class="ss-kind' + (ask ? " is-ask" : "") + '">' + icon(kind[0]) + "<span>" + kind[1] + "</span>"
      + (concepts.length ? '<i class="ss-dot"></i><span class="ss-concept">' + esc(conceptName(concepts[0])) + "</span>" : "")
      + (extra ? '<i class="ss-dot"></i><span>' + extra + "</span>" : "") + "</div>";
  }

  function el(html) { var d = document.createElement("div"); d.innerHTML = html; return d.firstElementChild; }

  function build(card, i) {
    var make = BUILD[card.type] || BUILD.fact;
    var node = make(card, i);
    node.setAttribute("data-card", card.id);
    node.setAttribute("data-type", card.type);
    return node;
  }

  function teachFoot(card, canClaim) {
    return '<div class="ss-foot"><div class="ss-seen" data-seen><span class="ss-seen-bar"><i></i></span>' + icon("check") + '<span data-seen-text>Reading</span></div>'
      + (canClaim ? '<button type="button" class="ss-btn is-ghost is-small" data-know>I know this</button>' : "") + "</div>";
  }

  var BUILD = {
    start: function () {
      var due = pack.concepts.filter(function (c) { return c.prior; }).length;
      var node = el('<div class="ss-card is-plain"><div class="ss-hero">' + sunMark() + "<h2>" + esc(pack.meta.title) + "</h2><p>" + GOAL + " cards today. " + due + " ideas from last time are due for review; the rest is new.</p></div>"
        + '<div class="ss-grow"></div><div class="ss-hint-up">' + icon("up") + "<span>Swipe up to start</span></div>"
        + '<div class="ss-grow"></div><div class="ss-hero" style="padding:0"><span class="ss-credit">' + treeMark() + "Made with Neyvia</span></div></div>");
      return node;
    },
    fact: function (card, i) {
      return el('<div class="ss-card">' + kindLine(card, i) + '<div class="ss-grow"></div><h2 class="ss-title">' + card.title + '</h2><p class="ss-body">' + card.body + "</p>"
        + (card.why ? '<p class="ss-why"><strong>Why:</strong> ' + card.why + "</p>" : "") + '<div class="ss-grow"></div>' + teachFoot(card, true) + "</div>");
    },
    explainer: function (card, i) {
      return el('<div class="ss-card">' + kindLine(card, i) + '<div class="ss-grow"></div><h2 class="ss-title">' + card.title + "</h2>" + (card.figure ? FIGURES[card.figure] : "")
        + '<div class="ss-body">' + card.body + '</div><div class="ss-grow"></div>' + teachFoot(card, true) + "</div>");
    },
    recap: function (card, i) {
      return el('<div class="ss-card">' + kindLine(card, i) + '<div class="ss-grow"></div><h2 class="ss-title">' + card.title + '</h2><ul class="ss-recap">'
        + card.bullets.map(function (b) { return "<li><span>" + b + "</span></li>"; }).join("") + '</ul><div class="ss-grow"></div>' + teachFoot(card, false) + "</div>");
    },
    reward: function (card, i) {
      return el('<div class="ss-card is-reward">' + kindLine(card, i) + '<div class="ss-grow"></div><h2 class="ss-title">' + card.title + '</h2><p class="ss-body">' + card.body + "</p>"
        + '<div class="ss-grow"></div><p class="ss-why">Rare cards turn up now and then. Nothing to answer.</p></div>');
    },
    worked: function (card, i) {
      if (card.fade > 0) {
        card.front = card.steps.map(function(step,k){return (k+1)+". "+step.text;}).join("<br>");
        card.back = card.steps.map(function(step,k){return (k+1)+". "+(step.answer || step.text);}).join("<br>");
        return recallCard(card,i,card.front,card.back);
      }
      var node = el('<div class="ss-card">' + kindLine(card, i) + '<h2 class="ss-title">' + card.title + '</h2><div class="ss-steps" data-steps></div>'
        + '<div class="ss-grow"></div><div class="ss-foot"><div class="ss-dots" aria-hidden="true">' + card.steps.map(function () { return "<i></i>"; }).join("") + "</div>"
        + '<span class="ss-spacer" style="flex:1"></span><button type="button" class="ss-btn is-primary is-small" data-next-step>Next step ' + icon("right") + "</button></div></div>");
      card._ui = card._ui || { step: 0 };
      renderSteps(card, node);
      return node;
    },
    truefalse: function (card, i) {
      var node = el('<div class="ss-card">' + kindLine(card, i) + '<div class="ss-grow"></div><div class="ss-swipe" data-swipe><span class="ss-swipe-hint is-left">' + icon("left") + 'False</span><span class="ss-swipe-hint is-right">True' + icon("right") + "</span>"
        + '<p class="ss-statement">' + card.body + '</p></div><div class="ss-grow"></div><div data-answer-area><div class="ss-row">'
        + '<button type="button" class="ss-btn is-ghost" data-tf="false">' + icon("left") + 'False</button><button type="button" class="ss-btn is-ghost" data-tf="true">True' + icon("right") + "</button></div>"
        + '<p class="ss-gesture">Swipe right for true, left for false</p></div></div>');
      return node;
    },
    mcq: function (card, i) {
      var order = shuffle(card.options.map(function (_, k) { return k; }), card.id);
      return el('<div class="ss-card">' + kindLine(card, i) + '<p class="ss-face">' + card.body + '</p><div class="ss-grow"></div><div class="ss-options" role="group" aria-label="Answers">'
        + order.map(function (k) { return '<button type="button" class="ss-option" data-option="' + k + '">' + card.options[k].text + "</button>"; }).join("") + "</div><div data-answer-area></div></div>");
    },
    flashcard: function (card, i) { return recallCard(card, i, card.front, card.back); },
    why: function (card, i) { return recallCard(card, i, card.front, card.back); },
    cloze: function (card, i) {
      return el('<div class="ss-card">' + kindLine(card, i) + '<div class="ss-grow"></div><p class="ss-cloze">' + card.before + ' <button type="button" class="ss-blank" data-reveal aria-label="Reveal the missing part">Tap to reveal</button> ' + (card.after || "") + "</p>"
        + '<p class="ss-why">Say it in your head first, then tap.</p><div class="ss-grow"></div><div data-answer-area></div></div>');
    },
    order: function (card, i) {
      var order = shuffle(card.items.map(function (_, k) { return k; }), card.id, true);
      card._ui = card._ui || { picked: [] };
      return el('<div class="ss-card">' + kindLine(card, i) + '<p class="ss-face">' + card.body + '</p><p class="ss-why">Tap the steps in order.</p><div class="ss-grow"></div><div class="ss-options">'
        + order.map(function (k) { return '<button type="button" class="ss-option" data-item="' + k + '"><span class="ss-num"></span><span>' + card.items[k] + "</span></button>"; }).join("")
        + '</div><div class="ss-row" data-order-tools hidden><button type="button" class="ss-btn is-ghost is-small" data-undo>Undo last</button></div><div data-answer-area></div></div>');
    },
    spot: function (card, i) {
      return el('<div class="ss-card">' + kindLine(card, i) + '<h2 class="ss-title">' + card.title + '</h2><p class="ss-why">' + card.body + '</p><div class="ss-grow"></div><div class="ss-options">'
        + card.lines.map(function (line, k) { return '<button type="button" class="ss-option" data-line="' + k + '"><span class="ss-num">' + (k + 1) + "</span><span>" + line + "</span></button>"; }).join("")
        + "</div><div data-answer-area></div></div>");
    },
    goal: function (card) {
      return el('<div class="ss-card is-plain"><div class="ss-hero" data-goal-hero></div><div class="ss-grow"></div><div class="ss-row">'
        + '<button type="button" class="ss-btn is-ghost" data-more>10 more</button><button type="button" class="ss-btn is-primary" data-finish>Finish for today</button></div></div>');
    },
    end: function () {
      return el('<div class="ss-card is-plain"><div class="ss-hero" data-end-hero></div></div>');
    }
  };

  function recallCard(card, i, front, back) {
    return el('<div class="ss-card">' + kindLine(card, i) + '<div class="ss-grow"></div><div class="ss-swipe" data-swipe><span class="ss-swipe-hint is-left">' + icon("left") + 'Missed it</span><span class="ss-swipe-hint is-right">Got it' + icon("right") + "</span>"
      + '<p class="ss-face" style="padding-top:42px">' + front + '</p><div data-back hidden></div></div><div class="ss-grow"></div><div data-answer-area>'
      + '<button type="button" class="ss-btn is-primary" style="width:100%" data-reveal>Show answer</button><p class="ss-gesture">Answer in your head first.</p></div></div>');
  }

  function shuffle(list, seed, notSorted) {
    var h = 0;
    for (var k = 0; k < seed.length; k++) h = (h * 31 + seed.charCodeAt(k)) >>> 0;
    var out = list.slice();
    for (var n = out.length - 1; n > 0; n--) { h = (h * 1103515245 + 12345) >>> 0; var j = h % (n + 1); var t = out[n]; out[n] = out[j]; out[j] = t; }
    if (notSorted && out.every(function (v, k) { return v === k; })) out.reverse();
    return out;
  }

  // ---------------------------------------------------------------- worked --
  function renderSteps(card, node) {
    var ui = card._ui;
    var box = node.querySelector("[data-steps]");
    box.innerHTML = card.steps.slice(0, ui.step + 1).map(function (step, k) {
      return '<div class="ss-step' + (k === ui.step ? " is-current" : "") + (k === ui.step && ui.step > 0 && ui.animate ? " is-new" : "") + '"><b>' + (k + 1) + "</b><div>" + step.text
        + (step.why && k <= ui.step ? (ui.why === k ? '<p class="ss-step-why">' + step.why + "</p>" : '<div><button type="button" class="ss-link" data-step-why="' + k + '">Why this step?</button></div>') : "") + "</div></div>";
    }).join("");
    node.querySelectorAll(".ss-dots i").forEach(function (dot, k) { dot.classList.toggle("is-on", k <= ui.step); });
    var next = node.querySelector("[data-next-step]");
    var last = ui.step >= card.steps.length - 1;
    next.hidden = last;
  }

  function nextStep(page) {
    var card = page._card;
    if (card.type !== "worked" || card._ui.step >= card.steps.length - 1) return false;
    card._ui.step += 1;
    card._ui.animate = true;
    renderSteps(card, page.firstElementChild);
    card._ui.animate = false;
    if (card._ui.step >= card.steps.length - 1) markSeen(page, S.feed.indexOf(card));
    return true;
  }

  // -------------------------------------------------------------- exposure --
  function startExposure(page, i) {
    var card = page._card;
    clearTimeout(exposeTimer);
    if (!F.isTeach(card) || card._seen || card.type === "worked") return;
    var ms = Math.min(0.6 * (card.seconds || 10), 4) * 1000;
    var seen = page.querySelector("[data-seen]");
    if (seen) {
      var bar = seen.querySelector("i");
      bar.style.transitionDuration = ms + "ms";
      seen.classList.remove("is-running");
      void bar.offsetWidth;
      seen.classList.add("is-running");
    }
    exposeTimer = setTimeout(function () { markSeen(page, i); }, ms);
  }

  function stopExposure(page) {
    clearTimeout(exposeTimer);
    var seen = page && page.querySelector("[data-seen]");
    if (seen && !page._card._seen) seen.classList.remove("is-running");
  }

  function markSeen(page, i, claimed) {
    var card = page._card;
    if (card._seen) return;
    card._seen = true;
    if (claimed) F.knowThis(S, card, i); else F.expose(S, card, i);
    persist();
    S.done += 1;
    var seen = page.querySelector("[data-seen]");
    if (seen) { seen.classList.add("is-done"); seen.querySelector("[data-seen-text]").textContent = claimed ? "Check coming up" : "Seen"; }
    var know = page.querySelector("[data-know]");
    if (know) know.remove();
    updateTop();
    replan();
  }

  // ---------------------------------------------------------------- answers --
  function finish(page, ok, detail) {
    var card = page._card;
    var i = S.feed.indexOf(card);
    if (card._ui && card._ui.answered) return;
    card._ui = card._ui || {};
    card._ui.answered = true;
    var ms = Date.now() - (page._shownAt || Date.now());
    var correctText = card.type === "truefalse" ? (card.answer ? "True" : "False") : card.type === "mcq" ? card.options.find(function(o){return o.correct;}).text : card.back || card.blank || detail || (card.items && card.items.join(" → ")) || card.fix || (card.steps && card.steps.map(function(s){return s.answer || s.text;}).join(" → "));
    card._feedback = {verdict: ok ? "right" : "wrong", answer: correctText, reason: card.explanation || "", source: card.source || card.src};
    F.answer(S, card, i, ok ? "right" : "wrong", ms);
    S.done += 1;
    var area = page.querySelector("[data-answer-area]");
    var fx = ok ? " fx-" + (fxn++ % 3) : "";
    var head = ok ? ["Right", "Correct", "That’s it"][fxn % 3] : "Not quite";
    if (card.type === "flashcard" || card.type === "why" || card.type === "cloze") head = ok ? "Got it" : "Missed it";
    var answerLine = correctText ? '<p class="ss-verdict-text"><strong>Answer:</strong> ' + correctText + "</p>" : "";
    var again = !ok ? '<p class="ss-verdict-text">It comes back in a few cards.</p>' : "";
    area.innerHTML = '<div class="ss-verdict is-' + (ok ? "right" : "wrong") + fx + '" role="status">'
      + '<div class="ss-verdict-head">' + icon(ok ? "check" : "x", "ss-verdict-icon") + "<span>" + head + "</span></div>" + answerLine
      + '<p class="ss-verdict-text">' + (card.explanation || "") + "</p>" + again
      + '<div class="ss-verdict-foot"><button type="button" class="ss-link" data-source>Show me where</button><span class="ss-verdict-next">Next' + icon("up") + "</span></div></div>";
    if (ok && navigator.vibrate) { try { navigator.vibrate(8); } catch (e) { /* not allowed */ } }
    page._swipe = null;
    updateTop(true);
    replan();
    persist();
  }

  function answerTF(page, value) {
    var card = page._card;
    if (card._ui && card._ui.answered) return;
    var ok = value === card.answer;
    var statement = page.querySelector(".ss-statement");
    finish(page, ok, ok ? "" : (card.answer ? "True" : "False"));
  }

  function answerMCQ(page, k) {
    var card = page._card;
    if (card._ui && card._ui.answered) return;
    var ok = Boolean(card.options[k].correct);
    page.querySelectorAll("[data-option]").forEach(function (button) {
      var j = Number(button.getAttribute("data-option"));
      button.disabled = true;
      if (card.options[j].correct) { button.classList.add("is-right"); button.insertAdjacentHTML("beforeend", icon("check", "ss-mark")); }
      else if (j === k) {
        button.classList.add("is-wrong");
        button.insertAdjacentHTML("beforeend", icon("x", "ss-mark"));
        if (card.options[j].why) button.insertAdjacentHTML("afterend", '<p class="ss-whynot">' + card.options[j].why + "</p>");
      } else button.classList.add("is-dim");
    });
    var right = card.options.filter(function (o) { return o.correct; })[0];
    finish(page, ok, ok ? "" : right.text);
  }

  function reveal(page) {
    var card = page._card;
    card._ui = card._ui || {};
    if (card._ui.revealed) return;
    card._ui.revealed = true;
    card._ui.revealAt = Date.now();
    card._ui.revealedAt = card._ui.revealAt;
    card._revealMs = card._ui.revealAt - (page._shownAt || card._ui.revealAt);
    if (card.type === "cloze") {
      var blank = page.querySelector(".ss-blank");
      blank.outerHTML = '<span class="ss-blank is-open">' + card.blank + "</span>";
    } else {
      var back = page.querySelector("[data-back]");
      back.hidden = false;
      back.innerHTML = '<div class="ss-back">' + card.back + "</div>";
    }
    var area = page.querySelector("[data-answer-area]");
    area.innerHTML = '<div class="ss-row"><button type="button" class="ss-btn is-ghost" data-self="missed">' + icon("left") + 'Missed it</button><button type="button" class="ss-btn is-ghost" data-self="got">Got it' + icon("right") + "</button></div>"
      + '<p class="ss-gesture">Be honest: a miss brings it back sooner.</p>';
    if (card.type === "cloze") {
      // the cloze has no swipe surface until revealed; let the sentence carry the swipe
      var sentence = page.querySelector(".ss-cloze");
      sentence.setAttribute("data-swipe", "");
    }
  }

  function selfGrade(page, got) {
    var card = page._card;
    if (!card._ui || !card._ui.revealed || card._ui.answered) return;
    finish(page, got, "");
  }

  function pickOrder(page, k) {
    var card = page._card;
    var ui = card._ui;
    if (ui.answered || ui.picked.indexOf(k) >= 0) return;
    ui.picked.push(k);
    paintOrder(page);
    if (ui.picked.length === card.items.length) {
      var ok = ui.picked.every(function (v, n) { return v === n; });
      page.querySelectorAll("[data-item]").forEach(function (button) {
        var j = Number(button.getAttribute("data-item"));
        button.disabled = true;
        button.classList.add(ui.picked.indexOf(j) === j ? "is-right" : "is-wrong");
      });
      page.querySelector("[data-order-tools]").hidden = true;
      finish(page, ok, ok ? "" : card.items.map(function (t, n) { return (n + 1) + ". " + t; }).join("<br>"));
    }
  }

  function paintOrder(page) {
    var ui = page._card._ui;
    page.querySelectorAll("[data-item]").forEach(function (button) {
      var j = Number(button.getAttribute("data-item"));
      var at = ui.picked.indexOf(j);
      button.classList.toggle("is-picked", at >= 0);
      button.querySelector(".ss-num").textContent = at >= 0 ? String(at + 1) : "";
    });
    page.querySelector("[data-order-tools]").hidden = !ui.picked.length || ui.answered;
  }

  function answerSpot(page, k) {
    var card = page._card;
    if (card._ui && card._ui.answered) return;
    var ok = k === card.wrong;
    page.querySelectorAll("[data-line]").forEach(function (button) {
      var j = Number(button.getAttribute("data-line"));
      button.disabled = true;
      if (j === card.wrong) button.classList.add(ok ? "is-right" : "is-wrong");
      else if (j === k) button.classList.add("is-dim");
    });
    finish(page, ok, "line " + (card.wrong + 1) + " should be " + card.fix);
  }

  // ------------------------------------------------------------- goal / end --
  function stats() {
    var graded = S.feed.slice(0, S.seen + 1).filter(function (c) { return F.isGraded(c) && c._result && c._result !== "skipped"; });
    var right = graded.filter(function (c) { return c._result === "right"; }).length;
    var fresh = pack.concepts.filter(function (c) { var row = S.ledger[c.id]; return !c.prior && row.exposedAt !== null; }).length;
    return { graded: graded.length, right: right, fresh: fresh };
  }

  function paintGoal(page) {
    var st = streak();
    if (!page._card._counted) {
      page._card._counted = true;
      if (st.last !== day(0)) { st = { days: st.last === day(-1) ? st.days + 1 : 1, last: day(0) }; store.set("ss.streak", st); }
    }
    var s = stats();
    var hero = page.querySelector("[data-goal-hero]");
    hero.innerHTML = sunMark(reduce() ? "" : "is-rising") + "<h2>" + (S.extra ? "That’s 10 more" : "Today’s goal done") + "</h2>"
      + "<p>" + daysText(st.days) + " in a row. Everything you saw today is scheduled for its next review.</p>"
      + '<div class="ss-stats"><div class="ss-stat"><b>' + S.done + "</b><span>cards</span></div><div class=\"ss-stat\"><b>" + s.right + "/" + s.graded
      + '</b><span>right</span></div><div class="ss-stat"><b>' + s.fresh + "</b><span>new ideas</span></div></div>";
    updateTop();
  }

  function paintEnd(page) {
    var s = stats();
    var tomorrow = pack.concepts.filter(function (c) { return S.ledger[c.id].exposedAt !== null; }).length;
    page.querySelector("[data-end-hero]").innerHTML = "<h2>All done for today</h2><p>Come back tomorrow: about " + tomorrow + " ideas will be due for a quick review.</p>"
      + '<div class="ss-stats"><div class="ss-stat"><b>' + S.done + '</b><span>cards</span></div><div class="ss-stat"><b>' + (s.graded ? Math.round(100 * s.right / s.graded) : 0)
      + '%</b><span>recalled</span></div><div class="ss-stat"><b>' + s.fresh + "</b><span>new ideas</span></div></div>";
  }

  function more(page) {
    S.extra += 10;
    var i = S.feed.indexOf(page._card);
    F.release(S, i);
    F.plan(S, i, 3);
    sync();
    go(i + 1);
  }

  function finishDay(page) {
    var i = S.feed.indexOf(page._card);
    F.release(S, i);
    S.feed.length = i + 1;
    S.log.length = i + 1;
    S.ended = true;
    S.feed[i + 1] = { id: "end", type: "end" };
    S.log[i + 1] = { index: i + 1, id: "end", type: "end", reason: "finished", exposure: {} };
    sync();
    go(i + 1);
  }

  // ------------------------------------------------------------- navigation --
  function go(i, animate) {
    if (animate === undefined) animate = true;
    i = Math.max(0, Math.min(i, S.feed.length - 1));
    var from = current;
    var leaving = pages.get(from);
    if (i !== from && leaving) {
      stopExposure(leaving);
      var card = leaving._card;
      if (i > from && F.isGraded(card) && !(card._ui && card._ui.answered) && !card._result) {
        F.answer(S, card, from, "skipped", 0);
      }
    }
    current = i;
    var moving = animate && !reduce() && i !== from;
    track.classList.toggle("is-moving", moving || (animate && !reduce()));
    track.style.transform = "translate3d(0," + (-i * 100) + "%,0)";
    pages.forEach(function (el, k) { el.setAttribute("aria-hidden", k === i ? "false" : "true"); el.inert = k !== i; });
    clearTimeout(landTimer);
    if(resolveNavigation)resolveNavigation();
    navigationReady = new Promise(function(resolve){resolveNavigation=resolve;});
    landTimer = setTimeout(function () {
      land(i);
      if(resolveNavigation){resolveNavigation();resolveNavigation=null;}
    }, moving ? 330 : 0);
  }

  function land(i) {
    if (i !== current) return;
    track.classList.remove("is-moving");
    if (i > S.seen) {
      S.seen = i;
      F.release(S, i);
      F.plan(S, i, 3);
      sync();
    }
    var page = pages.get(i);
    if (!page) return;
    page._shownAt = page._shownAt || Date.now();
    var card = page._card;
    if (card.type === "reward" && !card._counted) {
      card._counted = true;
      S.rewards += 1;
      if (!reduce()) page.firstElementChild.classList.add("is-arrived");
    }
    if (card.type === "goal") paintGoal(page);
    if (card.type === "end") paintEnd(page);
    if (card.type === "truefalse" || ((card.type === "flashcard" || card.type === "why" || card.type === "cloze") && card._ui && card._ui.revealed) || card.type === "worked") {
      page._swipe = page.querySelector("[data-swipe]") || page.firstElementChild;
    }
    startExposure(page, i);
    updateTop();
  }

  // ---------------------------------------------------------------- top bar --
  var lastRun = 0;
  function updateTop(answered) {
    var goal = S.goal + S.extra;
    var shown = Math.min(S.done, goal);
    document.getElementById("count").textContent = shown + " of " + goal;
    var bar = document.getElementById("goal");
    bar.setAttribute("aria-valuenow", String(shown));
    bar.setAttribute("aria-valuemax", String(goal));
    bar.querySelector(".ss-goal-fill").style.transform = "scaleX(" + (shown / goal).toFixed(3) + ")";
    bar.classList.toggle("is-done", S.done >= goal);
    var run = document.getElementById("run");
    run.classList.toggle("is-on", S.run >= 3);
    run.querySelector("span").textContent = S.run + " in a row";
    if (answered && S.run >= 3 && S.run !== lastRun && !reduce()) {
      run.classList.remove("is-bump"); void run.offsetWidth; run.classList.add("is-bump");
    }
    lastRun = S.run;
    document.getElementById("streak").querySelector("span").textContent = daysText(streak().days);
  }

  // ------------------------------------------------------------------ sheet --
  var sheetOpen = null;
  function openSheet(html, opener) {
    closeSheet();
    var scrim = el('<div class="ss-scrim"></div>');
    var sheet = el('<div class="ss-sheet" role="dialog" aria-modal="true" tabindex="-1"><div class="ss-sheet-grip" aria-hidden="true"></div>' + html + "</div>");
    sheet.setAttribute("aria-label", (sheet.querySelector("h3") || {}).textContent || "Details");
    document.body.appendChild(scrim);
    document.body.appendChild(sheet);
    scrim.addEventListener("click", closeSheet);
    sheetOpen = { scrim: scrim, sheet: sheet, opener: opener };
    document.getElementById("app").inert = true;
    sheet.focus();
    return sheet;
  }
  function closeSheet() {
    if (!sheetOpen) return;
    sheetOpen.scrim.remove();
    sheetOpen.sheet.remove();
    document.getElementById("app").inert = false;
    if (sheetOpen.opener && sheetOpen.opener.focus) sheetOpen.opener.focus();
    sheetOpen = null;
  }

  function showSource(card, opener) {
    var text = pack.source.text[card.src] || "";
    openSheet('<h3>From your notes</h3><p class="ss-sub">' + esc(pack.source.title) + '</p><p class="ss-source"><mark>' + esc(text) + "</mark></p>", opener);
  }

  function showMenu(opener) {
    var sheet = openSheet('<h3>Scroll Study</h3><p class="ss-sub">Prototype with sample cards. Progress resets when you restart.</p><div class="ss-menu">'
      + '<button type="button" data-menu="checks">' + icon("checks") + "How the feed chose these cards</button>"
      + '<button type="button" data-menu="restart">' + icon("restart") + "Restart the sample</button></div>"
      + '<p class="ss-about">Made with Neyvia. If you build on this, we would love a credit: "Made with Neyvia".</p>', opener);
    sheet.addEventListener("click", function (event) {
      var button = event.target.closest("[data-menu]");
      if (!button) return;
      if (button.getAttribute("data-menu") === "restart") { closeSheet(); boot(); }
      else showChecks(opener);
    });
  }

  function showChecks(opener) {
    var rows = F.checks(S);
    openSheet("<h3>How the feed chose these cards</h3><p class=\"ss-sub\">Checked live on the " + (S.seen + 1) + " cards shown so far.</p><ul class=\"ss-checks\">"
      + rows.map(function (r) { return '<li class="is-' + (r.ok ? "ok" : "fail") + '">' + icon(r.ok ? "check" : "x") + "<span>" + r.text + (r.detail ? "<small>" + esc(r.detail) + "</small>" : "") + "</span></li>"; }).join("")
      + "</ul>", opener);
  }

  // --------------------------------------------------------------- gestures --
  var drag = null;
  function swipeFor(target) {
    var page = pages.get(current);
    if (!page || !page._swipe || !page.contains(target)) return null;
    var card = page._card;
    if (card._ui && card._ui.answered) return null;
    return page._swipe;
  }

  viewport.addEventListener("pointerdown", function (event) {
    if (event.button > 0 || sheetOpen) return;
    drag = { x: event.clientX, y: event.clientY, t: performance.now(), id: event.pointerId, axis: null, dx: 0, dy: 0, vx: 0, vy: 0,
      lt: performance.now(), lx: event.clientX, ly: event.clientY, swipe: swipeFor(event.target), moved: false };
  });
  window.addEventListener("pointermove", function (event) {
    if (!drag || event.pointerId !== drag.id) return;
    var dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    var now = performance.now(), dt = Math.max(1, now - drag.lt);
    drag.vx = (event.clientX - drag.lx) / dt; drag.vy = (event.clientY - drag.ly) / dt;
    drag.lx = event.clientX; drag.ly = event.clientY; drag.lt = now;
    drag.dx = dx; drag.dy = dy;
    if (!drag.axis) {
      if (Math.hypot(dx, dy) < 8) return;
      drag.axis = Math.abs(dx) > Math.abs(dy) * 1.2 && drag.swipe ? "x" : Math.abs(dy) >= Math.abs(dx) ? "y" : null;
      if (!drag.axis) { drag = null; return; }
      drag.moved = true;
      track.classList.remove("is-moving");
      if (drag.axis === "x") drag.swipe.classList.add("is-dragging");
    }
    if (drag.axis === "y") {
      var off = dy;
      if ((dy > 0 && current === 0) || (dy < 0 && current >= S.feed.length - 1)) off = dy * 0.25;
      track.style.transform = "translate3d(0,calc(" + (-current * 100) + "% + " + off + "px),0)";
    } else {
      var page = pages.get(current);
      var isWorked = page._card.type === "worked";
      var x = isWorked ? Math.min(0, dx) : dx;
      if (!isWorked) {
        drag.swipe.style.transform = "translateX(" + x + "px) rotate(" + (x / 26).toFixed(2) + "deg)";
        var l = drag.swipe.querySelector(".ss-swipe-hint.is-left"), r = drag.swipe.querySelector(".ss-swipe-hint.is-right");
        if (l) l.style.opacity = Math.min(1, Math.max(0, -x / 80)).toFixed(2);
        if (r) r.style.opacity = Math.min(1, Math.max(0, x / 80)).toFixed(2);
      } else drag.swipe.style.transform = "translateX(" + (x * 0.35) + "px)";
    }
  });
  function endDrag(event) {
    if (!drag || event.pointerId !== drag.id) return;
    var d = drag;
    drag = null;
    if (!d.moved) return;
    var swallow = function (click) { click.stopPropagation(); click.preventDefault(); };
    window.addEventListener("click", swallow, true);
    setTimeout(function () { window.removeEventListener("click", swallow, true); }, 0);
    if (d.axis === "y") {
      var h = viewport.clientHeight;
      if (d.dy < -h * 0.16 || d.vy < -0.5) go(current + 1);
      else if (d.dy > h * 0.16 || d.vy > 0.5) go(current - 1);
      else go(current);
      return;
    }
    var swipe = d.swipe;
    swipe.classList.remove("is-dragging");
    swipe.style.transform = "";
    swipe.querySelectorAll(".ss-swipe-hint").forEach(function (hint) { hint.style.opacity = ""; });
    if (Math.abs(d.dx) > 80 || Math.abs(d.vx) > 0.6) commitSwipe(d.dx > 0 ? "right" : "left");
  }
  window.addEventListener("pointerup", endDrag);
  window.addEventListener("pointercancel", endDrag);
  // Mobile Studio's preview turns mouse drags into touch events and scrolls with them;
  // the feed moves itself, so tell it not to.
  viewport.addEventListener("touchmove", function (event) { event.preventDefault(); }, { passive: false });

  function commitSwipe(direction) {
    var page = pages.get(current);
    if (!page) return false;
    var card = page._card;
    if (card.type === "worked") return direction === "left" ? nextStep(page) : false;
    if (card._ui && card._ui.answered) return false;
    if (card.type === "truefalse") { answerTF(page, direction === "right"); return true; }
    if (card._ui && card._ui.revealed) { selfGrade(page, direction === "right"); return true; }
    return false;
  }

  var wheelAcc = 0, wheelLock = 0;
  viewport.addEventListener("wheel", function (event) {
    event.preventDefault();
    if (sheetOpen) return;
    var now = Date.now();
    if (now < wheelLock) return;
    wheelAcc += event.deltaY;
    if (Math.abs(wheelAcc) > 40) { go(current + (wheelAcc > 0 ? 1 : -1)); wheelAcc = 0; wheelLock = now + 450; }
  }, { passive: false });

  window.addEventListener("keydown", function (event) {
    if (sheetOpen) { if (event.key === "Escape") closeSheet(); return; }
    var onButton = event.target && event.target.closest && event.target.closest("button");
    if (event.key === "ArrowDown" || event.key === "PageDown" || event.key === "j") { event.preventDefault(); go(current + 1); focusPage(); }
    else if (event.key === "ArrowUp" || event.key === "PageUp" || event.key === "k") { event.preventDefault(); go(current - 1); focusPage(); }
    else if (event.key === "ArrowRight" && !onButton) commitSwipe("right");
    else if (event.key === "ArrowLeft" && !onButton) commitSwipe("left");
  });
  function focusPage() { setTimeout(function () { var p = pages.get(current); if (p) p.focus({ preventScroll: true }); }, 0); }

  // ------------------------------------------------------------------ clicks --
  document.getElementById("app").addEventListener("click", function (event) {
    var t = event.target.closest("button");
    if (!t) return;
    if (t.id === "menu") return showMenu(t);
    var page = t.closest(".ss-page");
    if (!page) return;
    var card = page._card;
    var i = S.feed.indexOf(card);
    if (t.hasAttribute("data-tf")) answerTF(page, t.getAttribute("data-tf") === "true");
    else if (t.hasAttribute("data-option")) answerMCQ(page, Number(t.getAttribute("data-option")));
    else if (t.hasAttribute("data-reveal")) { reveal(page); page._swipe = page.querySelector("[data-swipe]"); }
    else if (t.hasAttribute("data-self")) selfGrade(page, t.getAttribute("data-self") === "got");
    else if (t.hasAttribute("data-item")) pickOrder(page, Number(t.getAttribute("data-item")));
    else if (t.hasAttribute("data-undo")) { card._ui.picked.pop(); paintOrder(page); }
    else if (t.hasAttribute("data-line")) answerSpot(page, Number(t.getAttribute("data-line")));
    else if (t.hasAttribute("data-next-step")) nextStep(page);
    else if (t.hasAttribute("data-step-why")) { card._ui.why = Number(t.getAttribute("data-step-why")); renderSteps(card, page.firstElementChild); }
    else if (t.hasAttribute("data-know")) { stopExposure(page); markSeen(page, i, true); }
    else if (t.hasAttribute("data-source")) showSource(card, t);
    else if (t.hasAttribute("data-more")) more(page);
    else if (t.hasAttribute("data-finish")) finishDay(page);
  });

  // ------------------------------------------- the app's own state API (A1) --
  function page() { return pages.get(current); }
  window.scrollStudy = {
    version: "prototype-1",
    state: function () {
      var card = S.feed[current];
      return {
        index: current, seen: S.seen, done: S.done, goal: S.goal + S.extra, run: S.run, streakDays: streak().days, ended: S.ended,
        card: card ? { id: card.id, type: card.type, concepts: F.conceptsOf(card), answered: Boolean(card._ui && card._ui.answered), result: card._result || null, seen: Boolean(card._seen) } : null,
        ledger: Object.keys(S.ledger).reduce(function (out, id) { out[id] = { state: S.ledger[id].state, exposedAt: S.ledger[id].exposedAt }; return out; }, {}),
        upcoming: S.feed.slice(current + 1).map(function (c) { return c.id; }),
        pack: pack.meta ? pack.meta.id : "sample", schedule: S.schedule, storageError: storageError,
        feedback: card && card._feedback || null
      };
    },
    next: function () { go(current + 1); return true; },
    prev: function () { go(current - 1); return true; },
    seeNow: function () { var p = page(); if (p && F.isTeach(p._card)) { markSeen(p, current); return true; } return false; },
    knowThis: function () { var p = page(); if (p && (p._card.type === "fact" || p._card.type === "explainer")) { markSeen(p, current, true); return true; } return false; },
    reveal: function () { var p = page(); if (p) { reveal(p); p._swipe = p.querySelector("[data-swipe]"); } return true; },
    swipe: function (direction) { return commitSwipe(direction); },
    answer: function (value) {
      var p = page(), card = p && p._card;
      if (!card || !F.isGraded(card)) return false;
      if (card.type === "truefalse") answerTF(p, Boolean(value));
      else if (card.type === "mcq") answerMCQ(p, value === "correct" ? card.options.findIndex(function (o) { return o.correct; }) : Number(value));
      else if (card.type === "spot") answerSpot(p, value === "correct" ? card.wrong : Number(value));
      else if (card.type === "order") { (value === "correct" ? card.items.map(function (_, k) { return k; }) : value).forEach(function (k) { pickOrder(p, k); }); }
      else { reveal(p); selfGrade(p, value === true || value === "got" || value === "correct"); }
      return true;
    },
    correct: function () { var card = S.feed[current]; return card.type === "truefalse" ? card.answer : "correct"; },
    more: function () { var p = page(); if (p && p._card.type === "goal") { more(p); return true; } return false; },
    finish: function () { var p = page(); if (p && p._card.type === "goal") { finishDay(p); return true; } return false; },
    restart: function () { closeSheet(); boot(); return true; },
    checks: function () { return F.checks(S); },
    log: function () { return S.log.slice(0, S.seen + 1); },
    exportProgress: function () { return window.SSStorage.exportProgress(S); },
    importProgress: async function (text) { restored = await window.SSStorage.importProgress(text,pack); boot(); return window.scrollStudy.state(); },
    save: persist
  };

  // A1's CL 1.1 bridge conventions, specialized to the existing feed reducer.
  // User controls and agent calls act on S and use the same IndexedDB store.
  var revision = 0, observedState = null, actionReceipts = new Map();
  function versionedState() {
    var state=window.scrollStudy.state(), fingerprint=JSON.stringify(state);
    if(observedState!==null && observedState!==fingerprint)revision+=1;
    observedState=fingerprint;
    return Object.assign(state,{revision:revision});
  }
  window.neyviaApp = Object.freeze({
    describe: function () { return {version:"1.1",instance:"scroll-study",transport:storageError?"preview-memory":"device-local-indexeddb",actions:["next","prev","seeNow","knowThis","reveal","swipe","answer","more","finish","restart"],state:this.state()}; },
    state: versionedState,
    checks: function () { return window.scrollStudy.checks().reduce(function(out,row){out[row.id]=row.ok;return out;},{}); },
    async act(name,args,options) {
      args=args||{};options=options||{};
      var fingerprint=JSON.stringify([name,args]);
      if(options.actionId && actionReceipts.has(options.actionId)) {
        var old=actionReceipts.get(options.actionId);
        if(old.fingerprint!==fingerprint)throw new Error("Action ID is already bound to different arguments");
        return Object.assign({},old.receipt,{replayed:true});
      }
      var before=this.state();
      if(options.expectedRevision!==undefined && options.expectedRevision!==before.revision)throw new Error("State changed; observe again");
      if(!this.describe().actions.includes(name))throw new Error("Unknown action: "+name);
      var result=await window.scrollStudy[name](name==="answer"?args.value:name==="swipe"?args.direction:undefined);
      await navigationReady;
      await persist();
      var receipt={ok:result!==false,before:before,after:this.state(),checks:this.checks(),transport:this.describe().transport};
      if(options.actionId){actionReceipts.set(options.actionId,{fingerprint:fingerprint,receipt:receipt});if(actionReceipts.size>1000)actionReceipts.delete(actionReceipts.keys().next().value);}
      return receipt;
    }
  });

  document.getElementById("streak").innerHTML = icon("sun") + "<span></span>";
  document.getElementById("run").innerHTML = icon("zap") + "<span></span>";
  document.getElementById("menu").innerHTML = icon("more");
  boot();
  window.dispatchEvent(new Event("neyvia-app-ready"));
}).catch(function(error){document.getElementById("track").textContent=error.message;window.SS_LOAD_ERROR=error.message;});
