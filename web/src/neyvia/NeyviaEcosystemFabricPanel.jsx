import { useEffect, useMemo, useState } from "react";
import {
  Check,
  Clipboard,
  ExternalLink,
  Mail,
  RefreshCw,
  Share2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import {
  COMMUNICATION_ROUTES,
  COMMUNICATION_STATES,
  PRESENTATION_PROFILES,
  buildCommunicationAccountPayload,
  canInsertPresentationPrompt,
  communicationStateTone,
  normalizeCommunicationFabric,
  permissionApprovalLabel,
} from "./neyviaEcosystemFabricModel.js";
import { buildPresentationCapturePayload } from "./neyviaEcosystemActionModel.js";

async function callNeyvia(command, payload = {}) {
  const response = await fetch("/api/backend", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, payload }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) {
    throw new Error(result?.error || `${command} failed`);
  }
  return result?.data || {};
}

const INITIAL_ACCOUNT = Object.freeze({
  label: "",
  addressHint: "",
  organization: "",
  route: "file-import",
  state: "not-configured",
  limitation: "",
  permissions: ["read", "draft"],
});

function stateLabel(state) {
  return COMMUNICATION_STATES.find(item => item.id === state)?.label || state || "Not reported";
}

function routeLabel(route) {
  return COMMUNICATION_ROUTES.find(item => item.id === route)?.label || route || "Unknown route";
}

