// Replay the actual model-generated pack through the production feed planner.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const F = require('../apps/scroll-study/www/feed.js');
const folder = path.resolve(process.argv[2] || 'scripts/evidence/MS-runs/study');
const pack = JSON.parse(fs.readFileSync(path.join(folder, 'pack.json'), 'utf8'));
const s = F.create(pack, {goal: 54, sessionId: 'ms-real-note', now: '2026-10-04T10:00:00Z'});
let missed = null;
const history = [];
// Planning cannot treat a teach card as learned in advance.
const unseen = F.buildBlock(s.ledger, {history: [], sessionId: s.sessionId}, pack, {}, s.now);
assert.ok(unseen.every(c => !F.isGraded(c)), 'initial plan grades no unseen content');
for (let i = 0; i < 90; i++) {
  F.release(s, i - 1); F.plan(s, i - 1, 1);
  const card = s.feed[i]; if (!card) break;
  s.seen = i;
  if (['end', 'goal'].includes(card.type)) break;
  if (F.isTeach(card)) { F.expose(s, card, i); s.done++; }
  else if (F.isGraded(card)) {
    assert.ok(F.hardEligible(s.ledger, card, i, s.sessionId));
    for (const id of card.concepts.tests) {
      assert.ok(i - s.ledger[id].exposedAt >= 8, 'strict eight-card test lag');
      assert.ok(card.requiresParts.every(p => s.ledger[id].parts.includes(p)), 'all supporting parts have been read');
    }
    const wrong = !missed;
    if (wrong) missed = {index: i, card: card.id, concept: card.concepts.tests[0]};
    card._feedback = {verdict: wrong ? 'Not quite' : 'Right', answer: card.back, reason: card.explanation, source: card.source};
    F.answer(s, card, i, wrong ? 'wrong' : 'right', 15000); s.done++;
  }
  history.push({index: i, id: card.id, type: card.type, part: card.part, reason: card._planning.reason,
                result: card._result, exposure: card._planning.exposure});
}
const checks = F.checks(s);
assert.ok(checks.every(c => c.ok), JSON.stringify(checks.filter(c => !c.ok)));
assert.ok(missed, 'real pack exposes an exercise');
const retest = s.feed.slice(missed.index + 5, missed.index + 11).find(c => F.isGraded(c) && c.concepts.tests.includes(missed.concept));
assert.ok(retest && retest.id !== missed.card, 'miss reappears in changed form five to ten cards later');
const parts = ['formula', 'when', 'write', 'pattern', 'course_example', 'your_exercise', 'variations_traps'];
for (const concept of pack.concepts) assert.ok(parts.every(part => pack.cards.some(c => c.type === part && F.conceptsOf(c).includes(concept.id))), 'seven-part per concept');
assert.ok(history.some(c => c.type === 'pattern_drill'), 'recognition drill is scheduled');
assert.ok(history.some(c => c.type === 'exercise_variant'), 'changed exercise is scheduled');
const result = {ok: true, source: 'actual Luna/T14 generated OpenStax note pack', cardsShown: history.length,
                tests: history.filter(c => c.result).length, checks, initialNoUnseenTests: true,
                strictEightCardLag: true, supportingPartsTaught: true,
                missed, changedRetest: retest.id, history,
                boundary: 'The real production scheduler is executed; DOM and IndexedDB persistence need the separate running-browser journey.'};
fs.writeFileSync(path.join(folder, 'feed-proof.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify({ok: true, cardsShown: result.cardsShown, tests: result.tests, changedRetest: retest.id}));
