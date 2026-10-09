import assert from "node:assert/strict";
import test from "node:test";

import {
  amplifyPayload, cardPhase, chatContext, composeEdit, fieldsFrom, isEdited, learningLine, openQuestions,
  receiptLine, sendOptions, shouldAmplify,
} from "./nxAmplifyModel.js";

const ready = {
  id: "amp-1", revision: 1, status: "ready", original: "fix the side bar thing from before its too wide",
  goal: "Make the sidebar narrower", deliverable: { form: "CSS change", path: "web/src/nxSidebar.css" },
  checks: ["Sidebar is 248 px or less", "Phone layout unchanged"], assumptions: ["\"the side bar thing\" is the chat sidebar"],
  constraints: ["Theme tokens only"], questions: [], contextPointers: [{ kind: "file", target: "web/src/nxSidebar.css" }],
  route: "script", elapsedMs: 140, tokens: 0,
};

test("which sends go through the card", () => {
  assert.equal(shouldAmplify({ mode: "auto", message: "fix the sidebar width please" }), true);
  assert.equal(shouldAmplify({ mode: "off", message: "fix the sidebar width please" }), false);
  assert.equal(shouldAmplify({ mode: "auto", message: "ok" }), false);
  assert.equal(shouldAmplify({ mode: "auto", message: "fix the sidebar width please", steering: true }), false);
  assert.equal(shouldAmplify({ mode: "auto", message: "fix the sidebar width please", autopilot: true }), false);
  assert.equal(shouldAmplify({ mode: "weird", message: "fix the sidebar width please" }), true);
});

test("context is bounded chat text, no optimistic or tool items", () => {
  const items = [
    { kind: "tool", data: { output: "x" } },
    ...Array.from({ length: 8 }, (_, index) => ({ kind: index % 2 ? "assistant" : "user", data: { text: `turn ${index}` } })),
    { kind: "user", optimistic: true, data: { text: "pending" } },
    { kind: "assistant", data: { text: "y".repeat(5000) } },
  ];
  const chat = chatContext(items);
  assert.equal(chat.length, 6);
  assert.equal(chat.at(-1).text.length, 1201);
  assert.ok(!chat.some(turn => turn.text === "pending"));
  const payload = amplifyPayload({ text: "  do that again  ", requestId: "r1", sessionId: "s1", items, project: "C:/p", mode: "off" });
  assert.equal(payload.text, "do that again");
  assert.equal(payload.mode, "auto");
  assert.deepEqual(payload.context, { project: "C:/p" });  // the broker supplies the chat's turns
  assert.equal(amplifyPayload({ text: "x", requestId: "r", items, mode: "auto" }).context.chat.length, 6);
  assert.deepEqual(amplifyPayload({ text: "x", requestId: "r", mode: "review" }), { text: "x", requestId: "r", mode: "review" });
});

test("phases: count down only when ready, unedited and not held", () => {
  const fields = fieldsFrom(ready);
  assert.equal(fields.deliverable, "CSS change: web/src/nxSidebar.css");
  assert.equal(cardPhase({ amplification: null, fields, mode: "auto" }), "wait");
  assert.equal(cardPhase({ amplification: ready, fields, mode: "auto" }), "count");
  assert.equal(cardPhase({ amplification: ready, fields, mode: "auto", held: true }), "review");
  assert.equal(cardPhase({ amplification: ready, fields, mode: "review" }), "review");
  const edited = { ...fields, checks: [fields.checks[0]] };
  assert.equal(isEdited(ready, edited), true);
  assert.equal(cardPhase({ amplification: ready, fields: edited, mode: "auto" }), "edited");
  assert.equal(isEdited(ready, { ...fields, goal: ` ${fields.goal} ` }), false);
});

test("a question blocks auto-send until answered, and the answer is an edit", () => {
  const asks = { ...ready, status: "needs_input", questions: ["Phone or desktop width?"] };
  const fields = fieldsFrom(asks);
  assert.deepEqual(openQuestions(asks, fields), ["Phone or desktop width?"]);
  assert.equal(cardPhase({ amplification: asks, fields, mode: "auto" }), "ask");
  const answered = { ...fields, answers: ["desktop"] };
  assert.equal(cardPhase({ amplification: asks, fields: answered, mode: "auto" }), "edited");
  assert.match(composeEdit(asks, answered), /Phone or desktop width\? desktop$/);
});

test("an edit sends the selected prompt plus only what Paul changed", () => {
  const fields = { ...fieldsFrom(ready), checks: ["Sidebar is 240 px", ""], assumptions: [] };
  const text = composeEdit(ready, fields);
  assert.ok(text.startsWith(ready.original));  // no agentPrompt on this record: the original words lead
  assert.match(text, /Checks:\n- Sidebar is 240 px$/);
  assert.doesNotMatch(text, /Goal:|Constraints:|Assumptions:/);  // unchanged or emptied parts add nothing
  const withPrompt = { ...ready, agentPrompt: "CL 1.1\nG \"Make the sidebar narrower\"" };
  assert.ok(composeEdit(withPrompt, { ...fieldsFrom(withPrompt), goal: "Make it 232 px" }).startsWith("CL 1.1\nG"));
});

test("send options, receipts and learning lines", () => {
  assert.deepEqual(sendOptions(ready), { amplificationId: "amp-1", amplificationRevision: 1 });
  assert.deepEqual(sendOptions(null), {});
  assert.equal(receiptLine(ready), "script · 140 ms");
  assert.equal(receiptLine({ route: { tier: "gpt-6-luna" }, elapsedMs: 1830, tokens: { total: 412 } }), "gpt-6-luna · 1.8 s · 412 tokens");
  assert.match(learningLine({ state: "pending_gate", lessonIds: [] }), /manuals are unchanged/);
  assert.match(learningLine({ state: "quarantined", lessonIds: ["l1"] }), /\(1 lesson\)/);
  assert.equal(learningLine(null), "");
  assert.doesNotMatch(learningLine({ state: "pending_gate", lessonIds: [] }), /Learned/);
});
