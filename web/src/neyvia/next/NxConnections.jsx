import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, ChevronRight, ExternalLink, HardDrive, KeyRound, RefreshCw, TriangleAlert } from "lucide-react";

import { backendBase, callNx } from "./nxApi.js";
import { getOs, os } from "./nxOsStore.js";
import { ProviderMark, resolveProviderMarkId } from "./ProviderMark.jsx";
import { Button, Icon, Spinner, StatusDot, ago } from "./nxPrimitives.jsx";
import { connectionHeadline, connectionTone, describeStep, mergeProof } from "./nxConnectionsModel.js";
import "./nxConnections.css";

// One simple list of every way Neyvia reaches a model: your Claude and ChatGPT plans, other coding
// agents, API keys, local models. Each row says plainly whether it works and has one button that
// does the next thing: sign in (opens the provider's own sign-in in your terminal), install,
// check again, or test it (one real prompt and one real tool call, run for you). The same
// component sits on the Runtime page and in first-run setup (props: compact, onConnected).

const KeysQueue = lazy(() => import("../NeyviaProviderAuthQueue.jsx"));

function clearApproval(approvalId) {
  const clear = () => { for (const notice of getOs().notices.filter(row => row.approvalId === approvalId)) os.dismiss(notice.id); };
  clear();
  setTimeout(clear, 1200); // the bus notice can arrive after the card's own consent
}

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

async function api(body) {
  const response = await fetch(`${base()}/api/ui/connections`, body ? {
    method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : { credentials: "include" });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) throw new Error(result?.error || `Connection check failed (HTTP ${response.status})`);
  return result?.data ?? result;
}

function Mark({ card }) {
  if (card.kind === "keys") return <span className="nx-cn-mark"><Icon as={KeyRound} size={18} /></span>;
  if (card.kind === "local") return <span className="nx-cn-mark"><Icon as={HardDrive} size={18} /></span>;
  const mark = resolveProviderMarkId(card.id);
  if (mark) return <span className="nx-cn-mark"><ProviderMark id={mark} size={20} /></span>;
  return <span className="nx-cn-mark nx-cn-letter" aria-hidden="true">{card.label.slice(0, 1)}</span>;
}

function Steps({ proof, proving }) {
  const steps = proving ? [] : proof?.steps || [];
  if (!steps.length) return null;
  return (
    <ol className="nx-cn-steps" aria-label="What the test did">
      {steps.map((step, index) => (
        <li key={`${step.step}-${index}`} className={step.ok ? "is-ok" : "is-bad"}>
          <Icon as={step.ok ? Check : TriangleAlert} size={13} />
          <span><b>{describeStep(step.step)}.</b> {step.detail}</span>
        </li>
      ))}
    </ol>
  );
}

