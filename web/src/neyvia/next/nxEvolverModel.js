// Evolver (Lab > Hill climbing): pure helpers that turn the backend's frozen
// state (neyvia.evolver.state) into what the screen says. No data is invented
// here: every number shown comes from a receipt, a panel or the Pareto front.

const FAMILY_INFO = {
  manual_compression: {
    name: "Notes manual",
    goal: "Shorten the Notes manual without losing task success.",
    success: "Task success",
    fitness: "Notes task success per instruction token",
  },
  cl_skill: {
    name: "Design CL-Skill",
    goal: "Shorten the design CL-Skill without losing build quality.",
    success: "Adherence × quality",
    fitness: "CL adherence × build quality per instruction token",
  },
};

/** "cl_skill_v3" -> { family: "cl_skill", version: 3 }; an id without a suffix is version 1. */
export function splitDomain(id) {
  const match = /^(.*)_v(\d+)$/.exec(String(id || ""));
  return match ? { family: match[1], version: Number(match[2]) } : { family: String(id || ""), version: 1 };
}

const titleCase = text => text.replace(/_/g, " ").replace(/^./, letter => letter.toUpperCase());

export function familyInfo(family) {
  return FAMILY_INFO[family] || { name: titleCase(family), goal: "", success: "Success", fitness: "Fitness" };
}

/**
 * Group domains into families (one per thing being improved), versions oldest
 * first. The newest version is the current one; older ones stay as history and
 * their scores are never mixed with the current one.
 */
export function groupFamilies(domains = []) {
  const families = new Map();
  for (const domain of domains) {
    const { family, version } = splitDomain(domain.id);
    if (!families.has(family)) families.set(family, { id: family, ...familyInfo(family), versions: [] });
    families.get(family).versions.push({ ...domain, version });
  }
  return [...families.values()].map(entry => {
    const versions = entry.versions.sort((a, b) => a.version - b.version);
    return {
      ...entry,
      versions,
      current: versions[versions.length - 1],
      totalTrials: versions.reduce((sum, row) => sum + (Number(row.trials) || 0), 0),
    };
  });
}

export const shortHash = hash => (hash ? String(hash).slice(0, 8) : "");

/** Where a run budget stands: how many trials are left and why a run can't start. */
export function runBudget(domain, current = domain) {
  const max = Number(domain?.budget?.max_trials) || 0;
  const used = Number(domain?.trials) || 0;
  const left = Math.max(0, max - used);
  let blocked = "";
  if (domain && domain.frozen_lock && domain.frozen_lock.ok === false) blocked = "The locked checks changed. This needs review before any new trial.";
  else if (domain?.active_trial) blocked = "A trial is already running in this version.";
  else if (current && domain && current.id !== domain.id) blocked = `Trials run only on the current version (v${current.version ?? ""}). This one is kept as history.`;
  else if (!left) blocked = `No trials left: this version used ${used} of ${max}. A bigger budget needs a reviewed new version.`;
  return { max, used, left, blocked, options: Array.from({ length: Math.min(2, left) }, (_, index) => index + 1) };
}

// ---- Objectives and statistics ---------------------------------------------

export function objectiveLabel(name, family) {
  if (name === "tokens") return "Instruction tokens";
  if (name === "success") return familyInfo(family).success;
  if (name === "fitness") return "Fitness";
  return titleCase(name);
}

export const objectiveOrder = objectives => Object.keys(objectives || {}).sort((a, b) => ["success", "tokens", "fitness"].indexOf(a) - ["success", "tokens", "fitness"].indexOf(b));

/** A measured value in the unit people read it in. Fitness is success per 1k instruction tokens. */
export function formatValue(name, value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "–";
  if (name === "tokens") return Math.round(number).toLocaleString("en-US");
  if (name === "success") return `${Math.round(number * 1000) / 10}%`;
  if (name === "fitness") return (number * 1000).toFixed(2);
  return String(Math.round(number * 1000) / 1000);
}

