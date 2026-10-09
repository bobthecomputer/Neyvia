# Neyvia Expanded Ecosystem Product Contract — 2026-07-25

Definitive product contract for the ecosystem expansion milestone. It reconciles the
existing 22 capability domains and 89 capabilities around real user outcomes, defines the
attention-first sidebar, and specifies exactly what Codex must implement.

This document does not introduce a new taxonomy. Everything below composes capabilities
that already exist in `config/capability_packs.json` and the shipped foundations.

**Truthfulness rule that governs the whole contract:** a surface may only assert what the
backend has reported. Where a behaviour needs a backend command that does not exist, this
document specifies the command and the frontend renders an honest unavailable state — never
a dead control.

---

## 1. Ecosystem information architecture

Neyvia has ten layers. The user only ever sees four kinds of place:

| Kind | Places | What the user is doing |
| --- | --- | --- |
| **Working surfaces** | Chat, Orchestration (Builder + Agent Live), Notebook, Lab, Office, Image Playground | Doing the work |
| **Supply** | Library, Marketplace | Finding and installing capability |
| **Fabric** | Personal Mesh, Communication Fabric, Experimental Systems Lab | The user's own machines, accounts and physical world |
| **Evidence** | Benchmark Lab, receipts, Share Capsules | Proving and passing on what happened |

The thin navigation rail stays as-is. The attention inbox is the only always-present list.

### 1.1 Placement rules

1. A capability has **one identity** (`neyviaCapabilityIdentity.js`). It may be *discovered*
   in one zone and *used* in another. Discovery never duplicates state.
2. **Capability / application / artifact / runtime** are different things and never merge:
   a capability is an operation Neyvia can run; an application is installed and may be
   inactive; an artifact is produced; a runtime is a live lane.
3. Anything opened inside a session uses the embedded-workspace contract
   (`neyviaEmbeddedWorkspace.js`). One grammar: Open here, Focus, Expand, Collapse, Return,
   Close.
4. An installed Marketplace tile never implies an active application.

---

## 2. Sidebar v2 — the attention inbox

**Implemented in this milestone.** `web/src/neyvia/neyviaAttentionInbox.js` +
`NeyviaAttentionInbox.jsx`, rendered inside the existing `NeyviaConversationSidebar`.

The sidebar is the user's set of open mental obligations, not a list of chats.

### 2.1 States, in attention order

| State | Meaning | Reasons |
| --- | --- | --- |
| **Needs action** | Blocked on the user | `approval-required`, `answer-required`, `verification-failed`, `runtime-unavailable`, `security-decision` |
| **Active** | Moving, no decision needed | `running`, `delegated`, `waiting-runtime`, `waiting-external`, `paused-resumable` |
| **Ready for review** | Finished, not accepted | `work-complete-unaccepted`, `artifact-delivered`, `pr-ready`, `evidence-ready` |
| **Quiet** | Deliberately not asking | `snoozed`, `waiting-no-attention` |
| **Settled** | Accepted or closed, still searchable | `accepted`, `closed` |

### 2.2 Two invariants

1. **Completion is not settlement.** A runtime reporting `completed` maps to
   `ready-for-review`. Settlement requires `settledAt` + `settledBy` recorded by the
   backend from an explicit user acceptance. This is enforced in
   `projectAttentionThread`.
2. **Blocking obligations escape snooze.** Approvals, security decisions and verification
   failures return to `needs-action` even while `snoozedUntil` is in the future, flagged
   `escapedSnooze`. Snooze controls are disabled on blocking threads.

### 2.3 Derived vs durable mode

The durable lifecycle fields do not exist yet. The frontend therefore runs in one of two
modes and says which:

- **durable** — `get_neyvia_attention_inbox_command` answered with the expected schema.
  Settle / snooze / reopen controls render and write to the backend.
- **derived** — the command is unavailable. Grouping is still real: it is computed from
  live mission signals (`approvals`, `blockers`, `status`, `artifactCount`, `terminal`
  from the shared mission projection) and conversation rows
  (`lastMeaningfulActivityAt`, `status`, `kind`, `workspaceId`). **No lifecycle controls
  are rendered at all**, and the panel states that decisions cannot be stored yet.

