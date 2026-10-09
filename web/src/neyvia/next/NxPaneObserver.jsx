import { createContext, useContext, useEffect, useMemo, useRef } from "react";

import { ackPane } from "./nxBus.js";
import { HEARTBEAT_MS, SETTLE_MS, ackBody, elementBusy, elementVisible, projectText, sameAck, sha256Hex } from "./nxPaneObserve.js";

// Every pane on the stage sits in an ObservedPane. When the pane was opened by a pane.show event
// that asks for a renderer observation (plans/15-handoff.md "## FIXCL renderer"), the pane itself
// tells the backend, over the existing ack channel, what really mounted and what it shows:
//   - panes with a real runtime (file editor, artifact, owned browser tab, terminal, app preview)
//     report their runtime id and the content they display through usePaneObservation();
//   - every other pane is its own content, so its settled DOM text is the projection.
// Nothing is reported from the request or from a loading veil. Reports repeat every few seconds
// while visible, change when the content does, and say mounted:false/visible:false on the way out.
// A pane that fails or refuses to load says ok:false with the reason.

const NOOP = { active: false, report: () => {}, fail: () => {}, withdraw: () => {}, dom: () => {} };
const Context = createContext(NOOP);

/** The mounted pane's reporter (a no-op outside an observed pane or when nobody asked). */
export function usePaneObservation() {
  return useContext(Context);
}

/** Switches a subtree to DOM projection (a pane with no runtime of its own, like the PDF viewer). */
export function ObserveDom() {
  const observation = usePaneObservation();
  useEffect(() => { observation.dom(true); return () => observation.dom(false); }, [observation]);
  return null;
}

/** Reports a load failure or refusal (ok:false) while it is on screen. */
export function PaneRefused({ reason }) {
  const observation = usePaneObservation();
  useEffect(() => { observation.fail(reason); }, [observation, reason]);
  return null;
}

/** An image, reported once it has really decoded (its address and pixel size are what shows). */
export function ObservedImage({ src, alt, runtime }) {
  const observation = usePaneObservation();
  return (
    <img src={src} alt={alt}
      onLoad={event => void observation.report({ runtimeId: runtime, content: `image\n${alt}\n${event.currentTarget.naturalWidth}x${event.currentTarget.naturalHeight}` })}
      onError={() => observation.fail(`The image ${alt} could not be loaded`)} />
  );
}

const mountSeq = { value: 0 };

export function ObservedPane({ request, kind, explicit, children }) {
  const element = useRef(null);
  const requestRef = useRef(request);
  requestRef.current = request;
  const mountId = useMemo(() => `${Date.now().toString(36)}${(mountSeq.value += 1).toString(36)}`, []);
  const state = useRef({ report: null, failure: null, shown: true, mounted: true, dom: !explicit, last: null, seq: 0 });

  const api = useMemo(() => {
    const mark = (status, extra = {}) => {
      const node = element.current;
      if (!node) return;
      node.dataset.observation = status;
      for (const [key, value] of Object.entries(extra)) {
        if (value == null) delete node.dataset[key];
        else node.dataset[key] = value;
      }
    };
    const push = force => {
      const current = requestRef.current;
      if (!current) return;
      const now = state.current;
      const visible = now.mounted && now.shown && elementVisible(element.current);
      const body = ackBody(current, { failure: now.failure, report: now.report, mounted: now.mounted, visible }, undefined);
      if (!body) return;
      if (!force && sameAck(body, now.last)) return;
      now.last = body;
      mark(body.ok ? (body.observation.visible ? "sending" : "hidden") : "failed", {
        runtimeId: body.observation?.runtimeId, contentHash: body.observation?.contentHash, ackError: body.ok ? null : body.error,
      });
      void ackPane(body).then(
        () => { if (state.current.last === body) mark(body.ok ? (body.observation.visible ? "acknowledged" : "hidden") : "failed"); },
        error => { if (state.current.last === body) mark("refused", { ackError: String(error?.message || error).slice(0, 300) }); },
      );
    };
    return {
      active: true,
      push,
      /**
       * The runtime that really mounted and the content it displays right now. Blank content is a
       * placeholder unless the runtime says it really shows nothing (an empty file: allowEmpty).
       */
      report: async ({ runtimeId, content, allowEmpty = false }) => {
        const seq = (state.current.seq += 1);
        const text = String(content ?? "");
        const contentHash = await sha256Hex(text);
        if (seq !== state.current.seq || !state.current.mounted) return; // newer content already reported
        state.current.report = { runtimeId: String(runtimeId || ""), contentHash, empty: !allowEmpty && !text.trim() };
        state.current.failure = null;
        state.current.shown = true;
        push(false);
      },
      fail: reason => {
        state.current.seq += 1;
        state.current.failure = String(reason || "The pane could not load");
        state.current.report = null;
        push(false);
      },
      /** The content is not displayed any more (another view of the pane took its place). */
      withdraw: () => { state.current.shown = false; push(false); },
      dom: on => { state.current.dom = Boolean(on) || !explicit; if (on) api.scan?.(); },
    };
  }, [explicit]);

  // DOM projection: the pane's settled, non-loading text.
  useEffect(() => {
    if (!request) return undefined;
    const node = element.current;
    let timer = 0;
    const scan = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (!state.current.dom || !node.isConnected || elementBusy(node)) return;
        const text = projectText(node.innerText ?? node.textContent);
        if (text) void api.report({ runtimeId: `dom:${kind}:${mountId}`, content: `${kind}\n${text}` });
      }, SETTLE_MS);
    };
    api.scan = scan;
    const observer = new MutationObserver(scan);
    observer.observe(node, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["aria-busy", "class", "hidden"] });
    scan();
    return () => { observer.disconnect(); clearTimeout(timer); api.scan = null; };
  }, [request?.eventId, kind, mountId, api]); // eslint-disable-line react-hooks/exhaustive-deps

  // A new request for the pane already on screen: it gets its own acknowledgement.
  useEffect(() => {
    if (!request) return;
    state.current.last = null;
    if (element.current) element.current.dataset.paneId = request.paneId;
    api.push(true);
  }, [request?.eventId, api]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fresh while visible, and an immediate report when the page or the pane is hidden or shown.
  useEffect(() => {
    if (!request) return undefined;
    const beat = setInterval(() => api.push(true), HEARTBEAT_MS);
    const onVisibility = () => api.push(false);
    document.addEventListener("visibilitychange", onVisibility);
    return () => { clearInterval(beat); document.removeEventListener("visibilitychange", onVisibility); };
  }, [request?.eventId, api]); // eslint-disable-line react-hooks/exhaustive-deps

  // Unmounted: the backend hears it, so a closed pane never stays "visible".
  useEffect(() => () => {
    state.current.mounted = false;
    state.current.last = null;
    api.push(true);
  }, [api]);

  const value = request ? api : NOOP;
  return (
    <div ref={element} className="nx-pane-observed" data-pane-kind={kind} data-pane-id={request?.paneId} data-observation={request ? "pending" : undefined}>
      <Context.Provider value={value}>{children}</Context.Provider>
    </div>
  );
}
