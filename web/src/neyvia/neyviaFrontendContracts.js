import { CHAT_CONTRACTS } from "./neyviaChatContracts.js";
// Executable feature-manual claims. Errors identify claims, never user inputs.
export class FrontendContractError extends Error {
  constructor(id) { super(`Frontend contract ${id} failed`); this.name = "FrontendContractError"; this.contract = id; }
}
export const equalContractValue = (a, b) => {
  if (Object.is(a, b)) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object") return false;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(key => Object.hasOwn(b, key) && equalContractValue(a[key], b[key]));
};
const eq = equalContractValue, text = value => String(value || "").trim();
const permissionModes = ["read-only", "workspace", "full-access"];
function permission(value, fallback = "read-only") {
  const normalized = text(value).toLowerCase();
  return permissionModes.includes(normalized) ? normalized : ({ readonly: "read-only", read_only: "read-only", "workspace-tools": "workspace", workspace_tools: "workspace", full: "full-access", full_access: "full-access" })[normalized] || (value === true ? "workspace" : permissionModes.includes(fallback) ? fallback : "read-only");
}
const storageKey = "fluxio.chat.workspacePermissionModes";
function savedPermissions(storage) {
  try { const value = JSON.parse(storage?.getItem(storageKey) || "{}"); return value && !Array.isArray(value) && typeof value === "object" ? Object.fromEntries(Object.entries(value).filter(([key]) => key).map(([key, mode]) => [key, permission(mode)])) : {}; } catch { return {}; }
}
export function frontendContractBefore(id, args) {
  return ["permission.write", "permission.transfer"].includes(id) ? savedPermissions(args[0]) : undefined;
}
function transferEligible(previous, next, saved) {
  try {
    const a = JSON.parse(previous), b = JSON.parse(next);
    return previous !== next && Array.isArray(a) && Array.isArray(b) && a.length === 3 && b.length === 3 && a[0] === b[0] && a[1] === b[1] && ["new-chat", "mission-draft"].includes(a[2]) && b[2] && !["new-chat", "mission-draft"].includes(b[2]) && Object.hasOwn(saved, previous) && !Object.hasOwn(saved, next);
  } catch { return false; }
}
function batchExpected(value) {
  const lines = String(value || "").split(/\r?\n/).filter(line => line.trim());
  if (!lines.length || lines.length > 100) return null;
  try { return lines.map(line => { if (!line.trimStart().startsWith("{")) return line.trim(); const row = JSON.parse(line); if (typeof row.prompt !== "string" || !row.prompt.trim() || Object.keys(row).some(key => key !== "prompt")) throw Error(); return row.prompt; }); } catch { return null; }
}
function meshNumeric(value, fallback, render) {
  return value === null || value === undefined || value === "" || !Number.isFinite(Number(value)) ? fallback : render(Number(value));
}
const claim = (id, check) => ({ id, check });
export const FRONTEND_CONTRACTS = Object.freeze({
  "chat.cancelled": claim("chat.cancelled", ([current = {}, fallback = ""], result) => {
    const original = text(current.title);
    return eq(result, { title: ["", "thinking...", "working..."].includes(original.toLowerCase()) ? String(fallback || "Stopped by you.") : original, detail: "Stopped by you.", pending: false, tone: "neutral", source: "chat-cancelled" });
  }),
  "chat.cancellation-result": claim("chat.cancellation-result", ([result], actual) => actual === (text(result?.status || result?.compartment?.state).toLowerCase() === "cancelled" || result?.cancelled === true)),
  "chat.runtime-source": claim("chat.runtime-source", ([source], result) => result === ["backend-model-message", "backend-runtime-reply", "runtime-stream", "runtime-compartment", "runtime_compartment"].includes(String(source ?? "").trim().toLowerCase())),
  "chat.stopped-visibility": claim("chat.stopped-visibility", ([turn, classifiers = {}], result) => !["chat-cancelled", "chat-interrupted"].includes(turn?.source) || turn.pending || !["assistant", "user", "operator"].includes(turn.role) || Object.keys(classifiers).length || !text(turn.title) ? true : result === null),
  "chat.stopped-body": claim("chat.stopped-body", ([turn], result) => !["chat-cancelled", "chat-interrupted"].includes(turn?.source) || !turn.title ? true : result === turn.title),
  "permission.normalize": claim("permission.normalize", ([value, fallback], result) => result === permission(value, fallback)),
  "permission.tools": claim("permission.tools", ([value], result) => result === (permission(value) !== "read-only")),
  "permission.runtime": claim("permission.runtime", ([value], result) => result === ["neyvia-agent", "neyvia", "own", "codex", "claude-code", "hermes"].includes(text(value).toLowerCase())),
  "permission.scope": claim("permission.scope", ([workspace, path, chat], result) => result === JSON.stringify([workspace, path, chat].map(text))),
  "permission.grant": claim("permission.grant", ([grant, scope, fallback = "full-access"], result) => result === (grant?.scope === scope ? permission(grant?.permissionMode, fallback) : permission(fallback, "full-access"))),
  "permission.read": claim("permission.read", ([storage], result) => eq(result, savedPermissions(storage))),
  "permission.write": claim("permission.write", ([storage, scope, mode], result, before) => typeof result === "boolean" && (result ? (typeof scope === "string" && scope && eq(savedPermissions(storage), { ...before, [scope]: permission(mode, "full-access") })) : eq(savedPermissions(storage), before))),
  "permission.get": claim("permission.get", ([storage, scope, fallback = "full-access"], result) => result === (Object.hasOwn(savedPermissions(storage), scope) ? savedPermissions(storage)[scope] : permission(fallback, "full-access"))),
  "permission.transfer": claim("permission.transfer", ([storage, previous, next], result, before) => typeof result === "boolean" && (!result ? eq(before, savedPermissions(storage)) : Boolean(transferEligible(previous, next, before)) && eq(savedPermissions(storage), { ...before, [next]: before[previous] }))),
  "mesh.value": claim("mesh.value", ([value, unavailable = "Unavailable"], result) => result === (value == null || typeof value === "string" && !value.trim() ? unavailable : String(value))),
  "mesh.boolean": claim("mesh.boolean", ([value, options = {}], result) => result === (value === true ? options.trueLabel ?? "Enabled" : value === false ? options.falseLabel ?? "Disabled" : options.unavailableLabel ?? "Unavailable")),
  "mesh.count": claim("mesh.count", ([value, unavailable = "Unavailable"], result) => result === meshNumeric(value, unavailable, String)),
  "mesh.duration": claim("mesh.duration", ([value], result) => result === meshNumeric(value, "Unavailable", number => `${number} ms`)),
  "mesh.bytes": claim("mesh.bytes", ([value], result) => result === meshNumeric(value, "Unavailable", number => number < 0 ? "Unavailable" : number < 1024 ? `${number} B` : number < 1048576 ? `${(number / 1024).toFixed(1)} KiB` : `${(number / 1048576).toFixed(2)} MiB`)),
  "mesh.hash": claim("mesh.hash", ([value], result) => { const original = value == null || typeof value === "string" && !value.trim() ? "Unavailable" : String(value); return result === (original.length <= 16 ? original : `${original.slice(0, 8)}…${original.slice(-6)}`); }),
  "mesh.snapshot": claim("mesh.snapshot", ([value], result) => result === Boolean(value && typeof value === "object" && Object.values(value).some(item => item != null))),
  "batch.prompts": claim("batch.prompts", ([value], result) => batchExpected(value) !== null && eq(result, batchExpected(value))),
  "workflow.availability": claim("workflow.availability", ([{ route = {}, selectedRuntime = "", evidence = {}, tools = [], workspacePath = "" } = {}], result) => {
    const runtime = evidence?.runtimeStatus?.[selectedRuntime || route.runtimeId || route.runtime], ready = runtime?.available === true && runtime?.credentialPresent === true, rows = Array.isArray(tools) ? tools : [];
    return eq(result, { model: Boolean(route.provider && route.model && ready), cli: ready, files: Boolean(workspacePath), browser: rows.some(row => row?.toolId === "tool.playwright" && row.agentReady === true), mcp: rows.some(row => String(row?.toolId || "").startsWith("mcp.") && row.agentReady === true) });
  }),
  "workflow.explain": claim("workflow.explain", ([workflow, available = {}], result) => { const missing = (workflow?.requires || []).filter(key => !available[key]); return eq(result.missing, missing) && result.runnable === !missing.length && (missing.length || result.reason === "Prerequisites detected. The runtime checks the connection at launch."); }),
  "ecosystem.capture": claim("ecosystem.capture", ([form = {}], result) => eq(result, { source: text(form.source), direction: "chatgpt-to-neyvia", content: { selectedText: text(form.content) }, userInitiated: form.userInitiated === true, ...Object.fromEntries(["project", "conversation", "mission"].map(kind => [`${kind}Id`, text(form.destinationKind || "project") === kind ? text(form.destinationId) : ""])) })),
  "ecosystem.benchmark": claim("ecosystem.benchmark", ([form = {}], result) => eq(result, { subjectId: text(form.subjectId), success: String(form.success || "not-reported") === "true" ? true : String(form.success || "") === "false" ? false : "not-reported", comparableContext: form.comparableContext === true, budgetExceeded: form.budgetExceeded === true, measuredFacts: text(form.measuredFacts) || "not-reported" })),
  "ecosystem.submit": claim("ecosystem.submit", ([run, form = {}], result) => result === Boolean(run?.runId && text(form.subjectId) && (Array.isArray(run.subjects) ? run.subjects : []).some(subject => String(typeof subject === "object" ? subject.subjectId : subject) === text(form.subjectId)))),
  "ecosystem.conclude": claim("ecosystem.conclude", ([experiment, verdict], result) => result === Boolean(experiment?.experimentId && experiment.state !== "concluded" && text(verdict))),
  "fabric.normalize": claim("fabric.normalize", ([value], result) => result.schema === String(value?.schema || "") && ["accounts", "imports", "permissionLadder"].every(key => eq(result[key], Array.isArray(value?.[key]) ? value[key] : []))),
  "fabric.tone": claim("fabric.tone", ([value], result) => result === ({ connected: "good", limited: "warning", "approval-required": "warning", "credentials-missing": "warning", "blocked-by-organization": "blocked" })[text(value).toLowerCase()] || result === "neutral" && !["connected", "limited", "approval-required", "credentials-missing", "blocked-by-organization"].includes(text(value).toLowerCase())),
  "fabric.account": claim("fabric.account", ([form = {}], result) => eq(Object.keys(result).sort(), ["label", "addressHint", "organization", "route", "state", "limitation", "permissions", "configuration"].sort()) && eq(result.configuration, {}) && eq(result.permissions, [...new Set((Array.isArray(form.permissions) ? form.permissions : ["read", "draft"]).map(value => text(value).toLowerCase()).filter(Boolean))].sort()) && result.route === text(form.route || "file-import") && result.state === text(form.state || "not-configured")),
  "fabric.approval": claim("fabric.approval", ([value], result) => result === (["send", "delete", "unsubscribe"].includes(String(value || "").toLowerCase()) ? "Confirm each action" : "Approve for this account")),
  "fabric.insert": claim("fabric.insert", ([value], result) => result === Boolean(value && value.requiresExplicitInsert === true && value.automatedLogin === false && value.transcriptHarvesting === false && text(value.compiled))),
  "roles.normalize": claim("roles.normalize", ([roles = []], result) => eq(result, [...new Set(["planner", "executor", "verifier", ...(Array.isArray(roles) ? roles : []).map(role => text(role).toLowerCase()).filter(Boolean)])])),
  "roles.default": claim("roles.default", ([role], result) => result === ["planner", "executor", "verifier"].includes(text(role).toLowerCase())),
  "roles.meta": claim("roles.meta", ([role], result) => { const id=text(role).toLowerCase(), known={planner:"Planner",executor:"Executor",verifier:"Verifier",backend:"Backend specialist",frontend:"Frontend specialist",operator:"Operator",attacker:"Attacker",defender:"Defender",auditor:"Auditor"}; const label=known[id] || id.split(/[-_\s]+/).filter(Boolean).map(word=>word[0].toUpperCase()+word.slice(1)).join(" ") || "Specialist";return result?.label===label && typeof result.detail==="string"; }),
  "batch.runtime-options": claim("batch.runtime-options", ([options = []], result) => {
    const rows = Array.isArray(options) ? options : [], ids = result.map(row => row.value);
    return new Set(ids).size === ids.length && ["neyvia-agent", "codex", "claude-code", "grok-build", "kimi-code", "opencode", "hermes", "openclaw", "opencode-go"].every(id => ids.includes(id)) && rows.every((row, index) => { const id = text(row?.value || row?.runtime_id); if (!id || rows.slice(0,index).some(previous => text(previous?.value || previous?.runtime_id) === id)) return true; const actual = result.find(item => item.value === id); return actual && Object.keys(row).filter(key => !["value", "label", "family"].includes(key)).every(key => eq(row[key], actual[key])); });
  }),
  "workflow.list": claim("workflow.list", ([available = {}], result) => {
    const requirements = { "research-brief": ["model"], "fix-failing-test": ["model", "files"], "review-changes": ["model", "files"], "watch-a-run": ["model", "browser"], "document-this": ["model", "files"], "extract-from-documents": ["model", "files"] };
    return result.length === Object.keys(requirements).length && result.every(row => Object.hasOwn(requirements,row.id) && eq(row.missing,requirements[row.id].filter(key => !available[key])) && row.runnable === requirements[row.id].every(key => Boolean(available[key])) && (!row.runnable || row.reason === "Prerequisites detected. The runtime checks the connection at launch."));
  }),
  "preferences.normalize": claim("preferences.normalize", ([value = {}], result) => result.effectIntensity === (["off", "subtle", "balanced", "vivid"].includes(value.effectIntensity) ? value.effectIntensity : "balanced") && result.transparencyLevel === (["solid", "soft", "glass"].includes(value.transparencyLevel) ? value.transparencyLevel : "soft") && (value.showLabels === undefined || result.showLabels === Boolean(value.showLabels))),
  "preferences.motion": claim("preferences.motion", ([value = {}], result) => {
    const effects = {off:[0,0,0,0,0,0],subtle:[120,170,240,1.8,4,.24],balanced:[160,220,320,1.35,8,.35],vivid:[180,260,380,1.1,12,.45]}, effect = effects[value.effectIntensity] || effects.balanced, reduced=Boolean(value.reduceMotion), transparency=({solid:["100%","0px"],soft:["97%","6px"],glass:["92%","12px"]})[value.transparencyLevel] || ["97%","6px"];
    return ["fast","med","slow"].every((key,index) => result[`--neyvia-motion-${key}`] === `${reduced?0:effect[index]}ms`) && result["--neyvia-motion-pulse"] === (reduced || effect[3]===0 ? "0ms" : `${effect[3]}s`) && result["--neyvia-effect-lift"] === `${reduced?0:effect[4]}px` && result["--neyvia-effect-shadow-alpha"] === String(effect[5]) && result["--neyvia-surface-opacity"] === transparency[0] && result["--neyvia-surface-blur"] === transparency[1];
  }),
  "mission.live": claim("mission.live", ([store, missionId], result) => {
    const record=store?.missions?.[text(missionId)]; if(!record)return result===null;
    const status=text(record.summary?.status || record.summary?.state?.status || record.summary?.statusLabel || "unknown").toLowerCase();
    return result.status===status && result.live === ["running","working","active"].includes(status) && eq(result.artifacts,record.artifacts);
  }),
  "mission.delta": claim("mission.delta", ([store, missionId, events = [], cursor = null, options = {}], result) => {
    const id=text(missionId);if(!id)return result===store;
    const record=result?.missions?.[id], original=store.missions[id];
    return record && record.eventCursor === (cursor != null ? cursor : original?.eventCursor ?? null) && (!options.reset || record.events.every(event => (Array.isArray(events)?events:[]).some(input => !input.eventId || input.eventId===event.eventId))) && record.events.length<=600 && new Set(record.events.map(event=>event.eventId)).size===record.events.length;
  }),
  "mission.artifacts": claim("mission.artifacts", ([store, missionId, artifacts = []], result) => !text(missionId) ? result===store : (Array.isArray(artifacts)?artifacts:[]).every(input => !input?.artifactId || !input.servedUrl ? true : result.missions[text(missionId)].artifacts.some(item => item.artifactId===input.artifactId && item.contentRef.url===input.servedUrl && (!input.safeEndpoint || item.contentRef.endpoint===input.safeEndpoint) && (!input.mediaType || item.mediaType===input.mediaType)))),
  "office.classify": claim("office.classify", ([payload = {}, options = {}], result) => result === officeOutcome(payload, options.kind)),
  "office.describe": claim("office.describe", ([raw = null, options = {}], result) => result.outcome === (options.connectionError ? "backend-error" : officeOutcome(raw, "describe")) && result.agentReady === (!options.connectionError && raw?.agentReady === true)),
  "office.execute": claim("office.execute", ([raw = null, options = {}], result) => {
    if (options.connectionError) return result.outcome === "backend-error" && !result.ok && result.artifact===null && result.verification===null && result.lineage.length===0 && result.summary===String(options.connectionError.message || options.connectionError).trim();
    const source=raw?.result || {}, verification=source.verification || raw?.verification || null, relations=Array.isArray(raw?.artifactReceipt?.relations)?raw.artifactReceipt.relations:[];
    return result.outcome===officeOutcome(raw) && result.ok===(raw?.ok===true) && eq(result.verification,verification) && ["outputPath","sha256","bytes","sourcePath","mediaType","engine"].every(key => source[key] === undefined || source[key] === null || source[key] === "" ? result.artifact?.[key]===undefined : eq(result.artifact?.[key],source[key])) && eq(result.lineage,relations.map(row=>({relation:String(row.relation??"").trim(),from:String(row.from||row.parentArtifactId||row.sourceArtifactId||"").trim(),to:String(row.to||row.childArtifactId||row.targetArtifactId||"").trim(),capabilityId:String(row.capabilityId??"").trim(),runId:String(row.runId??"").trim()}))) && eq(result.inputs,options.inputs || raw?.arguments || null) && ["allowed","approvalRequired","denied"].every(key=>raw?.permissionSummary ? eq(result.permissionSummary[key],(Array.isArray(raw.permissionSummary[key])?raw.permissionSummary[key]:[]).map(String)) : result.permissionSummary===null) && eq(result.inputValidation,raw?.inputValidation || null);
  }),
  "office.payload": claim("office.payload", ([form = {}], result) => result.toolId===text(form.toolId) && result.operationId===text(form.operationId) && result.permissionMode===text(form.permissionMode || "workspace_safe") && eq(result.arguments,form.arguments && typeof form.arguments==="object" && !Array.isArray(form.arguments)?form.arguments:{})),
  "recovery.interrupted": claim("recovery.interrupted", ([turn = {}, message = ""], result) => {
    const partial=Boolean(text(turn.title)) && !/^(thinking|working|starting with)\b/i.test(text(turn.title)), reason=text(message) || "Neyvia closed while this response was running, so it could not finish.";
    return eq(result,{title:partial?String(turn.title):"This response was interrupted before a reply arrived.",detail:partial?`${reason} The text above is what arrived before it stopped.`:reason,pending:false,tone:"warn",source:"chat-interrupted",toolCalls:(Array.isArray(turn.toolCalls)?turn.toolCalls:[]).map(call=>["started","running"].includes(String(call?.status||"").toLowerCase())?{...call,status:"interrupted"}:call)});
  }),
  "recovery.decision": claim("recovery.decision", ([status, turn = {}, {now=Date.now(), cleanReply} = {}], result) => {
    const state=String(status?.status||"").toLowerCase(), finished=epoch(status?.finishedAt), created=epoch(turn.createdAt);
    const action=!status || typeof status!=="object" ? "wait" : state==="running" ? "watch" : status.result && typeof status.result==="object" && state!=="interrupted" || state==="interrupted" ? "settle" : ["finished","failed","cancelled"].includes(state) ? Number.isFinite(finished)&&now-finished<8000?"wait":"settle" : Number.isFinite(created)&&now-created<120000?"wait":"settle";
    if (result.action!==action || action==="watch" && Number.isFinite(epoch(status.lastActivityAt)) && result.lastActivityAt!==epoch(status.lastActivityAt)) return false;
    if (action!=="settle") return !result.patch;
    if (status.result && typeof status.result === "object" && state!=="interrupted") return FRONTEND_CONTRACTS["recovery.recorded"].check([turn,status.result,{cleanReply}],result.patch);
    if (state==="cancelled") return result.patch?.pending===false && result.patch.source==="chat-cancelled" && result.patch.detail==="Stopped by you." && eq(result.patch.toolCalls,(Array.isArray(turn.toolCalls)?turn.toolCalls:[]).map(call=>["started","running"].includes(String(call?.status||"").toLowerCase())?{...call,status:"interrupted"}:call));
    const reason=state==="interrupted"?status.message:state==="failed"?"The runtime failed while this window was away, and its error was not saved.":state==="finished"?"This response ended while this window was away, and its final text was not saved.":"No running process owns this response anymore, so it cannot finish.";
    return FRONTEND_CONTRACTS["recovery.interrupted"].check([turn,reason],result.patch);
  }),
  "recovery.recorded": claim("recovery.recorded", ([turn = {}, result = {}, options = {}], patch) => {
    const compartment=result?.compartment || {}, reply=(options.cleanReply || (value=>String(value||"").trim()))(result?.reply || result?.finalMessage || result?.message), cancelled=text(result?.status || compartment.state).toLowerCase()==="cancelled" || result?.cancelled===true;
    if(cancelled)return patch.pending===false && patch.source==="chat-cancelled";
    const failed=result?.ok===false || ["failed","error","timeout","stop_unconfirmed"].includes(String(result?.status || compartment.state || "").toLowerCase()), error=text(result?.error || (Array.isArray(compartment.errors)?compartment.errors[0]:""));
    return patch.pending===false && patch.title===(reply || (failed?"The runtime failed before a readable reply.":"The runtime finished without a readable reply.")) && patch.detail===(failed?error || "The runtime failed.":"") && patch.tone===(failed?"bad":reply?"neutral":"warn") && patch.source===(failed?"backend-runtime-error":reply?"backend-runtime-reply":"backend-runtime-empty") && eq(patch.rawTurnReceipt,compartment.turnReceipt || result?.turnReceipt || null);
  }),
  "recovery.unowned": claim("recovery.unowned", ([transcripts, owned = new Set(), limit = 12], result) => {
    const rows=Object.entries(transcripts || {}).flatMap(([sessionId,turns])=>(Array.isArray(turns)?turns:[]).filter(turn=>turn?.role==="assistant" && turn.pending && turn.id && !owned.has(String(turn.id))).map(turn=>({sessionId,turn}))).sort((a,b)=>(epoch(b.turn.createdAt)||0)-(epoch(a.turn.createdAt)||0)).slice(0,Math.max(0,limit));return eq(result,rows);
  }),
  "recovery.quiet": claim("recovery.quiet", ([lastActivityAt, now=Date.now()], result) => {const last=epoch(lastActivityAt), quiet=now-last, minutes=Math.floor(quiet/60000);return result===(!Number.isFinite(last)||quiet<90000?"":minutes<2?"No new output for over a minute":`No new output for ${minutes} min`);}),
  "recovery.merge": claim("recovery.merge", ([turn = {}, streamed = null], result) => {if(!streamed)return eq(result,turn);const answer=String(streamed.answer||""), current=text(turn.title)&&!/^(thinking|working|starting with)\b/i.test(text(turn.title))?String(turn.title):"", use=answer.trim()&&answer.length>=current.length, segments=Array.isArray(streamed.activitySegments)&&streamed.activitySegments.length;return result.title===(use?answer:turn.title) && result.source===(use?"runtime-stream":turn.source) && (!Array.isArray(streamed.toolCalls)||!streamed.toolCalls.length?eq(result.toolCalls,turn.toolCalls):CHAT_CONTRACTS.normalizedCalls([streamed.toolCalls],result.toolCalls)) && result.reasoningSummary===(streamed.reasoningSummary || turn.reasoningSummary || "") && eq(result.activitySegments,segments?streamed.activitySegments:turn.activitySegments) && result.activityOrderKnown===(segments?true:Boolean(turn.activityOrderKnown));}),
  "factory.progress": claim("factory.progress", ([job], result) => {const completed=(Array.isArray(job?.stages)?job.stages:[]).filter(stage=>stage?.state==="completed").length;return eq(result,{completed,total:5,percent:Math.round(completed/5*100)});}),
  "attention.thread": claim("attention.thread", ([form = {}], result) => attentionThreadClaim(form,result)),
  "attention.activity": claim("attention.activity", ([value,now=Date.now()], result) => {const at=attentionTime(value),age=Math.max(0,attentionTime(now)-at);return result===(!at?"unknown":age<900000?"now":age<21600000?"recent":age<86400000?"today":"older");}),
  "attention.description": claim("attention.description", ([thread], result) => text(thread?.lastActivitySummary) ? result===text(thread.lastActivitySummary) : Number(thread?.approvals||0)>0 ? result==="Waiting for your approval before work can continue." : Number(thread?.blockers||0)>0 ? result==="Verification found a blocker that needs attention." : typeof result==="string"&&result.length>0),
  "attention.sections": claim("attention.sections", ([threads = [], options = {}], result) => attentionSectionsClaim(threads,options,result)),
  "attention.inbox": claim("attention.inbox", ([form = {}], result) => {
    const conversations=Array.isArray(form.conversations)?form.conversations:[],missions=Array.isArray(form.missions)?form.missions:[],now=form.now ?? Date.now();
    const supplied=new Set(conversations.map(row=>text(row?.conversationId)).filter(Boolean));
    const linked=new Set(conversations.map(row=>text(row?.missionId||row?.metadata?.missionId)).filter(Boolean));
    for(const mission of missions)if(text(mission?.missionId)&&!linked.has(text(mission.missionId))&&!(attentionTime(mission.lastEventAt||mission.updatedAt||mission.createdAt)>0&&now-attentionTime(mission.lastEventAt||mission.updatedAt||mission.createdAt)>1209600000))supplied.add(text(mission.missionId));
    const ids=result.threads.map(row=>row.threadId);
    return new Set(ids).size===ids.length && ids.length===supplied.size && ids.every(id=>supplied.has(id)) && Object.entries(result.counts).every(([state,count])=>count===result.threads.filter(row=>row.attentionState===state).length) && result.needsActionCount===result.threads.filter(row=>row.attentionState==="needs-action").length && result.derivedCount===result.threads.filter(row=>row.derivation==="derived").length && result.durableLifecycle===Boolean(form.durableLifecycle) && result.disclosure===(form.durableLifecycle?"Attention states are read from the durable conversation lifecycle.":"Attention states are derived from live mission and conversation signals. Settle and snooze need the durable lifecycle commands before they can be offered.") && attentionSectionsClaim(result.threads,form,result.groups);
  }),
  "attention.filter": claim("attention.filter", ([inbox, filter], result) => {
    const states=({open:["needs-action","active","ready-for-review"],"needs-action":["needs-action"],review:["ready-for-review"],quiet:["quiet"],settled:["settled"],all:["needs-action","active","ready-for-review","quiet","settled"]})[filter]||["needs-action","active","ready-for-review"],open=filter==="open"||!["needs-action","review","quiet","settled","all"].includes(filter);
    return result.length===(inbox?.groups||[]).length && result.every((group,index)=>group.id===inbox.groups[index].id&&eq(group.threads,inbox.groups[index].threads.filter(thread=>states.includes(thread.attentionState)&&(!open||!thread.archivedReport))));
  }),
  "attention.projects": claim("attention.projects", ([threads = [], {labels={}} = {}], result) => {
    const groups=new Map();for(const thread of Array.isArray(threads)?threads:[]) {const key=thread.projectId||thread.workspaceId||"",id=key||"unassigned";if(!groups.has(id))groups.set(id,{id,label:labels[id]||(key?key:"No project"),assigned:Boolean(key),threads:[]});groups.get(id).threads.push(thread);}
    const expected=[...groups.values()].map(group=>({...group,threads:group.threads.sort(attentionCompare)})).sort((a,b)=>a.assigned!==b.assigned?a.assigned?-1:1:String(a.label).localeCompare(String(b.label)));return eq(result,expected);
  }),
  "attention.recent": claim("attention.recent", ([left,right], result) => result===(attentionTime(right.lastMeaningfulActivityAt)-attentionTime(left.lastMeaningfulActivityAt)||attentionCompare(left,right))),
  "attention.subagents": claim("attention.subagents", ([raw = []], result) => {
    const rows=(Array.isArray(raw)?raw:[]).filter(row=>row&&typeof row==="object"&&text(row.id||row.invocationId||row.sessionId));
    return result.total===rows.length && rows.every(row=> {const agent=result.agents.find(item=>item.id===text(row.id||row.invocationId||row.sessionId));return agent && (text(row.state||row.status).toLowerCase()!=="waiting"||agent.state==="paused") && (text(row.state||row.status).toLowerCase()!=="requested"||agent.state==="planned");}) && (!rows.some(row=>text(row.state||row.status).toLowerCase()==="waiting")||rows.some(row=>!["waiting","requested"].includes(text(row.state||row.status).toLowerCase()))||result.stateLabel==="Paused");
  }),
  "attention.showcase": claim("attention.showcase", (args,result) => result.length===5&&result.some(row=>row.kind==="chat")&&result.some(row=>row.kind==="orchestration")&&result.some(row=>row.attentionState==="needs-action")&&result.some(row=>row.attentionState==="ready-for-review")&&result.some(row=>/notepad\.exe/i.test(row.title))&&result.every(row=>row.lastActivitySummary)),
  "factory.tone": claim("factory.tone", ([job], result) => result===(job?.nativeBuild?.state==="failed" || ["failed","needs_attention"].includes(job?.status)?"danger":["queued","running"].includes(job?.nativeBuild?.state)||job?.status==="building"?"working":job?.verification?.state==="passed"&&job?.registration?.state==="draft-ready"?"ready":"neutral")),
  "factory.catalog": claim("factory.catalog", ([value = {}], result) => ["jobs","targets","capabilityHandoffs","pipeline"].every(key=>eq(result[key],(Array.isArray(value?.[key])?value[key]:[]).filter(Boolean))) && Object.is(result.summary.total,Number(value?.summary?.total || result.jobs.length)) && Object.is(result.summary.capabilityReady,Number(value?.summary?.capabilityReady ?? result.capabilityHandoffs.filter(item=>item?.state==="review_required").length))),
  "factory.create": claim("factory.create", ([form,root=""], result) => eq(result,{name:text(form?.name),brief:text(form?.brief),target:text(form?.target||"desktop"),template:text(form?.template||"auto"),theme:text(form?.theme||"midnight"),directory:text(form?.directory),...(text(root)?{root:text(root)}:{})})),
  "factory.job": claim("factory.job", ([jobId,root=""], result) => eq(result,{jobId:text(jobId),...(text(root)?{root:text(root)}:{})})),
  "factory.import": claim("factory.import", ([bundle,root=""], result) => !bundle || typeof bundle!=="object" || Array.isArray(bundle) || bundle.schema!=="neyvia.capability-run-bundle/v2" || !text(bundle.appFactoryJobId) || !Array.isArray(bundle.runs) || !bundle.runs.length ? result===null : eq(result,{bundle,importedBy:"operator",...(text(root)?{root:text(root)}:{})})),
  "factory.capability": claim("factory.capability", ([handoff,form,root="",review=false], result) => handoff?.canCreateApp!==true || handoff?.state!=="review_required" || !handoff?.materializationId || !handoff?.candidateDigest || review!==true ? result===null : eq(result,{materializationId:text(handoff.materializationId),candidateDigest:text(handoff.candidateDigest),reviewConfirmed:true,reviewedBy:"operator",name:text(form?.name),brief:text(form?.brief),target:text(form?.target||"neyvia"),theme:text(form?.theme||"midnight"),directory:text(form?.directory),...(text(root)?{root:text(root)}:{})})),
  "factory.eligible": claim("factory.eligible", ([catalog], result) => eq(result,(Array.isArray(catalog?.capabilityHandoffs)?catalog.capabilityHandoffs:[]).filter(item=>item?.state==="review_required"&&item?.canCreateApp===true))),
  "factory.handoff": claim("factory.handoff", ([catalog,job], result) => result === (!job?.capabilityHandoff?.materializationId?null:(Array.isArray(catalog?.capabilityHandoffs)?catalog.capabilityHandoffs:[]).find(item=>item?.materializationId===job.capabilityHandoff.materializationId)||null)),
  "factory.hash": claim("factory.hash", ([value], result) => result===(text(value)?text(value).length>18?`${text(value).slice(0,10)}…${text(value).slice(-6)}`:text(value):"Not recorded")),
  "factory.commands": claim("factory.commands", (args,result) => result.buildNative==="start_app_factory_native_build_command" && result.createFromCapability==="create_app_factory_from_materialization_command" && result.importOutcomes==="import_capability_run_bundle_command"),
  "activity.href": claim("activity.href", ([value], result) => {
    const href=text(value);let expected="";
    if(href && !/[\u0000-\u001f\u007f]/.test(href)) { if(href.startsWith("/") && !href.startsWith("//") && !href.includes("\\"))expected=href;else try{if(["http:","https:"].includes(new URL(href).protocol))expected=href;}catch{} }
    return result===expected;
  }),
  "activity.duration": claim("activity.duration", ([value], result) => {
    const ms=Number(value);return result===(value==null || value==="" || !Number.isFinite(ms)||ms<0?"Not recorded":ms<1000?`${Math.round(ms)}ms`:ms<60000?`${(ms/1000).toFixed(ms<10000?1:0)}s`:`${Math.floor(ms/60000)}m ${Math.round(ms%60000/1000)}s`);
  }),
});
function epoch(value) {if(value==null||value==="")return NaN;return typeof value==="number"?value<1e12?value*1000:value:Date.parse(String(value));}
function attentionTime(value){if(!value)return 0;const number=new Date(value).getTime();return Number.isNaN(number)?0:number;}
const attentionStates=["needs-action","active","ready-for-review","quiet","settled"];
function attentionCompare(left,right){return right.blockingReasons.length-left.blockingReasons.length || right.unreadMeaningfulChanges-left.unreadMeaningfulChanges || attentionTime(right.settledAt||right.lastMeaningfulActivityAt)-attentionTime(left.settledAt||left.lastMeaningfulActivityAt) || String(left.title).localeCompare(String(right.title)) || String(left.threadId).localeCompare(String(right.threadId));}
function attentionThreadClaim({conversation=null,mission=null,runtimeStatus=null,now=Date.now()}={},result){
  const row=conversation&&typeof conversation==="object"&&!Array.isArray(conversation)?conversation:{},task=mission&&typeof mission==="object"&&!Array.isArray(mission)?mission:{};
  const id=text(row.conversationId||task.missionId);if(!id)return result===null;
  const reasons=[],add=id=>{if(!reasons.includes(id))reasons.push(id);},approvals=Number(task.approvals||row.pendingApprovalCount||0),blockers=Number(task.blockers||row.verificationFailureCount||0),runtime=text(task.responsible||row.runtime).toLowerCase(),status=text(task.status||row.status).toLowerCase(),blocked=["failed","error","blocked","needs_approval","verification_failed","awaiting_input"],terminal=task.terminal===true||["completed","done","failed","stopped","cancelled","canceled"].includes(status),settled=text(row.settledAt),snooze=text(row.snoozedUntil),durable=text(row.attentionState);
  if(approvals>0||row.hasBlockingApproval===true)add("approval-required");if(blockers>0||row.hasVerificationFailure===true)add("verification-failed");if(row.awaitingUserAnswer===true)add("answer-required");if(row.securityDecisionPending===true)add("security-decision");if(runtime&&runtimeStatus?.[runtime]?.available===false)add("runtime-unavailable");
  if(blocked.includes(status)&&!reasons.length)add(({needs_approval:"approval-required",awaiting_input:"answer-required",verification_failed:"verification-failed"})[status]||"blocked");
  const blocking=[...reasons];
  if(!terminal){if(["running","active","launching","executing"].includes(status)&&(status!=="active"||text(task.status)))add("running");if(text(task.responsible))add("delegated");if(["queued","waiting"].includes(status))add("waiting-runtime");if(["paused","suspended"].includes(status))add("paused-resumable");}
  if(terminal&&!settled&&["completed","done","succeeded"].includes(status)){add("work-complete-unaccepted");if(Number(task.artifactCount||0)>0)add("artifact-delivered");}if(text(row.pullRequest?.state||row.pullRequest?.url))add("pr-ready");if(row.hasVerificationEvidence===true)add("evidence-ready");
  const snoozed=Boolean(snooze)&&attentionTime(snooze)>now;
  const state=blocking.length?"needs-action":settled?"settled":snoozed?"quiet":durable?attentionStates.includes(durable)?durable:"active":reasons.some(reason=>["work-complete-unaccepted","artifact-delivered","pr-ready","evidence-ready"].includes(reason))?"ready-for-review":reasons.length?"active":blocked.includes(status)?"needs-action":"quiet";
  if(!blocking.length&&settled)add(text(row.settlementReason)==="closed"?"closed":"accepted");else if(!blocking.length&&snoozed)add("snoozed");else if(!blocking.length&&!settled&&!snoozed&&!durable&&!reasons.length)add("waiting-no-attention");
  const activity=[row.lastMeaningfulActivityAt,task.lastEventAt,row.updatedAt,row.createdAt].map(text).filter(Boolean).sort((a,b)=>attentionTime(b)-attentionTime(a))[0]||null;
  const age=Math.max(0,attentionTime(now)-attentionTime(activity)),tier=!attentionTime(activity)?"unknown":age<900000?"now":age<21600000?"recent":age<86400000?"today":"older";
  return result.threadId===id&&result.attentionState===state&&eq(result.reasons,reasons)&&eq(result.blockingReasons,blocking)&&result.escapedSnooze===(Boolean(blocking.length)&&snoozed)&&result.settledAt===(settled||null)&&result.lastMeaningfulActivityAt===activity&&result.activityTier===tier&&result.lastActivitySummary===(text(task.lastEventSummary||row.lastActivitySummary)||null)&&result.derivation===(durable||settled||snooze?"durable":"derived")&&result.archivedReport===(text(row.kind)==="orchestration"&&Boolean(row.conversationId)&&attentionTime(activity)>0&&now-attentionTime(activity)>1209600000);
}
function attentionSectionsClaim(threads,options,result){
  let zone=text(options.timeZone)||Intl.DateTimeFormat().resolvedOptions().timeZone||"UTC";try{new Intl.DateTimeFormat("en",{timeZone:zone}).format();}catch{zone="UTC";}
  const key=value=>{const parts=Object.fromEntries(new Intl.DateTimeFormat("en-US",{day:"2-digit",month:"2-digit",year:"numeric",timeZone:zone}).formatToParts(new Date(attentionTime(value))).filter(part=>part.type!=="literal").map(part=>[part.type,part.value]));return `${parts.year}-${parts.month}-${parts.day}`;};
  const today=key(options.now??Date.now()),[y,m,d]=today.split("-").map(Number),yesterday=new Date(Date.UTC(y,m-1,d)-86400000).toISOString().slice(0,10),history=new Map(),priority=[];
  for(const thread of Array.isArray(threads)?threads:[])if(attentionStates.slice(0,3).includes(thread.attentionState))priority.push(thread);else{const date=key(thread.settledAt||thread.lastMeaningfulActivityAt||0);if(!history.has(date))history.set(date,[]);history.get(date).push(thread);}
  const dates=[today,yesterday,...[...history.keys()].filter(date=>date!==today&&date!==yesterday).sort((a,b)=>b.localeCompare(a))];
  return result.length===dates.length+1&&result[0].id==="priority"&&eq(result[0].threads,priority.sort((a,b)=>attentionStates.indexOf(a.attentionState)-attentionStates.indexOf(b.attentionState)||attentionCompare(a,b)))&&dates.every((date,index)=>{const group=result[index+1],id=index===0?"today":index===1?"yesterday":`date:${date}`;const [year,month,day]=date.split("-").map(Number);const label=index===0?"Today":index===1?"Yesterday":new Intl.DateTimeFormat(options.locale||undefined,{day:"numeric",month:"short",year:"numeric",timeZone:zone}).format(new Date(Date.UTC(year,month-1,day,12)));return group.id===id&&group.dateKey===date&&group.label===label&&eq(group.threads,(history.get(date)||[]).sort(attentionCompare));});
}
function officeOutcome(payload, kind = "execute") {
  if(payload==null)return "unavailable";if(payload instanceof Error)return "backend-error";
  const status=text(payload.status || payload.error).toLowerCase();
  if(kind==="describe")return payload.connectionState==="unavailable" || payload.unavailable===true ? "unavailable" : payload.agentReady===true ? "available" : status.includes("error") || payload.error ? "backend-error" : "unavailable";
  if(["invalid_arguments","invalid"].includes(status))return "invalid";
  if(["permission_denied","denied"].includes(status))return "denied";
  if(status==="approval_required")return "approval";
  if(["tool_not_ready","adapter_required","unavailable"].includes(status))return "unavailable";
  if(payload.ok===true && ["completed","","ok"].includes(status)) { const verification=text(payload.result?.verification?.status || payload.verification?.status).toLowerCase();return verification==="failed" ? "backend-error" : ["passed","verified"].includes(verification)?"verified":"completed"; }
  return payload.error || status ? "backend-error" : "unavailable";
}
export function checkedFrontendAction(id, args, result, before) {
  if (!FRONTEND_CONTRACTS[id]?.check(args, result, before)) throw new FrontendContractError(id);
  return result;
}
