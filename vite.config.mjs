import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { realpathSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { checkVitePhysicalPaths } from "./scripts/release-contracts.mjs";

const host = process.env.TAURI_DEV_HOST || "127.0.0.1";
const port = Number(process.env.TAURI_DEV_PORT || "1420");
const backendTarget = process.env.FLUXIO_WEB_BACKEND_URL || "http://127.0.0.1:47880";
// Keep Vite and Rollup on one physical path when the operator checkout uses
// Windows directory junctions (for example a C: workspace backed by D:).
const webRoot = realpathSync(fileURLToPath(new URL("./web", import.meta.url)));
const repoRoot = resolve(webRoot, "..");
const webSrc = resolve(webRoot, "src");

// The desktop app keeps a copy of this interface, but prefers the current one
// from the PC service, so a promotion updates the desktop app without a new
// build. The page stays on the app's own origin (every desktop feature keeps
// working) and only its code is loaded from the service; relative imports then
// fetch the rest from there too. If the service does not answer in time, the
// copy inside the app loads instead. Browsers and phones load their own copy.
const DESKTOP_UI_SERVICE = "http://127.0.0.1:47881";
const DESKTOP_LOADER = `(() => {
  const own = __ENTRY__;
  const load = (base, entry) => {
    for (const href of entry.css || []) {
      const link = document.createElement("link");
      link.rel = "stylesheet"; link.crossOrigin = ""; link.href = base + href;
      document.head.appendChild(link);
    }
    for (const href of entry.preload || []) {
      const link = document.createElement("link");
      link.rel = "modulepreload"; link.crossOrigin = ""; link.href = base + href;
      document.head.appendChild(link);
    }
    const script = document.createElement("script");
    script.type = "module"; script.crossOrigin = ""; script.src = base + entry.js;
    document.body.appendChild(script);
  };
  const desktop = Boolean(window.__TAURI_INTERNALS__) && (location.hostname === "tauri.localhost" || location.protocol === "tauri:");
  if (!desktop) { load("./", own); return; }
  const service = "${DESKTOP_UI_SERVICE}";
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), 2000);
  fetch(service + "/desktop-entry.json", { cache: "no-store", signal: stop.signal })
    .then(response => (response.ok ? response.json() : Promise.reject(new Error(String(response.status)))))
    .then(current => {
      clearTimeout(timer);
      if (!current || typeof current.js !== "string") throw new Error("no entry");
      window.__NEYVIA_UI_SOURCE__ = service;
      load(service + "/", current);
    })
    .catch(() => {
      clearTimeout(timer);
      window.__NEYVIA_UI_SOURCE__ = "bundled";
      load("./", own);
    });
})();`;

function desktopLoader() {
  let entry = null;
  let outDir = "";
  const strip = href => href.replace(/^\.?\//, "");
  return {
    name: "neyvia-desktop-loader",
    apply: "build",
    configResolved(config) {
      outDir = config.build.outDir;
    },
    transformIndexHtml: {
      order: "post",
      handler(html) {
        if (process.env.NEYVIA_SLIM_INSTALLER === "1") return html;
        const script = /<script type="module" crossorigin src="([^"]+)"><\/script>\s*/g;
        const style = /<link rel="stylesheet" crossorigin href="([^"]+)">\s*/g;
        const preload = /<link rel="modulepreload" crossorigin href="([^"]+)">\s*/g;
        const scripts = [...html.matchAll(script)];
        if (scripts.length !== 1) return html; // an unexpected page shape is left exactly as Vite built it
        entry = {
          js: strip(scripts[0][1]),
          css: [...html.matchAll(style)].map(match => strip(match[1])),
          preload: [...html.matchAll(preload)].map(match => strip(match[1])),
        };
        const page = html.replace(script, "").replace(style, "").replace(preload, "");
        return page.replace("</body>", `<script>${DESKTOP_LOADER.replace("__ENTRY__", JSON.stringify(entry))}</script>\n</body>`);
      },
    },
    writeBundle() {
      if (entry) writeFileSync(resolve(outDir, "desktop-entry.json"), `${JSON.stringify({ ...entry, builtAt: new Date().toISOString() })}\n`);
    },
  };
}

function manualChunks(id) {
  const normalizedId = id.replaceAll("\\", "/");

  // Keep the single shell's tool support modules separately cacheable.
  if (
    normalizedId.endsWith("/missionControlModel.js")
  ) {
    return "neyvia-mission-models";
  }
  if (
    normalizedId.endsWith("/web/src/neyvia/RuntimeOperationsPanel.jsx") ||
    normalizedId.endsWith("/web/src/neyvia/HarnessesSurface.jsx") ||
    normalizedId.endsWith("/web/src/neyvia/NeyviaUpdatePanel.jsx")
  ) {
    return "neyvia-tool-operations";
  }
  if (!normalizedId.includes("node_modules")) {
    return undefined;
  }
  if (
    normalizedId.includes("node_modules/react/") ||
    normalizedId.includes("node_modules/scheduler")
  ) {
    return "vendor-react";
  }
  if (normalizedId.includes("node_modules/react-dom")) {
    return "vendor-react-dom";
  }
  if (normalizedId.includes("node_modules/@tauri-apps")) {
    return "vendor-tauri";
  }
  if (
    normalizedId.includes("node_modules/lucide-react") ||
    normalizedId.includes("node_modules/@phosphor-icons")
  ) {
    return "vendor-icons";
  }
  // Keep feature-only dependencies with their lazy importer. A single catch-all
  // vendor chunk made the Markdown parser part of the initial chat download.
  return undefined;
}

export default defineConfig(({ command }) => checkVitePhysicalPaths({
  define: { "import.meta.env.VITE_NEYVIA_SLIM_INSTALLER": process.env.NEYVIA_SLIM_INSTALLER === "1" },
  // Packaged Tauri builds need relative asset URLs instead of /assets/... .
  base: command === "serve" ? "/" : "./",
  plugins: [react(), tailwindcss(), desktopLoader()],
  root: webRoot,
  resolve: {
    alias: {
      "~": webSrc,
    },
  },
  server: {
    host,
    port,
    strictPort: true,
    fs: {
      // A worktree's node_modules may be a junction to another checkout: allow
      // its real path too, or bundled fonts (Geist) answer 403 in dev.
      allow: [repoRoot, realpathSync(resolve(repoRoot, "node_modules"))],
    },
    hmr: {
      protocol: "ws",
      host,
    },
    proxy: {
      "/api": backendTarget,
      "/health": backendTarget,
    },
  },
  preview: {
    host,
    port,
    strictPort: true,
  },
  build: {
    outDir: resolve(webRoot, "dist"),
    emptyOutDir: true,
    // Makes the release performance gate account for entry imports precisely.
    manifest: true,
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
}, repoRoot));
