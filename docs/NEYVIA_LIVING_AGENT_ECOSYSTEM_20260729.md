# Neyvia Living Agent Ecosystem

Status: receipt-bound comparison, sealed candidates, inactive skill materialization, proof leases, proven-skill app handoff, and a privacy-bounded friction-to-dividend loop implemented; live legacy trial remains unapproved
Date: 2026-07-29

## Product promise

Neyvia should become more valuable each time a person uses it, but never by quietly changing behavior or calling repetition "learning."

The operator-facing promise is:

> Show me what became easier, prove why, and let me decide what Neyvia may keep.

This is the center of the product. Chat, orchestration, skills, local apps, native apps, provider routes, and the NAS become parts of one supervised capability system.

## Reconciled prior direction

The existing plans remain useful and are combined rather than replaced:

- `NEYVIA_AGENT_EXTENSION_MASTER_PLAN.md`: provider-neutral agent extension, orchestration, proof, and controlled delegation.
- `NEYVIA_MODULAR_PLATFORM_AND_PERSONAL_MESH_PLAN.md`: private local and NAS continuity, modular capabilities, and cross-device ownership.
- App Factory and native studio work: turn repeated successful work into installable local applications.
- Skill Studio work: create, validate, version, and recover project or personal skills.
- Constellation work: decompose a goal into specialists and synthesize their results.
- Hermes imports: learn from aggregate prior usage without importing private conversation content.

The missing link was a durable rule for how accepted work becomes a better capability. The Compounding Loop now supplies that link.

## What current systems establish

Current agent platforms already cover important primitives:

- OpenAI Agents SDK provides agents, handoffs, sessions, guardrails, human approval, and tracing.
- OpenAI AgentKit adds visual workflow construction, connector management, trace grading, and prompt optimization.
- Microsoft Agent Framework defines sequential, concurrent, handoff, group-chat, and Magentic orchestration patterns.
- A2A defines interoperable agent cards, messages, tasks, and artifacts.
- MCP defines portable tools, resources, prompts, elicitation, and durable tasks.
- Agent Skills defines portable, progressively disclosed capability folders.
- Hermes demonstrates local skill use and a self-evolution direction.

Those systems largely answer: "How can agents work?"

Neyvia must answer a more personal question:

> Which parts of my work should become durable capabilities, and what evidence gives them permission to evolve?

## The architecture

### 1. Constellation is the work engine

Every specialist receives an explicit team contract:

- outcome
- required evidence
- allowed, approval-gated, and forbidden authority
- budget
- stop condition
- typed handback

Specialists return `neyvia.agent_delta.v1` evidence instead of relying on transcript volume as proof.

### 2. The evolution ledger owns capability history

Each capability has a lineage. An improvement is a candidate branch, not an overwrite.

The ledger records:

- parent and candidate identity
- baseline and candidate outcomes
- verification quality
- operator value
- cost and duration
- regressions and interventions
- approval and rollback
- materialization state

The active capability stays unchanged until evidence and operator approval are both present.

### 3. The Compounding Loop is the operator surface

Inside Constellation, the user sees:

- owned capabilities
- stagnant capabilities
- active bounded trials
- approved evolutions
- the highest-value proposed action
- team-contract readiness
- aggregate prior-system learning

Its primary question is "What became easier, with proof?"

### 4. App Factory is the promotion path

A skill does not become an app because it was used often. Promotion requires:

- repeated measured lift
- a stable input and output contract
- operator value
- safe authority boundaries
- a rollback path

When those conditions hold, Neyvia can prepare a local or native app brief with the evidence attached.

### 5. The personal mesh is the ownership layer

Capability lineages, proof receipts, apps, and preferences remain portable across workstation, NAS, and personal devices. Public interoperability can use MCP, A2A, and Agent Skills, while trust remains locally computed.

## Trust rules

These rules are product invariants:

1. Usage count never raises trust by itself.
2. Zero-lift repetition is stagnation evidence.
3. Missing evidence remains visibly missing.
4. A candidate never silently replaces the active capability.
5. Comparable verification and operator value are both required.
6. Impactful materialization requires human approval and rollback.
7. Imported learning uses aggregate evidence by default, not conversation content.
8. A synthesis cannot enter learning until every required team contract is complete.
9. A skill branch cannot inherit evidence unless its exact package was sealed before the comparison.
10. Materialization creates an inactive version branch; installation and activation remain separate decisions.
11. An app draft must bind its specification to the exact reviewed skill package, evidence, authority, and rollback lineage before generation.
12. Proven readiness expires when its provider, tracked dependencies, runtime family, review date, or user goal no longer matches.
13. Re-proof appends a newer receipt and lease revision; it never rewrites prior proof, expands authority, or silently repairs, retires, or activates a capability.
14. Two distinct, exact app-run receipts may reveal repeated friction, but the pattern opens only a repair or branch proposal and never raises trust.
15. Goal text, proof notes, and workflow-step text are transient verification inputs. The evolution ledger keeps typed outcomes, timing, friction, corrections, binding ids, and receipt digests only.
16. Measured elapsed time and operator-estimated time returned remain separate claims.
17. A returned run must revalidate its current App Factory job, durable verification receipt, handoff digest, app-binding digest, materialization, and Proof Lease before it enters discovery.

