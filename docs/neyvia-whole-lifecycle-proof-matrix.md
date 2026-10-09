# Neyvia whole-lifecycle proof matrix

This matrix is the durable implementation ledger for the Whole-Lifecycle and Blind-Spot product contract. It is intentionally stricter than screenshots or component presence: **implemented** means a backend/UI contract exists, while **proven** requires failure injection or a real user journey. Unknown areas remain **unverified** rather than being inferred from copy.

Current implementation baseline for this matrix: `main` at `233a0d34201600e1538d21985db2d625f3799996` (2026-09-01), the squash merge of PR #45. PR #45 removed the retired self-mutating Native publication workflows and replaced them with a read-only publication-integrity audit. That baseline includes PR #44's canonical paired-device command plane (`a92a0843c27c721d34536ebd6c508446d9f81a56`), PR #42's adaptive domain-to-Chat experience bridge (`979d88a9b4b4bedbfab96aed1eab5019c729b077`), the Cryptography 50 compatibility/security maintenance from PR #5 (`a249e396351ea44364552a68fce1528302148f08`), the Harness execution-capacity baseline from PR #39 (`4daed33c5dd937e466ec8633d8cf286eb558aa58`), and its proof publication from PR #40 (`40ef35cf3d19a8c1b16a0b59b6b4d722677172a0`). These are scoped controls, not whole-product proof.

The provider-auth transaction hardening remains part of the baseline: PR #37 (`63bd1c51c3008e1bffd573ffced0616742523da8`) anchored provider queue/guard/credential I/O to retained control-directory transactions, hardened Windows leaf opens/reparse-point handling, made malformed/future credential evidence fail closed, refreshed cross-process cache ownership, and closed the same-process BSD/macOS advisory-lock gap. Its scoped cross-platform evidence remains valid; it does not prove real mid-run provider-expiry recovery.

The paired-device deadline candidate associated with PR #46 extends PR #44 without replacing its authority model: command TTL is the outer claim deadline, claimed expiry becomes outcome-uncertain rather than replayable, and only the exact authenticated claim receipt may reconcile explicitly receipt-resolvable uncertainty. Hosted run `33542722207` passed 20 focused pairing/command/RPC tests on the implementation/test candidate `802b6c51e39dde8d87b13852309bf4a53a3c8138`; publication-integrity run `33542722232` also passed. This does not claim native Android/iOS execution or a physical-phone end-to-end proof.

## Implementation / proof matrix