/** Gains come from the backend already oriented: positive is better for both max and min objectives. */
export function formatGain(name, value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "–";
  const sign = number > 0 ? "+" : number < 0 ? "−" : "";
  const size = Math.abs(number);
  if (name === "tokens") return number === 0 ? "0" : `${Math.round(size).toLocaleString("en-US")} ${number > 0 ? "fewer" : "more"}`;
  if (name === "success") return `${sign}${Math.round(size * 1000) / 10} pts`;
  if (name === "fitness") return `${sign}${(size * 1000).toFixed(2)}`;
  return `${sign}${Math.round(size * 1000) / 1000}`;
}

/** Relative change of a mean, oriented so a smaller token count reads as a negative percent. */
export function percentChange(before, after) {
  const a = Number(before);
  const b = Number(after);
  if (!Number.isFinite(a) || !Number.isFinite(b) || a === 0) return "";
  const change = ((b - a) / Math.abs(a)) * 100;
  if (Math.abs(change) < 0.05) return "same";
  return `${change > 0 ? "+" : change < 0 ? "−" : ""}${Math.abs(change).toFixed(1)}%`;
}

/** Verdict on one objective at one stage. */
export function objectiveVerdict(stat) {
  if (!stat) return { tone: "idle", word: "Not measured" };
  if (stat.noninferior === false) return { tone: "red", word: "Could be worse" };
  if (stat.improved) return { tone: "green", word: "Better" };
  return { tone: "idle", word: "No worse" };
}

// ---- Stages, trials and the gate --------------------------------------------

export function stageLabel(stage) {
  if (!stage) return "";
  if (stage.role === "discovery") return "Discovery tasks";
  if (stage.purpose === "fresh_reconfirmation") return "Fresh confirmation";
  return "Held-out tasks";
}

export const TRIAL_STATES = {
  accepted: { tone: "green", word: "Accepted" },
  rejected: { tone: "red", word: "Rejected" },
  blocked: { tone: "idle", word: "Blocked" },
  running: { tone: "live", word: "Running" },
};
export const trialState = state => TRIAL_STATES[state] || { tone: "idle", word: titleCase(String(state || "Unknown")) };

/** Keep an error readable: the raw-receipt path goes to the detail, not the sentence. */
export function splitError(error) {
  const text = String(error || "").trim();
  const [head, ...rest] = text.split(/;\s*raw receipt\s*/i);
  return { message: head.replace(/\.$/, ""), detail: rest.join(" ").trim() };
}

const listWords = words => (words.length < 2 ? words.join("") : `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`);

/**
 * Why the frozen gate promoted or rejected a candidate, in one or two plain
 * sentences. Promotion needs discovery, held-out and fresh confirmation, no
 * hard-check failure, every objective no worse within its frozen tolerance,
 * and at least one objective better beyond noise.
 */
export function explainTrial(receipt, objectives = {}, family = "") {
  if (!receipt) return { tone: "idle", headline: "", reasons: [] };
  const label = name => objectiveLabel(name, family).toLowerCase();
  if (receipt.state === "blocked") {
    const { message } = splitError(receipt.error);
    return { tone: "idle", headline: "Blocked before a verdict. The current version stays.", reasons: [message || "The trial stopped before every check could run."] };
  }
  const stages = receipt.stages || [];
  if (receipt.state === "accepted" || receipt.promoted) {
    const last = stages[stages.length - 1];
    const better = objectiveOrder(last?.statistics).filter(name => last.statistics[name].improved).map(label);
    return {
      tone: "green",
      headline: "Accepted. It became the current version of this workspace.",
      reasons: [
        `Passed ${listWords(stages.map(stage => stageLabel(stage).toLowerCase()))}.`,
        better.length ? `${listWords(better).replace(/^./, letter => letter.toUpperCase())} improved beyond noise, and nothing got worse.` : "Nothing got worse.",
      ],
    };
  }
  const reasons = [];
  const failed = stages.find(stage => !stage.eligible) || null;
  if (failed) {
    const where = stageLabel(failed).toLowerCase();
    if (failed.hard_gates_passed === false) reasons.push(`A hard check failed on the ${where}.`);
    for (const name of objectiveOrder(failed.statistics)) {
      const stat = failed.statistics[name];
      const tolerance = Number(objectives?.[name]?.tolerance) || 0;
      if (stat.noninferior === false) {
        reasons.push(`${objectiveLabel(name, family)} could be worse on the ${where}: the lower confidence bound of its gain is ${formatGain(name, stat.lower_confidence_gain)}, below the allowed ${formatGain(name, -tolerance)}.`);
      }
    }
    if (reasons.length === 0) reasons.push(`Nothing improved beyond noise on the ${where}.`);
  } else if (stages.length < 3) {
    reasons.push("It stopped before fresh confirmation.");
  }
  return { tone: "red", headline: "Rejected by the locked checks. The current version stays.", reasons };
}

