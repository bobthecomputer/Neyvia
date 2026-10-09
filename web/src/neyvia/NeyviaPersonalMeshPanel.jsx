import { useEffect, useRef, useState } from "react";
import { usePoller } from "./usePoller.js";
import {
  FolderSync,
  Network,
  Radio,
  RefreshCw,
  Route,
  Send,
  Shield,
  ShieldOff,
  X,
} from "lucide-react";

import {
  MESH_UNAVAILABLE,
  asList,
  formatBooleanStatus,
  formatBytes,
  formatCount,
  formatDuration,
  formatValue,
  hasMeshSnapshot,
  routeTone,
  settledError,
  settledValue,
  shortHash,
} from "./neyviaPersonalMeshModel.js";
import { neyviaPanelEnterClass } from "./neyviaToolVisuals.js";

async function callNeyvia(command, payload = {}) {
  const response = await fetch("/api/backend", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, payload }),
  });

  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error(`${command} returned an unreadable response`);
  }
  if (!response.ok || !result?.ok) {
    throw new Error(result?.error || `${command} failed`);
  }
  return result.data;
}

function OverlayShell({ title, subtitle, onClose, children }) {
  const dialogRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const enterClass = neyviaPanelEnterClass("personal-mesh");

  useEffect(() => {
    const returnTarget = document.activeElement;
    dialogRef.current?.focus();
    const handleKeyDown = event => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current?.();
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
      className="neyvia-overlay is-wide"
      data-neyvia-overlay="true"
      data-neyvia-panel="personal-mesh"
      role="presentation"
    >
      <button
        aria-label="Close Personal Mesh"
        className="neyvia-overlay-backdrop"
        onClick={onClose}
        tabIndex={-1}
        type="button"
      />
      <div
        aria-describedby="neyvia-personal-mesh-description"
        aria-labelledby="neyvia-personal-mesh-title"
        aria-modal="true"
        className={`neyvia-overlay-card ${enterClass}`}
        data-neyvia-panel-enter="personal-mesh"
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        <header>
          <div>
            <h2 id="neyvia-personal-mesh-title">{title}</h2>
            <p id="neyvia-personal-mesh-description">{subtitle}</p>
          </div>
          <button aria-label="Close Personal Mesh" onClick={onClose} type="button">
            <X aria-hidden="true" size={16} />
          </button>
        </header>
        <div className="neyvia-overlay-body">{children}</div>
      </div>
    </div>
  );
}

function StatusLine({ label, value, tone = "neutral" }) {
  return (
    <span className="neyvia-personal-mesh-status" data-tone={tone}>
      <strong>{label}</strong>
      <span>{value}</span>
    </span>
  );
}

function SectionError({ children }) {
  if (!children) return null;
  return (
    <p className="neyvia-personal-mesh-banner" data-tone="failed" role="alert">
      {children}
    </p>
  );
}

function EmptyState({ children, unavailable = false }) {
  return (
    <p
      className="neyvia-personal-mesh-empty"
      data-state={unavailable ? "unavailable" : "empty"}
    >
      {children}
    </p>
  );
}

const TABS = Object.freeze([
  { id: "trust", label: "Trust & enrollment", Icon: Shield },
  { id: "nearby", label: "Nearby Send", Icon: Send },
  { id: "sync", label: "Folder Sync", Icon: FolderSync },
]);

export function NeyviaPersonalMeshPanel({ open = false, onClose }) {
  const [tab, setTab] = useState("trust");
  const [state, setState] = useState("idle");
  const [refreshError, setRefreshError] = useState("");
  const [sectionErrors, setSectionErrors] = useState({ trust: "", nearby: "", sync: "" });
  const [trust, setTrust] = useState(null);
  const [nearbyCompat, setNearbyCompat] = useState(null);
  const [history, setHistory] = useState(null);
  const [activeTransfer, setActiveTransfer] = useState(null);
  const [sidecar, setSidecar] = useState(null);
  const [devices, setDevices] = useState(null);
  const [discoveryState, setDiscoveryState] = useState("idle");
  const [discoveryError, setDiscoveryError] = useState("");
  const [syncCompat, setSyncCompat] = useState(null);
  const [syncHealth, setSyncHealth] = useState(null);
  const [syncHealthState, setSyncHealthState] = useState("idle");
  const [syncHealthError, setSyncHealthError] = useState("");
  const requestGeneration = useRef(0);

  const refresh = async () => {
    const generation = ++requestGeneration.current;
    setState("loading");
    setRefreshError("");

    const results = await Promise.allSettled([
      callNeyvia("get_mesh_enrollment_trust_command", {}),
      callNeyvia("get_nearby_send_compatibility_command", {}),
      callNeyvia("get_nearby_transfer_history_command", { limit: 40 }),
      callNeyvia("get_nearby_active_transfer_command", {}),
      callNeyvia("get_folder_sync_compatibility_command", {}),
      callNeyvia("get_nearby_receiver_sidecar_status_command", {}),
    ]);
    if (generation !== requestGeneration.current) return;

    const [trustResult, nearbyResult, historyResult, activeResult, syncResult, sidecarResult] = results;
    const nextSnapshot = {
      trust: settledValue(trustResult),
      nearbyCompat: settledValue(nearbyResult),
      history: settledValue(historyResult),
      activeTransfer: settledValue(activeResult),
      syncCompat: settledValue(syncResult),
      sidecar: settledValue(sidecarResult),
    };

    setTrust(nextSnapshot.trust);
    setNearbyCompat(nextSnapshot.nearbyCompat);
    setHistory(nextSnapshot.history);
    setActiveTransfer(nextSnapshot.activeTransfer);
    setSyncCompat(nextSnapshot.syncCompat);
    setSidecar(nextSnapshot.sidecar);

    const trustError = settledError(trustResult, "Mesh trust is unavailable.");
    const nearbyErrors = [
      settledError(nearbyResult, "Nearby compatibility is unavailable."),
      settledError(historyResult, "Transfer history is unavailable."),
      settledError(activeResult, "Active transfer state is unavailable."),
      settledError(sidecarResult, "Receiver sidecar state is unavailable."),
    ].filter(Boolean);
    const syncError = settledError(syncResult, "Folder Sync compatibility is unavailable.");
    setSectionErrors({
      trust: trustError,
      nearby: nearbyErrors.join(" "),
      sync: syncError,
    });

    if (hasMeshSnapshot(nextSnapshot)) {
      setState("ready");
      if (results.some(result => result.status === "rejected")) {
        setRefreshError("Some Personal Mesh services are unavailable. Available sections remain live.");
      }
    } else {
      setState("unavailable");
      setRefreshError("Personal Mesh backend unavailable. No status was inferred.");
    }
  };

  useEffect(() => {
    if (!open) {
      requestGeneration.current += 1;
      return undefined;
    }
    void refresh();
    return () => {
      requestGeneration.current += 1;
    };
  }, [open]);

  // A running transfer is followed at 1 s while it moves, backing off to 8 s when it stalls; hidden pages are skipped.
  usePoller(async () => {
    const active = await callNeyvia("get_nearby_active_transfer_command", {});
    setActiveTransfer(active);
    if (active?.active === false) {
      const transfers = await callNeyvia("get_nearby_transfer_history_command", { limit: 40 });
      setHistory(transfers);
    }
    return active;
  }, {
    enabled: Boolean(open) && activeTransfer?.active === true, activeMs: 1000, maxMs: 8000,
    onError: error => setSectionErrors(current => ({
      ...current,
      nearby: `Active transfer refresh failed: ${formatValue(error?.message, "Unknown error")}`,
    })),
  });

  const loadSyncHealth = async () => {
    setSyncHealthState("loading");
    setSyncHealthError("");
    try {
      const health = await callNeyvia("get_folder_sync_health_command", {
        includeFolderStatus: true,
        refresh: true,
      });
      setSyncHealth(health);
      if (health?.available === false) {
        setSyncHealthState("unavailable");
        setSyncHealthError(formatValue(health?.reason, "Syncthing health is unavailable."));
      } else {
        setSyncHealthState("ready");
      }
    } catch (error) {
      setSyncHealth(null);
      setSyncHealthState("unavailable");
      setSyncHealthError(formatValue(error?.message, "Syncthing health is unavailable."));
    }
  };

  useEffect(() => {
    if (!open || tab !== "sync" || syncHealthState !== "idle") return undefined;
    void loadSyncHealth();
    return undefined;
  }, [open, tab, syncHealthState]);

  const discoverNearby = async () => {
    setDiscoveryState("loading");
    setDiscoveryError("");
    try {
      const result = await callNeyvia("discover_nearby_devices_command", { timeoutSeconds: 2 });
      setDevices(result);
      setDiscoveryState("ready");
    } catch (error) {
      setDevices(null);
      setDiscoveryState("unavailable");
      setDiscoveryError(formatValue(error?.message, "Nearby discovery is unavailable."));
    }
  };

  if (!open) return null;

  const snapshot = { trust, nearbyCompat, history, activeTransfer, syncCompat, sidecar };
  const hasSnapshot = hasMeshSnapshot(snapshot);
  const peers = asList(trust?.trust?.peers);
  const gates = asList(trust?.enrollment?.gates);
  const activeServices = asList(trust?.services?.active);
  const transfers = asList(history?.transfers);
  const discovered = asList(devices?.devices);
  const folders = asList(syncHealth?.folders);
  const connections = asList(syncHealth?.connections);
  const progress = activeTransfer?.progress;

  return (
    <OverlayShell
      onClose={onClose}
      subtitle="Live mesh trust, Nearby Send receipts, and Folder Sync state. Missing data stays unavailable."
      title="Personal Mesh"
    >
      <div
        aria-busy={state === "loading" ? "true" : "false"}
        className="neyvia-personal-mesh"
        data-neyvia-personal-mesh="true"
        data-state={state}
      >
        <div className="neyvia-personal-mesh-toolbar">
          <div aria-label="Personal Mesh sections" className="neyvia-personal-mesh-tabs" role="tablist">
            {TABS.map(({ id, label, Icon }) => (
              <button
                aria-controls={`neyvia-personal-mesh-${id}`}
                aria-selected={tab === id}
                className={tab === id ? "is-active" : ""}
                id={`neyvia-personal-mesh-tab-${id}`}
                key={id}
                onClick={() => setTab(id)}
                role="tab"
                tabIndex={tab === id ? 0 : -1}
                type="button"
              >
                <Icon aria-hidden="true" size={14} />
                {label}
              </button>
            ))}
          </div>
          <button
            data-neyvia-mesh-action="refresh"
            disabled={state === "loading"}
            onClick={() => void refresh()}
            type="button"
          >
            <RefreshCw aria-hidden="true" size={14} />
            {state === "loading" ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {state === "loading" ? (
          <p
            aria-live="polite"
            className="neyvia-personal-mesh-banner"
            data-tone="neutral"
            role="status"
          >
            {hasSnapshot ? "Refreshing Personal Mesh state…" : "Loading Personal Mesh state…"}
          </p>
        ) : null}
        {refreshError ? (
          <p className="neyvia-personal-mesh-banner" data-tone={state === "unavailable" ? "failed" : "warn"}>
            {refreshError}
          </p>
        ) : null}

        {!hasSnapshot && state === "loading" ? null : (
          <>
            {tab === "trust" ? (
              <section
                aria-labelledby="neyvia-personal-mesh-tab-trust"
                className="neyvia-personal-mesh-section"
                data-mesh-section="trust"
                id="neyvia-personal-mesh-trust"
                role="tabpanel"
              >
                <header>
                  <h3>
                    <Network aria-hidden="true" size={15} />
                    Device enrollment & trust
                  </h3>
                  <p>
                    Provider {formatValue(trust?.selectedProvider)} · target{" "}
                    {formatValue(trust?.targetProvider)} · cutover{" "}
                    {formatBooleanStatus(trust?.cutoverEnabled)}
                  </p>
                </header>
                <SectionError>{sectionErrors.trust}</SectionError>

                {trust ? (
                  <>
                    <article
                      className="neyvia-personal-mesh-card"
                      data-tone={trust?.enrollment?.available === true ? "good" : "warn"}
                    >
                      <strong>Enrollment</strong>
                      <p>{formatValue(trust?.enrollment?.reason, "No enrollment reason reported.")}</p>
                      {gates.length ? (
                        <ul className="neyvia-personal-mesh-gates">
                          {gates.map((gate, index) => (
                            <li
                              data-passed={gate?.passed === true ? "true" : "false"}
                              key={gate?.gate || `gate-${index}`}
                            >
                              <span>{gate?.passed === true ? "pass" : "blocked"}</span>
                              <strong>{formatValue(gate?.gate)}</strong>
                              <em>{formatValue(gate?.reason, "No reason reported.")}</em>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <EmptyState>No enrollment gates were reported.</EmptyState>
                      )}
                      <div className="neyvia-personal-mesh-status-grid">
                        <StatusLine
                          label="Agent enrollment"
                          value={formatBooleanStatus(trust?.policy?.agentMayEnrollDevices, {
                            trueLabel: "Allowed",
                            falseLabel: "Blocked",
                          })}
                        />
                        <StatusLine
                          label="Device revocation"
                          value={formatBooleanStatus(trust?.policy?.agentMayRevokeDevices, {
                            trueLabel: "Allowed",
                            falseLabel: "Blocked",
                          })}
                        />
                        <StatusLine
                          label="Short-lived setup"
                          value={formatBooleanStatus(trust?.policy?.shortLivedEnrollment)}
                        />
                      </div>
                    </article>

                    <div className="neyvia-personal-mesh-metrics">
                      <div><strong>{formatCount(trust?.trust?.summary?.onlinePeers)}</strong><span>online peers</span></div>
                      <div><strong>{formatCount(trust?.trust?.directActive)}</strong><span>direct</span></div>
                      <div><strong>{formatCount(trust?.trust?.relayedActive)}</strong><span>relayed</span></div>
                      <div><strong>{formatDuration(trust?.durationMs)}</strong><span>snapshot</span></div>
                    </div>

                    <h4><Route aria-hidden="true" size={14} /> Peers · direct vs relay</h4>
                    {peers.length ? (
                      <ul className="neyvia-personal-mesh-list">
                        {peers.map((peer, index) => (
                          <li key={peer?.deviceId || peer?.dnsName || peer?.hostName || `peer-${index}`}>
                            <div>
                              <strong>{formatValue(peer?.hostName || peer?.dnsName || peer?.deviceId)}</strong>
                              <span data-tone={routeTone(peer?.routeState)}>
                                {formatValue(peer?.routeState, "Unknown route")}
                              </span>
                            </div>
                            <p>
                              {formatValue(peer?.os, "Unknown OS")} ·{" "}
                              {asList(peer?.addresses).join(", ") || "No address reported"} ·{" "}
                              {formatBooleanStatus(peer?.online, {
                                trueLabel: "Online",
                                falseLabel: "Offline",
                              })}
                            </p>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <EmptyState>No enrolled bridge peers reported.</EmptyState>
                    )}

                    <h4><ShieldOff aria-hidden="true" size={14} /> Service trust</h4>
                    <p className="neyvia-personal-mesh-note">
                      Device identity revocation:{" "}
                      {formatBooleanStatus(trust?.services?.deviceRevocationImplemented, {
                        trueLabel: "Implemented",
                        falseLabel: "Not implemented",
                      })}
                    </p>
                    {activeServices.length ? (
                      <ul className="neyvia-personal-mesh-list">
                        {activeServices.map((service, index) => (
                          <li key={service?.serviceId || `service-${index}`}>
                            <div>
                              <strong>{formatValue(service?.serviceId)}</strong>
                              <span data-tone="neutral">{formatValue(service?.serviceType, "Service")}</span>
                            </div>
                            <p>{formatValue(service?.endpoint, "Endpoint withheld")}</p>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <EmptyState>No active advertised services.</EmptyState>
                    )}
                  </>
                ) : (
                  <EmptyState unavailable>Trust and enrollment data is unavailable.</EmptyState>
                )}
              </section>
            ) : null}

            {tab === "nearby" ? (
              <section
                aria-labelledby="neyvia-personal-mesh-tab-nearby"
                className="neyvia-personal-mesh-section"
                data-mesh-section="nearby"
                id="neyvia-personal-mesh-nearby"
                role="tabpanel"
              >
                <header>
                  <h3><Radio aria-hidden="true" size={15} /> Nearby Send</h3>
                  <p>
                    Protocol {formatValue(nearbyCompat?.protocol?.name)}{" "}
                    {formatValue(nearbyCompat?.protocol?.version, "")}
                  </p>
                </header>
                <SectionError>{sectionErrors.nearby}</SectionError>

                <article className="neyvia-personal-mesh-card" data-tone="warn">
                  <strong>Physical-device proof</strong>
                  <p>
                    {formatValue(
                      history?.physicalDeviceProof?.reason,
                      "Windows, Android, and NAS transfer proof is unavailable without enrolled devices.",
                    )}
                  </p>
                </article>

                <article className="neyvia-personal-mesh-card">
                  <strong>Compatibility</strong>
                  <div className="neyvia-personal-mesh-status-grid">
                    <StatusLine
                      label="Client installed"
                      value={formatBooleanStatus(nearbyCompat?.client?.installed, {
                        trueLabel: "Installed",
                        falseLabel: "Not installed",
                      })}
                    />
                    <StatusLine
                      label="Binary hash"
                      value={formatBooleanStatus(nearbyCompat?.client?.hashVerified, {
                        trueLabel: "Verified",
                        falseLabel: "Unverified",
                      })}
                    />
                    <StatusLine
                      label="Receiver sidecar"
                      value={formatBooleanStatus(sidecar?.running, {
                        trueLabel: "Running",
                        falseLabel: "Stopped",
                      })}
                    />
                  </div>
                </article>

                {activeTransfer?.active === true && progress ? (
                  <article className="neyvia-personal-mesh-card" data-nearby-active="true" data-tone="warn">
                    <strong>Active transfer · {formatValue(progress?.status)}</strong>
                    <p>
                      Plan {shortHash(progress?.planId)} ·{" "}
                      {formatCount(progress?.summary?.completedFiles)}/
                      {formatCount(progress?.summary?.fileCount)} files ·{" "}
                      {formatBytes(progress?.summary?.bytesSent)} /{" "}
                      {formatBytes(progress?.summary?.totalBytes)}
                    </p>
                    {asList(progress?.files).length ? (
                      <ul className="neyvia-personal-mesh-file-progress">
                        {asList(progress.files).map((file, index) => (
                          <li key={file?.fileId || `active-file-${index}`}>
                            <span>{formatValue(file?.fileName)}</span>
                            <em>{formatValue(file?.state)}</em>
                            <code title={formatValue(file?.sha256, "")}>{shortHash(file?.sha256)}</code>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <EmptyState>No per-file progress was reported.</EmptyState>
                    )}
                    <button className="neyvia-personal-mesh-disabled-action" disabled type="button">
                      Cancellation awaits cooperative backend proof
                    </button>
                  </article>
                ) : activeTransfer?.active === false ? (
                  <EmptyState>No in-flight Nearby Send transfer.</EmptyState>
                ) : (
                  <EmptyState unavailable>Active transfer state is unavailable.</EmptyState>
                )}

                <div className="neyvia-personal-mesh-row-actions">
                  <button
                    disabled={discoveryState === "loading"}
                    onClick={() => void discoverNearby()}
                    type="button"
                  >
                    {discoveryState === "loading" ? "Discovering…" : "Discover nearby devices"}
                  </button>
                </div>
                <SectionError>{discoveryError}</SectionError>
                {devices ? (
                  <article className="neyvia-personal-mesh-card">
                    <strong>
                      Discovery · {formatCount(devices?.summary?.devices ?? discovered.length)} devices
                    </strong>
                    {discovered.length ? (
                      <ul className="neyvia-personal-mesh-list">
                        {discovered.map((device, index) => (
                          <li key={device?.fingerprint || device?.endpoint || `device-${index}`}>
                            <div>
                              <strong>{formatValue(device?.alias || device?.deviceModel, "Unnamed device")}</strong>
                              <span data-tone="neutral">{formatValue(device?.protocol, "Unknown protocol")}</span>
                            </div>
                            <p>
                              {formatValue(device?.endpoint, "No endpoint")} · fingerprint{" "}
                              {shortHash(device?.fingerprint)}
                            </p>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <EmptyState>No LocalSend peers answered discovery on this LAN.</EmptyState>
                    )}
                  </article>
                ) : null}

                <h4>Transfer history</h4>
                <p className="neyvia-personal-mesh-note" data-nearby-hash-summary="true">
                  Destination integrity is proven only when the receiver acknowledges a matching SHA-256.
                  Remote-verified: {formatCount(history?.summary?.remoteHashVerifiedCount)}.
                </p>
                {history ? (
                  transfers.length ? (
                    <ul className="neyvia-personal-mesh-list" data-nearby-history="true">
                      {transfers.map((transfer, index) => (
                        <li key={transfer?.receiptId || `receipt-${index}`}>
                          <div>
                            <strong>{formatValue(transfer?.status)}</strong>
                            <span data-tone={transfer?.ok === true ? "good" : "warn"}>
                              {formatBooleanStatus(transfer?.ok, {
                                trueLabel: "Completed",
                                falseLabel: "Not completed",
                              })}
                            </span>
                          </div>
                          <p>
                            {formatValue(transfer?.completedAt)} ·{" "}
                            {formatCount(transfer?.summary?.fileCount)} files ·{" "}
                            {formatBytes(transfer?.summary?.totalBytes)} ·{" "}
                            {formatDuration(transfer?.summary?.durationMs)}
                          </p>
                          {asList(transfer?.files).length ? (
                            <ul className="neyvia-personal-mesh-file-progress">
                              {asList(transfer.files).map((file, fileIndex) => (
                                <li key={file?.fileId || file?.sha256 || `receipt-file-${fileIndex}`}>
                                  <span>{formatValue(file?.fileName)}</span>
                                  <em>
                                    {formatBooleanStatus(file?.remoteHashVerified, {
                                      trueLabel: "Destination hash matched",
                                      falseLabel: "Destination hash unverified",
                                    })}
                                  </em>
                                  <code title={formatValue(file?.sha256, "")}>{shortHash(file?.sha256)}</code>
                                </li>
                              ))}
                            </ul>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <EmptyState>No durable transfer receipts yet.</EmptyState>
                  )
                ) : (
                  <EmptyState unavailable>Transfer history is unavailable.</EmptyState>
                )}
              </section>
            ) : null}

            {tab === "sync" ? (
              <section
                aria-labelledby="neyvia-personal-mesh-tab-sync"
                className="neyvia-personal-mesh-section"
                data-mesh-section="sync"
                id="neyvia-personal-mesh-sync"
                role="tabpanel"
              >
                <header>
                  <h3><FolderSync aria-hidden="true" size={15} /> Folder Sync</h3>
                  <p>
                    Syncthing {formatValue(syncCompat?.binary?.version || syncCompat?.transport?.version)} ·{" "}
                    state {formatValue(syncHealth?.state || syncCompat?.binary?.serviceState || syncCompat?.state)}
                  </p>
                </header>
                <SectionError>{sectionErrors.sync}</SectionError>

                <article
                  className="neyvia-personal-mesh-card"
                  data-sync-availability={syncHealth?.available === true ? "available" : "unavailable"}
                  data-tone={syncHealth?.available === true ? "good" : "warn"}
                >
                  <strong>Live availability</strong>
                  <p>
                    {syncHealth?.available === true
                      ? `Syncthing reachable · uptime ${formatCount(syncHealth?.uptimeSeconds)} seconds`
                      : syncHealthError || "Live Syncthing health has not been confirmed."}
                  </p>
                  <div className="neyvia-personal-mesh-status-grid">
                    <StatusLine
                      label="Installed"
                      value={formatBooleanStatus(syncCompat?.binary?.installed, {
                        trueLabel: "Installed",
                        falseLabel: "Not installed",
                      })}
                    />
                    <StatusLine
                      label="Binary hash"
                      value={formatBooleanStatus(syncCompat?.binary?.hashVerified, {
                        trueLabel: "Verified",
                        falseLabel: "Unverified",
                      })}
                    />
                    <StatusLine
                      label="Credential"
                      value={formatBooleanStatus(
                        syncHealth?.enablement?.credentialAvailable ??
                          syncCompat?.transport?.credentialAvailable,
                        { trueLabel: "Available", falseLabel: "Unavailable" },
                      )}
                    />
                  </div>
                  {syncHealth?.available !== true && asList(syncHealth?.enablement?.steps).length ? (
                    <ul className="neyvia-personal-mesh-enablement">
                      {asList(syncHealth.enablement.steps).map((step, index) => (
                        <li key={`${formatValue(step)}-${index}`}>{formatValue(step)}</li>
                      ))}
                    </ul>
                  ) : null}
                </article>

                <div className="neyvia-personal-mesh-row-actions">
                  <button
                    data-neyvia-mesh-action="load-sync-health"
                    disabled={syncHealthState === "loading"}
                    onClick={() => void loadSyncHealth()}
                    type="button"
                  >
                    {syncHealthState === "loading" ? "Loading sync health…" : "Refresh live sync health"}
                  </button>
                </div>
                {syncHealthError ? (
                  <p className="neyvia-personal-mesh-banner" data-tone="warn">
                    Sync health unavailable: {syncHealthError}
                  </p>
                ) : null}

                {syncHealth?.available === true ? (
                  <>
                    <div className="neyvia-personal-mesh-metrics">
                      <div><strong>{formatCount(syncHealth?.summary?.folders ?? folders.length)}</strong><span>folders</span></div>
                      <div><strong>{formatCount(syncHealth?.summary?.pausedFolders)}</strong><span>paused</span></div>
                      <div><strong>{formatCount(syncHealth?.summary?.connectedDevices)}</strong><span>connected</span></div>
                      <div><strong>{formatDuration(syncHealth?.summary?.durationMs)}</strong><span>health</span></div>
                    </div>

                    <h4>Folders</h4>
                    {folders.length ? (
                      <ul className="neyvia-personal-mesh-list">
                        {folders.map((folder, index) => (
                          <li key={folder?.folderId || `folder-${index}`}>
                            <div>
                              <strong>{formatValue(folder?.label || folder?.folderId)}</strong>
                              <span data-tone={folder?.paused === true ? "warn" : "neutral"}>
                                {folder?.paused === true ? "Paused" : formatValue(folder?.folderType, "Active")}
                              </span>
                            </div>
                            <p>
                              {formatValue(folder?.path, "Path withheld")} · versioning{" "}
                              {formatValue(folder?.versioningType, "None")}
                            </p>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <EmptyState>No folder relationships configured.</EmptyState>
                    )}

                    <h4>Connections</h4>
                    {connections.length ? (
                      <ul className="neyvia-personal-mesh-list">
                        {connections.map((connection, index) => (
                          <li key={connection?.deviceRef || `connection-${index}`}>
                            <div>
                              <strong>{formatValue(connection?.deviceRef)}</strong>
                              <span data-tone={connection?.connected === true ? "good" : "neutral"}>
                                {formatValue(
                                  connection?.route || connection?.transport,
                                  connection?.connected === true ? "Connected" : MESH_UNAVAILABLE,
                                )}
                              </span>
                            </div>
                            <p>
                              in {formatBytes(connection?.inBytesTotal)} · out{" "}
                              {formatBytes(connection?.outBytesTotal)}
                            </p>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <EmptyState>No device connections reported.</EmptyState>
                    )}
                  </>
                ) : (
                  <EmptyState unavailable>
                    Folder and connection state remains unavailable until Syncthing health is confirmed.
                  </EmptyState>
                )}
              </section>
            ) : null}
          </>
        )}
      </div>
    </OverlayShell>
  );
}