function Card({ card, waiting, onConnect, onStopWaiting, onInstall, consent, onConsent, onProve, onRecheck, onKeys, error, compact }) {
  const [open, setOpen] = useState(false);
  const proving = Boolean(card.proving);
  const proof = mergeProof(card);
  const tone = connectionTone(card, proving, waiting);
  const fix = card.fix;
  const link = <a className="nx-btn nx-btn-outline nx-btn-sm" href={fix?.url} target="_blank" rel="noreferrer"><span className="nx-btn-label">{fix?.label}</span></a>;
  let action = null;
  if (card.state === "installing") action = <Button size="sm" loading>Installing…</Button>;
  else if (waiting) action = <><Button size="sm" loading>Waiting for sign-in</Button><Button size="sm" variant="ghost" onClick={() => onStopWaiting(card)}>Stop waiting</Button></>;
  else if (proving) action = <Button size="sm" loading>{describeStep(card.proving.step)}</Button>;
  else if (card.state === "needs-signin" && ["terminal", "provider"].includes(fix?.kind)) action = <Button size="sm" variant="outline" onClick={() => onConnect(card)}>{fix.label}</Button>;
  else if (card.state === "needs-signin" && fix?.kind === "keys") action = <Button size="sm" variant="outline" onClick={onKeys}>{fix.label}</Button>;
  else if (card.state === "needs-signin" && fix?.kind === "link") action = link;
  else if (fix?.kind === "install") action = <Button size="sm" variant="outline" disabled={Boolean(consent)} onClick={() => onInstall(card)}>{fix.label || "Install"}</Button>;
  else if (card.state === "not-installed" && fix?.kind === "link") action = link;
  else if (card.state === "broken" && fix?.kind === "terminal") action = <Button size="sm" variant="outline" onClick={() => onConnect(card)}>{fix.label}</Button>;
  else if (card.state === "broken") action = <Button size="sm" variant="outline" onClick={onRecheck}>Check again</Button>;
  else if (fix?.kind === "recheck") action = <Button size="sm" variant="outline" onClick={onRecheck}>{fix.label}</Button>;
  else if (card.state === "connected" && card.provable) action = <Button size="sm" variant={proof?.ok ? "ghost" : "primary"} onClick={() => onProve(card, false)}>{proof ? "Test again" : "Test it"}</Button>;
  else if (card.kind === "keys" && card.state === "connected") action = <Button size="sm" onClick={onKeys}>{fix?.label || "Add or change keys"}</Button>;

  const headline = connectionHeadline(card, proof, waiting, proving);
  return (
    <li className={`nx-cn-card is-${card.state}${open ? " is-open" : ""}`} data-connection={card.id} data-state={card.state} data-proven={proof?.ok ? "yes" : "no"}>
      <div className="nx-cn-line">
        <Mark card={card} />
        <div className="nx-cn-text">
          <div className="nx-cn-name">
            <span>{card.label}</span>
            <span className={`nx-cn-state nx-cn-${tone}`}>{proving || waiting || card.state === "checking" || card.state === "installing" ? <Spinner size={11} /> : <StatusDot tone={tone} />}{headline.state}</span>
          </div>
          <p className="nx-cn-why">{headline.why}</p>
          {card.updates ? <p className="nx-cn-note">{card.updates}</p> : null}
          {consent ? <div className="nx-cn-confirm" role="group" aria-label={`Install ${card.label}`}>
            <span>Allow Neyvia to download {card.label} and any missing prerequisites? Installation runs quietly. Neyvia can keep it updated when tool updates are enabled in Settings.</span>
            <Button size="sm" onClick={() => onConsent(card, true)}>Allow install</Button>
            <Button size="sm" variant="ghost" onClick={() => onConsent(card, false)}>Not now</Button>
          </div> : null}
          {error ? <p className="nx-cn-err" role="alert"><Icon as={TriangleAlert} size={13} />{error}</p> : null}
        </div>
        <div className="nx-cn-act">{action}</div>
        {!compact ? (
          <button type="button" className="nx-cn-more" aria-expanded={open} aria-label={`${open ? "Hide" : "Show"} details for ${card.label}`} onClick={() => setOpen(!open)}>
            <Icon as={open ? ChevronDown : ChevronRight} size={14} />
          </button>
        ) : null}
      </div>
      {open && !compact ? (
        <div className="nx-cn-detail">
          <dl>
            <dt>About</dt><dd>{card.about}</dd>
            {card.version ? <><dt>Version</dt><dd className="nx-cn-mono">{card.version}</dd></> : null}
            {card.servers?.length ? <><dt>Servers</dt><dd>{card.servers.map(row => `${row.label}: ${row.running ? `${row.models} model${row.models === 1 ? "" : "s"}` : row.installed ? "not running" : "not installed"}`).join(" · ")}</dd></> : null}
            {proof ? <><dt>Last test</dt><dd>{proof.ok ? "Passed" : "Failed"} {proof.at ? ago(proof.at) : ""}{proof.ms ? `, ${Math.round(proof.ms / 1000)} s` : ""}{proof.model ? `, ${proof.model}` : ""}</dd></> : null}
          </dl>
          <Steps proof={proof} proving={proving} />
          <div className="nx-cn-detail-actions">
            {card.state === "connected" && card.provable && !["kimi-code", "gptme"].includes(card.id) ? (
              <Button size="sm" disabled={proving} onClick={() => onProve(card, true)}>Test a long chat too</Button>
            ) : null}
            {card.docs ? <a className="nx-btn nx-btn-ghost nx-btn-sm" href={card.docs} target="_blank" rel="noreferrer"><Icon as={ExternalLink} size={14} /><span className="nx-btn-label">Docs</span></a> : null}
          </div>
          {card.provable ? <p className="nx-cn-note">A test is one tiny chat on your plan: it reads a file with the tool, and Neyvia checks the answer.</p> : null}
        </div>
      ) : null}
      {compact && proof ? <Steps proof={proof} proving={proving} /> : null}
    </li>
  );
}

