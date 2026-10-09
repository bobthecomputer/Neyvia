import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import {
  CircleDashed,
  FileText,
  Image as ImageIcon,
  Monitor,
  Package,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  Terminal,
} from "lucide-react";

import {
  NEYVIA_RESERVED_RESPONSIBILITIES,
  invocationModeMeta,
  responsibilityMeta,
} from "./neyviaRuntimeInvocation.js";
import {
  closeRuntimeInvocationById,
  findRuntimeInvocation,
  getRuntimeRegistry,
  refreshRuntimeInvocations,
  resumeRuntimeInvocation,
  subscribeRuntimeRegistry,
  suspendRuntimeInvocation,
} from "./neyviaRuntimeStore.js";
import { NeyviaRuntimeComposer } from "./NeyviaRuntimeComposer.jsx";

/**
 * Concrete embedded-workspace adapters.
 *
 * The window behaviour (open, focus, expand, collapse, return, close) belongs
 * to the host. These components are only the *content*: each one receives the
 * workspace record — including its `contentRef`, lineage and permissions — so a
 * specific PDF opens that PDF rather than a generic panel, and a runtime window
 * shows its own invocation rather than a placeholder.
 *
 * Where the backend has not supplied a readable source, the adapter says what
 * is missing. None of them fabricate content.
 */

/* ------------------------------------------------------------------ shared */

/** The one place that decides whether a workspace has anything to show. */
export function resolveWorkspaceSource(workspace) {
  const ref = workspace?.contentRef || {};
  const context = workspace?.context || {};
  const url = String(ref.url || "").trim();
  const endpoint = String(ref.endpoint || "").trim();
  const path = String(ref.path || "").trim();
  const captureHref = String(
    ref.captureUrl ||
      ref.capture_url ||
      ref.screenshotUrl ||
      ref.screenshot_url ||
      ref.imageUrl ||
      context.captureUrl ||
      context.capture_url ||
      context.screenshotUrl ||
      "",
  ).trim();
  const executablePath = String(
    ref.executablePath ||
      ref.executable_path ||
      context.executablePath ||
      context.executable_path ||
      "",
  ).trim();
  const windowId = String(
    ref.windowId || ref.window_id || context.windowId || context.window_id || context.targetWindow || "",
  ).trim();
  const processId = Number(
    ref.processId || ref.process_id || ref.pid || context.processId || context.process_id || context.pid || 0,
  );
  const desktopDeclared = Boolean(captureHref || executablePath || windowId || processId > 0);
  return {
    /** Something the browser can actually load. */
    href: url || endpoint || "",
    /** A workspace path we can name but not necessarily render. */
    path,
    captureHref,
    executablePath,
    windowId,
    processId,
    desktopDeclared,
    label: captureHref || url || endpoint || executablePath || path || windowId || "",
    loadable: Boolean(url || endpoint),
  };
}

function AdapterShell({ icon: Icon, kind, title, detail, children, footer }) {
  return (
    <div className="neyvia-adapter" data-neyvia-adapter-kind={kind}>
      <header className="neyvia-adapter-head">
        {Icon ? <Icon aria-hidden="true" size={14} /> : null}
        <div>
          <strong>{title}</strong>
          {detail ? <small>{detail}</small> : null}
        </div>
      </header>
      <div className="neyvia-adapter-body">{children}</div>
      {footer ? <footer className="neyvia-adapter-foot">{footer}</footer> : null}
    </div>
  );
}

/** Truthful empty state: names the missing thing instead of showing a shell. */
function UnavailableSource({ what, workspace }) {
  const source = resolveWorkspaceSource(workspace);
  return (
    <div className="neyvia-adapter-unavailable" role="status">
      <CircleDashed aria-hidden="true" size={18} />
      <strong>No readable {what} source</strong>
      {source.path ? (
        <p>
          This workspace points at <code>{source.path}</code>, but the backend has not
          returned a served URL for it, so nothing can be displayed here yet.
        </p>
      ) : (
        <p>
          Nothing was attached to this workspace. Open it from an artifact, an Office
          document or a mission deliverable so it carries a source.
        </p>
      )}
    </div>
  );
}