| concern | current contract | evidence / recovery | status | remaining limitation |
| --- | --- | --- | --- | --- |
| Lifecycle / duplicate execution | Queued launch is single-flight. Blocked/interrupted remain explicit. A worker waiting for execution capacity stays lifecycle `running`, owns its PID, persists `waitingReason=execution-capacity`, and cannot be started again. Paired-device commands are separately idempotent and single-claim; a potentially executed command whose receipt is missing becomes `uncertain` rather than automatically replaying. | Start/cancel, lock recovery, blocked lifecycle, admission, execution-capacity and duplicate-start regressions. Paired-device claim loss, command expiry and idempotency failure injection run beside the existing Harness lifecycle tests. | **Partial, materially strengthened** | Harness pause/resume, in-place adoption/retry, force-stop and a complete parent/child ownership state machine remain incomplete. Device commands still lack full human-approval/run-identity binding. |
| Cancellation propagation | Atomic launch/cancel claim; verified process-tree stop; late completion cannot overwrite cancellation; blocked cleanup does not fabricate a process stop. Capacity waiting does not reopen launch admission. Device command expiry bounds claim authority; missing receipts do not become implicit retries. | Start-vs-cancel, runtime-budget/cancel, blocked-cleanup and capacity-wait transitions are injected. Device deadline and late-receipt reconciliation are separately injected. | **Partial** | Ports, connector leases, reservations and other non-process resources still lack complete ownership/cleanup receipts; genuine multi-child survival proof and explicit device-command cancel-before-claim remain pending. |
| Crash / disconnection recovery | Harness locks and execution slots are crash-released at the OS boundary; Native checkpoint restore journals before-image/transaction state; provider-auth durable operations retain anchored transaction state. Claimed device commands that lose a receipt are preserved as uncertain and never replayed automatically. | Orphan/PID-reuse/dead-owner, checkpoint crash/conflict, provider-auth redirection/malformed evidence, execution-slot recovery, device claim-loss and late-receipt regressions. Unknown/unreadable active work fails closed rather than being assumed dead/free. | **Partial, materially strengthened** | Whole-agent adoption, split-brain handling, external-resource restoration, NAS crash proof, real provider-expiry recovery and physical mobile disconnect/reconnect proof remain unverified. |
| Resources / cost | `maxRuntimeSeconds` is a hard wall-clock budget. `NEYVIA_MAX_OPEN_HARNESS_JOBS` bounds durable non-terminal work. PR #39 adds separate `NEYVIA_MAX_RUNNING_HARNESS_JOBS` execution concurrency (default 4), persisted with monotonic tightening. Device command TTL is now an outer authorization deadline for a claim. | Runtime-budget expiry; concurrent open-run admission; FIFO execution-capacity tests; mixed-version/unknown fail-closed accounting; late-legacy oversubscription regression; device claim deadline capping. Waiting time remains inside the Harness wall-clock budget. | **Partial, materially strengthened** | No token/spend/provider quota, CPU/GPU/RAM/disk hard allocation, global scheduler, priority/preemption, complete policy-editor/raise workflow, or global device-command admission budget. |
| Security / secrets | Provider-auth durable state rejects corrupt/future/malformed/noncanonical/link/reparse-point evidence; operations are anchored to control-directory handles; credential values remain typed/string-only; support bundle is allowlist-first and redacted. Windows Harness PID liveness fails closed on indeterminate process-open errors. Paired-device command arguments/results reject credential/secret-shaped fields; device credentials are authenticated and never emitted in command receipts. PR #5 permits the Cryptography 50.x security-fixed line. | Provider-auth run `33502600259`; execution-capacity run `33509573463`; support-export privacy injections; Windows liveness regressions; Cryptography 50 run `33515334063`; paired-device command safety run `33542722207`. | **Partial, materially strengthened** | Credential presence is not health; secure-store provenance/revocation, broader permission policy, NAS/adversarial-kernel proof, native keystore proof and the separately observed high-severity npm audit finding require separate work. |
| Connectors / harnesses | Installed/configured/authenticated/compatible/healthy/executing remain distinct. Provider-flow startup is durable/single-flight. Harness execution waiting is distinct from active provider/model execution. Paired devices advertise explicit capabilities instead of NEYVIA inferring them. | Provider-auth component/adjacent tests, Harness execution-capacity/UI contracts, authenticated device capability/claim/receipt tests. | **Partial** | Continuous provider health, real token-expiry pause/re-auth/resume, callback-to-operation binding, Codex/Hermes credential ownership isolation, signed native transport and live genuine mobile execution remain incomplete. |
| Update safety | Update-required/incompatible/rollback must derive from evidence rather than optimistic state. | No new update-system proof this cycle. | **Unverified** | Active-run pinning, canary, rollback, revocation and mixed-version migration proof required. |
| Ownership / portability | Native checkpoints are content-addressed/workspace-bounded with durable restore journals; unresolved/future Harness/provider evidence is preserved rather than silently pruned/migrated; support ZIP is diagnostic evidence only. | Checkpoint corruption/apply/startup/conflict injections; future-schema retention; support-export privacy tests. | **Partial** | Full session/project export, deletion, import, backup, retention-policy migration and artifact/model provenance remain unverified. |
| Agent Live semantics | Dialogue/delegation/CLI/tools/approvals/process/artifacts/warnings/receipts remain semantically distinct. UI renders blocked as attention-required and capacity wait as **waiting for capacity**, explicitly saying no execution slot is claimed. Device `queued`/`claimed` states are control-plane truth only; `executionProven` requires an authenticated succeeded receipt. | Blocked UI/source contracts, `tests/test_harness_execution_capacity_ui_contract.py`, backend durable receipt tests and paired-device receipt truth tests. | **Partial, strengthened** | Parent/child lineage, in-place resume, real large-agent-count streaming, actor/session/run binding for mobile actions and complete semantic event proof remain incomplete. |
| Offline / degraded / mobile | Disconnected/recovering/restored must come from live evidence. PR #44 adds a durable authenticated paired-device queue with explicit capability declarations, idempotency, single-flight claims, revocation handling and `uncertain` outcome semantics. PR #46's deadline candidate prevents a claim lease from outliving command authority. | Device claim-loss, command-expiry, capability-withdrawal, revocation and late-receipt failure injection; no automatic replay after potentially executed side effects. | **Partial, materially strengthened** | No signed native transport, Android Accessibility/iOS App Intent execution proof, push delivery, stale-client UI/deep-link journey, secure-keystore proof, background entitlement proof or physical-phone E2E yet. |
| Collaboration | Narrow checkpoint conflict handling and provider-session ownership exist. | Third-state checkpoint edits and provider-auth conflicting-observer/late-completion regressions. | **Partial, narrow** | Simultaneous edits, handoff, locks, actor attribution, approvals and multi-operator auth ownership remain incomplete. |
| Accessibility / i18n | Blocked/capacity states have meaningful text/ARIA-derived status rather than color-only meaning. | Capacity label participates in Harness item `aria-label`; source contract exercised in focused test target. | **Partial, narrow** | Full keyboard, screen-reader, focus, reduced-motion, scaling, locale resilience and mobile assistive-tech journeys remain unverified. |
| Diagnosis / support | `neyvia.support_bundle.v1` emits bounded allowlisted diagnostic JSON; blocker and cleanup attribution remain durable; unsafe export fails closed before ZIP publication. Device command receipts retain explicit error/status truth rather than synthesizing completion. | 7 focused support-bundle privacy/path/size injections plus lifecycle/device receipt tests. | **Partial** | One-click repair/export, pre-share viewer, automatic support upload and richer provider/connector/mobile classification remain incomplete. |
| Marketplace / SDK | Trust must not be inferred from popularity or installability. | Cryptography 50 exploratory validation exposed stale OCI test-fixture ownership data before the cryptographic verification boundary; production publisher-ownership validation was not weakened. | **Unverified** | Signing, publisher identity, semantic migrations, fixture maintenance, permission declarations and revocation require proof. Seven current OCI tests use fixture IDs that no longer satisfy publisher ownership and need a separate evidence-quality repair. |
| Performance / scale | Open-run admission and expensive execution are now bounded separately; support/provider reads are bounded; checkpoints are bounded; capacity pressure expands state only when relevant. Device claim leases are bounded by both lease policy and command TTL. | Cross-platform execution-capacity failure-injection target; concurrent admission tests; runtime-budget/bounded-input regressions; paired-device deadline test. | **Partial, materially strengthened** | No large-agent/slow-provider/constrained-host benchmark, global scheduling, priority/preemption, sustained long-session proof or mobile fleet/load benchmark. |
| Release / publication integrity | Editable/candidate/merged/current/public are distinct states. PR #45 removed 11 retired workflow entry points, including self-mutating Native publication machinery, and added a permanent read-only fail-closed workflow audit. New paired-device safety validation is also read-only. | PR #45 exact candidate and post-merge publication-integrity evidence; PR #46 implementation candidate publication-integrity run `33542722232` passed with the new workflow present. | **Partial, materially strengthened** | This is not full-repository CI, branch/ruleset proof, artifact attestation, rollback proof or current/public served-state proof. Detection of every conceivable future mutation spelling is not claimed. |