/** The three gate steps of a trial, with how far it got (for the step strip). */
export function gateSteps(receipt) {
  const stages = receipt?.stages || [];
  const steps = [
    { key: "discovery", label: "Discovery tasks", stage: stages.find(stage => stage.role === "discovery") },
    { key: "held_out", label: "Held-out tasks", stage: stages.find(stage => stage.role !== "discovery" && stage.purpose !== "fresh_reconfirmation") },
    { key: "fresh", label: "Fresh confirmation", stage: stages.find(stage => stage.purpose === "fresh_reconfirmation") },
  ];
  let stopped = false;
  return steps.map(step => {
    const state = stopped ? "skipped" : !step.stage ? (receipt?.state === "blocked" ? "blocked" : "skipped") : step.stage.eligible ? "passed" : "failed";
    if (state !== "passed") stopped = true;
    return { ...step, state };
  });
}

/** The headline before/after numbers: the last stage the candidate reached. */
export function headlineStats(receipt) {
  const stages = receipt?.stages || [];
  const last = stages[stages.length - 1];
  return last ? { stage: last, statistics: last.statistics || {} } : null;
}

/** The latest trial that reached a verdict (accepted or rejected); else the latest one. */
export function latestDecisive(receipts = []) {
  const ordered = [...receipts].sort((a, b) => (b.trial_number || 0) - (a.trial_number || 0));
  return ordered.find(row => row.state === "accepted" || row.state === "rejected") || ordered[0] || null;
}

// ---- Panels and the Pareto front -------------------------------------------

/** Each task panel, its role, and which trial and step used it. */
export function panelRows(domain) {
  const used = new Set(domain?.held_out_used || []);
  const usage = new Map();
  for (const receipt of domain?.receipts || []) {
    for (const stage of receipt.stages || []) {
      if (!usage.has(stage.panel)) usage.set(stage.panel, []);
      usage.get(stage.panel).push({ trial: receipt.trial_number, label: stageLabel(stage) });
    }
  }
  return (domain?.panels || []).map(panel => ({
    ...panel,
    used: used.has(panel.id) || usage.has(panel.id),
    usedBy: usage.get(panel.id) || [],
    short: String(panel.id).replace(/^.*panel-/, "Panel "),
  }));
}

/** Front points with who they are (current version, candidate) and the trial that measured them. */
export function frontPoints(domain) {
  const byTrial = new Map((domain?.receipts || []).map(receipt => [receipt.id, receipt]));
  return (domain?.pareto_front || []).map(point => {
    const receipt = byTrial.get(point.trial);
    const isCurrent = point.genome === domain.incumbent;
    return {
      ...point,
      isCurrent,
      role: isCurrent ? "Current version" : "Candidate",
      trialNumber: receipt?.trial_number || null,
      trialState: receipt?.state || "",
    };
  });
}

// ---- Lineage ---------------------------------------------------------------

const OPERATORS = { seed: "Original", "luna-wording-structure": "Luna rewrite", "discovery-qualified-transport-transfer": "Carried over from the earlier version" };
export const operatorLabel = operator => OPERATORS[operator] || titleCase(String(operator || "change").replace(/-/g, " "));

/** Lineage rows as a tree (roots first), each node carrying its trials and markers. */
export function lineageTree(domain) {
  const rows = domain?.lineage || [];
  const trials = new Map();
  for (const receipt of domain?.receipts || []) {
    if (!trials.has(receipt.candidate)) trials.set(receipt.candidate, []);
    trials.get(receipt.candidate).push(receipt);
  }
  const front = new Set((domain?.pareto_front || []).map(point => point.genome));
  const known = new Set(rows.map(row => row.genome));
  const nodes = new Map(rows.map(row => [row.genome, {
    ...row,
    children: [],
    trials: (trials.get(row.genome) || []).sort((a, b) => a.trial_number - b.trial_number),
    isCurrent: row.genome === domain.incumbent,
    onFront: front.has(row.genome),
  }]));
  const roots = [];
  for (const node of nodes.values()) {
    if (node.parent && known.has(node.parent)) nodes.get(node.parent).children.push(node);
    else roots.push(node);
  }
  const byTime = (a, b) => (a.created || 0) - (b.created || 0);
  for (const node of nodes.values()) node.children.sort(byTime);
  return roots.sort(byTime);
}