There is no localStorage fallback for settlement, snooze, approval or security state.

### 2.4 Ordering and grouping

Within a group: blocking count → unread meaningful changes → most recent meaningful
activity → title. Settled sorts by `settledAt` so the most recent acceptance is easiest to
recover. Project grouping uses `projectId` when supplied and falls back to `workspaceId`,
which is real today. `Settled` is collapsed by default.

### 2.5 Acceptance scenarios

- A mission with a pending approval appears under **Needs action** with the approval named,
  above everything else, even if the user snoozed it.
- A mission whose runtime reports `completed` with two artifacts appears under **Ready for
  review**, never **Settled**, until the user accepts it.
- Accepting removes it from the open filters and collapses it into **Settled**; it remains
  findable by search and openable by durable link.
- A runtime the backend reports unavailable puts its thread in **Needs action** with
  `runtime-unavailable`, not in **Active**.
- With the backend command absent, all of the above grouping still happens, and no Accept
  or Snooze button is shown.

---

## 3. Experimental Systems Lab

**Name:** Experimental Systems Lab. Lives in **Lab**.

Not a new tool category — the coherent front for capabilities that already exist: Maker and
Engineering, Browser and Device Application Lab, Software and Infrastructure, AI and ML,
Security and Red Team, Private Mesh and Service Discovery, connected-device bridge, Nearby
Sharing, Folder Sync, Secret Broker, P2P Cache, Niche Knowledge and Custom Packs.

### 3.1 Structure

1. **Architecture map** — the user's computers, devices, services and trusted links, drawn
   from the existing mesh snapshot and connected-device bridge. Nodes show *observed*
   status only; a node that has never been probed reads "not probed", not "offline".
2. **Device shelf** — USB, serial, Bluetooth and network devices from the connected-device
   bridge, each with its own permission ladder.
3. **Experiments** — the unit of work. An experiment has a hypothesis, a baseline, variants,
   a measurement journal, a lifetime, and a verdict that may be *failed* and still retained.
4. **Promotion** — a successful experiment becomes a persistent project, skill, application,
   workflow or marketplace capability. Promotion is explicit and carries the evidence.

### 3.2 Three-tier action boundary

Every action is one of, and is labelled as one of:

| Tier | Meaning | Approval |
| --- | --- | --- |
| **Observe** | Read state, enumerate, capture | Session-level |
| **Simulate** | Model, dry-run, replay against a recording | Session-level, results marked simulated |
| **Act** | Transmit, flash firmware, drive a device, run a command | Per-action, named target, explicit scope |

Authorised Flipper Zero-class experimentation lives in **Act** and additionally requires a
stated authorisation context. Neyvia records the authorisation with the experiment. A
planned adapter is never presented as executable — an adapter without a backend reports
`planned`.

### 3.3 Sandboxed experiments

A disposable experiment declares a lifetime up front. On expiry the workspace is released
and the **evidence is retained**: journal, measurements, failures and conclusion.

---

## 4. Communication Fabric

One capability, not a Gmail page and an Outlook page.

### 4.1 Account model

| Source | Route |
| --- | --- |
| Personal Google / Microsoft | Delegated OAuth |
| Organisational accounts | Delegated OAuth where the org permits; otherwise `Blocked by organization` |
| Custom domains | IMAP / SMTP / JMAP |
| Local clients | Outlook and Thunderbird bridges |
| Files | EML, MSG, Maildir drag-and-drop and import |
| No-API path | Forward/BCC ingestion address; draft handoff through the installed client |

### 4.2 Permission ladder

`read` → `draft` → `send` → `forward` → `delete` → `unsubscribe`. Each is granted
separately per account. `send`, `delete` and `unsubscribe` are always per-action approvals.

### 4.3 Truthful account states

`Connected` · `Limited` (named limitation, e.g. read-only, no send scope) · `Approval
required` · `Blocked by organization` · `Credentials missing` · `Not configured`.

An account is never shown as Connected because a provider was configured somewhere else.

### 4.4 Composition

Messages, calendar, contacts, attachments and tasks are one context. An email attachment
opens through the embedded-workspace contract; a thread can become a mission; a mission
deliverable can become a draft. Account and organisation boundaries are shown on every
compose surface, and cross-boundary composition warns before it happens.