## End-to-end journey ledger

`Partial` means component-level or narrower proof, not full-product completion.

| # | journey | status | current evidence / next proof |
| ---: | --- | --- | --- |
| 1 | First-time harness + dependency installation | Unverified | Genuine missing dependency → safe install/repair → authenticated health still required. |
| 2 | Select harness/provider/model/project/permissions/budget | **Partial, strengthened** | Routes, hard wall-clock budget, durable open-run cap and separate running-execution cap exist; permission scope and broader budgets remain. |
| 3 | Start real session + observe real CLI and Agent Live | Partial | Historical receipts exist; repeat on current merged baseline with semantic stream separation and real execution. |
| 4 | Spawn multiple child agents + trace lineage | Unverified | Real child-agent/process-tree lineage proof required. |
| 5 | Cancel parent while child processes active | Partial | Atomic start/cancel + process-tree stop race-tested; genuine multi-child/non-process cleanup required. |
| 6 | Provider auth expires mid-run | Unverified | PR #37 makes durable auth state substantially safer but does not prove expiry recovery. Inject a real expiry/401, bind it to exact provider/account/run, block/pause safely, re-auth/refresh, then prove no duplicate side effect on resume/retry. |
| 7 | Neyvia closes/reopens while run continues | Partial | Detached worker/runtime budget survives client/backend closure; full UI/state restoration remains unverified. |
| 8 | Harness/CLI crash, orphan detection, checkpoint recovery | **Partial, strengthened** | Dead-worker reconciliation, crash-safe locks, crash-released execution slots and Native checkpoint recovery exist; whole-agent adoption/external resources remain unverified. |
| 9 | Resource/spending budget exhaustion | **Partial, materially strengthened** | Runtime exhaustion, open-run backpressure and separate running-execution backpressure are injected; token/cost/CPU/GPU/RAM/disk/per-agent exhaustion remains unverified. |
| 10 | Offline then reconnect | **Partial, narrow** | Paired-device claim loss is preserved as uncertain with no replay; stale mobile UI/network reconnection and a real device journey remain unverified. |
| 11 | Incompatible update rejected + rollback | Unverified | Canary/pinning/rollback journey required. |
| 12 | Unsigned/revoked/over-permissioned connector blocked | Unverified | Trust-policy failure injection required. |
| 13 | Mobile approval opens exact affected run | Unverified | The paired-device command foundation now exists, but approval/actor/session/run binding and exact deep-link proof are still required. |
| 14 | Export/delete/import/backup/restore | Unverified | Diagnostic support export and checkpoint restore are not complete portability proof. |
| 15 | Full keyboard + screen reader | Unverified | Full top-level and recovery journey required. |
| 16 | Empty/loading/success/blocked/degraded/error/disabled/hover/focus/active/disconnected/recovering/restored | Partial | Blocked, capacity-wait and device uncertain states are explicit in their owning contracts; degraded/disconnected/recovering/restored UI and assistive-tech browser proof remain pending. |
| 17 | Narrow phone/laptop/large monitor/long content/large-agent-count | Partial | Historical responsive evidence covers subsets; current physical-phone and large-agent/long-session stress remain pending. |

