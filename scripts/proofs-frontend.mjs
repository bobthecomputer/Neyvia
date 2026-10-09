#!/usr/bin/env node
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";
import * as editor from "../web/src/neyvia/next/nxDictationEdit.js";
import { wordsShown } from "../web/src/neyvia/next/nxDictationReveal.js";
import { providerChoices } from "../web/src/neyvia/next/nxDictationProviders.js";
import { DICTATION_CONTRACTS, checkedDictationAction, DictationContractError } from "../web/src/neyvia/next/nxDictationContracts.js";

const repository = fileURLToPath(new URL("../", import.meta.url));
// Public functions guarded by DICTATION_CONTRACTS: the editor model plus the reveal pacer and provider list.
const guarded = { ...editor, wordsShown, providerChoices };
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);
const observe = (value, path) => path ? path.split(".").reduce((state, key) => state?.[key], value) : value;

/** Run manual observers and goal procedures in an isolated, persisted scratch root.
 * No ASR, network, model, DOM, test framework, or mocked backend is involved: this
 * manual's state is the text/caret/actions model used by the real composer.
 */
export async function runFrontendProofs({ root = resolve(repository, ".agent_control/proofs/frontend") } = {}) {
  const started = performance.now();
  const manual = JSON.parse(await readFile(resolve(repository, "config/proofs/frontend.json"), "utf8"));
  await mkdir(root, { recursive: true });
  const procedures = [], failures = [], seen = new Set();
  for (const procedure of manual.procedures) {
    let calls = 0;
    try {
      for (const action of procedure.actions) {
        const result = guarded[action.function](...action.args);
        seen.add(DICTATION_CONTRACTS[action.function].id);
        calls++;
        for (const goal of action.goals || []) {
          if (!same(observe(result, goal.path), goal.value)) throw new Error(`Goal ${goal.path || "result"} was not reached`);
        }
      }
      procedures.push({ id: procedure.id, status: "passed", calls });
    } catch (error) {
      const failure = { id: procedure.id, status: "failed", calls, error: error.message };
      procedures.push(failure); failures.push(failure);
    }
  }
  // Exercise the failure boundary directly: a corrupted result must be rejected
  // before the UI can observe it. This is each contract's own checker, not a mock.
  const observers = [];
  for (const [name, contract] of Object.entries(DICTATION_CONTRACTS)) {
    const witness = manual.procedures.flatMap(row => row.actions).find(row => row.function === name);
    if (!witness) { failures.push({ id: contract.id, error: "Missing startup witness" }); continue; }
    const result = guarded[name](...witness.args);
    const field = result && typeof result === "object" ? ("value" in result ? "value" : "stable" in result ? "stable" : "before") : null;
    const corrupt = typeof result === "string" ? `${result}\u0000` : typeof result === "number" ? result + 1 : typeof result === "boolean" ? !result : Array.isArray(result) ? [...result, "corrupt"] : { ...result, [field]: `${result[field]}\u0000` };
    let rejected = false;
    try { checkedDictationAction(name, witness.args, corrupt); } catch (error) { rejected = error instanceof DictationContractError && error.contract === contract.id; }
    observers.push({ id: contract.id, status: rejected ? "passed" : "failed", corrupt_result_rejected: rejected });
    if (!rejected) failures.push({ id: contract.id, error: "Corrupt result escaped contract" });
  }
  const report = { area: "frontend", status: failures.length ? "failed" : "passed", ok: failures.length === 0, scratchRoot: resolve(root), contractCount: Object.keys(DICTATION_CONTRACTS).length, contracts: Object.values(DICTATION_CONTRACTS).map(row => ({ id: row.id, status: seen.has(row.id) ? "passed" : "unobserved" })), procedures, observers, coverage: manual.coverage, elapsedMs: Math.round((performance.now() - started) * 100) / 100, failures, boundary: "Actual composer text model; microphone/ASR and rendered browser are outside this manual" };
  await writeFile(resolve(root, "frontend-receipt.json"), JSON.stringify(report, null, 2) + "\n");
  return report;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2), rootFlag = args.indexOf("--root");
  if (rootFlag >= 0 && !args[rootFlag + 1]) throw new Error("--root requires a scratch directory");
  const report = await runFrontendProofs({ root: rootFlag >= 0 ? resolve(args[rootFlag + 1]) : undefined });
  console.log(JSON.stringify(report, null, args.includes("--json") ? 0 : 2));
  process.exitCode = report.ok ? 0 : 1;
}
