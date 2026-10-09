import { useState } from "react";
import { ShieldAlert, RefreshCw } from "lucide-react";

export function NeyviaClaudeSubscription({ callBackend }) {
  const [status, setStatus] = useState(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function run(action) {
    setBusy(true);
    setMessage("");
    try {
      if (action) {
        const result = await callBackend("setup_hermes_subscription_command", { action, acknowledged });
        setMessage(result.message);
      }
      setStatus(await callBackend("get_hermes_subscription_status_command", {}));
    } catch (error) {
      setMessage(String(error?.message || error));
    } finally { setBusy(false); }
  }
  return <section className="neyvia-provider-auth" aria-label="Claude subscription through Hermes">
    <header><strong>Claude subscription · Hermes</strong><em>Experimental</em></header>
    <p>Hermes runs the tools and work loop; the official Claude CLI supplies model access using its signed-in account.</p>
    <p><ShieldAlert size={14} aria-hidden="true" /> Anthropic has not certified this integration. Account restrictions and billing remain under its control; no ban-free guarantee. Turn off extra usage in your Claude account to avoid overage charges.</p>
    <p><a href="https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account" target="_blank" rel="noreferrer">Anthropic account guidance</a>{" · "}<a href="https://hermes-agent.nousresearch.com/docs/plugins/claude-subscription-directsdk" target="_blank" rel="noreferrer">Plugin details</a></p>
    <label className="neyvia-subscription-ack"><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} /> <span>I understand this is an experimental third-party route.</span></label>
    <div className="neyvia-provider-auth__actions">
      <button type="button" disabled={busy} onClick={() => run()}><RefreshCw size={14} /> Check readiness</button>
      <button type="button" disabled={busy || !acknowledged || !status?.compatible} onClick={() => run("install")}>Install plugin</button>
      <button type="button" disabled={busy || !acknowledged || !status?.compatible || !status?.claudeInstalled} onClick={() => run("login")}>Sign in with Claude CLI</button>
      {status?.acknowledged
        ? <button type="button" disabled={busy} onClick={() => run("disable")}>Disable route</button>
        : <button type="button" disabled={busy || !acknowledged || !status?.ready} onClick={() => run("acknowledge")}>Enable for this workspace</button>}
    </div>
    <p role="status">{busy ? "Checking this host…" : message || status?.message || "Check this host before installing or enabling. Existing chats stay on their selected route."}</p>
    {status?.acknowledged && <p>Select “Claude subscription · Hermes (experimental)” in the chat provider picker. This uses Hermes orchestration, not Neyvia’s native loop.</p>}
  </section>;
}
