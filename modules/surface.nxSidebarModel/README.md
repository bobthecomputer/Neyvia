# nxSidebarModel

Provides DEFAULT_CLEANUP, CLI_BRANCH, cliBranch, basename for Neyvia's UI state and behavior.

- **Public API:** `CLI_BRANCH`, `DEFAULT_CLEANUP`, `agentStatus`, `agentSummary`, `basename`, `buildTree`, `childChatIds`, `cliBranch`, `isNeedsYou`, `kindOf`, `leafState`, `orderAgents`, `placeSession`, `shouldOfferTidy`, `staleCandidates`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [sidebar.cl](../../manuals/cl/sidebar.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-e.shell.agentSummary`, `proofs-e.shell.buildTree`, `proofs-e.shell.kindOf`, `proofs-e.shell.placeSession`, `proofs-e.shell.shouldOfferTidy`, `proofs-e.shell.staleCandidates`.
- **Dependencies:** [surface.nxProofsEShellContracts](../surface.nxProofsEShellContracts/README.md).
- **Owner:** Neyvia / nxSidebarModel.
- **Files:** [web/src/neyvia/next/nxSidebarModel.js](../../web/src/neyvia/next/nxSidebarModel.js).
