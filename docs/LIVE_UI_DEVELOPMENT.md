# Live UI Development

Fluxio now runs with its shell and style system under `web/src/neyvia/*`.

## What changed

- `web/src/neyvia/NeyviaShell.jsx` now owns layout, state composition, and mission thread rendering.
- `web/src/neyvia/NeyviaApp.tsx` now wraps the shell in a real error boundary with recoverable diagnostics.
- `web/src/neyvia/styles.css` now owns the visual system for the shell.
- `desktop-ui/NeyviaDesktop.jsx` is now a compatibility wrapper only.
- `desktop-ui/styles.css` now imports the web shell stylesheet as a shim.

This removes split ownership between the frontend entrypoint and `desktop-ui` for the main app experience.

## Current local setup

- `package.json`
  - `npm run frontend:dev` starts Vite for `web`
  - `npm run frontend:build` builds `web/dist`
  - `npm run web:serve` builds `web/dist` and serves the website plus the local HTTP backend on `http://127.0.0.1:47880`
  - `npm run nas:setup` prepares a NAS install and generates an ignored local account password
- `src-tauri/tauri.conf.json`
  - `beforeDevCommand` runs the Vite dev server
  - `devUrl` points Tauri at the live frontend
  - `frontendDist` points packaged builds to `web/dist`
- `web/src/main.tsx`
  - mounts `NeyviaApp`
  - imports `web/src/neyvia/styles.css`

## Website Backend

The React shell keeps the Tauri command path for the desktop app and falls back to `POST /api/backend` when it runs as a website. The web backend is `python -m grant_agent.web_backend`; it exposes the control-room snapshot, workspace/mission actions, provider presence, Codex import inspection, and connected-app bridge status through the same command names used by the Tauri shell. Browser access requires the local Neyvia account login before command APIs are available.

Hosted static deployments on GitHub Pages or Vercel can render the Fluxio web shell and fixture fallback. Machine-local control, provider secrets, OpenClaw/Hermes runtime detection, and Synology Fast Sync bridge state require the local backend because they read this workstation and its environment. For a browser-hosted shell pointed at a separately hosted backend, set `VITE_FLUXIO_BACKEND_URL` at build time or `window.__FLUXIO_BACKEND_URL__` before boot.

NAS setup lives in `docs/SYNOLOGY_NAS_SETUP.md`.

Deployment config:

- GitHub Pages: `.github/workflows/web-pages.yml`
- Vercel: `vercel.json`

## Runtime review loop

1. Run `npm run tauri:dev`.
2. Use `Agent` mode for normal operator supervision.
3. Switch to `Builder` mode and open the Builder drawer to access:
   - fixture selection
   - live-sync cadence
   - release-confidence score and required-gate breakdown
   - roadmap-to-100 quality sprint (state-driven next actions)
   - workspace profile policy editor (harness, routing, execution target, MiniMax auth path)
   - service management surface with executable setup actions
   - skill studio catalog review with filter/search/profile coverage
   - workflow studio recipes and learning queue
   - git and validation operations
   - feature-truth audit
   - core-state audit
4. Keep `Preview = Live Backend` for real mission validation.
5. Use fixtures only for review states where backend mutation is undesirable.

## Live behavior notes

- Snapshot refresh still supports push events (`control-room://changed`, `control-room://delta`) plus optional polling fallback.
- Polling suspends when the window is hidden and resumes on visibility restore.
- Activity, runtime events, and proof deltas are shown in the mission thread and review drawers.
- Builder mode now expands into a materially denser technical surface; Agent mode stays thread-first with lower control density.
- Render-time crashes now show a recoverable error panel with failing action context and boot diagnostics.

Official references:

- Tauri develop docs: <https://v2.tauri.app/develop/>
- Tauri config reference: <https://tauri.app/es/reference/config/>
- Tauri + Vite frontend guide: <https://v2.tauri.app/start/frontend/vite/>
- Vite HMR docs: <https://vite.dev/guide/features.html#hot-module-replacement>
