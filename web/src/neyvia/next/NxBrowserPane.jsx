import { useEffect, useRef, useState } from "react";
import { Copy, Globe, ScanText, TriangleAlert } from "lucide-react";

import { isDesktopApp } from "./nxApi.js";
import { act, attachRuntime, useBrowser } from "./nxBrowserApi.js";
import { NativeSlot } from "./NxBrowser.jsx";
import { AgentLive, useProjection } from "./NxBrowserParts.jsx";
import { PaneRefused, usePaneObservation } from "./NxPaneObserver.jsx";
import { Button, Icon, Spinner } from "./nxPrimitives.jsx";
import { os } from "./nxOsStore.js";
import "./nxBrowser.css";

// pane.show {kind: "browser"}: a web page shown in a tab Neyvia owns and controls, never a
// free-floating iframe. The tab lives in the integrated browser (plans/15-handoff.md "## T20"):
// in the desktop app a WebView2 tab drawn into this pane, elsewhere the headless engine's tab,
// shown as the page reads. No popups, no new windows: when no owned runtime can show the page,
// the pane says so and offers the address as a plain link Paul can click himself.

const desktop = isDesktopApp();
export const isWebUrl = value => /^https?:\/\//i.test(String(value || ""));

/** The engine that can show a page here right now, or null. */
export function paneEngine(state, inDesktop = desktop) {
  if (!state) return null;
  if (inDesktop && state.runtime?.connected) return "webview2";
  if (state.headless?.connected) return "obscura";
  return null;
}

/** The semantic content a page tab displays: what the observation hashes. */
export function pageProjection(value) {
  return JSON.stringify({ url: value?.url || "", title: value?.title || "", text: String(value?.text || "") });
}

function PlainLink({ target }) {
  return (
    <code className="nx-pane-target" title={target}>
      <a href={target} rel="noreferrer noopener">{target}</a>
      <button type="button" aria-label="Copy" title="Copy" onClick={() => void navigator.clipboard?.writeText(target)}><Icon as={Copy} size={13} /></button>
    </code>
  );
}

function NoRuntime({ target, reason }) {
  return (
    <div className="nx-pane-honest" role="status">
      <PaneRefused reason={reason} />
      <Icon as={Globe} size={22} />
      <strong>This page opens in Neyvia's browser</strong>
      <p>{reason} The address is below if you want to open it yourself.</p>
      <PlainLink target={target} />
      <Button size="sm" variant="outline" icon={Globe} onClick={() => os.openApp("browser", "", target)}>Open the Browser</Button>
    </div>
  );
}

export function OwnedBrowserPane({ target }) {
  const observation = usePaneObservation();
  const { status, state, error } = useBrowser();
  const [opened, setOpened] = useState({ key: "", status: "idle" });
  const [attach, setAttach] = useState({ status: desktop ? "attaching" : "web" });
  const engine = paneEngine(state);
  const key = `${engine}:${target}`;

  // The desktop app draws visible tabs; attach its runtime once (a no-op when already attached).
  useEffect(() => {
    if (!desktop) return;
    attachRuntime().then(() => setAttach({ status: "ready" }), failure => setAttach({ status: "error", error: failure?.message || String(failure) }));
  }, []);

  // One owned tab per page and engine: reuse a live one showing this address, else open it.
  const asked = useRef("");
  useEffect(() => {
    if (status !== "ready" || !engine || asked.current === key) return;
    asked.current = key;
    const existing = state.tabs?.find(tab => tab.url === target && (tab.engine || "webview2") === engine && tab.live && !tab.mirrorOf);
    if (existing) { setOpened({ key, status: "ready", tabId: existing.id }); return; }
    setOpened({ key, status: "opening" });
    act("tab.open", { url: target, engine }).then(
      result => setOpened({ key, status: "ready", tabId: result?.tabId || result?.tab?.id }),
      failure => setOpened({ key, status: "error", error: failure?.message || String(failure) }),
    );
  }, [status, engine, key, target, state]);

  const tab = opened.key === key && opened.tabId ? state?.tabs?.find(row => row.id === opened.tabId) || null : null;
  const projection = useProjection(tab);

  // Observation: the owned tab's runtime and the page it shows, once the engine has read it.
  const value = projection.status === "ready" ? projection.value : null;
  useEffect(() => {
    if (!tab || !value) return;
    void observation.report({ runtimeId: `browser:${tab.engine || "webview2"}:${tab.id}`, content: pageProjection(value) });
  }, [observation, tab?.id, tab?.engine, value]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (projection.status === "error" && !value) observation.fail(projection.error || "The page could not be read");
  }, [observation, projection.status, projection.error, value]);
  useEffect(() => { if (opened.status === "error") observation.fail(opened.error); }, [observation, opened.status, opened.error]);
  useEffect(() => { if (tab && tab.live === false && /needed$/.test(tab.status || "")) observation.withdraw(); }, [observation, tab?.live, tab?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  if (status === "loading" || (desktop && attach.status === "attaching" && !engine)) return <div className="nx-stage-loading"><Spinner size={16} /></div>;
  if (status === "error" && !state) return <NoRuntime target={target} reason={`The browser service can't be reached: ${error || "no answer"}.`} />;
  if (!engine) {
    const why = desktop
      ? `The page view isn't running${attach.error ? ` (${attach.error})` : ""}.`
      : "Pages open inside Neyvia in the desktop app, or here once the agent browser is started from Runtimes.";
    return <NoRuntime target={target} reason={why} />;
  }
  if (opened.status === "error") return <NoRuntime target={target} reason={`Neyvia's browser couldn't open it: ${opened.error}.`} />;
  if (!tab) return <div className="nx-stage-loading"><Spinner size={16} /></div>;

  return (
    <div className="nx-pane-browser" data-runtime={`${tab.engine || "webview2"}:${tab.id}`}>
      <div className="nx-pane-bar">
        <span className="nx-pane-url" title={tab.url}>{tab.url}</span>
        <Button size="sm" variant="ghost" icon={ScanText} onClick={() => os.showPane("perception", `browser:${target}`)}>See as the agent</Button>
        <Button size="sm" variant="ghost" icon={Globe} onClick={() => os.openApp("browser", "", target)}>Open in Browser</Button>
      </div>
      {tab.engine === "obscura" ? (
        <AgentLive tab={tab} sessionId={state.headless?.sessionId} desktop={desktop} runtimeConnected={Boolean(state.runtime?.connected)}
          onWatch={() => void act("promote", { tabId: tab.id }).catch(() => {})} onTakeOver={() => os.openApp("browser", "", target)} />
      ) : (
        <NativeSlot slot="stage-pane" tabId={tab.id} className="nx-pane-native">
          {tab.loading || !tab.live ? <div className="nx-br-center" aria-busy="true"><Spinner size={16} /><span>Opening the page…</span></div> : null}
          {projection.status === "error" && !value ? <div className="nx-br-center"><Icon as={TriangleAlert} size={20} /><span>{projection.error}</span></div> : null}
        </NativeSlot>
      )}
    </div>
  );
}
