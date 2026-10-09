import { useEffect, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import "./NeyviaPromptEditorDialog.css";
import { readPromptImport } from "./promptFileImport.js";

const ROLES = ["common", "chat", "reader", "planner", "executor", "verifier"];
const MAX_PROMPT_CHARACTERS = 100_000;
const SYSTEM_PROMPT_RUNTIMES = new Set(["neyvia-agent", "neyvia", "own", "codex", "codex-cli", "openai-codex", "opencode", "open-code", "opencode-native", "opencode-go", "claude", "claude-code"]);
const promptKey = (scopeId, role) => `${scopeId}::${role}`;

function instructionsFor(library, role) {
  return String(role === "common" ? library?.common?.instructions || "" : library?.roles?.[role]?.instructions || "");
}
function scopedInstructions(library, scopeId, role) {
  return String(library?.scopes?.[scopeId]?.roles?.[role]?.instructions || "");
}
function globalEffectivePrompt(library, role) {
  const composition = library?.composition?.[role];
  if (composition?.mode === "role-replaces-defaults") return instructionsFor(library, role);
  if (composition?.mode === "shared-replaces-defaults") return instructionsFor(library, "common");
  return `${instructionsFor(library, "common")}\n\n${instructionsFor(library, role)}`;
}
function inheritedPrompt(library, scopeId, role) {
  const index = (library?.scopeOptions || []).findIndex(item => item.id === scopeId);
  for (let cursor = index - 1; cursor >= 0; cursor--) {
    const prompt = scopedInstructions(library, library.scopeOptions[cursor].id, role);
    if (prompt) return prompt;
  }
  return globalEffectivePrompt(library, role);
}
function scopeDescriptor(library, scopeId) {
  const kind = library?.scopeOptions?.find(item => item.id === scopeId)?.kind;
  const route = library?.activeRoute || {};
  if (kind === "runtime") return { runtime: route.runtime, provider: null, model: null };
  if (kind === "provider") return { runtime: null, provider: route.provider, model: null };
  if (kind === "model") return { runtime: null, provider: route.provider, model: route.model };
  if (kind === "route") return { runtime: route.runtime, provider: route.provider, model: route.model };
  return { runtime: null, provider: null, model: null };
}

export function NeyviaPromptEditorDialog({ callBackend, initialRole = "chat", activeRoute, onClose }) {
  const dialog = useRef(null);
  const fileInput = useRef(null);
  const [library, setLibrary] = useState(null);
  const [role, setRole] = useState(ROLES.includes(initialRole) ? initialRole : "chat");
  const [scopeId, setScopeId] = useState("global");
  const [drafts, setDrafts] = useState({});
  const [state, setState] = useState("loading");
  const [error, setError] = useState("");
  const [fileName, setFileName] = useState("");
  const [alternatePicker, setAlternatePicker] = useState(false);

  const callPromptBackend = async (command, payload = {}) => {
    const data = await callBackend(command, payload, { throwOnError: true });
    if (data == null) throw new Error(`${command} returned no data. Check that the desktop backend is running, then retry.`);
    return data;
  };
  const loadLibrary = () => callPromptBackend("get_agent_prompt_library_command", {
    runtime: activeRoute?.runtime, provider: activeRoute?.provider, model: activeRoute?.model,
  });
  const hydrate = data => {
    setLibrary(data);
    setScopeId(current => data.scopeOptions?.some(item => item.id === current) ? current : "global");
    setDrafts(current => {
      const next = { ...current };
      for (const item of ROLES) {
        const key = promptKey("global", item);
        if (!(key in next)) next[key] = instructionsFor(data, item);
      }
      return next;
    });
    setState("ready");
  };
  const savedFor = (selectedScope, selectedRole) => selectedScope === "global"
    ? instructionsFor(library, selectedRole)
    : scopedInstructions(library, selectedScope, selectedRole) || inheritedPrompt(library, selectedScope, selectedRole);
  const dirty = selectedRole => selectedScopeDirty(scopeId, selectedRole);
  const selectedScopeDirty = (selectedScope, selectedRole) => Boolean(library
    && !(selectedScope !== "global" && selectedRole === "common")
    && (drafts[promptKey(selectedScope, selectedRole)] ?? savedFor(selectedScope, selectedRole)) !== savedFor(selectedScope, selectedRole));
  const dirtyRoles = ROLES.filter(item => selectedScopeDirty(scopeId, item));
  const allDirtyEntries = Object.entries(drafts).filter(([key, value]) => {
    const splitAt = key.lastIndexOf("::");
    if (splitAt < 0) return false;
    const savedScope = key.slice(0, splitAt);
    const savedRole = key.slice(splitAt + 2);
    return ROLES.includes(savedRole) && selectedScopeDirty(savedScope, savedRole) && value !== savedFor(savedScope, savedRole);
  });

  useEffect(() => {
    const element = dialog.current;
    if (element) element.showModal();
    return () => { if (element?.open) element.close(); };
  }, []);
  useEffect(() => {
    let active = true;
    loadLibrary().then(data => { if (active) hydrate(data); }).catch(cause => {
      if (!active) return;
      setError(String(cause?.message || cause));
      setState("error");
    });
    return () => { active = false; };
  }, [callBackend, activeRoute?.runtime, activeRoute?.provider, activeRoute?.model]);

  const draft = drafts[promptKey(scopeId, role)] ?? savedFor(scopeId, role);
  const roleDirty = dirty(role);
  const roleCanEdit = scopeId === "global" || role !== "common";
  const savedEffectivePrompt = scopeId === "global" ? globalEffectivePrompt(library, role === "common" ? "chat" : role)
    : scopedInstructions(library, scopeId, role) || inheritedPrompt(library, scopeId, role);
  const ownOverride = scopeId !== "global" && Boolean(scopedInstructions(library, scopeId, role));
  const close = () => {
    if (allDirtyEntries.length) {
      setError("There are " + allDirtyEntries.length + " unsaved prompt edit" + (allDirtyEntries.length === 1 ? "" : "s") + ". Save or discard them before closing.");
      return;
    }
    onClose();
  };
  const save = async () => {
    if (!library || !draft.trim() || !roleCanEdit) return;
    setState("saving"); setError("");
    try {
      const payload = scopeId === "global"
        ? role === "common"
          ? { expectedRevision: library.revision, common: { instructions: draft } }
          : { expectedRevision: library.revision, roles: { [role]: { instructions: draft } } }
        : { expectedRevision: library.revision, scopeId, ...scopeDescriptor(library, scopeId), role, instructions: draft };
      await callPromptBackend("save_agent_prompt_library_command", payload);
      const data = await loadLibrary();
      setLibrary(data);
      setDrafts(current => ({ ...current, [promptKey(scopeId, role)]: scopeId === "global" ? instructionsFor(data, role) : scopedInstructions(data, scopeId, role) }));
      setState("saved");
    } catch (cause) {
      setError(String(cause?.message || cause));
      setState("error");
    }
  };
  const reset = async () => {
    if (!library) return;
    setState("saving"); setError("");
    try {
      const payload = { role, expectedRevision: library.revision, ...(scopeId === "global" ? {} : { scopeId, ...scopeDescriptor(library, scopeId) }) };
      await callPromptBackend("reset_agent_prompt_library_command", payload);
      const data = await loadLibrary();
      setLibrary(data);
      setDrafts(current => ({ ...current, [promptKey(scopeId, role)]: scopeId === "global" ? instructionsFor(data, role) : inheritedPrompt(data, scopeId, role) }));
      setState("saved");
    } catch (cause) {
      setError(String(cause?.message || cause));
      setState("error");
    }
  };
  const applyPromptFile = (name, text) => {
    const content = String(text || "").replace(/^\uFEFF/, "");
    if (content.length > MAX_PROMPT_CHARACTERS) {
      setError(`This file has ${content.length.toLocaleString()} characters. The limit is ${MAX_PROMPT_CHARACTERS.toLocaleString()}.`);
      setFileName("");
      return;
    }
    setDrafts(current => ({ ...current, [promptKey(scopeId, role)]: content }));
    setFileName(name); setError(""); setState("ready");
  };
  const importPrompt = async event => {
    const file = event.target.files?.[0]; event.target.value = "";
    if (!file) return;
    try { const imported = await readPromptImport(file); applyPromptFile(imported.fileName, imported.text); }
    catch (cause) { setError(`Could not read ${file.name}: ${cause?.message || "file access failed"}`); setFileName(""); }
  };
  const importPromptFromExplorer = async () => {
    try {
      const selected = await invoke("import_agent_prompt_file_command");
      if (selected) applyPromptFile(selected.fileName, selected.text);
    } catch (cause) { setError(`The file picker couldn't open: ${String(cause?.message || cause)}. Choose a file below to try the other picker.`); setAlternatePicker(true); setFileName(""); }
  };
  const discardAll = () => {
    setDrafts(current => ({ ...current, ...Object.fromEntries(ROLES.map(item => [promptKey(scopeId, item), savedFor(scopeId, item)])) }));
    setFileName(""); setError("");
  };

  const options = library?.scopeOptions || [{ id: "global", kind: "global", label: "All runtimes and models" }];
  const resolution = library?.resolutions?.[role === "common" ? "chat" : role];
  const inherited = scopeId === "global" ? "" : inheritedPrompt(library, scopeId, role);
  const isInheritedDraft = scopeId !== "global" && !ownOverride && !roleDirty;

  return <dialog aria-label="Edit system prompts" className="neyvia-prompt-editor" onCancel={event => { event.preventDefault(); close(); }} ref={dialog}>
    <header>
      <div><span>AGENT BEHAVIOR</span><h2>Edit system prompts</h2><p>Choose a scope and role. Saved overrides apply to new turns; imported .txt and .md files stay editable before saving.</p></div>
      <button aria-label="Close prompt editor" onClick={close} type="button">×</button>
    </header>
    {state === "loading" ? <div role="status" className="neyvia-prompt-editor__loading"><span className="neyvia-prompt-editor__spinner" /> Loading your saved prompts…</div> : null}
    {error ? <p className="neyvia-prompt-editor__error" role="alert">{error}</p> : null}
    {state === "error" && !library ? <div className="neyvia-prompt-editor__retry"><button onClick={() => { setState("loading"); setError(""); loadLibrary().then(hydrate).catch(cause => { setError(String(cause?.message || cause)); setState("error"); }); }} type="button">Retry loading</button></div> : null}
    {library ? <>
      <label className="neyvia-prompt-editor__scope-label" htmlFor="neyvia-prompt-editor-scope">Apply prompt to</label>
      <select id="neyvia-prompt-editor-scope" className="neyvia-prompt-editor__scope" onChange={event => { setScopeId(event.target.value); setError(""); setFileName(""); }} value={scopeId}>
        {options.map(item => <option key={item.id} value={item.id}>{item.label}{library.scopes?.[item.id]?.roles?.[role] ? " · custom" : ""}</option>)}
      </select>
      {activeRoute?.runtime === "hermes" ? <p className="neyvia-prompt-editor__composition">Hermes receives this prompt in its system channel on each model call. Hermes base instructions remain; this is an additive overlay. Unsupported installations report an error instead of sending it as user text.</p> : activeRoute?.runtime && !SYSTEM_PROMPT_RUNTIMES.has(activeRoute.runtime) ? <p className="neyvia-prompt-editor__composition">This CLI adapter supplies the saved prompt as task context. Full system-prompt replacement is available with Neyvia Native, Codex, OpenCode and Claude Code.</p> : null}
      <div className="neyvia-prompt-editor__roles" role="tablist" aria-label="Prompt role">
        {ROLES.map(item => <button aria-disabled={scopeId !== "global" && item === "common"} aria-selected={role === item} disabled={scopeId !== "global" && item === "common"} key={item} onClick={() => { setRole(item); setError(""); setFileName(""); }} role="tab" type="button">{item[0].toUpperCase() + item.slice(1)}{selectedScopeDirty(scopeId, item) ? <span aria-label="unsaved edits" className="neyvia-prompt-editor__dirty-dot" /> : null}</button>)}
      </div>
      <p className="neyvia-prompt-editor__composition">{scopeId === "global"
        ? role === "common" ? "Shared instructions are used across roles; a custom role prompt is added after them." : `The global ${role} prompt uses the existing shared and role composition.`
        : `${ownOverride ? "This scope has its own complete prompt and replaces broader prompts." : "This scope inherits the nearest saved prompt; editing and saving creates a complete override."} ${role === "common" ? "Edit Common at the global scope." : ""}`}</p>
      {scopeId !== "global" ? <p className="neyvia-prompt-editor__scope-status" role="status">{isInheritedDraft ? "Using inherited prompt" : ownOverride ? "Custom prompt at this scope" : "Unsaved scope override"}{resolution?.hash ? ` · resolved ${resolution.hash.slice(0, 12)}` : ""}</p> : null}
      <details className="neyvia-prompt-editor__effective">
        <summary>View saved prompt for this scope</summary>
        <pre>{savedEffectivePrompt}</pre>
        <small>{scopeId === "global" ? "This is the global prompt composition." : inherited ? "Reset this scope to inherit the nearest broader prompt." : "This scope has no broader override."}</small>
      </details>
      <div className="neyvia-prompt-editor__field-head"><label htmlFor="neyvia-prompt-editor-content">{role === "common" ? "Shared system instructions" : `${role[0].toUpperCase() + role.slice(1)} system prompt`}</label><button disabled={state === "saving" || !roleCanEdit} onClick={() => isTauri() ? void importPromptFromExplorer() : fileInput.current?.click()} type="button">Import .txt or .md</button><input accept=".txt,.md,text/plain,text/markdown" aria-label="Import a text or Markdown system prompt" className="neyvia-prompt-editor__file" onChange={importPrompt} ref={fileInput} type="file" /></div>
      {fileName ? <p className="neyvia-prompt-editor__file-note">Imported {fileName}. Review or edit the text below, then save to apply it.</p> : null}
      {alternatePicker ? <button type="button" onClick={() => fileInput.current?.click()}>Choose a file</button> : null}
      <textarea aria-describedby="neyvia-prompt-editor-count" disabled={state === "saving" || !roleCanEdit} id="neyvia-prompt-editor-content" maxLength={MAX_PROMPT_CHARACTERS} onChange={event => { setDrafts(current => ({ ...current, [promptKey(scopeId, role)]: event.target.value })); setState("ready"); }} rows={14} value={draft} />
      <span className="neyvia-prompt-editor__count" id="neyvia-prompt-editor-count">{draft.length.toLocaleString()} / {MAX_PROMPT_CHARACTERS.toLocaleString()} characters</span>
      <footer>
        <span>Revision {library.revision}{allDirtyEntries.length ? " · " + allDirtyEntries.length + " unsaved edit" + (allDirtyEntries.length === 1 ? "" : "s") : state === "saved" ? " · Saved" : ""}</span>
        <div><button disabled={state === "saving" || !dirtyRoles.length} onClick={discardAll} type="button">Discard edits</button><button disabled={state === "saving" || (scopeId !== "global" && !ownOverride)} onClick={reset} type="button">{scopeId === "global" ? "Reset this role" : "Use inherited"}</button><button className="primary" disabled={state === "saving" || !roleDirty || !draft.trim()} onClick={save} type="button">{state === "saving" ? "Saving…" : scopeId === "global" ? "Save role" : "Save override"}</button></div>
      </footer>
    </> : null}
  </dialog>;
}