## Implemented foundation

The current slice implements:

- a SQLite capability lineage, trial, and observation ledger
- aggregate Hermes evidence import without conversation content
- stagnation, regression, proof, and app-promotion recommendations
- bounded comparison contracts
- approval-gated lineage acceptance
- explicit `candidateActivated: false` behavior
- typed specialist team contracts
- evidence-gated Constellation synthesis
- branch behavior after repeated zero-lift skill feedback
- a live Compounding Loop in the Constellation UI
- durable trial state across reloads
- navigation that keeps the operator in context after an evolution action
- a revised `skill-evolution-proof` skill with comparable-evidence decision rules
- server-resolved baseline and candidate turn receipts
- deterministic receipt-derived outcome, proof, duration, and intervention metrics
- receipt-pair hashing, transcript exclusion, and duplicate-pair idempotence
- an operator-facing receipt comparison form inside the existing Compounding Loop
- a bounded Counterfactual Skill Forge with win, tie, regression, and inconclusive classifications
- receipt-bound authority comparison that blocks broader candidate permissions
- explicit replay review before lineage approval
- deterministic version names and exact candidate `SKILL.md` package sealing before comparison evidence
- candidate package digests carried through receipt pairs, comparison runs, replay cases, and forge approval
- rejection of post-hoc skill instructions that were not bound to the evidence
- accepted-package materialization into a versioned store outside the active skills directory
- immutable materialization receipts with parent source digest, authority boundary, and rollback anchor
- non-destructive rollback that quarantines the inactive branch while retaining its proof package
- a reviewed inactive-skill to App Factory handoff with exact package copying and a second app-binding digest
- a generated human-guided runner with exact workflow steps, local persistence, SHA-256 run receipts, and proof-bundle export
- an App Factory proven-capability rail plus Compounding Loop actions that keep app drafting, native compilation, publication, and activation separate
- revision 4 of `skill-evolution-proof`, which makes the forge a reusable iteration invariant
- revision 5 of `skill-evolution-proof`, which adds sealed package identity, inactive materialization, and retained-evidence rollback
- a durable Proof Lease per materialized skill, bound to exact package hashes, accepted provider/runtime/model receipts, an authority envelope, a lasting user goal, safe dependency-file hashes, runtime family, and a bounded review date
- live readiness states for current, review due, re-proof required, held, retirement review, and withdrawn capabilities
- server-computed dependency hashes with workspace containment, symlink, size, generated-directory, and secret-file guards
- renewal only from a newer ledger-resolved receipt with passing verification, explicit operator value, and no authority expansion
- append-only establish, renew, disposition, and withdrawal events that retain every earlier lease digest
- App Factory gating and lineage binding to the current lease, while pre-lease drafts remain readable as legacy artifacts
- revision 6 of `skill-evolution-proof`, which makes freshness and bounded re-proof reusable iteration invariants
- an explicitly reconciled six-receipt skill history whose backup hashes, parent hashes, and current-file hash form one continuous chain
- a v2 generated capability-run receipt bound to the exact App Factory job, app, handoff, sealed skill candidate, and current Proof Lease
- direct embedded return to Neyvia plus standalone or native JSON export and explicit manual import
- server-side canonical rehashing, current-job and durable-receipt checks, duplicate idempotence, typed-only persistence, and private run-text exclusion
- a Personal Friction Graph that waits for two distinct matching receipt digests before offering the smallest repair or branch proposal
- Operator Dividends that report measured elapsed time separately from operator-estimated usual time and time returned
- a bounded trial handoff that leaves the active skill, app, trust, installation, publication, and activation unchanged
- revision 7 of `skill-evolution-proof`, which makes friction discovery, typed privacy, claim separation, and proof-bounded iteration reusable invariants

The imported aggregate case study currently covers 619 sessions, 13,670 tool calls, 36 delegations, and two generic learned skills. It shows why repetition alone is not a sufficient fitness signal.

## Novel capability roadmap

Items explicitly marked implemented are working product behavior. The remaining items are product directions, not claims of completed implementation.

### Personal friction graph