## Paired-device command deadline contract

PR #46's candidate extends the canonical PR #44 device command plane only for the scoped lifecycle contract below; it does not upgrade native mobile execution or mobile approval journeys to proven.

1. The command TTL is the outer authorization deadline. A new claim lease is capped at `min(now + lease, command.expiresAt)`.
2. Queued expiry remains terminal `expired` and is never handed to a device.
3. A command already claimed when its command deadline passes becomes `uncertain` with `command-expired-after-claim`; this is not success, failure or permission to retry.
4. The same reconciliation safely repairs legacy/pre-fix claimed rows whose claim lease was stored beyond command expiry.
5. Automatic retry remains false for potentially executed claimed side effects.
6. An exact authenticated late receipt may reconcile only `claim-lost`, `command-expired-after-claim`, or `capability-withdrawn-after-claim`, and only with the original claim ID. Mismatched or unrelated terminal state remains immutable.
7. Capability withdrawal before claim rejects queued work. After claim it remains uncertain until the matching authenticated device reports what happened.
8. Device revocation remains fail-closed: revoked credentials cannot use this completion path.
9. Run `33542722207` passed 20 focused pairing/device-command/RPC tests and source compilation on Ubuntu 24.04 / Python 3.12.14 with read-only token permissions; `git diff --check` passed.
10. Publication-integrity run `33542722232` passed on the same implementation/test head, proving the permanent device safety workflow does not reintroduce retired source-mutating workflow behavior under the existing audit.
11. This evidence does not claim Android Accessibility execution, iOS App Intents, push/background delivery, secure native keystore behavior, physical-phone E2E, human approval/run attribution, full-repository CI, Windows/macOS command-path proof or current/public served deployment.

