# How Neyvia keeps itself current

Three parts, three routes. None of them needs an installer after the one install of 0.2.0.

## 1. The interface (desktop app, browser, phone)

The PC service (`127.0.0.1:47881`, supervisor-managed) serves the current interface. A promotion updates it.

- **Browser and phone** load it from the service directly.
- **The desktop app** keeps its own copy, but its `index.html` loader first asks the service for `/desktop-entry.json` and loads the interface code from there. The page stays on the app's own origin, so every desktop feature keeps working. If the service does not answer within 2 seconds, the copy inside the app loads instead. The loader is a Vite plugin in `vite.config.mjs`.
- **The service** answers the desktop origins (`http://tauri.localhost` and the others in `DESKTOP_SHELL_ORIGINS`) with CORS headers for interface files, never for the page itself.

## 2. The desktop shell (Rust: tray, window, native commands, updater)

Only changes under `src-tauri` need a new build.

- **Building:** `python scripts/publish_desktop_update.py --tree C:\Users\example\Projects\Neyvia --bump` raises the patch version and builds a signed installer. It publishes the installer to `<state root>/.agent_control/desktop-updates/` and writes `latest.json` there. The service serves that folder at `/updates/desktop/`, without sign-in; every file is signature-checked by the app.
- **Checking:** the app checks the feed 20 seconds after start and every 6 hours (`start_self_update` in `src-tauri/src/lib.rs`). It installs only while its window is not in use. The passive installer restarts the app, and conversations live in the service, so they are untouched.
- **Signing key:** `%APPDATA%\Neyvia\updater\neyvia-updater.key`, public key id `44915C00CB3B4477`. Its random password is stored with Windows DPAPI in `neyvia-updater.password.dpapi` (`scripts/desktop_update_key.py`). **Back up the key file**: without it, the next shell update needs a manual install again.
- **The older key** (`B5EC92196C4E569D`) exists only as the GitHub secret `TAURI_SIGNING_PRIVATE_KEY` for `.github/workflows/publish-desktop-release.yml`. GitHub-built releases are signed with it, so apps from 0.2.0 on do not accept them unless that secret is replaced with the new key.

## 3. Agent CLIs (Claude Code, Codex, OpenCode, OpenClaw, Hermes, Cursor, ...)

The service updates them in the background (`_keep_tools_updated` in `web_backend.py`): first 10 minutes after start, then hourly. Turn it off with `NEYVIA_TOOL_AUTO_UPDATE=0`.

- **Your own npm CLIs** (`%APPDATA%\npm`, used by your terminal and by connected chats): `update_user_global_clis` compares each installed package with its newest npm release and updates it. It keeps a receipt in `.agent_control/user_cli_update.json`.
- **Neyvia's managed runtimes** (its separate CLI home, e.g. `D:\NeyviaCLI`): `ensure_runtime_auto_update(..., runtime_ids=["all"], skip_missing=True)`. npm-installed runtimes are compared with npm; the others use their own update command. It keeps a receipt in `.agent_control/runtime_update_preflight.json`.
- **A tool that is running is never updated under it.** It is marked `deferred` and retried the next hour. Neyvia's own Codex app-server is released first when idle (`CodexAdapter.release_for_update`); it restarts on its own at the next request.

## Sign-in to Neyvia (browser and phone)

A session renews itself while it is used, at most once a day, to 180 days from then (`web_auth_sessions.py`); the cookie lasts 400 days, the browser maximum. You sign in again only after signing out, after 180 days unused, or when the account's identity changes (a new password or user list). The desktop app needs no Neyvia sign-in.

Publication note: local account paths and network identifiers in this document are neutral examples.
