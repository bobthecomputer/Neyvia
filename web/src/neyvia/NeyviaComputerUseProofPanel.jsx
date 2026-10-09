import { useEffect, useMemo, useState } from "react";
import { MonitorCheck, Play, RefreshCw, ShieldCheck } from "lucide-react";
import { callPcHost, PC_OFFLINE_MESSAGE, usePcHostStatus } from "./neyviaPcHost.js";
import "./neyviaComputerUseProof.css";

const FLOW_OPTIONS = Object.freeze([
  { id: "login_session", label: "Login and session boundary", detail: "Prove the local sign-in surface and revision-gated UI action without storing a password." },
  { id: "library_or_preview", label: "Library or preview", detail: "Open one product surface and prove it rendered." },
  { id: "product_mode_switch", label: "Product mode switch", detail: "Switch Chat and Orchestration without losing the shell." },
  { id: "harnesses_surface", label: "Harnesses surface", detail: "Open the runtime harness surface and verify its controls." },
  { id: "surface_navigation", label: "Surface navigation", detail: "Exercise the primary workspace navigation." },
  { id: "control_room", label: "Control room", detail: "Verify the authenticated control-room landmarks." },
]);

// Computer use runs on the PC, so every call goes to the PC app.
const callNeyvia = callPcHost;

function defaultBaseUrl() {
  if (typeof window === "undefined") return "";
  return window.location.origin;
}

function displayNumber(value, suffix = "") {
  return Number.isFinite(Number(value)) ? `${Number(value)}${suffix}` : "Not reported";
}

