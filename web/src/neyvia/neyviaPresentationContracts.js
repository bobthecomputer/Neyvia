import { equalContractValue, FrontendContractError } from "./neyviaFrontendContracts.js";

const levels = new Set(["everything", "summaries", "minimal"]);
const text = value => value == null ? "" : typeof value === "string" ? value : JSON.stringify(value, null, 2);
const retained = state => ["open", "opening", "collapsed"].includes(state);
const object = value => value && typeof value === "object" && !Array.isArray(value) ? value : {};
const list = value => Array.isArray(value) ? value : [];
const label = (value, fallback = "Not reported") => String(value ?? "").trim() || fallback;
const identity = record => `${record.adapterId}::${record.context?.artifactId || record.context?.applicationId || record.context?.imageSessionId || record.lineage?.originInvocationId || record.contentRef?.path || record.contentRef?.url || record.contentRef?.endpoint || record.title || ""}`;
function requireValue(id, actual, expected) {
  if (!equalContractValue(actual, expected)) throw new FrontendContractError(id, "Presentation changed the recorded evidence or lifecycle policy");
}

/** Semantic checks at the presentation boundary, independent of source layout. */
export function checkPresentationAction(id, args, result, adapters = []) {
  const [a, b, c, d] = args;
  const expectedLevel = levels.has(a) ? a : "everything";
  if (id === "transparency.normalize") requireValue(id, result, expectedLevel);
  else if (id === "transparency.text") requireValue(id, result, text(a));
  else if (id === "transparency.visible") {
    const data = a.data || {};
    requireValue(id, result, b !== "minimal" ? true : a.kind === "tool" ? data.status === "error" || (data.exitCode != null && Number(data.exitCode) !== 0) : a.kind === "diff" ? false : a.kind === "reasoning" ? Boolean(data.hidden || data.notice) : true);
  } else if (id === "transparency.expanded") requireValue(id, result, b === "everything" || !levels.has(b) || d ? !c.has(a) : c.has(a));
  else if (id === "transparency.notice") requireValue(id, result, a?.notice || `${a?.provider || b || "The provider"} didn’t share its reasoning for this step`);
  else if (id === "transparency.details") {
    const data = a || {}, fields = [], input = text(data.input), command = text(data.command || (data.category === "command" ? input : "")), argText = text(data.args), output = text(data.output), value = text(data.result);
    if (command) fields.push({ label: "Command", text: command });
    if (argText && argText !== command) fields.push({ label: "Arguments", text: argText });
    if (input && input !== command && input !== argText) fields.push({ label: "Input", text: input });
    if (output || data.output === "") fields.push({ label: "Output", text: output || "(empty output)" });
    if (value && value !== output) fields.push({ label: "Result", text: value });
    requireValue(id, result, fields);
  } else if (id === "transparency.metadata") {
    const data = a || {}, parts = [], running = data.status === "running", command = data.category === "command";
    if (data.exitCode != null) parts.push(`Exit ${data.exitCode}`);
    else if (command && !running) parts.push("Exit not reported");
    if (Number.isFinite(data.durationMs)) parts.push(`${["transcript-timestamps", "transport-observed"].includes(data.durationSource) ? "Observed " : ""}${(data.durationMs / 1000).toFixed(data.durationMs < 1000 ? 3 : 2)} s`);
    else if (command && !running) parts.push("Duration not reported");
    if (running) parts.push("Running");
    requireValue(id, result, parts.join(" · "));
  } else if (id === "transparency.patch") requireValue(id, result, a?.patch != null ? text(a.patch) : list(a?.files).map(file => text(file.patch ?? file.diff ?? "")).filter(Boolean).join("\n\n"));
  else if (id === "starters.catalog") {
    if (result?.chat?.length !== 6 || result?.orchestration?.length !== 4 || [...result.chat, ...result.orchestration].some(row => !row.id || !row.title || !row.detail || row.prompt?.length <= 20)) throw new FrontendContractError(id, "Mode starters require complete usable prompts");
  } else if (id === "orchestration.preset") {
    const count = Math.trunc(Math.min(4, Math.max(2, Number(a) || 2))), expected = ["lead", ...Array(count).fill("worker"), ...(b ? ["integration"] : []), "barrier"];
    requireValue(id, result?.map(row => row.roleId), expected);
    requireValue(id, result?.map(row => row.routeSelection?.model), expected.map(role => role === "lead" ? "gpt-5.6-sol" : role === "barrier" ? "gpt-5.6-terra" : "gpt-5.6-luna"));
    requireValue(id, result?.map(row => row.routeSelection?.effort), expected.map(role => role === "lead" ? "xhigh" : role === "barrier" ? "medium" : "high"));
    result.forEach((row, index) => requireValue(id, [row.runtime, row.routeSelection.runtimeId, row.routeSelection.provider, row.status, row.goal], ["codex", "codex", "openai-codex", index === 0 ? "ready" : "queued", row.brief]));
  } else if (id === "orchestration.resolve") {
    const conversation = a || {}, metadata = object(conversation.metadata), selection = object(metadata.teamSelection), roles = selection.mode === "explicit" ? list(selection.roles).map(role => String(role || "").trim().toLowerCase()).filter(Boolean) : [], graph = object(d);
    if (roles.length) {
      requireValue(id, result?.map(row => row.roleId), roles);
      const objective = String(conversation.objective || metadata.objective || metadata.goal || conversation.title || conversation.name || "the orchestration objective").trim().slice(0, 320);
      result.forEach((row, index) => {
        const role = roles[index], route = metadata.routeSnapshot?.[role] && typeof metadata.routeSnapshot[role] === "object" ? { ...metadata.routeSnapshot[role], role } : { role, runtimeId: c || "hermes" }, roleLabel = String(route.label || role.split(/[-_\s]+/).filter(Boolean).map(token => token.charAt(0).toUpperCase() + token.slice(1)).join(" ")), goal = String(route.objective || route.goal || `${({ planner: "Plan", executor: "Execute", verifier: "Verify" })[role] || "Handle"} the bounded ${roleLabel.toLowerCase()} responsibility for: ${objective}.`);
        requireValue(id, row, { id: `explicit-${conversation.conversationId || "orchestration"}-${role}-${index + 1}`, roleId: role, role, label: roleLabel, brief: goal, goal, runtime: route.runtimeId || route.runtime || c || "hermes", routeSelection: route, status: "ready" });
      });
    } else if (graph.preset?.id === "lead-workers") {
      const count = Math.trunc(Math.min(4, Math.max(2, Number(graph.preset.workerCount) || 2))), expected = ["lead", ...Array(count).fill("worker"), ...(graph.preset.sequentialIntegration ? ["integration"] : []), "barrier"];
      requireValue(id, result?.map(row => row.roleId), expected);
      result.forEach(row => { const node = list(graph.nodes).find(node => String(node?.title || "").trim() === row.label); if (node) requireValue(id, [row.goal, row.runtime, row.status], [String(node.objective || row.brief), String(node.runtime || "codex"), String(node.lifecycleStage || node.status || (row.roleId === "lead" ? "ready" : "queued"))]); });
    } else requireValue(id, result, b || []);
  } else if (id === "transparency.transition") {
    if (!levels.has(c?.level)) throw new FrontendContractError(id, "Unknown transparency level must be rejected");
    requireValue(id, result, { ...a, transparency: c.level });
  } else if (id === "transparency.persistence") {
    requireValue(id, result, { level: a, key: "nx.os.transparency", value: JSON.stringify(a) });
  } else if (id === "marketplace.snapshots") {
    const catalog = object(a), toolchain = object(b), catalogValid = catalog.schema === "neyvia.installed-module-catalog/v1", toolchainValid = toolchain.schema === "neyvia.marketplace-toolchain-snapshot/v1", source = catalogValid ? list(catalog.modules) : [];
    requireValue(id, result?.schema, "neyvia.marketplace-operator-view/v1");
    requireValue(id, [result?.catalogSchema, result?.toolchainSchema, result?.activationGateReady], [catalogValid ? catalog.schema : null, toolchainValid ? toolchain.schema : null, toolchainValid && toolchain.activationGateReady === true]);
    requireValue(id, result?.errors?.length, Number(!catalogValid) + Number(!toolchainValid));
    requireValue(id, result?.modules?.length, source.length);
    const counts = { moduleCount: source.length, activeCount: 0, disabledCount: 0, installedCount: 0, blockedCount: 0 };
    for (let index = 0; index < source.length; index++) {
      const item = object(source[index]), view = result.modules[index], state = label(item.state, "unknown"), reasons = [String(item.integrityError || "").trim(), ...list(item.securityErrors).map(value => label(value))].filter(Boolean), blocked = state.includes("blocked") || reasons.length > 0, actions = object(item.actions), previous = String(item.previousVersion || "").trim(), trust = object(item.publisherTrust), signature = object(item.signatureReceipt), staging = object(item.staging);
      for (const key of ["active", "disabled", "installed"]) if (state === key) counts[`${key}Count`]++;
      if (blocked) counts.blockedCount++;
      requireValue(id, [view.id, view.state, view.blocked, view.blockedReasons, view.previousVersion, view.permissions], [label(item.moduleId), state, blocked, reasons, previous, list(item.permissions)]);
      requireValue(id, view.actions, { activate: actions.activate === true && !blocked && state !== "active", disable: actions.disable === true && state === "active", rollback: actions.rollback === true && Boolean(previous) });
      requireValue(id, view.activation.allowed, view.actions.activate);
      requireValue(id, [view.trust.state, view.signature.state, view.signature.toolReady, view.staging.state], [trust.trusted === true ? "Trusted" : trust.state === "untrusted" ? "Untrusted" : label(trust.state), signature.state === "verified" ? "Verified" : signature.state === "blocked" ? "Blocked" : signature.state === "missing" ? "Missing" : "Not reported", toolchainValid && toolchain.tools?.cosign?.healthy === true, staging.state === "staged" || state === "staged" ? "Staged" : staging.state === "none" ? "None" : "Not reported"]);
    }
    for (const [key, value] of Object.entries(counts)) requireValue(id, result[key], value);
    const names = toolchainValid ? ["cosign", "syft", "grype", "defender", "wasmtime"] : [];
    requireValue(id, result.tools?.map(tool => tool.name), names);
    names.forEach((name, index) => requireValue(id, result.tools[index], { name, healthy: toolchain.tools?.[name]?.healthy === true, status: toolchain.tools?.[name]?.healthy === true ? "Verified locally" : "Unavailable or hash mismatch", detail: label(toolchain.tools?.[name]?.reason || toolchain.tools?.[name]?.error || toolchain.tools?.[name]?.path) }));
  } else if (id === "embed.mount") {
    const item = a.workspaces.find(row => row.workspaceId === b);
    requireValue(id, result, Boolean(item && retained(item.state) && (item.state !== "collapsed" || item.retainsState === true)));
  } else if (id === "embed.visible") requireValue(id, result, a.workspaces.filter(item => retained(item.state) && (b?.parentSessionId == null || item.parentSessionId === String(b.parentSessionId)) && (b?.parentMissionId == null || item.parentMissionId === String(b.parentMissionId))));
  else if (id === "embed.fullscreen") requireValue(id, result, a.workspaces.find(item => item.state === "open" && item.presentation === "fullscreen") || null);
  else if (id === "embed.host") requireValue(id, result, { schema: "neyvia.embedded.workspace.v1", workspaces: [], focusedId: null, retainedLimit: Math.max(1, Number(a?.retainedLimit) || 4) });
  else if (id.startsWith("embed.")) {
    if (!result?.workspaces || result.schema !== a.schema || result.retainedLimit !== a.retainedLimit) throw new FrontendContractError(id, "Embedded host lost its identity or retention policy");
    const count = result.workspaces.filter(row => retained(row.state)).length;
    if (id === "embed.open" && count > a.retainedLimit) throw new FrontendContractError(id, "Embedded retention exceeded its bound");
    const sourceId = id === "embed.open" ? b?.workspaceId ? a.workspaces.find(row => retained(row.state) && identity(row) === identity(b))?.workspaceId || b.workspaceId : null : b;
    const item = result.workspaces.find(row => row.workspaceId === sourceId), before = a.workspaces.find(row => row.workspaceId === sourceId);
    if (id === "embed.open") {
      if (!b?.workspaceId) requireValue(id, result, a);
      else {
        requireValue(id, result.focusedId, b.state === "blocked" && !before ? a.focusedId : sourceId);
        requireValue(id, item?.state, b.state === "blocked" && !before ? "blocked" : "open");
        requireValue(id, item?.lineage, (before || b).lineage);
        requireValue(id, [item?.presentation, item?.restorePresentation], before ? [b.presentation || before.presentation, b.presentation || before.restorePresentation] : [b.presentation, b.restorePresentation]);
        requireValue(id, result.workspaces.filter(row => retained(row.state) && identity(row) === identity(b)).length, b.state === "blocked" && !before ? 0 : 1);
      }
    } else {
      const adapter = adapters.find(row => row.id === before?.adapterId);
      if (before) {
        requireValue(id, item?.lineage, before.lineage);
        if (id === "embed.collapse" && retained(before.state)) requireValue(id, [item.state, item.presentation], ["collapsed", before.restorePresentation]);
        if (id === "embed.focus") requireValue(id, item.state, before.state === "collapsed" ? "open" : before.state);
        if (id === "embed.expand") {
          const target = ["inline-card", "dock-right", "dock-left", "floating-center", "fullscreen"].includes(String(c || "").trim()) ? String(c).trim() : "fullscreen";
          requireValue(id, [item.state, item.presentation, item.restorePresentation], !retained(before.state) || (adapter && !adapter.presentations.includes(target)) ? [before.state, before.presentation, before.restorePresentation] : ["open", target, before.presentation === "fullscreen" ? before.restorePresentation : before.presentation]);
        }
        if (id === "embed.restore") requireValue(id, [item.state, item.presentation], retained(before.state) ? ["open", before.restorePresentation] : [before.state, before.presentation]);
        if (id === "embed.close") requireValue(id, [item.state, item.closedReason], ["closed", String(c || "")]);
      }
      requireValue(id, result.workspaces.filter(row => row.workspaceId !== sourceId), a.workspaces.filter(row => row.workspaceId !== sourceId));
      const refusedTransition = ["embed.focus", "embed.expand", "embed.restore"].includes(id) && (!before || !retained(before.state));
      requireValue(id, result.focusedId, refusedTransition ? a.focusedId : ["embed.collapse", "embed.close"].includes(id) ? a.focusedId === sourceId ? null : a.focusedId : sourceId);
    }
  } else throw new FrontendContractError(id, "Undeclared presentation contract");
  return result;
}
