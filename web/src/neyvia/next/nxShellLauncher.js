import { BUILTIN_SCENES } from "./nxLayoutModel.js";
import { THEMES, THEME_LABELS, applyUiAction, getOs, os } from "./nxOsStore.js";
import { windowAt } from "./nxPlacementModel.js";
import { placeSession } from "./nxSidebarModel.js";
import { isDesktopApp, signOutHere } from "./nxApi.js";
import { startVoiceCommand } from "./NxVoice.jsx";
import { openFromUi } from "./nxOutputsApi.js";
import { TOOL_SUITES, openTool } from "./NxToolScreens.jsx";

// What the launcher (Ctrl Space) offers besides apps and chats, and what each
// action does. Pure lists from the shell's state; NxShell keeps only routing.

const TOOL_LAUNCH = [
  ["app-factory", "App Factory", "Describe an app, build a draft, try it", ["app factory", "create app", "build app", "factory", "native", "desktop app"]],
  ["preview", "App preview", "Try App Factory builds and review their look", ["app preview", "preview app", "taste", "test app"]],
  ["harnesses", "Harnesses", "Runtimes, instructions, profiles, jobs, batches and comparisons", ["harness", "harnesses", "batch", "prompt batches", "compare", "benchmark", "profiles", "instructions", "provider sign in"]],
  ["ios-studio", "iOS Studio", "Build, preview and package iPhone and iPad apps", ["ios", "iphone", "ipad", "xcode", "mac builder"]],
  ["image-playground", "Image Playground", "Generate, layer, pin and export images", ["image", "images", "playground", "generate image", "layers"]],
  ["lab", "Lab", "Experiments, benchmarks, security, authored tools, MCP", ["lab", "experiments", "benchmarks", "adapters", "computer use proof"]],
  ["library", "Library", "Skills and capability packs, readiness and domain packs", ["library", "capabilities", "packs", "tool suite", "domain"]],
  ["notebook", "Notebook", "Sources, research and saved artifacts", ["notebook", "research", "sources", "documents"]],
  ["marketplace", "Marketplace", "Apps and signed local packages: install, activate, roll back", ["marketplace", "install", "packages", "apps store", "modules", "installed programs"]],
  ["office-suite", "Office tools", "Convert and render documents with LibreOffice and Pandoc", ["office", "libreoffice", "pandoc", "convert", "docx"]],
  ["personal-mesh", "Personal mesh", "Trust, Nearby Send and Folder Sync", ["mesh", "nearby", "folder sync", "trust", "devices"]],
  ["security", "Security", "Runtime audit, scope checks, purple-team plan", ["security", "audit", "threat model", "red team", "purple team"]],
  ["mcp-broker", "MCP servers", "Search, describe and call brokered MCP tools", ["mcp", "broker", "servers", "tools"]],
  ["lumaforge", "LumaForge", "Adjust and export images", ["lumaforge", "image edit", "adjust"]],
  ["frameweave", "FrameWeave", "Preview video and mark in and out", ["frameweave", "video", "clip"]],
  ["citecraft", "CiteCraft", "Sources, claims and research notes", ["citecraft", "citations", "claims", "research"]],
  ["aegis-range", "Aegis Range", "Security findings with severity", ["aegis", "findings", "security range"]],
  ["cueledger", "CueLedger", "Audio waveform and timestamped cues", ["cueledger", "audio", "cues", "waveform"]],
];
// Tool screens the backend's app.open already knows; the rest open locally.
const NAVIGABLE = new Set(["app-factory", "preview", "harnesses", "ios-studio", "image-playground", "lab", "library", "notebook", "lumaforge", "frameweave", "citecraft", "aegis-range", "cueledger"]);

const DENSITY_ACTIONS = [["calm", "Calm"], ["workshop", "Workshop"], ["grove", "Grove"]];

/** One entry per project folder, pointing at its latest chat. */
export function launcherProjects(rows) {
  const found = new Map();
  for (const row of rows) {
    if (row.archived) continue;
    const place = placeSession(row);
    if (place.group !== "project" || !place.path) continue;
    const key = place.project.toLowerCase();
    const known = found.get(key);
    if (!known || String(row.updated_at || "") > known.updated) found.set(key, { name: place.project, path: place.path, latest: row.id, updated: String(row.updated_at || "") });
  }
  return [...found.values()];
}