**Implemented and verified 2026-07-29.** A generated capability app can return a sealed, typed outcome to Neyvia. The backend recomputes its digest and exact App Factory, handoff, app-binding, materialization, and Proof Lease bindings. Only typed outcome, elapsed time, operator value, corrections, friction, ids, and hashes enter the ledger. After two distinct receipts report the same friction for the same lineage, the graph proposes the smallest repair or branch and names the triggering digests. It never edits, trusts, installs, or activates the candidate.

### Counterfactual Skill Forge

**Implemented and verified 2026-07-29.** Before promotion, Neyvia seals a bounded set of prior receipt-backed task contracts against both the active skill and a candidate. The user sees wins, ties, regressions, inconclusive cases, and authority differences before any behavior changes.

### Capability escrow

Third-party skills, agent cards, and proof capsules can enter a local quarantine. Neyvia evaluates them against the operator's contracts and data boundaries before granting trust or authority.

### Operator dividends

**Implemented and verified 2026-07-29.** The Compounding Loop reports completed and helpful outcomes, corrections, and measured run duration by lineage. When the operator supplies a usual-time estimate, Neyvia labels the resulting time-returned value as an operator counterfactual estimate rather than measured savings. This keeps personal value visible without manufacturing precision.

### Proof capsules

Users can share a portable skill candidate with its contract, tests, evidence schema, and provenance, but without private data. Another Neyvia installation recomputes trust locally instead of inheriting stars or reputation.

### Capability debt and decay

**Implemented and verified 2026-07-29.** Capabilities lose readiness when their exact package, provider route, tracked dependencies, runtime family, review date, or operator-confirmed goal changes. The Proof Lease workbench names the failed signal and offers one bounded next action: renew from a fresh verified receipt, open repair, review retirement, or restore the unavailable condition. Prior proof remains immutable.

### Ecosystem steward

A dedicated supervisory agent can manage contracts, budgets, conflicts, decay, and promotion proposals. It cannot grant itself authority. Its job is to keep the ecosystem coherent and bring clear decisions to the operator.

### Skill-to-app-to-agent ladder

One proven lineage can progress through controlled forms:

1. reusable skill
2. local workflow
3. focused local or native app
4. supervised team service
5. interoperable agent card

Each promotion keeps the same evidence lineage and rollback history.

## Next implementation sequence

1. Bind baseline and candidate runs directly to real Constellation turn receipts. **Implemented and verified 2026-07-29.**
2. Add the Counterfactual Skill Forge with a small replay set and regression view. **Implemented and verified 2026-07-29.**
3. Materialize an approved lineage into a versioned skill branch. **Infrastructure implemented and verified 2026-07-29; the saved legacy trial remains intentionally ineligible.**
4. Complete the proven-skill to App Factory handoff and generated app receipt. **Implemented and verified 2026-07-29.**
5. Add capability decay checks for provider, dependency, environment, review-date, and goal changes. **Implemented and verified 2026-07-29.**
6. Return privacy-bounded app outcomes into a Personal Friction Graph and Operator Dividends. **Implemented and verified 2026-07-29.**
7. Export and import privacy-preserving proof capsules.
8. Expose selected capabilities as local MCP tools and A2A agent cards.

## Current handoff

The saved branch trial still has four distinct, qualifying receipt pairs resolved from the durable Constellation ledger. Its forge uses the two newest authority-bearing pairs, both of which compare the immutable NAS handoff with the current implementation under the same receipt-binding contract.

The forge is `review_ready` with two wins, zero ties, zero regressions, zero inconclusive cases, and unchanged authority. Transcript text is excluded, repeating a set is idempotent, and the candidate cannot grant itself broader permission.

Research for materialization exposed a proof-identity gap: that older trial compared a candidate approach, but it never sealed the exact candidate `SKILL.md` before those runs. Attaching instructions written afterward would let untested content inherit unrelated evidence. Neyvia now fails closed on that condition.

The saved trial is therefore deliberately still `evidence_ready`, not accepted or materialized. Its receipts and forge remain useful historical evidence, but approval is locked and `candidateActivated` remains `false`. The operator surface labels it **legacy unbound** and offers a safe close-and-restart path.

New branch, repair, and merge trials receive a deterministic target skill id. Before the first comparison, the operator must review and seal the exact `SKILL.md` and interface metadata. Every later evidence and forge record must match that digest. After acceptance, materialization writes the same bytes into `.agent_control/capability_materializations`, outside `.codex/skills`, and records an exact parent-lineage rollback anchor. Rollback retains the package and quarantines the inactive candidate rather than deleting proof.

