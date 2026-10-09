CL 1.1
-- Owner interpreter metadata is prepared at authenticated bootstrap; no action runs.
-- MODREL first-turn contract: await bootstrap registration before reporting session start;
-- recover missing registrations at prompt.context; discovery tools are explicitly nondeferred.
-- Pending/empty MCP servers do not describe mod tool readiness. Five fresh real Haiku 5.5
-- first turns must each receive a successful Neyvia tool result; retain paired transcripts.
L claude-mod-awareness v1 -- Cold Claude Code workspace awareness through the real Neyvia mod, Haiku 5.5 low
A awareness.observe() -> json -- Read the authenticated mod snapshots, run records and real Claude transcript receipt
I awareness.observe reads:task-local-receipts
P verify(): awareness.observe()
C claude-mod-awareness.verify cold-question: awareness.observe().coldQuestion == true
C claude-mod-awareness.verify correct-model: awareness.observe().haikuLow == true
C claude-mod-awareness.verify discovery: awareness.observe().usedToolSearch == true
C claude-mod-awareness.verify native-activity: awareness.observe().calledActivity == true
C claude-mod-awareness.verify names-both: awareness.observe().namedBoth == true
C claude-mod-awareness.verify concurrent: awareness.observe().twoRunningDuringAnswer == true
C claude-mod-awareness.verify live-context: awareness.observe().liveContextNamesBoth == true
C claude-mod-awareness.verify bounded: awareness.observe().liveContextCharacters <= 600
C claude-mod-awareness.verify millisecond-hooks: awareness.observe().hotP95Ms < 200
C claude-mod-awareness.verify empty-omitted: awareness.observe().emptyOmitted == true
C claude-mod-awareness.verify stale-omitted: awareness.observe().staleOmitted == true
C claude-mod-awareness.verify no-duplicate: awareness.observe().liveOccursOnce == true
C claude-mod-awareness.verify refused-omitted: awareness.observe().refusedOmitted == true
C claude-mod-awareness.verify nightshift-state: awareness.observe().nightShiftReported == true
C claude-mod-awareness.verify mounted-apps: awareness.observe().openAppsReported == true
C claude-mod-awareness.verify token-accounting: awareness.observe().recordedFirstRequestTokens == true
M claude-mod-awareness "The executable receipt reader is D:/NeyviaRuns/29-MODAWARE/verify.mjs; raw transcripts and API observations remain alongside its receipt. This proves the local mod route and model turn, not public release." src:authored-contract state:verified