---

## 5. ChatGPT Presentation Bridge

ChatGPT.com is a presentation surface the user drives. It is **not** a Neyvia provider and
must never be described as one.

### 5.1 Four flows

1. **Neyvia → ChatGPT** — pick a task profile, compile a prompt and context pack, **review
   the diff of what Neyvia added**, then insert on an explicit user action.
2. **ChatGPT → Neyvia** — the user selects content, files, or an explicitly exported
   conversation. Neyvia attaches it to a project, conversation or mission and records the
   source and lineage.
3. **Continue in Neyvia** — a captured response becomes a task, artifact, benchmark subject
   or runtime handoff.
4. **ChatGPT as presentation** — Neyvia keeps project context, prompt profiles, receipts and
   continuation controls alongside; it does not claim to own the ChatGPT runtime.

### 5.2 Hard limits

- No invisible transcript harvesting. Every capture is user-initiated and visible.
- No automated login, scraping or DOM injection presented as an integration.
- Account and context boundary warnings before any capture crosses a project.
- Benchmarks may include the bridge only where a comparable **user-driven** flow exists, and
  the result is labelled as human-in-the-loop.

---

## 6. Share Capsule

One sharing primitive for artifacts, collections, applications, workflows, capability packs,
experiments with evidence, project summaries, forkable projects and social presentations.

### 6.1 Content selection

The user chooses, per capsule: final result · explanation · sources · prompt · receipts ·
benchmark evidence · editable project structure. Defaults to **result only**.

### 6.2 Modes

Private device-to-device (Nearby Sharing / mesh) · another Neyvia user · expiring link ·
selected collaborators · public showcase · forkable template · standard export for
non-Neyvia users · social summary.

### 6.3 Pre-share inspection (required)

Before any capsule leaves the device Neyvia scans for and reports: secrets and credentials,
personal filesystem paths, organisational material, private account identifiers, and hidden
metadata (EXIF, document authorship, revision history). Findings are shown as a checklist the
user resolves; the share action stays disabled while an unresolved secret is present.

### 6.4 Emotional design

Curiosity, teaching, reuse, collaboration. **No** rankings, streaks, leaderboards, activity
graphs or comparative self-measurement. A capsule invites a fork, not a score.

---

## 7. Domain experiences

For each: default intent · composed capabilities · auto-recommended tools · visible choices ·
prompt profile · approvals · artifacts · sharing · reality.

### 7.1 Student

- **Intent:** understand and retain material; organise assignments.
- **Composes:** Documents/OCR/Typesetting, Education and Learning, Research and Science,
  Literature, Office.
- **Auto:** OCR on captured material, document understanding, flashcard and quiz generation,
  citation lookup, explanation with sources.
- **Visible:** which source a claim came from; explanation depth; runtime.
- **Profile:** research/explanation. **Approvals:** low; reading is session-level.
- **Artifacts:** study set, flashcards, quiz, annotated source, assignment plan.
- **Sharing:** study-set capsule (result + explanation + sources).
- **Reality:** OCR/document/citation foundations exist. Flashcard/quiz generators are
  capability-pack work.
- **Correction:** teaching tools are secondary; study-material capture is the priority.

### 7.2 Writing and publishing

- **Intent:** produce a finished, correctly typeset, sourced document.
- **Composes:** Literature and Publishing, Documents/OCR/Typesetting, Office, Research,
  Image, Communication Fabric.
- **Auto:** structure outline, citation management, typesetting, figure generation, export.
- **Profile:** writing. **Approvals:** per-send when publishing or mailing.
- **Artifacts:** manuscript, bibliography, figures, typeset output.
- **Reality:** Pandoc/LibreOffice/LaTeX paths are real; publishing adapters are planned.

### 7.3 Research and science

- **Intent:** find, verify, analyse, conclude with evidence.
- **Composes:** Research and Science, Literature, Documents, Office and Data Work,
  experiment profiles, Benchmark Lab.
- **Auto:** literature discovery, citation extraction, dataset profiling, statistical summary.
- **Profile:** research. **Approvals:** per-action for external fetches.
- **Artifacts:** literature set, dataset, analysis notebook, evidence bundle.

