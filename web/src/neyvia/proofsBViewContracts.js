// The view consumed by JSX is checked on every real HarnessesSurface render.
// No DOM observers, browser globals, provider substitutions or diagnostics bus.
const TERMINAL = new Set(["completed", "failed", "cancelled", "interrupted"]);
const ATTENTION = new Set(["blocked", "failed", "interrupted"]);
const CLEANUP = new Set(["queued", "running", "cancelling", "blocked"]);
const RETRY = new Set(["completed", "failed", "cancelled", "interrupted", "blocked"]);

function require(condition, contract) {
  if (!condition) throw new Error(`Contract ${contract}: Harness view contradicts its durable job`);
}

function checkLabel(job, label) {
  const expected = job?.waitingReason === "execution-capacity"
    ? "waiting for capacity"
    : job?.status === "blocked" ? "needs attention" : String(job?.status || "unknown").replaceAll("-", " ");
  require(label === expected, "proofs-b.browser.capacity-label");
}

export function checkHarnessView(view) {
  const job = view.job;
  for (const row of view.rows) checkLabel(row.job, row.label);
  if (job) {
    checkLabel(job, view.label);
    require(view.terminal === TERMINAL.has(job.status)
      && view.attention === ATTENTION.has(job.status)
      && view.cleanup === CLEANUP.has(job.status)
      && view.retry === RETRY.has(job.status), "proofs-b.browser.blocked-receipt");
    if ((job.status === "blocked" || job.cancelOutcome === "blocked-cleanup") && job.result) {
      require(view.output === JSON.stringify(job.result, null, 2), "proofs-b.browser.blocked-receipt");
    }
    if (job.waitingReason === "execution-capacity" && !job.result && !job.error) {
      require(view.output.includes("Provider/model execution is waiting for a workspace capacity slot")
        && view.output.includes("no execution slot is claimed yet"), "proofs-b.browser.capacity-explanation");
    }
  } else {
    require(!view.terminal && !view.attention && !view.cleanup && !view.retry, "proofs-b.browser.blocked-receipt");
  }
  return view;
}
