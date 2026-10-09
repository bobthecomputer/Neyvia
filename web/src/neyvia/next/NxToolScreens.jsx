import { Suspense, lazy, useCallback, useEffect, useMemo } from "react";

import { backendBase, callNx } from "./nxApi.js";
import { local, Spinner } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { reportAppState } from "./nxBus.js";
import { saveSettings } from "./nxSettingsApi.js";
import "./nxToolScreens.css";
import { EMBED_EVENT, embeddedRoute } from "./nxEmbedRoute.js";

// Tool screens in the new shell (plan 15 T8 "port every remaining tool
// feature"). These tool screens are self-contained: they only need a way to
// call the backend, to move to another screen and to hand work to a chat. The
// same components run here, unchanged, with every control and failure state,
// on the same backend commands; this file gives them the new shell's
// navigation and colours (nxToolScreens.css maps their palettes onto the theme
// tokens). Inventory and gaps: docs/evidence/tool-gap.md.

// Tool surface id -> suite, as the backend's app.open knows them (neyvia_voice TOOL_APPS).
export const TOOL_SUITES = {
  agent: "canopy", "builder-review": "workshop", notebook: "shadow", lab: "workshop", library: "shadow", phone: "workshop",
  preview: "workshop", harnesses: "roots", skills: "roots", "rule-sets": "roots", "image-playground": "shadow",
  "app-factory": "workshop", "ios-studio": "workshop", lumaforge: "workshop", frameweave: "workshop", citecraft: "workshop",
  "aegis-range": "workshop", cueledger: "workshop",
  // Tool panels the Lab, Library and App Factory open; local stage apps until app.open lists them.
  marketplace: "workshop", "office-suite": "workshop", "personal-mesh": "workshop", security: "workshop", "mcp-broker": "workshop",
};

export const TOOL_TITLES = {
  agent: "Agent", notebook: "Notebook", lab: "Lab", library: "Library", preview: "App preview", harnesses: "Harnesses",
  "image-playground": "Image Playground", "app-factory": "App Factory", "ios-studio": "iOS Studio", lumaforge: "LumaForge",
  frameweave: "FrameWeave", citecraft: "CiteCraft", "aegis-range": "Aegis Range", cueledger: "CueLedger",
  marketplace: "Marketplace", "office-suite": "Office tools", "personal-mesh": "Personal mesh", security: "Security", "mcp-broker": "MCP servers",
};

const NATIVE_STUDIOS = ["lumaforge", "frameweave", "citecraft", "aegis-range", "cueledger"];

// The tool surfaces' shared stylesheet (classes only, all `.neyvia-*`) loads with the first tool screen.
const load = (factory, name) => lazy(() => Promise.all([factory(), import("./nxToolShared.css")]).then(([module]) => ({ default: module[name] })));
const VIEWS = {
  harnesses: load(() => import("../HarnessesSurface.jsx"), "HarnessesSurface"),
  preview: load(() => import("../NeyviaAppPreviewWorkspace.jsx"), "NeyviaAppPreviewWorkspace"),
  "app-factory": load(() => import("../NeyviaAppFactory.jsx"), "NeyviaAppFactory"),
  "ios-studio": load(() => import("../IosStudioSurface.jsx"), "IosStudioSurface"),
  studio: load(() => import("../NeyviaNativeStudios.jsx"), "NeyviaNativeStudioSurface"),
  "image-playground": load(() => import("../ImagePlayground.jsx"), "ImagePlaygroundSurface"),
  notebook: load(() => import("./NxLibrarySurfaces.jsx"), "NeyviaNotebookSurface"),
  lab: load(() => import("./NxLibrarySurfaces.jsx"), "NeyviaLabSurface"),
  library: load(() => import("./NxLibrarySurfaces.jsx"), "NeyviaLibrarySurface"),
  marketplace: load(() => import("../NeyviaMarketplacePanel.jsx"), "NeyviaMarketplacePanel"),
  "office-suite": load(() => import("../NeyviaOfficeSuitePanel.jsx"), "NeyviaOfficeSuitePanel"),
  "personal-mesh": load(() => import("../NeyviaPersonalMeshPanel.jsx"), "NeyviaPersonalMeshPanel"),
  security: load(() => import("../NeyviaSecurityRuntimePanel.jsx"), "NeyviaSecurityRuntimePanel"),
  "mcp-broker": load(() => import("../NeyviaMcpBrokerPanel.jsx"), "NeyviaMcpBrokerPanel"),
};