export function NeyviaEcosystemFabricPanel({ onRequestAction }) {
  const [activeTab, setActiveTab] = useState("communication");
  const [fabricState, setFabricState] = useState("loading");
  const [fabric, setFabric] = useState(normalizeCommunicationFabric(null));
  const [error, setError] = useState("");
  const [accountForm, setAccountForm] = useState(INITIAL_ACCOUNT);
  const [prompt, setPrompt] = useState("");
  const [profile, setProfile] = useState("explanation");
  const [compiledPrompt, setCompiledPrompt] = useState(null);
  const [copyState, setCopyState] = useState("idle");
  const [shareContent, setShareContent] = useState("");
  const [shareMode, setShareMode] = useState("standard-export");
  const [shareScan, setShareScan] = useState(null);
  const [shareCapsule, setShareCapsule] = useState(null);
  const [captureForm, setCaptureForm] = useState({
    source: "https://chatgpt.com/",
    content: "",
    destinationKind: "project",
    destinationId: "",
    userInitiated: false,
  });
  const [captureReceipt, setCaptureReceipt] = useState(null);
  const [archiveForm, setArchiveForm] = useState({
    accountId: "",
    sourcePath: "",
    userInitiated: false,
  });
  const [archiveInspection, setArchiveInspection] = useState(null);
  const [archiveReceipt, setArchiveReceipt] = useState(null);

  const refreshFabric = async () => {
    setFabricState("loading");
    setError("");
    try {
      const data = await callNeyvia("get_communication_fabric_command");
      setFabric(normalizeCommunicationFabric(data));
      setFabricState("ready");
    } catch (nextError) {
      setFabricState("unavailable");
      setError(nextError instanceof Error ? nextError.message : "Communication fabric unavailable");
    }
  };

  useEffect(() => {
    refreshFabric();
  }, []);

  const permissionRows = useMemo(() => {
    if (fabric.permissionLadder.length) return fabric.permissionLadder;
    return ["read", "draft", "send", "forward", "delete", "unsubscribe"].map(permission => ({
      permission,
      approval: permissionApprovalLabel(permission),
    }));
  }, [fabric.permissionLadder]);

  const registerAccount = async event => {
    event.preventDefault();
    setError("");
    try {
      await callNeyvia(
        "register_communication_account_command",
        buildCommunicationAccountPayload(accountForm),
      );
      setAccountForm(INITIAL_ACCOUNT);
      await refreshFabric();
      onRequestAction?.("neyvia:ecosystem:communication-account-registered", {
        route: accountForm.route,
        state: accountForm.state,
      });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Account route could not be saved");
    }
  };

  const compilePrompt = async event => {
    event.preventDefault();
    setError("");
    setCompiledPrompt(null);
    try {
      const result = await callNeyvia("compile_chatgpt_presentation_prompt_command", {
        profile,
        prompt,
        context: {
          source: "Neyvia Library",
          transferMode: "explicit-user-reviewed",
        },
      });
      setCompiledPrompt(result);
      setCopyState("idle");
      onRequestAction?.("neyvia:ecosystem:presentation-prompt-compiled", { profile });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Prompt could not be prepared");
    }
  };

  const copyCompiledPrompt = async () => {
    if (!canInsertPresentationPrompt(compiledPrompt)) return;
    await navigator.clipboard.writeText(compiledPrompt.compiled);
    setCopyState("copied");
  };

  const scanShare = async event => {
    event.preventDefault();
    setError("");
    setShareCapsule(null);
    try {
      const scan = await callNeyvia("scan_share_capsule_command", {
        content: { result: shareContent },
      });
      setShareScan(scan);
      onRequestAction?.("neyvia:ecosystem:share-capsule-scanned", {
        blocked: scan.blocked === true,
        findingCount: scan.findings?.length || 0,
      });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Share content could not be inspected");
    }
  };

  const prepareShare = async () => {
    if (!shareScan || shareScan.blocked) return;
    setError("");
    try {
      const capsule = await callNeyvia("build_share_capsule_command", {
        mode: shareMode,
        selection: ["result"],
        content: { result: shareContent },
      });
      setShareCapsule(capsule);
      onRequestAction?.("neyvia:ecosystem:share-capsule-prepared", {
        capsuleId: capsule.capsuleId,
        transportState: capsule.transportState,
      });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Share Capsule could not be prepared");
    }
  };

  const capturePresentationContent = async event => {
    event.preventDefault();
    setError("");
    setCaptureReceipt(null);
    try {
      const receipt = await callNeyvia(
        "capture_chatgpt_presentation_content_command",
        buildPresentationCapturePayload(captureForm),
      );
      setCaptureReceipt(receipt);
      onRequestAction?.("neyvia:ecosystem:presentation-content-captured", {
        captureId: receipt.captureId,
        destinationKind: captureForm.destinationKind,
      });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Content could not be captured");
    }
  };

  const inspectArchive = async event => {
    event.preventDefault();
    setError("");
    setArchiveInspection(null);
    setArchiveReceipt(null);
    try {
      const inspection = await callNeyvia("inspect_communication_archive_command", {
        sourcePath: archiveForm.sourcePath,
        limit: 100,
        userInitiated: archiveForm.userInitiated,
      });
      setArchiveInspection(inspection);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Archive could not be inspected");
    }
  };

  const importArchive = async () => {
    if (!archiveInspection || archiveInspection.status !== "ready" || !archiveForm.accountId) return;
    setError("");
    try {
      const receipt = await callNeyvia("import_communication_archive_command", {
        accountId: archiveForm.accountId,
        sourcePath: archiveForm.sourcePath,
        limit: 100,
        userInitiated: archiveForm.userInitiated,
      });
      setArchiveReceipt(receipt);
      await refreshFabric();
      onRequestAction?.("neyvia:ecosystem:communication-archive-imported", {
        importId: receipt.importId,
        messageCount: receipt.summary?.messageCount || 0,
      });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Archive could not be imported");
    }
  };

  return (
    <section
      aria-label="Ecosystem connections"
      className="neyvia-ecosystem-fabric"
      data-neyvia-ecosystem-fabric="true"
    >
      <header className="neyvia-ecosystem-fabric-head">
        <div>
          <span className="neyvia-surface-eyebrow"><ExternalLink aria-hidden="true" size={14} /> Ecosystem</span>
          <h3>Connections that keep Neyvia in control</h3>
          <p>Use provider, local, or file routes without pretending an organization restriction has disappeared.</p>
        </div>
        <div className="neyvia-ecosystem-tabs" role="tablist" aria-label="Ecosystem connection type">
          <button
            aria-selected={activeTab === "communication"}
            className={activeTab === "communication" ? "is-selected" : undefined}
            onClick={() => setActiveTab("communication")}
            role="tab"
            type="button"
          >
            <Mail aria-hidden="true" size={14} /> Communication
          </button>
          <button
            aria-selected={activeTab === "presentation"}
            className={activeTab === "presentation" ? "is-selected" : undefined}
            onClick={() => setActiveTab("presentation")}
            role="tab"
            type="button"
          >
            <Sparkles aria-hidden="true" size={14} /> ChatGPT bridge
          </button>
          <button
            aria-selected={activeTab === "sharing"}
            className={activeTab === "sharing" ? "is-selected" : undefined}
            onClick={() => setActiveTab("sharing")}
            role="tab"
            type="button"
          >
            <Share2 aria-hidden="true" size={14} /> Share
          </button>
        </div>
      </header>

      {error ? <div className="neyvia-ecosystem-error" role="alert">{error}</div> : null}

      {activeTab === "communication" ? (
        <div className="neyvia-ecosystem-columns" role="tabpanel">
          <div>
            <div className="neyvia-ecosystem-section-title">
              <div>
                <strong>Accounts and local routes</strong>
                <span>{fabric.accounts.length} configured</span>
              </div>
              <button aria-label="Refresh communication accounts" onClick={refreshFabric} type="button">
                <RefreshCw aria-hidden="true" size={14} />
              </button>
            </div>
            {fabricState === "loading" ? <p className="neyvia-empty-hint">Reading connection readiness…</p> : null}
            {fabricState === "unavailable" ? (
              <p className="neyvia-empty-hint">Backend unavailable. No account is presented as connected.</p>
            ) : null}
            {fabricState === "ready" && !fabric.accounts.length ? (
              <p className="neyvia-empty-hint">No communication route configured yet.</p>
            ) : null}
            <div className="neyvia-communication-accounts" role="list">
              {fabric.accounts.map(account => (
                <article data-connection-state={account.state} key={account.accountId} role="listitem">
                  <div>
                    <strong>{account.label}</strong>
                    <span>{account.addressHint || account.organization || "No address stored"}</span>
                  </div>
                  <em data-tone={communicationStateTone(account.state)}>{stateLabel(account.state)}</em>
                  <p>{routeLabel(account.route)}{account.limitation ? ` · ${account.limitation}` : ""}</p>
                  <small>{(account.permissions || []).join(" · ") || "No permissions granted"}</small>
                </article>
              ))}
            </div>
          </div>

          <form className="neyvia-connection-form" onSubmit={registerAccount}>
            <strong>Add a connection</strong>
            <p>Save readiness and limitations only. Secrets stay in the secret broker.</p>
            <label>
              Label
              <input
                onChange={event => setAccountForm(current => ({ ...current, label: event.target.value }))}
                placeholder="Personal Gmail"
                required
                value={accountForm.label}
              />
            </label>
            <label>
              Address hint
              <input
                onChange={event => setAccountForm(current => ({ ...current, addressHint: event.target.value }))}
                placeholder="p…@example.com"
                value={accountForm.addressHint}
              />
            </label>
            <label>
              Route
              <select
                onChange={event => setAccountForm(current => ({ ...current, route: event.target.value }))}
                value={accountForm.route}
              >
                {COMMUNICATION_ROUTES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </label>
            <label>
              Current readiness
              <select
                onChange={event => setAccountForm(current => ({ ...current, state: event.target.value }))}
                value={accountForm.state}
              >
                {COMMUNICATION_STATES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </label>
            <label>
              Organization or limitation
              <input
                onChange={event => setAccountForm(current => ({ ...current, limitation: event.target.value }))}
                placeholder="Optional — approval policy, import-only…"
                value={accountForm.limitation}
              />
            </label>
            <button className="primary" type="submit">Save connection truth</button>
          </form>

          <div className="neyvia-permission-ladder">
            <strong><ShieldCheck aria-hidden="true" size={15} /> Permission ladder</strong>
            {permissionRows.map(row => (
              <div key={row.permission}>
                <span>{row.permission}</span>
                <small>
                  {row.approval === "per-action"
                    ? "Confirm each action"
                    : row.approval === "per-account"
                      ? "Approve for this account"
                      : row.approval}
                </small>
              </div>
            ))}
          </div>
          <form className="neyvia-archive-import" onSubmit={inspectArchive}>
            <div>
              <strong>Local mailbox intake</strong>
              <p>Real EML file/folder and Maildir parsing. MSG stays blocked until a declared parser is installed.</p>
            </div>
            <label>
              Local archive account
              <select
                onChange={event => setArchiveForm(current => ({ ...current, accountId: event.target.value }))}
                required
                value={archiveForm.accountId}
              >
                <option value="">Choose account</option>
                {fabric.accounts
                  .filter(account => ["file-import", "outlook-bridge", "thunderbird-bridge"].includes(account.route))
                  .map(account => <option key={account.accountId} value={account.accountId}>{account.label}</option>)}
              </select>
            </label>
            <label>
              EML, EML folder, Maildir, or MSG path
              <input
                onChange={event => {
                  setArchiveForm(current => ({ ...current, sourcePath: event.target.value }));
                  setArchiveInspection(null);
                  setArchiveReceipt(null);
                }}
                placeholder="C:\Mail\Export or /volume1/mail/archive"
                required
                value={archiveForm.sourcePath}
              />
            </label>
            <label className="neyvia-explicit-checkbox">
              <input
                checked={archiveForm.userInitiated}
                onChange={event => setArchiveForm(current => ({ ...current, userInitiated: event.target.checked }))}
                type="checkbox"
              />
              I explicitly selected this local source for inspection.
            </label>
            <button disabled={!archiveForm.userInitiated || !archiveForm.accountId} type="submit">Inspect archive</button>
            {archiveInspection ? (
              <div className="neyvia-archive-inspection" data-archive-status={archiveInspection.status}>
                <strong>{archiveInspection.status === "ready" ? `${archiveInspection.messageCount} messages ready` : archiveInspection.status}</strong>
                <span>{archiveInspection.format} · {archiveInspection.attachmentCount} attachments</span>
                {(archiveInspection.limitations || []).map(item => <small key={item}>{item}</small>)}
                <button disabled={archiveInspection.status !== "ready" || Boolean(archiveReceipt)} onClick={importArchive} type="button">
                  {archiveReceipt ? "Imported locally" : "Import with receipt"}
                </button>
              </div>
            ) : null}
            {fabric.imports.length ? <small>{fabric.imports.length} recent durable import receipt{fabric.imports.length === 1 ? "" : "s"}</small> : null}
          </form>
        </div>
      ) : activeTab === "presentation" ? (
        <div className="neyvia-presentation-bridge" role="tabpanel">
          <form onSubmit={compilePrompt}>
            <div>
              <strong>Prepare for ChatGPT.com</strong>
              <p>Neyvia adds the selected task profile visibly. You review and insert it yourself.</p>
            </div>
            <label>
              Task profile
              <select onChange={event => setProfile(event.target.value)} value={profile}>
                {PRESENTATION_PROFILES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </label>
            <label>
              What do you want to ask?
              <textarea
                onChange={event => setPrompt(event.target.value)}
                placeholder="Keep the full intent here. Neyvia will append the profile and reviewed context."
                required
                rows={7}
                value={prompt}
              />
            </label>
            <button className="primary" type="submit">Prepare visible prompt</button>
          </form>
          <article className="neyvia-compiled-prompt" data-prompt-ready={canInsertPresentationPrompt(compiledPrompt)}>
            <div>
              <strong>Prepared handoff</strong>
              <span>No automated login · no transcript harvesting</span>
            </div>
            {canInsertPresentationPrompt(compiledPrompt) ? (
              <>
                <pre>{compiledPrompt.compiled}</pre>
                <button onClick={copyCompiledPrompt} type="button">
                  {copyState === "copied" ? <Check aria-hidden="true" size={14} /> : <Clipboard aria-hidden="true" size={14} />}
                  {copyState === "copied" ? "Copied" : "Copy for ChatGPT"}
                </button>
              </>
            ) : (
              <p className="neyvia-empty-hint">Prepare a prompt to review the exact additions before copying.</p>
            )}
          </article>
          <form className="neyvia-presentation-capture" onSubmit={capturePresentationContent}>
            <div>
              <strong>Capture back into Neyvia</strong>
              <p>Select or export content yourself, then attach it with source lineage.</p>
            </div>
            <label>
              Source URL or explicit file export
              <input
                onChange={event => setCaptureForm(current => ({ ...current, source: event.target.value }))}
                required
                type="url"
                value={captureForm.source}
              />
            </label>
            <label>
              Selected content
              <textarea
                onChange={event => setCaptureForm(current => ({ ...current, content: event.target.value }))}
                required
                rows={6}
                value={captureForm.content}
              />
            </label>
            <div className="neyvia-capture-destination">
              <label>
                Attach to
                <select
                  onChange={event => setCaptureForm(current => ({ ...current, destinationKind: event.target.value }))}
                  value={captureForm.destinationKind}
                >
                  <option value="project">Project</option>
                  <option value="conversation">Conversation</option>
                  <option value="mission">Mission</option>
                </select>
              </label>
              <label>
                Destination ID
                <input
                  onChange={event => setCaptureForm(current => ({ ...current, destinationId: event.target.value }))}
                  placeholder="Optional when attaching later"
                  value={captureForm.destinationId}
                />
              </label>
            </div>
            <label className="neyvia-explicit-checkbox">
              <input
                checked={captureForm.userInitiated}
                onChange={event => setCaptureForm(current => ({ ...current, userInitiated: event.target.checked }))}
                type="checkbox"
              />
              I explicitly selected this content and want Neyvia to capture it.
            </label>
            <button className="primary" disabled={!captureForm.userInitiated} type="submit">
              Capture with lineage
            </button>
            {captureReceipt ? (
              <div className="neyvia-capture-receipt">
                <Check aria-hidden="true" size={14} />
                <span>Captured as {captureReceipt.captureId}</span>
                <small>SHA-256 {captureReceipt.contentSha256}</small>
              </div>
            ) : null}
          </form>
        </div>
      ) : (
        <div className="neyvia-share-capsule" role="tabpanel">
          <form onSubmit={scanShare}>
            <div>
              <strong>Prepare a Share Capsule</strong>
              <p>Result only by default. Nothing leaves this device from this step.</p>
            </div>
            <label>
              Mode
              <select onChange={event => setShareMode(event.target.value)} value={shareMode}>
                <option value="standard-export">Standard export</option>
                <option value="private-device">Private device-to-device</option>
                <option value="neyvia-user">Another Neyvia user</option>
                <option value="expiring-link">Expiring link</option>
                <option value="selected-collaborators">Selected collaborators</option>
                <option value="public-showcase">Public showcase</option>
                <option value="forkable-template">Forkable template</option>
                <option value="social-summary">Social summary</option>
              </select>
            </label>
            <label>
              Result to package
              <textarea
                onChange={event => {
                  setShareContent(event.target.value);
                  setShareScan(null);
                  setShareCapsule(null);
                }}
                placeholder="Paste or describe the result. Add explanation, sources, receipts, and editable structure only when intentionally selected."
                required
                rows={8}
                value={shareContent}
              />
            </label>
            <button className="primary" type="submit">Inspect before sharing</button>
          </form>
          <article className="neyvia-share-inspection" data-share-blocked={shareScan?.blocked === true}>
            <div>
              <strong>Pre-share inspection</strong>
              <span>{shareScan ? `${shareScan.findings?.length || 0} findings` : "Not inspected"}</span>
            </div>
            {shareScan ? (
              <>
                <ul>
                  {(shareScan.checks || []).map(check => <li key={check}><Check aria-hidden="true" size={13} /> {check.replaceAll("-", " ")}</li>)}
                </ul>
                {(shareScan.findings || []).map(finding => (
                  <div className="neyvia-share-finding" data-severity={finding.severity} key={finding.findingId}>
                    <strong>{finding.kind.replaceAll("-", " ")}</strong>
                    <span>{finding.location} · {finding.severity}</span>
                    <small>{finding.preview}</small>
                  </div>
                ))}
                <button disabled={shareScan.blocked || Boolean(shareCapsule)} onClick={prepareShare} type="button">
                  {shareCapsule ? <Check aria-hidden="true" size={14} /> : <Share2 aria-hidden="true" size={14} />}
                  {shareCapsule ? "Prepared — not sent" : shareScan.blocked ? "Resolve secret blockers first" : "Prepare capsule"}
                </button>
                {shareCapsule ? <p>Capsule {shareCapsule.capsuleId} is stored locally. Sharing still requires an explicit transport action.</p> : null}
              </>
            ) : (
              <p className="neyvia-empty-hint">Inspect secrets, personal paths, account identifiers, organization declarations, and hidden metadata before preparing.</p>
            )}
          </article>
        </div>
      )}
    </section>
  );
}
