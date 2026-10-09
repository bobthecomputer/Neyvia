# neyviaAttentionInbox

Provides NEYVIA_ATTENTION_INBOX_SCHEMA, NEYVIA_ATTENTION_STATES, NEYVIA_ATTENTION_PRIORITY_STATES, attentionStateMeta for Neyvia's UI state and behavior.

- **Public API:** `NEYVIA_ATTENTION_COMMANDS`, `NEYVIA_ATTENTION_FILTERS`, `NEYVIA_ATTENTION_INBOX_SCHEMA`, `NEYVIA_ATTENTION_PRIORITY_STATES`, `NEYVIA_ATTENTION_REASONS`, `NEYVIA_ATTENTION_STATES`, `attentionActivityTier`, `attentionFilterMeta`, `attentionReasonMeta`, `attentionStateMeta`, `attentionThreadDescription`, `buildAttentionInbox`, `compareAttentionThreads`, `comparePriorityThreads`, `compareRecentThreads`, `filterInboxGroups`, `groupThreadsByProject`, `isBlockingReason`, `normalizeAttentionState`, `projectAttentionSections`, `projectAttentionThread`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `attention.activity`, `attention.description`, `attention.filter`, `attention.inbox`, `attention.projects`, `attention.recent`, `attention.sections`, `attention.thread`.
- **Dependencies:** [surface.neyviaFrontendContracts](../surface.neyviaFrontendContracts/README.md).
- **Owner:** Neyvia / neyviaAttentionInbox.
- **Files:** [web/src/neyvia/neyviaAttentionInbox.js](../../web/src/neyvia/neyviaAttentionInbox.js).
