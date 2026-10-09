import { useEffect, useMemo, useRef, useState } from "react";
import { FileType, RefreshCw, X } from "lucide-react";

import { neyviaPanelEnterClass } from "./neyviaToolVisuals.js";
import {
  OFFICE_SUITE_DEFAULT_TOOL_ID,
  OFFICE_SUITE_TOOL_IDS,
  buildOfficeSuiteExecutePayload,
  defaultArgumentsForOperation,
  normalizeOfficeExecuteResult,
  normalizeOfficeToolDescribe,
  officeOutputFormatChoices,
  officeSuiteOutcomeLabel,
  partitionOfficeFormFields,
} from "./neyviaOfficeSuiteModel.js";
import "./neyviaOfficeSuite.css";

/**
 * Isolated LibreOffice / Pandoc operator workspace.
 * Execution path: describe_tool_suite_command + execute_tool_suite_command only.
 * No shell shortcuts, no direct office binary calls from the UI.
 */

async function callNeyvia(command, payload = {}, { signal } = {}) {
  const response = await fetch("/api/backend", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, payload }),
    signal,
  });
  let result = null;
  try {
    result = await response.json();
  } catch (error) {
    throw new Error(
      `Backend returned non-JSON for ${command}: ${String(error?.message || error)}`,
    );
  }
  if (!response.ok || !result?.ok) {
    throw new Error(result?.error || `${command} failed (HTTP ${response.status})`);
  }
  return result.data;
}

function OverlayShell({ title, subtitle, onClose, children }) {
  const dialogRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const enterClass = neyviaPanelEnterClass("office-suite");

  useEffect(() => {
    const returnTarget = document.activeElement;
    const focusableSelector =
      'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';
    dialogRef.current?.querySelector(focusableSelector)?.focus();
    const handleKeyDown = event => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current?.();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [...(dialogRef.current?.querySelectorAll(focusableSelector) || [])].filter(
        node => !(node instanceof HTMLElement && node.classList.contains("neyvia-overlay-backdrop")),
      );
      if (!focusable.length) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      if (returnTarget instanceof HTMLElement && document.contains(returnTarget)) {
        returnTarget.focus();
      }
    };
  }, []);

  return (
    <div
      aria-labelledby="neyvia-office-suite-title"
      aria-modal="true"
      className="neyvia-overlay is-wide"
      data-neyvia-overlay="true"
      data-neyvia-panel="office-suite"
      role="presentation"
    >
      <button
        aria-label="Close overlay backdrop"
        className="neyvia-overlay-backdrop"
        onClick={onClose}
        type="button"
      />
      <div
        aria-modal="true"
        className={`neyvia-overlay-card ${enterClass}`}
        data-neyvia-panel-enter="office-suite"
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        <header>
          <div>
            <h2 id="neyvia-office-suite-title">{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          <button aria-label="Close" onClick={onClose} type="button">
            <X aria-hidden="true" size={16} />
          </button>
        </header>
        <div className="neyvia-overlay-body">{children}</div>
      </div>
    </div>
  );
}

function schemaPropertyKeys(operation) {
  const properties = operation?.inputSchema?.properties;
  if (!properties || typeof properties !== "object") return [];
  return Object.keys(properties).filter(key => key !== "operation");
}