/** The tool `callBackend(command, payload, {signal, throwOnError})`: the data, or null on failure unless asked to throw. */
export async function callToolBackend(command, payload, options = {}) {
  try {
    return await callNx(command, payload ?? {}, { signal: options.signal });
  } catch (error) {
    if (options.throwOnError) throw error;
    return null;
  }
}

/** Whether an app id is a tool screen this shell hosts. */
export const isToolScreen = id => Boolean(VIEWS[id] || NATIVE_STUDIOS.includes(id));

/** Open a tool screen on the stage (the same state app.open sets). */
export const openTool = (id, target = null) => os.openApp(id, TOOL_SUITES[id] || "workshop", target);

/** Mounted once by the shell: every "Open here" lands on a real surface or says why it can't. */
export function useEmbeddedWorkspaceBridge() {
  useEffect(() => {
    const onOpen = event => {
      const route = embeddedRoute(event.detail);
      if (!route) { os.notify({ level: "warning", message: `${event.detail?.title || "That"} can't open in this window yet. Open it from Apps instead.` }); return; }
      if (route.kind === "pane") os.showPane(route.pane, route.target);
      else if (route.kind === "tool") openTool(route.app, route.target);
      else os.openApp(route.app, route.suite, route.target);
    };
    window.addEventListener(EMBED_EVENT, onOpen);
    return () => window.removeEventListener(EMBED_EVENT, onOpen);
  }, []);
}

function useToolNavigation(nav, onShowChat) {
  const setSurface = useCallback(surface => {
    const id = String(surface || "");
    if (["agent", "home", "workbench", "workflows"].includes(id)) { os.closeStage(); nav?.onNewChat?.(); return; }
    if (id === "builder") { os.showPane("builder", ""); return; }
    if (id === "settings") { os.showPane("settings", ""); return; }
    if (id === "images") { openTool("image-playground"); return; }
    if (isToolScreen(id)) { openTool(id); return; }
    os.notify({ level: "warning", message: "This action has no screen in this build. Choose it from Apps or open a new chat." });
  }, [nav]);

  const openPanel = useCallback(panel => {
    const id = String(panel || "");
    if (isToolScreen(id)) { openTool(id); return; }
    if (id === "pdf") { os.openApp("pdf", "documents", null); return; }
    os.notify({ level: "warning", message: "This action has no screen in this build. Choose it from Apps or open a new chat." });
  }, []);

  // Hand work to a chat: the prompt goes in the new chat's message box (never sent by itself).
  const handToChat = useCallback(text => {
    if (text) local.set("draft.new", String(text));
    os.closeStage();
    nav?.onNewChat?.();
    onShowChat?.();
  }, [nav, onShowChat]);

  const requestAction = useCallback((action, payload = {}) => {
    const id = String(action || "");
    // The domain panel already handed its prepared brief to onSelectPrompt.
    // Its completion event must not replace that draft with a generic prompt.
    if (id === "neyvia:domain:start") return;
    if (id === "app-factory:open-preview") { openTool("preview", JSON.stringify({ jobId: String(payload.jobId || ""), root: String(payload.root || "") })); return; }
    if (id === "app-factory:continue-agent") {
      if (!payload.prompt) { os.notify({ level: "warning", message: "This App Factory job has no handoff for an agent yet." }); return; }
      handToChat(payload.prompt);
      return;
    }
    if (id === "ios-studio:open-agent") {
      handToChat(`Work on the iPhone app ${payload.appName || ""} (${payload.bundleIdentifier || "no bundle id yet"}, ${payload.framework || "framework not set"}) in ${payload.projectRoot || "its project folder"}.`);
      return;
    }
    if (id === "lab:open-images") { openTool("image-playground"); return; }
    if (/(-created|-planned|-prepared|-scanned|-compiled|-captured|-imported|-registered)$/.test(id)) {
      os.notify({ level: "success", message: "Saved." }); // the screen already shows what changed
      return;
    }
    if (id.startsWith("neyvia:tool:") || id.startsWith("neyvia:toolbar:") || id.endsWith(":plan") || id === "neyvia:domain:start" || id === "neyvia:library:describe" || id === "neyvia:command:describe") {
      const prompt = typeof payload?.prompt === "string" ? payload.prompt : "";
      handToChat(prompt || `Use the ${id.split(":").slice(-1)[0].replace(/-/g, " ")} tool.`);
      return;
    }
    os.notify({ level: "warning", message: "This action has no screen in this build. Choose it from Apps or open a new chat." });
  }, [handToChat]);

  return { setSurface, openPanel, requestAction, handToChat };
}