Cycle proof and limitations: `proof/20260901-device-command-expiry-truth/README.md`.

## Merged contract: bounded Harness execution capacity

PR #39 is merged only for the scoped contract below; none of these statements upgrades complete resource governance or whole-product journeys to proven.

1. Open-run admission and expensive execution concurrency are separate system responsibilities.
2. `NEYVIA_MAX_RUNNING_HARNESS_JOBS` is explicit, at least 1, bounded by the durable Harness ceiling, and defaults to 4.
3. The effective workspace execution policy persists with monotonic tightening; differently configured same-version processes cannot silently raise a stricter policy.
4. Current-version waiters dispatch FIFO.
5. OS advisory slot locks are the execution-ownership authority. Durable slot metadata is evidence, not ownership; a process crash releases the lock at the OS boundary.
6. Unreadable durable work and mixed/older-version running work consume capacity conservatively rather than becoming permission to oversubscribe.
7. Active current-version slot locks are counted while dispatch is serialized, including the late-legacy-worker case that could otherwise oversubscribe the remaining slot.
8. A capacity-waiting detached worker remains `running` with its PID and `waitingReason=execution-capacity`; retrying `.start()` cannot spawn a duplicate worker.
9. The UI labels this state **waiting for capacity** and states that no provider/model execution slot is claimed yet.
10. The existing hard wall-clock runtime budget includes time waiting for an execution slot.
11. Windows process liveness uses non-destructive `OpenProcess(SYNCHRONIZE)` plus zero-time `WaitForSingleObject`; access-denied/indeterminate probes fail closed as live rather than releasing ownership on a guess.
12. Run `33509573463` passed the exact candidate on Ubuntu (76 passed/3 skipped), macOS (76/3) and Windows (79 passed), with per-platform `git diff --check` and secret-diff gates. The publish job recreated the current-main-integrated source, reran 76/3, built the production frontend successfully, inspected the exact diff and published `cbe80d346911ff9af381aea3d256db1e7c3591d3` before PR #39 squash-merged as `4daed33c5dd937e466ec8633d8cf286eb558aa58`.
13. This contract does not claim token/cost/CPU/GPU/RAM/disk quotas, priority/preemption, global scheduling, live large-agent benchmarks, mobile/NAS proof, full-repository CI, live-provider health or current/public served deployment.

Cycle proof and limitations: `proof/20260901-harness-execution-capacity/README.md`.

## Merged dependency-security compatibility evidence

PR #5 is merged only for the narrow dependency-security contract below; it does not upgrade general secret-management or release-security status to proven.

1. NEYVIA permits `cryptography>=49.0.0,<51`, allowing the 50.x line that contains upstream security fixes including CVE-2026-69247.
2. No claim is made that NEYVIA used the affected PKCS#7 decrypt API or was exploitable through that CVE.
3. Hosted run `33515334063` resolved Cryptography 50.0.1 and completed successfully on Ubuntu, macOS, and Windows.
4. The run exercised the complete P2P signed-cache scheduler test target, focused Web Push VAPID key generation, and Ed25519 sign/verify/PEM primitives used around authenticated evidence. Ubuntu reported 38 signed-cache tests passed and 1 focused Web Push test passed; the corresponding steps succeeded on macOS and Windows.
5. An earlier broader exploratory target exposed seven stale `tests/test_marketplace_oci.py` fixtures that fail publisher/module ownership validation before cryptographic verification. Production validation was not relaxed to make those tests green.
6. Temporary validation workflow code was deleted before merge. The final PR #5 production diff was one dependency-bound line and squash-merged as `a249e396351ea44364552a68fce1528302148f08`.
7. The separately observed high-severity npm audit finding remains unresolved and must not be represented as fixed by this Python dependency change.
8. The publication-integrity debt observed during PR #5 was subsequently addressed by PR #45; that historical red-but-empty workflow is no longer part of current `main`.

