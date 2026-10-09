// Plain-language reading of one connection card (pure, so the wording is checkable).

const STEP = {
  start: "Starting a tiny chat",
  "tool call": "Reading a file with its tool",
  answer: "Checking the answer",
  compact: "Compacting the chat",
  "after compaction": "Asking again after compaction",
  error: "Test stopped",
};
export function describeStep(step) { return STEP[step] || "Working"; }

/** The receipt only counts for a card that is still connected. */
export function mergeProof(card) {
  return card?.state === "connected" && card.proof ? card.proof : null;
}

export function connectionTone(card, proving, waiting) {
  if (proving || waiting || card.state === "checking" || card.state === "installing") return "live";
  if (card.state === "connected") return "green";
  if (card.state === "needs-signin") return "gold";
  if (card.state === "broken") return "red";
  return "idle";
}

const STATE_WORD = { checking: "Checking", installing: "Installing…", connected: "Signed in", "needs-signin": "Not signed in", "not-installed": "Not installed", broken: "Needs attention" };

function failureReason(proof) {
  const bad = (proof.steps || []).find(step => !step.ok);
  return bad ? `The test stopped at "${describeStep(bad.step).toLowerCase()}": ${bad.detail}` : "The last test did not pass.";
}

export function connectionHeadline(card, proof, waiting, proving) {
  if (proving) return { state: "Testing", why: "Running one tiny chat that has to use a tool. This takes under a minute." };
  if (waiting) return { state: "Waiting for you", why: card.fix?.kind === "provider" ? "Finish on the provider's own sign-in page. This card updates automatically." : "Finish signing in in the terminal window that opened. This card turns green by itself." };
  if (card.state === "checking") return { state: "Checking", why: "Looking at this one…" };
  if (card.state === "connected") {
    const word = card.kind === "keys" || card.kind === "local" || card.id === "gptme" ? "Ready" : STATE_WORD.connected;
    if (proof?.ok) return { state: `${word}, tested`, why: `${card.why} It answered a real test chat using a tool.` };
    if (proof && !proof.ok) return { state: `${word}, test failed`, why: failureReason(proof) };
    return { state: word, why: card.provable ? `${card.why} Not tested yet.` : card.why };
  }
  return { state: STATE_WORD[card.state] || "Unknown", why: card.why };
}
