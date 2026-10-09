import { useCallback, useEffect, useRef, useState } from "react";
import { Check, FileUp } from "lucide-react";
import { backendBase } from "./nxApi.js";
import { LOCAL_DRAG } from "./nxDevicesModel.js";
import { Button, Icon, Spinner } from "./nxPrimitives.jsx";
import "./nxDocs.css";

const PART_LABELS = { formula: "FORMULA", when: "WHEN?", write: "WHAT DO I WRITE?", pattern: "PATTERN", course_example: "COURSE EXAMPLE", your_exercise: "YOUR EXERCISE", variations_traps: "VARIATIONS/TRAPS", pattern_drill: "Recognise the type", exercise_variant: "Changed exercise" };

// The seven parts every concept becomes, in study order (the first seven PART_LABELS).
const SEVEN_PARTS = ["Formula", "When?", "What do I write?", "Pattern", "Course example", "Your exercise", "Variations and traps"];

/** A note path carried by a drop: a file dragged from Files, a desktop file with a path, or a typed path. */
function droppedPath(dataTransfer) {
  const fromFiles = dataTransfer.getData(LOCAL_DRAG);
  if (fromFiles) return fromFiles;
  const file = dataTransfer.files?.[0];
  if (file?.path) return file.path;
  const text = dataTransfer.getData("text/plain").trim();
  return /^([A-Za-z]:[\\/]|\\\\|~?\/)[^\n]*$/.test(text) ? text : "";
}

// User and bot operate the same durable draft, job, review and approved archive.
async function studyCall(operation, args = {}) {
  const response = await fetch(`${backendBase()}/api/ui/scroll`, {
    method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ operation, ...args }),
  });
  const result = await response.json();
  if (!response.ok || result.ok === false) throw new Error(result.error || `${operation} failed`);
  return result.data ?? result;
}