Cycle proof and limitations: `proof/20260901-cryptography50-security-compatibility/README.md`.

## Preserved merged contracts and evidence

The current work extends rather than replaces these existing controls:

- Durable Harness admission backpressure: PR #31 and `proof/20260901-harness-admission-backpressure/README.md`. Every durable non-terminal/unknown Harness record consumes open-run capacity; unreadable state fails closed; `NEYVIA_MAX_OPEN_HARNESS_JOBS` is a persisted monotonic-tighten workspace policy.
- Privacy-safe diagnostic support bundle: PR #33 and `proof/20260901-privacy-safe-support-bundle/README.md`. Export is allowlist-first, bounded and fails closed on forbidden/secret-like residue.
- Blocked-run operator attention: `proof/20260901-harness-blocked-attention-ui/README.md`.
- Durable blocked/interrupted lifecycle: `proof/20260901-harness-blocked-lifecycle/README.md`.
- Hard runtime budget: `proof/20260901-harness-hard-runtime-budget/README.md`.
- Native checkpoint recovery: `proof/20260901-native-checkpoint-restore-recovery/README.md`.
- Crash-safe single-flight provider authentication and anchored provider-state transactions: PRs #35/#37, `proof/20260901-provider-auth-queue-truth/README.md`, and `proof/20260901-provider-auth-queue-truth/FINAL_VALIDATION_ADDENDUM.md`.
- Canonical paired-device control plane: PR #44 and its device pairing/command/RPC tests.
- Read-only workflow publication-integrity guard: PR #45 and `proof/20260901-workflow-publication-integrity/README.md`.

Provider-auth hosted run `33502600259` remains scoped evidence: Linux focused 44 passed/2 skipped + adjacent 28 passed; Windows focused 43/3 + adjacent 28; macOS focused 44/2 + adjacent 28. It does not prove real provider expiry/refresh/re-auth pause-resume behavior, NAS/adversarial-kernel filesystem behavior, mobile recovery, multi-operator attribution or current/public served deployment.

The known pre-existing Codex/Hermes credential-ownership defect remains unresolved and is not reclassified by the paired-device or publication-integrity work.

## Current blind spots to prioritize after this merge

The matrix now records bounded execution capacity, publication-integrity cleanup, a canonical paired-device command plane and command-deadline truth, but the highest-value product/runtime gaps remain: human approval and actor/session/run attribution for device actions; signed native transport and physical Android/iOS proof; real provider expiry/re-auth safe resume without duplicate side effects; complete CPU/GPU/RAM/disk/token/cost ownership and cleanup accounting; update pinning/rollback across active work; real multi-agent lineage/cancellation/resource cleanup; connector signing/revocation/permission policy; full accessibility/i18n journeys; large-agent/constrained-host benchmarks; and exact served/public release proof.

The stale marketplace OCI fixtures that no longer satisfy publisher ownership remain an evidence-quality problem and should be repaired without weakening the production publisher-ownership gate. The retired self-mutating Native workflows are no longer current publication debt after PR #45; future workflow changes remain guarded by the read-only publication-integrity audit.

A separate npm dependency-security triage is still required because the PR #39 publication environment's `npm ci` reported one high-severity audit finding. This matrix records the observation without assuming whether it is exploitable, reachable, newly introduced, or relevant to the shipped runtime.