### 7.4 Creative

- **Intent:** make and present something visual or audible.
- **Composes:** Image/Photography/Video/Audio, 3D/Games/XR, Publishing, Share Capsule.
- **Auto:** Image Playground, manifest-tracked iteration, comparison, export presets.
- **Artifacts:** image sets with manifests, edits, renders, share-ready presentation.
- **Reality:** Image Playground and manifests are real; video/audio pipelines are partial.

### 7.5 Software development

- **Intent:** change a codebase safely and prove it.
- **Composes:** Software and Infrastructure, runtimes, worktrees/branches/PRs, Browser and
  Device Application Lab, Security and Red Team, Benchmark Lab.
- **Auto:** runtime selection, worktree isolation, diff review with large diffs folded,
  browser/device testing, release evidence.
- **Visible:** runtime and model; branch; approval mode.
- **Profile:** implementation or diagnosis. **Approvals:** per-action for writes, commands
  and pushes.
- **Artifacts:** diffs, PRs, test and verification evidence, release proof.
- **Reality:** runtimes, worktrees, missions and receipts are real; PR fetch/link is a gap
  (§9.6).

### 7.6 Social communication

- **Intent:** prepare and send a message or campaign.
- **Composes:** Communication Fabric, Business/Communication/Everyday Design, Share Capsule,
  Image.
- **Auto:** draft preparation, audience/channel framing, asset generation, capsule packaging.
- **Approvals:** send is always per-action. **Reality:** provider-specific publishing
  adapters are planned; Share Capsule + draft handoff are the real path.

### 7.7 Casual exploration

Becomes a **disposable experiment** in the Experimental Systems Lab with a lifetime and a
retained journal — promotable later. It is not a miscellaneous bucket.

### 7.8 Niche

Custom capability packs remain the extension point. A pack declares its capabilities,
permissions and evidence; the placement rules in §1.1 apply unchanged.

---

## 8. Deep Benchmark Lab

A first-class product surface, not an internal test page.

### 8.1 Comparison subjects

Neyvia native · Codex · Claude Code · OpenCode · Grok · other configured runtimes · ChatGPT
presentation bridge (human-in-the-loop, labelled) · prompt profiles · orchestration
strategies · models within one runtime · warm vs cold context · local vs remote execution.

### 8.2 Metrics

Task success · artifact correctness · time to first useful action · total completion time ·
user interventions · approval interruptions · tool calls and round trips · retries and repair
loops · token and provider usage when reported · cache behaviour · context compaction · cost
when known · runtime failures · continuity across pause/resume · evidence quality · user
comprehension · resource usage for local models and device experiments · retained failures.

### 8.3 Fairness contract

A comparison claim requires **equal budgets and comparable task contracts**. A run that
exceeded its budget, used a different context state, or required different intervention is
reported but excluded from the claim, with the reason shown. Raw receipts are preserved.
**Measured facts and interpretation are visually and structurally separate**; an unreported
metric renders as "not reported", never as zero.

---

## 9. Codex backend handoff

Frontend is written against these contracts. Until they exist, the UI runs in derived mode
and says so.

### 9.1 Attention inbox — `get_neyvia_attention_inbox_command`

```
request:  { query?: string, filter?: string, projectId?: string, limit?: number, probe?: boolean }
response: {
  schema: "neyvia.attention.inbox.v1",
  generatedAt: string,
  threads: AttentionThread[],
  counts: { "needs-action": n, active: n, "ready-for-review": n, quiet: n, settled: n }
}
```

`AttentionThread` (fields the projection reads; all optional except the first three):

```
conversationId, kind, title,
missionId, projectId, workspaceId, branch,
pullRequest: { url, state, number },
attentionState: "needs-action"|"active"|"ready-for-review"|"quiet"|"settled",
lifecycleState, settledAt, settledBy, settlementReason,
snoozedUntil, snoozeReason, nextWakeCondition,
hasBlockingApproval, hasVerificationFailure, awaitingUserAnswer,
securityDecisionPending, hasVerificationEvidence,
unreadMeaningfulChanges, lastMeaningfulActivityAt
```