/** What produced a candidate: model, time and token usage when the proposal recorded them. */
export function proposalFacts(provenance) {
  const proposal = provenance?.proposal;
  if (!proposal) return provenance?.source ? [titleCase(provenance.source)] : [];
  const facts = [];
  if (proposal.model) facts.push(proposal.model);
  if (Number.isFinite(proposal.seconds)) facts.push(`${Math.round(proposal.seconds)}s`);
  const usage = proposal.usage;
  if (usage && Number.isFinite(usage.input_tokens)) facts.push(`${Math.round(usage.input_tokens / 100) / 10}k in · ${Math.round((usage.output_tokens || 0) / 100) / 10}k out`);
  return facts;
}

// ---- Genome diff -----------------------------------------------------------

/**
 * Line diff (longest common subsequence) between two instruction texts, with
 * long unchanged runs folded. Returns rows {type: same|add|del|fold, text|count}.
 */
export function diffLines(before, after, context = 2) {
  const a = String(before ?? "").split("\n");
  const b = String(after ?? "").split("\n");
  const n = a.length;
  const m = b.length;
  const table = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
  }
  const rows = [];
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { rows.push({ type: "same", text: a[i] }); i += 1; j += 1; }
    else if (i < n && (j >= m || table[i + 1][j] >= table[i][j + 1])) { rows.push({ type: "del", text: a[i] }); i += 1; }
    else { rows.push({ type: "add", text: b[j] }); j += 1; }
  }
  const added = rows.filter(row => row.type === "add").length;
  const removed = rows.filter(row => row.type === "del").length;
  const folded = [];
  for (let index = 0; index < rows.length;) {
    if (rows[index].type !== "same") { folded.push(rows[index]); index += 1; continue; }
    let end = index;
    while (end < rows.length && rows[end].type === "same") end += 1;
    const run = rows.slice(index, end);
    const keepHead = index === 0 ? 0 : context;
    const keepTail = end === rows.length ? 0 : context;
    if (run.length > keepHead + keepTail + 1) {
      folded.push(...run.slice(0, keepHead), { type: "fold", count: run.length - keepHead - keepTail }, ...run.slice(run.length - keepTail));
    } else folded.push(...run);
    index = end;
  }
  return { rows: folded, added, removed };
}

// ---- Jobs ------------------------------------------------------------------

export const JOB_STATES = {
  queued: { tone: "live", word: "Waiting to start", pulse: true },
  running: { tone: "live", word: "Running", pulse: true },
  completed: { tone: "green", word: "Finished" },
  failed: { tone: "red", word: "Stopped with an error" },
};
export const jobState = state => JOB_STATES[state] || { tone: "idle", word: titleCase(String(state || "Unknown")) };
export const jobActive = job => job && (job.state === "queued" || job.state === "running");

/** Trial outcomes a finished job recorded, kept apart from whether the job itself finished. */
export function jobOutcomes(job) {
  const domains = job?.result?.domains || {};
  return Object.entries(domains).flatMap(([domain, row]) => (row?.trials || []).map(trial => ({
    domain,
    trial: trial.trial_number ?? trial.trial ?? null,
    state: trial.state,
  })));
}

/** Seconds since the epoch (the backend's clock) as a short duration. */
export function seconds(value) {
  const number = Math.max(0, Math.round(Number(value) || 0));
  if (number < 60) return `${number}s`;
  const minutes = Math.floor(number / 60);
  return minutes < 60 ? `${minutes}m ${number % 60}s` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function when(epochSeconds) {
  const number = Number(epochSeconds);
  if (!Number.isFinite(number) || !number) return "";
  return new Date(number * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
