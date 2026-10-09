import { useEffect, useRef, useState } from "react";
import { usePoller } from "./usePoller.js";
import { parseBatchPrompts } from "./neyviaHarnessBatchModel.js";

const ACTIVE = new Set(["running", "cancelling"]);

export function NeyviaHarnessBatches({ callBackend, workspacePath, harness, profile, onInspectJob }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [model, setModel] = useState("");
  const [provider, setProvider] = useState("");
  const [parallel, setParallel] = useState(2);
  const [turns, setTurns] = useState(4);
  const [seconds, setSeconds] = useState(120);
  const [record, setRecord] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef(null);
  const revision = useRef(0);
  const editable = !record;
  const supported = harness && !harness.securityOnly && harness.harnessId !== "fluxio-hybrid";

  useEffect(() => {
    const suggested = profile?.model || harness?.defaultModel || "";
    setModel(["provider-selected", "route-selected", "profile-selected", "auto"].includes(suggested) ? "" : suggested);
    setProvider(profile?.providerId || (harness?.harnessId === "neyvia-agent" ? "openai-codex" : harness?.executionAdapter || ""));
    request.current = null;
  }, [harness?.harnessId, profile?.model, profile?.providerId]);

  // Fast while a batch runs, slow otherwise; both back off when nothing changes and pause when hidden.
  const batchRunning = ACTIVE.has(record?.status);
  usePoller(async () => {
    const data = await callBackend("list_harness_batches_command");
    const next = record?.id && batchRunning ? await callBackend("get_harness_batch_command", { batchId: record.id }) : null;
    return { batches: data.batches || [], next };
  }, {
    enabled: Boolean(open), activeMs: batchRunning ? 2500 : 15000, maxMs: batchRunning ? 10000 : 60000,
    onValue: ({ batches, next }) => { setHistory(batches); if (next) setRecord(next); },
    onError: e => setError(e.message || String(e)),
  });

  const perform = async action => {
    if (busy) return;
    setBusy(true); setError("");
    const currentRevision = ++revision.current;
    try {
      const result = await action();
      if (currentRevision === revision.current) setRecord(result);
    } catch (e) { setError(e.message || String(e)); }
    finally { setBusy(false); }
  };
  const prepare = () => perform(() => {
    const prompts = parseBatchPrompts(text);
    const payload = { runtime: harness.harnessId, workspacePath, prompts, model, provider,
      harnessProfileId: profile?.id || "", maxParallel: parallel, maxTurns: turns, runtimeBudgetSeconds: seconds };
    const fingerprint = JSON.stringify(payload);
    if (request.current?.fingerprint !== fingerprint) request.current = { fingerprint, id: `batch_${Date.now()}_${Math.random().toString(36).slice(2)}` };
    return callBackend("prepare_harness_batch_command", { ...payload, requestId: request.current.id });
  });
  const download = () => {
    const content = record.items.map(item => JSON.stringify({ ...item, batchId: record.id, runtime: record.runtime, model: record.model })).join("\n") + "\n";
    const url = URL.createObjectURL(new Blob([content], { type: "application/x-ndjson" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${record.id}.jsonl`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return <details className="neyvia-harness-batches" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary><strong>Prompt batches</strong><span>Prepare several prompts · set limits · inspect each result</span></summary>
    {open ? <div className="neyvia-harness-batches__body">
      <p>Each prompt gets a separate, read-only job and receipt. Preparation makes no model calls. Starting runs the exact route shown, within the workspace’s existing capacity limits.</p>
      {editable ? <>
        {!supported ? <p role="status">Select a general-purpose harness above to prepare a prompt batch.</p> : null}
        <label>Prompts<textarea aria-label="Batch prompts" value={text} onChange={event => setText(event.target.value)} placeholder={'One prompt per line, or JSONL: {"prompt":"Review the README"}'} rows={4} disabled={busy} /></label>
        <div className="neyvia-harness-batches__fields">
          <label>Exact model<input aria-label="Batch model" value={model} onChange={event => setModel(event.target.value)} disabled={busy} /></label>
          <label>Provider<input aria-label="Batch provider" value={provider} onChange={event => setProvider(event.target.value)} disabled={busy} /></label>
          <label>Concurrent jobs<select aria-label="Batch concurrency" value={parallel} onChange={event => setParallel(Number(event.target.value))} disabled={busy}>{[1,2,3,4].map(n => <option key={n} value={n}>{n}</option>)}</select></label>
          {harness?.harnessId === "neyvia-agent" ? <label>Turns per prompt<input aria-label="Batch turn limit" type="number" min="1" max="20" value={turns} onChange={event => setTurns(Number(event.target.value))} disabled={busy} /></label> : null}
          <label>Seconds per prompt<input aria-label="Batch time limit" type="number" min="30" max="300" value={seconds} onChange={event => setSeconds(Number(event.target.value))} disabled={busy} /></label>
        </div>
        <small>{harness?.harnessId === "neyvia-agent" ? "Medium effort · up to 1,024 output tokens per response." : "The external harness owns its turn and output settings."} The time limit includes job waiting and execution. Provider usage and cost depend on the selected route.</small>
        <button disabled={busy || !supported || !text.trim() || !model.trim() || !provider.trim()} onClick={prepare} type="button">Prepare batch</button>
      </> : <>
        <div className="neyvia-harness-batches__status" role="status"><strong>{record.status} · {record.items.length} prompts</strong><span>{record.runtime} · {record.model} · {record.maxParallel} concurrent</span></div>
        <p>{Object.entries(record.counts).map(([state, count]) => `${count} ${state}`).join(" · ")}</p>
        {record.error ? <p role="status">{record.error}</p> : null}
        <div className="neyvia-harness-batches__actions">
          {record.status === "prepared" || ACTIVE.has(record.status) ? <button disabled={busy} onClick={() => perform(() => callBackend("start_harness_batch_command", {batchId: record.id}))} type="button">{record.status === "prepared" ? "Start batch" : "Reconnect batch"}</button> : null}
          {record.status === "prepared" || ACTIVE.has(record.status) ? <button disabled={busy} onClick={() => perform(() => callBackend("cancel_harness_batch_command", {batchId: record.id}))} type="button">Cancel batch</button> : null}
          <button onClick={download} type="button">Export results</button>
          <button disabled={busy} onClick={() => { revision.current += 1; setRecord(null); request.current = null; }} type="button">New batch</button>
        </div>
        <ol className="neyvia-harness-batches__items">{record.items.map(item => <li key={item.jobId}><span>{item.prompt}</span><small>{item.status}</small>{item.receiptPath ? <button onClick={() => onInspectJob?.(item.jobId)} type="button">Inspect result {item.index + 1}</button> : null}{item.error ? <small>{item.error}</small> : null}</li>)}</ol>
      </>}
      {error ? <p role="alert">{error}</p> : null}
      {history.length ? <label>Saved batches<select aria-label="Saved batches" disabled={busy} value={record?.id || ""} onChange={event => { const id = event.target.value; if (id) void perform(() => callBackend("get_harness_batch_command", { batchId: id })); }}><option value="">Choose a saved batch</option>{history.map(item => <option key={item.id} value={item.id}>{item.title} · {item.status}</option>)}</select></label> : null}
      {harness?.harnessId === "hermes" ? <p>Hermes also has a separate dataset runner for training trajectories, toolset distributions and container images. <a href="https://hermes-agent.nousresearch.com/docs/user-guide/features/batch-processing/" target="_blank" rel="noreferrer">Hermes batch guide</a></p> : null}
    </div> : null}
  </details>;
}
