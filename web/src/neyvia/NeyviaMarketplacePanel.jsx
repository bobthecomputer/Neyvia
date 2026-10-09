import { useEffect, useMemo, useRef, useState } from "react";
import { Check, PackageOpen, Plus, RefreshCw, Search, ShieldCheck, Trash2, TriangleAlert, X } from "lucide-react";

import {
  MARKETPLACE_BACKEND_COMMANDS,
  MARKETPLACE_UNAVAILABLE,
  loadMarketplaceView,
  marketplaceCompatibility,
  marketplaceStateTone,
  runMarketplaceLifecycleAction,
  shortMarketplaceIdentity,
} from "./neyviaMarketplaceModel.js";
import {
  NEYVIA_APPLICATION_COMMANDS,
  resolveApplicationEmbedding,
} from "./neyviaApplicationContract.js";
import { openNeyviaEmbeddedWorkspace } from "./NeyviaEcosystemHost.jsx";
import { NeyviaToolIcon } from "./NeyviaToolVisuals.jsx";
import { NeyviaInstalledPrograms } from "./NeyviaInstalledPrograms.jsx";
import { NeyviaSourceMarketplace } from "./NeyviaSourceMarketplace.jsx";
import { Button, Icon, Segmented, StatusDot } from "./next/nxPrimitives.jsx";
import { ConfirmInPlace, EmptyState, useCalmLoading } from "./next/details/nxDetails.jsx";
import "./neyviaSourceStore.css";
import { createNeyviaClient } from "../../../packages/neyvia-sdk/index.js";
import "./neyviaMarketplace.css";

const callNeyvia = createNeyviaClient().command;

function EvidenceRow({ label, state, detail, tone = "neutral" }) {
  return (
    <div className="neyvia-marketplace-evidence-row" data-tone={tone}>
      <span>{label}</span>
      <strong>{state}</strong>
      <p>{detail}</p>
    </div>
  );
}

