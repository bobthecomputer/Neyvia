import { useCallback, useEffect, useState } from "react";
import { callNx as callNeyvia } from "./nxApi.js";

import { ArrowRight, Beaker, BookOpen, FileType, FlaskConical, Grid2x2, Library, Network, PackageOpen, Palette, Search, SquareTerminal } from "lucide-react";

import { NEYVIA_MANAGED_SUITE_CATALOG, getNeyviaToolVisual, groupNeyviaChatToolsByCategory } from "../neyviaToolVisuals.js";

import { NeyviaToolIcon } from "../NeyviaToolVisuals.jsx";

import { NEYVIA_AVAILABILITY_FILTERS, resolveTileAvailability, tileMatchesAvailabilityFilter } from "../neyviaToolAvailability.js";

import { capabilitiesForZone, registeredCapabilities, resolveCapabilityPlacement, zoneMeta } from "../neyviaCapabilityIdentity.js";

import { openNeyviaEmbeddedWorkspace } from "../NeyviaEcosystemHost.jsx";

import { NeyviaEcosystemFabricPanel } from "../NeyviaEcosystemFabricPanel.jsx";

import { NeyviaLabEvidencePanel } from "../NeyviaLabEvidencePanel.jsx";

import { NeyviaDomainExperiencePanel } from "../NeyviaDomainExperiencePanel.jsx";

const asList = value => Array.isArray(value) ? value : [];
function CapabilityContractBanner({ state, message }) {
  return <p className="neyvia-empty-hint" data-state={state} role="status">{message}</p>;
}