function FieldControl({ fieldKey, schema, value, onChange, formatChoices = [] }) {
  const enumValues = Array.isArray(schema.enum)
    ? schema.enum
    : fieldKey === "outputFormat" && formatChoices.length
      ? formatChoices
      : null;
  const isLong =
    schema.type === "object" ||
    schema.type === "array" ||
    fieldKey.toLowerCase().includes("metadata") ||
    fieldKey.toLowerCase().includes("variable");

  if (enumValues) {
    return (
      <select
        data-office-field={fieldKey}
        id={`neyvia-office-field-${fieldKey}`}
        onChange={event => onChange(fieldKey, event.target.value)}
        value={value ?? ""}
      >
        <option value="">Select…</option>
        {enumValues.map(item => (
          <option key={String(item)} value={String(item)}>
            {String(item)}
          </option>
        ))}
      </select>
    );
  }
  if (schema.type === "boolean") {
    return (
      <select
        data-office-field={fieldKey}
        id={`neyvia-office-field-${fieldKey}`}
        onChange={event => onChange(fieldKey, event.target.value === "true")}
        value={value === true ? "true" : "false"}
      >
        <option value="false">false</option>
        <option value="true">true</option>
      </select>
    );
  }
  if (isLong) {
    return (
      <textarea
        data-office-field={fieldKey}
        id={`neyvia-office-field-${fieldKey}`}
        onChange={event => onChange(fieldKey, event.target.value)}
        spellCheck={false}
        value={
          typeof value === "string"
            ? value
            : value == null
              ? ""
              : formatJson(value)
        }
      />
    );
  }
  return (
    <input
      data-office-field={fieldKey}
      id={`neyvia-office-field-${fieldKey}`}
      onChange={event => onChange(fieldKey, event.target.value)}
      type={schema.type === "integer" || schema.type === "number" ? "number" : "text"}
      value={value ?? ""}
    />
  );
}