function PackageDetail({ item, busyAction, actionError, onAction }) {
  if (!item) {
    return (
      <div className="neyvia-marketplace-empty" data-state="empty">
        <PackageOpen aria-hidden="true" size={24} />
        <strong>No installed package selected</strong>
        <p>The reviewed catalog may legitimately be empty on a fresh installation.</p>
      </div>
    );
  }

  return (
    <article className="neyvia-marketplace-detail" data-marketplace-detail={item.id}>
      <header>
        <div>
          <span className="neyvia-marketplace-kicker">Installed package</span>
          <h3>{item.name}</h3>
          <p>{item.summary}</p>
          <p data-marketplace-compat={item.compatibility.status} title={item.compatibility.detail}>{item.compatibility.label}</p>
        </div>
        <span className="neyvia-marketplace-status" data-tone={item.tone}>
          {item.state}
        </span>
      </header>

      <dl className="neyvia-marketplace-facts">
        <div>
          <dt>Version</dt>
          <dd data-marketplace-version={item.version}>{item.version}</dd>
        </div>
        <div>
          <dt>Previous</dt>
          <dd data-marketplace-previous={item.previousVersion || "none"}>
            {item.previousVersion || MARKETPLACE_UNAVAILABLE}
          </dd>
        </div>
        <div>
          <dt>Publisher</dt>
          <dd>{item.publisher.name}</dd>
        </div>
        <div>
          <dt>Capabilities</dt>
          <dd>{item.capabilityCount ?? MARKETPLACE_UNAVAILABLE}</dd>
        </div>
      </dl>

      <section aria-labelledby="neyvia-marketplace-package-security">
        <div className="neyvia-marketplace-section-heading">
          <div>
            <span className="neyvia-marketplace-kicker">Acceptance evidence</span>
            <h4 id="neyvia-marketplace-package-security">Trust and package state</h4>
          </div>
          <ShieldCheck aria-hidden="true" size={18} />
        </div>
        <div className="neyvia-marketplace-evidence">
          <EvidenceRow
            detail={item.trust.detail}
            label="Publisher trust"
            state={item.trust.state}
            tone={item.trust.state === "Trusted" ? "good" : "warn"}
          />
          <EvidenceRow
            detail={`${item.signature.detail} Cosign tool: ${
              item.signature.toolReady ? "verified locally" : "unavailable or hash mismatch"
            }.`}
            label="Signature receipt"
            state={item.signature.state}
            tone={
              item.signature.state === "Verified"
                ? "good"
                : item.signature.toolReady
                  ? "neutral"
                  : "warn"
            }
          />
          <EvidenceRow
            detail={item.staging.detail}
            label="Staged activation"
            state={item.staging.state}
            tone={item.staging.state === "Staged" ? "warn" : "neutral"}
          />
          <EvidenceRow
            detail={
              item.blockedReasons.length
                ? item.blockedReasons.join(" · ")
                : "No integrity or security blocker is reported by the installed catalog."
            }
            label="Runtime gate"
            state={item.blocked ? "Blocked" : item.state}
            tone={item.blocked ? "blocked" : marketplaceStateTone(item.state)}
          />
        </div>
      </section>

      <section aria-labelledby="neyvia-marketplace-package-publisher">
        <span className="neyvia-marketplace-kicker">Manifest identity</span>
        <h4 id="neyvia-marketplace-package-publisher">Publisher</h4>
        <p>{item.publisher.id}</p>
        <code title={item.publisher.identity}>{shortMarketplaceIdentity(item.publisher.identity)}</code>
      </section>

      <section aria-labelledby="neyvia-marketplace-package-permissions">
        <span className="neyvia-marketplace-kicker">Declared scope</span>
        <h4 id="neyvia-marketplace-package-permissions">Permissions</h4>
        {item.permissions.length ? (
          <ul className="neyvia-marketplace-permissions">
            {item.permissions.map((permission, index) => {
              const value =
                typeof permission === "string"
                  ? permission
                  : permission?.permission || permission?.name || MARKETPLACE_UNAVAILABLE;
              return <li key={`${value}-${index}`}>{value}</li>;
            })}
          </ul>
        ) : (
          <p>{MARKETPLACE_UNAVAILABLE} by the installed catalog.</p>
        )}
      </section>

      <div className="neyvia-marketplace-activation" data-marketplace-actions="true">
        <div className="neyvia-marketplace-action-row">
          <button
            data-marketplace-action="activate"
            disabled={!item.actions.activate || Boolean(busyAction)}
            onClick={() => onAction("activate")}
            title={item.activation.detail}
            type="button"
          >
            {busyAction === "activate" ? "Activating…" : "Activate"}
          </button>
          <button
            data-marketplace-action="disable"
            disabled={!item.actions.disable || Boolean(busyAction)}
            onClick={() => onAction("disable")}
            type="button"
          >
            {busyAction === "disable" ? "Disabling…" : "Disable"}
          </button>
          <button
            data-marketplace-action="rollback"
            disabled={!item.actions.rollback || Boolean(busyAction)}
            onClick={() => onAction("rollback")}
            title={
              item.previousVersion
                ? `Roll back to ${item.previousVersion}`
                : "No previous verified version"
            }
            type="button"
          >
            {busyAction === "rollback" ? "Rolling back…" : "Rollback"}
          </button>
        </div>
        <p data-marketplace-action-detail="true">{item.activation.detail}</p>
        {actionError ? (
          <p className="neyvia-marketplace-action-error" data-marketplace-action-error="true">
            {actionError}
          </p>
        ) : null}
      </div>
    </article>
  );
}

/**
 * Two developer propositions, stated as different things.
 *
 * An SDK application is an independent product that uses Neyvia services; it
 * never renders Neyvia surfaces and is not a marketplace application. An
 * ecosystem application is built through Neyvia, declares where it may embed,
 * and only connects its declared capabilities once it is active.
 */
function AppTileIcon({ item }) {
  return (
    <span className="nx-store-icon" aria-hidden="true">
      {item.logoUrl ? <img alt="" src={item.logoUrl} /> : <NeyviaToolIcon size={19} toolId={item.iconToolId || item.applicationId} />}
    </span>
  );
}

