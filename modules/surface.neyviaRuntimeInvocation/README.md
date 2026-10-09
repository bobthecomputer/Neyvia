# neyviaRuntimeInvocation

Provides NEYVIA_RUNTIME_INVOCATION_SCHEMA, NEYVIA_INVOCATION_MODES, normalizeInvocationMode, invocationModeMeta for Neyvia's UI state and behavior.

- **Public API:** `NEYVIA_CONTEXT_SCOPES`, `NEYVIA_DELEGABLE_RESPONSIBILITIES`, `NEYVIA_INVOCATION_LIFECYCLE`, `NEYVIA_INVOCATION_MODES`, `NEYVIA_INVOCATION_PRESENTATIONS`, `NEYVIA_RESERVED_RESPONSIBILITIES`, `NEYVIA_RUNTIME_INVOCATION_COMMANDS`, `NEYVIA_RUNTIME_INVOCATION_SCHEMA`, `canTransitionInvocation`, `closeRuntimeInvocation`, `createRuntimeInvocation`, `describeEffectiveRuntimeComposition`, `emptyRuntimeInvocationRegistry`, `invocationModeMeta`, `invocationsOwnedBySession`, `isInvocationOpen`, `isInvocationResumable`, `normalizeContextScope`, `normalizeInvocationMode`, `normalizeInvocationPresentation`, `orphanedInvocations`, `partitionDelegation`, `recordRuntimeReturn`, `resolveRuntimeReadiness`, `responsibilityMeta`, `retainedResponsibilities`, `selectEcosystemOverrides`, `selectInlineInvocations`, `selectPrimaryRuntimeInvocation`, `transitionRuntimeInvocation`, `upsertRuntimeInvocation`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [surface.providerModelCatalog](../surface.providerModelCatalog/README.md).
- **Owner:** Neyvia / neyviaRuntimeInvocation.
- **Files:** [web/src/neyvia/neyviaRuntimeInvocation.js](../../web/src/neyvia/neyviaRuntimeInvocation.js).
