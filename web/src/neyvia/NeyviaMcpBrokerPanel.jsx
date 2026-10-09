import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Network,
  Play,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
} from "lucide-react";
import {
  asSchemaRecord,
  buildSchemaArguments,
  schemaArgumentProperties,
  schemaRequiredArguments,
} from "./neyviaSchemaArguments.js";
import "./neyviaMcpBroker.css";

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

function statusTone(server) {
  if (server?.callable && server?.authState === "authenticated") return "positive";
  if (server?.authState === "error" || server?.authState === "expired") return "danger";
  return "warning";
}

export function NeyviaMcpBrokerPanel() {
  const [state, setState] = useState("loading");
  const [snapshot, setSnapshot] = useState(null);
  const [selectedServer, setSelectedServer] = useState("");
  const [query, setQuery] = useState("");
  const [tools, setTools] = useState([]);
  const [selectedName, setSelectedName] = useState("");
  const [selectedTool, setSelectedTool] = useState(null);
  const [values, setValues] = useState({});
  const [extraArguments, setExtraArguments] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState("");

  const loadSnapshot = async () => {
    setState("loading");
    setError("");
    try {
      const data = await callNeyvia("get_mcp_broker_snapshot_command");
      const servers = asList(data.servers);
      setSnapshot(data);
      setSelectedServer(current =>
        servers.some(item => item.name === current) ? current : servers[0]?.name || "",
      );
      setState("ready");
    } catch (nextError) {
      setState("unavailable");
      setError(nextError instanceof Error ? nextError.message : "MCP broker unavailable");
    }
  };

  useEffect(() => {
    void loadSnapshot();
  }, []);

  useEffect(() => {
    setTools([]);
    setSelectedName("");
    setSelectedTool(null);
    setValues({});
    setExtraArguments("");
    setConfirmed(false);
    setReceipt(null);
  }, [selectedServer]);

  useEffect(() => {
    if (!selectedName) {
      setSelectedTool(null);
      return;
    }
    let active = true;
    setError("");
    void callNeyvia("describe_mcp_tool_command", { name: selectedName })
      .then(tool => {
        if (!active) return;
        setSelectedTool(tool);
        setValues({});
        setExtraArguments("");
        setConfirmed(false);
        setReceipt(null);
      })
      .catch(nextError => {
        if (active) setError(nextError instanceof Error ? nextError.message : "MCP schema unavailable");
      });
    return () => {
      active = false;
    };
  }, [selectedName]);

  const servers = asList(snapshot?.servers);
  const server = servers.find(item => item.name === selectedServer) || null;
  const inputSchema = asSchemaRecord(selectedTool?.inputSchema);
  const properties = schemaArgumentProperties(inputSchema);
  const required = schemaRequiredArguments(inputSchema);

  const searchTools = async event => {
    event.preventDefault();
    if (!selectedServer) return;
    setState("searching");
    setError("");
    setReceipt(null);
    try {
      const result = await callNeyvia("search_mcp_tools_command", {
        query,
        server: selectedServer,
        limit: 20,
      });
      const rows = asList(result.tools);
      setTools(rows);
      setSelectedName(rows[0]?.qualifiedName || "");
      setState("ready");
    } catch (nextError) {
      setState("ready");
      setError(nextError instanceof Error ? nextError.message : "MCP tool search failed");
    }
  };

  const execute = async event => {
    event.preventDefault();
    setError("");
    setReceipt(null);
    try {
      const argumentsPayload = buildSchemaArguments(inputSchema, values, extraArguments);
      setState("executing");
      const result = await callNeyvia("call_mcp_tool_command", {
        name: selectedTool.qualifiedName,
        arguments: argumentsPayload,
        approved: confirmed,
      });
      setReceipt(result);
      setConfirmed(false);
      setState("ready");
    } catch (nextError) {
      setState("ready");
      setError(nextError instanceof Error ? nextError.message : "MCP call failed");
    }
  };

  return (
    <section className="neyvia-mcp-broker" data-neyvia-mcp-broker="true">
      <header>
        <div>
          <span><Network aria-hidden="true" size={14} /> Outbound tool broker</span>
          <h3>Brokered tools</h3>
          <p>Only configured servers appear. Schemas load after search, and every call returns the broker’s real approval receipt.</p>
        </div>
        <button aria-label="Refresh MCP servers" onClick={() => void loadSnapshot()} type="button">
          <RefreshCw aria-hidden="true" size={14} />
        </button>
      </header>

      {error ? <div className="neyvia-mcp-alert" role="alert"><AlertTriangle aria-hidden="true" size={15} /> {error}</div> : null}
      {state === "unavailable" ? (
        <p className="neyvia-empty-hint">The MCP broker is unavailable. No external tools are shown as callable.</p>
      ) : state === "ready" && !servers.length ? (
        <div className="neyvia-mcp-empty">
          <Server aria-hidden="true" size={20} />
          <strong>No MCP servers configured for this workspace</strong>
          <p>Provider setup can add real stdio servers later. Neyvia does not insert a demo server into the product.</p>
        </div>
      ) : (
        <div className="neyvia-mcp-layout">
          <aside>
            <strong>Configured servers</strong>
            <div className="neyvia-mcp-servers" role="list">
              {servers.map(item => (
                <button
                  aria-current={selectedServer === item.name ? "true" : undefined}
                  className={selectedServer === item.name ? "is-selected" : undefined}
                  key={item.name}
                  onClick={() => setSelectedServer(item.name)}
                  role="listitem"
                  type="button"
                >
                  <Server aria-hidden="true" size={15} />
                  <span><b>{item.name}</b><small>{item.transport} · {item.authState}</small></span>
                  <em data-tone={statusTone(item)}>{item.callable ? "Callable" : "Not callable"}</em>
                </button>
              ))}
            </div>
            {server ? (
              <div className="neyvia-mcp-server-facts">
                <span>Auth <b>{server.authState}</b></span>
                <span>Transport <b>{server.transport}</b></span>
                <span>Cached tools <b>{server.toolCountCached ?? "not loaded"}</b></span>
                <span>Environment <b>{server.hasEnvironment ? "configured, hidden" : "none reported"}</b></span>
                {asList(server.notes).map(note => <small key={note}>{note}</small>)}
              </div>
            ) : null}
          </aside>

          <div className="neyvia-mcp-workspace">
            <form className="neyvia-mcp-search" onSubmit={searchTools}>
              <Search aria-hidden="true" size={15} />
              <input
                aria-label="Search selected MCP server"
                onChange={event => setQuery(event.target.value)}
                placeholder="Search tools on this server"
                value={query}
              />
              <button disabled={!selectedServer || state === "searching"} type="submit">
                {state === "searching" ? "Searching…" : "Search"}
              </button>
              <small>Searching a callable stdio server may start its configured local process. Full schemas stay deferred until selection.</small>
            </form>

            {state === "ready" && selectedServer && !tools.length ? (
              <p className="neyvia-empty-hint">Search this server to load its real tool catalog. Nothing is inferred from its name.</p>
            ) : null}

            {tools.length ? (
              <div className="neyvia-mcp-tools-layout">
                <div className="neyvia-mcp-tools" role="list">
                  {tools.map(tool => (
                    <button
                      aria-current={selectedName === tool.qualifiedName ? "true" : undefined}
                      className={selectedName === tool.qualifiedName ? "is-selected" : undefined}
                      key={tool.qualifiedName}
                      onClick={() => setSelectedName(tool.qualifiedName)}
                      role="listitem"
                      type="button"
                    >
                      <strong>{tool.name}</strong>
                      <p>{tool.description || "No description reported."}</p>
                      <small>{tool.requiresApproval ? "Approval required" : "Read-only hint"}</small>
                    </button>
                  ))}
                </div>

                {selectedTool ? (
                  <form className="neyvia-mcp-runner" onSubmit={execute}>
                    <div className="neyvia-mcp-runner-head">
                      <div><span>{selectedTool.server}</span><h4>{selectedTool.name}</h4><code>{selectedTool.qualifiedName}</code></div>
                      <em data-tone={selectedTool.available ? "positive" : "warning"}>{selectedTool.available ? "Callable" : "Unavailable"}</em>
                    </div>
                    <p>{selectedTool.description}</p>
                    <fieldset>
                      <legend>Arguments</legend>
                      {properties.map(([name, schema]) => {
                        const type = String(schema?.type || "string");
                        return (
                          <label key={name}>
                            <span>{schema?.title || name}{required.has(name) ? " *" : ""}</span>
                            {type === "boolean" ? (
                              <input checked={Boolean(values[name])} onChange={event => setValues(current => ({ ...current, [name]: event.target.checked }))} type="checkbox" />
                            ) : type === "object" || type === "array" ? (
                              <textarea onChange={event => setValues(current => ({ ...current, [name]: event.target.value }))} placeholder={type === "array" ? "[]" : "{}"} required={required.has(name)} rows={3} value={values[name] || ""} />
                            ) : (
                              <input onChange={event => setValues(current => ({ ...current, [name]: event.target.value }))} required={required.has(name)} type={type === "number" || type === "integer" ? "number" : "text"} value={values[name] || ""} />
                            )}
                            {schema?.description ? <small>{schema.description}</small> : null}
                          </label>
                        );
                      })}
                      {!properties.length ? <p>No declared fields. Use the JSON object below only if the schema permits additional values.</p> : null}
                      <label><span>Additional arguments (JSON object)</span><textarea onChange={event => setExtraArguments(event.target.value)} placeholder="{}" rows={3} value={extraArguments} /></label>
                    </fieldset>
                    <label className="neyvia-mcp-confirm">
                      <input checked={confirmed} onChange={event => setConfirmed(event.target.checked)} type="checkbox" />
                      <span><ShieldCheck aria-hidden="true" size={14} /> Approve this one call to <code>{selectedTool.qualifiedName}</code>{selectedTool.requiresApproval ? " (mutating call)" : ""}.</span>
                    </label>
                    <button className="neyvia-mcp-execute" disabled={!selectedTool.available || !confirmed || state === "executing"} type="submit">
                      <Play aria-hidden="true" size={14} /> {state === "executing" ? "Calling…" : "Call once"}
                    </button>
                    {receipt ? (
                      <div className="neyvia-mcp-receipt" data-status={receipt.ok ? "success" : "failed"}>
                        <strong>{receipt.ok ? <CheckCircle2 aria-hidden="true" size={15} /> : <AlertTriangle aria-hidden="true" size={15} />}{receipt.status}</strong>
                        <p>{receipt.ok ? "MCP call completed and the receipt was retained." : "The broker blocked or failed the call; inspect its real status below."}</p>
                        <pre>{JSON.stringify(receipt, null, 2)}</pre>
                      </div>
                    ) : null}
                  </form>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}
