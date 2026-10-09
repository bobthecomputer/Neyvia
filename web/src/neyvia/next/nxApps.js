import React, { lazy, useEffect, useState } from "react";
import { backendBase } from "./nxApi.js";

// The four app suites (07 §R1). The backend's registry (GET /api/apps) is the
// source of truth for which apps are ready; this built-in copy of the plan's
// list is shown, all "Coming", only while that registry can't be reached.
// Chat, the development workspace, runtime and missions are Neyvia itself,
// not launcher apps.

export const PLAN_SUITES = [
  { id: "documents", name: "Documents", description: "PDF, documents, LaTeX and spreadsheets", apps: [
    { id: "pdf", name: "PDF viewer", description: "Read, search and annotate PDFs" },
    { id: "notes", name: "Notes", description: "Markdown notes you can dictate, search and tag" },
    { id: "files", name: "Files", description: "Browse, preview, move and tidy your files" },
    { id: "doc-editor", name: "Document editor", description: "Write and edit documents" },
    { id: "latex", name: "LaTeX", description: "LaTeX with a rendered preview" },
    { id: "spreadsheets", name: "Spreadsheets", description: "Excel-style sheets" },
  ] },
  { id: "game-dev", name: "Game Dev", description: "Unity, Roblox, Godot, assets and playtests", apps: [
    { id: "unity", name: "Unity", description: "Scenes, components, compile and tests" },
    { id: "roblox", name: "Roblox Studio", description: "Hierarchy, scripts and playtest" },
    { id: "godot", name: "Godot", description: "Nodes, scripts and runs" },
    { id: "asset-checks", name: "Asset checks", description: "Blender export and glTF validation" },
    { id: "playtest", name: "Playtest runner", description: "Run, watch and report a playtest" },
  ] },
  { id: "studio", name: "Studio", description: "Images, video, visualization and quizzes", apps: [
    { id: "scroll-generator", name: "Scroll Study", description: "Course notes to seven-part revision packs" },
    { id: "image-studio", name: "Image Studio", description: "Generate, edit and dissect images" },
    { id: "mobile-studio", name: "Mobile Studio", description: "iPhone and Android apps, with a live phone preview" },
    { id: "video", name: "Video editing", description: "Cut, arrange and export video" },
    { id: "visualization", name: "Visualization", description: "Charts and diagrams" },
    { id: "quiz", name: "Quiz maker", description: "Build and run quizzes" },
  ] },
  { id: "lab", name: "Lab", description: "Decompiling, optimization, modding and security", apps: [
    { id: "decompile", name: "Decompiling", description: "Reverse engineering with Ghidra and ILSpy" },
    { id: "hill-climb", name: "Hill climbing", description: "The Evolver: searches, receipts, Pareto front" },
    { id: "modding", name: "Modding", description: "Mod projects and loaders" },
    { id: "security", name: "Security", description: "Security tools" },
  ] },
];

// Apps of the shell itself (not in a suite): opened with os.openApp, placed like any app
// (beside the chat, side panel, full screen or a bubble). NxStage renders `view`.
export const SHELL_APPS = [
  { id: "memory", name: "Memory", description: "Private project memories, corrections and forgetting",
    view: lazy(() => import("./NxMemoryPanel.jsx").then(module => ({ default: module.NxMemoryPanel }))) },
  { id: "sessions", name: "Sessions", description: "Every running session side by side, with live transcripts and actions",
    view: lazy(() => import("./NxSessionsPane.jsx").then(module => ({ default: ({ nav }) => React.createElement(module.NxSessionsPane, { nav }) }))) },
  { id: "agent-view", name: "Agents at work", description: "Watch agents on their own screens, steer them, and catch up with a time-lapse",
    view: lazy(() => import("./agentview/NxAgentView.jsx").then(module => ({ default: module.NxAgentView }))) },
];

const text = (...values) => values.find(value => typeof value === "string" && value.trim()) || "";

/** Accept the registry in any of the shapes a JSON route may wrap it in. */
export function normalizeRegistry(raw) {
  const body = raw?.data ?? raw;
  const suites = Array.isArray(body) ? body : body?.suites;
  if (!Array.isArray(suites) || !suites.length) return null;
  return suites.map(suite => ({
    id: text(suite.id, suite.key, suite.name).toLowerCase().replace(/\s+/g, "-"),
    name: text(suite.name, suite.title, suite.label, suite.id),
    description: text(suite.description, suite.summary),
    apps: (Array.isArray(suite.apps) ? suite.apps : []).map(app => ({
      id: text(app.id, app.key, app.name),
      name: text(app.name, app.title, app.label, app.id),
      description: text(app.description, app.summary),
      status: app.status === "ready" ? "ready" : "coming",
      manual: text(app.manual, app.manual_path, app.manualPath) || null,
    })),
  }));
}

const fallback = PLAN_SUITES.map(suite => ({ ...suite, apps: suite.apps.map(app => ({ ...app, status: "coming", manual: null })) }));

let cache = { suites: fallback, source: "plan", error: "" };
let inflight = null;
const listeners = new Set();

export async function loadApps() {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      if (import.meta.env.DEV && new URLSearchParams(globalThis.location?.search || "").get("bus") === "mock") {
        const { mockRegistry } = await import("./nxBusMock.js");
        cache = { suites: normalizeRegistry(mockRegistry(PLAN_SUITES)), source: "mock", error: "" };
        return cache;
      }
      const response = await fetch(`${backendBase()}/api/apps`, { credentials: "include", headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const suites = normalizeRegistry(await response.json());
      if (!suites) throw new Error("The app registry was empty");
      cache = { suites, source: "backend", error: "" };
    } catch (error) {
      cache = { suites: fallback, source: "plan", error: error?.message || "The app registry could not be read" };
    } finally {
      inflight = null;
      for (const listener of listeners) listener(cache);
    }
    return cache;
  })();
  return inflight;
}

export function useApps() {
  const [state, setState] = useState(cache);
  useEffect(() => {
    listeners.add(setState);
    if (cache.source !== "backend") void loadApps();
    return () => listeners.delete(setState);
  }, []);
  return state;
}

export function findApp(suites, appId) {
  for (const suite of suites) {
    const app = suite.apps.find(entry => entry.id === appId);
    if (app) return { suite, app };
  }
  return null;
}