function LineageRow({ workspace }) {
  const bits = [
    workspace.parentMissionId ? `mission ${workspace.parentMissionId}` : "",
    workspace.parentSessionId ? `session ${workspace.parentSessionId}` : "",
    workspace.lineage?.originEventId ? `event ${workspace.lineage.originEventId}` : "",
    workspace.context?.artifactId ? `artifact ${workspace.context.artifactId}` : "",
  ].filter(Boolean);
  if (!bits.length) return null;
  return <p className="neyvia-adapter-lineage">{bits.join(" · ")}</p>;
}

/* --------------------------------------------------------------- documents */

export function PdfAdapter({ workspace }) {
  const source = resolveWorkspaceSource(workspace);
  return (
    <AdapterShell
      detail={source.label || "No document attached"}
      footer={<LineageRow workspace={workspace} />}
      icon={FileText}
      kind="pdf"
      title={workspace.title || "PDF"}
    >
      {source.loadable ? (
        <object
          aria-label={`${workspace.title} document`}
          className="neyvia-adapter-frame"
          data={source.href}
          type="application/pdf"
        >
          {/* Browsers without an inline PDF viewer still get the real file. */}
          <p className="neyvia-adapter-fallback">
            This browser cannot display the PDF inline.{" "}
            <a href={source.href} rel="noreferrer" target="_blank">
              Open {workspace.title}
            </a>
          </p>
        </object>
      ) : (
        <UnavailableSource what="PDF" workspace={workspace} />
      )}
    </AdapterShell>
  );
}

const OFFICE_INLINE_TYPES = ["text/html", "text/plain", "application/pdf"];

export function OfficeDocumentAdapter({ workspace }) {
  const source = resolveWorkspaceSource(workspace);
  const mediaType = String(workspace.context?.mediaType || "").toLowerCase();
  // Office originals are not browser-renderable; only a converted/rendered
  // output is. Saying so is more useful than an empty viewer.
  const renderable =
    source.loadable && (!mediaType || OFFICE_INLINE_TYPES.some(type => mediaType.includes(type)));
  return (
    <AdapterShell
      detail={source.label || "No document attached"}
      footer={<LineageRow workspace={workspace} />}
      icon={FileText}
      kind="office"
      title={workspace.title || "Document"}
    >
      {renderable ? (
        <iframe
          className="neyvia-adapter-frame"
          sandbox="allow-same-origin"
          src={source.href}
          title={`${workspace.title} document`}
        />
      ) : source.loadable ? (
        <div className="neyvia-adapter-unavailable" role="status">
          <FileText aria-hidden="true" size={18} />
          <strong>Original format is not browser-renderable</strong>
          <p>
            <code>{source.label}</code> is available, but it needs a rendered or
            converted output before it can be shown inline. Convert it in Office to open
            the result here.
          </p>
        </div>
      ) : (
        <UnavailableSource what="document" workspace={workspace} />
      )}
    </AdapterShell>
  );
}

/* ------------------------------------------------------------------ visual */

export function BrowserCaptureAdapter({ workspace }) {
  const source = resolveWorkspaceSource(workspace);
  return (
    <AdapterShell
      detail={source.label || "No capture attached"}
      footer={<LineageRow workspace={workspace} />}
      icon={ImageIcon}
      kind="capture"
      title={workspace.title || "Capture"}
    >
      {source.loadable ? (
        <img alt={workspace.title || "Captured page"} className="neyvia-adapter-image" src={source.href} />
      ) : (
        <UnavailableSource what="capture" workspace={workspace} />
      )}
    </AdapterShell>
  );
}

