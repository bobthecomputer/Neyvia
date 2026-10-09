# Chat permission persistence — 2026-09-27

Fixed transient permission state resetting to read-only on chat changes. The frontend now saves explicit choices under `fluxio.chat.workspacePermissionModes`, keyed by workspace identity, path, and chat id. New and previously unsaved chats default to Full access as requested. An explicitly saved Read-only choice remains Read-only. Draft selections transfer to the created chat without overwriting an existing choice. Sending without an explicit run override uses the active selection.

Files: web/src/neyvia/workspaceToolAccess.js; permission imports/state/effect/send fallback in NeyviaShell.jsx. Backend permission enforcement is unchanged.

Verification: frontend build passed (existing chunk-size warning); seven focused Node tests passed. Actual browser at http://127.0.0.1:47881/control showed Full access after loading the rebuilt app, creating a new chat, opening an existing chat, and reloading. Explicit Read-only restoration and draft transfer are covered by the Node checks. No extra model invocation was used for this permission journey.

Persistence is local to this app/browser profile and origin. Existing choices were not persisted by the previous version, so missing historical choices cannot be recovered and use the requested Full access default. No new desktop installer or public release was made.
