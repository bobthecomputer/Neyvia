import { useEffect, useRef, useState } from "react";
import { Brain, Plus, RefreshCw } from "lucide-react";
import { callNx } from "./nxApi.js";
import { Icon, IconButton } from "./nxPrimitives.jsx";
import "./nxMemory.css";

const emptyDraft = () => ({ key: "", content: "", kind: "fact", cues: "", cueFields: {}, expiresAt: "", exportPolicy: "local" });
const editable = row => ({ ...row, cueFields: row.cues, cues: (row.cues?.intent || [row.key]).join(", "),
  expiresAt: row.expiresAt ? new Date(new Date(row.expiresAt).getTime() - new Date(row.expiresAt).getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "" });

export function NxMemoryPanel({ session = null }) {
  const sessionId = session?.id || "";
  const [state, setState] = useState(null), [draft, setDraft] = useState(null);
  const [error, setError] = useState(""), [receipt, setReceipt] = useState("");
  const [busy, setBusy] = useState(false), [forget, setForget] = useState(null);
  const [query, setQuery] = useState(""), [preview, setPreview] = useState(null);
  const epoch = useRef(0), controller = useRef(null);
  const scope = { ...(sessionId ? { sessionId } : {}) };

  const read = async (token = epoch.current) => {
    const value = await callNx("memory_list_command", scope, { signal: controller.current?.signal });
    if (token === epoch.current) setState(value);
    return value;
  };
  useEffect(() => {
    const token = ++epoch.current;
    controller.current = new AbortController();
    setState(null); setDraft(null); setForget(null); setPreview(null); setQuery(""); setError(""); setReceipt(""); setBusy(false);
    void read(token).catch(err => { if (token === epoch.current && err.name !== "AbortError") setError(err.message); });
    return () => { ++epoch.current; controller.current?.abort(); };
  }, [sessionId]);

  const change = (key, value) => setDraft(current => ({ ...current, [key]: value }));
  const mutate = async (operation, payload) => {
    const token = epoch.current;
    setBusy(true); setError(""); setReceipt("");
    try {
      await callNx(`memory_${operation}_command`, { ...scope, ...payload, requestId: crypto.randomUUID() }, { signal: controller.current?.signal });
      if (token !== epoch.current) return;
      setDraft(null); setForget(null); setPreview(null);
      await read(token);
      if (token === epoch.current) setReceipt(operation === "forget" ? "Forgotten. Earlier memory context needs a fresh chat." : "Saved on this PC.");
    } catch (err) {
      if (token !== epoch.current || err.name === "AbortError") return;
      setError(err.code === "memory_revision_conflict" ? "Someone changed this memory. Your draft is kept; reload the current version before saving." : err.message);
      await read(token).catch(() => {});
    } finally { if (token === epoch.current) setBusy(false); }
  };
  const save = event => {
    event.preventDefault();
    const payload = { key: draft.key, content: draft.content, kind: draft.kind,
      cues: { ...draft.cueFields, intent: draft.cues.split(",").map(item => item.trim()).filter(Boolean) },
      expiresAt: draft.expiresAt ? new Date(draft.expiresAt).toISOString() : null, exportPolicy: draft.exportPolicy };
    if (draft.id) Object.assign(payload, { id: draft.id, expectedRevision: draft.revision });
    void mutate(draft.id ? "correct" : "remember", payload);
  };
  const recall = async event => {
    event.preventDefault();
    const token = epoch.current;
    setBusy(true); setError("");
    try {
      const value = await callNx("memory_recall_command", { ...scope, situation: { intent: query }, budget: 256 }, { signal: controller.current?.signal });
      if (token === epoch.current) setPreview(value);
    } catch (err) { if (token === epoch.current && err.name !== "AbortError") setError(err.message); }
    finally { if (token === epoch.current) setBusy(false); }
  };

  return <section className="nx-memory nx-scroll" aria-label="Memory">
    <header className="nx-memory-head"><div><h2><Icon as={Brain} size={18} /> Memory</h2>
      <p>{state ? `${state.scope.user} · ${session?.project || state.scope.project.split(/[\\/]/).pop()}` : "Reading your project…"}</p></div>
      <IconButton icon={RefreshCw} label="Refresh memories" disabled={busy} onClick={() => void read().catch(err => setError(err.message))} />
    </header>
    <p className="nx-memory-note">Saved on this PC. Only memories you allow in agent context can be sent to your selected model.</p>
    {error ? <p role="alert" className="nx-memory-error">{error}</p> : null}
    {receipt ? <p role="status">{receipt}</p> : null}
    {state && !draft ? <button type="button" className="nx-memory-add" onClick={() => { setDraft(emptyDraft()); setError(""); }}><Icon as={Plus} size={14} /> Remember something</button> : null}
    {draft ? <form className="nx-memory-editor" onSubmit={save}>
      <h3>{draft.id ? "Edit memory" : "New memory"}</h3>
      <label>Subject<input required maxLength={160} value={draft.key} onChange={event => change("key", event.target.value)} /></label>
      <label>Memory<textarea aria-label="Memory" required maxLength={2000} rows={4} value={draft.content} onChange={event => change("content", event.target.value)} /></label>
      <label>Kind<select value={draft.kind} onChange={event => change("kind", event.target.value)}>{["fact", "preference", "procedure", "pitfall"].map(kind => <option key={kind}>{kind}</option>)}</select></label>
      <label>When needed <small>Separate cues with commas</small><input required value={draft.cues} onChange={event => change("cues", event.target.value)} placeholder="launch, release notes" /></label>
      <label>Forget after<input type="datetime-local" value={draft.expiresAt} onChange={event => change("expiresAt", event.target.value)} /></label>
      <label className="nx-memory-check"><input type="checkbox" checked={draft.exportPolicy === "provider"} onChange={event => change("exportPolicy", event.target.checked ? "provider" : "local")} /> Allow in agent context</label>
      <div className="nx-memory-actions"><button disabled={busy} type="submit">{busy ? "Saving…" : "Save memory"}</button>
        <button type="button" disabled={busy} onClick={() => setDraft(null)}>Cancel</button>
        {draft.id ? <button type="button" disabled={busy} onClick={() => { const latest = state?.memories.find(row => row.id === draft.id); if (latest) { setDraft(editable(latest)); setError(""); } }}>Reload current version</button> : null}</div>
    </form> : null}
    <div className="nx-memory-list">
      {state?.memories.length === 0 ? <p>No memories in this project yet. Add one here, or use <code>/remember subject = fact</code> in chat. Add <code>--share</code> to allow agent context.</p> : null}
      {state?.memories.map(row => <article key={row.id} className="nx-memory-row" data-memory-id={row.id}>
        <h3>{row.key}</h3><p className="nx-memory-content">{row.content}</p>
        <span className="nx-memory-meta">{row.kind} · {row.status === "pending" ? "Waiting for your review" : row.expiresAt && row.expiresAt <= new Date().toISOString() ? "Expired" : "Active"} · {row.exportPolicy === "provider" ? "Agent context allowed" : "Local only"}</span>
        <details><summary>When and why</summary><p>Cues: {Object.entries(row.cues).map(([key, values]) => `${key}: ${values.join(", ")}`).join(" · ")}</p>
          <p>Source: {row.provenance.kind} · {row.provenance.sourceId || "Memory panel"}</p><p>Revision {row.revision}{row.expiresAt ? ` · Expires ${new Date(row.expiresAt).toLocaleString()}` : ""}</p></details>
        <div className="nx-memory-actions"><button type="button" disabled={busy} onClick={() => { setDraft(editable(row)); setForget(null); setError(""); }}>Edit</button>
          <button type="button" disabled={busy} onClick={() => setForget(row)}>Forget</button></div>
        {forget?.id === row.id ? <div className="nx-memory-confirm"><p>Forget this memory? Its saved content and cues will be removed.</p>
          <button type="button" disabled={busy} onClick={() => void mutate("forget", { id: row.id, expectedRevision: row.revision })}>Forget this memory</button>
          <button type="button" onClick={() => setForget(null)}>Keep memory</button></div> : null}
      </article>)}
    </div>
    {state ? <form className="nx-memory-preview" onSubmit={recall}><label>Check what comes to mind<input value={query} onChange={event => setQuery(event.target.value)} required placeholder="What are you working on?" /></label><button type="submit" disabled={busy}>Preview recall</button>
      {preview ? <div role="status"><p>{preview.selected.length ? `${preview.selected.length} recalled` : "No matching memory"} · {preview.tokens}/{preview.budget} tokens · {preview.route}</p>
        {preview.selected.map(row => <p key={row.id}>{state.memories.find(memory => memory.id === row.id)?.key}: {row.why.map(cue => cue.cue).join(", ")}</p>)}</div> : null}</form> : null}
  </section>;
}