The reusable proof skill now has a repaired evolution history as well. Exact revision 3 and revision 4 files were recovered from their prior immutable NAS WIP snapshots and recorded as reconciled history, not retroactively described as live saves. The revision 5 receipt points to the exact revision 4 backup. Every receipt transition and backup hash matches through the current file.

The next ladder step is now implemented for lineages that satisfy the new proof rules. App Factory revalidates the materialized-inactive source, forge, evidence, authority, file bytes, and hashes, then copies the exact package into a local handoff store. A second digest binds the requested app specification to that lineage. Identical requests resume idempotently; a changed binding fails closed without damaging the ready receipt.

The generated capability app is deliberately human-guided. It turns the exact skill workflow into a local runner, requires a proof note for every completed step, persists runs on the device, seals SHA-256 receipts with Web Crypto, and exports a portable proof bundle. It does not invoke an agent, install or activate the skill, compile native code automatically, publish to Marketplace, or activate the app. Those remain separate supervised promotions on the skill-to-app-to-agent ladder.

The durability step now has an explicit expiry boundary. A materialized package receives a Proof Lease only after the operator states the lasting user goal and confirms which non-secret workspace dependencies should remain stable. Neyvia binds that declaration to exact package hashes, the accepted receipt routes, authority, platform family, and a review date.

Snapshots reassess those conditions without rewriting the ledger. A changed dependency or runtime requests re-proof; an unavailable provider or damaged package holds promotion; an elapsed review date requests human review; a repair or no-longer-needed decision remains an explicit operator disposition. App Factory accepts a new capability handoff only while the lease is current, and the lease digest travels into the app handoff, project lineage, verification receipt, registry, and generated guided runner.

Renewal resolves one newer passing receipt from the durable conversation ledger, checks that the same goal remains useful, rejects broader authority, recomputes dependency and runtime baselines, increments the lease revision, and appends an event that points back to the previous digest. A repair hold cannot be cleared by a receipt alone, and retirement remains a separate reviewed lineage action.

The generated app now closes one supervised loop without becoming an autonomous self-editor. At the end of a real run, the operator records a typed outcome, usefulness, controlled friction category and severity, correction count, optional usual-time estimate, and proof note. The browser seals the whole local receipt. Neyvia verifies the full receipt transiently, then stores only the typed measurements, exact binding ids, and digest. Embedded apps return through a same-origin message; standalone and future native builds export the same v2 bundle for explicit import.

One matching run displays discovery evidence and asks for another. Two distinct matching receipt digests create a Personal Friction Graph pattern and the smallest bounded mutation brief. Starting it creates a planned comparison trial with zero of two comparisons, keeps the sealed candidate requirement visible, and leaves activation off. A reload preserves both the pattern and the trial.

This design follows the strongest common thread in current self-improving agent research: experience is useful as structured memory and critique, but improvement claims require objective evaluation against a held contract. Neyvia adds a local ownership boundary, privacy-minimized storage, explicit authority comparison, rollback, Proof Leases, and a human promotion decision.

## Success measures

Neyvia is succeeding when:

- the user can name what became easier
- the improvement is backed by comparable evidence
- fewer corrections are needed on the next similar task
- time-to-verified-outcome falls without broader authority
- skills branch or repair when they stagnate
- promoted apps remain reversible
- the operator can understand and control every trust increase

## Primary references

- OpenAI Agents SDK: <https://openai.github.io/openai-agents-python/>
- OpenAI AgentKit: <https://openai.com/index/introducing-agentkit/>
- Microsoft Agent Framework: <https://learn.microsoft.com/en-us/agent-framework/overview/>
- A2A specification: <https://github.com/a2aproject/A2A/blob/main/docs/specification.md>
- Agent Skills: <https://github.com/agentskills/agentskills>
- Hermes self-evolution: <https://github.com/NousResearch/hermes-agent-self-evolution>
- Hermes self-evolution issue 38: <https://github.com/NousResearch/hermes-agent-self-evolution/issues/38>
- The Update Framework specification: <https://theupdateframework.github.io/specification/latest/>
- SLSA provenance: <https://slsa.dev/spec/v1.2/provenance>
- SLSA artifact verification: <https://slsa.dev/spec/v1.2/verifying-artifacts>
- Microsoft agent evaluation frameworks: <https://learn.microsoft.com/en-us/agents/architecture/evaluation-frameworks>
- OpenAI, building self-improving tax agents with Codex: <https://openai.com/index/building-self-improving-tax-agents-with-codex/>
- Voyager, an open-ended embodied agent with an automatic curriculum and skill library: <https://arxiv.org/abs/2305.16291>
- Reflexion, language agents with verbal reinforcement learning: <https://arxiv.org/abs/2303.11366>
- Anthropic, demystifying evals for AI agents: <https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents>