export function AppPreviewAdapter({ workspace }) {
  const source = resolveWorkspaceSource(workspace);
  const receipt = workspace?.context?.captureReceipt || workspace?.contentRef?.captureReceipt || "";
  return (
    <AdapterShell
      detail={source.label || "No preview target"}
      footer={<LineageRow workspace={workspace} />}
      icon={Monitor}
      kind="preview"
      title={workspace.title || "Preview"}
    >
      {source.captureHref ? (
        <div className="neyvia-adapter-desktop-preview" data-preview-target="desktop-capture">
          <img
            alt={`${workspace.title || "Desktop app"} window capture`}
            className="neyvia-adapter-image"
            src={source.captureHref}
          />
          <p>
            Captured from {source.windowId ? `window ${source.windowId}` : "the running app"}
            {source.processId ? ` · process ${source.processId}` : ""}
            {receipt ? ` · receipt ${receipt}` : ""}.
          </p>
        </div>
      ) : source.loadable ? (
        <iframe
          className="neyvia-adapter-frame"
          // A delivered preview is untrusted content: it may script itself but
          // gets no same-origin access to the Neyvia session.
          sandbox="allow-scripts allow-forms"
          src={source.href}
          title={`${workspace.title} preview`}
        />
      ) : source.desktopDeclared ? (
        <div
          className="neyvia-adapter-unavailable"
          data-preview-target={source.executablePath ? "executable" : "desktop-window"}
          role="status"
        >
          <Monitor aria-hidden="true" size={18} />
          <strong>
            {source.executablePath ? "Executable is ready for desktop preview" : "App window is ready for capture"}
          </strong>
          <p>
            {source.executablePath ? <><code>{source.executablePath}</code>{" "}</> : null}
            Neyvia will show this app only after Application Surface or Computer Use returns
            a real window capture and proof receipt. It will not substitute a fake frame.
          </p>
          {source.windowId || source.processId ? (
            <dl className="neyvia-adapter-facts">
              {source.windowId ? <div><dt>Window</dt><dd>{source.windowId}</dd></div> : null}
              {source.processId ? <div><dt>Process</dt><dd>{source.processId}</dd></div> : null}
            </dl>
          ) : null}
        </div>
      ) : (
        <UnavailableSource what="preview" workspace={workspace} />
      )}
    </AdapterShell>
  );
}

/* ------------------------------------------------------------ marketplace */

export function MarketplaceApplicationAdapter({ workspace }) {
  const applicationId = String(workspace.context?.applicationId || "").trim();
  const declaredPresentation = String(workspace.context?.presentation || workspace.presentation);
  const active = workspace.context?.applicationState === "active";
  const source = resolveWorkspaceSource(workspace);
  return (
    <AdapterShell
      detail={applicationId || "No application identity"}
      footer={<LineageRow workspace={workspace} />}
      icon={Package}
      kind="application"
      title={workspace.title || "Application"}
    >
      {/* An installed tile is not an active capability. Only an active
          application with a served entry point renders anything. */}
      {active && source.loadable ? (
        <iframe
          className="neyvia-adapter-frame"
          sandbox="allow-scripts allow-forms"
          src={source.href}
          title={`${workspace.title} application`}
        />
      ) : (
        <div className="neyvia-adapter-unavailable" role="status">
          <Package aria-hidden="true" size={18} />
          <strong>{active ? "No served entry point" : "Not active"}</strong>
          <p>
            {active
              ? "This application is active but did not declare a served entry point, so there is nothing to embed."
              : "This application is installed but not active. Activate it in Marketplace before it can provide capabilities here."}
          </p>
          <dl className="neyvia-adapter-facts">
            <div>
              <dt>Declared presentation</dt>
              <dd>{declaredPresentation}</dd>
            </div>
            {workspace.permissions?.grants?.length ? (
              <div>
                <dt>Granted</dt>
                <dd>{workspace.permissions.grants.join(", ")}</dd>
              </div>
            ) : null}
          </dl>
        </div>
      )}
    </AdapterShell>
  );
}

/* ------------------------------------------------------------ runtime pane */