export function launcherActions({ density, theme, arranging, scenes, sidebarHidden, stage, chatId, floating, hasPrevious }) {
  return [
    { id: "new-chat", title: "New chat", keywords: ["start", "compose"] },
    { id: "memory", title: "Memory", subtitle: "What Neyvia remembers in this project", keywords: ["memory", "remember", "recall", "forget", "preferences"] },
    ...(hasPrevious ? [{ id: "previous-chat", title: "Back to the previous conversation", subtitle: "Or hold Ctrl and tap `", keywords: ["switch", "recent", "layer", "last"] }] : []),
    { id: "builder", title: "Builder", subtitle: "Every project at a glance, and what's next", keywords: ["builder", "dashboard", "projects", "overview", "board", "today", "next"] },
    { id: "nightshift", title: "Night Shift", subtitle: "Tasks that start each other overnight, with evidence and a budget", keywords: ["night shift", "night", "overnight", "tasks", "board", "TASKS.md", "prerequisites", "budget", "quiet hours", "morning"] },
    { id: "agent-view", title: "Agents at work", subtitle: "Watch agents on their own screens, steer them, catch up with a time-lapse", keywords: ["agents", "watch", "live", "computer use", "screen", "time-lapse", "timelapse", "replay", "steer", "feedback", "browser agent"] },
    { id: "missions", title: "Missions", subtitle: "One goal, many agents: plan, approve, watch", keywords: ["missions", "orchestration", "orchestrate", "agents", "plan", "team", "night shift"] },
    { id: "parallel", title: "Parallel branches", subtitle: "Several agents on their own worktrees, a main agent answering, one branch at the end", keywords: ["parallel", "branches", "worktrees", "worktree", "agents", "merge", "conflict", "settle", "main agent", "tracks", "t3", "orchestration", "team"] },
    { id: "conductor", title: "Conductor", subtitle: "One goal: a planner splits it, agents do it, a verifier proves it", keywords: ["conductor", "goal", "orchestration", "orchestrate", "agents", "plan", "planner", "verifier", "routes", "jobs", "task tree"] },
    { id: "onboarding", title: "Setup and tour", subtitle: "Downloads, the Claude Code mod, Codex skills and connections", keywords: ["setup", "set up", "onboarding", "first run", "interests", "settings", "welcome", "install", "packs", "runtimes", "agents"] },
    { id: "unique", title: "What makes Neyvia different", subtitle: "The things a plain chat does not do, and what unlocks each", keywords: ["help", "different", "unique", "what is neyvia", "features", "laya", "manuals", "mod", "skills", "new", "learn"] },
    { id: "tour", title: "Replay the tour", subtitle: "The full walk through Neyvia", keywords: ["help", "tour", "tutorial", "video", "walkthrough", "guide", "learn", "how"] },
    { id: "usage", title: "Usage", subtitle: "Plan windows, tokens by day and model, estimated API cost", keywords: ["usage", "tokens", "cost", "price", "spend", "limits", "plan", "quota", "analytics", "cache", "budget", "api"] },
    { id: "agents", title: "Agents overview", subtitle: "Every agent at work, its helpers and connections", keywords: ["agents", "overview", "working", "tree", "delegation", "subagents", "needs you"] },
    { id: "connections", title: "Connections", subtitle: "Every agent, key and local model: sign in, test, connect in one click", keywords: ["connections", "connect", "connected", "sign in", "login", "log in", "keys", "api keys", "accounts", "harnesses", "providers", "test", "kimi", "gptme", "local models"] },
    { id: "runtime", title: "Runtimes", subtitle: "Codex, Claude Code, OpenCode and more: found, version, models, limits", keywords: ["runtime", "runtimes", "harness", "harnesses", "codex", "claude", "opencode", "models", "permissions", "ceiling", "cli", "agents", "installed", "version"] },
    { id: "preview", title: "Preview: apps agents are using", subtitle: "Watch an agent drive an app and use it with it", keywords: ["preview", "computer use", "watch", "live", "app", "drive", "desktop", "take over", "test", "window", "cua"] },
    { id: "remote-use", title: "Use an app on another PC", subtitle: "Live, with a one-use code from that PC", keywords: ["remote", "remote control", "other pc", "another pc", "control", "zen", "chatgpt", "tailscale", "connect", "screen"] },
    { id: "remote-share", title: "Let another PC use an app here", subtitle: "Pick the windows and the time; Stop now anytime", keywords: ["remote", "remote control", "share", "share screen", "allow", "other pc", "another pc", "stop", "kill switch"] },
    { id: "browser", title: "Browser", subtitle: "Your tabs and agents' tabs: spaces, split view, reader mode, peek", keywords: ["browser", "web", "internet", "tabs", "url", "website", "search", "arc", "spaces", "split", "reader", "peek", "obscura", "agent tabs", "history", "downloads"] },
    { id: "3d-studio", title: "3D Studio", subtitle: "The browser 3D scene editor: side panel, full screen or a bubble", keywords: ["3d", "three d", "scene", "babylon", "mesh", "model", "studio", "webgl", "game"] },
    { id: "laya", title: "LAYA activity", subtitle: "What the small local model answered, as a window", keywords: ["laya", "local model", "small model", "decisions", "tokens saved", "computer use"] },
    { id: "outputs", title: "Outputs", subtitle: "Every file, change, image, report and receipt agents made", keywords: ["outputs", "artifacts", "results", "files", "images", "reports", "receipts", "diffs", "changes", "gallery", "published"] },
    // Screens brought over from the tool view (NxToolScreens), with the same controls and backend.
    ...TOOL_LAUNCH.map(([app, title, subtitle, keywords]) => ({ id: `tool-app:${app}`, title, subtitle, keywords })),
    { id: "terminal", title: "Terminal", subtitle: "A shell in this chat's folder", keywords: ["terminal", "shell", "console", "powershell", "command", "cmd", "prompt"] },
    { id: "accounts", title: "Accounts", subtitle: "Your password and devices; people on this PC", keywords: ["account", "accounts", "users", "people", "password", "profile", "devices", "sessions", "members", "sign out", "logout"] },
    ...(isDesktopApp() ? [] : [{ id: "sign-out", title: "Sign out of this browser", keywords: ["sign out", "log out", "logout", "leave"] }]),
    { id: "arrange", title: arranging ? "Finish arranging" : "Arrange the layout", subtitle: "Move and resize regions, arrange the home widgets", keywords: ["move", "resize", "customize", "widgets", "dashboard", "layout", "rearrange", "drag", "dock"] },
    ...Object.entries({ ...BUILTIN_SCENES, ...scenes }).map(([id, scene]) => ({ id: `scene:${id}`, title: `Scene: ${scene.label}`, subtitle: scene.hint || "Saved scene", keywords: ["scene", "mode", "layout", "preset", scene.label] })),
    ...(chatId ? [{ id: "replay", title: "Replay this chat, fast", subtitle: "Everything that happened, at up to 60×", keywords: ["replay", "playback", "history", "timeline", "rewind", "watch", "accelerated"] }] : []),
    ...(chatId ? [{ id: "float", title: floating ? "Bring this chat back from its bubble" : "Float this chat as a bubble", subtitle: "Keep an eye on it from anywhere", keywords: ["float", "bubble", "window", "pip", "pin", "watch"] }] : []),
    ...THEMES.map(id => ({ id: `theme:${id}`, title: `Theme: ${THEME_LABELS[id]}`, subtitle: id === theme ? "Current" : "", keywords: ["theme", "colour", "color", "dark", "light", "appearance", id, THEME_LABELS[id]] })),
    ...DENSITY_ACTIONS.map(([level, label]) => ({ id: `density:${level}`, title: `Density: ${label}`, subtitle: level === density ? "Current" : "", keywords: [label, "layout", "density"] })),
    { id: "tidy", title: "Tidy the sidebar", subtitle: "See which stale chats would be archived, then confirm", keywords: ["cleanup", "archive", "clean"] },
    { id: "look", title: "Look", subtitle: "Theme, typeface, text size and background", keywords: ["look", "appearance", "font", "typeface", "text size", "bigger text", "background", "wallpaper", "picture", "colour", "color", "theme", "dark", "light"] },
    { id: "settings", title: "Settings", subtitle: "Look, initiative, Night Shift budget, local-only, cleanup and setup", keywords: ["settings", "preferences", "options", "cleanup", "automatic", "archive", "theme", "density", "initiative", "night shift", "budget", "local-only", "offline", "privacy", "internet", "setup"] },
    { id: "sidebar", title: sidebarHidden ? "Show the sidebar" : "Hide the sidebar", keywords: ["sidebar"] },
    { id: "help", title: "Keyboard and voice", subtitle: "Every shortcut and every voice command (Ctrl /)", keywords: ["keyboard", "shortcuts", "keys", "hotkeys", "voice", "commands", "accessibility", "help", "what can i say"] },
    { id: "voice", title: "Say a command", subtitle: "Voice control: hold Ctrl Alt Space, talk, release", keywords: ["voice", "speak", "talk", "say", "command", "microphone", "mic", "hands free", "accessibility"] },
    ...(stage ? [{ id: "close-stage", title: "Close the open app", keywords: ["close", "undock"] }] : []),
    // Placement of the app beside the chat (every window also has these as buttons and Alt+Shift+arrows).
    ...(stage ? [
      { id: "place:side", title: "Move the open app to the side panel", keywords: ["side", "panel", "dock", "move", "placement", "split"] },
      { id: "place:full", title: "Open app full screen", keywords: ["full screen", "fullscreen", "maximize", "placement"] },
      { id: "place:bubble", title: "Collapse the open app to a bubble", keywords: ["bubble", "minimize", "float", "pip", "placement"] },
    ] : []),
  ];
}

