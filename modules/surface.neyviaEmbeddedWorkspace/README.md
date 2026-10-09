# neyviaEmbeddedWorkspace

Provides NEYVIA_EMBEDDED_WORKSPACE_SCHEMA, NEYVIA_EMBED_PRESENTATIONS, normalizeEmbedPresentation, embedPresentationMeta for Neyvia's UI state and behavior.

- **Public API:** `NEYVIA_EMBEDDED_WORKSPACE_SCHEMA`, `NEYVIA_EMBED_PRESENTATIONS`, `NEYVIA_EMBED_STATES`, `adapterForArtifact`, `closeEmbeddedWorkspace`, `closeWorkspacesForSession`, `collapseEmbeddedWorkspace`, `createEmbeddedWorkspace`, `createEmbeddedWorkspaceHost`, `embedPresentationMeta`, `embeddedAdapter`, `embeddedInteractionEvent`, `embeddedWorkspaceIdentity`, `expandEmbeddedWorkspace`, `findEquivalentWorkspace`, `focusEmbeddedWorkspace`, `fullscreenEmbeddedWorkspace`, `isEmbedRetained`, `normalizeEmbedPresentation`, `openEmbeddedWorkspace`, `pruneClosedWorkspaces`, `registerEmbeddedAdapter`, `registeredEmbeddedAdapters`, `restoreEmbeddedWorkspace`, `shouldMountEmbeddedWorkspace`, `visibleEmbeddedWorkspaces`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `embed.close`, `embed.collapse`, `embed.expand`, `embed.focus`, `embed.fullscreen`, `embed.host`, `embed.mount`, `embed.open`, `embed.restore`, `embed.visible`.
- **Dependencies:** [surface.neyviaPresentationContracts](../surface.neyviaPresentationContracts/README.md).
- **Owner:** Neyvia / neyviaEmbeddedWorkspace.
- **Files:** [web/src/neyvia/neyviaEmbeddedWorkspace.js](../../web/src/neyvia/neyviaEmbeddedWorkspace.js).
