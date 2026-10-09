import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useState,
  useSyncExternalStore,
} from "react";
import { ChevronDown, ChevronUp, Expand, Minimize2, PlugZap, X } from "lucide-react";

import {
  NEYVIA_INVOCATION_MODES,
  NEYVIA_DELEGABLE_RESPONSIBILITIES,
  NEYVIA_RESERVED_RESPONSIBILITIES,
  invocationModeMeta,
} from "./neyviaRuntimeInvocation.js";
import {
  closeRuntimeInvocationById,
  getRuntimeReadiness,
  getRuntimeRegistry,
  loadRuntimeReadiness,
  openRuntimeInvocation,
  reapRuntimeInvocations,
  runtimeComposition,
  subscribeRuntimeRegistry,
  suspendRuntimeInvocation,
} from "./neyviaRuntimeStore.js";
import { embeddedAdapterComponent } from "./NeyviaEmbeddedAdapters.jsx";
import {
  closeEmbeddedWorkspace,
  collapseEmbeddedWorkspace,
  createEmbeddedWorkspace,
  createEmbeddedWorkspaceHost,
  embedPresentationMeta,
  embeddedAdapter,
  expandEmbeddedWorkspace,
  focusEmbeddedWorkspace,
  fullscreenEmbeddedWorkspace,
  openEmbeddedWorkspace,
  restoreEmbeddedWorkspace,
  shouldMountEmbeddedWorkspace,
  visibleEmbeddedWorkspaces,
} from "./neyviaEmbeddedWorkspace.js";

/**
 * Ecosystem host: the one place that renders embedded workspaces and states the
 * effective runtime composition.
 *
 * Call sites do not import this — they dispatch the events below, exactly like
 * the existing `neyvia:open-overlay` pattern, so a PDF opened from Office, an
 * artifact opened from Agent Live and a runtime window opened from Chat all
 * reach the same window contract without new plumbing per surface.
 */

export const NEYVIA_EMBED_EVENT = "neyvia:open-embedded-workspace";
export const NEYVIA_RUNTIME_INVOCATION_EVENT = "neyvia:runtime-invocation";

/** Open an embedded workspace from anywhere in the shell. */
export function openNeyviaEmbeddedWorkspace(detail = {}) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(NEYVIA_EMBED_EVENT, { detail }));
}

/** Request one of the three runtime invocation modes from anywhere. */
export function requestNeyviaRuntimeInvocation(detail = {}) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(NEYVIA_RUNTIME_INVOCATION_EVENT, { detail }));
}

async function callBackend(command, payload = {}) {
  const response = await fetch("/api/backend", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, payload }),
  });
  const result = await response.json();
  if (!response.ok || !result?.ok) throw new Error(result?.error || `${command} failed`);
  return result.data;
}

/* --------------------------------------------------------- content adapters */

/**
 * Image Playground is the one adapter whose surface is a large existing module,
 * so it stays lazily imported. Everything else is a small dedicated adapter that
 * receives the workspace record directly.
 */
const LazyImagePlayground = lazy(() =>
  import("./ImagePlayground.jsx").then(module => ({ default: module.ImagePlaygroundSurface })),
);

