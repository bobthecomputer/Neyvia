CL 1.1
L rel-release-harness v1 -- Disposable release storage contracts; native rendered journeys are recorded separately
A release.observe(case:str) -> json -- Read facts from the real storage module with controlled IndexedDB fixtures
I release.observe reads:files writes:task-local-scratch
P verify(): release.observe("storage")
C rel-release-harness.verify storage-opens: release.observe("storage").successfulInitialization == true
C rel-release-harness.verify storage-hydrates: release.observe("storage").hydratedValue == "saved-db-value"
C rel-release-harness.verify storage-preserves-before-commit: release.observe("storage").legacyBeforeCommit == true
C rel-release-harness.verify storage-removes-after-commit: release.observe("storage").committedValue == true and release.observe("storage").legacyRemovedAfterCommit == true
C rel-release-harness.verify storage-timeout: release.observe("storage").timeoutUnavailable == true and release.observe("storage").durationMs >= 7000 and release.observe("storage").durationMs < 20000
C rel-release-harness.verify storage-timeout-retains: release.observe("storage").legacyRetained == true and release.observe("storage").warningReported == true
C rel-release-harness.verify storage-late-open: release.observe("storage").lateDatabaseClosed == true and release.observe("storage").lateHydrationIgnored == true
C rel-release-harness.verify image-fresh-empty: release.observe("storage").imageFreshEmpty == true
C rel-release-harness.verify image-owned-preserved: release.observe("storage").imageSavedPreserved == true
C rel-release-harness.verify image-empty-kept: release.observe("storage").imageEmptyStaysEmpty == true
M rel-release-harness "These fixtures prove module semantics, not a native browser database or remote server synchronization." src:authored-contract state:verified