export function NeyviaComputerUseProofPanel() {
  const [catalogState, setCatalogState] = useState("loading");
  const [twins, setTwins] = useState([]);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [form, setForm] = useState({
    changeLabel: "Lab computer-use operator path",
    baseUrl: defaultBaseUrl(),
    flow: "login_session",
    baselineReceiptPath: "",
    approved: false,
  });

  const pc = usePcHostStatus();
  // A backend with no paired PC app runs the check on its own host.
  const pcOffline = pc.checked && pc.registered && !pc.online;

  const selectedFlow = useMemo(
    () => FLOW_OPTIONS.find(item => item.id === form.flow) || FLOW_OPTIONS[0],
    [form.flow],
  );

  const refreshTwins = async () => {
    setCatalogState("loading");
    setError("");
    try {
      const data = await callNeyvia("list_computer_use_twins_command", {});
      setTwins(Array.isArray(data?.specs) ? data.specs : []);
      setCatalogState("ready");
    } catch (nextError) {
      setTwins([]);
      setCatalogState("unavailable");
      // The offline banner already says why; do not repeat it as a second error.
      setError(nextError?.offline ? "" : nextError instanceof Error ? nextError.message : "Computer Use catalog unavailable");
    }
  };

  // Load once the PC is known to be answering, and again when it comes back.
  useEffect(() => {
    if (pc.checked && (pc.online || !pc.registered)) void refreshTwins();
  }, [pc.checked, pc.online, pc.registered]);

  const runProof = async event => {
    event.preventDefault();
    if (!form.approved || running || pcOffline) return;
    setRunning(true);
    setError("");
    setResult(null);
    try {
      const data = await callNeyvia("verify_computer_use_change_command", {
        approved: true,
        changeLabel: form.changeLabel.trim(),
        name: form.changeLabel.trim(),
        mode: "live",
        baseUrl: form.baseUrl.trim(),
        flows: [form.flow],
        repetitions: 1,
        baselineReceiptPath: form.baselineReceiptPath.trim(),
        thresholds: {
          requireLiveProof: true,
          minimumFlowSuccessRate: 1,
          minimumDeterministicAgreement: 1,
          maximumCompactReceiptBytes: 256000,
        },
        metadata: {
          requestedFrom: "neyvia.lab",
          boundedFlow: form.flow,
        },
      });
      setResult(data);
      await refreshTwins();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Computer Use verification failed");
    } finally {
      setRunning(false);
    }
  };

  const hostBanner = pcOffline ? (
    <div className="neyvia-cu-host is-offline" data-pc-host-state="offline" role="alert">
      <strong>PC app is offline</strong>
      <p>{pc.reason || PC_OFFLINE_MESSAGE} Computer use runs on your PC.</p>
    </div>
  ) : pc.checked && pc.registered ? (
    <div className="neyvia-cu-host" data-pc-host-state="online" role="status">
      <strong>Runs on {pc.deviceName || "your PC"}</strong>
    </div>
  ) : null;

  return (
    <div
      aria-label="Computer Use proof"
      className="neyvia-cu-proof"
      data-neyvia-cu-proof="true"
      role="tabpanel"
    >
      <form className="neyvia-cu-proof-form" onSubmit={runProof}>
        {hostBanner}
        <div className="neyvia-cu-proof-heading">
          <span><MonitorCheck aria-hidden="true" size={15} /> Smallest useful live proof</span>
          <p>One flow, one repetition, compact accessibility state first. Screenshots remain fallback-only.</p>
        </div>
        <label>
          Change to verify
          <input
            onChange={event => setForm(current => ({ ...current, changeLabel: event.target.value }))}
            required
            value={form.changeLabel}
          />
        </label>
        <label>
          Local app base URL
          <input
            inputMode="url"
            onChange={event => setForm(current => ({ ...current, baseUrl: event.target.value }))}
            required
            value={form.baseUrl}
          />
        </label>
        <label>
          Bounded flow
          <select
            onChange={event => setForm(current => ({ ...current, flow: event.target.value }))}
            value={form.flow}
          >
            {FLOW_OPTIONS.map(option => (
              <option key={option.id} value={option.id}>{option.label}</option>
            ))}
          </select>
          <small>{selectedFlow.detail}</small>
        </label>
        <label>
          Optional retained live baseline receipt
          <input
            onChange={event => setForm(current => ({ ...current, baselineReceiptPath: event.target.value }))}
            placeholder="Leave empty to make no speed or accuracy comparison"
            value={form.baselineReceiptPath}
          />
        </label>
        <label className="neyvia-explicit-checkbox neyvia-cu-approval">
          <input
            checked={form.approved}
            onChange={event => setForm(current => ({ ...current, approved: event.target.checked }))}
            type="checkbox"
          />
          I approve one local browser verification now.
        </label>
        <button
          className="primary"
          disabled={!form.approved || !form.changeLabel.trim() || !form.baseUrl.trim() || running || pcOffline}
          type="submit"
        >
          <Play aria-hidden="true" size={14} />
          {running ? "Running bounded proof…" : "Run one approved proof"}
        </button>
        <small>
          This writes a local verification receipt and may click only inside the selected local Neyvia flow.
        </small>
      </form>

      <section className="neyvia-cu-proof-result" aria-live="polite">
        <header>
          <div>
            <span className="neyvia-surface-eyebrow"><ShieldCheck aria-hidden="true" size={14} /> Verification truth</span>
            <strong>{result ? result.status : "No proof run yet"}</strong>
          </div>
          <button aria-label="Refresh Computer Use twins" disabled={pcOffline} onClick={refreshTwins} type="button">
            <RefreshCw aria-hidden="true" size={14} />
          </button>
        </header>

        {error ? <div className="neyvia-ecosystem-error" role="alert">{error}</div> : null}

        {result ? (
          <>
            <div className="neyvia-cu-metrics">
              <div><span>Evidence</span><strong>{result.evidenceMode || "Unknown"}</strong></div>
              <div><span>Live proof</span><strong>{result.liveProof ? "Confirmed" : "Not confirmed"}</strong></div>
              <div><span>Flow success</span><strong>{displayNumber(Number(result.metrics?.flowSuccessRate) * 100, "%")}</strong></div>
              <div><span>Determinism</span><strong>{displayNumber(Number(result.metrics?.deterministicAgreement) * 100, "%")}</strong></div>
              <div><span>Latency p95</span><strong>{displayNumber(result.metrics?.latency?.p95Ms, " ms")}</strong></div>
              <div><span>Compact receipt</span><strong>{displayNumber(result.metrics?.compactReceiptBytes, " B")}</strong></div>
            </div>
            <div className="neyvia-cu-claim" data-claim-allowed={result.comparison?.comparativeClaimAllowed ? "true" : "false"}>
              <strong>{result.comparison?.comparativeClaimAllowed ? "Comparative claim allowed" : "No comparative claim"}</strong>
              <p>
                {result.comparison?.comparativeClaimAllowed
                  ? "A retained live baseline and the live candidate passed every gate."
                  : "Passing this flow proves the change only. Faster or more accurate remains unclaimed without a retained live baseline."}
              </p>
            </div>
            {Array.isArray(result.flows) && result.flows.length ? (
              <ul className="neyvia-cu-flow-results" aria-label="Computer Use flow results">
                {result.flows.map((flow, index) => (
                  <li data-flow-status={flow.status || "unknown"} key={`${flow.flow || "flow"}-${index}`}>
                    <div>
                      <strong>{flow.flow || "Unnamed flow"}</strong>
                      <span>{flow.status || (flow.pass ? "passed" : "failed")}</span>
                    </div>
                    {flow.reason ? <p>{flow.reason}</p> : null}
                  </li>
                ))}
              </ul>
            ) : null}
            <small className="neyvia-cu-receipt">Receipt: {result.receiptPath || "Not reported"}</small>
          </>
        ) : (
          <p className="neyvia-empty-hint">
            Approval is deliberately per run. The verifier will label replay evidence and will not convert it into a live claim.
          </p>
        )}

        <div className="neyvia-cu-twins">
          <div>
            <strong>Saved twins</strong>
            <span>{catalogState === "loading" ? "Loading…" : `${twins.length} backend-reported`}</span>
          </div>
          {catalogState === "unavailable" ? (
            <p className="neyvia-empty-hint">Twin catalog unavailable. No saved spec is invented.</p>
          ) : null}
          {catalogState === "ready" && !twins.length ? (
            <p className="neyvia-empty-hint">No saved Computer Use twin yet.</p>
          ) : null}
          <ul>
            {twins.slice(0, 6).map(twin => (
              <li key={twin.specId}>
                <strong>{twin.name || twin.specId}</strong>
                <span>{twin.mode || "unknown"} · {(twin.flows || []).join(", ") || "no flows"}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