/** Run an interface action. Returns false for the ones that need the shell (chats, tidy). */
export function runInterfaceAction(id, { chatId, floating } = {}) {
  if (id.startsWith("density:")) os.setDensity(id.slice(8));
  else if (id.startsWith("theme:")) os.setTheme(id.slice(6));
  else if (id.startsWith("scene:")) os.scene(id.slice(6));
  else if (id === "arrange") os.arrange();
  else if (id === "builder") os.showPane("builder", "");
  else if (id === "agent-view") os.openApp("agent-view", "", null);
  else if (id === "missions") os.showPane("mission", "");
  else if (id === "nightshift") os.showPane("mission", "nightshift");
  else if (id === "conductor") os.showPane("mission", "conductor");
  else if (id === "parallel") os.showPane("parallel", "");
  else if (id === "accounts") os.showPane("accounts", "");
  else if (id === "runtime" || id === "connections") os.showPane("runtime", "");  // Connections is the top of the Runtimes pane
  else if (id === "usage") os.showPane("usage", "");
  else if (id === "agents") applyUiAction("pane.show", { kind: "agents", target: "", placement: "full" });
  else if (id === "terminal") os.showPane("terminal", "");
  else if (id === "preview") os.showPane("preview", "");
  else if (id === "remote-use") os.showPane("preview", "remote:use");
  else if (id === "remote-share") os.showPane("preview", "remote:host");
  else if (id === "browser") os.openApp("browser", "", null);
  else if (id === "3d-studio") os.openApp("3d-studio", "studio", null);
  else if (id === "laya") os.openApp("laya", "", null);
  else if (id === "memory") os.openApp("memory", "", null);
  else if (id.startsWith("place:")) {
    const win = windowAt(getOs().windows, "main");
    if (win) os.placeWindow(win.id, id.slice(6));
  }
  else if (id === "outputs") void openFromUi("outputs", { local: () => os.showPane("outputs", "") });
  else if (id.startsWith("tool-app:")) {
    const app = id.slice(9);
    if (NAVIGABLE.has(app)) void openFromUi(app, { suite: TOOL_SUITES[app], local: () => openTool(app) }); else openTool(app);
  }
  else if (id === "onboarding") os.openOnboarding("welcome");
  else if (id === "settings") os.showPane("settings", "");
  else if (id === "look") os.showPane("settings", "look");
  else if (id === "tidy") os.showPane("settings", "tidy");
  else if (id === "tour") os.openOnboarding("tour", "tour");
  else if (id === "unique") os.openOnboarding("unique", "unique");
  else if (id === "sign-out") void signOutHere();
  else if (id === "float" && chatId) (floating ? os.unfloat : os.float)(chatId);
  else if (id === "replay" && chatId) os.showPane("replay", chatId);
  else if (id === "sidebar") os.toggleSidebar();
  else if (id === "close-stage") os.closeStage();
  else if (id === "help") os.setHelp(true);
  else if (id === "voice") startVoiceCommand();
  else return false;
  return true;
}
