#!/usr/bin/env node
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import * as accounts from "../web/src/neyvia/next/nxAccountsModel.js";
import * as pdf from "../web/src/neyvia/next/nxPdfModel.js";
import { ACCOUNT_CONTRACTS, PDF_CONTRACTS, checkedModelAction, ModelContractError } from "../web/src/neyvia/next/nxModelContracts.js";

const repository = fileURLToPath(new URL("../", import.meta.url));
const modules = { accounts, pdf }, registries = { accounts: ACCOUNT_CONTRACTS, pdf: PDF_CONTRACTS };
const observe = (value, path) => path ? path.split(".").reduce((state, key) => state?.[key], value) : value;

export async function runFrontendModelProofs({ root = resolve(repository, ".agent_control/proofs/frontend-models") } = {}) {
  const started = performance.now(), failures = [], procedures = [], observers = [];
  const manual = JSON.parse(await readFile(resolve(repository, "config/proofs/frontend-models.json"), "utf8"));
  const selected = process.env.NEYVIA_GATE_CONTRACTS ? new Set(JSON.parse(process.env.NEYVIA_GATE_CONTRACTS)) : null;
  await mkdir(root, { recursive: true });
  for (const procedure of manual.procedures) {
    if (selected && !procedure.actions.some(action => selected.has(registries[action.module]?.[action.function]?.id))) continue;
    let calls = 0;
    const observed = new Map();
    try {
      for (const action of procedure.actions) {
        let callArgs = action.args;
        if (action.randomSeed !== undefined) {
          let seed = action.randomSeed;
          callArgs = [limit => (seed = (seed * 17 + 3) % 101) % limit];
        }
        const result = modules[action.module][action.function](...callArgs);
        calls++;
        for (const goal of action.goals || []) {
          const actual = observe(result, goal.path);
          const expected = goal.equalsRef ? observed.get(goal.equalsRef) : goal.value;
          if (goal.match ? !new RegExp(goal.match).test(actual) : JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`Goal ${goal.path || "result"} was not reached`);
        }
        if (action.saveAs) observed.set(action.saveAs, result);
      }
      procedures.push({ id: procedure.id, status: "passed", calls });
    } catch (error) { const failure = { id: procedure.id, status: "failed", calls, error: error.message }; procedures.push(failure); failures.push(failure); }
  }
  for (const [module, registry] of Object.entries(registries)) for (const [name, contract] of Object.entries(registry)) {
    if (selected && !selected.has(contract.id)) continue;
    const witness = manual.procedures.flatMap(row => row.actions).find(row => row.module === module && row.function === name);
    if (!witness) { failures.push({ id: contract.id, error: "Missing startup witness" }); continue; }
    let checkArgs = witness.args, result;
    if (name === "generatePassword") {
      const draws = [], random = limit => {
        const bytes = new Uint32Array(1); globalThis.crypto.getRandomValues(bytes);
        const value = bytes[0] % limit; draws.push({ limit, value }); return value;
      };
      result = accounts.generatePassword(random);
      checkArgs = [random, draws];
    } else result = modules[module][name](...witness.args);
    // A valid-shaped wrong result exercises semantics rather than shape only.
    const corrupt = name === "generatePassword" ? (result[0] === "b" ? "c" : "b") + result.slice(1) : typeof result === "string" ? `${result}\u0000` : typeof result === "number" ? result + 1 : name === "itemRect" ? result.map((value, index) => index === 0 ? value + 1 : value) : result.length ? result.slice(1) : [{ page: 999, rect: [], text: "" }];
    let rejected = false;
    try { checkedModelAction(registry, name, checkArgs, corrupt); } catch (error) { rejected = error instanceof ModelContractError && error.contract === contract.id; }
    observers.push({ id: contract.id, status: rejected ? "passed" : "failed", corrupt_result_rejected: rejected });
    if (!rejected) failures.push({ id: contract.id, error: "Corrupt result escaped contract" });
  }
  const report = { area: manual.area, status: failures.length ? "failed" : "passed", ok: !failures.length, scratchRoot: resolve(root), contractCount: manual.contracts.length, contracts: observers.map(row => ({ id: row.id, status: row.status })), procedures, observers, coverage: manual.coverage, elapsedMs: Math.round((performance.now() - started) * 100) / 100, failures, boundary: "Real account helpers and PDF text/geometry/navigation; authentication and PDF rendering/loading require their own manual" };
  await writeFile(resolve(root, "frontend-models-receipt.json"), JSON.stringify(report, null, 2) + "\n");
  return report;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2), flag = args.indexOf("--root");
  if (flag >= 0 && !args[flag + 1]) throw new Error("--root requires a scratch directory");
  const report = await runFrontendModelProofs({ root: flag >= 0 ? resolve(args[flag + 1]) : undefined });
  console.log(JSON.stringify(report, null, args.includes("--json") ? 0 : 2));
  process.exitCode = report.ok ? 0 : 1;
}