export function NxScrollStudy({ target }) {
  const [snapshot, setSnapshot] = useState({ packs: [], jobs: [] });
  const [pack, setPack] = useState(target || "");
  const [path, setPath] = useState("");
  const [subject, setSubject] = useState("math");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState("");
  const [validation, setValidation] = useState(null);
  const [over, setOver] = useState(false);
  const pathField = useRef(null);
  const refresh = useCallback(async () => {
    const value = await studyCall("state", pack ? { pack } : {});
    setSnapshot(value);
    if (!pack && value.packs.length) setPack(value.packs[0].id);
  }, [pack]);
  useEffect(() => { void refresh().catch(cause => setError(cause.message)); }, [refresh]);
  const job = snapshot.jobs.find(row => row.pack === pack && ["queued", "running"].includes(row.state));
  useEffect(() => {
    if (!job) return undefined;
    const timer = setInterval(() => void refresh().catch(cause => setError(cause.message)), 2000);
    return () => clearInterval(timer);
  }, [job?.id, refresh]);
  const run = async (operation, args = {}) => {
    setBusy(operation); setError("");
    try {
      const result = await studyCall(operation, { ...(pack && operation !== "import" ? { pack } : {}), ...args });
      if (operation === "import") setPack(result.pack.meta.id);
      if (operation === "validate") setValidation(result);
      if (operation === "preview") setPreview(`${backendBase()}${result.preview.url}`);
      await refresh();
    } catch (cause) { setError(cause.message); }
    finally { setBusy(""); }
  };
  const active = snapshot.active;
  const selected = snapshot.packs.find(row => row.id === pack);
  const cards = active?.review?.chapters.flatMap(chapter => chapter.cards) || [];
  const unavailable = Boolean(busy || job);
  const importNote = value => {
    const note = String(value ?? path).trim();
    if (!note) { pathField.current?.focus(); return; }
    setPath(note);
    void run("import", { paths: [note], subject });
  };
  const allApproved = cards.length > 0 && cards.every(card => card.status === "approved");
  const steps = [
    { op: "concepts", label: "Confirm concepts", ready: Boolean(pack), go: () => run("concepts") },
    { op: "generate", label: "Generate seven parts", ready: Boolean(active?.graph?.concepts.length), go: () => run("generate", { requestId: `study-${crypto.randomUUID()}` }) },
    { op: "validate", label: "Check pack", ready: cards.length > 0, go: () => run("validate") },
    { op: "preview", label: "Study approved pack", ready: allApproved, go: () => run("preview") },
  ];
  // The step to do now: the last one whose inputs exist (none until a pack is chosen).
  const current = pack ? steps.reduce((at, step, index) => (step.ready ? index : at), 0) : -1;
  return <div className="nx-scroll-study">
    <div className="nx-docs-bar nx-sst-bar">
      <input ref={pathField} className="nx-input nx-sst-path" aria-label="Study note path" placeholder="Markdown or text note path" value={path}
        onChange={event => setPath(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !unavailable) importNote(); }} />
      <select className="nx-input nx-sst-select" aria-label="Study subject" value={subject} onChange={event => setSubject(event.target.value)}><option value="math">Maths</option><option value="physics">Physics</option></select>
      <Button variant="outline" disabled={unavailable || !path.trim()} onClick={() => importNote()}>Import note</Button>
      <select className="nx-input nx-sst-select nx-sst-pack" aria-label="Study pack" value={pack} onChange={event => { setPack(event.target.value); setValidation(null); setPreview(""); }}><option value="">Choose a pack</option>{snapshot.packs.map(row => <option key={row.id} value={row.id}>{row.title}</option>)}</select>
    </div>
    <div className="nx-docs-bar nx-sst-stepbar">
      <ol className="nx-sst-steps" aria-label="Study pack steps">
        {steps.map((step, index) => {
          const done = index < current;
          const state = done ? "is-done" : index === current ? "is-current" : "is-future";
          return <li key={step.op} className={state}>
            <button type="button" className="nx-sst-step" disabled={unavailable || !step.ready} aria-current={index === current ? "step" : undefined} onClick={step.go}>
              <span className="nx-sst-num" aria-hidden="true">{done ? <Icon as={Check} size={12} /> : index + 1}</span>
              <span className="nx-sst-label">{step.label}</span>
            </button>
          </li>;
        })}
      </ol>
      {busy || job ? <span className="nx-sst-status" role="status"><Spinner size={14} /> {job ? `${job.stage}: ${job.progress.done}/${job.progress.total}` : busy}</span> : null}
      {selected?.cost?.costPerCard?.tokens != null ? <span className="nx-sst-status">{Math.round(selected.cost.costPerCard.tokens)} tokens/card</span> : null}
    </div>
    {error ? <p className="nx-sst-note is-alert" role="alert">{error}</p> : null}
    {snapshot.jobs.filter(row => row.pack === pack && row.state === "failed").slice(0, 1).map(row => <p className="nx-sst-note is-alert" role="alert" key={row.id}>{row.error}</p>)}
    {validation ? <p className="nx-sst-note" role="status">{validation.ok ? "All pack checks passed." : validation.errors.map(item => `${item.rule}: ${item.message}`).join("; ")}</p> : null}
    <div className="nx-scroll-study-content">
      {preview ? <iframe title="Scroll Study approved pack" src={preview} width="100%" height="640" /> : null}
      {!cards.length && !preview ? <div className="nx-sst-empty">
        <div className={`nx-sst-drop${over ? " is-over" : ""}`} role="group" aria-label="Import a note"
          onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={event => {
            event.preventDefault(); setOver(false);
            const note = droppedPath(event.dataTransfer);
            if (note) importNote(note); else setError("Drop a note from Files, or type its path above: this file has no path on this PC.");
          }}>
          <Icon as={FileUp} size={22} />
          <strong>{selected ? `${selected.title}: ${steps[Math.max(current, 0)].label.toLowerCase()} next` : "Import a note"}</strong>
          <p>Drop a Markdown or text note from Files here, or type its path above. Confirm its concepts, then generate the seven revision parts and review the real examples and exercises before studying.</p>
          {selected && current >= 0
            ? <Button variant="primary" disabled={unavailable || !steps[current].ready} onClick={steps[current].go}>{steps[current].label}</Button>
            : <Button variant="outline" icon={FileUp} disabled={unavailable} onClick={() => importNote()}>Import a note</Button>}
        </div>
        <div className="nx-sst-parts">
          <span className="nx-sst-parts-title">Every concept becomes seven parts</span>
          <ol>{SEVEN_PARTS.map((part, index) => <li key={part}><span className="nx-sst-num" aria-hidden="true">{index + 1}</span>{part}</li>)}</ol>
        </div>
      </div> : null}
      {active?.review?.chapters.map(chapter => <section key={chapter.id}>
        <h3>{chapter.name}</h3>
        {chapter.cards.map(row => <details key={row.id}>
          <summary>{PART_LABELS[row.type] || row.type} · {row.card.title} · {row.status}</summary>
          <p>{row.card.body}</p>
          {row.card.steps?.map((step, index) => <p key={index}>{index + 1}. {step.text}</p>)}
          {row.card.back ? <p>Solution: {row.card.back}</p> : null}
          {row.card.answerCheck ? <p>Independent solution check: {row.card.answerCheck.ok ? "passed" : "needs review"}</p> : null}
          {row.flag ? <p role="alert">{row.flag.message}</p> : null}
          <Button disabled={unavailable || row.status === "approved"} onClick={() => run("review", { decisions: [{ cardId: row.id, action: "approve" }] })}>Approve this card</Button>
        </details>)}
      </section>)}
    </div>
  </div>;
}