function coerceFieldValue(key, value, schema = {}) {
  const type = String(schema.type || "").toLowerCase();
  if (type === "boolean") return Boolean(value);
  if (type === "integer") {
    if (value === "" || value == null) return undefined;
    const parsed = Number.parseInt(String(value), 10);
    return Number.isFinite(parsed) ? parsed : value;
  }
  if (type === "number") {
    if (value === "" || value == null) return undefined;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : value;
  }
  if (type === "array") {
    if (Array.isArray(value)) return value;
    const text = String(value || "").trim();
    if (!text) return [];
    try {
      const parsed = JSON.parse(text);
      return Array.isArray(parsed) ? parsed : text.split(/[\n,]/).map(part => part.trim()).filter(Boolean);
    } catch {
      return text.split(/[\n,]/).map(part => part.trim()).filter(Boolean);
    }
  }
  if (type === "object") {
    if (value && typeof value === "object") return value;
    const text = String(value || "").trim();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return value;
}

function buildArgumentsFromForm(operation, formValues) {
  const properties = operation?.inputSchema?.properties || {};
  const required = Array.isArray(operation?.inputSchema?.required)
    ? operation.inputSchema.required
    : [];
  const args = {};
  for (const key of schemaPropertyKeys(operation)) {
    const schema = properties[key] || {};
    let value = formValues[key];
    if (schema.const !== undefined) {
      args[key] = schema.const;
      continue;
    }
    value = coerceFieldValue(key, value, schema);
    if (value === undefined || value === "") {
      if (required.includes(key)) args[key] = value === undefined ? "" : value;
      continue;
    }
    if (Array.isArray(value) && value.length === 0 && !required.includes(key)) continue;
    if (value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0) {
      if (!required.includes(key)) continue;
    }
    args[key] = value;
  }
  return args;
}

function formatJson(value) {
  if (value == null) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function NeyviaOfficeSuitePanel({ open = false, onClose }) {
  const [toolId, setToolId] = useState(OFFICE_SUITE_DEFAULT_TOOL_ID);
  const [describeState, setDescribeState] = useState("idle");
  const [described, setDescribed] = useState(() => normalizeOfficeToolDescribe(null));
  const [operationId, setOperationId] = useState("");
  const [formValues, setFormValues] = useState({});
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const describeRequestRef = useRef({ requestId: 0, controller: null });
  const executeRequestRef = useRef({ requestId: 0, controller: null });

  const selectedOperation = useMemo(
    () => described.operations.find(op => op.operationId === operationId) || described.operations[0] || null,
    [described.operations, operationId],
  );

  const invalidateExecution = () => {
    executeRequestRef.current.controller?.abort();
    executeRequestRef.current = {
      requestId: executeRequestRef.current.requestId + 1,
      controller: null,
    };
    setApproved(false);
    setBusy(false);
    setResult(null);
  };

  const refreshDescribe = async (nextToolId = toolId) => {
    const requestId = describeRequestRef.current.requestId + 1;
    describeRequestRef.current.controller?.abort();
    const controller = new AbortController();
    describeRequestRef.current = { requestId, controller };
    setDescribeState("loading");
    invalidateExecution();
    try {
      const data = await callNeyvia(
        "describe_tool_suite_command",
        { toolId: nextToolId },
        { signal: controller.signal },
      );
      if (
        controller.signal.aborted ||
        describeRequestRef.current.requestId !== requestId
      ) {
        return;
      }
      const normalized = normalizeOfficeToolDescribe(data);
      setDescribed(normalized);
      const firstOp = normalized.operations[0]?.operationId || "";
      setOperationId(firstOp);
      setFormValues(defaultArgumentsForOperation(normalized.operations[0] || null));
      setShowAdvanced(false);
      setDescribeState(normalized.agentReady ? "ready" : "unavailable");
    } catch (error) {
      if (
        controller.signal.aborted ||
        error?.name === "AbortError" ||
        describeRequestRef.current.requestId !== requestId
      ) {
        return;
      }
      const normalized = normalizeOfficeToolDescribe(null, { connectionError: error });
      setDescribed(normalized);
      setOperationId("");
      setFormValues({});
      setDescribeState("unavailable");
    } finally {
      if (describeRequestRef.current.requestId === requestId) {
        describeRequestRef.current = { requestId, controller: null };
      }
    }
  };

  useEffect(() => {
    if (!open) return undefined;
    void refreshDescribe(toolId);
    return () => {
      describeRequestRef.current.controller?.abort();
      describeRequestRef.current = {
        requestId: describeRequestRef.current.requestId + 1,
        controller: null,
      };
      executeRequestRef.current.controller?.abort();
      executeRequestRef.current = {
        requestId: executeRequestRef.current.requestId + 1,
        controller: null,
      };
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, toolId]);

  if (!open) return null;

  const outcome = result?.outcome || described.outcome || (describeState === "idle" ? "idle" : "unavailable");
  const fieldPartition = partitionOfficeFormFields(selectedOperation);
  const formatChoices = officeOutputFormatChoices(selectedOperation);
  const canRun =
    Boolean(selectedOperation?.operationId) &&
    approved &&
    !busy &&
    describeState !== "loading";

  const updateFormValue = (key, value) => {
    setFormValues(current => ({ ...current, [key]: value }));
    invalidateExecution();
  };

  const renderField = key => {
    const schema = selectedOperation?.inputSchema?.properties?.[key] || {};
    return (
      <div className="neyvia-office-suite__field" key={key}>
        <label htmlFor={`neyvia-office-field-${key}`}>
          {key}
          {Array.isArray(selectedOperation?.inputSchema?.required) &&
          selectedOperation.inputSchema.required.includes(key)
            ? " *"
            : ""}
        </label>
        <FieldControl
          fieldKey={key}
          formatChoices={formatChoices}
          onChange={updateFormValue}
          schema={schema}
          value={formValues[key]}
        />
      </div>
    );
  };

  const runOperation = async () => {
    if (!canRun || !selectedOperation) return;
    const requestId = executeRequestRef.current.requestId + 1;
    executeRequestRef.current.controller?.abort();
    const controller = new AbortController();
    executeRequestRef.current = { requestId, controller };
    setBusy(true);
    const args = buildArgumentsFromForm(selectedOperation, formValues);
    const payload = buildOfficeSuiteExecutePayload({
      toolId,
      operationId: selectedOperation.operationId,
      arguments: args,
      approvedPermissions: selectedOperation.permissions || [],
      permissionMode: "workspace_safe",
      capabilityId: described.capabilities[0] || "",
    });
    try {
      const data = await callNeyvia(
        "execute_tool_suite_command",
        payload,
        { signal: controller.signal },
      );
      if (
        controller.signal.aborted ||
        executeRequestRef.current.requestId !== requestId
      ) {
        return;
      }
      setResult(normalizeOfficeExecuteResult(data, { inputs: args }));
    } catch (error) {
      if (
        controller.signal.aborted ||
        error?.name === "AbortError" ||
        executeRequestRef.current.requestId !== requestId
      ) {
        return;
      }
      setResult(normalizeOfficeExecuteResult(null, { connectionError: error, inputs: args }));
    } finally {
      if (executeRequestRef.current.requestId === requestId) {
        executeRequestRef.current = { requestId, controller: null };
        setBusy(false);
      }
    }
  };

  return (
    <OverlayShell
      onClose={onClose}
      subtitle="Inspect, convert, and render PDF through the managed tool-suite path only. Workspace-contained inputs. No overwrite. No invented success."
      title="Office Suite"
    >
      <div
        className="neyvia-office-suite"
        data-neyvia-office-suite="true"
        data-outcome={outcome}
        data-state={describeState}
        data-tool-id={toolId}
      >
        <div className="neyvia-office-suite__toolbar">
          <div aria-label="Office tools" className="neyvia-office-suite__tools" role="tablist">
            {OFFICE_SUITE_TOOL_IDS.map(id => (
              <button
                aria-selected={toolId === id}
                className={toolId === id ? "is-active" : undefined}
                data-office-tool={id}
                key={id}
                onClick={() => {
                  invalidateExecution();
                  setToolId(id);
                }}
                role="tab"
                type="button"
              >
                <FileType aria-hidden="true" size={14} />{" "}
                {id === "tool.libreoffice" ? "LibreOffice" : "Pandoc"}
              </button>
            ))}
          </div>
          <button
            data-office-action="refresh"
            onClick={() => void refreshDescribe(toolId)}
            type="button"
          >
            <RefreshCw aria-hidden="true" size={14} /> Refresh describe
          </button>
        </div>

        <div className="neyvia-office-suite__status" data-office-availability="true">
          <div>
            <span>Availability</span>
            <strong>
              {described.agentReady
                ? "agentReady"
                : described.state || describeState || "unavailable"}
            </strong>
          </div>
          <div>
            <span>Health / version</span>
            <strong>
              {[described.health, described.selectedVersion].filter(Boolean).join(" · ") || "—"}
            </strong>
          </div>
          <div>
            <span>Operations</span>
            <strong>{described.operations.length || 0}</strong>
          </div>
          <div>
            <span>Outcome</span>
            <strong>{officeSuiteOutcomeLabel(outcome)}</strong>
          </div>
        </div>

        <p className="neyvia-office-suite__banner" data-office-banner="true">
          {described.error
            ? described.error
            : described.agentReady
              ? "Backend reports agent-ready. Approve explicitly before execute_tool_suite_command."
              : "Backend does not report agent-ready for this tool. Run still asks the suite and surfaces tool_not_ready / adapter_required honestly — never a fake convert."}
        </p>

        <div className="neyvia-office-suite__layout">
          <section className="neyvia-office-suite__form" aria-label="Office operation">
            <h3>Operation & inputs</h3>
            {!selectedOperation ? (
              <p className="neyvia-office-suite__empty">
                No backend operations listed for {toolId}. Nothing to invent here.
              </p>
            ) : (
              <>
                <div className="neyvia-office-suite__field">
                  <label htmlFor="neyvia-office-operation">Operation</label>
                  <select
                    data-office-field="operationId"
                    id="neyvia-office-operation"
                    onChange={event => {
                      const next = described.operations.find(
                        op => op.operationId === event.target.value,
                      );
                      setOperationId(event.target.value);
                      setFormValues(defaultArgumentsForOperation(next || null));
                      setShowAdvanced(false);
                      invalidateExecution();
                    }}
                    value={selectedOperation.operationId}
                  >
                    {described.operations.map(op => (
                      <option key={op.operationId} value={op.operationId}>
                        {op.operationId}
                        {op.name && op.name !== op.operationId ? ` — ${op.name}` : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <p className="neyvia-office-suite__hint">
                  {selectedOperation.description || "No description from describe_tool_suite_command."}
                  {selectedOperation.verifier
                    ? ` Verifier: ${selectedOperation.verifier}.`
                    : ""}{" "}
                  Paths must stay inside the active workspace. Existing output paths are rejected (no overwrite).
                </p>
                {fieldPartition.common.length ? (
                  <div className="neyvia-office-suite__field-group" data-office-fields="common">
                    <h4>Common inputs</h4>
                    {fieldPartition.common.map(renderField)}
                  </div>
                ) : (
                  <p className="neyvia-office-suite__hint" data-office-fields="common-empty">
                    This operation needs no common inputs beyond explicit approval.
                  </p>
                )}
                {fieldPartition.advanced.length ? (
                  <details
                    className="neyvia-office-suite__advanced"
                    data-office-fields="advanced"
                    onToggle={event => setShowAdvanced(event.currentTarget.open)}
                    open={showAdvanced}
                  >
                    <summary>
                      Advanced schema fields ({fieldPartition.advanced.length})
                    </summary>
                    {fieldPartition.advanced.map(renderField)}
                  </details>
                ) : null}
                <label className="neyvia-office-suite__hint">
                  <input
                    checked={approved}
                    data-office-approve="true"
                    onChange={event => setApproved(event.target.checked)}
                    type="checkbox"
                  />{" "}
                  I approve this tool-suite operation with workspace_safe permissions
                  {selectedOperation.permissions?.length
                    ? ` (${selectedOperation.permissions.join(", ")})`
                    : ""}.
                </label>
                <div className="neyvia-office-suite__actions">
                  <button onClick={onClose} type="button">
                    Close
                  </button>
                  <button
                    className="primary"
                    data-office-action="execute"
                    disabled={!canRun}
                    onClick={() => void runOperation()}
                    type="button"
                  >
                    {busy ? "Running…" : "Execute via tool suite"}
                  </button>
                </div>
              </>
            )}
          </section>

          <section className="neyvia-office-suite__proof" aria-label="Office proof">
            <h3>Backend proof</h3>
            {!result ? (
              <p className="neyvia-office-suite__empty" data-office-proof="empty">
                Proof stays empty until execute_tool_suite_command returns. Availability above comes only from describe.
              </p>
            ) : (
              <dl data-office-proof="true" data-office-outcome={result.outcome}>
                <div>
                  <dt>Status</dt>
                  <dd>
                    {result.status}
                    {result.ok ? " · ok" : " · not ok"} · {officeSuiteOutcomeLabel(result.outcome)}
                  </dd>
                </div>
                <div>
                  <dt>Operation & inputs</dt>
                  <dd>
                    {result.toolId || toolId} / {result.operationId || selectedOperation?.operationId || "—"}
                    <pre>{formatJson(result.inputs) || "—"}</pre>
                  </dd>
                </div>
                <div>
                  <dt>Permission decision</dt>
                  <dd>
                    {result.permissionSummary ? (
                      <pre>{formatJson(result.permissionSummary)}</pre>
                    ) : (
                      "No permissionSummary returned."
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Artifact path / hash / size</dt>
                  <dd>
                    {result.artifact ? (
                      <pre>{formatJson(result.artifact)}</pre>
                    ) : (
                      "No artifact fields returned."
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Verification</dt>
                  <dd>
                    {result.verification ? (
                      <pre>{formatJson(result.verification)}</pre>
                    ) : (
                      "No verification object returned."
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Lineage</dt>
                  <dd>
                    {result.lineage?.length ? (
                      <pre>{formatJson(result.lineage)}</pre>
                    ) : (
                      "No artifactReceipt relations returned."
                    )}
                  </dd>
                </div>
                {result.summary ? (
                  <div>
                    <dt>Summary</dt>
                    <dd>{result.summary}</dd>
                  </div>
                ) : null}
                {result.inputValidation ? (
                  <div>
                    <dt>Input validation</dt>
                    <dd>
                      <pre>{formatJson(result.inputValidation)}</pre>
                    </dd>
                  </div>
                ) : null}
              </dl>
            )}
          </section>
        </div>
      </div>
    </OverlayShell>
  );
}