export function NxConnections({ compact = false, onConnected }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState({});
  const [errors, setErrors] = useState({});
  const [keys, setKeys] = useState(false);
  const [consents, setConsents] = useState({});
  const seen = useRef(new Set());

  const load = useCallback(async force => {
    setBusy(true);
    try {
      const next = force ? await api({ operation: "status", force: true }) : await api();
      setData(next);
      setError("");
      return next;
    } catch (failure) {
      setError(failure.message);
      return null;
    } finally { setBusy(false); }
  }, []);

  useEffect(() => { void load(false); }, [load]);
  useEffect(() => {
    const refresh = () => { if (document.visibilityState === "visible") void load(false); };
    document.addEventListener("visibilitychange", refresh);
    return () => document.removeEventListener("visibilitychange", refresh);
  }, [load]);

  const cards = data?.cards || [];
  const anyProving = cards.some(card => card.proving);
  const anyInstalling = cards.some(card => card.state === "installing");
  const anyWaiting = Object.values(waiting).some(Boolean) || cards.some(card => card.signingIn);
  const measuring = Boolean(data?.checking);
  useEffect(() => {
    if (!anyProving && !anyWaiting && !anyInstalling && !measuring) return undefined;
    const timer = setInterval(() => void load(anyWaiting), anyWaiting ? 4000 : 2000);
    return () => clearInterval(timer);
  }, [anyProving, anyWaiting, anyInstalling, measuring, load]);

  // A sign-in the person finished in their terminal turns the card green; tell the host once.
  useEffect(() => {
    for (const card of cards) {
      if (waiting[card.id] && card.signin?.state === "failed") {
        setWaiting(current => ({ ...current, [card.id]: false }));
        setErrors(current => ({ ...current, [card.id]: "Sign-in did not finish. Please try again." }));
      }
      if ((waiting[card.id] || card.signingIn) && card.state === "connected") {
        setWaiting(current => ({ ...current, [card.id]: false }));
        if (!seen.current.has(card.id)) { seen.current.add(card.id); onConnected?.(card); }
      }
    }
  }, [cards, waiting, onConnected]);

  const fail = (id, message) => setErrors(current => ({ ...current, [id]: message }));
  const onConnect = async card => {
    fail(card.id, "");
    try {
      await api({ operation: "connect", id: card.id, fromClick: true });
      setWaiting(current => ({ ...current, [card.id]: true }));
      await load(false);
    } catch (failure) { fail(card.id, failure.message); }
  };
  const onStopWaiting = async card => {
    try {
      await api({ operation: "cancel-signin", id: card.id });
      setWaiting(current => ({ ...current, [card.id]: false }));
      await load(false);
    } catch (failure) { fail(card.id, failure.message); }
  };
  const onInstall = async card => {
    fail(card.id, "");
    try {
      const result = await api({ operation: "install", id: card.id, fromClick: true });
      if (result.needsConsent && result.approvalId) {
        setConsents(current => ({ ...current, [card.id]: result.approvalId }));
        clearApproval(result.approvalId); // the inline consent owns this decision
      }
      else if (result.needsConsent) throw new Error(result.error || "Installation was declined. Try again when you are ready.");
      else if (result.install?.approvalId) clearApproval(result.install.approvalId);
      await load(false);
    } catch (failure) { fail(card.id, failure.message); }
  };
  const onConsent = async (card, yes) => {
    const approvalId = consents[card.id];
    clearApproval(approvalId);
    setConsents(current => ({ ...current, [card.id]: null }));
    if (!yes) return;
    try {
      await api({ operation: "install", id: card.id, fromClick: true, consent: true, approvalId });
      await load(false);
    } catch (failure) { fail(card.id, failure.message); }
  };
  const onProve = async (card, longChat) => {
    fail(card.id, "");
    try {
      await api({ operation: "prove", id: card.id, longChat, fromClick: true });
      await load(false);
    } catch (failure) { fail(card.id, failure.message); }
  };

  const summary = data?.summary;
  return (
    <section className={`nx-cn${compact ? " is-compact" : ""}`} aria-label="Connections">
      <header className="nx-cn-head">
        <div>
          <h3>Connections</h3>
          <p>{!summary ? "Looking at what is on this PC…" : `${summary.connected} of ${summary.total} ready${summary.proven ? `, ${summary.proven} tested` : ""}${summary.pending ? `, still looking at ${summary.pending}` : ""}. Everything here runs on your own accounts.`}</p>
        </div>
        <span className="nx-head-spacer" />
        {busy ? <Spinner size={14} /> : null}
        <Button size="sm" icon={RefreshCw} disabled={busy} onClick={() => void load(true)}>Check again</Button>
      </header>
      {error ? <p className="nx-cn-err" role="alert"><Icon as={TriangleAlert} size={13} />{error}</p> : null}
      {!data && !error ? <div className="nx-stage-loading"><Spinner size={16} /></div> : null}
      <ul className="nx-cn-list">
        {cards.map(card => (
          <Card key={card.id} card={card} compact={compact} waiting={Boolean(waiting[card.id] || card.signingIn)} error={errors[card.id]}
            consent={consents[card.id]} onInstall={onInstall} onConsent={onConsent} onStopWaiting={onStopWaiting}
            onConnect={onConnect} onProve={onProve} onRecheck={() => void load(true)} onKeys={() => setKeys(true)} />
        ))}
      </ul>
      {keys ? (
        <div className="nx-cn-keys">
          <div className="nx-cn-keys-head"><h4>API keys</h4><Button size="sm" onClick={() => { setKeys(false); void load(true); }}>Done</Button></div>
          <Suspense fallback={<Spinner size={14} />}>
            <KeysQueue callBackend={callNx} />
          </Suspense>
        </div>
      ) : null}
    </section>
  );
}

export default NxConnections;
