#!/usr/bin/env node
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { FRONTEND_CONTRACTS, checkedFrontendAction, FrontendContractError, frontendContractBefore, equalContractValue } from "../web/src/neyvia/neyviaFrontendContracts.js";
import { checkProviderRegistry, checkProviderResolution, checkProviderTree, checkProviderSvg } from "../web/src/neyvia/next/nxProviderMarkContracts.js";
import { checkCapabilityAction } from "../web/src/neyvia/neyviaCapabilityContracts.js";
import { checkPresentationAction } from "../web/src/neyvia/neyviaPresentationContracts.js";
const repository = fileURLToPath(new URL("../", import.meta.url));
function storage() { const values = new Map(); return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key) }; }
export async function runProofsEFrontend({ root = resolve(repository, ".agent_control/proofs-e/frontend") } = {}) {
  const started = performance.now(), failures = [], procedures = [], observers = [], manifest = JSON.parse(await readFile(resolve(repository, "config/proofs/proofs-e-frontend.json"), "utf8"));
  const modules = Object.fromEntries(await Promise.all(Object.entries(manifest.modules).map(async ([key, path]) => [key, await import(new URL(`../${path}`, import.meta.url))])));
  const seen = new Map(), stores = new Map();
  for (const procedure of manifest.procedures) {
    let calls = 0;
    const previousStorage = globalThis.localStorage;
    try {
      if (procedure.storageScope) globalThis.localStorage = storage();
      for (const action of procedure.actions) {
        const args = (action.args || []).map(value => value?.$storage ? (stores.has(value.$storage) ? stores.get(value.$storage) : (stores.set(value.$storage, storage()), stores.get(value.$storage))) : value?.$ref ? (value.path ? value.path.split('.').reduce((record,key)=>record?.[key],seen.get(value.$ref)) : seen.get(value.$ref)) : value?.$set ? new Set(value.$set) : value?.$module ? modules[value.$module][value.export] : value);
        const before = frontendContractBefore(action.contract, args);
        let result, thrown;
        try {
          if(action.function === '$setTransparency') { modules[action.module].os.setTransparency(...args); result = { level: modules[action.module].getOs().transparency, key: 'nx.os.transparency', value: localStorage.getItem('nx.os.transparency') }; }
          else if(action.function === '$seedTransparency') { modules[action.module].seedFromSnapshot(...args); result = { level: modules[action.module].getOs().transparency, key: 'nx.os.transparency', value: localStorage.getItem('nx.os.transparency') }; }
          else if(action.function === '$applyTransparency') { modules[action.module].applyUiAction('view.transparency',{level:args[0]}); result = { level: modules[action.module].getOs().transparency, key: 'nx.os.transparency', value: localStorage.getItem('nx.os.transparency') }; }
          else result = await modules[action.module][action.function](...args);
        } catch (error) { thrown = error; }
        calls++;
        if (action.rejects) { if (!thrown || !new RegExp(action.rejects).test(thrown.message)) throw Error("Required rejection was not observed"); continue; }
        if (thrown) throw thrown;
        for (const goal of action.goals || []) {
          const actual = goal.path ? goal.path.split(".").reduce((value, key) => value?.[key], result) : result;
          if (goal.match ? !new RegExp(goal.match).test(String(actual)) : !equalContractValue(actual, goal.value)) throw Error(`Goal ${goal.path || "result"} was not reached`);
        }
        if (action.saveAs) seen.set(action.saveAs, result);
        if (action.contract) {
          const corrupt = action.corrupt ?? (typeof result === "boolean" ? !result : typeof result === "string" ? `${result}\u0000` : Array.isArray(result) ? [...result, "invalid"] : { ...result, invalid: true });
          let rejected = false;
          try {
            if(['transparency.','marketplace.','embed.','starters.','orchestration.'].some(prefix=>action.contract.startsWith(prefix)))checkPresentationAction(action.contract,action.function === '$seedTransparency' ? [args[0].transparency] : args,corrupt,modules.embedded.registeredEmbeddedAdapters());
            else if(action.contract.startsWith('capability.'))checkCapabilityAction(action.contract.slice('capability.'.length),args,corrupt);
            else if(action.contract === 'provider.registry')checkProviderRegistry(corrupt,Object.keys(corrupt));
            else if(action.contract === 'provider.resolution')checkProviderResolution(args[0],corrupt,modules.providerData.PROVIDER_MARKS,{});
            else if(action.contract === 'provider.tree'){const id=modules.providerData.resolveProviderMarkId(args[0]);checkProviderTree(args[0],args[1],corrupt,id?modules.providerData.PROVIDER_MARKS[id]:null);}
            else if(action.contract === 'provider.svg')checkProviderSvg(args[0],args[1],corrupt);
            else checkedFrontendAction(action.contract, args, corrupt, before);
          } catch (error) { rejected = error instanceof FrontendContractError && error.contract === action.contract; }
          const observer = { id: action.contract, status: rejected ? "passed" : "failed", corrupt_result_rejected: rejected }; observers.push(observer);
          if (!rejected) throw Error(`Corrupted semantic result escaped ${action.contract}`);
        }
      }
      procedures.push({ id: procedure.id, status: "passed", calls });
    } catch (error) { const failure = { id: procedure.id, status: "failed", calls, error: error.message }; procedures.push(failure); failures.push(failure); }
    finally { if(procedure.storageScope) globalThis.localStorage = previousStorage; }
  }
  for (const id of manifest.contracts.map(row => row.id)) if (!observers.some(row => row.id === id && row.status === "passed")) failures.push({ id, error: "Missing passing semantic rejection witness" });
  const report = { area: manifest.area, status: failures.length ? "failed" : "passed", ok: !failures.length, contractCount: manifest.contracts.length, contracts: manifest.contracts.map(({ id }) => ({ id, status: observers.some(row => row.id === id && row.status === "passed") ? "passed" : "failed" })), procedures, observers, coverage: manifest.coverage, elapsedMs: Math.round((performance.now() - started) * 100) / 100, failures, boundary: manifest.frontier };
  await mkdir(root, { recursive: true });
  await writeFile(resolve(root, "proofs-e-frontend-receipt.json"), JSON.stringify(report, null, 2) + "\n");
  return report;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2), flag = args.indexOf("--root");
  if (flag >= 0 && !args[flag + 1]) throw Error("--root requires a directory");
  const report = await runProofsEFrontend({ root: flag >= 0 ? resolve(args[flag + 1]) : undefined });
  console.log(JSON.stringify(report, null, args.includes("--json") ? 0 : 2)); process.exitCode = report.ok ? 0 : 1;
}
