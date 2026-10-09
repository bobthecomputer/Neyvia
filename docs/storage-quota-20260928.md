# Storage quota repair — 2026-09-28

The desktop failed during refresh because a React effect synchronously wrote the entire transcript map to localStorage and exceeded its quota. The error prevented normal rendering and could interrupt subsequent persistence effects.

neyviaStorage keeps synchronous reads backed by an in-memory map initialized from IndexedDB before React mounts. Large values and quota-failed small writes use IndexedDB. The previous localStorage value is removed only after transaction completion. Failed persistence retains the current in-memory value, logs the failure, and does not throw through React. No transcript truncation or history deletion was added. Shell storage calls and the secondary transcript reader use the shared store.

Verification: Playwright Chromium saved and recovered a 7,000,022-character transcript across reload; checked old-copy retention before commit, replacement after reload, and unavailable-storage behavior. Vite and the NSIS desktop build succeeded. NSIS installer exited 0. NSIS size 13.10 MiB and resources 11.65 MiB meet budgets; the all-artifact size script flags an unrelated old MSI dated September 24, which was not rebuilt or installed.

Preservation: source, backend conversation state, and WebView local storage backed up under .agent_control/backups/storage-quota-20260928. Relevant files from the prior NAS checkpoint were pulled separately and matched pre-edit local files.

Follow-up found through the installed journey: paginated conversation history embedded full runtime snapshots in each assistant turn and exceeded the desktop bridge's 16 MiB response cap. get_conversation_page now projects dialogue and route/receipt metadata; raw get_turn results and durable records are untouched. The affected 35-turn conversation returns 1,600,378 bytes with identical content/detail for every turn. The installed app listed all 89 conversations and opened the previously unavailable conversation. A Node-driven production Python check verifies a >10 MB raw snapshot remains intact while its history projection retains full text and receipts.
