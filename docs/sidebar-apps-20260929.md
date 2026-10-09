# Chat apps and host identity

The conversation sidebar now filters Neyvia, Codex, Claude Code, and OpenCode. App icons accompany external chat titles and the host name stays visible beside the device icon. Less-used destinations are under **Spaces & settings**, leaving room for the chat list. The same controls are available in the phone conversation drawer.

External history is read from the connected backend host's own local stores. Namespaced IDs include the app and host; they are never sent to Neyvia's delete/archive endpoints. Opening a row shows saved messages in a read-only dialog. This does not import the thread or continue it in a different harness, and does not aggregate disconnected computers. Connect to the desired host to inspect its stores.

Codex uses its SQLite index and stored names, handles Windows extended paths, and does not trust the stale `has_user_event` flag as evidence that a conversation is empty. Claude Code reads its project transcripts/index; OpenCode uses read-only SQLite. Transcript excerpts have explicit truncation labels. Private reasoning channels and tool payloads are omitted. File paths are resolved from discovered IDs rather than accepted from requests.

## Claude connection

**Settings → Runtimes & Rooms → Harness Control → Provider connections** includes an opt-in **Hermes / Claude Max** connection. It delegates OAuth to the installed Hermes CLI. The UI explains the documented Max plus purchased extra-usage requirement before connection; see [the connection notes](NEYVIA_HERMES_CLAUDE_SUBSCRIPTION.md). The existing Claude Code and API-key routes are unchanged. Authentication and a paid model turn were not performed during this change.

## Verification

- `node scripts/check_external_chat_inventory.mjs`: three source adapters, query filtering, read-only store hashes, private-channel omission, optional OpenCode columns, Codex named desktop sessions with stale user-event metadata and extended Windows paths.
- Actual browser: filtered each app; opened real OpenCode, Codex (237 displayed messages), and Claude Code (36 displayed messages) transcripts; title search returned the expected Codex chat; modal close returned to the list.
- Desktop and 390 × 844 phone layout inspected. No horizontal overflow on the checked transcript journey. Chrome was unavailable, so the in-app browser was used.
- Provider setup showed the new opt-in connection. Hermes launch routing was checked with the process runner stubbed, without a paid inference or login.
- Frontend, desktop executable, and NSIS installer built locally. The installed/running application and public services were not replaced or restarted.

The live verification preview uses ports 1427/47883. The existing controller on 47881 was left running. Screenshots remain local under `proof/sidebar-apps-20260929`.
