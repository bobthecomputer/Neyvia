// Planner simulation: 3 seeds x simulated learner; prints the feed and goal checks G1-G10.
// node apps/scroll-study/scripts/simulate.cjs [wwwDir] [accuracy]
global.window = {};
const dir = process.argv[2] || require("path").join(__dirname, "..", "www");
require(dir + "/pack.js"); require(dir + "/feed.js");
const F = window.SSFeed, pack = window.SS_PACK;
for (const seed of [1, 2, 3]) {
  let rnd = seed * 9301;
  const r = () => ((rnd = (rnd * 9301 + 49297) % 233280) / 233280);
  const s = F.create(pack, { goal: 20, seed });
  const out = [];
  for (let i = 0; i < 40; i++) {
    F.release(s, i - 1); F.plan(s, i - 1, 3);
    const card = s.feed[i]; if (!card) { out.push("(none)"); break; }
    s.seen = i;
    if (card.type === "goal") { if (s.extra) { out.push("GOAL+"); break; } s.extra = 10; out.push("GOAL"); continue; }
    if (card.type === "end") { out.push("END"); break; }
    if (card.type === "reward") { s.rewards++; } else if (F.isTeach(card)) { F.expose(s, card, i); s.done++; }
    else if (F.isGraded(card)) { const ok = r() < (process.argv[3] ? Number(process.argv[3]) : 0.8); F.answer(s, card, i, ok ? "right" : "wrong", 5000); s.done++; }
    out.push(`${i}:${card.id}${card._result === "wrong" ? "(x)" : ""}[${s.log[i].reason}]`);
  }
  console.log("seed", seed, "\n " + out.join("\n "));
  console.log(F.checks(s).map(c => `${c.id} ${c.ok ? "ok" : "FAIL"} ${c.detail}`).join("\n"));
}
