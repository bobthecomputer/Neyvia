CL 1.1
L taste-harness v1 -- Host-owned C13 context, budget, advisory and rendered-evidence contracts
A taste.observe(case:str) -> json -- read facts from disposable owned observers; no live model, no credentials; native render proof uses explicit owned ports
I taste.observe reads:files writes:task-local-scratch
P verify(): taste.observe("context"); taste.observe("prefix"); taste.observe("budget"); taste.observe("laya"); taste.observe("motion"); taste.observe("page-checks"); taste.observe("native-theme")
C taste-harness.verify context-owned-helper: taste.observe("context").ownedHelper == true -- block c13g-migration: preserve context owned-helper behavior
C taste-harness.verify context-isolated-section: taste.observe("context").unaffectedSectionExcluded == true -- block c13g-migration: preserve context isolated-section behavior
C taste-harness.verify context-descendants: taste.observe("context").descendantCount == 3 and taste.observe("context").allDescendants == true -- block c13g-migration: preserve context descendants behavior
C taste-harness.verify context-structural-ordinal: taste.observe("context").structuralOrdinal == true -- block c13g-migration: preserve context structural-ordinal behavior
C taste-harness.verify context-nested-helper: taste.observe("context").nestedHelper == true -- block c13g-migration: preserve context nested-helper behavior
C taste-harness.verify context-bounded-helper: taste.observe("context").sharedWindowChars < 6000 and taste.observe("context").targetedHelper == true -- block c13g-migration: preserve context bounded-helper behavior
C taste-harness.verify context-real-crops: taste.observe("context").cropCount == 4 and taste.observe("context").cropGeometry == true -- block c13g-migration: preserve context real-crops behavior
C taste-harness.verify context-cached-anchor: taste.observe("context").anchorImages == 1 and taste.observe("context").anchorResolution <= 480 -- block c13g-migration: preserve context cached-anchor behavior
C taste-harness.verify context-failures-only: taste.observe("context").failuresOnly == true -- block c13g-migration: preserve context failures-only behavior
C taste-harness.verify context-unknown-geometry: taste.observe("context").unknownGeometryRefused == true -- block c13g-migration: preserve context unknown-geometry behavior
C taste-harness.verify context-bounded-prompt: taste.observe("context").immutableRetained == true and taste.observe("context").rawArchived == true and taste.observe("context").promptTokens <= 400 -- block c13g-migration: preserve context bounded-prompt behavior
C taste-harness.verify context-oversize-refusal: taste.observe("context").oversizeRefused == true -- block c13g-migration: preserve context oversize-refusal behavior
C taste-harness.verify context-changed-code: taste.observe("context").changedSourceExact == true -- block c13g-migration: preserve context changed-code behavior
C taste-harness.verify prefix-brief-isolation: taste.observe("prefix").briefIsolation == true -- block c13g-migration: preserve prefix brief-isolation behavior
C taste-harness.verify prefix-rubric-checks: taste.observe("prefix").rubricAndChecks == true -- block c13g-migration: preserve prefix rubric-checks behavior
C taste-harness.verify prefix-stock-list: taste.observe("prefix").stockProjected == true -- block c13g-migration: preserve prefix stock-list behavior
C taste-harness.verify prefix-plain-voice: taste.observe("prefix").voiceProjected == true -- block c13g-migration: preserve prefix plain-voice behavior
C taste-harness.verify prefix-motion-case: taste.observe("prefix").motionProjected == true -- block c13g-migration: preserve prefix motion-case behavior
C taste-harness.verify prefix-worked-crops: taste.observe("prefix").cropCount >= 9 and taste.observe("prefix").cropBounds == true -- block c13g-migration: preserve prefix worked-crops behavior
C taste-harness.verify prefix-worked-decisions: taste.observe("prefix").caseFields == true -- block c13g-migration: preserve prefix worked-decisions behavior
C taste-harness.verify prefix-no-quantity-proxy: taste.observe("prefix").quantityProxiesAbsent == true -- block c13g-migration: preserve prefix no-quantity-proxy behavior
C taste-harness.verify budget-round-limit: taste.observe("budget").roundLimit == true -- block c13g-migration: preserve budget round-limit behavior
C taste-harness.verify budget-call-limit: taste.observe("budget").callLimit == true -- block c13g-migration: preserve budget call-limit behavior
C taste-harness.verify budget-overrun-stop: taste.observe("budget").overrunClosed == true -- block c13g-migration: preserve budget overrun-stop behavior
C taste-harness.verify budget-usage-counter: taste.observe("budget").totalTokens == 240 and taste.observe("budget").cachedTokens == 120 and taste.observe("budget").usageComplete == true -- block c13g-migration: preserve budget usage-counter behavior
C taste-harness.verify budget-capacity-only-zero: taste.observe("budget").strictCapacity == true -- block c13g-migration: preserve budget capacity-only-zero behavior
C taste-harness.verify budget-searched-draft: taste.observe("budget").searchedDraftReservation > 97688 -- block c13g-migration: preserve budget searched-draft behavior
C taste-harness.verify budget-fixed-envelope: taste.observe("budget").fixedEnvelopeReservation > 80000 -- block c13g-migration: preserve budget fixed-envelope behavior
C taste-harness.verify budget-explicit-sol: taste.observe("budget").solDispatch == true and taste.observe("budget").solCost == 0.000286 -- block c13g-migration: preserve budget explicit-sol behavior
C taste-harness.verify budget-hidden-skills: taste.observe("budget").hiddenSkillsDisabled == true -- block c13g-migration: preserve budget hidden-skills behavior
C taste-harness.verify budget-prior-receipts: taste.observe("budget").priorPreserved == true -- block c13g-migration: preserve budget prior-receipts behavior
C taste-harness.verify budget-capacity-retry: taste.observe("budget").capacityFree == true and taste.observe("budget").retryCalls == 2 -- block c13g-migration: preserve budget capacity-retry behavior
C taste-harness.verify budget-missing-usage: taste.observe("budget").missingUsageClosed == true -- block c13g-migration: preserve budget missing-usage behavior
C taste-harness.verify budget-failed-receipts: taste.observe("budget").failedPreserved == true -- block c13g-migration: preserve budget failed-receipts behavior
C taste-harness.verify budget-malformed-usage: taste.observe("budget").malformedUsageRefused == true -- block c13g-migration: preserve budget malformed-usage behavior
C taste-harness.verify laya-typed-answer: taste.observe("laya").answer == "B" -- block c13g-migration: preserve laya typed-answer behavior
C taste-harness.verify laya-low-confidence: taste.observe("laya").escalated == "escalate" -- block c13g-migration: preserve laya low-confidence behavior
C taste-harness.verify laya-port-boundary: taste.observe("laya").outOfScopeRefused == "unavailable" -- block c13g-migration: preserve laya port-boundary behavior
C taste-harness.verify laya-deterministic-block: taste.observe("laya").blockingCannotBeWaived == true -- block c13g-migration: preserve laya deterministic-block behavior
C taste-harness.verify laya-no-savings-proxy: taste.observe("laya").noClaimedSavings == true -- block c13g-migration: preserve laya no-savings-proxy behavior
C taste-harness.verify motion-observed-motion: taste.observe("motion").positiveObserved == true -- block c13g-migration: preserve motion observed-motion behavior
C taste-harness.verify motion-reduced-negative: taste.observe("motion").movingReducedRejected == true -- block c13g-migration: preserve motion reduced-negative behavior
C taste-harness.verify motion-missing-evidence: taste.observe("motion").missingObservationsRejected == true -- block c13g-migration: preserve motion missing-evidence behavior
C taste-harness.verify motion-ordered-frames: taste.observe("motion").orderedSheets == 3 and taste.observe("motion").orderedFrames == true -- block c13g-migration: preserve motion ordered-frames behavior
C taste-harness.verify motion-owned-engine: taste.observe("motion").engine == "obscura" -- block c13g-migration: preserve motion owned-engine behavior
C taste-harness.verify page-checks-ignoredDark: taste.observe("page-checks").ignoredDark == true -- block c13g-migration: preserve page-checks ignoredDark behavior
C taste-harness.verify page-checks-invalidRender: taste.observe("page-checks").invalidRender == true -- block c13g-migration: preserve page-checks invalidRender behavior
C taste-harness.verify page-checks-voidColumns: taste.observe("page-checks").voidColumns == true -- block c13g-migration: preserve page-checks voidColumns behavior
C taste-harness.verify page-checks-voidLocations: taste.observe("page-checks").voidLocations == true -- block c13g-migration: preserve page-checks voidLocations behavior
C taste-harness.verify page-checks-dashes: taste.observe("page-checks").dashes == true -- block c13g-migration: preserve page-checks dashes behavior
C taste-harness.verify page-checks-stock: taste.observe("page-checks").stock == true -- block c13g-migration: preserve page-checks stock behavior
C taste-harness.verify page-checks-metaphorWarnings: taste.observe("page-checks").metaphorWarnings == true -- block c13g-migration: preserve page-checks metaphorWarnings behavior
C taste-harness.verify page-checks-repairableChecks: taste.observe("page-checks").repairableChecks == true -- block c13g-migration: preserve page-checks repairableChecks behavior
C taste-harness.verify page-checks-earlyFailures: taste.observe("page-checks").earlyFailures == true -- block c13g-migration: preserve page-checks earlyFailures behavior
C taste-harness.verify page-checks-anchorNegative: taste.observe("page-checks").anchorNegative == true -- block c13g-migration: preserve page-checks anchorNegative behavior
C taste-harness.verify page-checks-anchorDarkInvalid: taste.observe("page-checks").anchorDarkInvalid == true -- block c13g-migration: preserve page-checks anchorDarkInvalid behavior
C taste-harness.verify page-checks-r8Negative: taste.observe("page-checks").r8Negative == true -- block c13g-migration: preserve page-checks r8Negative behavior
C taste-harness.verify page-checks-claudeVoidNegative: taste.observe("page-checks").claudeVoidNegative == true -- block c13g-migration: preserve page-checks claudeVoidNegative behavior
C taste-harness.verify page-checks-lunaVoidPositive: taste.observe("page-checks").lunaVoidPositive == true -- block c13g-migration: preserve page-checks lunaVoidPositive behavior
C taste-harness.verify page-checks-noThemeDefect: taste.observe("page-checks").noThemeDefect == true -- block c13g-migration: preserve page-checks noThemeDefect behavior
C taste-harness.verify page-checks-rendererDefect: taste.observe("page-checks").rendererDefect == true -- block c13g-migration: preserve page-checks rendererDefect behavior
C taste-harness.verify page-checks-genuineDarkAccepted: taste.observe("page-checks").genuineDarkAccepted == true -- block c13g-migration: preserve page-checks genuineDarkAccepted behavior
C taste-harness.verify page-checks-missingDarkRefused: taste.observe("page-checks").missingDarkRefused == true -- block c13g-migration: preserve page-checks missingDarkRefused behavior
C taste-harness.verify page-checks-historical-observations: taste.observe("page-checks").historicalBlocks == 8 -- block c13g-migration: preserve page-checks historical-observations behavior
C taste-harness.verify native-theme-native-contexts: taste.observe("native-theme").nativeContexts == 2 -- block c13g-migration: preserve native-theme native-contexts behavior
C taste-harness.verify native-theme-native-light: taste.observe("native-theme").light == true -- block c13g-migration: preserve native-theme native-light behavior
C taste-harness.verify native-theme-native-dark: taste.observe("native-theme").dark == true -- block c13g-migration: preserve native-theme native-dark behavior
F Controlled transport proves dispatch and accounting, never live provider execution or page quality; fresh arms retain real provider receipts.
M taste-harness "Converted five added test files to executable contract checks, per Paul 5 Oct 2026" src:lead-message state:verified
C taste-harness.verify context-citation-label: taste.observe("context").citationLabel == true -- block c13g: a DOI link label is not a bibliographic title; use the visible cited title
C taste-harness.verify context-qualified-ordinal: taste.observe("context").qualifiedOrdinal == true -- block c13g: descendant ordinal selects only the actual owning article
C taste-harness.verify laya-outcome-order: taste.observe("laya").outcomeOrder == true -- block c13g: all advice outcomes remain visible in their decision ledger

