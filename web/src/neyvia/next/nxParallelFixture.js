// Development-only design states for the Parallel branches pane (`?fixtures=1&parallel=working|conflict|settled` under
// `vite dev`). Same shape as GET /api/ui/parallel (PARALLEL-contract.md). Nothing here is bundled into a build:
// nxParallelApi imports it only behind `import.meta.env.DEV`.

const now = Date.now();
const iso = minutesAgo => new Date(now - minutesAgo * 60000).toISOString();
const REPO = "D:\\NeyviaRuns\\29-PARALLEL\\repo";
const RUN = "orchard-4f2a";

const lane = (id, title, agent, model, extra) => ({
  id, title, brief: "", agent, model, effort: "low", worktree: `${REPO}\\.neyvia-worktrees\\${RUN}\\${id}`, branch: `parallel/${RUN}/${id}`,
  session: `fx-${id}`, runId: `fx-run-${id}`, liveState: "working", lastActivity: "", pendingRequest: null, error: null, state: "working",
  questions: [], commitsAhead: 0, summary: null, mergeResult: null, ...extra,
});

const labels = extra => lane("labels", "Say Gala, not Apple, in every label", "claude-code", "haiku-5.5", {
  summary: "Labels now read Gala in the crate list, the header and the empty state.", commitsAhead: 1, lastActivity: "Committed: Say Gala in the crate labels",
  questions: [{ id: "q1", question: "Should the crate header say Gala crates or Gala harvest?", answer: "Gala crates. The harvest log is a separate screen.", askedAt: iso(9), answeredAt: iso(8), delivery: null }], ...extra,
});
const crates = extra => lane("crates", "Number crates from 100, not 1", "claude-code", "haiku-5.5", {
  commitsAhead: 1, lastActivity: "Edit src/crates.js: const FIRST_CRATE = 100;", ...extra,
});
const harvest = extra => lane("harvest", "Add the harvest log screen", "codex", "gpt-6.1-sol", {
  commitsAhead: 2, lastActivity: "Waiting for the main agent to answer", ...extra,
});
const main = extra => lane("main", "Main agent", "claude-code", "haiku-5.5", {
  branch: `parallel/${RUN}/main`, worktree: `${REPO}\\.neyvia-worktrees\\${RUN}\\main`, session: "fx-main", lastActivity: "Watching 3 tracks, answering questions", ...extra,
});

const base = extra => ({
  id: RUN, repo: REPO, goal: "Orchard app: Gala labels, crates numbered from 100, and a harvest log", base: "main", baseCommit: "9c41e07a2d",
  integrationBranch: `parallel/${RUN}/main`, integrationWorktree: `${REPO}\\.neyvia-worktrees\\${RUN}\\main`,
  createdAt: iso(14), updatedAt: iso(0.1), state: "working", mergeOrder: ["labels", "crates", "harvest"], conflict: null, checks: null,
  settings: { allowFinish: true, checkCommand: "node check.js", checkTimeoutSeconds: 120 }, finish: null, receipt: null, error: null, logPath: `.agent_control/parallel/${RUN}.jsonl`, ...extra,
});