The probe contract: responding with `schema: "neyvia.attention.inbox.v1"` is what flips the
frontend from derived to durable mode.

### 9.2 Lifecycle commands

| Command | Request | Effect |
| --- | --- | --- |
| `settle_neyvia_conversation_command` | `{ conversationId, settlementReason, settledBy? }` | Sets `settledAt`/`settledBy`. Must reject while a blocking approval or verification failure is open. |
| `reopen_neyvia_conversation_command` | `{ conversationId, reason? }` | Clears settlement; returns to derived attention state. |
| `snooze_neyvia_conversation_command` | `{ conversationId, snoozedUntil?, untilEvent?, snoozeReason? }` | One of `snoozedUntil` / `untilEvent` required. Must **not** suppress blocking reasons. |
| `wake_neyvia_conversation_command` | `{ conversationId }` | Clears snooze immediately. |
| `set_neyvia_conversation_project_command` | `{ conversationId, projectId }` | Stable project association. |

### 9.3 Transitions

```
active ⇄ needs-action        (blocking reason appears / is resolved)
active  → ready-for-review   (terminal status reached)
ready-for-review → settled   (explicit acceptance only)
settled → needs-action|active|ready-for-review   (reopen re-derives)
any non-settled → quiet      (snooze)
quiet → previous             (wake, snooze expiry, or wake condition met)
quiet → needs-action         (blocking reason appears — overrides snooze)
```

A runtime status of `completed` must never write `settledAt`.

### 9.4 Persistence

New columns on the conversations table (or a side table keyed by `conversation_id`):
`attention_state`, `lifecycle_state`, `settled_at`, `settled_by`, `settlement_reason`,
`snoozed_until`, `snooze_reason`, `next_wake_condition`, `project_id`, `branch`,
`pull_request_json`, `unread_meaningful_changes`.

Likely files: `src/grant_agent/neyvia_conversations.py` (schema + commands),
`src/grant_agent/web_backend.py` (dispatch).

**A settled thread must still open from a durable link** — settlement is a lifecycle flag,
never a soft delete, and must not be filtered out of `get_neyvia_conversation_command`.

### 9.5 Branch and worktree stability

- A thread's branch/worktree association must be stable: a new thread must not take the
  branch of whatever thread was being viewed.
- A thread must not silently drift off its branch; a drift is a `needs-action` reason.
- A PR merging under a thread must not unsettle a warm thread.

### 9.6 Missing provider adapters and integrations

| Area | Needed | Current honest state |
| --- | --- | --- |
| PR fetch/link | `get_pull_request_status_command` | `pr-ready` cannot be derived |
| Communication Fabric | Provider adapters, credential handling, local mailbox bridges | Not connected |
| ChatGPT bridge | Capture/export handling, lineage recording | Not connected |
| Share Capsule | Capsule build, secret scan, transport | Not connected |
| Benchmark Lab | Run harness, budget enforcement, receipt storage | Partial (mission receipts exist) |
| Experimental Systems Lab | Device act-tier execution, sandbox lifetime, firmware paths | Bridge exists; act tier not exposed |

### 9.7 Security-sensitive operations (Codex-owned)

Credential storage, provider authentication, local mailbox automation, device act-tier
execution, firmware writes, secret scanning before share, and workspace-root enforcement.
The frontend never handles credentials and never bypasses an approval gate.

---

## 10. Realization estimate

| Area | State |
| --- | --- |
| Runtime modes, embedded workspaces, Builder ↔ Agent Live | Implemented |
| Attention inbox projection, grouping, ordering, invariants | Implemented (derived mode) |
| Attention durable lifecycle | Contract specified, backend pending |
| Capability identity and placement | Implemented |
| Experimental Systems Lab | Designed; device act tier backend pending |
| Communication Fabric | Designed; all adapters pending |
| ChatGPT bridge | Designed; capture path pending |
| Share Capsule | Designed; build + secret scan pending |
| Benchmark Lab | Designed; harness pending |

Overall: the interaction system and its contracts are defined end-to-end; roughly half the
surfaces have live data behind them today, and the rest are specified precisely enough for
Codex to implement without reinterpreting product intent.