function EmbeddedAdapterBody({ workspace }) {
  const adapter = embeddedAdapter(workspace.adapterId);

  if (workspace.state === "blocked") {
    return (
      <div className="neyvia-embed-blocked" role="status">
        <strong>Not opened</strong>
        <ul>
          {workspace.problems.map(problem => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      </div>
    );
  }

  if (workspace.adapterId === "image-playground") {
    return (
      <Suspense fallback={<p className="neyvia-embed-loading">Loading Image Playground…</p>}>
        <LazyImagePlayground
          callBackend={callBackend}
          initialSessionId={workspace.context?.imageSessionId || undefined}
          initialManifestId={workspace.context?.manifestId || undefined}
        />
      </Suspense>
    );
  }

  const AdapterComponent = embeddedAdapterComponent(workspace.adapterId);
  if (AdapterComponent) {
    return <AdapterComponent workspace={workspace} />;
  }

  // Unmapped adapter: name it rather than rendering the wrong viewer.
  return (
    <div className="neyvia-embed-blocked" role="status">
      <strong>No viewer for {adapter?.label || workspace.adapterId}</strong>
      <p>
        This workspace is registered but no adapter component is mapped to it, so its
        content cannot be displayed here.
      </p>
    </div>
  );
}

/* ----------------------------------------------------------- window frame */

function EmbeddedWorkspaceFrame({
  workspace,
  focused,
  mounted,
  onFocus,
  onCollapse,
  onExpand,
  onRestore,
  onClose,
}) {
  const presentation = embedPresentationMeta(workspace.presentation);
  const expanded = workspace.presentation === "fullscreen";
  const collapsed = workspace.state === "collapsed";
  return (
    <section
      aria-label={`${workspace.title} embedded workspace`}
      className={[
        "neyvia-embed",
        `presentation-${workspace.presentation}`,
        focused ? "is-focused" : "is-background",
        collapsed ? "is-collapsed" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-neyvia-embed={workspace.workspaceId}
      data-embed-adapter={workspace.adapterId}
      data-embed-mounted={mounted ? "true" : "false"}
      data-embed-presentation={workspace.presentation}
      data-embed-state={workspace.state}
      onMouseDown={() => onFocus(workspace.workspaceId)}
    >
      <header className="neyvia-embed-chrome">
        <button
          className="neyvia-embed-title"
          onClick={() => onFocus(workspace.workspaceId)}
          type="button"
        >
          <strong>{workspace.title}</strong>
          {workspace.subtitle ? <small>{workspace.subtitle}</small> : null}
        </button>
        <span className="neyvia-embed-presentation" title={presentation?.detail}>
          {presentation?.label || workspace.presentation}
        </span>
        <div className="neyvia-embed-actions" role="group" aria-label="Window controls">
          {expanded ? (
            <button
              aria-label="Return to the session"
              onClick={() => onRestore(workspace.workspaceId)}
              title="Return to the session"
              type="button"
            >
              <Minimize2 aria-hidden="true" size={14} />
            </button>
          ) : (
            <button
              aria-label="Expand to fullscreen"
              onClick={() => onExpand(workspace.workspaceId)}
              title="Expand"
              type="button"
            >
              <Expand aria-hidden="true" size={14} />
            </button>
          )}
          <button
            aria-label={collapsed ? "Reopen window" : "Collapse window"}
            data-embed-action={collapsed ? "reopen" : "collapse"}
            onClick={() => onCollapse(workspace.workspaceId)}
            title={
              workspace.retainsState
                ? "Collapse — its state is kept, nothing restarts"
                : "Collapse"
            }
            type="button"
          >
            {collapsed ? <ChevronUp aria-hidden="true" size={14} /> : <ChevronDown aria-hidden="true" size={14} />}
          </button>
          <button
            aria-label="Close window"
            data-embed-action="close"
            onClick={() => onClose(workspace.workspaceId)}
            title="Close — releases this workspace"
            type="button"
          >
            <X aria-hidden="true" size={14} />
          </button>
        </div>
      </header>
      {collapsed ? (
        <p className="neyvia-embed-collapsed-note">
          {workspace.retainsState
            ? "Collapsed. Its state is retained — reopening does not restart it."
            : "Collapsed. Reopening reloads its content."}
        </p>
      ) : null}
      {/*
        Collapse hides the body; it does not unmount it. That is what makes the
        retained-state promise true: a runtime pane or application keeps running
        while collapsed and reopening does not restart it. Adapters that declared
        no retained state are unmounted on collapse, which is also honest.
      */}
      {mounted ? (
        <div className="neyvia-embed-body" hidden={collapsed}>
          <EmbeddedAdapterBody workspace={workspace} />
        </div>
      ) : null}
    </section>
  );
}

/* ---------------------------------------------------- runtime composition */

/**
 * The effective composition control.
 *
 * Compact by default so it never becomes a configuration dashboard sitting in
 * the middle of the session, and expandable when the user wants to see exactly
 * which responsibilities have moved, which stayed, and whether the runtime is
 * ready. Changing or removing an override touches only the invocation — the
 * surrounding conversation or mission is untouched.
 */
function RuntimeCompositionControl({
  composition,
  invocations,
  onClose,
  onSuspend,
  onChange,
}) {
  const [expanded, setExpanded] = useState(false);
  if (!composition) return null;
  const relevant = invocations.filter(item => item.mode !== "inline-tool");
  const showing =
    composition.surfaceOwner !== "neyvia"
    || composition.delegations.length > 0
    || relevant.length > 0;
  if (!showing) return null;

  return (
    <aside
      aria-label="Effective runtime composition"
      className={`neyvia-runtime-composition${expanded ? " is-expanded" : ""}`}
      data-neyvia-runtime-composition="true"
      data-composition-expanded={expanded ? "true" : "false"}
      data-surface-owner={composition.surfaceOwner}
    >
      <button
        aria-expanded={expanded}
        className="neyvia-runtime-composition-summary"
        onClick={() => setExpanded(current => !current)}
        type="button"
      >
        <PlugZap aria-hidden="true" size={14} />
        <span>{composition.summary}</span>
        {expanded ? <ChevronDown aria-hidden="true" size={13} /> : <ChevronUp aria-hidden="true" size={13} />}
      </button>

      {expanded ? (
        <div className="neyvia-runtime-composition-detail">
          {composition.delegations.length ? (
            <>
              <h4>Powered by an external runtime</h4>
              <ul className="neyvia-runtime-delegations">
                {composition.delegations.map(item => (
                  <li key={item.responsibility}>
                    <em>{item.label}</em> → {item.runtime}
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          <h4>Retained by Neyvia</h4>
          <ul className="neyvia-runtime-retained">
            {NEYVIA_RESERVED_RESPONSIBILITIES.map(id => (
              <li key={id}>{id}</li>
            ))}
            {NEYVIA_DELEGABLE_RESPONSIBILITIES.filter(
              item => !composition.delegations.some(row => row.responsibility === item.id),
            ).map(item => (
              <li key={item.id}>{item.label.toLowerCase()}</li>
            ))}
          </ul>

          {relevant.length ? (
            <ul className="neyvia-runtime-invocation-list">
              {relevant.map(item => (
                <li key={item.invocationId} data-invocation-state={item.state}>
                  <span>
                    <strong>{item.runtime}</strong>
                    <small>
                      {invocationModeMeta(item.mode)?.label || item.mode} · {item.state} ·{" "}
                      {item.readiness?.ready ? "ready" : item.readiness?.detail || "readiness unknown"}
                    </small>
                  </span>
                  <span className="neyvia-runtime-invocation-actions">
                    <button
                      data-composition-action="change"
                      onClick={() => onChange(item)}
                      type="button"
                    >
                      Change
                    </button>
                    {item.state !== "suspended" ? (
                      <button
                        data-composition-action="suspend"
                        onClick={() => onSuspend(item.invocationId)}
                        title="Keep it resumable"
                        type="button"
                      >
                        Suspend
                      </button>
                    ) : null}
                    <button
                      data-composition-action="remove"
                      onClick={() => onClose(item.invocationId)}
                      title="Remove the override — the conversation or mission is untouched"
                      type="button"
                    >
                      Remove
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}

/* ------------------------------------------------------------ picker sheet */

function RuntimeInvocationPicker({
  open,
  request,
  readiness,
  onCancel,
  onConfirm,
}) {
  const [mode, setMode] = useState(request?.mode || "inline-tool");
  const [runtime, setRuntime] = useState(request?.runtime || "");
  const [delegate, setDelegate] = useState(request?.delegate || []);

  useEffect(() => {
    if (!open) return;
    setMode(request?.mode || "inline-tool");
    setRuntime(request?.runtime || "");
    setDelegate(request?.delegate || []);
  }, [open, request]);

  const runtimeIds = useMemo(
    () => Object.keys(readiness?.runtimeStatus || {}).sort(),
    [readiness],
  );
  const status = readiness?.runtimeStatus?.[runtime] || null;

  if (!open) return null;

  return (
    <div className="neyvia-runtime-picker" role="dialog" aria-label="Choose how to use this runtime">
      <header>
        <h2>Use an external runtime</h2>
        <button aria-label="Cancel" onClick={onCancel} type="button">
          <X aria-hidden="true" size={14} />
        </button>
      </header>

      <fieldset className="neyvia-runtime-modes">
        <legend>Relationship with Neyvia</legend>
        {NEYVIA_INVOCATION_MODES.map(item => (
          <label key={item.id} data-selected={mode === item.id ? "true" : "false"}>
            <input
              checked={mode === item.id}
              name="neyvia-invocation-mode"
              onChange={() => setMode(item.id)}
              type="radio"
              value={item.id}
            />
            <span>
              <strong>{item.label}</strong>
              <small>{item.summary}</small>
            </span>
          </label>
        ))}
      </fieldset>

      <label className="neyvia-runtime-select">
        <span>Runtime</span>
        <select onChange={event => setRuntime(event.target.value)} value={runtime}>
          <option value="">Select a runtime…</option>
          {runtimeIds.map(id => (
            <option key={id} value={id}>
              {id}
              {readiness?.runtimeStatus?.[id]?.available ? "" : " — unavailable"}
            </option>
          ))}
        </select>
      </label>

      {status ? (
        <p className="neyvia-runtime-readiness" data-ready={status.available ? "true" : "false"}>
          {status.detail}
        </p>
      ) : null}

      {mode === "ecosystem-override" ? (
        <fieldset className="neyvia-runtime-delegation">
          <legend>What this runtime powers</legend>
          {NEYVIA_DELEGABLE_RESPONSIBILITIES.map(item => (
            <label key={item.id}>
              <input
                checked={delegate.includes(item.id)}
                onChange={event =>
                  setDelegate(current =>
                    event.target.checked
                      ? [...current, item.id]
                      : current.filter(id => id !== item.id),
                  )
                }
                type="checkbox"
              />
              <span>
                <strong>{item.label}</strong>
                <small>{item.detail}</small>
              </span>
            </label>
          ))}
          <p className="neyvia-runtime-reserved">
            Never delegated: {NEYVIA_RESERVED_RESPONSIBILITIES.join(", ")}.
          </p>
        </fieldset>
      ) : null}

      <footer>
        <button onClick={onCancel} type="button">
          Cancel
        </button>
        <button
          disabled={!runtime || (mode === "ecosystem-override" && !delegate.length)}
          onClick={() => onConfirm({ mode, runtime, delegate })}
          type="button"
        >
          {invocationModeMeta(mode)?.label || "Continue"}
        </button>
      </footer>
    </div>
  );
}

/* ------------------------------------------------------------------ host */

function embedReducer(state, action) {
  switch (action.type) {
    case "open":
      return openEmbeddedWorkspace(state, action.record);
    case "focus":
      return focusEmbeddedWorkspace(state, action.workspaceId);
    case "collapse":
      return collapseEmbeddedWorkspace(state, action.workspaceId);
    case "expand":
      return expandEmbeddedWorkspace(state, action.workspaceId, action.presentation);
    case "restore":
      return restoreEmbeddedWorkspace(state, action.workspaceId);
    case "close":
      return closeEmbeddedWorkspace(state, action.workspaceId, action.reason);
    default:
      return state;
  }
}

export function NeyviaEcosystemHost({
  sessionId = null,
  missionId = null,
  onEcosystemEvent,
}) {
  const [embedHost, dispatchEmbed] = useReducer(embedReducer, undefined, () =>
    createEmbeddedWorkspaceHost({ retainedLimit: 4 }),
  );
  const [pickerRequest, setPickerRequest] = useState(null);
  // The registry lives outside this component so the chat send path and the
  // shell surface can read the same invocations this window renders.
  const registry = useSyncExternalStore(subscribeRuntimeRegistry, getRuntimeRegistry, getRuntimeRegistry);
  const readiness = useSyncExternalStore(subscribeRuntimeRegistry, getRuntimeReadiness, getRuntimeReadiness);

  const openWorkspace = useCallback(
    detail => {
      const record = createEmbeddedWorkspace({
        adapterId: detail.adapterId,
        title: detail.title,
        subtitle: detail.subtitle,
        parentSessionId: detail.parentSessionId ?? sessionId,
        parentMissionId: detail.parentMissionId ?? missionId,
        originEventId: detail.originEventId,
        originInvocationId: detail.originInvocationId,
        contentRef: detail.contentRef,
        context: detail.context,
        permissions: detail.permissions,
        presentation: detail.presentation,
      });
      dispatchEmbed({ type: "open", record });
      return record;
    },
    [missionId, sessionId],
  );

  /* Embedded workspace requests from any surface. */
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handler = event => {
      const detail = event?.detail;
      if (!detail?.adapterId) return;
      openWorkspace(detail);
    };
    window.addEventListener(NEYVIA_EMBED_EVENT, handler);
    return () => window.removeEventListener(NEYVIA_EMBED_EVENT, handler);
  }, [openWorkspace]);

  const confirmInvocation = useCallback(
    async detail => {
      setPickerRequest(null);
      const bound = await openRuntimeInvocation({
        mode: detail.mode,
        runtime: detail.runtime,
        model: detail.model,
        parentSessionId: detail.parentSessionId ?? sessionId,
        parentMissionId: detail.parentMissionId ?? missionId,
        purpose: detail.purpose,
        contextScope: detail.contextScope,
        contextSelection: detail.contextSelection,
        delegate: detail.delegate,
        presentation: detail.presentation,
        permissions: detail.permissions,
      });
      if (!bound || bound.state === "blocked") return bound;
      // Changing an override replaces the previous one without touching the
      // surrounding conversation or mission.
      if (detail.replacesInvocationId && detail.replacesInvocationId !== bound.invocationId) {
        void closeRuntimeInvocationById(detail.replacesInvocationId, "Replaced by a changed override.");
      }
      onEcosystemEvent?.({ kind: "runtime-invocation.opened", invocation: bound });

      // Inline invocations return into the transcript as an embedded window.
      if (bound.mode === "inline-tool") {
        openWorkspace({
          adapterId: "runtime-window",
          title: `${bound.runtime} · ${bound.purpose || "scoped task"}`,
          subtitle: `Inline runtime in this session — ${bound.readiness.detail}`,
          parentSessionId: bound.parentSessionId,
          parentMissionId: bound.parentMissionId,
          originInvocationId: bound.durableInvocationId || bound.invocationId,
          presentation: "inline-card",
          context: { contextScope: bound.contextScope },
          permissions: { grants: [...bound.permissions.grants] },
        });
      }
      return bound;
    },
    [missionId, onEcosystemEvent, openWorkspace, sessionId],
  );

  /* Runtime invocation requests. `pick: true` opens the chooser. */
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handler = event => {
      const detail = event?.detail || {};
      void loadRuntimeReadiness();
      if (detail.pick !== false) {
        setPickerRequest(detail);
        return;
      }
      void confirmInvocation(detail);
    };
    window.addEventListener(NEYVIA_RUNTIME_INVOCATION_EVENT, handler);
    return () => window.removeEventListener(NEYVIA_RUNTIME_INVOCATION_EVENT, handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [confirmInvocation]);

  const handleCloseInvocation = useCallback(
    invocationId => {
      void closeRuntimeInvocationById(invocationId, "Closed by the operator.");
    },
    [],
  );

  // Nothing external outlives this Neyvia session. Cleanup is explicitly bound
  // to the captured owner; it must not sweep API-owned or other-session work.
  useEffect(() => {
    if (!sessionId) return undefined;
    return () => {
      void reapRuntimeInvocations([], { ownerSessionId: sessionId });
    };
  }, [sessionId]);

  const composition = useMemo(
    () => runtimeComposition(sessionId),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [registry, sessionId],
  );
  const liveInvocations = useMemo(
    () => registry.invocations.filter(item => item.state !== "closed"),
    [registry],
  );

  /*
    Workspaces stay attached to the context that opened them: a mission's window
    does not follow the user into an unrelated mission, and a session's window
    does not leak into another session. Workspaces with no parent are global.
  */
  const workspaces = useMemo(() => {
    const all = visibleEmbeddedWorkspaces(embedHost, {});
    return all.filter(item => {
      if (!item.parentSessionId && !item.parentMissionId) return true;
      if (item.parentMissionId && missionId && item.parentMissionId === String(missionId)) return true;
      if (item.parentSessionId && sessionId && item.parentSessionId === String(sessionId)) return true;
      return false;
    });
  }, [embedHost, missionId, sessionId]);

  const fullscreen = fullscreenEmbeddedWorkspace(embedHost);

  if (!workspaces.length && !liveInvocations.length && !pickerRequest) return null;

  return (
    <div className="neyvia-ecosystem-host" data-neyvia-ecosystem-host="true">
      <RuntimeCompositionControl
        composition={composition}
        invocations={liveInvocations}
        onChange={invocation =>
          setPickerRequest({
            mode: invocation.mode,
            runtime: invocation.runtime,
            delegate: [...(invocation.delegated || [])],
            replacesInvocationId: invocation.invocationId,
          })
        }
        onClose={handleCloseInvocation}
        onSuspend={invocationId => void suspendRuntimeInvocation(invocationId)}
      />

      <RuntimeInvocationPicker
        onCancel={() => setPickerRequest(null)}
        onConfirm={detail => {
          void confirmInvocation({ ...pickerRequest, ...detail });
        }}
        open={Boolean(pickerRequest)}
        readiness={readiness}
        request={pickerRequest}
      />

      <div
        className="neyvia-embed-host"
        data-embed-count={workspaces.length}
        data-fullscreen={fullscreen ? "true" : "false"}
      >
        {workspaces.map(workspace => (
          <EmbeddedWorkspaceFrame
            focused={embedHost.focusedId === workspace.workspaceId}
            key={workspace.workspaceId}
            mounted={shouldMountEmbeddedWorkspace(embedHost, workspace.workspaceId)}
            onClose={workspaceId => dispatchEmbed({ type: "close", workspaceId })}
            onCollapse={workspaceId =>
              dispatchEmbed({
                type: workspace.state === "collapsed" ? "focus" : "collapse",
                workspaceId,
              })
            }
            onExpand={workspaceId => dispatchEmbed({ type: "expand", workspaceId })}
            onFocus={workspaceId => dispatchEmbed({ type: "focus", workspaceId })}
            onRestore={workspaceId => dispatchEmbed({ type: "restore", workspaceId })}
            workspace={workspace}
          />
        ))}
      </div>
    </div>
  );
}

export default NeyviaEcosystemHost;
