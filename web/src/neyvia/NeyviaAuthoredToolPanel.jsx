import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  WandSparkles,
} from "lucide-react";
import "./neyviaAuthoredTool.css";
import {
  asSchemaRecord,
  buildSchemaArguments,
  schemaArgumentProperties,
  schemaRequiredArguments,
} from "./neyviaSchemaArguments.js";

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

function asList(value) {
  return Array.isArray(value) ? value : [];
}

function resultSummary(result) {
  if (!result) return "";
  if (result.ok === true) return "Execution completed with a retained backend receipt.";
  if (result.status === "approval_required") return "One or more declared permissions still need approval.";
  if (result.status === "permission_denied") return "The current permission mode denied this execution.";
  if (result.status === "adapter_required") return "The tool adapter is not available on this machine.";
  return "The backend returned a non-success result. Details are retained below.";
}

export function NeyviaAuthoredToolPanel() {
  const [state, setState] = useState("loading");
  const [query, setQuery] = useState("");
  const [tools, setTools] = useState([]);
  const [loadErrors, setLoadErrors] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [selected, setSelected] = useState(null);
  const [values, setValues] = useState({});
  const [extraArguments, setExtraArguments] = useState("");
  const [approvedPermissions, setApprovedPermissions] = useState([]);
  const [confirmed, setConfirmed] = useState(false);
  const [execution, setExecution] = useState(null);
  const [error, setError] = useState("");

  const load = async nextQuery => {
    setState("loading");
    setError("");
    try {
      const normalized = String(nextQuery || "").trim();
      const catalog = normalized
        ? await callNeyvia("search_authored_tools_command", { query: normalized, limit: 50 })
        : await callNeyvia("list_authored_tools_command");
      const rows = asList(catalog.tools);
      setTools(rows);
      setLoadErrors(asList(catalog.loadErrors));
      setSelectedId(current =>
        rows.some(item => item.toolId === current) ? current : rows[0]?.toolId || "",
      );
      setState("ready");
    } catch (nextError) {
      setState("unavailable");
      setError(nextError instanceof Error ? nextError.message : "Authored tools unavailable");
    }
  };

  useEffect(() => {
    void load("");
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    let active = true;
    setError("");
    void callNeyvia("describe_authored_tool_command", { toolId: selectedId })
      .then(tool => {
        if (!active) return;
        setSelected(tool);
        setValues({});
        setExtraArguments("");
        setApprovedPermissions([]);
        setConfirmed(false);
        setExecution(null);
      })
      .catch(nextError => {
        if (active) setError(nextError instanceof Error ? nextError.message : "Tool description unavailable");
      });
    return () => {
      active = false;
    };
  }, [selectedId]);

  const inputSchema = asSchemaRecord(selected?.inputSchema);
  const properties = schemaArgumentProperties(inputSchema);
  const required = schemaRequiredArguments(inputSchema);
  const permissions = asList(selected?.permissions);
  const missingPermissionApprovals = permissions.filter(item => !approvedPermissions.includes(item));

  const togglePermission = permission => {
    setApprovedPermissions(current =>
      current.includes(permission)
        ? current.filter(item => item !== permission)
        : [...current, permission],
    );
    setConfirmed(false);
  };

  const execute = async event => {
    event.preventDefault();
    setError("");
    setExecution(null);
    try {
      const argumentsPayload = buildSchemaArguments(inputSchema, values, extraArguments);
      setState("executing");
      const result = await callNeyvia("execute_authored_tool_command", {
        toolId: selected.toolId,
        arguments: argumentsPayload,
        permissionMode: "workspace_safe",
        approvedPermissions,
        approved: confirmed,
      });
      setExecution(result);
      setState("ready");
      setConfirmed(false);
    } catch (nextError) {
      setState("ready");
      setError(nextError instanceof Error ? nextError.message : "Authored tool execution failed");
    }
  };

  return (
    <section className="neyvia-authored-tool" data-neyvia-authored-tool="true">
      <header>
        <div>
          <span><WandSparkles aria-hidden="true" size={14} /> Workspace tool factory</span>
          <h3>Authored tools</h3>
          <p>Browse only saved workspace manifests. Every run uses the backend permission gate and returns its real receipt.</p>
        </div>
        <button aria-label="Refresh authored tools" onClick={() => void load(query)} type="button">
          <RefreshCw aria-hidden="true" size={14} />
        </button>
      </header>

      <form className="neyvia-authored-search" onSubmit={event => { event.preventDefault(); void load(query); }}>
        <Search aria-hidden="true" size={15} />
        <input
          aria-label="Search authored tools"
          onChange={event => setQuery(event.target.value)}
          placeholder="Search saved tools"
          value={query}
        />
        <button type="submit">Search</button>
      </form>

      {error ? <div className="neyvia-authored-alert" role="alert"><AlertTriangle aria-hidden="true" size={15} /> {error}</div> : null}
      {loadErrors.length ? (
        <div className="neyvia-authored-alert" role="alert">
          <AlertTriangle aria-hidden="true" size={15} />
          {loadErrors.length} invalid manifest{loadErrors.length === 1 ? "" : "s"} excluded from the catalog.
        </div>
      ) : null}

      {state === "unavailable" ? (
        <p className="neyvia-empty-hint">The authored-tool backend is unavailable. No tools are shown as runnable.</p>
      ) : state === "ready" && !tools.length ? (
        <div className="neyvia-authored-empty">
          <WandSparkles aria-hidden="true" size={20} />
          <strong>{query.trim() ? "No saved tools match this search" : "No authored tools saved in this workspace"}</strong>
          <p>Create or import a manifest through the tool-authoring contract; this browser will never invent examples.</p>
        </div>
      ) : (
        <div className="neyvia-authored-layout">
          <div className="neyvia-authored-list" role="list">
            {tools.map(tool => (
              <button
                aria-current={selectedId === tool.toolId ? "true" : undefined}
                className={selectedId === tool.toolId ? "is-selected" : undefined}
                key={tool.toolId}
                onClick={() => setSelectedId(tool.toolId)}
                role="listitem"
                type="button"
              >
                <span>{tool.kind || "tool"}</span>
                <strong>{tool.name || tool.toolId}</strong>
                <p>{tool.description || "No description provided."}</p>
                <small>{asList(tool.permissions).length} permission{asList(tool.permissions).length === 1 ? "" : "s"}</small>
              </button>
            ))}
          </div>

          {selected ? (
            <form className="neyvia-authored-runner" onSubmit={execute}>
              <div className="neyvia-authored-runner-head">
                <div>
                  <span>{selected.kind} · {selected.version || "unversioned"}</span>
                  <h4>{selected.name}</h4>
                  <code>{selected.toolId}</code>
                </div>
                <em data-tone={selected.available ? "positive" : "warning"}>
                  {selected.available ? "Adapter ready" : "Adapter unavailable"}
                </em>
              </div>
              <p>{selected.description}</p>

              <div className="neyvia-authored-facts">
                <span>Source <b>{selected.provenance?.provider || selected.provenance?.sourceKind || "workspace"}</b></span>
                <span>Trust <b>{selected.provenance?.trustLevel || "not reported"}</b></span>
                <span>Adapter <b>{selected.adapterDescriptor?.adapterId || selected.command?.adapterId || selected.delegated?.adapterId || "composite"}</b></span>
              </div>

              <fieldset>
                <legend>Arguments</legend>
                {properties.map(([name, schema]) => {
                  const type = String(schema?.type || "string");
                  return (
                    <label key={name}>
                      <span>{schema?.title || name}{required.has(name) ? " *" : ""}</span>
                      {type === "boolean" ? (
                        <input
                          checked={Boolean(values[name])}
                          onChange={event => setValues(current => ({ ...current, [name]: event.target.checked }))}
                          type="checkbox"
                        />
                      ) : type === "object" || type === "array" ? (
                        <textarea
                          onChange={event => setValues(current => ({ ...current, [name]: event.target.value }))}
                          placeholder={type === "array" ? "[]" : "{}"}
                          required={required.has(name)}
                          rows={3}
                          value={values[name] || ""}
                        />
                      ) : (
                        <input
                          onChange={event => setValues(current => ({ ...current, [name]: event.target.value }))}
                          required={required.has(name)}
                          type={type === "number" || type === "integer" ? "number" : "text"}
                          value={values[name] || ""}
                        />
                      )}
                      {schema?.description ? <small>{schema.description}</small> : null}
                    </label>
                  );
                })}
                {!properties.length ? <p>No declared fields. You can supply a JSON object below if the schema permits it.</p> : null}
                <label>
                  <span>Additional arguments (JSON object)</span>
                  <textarea onChange={event => setExtraArguments(event.target.value)} placeholder="{}" rows={3} value={extraArguments} />
                </label>
              </fieldset>

              <fieldset>
                <legend><ShieldCheck aria-hidden="true" size={14} /> Permission approval</legend>
                {permissions.length ? permissions.map(permission => (
                  <label className="neyvia-authored-check" key={permission}>
                    <input
                      checked={approvedPermissions.includes(permission)}
                      onChange={() => togglePermission(permission)}
                      type="checkbox"
                    />
                    <span>Approve <code>{permission}</code> for this run</span>
                  </label>
                )) : <p>This manifest declares no permissions.</p>}
                <label className="neyvia-authored-check is-final">
                  <input
                    checked={confirmed}
                    disabled={Boolean(missingPermissionApprovals.length)}
                    onChange={event => setConfirmed(event.target.checked)}
                    type="checkbox"
                  />
                  <span>I reviewed the tool, arguments, target adapter, and permissions for this one run.</span>
                </label>
              </fieldset>

              <button className="neyvia-authored-execute" disabled={!selected.available || !confirmed || state === "executing"} type="submit">
                <Play aria-hidden="true" size={14} />
                {state === "executing" ? "Executing…" : "Execute once"}
              </button>

              {execution ? (
                <div className="neyvia-authored-receipt" data-status={execution.ok ? "success" : "failed"}>
                  <strong>
                    {execution.ok ? <CheckCircle2 aria-hidden="true" size={15} /> : <AlertTriangle aria-hidden="true" size={15} />}
                    {execution.status || (execution.ok ? "completed" : "failed")}
                  </strong>
                  <p>{resultSummary(execution)}</p>
                  <pre>{JSON.stringify(execution, null, 2)}</pre>
                </div>
              ) : null}
            </form>
          ) : null}
        </div>
      )}
    </section>
  );
}