const RUNTIME_STATE_COPY = {
  requested: "Requested — waiting for the backend to report readiness.",
  ready: "Ready — the backend resolved this runtime but no turn has run yet.",
  active: "Active — the runtime is working on this invocation.",
  suspended: "Suspended — state kept, nothing restarts on resume.",
  returned: "Returned — the runtime handed work back to this session.",
  blocked: "Blocked — this invocation cannot proceed.",
  closed: "Closed — this invocation will not resume.",
};

/**
 * The inline runtime window.
 *
 * It is bound to a real invocation record and shows only what that record and
 * the durable registry contain: identity, model, scoped purpose, context scope,
 * parent session/mission, readiness, lifecycle state, and whatever the runtime
 * actually returned. When nothing has been returned yet it says so instead of
 * animating fake activity.
 */
export function RuntimeWindowAdapter({ workspace }) {
  const [refreshing, setRefreshing] = useState(false);
  useSyncExternalStore(subscribeRuntimeRegistry, getRuntimeRegistry, getRuntimeRegistry);

  const invocationId = workspace.lineage?.originInvocationId || workspace.context?.invocationId || "";
  const invocation = useMemo(
    () => (invocationId ? findRuntimeInvocation(invocationId) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [invocationId, getRuntimeRegistry()],
  );

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await refreshRuntimeInvocations({ parentSessionId: workspace.parentSessionId });
    } finally {
      setRefreshing(false);
    }
  }, [workspace.parentSessionId]);

  // One reconcile when the pane opens, so a window reopened later shows what
  // the backend recorded while it was collapsed.
  useEffect(() => {
    if (!invocationId) return;
    void refresh();
  }, [invocationId, refresh]);

  if (!invocation) {
    return (
      <AdapterShell icon={Terminal} kind="runtime" title={workspace.title || "Runtime"}>
        <div className="neyvia-adapter-unavailable" role="status">
          <CircleDashed aria-hidden="true" size={18} />
          <strong>No invocation record</strong>
          <p>
            This window is not bound to a runtime invocation, so there is no lifecycle,
            context or return channel to show.
          </p>
        </div>
      </AdapterShell>
    );
  }

  const returns = invocation.returns || {};
  const returnedAnything =
    (returns.messages?.length || 0)
    + (returns.artifacts?.length || 0)
    + (returns.receipts?.length || 0)
    + (returns.changes?.length || 0) > 0;
  const suspended = invocation.state === "suspended";
  const closed = invocation.state === "closed";

  return (
    <AdapterShell
      detail={`${invocationModeMeta(invocation.mode)?.label || invocation.mode}${
        invocation.model ? ` · ${invocation.model}` : ""
      }`}
      icon={Terminal}
      kind="runtime"
      title={invocation.runtime}
    >
      <dl className="neyvia-adapter-facts" data-runtime-state={invocation.state}>
        <div>
          <dt>Purpose</dt>
          <dd>{invocation.purpose || "Not stated"}</dd>
        </div>
        <div>
          <dt>Context</dt>
          <dd>
            {invocation.contextScope}
            {invocation.contextSelection?.length
              ? ` · ${invocation.contextSelection.length} selected item(s)`
              : ""}
          </dd>
        </div>
        <div>
          <dt>Parent</dt>
          <dd>
            {invocation.parentMissionId
              ? `mission ${invocation.parentMissionId}`
              : invocation.parentSessionId
                ? `session ${invocation.parentSessionId}`
                : "None recorded"}
          </dd>
        </div>
        <div>
          <dt>Readiness</dt>
          <dd data-ready={invocation.readiness?.ready ? "true" : "false"}>
            {invocation.readiness?.detail || "Not reported"}
          </dd>
        </div>
        <div>
          <dt>State</dt>
          <dd>{RUNTIME_STATE_COPY[invocation.state] || invocation.state}</dd>
        </div>
        {invocation.delegated?.length ? (
          <div>
            <dt>Powers</dt>
            <dd>
              {invocation.delegated
                .map(id => responsibilityMeta(id)?.label || id)
                .join(", ")}
            </dd>
          </div>
        ) : null}
      </dl>

      {invocation.problems?.length ? (
        <ul className="neyvia-adapter-problems">
          {invocation.problems.map(problem => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}

      {returnedAnything ? (
        <div className="neyvia-adapter-returns">
          {returns.messages?.length ? (
            <section>
              <h4>Messages</h4>
              <ol>
                {returns.messages.map((message, index) => (
                  <li key={`message-${index}`}>
                    {typeof message === "string" ? message : message?.text || message?.message || ""}
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
          {returns.changes?.length ? (
            <section>
              <h4>Changes</h4>
              <ul>
                {returns.changes.map((change, index) => (
                  <li key={`change-${index}`}>
                    {typeof change === "string" ? change : change?.path || change?.label || "change"}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {returns.artifacts?.length ? (
            <section>
              <h4>Artifacts</h4>
              <ul>
                {returns.artifacts.map((artifact, index) => (
                  <li key={`artifact-${index}`}>
                    {typeof artifact === "string"
                      ? artifact
                      : artifact?.label || artifact?.artifactId || artifact?.path || "artifact"}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {returns.receipts?.length ? (
            <section>
              <h4>Receipts</h4>
              <ul>
                {returns.receipts.map((receipt, index) => (
                  <li key={`receipt-${index}`}>
                    {typeof receipt === "string" ? receipt : receipt?.id || receipt?.kind || "receipt"}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      ) : (
        <p className="neyvia-adapter-waiting" role="status">
          {closed
            ? "This invocation is closed. Nothing further will be returned."
            : "Nothing returned yet. This window shows the runtime's own output as soon as the backend records it — it does not simulate activity."}
        </p>
      )}

      {!closed ? (
        <NeyviaRuntimeComposer
          invocation={invocation}
          workspacePath={workspace.context?.workspacePath || null}
        />
      ) : null}

      <div className="neyvia-adapter-runtime-actions" role="group" aria-label="Runtime lifecycle">
        <button disabled={refreshing} onClick={() => void refresh()} type="button">
          <RefreshCw aria-hidden="true" size={13} />
          {refreshing ? "Checking…" : "Check for returns"}
        </button>
        {!closed && suspended ? (
          <button
            data-runtime-action="resume"
            onClick={() => void resumeRuntimeInvocation(invocation.invocationId)}
            type="button"
          >
            <PlayCircle aria-hidden="true" size={13} /> Resume
          </button>
        ) : null}
        {!closed && !suspended ? (
          <button
            data-runtime-action="suspend"
            onClick={() => void suspendRuntimeInvocation(invocation.invocationId)}
            title="Leave it running state intact — it can be resumed"
            type="button"
          >
            <PauseCircle aria-hidden="true" size={13} /> Suspend
          </button>
        ) : null}
        {!closed ? (
          <button
            data-runtime-action="close"
            onClick={() =>
              void closeRuntimeInvocationById(invocation.invocationId, "Closed from the runtime window.")
            }
            title="End this invocation permanently — it will not resume"
            type="button"
          >
            End invocation
          </button>
        ) : null}
      </div>

      <small className="neyvia-adapter-reserved">
        Neyvia keeps {NEYVIA_RESERVED_RESPONSIBILITIES.join(", ")}.
      </small>
    </AdapterShell>
  );
}

/* ---------------------------------------------------------------- registry */

/**
 * Adapter id → component. The host looks up here; anything unmapped falls back
 * to a descriptor rather than rendering the wrong viewer.
 */
export const NEYVIA_EMBEDDED_ADAPTER_COMPONENTS = Object.freeze({
  "pdf-reader": PdfAdapter,
  "office-document": OfficeDocumentAdapter,
  "browser-capture": BrowserCaptureAdapter,
  "app-preview": AppPreviewAdapter,
  "marketplace-app": MarketplaceApplicationAdapter,
  "runtime-window": RuntimeWindowAdapter,
});

export function embeddedAdapterComponent(adapterId) {
  return NEYVIA_EMBEDDED_ADAPTER_COMPONENTS[String(adapterId || "")] || null;
}
