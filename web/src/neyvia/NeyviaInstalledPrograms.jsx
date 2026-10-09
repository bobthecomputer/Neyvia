import { useEffect, useRef, useState } from "react";
import { usePoller } from "./usePoller.js";

export function NeyviaInstalledPrograms({ callBackend, onOpenPreview, onSendInspection }) {
  const [programs, setPrograms] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [executable, setExecutable] = useState("");
  const [argumentsText, setArgumentsText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [opened, setOpened] = useState(false);
  const [previewUrls, setPreviewUrls] = useState({});
  const [inspections, setInspections] = useState({});
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function tool(name, args = {}) {
    if (!callBackend) throw new Error("The Neyvia backend connection is unavailable.");
    const receipt = await callBackend("call_native_tool_command", { tool: name, arguments: args });
    if (!receipt?.ok) throw new Error(receipt?.error || "Program operation failed");
    return receipt.result?.session || receipt.result;
  }
  async function refresh() {
    const result = await tool("host.sessions");
    if (mounted.current) setSessions(result.sessions);
  }
  // 2.5 s while the list changes, backing off to 30 s when it does not; nothing while the page is hidden.
  usePoller(async () => (await tool("host.sessions")).sessions, {
    enabled: opened, activeMs: 2500, maxMs: 30000,
    onValue: sessions => setSessions(sessions), onError: reason => setError(String(reason.message || reason)),
  });
  async function act(callback) {
    setBusy(true); setError("");
    try { await callback(); await refresh(); }
    catch (reason) { if (mounted.current) setError(String(reason.message || reason)); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <details className="neyvia-preview-search" onToggle={event => setOpened(event.currentTarget.open)}>
    <summary>Run an installed program</summary>
    <p>Reuse software on the connected host. Each session has its own working and temporary folders and a one-hour time limit. Programs retain your host access; this is not a security sandbox. Native windows open on that host.</p>
    <button disabled={busy} type="button" onClick={() => act(async () => {
      const result = await tool("host.programs"); setPrograms(result.programs);
    })}>Find installed programs</button>
    {programs.length > 0 && <select aria-label="Installed programs" value={executable}
      onChange={event => setExecutable(event.target.value)}>
      <option value="">Choose a program</option>
      {programs.map(program => <option key={program.path} value={program.path}>{program.name} — {program.path}</option>)}
    </select>}
    <form onSubmit={event => { event.preventDefault(); const script = /\.(py|[cm]?js)$/i.test(executable.trim()); act(() => tool(script ? "host.launch_file" : "host.launch", {
      ...(script ? {path: executable.trim()} : {executable: executable.trim()}), arguments: argumentsText ? argumentsText.split("\n").map(line => line.replace(/\r$/, "")) : [],
    })); }}>
      <label>Program or workspace script path<input aria-label="Existing executable path" required value={executable}
        onChange={event => setExecutable(event.target.value)} placeholder="Choose above or paste an existing executable path" /></label>
      <label>Arguments, one per line<textarea aria-label="Program arguments" value={argumentsText}
        onChange={event => setArgumentsText(event.target.value)} rows={3} placeholder="Optional" /></label>
      <button type="submit" disabled={busy || !executable.trim()}>Run in own working folder</button>
      <p>Python and JavaScript files use an existing runtime. Missing dependencies are reported without installing them.</p>
    </form>
    {error && <p role="alert">{error}</p>}
    <div aria-live="polite">{sessions.map(session => <details key={session.sessionId}>
      <summary>{session.executable.split(/[\\/]/).pop()} · {session.status}</summary>
      <p>{session.workingDirectory}</p>
      {session.sourceRecipe && <p>{session.sourceRecipe.reason}</p>}
      <p>Session controls: {session.control?.owner === "agent" ? "Agent" : "You"}</p>
      {["queued", "starting", "running"].includes(session.status) && <button type="button" disabled={busy}
        onClick={() => act(() => callBackend("set_host_session_control_command", {
          sessionId: session.sessionId, owner: session.control?.owner === "agent" ? "operator" : "agent",
          expectedRevision: session.control?.revision ?? 0,
        }))}>{session.control?.owner === "agent" ? "Take back session controls" : "Let agent manage session"}</button>}
      {session.error && <p role="alert">{session.error}</p>}
      {session.message && <p>{session.message}</p>}
      <pre>{session.stdout || session.stderr || "No captured output yet."}</pre>
      {session.stdout && session.stderr && <pre>{session.stderr}</pre>}
      {session.outputTruncated && <p>Captured output was limited.</p>}
      {session.status === "running" && <form onSubmit={event => {
        event.preventDefault();
        setInspections(current => ({ ...current, [session.sessionId]: null }));
        act(async () => {
          const result = await tool("host.inspect_preview", { sessionId: session.sessionId,
            url: previewUrls[session.sessionId] ?? session.preview?.url ?? "" });
          if (mounted.current) setInspections(current => ({ ...current, [session.sessionId]: result.preview }));
        });
      }}>
        <label>Local web address<input aria-label={`Local web address for ${session.sessionId}`}
          placeholder="http://127.0.0.1:3000" required type="url"
          value={previewUrls[session.sessionId] ?? session.preview?.url ?? ""}
          onChange={event => { setPreviewUrls(current => ({ ...current, [session.sessionId]: event.target.value }));
            setInspections(current => ({ ...current, [session.sessionId]: null })); }} /></label>
        <button disabled={busy} type="submit">Inspect on connected host</button>
      </form>}
      {session.preview && <p>Last inspected {new Date(session.preview.observedAt * 1000).toLocaleTimeString()} · HTTP {session.preview.httpStatus}. Endpoint ownership by this process is unverified.</p>}
      {inspections[session.sessionId] && <div>
        <pre>{inspections[session.sessionId].text}</pre>
        {inspections[session.sessionId].truncated && <p>Response excerpt limited.</p>}
        <p>This is fetched content. Signed-in browser state and live page changes are not included.</p>
        {onSendInspection && <button type="button" onClick={() => {
          const preview = inspections[session.sessionId];
          onSendInspection({ title: "Installed-program endpoint inspection", targetUrl: preview.url,
            textSnippet: preview.text, selector: `session ${session.sessionId}`,
            comment: `Observed ${new Date(preview.observedAt * 1000).toISOString()}; response SHA-256 ${preview.contentSha256}; process ownership unverified.` });
        }}>Send inspection to Agent</button>}
        {onOpenPreview && session.status === "running" && <>
          <button type="button" onClick={() => onOpenPreview(inspections[session.sessionId].url)}>Load URL in this device’s Preview</button>
          <p>Loading the local URL requires this device to be the execution host. Inspection above also works from another device.</p>
        </>}
      </div>}
      {["queued", "starting", "running", "unknown"].includes(session.status) &&
        <button type="button" disabled={busy} onClick={() => act(() => tool("host.stop", { sessionId: session.sessionId }))}>Stop session</button>}
    </details>)}</div>
  </details>;
}