function ApplicationsPanel({
  registry,
  error,
  busyApplicationId,
  applicationMessage,
  onApplicationAction,
  onOpenApplication,
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [aboutOpen, setAboutOpen] = useState(false);
  const showLoading = useCalmLoading(!registry && !error);
  const propositions = registry?.propositions || [];
  const available = registry?.availableApplications || [];
  const bundledIds = new Set(available.map(item => item.applicationId));
  const ecosystem = (registry?.ecosystemApplications || []).filter(
    item => !bundledIds.has(item.applicationId),
  );
  const sdk = registry?.sdkApplications || [];
  const bindings = new Map((registry?.bindings || []).map(item => [item.applicationId, item]));
  const needle = query.trim().toLowerCase();
  const matches = item => !needle || [item.name, item.summary, item.category, item.applicationId].join(" ").toLowerCase().includes(needle);
  const shown = available.filter(item => matches(item)
    && (filter === "all" || (filter === "installed" ? item.installed : !item.installed)));
  const installedCount = available.filter(item => item.installed).length;

  return (
    <section
      aria-labelledby="neyvia-marketplace-applications-tab"
      className="nx-store"
      id="neyvia-marketplace-applications"
      role="tabpanel"
    >
      <div className="nx-store-bar">
        <label className="nx-store-search">
          <Icon as={Search} size={14} />
          <input aria-label="Search apps" onChange={event => setQuery(event.target.value)} placeholder="Search apps" type="search" value={query} />
        </label>
        <Segmented label="Show" onChange={setFilter} size="sm" value={filter} options={[
          { value: "all", label: "All", count: available.length || undefined },
          { value: "installed", label: "Installed", count: installedCount || undefined },
          { value: "available", label: "Not installed", count: (available.length - installedCount) || undefined },
        ]} />
      </div>

      <div aria-live="polite" className="nx-store-messages">
        {error ? <div className="nx-store-error" role="alert"><Icon as={TriangleAlert} size={14} /><span>{error}</span></div> : null}
        {applicationMessage ? <p className="nx-store-notice" role="status"><Icon as={Check} size={14} />{applicationMessage}</p> : null}
      </div>

      {!registry && !error ? (showLoading ? (
        <ul aria-hidden="true" className="nx-store-grid is-loading">
          {[0, 1, 2].map(index => <li className="nx-store-card is-skeleton" key={index}><span /><span /><span /></li>)}
        </ul>
      ) : null) : !available.length ? (
        <EmptyState hint="This build reports no bundled apps. Apps you add yourself live in Apps & mods." icon={PackageOpen} title="No bundled apps here" />
      ) : !shown.length ? (
        <EmptyState action={{ label: "Show all", onClick: () => { setQuery(""); setFilter("all"); } }} hint="Try another word or filter."
          icon={Search} title={needle ? `Nothing matches “${query.trim()}”` : "Nothing here yet"} tone="filtered" />
      ) : (
        <ul aria-label="Available Neyvia applications" className="nx-store-grid">
          {shown.map(item => {
            const busy = busyApplicationId === item.applicationId;
            const hostReady = item?.launch?.kind !== "mcp-app" || Boolean(item?.entryPointUrl);
            return (
              <li
                className={`nx-store-card is-${item.installed ? "installed" : "available"}`}
                data-application-installed={item.installed ? "true" : "false"}
                data-application-marketplace-id={item.applicationId}
                key={item.applicationId}
              >
                <div className="nx-store-card-main is-static">
                  <AppTileIcon item={item} />
                  <span className="nx-store-card-title">
                    <strong>{item.name}</strong>
                    <span className="nx-store-meta">{item.category || "Application"}</span>
                  </span>
                  {item.installed ? <span className="nx-store-pill is-enabled"><StatusDot tone="green" />Installed</span> : null}
                </div>
                <p className="nx-store-card-summary">{item.summary}</p>
                <p className="nx-store-meta" data-marketplace-compat={marketplaceCompatibility(item.compat).status}>{marketplaceCompatibility(item.compat).label}</p>
                <footer className="nx-store-card-foot">
                  <span className="nx-store-source" title={item.integrity}>{item.integrity}</span>
                  {item.installed ? (
                    <span className="nx-store-card-actions">
                      <ConfirmInPlace confirmLabel="Remove" doneText={`${item.name} removed`} onConfirm={() => onApplicationAction("uninstall", item)} question={`Remove ${item.name}?`}>
                        {ask => (
                          <Button data-application-action="uninstall" data-application-id={item.applicationId} disabled={busy} icon={Trash2}
                            className="nx-store-remove" onClick={ask} size="sm">
                            {busy ? "Removing…" : "Remove"}
                          </Button>
                        )}
                      </ConfirmInPlace>
                      <Button data-application-action="open" data-application-id={item.applicationId} disabled={busy || !hostReady}
                        onClick={() => onOpenApplication(item)} size="sm" variant="outline"
                        title={hostReady ? "Open application" : "Runtime installed; the Neyvia MCP App iframe host is not connected yet."}>
                        {hostReady ? "Open" : "Host pending"}
                      </Button>
                    </span>
                  ) : (
                    <Button data-application-action="install" data-application-id={item.applicationId} disabled={busy} icon={Plus}
                      loading={busy} onClick={() => onApplicationAction("install", item)} size="sm" variant="outline">
                      {busy ? "Installing…" : "Install"}
                    </Button>
                  )}
                </footer>
              </li>
            );
          })}
        </ul>
      )}

      {ecosystem.length || sdk.length ? (
        <div className="nx-store-more">
          {ecosystem.length ? <h4>Added apps</h4> : null}
          {ecosystem.length ? (
            <ul className="nx-store-grid">
              {ecosystem.map(item => {
                const binding = bindings.get(item.applicationId);
                const zone = item.surfaces[0] || "";
                const embedding = zone ? resolveApplicationEmbedding(item, zone) : { allowed: false, reason: "No declared surface." };
                return (
                  <li className="nx-store-card is-installed" data-application-id={item.applicationId} key={item.applicationId}>
                    <div className="nx-store-card-main is-static">
                      <AppTileIcon item={item} />
                      <span className="nx-store-card-title">
                        <strong>{item.name}</strong>
                        <span className="nx-store-meta">{item.version || MARKETPLACE_UNAVAILABLE}{binding ? ` · ${binding.capabilities.length} connected` : ""}</span>
                      </span>
                    </div>
                    <p className="nx-store-card-summary">{item.summary || "No summary in the installed manifest."}</p>
                    <p className="nx-store-meta" data-marketplace-compat={marketplaceCompatibility(item.compat).status}>{marketplaceCompatibility(item.compat).label}</p>
                    {item.problems.length ? (
                      <ul className="nx-store-limits">
                        {item.problems.map(problem => <li key={problem}>{problem}</li>)}
                      </ul>
                    ) : null}
                    {/*
                      An application opens through the same embedded-workspace
                      contract as every other content type, carrying its identity,
                      activation state and declared presentation. A tile alone never
                      claims the application is active.
                    */}
                    <footer className="nx-store-card-foot">
                      <span className="nx-store-source">{item.surfaces.length ? item.surfaces.join(", ") : "No surface declared"}</span>
                      {embedding.allowed ? (
                        <Button data-application-open={item.applicationId} size="sm" variant="outline"
                          onClick={() =>
                            openNeyviaEmbeddedWorkspace({
                              adapterId: embedding.adapterId,
                              title: item.name,
                              subtitle: `${item.kindLabel} · ${zone}`,
                              presentation: embedding.presentation,
                              permissions: { grants: [...(embedding.permissions || [])] },
                              context: {
                                applicationId: item.applicationId,
                                applicationState: binding?.state || "installed",
                                presentation: embedding.presentation,
                                zoneId: zone,
                              },
                              contentRef: { url: item.entryPointUrl || null },
                            })
                          }>
                          Open here
                        </Button>
                      ) : <span className="nx-store-source">{embedding.reason}</span>}
                    </footer>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {sdk.length ? <h4>Apps built on the Neyvia SDK</h4> : null}
          {sdk.length ? (
            <ul className="nx-store-grid">
              {sdk.map(item => (
                <li className="nx-store-card is-installed" data-application-id={item.applicationId} key={item.applicationId}>
                  <div className="nx-store-card-main is-static">
                    <AppTileIcon item={item} />
                    <span className="nx-store-card-title"><strong>{item.name}</strong><span className="nx-store-meta">Independent product</span></span>
                  </div>
                  <p className="nx-store-card-summary">{item.summary || "Uses Neyvia services through the SDK."}</p>
                  <p className="nx-store-meta" data-marketplace-compat={marketplaceCompatibility(item.compat).status}>{marketplaceCompatibility(item.compat).label}</p>
                  <footer className="nx-store-card-foot">
                    <span className="nx-store-source">{item.services.length ? item.services.join(", ") : "No services declared"}</span>
                  </footer>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="nx-store-about">
        <Button aria-controls="neyvia-marketplace-about" aria-expanded={aboutOpen} onClick={() => setAboutOpen(open => !open)} size="sm">
          {aboutOpen ? "Hide how apps connect" : "How apps connect"}
        </Button>
        {aboutOpen ? (
          <div className="nx-store-about-body" id="neyvia-marketplace-about">
            <p>{registry?.disclosure || "Waiting for the application registry."}</p>
            <p>Bundled workspaces activate locally. Independent apps name their public source and pinned release; Neyvia verifies the declared SHA-256 and disables package scripts before installation.</p>
            <ul className="neyvia-marketplace-propositions">
              {propositions.map(item => (
                <li data-application-kind={item.id} key={item.id}>
                  <strong>{item.label}</strong>
                  <p>{item.summary}</p>
                  <small>{item.publication}</small>
                  <code>{(item.services || []).join(" · ")}</code>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export function NeyviaMarketplacePanel({
  open = false,
  onClose,
  onOpenPanel,
  onSetSurface,
  callBackend = callNeyvia,
}) {
  const [phase, setPhase] = useState("idle");
  const [view, setView] = useState(null);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [tab, setTab] = useState("applications");
  const [busyAction, setBusyAction] = useState("");
  const [actionError, setActionError] = useState("");
  const [installPaths, setInstallPaths] = useState({
    manifestPath: "",
    archivePath: "",
    publicKeyPath: "",
  });
  const [installMessage, setInstallMessage] = useState("");
  const [applicationRegistry, setApplicationRegistry] = useState(null);
  const [applicationError, setApplicationError] = useState("");
  const [busyApplicationId, setBusyApplicationId] = useState("");
  const [applicationMessage, setApplicationMessage] = useState("");
  const [sourcesRefresh, setSourcesRefresh] = useState(0);
  const dialogRef = useRef(null);

  const refresh = async () => {
    setPhase("loading");
    const next = await loadMarketplaceView(callBackend);
    setView(next);
    setPhase(next.catalogSchema || next.toolchainSchema ? "ready" : "unavailable");
  };

  useEffect(() => {
    if (!open) return undefined;
    void refresh();
    return undefined;
  }, [open]);

  // The two developer propositions are separate records, not one merged list:
  // ecosystem applications come from the installed catalog, SDK applications
  // from local SDK registrations. Neither is invented when its source is empty.
  const refreshApplications = async () => {
    setApplicationError("");
    try {
      const data = await callBackend(NEYVIA_APPLICATION_COMMANDS.registry, {});
      if (data) setApplicationRegistry(data);
      else setApplicationError("The app list didn't load. Try Refresh.");
    } catch (error) {
      setApplicationError(String(error?.message || error));
    }
  };

  useEffect(() => {
    if (!open || tab !== "applications") return undefined;
    let cancelled = false;
    setApplicationError("");
    callBackend(NEYVIA_APPLICATION_COMMANDS.registry, {})
      .then(data => {
        if (cancelled) return;
        if (data) setApplicationRegistry(data);
        else setApplicationError("The app list didn't load. Try Refresh.");
      })
      .catch(error => {
        if (!cancelled) setApplicationError(String(error?.message || error));
      });
    return () => {
      cancelled = true;
    };
  }, [open, tab, callBackend]);

  const onBundledApplicationAction = async (action, item) => {
    if (!item?.applicationId) return;
    setBusyApplicationId(item.applicationId);
    setApplicationError("");
    setApplicationMessage("");
    try {
      const command =
        action === "install"
          ? NEYVIA_APPLICATION_COMMANDS.installBundledApplication
          : NEYVIA_APPLICATION_COMMANDS.uninstallBundledApplication;
      const receipt = await callBackend(command, {
        applicationId: item.applicationId,
        requestedBy: "marketplace-panel",
      });
      setApplicationMessage(`${item.name}: ${receipt.detail || `${action} complete.`}`);
      await refreshApplications();
    } catch (error) {
      setApplicationError(String(error?.message || error));
    } finally {
      setBusyApplicationId("");
    }
  };

  const onOpenBundledApplication = item => {
    const launch = item?.launch || {};
    if (launch.kind === "surface" && launch.target) {
      onSetSurface?.(launch.target);
      onClose?.();
      return;
    }
    if (launch.kind === "panel" && launch.target) {
      onOpenPanel?.(launch.target);
      return;
    }
    if (launch.kind === "mcp-app") {
      setApplicationError(
        `${item?.name || "Application"} is installed and agent-callable, but the secure MCP App iframe host is not connected yet.`,
      );
      return;
    }
    if (launch.kind === "embedded-web" && launch.target) {
      openNeyviaEmbeddedWorkspace({
        adapterId: "marketplace-app",
        title: item.name,
        subtitle: `${item.category || "Neyvia application"} · live workspace`,
        presentation: "fullscreen",
        permissions: { grants: [...(item.permissions || [])] },
        context: {
          applicationId: item.applicationId,
          applicationState: item.state || "active",
          presentation: "fullscreen",
          zoneId: item.surfaces?.[0] || "orchestration",
        },
        contentRef: { url: launch.target },
      });
      onClose?.();
      return;
    }
    setApplicationError(`${item?.name || "Application"} has no verified launch target.`);
  };

  useEffect(() => {
    if (!open) return undefined;
    const previousFocus = document.activeElement;
    dialogRef.current?.focus();
    const onKeyDown = event => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose?.();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (previousFocus instanceof HTMLElement && document.contains(previousFocus)) {
        previousFocus.focus();
      }
    };
  }, [open, onClose]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const modules = view?.modules || [];
    if (!needle) return modules;
    return modules.filter(item =>
      [item.name, item.id, item.summary, item.publisher.name, item.publisher.id, item.state]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [query, view]);

  const selected =
    filtered.find(item => item.id === selectedId) || filtered[0] || null;

  const onLifecycleAction = async action => {
    if (!selected) return;
    setBusyAction(action);
    setActionError("");
    try {
      await runMarketplaceLifecycleAction(callBackend, action, selected);
      await refresh();
    } catch (error) {
      setActionError(String(error?.message || error));
    } finally {
      setBusyAction("");
    }
  };

  const onInstall = async event => {
    event.preventDefault();
    setBusyAction("install");
    setInstallMessage("");
    setActionError("");
    try {
      const manifestPath = installPaths.manifestPath.trim();
      const archivePath = installPaths.archivePath.trim();
      if (!manifestPath || !archivePath) {
        throw new Error("Manifest path and archive path are required");
      }
      const install = await callBackend(MARKETPLACE_BACKEND_COMMANDS.installFromPaths, {
        manifestPath,
        archivePath,
        publicKeyPath: installPaths.publicKeyPath.trim() || undefined,
        approvedBy: "marketplace-panel",
        activate: false,
      });
      if (install?.blockedBy?.length) {
        throw new Error(`Install blocked: ${install.blockedBy.join(", ")}`);
      }
      setInstallMessage(
        `Installed ${install.moduleId}@${install.version} (${install.status}). Activation remains a separate attested step.`,
      );
      setSelectedId(String(install.moduleId || ""));
      await refresh();
    } catch (error) {
      setActionError(String(error?.message || error));
    } finally {
      setBusyAction("");
    }
  };

  if (!open) return null;

  return (
    <div
      aria-labelledby="neyvia-marketplace-title"
      aria-modal="true"
      className="neyvia-overlay is-wide"
      data-neyvia-overlay="true"
      data-neyvia-panel="marketplace"
      role="presentation"
    >
      <button
        aria-label="Close Marketplace backdrop"
        className="neyvia-overlay-backdrop"
        onClick={onClose}
        type="button"
      />
      <div
        aria-modal="true"
        className="neyvia-overlay-card neyvia-marketplace-dialog"
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        <header>
          <div>
            <h2 id="neyvia-marketplace-title">Marketplace</h2>
            <p>Apps and mods for Neyvia, and the signed packages on this PC.</p>
          </div>
          <button aria-label="Close Marketplace" onClick={onClose} type="button">
            <X aria-hidden="true" size={16} />
          </button>
        </header>

        <div className="neyvia-overlay-body">
          <div className="neyvia-marketplace" data-neyvia-marketplace="true" data-state={phase}>
            <div className="neyvia-marketplace-toolbar">
              <div aria-label="Marketplace sections" className="neyvia-marketplace-tabs" role="tablist">
                {[
                  ["applications", "Apps"],
                  ["sources", "Apps & mods"],
                  ["host", "On this host"],
                  ["packages", "Local packages"],
                  ["gates", "Security gates"],
                ].map(([id, label]) => (
                  <button
                    aria-controls={`neyvia-marketplace-${id}`}
                    aria-selected={tab === id}
                    id={`neyvia-marketplace-${id}-tab`}
                    key={id}
                    onClick={() => setTab(id)}
                    role="tab"
                    tabIndex={tab === id ? 0 : -1}
                    type="button"
                  >
                    {label}
                  </button>
                ))}
              </div>
              <button disabled={phase === "loading"} onClick={() => { setSourcesRefresh(count => count + 1); if (tab === "applications") void refreshApplications(); void refresh(); }} type="button">
                <RefreshCw aria-hidden="true" size={14} />
                {phase === "loading" ? "Loading…" : "Refresh"}
              </button>
            </div>

            {(tab === "packages" || tab === "gates") && <div className="neyvia-marketplace-disclosure" data-tone="warn">
              <strong>Signed apps and local lifecycle</strong>
              <p>{view?.sourceDisclosure || "Waiting for reviewed marketplace snapshots."}</p>
            </div>}

            {view?.errors?.length ? (
              <div aria-live="polite" className="neyvia-marketplace-errors">
                {view.errors.map(error => <p key={error}>{error}</p>)}
              </div>
            ) : null}

            {tab === "host" && <section role="tabpanel" id="neyvia-marketplace-host" aria-labelledby="neyvia-marketplace-host-tab">
              <NeyviaInstalledPrograms callBackend={callBackend} />
            </section>}
            {tab === "sources" && <NeyviaSourceMarketplace refreshKey={sourcesRefresh} />}
            {tab === "packages" ? (
              <section
                aria-labelledby="neyvia-marketplace-packages-tab"
                id="neyvia-marketplace-packages"
                role="tabpanel"
              >
                <div className="neyvia-marketplace-summary">
                  <div><strong>{view?.moduleCount ?? "—"}</strong><span>Installed</span></div>
                  <div><strong>{view?.activeCount ?? "—"}</strong><span>Active</span></div>
                  <div><strong>{view?.disabledCount ?? "—"}</strong><span>Disabled</span></div>
                  <div><strong>{view?.blockedCount ?? "—"}</strong><span>Blocked</span></div>
                </div>

                <form
                  className="neyvia-marketplace-install"
                  data-marketplace-install="true"
                  onSubmit={event => void onInstall(event)}
                >
                  <div className="neyvia-marketplace-section-heading">
                    <div>
                      <span className="neyvia-marketplace-kicker">Install</span>
                      <h4>Signed local package</h4>
                    </div>
                  </div>
                  <label>
                    <span>Manifest path</span>
                    <input
                      data-marketplace-install-field="manifestPath"
                      onChange={event =>
                        setInstallPaths(current => ({
                          ...current,
                          manifestPath: event.target.value,
                        }))
                      }
                      placeholder="C:/path/manifest.json"
                      value={installPaths.manifestPath}
                    />
                  </label>
                  <label>
                    <span>Archive path (.nymod)</span>
                    <input
                      data-marketplace-install-field="archivePath"
                      onChange={event =>
                        setInstallPaths(current => ({
                          ...current,
                          archivePath: event.target.value,
                        }))
                      }
                      placeholder="C:/path/package.nymod"
                      value={installPaths.archivePath}
                    />
                  </label>
                  <label>
                    <span>Publisher public key (optional trust bind)</span>
                    <input
                      data-marketplace-install-field="publicKeyPath"
                      onChange={event =>
                        setInstallPaths(current => ({
                          ...current,
                          publicKeyPath: event.target.value,
                        }))
                      }
                      placeholder="C:/path/publisher.pub"
                      value={installPaths.publicKeyPath}
                    />
                  </label>
                  <button
                    data-marketplace-action="install"
                    disabled={Boolean(busyAction)}
                    type="submit"
                  >
                    {busyAction === "install" ? "Installing…" : "Install package"}
                  </button>
                  {installMessage ? (
                    <p data-marketplace-install-message="true">{installMessage}</p>
                  ) : null}
                </form>

                {phase === "loading" && !view ? (
                  <div className="neyvia-marketplace-empty" data-state="loading">
                    <RefreshCw aria-hidden="true" size={22} />
                    <strong>Loading reviewed snapshots…</strong>
                  </div>
                ) : (
                  <>
                    <label className="neyvia-marketplace-search">
                      <span>Filter installed packages</span>
                      <input
                        onChange={event => setQuery(event.target.value)}
                        placeholder="Name, publisher, state…"
                        type="search"
                        value={query}
                      />
                    </label>
                    <div className="neyvia-marketplace-split">
                      <ul aria-label="Installed marketplace packages" className="neyvia-marketplace-list">
                        {filtered.map(item => (
                          <li key={item.id}>
                            <button
                              aria-current={selected?.id === item.id ? "true" : undefined}
                              data-marketplace-module={item.id}
                              data-marketplace-state={item.state}
                              onClick={() => setSelectedId(item.id)}
                              type="button"
                            >
                              <span>
                                <strong>{item.name}</strong>
                                <small>{item.publisher.name} · {item.version}</small>
                                <small data-marketplace-compat={item.compatibility.status}>{item.compatibility.label}</small>
                              </span>
                              <em data-tone={item.tone}>{item.blocked ? "blocked" : item.state}</em>
                            </button>
                          </li>
                        ))}
                      </ul>
                      <PackageDetail
                        actionError={actionError}
                        busyAction={busyAction}
                        item={selected}
                        onAction={action => void onLifecycleAction(action)}
                      />
                    </div>
                  </>
                )}
              </section>
            ) : tab === "applications" ? (
              <ApplicationsPanel
                applicationMessage={applicationMessage}
                busyApplicationId={busyApplicationId}
                error={applicationError}
                onApplicationAction={(action, item) => void onBundledApplicationAction(action, item)}
                onOpenApplication={onOpenBundledApplication}
                registry={applicationRegistry}
              />
            ) : tab === "gates" ? (
              <section
                aria-labelledby="neyvia-marketplace-gates-tab"
                id="neyvia-marketplace-gates"
                role="tabpanel"
              >
                <div className="neyvia-marketplace-gate-heading">
                  <div>
                    <span className="neyvia-marketplace-kicker">Activation gate</span>
                    <h3>{view?.activationGateReady ? "Toolchain reports ready" : "Not ready"}</h3>
                  </div>
                  <span data-tone={view?.activationGateReady ? "good" : "blocked"}>
                    {view?.activationGateReady ? "ready" : "blocked"}
                  </span>
                </div>
                <p className="neyvia-marketplace-gate-note">
                  Tool readiness is necessary but never sufficient for activation. Publisher trust,
                  detached signature, SBOM, malware, compatibility, and staged transaction receipts
                  must still be verified for the exact package.
                </p>
                <ul className="neyvia-marketplace-tools">
                  {(view?.tools || []).map(tool => (
                    <li key={tool.name}>
                      <span aria-hidden="true" data-tone={tool.healthy ? "good" : "blocked"} />
                      <div><strong>{tool.name}</strong><p>{tool.status}</p></div>
                      <code>{tool.detail}</code>
                    </li>
                  ))}
                </ul>
                <div className="neyvia-marketplace-disclosure">
                  <strong>Lifecycle policy</strong>
                  <p>{view?.installDisclosure}</p>
                </div>
              </section>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