C taste-harness.verify context-scoped-failures: taste.observe("context").scopedFailures == true -- block c13g: repair driver excludes unrelated controls
C taste-harness.verify context-unresolved-refusal: taste.observe("context").unresolvedRefused == true -- block c13g: shared styles cannot validate an unresolved selector

C taste-harness.verify prefix-action-enum: taste.observe("prefix").actionEnumGuidance == true -- block c13g: generator and repair instructions declare exact driver enum, not prose

C taste-harness.verify context-duplicate-replacement: taste.observe("context").duplicateReplacement == true -- block c13g: exact attested offsets resolve repeated replacement text without broadening source authority

C taste-harness.verify motion-geometry-summary: taste.observe("motion").geometrySummary == true -- block c13g: overlapping SVG node lists project readable names and details

C taste-harness.verify motion-straight-connectors: taste.observe("motion").straightConnectors == true -- block c13g: actual Obscura root mapping accepts aligned endpoints and catches both deliberately displaced endpoints

C taste-harness.verify motion-native-font-geometry: taste.observe("motion").nativeFontGeometry == true -- block c13g: actual rendered font advances accept the fitted SVG label and reject the narrow node
C taste-harness.verify motion-measured-projection: taste.observe("motion").measuredProjection == true -- block c13g: critic and repair receive actual diagram dimensions, not just label names