export function NeyviaNotebookSurface({ onRequestAction, onSetSurface }) {
  const [state, setState] = useState("loading");
  const [lineage, setLineage] = useState(null);
  const [artifacts, setArtifacts] = useState([]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [contract, snapshot] = await Promise.all([
          callNeyvia("get_capability_ui_contract_command", {}),
          callNeyvia("get_capability_os_snapshot_command", {}),
        ]);
        if (!active) return;
        setLineage(contract);
        setArtifacts(asList(snapshot?.artifactGraph?.artifacts || snapshot?.artifactGraph?.nodes));
        setState("ready");
      } catch {
        if (active) setState("unavailable");
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const toolDrawers = [
    { id: "images", label: "Image Playground", detail: "Tool drawer — not a permanent mode", Icon: Palette, surface: "images" },
    { id: "harnesses", label: "Harnesses", detail: "Runtime harness controls", Icon: SquareTerminal, surface: "harnesses" },
    { id: "skills", label: "Skills", detail: "Skill library from the control room", Icon: Grid2x2, surface: "skills" },
  ];

  return (
    <section
      aria-label="Notebook"
      className="neyvia-shell-surface neyvia-notebook-surface"
      data-a11y-region="neyvia-notebook"
      data-neyvia-motion-target="notebook"
      data-neyvia-surface-panel="notebook"
      id="neyvia-surface-panel-notebook"
    >
      <header className="neyvia-surface-head">
        <div>
          <span className="neyvia-surface-eyebrow"><BookOpen aria-hidden="true" size={14} /> Notebook</span>
          <h2>Documents, research, lessons</h2>
          <p>Keep your source documents and research together.</p>
        </div>
      </header>

      {state === "loading" ? <CapabilityContractBanner state="loading" message="Loading capability contract…" /> : null}
      {state === "unavailable" ? (
        <CapabilityContractBanner
          state="unavailable"
          message="Document services are offline. You can still plan in Chat; previews appear when the connection returns."
        />
      ) : null}
      {state === "ready" ? (
        <details className="neyvia-notebook-service-details"><summary>{artifacts.length} saved artifacts · Service details</summary><p>{lineage?.catalogSummary?.capabilities ?? 0} capabilities catalogued. Contract: {lineage?.schema || "unknown"}.</p></details>
      ) : null}

      <div className="neyvia-notebook-layout">
        <aside aria-label="Notebook tools and sections" data-neyvia-notebook-toc="true">
          <strong>Sources</strong>
          <div className="neyvia-notebook-tool-drawers" data-neyvia-tool-drawers="true">
            <span>Tools</span>
            {toolDrawers.map(tool => {
              const Icon = tool.Icon;
              return (
                <button
                  data-neyvia-tool-drawer={tool.id}
                  key={tool.id}
                  onClick={() => {
                    onSetSurface?.(tool.surface);
                  }}
                  title={tool.detail}
                  type="button"
                >
                  <Icon aria-hidden="true" size={13} />
                  {tool.label}
                </button>
              );
            })}
          </div>
        </aside>
        <article className="neyvia-doc-page" data-neyvia-notebook-canvas="true">
          {artifacts.length ? (
            <>
              <div className="neyvia-page-label">{artifacts.length} artifact{artifacts.length === 1 ? "" : "s"} from backend</div>
              <div className="neyvia-artifact-list" role="list">
                {artifacts.slice(0, 16).map((item, index) => (
                  <article
                    data-artifact-id={item.id || item.artifactId || index}
                    key={item.id || item.artifactId || `artifact-${index}`}
                    role="listitem"
                  >
                    <span>{item.kind || item.type || "artifact"}</span>
                    <strong>{item.title || item.name || item.path || item.id || "Untitled artifact"}</strong>
                    <p>{item.summary || item.detail || item.status || "Reported by capability backend."}</p>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <div className="neyvia-notebook-empty" data-notebook-empty="true">
              <div className="neyvia-notebook-empty-mark" aria-hidden="true">
                <BookOpen size={22} strokeWidth={1.55} />
                <i />
                <i />
                <i />
              </div>
              <div className="neyvia-page-label">No artifact selected</div>
              <h3>Bring a source into focus</h3>
              <p>
                Open a PDF or DOCX, or ask Chat to plan a manuscript revision. Preview, extracted text, citations,
                and redlines will stay together here when the document service connects.
              </p>
              <button
                data-neyvia-notebook-action="plan"
                onClick={() => onRequestAction?.("neyvia:notebook:plan")}
                type="button"
              >
                Plan with Chat <ArrowRight aria-hidden="true" size={14} />
              </button>
            </div>
          )}
        </article>
      </div>
    </section>
  );
}

export function NeyviaLabSurface({ onRequestAction, onSetSurface, onOpenPanel, requestedTab }) {
  const [state, setState] = useState("loading");
  const [snapshot, setSnapshot] = useState(null);

  const refreshLab = useCallback(async () => {
    setState("loading");
    try {
      const data = await callNeyvia("get_capability_os_snapshot_command", {});
      setSnapshot(data);
      setState("ready");
    } catch {
      setSnapshot(null);
      setState("unavailable");
    }
  }, []);

  useEffect(() => {
    void refreshLab();
  }, [refreshLab]);

  const adapters = asList(snapshot?.adapters || snapshot?.adapterSummary?.rows);
  const twins = asList(snapshot?.computerUseTwins?.specs || snapshot?.computerUseTwins);
  const authored = asList(snapshot?.authoredTools?.tools || snapshot?.authoredTools);
  const runs = asList(snapshot?.runs);
  const availableCount = adapters.filter(row => row?.available || row?.state === "available").length;
  const reportedCount = availableCount + twins.length + authored.length + runs.length;

  return (
    <section
      aria-label="Lab"
      className="neyvia-shell-surface neyvia-lab-surface"
      data-a11y-region="neyvia-lab"
      data-neyvia-motion-target="lab"
      data-neyvia-surface-panel="lab"
      id="neyvia-surface-panel-lab"
    >
      <header className="neyvia-surface-head">
        <div>
          <span className="neyvia-surface-eyebrow"><FlaskConical aria-hidden="true" size={14} /> Lab</span>
          <h2>Creative and technical lab</h2>
          <p>Test code, models, devices, 3D, and media in one supervised workspace.</p>
        </div>
      </header>

      {state === "unavailable" ? (
        <CapabilityContractBanner
          state="unavailable"
          message="Lab services are offline. Connect a runtime to preview devices, scenes, and live results."
        />
      ) : null}

      <div className="neyvia-lab-stage" data-lab-state={state}>
        <div className="neyvia-lab-viewport">
          <Beaker aria-hidden="true" size={28} />
          <strong>{state === "ready" ? "Lab ready" : state === "loading" ? "Connecting…" : "Connect a runtime"}</strong>
          <p>
            {state === "ready"
              ? `${availableCount} connected adapter${availableCount === 1 ? "" : "s"} · ${twins.length} device view${twins.length === 1 ? "" : "s"} · ${authored.length} custom tool${authored.length === 1 ? "" : "s"} · ${runs.length} recent run${runs.length === 1 ? "" : "s"}`
              : "Choose a connected runtime or tool to begin a supervised session."}
          </p>
          <div className="neyvia-lab-actions">
            <button
              onClick={() => {
                onSetSurface?.("images");
                onRequestAction?.("lab:open-images", {});
              }}
              type="button"
            >
              <Palette aria-hidden="true" size={14} /> Image Studio
            </button>
            <button
              data-neyvia-lab-action="personal-mesh"
              onClick={() => onOpenPanel?.("personal-mesh")}
              type="button"
            >
              <Network aria-hidden="true" size={14} /> Personal Mesh
            </button>
            <button
              data-neyvia-lab-action="office-suite"
              onClick={() => onOpenPanel?.("office-suite")}
              type="button"
            >
              <FileType aria-hidden="true" size={14} /> Office Suite
            </button>
            <button
              data-neyvia-lab-action="marketplace"
              onClick={() => onOpenPanel?.("marketplace")}
              type="button"
            >
              <PackageOpen aria-hidden="true" size={14} /> Marketplace
            </button>
          </div>
        </div>
        <aside aria-label="Run trace">
          <div className="neyvia-lab-trace-head">
            <h3>Run trace</h3>
            <button
              aria-label="Refresh lab connections"
              data-neyvia-lab-action="refresh"
              onClick={() => {
                void refreshLab();
              }}
              title="Refresh connections"
              type="button"
            >
              <PackageOpen aria-hidden="true" size={13} />
            </button>
          </div>
          <p>Sources, transformations, and result receipts appear after a run.</p>
          <ul>
            {twins.slice(0, 4).map((item, index) => (
              <li key={item.id || item.specId || `twin-${index}`}>
                <span data-tone="neutral">Twin</span> {item.name || item.title || item.id || "Computer-use twin"}
              </li>
            ))}
            {authored.slice(0, 4).map((item, index) => (
              <li key={item.id || item.toolId || `tool-${index}`}>
                <span data-tone="neutral">Tool</span> {item.name || item.title || item.id || "Authored tool"}
              </li>
            ))}
            {!twins.length && !authored.length ? (
              <>
                <li><span data-tone="neutral">Status</span> No active run</li>
                <li><span data-tone="neutral">Results</span> Waiting for a connected runtime</li>
              </>
            ) : null}
          </ul>
        </aside>
      </div>
      <NeyviaLabEvidencePanel onRequestAction={onRequestAction} requestedTab={requestedTab} />
    </section>
  );
}

export function NeyviaLibrarySurface({
  onApplyExperience,
  onRequestAction,
  onSelectPrompt,
  onSetSurface,
  onOpenPanel,
  toolAvailability = null,
  availabilityFilter = "wave1",
  onAvailabilityFilterChange,
}) {
  const [state, setState] = useState("loading");
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState([]);
  const [contract, setContract] = useState(null);
  const [suiteFilter, setSuiteFilter] = useState(availabilityFilter);

  useEffect(() => {
    setSuiteFilter(availabilityFilter);
  }, [availabilityFilter]);

  const refresh = async (nextQuery = query) => {
    setState("loading");
    try {
      const [uiContract, search] = await Promise.all([
        callNeyvia("get_capability_ui_contract_command", {}),
        callNeyvia("search_capabilities_command", {
          query: nextQuery.trim() || "pack",
          limit: 24,
          includeUnavailable: true,
        }),
      ]);
      setContract(uiContract);
      setRows(asList(search?.results || search?.capabilities || search?.items));
      setState("ready");
    } catch {
      setRows([]);
      setState("unavailable");
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => refresh(query), query ? 200 : 0);
    return () => window.clearTimeout(timer);
  }, [query]);

  return (
    <section
      aria-label="Library"
      className="neyvia-shell-surface neyvia-library-surface"
      data-a11y-region="neyvia-library"
      data-neyvia-motion-target="library"
      data-neyvia-surface-panel="library"
      id="neyvia-surface-panel-library"
    >
      <header className="neyvia-surface-head">
        <div>
          <span className="neyvia-surface-eyebrow"><Library aria-hidden="true" size={14} /> Library</span>
          <h2>Skills and capability packs</h2>
          <p>Find the tools, specialist skills, and domain packs available to your workspace.</p>
        </div>
      </header>

      <div className="neyvia-library-search">
        <Search aria-hidden="true" size={14} />
        <input
          aria-label="Search capability packs"
          onChange={event => setQuery(event.target.value)}
          placeholder="Search capabilities and packs"
          type="search"
          value={query}
        />
        <button aria-label="Refresh library" onClick={() => refresh(query)} title="Refresh library" type="button">
          <PackageOpen aria-hidden="true" size={14} />
        </button>
      </div>

      {state === "unavailable" ? (
        <CapabilityContractBanner
          state="unavailable"
          message="Library services are offline. Installed skills remain available; connected packs will appear here when service returns."
        />
      ) : null}

      {state === "ready" && !rows.length ? (
        <CapabilityContractBanner
          state="empty"
          message={query.trim() ? "No skills or packs match this search." : "No connected capability packs yet."}
        />
      ) : null}

      <div className="neyvia-library-grid" role="list">
        {rows.map(row => {
          const id = row.id || row.capabilityId || row.packId || row.name;
          const available = row.available !== false && row.state !== "unavailable";
          const visual = getNeyviaToolVisual(id);
          return (
            <article
              className={visual.animationClass}
              data-available={available ? "true" : "false"}
              data-tool-id={id}
              key={id}
              role="listitem"
            >
              <span className="neyvia-library-cap-icon" aria-hidden="true">
                <NeyviaToolIcon size={14} toolId={id} />
              </span>
              <span>{row.verb || row.domain || "Capability"}</span>
              <strong>{row.label || row.name || id}</strong>
              <p>{row.summary || row.description || "No description reported."}</p>
              <em aria-label={available ? "Available" : "Unavailable"}>
                {available ? "Available" : row.state || "Unavailable"}
              </em>
              <button
                disabled={!available}
                onClick={() => onRequestAction?.("neyvia:library:describe", { capabilityId: id })}
                type="button"
              >
                Inspect
              </button>
            </article>
          );
        })}
        {state === "loading" ? <p className="neyvia-empty-hint">Searching library…</p> : null}
      </div>

      <details className="neyvia-library-disclosure">
        <summary>Domain experiences</summary>
        <NeyviaDomainExperiencePanel
          onApplyExperience={onApplyExperience}
          onRequestAction={onRequestAction}
          onSelectPrompt={onSelectPrompt}
          onSetSurface={onSetSurface}
        />
      </details>

      <details className="neyvia-library-disclosure">
        <summary>Connections and sharing</summary>
        <NeyviaEcosystemFabricPanel onRequestAction={onRequestAction} />
      </details>

      {/*
        Shared capability identity: one object per capability, listed with where
        it is discovered and where it is used. A capability discoverable here and
        usable in Office or Orchestration is the same record, not a second tile
        with its own state.
      */}
      <details className="neyvia-library-disclosure">
        <summary>Where capabilities can be used</summary>
      <section aria-label="Capability placement" className="neyvia-library-placement-section">
        <header className="neyvia-surface-head" style={{ marginBottom: 8 }}>
          <div>
            <span className="neyvia-surface-eyebrow">Capability map</span>
            <h3 style={{ margin: "4px 0" }}>
              {registeredCapabilities().length} shared capabilities · {capabilitiesForZone("library", { role: "discover" }).length} available in Library
            </h3>
            <p style={{ margin: 0 }}>
              See where each capability is available across Neyvia.
            </p>
          </div>
        </header>
        <div className="neyvia-library-placement" data-neyvia-capability-placement="true">
          {registeredCapabilities().map(capability => {
            const placement = resolveCapabilityPlacement(capability.id, "library");
            return (
              <article
                className="neyvia-library-placement-row"
                data-capability-id={capability.id}
                data-capability-kind={capability.kind}
                key={capability.id}
              >
                <div>
                  <strong>{capability.label}</strong>
                  <p>{capability.summary}</p>
                </div>
                <dl>
                  <div>
                    <dt>Discover</dt>
                    <dd>
                      {capability.discoverIn.map(id => zoneMeta(id)?.label || id).join(", ") || "—"}
                    </dd>
                  </div>
                  <div>
                    <dt>Use</dt>
                    <dd>{capability.useIn.map(id => zoneMeta(id)?.label || id).join(", ") || "—"}</dd>
                  </div>
                </dl>
                {placement.allowed && capability.adapterId ? (
                  <button
                    data-capability-open={capability.id}
                    onClick={() =>
                      openNeyviaEmbeddedWorkspace({
                        adapterId: capability.adapterId,
                        title: capability.label,
                        subtitle: "Opened from Library",
                        presentation: placement.presentation,
                        context: { capabilityId: capability.id, zoneId: "library" },
                      })
                    }
                    type="button"
                  >
                    Open here
                  </button>
                ) : (
                  <span className="neyvia-library-placement-note">
                    {placement.allowed ? "No embedded adapter" : placement.reason}
                  </span>
                )}
              </article>
            );
          })}
        </div>
      </section>
      </details>

      <details className="neyvia-library-disclosure">
        <summary>Managed tools</summary>
      <section aria-label="Managed tool suite" className="neyvia-library-suite-section" data-neyvia-managed-suite="true">
        <header className="neyvia-surface-head" style={{ marginBottom: 8 }}>
          <div>
            <span className="neyvia-surface-eyebrow">Managed tools</span>
            <h3 style={{ margin: "4px 0" }}>
              {toolAvailability?.agentReadyCount ?? 0} ready · {NEYVIA_MANAGED_SUITE_CATALOG.length} registered
            </h3>
            <p style={{ margin: 0 }}>
              Ready tools can run now. Upcoming tools stay visible without appearing connected.
            </p>
          </div>
        </header>
        <div className="neyvia-availability-filters" role="toolbar" aria-label="Suite readiness filter">
          {NEYVIA_AVAILABILITY_FILTERS.map(item => (
            <button
              aria-pressed={suiteFilter === item.id}
              className={suiteFilter === item.id ? "is-selected" : undefined}
              key={item.id}
              onClick={() => {
                setSuiteFilter(item.id);
                onAvailabilityFilterChange?.(item.id);
              }}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
        {groupNeyviaChatToolsByCategory(
          NEYVIA_MANAGED_SUITE_CATALOG.filter(tool =>
            tileMatchesAvailabilityFilter(tool.id, toolAvailability, suiteFilter),
          ),
        ).map(group => (
          <div className="neyvia-tools-category" data-tool-category={group.category} key={`suite-${group.category}`}>
            <header className="neyvia-tools-category-head">
              <strong>{group.label}</strong>
              <span>{group.tools.length}</span>
            </header>
            <div className="neyvia-tools-grid neyvia-library-suite-grid" role="list">
              {group.tools.map(tool => {
                const visual = getNeyviaToolVisual(tool.id);
                const availability = resolveTileAvailability(tool.id, toolAvailability);
                return (
                  <button
                    className={`${visual.animationClass}${availability.agentReady ? " is-agent-ready" : " is-demoted"}`}
                    data-agent-ready={availability.agentReady ? "true" : "false"}
                    data-availability-tier={availability.tier}
                    data-stub={availability.agentReady ? "false" : "true"}
                    data-tool-id={tool.id}
                    key={tool.id}
                    onClick={() =>
                      onRequestAction?.(`neyvia:tool:${tool.id}`, {
                        toolId: tool.id,
                        suiteToolId: tool.id,
                        status: availability.agentReady ? "agent_ready" : "not_connected",
                        agentReady: availability.agentReady,
                        tier: availability.tier,
                      })
                    }
                    role="listitem"
                    type="button"
                  >
                    <span className="neyvia-tools-grid-icon" aria-hidden="true">
                      <NeyviaToolIcon size={14} toolId={tool.id} />
                    </span>
                    <strong>{tool.label}</strong>
                    <em data-tone={availability.agentReady ? "good" : "neutral"}>{availability.badge}</em>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </section>
      </details>
    </section>
  );
}