/** One tool screen, hosted on the stage. `target` carries a preview request (App preview) when there is one. */
export function NxToolScreen({ app, target, session, nav, onShowChat, readOnly = false }) {
  const imageAsset = useOs(state => state.imageAsset);
  const reportNativeImage = useCallback(state => reportAppState('image-studio', state), []);
  const { setSurface, openPanel, requestAction, handToChat } = useToolNavigation(nav, onShowChat);
  const workspaceRoot = session?.cwd || "";
  const previewRequest = useMemo(() => { try { return target ? JSON.parse(target) : null; } catch { return null; } }, [target]);
  const studio = NATIVE_STUDIOS.includes(app);
  // The tool Agent screen is the chat itself: app.open agent starts a new chat.
  useEffect(() => { if (app === "agent") setSurface("agent"); }, [app, setSurface]);
  const View = studio ? VIEWS.studio : VIEWS[app];
  if (!View) return null;
  const common = { callBackend: callToolBackend, onSetSurface: setSurface, onRequestAction: requestAction, onOpenPanel: openPanel, workspaceRoot, readOnly };
  const props = app === "image-playground" ? { ...common,
    nativeAsset: !readOnly && imageAsset ? { ...imageAsset, url: backendBase() + imageAsset.url } : null,
    onNativeImageState: readOnly ? undefined : reportNativeImage }
    : studio ? { callBackend: callToolBackend, onSetSurface: setSurface, studioId: app }
    : app === "preview" ? { ...common, previewRequest }
      : app === "ios-studio" ? { ...common, currentProjectLabel: session?.project || "" }
        : app === "lab" ? { ...common, requestedTab: target || undefined }
          : app === "library" ? { ...common, availabilityFilter: local.get("library.filter", "all"), onAvailabilityFilterChange: value => local.set("library.filter", value),
            onApplyExperience: async experience => {
              const layouts = { minimal: ["calm", "minimal"], creator: ["workshop", "summaries"], researcher: ["grove", "everything"], engineer: ["workshop", "summaries"] };
              const selected = layouts[experience.uiPreset];
              if (!selected) throw new Error("This domain has no supported layout.");
              await saveSettings({ density: selected[0] });
              os.setTransparency(selected[1]);
            }, onSelectPrompt: handToChat }
            : ["marketplace", "office-suite", "personal-mesh"].includes(app) ? { ...common, open: true, onClose: os.closeStage }
              : common;
  return (
    <div className={`nx-tool-screen nx-tool-screen-${studio ? "studio" : app} nx-scroll`} data-tool-screen={app}>
      <Suspense fallback={<div className="nx-stage-loading"><Spinner size={16} /></div>}>
        <View {...props} />
      </Suspense>
    </div>
  );
}