const SCENES = {
  // Working: one track asked a question and waits; another is mid-edit; one is finished.
  working: () => base({
    state: "working",
    main: main({ state: "working", lastActivity: "Reading harvest's question about the date format" }),
    tracks: [
      labels({ state: "done", liveState: "idle", lastActivity: "Committed: Say Gala in the crate labels" }),
      crates({ state: "working" }),
      harvest({ state: "asking", liveState: "waiting_input", lastActivity: "Waiting for the main agent to answer", questions: [
        { id: "q2", question: "Harvest dates: show 12 Oct 2026 or 2026-10-12?", answer: null, askedAt: iso(0.7), answeredAt: null, delivery: null },
      ] }),
    ],
  }),
  // Conflict: labels merged, crates touches the same line as labels, so the merge stopped and the main agent resolves it.
  conflict: () => base({
    state: "conflict",
    main: main({ state: "working", lastActivity: "Resolving src/crates.js: keeping Gala and the 100 numbering" }),
    conflict: {
      track: "crates", previousTracks: ["labels"], files: ["src/crates.js"],
      summaries: { labels: "Labels now read Gala in the crate list, the header and the empty state.", crates: "Crates are numbered from 100 and show the number in the header." }, sides: {},
    },
    tracks: [
      labels({ state: "merged", liveState: "idle", mergeResult: { status: "merged", commit: "b71e0c4" }, lastActivity: "Merged into the integration branch" }),
      crates({ state: "conflict", liveState: "idle", summary: "Crates are numbered from 100 and show the number in the header.", lastActivity: "Done: numbering starts at 100", mergeResult: { status: "conflict", files: ["src/crates.js"] } }),
      harvest({ state: "done", liveState: "idle", summary: "Harvest log screen added, dates shown as 12 Oct 2026.", lastActivity: "Committed: Add the harvest log screen",
        questions: [{ id: "q2", question: "Harvest dates: show 12 Oct 2026 or 2026-10-12?", answer: "12 Oct 2026, like the rest of the app.", askedAt: iso(6), answeredAt: iso(5), delivery: null }] }),
    ],
  }),
  // Settled: everything merged, checks passed, finished into main, worktrees removed.
  settled: () => base({
    state: "settled", updatedAt: iso(0.2),
    main: main({ state: "settled", liveState: "idle", lastActivity: "Finished into main", worktree: "" }),
    checks: { passed: true, command: "node check.js", exitCode: 0, output: "ok: 3 files, 7 checks" },
    finish: { into: "main", commit: "e08a3d19" },
    receipt: { removed: ["labels", "crates", "harvest", "main"], deletedBranches: [`parallel/${RUN}/labels`, `parallel/${RUN}/crates`, `parallel/${RUN}/harvest`], keptBranches: [] },
    tracks: [
      labels({ state: "settled", liveState: null, mergeResult: { status: "merged", commit: "b71e0c4" }, lastActivity: "Settled: worktree removed", worktree: "" }),
      crates({ state: "settled", liveState: null, mergeResult: { status: "merged", commit: "5d3f9a8" }, summary: "Crates are numbered from 100 and show the number in the header.", lastActivity: "Settled: worktree removed", worktree: "" }),
      harvest({ state: "settled", liveState: null, mergeResult: { status: "merged", commit: "c92a6e1" }, summary: "Harvest log screen added, dates shown as 12 Oct 2026.", lastActivity: "Settled: worktree removed", worktree: "",
        questions: [{ id: "q2", question: "Harvest dates: show 12 Oct 2026 or 2026-10-12?", answer: "12 Oct 2026, like the rest of the app.", askedAt: iso(12), answeredAt: iso(11), delivery: null }] }),
    ],
  }),
};

const wanted = () => {
  const name = new URLSearchParams(globalThis.location?.search || "").get("parallel");
  return name in SCENES ? name : "working";
};
let runs = null;
const current = () => (runs ||= [SCENES[wanted()]()]);

const track = (run, id) => run.tracks.find(row => row.id === id);

/** GET /api/ui/parallel */
export function fixtureParallelRead() {
  return { ok: true, runs: structuredClone(current()) };
}

/** POST /api/ui/parallel: the same transitions the backend makes, enough to try every button. */
export function fixtureParallelAction(body) {
  const run = current().find(row => row.id === body.run) || current()[0];
  const fail = message => Object.assign(new Error(message), { status: 409 });
  switch (body.operation) {
    case "answer": {
      const lane = track(run, body.track);
      const open = lane?.questions.find(row => row.answer == null);
      if (open) { open.answer = body.answer; open.answeredAt = new Date().toISOString(); lane.state = "working"; lane.liveState = "working"; }
      break;
    }
    case "merge":
      for (const lane of run.tracks) if (lane.state === "done") { lane.state = "merged"; lane.mergeResult = { status: "merged", commit: "a1b2c3d" }; }
      if (run.tracks.every(lane => lane.state === "merged")) { run.state = "ready"; run.checks = { passed: true, command: "node check.js", exitCode: 0, output: "ok" }; }
      break;
    case "finish":
      if (run.state !== "ready") throw fail("The run is not ready to finish.");
      run.state = "finished"; run.finish = { into: body.into || run.base, commit: "e08a3d19" };
      break;
    case "settle":
      if (!["ready", "finished", "stopped", "failed", "checks_failed"].includes(run.state)) throw fail("Stop or finish the run before settling it.");
      run.state = "settled";
      for (const lane of run.tracks) lane.state = lane.mergeResult?.status === "merged" ? "settled" : lane.state;
      run.receipt = { removed: [...run.tracks.map(lane => lane.id), "main"], deletedBranches: run.tracks.filter(lane => lane.mergeResult?.status === "merged").map(lane => lane.branch), keptBranches: [] };
      return { ok: true, run: structuredClone(run), receipt: run.receipt };
    case "stop":
      run.state = "stopped";
      for (const lane of [run.main, ...run.tracks]) lane.liveState = "idle";
      break;
    default:
      throw fail(`${body.operation} is not in the design fixtures`);
  }
  run.updatedAt = new Date().toISOString();
  return { ok: true, run: structuredClone(run) };
}
