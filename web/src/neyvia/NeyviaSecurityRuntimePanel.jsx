import { useEffect, useMemo, useState } from "react";
import { ListChecks, RefreshCw, ShieldCheck, Swords } from "lucide-react";
import "./neyviaSecurityRuntime.css";

async function callNeyvia(command, payload = {}) {
  const response = await fetch("/api/backend", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, payload }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) throw new Error(result?.error || `${command} failed`);
  return result?.data || {};
}

function splitLines(value) {
  return Array.from(
    new Set(
      String(value || "")
        .split(/[\n,]/)
        .map(item => item.trim())
        .filter(Boolean),
    ),
  );
}

function phaseLabel(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, letter => letter.toUpperCase());
}

export function NeyviaSecurityRuntimePanel() {
  const [auditState, setAuditState] = useState("loading");
  const [audit, setAudit] = useState(null);
  const [validation, setValidation] = useState(null);
  const [plan, setPlan] = useState(null);
  const [decision, setDecision] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    target: "local-authorized-lab",
    authorizedBy: "",
    environment: "lab",
    mode: "passive",
    allowedTargets: "local-authorized-lab",
    excludedTargets: "",
    allowedActionClasses: "reconnaissance\nvalidation",
    actionClass: "reconnaissance",
    maxProbeAttempts: "3",
    authorizationConfirmed: false,
  });

  const scope = useMemo(
    () => ({
      target: form.target.trim(),
      authorizedBy: form.authorizedBy.trim(),
      authorizationConfirmed: form.authorizationConfirmed,
      environment: form.environment,
      mode: form.mode,
      allowedTargets: splitLines(form.allowedTargets),
      excludedTargets: splitLines(form.excludedTargets),
      allowedActionClasses: splitLines(form.allowedActionClasses),
      maxProbeAttempts: Number(form.maxProbeAttempts) || 1,
      dataHandling: "minimize-and-redact",
      allowCredentialAccess: false,
      allowDestructiveActions: false,
      allowPersistence: false,
      allowExternalDelivery: false,
    }),
    [form],
  );

  const refreshAudit = async () => {
    setAuditState("loading");
    setError("");
    try {
      const result = await callNeyvia("get_security_runtime_audit_command", {});
      setAudit(result);
      setAuditState("ready");
    } catch (nextError) {
      setAudit(null);
      setAuditState("unavailable");
      setError(nextError instanceof Error ? nextError.message : "Security runtime audit unavailable");
    }
  };

  useEffect(() => {
    refreshAudit();
  }, []);

  const buildPlan = async event => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const [nextValidation, nextPlan, nextDecision] = await Promise.all([
        callNeyvia("validate_security_scope_command", { scope }),
        callNeyvia("build_purple_team_plan_command", { scope }),
        callNeyvia("evaluate_security_action_command", {
          scope,
          action: {
            target: scope.target,
            actionClass: form.actionClass.trim(),
            active: scope.mode === "active",
          },
        }),
      ]);
      setValidation(nextValidation);
      setPlan(nextPlan);
      setDecision(nextDecision);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Security plan could not be built");
    } finally {
      setBusy(false);
    }
  };

  const coveragePhases = Array.isArray(audit?.coverage?.phases) ? audit.coverage.phases : [];
  const unavailable = Array.isArray(audit?.coverage?.unavailableCandidates)
    ? audit.coverage.unavailableCandidates
    : [];

  return (
    <div
      aria-label="Security runtime"
      className="neyvia-security-runtime"
      data-neyvia-security-runtime="true"
      role="tabpanel"
    >
      <section className="neyvia-security-coverage">
        <header>
          <div>
            <span className="neyvia-surface-eyebrow"><ShieldCheck aria-hidden="true" size={14} /> Installed coverage</span>
            <strong>
              {auditState === "loading"
                ? "Auditing…"
                : audit?.ready
                  ? "Purple-team path ready"
                  : "Coverage incomplete"}
            </strong>
          </div>
          <button aria-label="Refresh security runtime audit" onClick={refreshAudit} type="button">
            <RefreshCw aria-hidden="true" size={14} />
          </button>
        </header>
        {error ? <div className="neyvia-ecosystem-error" role="alert">{error}</div> : null}
        {auditState === "unavailable" ? (
          <p className="neyvia-empty-hint">Runtime audit unavailable. No security tool is shown as ready.</p>
        ) : null}
        <ul className="neyvia-security-phase-list">
          {coveragePhases.map(phase => (
            <li data-ready={phase.ready ? "true" : "false"} key={phase.phase}>
              <div>
                <strong>{phaseLabel(phase.phase)}</strong>
                <span>{phase.ready ? "Ready" : "Missing"}</span>
              </div>
              <p>{phase.matchedTools?.join(", ") || "No execution-ready tool receipt"}</p>
            </li>
          ))}
        </ul>
        {unavailable.length ? (
          <details>
            <summary>{unavailable.length} catalogued tool{unavailable.length === 1 ? "" : "s"} excluded from readiness</summary>
            <ul className="neyvia-security-unavailable">
              {unavailable.map(item => (
                <li key={item.id}>
                  <strong>{item.id}</strong>
                  <span>{item.state} · {item.reason}</span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>

      <form className="neyvia-security-scope-form" onSubmit={buildPlan}>
        <div className="neyvia-security-heading">
          <span><Swords aria-hidden="true" size={15} /> Bound the work before execution</span>
          <p>This screen validates and plans only. Mission execution still uses the durable scheduler and action-time approvals.</p>
        </div>
        <label>
          Named target
          <input
            onChange={event => setForm(current => ({ ...current, target: event.target.value }))}
            required
            value={form.target}
          />
        </label>
        <div className="neyvia-security-form-pair">
          <label>
            Environment
            <select onChange={event => setForm(current => ({ ...current, environment: event.target.value }))} value={form.environment}>
              <option value="lab">Lab</option>
              <option value="staging">Staging</option>
              <option value="production">Production</option>
            </select>
          </label>
          <label>
            Mode
            <select onChange={event => setForm(current => ({ ...current, mode: event.target.value }))} value={form.mode}>
              <option value="passive">Passive</option>
              <option value="active">Active</option>
            </select>
          </label>
        </div>
        <label>
          Authorization owner
          <input
            onChange={event => setForm(current => ({ ...current, authorizedBy: event.target.value }))}
            placeholder={form.mode === "active" ? "Required for active work" : "Optional for passive review"}
            value={form.authorizedBy}
          />
        </label>
        <label>
          Allowed targets
          <textarea
            onChange={event => setForm(current => ({ ...current, allowedTargets: event.target.value }))}
            rows={2}
            value={form.allowedTargets}
          />
        </label>
        <label>
          Excluded targets
          <textarea
            onChange={event => setForm(current => ({ ...current, excludedTargets: event.target.value }))}
            placeholder="One per line"
            rows={2}
            value={form.excludedTargets}
          />
        </label>
        <label>
          Allowed action classes
          <textarea
            onChange={event => setForm(current => ({ ...current, allowedActionClasses: event.target.value }))}
            rows={2}
            value={form.allowedActionClasses}
          />
        </label>
        <div className="neyvia-security-form-pair">
          <label>
            Action to evaluate
            <input
              onChange={event => setForm(current => ({ ...current, actionClass: event.target.value }))}
              required
              value={form.actionClass}
            />
          </label>
          <label>
            Max probe attempts
            <input
              max="50"
              min="1"
              onChange={event => setForm(current => ({ ...current, maxProbeAttempts: event.target.value }))}
              type="number"
              value={form.maxProbeAttempts}
            />
          </label>
        </div>
        <label className="neyvia-explicit-checkbox neyvia-security-authorization">
          <input
            checked={form.authorizationConfirmed}
            onChange={event => setForm(current => ({ ...current, authorizationConfirmed: event.target.checked }))}
            type="checkbox"
          />
          Authorization for this scope is confirmed.
        </label>
        <button className="primary" disabled={busy || !form.target.trim()} type="submit">
          <ListChecks aria-hidden="true" size={14} />
          {busy ? "Checking scope…" : "Validate scope and build plan"}
        </button>
      </form>

      <section className="neyvia-security-plan" aria-live="polite">
        <header>
          <span className="neyvia-surface-eyebrow"><ListChecks aria-hidden="true" size={14} /> Plan truth</span>
          <strong>
            {!validation
              ? "No scope checked yet"
              : validation.valid
                ? "Scope valid"
                : `${validation.blockers?.length || 0} blocker${validation.blockers?.length === 1 ? "" : "s"}`}
          </strong>
        </header>
        {validation?.blockers?.length ? (
          <ul className="neyvia-security-findings" data-tone="blocked">
            {validation.blockers.map(item => <li key={item}>{item}</li>)}
          </ul>
        ) : null}
        {validation?.warnings?.length ? (
          <ul className="neyvia-security-findings">
            {validation.warnings.map(item => <li key={item}>{item}</li>)}
          </ul>
        ) : null}
        {decision ? (
          <div className="neyvia-security-decision" data-allowed={decision.allowed ? "true" : "false"}>
            <strong>{decision.allowed ? "Evaluated action is in scope" : "Evaluated action is blocked"}</strong>
            <span>
              {decision.approvalRequired
                ? decision.approvalSatisfied
                  ? "Action-time approval present"
                  : "Action-time approval required"
                : "No action-time approval required for this proposal"}
            </span>
            <p>{decision.nextAction}</p>
          </div>
        ) : null}
        {plan?.phases?.length ? (
          <ol className="neyvia-security-plan-phases">
            {plan.phases.map(phase => (
              <li key={phase.id}>
                <div>
                  <strong>{phaseLabel(phase.id)}</strong>
                  <span>{phase.owner}</span>
                </div>
                <p>{phase.proof?.join(" · ")}</p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="neyvia-empty-hint">
            Build a scope to see the five required phases, proof for each owner, and fail-closed stop conditions.
          </p>
        )}
        {plan?.stopConditions?.length ? (
          <div className="neyvia-security-stop">
            <strong>Automatic stop conditions</strong>
            <span>{plan.stopConditions.map(phaseLabel).join(" · ")}</span>
          </div>
        ) : null}
      </section>
    </div>
  );
}
