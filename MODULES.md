# Neyvia modules

Generated from source ownership, exported APIs, imports and executable CL manuals. Regenerate with `scripts/generate_module_map.py`; `run modules.verify-map()` and the CL compiler's `--check` reject drift.

Apps and mods reuse the stable [neyvia-sdk](packages/neyvia-sdk/README.md) boundary. Internal module exports below describe today's source; only documented SDK APIs are compatibility promises. See [Building apps and mods](docs/BUILDING_APPS_AND_MODS.md).

| Module | Purpose | API and manual |
|---|---|---|
| [app.hyperframes-studio.host-contract](modules/app.hyperframes-studio.host-contract/README.md) | Provides app / hyperframes-studio / host-contract in Neyvia. | neyvia |
| [app.hyperframes-studio.manual](modules/app.hyperframes-studio.manual/README.md) | Provides app / hyperframes-studio / manual in Neyvia. | neyvia |
| [app.hyperframes-studio.neyvia.app](modules/app.hyperframes-studio.neyvia.app/README.md) | Provides app / hyperframes-studio / neyvia / app in Neyvia. | neyvia |
| [app.hyperframes-studio.www.app](modules/app.hyperframes-studio.www.app/README.md) | Provides app / hyperframes-studio / www / app in Neyvia. | neyvia |
| [app.hyperframes-studio.www.index](modules/app.hyperframes-studio.www.index/README.md) | Provides app / hyperframes-studio / www / index in Neyvia. | neyvia |
| [app.laya-video.briefs.neyvia-launch-v2](modules/app.laya-video.briefs.neyvia-launch-v2/README.md) | Provides app / laya-video / briefs / neyvia-launch-v2 in Neyvia. | neyvia |
| [app.laya-video.briefs.neyvia-launch-v3](modules/app.laya-video.briefs.neyvia-launch-v3/README.md) | Provides app / laya-video / briefs / neyvia-launch-v3 in Neyvia. | neyvia |
| [app.scroll-study.host-contract](modules/app.scroll-study.host-contract/README.md) | Provides app / scroll-study / host-contract in Neyvia. | neyvia |
| [app.scroll-study.manual](modules/app.scroll-study.manual/README.md) | Provides app / scroll-study / manual in Neyvia. | scroll-generator |
| [app.scroll-study.neyvia.app](modules/app.scroll-study.neyvia.app/README.md) | Provides app / scroll-study / neyvia / app in Neyvia. | neyvia |
| [app.scroll-study.package](modules/app.scroll-study.package/README.md) | Provides app / scroll-study / package in Neyvia. | neyvia |
| [app.scroll-study.scripts.journey](modules/app.scroll-study.scripts.journey/README.md) | User-path proof for the Scroll Study prototype. | neyvia |
| [app.scroll-study.scripts.property](modules/app.scroll-study.scripts.property/README.md) | Provides app / scroll-study / scripts / property in Neyvia. | scroll-generator |
| [app.scroll-study.scripts.property-results](modules/app.scroll-study.scripts.property-results/README.md) | Provides app / scroll-study / scripts / property-results in Neyvia. | neyvia |
| [app.scroll-study.scripts.simulate](modules/app.scroll-study.scripts.simulate/README.md) | Provides app / scroll-study / scripts / simulate in Neyvia. | scroll-generator |
| [app.scroll-study.www.app](modules/app.scroll-study.www.app/README.md) | Provides app / scroll-study / www / app in Neyvia. | scroll-generator |
| [app.scroll-study.www.feed](modules/app.scroll-study.www.feed/README.md) | Provides app / scroll-study / www / feed in Neyvia. | scroll-generator |
| [app.scroll-study.www.index](modules/app.scroll-study.www.index/README.md) | Provides app / scroll-study / www / index in Neyvia. | scroll-generator |
| [app.scroll-study.www.load-pack](modules/app.scroll-study.www.load-pack/README.md) | Provides app / scroll-study / www / load-pack in Neyvia. | scroll-generator |
| [app.scroll-study.www.manifest](modules/app.scroll-study.www.manifest/README.md) | Provides app / scroll-study / www / manifest in Neyvia. | neyvia |
| [app.scroll-study.www.neyvia-services](modules/app.scroll-study.www.neyvia-services/README.md) | Provides app / scroll-study / www / neyvia-services in Neyvia. | scroll-generator |
| [app.scroll-study.www.pack](modules/app.scroll-study.www.pack/README.md) | Provides app / scroll-study / www / pack in Neyvia. | scroll-generator |
| [app.scroll-study.www.storage](modules/app.scroll-study.www.storage/README.md) | Provides app / scroll-study / www / storage in Neyvia. | scroll-generator |
| [app.scroll-study.www.styles](modules/app.scroll-study.www.styles/README.md) | Styles styles with Neyvia's shared theme tokens. | scroll-generator |
| [backend.__init__](modules/backend.__init__/README.md) | Grant Agent Harness package. | neyvia |
| [backend.action_executor](modules/backend.action_executor/README.md) | Provides backend / action_executor in Neyvia. | neyvia-core |
| [backend.action_receipts](modules/backend.action_receipts/README.md) | At-most-once native tool attempts with durable, inspectable outcomes. | neyvia |
| [backend.action_verification](modules/backend.action_verification/README.md) | Provides backend / action_verification in Neyvia. | neyvia |
| [backend.adaptive_work](modules/backend.adaptive_work/README.md) | Durable adaptive-work state: explicit blockers, evidence, constraints and focus. | neyvia |
| [backend.agent_delta](modules/backend.agent_delta/README.md) | Typed AgentDelta for agent_nodes progress/result_summary columns. | neyvia |
| [backend.agent_prompt_library](modules/backend.agent_prompt_library/README.md) | Durable, validated role prompts for Neyvia agent lanes. | neyvia |
| [backend.agent_questions](modules/backend.agent_questions/README.md) | Durable operator questions for agent runs. | neyvia |
| [backend.agent_submission_gate](modules/backend.agent_submission_gate/README.md) | Read-only validation for immutable agent-submission receipts. | neyvia |
| [backend.agent_vision](modules/backend.agent_vision/README.md) | Keep observed pixels visible on Chat Completions' text-only tool channel. | neyvia |
| [backend.agents_message](modules/backend.agents_message/README.md) | Read successful inbox delivery metadata, without exposing message text. | neyvia |
| [backend.agents_overview](modules/backend.agents_overview/README.md) | One cached, read-only agent graph for the pane, CL and native clients. | neyvia |
| [backend.agents_overview_sources](modules/backend.agents_overview_sources/README.md) | Read orchestration owners into the shared graph without activating workers. | neyvia |
| [backend.app_capability_standard](modules/backend.app_capability_standard/README.md) | Provides backend / app_capability_standard in Neyvia. | neyvia |
| [backend.app_factory](modules/backend.app_factory/README.md) | Durable local application scaffolding for the Neyvia App Factory. | neyvia |
| [backend.app_factory_semantics](modules/backend.app_factory_semantics/README.md) | Semantic adapter from real App Factory jobs to Living Applications. | neyvia |
| [backend.app_sdk](modules/backend.app_sdk/README.md) | Generated apps with a shared state bridge and observer-backed CL 1.1 goals. | neyvia |
| [backend.app_sdk_server](modules/backend.app_sdk_server/README.md) | Loopback static host and CAS bridge for generated apps; no implicit port. | neyvia |
| [backend.apple_bundle](modules/backend.apple_bundle/README.md) | Apple artifact outcomes and portable ad-hoc signing. No host-execution claim. | neyvia |
| [backend.apple_targets](modules/backend.apple_targets/README.md) | Supported Apple lanes, dormant cloud preparation and artifact observations. | neyvia |
| [backend.application_surface](modules/backend.application_surface/README.md) | Bounded contracts for optional workspace-built application surfaces. | neyvia |
| [backend.approval_modes](modules/backend.approval_modes/README.md) | Approval modes for tool execution — the setting the product never had. | neyvia |
| [backend.artifact_graph](modules/backend.artifact_graph/README.md) | Durable content-addressed artifact lineage for N-E-Y-V-I-A. | neyvia |
| [backend.assigned_ports](modules/backend.assigned_ports/README.md) | Explicitly assigned port blocks and scratch output roots for proof harnesses. | neyvia |
| [backend.autopilot_model](modules/backend.autopilot_model/README.md) | Bounded, provider-owned Codex judgements for the autopilot execution engine. | neyvia |
| [backend.behavior_capsules](modules/backend.behavior_capsules/README.md) | Executable behavior capsules for Neyvia Native. | neyvia |
| [backend.behavioral_experiments](modules/backend.behavioral_experiments/README.md) | Durable observable API experiment ledger; no activation or causal claims. | neyvia |
| [backend.browser_capabilities](modules/backend.browser_capabilities/README.md) | Provides backend / browser_capabilities in Neyvia. | neyvia |
| [backend.browser_dom](modules/backend.browser_dom/README.md) | Provides backend / browser_dom in Neyvia. | neyvia |
| [backend.browser_event_source](modules/backend.browser_event_source/README.md) | Provides backend / browser_event_source in Neyvia. | neyvia |
| [backend.browser_laya](modules/backend.browser_laya/README.md) | Explicit advisory HTTP provider for the browser's LAYA hook. | neyvia |
| [backend.browser_native_launcher](modules/backend.browser_native_launcher/README.md) | Normal WebView2 runtime on C1's private desktop, never the input desktop. | neyvia |
| [backend.browser_obscura](modules/backend.browser_obscura/README.md) | Explicit non-stealth Obscura CDP process, with no Chromium fallback. | neyvia |
| [backend.browser_ports](modules/backend.browser_ports/README.md) | Caller-assigned local port ranges for Neyvia's browser. | neyvia |
| [backend.browser_preflight](modules/backend.browser_preflight/README.md) | Provides backend / browser_preflight in Neyvia. | neyvia |
| [backend.browser_render_assets](modules/backend.browser_render_assets/README.md) | Bounded public assets for explicitly authorized local Obscura render fixtures. | neyvia |
| [backend.browser_render_profile](modules/backend.browser_render_profile/README.md) | Provides backend / browser_render_profile in Neyvia. | neyvia |
| [backend.browser_scripts](modules/backend.browser_scripts/README.md) | First-success browser procedures, parameterized and replayed without a model. | neyvia |
| [backend.browser_site_manuals](modules/backend.browser_site_manuals/README.md) | Observed site manuals and bounded semantic batches, using the real browser service. | neyvia |
| [backend.browser_task](modules/backend.browser_task/README.md) | Goal-checked browser cascade on the existing tab and action receipt seams. | neyvia |
| [backend.browser_verification](modules/backend.browser_verification/README.md) | Validate the bounded effect predicate before any browser action is executed. | neyvia |
| [backend.capability_adapters](modules/backend.capability_adapters/README.md) | Demand-start adapter registry for capability execution. | neyvia |
| [backend.capability_catalog](modules/backend.capability_catalog/README.md) | Capability-pack catalog, fast routing, and deterministic plan compiler. | neyvia |
| [backend.capability_contracts](modules/backend.capability_contracts/README.md) | Typed contracts for the N-E-Y-V-I-A capability operating system. | neyvia |
| [backend.capability_evolution](modules/backend.capability_evolution/README.md) | Durable, evidence-gated capability evolution for the Neyvia ecosystem. | neyvia |
| [backend.capability_routes](modules/backend.capability_routes/README.md) | Constraint-aware model and harness capability routing. | neyvia |
| [backend.capability_runtime](modules/backend.capability_runtime/README.md) | Permission, preview, and performance runtime for capability plans. | neyvia |
| [backend.capability_service](modules/backend.capability_service/README.md) | Facade joining N-E-Y-V-I-A capability catalog, artifacts, runs, and adapters. | neyvia |
| [backend.cdp_client](modules/backend.cdp_client/README.md) | Reusable Chrome DevTools Protocol client (promoted from control_route_interaction_smoke). | neyvia |
| [backend.challenge_presets](modules/backend.challenge_presets/README.md) | Provides backend / challenge_presets in Neyvia. | neyvia |
| [backend.chat_context](modules/backend.chat_context/README.md) | Migrate only legacy app-authored workspace descriptions, never user prompts. | neyvia |
| [backend.chat_run_control](modules/backend.chat_run_control/README.md) | Cancellation and recovery for a single active chat, shared by desktop and web processes. | neyvia |
| [backend.chat_storage_compaction](modules/backend.chat_storage_compaction/README.md) | Shrink chat storage written before turns stored references instead of session windows. | neyvia |
| [backend.chat_stream](modules/backend.chat_stream/README.md) | Bounded, authenticated chat event polling shared by web and desktop bridges. | neyvia |
| [backend.checkpoints](modules/backend.checkpoints/README.md) | Provides backend / checkpoints in Neyvia. | neyvia |
| [backend.chrome_environment](modules/backend.chrome_environment/README.md) | Chrome-only Windows metadata with explicit application-owned browser data. | neyvia |
| [backend.chromium_review](modules/backend.chromium_review/README.md) | Small installed-desktop CDP renderer for observational Preview reviews. | neyvia |
| [backend.cl.__init__](modules/backend.cl.__init__/README.md) | Connected Language 1: shared, typed agent-facing state and actions. | neyvia |
| [backend.cl.agents_message_effects](modules/backend.cl.agents_message_effects/README.md) | Prove a message against its fresh successful delivery event. | neyvia |
| [backend.cl.app_open_effects](modules/backend.cl.app_open_effects/README.md) | App aliases complete only when their exact text mounts in the owned renderer. | neyvia |
| [backend.cl.apple_effects](modules/backend.cl.apple_effects/README.md) | Exact Apple build, preview-state and dormant cloud effects for canonical CL. | neyvia |
| [backend.cl.benchmark](modules/backend.cl.benchmark/README.md) | Paired CL/JSON/no-manual model action loops and outcome-based five-layer scores. | neyvia |
| [backend.cl.benchmark11](modules/backend.cl.benchmark11/README.md) | Frozen CL 1.1 cohorts, independent outcomes and honest bootstrap gates. | neyvia |
| [backend.cl.benchmark11_fixtures](modules/backend.cl.benchmark11_fixtures/README.md) | Frozen CL 1.1 tasks over production gateways and disposable real applications. | neyvia |
| [backend.cl.benchmark_fixtures](modules/backend.cl.benchmark_fixtures/README.md) | Disposable five-layer fixtures backed by production Notes/Files/UIA/browser tools. | neyvia |
| [backend.cl.benchmark_provider](modules/backend.cl.benchmark_provider/README.md) | Isolated Codex proposals with actual usage, raw events and no model fallback. | neyvia |
| [backend.cl.browser_effects](modules/backend.cl.browser_effects/README.md) | Fresh Obscura tab and DOM effects for the integrated browser owner. | neyvia |
| [backend.cl.codecs](modules/backend.cl.codecs/README.md) | Semantic CL projections over owner state, without changing archival payloads. | neyvia |
| [backend.cl.comments_effects](modules/backend.cl.comments_effects/README.md) | CL comments actions are checked against fresh immutable store events. | neyvia |
| [backend.cl.configuration_effects](modules/backend.cl.configuration_effects/README.md) | Fresh owner checks for workspace setup, dictation policy and script extraction. | neyvia |
| [backend.cl.coordination_effects](modules/backend.cl.coordination_effects/README.md) | Owner-bound receipt proof for the local workflow recorder. | neyvia |
| [backend.cl.creative_effects](modules/backend.cl.creative_effects/README.md) | Fresh owner checks for local task contracts and reported attention trials. | neyvia |
| [backend.cl.device_effects](modules/backend.cl.device_effects/README.md) | Completed paired-PC file effects, proved from both endpoints afresh. | neyvia |
| [backend.cl.document_effects](modules/backend.cl.document_effects/README.md) | Fetched documents, PDF and Scroll Study effects over fresh owning observers. | neyvia |
| [backend.cl.durable_effects](modules/backend.cl.durable_effects/README.md) | Fresh owner observations for retained projects, missions, and Night Shift. | neyvia |
| [backend.cl.effects](modules/backend.cl.effects/README.md) | Subject-bound effect observers for CL actions. | neyvia |
| [backend.cl.efficient_runner](modules/backend.cl.efficient_runner/README.md) | Procedures-first, bounded CL proposal execution over the production gateway. | neyvia |
| [backend.cl.environment_effects](modules/backend.cl.environment_effects/README.md) | Fresh pinned-environment identity and declared task output byte witnesses. | neyvia |
| [backend.cl.expressions](modules/backend.cl.expressions/README.md) | Bounded CL check expressions, with read-only observers and no eval. | neyvia |
| [backend.cl.fixcl4_browser_sdk_effects](modules/backend.cl.fixcl4_browser_sdk_effects/README.md) | Actual owned browser sessions, SDK runtime verification and LAYA receipts. | neyvia |
| [backend.cl.fixcl4_evaluation_effects](modules/backend.cl.fixcl4_evaluation_effects/README.md) | Fresh witnesses for bounded questions, frozen curricula and measured lab work. | neyvia |
| [backend.cl.fixcl4_evolver_effects](modules/backend.cl.fixcl4_evolver_effects/README.md) | Evolver completion requires actual paired compiler work, not queued jobs. | neyvia |
| [backend.cl.fixcl4_host_effects](modules/backend.cl.fixcl4_host_effects/README.md) | Fresh managed-process observations and explicit plugin byte postconditions. | neyvia |
| [backend.cl.fixcl4_media_effects](modules/backend.cl.fixcl4_media_effects/README.md) | Fresh byte-bound preview, video and skill revision effects. | neyvia |
| [backend.cl.fixcl4_render_effects](modules/backend.cl.fixcl4_render_effects/README.md) | Effects witnessed by the mounted shell, never by a queued bus ACK. | neyvia |
| [backend.cl.fixcl4_service_effects](modules/backend.cl.fixcl4_service_effects/README.md) | Exact service observations and durable setup/native-check effects. | neyvia |
| [backend.cl.frontier_effects](modules/backend.cl.frontier_effects/README.md) | Dispatch additional CL effects to the module that owns each observer. | neyvia |
| [backend.cl.frontier_local_effects](modules/backend.cl.frontier_local_effects/README.md) | Fresh UI-bus postconditions for local chat and sidebar actions. | neyvia |
| [backend.cl.gamedev_effects](modules/backend.cl.gamedev_effects/README.md) | Project package and affinity-bound native request observers for CL. | neyvia |
| [backend.cl.goals](modules/backend.cl.goals/README.md) | CL 1.1 observer goals: bounded Python expressions without eval or imports. | neyvia |
| [backend.cl.host](modules/backend.cl.host/README.md) | CL 1.1 host context over existing dispatch, permissions and observer contracts. | neyvia |
| [backend.cl.integration](modules/backend.cl.integration/README.md) | Adapt the grounded manual archive and original gateway to CL 1.1. | proofs |
| [backend.cl.integrity_effects](modules/backend.cl.integrity_effects/README.md) | Fresh artifact verification; never promote a capsule's semantic claim. | neyvia |
| [backend.cl.jobs_effects](modules/backend.cl.jobs_effects/README.md) | Exact durable supervision effects; admission never proves provider execution. | neyvia |
| [backend.cl.lab_context_effects](modules/backend.cl.lab_context_effects/README.md) | Fresh isolated competition measurements and lossless context compaction. | neyvia |
| [backend.cl.manual_effects](modules/backend.cl.manual_effects/README.md) | Quarantined manual edits verified from the owning version and patch stores. | neyvia |
| [backend.cl.manual_execution_effects](modules/backend.cl.manual_execution_effects/README.md) | Fresh manual-run effects and exact compiler/recovery provenance admission. | neyvia |
| [backend.cl.manual_projection_effects](modules/backend.cl.manual_projection_effects/README.md) | Exact immutable projections and fresh source-bound observation artifacts. | neyvia |
| [backend.cl.manual_routing](modules/backend.cl.manual_routing/README.md) | Current-source owner hints when the release's compiled index has drifted. | neyvia |
| [backend.cl.manuals](modules/backend.cl.manuals/README.md) | Authored CL manuals compile to the existing safe, typed manual runner. | proofs |
| [backend.cl.measured_context](modules/backend.cl.measured_context/README.md) | Generated by scripts/build_cl_context.py; exact local o200k measurements. | neyvia |
| [backend.cl.memory_effects](modules/backend.cl.memory_effects/README.md) | CL memory mutations require exact fresh scoped owner postconditions. | neyvia |
| [backend.cl.parallel_effects](modules/backend.cl.parallel_effects/README.md) | Subject-bound Parallel effects: reread durable state, broker runs and Git. | neyvia |
| [backend.cl.parser](modules/backend.cl.parser/README.md) | Connected Language 1 lexical/document and action parser; no eval or imports. | neyvia |
| [backend.cl.pdf_effects](modules/backend.cl.pdf_effects/README.md) | Fresh PDF renderer state and source conservation predicates. | pdf |
| [backend.cl.protocol](modules/backend.cl.protocol/README.md) | The single CL tool over the existing native permission and manual seams. | neyvia |
| [backend.cl.provider11](modules/backend.cl.provider11/README.md) | CL 1.1 provider transport: explicit routes, raw events, bounded native sessions. | neyvia |
| [backend.cl.provider_effects](modules/backend.cl.provider_effects/README.md) | Fresh provider owner observations; scheduling is never model completion. | neyvia |
| [backend.cl.record_effects](modules/backend.cl.record_effects/README.md) | Fresh local record and frozen-artifact checks; no inferred model quality. | neyvia |
| [backend.cl.remote_effects](modules/backend.cl.remote_effects/README.md) | The remote bot API observes existing consent; it grants no remote input. | neyvia |
| [backend.cl.renderer](modules/backend.cl.renderer/README.md) | Injection-safe CL observations, immutable projections, and context aliases. | neyvia |
| [backend.cl.renderer_effects](modules/backend.cl.renderer_effects/README.md) | Pane effects are renderer observations, never merely queued UI events. | neyvia |
| [backend.cl.runtime](modules/backend.cl.runtime/README.md) | CL execution adapts syntax to existing tools; it never grants authority. | neyvia |
| [backend.cl.schema](modules/backend.cl.schema/README.md) | Lossless JSON Schema and MCP bridges for Connected Language. | neyvia |
| [backend.cl.scroll_effects](modules/backend.cl.scroll_effects/README.md) | Fresh Scroll Study store, archive and preview predicates. | neyvia |
| [backend.cl.semantic_effects](modules/backend.cl.semantic_effects/README.md) | Subject-bound observations for durable semantic native actions. | neyvia |
| [backend.cl.state](modules/backend.cl.state/README.md) | CL view of the existing immutable observer stream; JSON remains archival. | neyvia |
| [backend.cl.terminal_effects](modules/backend.cl.terminal_effects/README.md) | Fresh, integrity-checked terminal completion; task effects still require G. | neyvia |
| [backend.cl.terminal_receipts](modules/backend.cl.terminal_receipts/README.md) | Ground synchronous command observations in the existing native action journal. | neyvia |
| [backend.cl.tokens](modules/backend.cl.tokens/README.md) | CL token measurements. Claude estimates are never reported as exact counts. | neyvia |
| [backend.cl.turn_context](modules/backend.cl.turn_context/README.md) | Deterministic, measured context for a CL proposal loop. | neyvia |
| [backend.cl.validator](modules/backend.cl.validator/README.md) | Practical CL conformance checks; unknown verification is not success. | neyvia |
| [backend.cl.work_effects](modules/backend.cl.work_effects/README.md) | Exact persisted-state checks for one adaptive-work identity per CL action. | neyvia |
| [backend.cl_deliverables](modules/backend.cl_deliverables/README.md) | Deliverable observers shared by the CL-Skill CLI and host completion gate. | neyvia |
| [backend.cl_skill](modules/backend.cl_skill/README.md) | CL-Skill check runner (docs/standard/cl-skill.md). | proofs |
| [backend.claude_code_activity](modules/backend.claude_code_activity/README.md) | ``neyvia.activity``, ``neyvia.message`` and ``neyvia.claude.open_cli``: awareness and contact between agents. | neyvia |
| [backend.claude_code_cli](modules/backend.claude_code_cli/README.md) | Open Claude Code's real CLI for the person: ``neyvia.claude.open_cli`` and its UI button. | neyvia |
| [backend.claude_code_host](modules/backend.claude_code_host/README.md) | Neyvia's side of the Claude Code mod: the endpoints under ``/api/ui/claude-code/mod/`` (plan 29 section A). | neyvia |
| [backend.claude_code_mods](modules/backend.claude_code_mods/README.md) | Neyvia's tools as a Claude Code plugin (``plugins/neyvia``): the setting, the launch environment, the mod's reports. | agents |
| [backend.claude_mod](modules/backend.claude_mod/README.md) | "Add Neyvia to my Claude Code": install, update and remove the Neyvia plugin for the person's own Claude Code. | neyvia |
| [backend.cli](modules/backend.cli/README.md) | Provides backend / cli in Neyvia. | proofs |
| [backend.cli_catalog](modules/backend.cli_catalog/README.md) | Catalogue of optional CLIs, for the setup screen a nontechnical user sees. | neyvia |
| [backend.cli_installer](modules/backend.cli_installer/README.md) | Crash-aware per-user installer for optional npm-backed agent CLIs. | neyvia |
| [backend.cluster](modules/backend.cluster/README.md) | Provides backend / cluster in Neyvia. | neyvia |
| [backend.codex_app_server_stream](modules/backend.codex_app_server_stream/README.md) | One bounded Codex app-server turn with observable answer deltas. | neyvia |
| [backend.codex_import](modules/backend.codex_import/README.md) | Provides backend / codex_import in Neyvia. | neyvia |
| [backend.codex_local_oauth_helper](modules/backend.codex_local_oauth_helper/README.md) | Provides backend / codex_local_oauth_helper in Neyvia. | neyvia |
| [backend.codex_plugin_access](modules/backend.codex_plugin_access/README.md) | Native execution of portable, enabled Codex MCP servers. | neyvia |
| [backend.codex_skill_access](modules/backend.codex_skill_access/README.md) | On-demand, read-only access to installed Codex skill instructions. | neyvia |
| [backend.codex_skills](modules/backend.codex_skills/README.md) | Install Neyvia's Codex skills into ``$CODEX_HOME/skills/neyvia-*`` and keep them current. | neyvia |
| [backend.collaboration_prompt](modules/backend.collaboration_prompt/README.md) | One collaboration contract for native and external chat harnesses. | neyvia |
| [backend.communication_archive](modules/backend.communication_archive/README.md) | Provides backend / communication_archive in Neyvia. | neyvia |
| [backend.compaction_model](modules/backend.compaction_model/README.md) | Bookkeeping model calls, isolated from execution and fully accounted for. | neyvia |
| [backend.compaction_policy](modules/backend.compaction_policy/README.md) | Route-specific context admission. Pricing never silently becomes a stop budget. | neyvia |
| [backend.compat](modules/backend.compat/README.md) | Which Neyvia API and SDK each installed mod or app was written for. | neyvia |
| [backend.compiled_tool_maps](modules/backend.compiled_tool_maps/README.md) | Run-scoped immutable compiled maps and version-bound provider selections. | neyvia |
| [backend.component_install](modules/backend.component_install/README.md) | Shared staging, hashing and receipt helpers for Neyvia's managed components. | neyvia |
| [backend.components](modules/backend.components/README.md) | One list of everything Neyvia installs or keeps current, with real state and one-click actions. | neyvia |
| [backend.computer_use_twin](modules/backend.computer_use_twin/README.md) | Isolated structured Computer Use comparison and worker-dispatch backend. | neyvia |
| [backend.computer_use_verifier](modules/backend.computer_use_verifier/README.md) | Primary change-verification facade for structured N-E-Y-V-I-A Computer Use. | neyvia |
| [backend.connected_app_chats](modules/backend.connected_app_chats/README.md) | Durable, idempotent dispatch for same-session connected app messages. | neyvia |
| [backend.connected_app_window](modules/backend.connected_app_window/README.md) | Consent-driven, single-window remote control for the installed Codex/Claude apps. | neyvia |
| [backend.connected_chat_context](modules/backend.connected_chat_context/README.md) | Public context counters reported by the source app, never inferred from text. | neyvia |
| [backend.connected_chat_media](modules/backend.connected_chat_media/README.md) | Authenticated media referenced by an existing public chat message. | neyvia |
| [backend.connected_chrome](modules/backend.connected_chrome/README.md) | Operate the user's authenticated Chrome through the DevTools Protocol. | neyvia |
| [backend.connected_chrome_policy](modules/backend.connected_chrome_policy/README.md) | Approval boundaries for actions taken in the user's connected browser. | neyvia |
| [backend.connected_claude_chats](modules/backend.connected_claude_chats/README.md) | Connected chat adapter for local Claude Code sessions. | neyvia |
| [backend.connected_codex_chats](modules/backend.connected_codex_chats/README.md) | Read and continue existing Codex chats through the supported app-server API. | neyvia |
| [backend.connected_device_bridge](modules/backend.connected_device_bridge/README.md) | Provides backend / connected_device_bridge in Neyvia. | neyvia |
| [backend.connected_device_inventory](modules/backend.connected_device_inventory/README.md) | Read the local tailnet roster without treating network presence as control. | neyvia |
| [backend.connected_sessions.__init__](modules/backend.connected_sessions.__init__/README.md) | Live connected sessions: Claude Code, Codex and OpenCode, continued in place. | neyvia |
| [backend.connected_sessions.api](modules/backend.connected_sessions.api/README.md) | HTTP and command surface of the connected-sessions broker. | neyvia |
| [backend.connected_sessions.attachments](modules/backend.connected_sessions.attachments/README.md) | Files attached to a message: saved on this PC and named in the message for the agent to open. | neyvia |
| [backend.connected_sessions.broker](modules/backend.connected_sessions.broker/README.md) | The live service behind connected sessions. | neyvia |
| [backend.connected_sessions.claude](modules/backend.connected_sessions.claude/README.md) | Claude Code adapter for connected sessions. | neyvia |
| [backend.connected_sessions.claude_hook](modules/backend.connected_sessions.claude_hook/README.md) | Claude Code hook used by Neyvia's plan-limits (terminal) mode. Standard library only. | neyvia |
| [backend.connected_sessions.claude_items](modules/backend.connected_sessions.claude_items/README.md) | Pure helpers that turn Claude Code data into connected-session items. | neyvia |
| [backend.connected_sessions.claude_login](modules/backend.connected_sessions.claude_login/README.md) | Claude Code's own sign-in, finished from any device. | neyvia |
| [backend.connected_sessions.claude_plan_history](modules/backend.connected_sessions.claude_plan_history/README.md) | Selective historical checklist scan; ordinary transcript text is never JSON-decoded here. | neyvia |
| [backend.connected_sessions.claude_stream](modules/backend.connected_sessions.claude_stream/README.md) | One Claude Code turn: a persistent stream-json CLI process, its control protocol and the live events. | neyvia |
| [backend.connected_sessions.claude_terminal](modules/backend.connected_sessions.claude_terminal/README.md) | One Claude Code turn in its normal interactive mode, in a hidden terminal (the "plan limits" route). | host-runtime |
| [backend.connected_sessions.claude_transcript](modules/backend.connected_sessions.claude_transcript/README.md) | Incremental, tail-first reader for Claude Code session transcripts (``~/.claude/projects``). | neyvia |
| [backend.connected_sessions.claude_trust](modules/backend.connected_sessions.claude_trust/README.md) | Recognize only Claude Code's startup folder-trust menu; never answer it automatically. | neyvia |
| [backend.connected_sessions.claude_usage](modules/backend.connected_sessions.claude_usage/README.md) | Incremental per-turn Claude token spend, using the Usage pane's transcript interpretation. | neyvia |
| [backend.connected_sessions.codex](modules/backend.connected_sessions.codex/README.md) | Codex adapter for connected sessions. | neyvia |
| [backend.connected_sessions.codex_items](modules/backend.connected_sessions.codex_items/README.md) | Map Codex app-server records to connected-session shapes. | proofs |
| [backend.connected_sessions.codex_rpc](modules/backend.connected_sessions.codex_rpc/README.md) | One long-lived ``codex app-server`` JSON-RPC connection over stdio. | neyvia |
| [backend.connected_sessions.codex_stream](modules/backend.connected_sessions.codex_stream/README.md) | Turn one thread's live app-server notifications into connected-session events. | neyvia |
| [backend.connected_sessions.codex_writer](modules/backend.connected_sessions.codex_writer/README.md) | Read-only probes of Codex's cross-process writer lock (never touch rollouts). | neyvia |
| [backend.connected_sessions.dashboard](modules/backend.connected_sessions.dashboard/README.md) | Everything working right now, in one read: the agents dashboard (UI) and ``neyvia.agents.state`` (bot). | neyvia |
| [backend.connected_sessions.events](modules/backend.connected_sessions.events/README.md) | The live stream's memory: a bounded ring of cursor-stamped events with blocking reads. | neyvia |
| [backend.connected_sessions.folder_jobs](modules/backend.connected_sessions.folder_jobs/README.md) | Durable, hidden worktree checkout jobs independent of the request/service lifetime. | neyvia |
| [backend.connected_sessions.folders](modules/backend.connected_sessions.folders/README.md) | Where a new chat can run: recent folders, local git projects, GitHub repos. | neyvia |
| [backend.connected_sessions.forward](modules/backend.connected_sessions.forward/README.md) | Forward a connected-sessions command from the desktop bridge to the persistent PC service. | neyvia |
| [backend.connected_sessions.live_limits](modules/backend.connected_sessions.live_limits/README.md) | Read quotas through the installed CLIs. No credential files or raw terminal receipts. | neyvia |
| [backend.connected_sessions.model](modules/backend.connected_sessions.model/README.md) | Shared shapes for connected app sessions (Claude Code, Codex, OpenCode). | neyvia |
| [backend.connected_sessions.neyvia](modules/backend.connected_sessions.neyvia/README.md) | Neyvia's own conversations (Native and Hybrid) as connected sessions. | neyvia |
| [backend.connected_sessions.neyvia_items](modules/backend.connected_sessions.neyvia_items/README.md) | Neyvia chat turns and chat-stream events as connected-session items. | neyvia |
| [backend.connected_sessions.neyvia_options](modules/backend.connected_sessions.neyvia_options/README.md) | What Neyvia offers for a chat: runtimes, models and permission modes. | neyvia |
| [backend.connected_sessions.opencode](modules/backend.connected_sessions.opencode/README.md) | Native inventory plus supervised OpenCode ACP turns; no extra server port. | neyvia |
| [backend.connected_sessions.opencode_acp](modules/backend.connected_sessions.opencode_acp/README.md) | OpenCode's supported ACP transport, with owner-only permission decisions. | neyvia |
| [backend.connected_sessions.opencode_history](modules/backend.connected_sessions.opencode_history/README.md) | Project OpenCode's saved native parts without losing tools or edit receipts. | neyvia |
| [backend.connected_sessions.plan](modules/backend.connected_sessions.plan/README.md) | An agent's own checklist, as data: Claude Code's TodoWrite and task tools, Codex's plan, Neyvia runs. | neyvia |
| [backend.connected_sessions.plan_limits](modules/backend.connected_sessions.plan_limits/README.md) | Plan-limit windows (5-hour, weekly) as the apps themselves last reported them. Nothing is estimated. | proofs |
| [backend.connected_sessions.registry](modules/backend.connected_sessions.registry/README.md) | Adapter registry for connected sessions, and the small calls around it. | neyvia |
| [backend.connected_sessions.runs](modules/backend.connected_sessions.runs/README.md) | Durable run records for connected sessions, in ``.agent_control/connected_chats.sqlite3``. | neyvia |
| [backend.connected_sessions.seen](modules/backend.connected_sessions.seen/README.md) | Per-session "last seen" markers, so the session list can show an unread dot. | neyvia |
| [backend.connected_sessions.sidebar_cleanup](modules/backend.connected_sessions.sidebar_cleanup/README.md) | Observe real workspace/job safety before reversible sidebar cleanup. | neyvia |
| [backend.connected_sessions.transparency](modules/backend.connected_sessions.transparency/README.md) | Shared transparency vocabulary; only text actually exposed by a harness is shown. | neyvia |
| [backend.connected_sessions.work_board](modules/backend.connected_sessions.work_board/README.md) | Turn-scoped work awareness shared by connected harnesses. | neyvia |
| [backend.connected_sessions.workspace](modules/backend.connected_sessions.workspace/README.md) | Git and GitHub state for a connected session's folder. | neyvia |
| [backend.connections_install](modules/backend.connections_install/README.md) | Consented, hidden harness installation; progress and receipts share the Connections card. | neyvia |
| [backend.constitution](modules/backend.constitution/README.md) | Provides backend / constitution in Neyvia. | neyvia |
| [backend.context_engine](modules/backend.context_engine/README.md) | Provides backend / context_engine in Neyvia. | neyvia |
| [backend.context_import](modules/backend.context_import/README.md) | Selective, provider-neutral context import with durable lineage. | neyvia |
| [backend.context_manager](modules/backend.context_manager/README.md) | Provides backend / context_manager in Neyvia. | neyvia |
| [backend.context_microkernel](modules/backend.context_microkernel/README.md) | Phase 0/1 Context Microkernel glue: metrics, unified bundles, cache-control. | neyvia |
| [backend.context_window](modules/backend.context_window/README.md) | Bound model replay without deleting durable session history or splitting tools. | neyvia |
| [backend.contextual_learning](modules/backend.contextual_learning/README.md) | Context-bound correction history and observable attention experiments. | neyvia |
| [backend.continuity_policy](modules/backend.continuity_policy/README.md) | Durable, risk-aware mission continuity for Neyvia. | neyvia |
| [backend.contract_build_cache](modules/backend.contract_build_cache/README.md) | Source- and artifact-bound cache for a successful Vite build receipt. | neyvia |
| [backend.contract_coverage](modules/backend.contract_coverage/README.md) | Declared path classes and outcome ownership from the track/mod registry. | neyvia |
| [backend.contract_diff](modules/backend.contract_diff/README.md) | Git-backed changed-line inventory for impact-scoped contract coverage. | neyvia |
| [backend.contract_execution](modules/backend.contract_execution/README.md) | Low-overhead Python line execution receipts for measured contract coverage. | neyvia |
| [backend.contract_gate](modules/backend.contract_gate/README.md) | Select authored proof outcomes through source sites and module dependencies. | neyvia |
| [backend.contract_measurements](modules/backend.contract_measurements/README.md) | Reuse source-bound execution of passing outcomes, never declared ownership. | neyvia |
| [backend.contract_ratchet](modules/backend.contract_ratchet/README.md) | Pure release admission and monotonic behavior-debt baseline checks. | neyvia |
| [backend.contract_resources](modules/backend.contract_resources/README.md) | Cross-process resource guards for bounded contract workers. | neyvia |
| [backend.contract_web_reach](modules/backend.contract_web_reach/README.md) | Report source files statically reachable from passing, source-bound UI journeys. | neyvia |
| [backend.crashproof](modules/backend.crashproof/README.md) | Provides backend / crashproof in Neyvia. | neyvia |
| [backend.creative_tools](modules/backend.creative_tools/README.md) | Workspace-scoped tool entry points for adaptive work and creative evidence. | neyvia |
| [backend.cu_acceptance](modules/backend.cu_acceptance/README.md) | Standalone structured Computer Use acceptance for N-E-Y-V-I-A. | neyvia |
| [backend.cua_adaptation](modules/backend.cua_adaptation/README.md) | First-use UIA exploration and evidence-grounded, workspace-only flow learning. | neyvia |
| [backend.cua_bureau](modules/backend.cua_bureau/README.md) | Hidden-first Windows virtual desktop fallback through maintained winvd. | neyvia |
| [backend.cua_chromium](modules/backend.cua_chromium/README.md) | DOM fallback for a fresh, job-owned Chromium profile and local document. | neyvia |
| [backend.cua_desktop](modules/backend.cua_desktop/README.md) | Private desktop and previsibility-contained fallback; never switches input. | neyvia |
| [backend.cua_fast](modules/backend.cua_fast/README.md) | Deadline-bounded native CUA. COM objects never leave their owning MTA lane. | neyvia |
| [backend.cua_guard](modules/backend.cua_guard/README.md) | Fail-closed input-desktop observation for isolated computer-use sessions. | neyvia |
| [backend.cua_launch](modules/backend.cua_launch/README.md) | Process-local CUA registration; never changes a user's CLI settings. | neyvia |
| [backend.cua_native](modules/backend.cua_native/README.md) | Hidden, bounded JSONL bridge to the installed Windows UI Automation runtime. | neyvia |
| [backend.cua_native_procedures](modules/backend.cua_native_procedures/README.md) | Host-bound native application tools for grounded manual learning. | neyvia |
| [backend.cua_office](modules/backend.cua_office/README.md) | Hidden, new-instance Office automation on token-owned disposable documents. | neyvia |
| [backend.cua_parked](modules/backend.cua_parked/README.md) | Fail-closed input-desktop fallback, contained before any window visibility. | neyvia |
| [backend.cua_upstream](modules/backend.cua_upstream/README.md) | Private, process-owned MIT Cua Driver runtime; no global installation or daemon. | neyvia |
| [backend.cue_memory](modules/backend.cue_memory/README.md) | Private cue memory. The caller must supply a server-bound scope, never tool args. | neyvia |
| [backend.cursor_bridge](modules/backend.cursor_bridge/README.md) | Provides backend / cursor_bridge in Neyvia. | neyvia |
| [backend.dashboard](modules/backend.dashboard/README.md) | Provides backend / dashboard in Neyvia. | neyvia |
| [backend.debugger_bundle](modules/backend.debugger_bundle/README.md) | Provides backend / debugger_bundle in Neyvia. | neyvia |
| [backend.delivery_receipt](modules/backend.delivery_receipt/README.md) | Provides backend / delivery_receipt in Neyvia. | neyvia |
| [backend.demo_button](modules/backend.demo_button/README.md) | Provides backend / demo_button in Neyvia. | neyvia |
| [backend.demo_runner](modules/backend.demo_runner/README.md) | Provides backend / demo_runner in Neyvia. | neyvia |
| [backend.dependency_inventory](modules/backend.dependency_inventory/README.md) | Offline canonical dependency inventory used by updater preflight. | neyvia |
| [backend.desktop_bridge](modules/backend.desktop_bridge/README.md) | Bounded Tauri bridge into Neyvia's durable Python backend. | neyvia |
| [backend.desktop_controller](modules/backend.desktop_controller/README.md) | Durable, bounded request queue for controlling the local Neyvia desktop. | neyvia |
| [backend.desktop_gateway](modules/backend.desktop_gateway/README.md) | Provides backend / desktop_gateway in Neyvia. | neyvia |
| [backend.doc_ingestion](modules/backend.doc_ingestion/README.md) | Provides backend / doc_ingestion in Neyvia. | neyvia |
| [backend.durability](modules/backend.durability/README.md) | Provides backend / durability in Neyvia. | neyvia |
| [backend.ecosystem_fabric](modules/backend.ecosystem_fabric/README.md) | Provides backend / ecosystem_fabric in Neyvia. | neyvia |
| [backend.edge_contracts](modules/backend.edge_contracts/README.md) | Bounded, reproducible adversarial campaigns against the real contract host. | neyvia |
| [backend.edge_fixture_artifact_manual](modules/backend.edge_fixture_artifact_manual/README.md) | Owned host observations and local artifact/receipt fixtures. | neyvia |
| [backend.edge_fixture_c7d_adapters](modules/backend.edge_fixture_c7d_adapters/README.md) | Real local adapter bytes, object history and publication policy observations. | neyvia |
| [backend.edge_fixture_c7d_capability](modules/backend.edge_fixture_c7d_capability/README.md) | Exact C7d capability and support fixtures, below rendering authority. | neyvia |
| [backend.edge_fixture_c7d_codex](modules/backend.edge_fixture_c7d_codex/README.md) | Confined Node JSON-RPC peer exercises host semantics, never a provider/model. | neyvia |
| [backend.edge_fixture_c7d_control](modules/backend.edge_fixture_c7d_control/README.md) | C7d exact control/runtime boundaries on owned data. | neyvia |
| [backend.edge_fixture_c7d_control_completion](modules/backend.edge_fixture_c7d_control_completion/README.md) | Exact remaining control/runtime observations in guarded disposable state. | neyvia |
| [backend.edge_fixture_c7d_desktop](modules/backend.edge_fixture_c7d_desktop/README.md) | C7d owned desktop, runtime and installer adversarial observations. | neyvia |
| [backend.edge_fixture_c7d_engine](modules/backend.edge_fixture_c7d_engine/README.md) | Remaining C7d local engine and harness owner observations. | neyvia |
| [backend.edge_fixture_c7d_host_actions](modules/backend.edge_fixture_c7d_host_actions/README.md) | Generated native action attempts, durable replay and receipt projection. | neyvia |
| [backend.edge_fixture_c7d_local](modules/backend.edge_fixture_c7d_local/README.md) | Owned local completion fixtures, with exact invariant/effect bindings. | neyvia |
| [backend.edge_fixture_c7d_mission_completion](modules/backend.edge_fixture_c7d_mission_completion/README.md) | Exact mission completion fixtures; local simulations never prove execution. | neyvia |
| [backend.edge_fixture_c7d_native_commands](modules/backend.edge_fixture_c7d_native_commands/README.md) | Actual local native session and signed operator authority edge fixtures. | neyvia |
| [backend.edge_fixture_c7d_native_completion](modules/backend.edge_fixture_c7d_native_completion/README.md) | Exact Native completion effects in disposable state, without model execution. | neyvia |
| [backend.edge_fixture_c7d_projection](modules/backend.edge_fixture_c7d_projection/README.md) | Exact local mission projection edges and actual attachment read denial. | neyvia |
| [backend.edge_fixture_c7d_provider_marks](modules/backend.edge_fixture_c7d_provider_marks/README.md) | Current provider-vector owner calls and actual React server markup. | neyvia |
| [backend.edge_fixture_c7d_providers](modules/backend.edge_fixture_c7d_providers/README.md) | Confined provider host semantics; supplied protocol inputs are never model proof. | neyvia |
| [backend.edge_fixture_c7d_rendered](modules/backend.edge_fixture_c7d_rendered/README.md) | Fresh native browser journeys in the registered host, never receipt replay. | neyvia |
| [backend.edge_fixture_c7d_sessions](modules/backend.edge_fixture_c7d_sessions/README.md) | Remaining session contracts on generated state and owned local transports. | neyvia |
| [backend.edge_fixture_c7d_syncthing](modules/backend.edge_fixture_c7d_syncthing/README.md) | Actual isolated, pinned Syncthing owner observations; never configured NAS. | neyvia |
| [backend.edge_fixture_c7d_ui](modules/backend.edge_fixture_c7d_ui/README.md) | Inspected UI argument models with independent effects, never rendered proof. | neyvia |
| [backend.edge_fixture_c7d_ui_control](modules/backend.edge_fixture_c7d_ui_control/README.md) | Exact supplied-input control projections; no rendered or runtime proof. | neyvia |
| [backend.edge_fixture_c7d_ui_settings](modules/backend.edge_fixture_c7d_ui_settings/README.md) | Settings argument and supplied-storage behavior, explicitly never rendered proof. | neyvia |
| [backend.edge_fixture_c7d_verification](modules/backend.edge_fixture_c7d_verification/README.md) | Production local verification, measurement and artifact fixtures. | neyvia |
| [backend.edge_fixture_c7d_wz](modules/backend.edge_fixture_c7d_wz/README.md) | Exact local WZ boundary fixtures; generated inputs never imply remote proof. | neyvia |
| [backend.edge_fixture_capabilities](modules/backend.edge_fixture_capabilities/README.md) | Generated capability feature journeys against real local production owners. | neyvia |
| [backend.edge_fixture_capability_models](modules/backend.edge_fixture_capability_models/README.md) | Real checked capability model calls on generated, supplied snapshots. | neyvia |
| [backend.edge_fixture_catalog](modules/backend.edge_fixture_catalog/README.md) | Reviewed feature builders and honest per-contract/category obligations. | neyvia |
| [backend.edge_fixture_chat_shell](modules/backend.edge_fixture_chat_shell/README.md) | Generated chat trace, recovery, sidebar and shell bus feature witnesses. | neyvia |
| [backend.edge_fixture_commands_adverse](modules/backend.edge_fixture_commands_adverse/README.md) | Adverse durable-effect fixtures for native device command contracts. | neyvia |
| [backend.edge_fixture_control](modules/backend.edge_fixture_control/README.md) | Generated control-room and local harness feature mutations. | neyvia |
| [backend.edge_fixture_control_remaining](modules/backend.edge_fixture_control_remaining/README.md) | Exact remaining control/intent/runtime mutations in disposable local state. | neyvia |
| [backend.edge_fixture_core](modules/backend.edge_fixture_core/README.md) | Generated durable conversation and synthetic account-session journeys. | neyvia |
| [backend.edge_fixture_engine](modules/backend.edge_fixture_engine/README.md) | Generated local engine, journal and adapter fixtures; no enrolled credentials. | neyvia |
| [backend.edge_fixture_frontend](modules/backend.edge_fixture_frontend/README.md) | Generated image/PDF model scenarios; no rendering or provider claim. | neyvia |
| [backend.edge_fixture_host_runtime](modules/backend.edge_fixture_host_runtime/README.md) | Generated host/runtime journeys with confined files, SQLite and real HTTP. | neyvia |
| [backend.edge_fixture_local](modules/backend.edge_fixture_local/README.md) | Generated, disposable feature fixtures for local semantic contract families. | neyvia |
| [backend.edge_fixture_mcp_adverse](modules/backend.edge_fixture_mcp_adverse/README.md) | Focused MCP-adjacent event boundary fixtures for C7d. | neyvia |
| [backend.edge_fixture_missions](modules/backend.edge_fixture_missions/README.md) | Generated mission effects and frontend state transitions in owned scratch. | neyvia |
| [backend.edge_fixture_mobile](modules/backend.edge_fixture_mobile/README.md) | Generated local mobile authoring, packaging and checked byte-transfer fixtures. | neyvia |
| [backend.edge_fixture_models](modules/backend.edge_fixture_models/README.md) | Adversarial model-route and callable-compiler feature journeys. | neyvia |
| [backend.edge_fixture_native](modules/backend.edge_fixture_native/README.md) | Generative Native store fixtures with independently read durable effects. | neyvia |
| [backend.edge_fixture_preferences_skills](modules/backend.edge_fixture_preferences_skills/README.md) | Owned skill, SDK and preference workflows with generated perturbations. | neyvia |
| [backend.edge_fixture_providers](modules/backend.edge_fixture_providers/README.md) | Generative provider fixtures on owned files, pipes and operating-system locks. | neyvia |
| [backend.edge_fixture_pure](modules/backend.edge_fixture_pure/README.md) | Generated semantic fixtures for production parsers and local browser state. | neyvia |
| [backend.edge_fixture_scheduler](modules/backend.edge_fixture_scheduler/README.md) | Generated feature fixtures for durable coordination and local worker effects. | neyvia |
| [backend.edge_fixture_sessions](modules/backend.edge_fixture_sessions/README.md) | Generative connected-session fixtures on isolated local files and real stores. | neyvia |
| [backend.edge_fixture_surfaces](modules/backend.edge_fixture_surfaces/README.md) | Generative presentation-model and local control fixtures. | neyvia |
| [backend.edge_fixture_ui_planning_local](modules/backend.edge_fixture_ui_planning_local/README.md) | Generated local planning, compiler and durable view fixtures. | neyvia |
| [backend.edge_fixture_ui_remaining](modules/backend.edge_fixture_ui_remaining/README.md) | Generated production frontend-model fixtures, explicitly below rendering authority. | neyvia |
| [backend.edge_journeys](modules/backend.edge_journeys/README.md) | Real local effect/restart journeys for the adversarial contract campaign. | neyvia |
| [backend.edge_live_observations](modules/backend.edge_live_observations/README.md) | Campaign-local native observations; retained receipt bytes cannot admit cases. | neyvia |
| [backend.edge_notes](modules/backend.edge_notes/README.md) | Adversarial Notes/Files journeys on disposable production state, not a test suite. | neyvia |
| [backend.efficiency_cascade](modules/backend.efficiency_cascade/README.md) | Validated script → transition memory → System 1 → cache → Luna → Sol routing. | neyvia |
| [backend.efficient_workflow](modules/backend.efficient_workflow/README.md) | Four explicit, bounded lanes over the existing durable orchestration graph. | neyvia |
| [backend.encrypted_chat](modules/backend.encrypted_chat/README.md) | Scoped encrypted Matrix chat using a Rust SDK compatibility transport. | neyvia |
| [backend.engine](modules/backend.engine/README.md) | Provides backend / engine in Neyvia. | neyvia |
| [backend.eval](modules/backend.eval/README.md) | Provides backend / eval in Neyvia. | neyvia |
| [backend.evolve_engine](modules/backend.evolve_engine/README.md) | Plan-25 evolving engine: populations, real judges, a move library that grows, an adversary. | neyvia |
| [backend.evolve_gate](modules/backend.evolve_gate/README.md) | Plan-25 target adapter: the P22 release gate (``scripts/gate.py``) as an evolvable task. | neyvia |
| [backend.evolve_moves](modules/backend.evolve_moves/README.md) | LAYA's library of known code moves and known exploits for the plan-25 evolving engine. | neyvia |
| [backend.evolver_core](modules/backend.evolver_core/README.md) | Durable paired text evolution; genomes never carry evaluation authority. | hill-climb |
| [backend.evolver_domains](modules/backend.evolver_domains/README.md) | Real, bounded GPT-6 Luna evaluators for the first Evolver text domains. | hill-climb |
| [backend.evolver_domains_v2](modules/backend.evolver_domains_v2/README.md) | Lead-reviewed adapter repair; v1 judges and rejected receipts stay frozen. | neyvia |
| [backend.evolver_domains_v3](modules/backend.evolver_domains_v3/README.md) | Fresh authority-domain review; reuse only discovery-qualified candidate text. | neyvia |
| [backend.evolver_laya](modules/backend.evolver_laya/README.md) | CPU LAYA architecture binding for the existing frozen text Evolver. | neyvia |
| [backend.evolver_manual_local](modules/backend.evolver_manual_local/README.md) | Deterministic manual compression through the real frozen paired engine. | neyvia |
| [backend.evolver_paul_intent](modules/backend.evolver_paul_intent/README.md) | Evolver domain ``paul_intent``: tune the manual of Paul's model view on his real messages. | neyvia |
| [backend.evolver_transport_v3](modules/backend.evolver_transport_v3/README.md) | Frozen closed-book CLI transport: physical tool-surface exclusion plus audit. | neyvia |
| [backend.execution_ownership](modules/backend.execution_ownership/README.md) | Single-host execution ownership, independent of a browser connection. | neyvia |
| [backend.execution_truth](modules/backend.execution_truth/README.md) | Provides backend / execution_truth in Neyvia. | neyvia |
| [backend.experience_learning](modules/backend.experience_learning/README.md) | Durable experience traces and evidence-gated candidate skill promotion. | neyvia |
| [backend.experiment_studio](modules/backend.experiment_studio/README.md) | Isolated, hash-manifested local experiments without source-tree overwrite. | neyvia |
| [backend.experimental_quality](modules/backend.experimental_quality/README.md) | Sealed, evidence-only quality instruments and counterfactual comparisons. | neyvia |
| [backend.external_chat_inventory](modules/backend.external_chat_inventory/README.md) | Read-only inventory of local Codex, Claude Code, and OpenCode chats. | neyvia |
| [backend.external_cli_bridge](modules/backend.external_cli_bridge/README.md) | Provides backend / external_cli_bridge in Neyvia. | neyvia |
| [backend.feature_suggester](modules/backend.feature_suggester/README.md) | Provides backend / feature_suggester in Neyvia. | neyvia |
| [backend.file_links](modules/backend.file_links/README.md) | Materialize an owned local dependency without requiring symlink privilege. | neyvia |
| [backend.flight_recorder](modules/backend.flight_recorder/README.md) | Provides backend / flight_recorder in Neyvia. | neyvia |
| [backend.fluxio_harness](modules/backend.fluxio_harness/README.md) | Provides backend / fluxio_harness in Neyvia. | neyvia |
| [backend.folder_sync](modules/backend.folder_sync/README.md) | Permissioned Syncthing control with scoped checksums and safe activation. | neyvia |
| [backend.generated.__init__](modules/backend.generated.__init__/README.md) | Schema-derived Neyvia SDK bindings. | neyvia |
| [backend.generated.neyvia_contracts](modules/backend.generated.neyvia_contracts/README.md) | Provides backend / generated / neyvia_contracts in Neyvia. | neyvia |
| [backend.git_reference_adapter](modules/backend.git_reference_adapter/README.md) | Fail-closed, object-only Git reference adapter. | neyvia |
| [backend.github_client](modules/backend.github_client/README.md) | A small GitHub HTTP client that spends as few API requests as it can. | neyvia |
| [backend.github_release_source](modules/backend.github_release_source/README.md) | Resolve Neyvia marketplace applications from GitHub releases. | neyvia |
| [backend.goal_loop](modules/backend.goal_loop/README.md) | Explicit native goal checkpoints; a model reply is not a completion signal. | neyvia |
| [backend.handoff](modules/backend.handoff/README.md) | Provides backend / handoff in Neyvia. | neyvia |
| [backend.harness_auth_inventory](modules/backend.harness_auth_inventory/README.md) | Secret-free, live authentication truth for Neyvia harnesses. | neyvia |
| [backend.harness_batches](modules/backend.harness_batches/README.md) | Bounded prompt batches over the existing durable, isolated Harness jobs. | neyvia |
| [backend.harness_comparison](modules/backend.harness_comparison/README.md) | Deterministic, receipt-backed comparison for installed Neyvia harnesses. | neyvia |
| [backend.harness_execution_capacity](modules/backend.harness_execution_capacity/README.md) | Provides backend / harness_execution_capacity in Neyvia. | neyvia |
| [backend.harness_job_worker](modules/backend.harness_job_worker/README.md) | Provides backend / harness_job_worker in Neyvia. | neyvia |
| [backend.harness_jobs](modules/backend.harness_jobs/README.md) | Provides backend / harness_jobs in Neyvia. | neyvia |
| [backend.harness_registry](modules/backend.harness_registry/README.md) | Provides backend / harness_registry in Neyvia. | neyvia |
| [backend.harness_runtime_inspection](modules/backend.harness_runtime_inspection/README.md) | Provides backend / harness_runtime_inspection in Neyvia. | neyvia |
| [backend.hermes_claude_subscription](modules/backend.hermes_claude_subscription/README.md) | Hermes-owned Anthropic OAuth connection helpers. | neyvia |
| [backend.hermes_integration](modules/backend.hermes_integration/README.md) | Resolve the installed Hermes runtime and read its native plugin inventory. | agents |
| [backend.hermes_prompt_bridge](modules/backend.hermes_prompt_bridge/README.md) | File-backed system overlay for the installed Hermes CLI. | neyvia |
| [backend.hermes_subscription_route](modules/backend.hermes_subscription_route/README.md) | Opt-in Hermes subscription provider; credentials remain with official Claude CLI. | neyvia |
| [backend.html_site_benchmark](modules/backend.html_site_benchmark/README.md) | Frozen, route-honest HTML site benchmark for Neyvia harnesses. | neyvia |
| [backend.image_budget](modules/backend.image_budget/README.md) | Keep screenshots small before they enter a model's history. | neyvia |
| [backend.improvement_advisor](modules/backend.improvement_advisor/README.md) | Provides backend / improvement_advisor in Neyvia. | neyvia |
| [backend.improvement_lab](modules/backend.improvement_lab/README.md) | Executable comparisons and bounded, evidence-linked improvement decisions. | neyvia |
| [backend.improvement_tools](modules/backend.improvement_tools/README.md) | Native entry points for the improvement lab; execution still needs tool grants. | neyvia |
| [backend.innovation_tools](modules/backend.innovation_tools/README.md) | Model-facing entry points; operator preference/promotion is intentionally separate. | neyvia |
| [backend.install_profiles](modules/backend.install_profiles/README.md) | Truthful core/optional installation composition for Neyvia. | neyvia |
| [backend.installed_programs](modules/backend.installed_programs/README.md) | Reuse existing host executables in managed work folders, without installation. | neyvia |
| [backend.intent_actions](modules/backend.intent_actions/README.md) | Resolve semantic user intents against fresh observations before acting. | neyvia |
| [backend.ios_studio](modules/backend.ios_studio/README.md) | Provides backend / ios_studio in Neyvia. | neyvia |
| [backend.judgment_evidence](modules/backend.judgment_evidence/README.md) | Judgment kinds and evidence binding. | neyvia |
| [backend.launch_recommendation](modules/backend.launch_recommendation/README.md) | Provides backend / launch_recommendation in Neyvia. | neyvia |
| [backend.laya_app_service](modules/backend.laya_app_service/README.md) | Owned LAYA service: transformer by default, calibrated CPU head for browser calls. | neyvia |
| [backend.laya_client.__init__](modules/backend.laya_client.__init__/README.md) | Shipped T15-r2 advisory client; model/runtime remain service-owned. | neyvia |
| [backend.laya_client.browser_client](modules/backend.laya_client.browser_client/README.md) | Small adapter for the merged T20 two-argument advisory provider hook. | neyvia |
| [backend.laya_client.calibration](modules/backend.laya_client.calibration/README.md) | Identity-bound browser confidence calibration; never changes model choices. | neyvia |
| [backend.laya_client.contracts](modules/backend.laya_client.contracts/README.md) | Versioned typed decisions and an injectable T20 hook; no app dependencies. | neyvia |
| [backend.laya_client.fast_cpu](modules/backend.laya_client.fast_cpu/README.md) | Resident adapter for the existing, hash-verified LAYA R5 CPU family. | neyvia |
| [backend.laya_components](modules/backend.laya_components/README.md) | Source-attributed component representations and original compositional drafts. | neyvia |
| [backend.laya_computer_use](modules/backend.laya_computer_use/README.md) | Fail-closed bridge to Laya's named local computer-use workflows. | neyvia |
| [backend.laya_curriculum](modules/backend.laya_curriculum/README.md) | Bounded learned representations beside LAYA's frozen encoder. | neyvia |
| [backend.laya_glance](modules/backend.laya_glance/README.md) | UI adapter for the shared Scene core. | laya-glance |
| [backend.laya_glance_contracts](modules/backend.laya_glance_contracts/README.md) | Run LAYAG live scene contracts in an owned headless browser; no test framework. | neyvia |
| [backend.laya_glance_gate](modules/backend.laya_glance_gate/README.md) | LAYA glance for the P22 release gate: changed web sources -> rendered states -> verdict rows. | neyvia |
| [backend.laya_glance_image](modules/backend.laya_glance_image/README.md) | Pixel transcriber for the UI adapter: one screenshot -> Scene v1 nodes. | laya-glance |
| [backend.laya_glance_proof](modules/backend.laya_glance_proof/README.md) | Before/after proof for the three P22 bugs, from pixels alone, plus cold latency. | laya-glance |
| [backend.laya_hooks](modules/backend.laya_hooks/README.md) | Small, self-contained hooks that put LAYA's learned decisions in front of the big model. | neyvia |
| [backend.laya_host](modules/backend.laya_host/README.md) | The Neyvia backend owns the LAYA service: start it hidden, watch it, restart it, stop it with the backend. | neyvia |
| [backend.laya_instant](modules/backend.laya_instant/README.md) | Local append-only episodic learning. Frozen encoders; no optimizer on writes. | neyvia |
| [backend.laya_instant_calibration](modules/backend.laya_instant_calibration/README.md) | Incremental leave-one-episode-out scores, never a held-out accuracy claim. | neyvia |
| [backend.laya_instant_consolidate](modules/backend.laya_instant_consolidate/README.md) | Background ridge distillation with independent holdout veto; episodes survive. | neyvia |
| [backend.laya_instant_ingest](modules/backend.laya_instant_ingest/README.md) | Provenance-preserving local vote/experience ingestion, outside the query path. | neyvia |
| [backend.laya_instant_semantic](modules/backend.laya_instant_semantic/README.md) | Explicit, pinned optional CPU sentence encoder; no network or auto-download. | neyvia |
| [backend.laya_ledger](modules/backend.laya_ledger/README.md) | Receipts for every routine decision LAYA answered or handed up, plus computer-use activity. | neyvia |
| [backend.laya_outcomes](modules/backend.laya_outcomes/README.md) | Durable app outcome queue: posting is outside the user action's critical path. | neyvia |
| [backend.laya_selfcheck](modules/backend.laya_selfcheck/README.md) | Deterministic observations of LAYA's gate, receipts, hosting and UI models, for the efficiency manual's contracts. | neyvia |
| [backend.laya_service](modules/backend.laya_service/README.md) | Typed advisory LAYA attachment; unavailable service never gains authority. | neyvia |
| [backend.laya_ui_fix](modules/backend.laya_ui_fix/README.md) | UI fix actions for the shared Scene core (plan 23: "CSS/token patches"). | neyvia |
| [backend.laya_video](modules/backend.laya_video/README.md) | LAYA video adapter on the shared Scene core (plan 28). | video |
| [backend.laya_video_audio](modules/backend.laya_video_audio/README.md) | Audio for the LAYA video loop: a deterministic beat-grid bed and exact measurements. | neyvia |
| [backend.laya_video_edit](modules/backend.laya_video_edit/README.md) | LAYA pre-render check of a HyperFrames video project (domain ``video-edit``). | neyvia |
| [backend.laya_vision](modules/backend.laya_vision/README.md) | Evolving vision (plan 24): the model look, look memory, and lens authoring. | neyvia |
| [backend.laya_vision_render](modules/backend.laya_vision_render/README.md) | The same evolving-vision mechanism on 3D renders (plan 24 -> plans 23/26). | neyvia |
| [backend.legacy_asset_treasury](modules/backend.legacy_asset_treasury/README.md) | Bounded, privacy-preserving recovery of value from prior Neyvia work. | neyvia |
| [backend.lesson_evolver](modules/backend.lesson_evolver/README.md) | Feedback lessons with frozen paired replays and reversible workspace versions. | neyvia |
| [backend.lesson_preference](modules/backend.lesson_preference/README.md) | Small, frozen personalized ranker; anonymous features, supervised preferences. | neyvia |
| [backend.lesson_replay](modules/backend.lesson_replay/README.md) | Bounded real task replay: model writes files; host owns executable measurements. | neyvia |
| [backend.lesson_rubric](modules/backend.lesson_rubric/README.md) | Paul's explicit output rubric, observed before any preference weighting. | neyvia |
| [backend.living_applications](modules/backend.living_applications/README.md) | Durable registry objects for applications and supervised autonomy. | neyvia |
| [backend.local_app_install](modules/backend.local_app_install/README.md) | Reversible per-user installation of an App Factory Windows executable. | neyvia |
| [backend.local_browser_authority](modules/backend.local_browser_authority/README.md) | Owner-configured local control origins shared by MCP and extension workers. | neyvia |
| [backend.local_network_policy](modules/backend.local_network_policy/README.md) | Application egress boundary. Loopback services remain usable; children fail closed. | neyvia |
| [backend.local_provisioning](modules/backend.local_provisioning/README.md) | Provision ignored interpreter-local bytecode at the normal entry points. | neyvia |
| [backend.managed_local_service](modules/backend.managed_local_service/README.md) | Hash-pinned demand-start lifecycle for local model and tool services. | neyvia |
| [backend.managed_node_runtime](modules/backend.managed_node_runtime/README.md) | Resolve a compatible per-user Node.js runtime for optional Neyvia CLIs. | neyvia |
| [backend.manual_compiler](modules/backend.manual_compiler/README.md) | Evidence-derived procedure plans; execution stays in the grounded manual runner. | neyvia |
| [backend.manual_contracts](modules/backend.manual_contracts/README.md) | One strict notation for manuals; no eval, import paths or untyped procedure calls. | neyvia |
| [backend.manual_first](modules/backend.manual_first/README.md) | Small model-facing core; full catalogs remain behind discovery. | neyvia |
| [backend.manual_recovery](modules/backend.manual_recovery/README.md) | Nogoods bound to durable failures and typed, explicitly selected recovery recipes. | neyvia |
| [backend.manual_state](modules/backend.manual_state/README.md) | Durable observation handles, bounded projections and JSON Patch deltas. | neyvia |
| [backend.manual_versions](modules/backend.manual_versions/README.md) | Scoped manual revisions: quarantined JSON patches, explicit promotion and lineage. | neyvia |
| [backend.marketplace_toolchain](modules/backend.marketplace_toolchain/README.md) | Auditable update discovery for the portable marketplace security toolchain. | neyvia |
| [backend.mcp_broker](modules/backend.mcp_broker/README.md) | Outbound MCP broker MVP: discover → describe → call with auth + approval receipts. | neyvia |
| [backend.mcp_http_transport](modules/backend.mcp_http_transport/README.md) | MCP Streamable HTTP client using the standard library (JSON and SSE). | neyvia |
| [backend.mcp_protocol](modules/backend.mcp_protocol/README.md) | Shared MCP catalog pagination and incoming notification dispatch. | neyvia |
| [backend.memory](modules/backend.memory/README.md) | Provides backend / memory in Neyvia. | neyvia |
| [backend.memory_recall](modules/backend.memory_recall/README.md) | Situation matching, local LAYA advisory selection and exact bounded M data. | neyvia |
| [backend.mesh_service](modules/backend.mesh_service/README.md) | Provider-neutral private-mesh control and service-discovery boundary. | neyvia |
| [backend.mission_acceptance_harness](modules/backend.mission_acceptance_harness/README.md) | Fast, deterministic acceptance journeys for Neyvia's mission runtime. | neyvia |
| [backend.mission_artifacts](modules/backend.mission_artifacts/README.md) | Provides backend / mission_artifacts in Neyvia. | neyvia |
| [backend.mission_control](modules/backend.mission_control/README.md) | Provides backend / mission_control in Neyvia. | proofs |
| [backend.mission_control_artifact_gates](modules/backend.mission_control_artifact_gates/README.md) | Concrete artifact and planned-scope completion gates. | neyvia |
| [backend.mission_control_detail](modules/backend.mission_control_detail/README.md) | Mission detail, transcript and notification read models. | neyvia |
| [backend.mission_control_harness](modules/backend.mission_control_harness/README.md) | Harness responsibilities for the control room. | neyvia |
| [backend.mission_control_integration](modules/backend.mission_control_integration/README.md) | Integration responsibilities for the control room. | neyvia |
| [backend.mission_control_operator_audit](modules/backend.mission_control_operator_audit/README.md) | Operator audit responsibilities for the control room. | neyvia |
| [backend.mission_control_projections](modules/backend.mission_control_projections/README.md) | Summary and bootstrap projections for the control room. | neyvia |
| [backend.mission_control_release](modules/backend.mission_control_release/README.md) | Release responsibilities for the control room. | neyvia |
| [backend.mission_control_workspace_deletion](modules/backend.mission_control_workspace_deletion/README.md) | Recover scoped workspace deletion after a lost multi-file acknowledgement. | neyvia |
| [backend.mission_phase_inputs](modules/backend.mission_phase_inputs/README.md) | Provides backend / mission_phase_inputs in Neyvia. | neyvia |
| [backend.mission_phase_runner](modules/backend.mission_phase_runner/README.md) | Provides backend / mission_phase_runner in Neyvia. | neyvia |
| [backend.mission_receipts](modules/backend.mission_receipts/README.md) | Provides backend / mission_receipts in Neyvia. | neyvia |
| [backend.mission_watchdog](modules/backend.mission_watchdog/README.md) | Provides backend / mission_watchdog in Neyvia. | neyvia |
| [backend.model_catalog](modules/backend.model_catalog/README.md) | Provides backend / model_catalog in Neyvia. | neyvia |
| [backend.model_portfolio](modules/backend.model_portfolio/README.md) | Provider-neutral task lanes for Neyvia model routing. | neyvia |
| [backend.model_routing](modules/backend.model_routing/README.md) | Provides backend / model_routing in Neyvia. | neyvia |
| [backend.model_tool_intelligence](modules/backend.model_tool_intelligence/README.md) | Model-facing tool intelligence for N-E-Y-V-I-A. | neyvia |
| [backend.model_usage](modules/backend.model_usage/README.md) | Usage receipts: context size and cumulative thread spend are different facts. | neyvia |
| [backend.model_view](modules/backend.model_view/README.md) | What a tool result looks like to the model: the facts it needs, not the audit envelope around them. | neyvia |
| [backend.models](modules/backend.models/README.md) | Provides backend / models in Neyvia. | neyvia |
| [backend.modes](modules/backend.modes/README.md) | Provides backend / modes in Neyvia. | neyvia |
| [backend.module_map](modules/backend.module_map/README.md) | Generate a navigable module map from source ownership, imports and CL manuals. | proofs |
| [backend.module_marketplace](modules/backend.module_marketplace/README.md) | Verified, non-invasive module lifecycle for the Neyvia marketplace. | neyvia |
| [backend.module_plugins](modules/backend.module_plugins/README.md) | Trusted, repository-local optional modules; one manifest owns each action. | neyvia |
| [backend.nas_bridge](modules/backend.nas_bridge/README.md) | Provides backend / nas_bridge in Neyvia. | neyvia |
| [backend.nas_transfer](modules/backend.nas_transfer/README.md) | Provides backend / nas_transfer in Neyvia. | neyvia |
| [backend.native_access](modules/backend.native_access/README.md) | Server-side permission modes for Neyvia Native chat access. | neyvia |
| [backend.native_arguments](modules/backend.native_arguments/README.md) | Normalize unambiguous typed transport values only against declared tool schemas. | neyvia |
| [backend.native_checkpoints](modules/backend.native_checkpoints/README.md) | Content-addressed, workspace-bounded checkpoints for Neyvia Native. | neyvia |
| [backend.native_commands](modules/backend.native_commands/README.md) | Bounded execution and discovery for local native commands. | neyvia |
| [backend.native_device_commands](modules/backend.native_device_commands/README.md) | Receipt-bound, human-authorized command queue for paired Neyvia devices. | neyvia |
| [backend.native_device_operator_authority](modules/backend.native_device_operator_authority/README.md) | Verify-only operator authority for paired-device command approvals. | neyvia |
| [backend.native_device_operator_signing_wire](modules/backend.native_device_operator_signing_wire/README.md) | Opaque signing-wire package for paired-device operator approvals. | neyvia |
| [backend.native_event_stream](modules/backend.native_event_stream/README.md) | Append-only, hash-chained event stream for Neyvia Native. | neyvia |
| [backend.native_goals](modules/backend.native_goals/README.md) | Durable goals, milestones, heartbeats, and due-work queries for Neyvia Native. | neyvia |
| [backend.native_harness_quality](modules/backend.native_harness_quality/README.md) | Frozen, route-honest quality ladder for Neyvia's native harness. | neyvia |
| [backend.native_hooks](modules/backend.native_hooks/README.md) | Bounded, receipt-producing lifecycle hooks for Neyvia Native. | neyvia |
| [backend.native_learning](modules/backend.native_learning/README.md) | Evidence-bound local learning for Neyvia Native. | neyvia |
| [backend.native_pairing](modules/backend.native_pairing/README.md) | Scoped one-time pairing for Neyvia computer, phone, and NAS surfaces. | neyvia |
| [backend.native_proof_audit](modules/backend.native_proof_audit/README.md) | Deterministic final-workspace proof auditing for Neyvia Native. | neyvia |
| [backend.native_resource_profiles](modules/backend.native_resource_profiles/README.md) | Resource-aware execution profiles for Neyvia Native. | neyvia |
| [backend.native_spawn_contracts](modules/backend.native_spawn_contracts/README.md) | Durable spawned-agent contracts and receipts for Neyvia Native. | neyvia |
| [backend.native_spawn_evaluator](modules/backend.native_spawn_evaluator/README.md) | Independent contract/evidence evaluation for Neyvia Native child agents. | neyvia |
| [backend.native_tool_worker](modules/backend.native_tool_worker/README.md) | Provides backend / native_tool_worker in Neyvia. | neyvia |
| [backend.native_tools](modules/backend.native_tools/README.md) | Provides backend / native_tools in Neyvia. | adaptive-work |
| [backend.nearby_send](modules/backend.nearby_send/README.md) | LocalSend-compatible nearby transfer with pinned identity and receipts. | neyvia |
| [backend.neyvia_accounts](modules/backend.neyvia_accounts/README.md) | Neyvia accounts: who can sign in to this PC's Neyvia, and where they are signed in. | neyvia |
| [backend.neyvia_agent](modules/backend.neyvia_agent/README.md) | Neyvia's native model loop with progressive tools and durable sessions. | memory |
| [backend.neyvia_agent_cli](modules/backend.neyvia_agent_cli/README.md) | Lightweight command entry point for the Neyvia native harness. | neyvia |
| [backend.neyvia_agents_tools](modules/backend.neyvia_agents_tools/README.md) | neyvia.agents.state: the bot side of the agents dashboard, on the same read the UI shows. | agents |
| [backend.neyvia_agentview](modules/backend.neyvia_agentview/README.md) | Agent view: watch and steer agents working on their own surfaces. | agent-view |
| [backend.neyvia_agentview_checks](modules/backend.neyvia_agentview_checks/README.md) | Executable contracts of the agent view, run on a scratch workspace (neyvia.agentview.check). | neyvia |
| [backend.neyvia_analytics](modules/backend.neyvia_analytics/README.md) | Bounded analytics over durable run receipts; no extra model calls or prompts. | neyvia |
| [backend.neyvia_app_sdk](modules/backend.neyvia_app_sdk/README.md) | App SDK transport bindings; generator and running-app checks live in app_sdk. | app-sdk |
| [backend.neyvia_application_contract](modules/backend.neyvia_application_contract/README.md) | N-E-Y-V-I-A application contract — two developer propositions, one core. | design |
| [backend.neyvia_attention](modules/backend.neyvia_attention/README.md) | A bounded actionable inbox from saved owner approvals, tasks and run states. | neyvia-core |
| [backend.neyvia_autopilot](modules/backend.neyvia_autopilot/README.md) | Intent-driven execution using grounded manuals, checks and compiled evidence. | autopilot |
| [backend.neyvia_awareness](modules/backend.neyvia_awareness/README.md) | Awareness: a shared work board (who works on which files), the impact map and the intent checklist. | agents |
| [backend.neyvia_browser](modules/backend.neyvia_browser/README.md) | Shared integrated-browser state and memory-only native runtime capabilities. | browser |
| [backend.neyvia_browser_capture](modules/backend.neyvia_browser_capture/README.md) | Capture contexts in the selected Neyvia runtime, without browser substitution. | neyvia |
| [backend.neyvia_browser_dom](modules/backend.neyvia_browser_dom/README.md) | Bounded DOM locators backed only by Neyvia's native browser receipts. | neyvia |
| [backend.neyvia_cl](modules/backend.neyvia_cl/README.md) | CL descriptors; authenticated HTTP owners use the same host as MCP. | neyvia |
| [backend.neyvia_comments](modules/backend.neyvia_comments/README.md) | Workspace comments: immutable events, derived current view and real session delivery. | comments |
| [backend.neyvia_conductor](modules/backend.neyvia_conductor/README.md) | Goal planning and frozen routed DAGs on the existing detached Harness workers. | conductor |
| [backend.neyvia_connections](modules/backend.neyvia_connections/README.md) | One honest list of every way Neyvia can reach a model, with a proven one-click connect. | connections |
| [backend.neyvia_conversations](modules/backend.neyvia_conversations/README.md) | Provides backend / neyvia_conversations in Neyvia. | neyvia |
| [backend.neyvia_coordinator](modules/backend.neyvia_coordinator/README.md) | Provides backend / neyvia_coordinator in Neyvia. | neyvia |
| [backend.neyvia_cua](modules/backend.neyvia_cua/README.md) | PC-owned MIT Cua Driver sessions, background preview, receipts and takeover. | computer-use |
| [backend.neyvia_cua_mcp](modules/backend.neyvia_cua_mcp/README.md) | MCP agent adapter to the PC-owned Cua session, approvals and shared preview log. | neyvia |
| [backend.neyvia_devices](modules/backend.neyvia_devices/README.md) | Owner-approved, scoped PC file access over the tailnet. | cross-pc |
| [backend.neyvia_dictation](modules/backend.neyvia_dictation/README.md) | Dictation: speech to prompt text with the local Phonon-2 engine, shared with the dictation service. | dictation |
| [backend.neyvia_dictation_providers](modules/backend.neyvia_dictation_providers/README.md) | Dictation providers: where the speech is turned into words while Paul talks. | neyvia |
| [backend.neyvia_documents](modules/backend.neyvia_documents/README.md) | Workspace tools for Paul's study documents (manuals/cl/documents.cl). | documents |
| [backend.neyvia_ecosystem](modules/backend.neyvia_ecosystem/README.md) | Neyvia ecosystem integration hooks (durable, honest). | neyvia |
| [backend.neyvia_efficiency](modules/backend.neyvia_efficiency/README.md) | Native, source-checked extraction and inspection of the efficiency cascade. | efficiency |
| [backend.neyvia_evolver](modules/backend.neyvia_evolver/README.md) | Workspace-scoped observation boundary for the frozen Evolver engine. | hill-climb |
| [backend.neyvia_extension_worker](modules/backend.neyvia_extension_worker/README.md) | Provides backend / neyvia_extension_worker in Neyvia. | neyvia |
| [backend.neyvia_files_tools](modules/backend.neyvia_files_tools/README.md) | Files app: a file explorer over Home, the workspace and project folders. | files |
| [backend.neyvia_gamedev](modules/backend.neyvia_gamedev/README.md) | Project-scoped live editor bridges and durable, affinity-bound receipts. | game-dev |
| [backend.neyvia_gateway](modules/backend.neyvia_gateway/README.md) | Compact native gateway shared by agent and CL transports. | neyvia |
| [backend.neyvia_image_approval](modules/backend.neyvia_image_approval/README.md) | Request approval before an image effect enters the durable mutation ledger. | neyvia |
| [backend.neyvia_image_generate](modules/backend.neyvia_image_generate/README.md) | Image generation through the Codex CLI's own built-in image tool. | image-studio |
| [backend.neyvia_image_tools](modules/backend.neyvia_image_tools/README.md) | Image Studio state and real pixel edits; generation reuses the existing provider. | image-studio |
| [backend.neyvia_image_verification](modules/backend.neyvia_image_verification/README.md) | Observe actual Image Studio postconditions without claiming rendered UI proof. | neyvia |
| [backend.neyvia_impact](modules/backend.neyvia_impact/README.md) | Impact map: given changed files, list what they connect to, and what is broken in the wiring today. | awareness |
| [backend.neyvia_inception](modules/backend.neyvia_inception/README.md) | Source-bound Inception coverage and release decisions; never invent journeys. | inception |
| [backend.neyvia_intent_plan](modules/backend.neyvia_intent_plan/README.md) | Model-authored intent plans; validation and publication make no provider call. | neyvia |
| [backend.neyvia_lab_board](modules/backend.neyvia_lab_board/README.md) | Read existing frozen improvement receipts; Pareto sets never imply promotion. | hill-climb |
| [backend.neyvia_language](modules/backend.neyvia_language/README.md) | No-slop language checks for UI strings and reports (plan 20, C5). | language |
| [backend.neyvia_laya_capabilities](modules/backend.neyvia_laya_capabilities/README.md) | Agent/App Factory/taste-loop access to bounded LAYA capabilities. | design |
| [backend.neyvia_manuals](modules/backend.neyvia_manuals/README.md) | Grounded data manuals: compact views, typed execution and quarantined discoveries. | C7e-artifact-manual |
| [backend.neyvia_mcp](modules/backend.neyvia_mcp/README.md) | Provides backend / neyvia_mcp in Neyvia. | neyvia |
| [backend.neyvia_mcp_bootstrap](modules/backend.neyvia_mcp_bootstrap/README.md) | Pin stdio imports to this checkout, even with a shared/linked Python environment. | neyvia |
| [backend.neyvia_mcp_stdio](modules/backend.neyvia_mcp_stdio/README.md) | Compact stdio MCP transport for model-facing N-E-Y-V-I-A tools. | memory |
| [backend.neyvia_memory_tools](modules/backend.neyvia_memory_tools/README.md) | Authenticated Memory UI commands and the same scope-bound agent tools. | memory |
| [backend.neyvia_mission_plan](modules/backend.neyvia_mission_plan/README.md) | Compile a sectioned Markdown plan into dormant, independently routed tasks. | neyvia |
| [backend.neyvia_missions](modules/backend.neyvia_missions/README.md) | Mission metadata and branch supervision over the existing Night Shift engine. | mission-plan |
| [backend.neyvia_mobile_preview_helper](modules/backend.neyvia_mobile_preview_helper/README.md) | Provides backend / neyvia_mobile_preview_helper in Neyvia. | neyvia |
| [backend.neyvia_mobile_studio](modules/backend.neyvia_mobile_studio/README.md) | Mobile Studio (Studio suite): a phone preview beside the chat, iPhone builds | mobile-studio |
| [backend.neyvia_modules](modules/backend.neyvia_modules/README.md) | Read-only repository module ownership and contract discovery. | modules |
| [backend.neyvia_native_rpc](modules/backend.neyvia_native_rpc/README.md) | Strict line-delimited JSON-RPC control surface for Neyvia Native. | neyvia |
| [backend.neyvia_nightshift](modules/backend.neyvia_nightshift/README.md) | User, bot and desktop access to the existing durable Night Shift engine. | neyvia-core |
| [backend.neyvia_notes_tools](modules/backend.neyvia_notes_tools/README.md) | Notes app: a folder of Markdown notes (default ~/Neyvia Notes) shared by Paul and models. | notes |
| [backend.neyvia_onboarding](modules/backend.neyvia_onboarding/README.md) | First run: base pack download, runtime detection, interests and the tour. | local-rendering |
| [backend.neyvia_outputs](modules/backend.neyvia_outputs/README.md) | Published outputs share the workspace bus, durable identity and guarded previews. | local-app-open |
| [backend.neyvia_panes](modules/backend.neyvia_panes/README.md) | The new shell's file, artifact and terminal panes (``pane.show``). | neyvia |
| [backend.neyvia_parallel](modules/backend.neyvia_parallel/README.md) | Parallel branches, one durable run with connected sessions and ordered Git merges. | parallel |
| [backend.neyvia_parallel_codex](modules/backend.neyvia_parallel_codex/README.md) | Scoped Codex dynamic tools, backed by the same native owner as Claude's mod. | neyvia |
| [backend.neyvia_parallel_git](modules/backend.neyvia_parallel_git/README.md) | Git effects for Parallel; all removal is confined to this run's worktree root. | neyvia |
| [backend.neyvia_pdf_api](modules/backend.neyvia_pdf_api/README.md) | Authenticated, workspace-scoped PDF file transport (including PDF.js range reads). | pdf |
| [backend.neyvia_pdf_tools](modules/backend.neyvia_pdf_tools/README.md) | The PDF bot side sends A2's typed actions and observes the same app state. | neyvia |
| [backend.neyvia_perception](modules/backend.neyvia_perception/README.md) | One model-language observation contract across layers, reusing T5 handles. | local-browser-sdk |
| [backend.neyvia_prompt_dictation](modules/backend.neyvia_prompt_dictation/README.md) | Prompt-only text policy shared by HTTP, desktop and model dictation callers. | neyvia |
| [backend.neyvia_remote](modules/backend.neyvia_remote/README.md) | Live, owner-consented remote windows on T16's background preview service. | neyvia-core |
| [backend.neyvia_remote_frames](modules/backend.neyvia_remote_frames/README.md) | Memory-only PNG frames for the desktop bridge's JSON transport. | neyvia |
| [backend.neyvia_run_watches](modules/backend.neyvia_run_watches/README.md) | One-shot run watches using the existing scheduler and broker state events. | neyvia-core |
| [backend.neyvia_runtime](modules/backend.neyvia_runtime/README.md) | Observed runtime matrix and owner-selected routing limits; no provider fallback. | neyvia |
| [backend.neyvia_runtime_invocation](modules/backend.neyvia_runtime_invocation/README.md) | Durable N-E-Y-V-I-A external runtime invocation registry. | neyvia |
| [backend.neyvia_scroll](modules/backend.neyvia_scroll/README.md) | One workspace store for the Scroll Study generator, UI and model tools. | neyvia-core |
| [backend.neyvia_session_clustering](modules/backend.neyvia_session_clustering/README.md) | Local title/project clustering with reviewable, reversible moves and no model calls. | neyvia |
| [backend.neyvia_settings](modules/backend.neyvia_settings/README.md) | Canonical owner preferences on the existing durable UI bus. | neyvia |
| [backend.neyvia_sidebar](modules/backend.neyvia_sidebar/README.md) | Sidebar observation and durable preview/confirm/undo on the existing UI bus. | agents |
| [backend.neyvia_sidebar_cleanup](modules/backend.neyvia_sidebar_cleanup/README.md) | One backend policy and archive guard shared by people, tools and maintenance. | neyvia |
| [backend.neyvia_sidebar_projection](modules/backend.neyvia_sidebar_projection/README.md) | Transcript-backed sidebar observations; never infer work from titles or folders. | neyvia |
| [backend.neyvia_sidebar_semantics](modules/backend.neyvia_sidebar_semantics/README.md) | Local CPU sentence embeddings with explicit availability and bounded caches. | neyvia |
| [backend.neyvia_stage_scheduler](modules/backend.neyvia_stage_scheduler/README.md) | Execute compiled NEYVIA/1 stages with best-checkpoint rollback receipts. | neyvia |
| [backend.neyvia_time_tools](modules/backend.neyvia_time_tools/README.md) | Precise clocks and durable elapsed timers; timers never cancel agent work. | neyvia |
| [backend.neyvia_ui_api](modules/backend.neyvia_ui_api/README.md) | HTTP boundary for the UI bus, workspace tools, app registry and Night Shift. | neyvia |
| [backend.neyvia_ui_client](modules/backend.neyvia_ui_client/README.md) | Loopback bridge for native agent workers; no provider credentials are copied. | neyvia |
| [backend.neyvia_version](modules/backend.neyvia_version/README.md) | Version identity shared by Neyvia's light and full harness entry points. | neyvia |
| [backend.neyvia_video](modules/backend.neyvia_video/README.md) | neyvia.video.* native tools: agent-usable HyperFrames editing, LAYA video judgement and the improve loop. | video |
| [backend.neyvia_view_tools](modules/backend.neyvia_view_tools/README.md) | neyvia.view.*: the agent arranges the interface through the same bus the user's layout lives on. | design |
| [backend.neyvia_voice](modules/backend.neyvia_voice/README.md) | Final voice transcripts use the existing workspace bus; never launch a run. | local-app-open |
| [backend.neyvia_workspace_tools](modules/backend.neyvia_workspace_tools/README.md) | Model tools for Neyvia's own workspace; changes and commands share one bus. | computer-use |
| [backend.night_mode](modules/backend.night_mode/README.md) | Provides backend / night_mode in Neyvia. | neyvia |
| [backend.nightshift](modules/backend.nightshift/README.md) | SQLite task board. Completion events, rather than a polling script, release work. | neyvia |
| [backend.nightshift_evidence](modules/backend.nightshift_evidence/README.md) | Task-bound completion checks. Transport completion is never work evidence. | neyvia |
| [backend.nightshift_import](modules/backend.nightshift_import/README.md) | Import the TASKS markdown dialect used by Paul's shared plan board. | neyvia |
| [backend.nightshift_ledger](modules/backend.nightshift_ledger/README.md) | Persisted night periods and every harness attempt, including failed retries. | neyvia |
| [backend.nightshift_resources](modules/backend.nightshift_resources/README.md) | Admission and event-driven limits; cancellation retains the repository lock. | proofs |
| [backend.nightshift_summary](modules/backend.nightshift_summary/README.md) | Morning card projection from persisted evidence and measured run receipts. | neyvia |
| [backend.ocr_benchmark](modules/backend.ocr_benchmark/README.md) | Deterministic OCR evaluation and routing primitives. | neyvia |
| [backend.onboarding](modules/backend.onboarding/README.md) | Provides backend / onboarding in Neyvia. | neyvia |
| [backend.openai_adapter](modules/backend.openai_adapter/README.md) | Provides backend / openai_adapter in Neyvia. | neyvia |
| [backend.opencode_bridge](modules/backend.opencode_bridge/README.md) | Provides backend / opencode_bridge in Neyvia. | neyvia |
| [backend.opencode_go_models](modules/backend.opencode_go_models/README.md) | Provides backend / opencode_go_models in Neyvia. | neyvia |
| [backend.operation_adapters](modules/backend.operation_adapters/README.md) | Trusted local postcondition adapters for operations with inspectable state. | neyvia |
| [backend.orchestration_control](modules/backend.orchestration_control/README.md) | Cross-process admission and cooperative stopping for durable agent graphs. | neyvia |
| [backend.orchestration_language](modules/backend.orchestration_language/README.md) | Provides backend / orchestration_language in Neyvia. | neyvia |
| [backend.p2p_cache](modules/backend.p2p_cache/README.md) | Local-first BLAKE3 object cache prepared for an Iroh peer transport. | neyvia |
| [backend.p2p_provider](modules/backend.p2p_provider/README.md) | Supervised, rollback-safe publication of Neyvia CAS objects over Iroh. | neyvia |
| [backend.paddle_ocr_worker](modules/backend.paddle_ocr_worker/README.md) | Isolated PaddleOCR worker used by the bounded Neyvia adapter. | neyvia |
| [backend.paul_intent_judge](modules/backend.paul_intent_judge/README.md) | Deterministic judge for reading Paul's long messages into intent checklists. | neyvia |
| [backend.paul_manual](modules/backend.paul_manual/README.md) | Public distribution: no bundled personal profile or learned messages. | neyvia |
| [backend.pdf_compat](modules/backend.pdf_compat/README.md) | Permissive PDF helpers: pypdf (BSD) reads text and fonts and writes PDFs, pypdfium2 (Apache-2.0/BSD-3, PDFium) renders pages. | neyvia |
| [backend.pdf_document](modules/backend.pdf_document/README.md) | Read real PDF metadata/text with an installed pypdf interpreter, without installs. | neyvia |
| [backend.pdf_document_worker](modules/backend.pdf_document_worker/README.md) | Isolated installed-library reader; stdin and stdout are JSON, never provider data. | neyvia |
| [backend.perception_browser](modules/backend.perception_browser/README.md) | Owned browser sessions: real DOM/accessibility text and guarded actions. | neyvia |
| [backend.perception_frames](modules/backend.perception_frames/README.md) | Compact, revision-bound semantic perception frames. | neyvia |
| [backend.perception_scene](modules/backend.perception_scene/README.md) | Provides backend / perception_scene in Neyvia. | laya-glance |
| [backend.perception_video](modules/backend.perception_video/README.md) | Decode one explicitly requested video frame with an already installed FFmpeg. | neyvia |
| [backend.perception_visual](modules/backend.perception_visual/README.md) | Bounded visual transcription through the installed, isolated Codex CLI. | neyvia |
| [backend.persona](modules/backend.persona/README.md) | Provides backend / persona in Neyvia. | neyvia |
| [backend.planner](modules/backend.planner/README.md) | Provides backend / planner in Neyvia. | neyvia |
| [backend.platform_config](modules/backend.platform_config/README.md) | Provides backend / platform_config in Neyvia. | neyvia |
| [backend.port_safety](modules/backend.port_safety/README.md) | Provides backend / port_safety in Neyvia. | neyvia |
| [backend.private_conpty](modules/backend.private_conpty/README.md) | Real Windows terminals without AllocConsole or an input-desktop broker. | neyvia |
| [backend.product_catalog](modules/backend.product_catalog/README.md) | Truthful product boundaries for Neyvia tools, apps, and agents. | neyvia |
| [backend.profiles](modules/backend.profiles/README.md) | Provides backend / profiles in Neyvia. | neyvia |
| [backend.progressive_setup](modules/backend.progressive_setup/README.md) | Plain-language, resumable first-run contract for Neyvia. | neyvia |
| [backend.progressive_tools](modules/backend.progressive_tools/README.md) | Progressive tool discovery: search → describe → call (schemas off by default). | neyvia |
| [backend.project_files](modules/backend.project_files/README.md) | Bounded file browsing and export for registered project workspaces. | neyvia |
| [backend.prompt_amplifier](modules/backend.prompt_amplifier/README.md) | Revision-bound rough-prompt preparation before a connected agent turn. | awareness |
| [backend.prompt_contract](modules/backend.prompt_contract/README.md) | Keep authored instructions intact across SDK tool rounds and session replay. | neyvia |
| [backend.prompt_coverage](modules/backend.prompt_coverage/README.md) | Lossless, script-only prompt checklist and independently checked coverage. | neyvia |
| [backend.prompt_references](modules/backend.prompt_references/README.md) | Conservative, zero-model antecedent hints for the prompt reading aid. | neyvia |
| [backend.prompts](modules/backend.prompts/README.md) | Provides backend / prompts in Neyvia. | neyvia |
| [backend.proof_capsules](modules/backend.proof_capsules/README.md) | Durable, independently verifiable proof capsules and coherent change sets. | neyvia |
| [backend.proof_contracts](modules/backend.proof_contracts/README.md) | Host-side manual contracts. Trusted local code, never eval or manual imports. | neyvia |
| [backend.proof_coverage](modules/backend.proof_coverage/README.md) | Reviewable test -> manual contract -> host check -> real receipt mapping. | neyvia |
| [backend.proof_credential_guard](modules/backend.proof_credential_guard/README.md) | Proof workers refuse saved credentials outside their disposable state. | neyvia |
| [backend.proof_digest](modules/backend.proof_digest/README.md) | Provides backend / proof_digest in Neyvia. | neyvia |
| [backend.proof_ports](modules/backend.proof_ports/README.md) | Explicit fixture port selection; sockets are never intercepted or remapped. | neyvia |
| [backend.proof_readiness](modules/backend.proof_readiness/README.md) | Startup readiness runs only the changed Connected Language contracts. | neyvia |
| [backend.proof_verifier](modules/backend.proof_verifier/README.md) | Run production manual observers/procedures in a new, confined scratch root. | neyvia |
| [backend.proofs_a_app_standard](modules/backend.proofs_a_app_standard/README.md) | Contracts for read-only connected-app observation and scoped persistence. | neyvia |
| [backend.proofs_a_capabilities](modules/backend.proofs_a_capabilities/README.md) | Action contracts for capability planning and recoverable local workflows. | neyvia |
| [backend.proofs_a_capability_evolution](modules/backend.proofs_a_capability_evolution/README.md) | Executable contracts for receipt-bound, inactive capability evolution. | neyvia |
| [backend.proofs_a_capability_tools](modules/backend.proofs_a_capability_tools/README.md) | Contracts for authored argv tools and honest Computer Use replay receipts. | neyvia |
| [backend.proofs_a_cli](modules/backend.proofs_a_cli/README.md) | CLI and durable coordination manual contracts; no external runtime authority. | neyvia |
| [backend.proofs_a_cli_lifecycle](modules/backend.proofs_a_cli_lifecycle/README.md) | Asset import, first-run choices and continuity policy runtime contracts. | neyvia |
| [backend.proofs_a_cli_preferences](modules/backend.proofs_a_cli_preferences/README.md) | Mission CLI contracts and bounded production command procedures. | neyvia |
| [backend.proofs_a_cli_scheduler](modules/backend.proofs_a_cli_scheduler/README.md) | Checks at scheduler transactions and isolated real local worker procedures. | neyvia |
| [backend.proofs_a_control](modules/backend.proofs_a_control/README.md) | Executable operator-control contracts, shared by real actions and startup. | neyvia |
| [backend.proofs_a_factory_browser](modules/backend.proofs_a_factory_browser/README.md) | User journeys through actual generated local apps with owned Obscura. | neyvia |
| [backend.proofs_a_livecontrol](modules/backend.proofs_a_livecontrol/README.md) | Authenticated report truth contracts; DOM evidence stays distinct from APIs. | neyvia |
| [backend.proofs_a_native_sessions](modules/backend.proofs_a_native_sessions/README.md) | Native connected-session action contracts and confined provider journeys. | neyvia |
| [backend.proofs_a_providers](modules/backend.proofs_a_providers/README.md) | Provider contracts and confined protocol observer procedures. | neyvia |
| [backend.proofs_a_sessions](modules/backend.proofs_a_sessions/README.md) | Connected-session host contracts and confined scratch observer procedures. | neyvia |
| [backend.proofs_apple_outcomes](modules/backend.proofs_apple_outcomes/README.md) | Retained Apple bytes and a fresh authenticated rendered mode journey. | neyvia |
| [backend.proofs_applications_journey](modules/backend.proofs_applications_journey/README.md) | A short, owned Git note journey through Neyvia's native application tools. | neyvia |
| [backend.proofs_awareness](modules/backend.proofs_awareness/README.md) | Work-board and impact-graph manual contracts checked by the local host. | neyvia |
| [backend.proofs_b_adapters](modules/backend.proofs_b_adapters/README.md) | Action contracts and bounded real procedures for the PROOFS-b adapter chapter. | neyvia |
| [backend.proofs_b_desktop](modules/backend.proofs_b_desktop/README.md) | Desktop evidence contracts checked by the same functions used in real actions. | neyvia |
| [backend.proofs_b_engine](modules/backend.proofs_b_engine/README.md) | Always-on action contracts and bounded local proofs for the PROOFS-b engine slice. | neyvia |
| [backend.proofs_b_harness](modules/backend.proofs_b_harness/README.md) | Executable contracts for durable local Harness actions. | neyvia |
| [backend.proofs_browser_journey](modules/backend.proofs_browser_journey/README.md) | Native Obscura journey for learned browser site manuals. | neyvia |
| [backend.proofs_browser_scripts](modules/backend.proofs_browser_scripts/README.md) | Bounded outcomes for browser procedure binding and goal admission. | neyvia |
| [backend.proofs_build_cache](modules/backend.proofs_build_cache/README.md) | Pure C7 invalidation cases for the D-only Vite build cache. | neyvia |
| [backend.proofs_c_control](modules/backend.proofs_c_control/README.md) | Control-room action invariants and local, durable manual self-checks. | neyvia |
| [backend.proofs_c_intent](modules/backend.proofs_c_intent/README.md) | Intent-turn contracts at the existing harness argument boundary. | neyvia |
| [backend.proofs_c_missions](modules/backend.proofs_c_missions/README.md) | Mission contracts enforced by production boundaries and replayed in scratch. | neyvia |
| [backend.proofs_c_mobile](modules/backend.proofs_c_mobile/README.md) | Local authoring and package contracts; never claim a compiler/device journey. | neyvia |
| [backend.proofs_c_models](modules/backend.proofs_c_models/README.md) | Model contracts at production entry points and isolated action self-checks. | neyvia |
| [backend.proofs_c_runtime](modules/backend.proofs_c_runtime/README.md) | Executable runtime contracts; checks use real state, not result schemas. | neyvia |
| [backend.proofs_capability_config_journey](modules/backend.proofs_capability_config_journey/README.md) | Prove that capability catalog configuration changes real discovery and plans. | neyvia |
| [backend.proofs_chat_journey](modules/backend.proofs_chat_journey/README.md) | Connected Chats journeys over disposable saved history and sidebar state. | neyvia |
| [backend.proofs_cl_completion](modules/backend.proofs_cl_completion/README.md) | Outcome contracts for CL completion and stale native references. | neyvia |
| [backend.proofs_cl_effect_outcomes](modules/backend.proofs_cl_effect_outcomes/README.md) | Measured CL adaptive-work journey through the real host and durable store. | neyvia |
| [backend.proofs_codex_transcript_journey](modules/backend.proofs_codex_transcript_journey/README.md) | Bounded production-parser journey for Codex thread items and rollout state. | neyvia |
| [backend.proofs_connections](modules/backend.proofs_connections/README.md) | Pure cases for the connections screen's invariants (track CONN): no process, network or credential is touched. | neyvia |
| [backend.proofs_context_config_journey](modules/backend.proofs_context_config_journey/README.md) | Outcome contract for route context policy at the Native agent boundary. | neyvia |
| [backend.proofs_creative_journey](modules/backend.proofs_creative_journey/README.md) | Durable creative brief selection with protected operator corrections. | neyvia |
| [backend.proofs_d_host](modules/backend.proofs_d_host/README.md) | PROOFS-d host invariants and disposable local action procedures. | neyvia |
| [backend.proofs_d_native](modules/backend.proofs_d_native/README.md) | Native runtime semantic contracts and confined startup journeys. | neyvia |
| [backend.proofs_d_nearby](modules/backend.proofs_d_nearby/README.md) | Nearby transfer action contracts and bounded real loopback protocol lab. | nearby-send-runtime |
| [backend.proofs_d_neyvia](modules/backend.proofs_d_neyvia/README.md) | Runtime semantic contracts for Neyvia prompt preparation and applications. | neyvia |
| [backend.proofs_d_onboarding](modules/backend.proofs_d_onboarding/README.md) | Onboarding semantic contracts and real disposable staging procedures. | onboarding |
| [backend.proofs_d_runtime](modules/backend.proofs_d_runtime/README.md) | Runtime/provider manual invariants and confined host self-check procedures. | neyvia |
| [backend.proofs_d_runtime_auth](modules/backend.proofs_d_runtime_auth/README.md) | Transaction-local provider circuit and secret-free auth-queue contracts. | neyvia |
| [backend.proofs_d_ui_planning](modules/backend.proofs_d_ui_planning/README.md) | Semantic contracts at planning/UI service boundaries; no rendered-UI claims. | neyvia |
| [backend.proofs_dictation](modules/backend.proofs_dictation/README.md) | Executable dictation policy contracts shared by every production entry point. | neyvia |
| [backend.proofs_documents](modules/backend.proofs_documents/README.md) | Fast outcome contracts for study documents (manuals/cl/documents.cl, plan 22). | neyvia |
| [backend.proofs_e_chat](modules/backend.proofs_e_chat/README.md) | Per-action stream claims, independent of display and cursor implementations. | neyvia |
| [backend.proofs_e_host](modules/backend.proofs_e_host/README.md) | Production invariants for owned OS probes and portable host observations. | neyvia |
| [backend.proofs_e_release](modules/backend.proofs_e_release/README.md) | Executable PROOFS-e release, inventory and import-provenance postconditions. | neyvia |
| [backend.proofs_e_sv](modules/backend.proofs_e_sv/README.md) | Production invariants and confined startup checks for PROOFS-e's s-v share. | neyvia |
| [backend.proofs_e_wz](modules/backend.proofs_e_wz/README.md) | Contracts at authentication, background process, repair and source boundaries. | neyvia |
| [backend.proofs_event_recovery_journey](modules/backend.proofs_event_recovery_journey/README.md) | Bounded durable Native event-log recovery and refusal outcome contract. | neyvia |
| [backend.proofs_fast_contracts](modules/backend.proofs_fast_contracts/README.md) | Fast CL gate outcomes and migrated configuration authority cases. | neyvia |
| [backend.proofs_games_journey](modules/backend.proofs_games_journey/README.md) | Outcome contract for the local game asset export and import boundary. | neyvia |
| [backend.proofs_generator_outcomes](modules/backend.proofs_generator_outcomes/README.md) | Measured, read-only outcomes for Neyvia's three source generators. | neyvia |
| [backend.proofs_image_studio_journey](modules/backend.proofs_image_studio_journey/README.md) | Exercise real local Image Studio pixel edits and their durable observers. | neyvia |
| [backend.proofs_installed_preflight_journey](modules/backend.proofs_installed_preflight_journey/README.md) | Read-only outcome contract for local installed-program discovery and resolution. | neyvia |
| [backend.proofs_installer_extra](modules/backend.proofs_installer_extra/README.md) | Outcome contract for the real first-run onboarding snapshot projection. | neyvia |
| [backend.proofs_installer_journey](modules/backend.proofs_installer_journey/README.md) | Fast, offline proof of the real onboarding pack staging journey. | neyvia |
| [backend.proofs_laya_floor](modules/backend.proofs_laya_floor/README.md) | Fresh frozen CPU floor and live-browser route checks; no training. | neyvia |
| [backend.proofs_local_host_journey](modules/backend.proofs_local_host_journey/README.md) | A scoped local-host journey through Neyvia's native managed-process owner. | neyvia |
| [backend.proofs_local_session_fixture](modules/backend.proofs_local_session_fixture/README.md) | Finite child-process transport for confined owner proof adapters. | neyvia |
| [backend.proofs_manual_registry_journey](modules/backend.proofs_manual_registry_journey/README.md) | Outcome contract for grounded manual validation and nested-tool admission. | neyvia |
| [backend.proofs_measured_coverage](modules/backend.proofs_measured_coverage/README.md) | Contract for execution-traced coverage receipts and incremental admission. | neyvia |
| [backend.proofs_mission_journey](modules/backend.proofs_mission_journey/README.md) | Mission operator journey through the persisted control-room read model. | neyvia |
| [backend.proofs_notes_files](modules/backend.proofs_notes_files/README.md) | Durable Notes/Files action contracts; also used at UI/direct-call boundaries. | neyvia |
| [backend.proofs_onboarding_external_journey](modules/backend.proofs_onboarding_external_journey/README.md) | Outcome contract for authored external onboarding manifests and readiness. | neyvia |
| [backend.proofs_pack_generator](modules/backend.proofs_pack_generator/README.md) | Offline outcome contract for the actual local onboarding-pack generator. | neyvia |
| [backend.proofs_parallel_outcomes](modules/backend.proofs_parallel_outcomes/README.md) | Real Git/worktree lifecycle with confined local session transport. | neyvia |
| [backend.proofs_path_policy_outcomes](modules/backend.proofs_path_policy_outcomes/README.md) | Real disposable-Git outcomes for path policy and changed-line admission. | neyvia |
| [backend.proofs_pdf_backend_journey](modules/backend.proofs_pdf_backend_journey/README.md) | Real PDF bytes, PDFium raster, text-worker and refusal journey. | neyvia |
| [backend.proofs_plan_history](modules/backend.proofs_plan_history/README.md) | Bounded connected-session plan-history outcomes. | neyvia |
| [backend.proofs_project_files_journey](modules/backend.proofs_project_files_journey/README.md) | Outcome journey for registered Project Files browsing and export policy. | neyvia |
| [backend.proofs_python_sdk_journey](modules/backend.proofs_python_sdk_journey/README.md) | Outcome proof for the Python Neyvia SDK's typed HTTP 400 boundary. | neyvia |
| [backend.proofs_ratchet](modules/backend.proofs_ratchet/README.md) | C7 cases for the monotonic, source-bound release coverage ratchet. | neyvia |
| [backend.proofs_rel29_outcomes](modules/backend.proofs_rel29_outcomes/README.md) | Release-29 owner outcomes on disposable local state; no provider calls. | neyvia |
| [backend.proofs_release_outcomes](modules/backend.proofs_release_outcomes/README.md) | Selected release outcomes, using production observers and confined transports. | neyvia |
| [backend.proofs_research_journey](modules/backend.proofs_research_journey/README.md) | Local research search outcome through the production workspace-search path. | neyvia |
| [backend.proofs_resource_outcomes](modules/backend.proofs_resource_outcomes/README.md) | Observe real lease contention, bounded log capture and owned memory termination. | neyvia |
| [backend.proofs_runtime_edges](modules/backend.proofs_runtime_edges/README.md) | Migrated CL cases for budget authority and offline release parsing. | neyvia |
| [backend.proofs_runtime_journey](modules/backend.proofs_runtime_journey/README.md) | Bounded Native runtime admission and owned-process outcome contract. | neyvia |
| [backend.proofs_scene_outcomes](modules/backend.proofs_scene_outcomes/README.md) | Shared judge and rendered-video outcome owners, with fresh receipts. | neyvia |
| [backend.proofs_scroll_export_journey](modules/backend.proofs_scroll_export_journey/README.md) | Outcome contract for Scroll pack export and single-use phone delivery. | neyvia |
| [backend.proofs_semantic_outcomes](modules/backend.proofs_semantic_outcomes/README.md) | Fast native semantic outcomes using disposable production state. | neyvia |
| [backend.proofs_session_events_journey](modules/backend.proofs_session_events_journey/README.md) | Outcome contract for the connected-session event cursor stream. | neyvia |
| [backend.proofs_settings](modules/backend.proofs_settings/README.md) | Canonical Settings contracts checked inside its existing SQLite transaction. | neyvia |
| [backend.proofs_settings_journey](modules/backend.proofs_settings_journey/README.md) | A user-facing Settings preference journey over the production local service. | neyvia |
| [backend.proofs_surface_games_extra](modules/backend.proofs_surface_games_extra/README.md) | Game Dev's typed screen-selection state survives backend readback and rejects invalid tabs without overwriting it. | neyvia |
| [backend.proofs_transcript_journey](modules/backend.proofs_transcript_journey/README.md) | Fast production-parser journey for incremental Claude transcript pages. | neyvia |
| [backend.proofs_ui_planning_journey](modules/backend.proofs_ui_planning_journey/README.md) | One user-path contract for typed mission planning and execution authority. | neyvia |
| [backend.proofs_usage](modules/backend.proofs_usage/README.md) | Pure cases for the Usage endpoint contracts (usage.endpoint.shape, usage.plan.api-equivalent-only): no scan, process or network. | neyvia |
| [backend.proofs_web_reach](modules/backend.proofs_web_reach/README.md) | C7 contract for fail-closed static web source reachability. | neyvia |
| [backend.proofs_working_memory_journey](modules/backend.proofs_working_memory_journey/README.md) | Outcome contract for scoped working-memory continuity and retrieval. | neyvia |
| [backend.proofs_workspace_journey](modules/backend.proofs_workspace_journey/README.md) | Fast production workspace report to durable Outputs journey. | neyvia |
| [backend.provider_auth_broker](modules/backend.provider_auth_broker/README.md) | Provides backend / provider_auth_broker in Neyvia. | proofs |
| [backend.provider_auth_queue](modules/backend.provider_auth_queue/README.md) | Provides backend / provider_auth_queue in Neyvia. | neyvia |
| [backend.provider_catalog](modules/backend.provider_catalog/README.md) | Provider and model discovery for routes delegated to OpenCode. | neyvia |
| [backend.provider_state_io](modules/backend.provider_state_io/README.md) | Provides backend / provider_state_io in Neyvia. | neyvia |
| [backend.public_web_search](modules/backend.public_web_search/README.md) | Public search transports, with observed provider attribution and failures. | neyvia |
| [backend.read_only_workspace](modules/backend.read_only_workspace/README.md) | Provides backend / read_only_workspace in Neyvia. | neyvia |
| [backend.real_agent_proof](modules/backend.real_agent_proof/README.md) | Provides backend / real_agent_proof in Neyvia. | neyvia |
| [backend.reasoning_capabilities](modules/backend.reasoning_capabilities/README.md) | Provides backend / reasoning_capabilities in Neyvia. | neyvia |
| [backend.recovery_objects](modules/backend.recovery_objects/README.md) | Durable recovery objects for ambiguous or failed operations. | neyvia |
| [backend.replay](modules/backend.replay/README.md) | Provides backend / replay in Neyvia. | neyvia |
| [backend.reporting](modules/backend.reporting/README.md) | Provides backend / reporting in Neyvia. | neyvia |
| [backend.research](modules/backend.research/README.md) | Provides backend / research in Neyvia. | neyvia |
| [backend.research_evaluator](modules/backend.research_evaluator/README.md) | Question-scoped evaluation and budget finalization, adapted from Jina AI. | neyvia |
| [backend.research_grounding](modules/backend.research_grounding/README.md) | Soft reference matching; literal validation is reserved for verbatim quotes. | neyvia |
| [backend.research_hops](modules/backend.research_hops/README.md) | Bounded public research, expressed as a CL-Passage variation of CL-State. | neyvia |
| [backend.research_journey](modules/backend.research_journey/README.md) | Tool-only public research journey with verified citations. | neyvia |
| [backend.research_pipeline](modules/backend.research_pipeline/README.md) | Public-source research on shared Obscura tabs, with grounded cascade answers. | neyvia |
| [backend.research_quotes](modules/backend.research_quotes/README.md) | Host-bound actual quotations; models select spans rather than retype text. | neyvia |
| [backend.research_review_loop](modules/backend.research_review_loop/README.md) | Bounded evaluator feedback; exhausted attempts produce a best final answer. | neyvia |
| [backend.research_sol](modules/backend.research_sol/README.md) | Sol research with C10b source capture and separately measured grounding. | neyvia |
| [backend.research_sources](modules/backend.research_sources/README.md) | Resolve explicit public Wikipedia research dates through native web.fetch. | neyvia |
| [backend.research_state](modules/backend.research_state/README.md) | Bounded native tool observations with periodic resumable summary state. | neyvia |
| [backend.resource_admission](modules/backend.resource_admission/README.md) | Crash-safe managed-process admission; shared slots plus an operator reserve. | neyvia |
| [backend.runtime_auto_update](modules/backend.runtime_auto_update/README.md) | Provides backend / runtime_auto_update in Neyvia. | neyvia |
| [backend.runtime_capability_inventory](modules/backend.runtime_capability_inventory/README.md) | Small, secret-safe inventory for runtime tools, linked plugins, and MCP servers. | awareness |
| [backend.runtime_diagnostics](modules/backend.runtime_diagnostics/README.md) | Observed execution facts, without inferring a policy owner from error text. | neyvia |
| [backend.runtime_handback](modules/backend.runtime_handback/README.md) | Bring what a runtime produced back into the session that opened it. | neyvia |
| [backend.runtime_invocation](modules/backend.runtime_invocation/README.md) | Provides backend / runtime_invocation in Neyvia. | neyvia |
| [backend.runtime_lane_cycle](modules/backend.runtime_lane_cycle/README.md) | Provides backend / runtime_lane_cycle in Neyvia. | neyvia |
| [backend.runtime_supervisor](modules/backend.runtime_supervisor/README.md) | Provides backend / runtime_supervisor in Neyvia. | neyvia |
| [backend.runtime_updates](modules/backend.runtime_updates/README.md) | Provides backend / runtime_updates in Neyvia. | proofs |
| [backend.runtime_worker](modules/backend.runtime_worker/README.md) | Provides backend / runtime_worker in Neyvia. | neyvia |
| [backend.runtime_wrapper](modules/backend.runtime_wrapper/README.md) | Provides backend / runtime_wrapper in Neyvia. | neyvia |
| [backend.runtimes.__init__](modules/backend.runtimes.__init__/README.md) | Provides backend / runtimes / __init__ in Neyvia. | neyvia |
| [backend.runtimes.base](modules/backend.runtimes.base/README.md) | Provides backend / runtimes / base in Neyvia. | neyvia |
| [backend.runtimes.codex](modules/backend.runtimes.codex/README.md) | Provides backend / runtimes / codex in Neyvia. | neyvia |
| [backend.runtimes.cursor](modules/backend.runtimes.cursor/README.md) | Provides backend / runtimes / cursor in Neyvia. | neyvia |
| [backend.runtimes.hermes](modules/backend.runtimes.hermes/README.md) | Provides backend / runtimes / hermes in Neyvia. | neyvia |
| [backend.runtimes.managed_cli](modules/backend.runtimes.managed_cli/README.md) | Provides backend / runtimes / managed_cli in Neyvia. | neyvia |
| [backend.runtimes.neyvia](modules/backend.runtimes.neyvia/README.md) | Provides backend / runtimes / neyvia in Neyvia. | neyvia |
| [backend.runtimes.openclaw](modules/backend.runtimes.openclaw/README.md) | Provides backend / runtimes / openclaw in Neyvia. | neyvia |
| [backend.runtimes.opencode](modules/backend.runtimes.opencode/README.md) | Provides backend / runtimes / opencode in Neyvia. | neyvia |
| [backend.safety](modules/backend.safety/README.md) | Provides backend / safety in Neyvia. | neyvia |
| [backend.scene_core.__init__](modules/backend.scene_core.__init__/README.md) | Shared transcribe -> define -> judge -> improve mechanism (Scene v1). | laya-glance |
| [backend.scene_core.gamedev](modules/backend.scene_core.gamedev/README.md) | Thin native editor adapters; all predicates and retention run in scene_core. | neyvia |
| [backend.scene_core.image_cameras](modules/backend.scene_core.image_cameras/README.md) | LAYA eyes for concept-art sheets: fit one weak-perspective camera per view. | neyvia |
| [backend.scene_core.image_model](modules/backend.scene_core.image_model/README.md) | LAYA inverse graphics adapter: sheet pixels -> CL observation -> CL shape program -> | neyvia |
| [backend.scene_core.image_parts](modules/backend.scene_core.image_parts/README.md) | Local image eyes: mask -> CL parts, outlines, proportions and colour, never a mesh generator. | neyvia |
| [backend.scene_core.image_sheets](modules/backend.scene_core.image_sheets/README.md) | SEE for character/prop sheets: physical cells -> matted views -> fitted cameras -> CL. | neyvia |
| [backend.scene_core.lens_programs.absolute_path_scan](modules/backend.scene_core.lens_programs.absolute_path_scan/README.md) | Provides backend / scene_core / lens_programs / absolute_path_scan in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.culled_interior_voids](modules/backend.scene_core.lens_programs.culled_interior_voids/README.md) | Provides backend / scene_core / lens_programs / culled_interior_voids in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.culled_surface_gaps](modules/backend.scene_core.lens_programs.culled_surface_gaps/README.md) | Provides backend / scene_core / lens_programs / culled_surface_gaps in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.culled_surface_hole_area](modules/backend.scene_core.lens_programs.culled_surface_hole_area/README.md) | Provides backend / scene_core / lens_programs / culled_surface_hole_area in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.culled_surface_hole_area_d580075b](modules/backend.scene_core.lens_programs.culled_surface_hole_area_d580075b/README.md) | Provides backend / scene_core / lens_programs / culled_surface_hole_area_d580075b in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.culled_surface_holes](modules/backend.scene_core.lens_programs.culled_surface_holes/README.md) | Provides backend / scene_core / lens_programs / culled_surface_holes in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.culling_gap_area](modules/backend.scene_core.lens_programs.culling_gap_area/README.md) | Provides backend / scene_core / lens_programs / culling_gap_area in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.detached_orange_piece_gap](modules/backend.scene_core.lens_programs.detached_orange_piece_gap/README.md) | Provides backend / scene_core / lens_programs / detached_orange_piece_gap in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.detached_subject_floaters](modules/backend.scene_core.lens_programs.detached_subject_floaters/README.md) | Provides backend / scene_core / lens_programs / detached_subject_floaters in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.detached_subject_pieces](modules/backend.scene_core.lens_programs.detached_subject_pieces/README.md) | Provides backend / scene_core / lens_programs / detached_subject_pieces in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.edge_control_cut](modules/backend.scene_core.lens_programs.edge_control_cut/README.md) | Provides backend / scene_core / lens_programs / edge_control_cut in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.encoded_path_text](modules/backend.scene_core.lens_programs.encoded_path_text/README.md) | Provides backend / scene_core / lens_programs / encoded_path_text in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.field_edge_text_truncation](modules/backend.scene_core.lens_programs.field_edge_text_truncation/README.md) | Provides backend / scene_core / lens_programs / field_edge_text_truncation in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.floating_text_intrusion](modules/backend.scene_core.lens_programs.floating_text_intrusion/README.md) | Provides backend / scene_core / lens_programs / floating_text_intrusion in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.foreign_text_through_surface](modules/backend.scene_core.lens_programs.foreign_text_through_surface/README.md) | Provides backend / scene_core / lens_programs / foreign_text_through_surface in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.glyph_boundary_clipping](modules/backend.scene_core.lens_programs.glyph_boundary_clipping/README.md) | Provides backend / scene_core / lens_programs / glyph_boundary_clipping in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.glyph_edge_clipping](modules/backend.scene_core.lens_programs.glyph_edge_clipping/README.md) | Provides backend / scene_core / lens_programs / glyph_edge_clipping in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.internal_id_copy](modules/backend.scene_core.lens_programs.internal_id_copy/README.md) | Provides backend / scene_core / lens_programs / internal_id_copy in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.internal_identifier_copy](modules/backend.scene_core.lens_programs.internal_identifier_copy/README.md) | Provides backend / scene_core / lens_programs / internal_identifier_copy in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.internal_identifier_copy_136476a4](modules/backend.scene_core.lens_programs.internal_identifier_copy_136476a4/README.md) | Provides backend / scene_core / lens_programs / internal_identifier_copy_136476a4 in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.internal_identifier_copy_e2be8b4f](modules/backend.scene_core.lens_programs.internal_identifier_copy_e2be8b4f/README.md) | Provides backend / scene_core / lens_programs / internal_identifier_copy_e2be8b4f in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.non_text_overlap](modules/backend.scene_core.lens_programs.non_text_overlap/README.md) | Provides backend / scene_core / lens_programs / non_text_overlap in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.painted_text_obstruction](modules/backend.scene_core.lens_programs.painted_text_obstruction/README.md) | Provides backend / scene_core / lens_programs / painted_text_obstruction in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.panel_bottom_control_cut](modules/backend.scene_core.lens_programs.panel_bottom_control_cut/README.md) | Provides backend / scene_core / lens_programs / panel_bottom_control_cut in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.right_edge_control_truncation](modules/backend.scene_core.lens_programs.right_edge_control_truncation/README.md) | Provides backend / scene_core / lens_programs / right_edge_control_truncation in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.right_edge_control_truncation_9a414a17](modules/backend.scene_core.lens_programs.right_edge_control_truncation_9a414a17/README.md) | Provides backend / scene_core / lens_programs / right_edge_control_truncation_9a414a17 in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.same_layer_element_overlap](modules/backend.scene_core.lens_programs.same_layer_element_overlap/README.md) | Provides backend / scene_core / lens_programs / same_layer_element_overlap in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.subject_height_scale](modules/backend.scene_core.lens_programs.subject_height_scale/README.md) | Provides backend / scene_core / lens_programs / subject_height_scale in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.subject_reference_height_ratio](modules/backend.scene_core.lens_programs.subject_reference_height_ratio/README.md) | Provides backend / scene_core / lens_programs / subject_reference_height_ratio in Neyvia. | neyvia |
| [backend.scene_core.lens_programs.visible_path_copy](modules/backend.scene_core.lens_programs.visible_path_copy/README.md) | Provides backend / scene_core / lens_programs / visible_path_copy in Neyvia. | neyvia |
| [backend.scene_core.lenses](modules/backend.scene_core.lenses/README.md) | Lens registry: LAYA's eyes as a growing set of small measuring programs (plan 24). | neyvia |
| [backend.scroll_cost](modules/backend.scroll_cost/README.md) | Observed generation usage, with explicitly supplied USD-per-million prices only. | neyvia |
| [backend.scroll_generation](modules/backend.scroll_generation/README.md) | Source-bound Scroll Study generation: deterministic procedures and bounded T14 decisions. | neyvia |
| [backend.scroll_pack](modules/backend.scroll_pack/README.md) | Scroll Study's untrusted pack boundary; source spans use Unicode character offsets. | neyvia |
| [backend.scroll_study_format](modules/backend.scroll_study_format/README.md) | Paul's seven-part course pack, generated and checked through the T14 owner. | neyvia |
| [backend.sdk](modules/backend.sdk/README.md) | Provides backend / sdk in Neyvia. | neyvia |
| [backend.sdk_cli](modules/backend.sdk_cli/README.md) | Safe CLI workflows over Neyvia's typed marketplace and surface services. | neyvia |
| [backend.sdk_codegen](modules/backend.sdk_codegen/README.md) | Deterministic Python and TypeScript bindings for Neyvia public schemas. | neyvia |
| [backend.secret_broker](modules/backend.secret_broker/README.md) | Opaque, one-time secret injection over a Bitwarden-compatible vault. | neyvia |
| [backend.security_runtime_policy](modules/backend.security_runtime_policy/README.md) | Scope and proof contracts for authorized red/blue-team missions. | neyvia |
| [backend.self_repair](modules/backend.self_repair/README.md) | Provides backend / self_repair in Neyvia. | neyvia |
| [backend.semantic_dispatch](modules/backend.semantic_dispatch/README.md) | Durable receipts around scheduled dispatch; downstream authority stays intact. | neyvia |
| [backend.semantic_missions](modules/backend.semantic_missions/README.md) | Durable semantic objects for missions and collaborative conversations. | neyvia |
| [backend.semantic_tools](modules/backend.semantic_tools/README.md) | Bounded native-tool handlers for Neyvia's durable semantic objects. | neyvia |
| [backend.session_compaction](modules/backend.session_compaction/README.md) | Incremental, durable semantic compaction at the model-input boundary. | neyvia |
| [backend.session_store](modules/backend.session_store/README.md) | Provides backend / session_store in Neyvia. | neyvia |
| [backend.shared_environments](modules/backend.shared_environments/README.md) | Pinned isolated environments with a shared uv cache and durable execution receipts. | neyvia |
| [backend.sidebar_model_assets](modules/backend.sidebar_model_assets/README.md) | Immutable public sidebar model assets; bounded lazy acquisition, no account. | neyvia |
| [backend.situation_browser](modules/backend.situation_browser/README.md) | Browser adapter for the situation protocol, using existing origin and action gates. | neyvia |
| [backend.situation_interface](modules/backend.situation_interface/README.md) | Durable situations and task-focused views over grounded browser observations. | neyvia |
| [backend.situation_service](modules/backend.situation_service/README.md) | Keep the browser on one owner thread across HTTP requests and SDK tool calls. | neyvia |
| [backend.situation_tools](modules/backend.situation_tools/README.md) | Provides backend / situation_tools in Neyvia. | neyvia |
| [backend.skill_capsules](modules/backend.skill_capsules/README.md) | Executable skill capsules layered over human-readable skill instructions. | neyvia |
| [backend.skill_import](modules/backend.skill_import/README.md) | Safe staging and explicit installation of local skill files and archives. | neyvia |
| [backend.skill_iteration](modules/backend.skill_iteration/README.md) | Provides backend / skill_iteration in Neyvia. | neyvia |
| [backend.skill_library](modules/backend.skill_library/README.md) | Provides backend / skill_library in Neyvia. | neyvia |
| [backend.skill_package](modules/backend.skill_package/README.md) | Shared validation and interface metadata for durable Codex skill packages. | neyvia |
| [backend.skills](modules/backend.skills/README.md) | Provides backend / skills in Neyvia. | neyvia |
| [backend.snapshot_cache](modules/backend.snapshot_cache/README.md) | Provides backend / snapshot_cache in Neyvia. | neyvia |
| [backend.source_marketplace](modules/backend.source_marketplace/README.md) | Developer-source apps and mods on the existing marketplace catalog and host. | modules |
| [backend.study_docs](modules/backend.study_docs/README.md) | Paul's study documents: the neyvia-study LaTeX class, Tectonic builds and outcome checks. | neyvia |
| [backend.sub_agent_receipts](modules/backend.sub_agent_receipts/README.md) | Provides backend / sub_agent_receipts in Neyvia. | neyvia |
| [backend.subprocess_utils](modules/backend.subprocess_utils/README.md) | Provides backend / subprocess_utils in Neyvia. | neyvia |
| [backend.suite_report](modules/backend.suite_report/README.md) | Provides backend / suite_report in Neyvia. | neyvia |
| [backend.support_bundle](modules/backend.support_bundle/README.md) | Provides backend / support_bundle in Neyvia. | neyvia |
| [backend.system_audit](modules/backend.system_audit/README.md) | Provides backend / system_audit in Neyvia. | neyvia |
| [backend.task_continuity](modules/backend.task_continuity/README.md) | Durable, bounded cross-device task resume checkpoints. | neyvia |
| [backend.task_feedback](modules/backend.task_feedback/README.md) | Terminal task feedback, shared by connected UI and workspace tools. | neyvia-core |
| [backend.taste_budget](modules/backend.taste_budget/README.md) | Admission reservations and measured accounting for a finite taste run. | neyvia |
| [backend.taste_checks](modules/backend.taste_checks/README.md) | Deterministic page checks the C13 critic kept missing (taste.cl, section "deterministic page checks"). | neyvia |
| [backend.taste_context](modules/backend.taste_context/README.md) | Bounded C13 views. Raw source/reports remain durable; projections are not proof. | neyvia |
| [backend.taste_contracts](modules/backend.taste_contracts/README.md) | Host-owned observers for the C13 executable manual contracts. | neyvia |
| [backend.taste_episode_export](modules/backend.taste_episode_export/README.md) | Append provenance-bound taste episodes for the independently owned LAYA store. | neyvia |
| [backend.taste_fewshot](modules/backend.taste_fewshot/README.md) | Head-free, provenance-bound taste conditioning and selective calibration. | neyvia |
| [backend.taste_fewshot_contracts](modules/backend.taste_fewshot_contracts/README.md) | Real-data observations for the authored R12 Connected Language checks. | neyvia |
| [backend.taste_fusion](modules/backend.taste_fusion/README.md) | Sol concept/draft/final crops, Luna reading/repairs, one measured arm budget. | neyvia |
| [backend.taste_gate](modules/backend.taste_gate/README.md) | Host-owned C13 draft, rendered difference and targeted repair completion gate. | neyvia |
| [backend.taste_judge](modules/backend.taste_judge/README.md) | Frozen text judges; visual taste still requires an image critic. | neyvia |
| [backend.taste_labels](modules/backend.taste_labels/README.md) | Blind-vote labels with identity and quality kept apart (plan 20 C9/C13, ASTRA2 review section 2). | neyvia |
| [backend.taste_laya](modules/backend.taste_laya/README.md) | C13 routine advice only; no service start and no completion authority. | neyvia |
| [backend.taste_lens](modules/backend.taste_lens/README.md) | Rendered taste awareness for Neyvia Native. | neyvia |
| [backend.taste_model](modules/backend.taste_model/README.md) | Metered, tool-free Luna image judgement and bounded targeted repair transport. | neyvia |
| [backend.taste_sources](modules/backend.taste_sources/README.md) | Verify claimed paper citations against primary DOI registration metadata. | neyvia |
| [backend.taste_spelling](modules/backend.taste_spelling/README.md) | Offline English/French Hunspell checks of rendered text. | neyvia |
| [backend.taste_vision](modules/backend.taste_vision/README.md) | Frozen local CLIP pixels with separate, reversible corrective/personal heads. | neyvia |
| [backend.thunder_compute](modules/backend.thunder_compute/README.md) | Work with the user's existing Thunder Compute account through connected Chrome. | neyvia |
| [backend.tool_factory](modules/backend.tool_factory/README.md) | Author, adapt, validate, and persist workspace-scoped N-E-Y-V-I-A tools. | neyvia |
| [backend.tool_manifest_registry](modules/backend.tool_manifest_registry/README.md) | Validated inventory for external tools that extend Neyvia capabilities. | neyvia |
| [backend.transition_memory](modules/backend.transition_memory/README.md) | Positive, scope-bound executable transitions backed by immutable journey receipts. | neyvia |
| [backend.turn_compartment](modules/backend.turn_compartment/README.md) | Persist a chat turn's runtime compartment as its own data plus a reference. | neyvia |
| [backend.ui_command_bus](modules/backend.ui_command_bus/README.md) | Durable backend-to-UI commands shared by the web service and model workers. | neyvia |
| [backend.ui_graph](modules/backend.ui_graph/README.md) | Resident browser UI graph: normalized nodes, revisions, semantic hash, compact deltas. | neyvia |
| [backend.ui_observer](modules/backend.ui_observer/README.md) | Browser-first UI observation adapters (Playwright a11y preferred; CDP AX fallback). | neyvia |
| [backend.ui_tools](modules/backend.ui_tools/README.md) | Compact model-facing UI query tools (ui.find / ui.diff / ui.do / …). | neyvia |
| [backend.ultra_reasoning](modules/backend.ultra_reasoning/README.md) | Provides backend / ultra_reasoning in Neyvia. | neyvia |
| [backend.updater_contract](modules/backend.updater_contract/README.md) | Offline, fail-closed contract for signed Neyvia desktop updates. | neyvia |
| [backend.usage_report](modules/backend.usage_report/README.md) | Token and plan-usage analytics for the Usage pane (GET /api/ui/usage). | neyvia |
| [backend.venv_sync](modules/backend.venv_sync/README.md) | Keep Neyvia's managed Python environment in step with the bundled requirements. | neyvia |
| [backend.verification](modules/backend.verification/README.md) | Provides backend / verification in Neyvia. | neyvia |
| [backend.verification_ladder](modules/backend.verification_ladder/README.md) | Provides backend / verification_ladder in Neyvia. | neyvia |
| [backend.verified_operations](modules/backend.verified_operations/README.md) | Durable, authority-bound operations with observable verification. | neyvia |
| [backend.vibe_suggestions](modules/backend.vibe_suggestions/README.md) | Provides backend / vibe_suggestions in Neyvia. | neyvia |
| [backend.video_contracts](modules/backend.video_contracts/README.md) | Fast outcome contracts for rendered video (plan 22 style), plus a fixture that proves each one bites. | video |
| [backend.video_hyperframes](modules/backend.video_hyperframes/README.md) | Edit decision lists compiled to HyperFrames compositions, driven headless. | video |
| [backend.video_tools](modules/backend.video_tools/README.md) | Provides backend / video_tools in Neyvia. | neyvia |
| [backend.visual_specifications](modules/backend.visual_specifications/README.md) | Persistent, provenance-bound visual specifications and deterministic edits. | neyvia |
| [backend.web_auth_sessions](modules/backend.web_auth_sessions/README.md) | Durable storage for web account sessions. | neyvia |
| [backend.web_backend](modules/backend.web_backend/README.md) | Provides backend / web_backend in Neyvia. | neyvia |
| [backend.web_backend_cache](modules/backend.web_backend_cache/README.md) | Provides backend / web_backend_cache in Neyvia. | neyvia |
| [backend.web_backend_chat](modules/backend.web_backend_chat/README.md) | Chat routing, CLI transports and durable turn persistence. | memory |
| [backend.web_backend_http](modules/backend.web_backend_http/README.md) | Authenticated HTTP transport for the public backend facade. | neyvia |
| [backend.web_backend_receipts](modules/backend.web_backend_receipts/README.md) | Provides backend / web_backend_receipts in Neyvia. | neyvia |
| [backend.web_backend_serving](modules/backend.web_backend_serving/README.md) | Provides backend / web_backend_serving in Neyvia. | neyvia |
| [backend.web_backend_workspace](modules/backend.web_backend_workspace/README.md) | Provides backend / web_backend_workspace in Neyvia. | neyvia |
| [backend.web_documents](modules/backend.web_documents/README.md) | Persistent immutable fetched documents, bounded continuations and grounded citations. | neyvia-core |
| [backend.windows_ios_compiler](modules/backend.windows_ios_compiler/README.md) | Provides backend / windows_ios_compiler in Neyvia. | neyvia |
| [backend.windows_macos_compiler](modules/backend.windows_macos_compiler/README.md) | Universal AppKit/WKWebView web-export bundle, compiled on Windows. | neyvia |
| [backend.worker](modules/backend.worker/README.md) | Provides backend / worker in Neyvia. | neyvia |
| [backend.workflow_evolver](modules/backend.workflow_evolver/README.md) | Workflow text domains on the existing frozen, paired Evolver mechanism. | neyvia |
| [backend.workflow_manuals](modules/backend.workflow_manuals/README.md) | Executable workflow adherence; measurements belong to host receipts, not prose. | neyvia |
| [backend.workflow_panels](modules/backend.workflow_panels/README.md) | Freeze future workflow task data from local source, maths and render artifacts. | neyvia |
| [backend.working_memory](modules/backend.working_memory/README.md) | Durable, bounded working memory for long-running Neyvia missions. | neyvia |
| [backend.workspace_actions](modules/backend.workspace_actions/README.md) | Provides backend / workspace_actions in Neyvia. | neyvia |
| [backend.workspace_intelligence](modules/backend.workspace_intelligence/README.md) | Artifact rationale, self-defending obligations, and executable handoffs. | neyvia |
| [backend.workspace_patches](modules/backend.workspace_patches/README.md) | Hash-bound character edits. Coordinates refer to the exact UTF-8 read snapshot. | neyvia |
| [backend.x_following_sources](modules/backend.x_following_sources/README.md) | Provides backend / x_following_sources in Neyvia. | neyvia |
| [configuration.app_sdk.desktop.native](modules/configuration.app_sdk.desktop.native/README.md) | Provides configuration / app_sdk / desktop / native in Neyvia. | neyvia |
| [configuration.app_sdk.expo.App](modules/configuration.app_sdk.expo.App/README.md) | Provides configuration / app_sdk / expo / App in Neyvia. | neyvia |
| [configuration.app_sdk.web.app](modules/configuration.app_sdk.web.app/README.md) | Provides configuration / app_sdk / web / app in Neyvia. | neyvia |
| [configuration.app_sdk.web.index](modules/configuration.app_sdk.web.index/README.md) | Provides configuration / app_sdk / web / index in Neyvia. | neyvia |
| [configuration.app_sdk.web.model](modules/configuration.app_sdk.web.model/README.md) | Provides configuration / app_sdk / web / model in Neyvia. | neyvia |
| [configuration.app_sdk.web.sdk](modules/configuration.app_sdk.web.sdk/README.md) | Provides configuration / app_sdk / web / sdk in Neyvia. | neyvia |
| [configuration.app_sdk.web.sw](modules/configuration.app_sdk.web.sw/README.md) | Provides configuration / app_sdk / web / sw in Neyvia. | neyvia |
| [configuration.browser.manual.contract](modules/configuration.browser.manual.contract/README.md) | Provides configuration / browser / manual / contract in Neyvia. | neyvia |
| [configuration.browser_goal_clauses](modules/configuration.browser_goal_clauses/README.md) | Provides configuration / browser_goal_clauses in Neyvia. | neyvia |
| [configuration.c13-taste](modules/configuration.c13-taste/README.md) | Provides configuration / c13-taste in Neyvia. | neyvia |
| [configuration.capability_packs](modules/configuration.capability_packs/README.md) | Provides configuration / capability_packs in Neyvia. | neyvia |
| [configuration.challenge_presets](modules/configuration.challenge_presets/README.md) | Provides configuration / challenge_presets in Neyvia. | neyvia |
| [configuration.cl_done_skills](modules/configuration.cl_done_skills/README.md) | Provides configuration / cl_done_skills in Neyvia. | neyvia |
| [configuration.cl_skills.deliverables](modules/configuration.cl_skills.deliverables/README.md) | Provides configuration / cl_skills / deliverables in Neyvia. | neyvia |
| [configuration.cl_skills.no-slop](modules/configuration.cl_skills.no-slop/README.md) | Provides configuration / cl_skills / no-slop in Neyvia. | neyvia |
| [configuration.components](modules/configuration.components/README.md) | Provides configuration / components in Neyvia. | neyvia |
| [configuration.connected_apps](modules/configuration.connected_apps/README.md) | Provides configuration / connected_apps in Neyvia. | neyvia |
| [configuration.constitution](modules/configuration.constitution/README.md) | Provides configuration / constitution in Neyvia. | neyvia |
| [configuration.contract_module_map](modules/configuration.contract_module_map/README.md) | Provides configuration / contract_module_map in Neyvia. | neyvia |
| [configuration.contract_path_policy](modules/configuration.contract_path_policy/README.md) | Provides configuration / contract_path_policy in Neyvia. | neyvia |
| [configuration.cua-desktop-contract](modules/configuration.cua-desktop-contract/README.md) | Provides configuration / cua-desktop-contract in Neyvia. | neyvia |
| [configuration.cua-everyday-tasks](modules/configuration.cua-everyday-tasks/README.md) | Provides configuration / cua-everyday-tasks in Neyvia. | neyvia |
| [configuration.design_details](modules/configuration.design_details/README.md) | Provides configuration / design_details in Neyvia. | neyvia |
| [configuration.fixcl_manual_cache](modules/configuration.fixcl_manual_cache/README.md) | Provides configuration / fixcl_manual_cache in Neyvia. | neyvia |
| [configuration.laya-ui-fixes.pdf-module-worker-fallback](modules/configuration.laya-ui-fixes.pdf-module-worker-fallback/README.md) | Provides configuration / laya-ui-fixes / pdf-module-worker-fallback in Neyvia. | neyvia |
| [configuration.laya-ui-fixes.pdf-plain-skeleton](modules/configuration.laya-ui-fixes.pdf-plain-skeleton/README.md) | Provides configuration / laya-ui-fixes / pdf-plain-skeleton in Neyvia. | neyvia |
| [configuration.laya_glance_calibration](modules/configuration.laya_glance_calibration/README.md) | Provides configuration / laya_glance_calibration in Neyvia. | neyvia |
| [configuration.laya_lenses](modules/configuration.laya_lenses/README.md) | Provides configuration / laya_lenses in Neyvia. | neyvia |
| [configuration.laya_ui_fix_library](modules/configuration.laya_ui_fix_library/README.md) | Provides configuration / laya_ui_fix_library in Neyvia. | neyvia |
| [configuration.lesson_learning](modules/configuration.lesson_learning/README.md) | Provides configuration / lesson_learning in Neyvia. | neyvia |
| [configuration.lesson_preferences](modules/configuration.lesson_preferences/README.md) | Provides configuration / lesson_preferences in Neyvia. | neyvia |
| [configuration.model_prices](modules/configuration.model_prices/README.md) | Provides configuration / model_prices in Neyvia. | neyvia |
| [configuration.modes](modules/configuration.modes/README.md) | Provides configuration / modes in Neyvia. | neyvia |
| [configuration.neyvia_application_surface_schema](modules/configuration.neyvia_application_surface_schema/README.md) | Provides configuration / neyvia_application_surface_schema in Neyvia. | neyvia |
| [configuration.neyvia_apps](modules/configuration.neyvia_apps/README.md) | Provides configuration / neyvia_apps in Neyvia. | neyvia |
| [configuration.neyvia_behavior_capsules](modules/configuration.neyvia_behavior_capsules/README.md) | Provides configuration / neyvia_behavior_capsules in Neyvia. | neyvia |
| [configuration.neyvia_browser_authority](modules/configuration.neyvia_browser_authority/README.md) | Provides configuration / neyvia_browser_authority in Neyvia. | neyvia |
| [configuration.neyvia_chat](modules/configuration.neyvia_chat/README.md) | Provides configuration / neyvia_chat in Neyvia. | neyvia |
| [configuration.neyvia_context_policy](modules/configuration.neyvia_context_policy/README.md) | Provides configuration / neyvia_context_policy in Neyvia. | neyvia |
| [configuration.neyvia_dependency_inventory_policy](modules/configuration.neyvia_dependency_inventory_policy/README.md) | Provides configuration / neyvia_dependency_inventory_policy in Neyvia. | neyvia |
| [configuration.neyvia_design_language](modules/configuration.neyvia_design_language/README.md) | Provides configuration / neyvia_design_language in Neyvia. | neyvia |
| [configuration.neyvia_folder_sync](modules/configuration.neyvia_folder_sync/README.md) | Provides configuration / neyvia_folder_sync in Neyvia. | neyvia |
| [configuration.neyvia_install_profiles](modules/configuration.neyvia_install_profiles/README.md) | Provides configuration / neyvia_install_profiles in Neyvia. | neyvia |
| [configuration.neyvia_manuals](modules/configuration.neyvia_manuals/README.md) | Provides configuration / neyvia_manuals in Neyvia. | neyvia |
| [configuration.neyvia_marketplace_apps](modules/configuration.neyvia_marketplace_apps/README.md) | Provides configuration / neyvia_marketplace_apps in Neyvia. | neyvia |
| [configuration.neyvia_marketplace_toolchain](modules/configuration.neyvia_marketplace_toolchain/README.md) | Provides configuration / neyvia_marketplace_toolchain in Neyvia. | neyvia |
| [configuration.neyvia_mesh](modules/configuration.neyvia_mesh/README.md) | Provides configuration / neyvia_mesh in Neyvia. | neyvia |
| [configuration.neyvia_module_manifest_schema](modules/configuration.neyvia_module_manifest_schema/README.md) | Provides configuration / neyvia_module_manifest_schema in Neyvia. | neyvia |
| [configuration.neyvia_nearby_send](modules/configuration.neyvia_nearby_send/README.md) | Provides configuration / neyvia_nearby_send in Neyvia. | neyvia |
| [configuration.neyvia_onboarding](modules/configuration.neyvia_onboarding/README.md) | Provides configuration / neyvia_onboarding in Neyvia. | neyvia |
| [configuration.neyvia_p2p_cache](modules/configuration.neyvia_p2p_cache/README.md) | Provides configuration / neyvia_p2p_cache in Neyvia. | neyvia |
| [configuration.neyvia_performance_budgets](modules/configuration.neyvia_performance_budgets/README.md) | Provides configuration / neyvia_performance_budgets in Neyvia. | neyvia |
| [configuration.neyvia_remote](modules/configuration.neyvia_remote/README.md) | Provides configuration / neyvia_remote in Neyvia. | neyvia |
| [configuration.neyvia_runtime_stack](modules/configuration.neyvia_runtime_stack/README.md) | Provides configuration / neyvia_runtime_stack in Neyvia. | neyvia |
| [configuration.neyvia_skill_capsules](modules/configuration.neyvia_skill_capsules/README.md) | Provides configuration / neyvia_skill_capsules in Neyvia. | neyvia |
| [configuration.neyvia_updater](modules/configuration.neyvia_updater/README.md) | Provides configuration / neyvia_updater in Neyvia. | neyvia |
| [configuration.nightshift.manual.contract](modules/configuration.nightshift.manual.contract/README.md) | Provides configuration / nightshift / manual / contract in Neyvia. | neyvia |
| [configuration.ocr_benchmark_manifest.sample](modules/configuration.ocr_benchmark_manifest.sample/README.md) | Provides configuration / ocr_benchmark_manifest / sample in Neyvia. | neyvia |
| [configuration.ocr_benchmark_manifest.schema](modules/configuration.ocr_benchmark_manifest.schema/README.md) | Provides configuration / ocr_benchmark_manifest / schema in Neyvia. | neyvia |
| [configuration.ocr_model_candidates](modules/configuration.ocr_model_candidates/README.md) | Provides configuration / ocr_model_candidates in Neyvia. | neyvia |
| [configuration.onboarding_packs](modules/configuration.onboarding_packs/README.md) | Provides configuration / onboarding_packs in Neyvia. | neyvia |
| [configuration.onboarding_packs.pack.android-lab.manifest](modules/configuration.onboarding_packs.pack.android-lab.manifest/README.md) | Provides configuration / onboarding_packs / pack / android-lab / manifest in Neyvia. | neyvia |
| [configuration.onboarding_packs.pack.developer-toolchains.manifest](modules/configuration.onboarding_packs.pack.developer-toolchains.manifest/README.md) | Provides configuration / onboarding_packs / pack / developer-toolchains / manifest in Neyvia. | neyvia |
| [configuration.onboarding_packs.pack.documents-office.manifest](modules/configuration.onboarding_packs.pack.documents-office.manifest/README.md) | Provides configuration / onboarding_packs / pack / documents-office / manifest in Neyvia. | neyvia |
| [configuration.onboarding_packs.pack.media-creative.manifest](modules/configuration.onboarding_packs.pack.media-creative.manifest/README.md) | Provides configuration / onboarding_packs / pack / media-creative / manifest in Neyvia. | neyvia |
| [configuration.onboarding_packs.pack.mesh-control-plane.manifest](modules/configuration.onboarding_packs.pack.mesh-control-plane.manifest/README.md) | Provides configuration / onboarding_packs / pack / mesh-control-plane / manifest in Neyvia. | neyvia |
| [configuration.onboarding_packs.pack.models-gpu.manifest](modules/configuration.onboarding_packs.pack.models-gpu.manifest/README.md) | Provides configuration / onboarding_packs / pack / models-gpu / manifest in Neyvia. | neyvia |
| [configuration.onboarding_packs.pack.ocr-local.manifest](modules/configuration.onboarding_packs.pack.ocr-local.manifest/README.md) | Provides configuration / onboarding_packs / pack / ocr-local / manifest in Neyvia. | neyvia |
| [configuration.pandoc_filters.neyvia_docx_layout](modules/configuration.pandoc_filters.neyvia_docx_layout/README.md) | Provides configuration / pandoc_filters / neyvia_docx_layout in Neyvia. | neyvia |
| [configuration.personas](modules/configuration.personas/README.md) | Provides configuration / personas in Neyvia. | neyvia |
| [configuration.profiles](modules/configuration.profiles/README.md) | Provides configuration / profiles in Neyvia. | neyvia |
| [configuration.proof-coverage-revalidation](modules/configuration.proof-coverage-revalidation/README.md) | Provides configuration / proof-coverage-revalidation in Neyvia. | neyvia |
| [configuration.proofs-d-scope](modules/configuration.proofs-d-scope/README.md) | Provides configuration / proofs-d-scope in Neyvia. | neyvia |
| [configuration.reference_documents.neyvia-pandoc-reference](modules/configuration.reference_documents.neyvia-pandoc-reference/README.md) | Provides configuration / reference_documents / neyvia-pandoc-reference in Neyvia. | neyvia |
| [configuration.scroll-study-pack.schema](modules/configuration.scroll-study-pack.schema/README.md) | Provides configuration / scroll-study-pack / schema in Neyvia. | neyvia |
| [configuration.scroll-study-prices](modules/configuration.scroll-study-prices/README.md) | Provides configuration / scroll-study-prices in Neyvia. | neyvia |
| [configuration.scroll-study-procedures](modules/configuration.scroll-study-procedures/README.md) | Provides configuration / scroll-study-procedures in Neyvia. | neyvia |
| [configuration.settings.manual.contract](modules/configuration.settings.manual.contract/README.md) | Provides configuration / settings / manual / contract in Neyvia. | neyvia |
| [configuration.skills](modules/configuration.skills/README.md) | Provides configuration / skills in Neyvia. | neyvia |
| [configuration.tool_suite_lock](modules/configuration.tool_suite_lock/README.md) | Provides configuration / tool_suite_lock in Neyvia. | neyvia |
| [configuration.user_profile](modules/configuration.user_profile/README.md) | Provides configuration / user_profile in Neyvia. | neyvia |
| [connector.android](modules/connector.android/README.md) | Game development integration described by game-dev.cl for Android. | game-dev |
| [connector.blender](modules/connector.blender/README.md) | Game development integration described by game-dev.cl for Blender. | game-dev |
| [connector.godot](modules/connector.godot/README.md) | Game development integration described by game-dev.cl for Godot. | game-dev |
| [connector.roblox](modules/connector.roblox/README.md) | Game development integration described by game-dev.cl for Roblox. | game-dev |
| [connector.unity](modules/connector.unity/README.md) | Game development integration described by game-dev.cl for Unity. | game-dev |
| [desktop-native.2](modules/desktop-native.2/README.md) | Provides desktop-native / 2 in Neyvia. | neyvia |
| [desktop-native.Cargo](modules/desktop-native.Cargo/README.md) | Provides desktop-native / Cargo in Neyvia. | neyvia |
| [desktop-native.browser-proof.conf](modules/desktop-native.browser-proof.conf/README.md) | Provides desktop-native / browser-proof / conf in Neyvia. | neyvia |
| [desktop-native.build](modules/desktop-native.build/README.md) | Provides desktop-native / build in Neyvia. | neyvia |
| [desktop-native.build_frontend_guard](modules/desktop-native.build_frontend_guard/README.md) | Provides desktop-native / build_frontend_guard in Neyvia. | neyvia |
| [desktop-native.capabilities.default](modules/desktop-native.capabilities.default/README.md) | Provides desktop-native / capabilities / default in Neyvia. | neyvia |
| [desktop-native.capabilities.desktop](modules/desktop-native.capabilities.desktop/README.md) | Provides desktop-native / capabilities / desktop in Neyvia. | neyvia |
| [desktop-native.examples.verify_updater_signature](modules/desktop-native.examples.verify_updater_signature/README.md) | Provides desktop-native / examples / verify_updater_signature in Neyvia. | neyvia |
| [desktop-native.icons.android.mipmap-anydpi-v26.ic_launcher](modules/desktop-native.icons.android.mipmap-anydpi-v26.ic_launcher/README.md) | Provides desktop-native / icons / android / mipmap-anydpi-v26 / ic_launcher in Neyvia. | neyvia |
| [desktop-native.icons.android.values.ic_launcher_background](modules/desktop-native.icons.android.values.ic_launcher_background/README.md) | Provides desktop-native / icons / android / values / ic_launcher_background in Neyvia. | neyvia |
| [desktop-native.installer-budget](modules/desktop-native.installer-budget/README.md) | Provides desktop-native / installer-budget in Neyvia. | neyvia |
| [desktop-native.proof-ui.index](modules/desktop-native.proof-ui.index/README.md) | Provides desktop-native / proof-ui / index in Neyvia. | neyvia |
| [desktop-native.src.base_pack](modules/desktop-native.src.base_pack/README.md) | Provides desktop-native / src / base_pack in Neyvia. | neyvia |
| [desktop-native.src.base_pack_bridge](modules/desktop-native.src.base_pack_bridge/README.md) | Provides desktop-native / src / base_pack_bridge in Neyvia. | neyvia |
| [desktop-native.src.browser_projection](modules/desktop-native.src.browser_projection/README.md) | Provides desktop-native / src / browser_projection in Neyvia. | neyvia |
| [desktop-native.src.browser_runtime](modules/desktop-native.src.browser_runtime/README.md) | Provides desktop-native / src / browser_runtime in Neyvia. | neyvia |
| [desktop-native.src.lib](modules/desktop-native.src.lib/README.md) | Provides desktop-native / src / lib in Neyvia. | neyvia |
| [desktop-native.src.main](modules/desktop-native.src.main/README.md) | Provides desktop-native / src / main in Neyvia. | neyvia |
| [desktop-native.src.runtime_env](modules/desktop-native.src.runtime_env/README.md) | Provides desktop-native / src / runtime_env in Neyvia. | neyvia |
| [desktop-native.tauri.ci-unsigned.conf](modules/desktop-native.tauri.ci-unsigned.conf/README.md) | Provides desktop-native / tauri / ci-unsigned / conf in Neyvia. | neyvia |
| [desktop-native.tauri.conf](modules/desktop-native.tauri.conf/README.md) | Provides desktop-native / tauri / conf in Neyvia. | neyvia |
| [desktop-native.tauri.slim.conf](modules/desktop-native.tauri.slim.conf/README.md) | Provides desktop-native / tauri / slim / conf in Neyvia. | neyvia |
| [effectcraft](modules/effectcraft/README.md) | Agent-usable EffectCraft (ArtCraft/storytold, an After Effects-style compositor in Rust) through its headless CLI: commands, comps and layers as a CL Scene, scripted edits, frames and renders. | effectcraft |
| [filmcraft](modules/filmcraft/README.md) | Agent-usable FilmCraft (ArtCraft/storytold, MIT or Apache-2.0; a Premiere-style editor in Rust) through its headless CLI: commands, the sequence as a CL Scene, scripted edits, export and frames. | filmcraft |
| [gamedev.blender.laya3d_background](modules/gamedev.blender.laya3d_background/README.md) | Private Blender bridge host and native labelled contract fixtures. | neyvia |
| [gamedev.blender.neyvia_bridge.__init__](modules/gamedev.blender.neyvia_bridge.__init__/README.md) | Blender-native scene bridge; networking never calls bpy from its worker. | neyvia |
| [gamedev.blender.neyvia_bridge.hull_math](modules/gamedev.blender.neyvia_bridge.hull_math/README.md) | One weak-perspective camera and silhouette-carving definition (numpy only, no bpy). | neyvia |
| [gamedev.blender.neyvia_bridge.mesh_quality](modules/gamedev.blender.neyvia_bridge.mesh_quality/README.md) | Blender observations and named operations for the shared Plan 23 Scene core. | neyvia |
| [gamedev.blender.neyvia_bridge.shape_program](modules/gamedev.blender.neyvia_bridge.shape_program/README.md) | Execute the bounded CL shape vocabulary, without Python eval or external generators. | neyvia |
| [gamedev.blender.neyvia_bridge.view_geometry](modules/gamedev.blender.neyvia_bridge.view_geometry/README.md) | One camera definition for native rendering and silhouette-cone construction. | neyvia |
| [gamedev.blender.neyvia_bridge.visual_hull](modules/gamedev.blender.neyvia_bridge.visual_hull/README.md) | Bounded local inverse graphics: carve a voxel grid with fitted-camera silhouettes. | neyvia |
| [gamedev.browser](modules/gamedev.browser/README.md) | Provides gamedev / browser in Neyvia. | game-dev |
| [gamedev.build-manual](modules/gamedev.build-manual/README.md) | Regenerate only T12's authored executable manual from registered schemas. | neyvia |
| [gamedev.call](modules/gamedev.call/README.md) | Provides gamedev / call in Neyvia. | game-dev |
| [gamedev.godot.addons.neyvia_bridge.client](modules/gamedev.godot.addons.neyvia_bridge.client/README.md) | Provides gamedev / godot / addons / neyvia_bridge / client in Neyvia. | game-dev |
| [gamedev.godot.addons.neyvia_bridge.plugin](modules/gamedev.godot.addons.neyvia_bridge.plugin/README.md) | Provides gamedev / godot / addons / neyvia_bridge / plugin in Neyvia. | game-dev |
| [gamedev.godot.addons.neyvia_bridge.runtime](modules/gamedev.godot.addons.neyvia_bridge.runtime/README.md) | Provides gamedev / godot / addons / neyvia_bridge / runtime in Neyvia. | game-dev |
| [gamedev.godot.addons.neyvia_bridge.scene_observer](modules/gamedev.godot.addons.neyvia_bridge.scene_observer/README.md) | Provides gamedev / godot / addons / neyvia_bridge / scene_observer in Neyvia. | game-dev |
| [gamedev.native-scene](modules/gamedev.native-scene/README.md) | Provides gamedev / native-scene in Neyvia. | game-dev |
| [gamedev.package](modules/gamedev.package/README.md) | Provides gamedev / package in Neyvia. | neyvia |
| [gamedev.roblox.NeyviaGameDevBridge.plugin](modules/gamedev.roblox.NeyviaGameDevBridge.plugin/README.md) | Provides gamedev / roblox / NeyviaGameDevBridge / plugin in Neyvia. | neyvia |
| [gamedev.scene-runtime](modules/gamedev.scene-runtime/README.md) | Provides gamedev / scene-runtime in Neyvia. | game-dev |
| [gamedev.unity.Editor.Neyvia.GameDev.Editor](modules/gamedev.unity.Editor.Neyvia.GameDev.Editor/README.md) | Provides gamedev / unity / Editor / Neyvia / GameDev / Editor in Neyvia. | neyvia |
| [gamedev.unity.Editor.NeyviaGameDevBridge](modules/gamedev.unity.Editor.NeyviaGameDevBridge/README.md) | Provides gamedev / unity / Editor / NeyviaGameDevBridge in Neyvia. | game-dev |
| [gamedev.unity.Editor.NeyviaSceneObserver](modules/gamedev.unity.Editor.NeyviaSceneObserver/README.md) | Provides gamedev / unity / Editor / NeyviaSceneObserver in Neyvia. | game-dev |
| [gamedev.unity.package](modules/gamedev.unity.package/README.md) | Provides gamedev / unity / package in Neyvia. | neyvia |
| [gamedev.validate-asset](modules/gamedev.validate-asset/README.md) | Provides gamedev / validate-asset in Neyvia. | game-dev |
| [hello-module](modules/hello-module/README.md) | Build a personal greeting through a small agent-callable optional mod. | hello-module |
| [hyperframes](modules/hyperframes/README.md) | Agent-usable HyperFrames (HeyGen, Apache-2.0): lint, observe the timeline, render headless to MP4 with outcome contracts, snapshot frames and run the Studio privately. | hyperframes |
| [laya-video](modules/laya-video/README.md) | LAYA edits video by itself: a CL brief becomes a first draft from real captures, the shared Scene core judges the rendered file and keeps only fixes that remove findings; A/B votes become personal taste episodes. | laya-video |
| [manual.C7e-artifact-manual](modules/manual.C7e-artifact-manual/README.md) | Executable Connected Language manual for C7e-artifact-manual. | C7e-artifact-manual |
| [manual.C7e-c7d-adapters](modules/manual.C7e-c7d-adapters/README.md) | Executable Connected Language manual for C7e-c7d-adapters. | C7e-c7d-adapters |
| [manual.C7e-c7d-control](modules/manual.C7e-c7d-control/README.md) | Executable Connected Language manual for C7e-c7d-control. | C7e-c7d-control |
| [manual.C7e-c7d-control-completion](modules/manual.C7e-c7d-control-completion/README.md) | Executable Connected Language manual for C7e-c7d-control-completion. | C7e-c7d-control-completion |
| [manual.C7e-c7d-desktop](modules/manual.C7e-c7d-desktop/README.md) | Executable Connected Language manual for C7e-c7d-desktop. | C7e-c7d-desktop |
| [manual.C7e-c7d-engine](modules/manual.C7e-c7d-engine/README.md) | Executable Connected Language manual for C7e-c7d-engine. | C7e-c7d-engine |
| [manual.C7e-c7d-native-commands](modules/manual.C7e-c7d-native-commands/README.md) | Executable Connected Language manual for C7e-c7d-native-commands. | C7e-c7d-native-commands |
| [manual.C7e-c7d-projection](modules/manual.C7e-c7d-projection/README.md) | Executable Connected Language manual for C7e-c7d-projection. | C7e-c7d-projection |
| [manual.C7e-c7d-provider-marks](modules/manual.C7e-c7d-provider-marks/README.md) | Executable Connected Language manual for C7e-c7d-provider-marks. | C7e-c7d-provider-marks |
| [manual.C7e-c7d-providers](modules/manual.C7e-c7d-providers/README.md) | Executable Connected Language manual for C7e-c7d-providers. | C7e-c7d-providers |
| [manual.C7e-c7d-rendered](modules/manual.C7e-c7d-rendered/README.md) | Executable Connected Language manual for C7e-c7d-rendered. | C7e-c7d-rendered |
| [manual.C7e-c7d-ui](modules/manual.C7e-c7d-ui/README.md) | Executable Connected Language manual for C7e-c7d-ui. | C7e-c7d-ui |
| [manual.C7e-c7d-ui-control](modules/manual.C7e-c7d-ui-control/README.md) | Executable Connected Language manual for C7e-c7d-ui-control. | C7e-c7d-ui-control |
| [manual.C7e-c7d-ui-settings](modules/manual.C7e-c7d-ui-settings/README.md) | Executable Connected Language manual for C7e-c7d-ui-settings. | C7e-c7d-ui-settings |
| [manual.C7e-c7d-verification](modules/manual.C7e-c7d-verification/README.md) | Executable Connected Language manual for C7e-c7d-verification. | C7e-c7d-verification |
| [manual.C7e-c7d-wz](modules/manual.C7e-c7d-wz/README.md) | Executable Connected Language manual for C7e-c7d-wz. | C7e-c7d-wz |
| [manual.C7e-capabilities](modules/manual.C7e-capabilities/README.md) | Executable Connected Language manual for C7e-capabilities. | C7e-capabilities |
| [manual.C7e-capability-completion](modules/manual.C7e-capability-completion/README.md) | Executable Connected Language manual for C7e-capability-completion. | C7e-capability-completion |
| [manual.C7e-capability-models](modules/manual.C7e-capability-models/README.md) | Executable Connected Language manual for C7e-capability-models. | C7e-capability-models |
| [manual.C7e-chat-shell](modules/manual.C7e-chat-shell/README.md) | Executable Connected Language manual for C7e-chat-shell. | C7e-chat-shell |
| [manual.C7e-control](modules/manual.C7e-control/README.md) | Executable Connected Language manual for C7e-control. | C7e-control |
| [manual.C7e-control-remaining](modules/manual.C7e-control-remaining/README.md) | Executable Connected Language manual for C7e-control-remaining. | C7e-control-remaining |
| [manual.C7e-core](modules/manual.C7e-core/README.md) | Executable Connected Language manual for C7e-core. | C7e-core |
| [manual.C7e-engine](modules/manual.C7e-engine/README.md) | Executable Connected Language manual for C7e-engine. | C7e-engine |
| [manual.C7e-frontend](modules/manual.C7e-frontend/README.md) | Executable Connected Language manual for C7e-frontend. | C7e-frontend |
| [manual.C7e-host-actions-completion](modules/manual.C7e-host-actions-completion/README.md) | Executable Connected Language manual for C7e-host-actions-completion. | C7e-host-actions-completion |
| [manual.C7e-host-runtime](modules/manual.C7e-host-runtime/README.md) | Executable Connected Language manual for C7e-host-runtime. | C7e-host-runtime |
| [manual.C7e-local](modules/manual.C7e-local/README.md) | Executable Connected Language manual for C7e-local. | C7e-local |
| [manual.C7e-local-completion](modules/manual.C7e-local-completion/README.md) | Executable Connected Language manual for C7e-local-completion. | C7e-local-completion |
| [manual.C7e-mission-completion](modules/manual.C7e-mission-completion/README.md) | Executable Connected Language manual for C7e-mission-completion. | C7e-mission-completion |
| [manual.C7e-missions](modules/manual.C7e-missions/README.md) | Executable Connected Language manual for C7e-missions. | C7e-missions |
| [manual.C7e-mobile](modules/manual.C7e-mobile/README.md) | Executable Connected Language manual for C7e-mobile. | C7e-mobile |
| [manual.C7e-models](modules/manual.C7e-models/README.md) | Executable Connected Language manual for C7e-models. | C7e-models |
| [manual.C7e-native](modules/manual.C7e-native/README.md) | Executable Connected Language manual for C7e-native. | C7e-native |
| [manual.C7e-native-completion](modules/manual.C7e-native-completion/README.md) | Executable Connected Language manual for C7e-native-completion. | C7e-native-completion |
| [manual.C7e-preferences-skills](modules/manual.C7e-preferences-skills/README.md) | Executable Connected Language manual for C7e-preferences-skills. | C7e-preferences-skills |
| [manual.C7e-providers](modules/manual.C7e-providers/README.md) | Executable Connected Language manual for C7e-providers. | C7e-providers |
| [manual.C7e-pure](modules/manual.C7e-pure/README.md) | Executable Connected Language manual for C7e-pure. | C7e-pure |
| [manual.C7e-scheduler](modules/manual.C7e-scheduler/README.md) | Executable Connected Language manual for C7e-scheduler. | C7e-scheduler |
| [manual.C7e-session-completion](modules/manual.C7e-session-completion/README.md) | Executable Connected Language manual for C7e-session-completion. | C7e-session-completion |
| [manual.C7e-sessions](modules/manual.C7e-sessions/README.md) | Executable Connected Language manual for C7e-sessions. | C7e-sessions |
| [manual.C7e-surfaces](modules/manual.C7e-surfaces/README.md) | Executable Connected Language manual for C7e-surfaces. | C7e-surfaces |
| [manual.C7e-ui-planning-local](modules/manual.C7e-ui-planning-local/README.md) | Executable Connected Language manual for C7e-ui-planning-local. | C7e-ui-planning-local |
| [manual.C7e-ui-remaining](modules/manual.C7e-ui-remaining/README.md) | Executable Connected Language manual for C7e-ui-remaining. | C7e-ui-remaining |
| [manual.adaptive-work](modules/manual.adaptive-work/README.md) | Executable Connected Language manual for adaptive-work. | adaptive-work |
| [manual.agent-view](modules/manual.agent-view/README.md) | Executable Connected Language manual for agent-view. | agent-view |
| [manual.agents](modules/manual.agents/README.md) | Executable Connected Language manual for agents. | agents |
| [manual.app-sdk](modules/manual.app-sdk/README.md) | Executable Connected Language manual for app-sdk. | app-sdk |
| [manual.assigned-ports](modules/manual.assigned-ports/README.md) | Executable Connected Language manual for assigned-ports. | assigned-ports |
| [manual.autopilot](modules/manual.autopilot/README.md) | Executable Connected Language manual for autopilot. | autopilot |
| [manual.awareness](modules/manual.awareness/README.md) | Executable Connected Language manual for awareness. | awareness |
| [manual.browser](modules/manual.browser/README.md) | Executable Connected Language manual for browser. | browser |
| [manual.claude-mod-awareness](modules/manual.claude-mod-awareness/README.md) | Executable Connected Language manual for claude-mod-awareness. | claude-mod-awareness |
| [manual.comments](modules/manual.comments/README.md) | Executable Connected Language manual for comments. | comments |
| [manual.computer-use](modules/manual.computer-use/README.md) | Executable Connected Language manual for computer-use. | computer-use |
| [manual.conductor](modules/manual.conductor/README.md) | Executable Connected Language manual for conductor. | conductor |
| [manual.connections](modules/manual.connections/README.md) | Executable Connected Language manual for connections. | connections |
| [manual.coverage-ratchet](modules/manual.coverage-ratchet/README.md) | Executable Connected Language manual for coverage-ratchet. | coverage-ratchet |
| [manual.creative-records](modules/manual.creative-records/README.md) | Executable Connected Language manual for creative-records. | creative-records |
| [manual.creativity](modules/manual.creativity/README.md) | Executable Connected Language manual for creativity. | creativity |
| [manual.critique-review](modules/manual.critique-review/README.md) | Executable Connected Language manual for critique-review. | critique-review |
| [manual.cross-pc](modules/manual.cross-pc/README.md) | Executable Connected Language manual for cross-pc. | cross-pc |
| [manual.design](modules/manual.design/README.md) | Executable Connected Language manual for design. | design |
| [manual.dictation](modules/manual.dictation/README.md) | Executable Connected Language manual for dictation. | dictation |
| [manual.documents](modules/manual.documents/README.md) | Executable Connected Language manual for documents. | documents |
| [manual.edge-contracts](modules/manual.edge-contracts/README.md) | Executable Connected Language manual for edge-contracts. | edge-contracts |
| [manual.effectcraft](modules/manual.effectcraft/README.md) | Executable Connected Language manual for effectcraft. | effectcraft |
| [manual.efficiency](modules/manual.efficiency/README.md) | Executable Connected Language manual for efficiency. | efficiency |
| [manual.evolve](modules/manual.evolve/README.md) | Executable Connected Language manual for evolve. | evolve |
| [manual.evolve-moves](modules/manual.evolve-moves/README.md) | Executable Connected Language manual for evolve-moves. | evolve-moves |
| [manual.files](modules/manual.files/README.md) | Executable Connected Language manual for files. | files |
| [manual.filmcraft](modules/manual.filmcraft/README.md) | Executable Connected Language manual for filmcraft. | filmcraft |
| [manual.game-dev](modules/manual.game-dev/README.md) | Executable Connected Language manual for game-dev. | game-dev |
| [manual.handoff-recovery](modules/manual.handoff-recovery/README.md) | Executable Connected Language manual for handoff-recovery. | handoff-recovery |
| [manual.hello-module](modules/manual.hello-module/README.md) | Executable Connected Language manual for hello-module. | hello-module |
| [manual.hill-climb](modules/manual.hill-climb/README.md) | Executable Connected Language manual for hill-climb. | hill-climb |
| [manual.host-runtime](modules/manual.host-runtime/README.md) | Executable Connected Language manual for host-runtime. | host-runtime |
| [manual.hyperframes](modules/manual.hyperframes/README.md) | Executable Connected Language manual for hyperframes. | hyperframes |
| [manual.image-studio](modules/manual.image-studio/README.md) | Executable Connected Language manual for image-studio. | image-studio |
| [manual.inception](modules/manual.inception/README.md) | Executable Connected Language manual for inception. | inception |
| [manual.language](modules/manual.language/README.md) | Executable Connected Language manual for language. | language |
| [manual.laya-3d](modules/manual.laya-3d/README.md) | Executable Connected Language manual for laya-3d. | laya-3d |
| [manual.laya-3d-image](modules/manual.laya-3d-image/README.md) | Executable Connected Language manual for laya-3d-image. | laya-3d-image |
| [manual.laya-glance](modules/manual.laya-glance/README.md) | Executable Connected Language manual for laya-glance. | laya-glance |
| [manual.laya-ui-fix](modules/manual.laya-ui-fix/README.md) | Executable Connected Language manual for laya-ui-fix. | laya-ui-fix |
| [manual.laya-video](modules/manual.laya-video/README.md) | Executable Connected Language manual for laya-video. | laya-video |
| [manual.laya-vision](modules/manual.laya-vision/README.md) | Executable Connected Language manual for laya-vision. | laya-vision |
| [manual.local-app-open](modules/manual.local-app-open/README.md) | Executable Connected Language manual for local-app-open. | local-app-open |
| [manual.local-browser-sdk](modules/manual.local-browser-sdk/README.md) | Executable Connected Language manual for local-browser-sdk. | local-browser-sdk |
| [manual.local-environment](modules/manual.local-environment/README.md) | Executable Connected Language manual for local-environment. | local-environment |
| [manual.local-evaluations](modules/manual.local-evaluations/README.md) | Executable Connected Language manual for local-evaluations. | local-evaluations |
| [manual.local-evolver](modules/manual.local-evolver/README.md) | Executable Connected Language manual for local-evolver. | local-evolver |
| [manual.local-host](modules/manual.local-host/README.md) | Executable Connected Language manual for local-host. | local-host |
| [manual.local-integrity](modules/manual.local-integrity/README.md) | Executable Connected Language manual for local-integrity. | local-integrity |
| [manual.local-mechanisms](modules/manual.local-mechanisms/README.md) | Executable Connected Language manual for local-mechanisms. | local-mechanisms |
| [manual.local-media](modules/manual.local-media/README.md) | Executable Connected Language manual for local-media. | local-media |
| [manual.local-records](modules/manual.local-records/README.md) | Executable Connected Language manual for local-records. | local-records |
| [manual.local-rendering](modules/manual.local-rendering/README.md) | Executable Connected Language manual for local-rendering. | local-rendering |
| [manual.manuals-next](modules/manual.manuals-next/README.md) | Executable Connected Language manual for manuals-next. | manuals-next |
| [manual.memory](modules/manual.memory/README.md) | Executable Connected Language manual for memory. | memory |
| [manual.mission-plan](modules/manual.mission-plan/README.md) | Executable Connected Language manual for mission-plan. | mission-plan |
| [manual.mobile-studio](modules/manual.mobile-studio/README.md) | Executable Connected Language manual for mobile-studio. | mobile-studio |
| [manual.modules](modules/manual.modules/README.md) | Executable Connected Language manual for modules. | modules |
| [manual.native-applications](modules/manual.native-applications/README.md) | Executable Connected Language manual for native-applications. | native-applications |
| [manual.native-runtime](modules/manual.native-runtime/README.md) | Executable Connected Language manual for native-runtime. | native-runtime |
| [manual.nearby-send-runtime](modules/manual.nearby-send-runtime/README.md) | Executable Connected Language manual for nearby-send-runtime. | nearby-send-runtime |
| [manual.neyvia](modules/manual.neyvia/README.md) | Executable Connected Language manual for neyvia. | neyvia |
| [manual.neyvia-core](modules/manual.neyvia-core/README.md) | Executable Connected Language manual for neyvia-core. | neyvia-core |
| [manual.neyvia-reference](modules/manual.neyvia-reference/README.md) | Executable Connected Language manual for neyvia-reference. | neyvia-reference |
| [manual.nightshift](modules/manual.nightshift/README.md) | Executable Connected Language manual for nightshift. | nightshift |
| [manual.notes](modules/manual.notes/README.md) | Executable Connected Language manual for notes. | notes |
| [manual.onboarding](modules/manual.onboarding/README.md) | Executable Connected Language manual for onboarding. | onboarding |
| [manual.outputs](modules/manual.outputs/README.md) | Executable Connected Language manual for outputs. | outputs |
| [manual.parallel](modules/manual.parallel/README.md) | Executable Connected Language manual for parallel. | parallel |
| [manual.pdf](modules/manual.pdf/README.md) | Executable Connected Language manual for pdf. | pdf |
| [manual.perception](modules/manual.perception/README.md) | Executable Connected Language manual for perception. | perception |
| [manual.photocraft](modules/manual.photocraft/README.md) | Executable Connected Language manual for photocraft. | photocraft |
| [manual.proofs](modules/manual.proofs/README.md) | Executable Connected Language manual for proofs. | proofs |
| [manual.proofs-b-adapters](modules/manual.proofs-b-adapters/README.md) | Executable Connected Language manual for proofs-b-adapters. | proofs-b-adapters |
| [manual.proofs-b-browser](modules/manual.proofs-b-browser/README.md) | Executable Connected Language manual for proofs-b-browser. | proofs-b-browser |
| [manual.proofs-b-desktop](modules/manual.proofs-b-desktop/README.md) | Executable Connected Language manual for proofs-b-desktop. | proofs-b-desktop |
| [manual.proofs-b-engine](modules/manual.proofs-b-engine/README.md) | Executable Connected Language manual for proofs-b-engine. | proofs-b-engine |
| [manual.proofs-b-harness](modules/manual.proofs-b-harness/README.md) | Executable Connected Language manual for proofs-b-harness. | proofs-b-harness |
| [manual.rel-release-harness](modules/manual.rel-release-harness/README.md) | Executable Connected Language manual for rel-release-harness. | rel-release-harness |
| [manual.remote](modules/manual.remote/README.md) | Executable Connected Language manual for remote. | remote |
| [manual.research](modules/manual.research/README.md) | Executable Connected Language manual for research. | research |
| [manual.research-assistant](modules/manual.research-assistant/README.md) | Executable Connected Language manual for research-assistant. | research-assistant |
| [manual.runtime-provider](modules/manual.runtime-provider/README.md) | Executable Connected Language manual for runtime-provider. | runtime-provider |
| [manual.scroll-generator](modules/manual.scroll-generator/README.md) | Executable Connected Language manual for scroll-generator. | scroll-generator |
| [manual.settings](modules/manual.settings/README.md) | Executable Connected Language manual for settings. | settings |
| [manual.sidebar](modules/manual.sidebar/README.md) | Executable Connected Language manual for sidebar. | sidebar |
| [manual.slim-installer](modules/manual.slim-installer/README.md) | Executable Connected Language manual for slim-installer. | slim-installer |
| [manual.taste](modules/manual.taste/README.md) | Executable Connected Language manual for taste. | taste |
| [manual.taste-harness](modules/manual.taste-harness/README.md) | Executable Connected Language manual for taste-harness. | taste-harness |
| [manual.tools-depth](modules/manual.tools-depth/README.md) | Executable Connected Language manual for tools-depth. | tools-depth |
| [manual.transparency](modules/manual.transparency/README.md) | Executable Connected Language manual for transparency. | transparency |
| [manual.ui-planning](modules/manual.ui-planning/README.md) | Executable Connected Language manual for ui-planning. | ui-planning |
| [manual.usage](modules/manual.usage/README.md) | Executable Connected Language manual for usage. | usage |
| [manual.video](modules/manual.video/README.md) | Executable Connected Language manual for video. | video |
| [manual.voice](modules/manual.voice/README.md) | Executable Connected Language manual for voice. | voice |
| [manual.workspace](modules/manual.workspace/README.md) | Executable Connected Language manual for workspace. | workspace |
| [photocraft](modules/photocraft/README.md) | Agent-usable PhotoCraft (ArtCraft/storytold, a Photoshop-style editor in Rust) for video frames: inspect, run engine commands, convert. | photocraft |
| [plugin..claude-plugin.plugin](modules/plugin..claude-plugin.plugin/README.md) | Provides plugin /  / claude-plugin / plugin in Neyvia. | neyvia |
| [plugin..claude-plugin.types.claude-code.index.d](modules/plugin..claude-plugin.types.claude-code.index.d/README.md) | Provides plugin /  / claude-plugin / types / claude-code / index / d in Neyvia. | neyvia |
| [plugin..claude-plugin.types.tsconfig](modules/plugin..claude-plugin.types.tsconfig/README.md) | Provides plugin /  / claude-plugin / types / tsconfig in Neyvia. | neyvia |
| [plugin..mcp](modules/plugin..mcp/README.md) | Provides plugin /  / mcp in Neyvia. | neyvia |
| [plugin.hooks.client](modules/plugin.hooks.client/README.md) | Provides plugin / hooks / client in Neyvia. | neyvia |
| [plugin.hooks.context](modules/plugin.hooks.context/README.md) | Provides plugin / hooks / context in Neyvia. | neyvia |
| [plugin.hooks.gate](modules/plugin.hooks.gate/README.md) | Provides plugin / hooks / gate in Neyvia. | neyvia |
| [plugin.hooks.hooks](modules/plugin.hooks.hooks/README.md) | Provides plugin / hooks / hooks in Neyvia. | neyvia |
| [plugin.hooks.inbox](modules/plugin.hooks.inbox/README.md) | Provides plugin / hooks / inbox in Neyvia. | neyvia |
| [plugin.hooks.register](modules/plugin.hooks.register/README.md) | Provides plugin / hooks / register in Neyvia. | neyvia |
| [plugin.hooks.report](modules/plugin.hooks.report/README.md) | Provides plugin / hooks / report in Neyvia. | neyvia |
| [plugin.hooks.roles](modules/plugin.hooks.roles/README.md) | Provides plugin / hooks / roles in Neyvia. | neyvia |
| [plugin.hooks.rules](modules/plugin.hooks.rules/README.md) | Provides plugin / hooks / rules in Neyvia. | neyvia |
| [plugin.hooks.session](modules/plugin.hooks.session/README.md) | Provides plugin / hooks / session in Neyvia. | neyvia |
| [plugin.hooks.tools](modules/plugin.hooks.tools/README.md) | Provides plugin / hooks / tools in Neyvia. | neyvia |
| [plugin.mcp.neyvia_mcp](modules/plugin.mcp.neyvia_mcp/README.md) | Neyvia's tools for Claude Code: a stdio MCP server that calls the local Neyvia service. Standard library only. | neyvia |
| [plugin.tsconfig](modules/plugin.tsconfig/README.md) | Provides plugin / tsconfig in Neyvia. | neyvia |
| [rust.evolver-core.Cargo](modules/rust.evolver-core.Cargo/README.md) | Provides rust / evolver-core / Cargo in Neyvia. | neyvia |
| [rust.evolver-core.src.main](modules/rust.evolver-core.src.main/README.md) | Provides rust / evolver-core / src / main in Neyvia. | neyvia |
| [script._final_native_merge_once](modules/script._final_native_merge_once/README.md) | Provides script / _final_native_merge_once in Neyvia. | neyvia |
| [script.advance_route_trust_sampling_loop](modules/script.advance_route_trust_sampling_loop/README.md) | Advance the route-trust sampling loop without duplicate launches. | neyvia |
| [script.advance_self_improvement_red_team_loop](modules/script.advance_self_improvement_red_team_loop/README.md) | Provides script / advance_self_improvement_red_team_loop in Neyvia. | neyvia |
| [script.agentview.InvoiceProbe](modules/script.agentview.InvoiceProbe/README.md) | Provides script / agentview / InvoiceProbe in Neyvia. | neyvia |
| [script.agentview.shop](modules/script.agentview.shop/README.md) | Provides script / agentview / shop in Neyvia. | neyvia |
| [script.agentview.start_backend](modules/script.agentview.start_backend/README.md) | Provides script / agentview / start_backend in Neyvia. | neyvia |
| [script.app_sdk](modules/script.app_sdk/README.md) | neyvia app new/describe/state/action/build/verify/serve, explicit ports only. | neyvia |
| [script.appdesign_final](modules/script.appdesign_final/README.md) | Before/after pairs for the app design pass: docs/evidence/appdesign/final/NN-<app>-<theme>.png | neyvia |
| [script.appdesign_sheet](modules/script.appdesign_sheet/README.md) | Contact sheet for scripts/appdesign_shots.py: one row per app, one column per theme, each cell the | neyvia |
| [script.appdesign_shots](modules/script.appdesign_shots/README.md) | App design pass: every app in every theme, rendered in Neyvia's Obscura engine (layout only). | neyvia |
| [script.apple.preview](modules/script.apple.preview/README.md) | Owned headless rendered journey. Temporary auth in memory; no credential reads. | neyvia |
| [script.apple.simulator](modules/script.apple.simulator/README.md) | Provides script / apple / simulator in Neyvia. | neyvia |
| [script.apple.simulator-workflow](modules/script.apple.simulator-workflow/README.md) | Provides script / apple / simulator-workflow in Neyvia. | neyvia |
| [script.apple_harness](modules/script.apple_harness/README.md) | Manual-first Apple commands through the worktree's production Neyvia harness. | neyvia |
| [script.apply_neyvia_native_breakthrough](modules/script.apply_neyvia_native_breakthrough/README.md) | Provides script / apply_neyvia_native_breakthrough in Neyvia. | neyvia |
| [script.apply_neyvia_native_breakthrough_v2](modules/script.apply_neyvia_native_breakthrough_v2/README.md) | Provides script / apply_neyvia_native_breakthrough_v2 in Neyvia. | neyvia |
| [script.apply_neyvia_native_evolution](modules/script.apply_neyvia_native_evolution/README.md) | Provides script / apply_neyvia_native_evolution in Neyvia. | neyvia |
| [script.apply_neyvia_native_runtime_hooks](modules/script.apply_neyvia_native_runtime_hooks/README.md) | Provides script / apply_neyvia_native_runtime_hooks in Neyvia. | neyvia |
| [script.apply_neyvia_native_runtime_hooks_v2](modules/script.apply_neyvia_native_runtime_hooks_v2/README.md) | Provides script / apply_neyvia_native_runtime_hooks_v2 in Neyvia. | neyvia |
| [script.apply_spawned_agent_ui](modules/script.apply_spawned_agent_ui/README.md) | Provides script / apply_spawned_agent_ui in Neyvia. | neyvia |
| [script.archive_c10_development](modules/script.archive_c10_development/README.md) | Preserve referenced public C10 attempts and account for observed model calls. | neyvia |
| [script.archive_release_proofs](modules/script.archive_release_proofs/README.md) | Provides script / archive_release_proofs in Neyvia. | neyvia |
| [script.assemble_C7e_deadline](modules/script.assemble_C7e_deadline/README.md) | Select latest intact source-current family receipts for an honest deadline seal. | neyvia |
| [script.assemble_C7e_local](modules/script.assemble_C7e_local/README.md) | Reconcile completed local C7 contract families after an interrupted worker. | neyvia |
| [script.assemble_C7e_parallel](modules/script.assemble_C7e_parallel/README.md) | Assemble unchanged-source local C7 family observations into one campaign. | neyvia |
| [script.assigned_ports_proof](modules/script.assigned_ports_proof/README.md) | Evidence: explicitly assigned port blocks and scratch roots (grant_agent.assigned_ports). | neyvia |
| [script.benchmark-manual-recovery](modules/script.benchmark-manual-recovery/README.md) | Provides script / benchmark-manual-recovery in Neyvia. | neyvia |
| [script.benchmark_glm_ocr_ollama](modules/script.benchmark_glm_ocr_ollama/README.md) | Benchmark an immutable GLM-OCR Ollama model through a loopback server. | neyvia |
| [script.benchmark_glm_ocr_transformers](modules/script.benchmark_glm_ocr_transformers/README.md) | Run a hash-verified GLM-OCR Transformers benchmark on one image. | neyvia |
| [script.benchmark_neyvia_ocr](modules/script.benchmark_neyvia_ocr/README.md) | Score saved OCR outputs against a small, explicit ground-truth manifest. | neyvia |
| [script.brand.neyvia_sun_mark](modules/script.brand.neyvia_sun_mark/README.md) | Neyvia sun mark: a broad tree against a banded southern sunset. | neyvia |
| [script.brand.rasterize_neyvia_icons](modules/script.brand.rasterize_neyvia_icons/README.md) | Provides script / brand / rasterize_neyvia_icons in Neyvia. | neyvia |
| [script.browser-probe.Cargo](modules/script.browser-probe.Cargo/README.md) | Provides script / browser-probe / Cargo in Neyvia. | neyvia |
| [script.browser-probe.build](modules/script.browser-probe.build/README.md) | Provides script / browser-probe / build in Neyvia. | neyvia |
| [script.browser-probe.capabilities.default](modules/script.browser-probe.capabilities.default/README.md) | Provides script / browser-probe / capabilities / default in Neyvia. | neyvia |
| [script.browser-probe.src.main](modules/script.browser-probe.src.main/README.md) | Provides script / browser-probe / src / main in Neyvia. | neyvia |
| [script.browser-probe.tauri.conf](modules/script.browser-probe.tauri.conf/README.md) | Provides script / browser-probe / tauri / conf in Neyvia. | neyvia |
| [script.browser_completion](modules/script.browser_completion/README.md) | Provides script / browser_completion in Neyvia. | neyvia |
| [script.browser_goal_checks](modules/script.browser_goal_checks/README.md) | Provides script / browser_goal_checks in Neyvia. | neyvia |
| [script.browser_luna](modules/script.browser_luna/README.md) | Provides script / browser_luna in Neyvia. | neyvia |
| [script.browser_source_goals](modules/script.browser_source_goals/README.md) | Provides script / browser_source_goals in Neyvia. | neyvia |
| [script.browser_task_cascade](modules/script.browser_task_cascade/README.md) | Provides script / browser_task_cascade in Neyvia. | neyvia |
| [script.build_C7_manual](modules/script.build_C7_manual/README.md) | Author the edge-campaign manual through the existing CL compiler. | neyvia |
| [script.build_C7d_browser](modules/script.build_C7d_browser/README.md) | Offline source-bound native probe build; never starts the application. | neyvia |
| [script.build_C7e_case_inventory](modules/script.build_C7e_case_inventory/README.md) | Build the C7e case denominator from source-bound receipts and declarations. | neyvia |
| [script.build_T20_browser_manual](modules/script.build_T20_browser_manual/README.md) | Ground the browser backend chapter in live tools; preserve authored UI chapters. | neyvia |
| [script.build_app_sdk_runtime](modules/script.build_app_sdk_runtime/README.md) | Provides script / build_app_sdk_runtime in Neyvia. | neyvia |
| [script.build_c10_manual](modules/script.build_c10_manual/README.md) | Generate and validate only the research-assistant executable manual. | neyvia |
| [script.build_c11_parked](modules/script.build_c11_parked/README.md) | Provides script / build_c11_parked in Neyvia. | neyvia |
| [script.build_c11f_panel](modules/script.build_c11f_panel/README.md) | Replace administration probes with disposable everyday-app goals. | neyvia |
| [script.build_c1_manual](modules/script.build_c1_manual/README.md) | Add the C1 chapter without changing other authored CL chapter bytes. | neyvia |
| [script.build_c1b_manual](modules/script.build_c1b_manual/README.md) | Add the bounded driver chapter while preserving other CL chapter bytes. | neyvia |
| [script.build_c2_browser_manual](modules/script.build_c2_browser_manual/README.md) | Author the C2 effect and decision contract in the existing browser manual. | neyvia |
| [script.build_c2f_browser_manual](modules/script.build_c2f_browser_manual/README.md) | Extend the existing authored browser manual; preserve other chapters. | neyvia |
| [script.build_c2g_browser_manual](modules/script.build_c2g_browser_manual/README.md) | Author the goal cascade and drag contract in the existing browser manual. | neyvia |
| [script.build_cl_context](modules/script.build_cl_context/README.md) | Compile exact, source-bound CL startup context without runtime downloads. | neyvia |
| [script.build_claude_plugin_skills](modules/script.build_claude_plugin_skills/README.md) | Write the Claude Code plugin's skills (plugins/neyvia/skills) from Neyvia's manuals. | neyvia |
| [script.build_fix_browser_ui](modules/script.build_fix_browser_ui/README.md) | Provides script / build_fix_browser_ui in Neyvia. | neyvia |
| [script.build_fixcl_manual_cache](modules/script.build_fixcl_manual_cache/README.md) | Seal fully checked CL manual artifacts for fast, exact-byte cold admission. | neyvia |
| [script.build_grounded_manuals](modules/script.build_grounded_manuals/README.md) | Validate CL manual sources and regenerate their JSON and Markdown artifacts. | neyvia |
| [script.build_native_harness_timelapse](modules/script.build_native_harness_timelapse/README.md) | Build a compact GIF from the three real native-harness proof frames. | neyvia |
| [script.build_neyvia_support_bundle](modules/script.build_neyvia_support_bundle/README.md) | Build a privacy-safe Neyvia diagnostic bundle from allowlisted local evidence. | neyvia |
| [script.build_pandoc_reference_docx](modules/script.build_pandoc_reference_docx/README.md) | Build Neyvia's deterministic Pandoc DOCX reference document. | neyvia |
| [script.build_scroll_manual](modules/script.build_scroll_manual/README.md) | Refresh the scroll manual's schemas from its real native definitions. | neyvia |
| [script.build_t10_manual_contract](modules/script.build_t10_manual_contract/README.md) | Produce a grounded manual source for Claude's owned manuals/docs handoff. | neyvia |
| [script.build_t13_manual](modules/script.build_t13_manual/README.md) | Add the executable Evolver chapter without replacing legacy Lab procedures. | neyvia |
| [script.build_t16_probe](modules/script.build_t16_probe/README.md) | Build and launch the disposable native proof app using installed .NET only. | neyvia |
| [script.build_t17_manual](modules/script.build_t17_manual/README.md) | Generate the grounded autopilot manual from the live tool schemas. | neyvia |
| [script.build_t18_manual](modules/script.build_t18_manual/README.md) | Author the grounded per-layer contract from the live perception schemas. | neyvia |
| [script.build_t4_manual](modules/script.build_t4_manual/README.md) | Generate the T4 executable manual from its live native tool schemas. | neyvia |
| [script.build_t7_manual](modules/script.build_t7_manual/README.md) | Build the backend-owned executable sidebar manual from its live tool schemas. | neyvia |
| [script.c10_runtime](modules/script.c10_runtime/README.md) | Owned CPU LAYA launcher; system Python, existing frozen local weights only. | neyvia |
| [script.c10_tools](modules/script.c10_tools/README.md) | Fixed real-source research-tool benchmarks through Neyvia's native registry. | neyvia-core |
| [script.c10_tools_checkpoint](modules/script.c10_tools_checkpoint/README.md) | Seal real tool evidence and append the research ledger without promotion. | neyvia |
| [script.c10_tools_manual](modules/script.c10_tools_manual/README.md) | Author Connected Language contracts for the measured research tools. | neyvia |
| [script.c10_tools_mcp](modules/script.c10_tools_mcp/README.md) | Use this checkout's real read-only stdio MCP, without changing attachments. | neyvia |
| [script.c10c_quality](modules/script.c10c_quality/README.md) | Frozen, gold-isolated paired FRAMES evaluation for C10c (stdlib only). | neyvia |
| [script.c10d_checkpoint](modules/script.c10d_checkpoint/README.md) | Summarize a completed development experiment and append its measured ledger row. | neyvia |
| [script.c10d_study](modules/script.c10d_study/README.md) | Independent Sol ablations and frozen C10 panels, using the existing blind judge. | neyvia |
| [script.c11_cohort_learning](modules/script.c11_cohort_learning/README.md) | Production Connected Language and grounded flow receipts for owned C1 apps. | neyvia |
| [script.c11_preview_ui](modules/script.c11_preview_ui/README.md) | Render Neyvia's complete production shell against the actual native driver. | neyvia |
| [script.c13_browser_probe](modules/script.c13_browser_probe/README.md) | Provides script / c13_browser_probe in Neyvia. | neyvia |
| [script.c13_browser_service_probe](modules/script.c13_browser_service_probe/README.md) | Exercise actual production Obscura capture and touch-input routes, hidden only. | neyvia |
| [script.c13_calibrate](modules/script.c13_calibrate/README.md) | Calibrate the C13 frozen text judge without model calls or downloads. | neyvia |
| [script.c13_contracts](modules/script.c13_contracts/README.md) | Run the compiled taste-harness CL contracts through the existing CL-Skill evaluator. | neyvia |
| [script.c13_lesson_replay](modules/script.c13_lesson_replay/README.md) | Rerun fresh Luna first drafts with/without a quarantined lesson through C9. | neyvia |
| [script.c13_motion_proof](modules/script.c13_motion_proof/README.md) | Provides script / c13_motion_proof in Neyvia. | neyvia |
| [script.c13_obscura_host](modules/script.c13_obscura_host/README.md) | Owned hidden Obscura lifecycle for the host-side render driver; no browser fallback. | neyvia |
| [script.c13_observed](modules/script.c13_observed/README.md) | Provides script / c13_observed in Neyvia. | neyvia |
| [script.c13_render](modules/script.c13_render/README.md) | Provides script / c13_render in Neyvia. | neyvia |
| [script.c13_run](modules/script.c13_run/README.md) | Re-run the two R6 briefs with real Luna calls and the production CL completion host. | neyvia |
| [script.c13_stitch](modules/script.c13_stitch/README.md) | Compose reader-walk viewport pixels without changing the browser viewport. | neyvia |
| [script.c13_verify](modules/script.c13_verify/README.md) | Fresh CL completion checks and a compact, hash-bound C13d live receipt. | neyvia |
| [script.c13f_seal](modules/script.c13f_seal/README.md) | Seal observed C13f evidence; never infer quality or usage from artifact existence. | neyvia |
| [script.c13g_summary](modules/script.c13g_summary/README.md) | Seal observed round-9 metrics; never turn a failure into a completed task. | neyvia |
| [script.c13h_jevbench](modules/script.c13h_jevbench/README.md) | Reuse the installed frozen public benchmark, keeping every write in this task. | neyvia |
| [script.c13h_learning](modules/script.c13h_learning/README.md) | Import attributed public defects and genuine Paul preferences into separate layers. | neyvia |
| [script.c13h_prepare](modules/script.c13h_prepare/README.md) | Acquire bounded, licensed local taste assets; no credentials or global installs. | neyvia |
| [script.c13h_public_render](modules/script.c13h_public_render/README.md) | Provides script / c13h_public_render in Neyvia. | neyvia |
| [script.c13h_report](modules/script.c13h_report/README.md) | Seal observed R11 artifacts, audit learning labels and publish a blind local packet. | neyvia |
| [script.c13i_alternate](modules/script.c13i_alternate/README.md) | Provides script / c13i_alternate in Neyvia. | neyvia |
| [script.c13i_calibrate](modules/script.c13i_calibrate/README.md) | Measure actual frozen LAYA on real page decisions; never tune on held-out. | neyvia |
| [script.c13i_checkpoint](modules/script.c13i_checkpoint/README.md) | Preserve the inherited taste work; keep large runtime proof outside Git. | neyvia |
| [script.c13i_data](modules/script.c13i_data/README.md) | Recover all Paul labels and frozen real page decisions without training heads. | neyvia |
| [script.c13i_destinations](modules/script.c13i_destinations/README.md) | Observe an alternate real filing destination; never manufacture its status. | neyvia |
| [script.c13i_jobs](modules/script.c13i_jobs/README.md) | Hidden owned R12 compiled jobs, with detached capture and durable PIDs. | neyvia |
| [script.c13i_labels](modules/script.c13i_labels/README.md) | Export all used Paul records and real retention decisions without training. | neyvia |
| [script.c13i_laya](modules/script.c13i_laya/README.md) | Restore only the isolated frozen CPU service used by R12; no watchdog. | neyvia |
| [script.c13i_negative](modules/script.c13i_negative/README.md) | Exercise failure and abstention routes using recorded real-page cases. | neyvia |
| [script.c13i_pixel_gate](modules/script.c13i_pixel_gate/README.md) | Select a head-free nearest-real-repair gate on calibration pages only. | neyvia |
| [script.c13i_reconcile_preflight](modules/script.c13i_reconcile_preflight/README.md) | Preserve the unmatched old-checker experiment and restore a matched seed. | neyvia |
| [script.c13i_report](modules/script.c13i_report/README.md) | Bind R12 blind screenshots, actual usage and bounded admission evidence. | neyvia |
| [script.c13i_run](modules/script.c13i_run/README.md) | Resumable R12 page comparison, using Obscura and metered tool-free models. | neyvia |
| [script.c13i_status](modules/script.c13i_status/README.md) | Bounded R12 status projection; never scans browser profiles or model streams. | neyvia |
| [script.c13i_usage](modules/script.c13i_usage/README.md) | Read only this task's orchestration token counter; no unrelated transcript output. | neyvia |
| [script.c13i_verify](modules/script.c13i_verify/README.md) | Compile and run only the authored R12 Connected Language contracts. | neyvia |
| [script.c1_comparison_checker](modules/script.c1_comparison_checker/README.md) | Fresh disposable fixtures and independent read-only C1 comparison checks. | neyvia |
| [script.c1_comparison_execution](modules/script.c1_comparison_execution/README.md) | Owned attempts and paired scoring for the immutable computer-use panel. | neyvia |
| [script.c1_native_benchmark](modules/script.c1_native_benchmark/README.md) | Bounded C1 Windows app benchmark using only windows launched by this run. | neyvia |
| [script.c1_openai_arm](modules/script.c1_openai_arm/README.md) | Launch the installed, official computer-use MCP runtime through codex exec. | neyvia |
| [script.c1cmp_visible_checker](modules/script.c1cmp_visible_checker/README.md) | Read only the newly owned Character Map field during the lead's Claude arm. | neyvia |
| [script.c2_browser_benchmark](modules/script.c2_browser_benchmark/README.md) | Provides script / c2_browser_benchmark in Neyvia. | neyvia |
| [script.c2_laya_consistency](modules/script.c2_laya_consistency/README.md) | Run the frozen local LAYA model and measure C2 browser decisions, offline. | neyvia |
| [script.c2b_action_capture](modules/script.c2b_action_capture/README.md) | Provides script / c2b_action_capture in Neyvia. | neyvia |
| [script.c2b_comparator_probe](modules/script.c2b_comparator_probe/README.md) | Provides script / c2b_comparator_probe in Neyvia. | neyvia |
| [script.c2b_corpus_align](modules/script.c2b_corpus_align/README.md) | Align recorded real action rows with the exact deployed CPU projection. | neyvia |
| [script.c2b_laya_advisory_corpus](modules/script.c2b_laya_advisory_corpus/README.md) | Freeze supported metadata decisions from fresh public native observations. | neyvia |
| [script.c2b_laya_computer_corpus](modules/script.c2b_laya_computer_corpus/README.md) | Retain independently observed historical UIA facts as replay-only decisions. | neyvia |
| [script.c2b_laya_evaluate](modules/script.c2b_laya_evaluate/README.md) | Fit only calibration rows; evaluate untouched real-run decision groups. | neyvia |
| [script.c2b_laya_filter_corpus](modules/script.c2b_laya_filter_corpus/README.md) | Reject semantically ambiguous recorded action goals before corpus grading. | neyvia |
| [script.c2b_laya_fit_probe](modules/script.c2b_laya_fit_probe/README.md) | One bounded representation comparison on fitting observations only. | neyvia |
| [script.c2b_laya_service](modules/script.c2b_laya_service/README.md) | Start exactly one warm task-owned LAYA CPU process on an explicit port. | neyvia |
| [script.c2b_laya_threshold_independence](modules/script.c2b_laya_threshold_independence/README.md) | Actual model calls prove policy thresholds do not change predictions. | neyvia |
| [script.c2b_live_loop](modules/script.c2b_live_loop/README.md) | Provides script / c2b_live_loop in Neyvia. | neyvia |
| [script.c2b_native_benchmark](modules/script.c2b_native_benchmark/README.md) | Provides script / c2b_native_benchmark in Neyvia. | neyvia |
| [script.c2b_public_answers](modules/script.c2b_public_answers/README.md) | Provides script / c2b_public_answers in Neyvia. | neyvia |
| [script.c2b_public_benchmark](modules/script.c2b_public_benchmark/README.md) | Provides script / c2b_public_benchmark in Neyvia. | neyvia |
| [script.c2c_cleanup](modules/script.c2c_cleanup/README.md) | Provides script / c2c_cleanup in Neyvia. | neyvia |
| [script.c2c_control](modules/script.c2c_control/README.md) | Provides script / c2c_control in Neyvia. | neyvia |
| [script.c2c_fill_proof](modules/script.c2c_fill_proof/README.md) | Provides script / c2c_fill_proof in Neyvia. | neyvia |
| [script.c2c_freeze_tasks](modules/script.c2c_freeze_tasks/README.md) | Provides script / c2c_freeze_tasks in Neyvia. | neyvia |
| [script.c2c_gate_audit](modules/script.c2c_gate_audit/README.md) | Rescore retained real model replies and production gates without a service. | neyvia |
| [script.c2c_laya_effects](modules/script.c2c_laya_effects/README.md) | Complete live effect checks after the frozen holdout; never refits a gate. | neyvia |
| [script.c2c_laya_fit](modules/script.c2c_laya_fit/README.md) | Fitting-only compact explicit-intent representation probe; never reads holdout. | neyvia |
| [script.c2c_laya_run](modules/script.c2c_laya_run/README.md) | Freeze fit gate, capture independent public groups, evaluate, and prove actions. | neyvia |
| [script.c2c_laya_seal](modules/script.c2c_laya_seal/README.md) | Independently rescore frozen choices and bind the final real receipt. | neyvia |
| [script.c2c_operator](modules/script.c2c_operator/README.md) | Provides script / c2c_operator in Neyvia. | neyvia |
| [script.c2c_webvoyager](modules/script.c2c_webvoyager/README.md) | Provides script / c2c_webvoyager in Neyvia. | neyvia |
| [script.c2d_batch_now](modules/script.c2d_batch_now/README.md) | Provides script / c2d_batch_now in Neyvia. | neyvia |
| [script.c2d_booking_dates](modules/script.c2d_booking_dates/README.md) | Provides script / c2d_booking_dates in Neyvia. | neyvia |
| [script.c2d_compact_history](modules/script.c2d_compact_history/README.md) | Provides script / c2d_compact_history in Neyvia. | neyvia |
| [script.c2d_control](modules/script.c2d_control/README.md) | Provides script / c2d_control in Neyvia. | neyvia |
| [script.c2d_dom_recovery](modules/script.c2d_dom_recovery/README.md) | Provides script / c2d_dom_recovery in Neyvia. | neyvia |
| [script.c2d_extract_pentagram](modules/script.c2d_extract_pentagram/README.md) | Provides script / c2d_extract_pentagram in Neyvia. | neyvia |
| [script.c2d_failure_audit](modules/script.c2d_failure_audit/README.md) | Provides script / c2d_failure_audit in Neyvia. | neyvia |
| [script.c2d_grade](modules/script.c2d_grade/README.md) | Provides script / c2d_grade in Neyvia. | neyvia |
| [script.c2d_inspect_receipt](modules/script.c2d_inspect_receipt/README.md) | Provides script / c2d_inspect_receipt in Neyvia. | neyvia |
| [script.c2d_native_receipt_proof](modules/script.c2d_native_receipt_proof/README.md) | Provides script / c2d_native_receipt_proof in Neyvia. | neyvia |
| [script.c2d_owner_grant](modules/script.c2d_owner_grant/README.md) | Provides script / c2d_owner_grant in Neyvia. | neyvia |
| [script.c2d_resource_proof](modules/script.c2d_resource_proof/README.md) | Provides script / c2d_resource_proof in Neyvia. | neyvia |
| [script.c2d_site_proof](modules/script.c2d_site_proof/README.md) | Provides script / c2d_site_proof in Neyvia. | neyvia |
| [script.c2d_token_meter](modules/script.c2d_token_meter/README.md) | Provides script / c2d_token_meter in Neyvia. | neyvia |
| [script.c2d_webvoyager](modules/script.c2d_webvoyager/README.md) | Provides script / c2d_webvoyager in Neyvia. | neyvia |
| [script.c2f_answers](modules/script.c2f_answers/README.md) | Provides script / c2f_answers in Neyvia. | neyvia |
| [script.c2f_build_obscura](modules/script.c2f_build_obscura/README.md) | Provides script / c2f_build_obscura in Neyvia. | neyvia |
| [script.c2f_engine_fetch_proof](modules/script.c2f_engine_fetch_proof/README.md) | Provides script / c2f_engine_fetch_proof in Neyvia. | neyvia |
| [script.c2f_grade](modules/script.c2f_grade/README.md) | Provides script / c2f_grade in Neyvia. | neyvia |
| [script.c2f_laya_proof](modules/script.c2f_laya_proof/README.md) | Provides script / c2f_laya_proof in Neyvia. | neyvia |
| [script.c2f_pane_proof](modules/script.c2f_pane_proof/README.md) | Provides script / c2f_pane_proof in Neyvia. | neyvia |
| [script.c2f_profile](modules/script.c2f_profile/README.md) | Provides script / c2f_profile in Neyvia. | neyvia |
| [script.c2f_replay](modules/script.c2f_replay/README.md) | Provides script / c2f_replay in Neyvia. | neyvia |
| [script.c2f_script_proof](modules/script.c2f_script_proof/README.md) | Provides script / c2f_script_proof in Neyvia. | neyvia |
| [script.c2f_search_compile](modules/script.c2f_search_compile/README.md) | Provides script / c2f_search_compile in Neyvia. | neyvia |
| [script.c2f_site_flows](modules/script.c2f_site_flows/README.md) | Provides script / c2f_site_flows in Neyvia. | neyvia |
| [script.c2g_admit_obscura](modules/script.c2g_admit_obscura/README.md) | Provides script / c2g_admit_obscura in Neyvia. | neyvia |
| [script.c2g_bbc_chronology](modules/script.c2g_bbc_chronology/README.md) | Provides script / c2g_bbc_chronology in Neyvia. | neyvia |
| [script.c2g_bbc_feed_probe](modules/script.c2g_bbc_feed_probe/README.md) | Provides script / c2g_bbc_feed_probe in Neyvia. | neyvia |
| [script.c2g_booking_flow](modules/script.c2g_booking_flow/README.md) | Provides script / c2g_booking_flow in Neyvia. | neyvia |
| [script.c2g_browser_abilities](modules/script.c2g_browser_abilities/README.md) | Actual owned Obscura network/render/DOM browser abilities, no mock result. | neyvia |
| [script.c2g_browser_port_contract](modules/script.c2g_browser_port_contract/README.md) | Run port admission parsers only; no socket or HTTP request to the extra range. | neyvia |
| [script.c2g_browser_preferences](modules/script.c2g_browser_preferences/README.md) | Provides script / c2g_browser_preferences in Neyvia. | neyvia |
| [script.c2g_build_native](modules/script.c2g_build_native/README.md) | Provides script / c2g_build_native in Neyvia. | neyvia |
| [script.c2g_build_obscura](modules/script.c2g_build_obscura/README.md) | Provides script / c2g_build_obscura in Neyvia. | neyvia |
| [script.c2g_close_initial_native](modules/script.c2g_close_initial_native/README.md) | Close the initial task-owned guardian; its kill-on-close job owns descendants. | neyvia |
| [script.c2g_compiled_recovery](modules/script.c2g_compiled_recovery/README.md) | Provides script / c2g_compiled_recovery in Neyvia. | neyvia |
| [script.c2g_finalize_engine_patch](modules/script.c2g_finalize_engine_patch/README.md) | Provides script / c2g_finalize_engine_patch in Neyvia. | neyvia |
| [script.c2g_launch_native](modules/script.c2g_launch_native/README.md) | Run the normal task-only browser bridge under the reused C1 private launcher. | neyvia |
| [script.c2g_native_abilities](modules/script.c2g_native_abilities/README.md) | Provides script / c2g_native_abilities in Neyvia. | neyvia |
| [script.c2g_ordinary_latency](modules/script.c2g_ordinary_latency/README.md) | Matched ordinary page-load/fetch probe; no extrapolation to public-task latency. | neyvia |
| [script.c2g_patch_engine](modules/script.c2g_patch_engine/README.md) | Provides script / c2g_patch_engine in Neyvia. | neyvia |
| [script.c2g_patch_fragment_render](modules/script.c2g_patch_fragment_render/README.md) | Provides script / c2g_patch_fragment_render in Neyvia. | neyvia |
| [script.c2g_scroll_background](modules/script.c2g_scroll_background/README.md) | Actual screenshot regression: ordinary scroll versus same-document fragment. | neyvia |
| [script.c2g_seal](modules/script.c2g_seal/README.md) | Provides script / c2g_seal in Neyvia. | neyvia |
| [script.c2g_site_controls](modules/script.c2g_site_controls/README.md) | Provides script / c2g_site_controls in Neyvia. | neyvia |
| [script.c2g_task_proof](modules/script.c2g_task_proof/README.md) | Provides script / c2g_task_proof in Neyvia. | neyvia |
| [script.c2h_admit_engine](modules/script.c2h_admit_engine/README.md) | Admit the opacity-cull Obscura build after the real-engine ability suite passes on it. | neyvia |
| [script.c2h_admit_websocket](modules/script.c2h_admit_websocket/README.md) | Provides script / c2h_admit_websocket in Neyvia. | neyvia |
| [script.c2h_apply_upstream](modules/script.c2h_apply_upstream/README.md) | Provides script / c2h_apply_upstream in Neyvia. | neyvia |
| [script.c2h_build_patch](modules/script.c2h_build_patch/README.md) | Provides script / c2h_build_patch in Neyvia. | neyvia |
| [script.c2h_context_proof](modules/script.c2h_context_proof/README.md) | Provides script / c2h_context_proof in Neyvia. | neyvia |
| [script.c2h_handoff_proof](modules/script.c2h_handoff_proof/README.md) | Provides script / c2h_handoff_proof in Neyvia. | neyvia |
| [script.c2h_handoff_ui](modules/script.c2h_handoff_ui/README.md) | Provides script / c2h_handoff_ui in Neyvia. | neyvia |
| [script.c2h_merge_segments](modules/script.c2h_merge_segments/README.md) | Provides script / c2h_merge_segments in Neyvia. | neyvia |
| [script.c2h_planner_proof](modules/script.c2h_planner_proof/README.md) | Provides script / c2h_planner_proof in Neyvia. | neyvia |
| [script.c2h_receipt](modules/script.c2h_receipt/README.md) | Provides script / c2h_receipt in Neyvia. | neyvia |
| [script.c2h_recovery_proof](modules/script.c2h_recovery_proof/README.md) | Provides script / c2h_recovery_proof in Neyvia. | neyvia |
| [script.c2h_review](modules/script.c2h_review/README.md) | Provides script / c2h_review in Neyvia. | neyvia |
| [script.c2h_upstream_tests](modules/script.c2h_upstream_tests/README.md) | Provides script / c2h_upstream_tests in Neyvia. | neyvia |
| [script.c2h_websocket_proof](modules/script.c2h_websocket_proof/README.md) | Provides script / c2h_websocket_proof in Neyvia. | neyvia |
| [script.c4_quality](modules/script.c4_quality/README.md) | Independent, bounded R4 artifact checks; never reads the blind answer key. | neyvia |
| [script.c4c_browser](modules/script.c4c_browser/README.md) | C4c owned Obscura checks. No Chromium launch, fallback, or personal tabs. | neyvia |
| [script.c4c_quality](modules/script.c4c_quality/README.md) | R5 blind artifact checks. No answer keys; identical checks for both arms. | neyvia |
| [script.c7_dependencies](modules/script.c7_dependencies/README.md) | Explicit, workspace-owned C7 dependencies; never install into System Python. | neyvia |
| [script.c8_backend](modules/script.c8_backend/README.md) | Start unmodified selected Neyvia source with an explicit empty harness scope. | neyvia |
| [script.c8_desktop_guard](modules/script.c8_desktop_guard/README.md) | Read-only desktop sampling for the owned C8 process tree. Never sends input. | neyvia |
| [script.c8_fixtures](modules/script.c8_fixtures/README.md) | Authored C8d fixture catalog; materialize only disposable task-local inputs. | neyvia |
| [script.c8_headless](modules/script.c8_headless/README.md) | Task-only restrictions on real Playwright transports; no result substitution. | neyvia |
| [script.c8_journey](modules/script.c8_journey/README.md) | Disposable UI journey worker using a pinned Neyvia's headless T18 code. | neyvia |
| [script.c8_scope](modules/script.c8_scope/README.md) | Process-local socket boundary for owned C8 services and journey workers. | neyvia |
| [script.c8d_worker](modules/script.c8d_worker/README.md) | Execute one source-bound manual journey through an owned headless web page. | neyvia |
| [script.c8e_browser_checks](modules/script.c8e_browser_checks/README.md) | Observe genuine Harness worker capacity waits without provider dispatch. | neyvia |
| [script.c8e_bug_checks](modules/script.c8e_bug_checks/README.md) | Confined real effects for four previously unauthored runtime procedures. | neyvia |
| [script.c8e_design_checks](modules/script.c8e_design_checks/README.md) | Run existing design owners with owned output and a real headless browser. | neyvia |
| [script.c8e_effects](modules/script.c8e_effects/README.md) | Fresh producer/effect checks for C8e's former empty status-read passes. | neyvia |
| [script.c8e_extra_effects](modules/script.c8e_extra_effects/README.md) | Additional C8e journeys through real owners, peers and mounted app controls. | neyvia |
| [script.c8e_host_effects](modules/script.c8e_host_effects/README.md) | Fresh durable/OS observations of the original B host contract runners. | neyvia |
| [script.c8e_local_checks](modules/script.c8e_local_checks/README.md) | Fresh independent effects for locally satisfied prerequisites. | neyvia |
| [script.c8e_onboarding](modules/script.c8e_onboarding/README.md) | Run the real local pack staging owner in a confined hidden child. | neyvia |
| [script.c8e_prerequisites](modules/script.c8e_prerequisites/README.md) | C8e prerequisite inventory and real scratch-owner preparation. | neyvia |
| [script.c8e_scroll_checks](modules/script.c8e_scroll_checks/README.md) | Authored untrusted pack inputs for the real no-inference validator journey. | neyvia |
| [script.c8e_session_checks](modules/script.c8e_session_checks/README.md) | Real stored Neyvia conversations prove reversible session overlays. | neyvia |
| [script.c8e_sidebar](modules/script.c8e_sidebar/README.md) | Pinned local embeddings and real stored-user-transcript sidebar journeys. | neyvia |
| [script.c8e_slim_build](modules/script.c8e_slim_build/README.md) | Produce a signed slim installer using only existing local offline tools. | neyvia |
| [script.c8e_speech](modules/script.c8e_speech/README.md) | Run the installed speech engine on CPU with a task-local write/network fence. | neyvia |
| [script.c8e_state_effects](modules/script.c8e_state_effects/README.md) | Mounted draft, file-admission and owner-state witnesses for C8e. | neyvia |
| [script.c8e_terminal](modules/script.c8e_terminal/README.md) | Scope the real private ConPTY shell to disposable profile and history state. | neyvia |
| [script.c8e_ui_effects](modules/script.c8e_ui_effects/README.md) | Real mounted actions for the layout, setup and launcher proof chapters. | neyvia |
| [script.c8e_verify_slim](modules/script.c8e_verify_slim/README.md) | Provides script / c8e_verify_slim in Neyvia. | neyvia |
| [script.c8e_vite.config](modules/script.c8e_vite.config/README.md) | Provides script / c8e_vite / config in Neyvia. | neyvia |
| [script.c8f_native](modules/script.c8f_native/README.md) | Execute the frozen C8 native manuals against an owned C11 application. | neyvia |
| [script.c8f_provider](modules/script.c8f_provider/README.md) | Bounded real Codex provider call; saved login stays inside the official CLI. | neyvia |
| [script.c8f_recount](modules/script.c8f_recount/README.md) | Recount C8f evidence without promoting partial effects into F10 passes. | neyvia |
| [script.c8f_sidebar](modules/script.c8f_sidebar/README.md) | Real stored conversations, sidebar bus effects and reversible cleanup. | neyvia |
| [script.c8f_sync](modules/script.c8f_sync/README.md) | Native Syncthing actions through Neyvia's selected producer and CL manual. | neyvia |
| [script.c8g_native](modules/script.c8g_native/README.md) | Run the integrated native journey from an explicitly private process desktop. | neyvia |
| [script.c8h_conpty](modules/script.c8h_conpty/README.md) | Bounded ConPTY desktop diagnostic; never switches desktops or shows UI. | neyvia |
| [script.c8h_f10](modules/script.c8h_f10/README.md) | Fresh bounded F10 batches. Execution receipts never substitute for full passes. | neyvia |
| [script.c8h_harness](modules/script.c8h_harness/README.md) | Bootstrap the worktree's real compact MCP/CL gateway with bounded output. | neyvia |
| [script.c8h_recount](modules/script.c8h_recount/README.md) | Keep C8h's preserved denominator and fresh authority boundaries explicit. | neyvia |
| [script.c8h_remote](modules/script.c8h_remote/README.md) | Actual loopback remote manuals against an owned private native window. | neyvia |
| [script.c9b_backend](modules/script.c9b_backend/README.md) | Owned proof backend with protected-read and socket boundaries installed first. | neyvia |
| [script.c9c_backend](modules/script.c9c_backend/README.md) | Isolated production handlers for hidden Neyvia browser rubric proof. | neyvia |
| [script.c9c_lifecycle](modules/script.c9c_lifecycle/README.md) | Real Luna feedback -> paired executable trial -> HTTP revert proof. | neyvia |
| [script.c9c_native](modules/script.c9c_native/README.md) | Launch the owned Neyvia browser on a verified separate Windows desktop. | neyvia |
| [script.capture_native_evolution](modules/script.capture_native_evolution/README.md) | Provides script / capture_native_evolution in Neyvia. | neyvia |
| [script.capture_neyvia_session_ui](modules/script.capture_neyvia_session_ui/README.md) | Provides script / capture_neyvia_session_ui in Neyvia. | neyvia |
| [script.capture_theme_pairs](modules/script.capture_theme_pairs/README.md) | Provides script / capture_theme_pairs in Neyvia. | neyvia |
| [script.check_C7e_deadline_retention](modules/script.check_C7e_deadline_retention/README.md) | Check deadline-receipt retention contracts using disposable local metadata. | neyvia |
| [script.check_connected_codex_chats](modules/script.check_connected_codex_chats/README.md) | Provides script / check_connected_codex_chats in Neyvia. | neyvia |
| [script.check_dispatch_returns](modules/script.check_dispatch_returns/README.md) | Check handler imports in guarded name dispatches have executable calls. | neyvia |
| [script.check_external_chat_inventory](modules/script.check_external_chat_inventory/README.md) | Provides script / check_external_chat_inventory in Neyvia. | neyvia |
| [script.check_hermes_subscription_route](modules/script.check_hermes_subscription_route/README.md) | Provides script / check_hermes_subscription_route in Neyvia. | neyvia |
| [script.check_installer_size](modules/script.check_installer_size/README.md) | Provides script / check_installer_size in Neyvia. | neyvia |
| [script.check_neyvia_marketplace_toolchain](modules/script.check_neyvia_marketplace_toolchain/README.md) | Provides script / check_neyvia_marketplace_toolchain in Neyvia. | neyvia |
| [script.check_workflow_publication_integrity](modules/script.check_workflow_publication_integrity/README.md) | Fail closed when GitHub Actions can silently mutate NEYVIA publication state. | neyvia |
| [script.checkpoint_C7e](modules/script.checkpoint_C7e/README.md) | Record current completed C7 contract families without claiming full coverage. | neyvia |
| [script.cl11_answer_probe](modules/script.cl11_answer_probe/README.md) | Real native image read plus explicit-answer transport and refusal journey. | neyvia |
| [script.cl11_boundary_review](modules/script.cl11_boundary_review/README.md) | Inspect owned native event inputs; never inspect protected targets themselves. | neyvia |
| [script.cl11_data_probe](modules/script.cl11_data_probe/README.md) | Actual stdio Notes content must preserve ordinary business identifiers. | neyvia |
| [script.cl11_finish_report](modules/script.cl11_finish_report/README.md) | Append method and transcript evidence without regrading the frozen cohort. | neyvia |
| [script.cl11_native_review](modules/script.cl11_native_review/README.md) | Conservative, reproducible evidence index for CL11 native transcripts. | neyvia |
| [script.cl11_playwright_mcp](modules/script.cl11_playwright_mcp/README.md) | Task-local raw Playwright MCP for native-alone runs. No manual or CL adapter. | neyvia |
| [script.cl11_preflight](modules/script.cl11_preflight/README.md) | Replay the disjoint development native/web recovery journeys with receipts. | neyvia |
| [script.cl11_procedures](modules/script.cl11_procedures/README.md) | Real, disposable development journeys for the preferred CL procedures. | neyvia |
| [script.cl11_projection_review](modules/script.cl11_projection_review/README.md) | Check rendered CL text in existing scored receipts; never regrade runs. | neyvia |
| [script.cl11_provenance_probe](modules/script.cl11_provenance_probe/README.md) | Disjoint dev adversary: a self-submitted answer is not source evidence. | neyvia |
| [script.cl11_recover_report](modules/script.cl11_recover_report/README.md) | Recover first-cohort display after the nullable native-result renderer error. | neyvia |
| [script.cl11_review](modules/script.cl11_review/README.md) | Bounded Claude review of the authored CL11 task set; no tool access. | neyvia |
| [script.cl11_seal_evidence](modules/script.cl11_seal_evidence/README.md) | Commit-sized CL11 receipts: raw transcripts, integrity index, aggregate proof. | neyvia |
| [script.cl11_semantic_native_review](modules/script.cl11_semantic_native_review/README.md) | Visible native transcript evidence with hash-bound human semantic annotations. | neyvia |
| [script.cl11_verify_evidence](modules/script.cl11_verify_evidence/README.md) | Independently read committed evidence bytes and check scheduled slot coverage. | neyvia |
| [script.cl_benchmark](modules/script.cl_benchmark/README.md) | Run the fixed five-layer paired Connected Language evaluation on real models. | neyvia |
| [script.cl_benchmark_1.1](modules/script.cl_benchmark_1.1/README.md) | Freeze/review/resume CL 1.1 cohorts; scored runs require reviewed task inputs. | neyvia |
| [script.cl_compile_manuals](modules/script.cl_compile_manuals/README.md) | Compile authored Connected Language manuals to the existing JSON artifact. | neyvia |
| [script.cl_conformance](modules/script.cl_conformance/README.md) | Run production CL syntax/semantic audits without executing tool effects. | handoff-recovery |
| [script.cl_evidence](modules/script.cl_evidence/README.md) | Export and verify the bounded CL handoff from task-owned real-run receipts. | neyvia |
| [script.cl_inventory](modules/script.cl_inventory/README.md) | Inventory the actual agent-facing contracts before and after CL migration. | neyvia |
| [script.cl_token_meter](modules/script.cl_token_meter/README.md) | Measure input text with exact o200k and a labelled Claude approximation. | neyvia |
| [script.claude_plan_limits](modules/script.claude_plan_limits/README.md) | Collect Claude's documented status-line windows, or launch its UI without an AI turn. | neyvia |
| [script.claudex](modules/script.claudex/README.md) | Provides script / claudex in Neyvia. | neyvia |
| [script.close_c11g_bureaus](modules/script.close_c11g_bureaus/README.md) | Release only empty, inactive Bureau UUIDs recorded by this task's receipts. | neyvia |
| [script.codex_local_oauth_helper](modules/script.codex_local_oauth_helper/README.md) | Provides script / codex_local_oauth_helper in Neyvia. | neyvia |
| [script.collect-t5-evidence](modules/script.collect-t5-evidence/README.md) | Provides script / collect-t5-evidence in Neyvia. | neyvia |
| [script.collect_dependency_license_evidence](modules/script.collect_dependency_license_evidence/README.md) | Create checked-in license evidence from already-resolved local metadata. | neyvia |
| [script.collect_fix_evidence](modules/script.collect_fix_evidence/README.md) | Bind FIX's actual receipts, final checks, commits and remaining work. | neyvia |
| [script.collect_t16_evidence](modules/script.collect_t16_evidence/README.md) | Consolidate observed T16 outcomes and hashes without replacing adverse receipts. | neyvia |
| [script.compact_C7d_evidence](modules/script.compact_C7d_evidence/README.md) | Prune owned disposable fixtures after preserving referenced evidence bytes. | neyvia |
| [script.configure_nas_provider_auth_broker](modules/script.configure_nas_provider_auth_broker/README.md) | Configure NAS consumers for Neyvia's provider-scoped auth broker. | neyvia |
| [script.control_route_interaction_smoke](modules/script.control_route_interaction_smoke/README.md) | DEPRECATED as a product UI gate. | neyvia |
| [script.control_route_responsive_smoke](modules/script.control_route_responsive_smoke/README.md) | Provides script / control_route_responsive_smoke in Neyvia. | neyvia |
| [script.control_route_smoke](modules/script.control_route_smoke/README.md) | Provides script / control_route_smoke in Neyvia. | neyvia |
| [script.control_route_visual_smoke](modules/script.control_route_visual_smoke/README.md) | DEPRECATED as a product UI gate. | neyvia |
| [script.core_gate_seam_proof](modules/script.core_gate_seam_proof/README.md) | Evidence: the LAYA glance answers plan 22's release-gate request as a command. | neyvia |
| [script.core_sdk_seam_proof](modules/script.core_sdk_seam_proof/README.md) | Evidence: an out-of-repo caller judges its own scene with its own predicates (plan 23 SDK seam). | neyvia |
| [script.core_ui_fix_proof](modules/script.core_ui_fix_proof/README.md) | Evidence: improve() with real UI fix actions on the three P22 bugs at their pre-fix commit. | neyvia |
| [script.design_normalize](modules/script.design_normalize/README.md) | Provides script / design_normalize in Neyvia. | neyvia |
| [script.design_proof](modules/script.design_proof/README.md) | Provides script / design_proof in Neyvia. | neyvia |
| [script.design_review](modules/script.design_review/README.md) | Provides script / design_review in Neyvia. | neyvia |
| [script.desktop_update_key](modules/script.desktop_update_key/README.md) | The desktop updater's signing key: where it lives and how its password is kept. | neyvia |
| [script.diagnose_C7e_rendered](modules/script.diagnose_C7e_rendered/README.md) | Run one isolated direct verifier pass to expose the rendered-family worker error. | neyvia |
| [script.dogfix_browser](modules/script.dogfix_browser/README.md) | Provides script / dogfix_browser in Neyvia. | neyvia |
| [script.dogfix_contracts](modules/script.dogfix_contracts/README.md) | Executable DOGFIX manual procedures; confined fixtures, no provider substitution. | neyvia |
| [script.dogfix_harness](modules/script.dogfix_harness/README.md) | Bounded command-line bridge to this worktree's Neyvia MCP/CL gateway. | neyvia |
| [script.dogfix_manual](modules/script.dogfix_manual/README.md) | Add one checked procedure to the existing authored workspace manual. | neyvia |
| [script.efficiency_log](modules/script.efficiency_log/README.md) | Receipt-backed efficiency ledger. Standard library only; never launches a provider. | neyvia |
| [script.evolve_final](modules/script.evolve_final/README.md) | Evidence script: the final EVOLVE gate + CL-compile patches against the current release candidate. | neyvia |
| [script.evolve_gate_runner](modules/script.evolve_gate_runner/README.md) | Evidence script: run one gate target from a candidate overlay inside a measurement tree. | neyvia |
| [script.evolve_proof](modules/script.evolve_proof/README.md) | Evidence script: turn evolve run summaries into the plan-25 proof and evaluate the CL checks. | neyvia |
| [script.evolve_run](modules/script.evolve_run/README.md) | Evidence script: run the plan-25 evolving engine on the P22 gate and verify the result. | neyvia |
| [script.export_t18_evidence](modules/script.export_t18_evidence/README.md) | Export reviewable real-run receipts; keep private runtime/auth state ignored. | neyvia |
| [script.finalize_c10c](modules/script.finalize_c10c/README.md) | Seal complete C10c comparisons and their actual local raw receipts. | neyvia |
| [script.finalize_c10d](modules/script.finalize_c10d/README.md) | Seal C10d evidence, full-panel gates and honest deduplicated usage. | neyvia |
| [script.finalize_c4b](modules/script.finalize_c4b/README.md) | Bind the sealed paired panel and real pressure probes without rewriting archives. | neyvia |
| [script.finalize_neyvia_native_evolution](modules/script.finalize_neyvia_native_evolution/README.md) | Provides script / finalize_neyvia_native_evolution in Neyvia. | neyvia |
| [script.finalize_neyvia_native_evolution_v2](modules/script.finalize_neyvia_native_evolution_v2/README.md) | Provides script / finalize_neyvia_native_evolution_v2 in Neyvia. | neyvia |
| [script.finalize_neyvia_native_evolution_v3](modules/script.finalize_neyvia_native_evolution_v3/README.md) | Provides script / finalize_neyvia_native_evolution_v3 in Neyvia. | neyvia |
| [script.finalize_neyvia_native_evolution_v4](modules/script.finalize_neyvia_native_evolution_v4/README.md) | Provides script / finalize_neyvia_native_evolution_v4 in Neyvia. | neyvia |
| [script.finalize_neyvia_native_evolution_v5](modules/script.finalize_neyvia_native_evolution_v5/README.md) | Provides script / finalize_neyvia_native_evolution_v5 in Neyvia. | neyvia |
| [script.finalize_t19_evidence](modules/script.finalize_t19_evidence/README.md) | Provides script / finalize_t19_evidence in Neyvia. | neyvia |
| [script.fix2_scope](modules/script.fix2_scope/README.md) | FIX2-only proof authority; denials are visible, never remapped successes. | neyvia |
| [script.fix_checks](modules/script.fix_checks/README.md) | Record FIX structural gates on the operator-selected Python and explicit ports. | neyvia |
| [script.fix_classic_manuals](modules/script.fix_classic_manuals/README.md) | Maintain FIX navigation contracts in authored CL, then compile normally. | neyvia |
| [script.fixcl2_acquire_sidebar_model](modules/script.fixcl2_acquire_sidebar_model/README.md) | Optional explicit acquisition; first sidebar use runs the same provisioner. | neyvia |
| [script.fixcl2_add_creative_manual](modules/script.fixcl2_add_creative_manual/README.md) | Author the focused local creative-records manual from current native schemas. | neyvia |
| [script.fixcl2_add_local_procedures](modules/script.fixcl2_add_local_procedures/README.md) | Append the FIXCL2 local procedures to the canonical JSON and CL manuals. | neyvia |
| [script.fixcl2_add_manual_procedures](modules/script.fixcl2_add_manual_procedures/README.md) | Add exact quarantined manual-edit procedures to the canonical CL pair. | neyvia |
| [script.fixcl2_add_work_manual](modules/script.fixcl2_add_work_manual/README.md) | Create the focused adaptive-work CL manual and its executable JSON artifact. | adaptive-work |
| [script.fixcl2_authority_probe](modules/script.fixcl2_authority_probe/README.md) | Real owner HTTP CL mutations and renderer-protocol adverse journeys. | neyvia |
| [script.fixcl2_browser_probe](modules/script.fixcl2_browser_probe/README.md) | Real hidden Obscura browser journey with fresh native and CL effect gates. | neyvia |
| [script.fixcl2_cold_probe](modules/script.fixcl2_cold_probe/README.md) | Cold process and warm transport timings for a real spawned CL procedure. | neyvia |
| [script.fixcl2_coordination_probe](modules/script.fixcl2_coordination_probe/README.md) | Actual local workflow recorder journey through the CL host, with byte drift. | neyvia |
| [script.fixcl2_creative_probe](modules/script.fixcl2_creative_probe/README.md) | Real CL records with exact owner state, corrupt/stale refusal, and no model calls. | neyvia |
| [script.fixcl2_documents_probe](modules/script.fixcl2_documents_probe/README.md) | Run actual PDF/Scroll owner actions and fresh document effect predicates. | neyvia |
| [script.fixcl2_durable_probe](modules/script.fixcl2_durable_probe/README.md) | Real CL host journeys for retained mission and Night Shift actions. | neyvia |
| [script.fixcl2_frontier_probe](modules/script.fixcl2_frontier_probe/README.md) | Real CL calls on disposable owner state for the FIXCL2 local frontier layer. | neyvia |
| [script.fixcl2_renderer_manual](modules/script.fixcl2_renderer_manual/README.md) | Append the renderer chapter without rewriting existing authored CL records. | neyvia |
| [script.fixcl2_renderer_probe](modules/script.fixcl2_renderer_probe/README.md) | Independently bind Claude's mounted-pane journey to the current FIXCL2 backend. | neyvia |
| [script.fixcl2_semantic_probe](modules/script.fixcl2_semantic_probe/README.md) | Exercise semantic native owner mutations and CL effect predicates in scratch. | neyvia |
| [script.fixcl2_sidebar_frontier_probe](modules/script.fixcl2_sidebar_frontier_probe/README.md) | Real offline CL sidebar grouping, model drift refusal, confirm, and undo. | neyvia |
| [script.fixcl2_terminal_probe](modules/script.fixcl2_terminal_probe/README.md) | Real hidden system-Python commands, exact terminal effects and corrupt receipt refusal. | neyvia |
| [script.fixcl2_work_probe](modules/script.fixcl2_work_probe/README.md) | Disposable real CL work actions with durable-state and refusal receipts. | neyvia |
| [script.fixcl3_app_open_manual](modules/script.fixcl3_app_open_manual/README.md) | Author exact acknowledged app/text-publication opening procedures. | neyvia |
| [script.fixcl3_app_open_probe](modules/script.fixcl3_app_open_probe/README.md) | Real app-open journeys, called inside the owned Neyvia renderer harness. | neyvia |
| [script.fixcl3_aud4_matrix](modules/script.fixcl3_aud4_matrix/README.md) | Re-run AUD4's exact 37 surfaces / 185 criteria on two source boundaries. | neyvia |
| [script.fixcl3_authority_probe](modules/script.fixcl3_authority_probe/README.md) | Real owner HTTP CL mutations and renderer-protocol adverse journeys. | neyvia |
| [script.fixcl3_capture_manual](modules/script.fixcl3_capture_manual/README.md) | Add exact HTTP-byte and native-PNG procedures to canonical existing manuals. | neyvia |
| [script.fixcl3_capture_probe](modules/script.fixcl3_capture_probe/README.md) | Real HTTP bytes and actual owned Obscura PNG through positive CL/manual gates. | neyvia |
| [script.fixcl3_cold_probe](modules/script.fixcl3_cold_probe/README.md) | Cold process and warm transport timings for a real spawned CL procedure. | neyvia |
| [script.fixcl3_configuration_manual](modules/script.fixcl3_configuration_manual/README.md) | Add exact local configuration procedures to existing canonical manuals. | neyvia |
| [script.fixcl3_configuration_probe](modules/script.fixcl3_configuration_probe/README.md) | Real CL configuration calls and independently re-read owner drift refusals. | neyvia |
| [script.fixcl3_core_probe](modules/script.fixcl3_core_probe/README.md) | Run the actual CL initializer and independent capsule hash verification. | neyvia |
| [script.fixcl3_device_pdf_probe](modules/script.fixcl3_device_pdf_probe/README.md) | Actual paired file copies and remote refusals over disposable local HTTP peers. | neyvia |
| [script.fixcl3_documents_probe](modules/script.fixcl3_documents_probe/README.md) | Run actual PDF/Scroll owner actions and fresh document effect predicates. | neyvia |
| [script.fixcl3_environment_manual](modules/script.fixcl3_environment_manual/README.md) | Author the bounded pinned environment CL procedures without editing the index. | neyvia |
| [script.fixcl3_environment_probe](modules/script.fixcl3_environment_probe/README.md) | Actual offline empty-lock uv environment and fresh task-file CL witnesses. | neyvia |
| [script.fixcl3_jobs_probe](modules/script.fixcl3_jobs_probe/README.md) | Real CL durable admission/control calls; no model/job-generation substitution. | neyvia |
| [script.fixcl3_manual_execution_manual](modules/script.fixcl3_manual_execution_manual/README.md) | Add current typed entry procedures to the existing manuals-next owner. | neyvia |
| [script.fixcl3_manual_execution_probe](modules/script.fixcl3_manual_execution_probe/README.md) | Real checked cohorts, zero-model compiled writes and exact failure recovery. | neyvia |
| [script.fixcl3_manual_gate_probe](modules/script.fixcl3_manual_gate_probe/README.md) | Exercise approved canonical wrapper preservation and actual recursion refusals. | neyvia |
| [script.fixcl3_manual_grounding_probe](modules/script.fixcl3_manual_grounding_probe/README.md) | Repair six owned manual contracts and prove strict grounding on actual registry reads. | neyvia |
| [script.fixcl3_mechanisms_manual](modules/script.fixcl3_mechanisms_manual/README.md) | Author exact frozen-lab and context compaction procedures, index owned by lead. | neyvia |
| [script.fixcl3_mechanisms_probe](modules/script.fixcl3_mechanisms_probe/README.md) | Real frozen candidate competition and durable transcript compaction witnesses. | neyvia |
| [script.fixcl3_obscura_runtime_probe](modules/script.fixcl3_obscura_runtime_probe/README.md) | Real Obscura PDF transport/parser witnesses and native canvas limitations. | neyvia |
| [script.fixcl3_projection_manual](modules/script.fixcl3_projection_manual/README.md) | Add typed observation/projection entry procedures to the existing owner. | neyvia |
| [script.fixcl3_projection_probe](modules/script.fixcl3_projection_probe/README.md) | Real local observer streams, immutable paging and large delta artifacts. | neyvia |
| [script.fixcl3_provider_manual](modules/script.fixcl3_provider_manual/README.md) | Append the exact provider procedures without rewriting historical CL types. | neyvia |
| [script.fixcl3_provider_probe](modules/script.fixcl3_provider_probe/README.md) | Actual loopback peer transport and fresh durable CL provider effect witnesses. | neyvia |
| [script.fixcl3_provision_probe](modules/script.fixcl3_provision_probe/README.md) | Fresh source/cache startup and real bounded local-peer sidebar provisioning. | neyvia |
| [script.fixcl3_records_manual](modules/script.fixcl3_records_manual/README.md) | Build the focused local-records executable manual without editing its index. | neyvia |
| [script.fixcl3_records_probe](modules/script.fixcl3_records_probe/README.md) | Retained positive CL witnesses and fresh drift refusals for every local adapter. | neyvia |
| [script.fixcl3_regression_compatibility](modules/script.fixcl3_regression_compatibility/README.md) | Resolve one obsolete FIXCL2 capture expectation with retained real FIXCL3 proof. | neyvia |
| [script.fixcl3_regression_probe](modules/script.fixcl3_regression_probe/README.md) | Replay unchanged FIXCL2 functional assertions against frozen FIXCL3 sources. | neyvia |
| [script.fixcl3_renderer_probe](modules/script.fixcl3_renderer_probe/README.md) | Current-source mounted panes and PDF in Neyvia's own headless browser. | neyvia |
| [script.fixcl4_browser_sdk_probe](modules/script.fixcl4_browser_sdk_probe/README.md) | Real private Neyvia browser sessions, SDK goals and frozen LAYA advice. | neyvia |
| [script.fixcl4_cold_probe](modules/script.fixcl4_cold_probe/README.md) | Cold process and warm transport timings for a real spawned CL procedure. | neyvia |
| [script.fixcl4_conductor_probe](modules/script.fixcl4_conductor_probe/README.md) | Real advertised Codex routes and owned detached Conductor provider turns. | neyvia |
| [script.fixcl4_evaluation_probe](modules/script.fixcl4_evaluation_probe/README.md) | Actual CL task evidence, trace, pixel, curriculum and managed rehearsal journeys. | neyvia |
| [script.fixcl4_evolver_probe](modules/script.fixcl4_evolver_probe/README.md) | Real CL evolution with locked judges, actual paired manuals and adverse loss. | neyvia |
| [script.fixcl4_host_probe](modules/script.fixcl4_host_probe/README.md) | Real managed hidden processes and an actual workspace-writing MCP plugin. | neyvia |
| [script.fixcl4_provider_probe](modules/script.fixcl4_provider_probe/README.md) | Real selected-provider Autopilot and Conductor journeys, no model fixtures. | neyvia |
| [script.fixcl4_render_alias_probe](modules/script.fixcl4_render_alias_probe/README.md) | Positive CL aliases witnessed in the actual mounted Neyvia shell. | neyvia |
| [script.fixcl4_render_media_probe](modules/script.fixcl4_render_media_probe/README.md) | Actual CL media journeys in Neyvia's own headless browser and FFmpeg. | neyvia |
| [script.fixcl4_render_pdf_probe](modules/script.fixcl4_render_pdf_probe/README.md) | Faithful actual PDF canvases in Neyvia's installed headless browser. | neyvia |
| [script.fixcl4_research_probe](modules/script.fixcl4_research_probe/README.md) | Real public-source research, bounded Sol synthesis and exact CL evidence. | neyvia |
| [script.fixcl4_sdk_mount_probe](modules/script.fixcl4_sdk_mount_probe/README.md) | Actual SDK Phone iframe and CL proof through the owned Neyvia renderer. | neyvia |
| [script.fixcl4_service_manuals](modules/script.fixcl4_service_manuals/README.md) | Append real provider/manual completion procedures, preserving old chapters. | neyvia |
| [script.fixcl4_service_source_hashes](modules/script.fixcl4_service_source_hashes/README.md) | Source boundary for the actual FIXCL4 service/provider journeys. | neyvia |
| [script.fixcl4_services_probe](modules/script.fixcl4_services_probe/README.md) | Real service observations and native contracts, confined to FIXCL ports. | neyvia |
| [script.fixcl5_manual_witnesses](modules/script.fixcl5_manual_witnesses/README.md) | Recover original emitted manual receipts from passing, source-current journeys. | neyvia |
| [script.fixcl7_build_obscura](modules/script.fixcl7_build_obscura/README.md) | Provides script / fixcl7_build_obscura in Neyvia. | neyvia |
| [script.fixcl7_cache_receipt](modules/script.fixcl7_cache_receipt/README.md) | Measure unchanged regeneration and execute a bounded C7 CL contract case. | neyvia |
| [script.fixcl7_complete_capture_patch](modules/script.fixcl7_complete_capture_patch/README.md) | Extend the native child raster to region/PDF captures; retain portable patch. | neyvia |
| [script.fixcl7_manual_contracts](modules/script.fixcl7_manual_contracts/README.md) | Author FIXCL7 acceptance in the owning Connected Language manual. | neyvia |
| [script.fixcl7_model_usage](modules/script.fixcl7_model_usage/README.md) | Read only scoped product-replay token counters; never prompts or credentials. | neyvia |
| [script.fixcl7_patch_iframe_renderer](modules/script.fixcl7_patch_iframe_renderer/README.md) | Prepare the task-local Obscura iframe paint patch; never edit the source donor. | neyvia |
| [script.fixcl7_refresh_manuals](modules/script.fixcl7_refresh_manuals/README.md) | Check or reconcile authored CL action schemas with the registered native tools. | neyvia |
| [script.fixcl7_regenerate](modules/script.fixcl7_regenerate/README.md) | One-command, source-current AUD4 regeneration through compiled CL journeys. | neyvia |
| [script.fixcl_codec_probe](modules/script.fixcl_codec_probe/README.md) | Focused codec invariant probe; production transport proof is FIXCL's runner. | neyvia |
| [script.fixcl_cold_probe](modules/script.fixcl_cold_probe/README.md) | Cold process and warm transport timings for a real spawned CL procedure. | neyvia |
| [script.fixcl_effect_journeys](modules/script.fixcl_effect_journeys/README.md) | Disposable inputs for real FIXCL transport journeys; no fake observer values. | neyvia |
| [script.fixcl_latency_probe](modules/script.fixcl_latency_probe/README.md) | Measure the real source-impact path, without invoking a desktop or provider. | neyvia |
| [script.fixcl_negative_probe](modules/script.fixcl_negative_probe/README.md) | Real refusal journeys against disposable Notes, manuals and pane requests. | neyvia |
| [script.fixcl_recycle_probe](modules/script.fixcl_recycle_probe/README.md) | Real quiet Recycle Bin conservation through CL and spawned MCP. | neyvia |
| [script.fixcl_verify](modules/script.fixcl_verify/README.md) | Real FIXCL CL-host, HTTP/plugin and spawned stdio journeys on disposable state. | neyvia |
| [script.fluxio-cli](modules/script.fluxio-cli/README.md) | Provides script / fluxio-cli in Neyvia. | neyvia |
| [script.gate](modules/script.gate/README.md) | Impact-scoped Connected Language release gate (no pytest or full tour). | neyvia |
| [script.generate_C7e_artifact_manual](modules/script.generate_C7e_artifact_manual/README.md) | Compile the artifact-manual Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_adapters](modules/script.generate_C7e_c7d_adapters/README.md) | Compile the c7d-adapters Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_control](modules/script.generate_C7e_c7d_control/README.md) | Compile the c7d-control Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_control_completion](modules/script.generate_C7e_c7d_control_completion/README.md) | Compile the c7d-control-completion Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_desktop](modules/script.generate_C7e_c7d_desktop/README.md) | Compile the c7d-desktop Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_engine](modules/script.generate_C7e_c7d_engine/README.md) | Compile the c7d-engine Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_native_commands](modules/script.generate_C7e_c7d_native_commands/README.md) | Compile the c7d-native-commands Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_projection](modules/script.generate_C7e_c7d_projection/README.md) | Compile the c7d-projection Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_provider_marks](modules/script.generate_C7e_c7d_provider_marks/README.md) | Compile the c7d-provider-marks Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_providers](modules/script.generate_C7e_c7d_providers/README.md) | Compile the c7d-providers Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_rendered](modules/script.generate_C7e_c7d_rendered/README.md) | Compile the c7d-rendered Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_ui](modules/script.generate_C7e_c7d_ui/README.md) | Compile the c7d-ui Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_ui_control](modules/script.generate_C7e_c7d_ui_control/README.md) | Compile the c7d-ui-control Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_ui_settings](modules/script.generate_C7e_c7d_ui_settings/README.md) | Compile the c7d-ui-settings Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_verification](modules/script.generate_C7e_c7d_verification/README.md) | Compile the c7d-verification Connected Language contract. | neyvia |
| [script.generate_C7e_c7d_wz](modules/script.generate_C7e_c7d_wz/README.md) | Compile the c7d-wz Connected Language contract. | neyvia |
| [script.generate_C7e_capabilities](modules/script.generate_C7e_capabilities/README.md) | Compile the capabilities Connected Language contract. | neyvia |
| [script.generate_C7e_capability_completion](modules/script.generate_C7e_capability_completion/README.md) | Compile the capability-completion Connected Language contract. | neyvia |
| [script.generate_C7e_capability_models](modules/script.generate_C7e_capability_models/README.md) | Compile the capability-models Connected Language contract. | neyvia |
| [script.generate_C7e_chat_shell](modules/script.generate_C7e_chat_shell/README.md) | Compile the chat-shell Connected Language contract. | neyvia |
| [script.generate_C7e_control](modules/script.generate_C7e_control/README.md) | Compile the control Connected Language contract. | neyvia |
| [script.generate_C7e_control_remaining](modules/script.generate_C7e_control_remaining/README.md) | Compile the control-remaining Connected Language contract. | neyvia |
| [script.generate_C7e_core](modules/script.generate_C7e_core/README.md) | Compile the core Connected Language contract. | neyvia |
| [script.generate_C7e_engine](modules/script.generate_C7e_engine/README.md) | Compile the engine Connected Language contract. | neyvia |
| [script.generate_C7e_family](modules/script.generate_C7e_family/README.md) | Compile a selected existing C7 builder into its executable CL family manual. | neyvia |
| [script.generate_C7e_frontend](modules/script.generate_C7e_frontend/README.md) | Compile the frontend Connected Language contract. | neyvia |
| [script.generate_C7e_host_actions_completion](modules/script.generate_C7e_host_actions_completion/README.md) | Compile the host-actions-completion Connected Language contract. | neyvia |
| [script.generate_C7e_host_runtime](modules/script.generate_C7e_host_runtime/README.md) | Compile the host-runtime Connected Language contract. | neyvia |
| [script.generate_C7e_local](modules/script.generate_C7e_local/README.md) | Compile the local Connected Language contract. | neyvia |
| [script.generate_C7e_local_completion](modules/script.generate_C7e_local_completion/README.md) | Compile the local-completion Connected Language contract. | neyvia |
| [script.generate_C7e_mission_completion](modules/script.generate_C7e_mission_completion/README.md) | Compile the mission-completion Connected Language contract. | neyvia |
| [script.generate_C7e_missions](modules/script.generate_C7e_missions/README.md) | Compile the missions Connected Language contract. | neyvia |
| [script.generate_C7e_mobile](modules/script.generate_C7e_mobile/README.md) | Compile the mobile Connected Language contract. | neyvia |
| [script.generate_C7e_models](modules/script.generate_C7e_models/README.md) | Compile the models Connected Language contract. | neyvia |
| [script.generate_C7e_native](modules/script.generate_C7e_native/README.md) | Compile the native Connected Language contract. | neyvia |
| [script.generate_C7e_native_completion](modules/script.generate_C7e_native_completion/README.md) | Compile the native-completion Connected Language contract. | neyvia |
| [script.generate_C7e_preferences_skills](modules/script.generate_C7e_preferences_skills/README.md) | Compile the preferences-skills Connected Language contract. | neyvia |
| [script.generate_C7e_providers](modules/script.generate_C7e_providers/README.md) | Compile the providers Connected Language contract. | neyvia |
| [script.generate_C7e_pure](modules/script.generate_C7e_pure/README.md) | Compile the family-scoped pure edge campaign manual from its JSON contract. | neyvia |
| [script.generate_C7e_scheduler](modules/script.generate_C7e_scheduler/README.md) | Compile the scheduler Connected Language contract. | neyvia |
| [script.generate_C7e_session_completion](modules/script.generate_C7e_session_completion/README.md) | Compile the session-completion Connected Language contract. | neyvia |
| [script.generate_C7e_sessions](modules/script.generate_C7e_sessions/README.md) | Compile the sessions Connected Language contract. | neyvia |
| [script.generate_C7e_surfaces](modules/script.generate_C7e_surfaces/README.md) | Compile the surfaces Connected Language contract. | neyvia |
| [script.generate_C7e_ui_planning_local](modules/script.generate_C7e_ui_planning_local/README.md) | Compile the ui-planning-local Connected Language contract. | neyvia |
| [script.generate_C7e_ui_remaining](modules/script.generate_C7e_ui_remaining/README.md) | Compile the ui-remaining Connected Language contract. | neyvia |
| [script.generate_dependency_inventory](modules/script.generate_dependency_inventory/README.md) | Write the deterministic Neyvia dependency inventory without network access. | neyvia |
| [script.generate_module_map](modules/script.generate_module_map/README.md) | Generate or check the source-derived module registry; no test framework. | neyvia |
| [script.glm_ui_redesign_proof](modules/script.glm_ui_redesign_proof/README.md) | Provides script / glm_ui_redesign_proof in Neyvia. | neyvia |
| [script.gui_harness](modules/script.gui_harness/README.md) | Bounded access to this worktree's compact Neyvia MCP server (GUI track). | neyvia |
| [script.gui_shots](modules/script.gui_shots/README.md) | GUI-track Obscura journeys on explicitly owned ports; no browser fallback. | neyvia |
| [script.import_efficiency_history](modules/script.import_efficiency_history/README.md) | Import the bounded A4 historical corpus without executing benchmarks or services. | neyvia |
| [script.import_real_agent_proof_bundle](modules/script.import_real_agent_proof_bundle/README.md) | Provides script / import_real_agent_proof_bundle in Neyvia. | neyvia |
| [script.inception_gate_api](modules/script.inception_gate_api/README.md) | JSON batch interface to the same Inception gate used by native tools. | neyvia |
| [script.install-neyvia-controller-startup](modules/script.install-neyvia-controller-startup/README.md) | Provides script / install-neyvia-controller-startup in Neyvia. | neyvia |
| [script.install_cua_driver](modules/script.install_cua_driver/README.md) | Stage the pinned MIT Cua Driver for this user; never install globally or start services. | neyvia |
| [script.install_nas_runtime_stack](modules/script.install_nas_runtime_stack/README.md) | Provides script / install_nas_runtime_stack in Neyvia. | neyvia |
| [script.int2_audit](modules/script.int2_audit/README.md) | Review INT2 lost-line findings against retained AST owners and CL semantics. | neyvia |
| [script.int2_benchmark](modules/script.int2_benchmark/README.md) | Six unchanged CL 1.1 Luna-b tasks, paired with the original scored receipts. | neyvia |
| [script.int2_follow_proof](modules/script.int2_follow_proof/README.md) | Real FOLLOW HTTP/tool journeys on the explicitly selected integration server. | neyvia |
| [script.int2_follow_remote](modules/script.int2_follow_remote/README.md) | Real two-backend/native FOLLOW proof. Never reads saved credentials. | neyvia |
| [script.int2_http_proof](modules/script.int2_http_proof/README.md) | Real CL 1.1 calls through plugin, HTTP, web dispatch and desktop forwarding. | neyvia |
| [script.int2_merge_text](modules/script.int2_merge_text/README.md) | Redo a conflicted Git three-way text merge with normalized temporary inputs. | neyvia |
| [script.int2_pytest_compare](modules/script.int2_pytest_compare/README.md) | Compare complete guarded pytest runs by exact node IDs and phase outcomes. | neyvia |
| [script.int2_pytest_composite](modules/script.int2_pytest_composite/README.md) | Verify complete final pytest coverage, retaining raw runs and real replacements. | neyvia |
| [script.int2_pytest_guard](modules/script.int2_pytest_guard/README.md) | INT2 test-only audit guard and exact pytest outcome recorder. | neyvia |
| [script.int2_pytest_run](modules/script.int2_pytest_run/README.md) | Run pytest in an isolated source snapshot with the INT2 safety boundary. | neyvia |
| [script.int2_pytest_snapshot](modules/script.int2_pytest_snapshot/README.md) | Capture current tracked source bytes for an isolated INT2 pytest run. | neyvia |
| [script.int2_resolve_http](modules/script.int2_resolve_http/README.md) | Retain night-specific HTTP guards in FOLLOW's extracted HTTP owner. | neyvia |
| [script.int2_server](modules/script.int2_server/README.md) | Serve the production HTTP handler on one explicitly owned INT2 scratch root. | neyvia |
| [script.int2_sidebar](modules/script.int2_sidebar/README.md) | Real HTTP sidebar proof against 900 persisted chats on an isolated native backend. | neyvia |
| [script.int3_align_proof_manifests](modules/script.int3_align_proof_manifests/README.md) | Regenerate enforcement sites from authoritative CL-compiled contracts. | neyvia |
| [script.int3_benchmark](modules/script.int3_benchmark/README.md) | Six unchanged CL 1.1 Luna-b tasks, paired with the original scored receipts. | neyvia |
| [script.int3_checks](modules/script.int3_checks/README.md) | Record the requested per-merge structural checks without changing shared state. | neyvia |
| [script.int3_closeout](modules/script.int3_closeout/README.md) | Assemble INT3 acceptance from completed real receipts, retaining limitations. | neyvia |
| [script.int3_contracts](modules/script.int3_contracts/README.md) | Reconcile proof migrations by identity while keeping authored CL authoritative. | neyvia |
| [script.int3_finish_sources](modules/script.int3_finish_sources/README.md) | Align authored proof interfaces with the complete integrated dispatcher. | neyvia |
| [script.int3_guard_probe](modules/script.int3_guard_probe/README.md) | Exercise synchronous deadlines in a disposable, deliberately failing suite. | neyvia |
| [script.int3_historical_laya_checks](modules/script.int3_historical_laya_checks/README.md) | Supplement the missing early related check with exact first-merge source. | neyvia |
| [script.int3_laya_proof](modules/script.int3_laya_proof/README.md) | Real paired Evolver execution for LAYA binding, using a bounded CPU fixture. | neyvia |
| [script.int3_loss_review](modules/script.int3_loss_review/README.md) | Read-only semantic inventory for INT3 merges; writes only its review receipt. | neyvia |
| [script.int3_node_compare](modules/script.int3_node_compare/README.md) | Compare the exact surviving Node test declarations and failures. | neyvia |
| [script.int3_node_guard](modules/script.int3_node_guard/README.md) | Provides script / int3_node_guard in Neyvia. | neyvia |
| [script.int3_ports](modules/script.int3_ports/README.md) | Review/apply explicit fixture-port selection to Python and JS proof sources. | neyvia |
| [script.int3_prepare_native](modules/script.int3_prepare_native/README.md) | Prepare the exact small upstream binary required by the existing B proof. | neyvia |
| [script.int3_pytest_compare](modules/script.int3_pytest_compare/README.md) | Compare matched INT3 runs, preserving exact failure and finished-ID sets. | neyvia |
| [script.int3_pytest_guard](modules/script.int3_pytest_guard/README.md) | INT3 test-only audit guard and exact pytest outcome recorder. | neyvia |
| [script.int3_pytest_run](modules/script.int3_pytest_run/README.md) | Run pytest in an isolated source snapshot with the INT3 safety boundary. | neyvia |
| [script.int3_pytest_snapshot](modules/script.int3_pytest_snapshot/README.md) | Freeze exact Git ref source bytes inside INT3 for matched isolated tests. | neyvia |
| [script.int3_reseal](modules/script.int3_reseal/README.md) | Bind changed integration source bytes without rewriting historical run outcomes. | neyvia |
| [script.int3_resolve_ms](modules/script.int3_resolve_ms/README.md) | Reviewed structural M/S resolution; CL sources supply all manual semantics. | neyvia |
| [script.int3_resolve_proofs](modules/script.int3_resolve_proofs/README.md) | Resolve proof-share catalog/generated joins from preserved authored sources. | neyvia |
| [script.int3_resolve_r2](modules/script.int3_resolve_r2/README.md) | Explicit R2 resolution retains LAYA stores and adds the Paul-intent run domain. | neyvia |
| [script.int3_retirement_check](modules/script.int3_retirement_check/README.md) | Check every retired Python test function against the reconciled inventory. | neyvia |
| [script.int3_runtime](modules/script.int3_runtime/README.md) | Authenticated production HTTP journeys for the INT3 integrated mechanisms. | neyvia |
| [script.int3_server](modules/script.int3_server/README.md) | Production HTTP handler, explicit INT3 port and disposable account only. | neyvia |
| [script.int3_snapshot_fork](modules/script.int3_snapshot_fork/README.md) | Fork sealed task source, sharing only integrity-checked historical evidence. | neyvia |
| [script.int3_snapshot_refresh](modules/script.int3_snapshot_refresh/README.md) | Record explicit pre-execution repairs to an existing working source snapshot. | neyvia |
| [script.intcl_assemble_pytest](modules/script.intcl_assemble_pytest/README.md) | Assemble honest complete collection coverage from an interrupted run and its tail. | neyvia |
| [script.intcl_benchmark](modules/script.intcl_benchmark/README.md) | Six unchanged CL 1.1 Luna-b tasks, paired with the original scored receipts. | neyvia |
| [script.intcl_compare_pytest](modules/script.intcl_compare_pytest/README.md) | Compare complete guarded pytest runs by exact node IDs and phase outcomes. | neyvia |
| [script.intcl_compile](modules/script.intcl_compile/README.md) | Compile changed implementation files and record their exact inspected bytes. | neyvia |
| [script.intcl_composite_pytest](modules/script.intcl_composite_pytest/README.md) | Verify complete final pytest coverage, retaining raw runs and real replacements. | neyvia |
| [script.intcl_http_proof](modules/script.intcl_http_proof/README.md) | Real CL 1.1 calls through plugin, HTTP, web dispatch and desktop forwarding. | neyvia |
| [script.intcl_product_proof](modules/script.intcl_product_proof/README.md) | Real Luna calls through the product CLI transport and its completion receipts. | neyvia |
| [script.intcl_pytest_guard](modules/script.intcl_pytest_guard/README.md) | INTCL test-only audit guard and exact pytest outcome recorder. | neyvia |
| [script.intcl_run_pytest](modules/script.intcl_run_pytest/README.md) | Run pytest in an isolated source snapshot with the INTCL safety boundary. | neyvia |
| [script.intcl_seal_smoke](modules/script.intcl_seal_smoke/README.md) | Seal the six-task smoke from original, initial, and environment-retry receipts. | neyvia |
| [script.intcl_snapshot](modules/script.intcl_snapshot/README.md) | Copy current tracked source bytes to a task-local pytest snapshot. | neyvia |
| [script.intcl_socketpair](modules/script.intcl_socketpair/README.md) | Real Windows asyncio wakeup sockets inside INTCL's explicit port assignment. | neyvia |
| [script.intn_android_sdk](modules/script.intn_android_sdk/README.md) | Install bounded official Android SDK archives on D: and inspect native discovery. | neyvia |
| [script.intn_blocking_self_check](modules/script.intn_blocking_self_check/README.md) | Run the product's blocking startup proof gate in an owned hidden scope. | neyvia |
| [script.intn_check_merge](modules/script.intn_check_merge/README.md) | Run the requested release integration checks and retain bounded receipts on D:. | neyvia |
| [script.intn_editor_bridges](modules/script.intn_editor_bridges/README.md) | Exercise real project-scoped editor bridges in hidden batch processes. | neyvia |
| [script.intn_gate_table](modules/script.intn_gate_table/README.md) | Render the release gate table from its single JSON record; never infer a pass. | neyvia |
| [script.intn_merge](modules/script.intn_merge/README.md) | Normalize conflicted text and reconcile manual data for the release integrator. | neyvia |
| [script.intn_python_suite](modules/script.intn_python_suite/README.md) | Run existing Python files six at a time in disposable, guarded state on D:. | neyvia |
| [script.intn_rebind_inception](modules/script.intn_rebind_inception/README.md) | Rebind unchanged C8 contract closures; refuse semantic changes for review. | neyvia |
| [script.intn_rebind_license](modules/script.intn_rebind_license/README.md) | Revalidate captured production licenses after non-production manifest edits. | neyvia |
| [script.intn_refresh_c7_ports](modules/script.intn_refresh_c7_ports/README.md) | Admit the integrator's explicit ports in the authored C7 campaign schema. | neyvia |
| [script.intn_repair_manual_schemas](modules/script.intn_repair_manual_schemas/README.md) | Repair the exact manual declaration failures observed by INTN's startup run. | neyvia |
| [script.intn_restore_obscura](modules/script.intn_restore_obscura/README.md) | Recover the source-admitted browser on D without installing a runtime. | neyvia |
| [script.intn_startup_controller](modules/script.intn_startup_controller/README.md) | Observe the real blocking backend gate and retain its source-bound receipts on D. | neyvia |
| [script.intn_tour](modules/script.intn_tour/README.md) | Tour all existing apps through their real controls in hidden Obscura. | neyvia |
| [script.judge_c4c](modules/script.judge_c4c/README.md) | Frozen, blinded Luna artifact review; never uses preference/answer keys. | neyvia |
| [script.launch_fluxio](modules/script.launch_fluxio/README.md) | Provides script / launch_fluxio in Neyvia. | neyvia |
| [script.launch_neyvia](modules/script.launch_neyvia/README.md) | Provides script / launch_neyvia in Neyvia. | neyvia |
| [script.launch_t16_notepad](modules/script.launch_t16_notepad/README.md) | Open a disposable native Notepad document without requesting activation. | neyvia |
| [script.laya3d_contracts](modules/script.laya3d_contracts/README.md) | Blender upgrade journey on native labelled fixtures, then evaluate laya-3d.cl checks. | neyvia |
| [script.laya3d_engines](modules/script.laya3d_engines/README.md) | Native Godot/Unity Scene adapter journeys; private headless editors, no installs. | neyvia |
| [script.laya3d_harness](modules/script.laya3d_harness/README.md) | Local MCP bootstrap when Neyvia is absent from the caller's tool inventory. | neyvia |
| [script.laya3d_kronos](modules/script.laya3d_kronos/README.md) | LAYA 3D on Paul's KRONOS sheets: SEE -> CL shape program -> Blender -> compare -> fix. | neyvia |
| [script.laya3d_regression](modules/script.laya3d_regression/README.md) | Frozen CPU replay only: JevBench, retained decisions and retained layout head. | neyvia |
| [script.laya_author_contracts](modules/script.laya_author_contracts/README.md) | Author LAYAT chapters in the existing CL manuals and compile their artifacts. | neyvia |
| [script.laya_calibrate](modules/script.laya_calibrate/README.md) | Build the labelled corpora, admit the training cases into a fresh LAYA service, measure held-out accuracy. | neyvia |
| [script.laya_default_proof](modules/script.laya_default_proof/README.md) | LAYA on by default: start the Neyvia backend normally (no LAYA environment variable) and prove it owns the service. | neyvia |
| [script.laya_glance_corpus](modules/script.laya_glance_corpus/README.md) | Import reviewed screenshots once; hold out whole application surfaces before querying. | neyvia |
| [script.laya_glance_eval](modules/script.laya_glance_eval/README.md) | Measure the UI glance on labelled screenshots, grouped by app surface. | neyvia |
| [script.laya_glance_gate](modules/script.laya_glance_gate/README.md) | LAYA glance command for the P22 release gate. | neyvia |
| [script.laya_glance_images](modules/script.laya_glance_images/README.md) | One image-layer model transcription per requested screenshot; retain failures. | neyvia |
| [script.laya_glance_ingest](modules/script.laya_glance_ingest/README.md) | Write every labelled capture and every located defect as LAYA episodes. | neyvia |
| [script.laya_glance_live](modules/script.laya_glance_live/README.md) | Two owned Neyvia surfaces through Obscura; no desktop windows, no tour. | neyvia |
| [script.laya_glance_manual](modules/script.laya_glance_manual/README.md) | Author/compile the shared Scene API's executable manual (no test files). | neyvia |
| [script.laya_glance_measure](modules/script.laya_glance_measure/README.md) | Measure held-out surface episodes without changing labels or admission thresholds. | neyvia |
| [script.laya_glance_proof](modules/script.laya_glance_proof/README.md) | Write scripts/evidence/LAYAG-proof.json from grant_agent.laya_glance_proof.run(). | neyvia |
| [script.laya_glance_report](modules/script.laya_glance_report/README.md) | Publish bounded evidence summaries from actual receipts; no evaluation rerun. | neyvia |
| [script.laya_glance_sdk](modules/script.laya_glance_sdk/README.md) | Exercise the actual SDK facade against fresh native tool dispatch. | neyvia |
| [script.laya_glance_verify](modules/script.laya_glance_verify/README.md) | Run the authored manual through Neyvia, compile and replay verified procedures. | neyvia |
| [script.laya_harvest_c7_outcomes](modules/script.laya_harvest_c7_outcomes/README.md) | Harvest deduplicated, explicit operation outcomes from C7 receipts. | neyvia |
| [script.laya_harvest_routes](modules/script.laya_harvest_routes/README.md) | Harvest bounded manual-first and C4 route evidence into the Laya review set. | neyvia |
| [script.laya_instant_session](modules/script.laya_instant_session/README.md) | Measured Instant learning curves over existing corpora; no invented labels. | neyvia |
| [script.laya_label_workers](modules/script.laya_label_workers/README.md) | Bounded explicit Luna labelling workers; root verifies every routing proposal. | neyvia |
| [script.laya_measure](modules/script.laya_measure/README.md) | Measure what a LAYA check saves against the big-model check it replaces, on the calibrated held-out cases. | neyvia |
| [script.laya_measure_neural](modules/script.laya_measure_neural/README.md) | Measure actual frozen LAYA over learned candidates and separate few-shot taste. | neyvia |
| [script.laya_regression_gate](modules/script.laya_regression_gate/README.md) | Regression gate: Neyvia's LAYA changes must not degrade LAYA's existing 2D-to-3D capability. | neyvia |
| [script.laya_render_components](modules/script.laya_render_components/README.md) | Render public examples and original LAYA compositions using owned Obscura only. | neyvia |
| [script.laya_render_instant](modules/script.laya_render_instant/README.md) | Actual NxLaya screen, real store writes and report polling, owned Obscura. | neyvia |
| [script.laya_review_corpus](modules/script.laya_review_corpus/README.md) | Provenance-first C7, integration receipt and manual episode collection. | neyvia |
| [script.laya_review_curves](modules/script.laya_review_curves/README.md) | Frozen family-separated review curves; never tune on these outcomes. | neyvia |
| [script.laya_review_ingest](modules/script.laya_review_ingest/README.md) | Persist provenance-bound review episodes; evaluation families stay excluded. | neyvia |
| [script.laya_review_visual](modules/script.laya_review_visual/README.md) | Separate human preferences, auxiliary Luna labels and unchanged pixel gate. | neyvia |
| [script.laya_run_contracts](modules/script.laya_run_contracts/README.md) | Run the authored CL contracts, compile repeated verified runs and replay them. | neyvia |
| [script.laya_train_capabilities](modules/script.laya_train_capabilities/README.md) | Fit explicit candidate representations from executable manuals and real receipts. | neyvia |
| [script.laya_train_outcomes](modules/script.laya_train_outcomes/README.md) | Admit real native receipt labels into isolated reversible LAYA memory and audit transfer. | neyvia |
| [script.laya_train_session](modules/script.laya_train_session/README.md) | Scoped LAYA experiments; writes live artifacts on D:, never the source model tree. | neyvia |
| [script.laya_train_vision](modules/script.laya_train_vision/README.md) | Refit and measure the existing frozen-pixel head in task-local D: state. | neyvia |
| [script.laya_video_describe](modules/script.laya_video_describe/README.md) | Evidence script (plan 29 VID): LAYA describes a rendered video in words, so a model can correct the | neyvia |
| [script.laya_video_draft](modules/script.laya_video_draft/README.md) | Evidence script: assemble the first draft of a brief and observe it once (no fixes). | neyvia |
| [script.laya_video_proof](modules/script.laya_video_proof/README.md) | Evidence script (plan 28 first real proof): LAYA cuts Neyvia's launch film from real captures. | neyvia |
| [script.laya_video_taste_check](modules/script.laya_video_taste_check/README.md) | Evidence script (plan 28 Build 4): the A/B taste mechanism, checked without casting Paul's vote. | neyvia |
| [script.laya_visible_proof](modules/script.laya_visible_proof/README.md) | Proof for LAYA visibility and live preview, in Neyvia's owned Obscura browser. | neyvia |
| [script.lock_external_pack_sources](modules/script.lock_external_pack_sources/README.md) | Provides script / lock_external_pack_sources in Neyvia. | neyvia |
| [script.look_backend](modules/script.look_backend/README.md) | Look track: the real web backend with a few disposable sample chats. | neyvia |
| [script.look_render](modules/script.look_render/README.md) | Provides script / look_render in Neyvia. | neyvia |
| [script.look_sheet](modules/script.look_sheet/README.md) | Tile screenshots into one contact sheet: python scripts/look_sheet.py out.png a.png b.png ... [--cols 2 --scale 0.5] | neyvia |
| [script.lost_lines_check](modules/script.lost_lines_check/README.md) | Report side-added lines missing after each first-parent integration merge. | neyvia |
| [script.manual-depth-mcp](modules/script.manual-depth-mcp/README.md) | Provides script / manual-depth-mcp in Neyvia. | neyvia |
| [script.manual-recovery-mcp](modules/script.manual-recovery-mcp/README.md) | Provides script / manual-recovery-mcp in Neyvia. | neyvia |
| [script.manual_procedures](modules/script.manual_procedures/README.md) | Content audit for authored manuals and their compiled CL projections. | neyvia |
| [script.measure_c1_clients](modules/script.measure_c1_clients/README.md) | Compare persistent native-COM C# and comtypes MTA window-scoped cache clients. | neyvia |
| [script.measure_manual_first](modules/script.measure_manual_first/README.md) | Measure actual initialized harness prompts and schemas; no model request is sent. | neyvia |
| [script.mem_browser_proof](modules/script.mem_browser_proof/README.md) | Owned hidden browser journey through the production Memory and chat paths. | neyvia |
| [script.mem_contract_cases](modules/script.mem_contract_cases/README.md) | Executable memory contract cases, observed by the authored Memory CL manual. | neyvia |
| [script.mem_harness](modules/script.mem_harness/README.md) | Bounded local CL transport when an attached MCP is not exposed by the client. | neyvia |
| [script.mem_lifecycle](modules/script.mem_lifecycle/README.md) | Run authored memory CL procedures against disposable, real gateway stores. | neyvia |
| [script.mem_server](modules/script.mem_server/README.md) | Production HTTP handler on an owned MEM port, without live-tree access. | neyvia |
| [script.mem_token_usage](modules/script.mem_token_usage/README.md) | Count reported provider usage from this task's owned synthetic chat runs. | neyvia |
| [script.mod_author_manuals](modules/script.mod_author_manuals/README.md) | Author MOD's CL chapters using the existing lossless manual compiler. | hello-module |
| [script.mod_compiled_proof](modules/script.mod_compiled_proof/README.md) | Exercise the existing CL runner/compiler with the greeting mod contract. | neyvia |
| [script.mod_harness](modules/script.mod_harness/README.md) | Task-local controller for this checkout's real, authenticated Neyvia MCP. | neyvia |
| [script.mod_render](modules/script.mod_render/README.md) | Owned hidden Obscura journey controller; production DOM and SDK, no fixtures. | neyvia |
| [script.mod_sdk_proof](modules/script.mod_sdk_proof/README.md) | Real SDK/CL acceptance driver; contracts live in manuals/cl/modules.cl. | neyvia |
| [script.modp_stub_backend](modules/script.modp_stub_backend/README.md) | MODP evidence script: a small local stand-in for plan 29 section A (the Claude Code mod <-> Neyvia contract). | agents |
| [script.ms_backend](modules/script.ms_backend/README.md) | Owned MS HTTP host: explicit ports, disposable identity, no saved credentials. | neyvia |
| [script.nas_finish_cliproxyapi](modules/script.nas_finish_cliproxyapi/README.md) | Finish CLIProxyAPI bring-up + OAuth attempt on the NAS runtime host. | neyvia |
| [script.nas_grok_open_surfaces_discovery](modules/script.nas_grok_open_surfaces_discovery/README.md) | Discover Grok Build open surfaces on the NAS runtime (protocol flags only). | neyvia |
| [script.nas_install_cliproxyapi](modules/script.nas_install_cliproxyapi/README.md) | Install and start CLIProxyAPI on the Neyvia NAS runtime host. | neyvia |
| [script.nas_managed_cli_phase_a_install](modules/script.nas_managed_cli_phase_a_install/README.md) | Non-interactive NAS backup + managed CLI install attempt for Phase A. | neyvia |
| [script.nas_runtime_doctor](modules/script.nas_runtime_doctor/README.md) | Provides script / nas_runtime_doctor in Neyvia. | neyvia |
| [script.nas_seed_cliproxy_from_codex_oauth](modules/script.nas_seed_cliproxy_from_codex_oauth/README.md) | Seed CLIProxyAPI Codex auth from existing Neyvia/Fluxio OpenAI Codex OAuth tokens. | neyvia |
| [script.nas_setup](modules/script.nas_setup/README.md) | Provides script / nas_setup in Neyvia. | neyvia |
| [script.nas_ssh_probe](modules/script.nas_ssh_probe/README.md) | Provides script / nas_ssh_probe in Neyvia. | neyvia |
| [script.neyvia-cli](modules/script.neyvia-cli/README.md) | Provides script / neyvia-cli in Neyvia. | neyvia |
| [script.neyvia-transfer](modules/script.neyvia-transfer/README.md) | Provides script / neyvia-transfer in Neyvia. | neyvia |
| [script.neyvia_device_operator_approval](modules/script.neyvia_device_operator_approval/README.md) | Provides script / neyvia_device_operator_approval in Neyvia. | neyvia |
| [script.neyvia_ios_builder](modules/script.neyvia_ios_builder/README.md) | Provides script / neyvia_ios_builder in Neyvia. | neyvia |
| [script.neyvia_phase_c_backend_chat_attempts](modules/script.neyvia_phase_c_backend_chat_attempts/README.md) | Call /api/backend send_agent_chat_command for managed CLIs and record outcomes. | neyvia |
| [script.neyvia_phase_c_live_proofs](modules/script.neyvia_phase_c_live_proofs/README.md) | Phase C live proof attempts for Claude Code, Grok Build, and OpenCode. | neyvia |
| [script.neyvia_phase_c_local_chat_attempts](modules/script.neyvia_phase_c_local_chat_attempts/README.md) | Attempt local authenticated chat turns for Phase C; record auth/runtime blockers. | neyvia |
| [script.nx_gate_shard](modules/script.nx_gate_shard/README.md) | pytest plugin for `nx_promote.py gate`: run only this worker's share of the tests. | neyvia |
| [script.nx_impact](modules/script.nx_impact/README.md) | Impact map from the command line: what do these changed files connect to, and what is broken today? | neyvia |
| [script.nx_promote](modules/script.nx_promote/README.md) | Promote sandbox work (Neyvia-next) into the main working tree, gated and reversible. | neyvia |
| [script.obscura-FIXCL7-iframe-paint](modules/script.obscura-FIXCL7-iframe-paint/README.md) | Provides script / obscura-FIXCL7-iframe-paint in Neyvia. | neyvia |
| [script.obscura-v024-C2g-capabilities](modules/script.obscura-v024-C2g-capabilities/README.md) | Provides script / obscura-v024-C2g-capabilities in Neyvia. | neyvia |
| [script.obscura-v024-C2g-fragment-render-key](modules/script.obscura-v024-C2g-fragment-render-key/README.md) | Provides script / obscura-v024-C2g-fragment-render-key in Neyvia. | neyvia |
| [script.obscura-v024-C2h-opacity-cull](modules/script.obscura-v024-C2h-opacity-cull/README.md) | Provides script / obscura-v024-C2h-opacity-cull in Neyvia. | neyvia |
| [script.obscura-v024-C2h-websocket](modules/script.obscura-v024-C2h-websocket/README.md) | Provides script / obscura-v024-C2h-websocket in Neyvia. | neyvia |
| [script.obscura-v024-context-storage](modules/script.obscura-v024-context-storage/README.md) | Provides script / obscura-v024-context-storage in Neyvia. | neyvia |
| [script.obscura-v024-fetch-retention](modules/script.obscura-v024-fetch-retention/README.md) | Provides script / obscura-v024-fetch-retention in Neyvia. | neyvia |
| [script.onb_shots](modules/script.onb_shots/README.md) | Onboarding (track ONB) screenshots, rendered in Neyvia's Obscura engine. | neyvia |
| [script.p22_agents_journey](modules/script.p22_agents_journey/README.md) | Provides script / p22_agents_journey in Neyvia. | neyvia |
| [script.p22_build](modules/script.p22_build/README.md) | Provides script / p22_build in Neyvia. | neyvia |
| [script.p22_contract_audit](modules/script.p22_contract_audit/README.md) | Inventory every authored CL proof/check and retained Python case without pytest. | neyvia |
| [script.p22_coverage_report](modules/script.p22_coverage_report/README.md) | Bounded coverage replay; retains detailed module obligations in its receipt. | neyvia |
| [script.p22_frontend_outcomes](modules/script.p22_frontend_outcomes/README.md) | Provides script / p22_frontend_outcomes in Neyvia. | neyvia |
| [script.p22_js_imports](modules/script.p22_js_imports/README.md) | Provides script / p22_js_imports in Neyvia. | neyvia |
| [script.p22_measure](modules/script.p22_measure/README.md) | Run existing proof areas once and index passing execution-trace receipts. | neyvia |
| [script.p22_nightshift_journey](modules/script.p22_nightshift_journey/README.md) | Provides script / p22_nightshift_journey in Neyvia. | neyvia |
| [script.p22_outputs_journey](modules/script.p22_outputs_journey/README.md) | Provides script / p22_outputs_journey in Neyvia. | neyvia |
| [script.p22_release_dom](modules/script.p22_release_dom/README.md) | Provides script / p22_release_dom in Neyvia. | neyvia |
| [script.p22_release_models](modules/script.p22_release_models/README.md) | Provides script / p22_release_models in Neyvia. | neyvia |
| [script.p22_render](modules/script.p22_render/README.md) | One owned Obscura journey for the P22 PDF/surface/copy outcome contracts. | neyvia |
| [script.p22_v8_coverage](modules/script.p22_v8_coverage/README.md) | Provides script / p22_v8_coverage in Neyvia. | neyvia |
| [script.p22_workspace](modules/script.p22_workspace/README.md) | Provides script / p22_workspace in Neyvia. | neyvia |
| [script.pack-probe.Cargo](modules/script.pack-probe.Cargo/README.md) | Provides script / pack-probe / Cargo in Neyvia. | neyvia |
| [script.pack-probe.main](modules/script.pack-probe.main/README.md) | Provides script / pack-probe / main in Neyvia. | neyvia |
| [script.package_onboarding_packs](modules/script.package_onboarding_packs/README.md) | Package the declared local add-on components for the existing verified downloader. | neyvia |
| [script.pair_theme_shots](modules/script.pair_theme_shots/README.md) | Join <view>-<a>.png and <view>-<b>.png side by side into <view>-pair.png (plan 19 R3). | neyvia |
| [script.paul_corpus_extract](modules/script.paul_corpus_extract/README.md) | Extract Paul's own user turns (no assistant text, no credential files) for the manual of Paul. | neyvia |
| [script.phase_c_live_login_retry](modules/script.phase_c_live_login_retry/README.md) | Provides script / phase_c_live_login_retry in Neyvia. | neyvia |
| [script.phase_c_local_chat_orch_attempts](modules/script.phase_c_local_chat_orch_attempts/README.md) | Provides script / phase_c_local_chat_orch_attempts in Neyvia. | neyvia |
| [script.phase_c_local_login_debug](modules/script.phase_c_local_login_debug/README.md) | Provides script / phase_c_local_login_debug in Neyvia. | neyvia |
| [script.phase_c_ui_mode_switch_proof](modules/script.phase_c_ui_mode_switch_proof/README.md) | Provides script / phase_c_ui_mode_switch_proof in Neyvia. | neyvia |
| [script.placement_contact_sheet](modules/script.placement_contact_sheet/README.md) | Contact sheet for docs/evidence/placement-shots: index.html from receipt.json (no network, no scripts). | neyvia |
| [script.placement_journeys](modules/script.placement_journeys/README.md) | The shot list for scripts/placement_shots.py: each app through every placement, with checks. | neyvia |
| [script.placement_shots](modules/script.placement_shots/README.md) | Placement proof: every app in every placement, rendered in Neyvia's own Obscura engine. | neyvia |
| [script.plan_mission_artifact_repairs](modules/script.plan_mission_artifact_repairs/README.md) | Plan mission artifact repairs for hard artifact gates. | neyvia |
| [script.plan_nas_storage_cleanup](modules/script.plan_nas_storage_cleanup/README.md) | Plan NAS storage cleanup actions. | neyvia |
| [script.prepare_C13_obscura](modules/script.prepare_C13_obscura/README.md) | Provides script / prepare_C13_obscura in Neyvia. | neyvia |
| [script.prepare_C7e_families](modules/script.prepare_C7e_families/README.md) | Integrate generated family manuals once before freezing their replay source. | neyvia |
| [script.prepare_T20_obscura](modules/script.prepare_T20_obscura/README.md) | Provides script / prepare_T20_obscura in Neyvia. | neyvia |
| [script.prepare_backend_bundle](modules/script.prepare_backend_bundle/README.md) | Provides script / prepare_backend_bundle in Neyvia. | neyvia |
| [script.prepare_c10_tasks](modules/script.prepare_c10_tasks/README.md) | Freeze the public FRAMES panel and arm-blind research rubric (stdlib only). | neyvia |
| [script.prepare_neyvia_capability_app_fixture](modules/script.prepare_neyvia_capability_app_fixture/README.md) | Provides script / prepare_neyvia_capability_app_fixture in Neyvia. | neyvia |
| [script.prepare_release_environment](modules/script.prepare_release_environment/README.md) | Prepare a reusable, lock-bound NAS environment before release activation. | neyvia |
| [script.prepare_slim_release](modules/script.prepare_slim_release/README.md) | Provides script / prepare_slim_release in Neyvia. | neyvia |
| [script.probe_C7e_git_concurrency](modules/script.probe_C7e_git_concurrency/README.md) | Measure the two existing concurrent Git adapter fixture rows in isolation. | neyvia |
| [script.probe_C7e_queued](modules/script.probe_C7e_queued/README.md) | Capture actual concurrent queued reconciliation outcomes without changing owners. | neyvia |
| [script.probe_C7e_sync_recovery](modules/script.probe_C7e_sync_recovery/README.md) | Diagnose the existing C7 native recovery contract using actual REST status. | neyvia |
| [script.probe_c1cmp_repair](modules/script.probe_c1cmp_repair/README.md) | Fresh repair validation, kept separate from the frozen comparison denominator. | neyvia |
| [script.proofs-b-browser](modules/script.proofs-b-browser/README.md) | Provides script / proofs-b-browser in Neyvia. | neyvia |
| [script.proofs-c-frontend](modules/script.proofs-c-frontend/README.md) | Provides script / proofs-c-frontend in Neyvia. | neyvia |
| [script.proofs-e-chat](modules/script.proofs-e-chat/README.md) | Provides script / proofs-e-chat in Neyvia. | neyvia |
| [script.proofs-e-frontend](modules/script.proofs-e-frontend/README.md) | Provides script / proofs-e-frontend in Neyvia. | neyvia |
| [script.proofs-e-models](modules/script.proofs-e-models/README.md) | Provides script / proofs-e-models in Neyvia. | neyvia |
| [script.proofs-e-release](modules/script.proofs-e-release/README.md) | Provides script / proofs-e-release in Neyvia. | neyvia |
| [script.proofs-e-shell](modules/script.proofs-e-shell/README.md) | Provides script / proofs-e-shell in Neyvia. | neyvia |
| [script.proofs-frontend](modules/script.proofs-frontend/README.md) | Provides script / proofs-frontend in Neyvia. | neyvia |
| [script.proofs-frontend-models](modules/script.proofs-frontend-models/README.md) | Provides script / proofs-frontend-models in Neyvia. | neyvia |
| [script.proofs_e_release_child](modules/script.proofs_e_release_child/README.md) | Run the release batch's real inventory and static impact observers on owned files. | neyvia |
| [script.prove-t10-nightshift](modules/script.prove-t10-nightshift/README.md) | Provides script / prove-t10-nightshift in Neyvia. | neyvia |
| [script.prove-t5-http](modules/script.prove-t5-http/README.md) | Provides script / prove-t5-http in Neyvia. | neyvia |
| [script.prove-t5-manuals](modules/script.prove-t5-manuals/README.md) | Provides script / prove-t5-manuals in Neyvia. | neyvia |
| [script.prove_A1](modules/script.prove_A1/README.md) | Reproducible A1 real-run acceptance, no test suite and no downloads. | neyvia |
| [script.prove_A1_exports](modules/script.prove_A1_exports/README.md) | CLI generation, portable host and static phone-export real runs. | neyvia |
| [script.prove_A1_wiring](modules/script.prove_A1_wiring/README.md) | Provides script / prove_A1_wiring in Neyvia. | neyvia |
| [script.prove_C7_host](modules/script.prove_C7_host/README.md) | Exercise the registered C7 bot tools and executable manual, plus stale receipts. | neyvia |
| [script.prove_C7c_artifact_manual](modules/script.prove_C7c_artifact_manual/README.md) | Run only owned local host/receipt/artifact journeys with compact source bindings. | neyvia |
| [script.prove_C7c_checkpoints](modules/script.prove_C7c_checkpoints/README.md) | Prove real family receipts survive worker exit and refuse corrupted claims. | neyvia |
| [script.prove_C7d_admission](modules/script.prove_C7d_admission/README.md) | Real native JSON admission, refusal receipts and owned stdio user path. | neyvia |
| [script.prove_C7d_aggregation](modules/script.prove_C7d_aggregation/README.md) | Exercise the production C7 matrix gate with adversarial case receipts. | neyvia |
| [script.prove_C7d_browser](modules/script.prove_C7d_browser/README.md) | Drive production embedded controls through Neyvia's hidden WebView2 tools. | neyvia |
| [script.prove_C7d_cache_race](modules/script.prove_C7d_cache_race/README.md) | Real mission/cache calls plus unchanged-state checks at the production boundary. | neyvia |
| [script.prove_C7d_claude_idle](modules/script.prove_C7d_claude_idle/README.md) | Real hidden Claude stdio admission, queued output and deadline observations. | neyvia |
| [script.prove_C7d_http_concurrency](modules/script.prove_C7d_http_concurrency/README.md) | Observe real owned HTTP owner runs and request threads without retries. | neyvia |
| [script.prove_C7d_installer_contention](modules/script.prove_C7d_installer_contention/README.md) | Replay the existing installer family against generated owned package bytes. | neyvia |
| [script.prove_C7d_livecontrol_failure](modules/script.prove_C7d_livecontrol_failure/README.md) | Observe production owner login followed by an actual Neyvia DOM refusal. | neyvia |
| [script.prove_C7d_loopback_policy](modules/script.prove_C7d_loopback_policy/README.md) | Real loopback HTTP under retained and locked durable Settings policies. | neyvia |
| [script.prove_C7d_native_capture](modules/script.prove_C7d_native_capture/README.md) | Real stdio-worker capture with invariant-specific native adverse events. | neyvia |
| [script.prove_C7d_rendered_category](modules/script.prove_C7d_rendered_category/README.md) | Invoke the same fresh native family for one explicit adverse category. | neyvia |
| [script.prove_C7d_session_watchdog](modules/script.prove_C7d_session_watchdog/README.md) | Observe actual owned children under competing production watchdog invocations. | neyvia |
| [script.prove_C7e_atomic_replace](modules/script.prove_C7e_atomic_replace/README.md) | Generate C7 contracts over actual Windows sharing denial and durable replacement. | neyvia |
| [script.prove_C7e_authorization](modules/script.prove_C7e_authorization/README.md) | Adversarial BrowserService authorization checks; no rendered proof claim. | neyvia |
| [script.prove_C7e_compiled](modules/script.prove_C7e_compiled/README.md) | Exercise a learned C7 admission procedure through actual Neyvia stdio MCP. | neyvia |
| [script.prove_C7e_manual_marker](modules/script.prove_C7e_manual_marker/README.md) | Generate C7 cases over the real manual client effect/stop handshake. | neyvia |
| [script.prove_C7e_memory](modules/script.prove_C7e_memory/README.md) | Observe a held real reader and concurrent production memory append. | neyvia |
| [script.prove_C7e_provider_trace](modules/script.prove_C7e_provider_trace/README.md) | C7 diagnostic cases observing actual finite-peer output and adapter states. | neyvia |
| [script.prove_C7e_typed_reference](modules/script.prove_C7e_typed_reference/README.md) | Generated C7 contract cases for fixed-port manual reference admission. | neyvia |
| [script.prove_agentview](modules/script.prove_agentview/README.md) | Agent view, real journey: agents work on their own surfaces, Paul watches and steers. | neyvia |
| [script.prove_c1](modules/script.prove_c1/README.md) | Execute C1's defining adaptation/promotion/compiled replay on a real owned app. | neyvia |
| [script.prove_c10_native](modules/script.prove_c10_native/README.md) | Real native research, receipt replay, and confined refusal on owned ports. | neyvia |
| [script.prove_c10c_cache](modules/script.prove_c10c_cache/README.md) | Replay an actual native captured source through the production cache reader. | neyvia |
| [script.prove_c10c_grounding](modules/script.prove_c10c_grounding/README.md) | Real Sol challenge of a matching quote attached to a false claim (F6). | neyvia |
| [script.prove_c10d_reference_matching](modules/script.prove_c10d_reference_matching/README.md) | Audit reference matching against a real captured source, including adverse controls. | neyvia |
| [script.prove_c11_bureau](modules/script.prove_c11_bureau/README.md) | Real Bureau lifecycle and previsibility assignment, without desktop switching. | neyvia |
| [script.prove_c11_parked](modules/script.prove_c11_parked/README.md) | Real safety journey: hidden probe attempts show, move, activate and focus. | neyvia |
| [script.prove_c11_preview](modules/script.prove_c11_preview/README.md) | Actual authenticated preview HTTP -> isolated native app -> persisted effect. | neyvia |
| [script.prove_c11e_bureau_app](modules/script.prove_c11e_bureau_app/README.md) | Try Shell membership of a real new utility under previsibility containment. | neyvia |
| [script.prove_c11f](modules/script.prove_c11f/README.md) | Bind real C11f lane receipts and independently inspect saved artifacts. | neyvia |
| [script.prove_c11f_bureau](modules/script.prove_c11f_bureau/README.md) | Real hidden-first Bureau launches; never selects a desktop or sends input. | neyvia |
| [script.prove_c11f_office](modules/script.prove_c11f_office/README.md) | Real hidden Office journeys; never creates a preview or visible window. | neyvia |
| [script.prove_c11f_shell](modules/script.prove_c11f_shell/README.md) | Everyday file tasks in persistent hidden Command Prompt and PowerShell. | neyvia |
| [script.prove_c11g](modules/script.prove_c11g/README.md) | Seal actual C11g receipts, keeping failed trials and source drift visible. | neyvia |
| [script.prove_c11g_native_apps](modules/script.prove_c11g_native_apps/README.md) | Real Office tool journeys and learned grounded compiler replay, no GUI input. | neyvia |
| [script.prove_c11g_native_failure](modules/script.prove_c11g_native_failure/README.md) | Real native host refusal journey; guards remain active through final receipt. | neyvia |
| [script.prove_c11g_native_http](modules/script.prove_c11g_native_http/README.md) | Actual authenticated native-app calls across independent HTTP handler threads. | neyvia |
| [script.prove_c11g_native_registry](modules/script.prove_c11g_native_registry/README.md) | Exercise the actual registered native tool surface with retained tool receipts. | neyvia |
| [script.prove_c11g_native_surfaces](modules/script.prove_c11g_native_surfaces/README.md) | Actual MCP discovery/calls and the desktop's persistent stdio worker protocol. | neyvia |
| [script.prove_c1_contracts](modules/script.prove_c1_contracts/README.md) | Validate C1's real registered contracts and authored manual without dispatch. | neyvia |
| [script.prove_c1_http](modules/script.prove_c1_http/README.md) | Real authenticated backend/MCP discovery and no-grant refusal on an explicit C1 port. | neyvia |
| [script.prove_c1_transport](modules/script.prove_c1_transport/README.md) | Bounded live native transport diagnostic without enumerating user windows. | neyvia |
| [script.prove_c1b_native](modules/script.prove_c1b_native/README.md) | Real compiled native UI build/action/app-written effect proof, not a suite. | neyvia |
| [script.prove_c1c_native](modules/script.prove_c1c_native/README.md) | Real disposable Windows observe/action/check proof. No private app contents. | neyvia |
| [script.prove_c8_report](modules/script.prove_c8_report/README.md) | Exercise the real Inception report tool and adverse receipts on owned HTTP. | neyvia |
| [script.prove_cl](modules/script.prove_cl/README.md) | Exercise the actual stdio CL transport and production Notes/manual runner. | neyvia |
| [script.prove_cl11](modules/script.prove_cl11/README.md) | CL 1.1 acceptance journey through owned production stdio, Notes and board. | neyvia |
| [script.prove_cl_http](modules/script.prove_cl_http/README.md) | Prove the authenticated plugin/HTTP CL read path on an owned backend. | neyvia |
| [script.prove_cl_model](modules/script.prove_cl_model/README.md) | Real Codex proposal -> production CL stdio MCP -> guarded Notes effects. | neyvia |
| [script.prove_details](modules/script.prove_details/README.md) | Prove Neyvia's details library (plan 17 A2) on the running design lab. | neyvia |
| [script.prove_efficiency_log](modules/script.prove_efficiency_log/README.md) | Real A4 CLI journey, receipt-processing benchmark and fail-closed readbacks. | neyvia |
| [script.prove_fix_browser_permissions](modules/script.prove_fix_browser_permissions/README.md) | Provides script / prove_fix_browser_permissions in Neyvia. | neyvia |
| [script.prove_fix_browser_permissions_build](modules/script.prove_fix_browser_permissions_build/README.md) | Provides script / prove_fix_browser_permissions_build in Neyvia. | neyvia |
| [script.prove_fix_evolver_ui](modules/script.prove_fix_evolver_ui/README.md) | Provides script / prove_fix_evolver_ui in Neyvia. | neyvia |
| [script.prove_fix_evolver_ui_build](modules/script.prove_fix_evolver_ui_build/README.md) | Provides script / prove_fix_evolver_ui_build in Neyvia. | neyvia |
| [script.prove_fix_manual_fixtures](modules/script.prove_fix_manual_fixtures/README.md) | Run real authored manual checks through reviewed, confined local fixtures. | neyvia |
| [script.prove_fix_observer](modules/script.prove_fix_observer/README.md) | Real CL calls and Windows background value readback, scoped to disposable state. | neyvia |
| [script.prove_fix_permission](modules/script.prove_fix_permission/README.md) | Exercise the actual stdio CLI permission modes with disposable local files. | neyvia |
| [script.prove_fix_process](modules/script.prove_fix_process/README.md) | Independent live-child proof of the production Windows process query. | neyvia |
| [script.prove_fix_video](modules/script.prove_fix_video/README.md) | Provides script / prove_fix_video in Neyvia. | neyvia |
| [script.prove_ms_evolver](modules/script.prove_ms_evolver/README.md) | Register six frozen domains and score actual three-task Luna captures. | neyvia |
| [script.prove_ms_evolver_live](modules/script.prove_ms_evolver_live/README.md) | Execute each registered workflow's fresh candidate evaluator once on Luna. | neyvia |
| [script.prove_ms_http](modules/script.prove_ms_http/README.md) | Use the production study HTTP, native and desktop paths on the owned MS host. | neyvia |
| [script.prove_ms_manuals](modules/script.prove_ms_manuals/README.md) | Frozen, receipt-backed three-task paired Luna panel for each MS workflow. | neyvia |
| [script.prove_ms_study](modules/script.prove_ms_study/README.md) | Real note -> Luna/T14 -> reviewed pack proof, with retained measured usage. | neyvia |
| [script.prove_ms_study_feed](modules/script.prove_ms_study_feed/README.md) | Provides script / prove_ms_study_feed in Neyvia. | neyvia |
| [script.prove_plan_mission](modules/script.prove_plan_mission/README.md) | Real Claude builds and Codex verification through the saved mission scheduler. | neyvia |
| [script.prove_proof_admission](modules/script.prove_proof_admission/README.md) | Exercise suite-scope admission against a real temporary source file. | neyvia |
| [script.prove_proofs](modules/script.prove_proofs/README.md) | Real CLI/host/HTTP proof journey; owns and always stops only its backend. | neyvia |
| [script.prove_proofs_a_admission](modules/script.prove_proofs_a_admission/README.md) | Prove owned coverage admission refuses stale or unobserved evidence. | neyvia |
| [script.prove_proofs_b](modules/script.prove_proofs_b/README.md) | Replay the defining proof-host journey using only PROOFS-b's owned port range. | neyvia |
| [script.prove_proofs_b_admission](modules/script.prove_proofs_b_admission/README.md) | Observe fail-closed coverage admission and source revalidation using owned fixtures. | neyvia |
| [script.prove_proofs_d](modules/script.prove_proofs_d/README.md) | Real CLI/host/HTTP proof journey; owns and always stops only its backend. | neyvia |
| [script.prove_proofs_d_admission](modules/script.prove_proofs_d_admission/README.md) | Exercise coverage admission refusals without retiring any test. | neyvia |
| [script.prove_rx_cua_journey](modules/script.prove_rx_cua_journey/README.md) | Integrated computer-use journey on Neyvia's private agent desktop. | neyvia |
| [script.prove_scroll_backend](modules/script.prove_scroll_backend/README.md) | Provides script / prove_scroll_backend in Neyvia. | neyvia |
| [script.prove_scroll_boundaries](modules/script.prove_scroll_boundaries/README.md) | Provides script / prove_scroll_boundaries in Neyvia. | neyvia |
| [script.prove_scroll_manual](modules/script.prove_scroll_manual/README.md) | Provides script / prove_scroll_manual in Neyvia. | neyvia |
| [script.prove_scroll_player](modules/script.prove_scroll_player/README.md) | Production T18 browser + CL 1.1 goals against the generated running feed. | neyvia |
| [script.prove_t14_cascade](modules/script.prove_t14_cascade/README.md) | Provides script / prove_t14_cascade in Neyvia. | neyvia |
| [script.prove_t17_autopilot](modules/script.prove_t17_autopilot/README.md) | Provides script / prove_t17_autopilot in Neyvia. | neyvia |
| [script.prove_t17_controls](modules/script.prove_t17_controls/README.md) | Provides script / prove_t17_controls in Neyvia. | neyvia |
| [script.prove_t18_final](modules/script.prove_t18_final/README.md) | Final production tool calls after schema/provenance guard changes. | neyvia |
| [script.prove_t18_http](modules/script.prove_t18_http/README.md) | Actual authenticated HTTP/native registry/desktop perception round-trip. | neyvia |
| [script.prove_t18_layers](modules/script.prove_t18_layers/README.md) | Supplemental live layer coverage: T16 OS/UIA, video, cache and restart. | neyvia |
| [script.prove_t18_perception](modules/script.prove_t18_perception/README.md) | Real disposable native/browser/chart journeys, matched Luna lanes and receipts. | neyvia |
| [script.prune_C7e](modules/script.prune_C7e/README.md) | Prune task-local redundant evidence after referenced observations are sealed. | neyvia |
| [script.public_export](modules/script.public_export/README.md) | Export a pinned release file tree, never its private Git history. | neyvia |
| [script.publish_desktop_update](modules/script.publish_desktop_update/README.md) | Build, sign and publish a desktop update to the PC service's feed. | neyvia |
| [script.publish_nas_candidate](modules/script.publish_nas_candidate/README.md) | Provides script / publish_nas_candidate in Neyvia. | neyvia |
| [script.publish_nas_candidate_ssh](modules/script.publish_nas_candidate_ssh/README.md) | Invoke the transactional Neyvia candidate publisher over private NAS SSH. | neyvia |
| [script.pull_neyvia_wip_ssh](modules/script.pull_neyvia_wip_ssh/README.md) | Pull a hash-verified N-E-Y-V-I-A WIP snapshot from NAS over SSH/SFTP. | neyvia |
| [script.push_neyvia_candidate_ssh](modules/script.push_neyvia_candidate_ssh/README.md) | Provides script / push_neyvia_candidate_ssh in Neyvia. | neyvia |
| [script.push_neyvia_wip_ssh](modules/script.push_neyvia_wip_ssh/README.md) | Upload a hash-verified N-E-Y-V-I-A work-in-progress bundle without publishing. | neyvia |
| [script.read_live_limits](modules/script.read_live_limits/README.md) | Read/refresh subscription windows through installed CLIs, with no AI turn. | neyvia |
| [script.reconcile_C7e](modules/script.reconcile_C7e/README.md) | Reconcile unchanged-source local observations with freshly witnessed native UI. | neyvia |
| [script.reconcile_native_canonical](modules/script.reconcile_native_canonical/README.md) | Provides script / reconcile_native_canonical in Neyvia. | neyvia |
| [script.record_C7c](modules/script.record_C7c/README.md) | Seal a compact C7c receipt with a compressed, independently reconciled matrix. | neyvia |
| [script.record_C7d](modules/script.record_C7d/README.md) | Seal current host-run observations; hashes preserve evidence, not UI proof. | neyvia |
| [script.record_C7e](modules/script.record_C7e/README.md) | Seal the exact C7c denominator and current generated family observations. | neyvia |
| [script.record_C7e_bugs](modules/script.record_C7e_bugs/README.md) | Separate source repair commits from fixture, receipt and resource repairs. | neyvia |
| [script.record_C7e_compiled_families](modules/script.record_C7e_compiled_families/README.md) | Validate and commit each completed compiled family independently. | neyvia |
| [script.record_C7e_families](modules/script.record_C7e_families/README.md) | Commit compact proofs only for completed, current generated families. | neyvia |
| [script.record_C7e_sync_recovery](modules/script.record_C7e_sync_recovery/README.md) | Keep the six native recovery failures and their actual closure commits separate. | neyvia |
| [script.record_C7e_tokens](modules/script.record_C7e_tokens/README.md) | Record bounded numeric usage from this session and directly linked children. | neyvia |
| [script.record_authenticated_mainstreet_proof](modules/script.record_authenticated_mainstreet_proof/README.md) | Provides script / record_authenticated_mainstreet_proof in Neyvia. | neyvia |
| [script.record_c1cmp_provider](modules/script.record_c1cmp_provider/README.md) | Import a lead's real provider attempt, scored by the shared independent checker. | neyvia |
| [script.record_fluxio_proof_session](modules/script.record_fluxio_proof_session/README.md) | Provides script / record_fluxio_proof_session in Neyvia. | neyvia |
| [script.record_int2_evidence](modules/script.record_int2_evidence/README.md) | Record INT2 acceptance gates from real receipts, with missing gates explicit. | neyvia |
| [script.record_intcl_evidence](modules/script.record_intcl_evidence/README.md) | Record the integration gates from their actual local receipts. | neyvia |
| [script.record_neyvia_session](modules/script.record_neyvia_session/README.md) | Provides script / record_neyvia_session in Neyvia. | neyvia |
| [script.record_proof_coverage](modules/script.record_proof_coverage/README.md) | Provides script / record_proof_coverage in Neyvia. | neyvia |
| [script.record_runtime_performance](modules/script.record_runtime_performance/README.md) | Record bounded, build-bound Neyvia runtime performance evidence. | neyvia |
| [script.recover_C7e](modules/script.recover_C7e/README.md) | Preserve inherited C7d observations without promoting diagnostics to proof. | neyvia |
| [script.regrade_harness_comparison](modules/script.regrade_harness_comparison/README.md) | Provides script / regrade_harness_comparison in Neyvia. | neyvia |
| [script.rel.vite.config](modules/script.rel.vite.config/README.md) | Provides script / rel / vite / config in Neyvia. | neyvia |
| [script.rel_agent_manual](modules/script.rel_agent_manual/README.md) | Author the release action directory from executable CL and registered contracts. | neyvia |
| [script.rel_contract_runner](modules/script.rel_contract_runner/README.md) | Run bounded, authored CL procedure cases through this checkout's real MCP adapter. | neyvia |
| [script.rel_handoff_fixture](modules/script.rel_handoff_fixture/README.md) | Loopback owner hand-off fixture. This is not a CAPTCHA solver. | neyvia |
| [script.rel_handoff_manual](modules/script.rel_handoff_manual/README.md) | Author owner hand-off checks in the existing Connected Language manual. | neyvia |
| [script.rel_harness](modules/script.rel_harness/README.md) | Bounded local access to this checkout's Neyvia MCP adapter (REL ports only). | neyvia |
| [script.rel_image_finish](modules/script.rel_image_finish/README.md) | One bounded migration of retained Image Studio styles and fresh defaults. | neyvia |
| [script.rel_import_graph](modules/script.rel_import_graph/README.md) | Find frontend files exclusively reachable from retired shell entry points. | neyvia |
| [script.rel_obscura](modules/script.rel_obscura/README.md) | Hidden renderer through Neyvia's own Obscura engine; owned REL URLs only. | neyvia |
| [script.rel_onboarding_catalog](modules/script.rel_onboarding_catalog/README.md) | Keep feature copy in Neyvia's shared onboarding catalog. | neyvia |
| [script.rel_release_cl_checks](modules/script.rel_release_cl_checks/README.md) | Execute the authored CL release harness against bounded owned observers. | neyvia |
| [script.rel_release_contracts](modules/script.rel_release_contracts/README.md) | Author bounded first-run failure checks in the executable onboarding manual. | neyvia |
| [script.rel_retire_classic](modules/script.rel_retire_classic/README.md) | Provides script / rel_retire_classic in Neyvia. | neyvia |
| [script.rel_runtime](modules/script.rel_runtime/README.md) | Start the task-owned backend hidden, with all automatic services disabled. | neyvia |
| [script.rel_storage_observer](modules/script.rel_storage_observer/README.md) | Provides script / rel_storage_observer in Neyvia. | neyvia |
| [script.rel_tool_styles](modules/script.rel_tool_styles/README.md) | Provides script / rel_tool_styles in Neyvia. | neyvia |
| [script.rel_tour_manual](modules/script.rel_tour_manual/README.md) | Author release-tour verification in the existing executable manual. | neyvia |
| [script.release-contracts](modules/script.release-contracts/README.md) | Provides script / release-contracts in Neyvia. | neyvia |
| [script.render_manuals](modules/script.render_manuals/README.md) | Generate Markdown views from authored CL manuals and their JSON contracts. | neyvia |
| [script.repair_c4c_collection](modules/script.repair_c4c_collection/README.md) | Bounded transport repairs; preserve raw trials and repeat interrupted pairs. | neyvia |
| [script.repair_codex_model_catalog](modules/script.repair_codex_model_catalog/README.md) | Provides script / repair_codex_model_catalog in Neyvia. | neyvia |
| [script.repair_nas_opencode_go_auth](modules/script.repair_nas_opencode_go_auth/README.md) | Repair and verify the NAS OpenCode Go credential path without printing secrets. | neyvia |
| [script.report_c4c](modules/script.report_c4c/README.md) | Render the sealed, verified C4c evidence without inventing missing results. | neyvia |
| [script.resolve-neyvia-python](modules/script.resolve-neyvia-python/README.md) | Provides script / resolve-neyvia-python in Neyvia. | neyvia |
| [script.resolve_release_python](modules/script.resolve_release_python/README.md) | Resolve a prepared dependency environment without mutating a sealed release. | neyvia |
| [script.resume_c4c_transport](modules/script.resume_c4c_transport/README.md) | Repeat both arms of the lock-interrupted pair; re-review repaired metadata. | neyvia |
| [script.retain_C7_evidence](modules/script.retain_C7_evidence/README.md) | Deduplicate historical C7 scratch while preserving receipt-referenced files. | neyvia |
| [script.retain_C7e_compiled](modules/script.retain_C7e_compiled/README.md) | Independently verify and retain selected actual compiled family traces. | neyvia |
| [script.retry_c10c_judges](modules/script.retry_c10c_judges/README.md) | Retry only failed independent judges, preserving their original receipts. | neyvia |
| [script.reuse_c10c_comparator](modules/script.reuse_c10c_comparator/README.md) | Copy complete real comparator receipts byte-for-byte, without printing answers. | neyvia |
| [script.review_C7_receipts](modules/script.review_C7_receipts/README.md) | Independently verify campaign artifacts, source binding and paired repairs. | neyvia |
| [script.review_C7b_receipts](modules/script.review_C7b_receipts/README.md) | Independently reconcile the C7b real-run receipt with its frozen baseline. | neyvia |
| [script.review_c1cmp](modules/script.review_c1cmp/README.md) | Re-read the frozen comparison receipts and preserve compact artifact proof. | neyvia |
| [script.review_proofs_d](modules/script.review_proofs_d/README.md) | Preserve every assigned original case's obligations and migration frontier. | neyvia |
| [script.review_route_trust_sampling_closeouts](modules/script.review_route_trust_sampling_closeouts/README.md) | Review route-trust sampling closeouts and wait for terminal missions. | neyvia |
| [script.run_C7e_family](modules/script.run_C7e_family/README.md) | Run selected existing generated builders for focused repair and evidence. | neyvia |
| [script.run_C7e_family_pool](modules/script.run_C7e_family_pool/README.md) | Bounded compiled-family replay on independent private Neyvia desktops. | neyvia |
| [script.run_C7e_family_worker](modules/script.run_C7e_family_worker/README.md) | Run one compiled family contract, logging only into its owned evidence area. | neyvia |
| [script.run_C7e_local_worker](modules/script.run_C7e_local_worker/README.md) | Log one existing C7 fixture family on its owned private desktop. | neyvia |
| [script.run_autopilot](modules/script.run_autopilot/README.md) | Run or inspect autopilot through the production Native permission gateway. | neyvia |
| [script.run_c10_research](modules/script.run_c10_research/README.md) | Resume real frozen-panel research arms; results remain separate from prompts. | neyvia |
| [script.run_c11_cohort](modules/script.run_c11_cohort/README.md) | Run the frozen C1 action cohort exclusively on private agent desktops. | neyvia |
| [script.run_c1_comparison](modules/script.run_c1_comparison/README.md) | Verify and execute the frozen C1 panel without changing its manifest. | neyvia |
| [script.run_c4_cohort](modules/script.run_c4_cohort/README.md) | Bounded two-worker cohort; subprocesses isolate environment and notes roots. | neyvia |
| [script.run_c4c](modules/script.run_c4c/README.md) | Frozen paired 18-task C4 ablation; no keys, native launches or public state. | neyvia |
| [script.run_c8_inception](modules/script.run_c8_inception/README.md) | Run a pinned scratch Neyvia against this candidate, with a strict release gate. | neyvia |
| [script.run_c8d](modules/script.run_c8d/README.md) | Run the complete authored C8 catalog in isolated, parallel headless batches. | neyvia |
| [script.run_c9b](modules/script.run_c9b/README.md) | Real Luna replay and source-bound C9b feedback evidence (never pytest). | neyvia |
| [script.run_c9c_judge](modules/script.run_c9c_judge/README.md) | Real rubric/LOO calibration with hidden Neyvia Search/WebView2 captures. | neyvia |
| [script.run_cl_efficient](modules/script.run_cl_efficient/README.md) | Run the bounded small-model CL host against a selected disposable workspace. | neyvia |
| [script.run_controlled_ai_safety_review](modules/script.run_controlled_ai_safety_review/README.md) | Provides script / run_controlled_ai_safety_review in Neyvia. | neyvia |
| [script.run_controlled_redteam_proof](modules/script.run_controlled_redteam_proof/README.md) | Provides script / run_controlled_redteam_proof in Neyvia. | neyvia |
| [script.run_grant_agent_cli](modules/script.run_grant_agent_cli/README.md) | Provides script / run_grant_agent_cli in Neyvia. | neyvia |
| [script.run_html_site_benchmark](modules/script.run_html_site_benchmark/README.md) | Provides script / run_html_site_benchmark in Neyvia. | neyvia |
| [script.run_live_harness_comparison](modules/script.run_live_harness_comparison/README.md) | Run the frozen read-only protocol across every eligible live NAS harness. | neyvia |
| [script.run_live_native_harness_proof](modules/script.run_live_native_harness_proof/README.md) | Run one authenticated, exact-route Neyvia Native proof without printing secrets. | neyvia |
| [script.run_live_native_harness_quality](modules/script.run_live_native_harness_quality/README.md) | Run the frozen Neyvia Native quality ladder through one exact live route. | neyvia |
| [script.run_manual_first_agents](modules/script.run_manual_first_agents/README.md) | Run authorized real Codex MCP and Claude plugin acceptance journeys in scratch roots. | neyvia |
| [script.run_nas_runtime_doctor_ssh](modules/script.run_nas_runtime_doctor_ssh/README.md) | Run the checked-in runtime doctor on the NAS and preserve its JSON proof. | neyvia |
| [script.run_neyvia_crash_campaign](modules/script.run_neyvia_crash_campaign/README.md) | Provides script / run_neyvia_crash_campaign in Neyvia. | neyvia |
| [script.run_route_trust_sampling_missions](modules/script.run_route_trust_sampling_missions/README.md) | Launch route-trust sampling missions safely against Hermes. | neyvia |
| [script.run_t13_evolution](modules/script.run_t13_evolution/README.md) | Run independent real Luna trials in the same workspace DB as the app. | neyvia |
| [script.run_t3_vite](modules/script.run_t3_vite/README.md) | Provides script / run_t3_vite in Neyvia. | neyvia |
| [script.run_t5_model_comparison](modules/script.run_t5_model_comparison/README.md) | Real, matched Claude CLI evaluation against production Notes MCP tools. | neyvia |
| [script.run_t7_luna](modules/script.run_t7_luna/README.md) | Provides script / run_t7_luna in Neyvia. | neyvia |
| [script.run_web_backend](modules/script.run_web_backend/README.md) | Provides script / run_web_backend in Neyvia. | neyvia |
| [script.rx_admit_engine](modules/script.rx_admit_engine/README.md) | Admit the rebuilt C2h Obscura engine from its durable D: home. | neyvia |
| [script.rx_browser_gate](modules/script.rx_browser_gate/README.md) | Release browser gate on the admitted Obscura engine (track rx-browser). | neyvia |
| [script.rx_browser_manual](modules/script.rx_browser_manual/README.md) | Author the admitted-engine contract in the browser CL manual (release browser gate). | neyvia |
| [script.rx_build_obscura_c2h](modules/script.rx_build_obscura_c2h/README.md) | Rebuild the source-admitted C2h Obscura engine on D and stage it durably. | neyvia |
| [script.rx_cua_readback](modules/script.rx_cua_readback/README.md) | Independent, read-only Win32 readback of an agent-desktop window. | neyvia |
| [script.rx_research_gateway](modules/script.rx_research_gateway/README.md) | Prove the research manual through a fresh Neyvia gateway (stdio MCP). | neyvia |
| [script.rx_research_journey](modules/script.rx_research_journey/README.md) | Time and check full research journeys through neyvia.research.journey. | neyvia |
| [script.score_c10_research](modules/script.score_c10_research/README.md) | Score frozen C10 arms blindly against independently fetched citation evidence. | neyvia |
| [script.scroll_math_validate](modules/script.scroll_math_validate/README.md) | Provides script / scroll_math_validate in Neyvia. | neyvia |
| [script.scroll_pack_probe](modules/script.scroll_pack_probe/README.md) | JSON stdin adapter used by the Node parser acceptance check (not pytest). | neyvia |
| [script.seal_A3B](modules/script.seal_A3B/README.md) | Seal observed Scroll Study artifacts and emit A4's receipt-backed result specs. | neyvia |
| [script.seal_C7_final](modules/script.seal_C7_final/README.md) | Seal a fresh complete C7 campaign and the three resumed compiled families. | neyvia |
| [script.seal_C7_recovered](modules/script.seal_C7_recovered/README.md) | Seal recovered real C7 runs without inventing interrupted compiled replays. | neyvia |
| [script.seal_C7e_deadline](modules/script.seal_C7e_deadline/README.md) | Write an honest incomplete C7e deadline receipt from sealed family work. | neyvia |
| [script.seal_c1](modules/script.seal_c1/README.md) | Archive exact C1 observations and prepare a receipt-backed ledger input. | neyvia |
| [script.seal_c10_research](modules/script.seal_c10_research/README.md) | Bind completed C10 pairs, preserve small public proof archives, append a result. | neyvia |
| [script.seal_c11_receipt](modules/script.seal_c11_receipt/README.md) | Seal small C11 receipts and recompute scores from dispatched actions only. | neyvia |
| [script.seal_c1b](modules/script.seal_c1b/README.md) | Seal exact current-source/native receipts without upgrading blocked gates. | neyvia |
| [script.seal_c2](modules/script.seal_c2/README.md) | Verify retained production runs, derive their metrics, and append the C2 ledger. | neyvia |
| [script.seal_c2b](modules/script.seal_c2b/README.md) | Independently verify C2b raw receipts and append scoped research results. | neyvia |
| [script.seal_c2c](modules/script.seal_c2c/README.md) | Verify retained live C2c receipts, recompute metrics and append scoped results. | neyvia |
| [script.seal_c2d](modules/script.seal_c2d/README.md) | Provides script / seal_c2d in Neyvia. | neyvia |
| [script.seal_c2f](modules/script.seal_c2f/README.md) | Provides script / seal_c2f in Neyvia. | neyvia |
| [script.seal_c4](modules/script.seal_c4/README.md) | Seal real C4 receipts, recalculate provider usage, and append the research ledger. | neyvia |
| [script.seal_c4b](modules/script.seal_c4b/README.md) | Seal a bounded paired C4b panel, retaining raw provider events and failures. | neyvia |
| [script.seal_c4c](modules/script.seal_c4c/README.md) | Verify real provider usage/artifact bindings, compute CIs and seal C4c. | neyvia |
| [script.seal_c8d](modules/script.seal_c8d/README.md) | Derive the reviewed C8 release report without changing any raw run receipt. | neyvia |
| [script.seal_c8e](modules/script.seal_c8e/README.md) | Add a source-bound C8e review without changing immutable journey outcomes. | neyvia |
| [script.seal_c9b](modules/script.seal_c9b/README.md) | Seal bounded C9b evidence; include no runtime databases or account stores. | neyvia |
| [script.seal_c9c](modules/script.seal_c9c/README.md) | Seal named sanitized proof artifacts; never traverse account/private stores. | neyvia |
| [script.seal_fix2](modules/script.seal_fix2/README.md) | Validate retained real-call receipts and seal FIX2 without hiding release failures. | neyvia |
| [script.seal_fixcl](modules/script.seal_fixcl/README.md) | Seal independently inspectable FIXCL receipts without promoting their scope. | neyvia |
| [script.seal_fixcl2](modules/script.seal_fixcl2/README.md) | Bind FIXCL2 real-run receipts, current coverage and bounded AUD4 updates. | neyvia |
| [script.seal_fixcl3](modules/script.seal_fixcl3/README.md) | Seal current real-run FIXCL3 evidence without promoting partial mechanisms. | neyvia |
| [script.seal_fixcl4](modules/script.seal_fixcl4/README.md) | Seal current FIXCL4 evidence, including every remaining local/external gap. | neyvia |
| [script.seal_fixcl5](modules/script.seal_fixcl5/README.md) | Seal current FIXCL5 evidence, including every remaining local/external gap. | neyvia |
| [script.seal_fixcl6](modules/script.seal_fixcl6/README.md) | Seal independently checked FIXCL6 evidence, retaining failure boundaries. | neyvia |
| [script.seal_fixcl7](modules/script.seal_fixcl7/README.md) | Retain current FIXCL7 evidence and costs without promoting partial goals. | neyvia |
| [script.seal_t13_evidence](modules/script.seal_t13_evidence/README.md) | Provides script / seal_t13_evidence in Neyvia. | neyvia |
| [script.seal_t22_evidence](modules/script.seal_t22_evidence/README.md) | Provides script / seal_t22_evidence in Neyvia. | neyvia |
| [script.serve-release-ui-proof](modules/script.serve-release-ui-proof/README.md) | Disposable authenticated release backend. Arguments: candidate directory, new proof workspace. | neyvia |
| [script.setup_c11_bureau](modules/script.setup_c11_bureau/README.md) | Provides script / setup_c11_bureau in Neyvia. | neyvia |
| [script.setup_nas_https](modules/script.setup_nas_https/README.md) | Provides script / setup_nas_https in Neyvia. | neyvia |
| [script.setup_neyvia_ecosystem](modules/script.setup_neyvia_ecosystem/README.md) | Provides script / setup_neyvia_ecosystem in Neyvia. | neyvia |
| [script.setup_t7_embeddings](modules/script.setup_t7_embeddings/README.md) | Fetch one pinned, bounded embedding model; never install packages. | neyvia |
| [script.sitecustomize](modules/script.sitecustomize/README.md) | One-shot reconciliation hook for the Native breakthrough sealing run. | neyvia |
| [script.spike_c11_desktop](modules/script.spike_c11_desktop/README.md) | Real C11 desktop feasibility, without ever showing an input-desktop app. | neyvia |
| [script.stage_neyvia_crashproof_candidate](modules/script.stage_neyvia_crashproof_candidate/README.md) | Provides script / stage_neyvia_crashproof_candidate in Neyvia. | neyvia |
| [script.stage_neyvia_reconciled_candidate](modules/script.stage_neyvia_reconciled_candidate/README.md) | Provides script / stage_neyvia_reconciled_candidate in Neyvia. | neyvia |
| [script.stage_neyvia_wip_snapshot](modules/script.stage_neyvia_wip_snapshot/README.md) | Stage a safe, complete Neyvia source workspace for immutable NAS transfer. | neyvia |
| [script.stage_portable_python](modules/script.stage_portable_python/README.md) | Copy an explicitly selected installed Python and its backend dependency closure. | neyvia |
| [script.start-neyvia-controller](modules/script.start-neyvia-controller/README.md) | Provides script / start-neyvia-controller in Neyvia. | neyvia |
| [script.start_fluxio_backend](modules/script.start_fluxio_backend/README.md) | Provides script / start_fluxio_backend in Neyvia. | neyvia |
| [script.start_fluxio_services](modules/script.start_fluxio_services/README.md) | Provides script / start_fluxio_services in Neyvia. | neyvia |
| [script.start_t7_backend](modules/script.start_t7_backend/README.md) | Provides script / start_t7_backend in Neyvia. | neyvia |
| [script.study_docs](modules/script.study_docs/README.md) | Create, build, check, render and compare study documents on the neyvia-study class. | neyvia |
| [script.summarize_A1](modules/script.summarize_A1/README.md) | Verify and bind the A1 real-call receipts to reviewable source/artifact bytes. | neyvia |
| [script.summarize_c10c_experiments](modules/script.summarize_c10c_experiments/README.md) | Preserve isolated post-study experiments without promoting their results. | neyvia |
| [script.summarize_fix_sidebar_ui](modules/script.summarize_fix_sidebar_ui/README.md) | Provides script / summarize_fix_sidebar_ui in Neyvia. | neyvia |
| [script.summarize_proofs_b](modules/script.summarize_proofs_b/README.md) | Audit Paul's exact PROOFS-b share and publish a compact evidence receipt. | neyvia |
| [script.sync_nas_mission_detail_status](modules/script.sync_nas_mission_detail_status/README.md) | Sync NAS mission-detail status receipts. | neyvia |
| [script.sync_nas_system_audit](modules/script.sync_nas_system_audit/README.md) | Sync non-secret NAS system audit evidence into the local control root. | neyvia |
| [script.t14_acceptance](modules/script.t14_acceptance/README.md) | Production acceptance journeys and explicit disposable-state fault injection. | neyvia |
| [script.t18_eval_mcp](modules/script.t18_eval_mcp/README.md) | Matched Luna evaluation bridge; only the disposable task target is exposed. | neyvia |
| [script.theme_rain_probe](modules/script.theme_rain_probe/README.md) | Matrix rain proof (plan 29 section 5): frame cost, pause rules and a frame, in Neyvia's Obscura engine. | neyvia |
| [script.theme_shots](modules/script.theme_shots/README.md) | Theme proof: every theme on the main surfaces, at 1440 and 390, rendered in Neyvia's Obscura engine. | neyvia |
| [script.trash_c9c_builds](modules/script.trash_c9c_builds/README.md) | Recycle only the two temporary build folders created by this C9c task. | neyvia |
| [script.uifix2_contracts](modules/script.uifix2_contracts/README.md) | Executable UIFIX2 manual procedures: the private-beta UI repairs, checked through the real code. | neyvia |
| [script.unblock_codex_network](modules/script.unblock_codex_network/README.md) | Provides script / unblock_codex_network in Neyvia. | neyvia |
| [script.update_c11g_manual](modules/script.update_c11g_manual/README.md) | Refresh only computer-use guidance; compile its authored CL artifact. | neyvia |
| [script.usage_film_shot](modules/script.usage_film_shot/README.md) | Trailer captures of the Usage pane, full screen (no sidebar, so no chat titles), Forest dark, 1920x1080 at device scale 2. | neyvia |
| [script.usage_shots](modules/script.usage_shots/README.md) | Usage pane proof: headless Playwright Chromium on a fixtures Vite build, the endpoint answered with this PC's real report. | neyvia |
| [script.validate_agent_submission_receipt](modules/script.validate_agent_submission_receipt/README.md) | Validate an immutable Neyvia agent-submission receipt without source writes. | neyvia |
| [script.vendor-research.cua-driver.discovery-proof](modules/script.vendor-research.cua-driver.discovery-proof/README.md) | Provides script / vendor-research / cua-driver / discovery-proof in Neyvia. | neyvia |
| [script.vendor-research.cua-driver.live-tools](modules/script.vendor-research.cua-driver.live-tools/README.md) | Provides script / vendor-research / cua-driver / live-tools in Neyvia. | neyvia |
| [script.vendor-research.cua-driver.manifest](modules/script.vendor-research.cua-driver.manifest/README.md) | Provides script / vendor-research / cua-driver / manifest in Neyvia. | neyvia |
| [script.vendor-research.cua-driver.provenance](modules/script.vendor-research.cua-driver.provenance/README.md) | Provides script / vendor-research / cua-driver / provenance in Neyvia. | neyvia |
| [script.vendor-research.cua-driver.windows-tools](modules/script.vendor-research.cua-driver.windows-tools/README.md) | Provides script / vendor-research / cua-driver / windows-tools in Neyvia. | neyvia |
| [script.verify-adaptive-work](modules/script.verify-adaptive-work/README.md) | Provides script / verify-adaptive-work in Neyvia. | neyvia |
| [script.verify-agent-collaboration](modules/script.verify-agent-collaboration/README.md) | Provides script / verify-agent-collaboration in Neyvia. | neyvia |
| [script.verify-agent-failure-recovery](modules/script.verify-agent-failure-recovery/README.md) | Provides script / verify-agent-failure-recovery in Neyvia. | neyvia |
| [script.verify-agent-route-boundaries](modules/script.verify-agent-route-boundaries/README.md) | Provides script / verify-agent-route-boundaries in Neyvia. | neyvia |
| [script.verify-ambient](modules/script.verify-ambient/README.md) | Provides script / verify-ambient in Neyvia. | neyvia |
| [script.verify-app-factory-semantics](modules/script.verify-app-factory-semantics/README.md) | Provides script / verify-app-factory-semantics in Neyvia. | neyvia |
| [script.verify-ask-tool-recovery](modules/script.verify-ask-tool-recovery/README.md) | Provides script / verify-ask-tool-recovery in Neyvia. | neyvia |
| [script.verify-backend-deliverables](modules/script.verify-backend-deliverables/README.md) | Provides script / verify-backend-deliverables in Neyvia. | neyvia |
| [script.verify-behavioral-experiments](modules/script.verify-behavioral-experiments/README.md) | Provides script / verify-behavioral-experiments in Neyvia. | neyvia |
| [script.verify-capability-routes](modules/script.verify-capability-routes/README.md) | Provides script / verify-capability-routes in Neyvia. | neyvia |
| [script.verify-chat-completion-push](modules/script.verify-chat-completion-push/README.md) | Provides script / verify-chat-completion-push in Neyvia. | neyvia |
| [script.verify-chat-lifecycle-bridge](modules/script.verify-chat-lifecycle-bridge/README.md) | Provides script / verify-chat-lifecycle-bridge in Neyvia. | neyvia |
| [script.verify-chat-no-deadline-cancellation](modules/script.verify-chat-no-deadline-cancellation/README.md) | Provides script / verify-chat-no-deadline-cancellation in Neyvia. | neyvia |
| [script.verify-chat-snapshot-integrity](modules/script.verify-chat-snapshot-integrity/README.md) | Provides script / verify-chat-snapshot-integrity in Neyvia. | neyvia |
| [script.verify-claude-system-prompt-file](modules/script.verify-claude-system-prompt-file/README.md) | Provides script / verify-claude-system-prompt-file in Neyvia. | neyvia |
| [script.verify-codex-skill-access](modules/script.verify-codex-skill-access/README.md) | Provides script / verify-codex-skill-access in Neyvia. | neyvia |
| [script.verify-collaboration-continuation](modules/script.verify-collaboration-continuation/README.md) | Provides script / verify-collaboration-continuation in Neyvia. | neyvia |
| [script.verify-complete-context](modules/script.verify-complete-context/README.md) | Provides script / verify-complete-context in Neyvia. | neyvia |
| [script.verify-connected-context](modules/script.verify-connected-context/README.md) | Provides script / verify-connected-context in Neyvia. | neyvia |
| [script.verify-connected-controls-backend](modules/script.verify-connected-controls-backend/README.md) | Provides script / verify-connected-controls-backend in Neyvia. | neyvia |
| [script.verify-context-policy](modules/script.verify-context-policy/README.md) | Provides script / verify-context-policy in Neyvia. | neyvia |
| [script.verify-context-recovery](modules/script.verify-context-recovery/README.md) | Provides script / verify-context-recovery in Neyvia. | neyvia |
| [script.verify-context-window](modules/script.verify-context-window/README.md) | Provides script / verify-context-window in Neyvia. | neyvia |
| [script.verify-contextual-learning](modules/script.verify-contextual-learning/README.md) | Provides script / verify-contextual-learning in Neyvia. | neyvia |
| [script.verify-conversation-archive](modules/script.verify-conversation-archive/README.md) | Provides script / verify-conversation-archive in Neyvia. | neyvia |
| [script.verify-creative-tools](modules/script.verify-creative-tools/README.md) | Provides script / verify-creative-tools in Neyvia. | neyvia |
| [script.verify-desktop-backend-deadlines](modules/script.verify-desktop-backend-deadlines/README.md) | Provides script / verify-desktop-backend-deadlines in Neyvia. | neyvia |
| [script.verify-desktop-capability-fastpaths](modules/script.verify-desktop-capability-fastpaths/README.md) | Provides script / verify-desktop-capability-fastpaths in Neyvia. | neyvia |
| [script.verify-desktop-controller](modules/script.verify-desktop-controller/README.md) | Provides script / verify-desktop-controller in Neyvia. | neyvia |
| [script.verify-desktop-controller-http](modules/script.verify-desktop-controller-http/README.md) | Provides script / verify-desktop-controller-http in Neyvia. | neyvia |
| [script.verify-desktop-controller-state](modules/script.verify-desktop-controller-state/README.md) | Provides script / verify-desktop-controller-state in Neyvia. | neyvia |
| [script.verify-desktop-state-fastpaths](modules/script.verify-desktop-state-fastpaths/README.md) | Provides script / verify-desktop-state-fastpaths in Neyvia. | neyvia |
| [script.verify-desktop-workspace-bootstrap](modules/script.verify-desktop-workspace-bootstrap/README.md) | Provides script / verify-desktop-workspace-bootstrap in Neyvia. | neyvia |
| [script.verify-experience-learning](modules/script.verify-experience-learning/README.md) | Provides script / verify-experience-learning in Neyvia. | neyvia |
| [script.verify-experiment-studio](modules/script.verify-experiment-studio/README.md) | Provides script / verify-experiment-studio in Neyvia. | neyvia |
| [script.verify-experimental-quality](modules/script.verify-experimental-quality/README.md) | Provides script / verify-experimental-quality in Neyvia. | neyvia |
| [script.verify-external-harness-permissions](modules/script.verify-external-harness-permissions/README.md) | Provides script / verify-external-harness-permissions in Neyvia. | neyvia |
| [script.verify-fixwave-intent](modules/script.verify-fixwave-intent/README.md) | Provides script / verify-fixwave-intent in Neyvia. | neyvia |
| [script.verify-fixwave-mcp](modules/script.verify-fixwave-mcp/README.md) | Provides script / verify-fixwave-mcp in Neyvia. | neyvia |
| [script.verify-fixwave-onboarding](modules/script.verify-fixwave-onboarding/README.md) | Provides script / verify-fixwave-onboarding in Neyvia. | neyvia |
| [script.verify-follow-local-only](modules/script.verify-follow-local-only/README.md) | Provides script / verify-follow-local-only in Neyvia. | neyvia |
| [script.verify-goal-loop](modules/script.verify-goal-loop/README.md) | Provides script / verify-goal-loop in Neyvia. | neyvia |
| [script.verify-goal-pause](modules/script.verify-goal-pause/README.md) | Provides script / verify-goal-pause in Neyvia. | neyvia |
| [script.verify-goal-state](modules/script.verify-goal-state/README.md) | Provides script / verify-goal-state in Neyvia. | neyvia |
| [script.verify-grounded-manuals](modules/script.verify-grounded-manuals/README.md) | Provides script / verify-grounded-manuals in Neyvia. | neyvia |
| [script.verify-handoff-evidence](modules/script.verify-handoff-evidence/README.md) | Provides script / verify-handoff-evidence in Neyvia. | neyvia |
| [script.verify-harness-actions-live](modules/script.verify-harness-actions-live/README.md) | Provides script / verify-harness-actions-live in Neyvia. | neyvia |
| [script.verify-harness-batches](modules/script.verify-harness-batches/README.md) | Provides script / verify-harness-batches in Neyvia. | neyvia |
| [script.verify-history-payload](modules/script.verify-history-payload/README.md) | Provides script / verify-history-payload in Neyvia. | neyvia |
| [script.verify-improvement-lab](modules/script.verify-improvement-lab/README.md) | Provides script / verify-improvement-lab in Neyvia. | neyvia |
| [script.verify-innovation-tools](modules/script.verify-innovation-tools/README.md) | Provides script / verify-innovation-tools in Neyvia. | neyvia |
| [script.verify-installed-programs](modules/script.verify-installed-programs/README.md) | Provides script / verify-installed-programs in Neyvia. | neyvia |
| [script.verify-installed-programs-http](modules/script.verify-installed-programs-http/README.md) | Provides script / verify-installed-programs-http in Neyvia. | neyvia |
| [script.verify-intent-actions](modules/script.verify-intent-actions/README.md) | Provides script / verify-intent-actions in Neyvia. | neyvia |
| [script.verify-intent-browser-integration](modules/script.verify-intent-browser-integration/README.md) | Provides script / verify-intent-browser-integration in Neyvia. | neyvia |
| [script.verify-living-applications](modules/script.verify-living-applications/README.md) | Provides script / verify-living-applications in Neyvia. | neyvia |
| [script.verify-main-chat-continuity](modules/script.verify-main-chat-continuity/README.md) | Provides script / verify-main-chat-continuity in Neyvia. | neyvia |
| [script.verify-managed-action-recovery](modules/script.verify-managed-action-recovery/README.md) | Provides script / verify-managed-action-recovery in Neyvia. | neyvia |
| [script.verify-manual-depth](modules/script.verify-manual-depth/README.md) | Provides script / verify-manual-depth in Neyvia. | neyvia |
| [script.verify-manual-first](modules/script.verify-manual-first/README.md) | Provides script / verify-manual-first in Neyvia. | neyvia |
| [script.verify-mcp-jsonl](modules/script.verify-mcp-jsonl/README.md) | Provides script / verify-mcp-jsonl in Neyvia. | neyvia |
| [script.verify-message-rendering](modules/script.verify-message-rendering/README.md) | Provides script / verify-message-rendering in Neyvia. | neyvia |
| [script.verify-mission-continuation](modules/script.verify-mission-continuation/README.md) | Provides script / verify-mission-continuation in Neyvia. | neyvia |
| [script.verify-native-access](modules/script.verify-native-access/README.md) | Provides script / verify-native-access in Neyvia. | neyvia |
| [script.verify-native-action-recovery](modules/script.verify-native-action-recovery/README.md) | Provides script / verify-native-action-recovery in Neyvia. | neyvia |
| [script.verify-native-capability-discovery](modules/script.verify-native-capability-discovery/README.md) | Provides script / verify-native-capability-discovery in Neyvia. | neyvia |
| [script.verify-native-codex-access](modules/script.verify-native-codex-access/README.md) | Provides script / verify-native-codex-access in Neyvia. | neyvia |
| [script.verify-native-command-access](modules/script.verify-native-command-access/README.md) | Provides script / verify-native-command-access in Neyvia. | neyvia |
| [script.verify-native-commands](modules/script.verify-native-commands/README.md) | Provides script / verify-native-commands in Neyvia. | neyvia |
| [script.verify-native-model-behavior-diagnostic](modules/script.verify-native-model-behavior-diagnostic/README.md) | Provides script / verify-native-model-behavior-diagnostic in Neyvia. | neyvia |
| [script.verify-native-preview-taste-path](modules/script.verify-native-preview-taste-path/README.md) | Provides script / verify-native-preview-taste-path in Neyvia. | neyvia |
| [script.verify-native-stream-fixture](modules/script.verify-native-stream-fixture/README.md) | Provides script / verify-native-stream-fixture in Neyvia. | neyvia |
| [script.verify-native-tool-discovery](modules/script.verify-native-tool-discovery/README.md) | Provides script / verify-native-tool-discovery in Neyvia. | neyvia |
| [script.verify-native-workspace-write](modules/script.verify-native-workspace-write/README.md) | Provides script / verify-native-workspace-write in Neyvia. | neyvia |
| [script.verify-opencode-recovery](modules/script.verify-opencode-recovery/README.md) | Provides script / verify-opencode-recovery in Neyvia. | neyvia |
| [script.verify-operation-adapter](modules/script.verify-operation-adapter/README.md) | Provides script / verify-operation-adapter in Neyvia. | neyvia |
| [script.verify-operation-adapters-expanded](modules/script.verify-operation-adapters-expanded/README.md) | Provides script / verify-operation-adapters-expanded in Neyvia. | neyvia |
| [script.verify-operation-gateway](modules/script.verify-operation-gateway/README.md) | Provides script / verify-operation-gateway in Neyvia. | neyvia |
| [script.verify-orchestration-runtime](modules/script.verify-orchestration-runtime/README.md) | Provides script / verify-orchestration-runtime in Neyvia. | neyvia |
| [script.verify-perception-frames](modules/script.verify-perception-frames/README.md) | Provides script / verify-perception-frames in Neyvia. | neyvia |
| [script.verify-personalization-laya](modules/script.verify-personalization-laya/README.md) | Provides script / verify-personalization-laya in Neyvia. | neyvia |
| [script.verify-preview-search](modules/script.verify-preview-search/README.md) | Provides script / verify-preview-search in Neyvia. | neyvia |
| [script.verify-product-activity-ui](modules/script.verify-product-activity-ui/README.md) | Provides script / verify-product-activity-ui in Neyvia. | neyvia |
| [script.verify-product-polish-ui](modules/script.verify-product-polish-ui/README.md) | Provides script / verify-product-polish-ui in Neyvia. | neyvia |
| [script.verify-product-startup-ui](modules/script.verify-product-startup-ui/README.md) | Provides script / verify-product-startup-ui in Neyvia. | neyvia |
| [script.verify-product-studios-ui](modules/script.verify-product-studios-ui/README.md) | Provides script / verify-product-studios-ui in Neyvia. | neyvia |
| [script.verify-project-downloads-http](modules/script.verify-project-downloads-http/README.md) | Provides script / verify-project-downloads-http in Neyvia. | neyvia |
| [script.verify-project-files](modules/script.verify-project-files/README.md) | Provides script / verify-project-files in Neyvia. | neyvia |
| [script.verify-proof-capsules](modules/script.verify-proof-capsules/README.md) | Provides script / verify-proof-capsules in Neyvia. | neyvia |
| [script.verify-provider-model-catalog](modules/script.verify-provider-model-catalog/README.md) | Provides script / verify-provider-model-catalog in Neyvia. | neyvia |
| [script.verify-provider-reconnect](modules/script.verify-provider-reconnect/README.md) | Provides script / verify-provider-reconnect in Neyvia. | neyvia |
| [script.verify-recovery-objects](modules/script.verify-recovery-objects/README.md) | Provides script / verify-recovery-objects in Neyvia. | neyvia |
| [script.verify-release-environment](modules/script.verify-release-environment/README.md) | Provides script / verify-release-environment in Neyvia. | neyvia |
| [script.verify-runtime-diagnostics](modules/script.verify-runtime-diagnostics/README.md) | Provides script / verify-runtime-diagnostics in Neyvia. | neyvia |
| [script.verify-runtime-prompt-dispatch](modules/script.verify-runtime-prompt-dispatch/README.md) | Provides script / verify-runtime-prompt-dispatch in Neyvia. | neyvia |
| [script.verify-scoped-agent-prompts](modules/script.verify-scoped-agent-prompts/README.md) | Provides script / verify-scoped-agent-prompts in Neyvia. | neyvia |
| [script.verify-semantic-boundaries](modules/script.verify-semantic-boundaries/README.md) | Provides script / verify-semantic-boundaries in Neyvia. | neyvia |
| [script.verify-semantic-dispatch](modules/script.verify-semantic-dispatch/README.md) | Provides script / verify-semantic-dispatch in Neyvia. | neyvia |
| [script.verify-semantic-http](modules/script.verify-semantic-http/README.md) | Provides script / verify-semantic-http in Neyvia. | neyvia |
| [script.verify-semantic-missions](modules/script.verify-semantic-missions/README.md) | Provides script / verify-semantic-missions in Neyvia. | neyvia |
| [script.verify-semantic-tools](modules/script.verify-semantic-tools/README.md) | Provides script / verify-semantic-tools in Neyvia. | neyvia |
| [script.verify-session-compaction](modules/script.verify-session-compaction/README.md) | Provides script / verify-session-compaction in Neyvia. | neyvia |
| [script.verify-shared-environments](modules/script.verify-shared-environments/README.md) | Provides script / verify-shared-environments in Neyvia. | neyvia |
| [script.verify-situation-http](modules/script.verify-situation-http/README.md) | Provides script / verify-situation-http in Neyvia. | neyvia |
| [script.verify-situation-interface](modules/script.verify-situation-interface/README.md) | Provides script / verify-situation-interface in Neyvia. | neyvia |
| [script.verify-situation-journeys](modules/script.verify-situation-journeys/README.md) | Provides script / verify-situation-journeys in Neyvia. | neyvia |
| [script.verify-situation-live-evidence](modules/script.verify-situation-live-evidence/README.md) | Provides script / verify-situation-live-evidence in Neyvia. | neyvia |
| [script.verify-skill-import](modules/script.verify-skill-import/README.md) | Provides script / verify-skill-import in Neyvia. | neyvia |
| [script.verify-skill-import-bridge](modules/script.verify-skill-import-bridge/README.md) | Provides script / verify-skill-import-bridge in Neyvia. | neyvia |
| [script.verify-storage-quota](modules/script.verify-storage-quota/README.md) | Provides script / verify-storage-quota in Neyvia. | neyvia |
| [script.verify-t12](modules/script.verify-t12/README.md) | Provides script / verify-t12 in Neyvia. | neyvia |
| [script.verify-t12-proxy](modules/script.verify-t12-proxy/README.md) | Provides script / verify-t12-proxy in Neyvia. | neyvia |
| [script.verify-t12-recovery](modules/script.verify-t12-recovery/README.md) | Provides script / verify-t12-recovery in Neyvia. | neyvia |
| [script.verify-t5-compiler](modules/script.verify-t5-compiler/README.md) | Provides script / verify-t5-compiler in Neyvia. | neyvia |
| [script.verify-task-continuity](modules/script.verify-task-continuity/README.md) | Provides script / verify-task-continuity in Neyvia. | neyvia |
| [script.verify-task-continuity-http](modules/script.verify-task-continuity-http/README.md) | Provides script / verify-task-continuity-http in Neyvia. | neyvia |
| [script.verify-verified-operations](modules/script.verify-verified-operations/README.md) | Provides script / verify-verified-operations in Neyvia. | neyvia |
| [script.verify-visual-region-performance](modules/script.verify-visual-region-performance/README.md) | Provides script / verify-visual-region-performance in Neyvia. | neyvia |
| [script.verify-visual-specifications](modules/script.verify-visual-specifications/README.md) | Provides script / verify-visual-specifications in Neyvia. | neyvia |
| [script.verify-work-scope-continuation](modules/script.verify-work-scope-continuation/README.md) | Provides script / verify-work-scope-continuation in Neyvia. | neyvia |
| [script.verify-working-memory](modules/script.verify-working-memory/README.md) | Provides script / verify-working-memory in Neyvia. | neyvia |
| [script.verify-working-memory-continuation](modules/script.verify-working-memory-continuation/README.md) | Provides script / verify-working-memory-continuation in Neyvia. | neyvia |
| [script.verify-workspace-intelligence](modules/script.verify-workspace-intelligence/README.md) | Provides script / verify-workspace-intelligence in Neyvia. | neyvia |
| [script.verify_T20](modules/script.verify_T20/README.md) | Provides script / verify_T20 in Neyvia. | neyvia |
| [script.verify_T6](modules/script.verify_T6/README.md) | Provides script / verify_T6 in Neyvia. | neyvia |
| [script.verify_T8](modules/script.verify_T8/README.md) | Provides script / verify_T8 in Neyvia. | neyvia |
| [script.verify_authenticated_live_agent](modules/script.verify_authenticated_live_agent/README.md) | Provides script / verify_authenticated_live_agent in Neyvia. | neyvia |
| [script.verify_authenticated_live_control](modules/script.verify_authenticated_live_control/README.md) | Provides script / verify_authenticated_live_control in Neyvia. | neyvia |
| [script.verify_authenticated_phone_progress](modules/script.verify_authenticated_phone_progress/README.md) | Provides script / verify_authenticated_phone_progress in Neyvia. | neyvia |
| [script.verify_authenticated_settings_surface](modules/script.verify_authenticated_settings_surface/README.md) | Authenticated settings surface verification entrypoint. | neyvia |
| [script.verify_c10_pdf_bounded32](modules/script.verify_c10_pdf_bounded32/README.md) | Actual bounded Arlington PDF extraction and a disposable over-cap transport. | neyvia |
| [script.verify_c1b_apps](modules/script.verify_c1b_apps/README.md) | Real, disposable Windows application action cohort for the C1b driver. | neyvia |
| [script.verify_c1c_apps](modules/script.verify_c1c_apps/README.md) | Real, disposable Windows application action cohort for the C1b driver. | neyvia |
| [script.verify_c4](modules/script.verify_c4/README.md) | Fresh R4 runs and independent artifacts; never reads the blind answer key. | neyvia |
| [script.verify_c4_browse](modules/script.verify_c4_browse/README.md) | Compare the R4 Markdown table to the real page's supported-version table. | neyvia |
| [script.verify_c4_compaction](modules/script.verify_c4_compaction/README.md) | Real Luna continuation under a small host budget, with independent R4 checks. | neyvia |
| [script.verify_c4_host](modules/script.verify_c4_host/README.md) | Exercise C4 host safety on disposable real files, without model calls/ports. | neyvia |
| [script.verify_c4_native](modules/script.verify_c4_native/README.md) | Read-only preflight for the R4 owner-granted Character Map target. | neyvia |
| [script.verify_c4_production](modules/script.verify_c4_production/README.md) | Actual gateway creation, CAS edit and standalone observer proof, no model. | neyvia |
| [script.verify_c4_ui](modules/script.verify_c4_ui/README.md) | Provides script / verify_c4_ui in Neyvia. | neyvia |
| [script.verify_c4c_context](modules/script.verify_c4c_context/README.md) | Exercise source paging, failure retention and mixed calls on the real CL host. | neyvia |
| [script.verify_c4c_pressure](modules/script.verify_c4c_pressure/README.md) | Real bounded bug-fix procedure; requested workloads execute at done(). | neyvia |
| [script.verify_c4c_terminal](modules/script.verify_c4c_terminal/README.md) | Actual CL command completion and corrupt-journal refusal; no model needed. | neyvia |
| [script.verify_c4c_transport](modules/script.verify_c4c_transport/README.md) | Real Windows byte-lock contention and UTF-8 subprocess failure checks. | neyvia |
| [script.verify_c7_edges](modules/script.verify_c7_edges/README.md) | Generate and execute adversarial contracts in owned, isolated state. | neyvia |
| [script.verify_c9b_deliverables](modules/script.verify_c9b_deliverables/README.md) | Small real file/CL-host journeys for C9.1; no network, services or test suite. | neyvia |
| [script.verify_c9b_http](modules/script.verify_c9b_http/README.md) | Provides script / verify_c9b_http in Neyvia. | neyvia |
| [script.verify_c9c_outcomes](modules/script.verify_c9c_outcomes/README.md) | Lead re-execution of retained actual outputs against frozen outcome recipes. | neyvia |
| [script.verify_c9c_voting](modules/script.verify_c9c_voting/README.md) | Exercise generated blind voting pages in Neyvia's actual Obscura workspace. | neyvia |
| [script.verify_c9c_voting_native](modules/script.verify_c9c_voting_native/README.md) | Actual generated vote pages, persistence and refusal in isolated Neyvia WebView2. | neyvia |
| [script.verify_composer_worker_dispatch](modules/script.verify_composer_worker_dispatch/README.md) | Provides script / verify_composer_worker_dispatch in Neyvia. | neyvia |
| [script.verify_connected_app_window_contract](modules/script.verify_connected_app_window_contract/README.md) | Provides script / verify_connected_app_window_contract in Neyvia. | neyvia |
| [script.verify_connected_claude_chats](modules/script.verify_connected_claude_chats/README.md) | Provides script / verify_connected_claude_chats in Neyvia. | neyvia |
| [script.verify_cross_pc](modules/script.verify_cross_pc/README.md) | Provides script / verify_cross_pc in Neyvia. | neyvia |
| [script.verify_cua_guard_attribution](modules/script.verify_cua_guard_attribution/README.md) | Verify attribution policy, then passively observe the real input desktop. | neyvia |
| [script.verify_fix2_browser](modules/script.verify_fix2_browser/README.md) | Exercise authoritative browser revision contracts through real native calls. | neyvia |
| [script.verify_fix2_driver](modules/script.verify_fix2_driver/README.md) | Real pinned Windows driver discovery, native call and readiness failures. | neyvia |
| [script.verify_fix2_http](modules/script.verify_fix2_http/README.md) | Provides script / verify_fix2_http in Neyvia. | neyvia |
| [script.verify_fix2_laya](modules/script.verify_fix2_laya/README.md) | Actual T15-r2 service + Obscura + production cascade attachment receipt. | neyvia |
| [script.verify_fix2_laya_fallback](modules/script.verify_fix2_laya_fallback/README.md) | Actual service-down decisions before a native page has been captured. | neyvia |
| [script.verify_fix2_sdk](modules/script.verify_fix2_sdk/README.md) | Fresh A1 generation + A2 rendered controls through the production SDK browser. | neyvia |
| [script.verify_fix2_search](modules/script.verify_fix2_search/README.md) | Real production local-only search journey; no network/child exemptions. | neyvia |
| [script.verify_fix_accessibility_ui](modules/script.verify_fix_accessibility_ui/README.md) | Provides script / verify_fix_accessibility_ui in Neyvia. | neyvia |
| [script.verify_fix_browser](modules/script.verify_fix_browser/README.md) | Provides script / verify_fix_browser in Neyvia. | neyvia |
| [script.verify_fix_browser_ui](modules/script.verify_fix_browser_ui/README.md) | Provides script / verify_fix_browser_ui in Neyvia. | neyvia |
| [script.verify_fix_classic](modules/script.verify_fix_classic/README.md) | Provides script / verify_fix_classic in Neyvia. | neyvia |
| [script.verify_fix_followups](modules/script.verify_fix_followups/README.md) | Provides script / verify_fix_followups in Neyvia. | neyvia |
| [script.verify_fix_followups_ui](modules/script.verify_fix_followups_ui/README.md) | Provides script / verify_fix_followups_ui in Neyvia. | neyvia |
| [script.verify_fix_native_browser](modules/script.verify_fix_native_browser/README.md) | Provides script / verify_fix_native_browser in Neyvia. | neyvia |
| [script.verify_fix_navigation_ui](modules/script.verify_fix_navigation_ui/README.md) | Provides script / verify_fix_navigation_ui in Neyvia. | neyvia |
| [script.verify_fix_provider_idle](modules/script.verify_fix_provider_idle/README.md) | Exercise the actual Claude protocol driver with a confined CLI peer and slow consumer. | neyvia |
| [script.verify_fix_reader](modules/script.verify_fix_reader/README.md) | Provides script / verify_fix_reader in Neyvia. | neyvia |
| [script.verify_fix_reader_ui](modules/script.verify_fix_reader_ui/README.md) | Provides script / verify_fix_reader_ui in Neyvia. | neyvia |
| [script.verify_fix_remote](modules/script.verify_fix_remote/README.md) | Real two-backend/native FOLLOW proof. Never reads saved credentials. | neyvia |
| [script.verify_fix_sidebar](modules/script.verify_fix_sidebar/README.md) | Real HTTP sidebar proof against 900 persisted chats on an isolated native backend. | neyvia |
| [script.verify_fix_sidebar_grouping](modules/script.verify_fix_sidebar_grouping/README.md) | Actual native conversation/CPU embedding/owner HTTP grouping and undo journey. | neyvia |
| [script.verify_fix_sidebar_network](modules/script.verify_fix_sidebar_network/README.md) | Real controlled TCP/TLS/Settings journey for the loopback I/O policy fast path. | neyvia |
| [script.verify_fix_sidebar_runs](modules/script.verify_fix_sidebar_runs/README.md) | Real disposable SQLite/broker recovery and fresh archive observations, no test framework. | neyvia |
| [script.verify_fix_sidebar_ui](modules/script.verify_fix_sidebar_ui/README.md) | Fixture and scoped normal CLI bootstrap for the real sidebar UI proof. | neyvia |
| [script.verify_fix_workflow_readiness](modules/script.verify_fix_workflow_readiness/README.md) | Provides script / verify_fix_workflow_readiness in Neyvia. | neyvia |
| [script.verify_fixwave_item2](modules/script.verify_fixwave_item2/README.md) | Profile-to-mission acceptance call, bounded to one Claude plan-limits turn. | neyvia |
| [script.verify_fixwave_sidebar](modules/script.verify_fixwave_sidebar/README.md) | Production HTTP archive/undo/policy calls with real scratch worktrees and jobs. | neyvia |
| [script.verify_fixwave_tool_maps](modules/script.verify_fixwave_tool_maps/README.md) | Real local compiler/search/read journey plus silent map-integrity checks. | neyvia |
| [script.verify_follow_approval](modules/script.verify_follow_approval/README.md) | Bounded original approval/replay cases plus isolated production journeys. | neyvia |
| [script.verify_follow_browser_authority](modules/script.verify_follow_browser_authority/README.md) | Owned installed-Chrome journeys plus actual HTTP origin/authority gates. | neyvia |
| [script.verify_follow_browser_render](modules/script.verify_follow_browser_render/README.md) | Rendered T3 phone layout and T12 shared receipts in an owned Chrome profile. | neyvia |
| [script.verify_follow_connected_contract](modules/script.verify_follow_connected_contract/README.md) | Replay the expanded connected command contract on an explicit owned port. | neyvia |
| [script.verify_follow_crash](modules/script.verify_follow_crash/README.md) | Exercise an early request error and a successful request on the owned host. | neyvia |
| [script.verify_follow_current_fixtures](modules/script.verify_follow_current_fixtures/README.md) | Check current native launcher, local lazy history, and manual discovery. | neyvia |
| [script.verify_follow_cycle_fixture](modules/script.verify_follow_cycle_fixture/README.md) | Verify the runtime-cycle fixture and the real HTTP dispatcher seam. | neyvia |
| [script.verify_follow_depth](modules/script.verify_follow_depth/README.md) | Replay the control-room split through an isolated real HTTP backend. | neyvia |
| [script.verify_follow_dictation](modules/script.verify_follow_dictation/README.md) | Recheck the three already-fixed T1 backend policy glitches on FOLLOW ports. | neyvia |
| [script.verify_follow_engine](modules/script.verify_follow_engine/README.md) | Measure the production engine lifecycle with instrumented dependencies, never ASR. | neyvia |
| [script.verify_follow_failures](modules/script.verify_follow_failures/README.md) | Classify historical failure evidence and record bounded repair receipts. | neyvia |
| [script.verify_follow_final_manuals](modules/script.verify_follow_final_manuals/README.md) | Validate the final executable manual catalog through owned HTTP only. | neyvia |
| [script.verify_follow_folder_health](modules/script.verify_follow_folder_health/README.md) | Replay recorded folder health cases against disposable explicit-port REST. | neyvia |
| [script.verify_follow_gamedev](modules/script.verify_follow_gamedev/README.md) | Provides script / verify_follow_gamedev in Neyvia. | neyvia |
| [script.verify_follow_image_skill](modules/script.verify_follow_image_skill/README.md) | Verify bundled skill installation and real fail-closed bridge resolution. | neyvia |
| [script.verify_follow_license](modules/script.verify_follow_license/README.md) | Replay Cargo license admission from actual offline, locked target metadata. | neyvia |
| [script.verify_follow_manuals](modules/script.verify_follow_manuals/README.md) | Live manual registration, execution and loud schema-drift checks. | neyvia |
| [script.verify_follow_permission_fixture](modules/script.verify_follow_permission_fixture/README.md) | Replay reviewed explicit Codex permission and Cursor flag invariants. | neyvia |
| [script.verify_follow_public_contracts](modules/script.verify_follow_public_contracts/README.md) | Current public contracts through reviewed direct cases and real owned HTTP. | neyvia |
| [script.verify_follow_publisher](modules/script.verify_follow_publisher/README.md) | Reviewed publisher cases plus isolated HTTP ownership/integrity proof. | neyvia |
| [script.verify_follow_remaining](modules/script.verify_follow_remaining/README.md) | Bounded replay of the remaining historical backend/source invariants. | neyvia |
| [script.verify_follow_remote](modules/script.verify_follow_remote/README.md) | Real two-backend/native FOLLOW proof. Never reads saved credentials. | neyvia |
| [script.verify_follow_runtime_current](modules/script.verify_follow_runtime_current/README.md) | Replay current runtime contracts without providers or child programs. | neyvia |
| [script.verify_follow_runtime_fixtures](modules/script.verify_follow_runtime_fixtures/README.md) | Direct replay of eight reviewed historical runtime fixture cases. | neyvia |
| [script.verify_follow_secret_fixtures](modules/script.verify_follow_secret_fixtures/README.md) | Replay the existing secret-policy cases with disposable protocol fixtures. | neyvia |
| [script.verify_follow_sidebar](modules/script.verify_follow_sidebar/README.md) | Real HTTP sidebar proof against 900 persisted chats on an isolated native backend. | neyvia |
| [script.verify_follow_sidebar_actual](modules/script.verify_follow_sidebar_actual/README.md) | Measure default provider history without printing private chat content. | neyvia |
| [script.verify_follow_small_failures](modules/script.verify_follow_small_failures/README.md) | Prove small historical invariants through the production native transport. | neyvia |
| [script.verify_follow_source_frontier](modules/script.verify_follow_source_frontier/README.md) | Replay source-only historical assertions without changing UI requirements. | neyvia |
| [script.verify_follow_voice](modules/script.verify_follow_voice/README.md) | Real owner voice approval and executable manual acceptance on FOLLOW ports. | neyvia |
| [script.verify_follow_web_depth](modules/script.verify_follow_web_depth/README.md) | Verify the HTTP/chat responsibility split with the owned HTTP acceptance run. | neyvia |
| [script.verify_follow_windows_spawns](modules/script.verify_follow_windows_spawns/README.md) | Prove real scoped child operations and explicit hidden flags on Windows. | neyvia |
| [script.verify_g2_ui_correction_browser](modules/script.verify_g2_ui_correction_browser/README.md) | G2 UI correction browser proof: modal contrast/scroll/CTA + mobile conversation picker. | neyvia |
| [script.verify_harness_auth_inventory](modules/script.verify_harness_auth_inventory/README.md) | Provides script / verify_harness_auth_inventory in Neyvia. | neyvia |
| [script.verify_harness_comparison](modules/script.verify_harness_comparison/README.md) | Independently verify the frozen live cross-harness comparison receipt. | neyvia |
| [script.verify_html_site_benchmark](modules/script.verify_html_site_benchmark/README.md) | Provides script / verify_html_site_benchmark in Neyvia. | neyvia |
| [script.verify_impact_loop](modules/script.verify_impact_loop/README.md) | Run the impact map against the real repo, including package imports and incremental refresh. | neyvia |
| [script.verify_int6_runtime](modules/script.verify_int6_runtime/README.md) | INT6 real HTTP integration proof against an explicitly owned scratch backend. | neyvia |
| [script.verify_iroh_provider_lifecycle](modules/script.verify_iroh_provider_lifecycle/README.md) | Provides script / verify_iroh_provider_lifecycle in Neyvia. | neyvia |
| [script.verify_launcher_package](modules/script.verify_launcher_package/README.md) | Provides script / verify_launcher_package in Neyvia. | neyvia |
| [script.verify_live_data_contract](modules/script.verify_live_data_contract/README.md) | Provides script / verify_live_data_contract in Neyvia. | neyvia |
| [script.verify_long_context_runtime](modules/script.verify_long_context_runtime/README.md) | Provides script / verify_long_context_runtime in Neyvia. | neyvia |
| [script.verify_mission_pack_launch](modules/script.verify_mission_pack_launch/README.md) | Provides script / verify_mission_pack_launch in Neyvia. | neyvia |
| [script.verify_mobile_conversation_paging_browser](modules/script.verify_mobile_conversation_paging_browser/README.md) | Live browser proof: durable conversation paging 80 → 160 turns. | neyvia |
| [script.verify_mobile_studio_http](modules/script.verify_mobile_studio_http/README.md) | Exercise Mobile Studio's real authenticated HTTP/tool and preview boundaries. | neyvia |
| [script.verify_model_collection_harness_launch](modules/script.verify_model_collection_harness_launch/README.md) | Provides script / verify_model_collection_harness_launch in Neyvia. | neyvia |
| [script.verify_ms_evidence](modules/script.verify_ms_evidence/README.md) | Verify the MS seal against actual files or the exact committed Git blobs. | neyvia |
| [script.verify_ms_workflows](modules/script.verify_ms_workflows/README.md) | Replay real captured Luna answers through registered executable CL manuals. | neyvia |
| [script.verify_nas_provider_cli_spawns](modules/script.verify_nas_provider_cli_spawns/README.md) | Run bounded, real spawn probes for Neyvia's native runtime and provider CLIs. | neyvia |
| [script.verify_nas_ssh_prompt](modules/script.verify_nas_ssh_prompt/README.md) | Provides script / verify_nas_ssh_prompt in Neyvia. | neyvia |
| [script.verify_native_harness_improvement](modules/script.verify_native_harness_improvement/README.md) | Provides script / verify_native_harness_improvement in Neyvia. | neyvia |
| [script.verify_native_harness_quality](modules/script.verify_native_harness_quality/README.md) | Independently verify Neyvia Native's frozen generalization evidence. | neyvia |
| [script.verify_neyvia_candidate_nas](modules/script.verify_neyvia_candidate_nas/README.md) | Provides script / verify_neyvia_candidate_nas in Neyvia. | neyvia |
| [script.verify_neyvia_conversation_fabric](modules/script.verify_neyvia_conversation_fabric/README.md) | Provides script / verify_neyvia_conversation_fabric in Neyvia. | neyvia |
| [script.verify_neyvia_crashproof_ui](modules/script.verify_neyvia_crashproof_ui/README.md) | Provides script / verify_neyvia_crashproof_ui in Neyvia. | neyvia |
| [script.verify_neyvia_marketplace_activation](modules/script.verify_neyvia_marketplace_activation/README.md) | Provides script / verify_neyvia_marketplace_activation in Neyvia. | neyvia |
| [script.verify_neyvia_marketplace_lifecycle](modules/script.verify_neyvia_marketplace_lifecycle/README.md) | Real signed marketplace lifecycle proof: install → activate → disable → rollback. | neyvia |
| [script.verify_neyvia_marketplace_panel_lifecycle](modules/script.verify_neyvia_marketplace_panel_lifecycle/README.md) | User-like Marketplace panel lifecycle proof via the same backend commands. | neyvia |
| [script.verify_neyvia_runtime_stack](modules/script.verify_neyvia_runtime_stack/README.md) | Verify real runtime bindings and every declared agent-ready tool. | neyvia |
| [script.verify_office_suite_operator_browser](modules/script.verify_office_suite_operator_browser/README.md) | Browser proof for the LibreOffice/Pandoc Office Suite operator workspace. | neyvia |
| [script.verify_openai_codex_durable_route](modules/script.verify_openai_codex_durable_route/README.md) | Prove one real OpenAI/Codex turn through Neyvia's durable backend. | neyvia |
| [script.verify_performance_budget](modules/script.verify_performance_budget/README.md) | Fail-closed Neyvia performance-budget gate. | neyvia |
| [script.verify_personal_mesh_browser_proof](modules/script.verify_personal_mesh_browser_proof/README.md) | Validate a redacted, deterministic Personal Mesh browser-proof receipt. | neyvia |
| [script.verify_phase1_folder_sync_status_browser](modules/script.verify_phase1_folder_sync_status_browser/README.md) | Browser-visible proof for Folder Sync status / conflicts / route panel. | neyvia |
| [script.verify_phase1_nearby_hash_ack_proof](modules/script.verify_phase1_nearby_hash_ack_proof/README.md) | Generate Phase 1 Nearby Send hash-ACK product proof (loopback only). | neyvia |
| [script.verify_phase1_nearby_text_link_browser](modules/script.verify_phase1_nearby_text_link_browser/README.md) | Browser-visible Phase 1 proof: Nearby Send text/link + favorites + receipts. | neyvia |
| [script.verify_phase1_personal_mesh_browser](modules/script.verify_phase1_personal_mesh_browser/README.md) | Browser-visible proof for Phase 1 Personal Mesh operator panel. | neyvia |
| [script.verify_phase2_marketplace_browse_browser](modules/script.verify_phase2_marketplace_browse_browser/README.md) | Browser-visible proof for Phase 2 Marketplace browse/detail slice. | neyvia |
| [script.verify_phase7_ui](modules/script.verify_phase7_ui/README.md) | Provides script / verify_phase7_ui in Neyvia. | neyvia |
| [script.verify_private_nas_web_deployment](modules/script.verify_private_nas_web_deployment/README.md) | Provides script / verify_private_nas_web_deployment in Neyvia. | neyvia |
| [script.verify_production_release](modules/script.verify_production_release/README.md) | Provides script / verify_production_release in Neyvia. | neyvia |
| [script.verify_proofs](modules/script.verify_proofs/README.md) | neyvia verify: production contracts and isolated manual self-checks. | neyvia |
| [script.verify_public_launch_readiness](modules/script.verify_public_launch_readiness/README.md) | Provides script / verify_public_launch_readiness in Neyvia. | neyvia |
| [script.verify_public_web_distribution](modules/script.verify_public_web_distribution/README.md) | Provides script / verify_public_web_distribution in Neyvia. | neyvia |
| [script.verify_pwa](modules/script.verify_pwa/README.md) | Provides script / verify_pwa in Neyvia. | neyvia |
| [script.verify_real_agent_conversation_proof](modules/script.verify_real_agent_conversation_proof/README.md) | Provides script / verify_real_agent_conversation_proof in Neyvia. | neyvia |
| [script.verify_real_neyvia_video_digest](modules/script.verify_real_neyvia_video_digest/README.md) | Provides script / verify_real_neyvia_video_digest in Neyvia. | neyvia |
| [script.verify_receipt_bound_evolution](modules/script.verify_receipt_bound_evolution/README.md) | Provides script / verify_receipt_bound_evolution in Neyvia. | neyvia |
| [script.verify_scroll_pack](modules/script.verify_scroll_pack/README.md) | Provides script / verify_scroll_pack in Neyvia. | neyvia |
| [script.verify_self_improvement_evidence](modules/script.verify_self_improvement_evidence/README.md) | Provides script / verify_self_improvement_evidence in Neyvia. | neyvia |
| [script.verify_solantir_preview](modules/script.verify_solantir_preview/README.md) | Provides script / verify_solantir_preview in Neyvia. | neyvia |
| [script.verify_t11_settings](modules/script.verify_t11_settings/README.md) | Provides script / verify_t11_settings in Neyvia. | neyvia |
| [script.verify_t13_evidence](modules/script.verify_t13_evidence/README.md) | Provides script / verify_t13_evidence in Neyvia. | neyvia |
| [script.verify_t13_http](modules/script.verify_t13_http/README.md) | Provides script / verify_t13_http in Neyvia. | neyvia |
| [script.verify_t13_restart](modules/script.verify_t13_restart/README.md) | Provides script / verify_t13_restart in Neyvia. | neyvia |
| [script.verify_t16](modules/script.verify_t16/README.md) | Provides script / verify_t16 in Neyvia. | neyvia |
| [script.verify_t16_contract](modules/script.verify_t16_contract/README.md) | Check real stdio framing, native authority, manual schemas and launcher cleanup. | neyvia |
| [script.verify_t16_luna](modules/script.verify_t16_luna/README.md) | One bounded real Luna manual/MCP native task, independently checked afterward. | neyvia |
| [script.verify_t16_ui](modules/script.verify_t16_ui/README.md) | Provides script / verify_t16_ui in Neyvia. | neyvia |
| [script.verify_t17_evidence](modules/script.verify_t17_evidence/README.md) | Provides script / verify_t17_evidence in Neyvia. | neyvia |
| [script.verify_t19](modules/script.verify_t19/README.md) | Provides script / verify_t19 in Neyvia. | neyvia |
| [script.verify_t1_dictation](modules/script.verify_t1_dictation/README.md) | Provides script / verify_t1_dictation in Neyvia. | neyvia |
| [script.verify_t21](modules/script.verify_t21/README.md) | Provides script / verify_t21 in Neyvia. | neyvia |
| [script.verify_t21_failures](modules/script.verify_t21_failures/README.md) | Provides script / verify_t21_failures in Neyvia. | neyvia |
| [script.verify_t22_live](modules/script.verify_t22_live/README.md) | Provides script / verify_t22_live in Neyvia. | neyvia |
| [script.verify_t22_parsers](modules/script.verify_t22_parsers/README.md) | Provides script / verify_t22_parsers in Neyvia. | neyvia |
| [script.verify_t22_ui](modules/script.verify_t22_ui/README.md) | Provides script / verify_t22_ui in Neyvia. | neyvia |
| [script.verify_t3_voice](modules/script.verify_t3_voice/README.md) | Provides script / verify_t3_voice in Neyvia. | neyvia |
| [script.verify_t4](modules/script.verify_t4/README.md) | Reproduce T4 journeys and write the consolidated, source-bound release receipt. | neyvia |
| [script.verify_t4_core](modules/script.verify_t4_core/README.md) | Exercise T4 through real backend HTTP and compact MCP subprocess calls. | neyvia |
| [script.verify_t4_feedback](modules/script.verify_t4_feedback/README.md) | Run T4 feedback migration, durability and concurrent-writer acceptance journeys. | neyvia |
| [script.verify_t4_mcp](modules/script.verify_t4_mcp/README.md) | Real local MCP protocol journeys, without patching broker or transport calls. | neyvia |
| [script.verify_t4_search](modules/script.verify_t4_search/README.md) | Real rg/Python search receipts using disposable workspace files (no pytest). | neyvia |
| [script.verify_t7_failures](modules/script.verify_t7_failures/README.md) | Provides script / verify_t7_failures in Neyvia. | neyvia |
| [script.verify_t7_sidebar](modules/script.verify_t7_sidebar/README.md) | Provides script / verify_t7_sidebar in Neyvia. | neyvia |
| [script.verify_t9_conductor](modules/script.verify_t9_conductor/README.md) | Provides script / verify_t9_conductor in Neyvia. | neyvia |
| [script.verify_t9_dashboard](modules/script.verify_t9_dashboard/README.md) | Provides script / verify_t9_dashboard in Neyvia. | neyvia |
| [script.verify_t9_opencode](modules/script.verify_t9_opencode/README.md) | Provides script / verify_t9_opencode in Neyvia. | neyvia |
| [script.verify_t9_surfaces](modules/script.verify_t9_surfaces/README.md) | Provides script / verify_t9_surfaces in Neyvia. | neyvia |
| [script.verify_windows_control_ui](modules/script.verify_windows_control_ui/README.md) | Cross-platform process/HTTP helpers for browser-proof verification scripts. | neyvia |
| [script.verify_work_board_codex](modules/script.verify_work_board_codex/README.md) | Real Codex new/resumed turn injection; board inputs seeded explicitly. | neyvia |
| [script.verify_work_board_lifecycle](modules/script.verify_work_board_lifecycle/README.md) | Check terminal cleanup and edit filtering against the real board store. | neyvia |
| [script.verify_work_board_live](modules/script.verify_work_board_live/README.md) | Two real Claude chats through Neyvia's connected-session broker (no fake adapter). | neyvia |
| [script.verify_workbench_program_bridge](modules/script.verify_workbench_program_bridge/README.md) | Provides script / verify_workbench_program_bridge in Neyvia. | neyvia |
| [script.verify_worker_self_repair](modules/script.verify_worker_self_repair/README.md) | Provides script / verify_worker_self_repair in Neyvia. | neyvia |
| [script.video2_tools_journey](modules/script.video2_tools_journey/README.md) | Evidence script (track VIDEO2): an agent's journey through the neyvia.video.* tools on the one video stack. | neyvia |
| [script.video_author_mods](modules/script.video_author_mods/README.md) | Author the video editor mods' descriptors and executable CL manuals (plan 28 Build 1-2). | neyvia |
| [script.video_kronos_turntable](modules/script.video_kronos_turntable/README.md) | Kronos 3D turntable clips for the launch film (headless Blender, nothing on screen). | neyvia |
| [script.video_manual](modules/script.video_manual/README.md) | Author/compile the video manual (manuals/cl/video.cl): HyperFrames editing actions, the LAYA video | neyvia |
| [script.video_recapture](modules/script.video_recapture/README.md) | Evidence script: fresh, populated Neyvia captures for the launch film (track VIDEO, plan 28). | neyvia |
| [script.video_store_proof](modules/script.video_store_proof/README.md) | Evidence script (plan 28 Build 1): the video editors go through the MOD source-install path. | neyvia |
| [script.vision2_calibration](modules/script.vision2_calibration/README.md) | VISION2: rebuild the shipped UI calibration (config/laya_glance_calibration.json) for the current transcriber. | neyvia |
| [script.vision2_new_split](modules/script.vision2_new_split/README.md) | VISION2: a NEW held-out split for the OCR second-pass decision (plan 27 §7, 7 Oct). | neyvia |
| [script.vision2_ocr_decision](modules/script.vision2_ocr_decision/README.md) | VISION2 (plan 27 §7): should the OCR second pass be on by default? Measured, with a rule fixed in advance. | neyvia |
| [script.vision2_second_pass_latency](modules/script.vision2_second_pass_latency/README.md) | VISION2: second-pass latency in ONE warm process (no crop memo), next to the pre-registered measurement. | neyvia |
| [script.vision2_text_runs_identity](modules/script.vision2_text_runs_identity/README.md) | VISION2: prove the faster _text_runs returns exactly what the previous implementation returned. | neyvia |
| [script.vision_blender_practice](modules/script.vision_blender_practice/README.md) | Blender background script: 3D renders with known faults (plan 24 practice, 3D half). | neyvia |
| [script.vision_evolve](modules/script.vision_evolve/README.md) | Missing observable -> Luna-written candidate lens -> grouped keep/reject -> retire (plan 24). | neyvia |
| [script.vision_lens_eval](modules/script.vision_lens_eval/README.md) | Grouped evaluation of LAYA lens sets on every labelled screenshot episode (plan 24). | neyvia |
| [script.vision_practice](modules/script.vision_practice/README.md) | Self-made practice for LAYA's eyes (plan 24 step 5): free, perfectly labelled episodes. | neyvia |
| [script.vision_promote](modules/script.vision_promote/README.md) | Promote the lens decisions of finished plan 24 runs into the repository registry. | neyvia |
| [script.vision_proof](modules/script.vision_proof/README.md) | Plan 24 proof: recompute every number Paul looks at from the run artifacts, then evaluate the | neyvia |
| [script.vision_render_run](modules/script.vision_render_run/README.md) | Plan 24 on 3D renders: the same look -> missing observable -> Luna lens -> held-out keep loop. | neyvia |
| [script.vision_repair_episodes](modules/script.vision_repair_episodes/README.md) | Write any cached model look that has no episode yet (a run killed between caching a look and | neyvia |
| [script.vision_stream](modules/script.vision_stream/README.md) | Plan 24 proof run: a stream of labelled screenshots arriving over time. | neyvia |
| [sdk-js.index](modules/sdk-js.index/README.md) | Provides sdk-js / index in Neyvia. | modules |
| [sdk-js.package](modules/sdk-js.package/README.md) | Provides sdk-js / package in Neyvia. | modules |
| [sdk-python.__init__](modules/sdk-python.__init__/README.md) | Stable, transport-only Neyvia app SDK (ABI 1). | modules |
| [sdk-python.client](modules/sdk-python.client/README.md) | Owner-authenticated client of existing Neyvia HTTP commands and CL tools. | modules |
| [sdk-python.pyproject](modules/sdk-python.pyproject/README.md) | Provides sdk-python / pyproject in Neyvia. | modules |
| [skill.deliverables](modules/skill.deliverables/README.md) | Provides skill / deliverables in Neyvia. | neyvia |
| [skill.design-craft](modules/skill.design-craft/README.md) | Provides skill / design-craft in Neyvia. | neyvia |
| [skill.no-slop](modules/skill.no-slop/README.md) | Provides skill / no-slop in Neyvia. | neyvia |
| [surface.HarnessesSurface](modules/surface.HarnessesSurface/README.md) | Provides HarnessesSurface for Neyvia's UI controls. | proofs-b-browser |
| [surface.ImagePlayground](modules/surface.ImagePlayground/README.md) | Provides ArtifactThumb, ImagePlaygroundSurface for Neyvia's UI controls. | image-studio |
| [surface.IosStudioSurface](modules/surface.IosStudioSurface/README.md) | Provides IosStudioSurface for Neyvia's UI controls. | neyvia |
| [surface.NeyviaApp](modules/surface.NeyviaApp/README.md) | Provides NeyviaApp for Neyvia's UI state and behavior. | neyvia |
| [surface.NeyviaAppFactory](modules/surface.NeyviaAppFactory/README.md) | Provides NeyviaAppFactory for Neyvia's UI controls. | neyvia |
| [surface.NeyviaAppFactoryCanvas](modules/surface.NeyviaAppFactoryCanvas/README.md) | Provides FRAMES, frameForTarget, templateFor, SAMPLE for Neyvia's UI controls. | neyvia |
| [surface.NeyviaAppPreviewWorkspace](modules/surface.NeyviaAppPreviewWorkspace/README.md) | Provides rememberAppFactoryJob, NeyviaAppPreviewWorkspace for Neyvia's UI controls. | neyvia |
| [surface.NeyviaAuthoredToolPanel](modules/surface.NeyviaAuthoredToolPanel/README.md) | Provides NeyviaAuthoredToolPanel for Neyvia's UI controls. | neyvia |
| [surface.NeyviaBrandMark](modules/surface.NeyviaBrandMark/README.md) | Provides NeyviaBrandMark, providerToneSlug, routeRoleToneClass for Neyvia's UI controls. | neyvia |
| [surface.NeyviaClaudeSubscription](modules/surface.NeyviaClaudeSubscription/README.md) | Provides NeyviaClaudeSubscription for Neyvia's UI controls. | neyvia |
| [surface.NeyviaComputerUseProofPanel](modules/surface.NeyviaComputerUseProofPanel/README.md) | Provides NeyviaComputerUseProofPanel for Neyvia's UI controls. | neyvia |
| [surface.NeyviaDevicePreview](modules/surface.NeyviaDevicePreview/README.md) | Provides NeyviaDevicePreview for Neyvia's UI controls. | neyvia |
| [surface.NeyviaDomainExperiencePanel](modules/surface.NeyviaDomainExperiencePanel/README.md) | Provides NeyviaDomainExperiencePanel for Neyvia's UI controls. | neyvia |
| [surface.NeyviaEcosystemFabricPanel](modules/surface.NeyviaEcosystemFabricPanel/README.md) | Provides NeyviaEcosystemFabricPanel for Neyvia's UI controls. | neyvia |
| [surface.NeyviaEcosystemHost](modules/surface.NeyviaEcosystemHost/README.md) | Provides NEYVIA_EMBED_EVENT, NEYVIA_RUNTIME_INVOCATION_EVENT, openNeyviaEmbeddedWorkspace, requestNeyviaRuntimeInvocation for Neyvia's UI controls. | neyvia |
| [surface.NeyviaEmbeddedAdapters](modules/surface.NeyviaEmbeddedAdapters/README.md) | Provides resolveWorkspaceSource, PdfAdapter, OfficeDocumentAdapter, BrowserCaptureAdapter for Neyvia's UI controls. | neyvia |
| [surface.NeyviaHarnessBatches](modules/surface.NeyviaHarnessBatches/README.md) | Provides NeyviaHarnessBatches for Neyvia's UI controls. | neyvia |
| [surface.NeyviaInstalledPrograms](modules/surface.NeyviaInstalledPrograms/README.md) | Provides NeyviaInstalledPrograms for Neyvia's UI controls. | neyvia |
| [surface.NeyviaLabEvidencePanel](modules/surface.NeyviaLabEvidencePanel/README.md) | Provides NeyviaLabEvidencePanel for Neyvia's UI controls. | neyvia |
| [surface.NeyviaMarketplacePanel](modules/surface.NeyviaMarketplacePanel/README.md) | Provides NeyviaMarketplacePanel for Neyvia's UI controls. | neyvia |
| [surface.NeyviaMcpBrokerPanel](modules/surface.NeyviaMcpBrokerPanel/README.md) | Provides NeyviaMcpBrokerPanel for Neyvia's UI controls. | neyvia |
| [surface.NeyviaMessageBody](modules/surface.NeyviaMessageBody/README.md) | Styles NeyviaMessageBody with Neyvia's shared theme tokens. | proofs |
| [surface.NeyviaNativeStudios](modules/surface.NeyviaNativeStudios/README.md) | Provides NeyviaNativeStudioSurface for Neyvia's UI controls. | neyvia |
| [surface.NeyviaOfficeSuitePanel](modules/surface.NeyviaOfficeSuitePanel/README.md) | Provides NeyviaOfficeSuitePanel for Neyvia's UI controls. | neyvia |
| [surface.NeyviaPersonalMeshPanel](modules/surface.NeyviaPersonalMeshPanel/README.md) | Provides NeyviaPersonalMeshPanel for Neyvia's UI controls. | neyvia |
| [surface.NeyviaPromptEditorDialog](modules/surface.NeyviaPromptEditorDialog/README.md) | Provides NeyviaPromptEditorDialog for Neyvia's UI controls. | neyvia |
| [surface.NeyviaProviderAuthQueue](modules/surface.NeyviaProviderAuthQueue/README.md) | Provides NeyviaProviderAuthQueue for Neyvia's UI controls. | neyvia |
| [surface.NeyviaRuntimeComposer](modules/surface.NeyviaRuntimeComposer/README.md) | Provides NeyviaRuntimeComposer for Neyvia's UI controls. | neyvia |
| [surface.NeyviaSecurityRuntimePanel](modules/surface.NeyviaSecurityRuntimePanel/README.md) | Provides NeyviaSecurityRuntimePanel for Neyvia's UI controls. | neyvia |
| [surface.NeyviaSignIn](modules/surface.NeyviaSignIn/README.md) | Provides NeyviaSignIn for Neyvia's UI controls. | neyvia |
| [surface.NeyviaSourceMarketplace](modules/surface.NeyviaSourceMarketplace/README.md) | Provides NeyviaSourceMarketplace for Neyvia's UI controls. | neyvia |
| [surface.NeyviaTasteReview](modules/surface.NeyviaTasteReview/README.md) | Provides NeyviaTasteReview for Neyvia's UI controls. | neyvia |
| [surface.NeyviaToolVisuals](modules/surface.NeyviaToolVisuals/README.md) | Provides resolveNeyviaLucideIcon, NeyviaToolIcon, NeyviaFileTypeIcon, NeyviaToolCallChip for Neyvia's UI controls. | neyvia |
| [surface.NeyviaWelcome](modules/surface.NeyviaWelcome/README.md) | Provides NeyviaWelcome for Neyvia's UI controls. | neyvia |
| [surface.NxAccounts](modules/surface.NxAccounts/README.md) | Provides NxAccounts for Neyvia's UI controls. | neyvia |
| [surface.NxAgentDashboard](modules/surface.NxAgentDashboard/README.md) | Provides useDashboard, ModLine, NxAgentDashboard for Neyvia's UI controls. | agents |
| [surface.NxAgentTree](modules/surface.NxAgentTree/README.md) | Provides NightTree, TONE, AgentTree for Neyvia's UI controls. | neyvia |
| [surface.NxAgentsOverview](modules/surface.NxAgentsOverview/README.md) | Provides NxAgentsOverview for Neyvia's UI controls. | neyvia |
| [surface.NxAgentsPanel](modules/surface.NxAgentsPanel/README.md) | Provides NxAgentsPanel for Neyvia's UI controls. | agents |
| [surface.NxAmplifyCard](modules/surface.NxAmplifyCard/README.md) | Provides useAmplifyMode, useAmplifier, NxAmplifyCard for Neyvia's UI controls. | neyvia |
| [surface.NxAppleTargets](modules/surface.NxAppleTargets/README.md) | Provides AppleTargets, IosCard for Neyvia's UI controls. | neyvia |
| [surface.NxArrange](modules/surface.NxArrange/README.md) | Provides WIDTH_VARS, useViewportWidth, Splitter, Region for Neyvia's UI controls. | neyvia |
| [surface.NxArtifactPane](modules/surface.NxArtifactPane/README.md) | Provides NxArtifactPane for Neyvia's UI controls. | outputs |
| [surface.NxAutopilot](modules/surface.NxAutopilot/README.md) | Provides useAutopilotRuns, AutopilotToggle, AutopilotScope, useAutopilotMode for Neyvia's UI controls. | neyvia |
| [surface.NxAvatar](modules/surface.NxAvatar/README.md) | Provides NxAvatar for Neyvia's UI controls. | neyvia |
| [surface.NxAwareness](modules/surface.NxAwareness/README.md) | Provides NxAwareness for Neyvia's UI controls. | neyvia |
| [surface.NxBackdrop](modules/surface.NxBackdrop/README.md) | Provides NxBackdrop for Neyvia's UI controls. | neyvia |
| [surface.NxBrowser](modules/surface.NxBrowser/README.md) | Provides NativeSlot, NxBrowser, PipFrame for Neyvia's UI controls. | neyvia |
| [surface.NxBrowserPane](modules/surface.NxBrowserPane/README.md) | Provides isWebUrl, paneEngine, pageProjection, OwnedBrowserPane for Neyvia's UI controls. | neyvia |
| [surface.NxBrowserParts](modules/surface.NxBrowserParts/README.md) | Provides Monogram, useCover, PermissionRequests, CommandBar for Neyvia's UI controls. | neyvia |
| [surface.NxBrowserPip](modules/surface.NxBrowserPip/README.md) | Provides NxBrowserPip for Neyvia's UI controls. | neyvia |
| [surface.NxBubbles](modules/surface.NxBubbles/README.md) | Provides NxBubbles for Neyvia's UI controls. | neyvia |
| [surface.NxBuilder](modules/surface.NxBuilder/README.md) | Provides NxBuilder for Neyvia's UI controls. | neyvia |
| [surface.NxCanopy](modules/surface.NxCanopy/README.md) | Provides NxCanopy for Neyvia's UI controls. | neyvia |
| [surface.NxChecklist](modules/surface.NxChecklist/README.md) | Provides NxChecklist for Neyvia's UI controls. | agents |
| [surface.NxComments](modules/surface.NxComments/README.md) | Provides CommentsStrip, StageTools, targetName, CommentsLayer for Neyvia's UI controls. | neyvia |
| [surface.NxComposer](modules/surface.NxComposer/README.md) | Provides forgetProviderOptions, useProviderOptions, NxComposer for Neyvia's UI controls. | neyvia |
| [surface.NxComposerPlus](modules/surface.NxComposerPlus/README.md) | Provides imageDrafts, fileDrafts, useFileDraft, FileTray for Neyvia's UI controls. | neyvia |
| [surface.NxConductor](modules/surface.NxConductor/README.md) | Provides ConductorJobView, NxConductor for Neyvia's UI controls. | neyvia |
| [surface.NxConnections](modules/surface.NxConnections/README.md) | Provides NxConnections for Neyvia's UI controls. | neyvia |
| [surface.NxDictation](modules/surface.NxDictation/README.md) | Provides useDictation, useTextareaDictation, startDictationIn, MicButton for Neyvia's UI controls. | dictation |
| [surface.NxDockDrag](modules/surface.NxDockDrag/README.md) | Provides useDockDrag, DockDragGhost for Neyvia's UI controls. | neyvia |
| [surface.NxEmulatedKeyboard](modules/surface.NxEmulatedKeyboard/README.md) | Provides EmulatedKeyboard for Neyvia's UI controls. | neyvia |
| [surface.NxEvolver](modules/surface.NxEvolver/README.md) | Provides NxEvolver for Neyvia's UI controls. | neyvia |
| [surface.NxEvolverParts](modules/surface.NxEvolverParts/README.md) | Provides Hash, Verdict, TrialCard, ParetoFront for Neyvia's UI controls. | neyvia |
| [surface.NxFilePane](modules/surface.NxFilePane/README.md) | Provides PaneMessage, DiffLines, NxFilePane for Neyvia's UI controls. | neyvia |
| [surface.NxFilesApp](modules/surface.NxFilesApp/README.md) | Provides NxFilesApp for Neyvia's UI controls. | neyvia |
| [surface.NxFolderPicker](modules/surface.NxFolderPicker/README.md) | Provides NxFolderPicker for Neyvia's UI controls. | neyvia |
| [surface.NxGameDev](modules/surface.NxGameDev/README.md) | Provides NxGameDev for Neyvia's UI controls. | neyvia |
| [surface.NxGrowingTree](modules/surface.NxGrowingTree/README.md) | Provides NxGrowingTree for Neyvia's UI controls. | neyvia |
| [surface.NxHomeWidgets](modules/surface.NxHomeWidgets/README.md) | Provides NxHomeWidgets for Neyvia's UI controls. | neyvia |
| [surface.NxIndicators](modules/surface.NxIndicators/README.md) | Provides NxIndicators for Neyvia's UI controls. | neyvia |
| [surface.NxKomorebi](modules/surface.NxKomorebi/README.md) | Provides NxKomorebi for Neyvia's UI controls. | neyvia |
| [surface.NxLauncher](modules/surface.NxLauncher/README.md) | Provides NxLauncher for Neyvia's UI controls. | neyvia |
| [surface.NxLaya](modules/surface.NxLaya/README.md) | Provides useLayaReport, NxLayaApp, LayaIndicator for Neyvia's UI controls. | neyvia |
| [surface.NxLayaLearned](modules/surface.NxLayaLearned/README.md) | Provides LayaLearned for Neyvia's UI controls. | neyvia |
| [surface.NxLibrarySurfaces](modules/surface.NxLibrarySurfaces/README.md) | Provides NeyviaNotebookSurface, NeyviaLabSurface, NeyviaLibrarySurface for Neyvia's UI controls. | neyvia |
| [surface.NxLocalOnly](modules/surface.NxLocalOnly/README.md) | Provides LocalOnlyGate for Neyvia's UI controls. | outputs |
| [surface.NxLook](modules/surface.NxLook/README.md) | Provides LookControls for Neyvia's UI controls. | neyvia |
| [surface.NxMedia](modules/surface.NxMedia/README.md) | Provides mediaSource, Attachments for Neyvia's UI controls. | neyvia |
| [surface.NxMemoryPanel](modules/surface.NxMemoryPanel/README.md) | Provides NxMemoryPanel for Neyvia's UI controls. | neyvia |
| [surface.NxMissions](modules/surface.NxMissions/README.md) | Provides useMissions, MissionView, NxMissions for Neyvia's UI controls. | neyvia |
| [surface.NxMobileBuildParts](modules/surface.NxMobileBuildParts/README.md) | Provides Missing, Check1, CopyPath, JobLine for Neyvia's UI controls. | neyvia |
| [surface.NxMobileStudio](modules/surface.NxMobileStudio/README.md) | Provides NxMobileStudio for Neyvia's UI controls. | neyvia |
| [surface.NxModelPicker](modules/surface.NxModelPicker/README.md) | Provides effortLabel, prettyModel, ModelPicker for Neyvia's UI controls. | neyvia |
| [surface.NxNewChat](modules/surface.NxNewChat/README.md) | Provides NxNewChat for Neyvia's UI controls. | neyvia |
| [surface.NxNightShift](modules/surface.NxNightShift/README.md) | Provides NxNightShift for Neyvia's UI controls. | nightshift |
| [surface.NxNightShiftParts](modules/surface.NxNightShiftParts/README.md) | Provides EvidenceLink, MorningCard, BudgetPanel for Neyvia's UI controls. | nightshift |
| [surface.NxNotesApp](modules/surface.NxNotesApp/README.md) | Provides NxNotesApp for Neyvia's UI controls. | neyvia |
| [surface.NxNotesWelcome](modules/surface.NxNotesWelcome/README.md) | Provides NOTE_STARTERS, NotesWelcome for Neyvia's UI controls. | neyvia |
| [surface.NxOnboarding](modules/surface.NxOnboarding/README.md) | Provides NxOnboarding for Neyvia's UI controls. | neyvia |
| [surface.NxOnboardingConnections](modules/surface.NxOnboardingConnections/README.md) | Provides ConnectionsSlot, ConnectionsStep for Neyvia's UI controls. | neyvia |
| [surface.NxOnboardingDownloads](modules/surface.NxOnboardingDownloads/README.md) | Provides useComponents, DownloadsStep for Neyvia's UI controls. | neyvia |
| [surface.NxOnboardingPacks](modules/surface.NxOnboardingPacks/README.md) | Provides usePackStatus, PackRow, PacksSection for Neyvia's UI controls. | neyvia |
| [surface.NxOtherPcs](modules/surface.NxOtherPcs/README.md) | Provides useDevices, pairedDevices, SendToPc, TransfersStrip for Neyvia's UI controls. | neyvia |
| [surface.NxOutputs](modules/surface.NxOutputs/README.md) | Provides OutputPreview, NxOutputs for Neyvia's UI controls. | outputs |
| [surface.NxPaneObserver](modules/surface.NxPaneObserver/README.md) | Provides usePaneObservation, ObserveDom, PaneRefused, ObservedImage for Neyvia's UI controls. | neyvia |
| [surface.NxPanes](modules/surface.NxPanes/README.md) | Provides StagePane, PaneView for Neyvia's UI controls. | neyvia |
| [surface.NxParallel](modules/surface.NxParallel/README.md) | Provides useParallel, NxParallel for Neyvia's UI controls. | neyvia |
| [surface.NxPdfApp](modules/surface.NxPdfApp/README.md) | Provides NxPdfApp for Neyvia's UI controls. | pdf |
| [surface.NxPdfPage](modules/surface.NxPdfPage/README.md) | Provides NxPdfPage for Neyvia's UI controls. | pdf |
| [surface.NxPdfToolbar](modules/surface.NxPdfToolbar/README.md) | Provides NxPdfToolbar for Neyvia's UI controls. | neyvia |
| [surface.NxPerception](modules/surface.NxPerception/README.md) | Provides NxPerception for Neyvia's UI controls. | neyvia |
| [surface.NxPermissionPicker](modules/surface.NxPermissionPicker/README.md) | Provides PermissionPicker for Neyvia's UI controls. | neyvia |
| [surface.NxPhone](modules/surface.NxPhone/README.md) | Provides insetsFor, isLight, shortPath, Phone for Neyvia's UI controls. | neyvia |
| [surface.NxPlacement](modules/surface.NxPlacement/README.md) | Provides SurfaceSlot, windowIcon, peekRect, bubblePoint for Neyvia's UI controls. | design |
| [surface.NxPopout](modules/surface.NxPopout/README.md) | Provides NxPopout for Neyvia's UI controls. | neyvia |
| [surface.NxPreviewPane](modules/surface.NxPreviewPane/README.md) | Provides NxPreviewPane for Neyvia's UI controls. | computer-use |
| [surface.NxRain](modules/surface.NxRain/README.md) | Provides NxRain for Neyvia's UI controls. | neyvia |
| [surface.NxRemote](modules/surface.NxRemote/README.md) | Provides NxRemote for Neyvia's UI controls. | remote |
| [surface.NxRemoteBanner](modules/surface.NxRemoteBanner/README.md) | Provides refreshRemote, useRemoteState, NxRemoteBanner for Neyvia's UI controls. | neyvia |
| [surface.NxReplay](modules/surface.NxReplay/README.md) | Provides NxReplay for Neyvia's UI controls. | neyvia |
| [surface.NxRoutePicker](modules/surface.NxRoutePicker/README.md) | Provides preferredTransport, billingNote, RoutePicker for Neyvia's UI controls. | neyvia |
| [surface.NxRuntime](modules/surface.NxRuntime/README.md) | Provides useRuntimeReading, NxRuntime for Neyvia's UI controls. | neyvia |
| [surface.NxScrollStudy](modules/surface.NxScrollStudy/README.md) | Provides NxScrollStudy for Neyvia's UI controls. | neyvia |
| [surface.NxSessionsPane](modules/surface.NxSessionsPane/README.md) | Provides tailLines, NxSessionsPane for Neyvia's UI controls. | neyvia |
| [surface.NxSettings](modules/surface.NxSettings/README.md) | Provides NxSettings for Neyvia's UI controls. | neyvia |
| [surface.NxSettingsParts](modules/surface.NxSettingsParts/README.md) | Provides InitiativeCard, UsageCard, NightShiftCard, PrivacyCard for Neyvia's UI controls. | neyvia |
| [surface.NxShell](modules/surface.NxShell/README.md) | Provides NxShell for Neyvia's UI controls. | design |
| [surface.NxShellParts](modules/surface.NxShellParts/README.md) | Provides SidePanel, ThreadHeader for Neyvia's UI controls. | neyvia |
| [surface.NxSidebar](modules/surface.NxSidebar/README.md) | Provides useSidebarRows, useObserveSidebar, SourceStatus, NxSidebar for Neyvia's UI controls. | agents |
| [surface.NxSidebarParts](modules/surface.NxSidebarParts/README.md) | Provides markFor, appLabel, statusLine, agentWords for Neyvia's UI controls. | neyvia |
| [surface.NxSidebarRail](modules/surface.NxSidebarRail/README.md) | Provides NxSidebarRail for Neyvia's UI controls. | neyvia |
| [surface.NxSidebarSort](modules/surface.NxSidebarSort/README.md) | Provides SortChip for Neyvia's UI controls. | neyvia |
| [surface.NxSignIn](modules/surface.NxSignIn/README.md) | Provides needsSignIn, SignInCard for Neyvia's UI controls. | neyvia |
| [surface.NxStage](modules/surface.NxStage/README.md) | Provides stageTitle, NxStage for Neyvia's UI controls. | neyvia |
| [surface.NxSwitcher](modules/surface.NxSwitcher/README.md) | Provides useLayers, NxSwitcher for Neyvia's UI controls. | neyvia |
| [surface.NxTaskFeedback](modules/surface.NxTaskFeedback/README.md) | Provides NxTaskFeedback for Neyvia's UI controls. | neyvia |
| [surface.NxTerminalPane](modules/surface.NxTerminalPane/README.md) | Provides promptFor, tabNames, NxTerminalPane for Neyvia's UI controls. | neyvia |
| [surface.NxThemeAmbient](modules/surface.NxThemeAmbient/README.md) | Provides NxThemeAmbient for Neyvia's UI controls. | neyvia |
| [surface.NxThemePicker](modules/surface.NxThemePicker/README.md) | Provides NxThemePicker for Neyvia's UI controls. | neyvia |
| [surface.NxThread](modules/surface.NxThread/README.md) | Provides NxThread for Neyvia's UI controls. | transparency |
| [surface.NxTidy](modules/surface.NxTidy/README.md) | Provides useTidy, TidyPreview, TidyChip, CleanupForm for Neyvia's UI controls. | neyvia |
| [surface.NxTimers](modules/surface.NxTimers/README.md) | Provides NxTimers for Neyvia's UI controls. | neyvia |
| [surface.NxToasts](modules/surface.NxToasts/README.md) | Provides NxToasts for Neyvia's UI controls. | neyvia |
| [surface.NxToolScreens](modules/surface.NxToolScreens/README.md) | Provides TOOL_SUITES, TOOL_TITLES, isToolScreen, openTool for Neyvia's UI controls. | neyvia |
| [surface.NxTour](modules/surface.NxTour/README.md) | Provides NxTour for Neyvia's UI controls. | neyvia |
| [surface.NxTourFeatureScenes](modules/surface.NxTourFeatureScenes/README.md) | Provides LookScene, WatchingScene, FactoryScene, ConnectorsScene for Neyvia's UI controls. | neyvia |
| [surface.NxTourScenes](modules/surface.NxTourScenes/README.md) | Provides TOUR_W, TOUR_H, SCENES for Neyvia's UI controls. | neyvia |
| [surface.NxUpdate](modules/surface.NxUpdate/README.md) | Provides UpdateCard for Neyvia's UI controls. | neyvia |
| [surface.NxUsage](modules/surface.NxUsage/README.md) | Provides NxUsage for Neyvia's UI controls. | neyvia |
| [surface.NxVoice](modules/surface.NxVoice/README.md) | Provides startVoiceCommand, NxVoice, VoiceButton, KEYMAP for Neyvia's UI controls. | neyvia |
| [surface.NxVoiceSettings](modules/surface.NxVoiceSettings/README.md) | Provides VoiceCard for Neyvia's UI controls. | neyvia |
| [surface.NxWorkspaceActions](modules/surface.NxWorkspaceActions/README.md) | Provides useGitFlow, WorkspaceFooter for Neyvia's UI controls. | neyvia |
| [surface.NxWorkspaceBits](modules/surface.NxWorkspaceBits/README.md) | Provides StatusBadge, Counts, FilePath, MiddlePath for Neyvia's UI controls. | neyvia |
| [surface.NxWorkspaceDiff](modules/surface.NxWorkspaceDiff/README.md) | Provides flatten, DiffRows, NxWorkspaceDiff for Neyvia's UI controls. | neyvia |
| [surface.NxWorkspacePanel](modules/surface.NxWorkspacePanel/README.md) | Provides RepoSection, ChangesSection, NxWorkspacePanel for Neyvia's UI controls. | neyvia |
| [surface.ProviderMark](modules/surface.ProviderMark/README.md) | Provides ProviderMark for Neyvia's UI controls. | neyvia |
| [surface.agentview.NxAgentView](modules/surface.agentview.NxAgentView/README.md) | Provides NxAgentRun, NxAgentView for Neyvia's UI controls. | neyvia |
| [surface.agentview.nxAgentView](modules/surface.agentview.nxAgentView/README.md) | Styles nxAgentView with Neyvia's shared theme tokens. | neyvia |
| [surface.agentview.nxAgentViewApi](modules/surface.agentview.nxAgentViewApi/README.md) | Provides holdExampleRuns, listRuns, readTimeline, readFrame for Neyvia's UI state and behavior. | neyvia |
| [surface.agentview.nxAgentViewExample](modules/surface.agentview.nxAgentViewExample/README.md) | Provides exampleKeyframe, exampleRuns for Neyvia's UI state and behavior. | neyvia |
| [surface.agentview.nxAgentViewModel](modules/surface.agentview.nxAgentViewModel/README.md) | Provides AgentViewContractError, MAX_LAYERS, POLL, QUIET_POLLS for Neyvia's UI state and behavior. | agent-view |
| [surface.build-provider-marks-preview](modules/surface.build-provider-marks-preview/README.md) | Provides surface / build-provider-marks-preview in Neyvia. | neyvia |
| [surface.chatCancellation](modules/surface.chatCancellation/README.md) | Provides isChatCancellationResult, cancelledChatTurnPatch for Neyvia's UI state and behavior. | agents |
| [surface.details.details.manifest](modules/surface.details.details.manifest/README.md) | Provides surface / details / details / manifest in Neyvia. | neyvia |
| [surface.details.kit.demo](modules/surface.details.kit.demo/README.md) | Provides surface / details / kit / demo in Neyvia. | neyvia |
| [surface.details.kit.details](modules/surface.details.kit.details/README.md) | Provides haptic, announce, rollingNumber, meter for Neyvia's UI state and behavior. | neyvia |
| [surface.details.kit.model](modules/surface.details.kit.model/README.md) | Provides surface / details / kit / model in Neyvia. | neyvia |
| [surface.details.nxDetails](modules/surface.details.nxDetails/README.md) | Provides PRESS, haptic, RollingNumber, Meter for Neyvia's UI controls. | neyvia |
| [surface.details.nxDetailsModel](modules/surface.details.nxDetailsModel/README.md) | Provides numberCells, WHEEL_FACES, wheelTarget, wheelRest for Neyvia's UI state and behavior. | neyvia |
| [surface.harnesses](modules/surface.harnesses/README.md) | Styles harnesses with Neyvia's shared theme tokens. | neyvia |
| [surface.imagePlaygroundContracts](modules/surface.imagePlaygroundContracts/README.md) | Provides ImageContractError, IMAGE_CONTRACTS, checkedImageAction, checkImagePromptPresets for Neyvia's UI state and behavior. | image-studio |
| [surface.imagePlaygroundScoped](modules/surface.imagePlaygroundScoped/README.md) | Styles imagePlaygroundScoped with Neyvia's shared theme tokens. | neyvia |
| [surface.imagePlaygroundState](modules/surface.imagePlaygroundState/README.md) | Provides IMAGE_PLAYGROUND_STORAGE_KEY, CANVAS_SIZE_PRESETS, IMAGE_PROMPT_PRESETS, IMAGE_TOOL_DEFINITIONS for Neyvia's UI state and behavior. | image-studio |
| [surface.imageProviderAdapters](modules/surface.imageProviderAdapters/README.md) | Provides QUEUE_TIMELINE_STAGES, IMAGE_PROVIDER_ADAPTERS, buildIssueThreadRef, snapshotOverlayAnnotations for Neyvia's UI state and behavior. | image-studio |
| [surface.iosStudio](modules/surface.iosStudio/README.md) | Styles iosStudio with Neyvia's shared theme tokens. | neyvia |
| [surface.lab.lab](modules/surface.lab.lab/README.md) | Styles lab with Neyvia's shared theme tokens. | neyvia |
| [surface.lab.main](modules/surface.lab.main/README.md) | Provides surface / lab / main in Neyvia. | neyvia |
| [surface.lab.specimens.agent-run-card](modules/surface.lab.specimens.agent-run-card/README.md) | Provides title for Neyvia's UI controls. | neyvia |
| [surface.lab.specimens.details](modules/surface.lab.specimens.details/README.md) | Styles details with Neyvia's shared theme tokens. | neyvia |
| [surface.lab.specimens.details-actions](modules/surface.lab.specimens.details-actions/README.md) | Provides title for Neyvia's UI controls. | neyvia |
| [surface.lab.specimens.details-numbers](modules/surface.lab.specimens.details-numbers/README.md) | Provides title for Neyvia's UI controls. | neyvia |
| [surface.lab.specimens.details-states](modules/surface.lab.specimens.details-states/README.md) | Provides title for Neyvia's UI controls. | neyvia |
| [surface.lab.specimens.primitives](modules/surface.lab.specimens.primitives/README.md) | Provides title for Neyvia's UI controls. | neyvia |
| [surface.missionControlModel](modules/surface.missionControlModel/README.md) | Provides parseWorkspaceSyncConflictBatchResolutions, parseWorkspaceSyncStatus, deriveProjectProgressHistory, deriveWorkspaceHealth for Neyvia's UI state and behavior. | neyvia-reference |
| [surface.missionHelpers](modules/surface.missionHelpers/README.md) | Provides titleizeToken, runtimeLabel, missionStatusTone, formatDurationCompact for Neyvia's UI state and behavior. | proofs |
| [surface.missionReviewContracts](modules/surface.missionReviewContracts/README.md) | Provides LIVE_REVIEW_CONTRACT, LiveReviewContractError, checkedLiveReviewProjection for Neyvia's UI state and behavior. | neyvia-reference |
| [surface.neyviaAppFactory](modules/surface.neyviaAppFactory/README.md) | Styles neyviaAppFactory with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaAppFactoryModel](modules/surface.neyviaAppFactoryModel/README.md) | Provides APP_FACTORY_COMMANDS, APP_FACTORY_STAGE_ORDER, appFactoryProgress, appFactoryJobTone for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaAppFactoryStudio](modules/surface.neyviaAppFactoryStudio/README.md) | Styles neyviaAppFactoryStudio with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaAppPreviewWorkspace](modules/surface.neyviaAppPreviewWorkspace/README.md) | Styles neyviaAppPreviewWorkspace with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaApplicationContract](modules/surface.neyviaApplicationContract/README.md) | Provides NEYVIA_APPLICATION_CONTRACT_SCHEMA, NEYVIA_APPLICATION_KINDS, normalizeApplicationKind, applicationKindMeta for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaAttentionFixtures](modules/surface.neyviaAttentionFixtures/README.md) | Provides isAttentionShowcaseFixture, buildAttentionShowcaseConversations for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaAttentionInbox](modules/surface.neyviaAttentionInbox/README.md) | Provides NEYVIA_ATTENTION_INBOX_SCHEMA, NEYVIA_ATTENTION_STATES, NEYVIA_ATTENTION_PRIORITY_STATES, attentionStateMeta for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaAuthoredTool](modules/surface.neyviaAuthoredTool/README.md) | Styles neyviaAuthoredTool with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaBackendFetch](modules/surface.neyviaBackendFetch/README.md) | Provides UNREACHABLE_MESSAGE, TIMEOUT_MESSAGE, isReadCommand, isNetworkFailure for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaBoot](modules/surface.neyviaBoot/README.md) | Provides neyviaBootMounted, neyviaBootReady for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaBridge](modules/surface.neyviaBridge/README.md) | Provides getTurnDiff, getFullThreadDiff, replayEvents, buildLiveReviewWorkbench for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaCapabilityContracts](modules/surface.neyviaCapabilityContracts/README.md) | Provides checkCapabilityAction for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaCapabilityEvolutionModel](modules/surface.neyviaCapabilityEvolutionModel/README.md) | Provides CAPABILITY_EVOLUTION_COMMANDS, COUNTERFACTUAL_FORGE_SCHEMA, SEALED_SKILL_CANDIDATE_SCHEMA, COUNTERFACTUAL_CASE_LIMIT for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaCapabilityIdentity](modules/surface.neyviaCapabilityIdentity/README.md) | Provides NEYVIA_CAPABILITY_IDENTITY_SCHEMA, NEYVIA_ZONES, zoneMeta, isNeyviaZone for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaChatContracts](modules/surface.neyviaChatContracts/README.md) | Provides ChatContractError, toolCallClaim, stringFieldClaim, CHAT_CONTRACTS for Neyvia's UI state and behavior. | agents |
| [surface.neyviaChatRecovery](modules/surface.neyviaChatRecovery/README.md) | Provides INTERRUPTED_CHAT_SOURCE, UNREGISTERED_TURN_GRACE_MS, MISSING_RESULT_GRACE_MS, QUIET_RESPONSE_MS for Neyvia's UI state and behavior. | agents |
| [surface.neyviaChatStream](modules/surface.neyviaChatStream/README.md) | Provides normalizeNeyviaChatActivitySegments, applyNeyviaChatStreamEvents, startNeyviaChatStreamPoll, createNeyviaChatStreamState for Neyvia's UI state and behavior. | agents |
| [surface.neyviaComputerUseProof](modules/surface.neyviaComputerUseProof/README.md) | Styles neyviaComputerUseProof with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaDevicePreview](modules/surface.neyviaDevicePreview/README.md) | Styles neyviaDevicePreview with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaDictation](modules/surface.neyviaDictation/README.md) | Provides DICTATION_ERRORS, createDictation for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaDomainExperiences](modules/surface.neyviaDomainExperiences/README.md) | Provides NEYVIA_DOMAIN_EXPERIENCES, domainExperienceById, domainStarterPrompt for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaEcosystemActionModel](modules/surface.neyviaEcosystemActionModel/README.md) | Provides buildPresentationCapturePayload, buildBenchmarkResultPayload, canSubmitBenchmarkResult, canConcludeExperiment for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaEcosystemFabricModel](modules/surface.neyviaEcosystemFabricModel/README.md) | Provides COMMUNICATION_ROUTES, COMMUNICATION_STATES, PRESENTATION_PROFILES, normalizeCommunicationFabric for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaEmbeddedWorkspace](modules/surface.neyviaEmbeddedWorkspace/README.md) | Provides NEYVIA_EMBEDDED_WORKSPACE_SCHEMA, NEYVIA_EMBED_PRESENTATIONS, normalizeEmbedPresentation, embedPresentationMeta for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaFonts](modules/surface.neyviaFonts/README.md) | Styles neyviaFonts with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaFrontendContracts](modules/surface.neyviaFrontendContracts/README.md) | Provides FrontendContractError, equalContractValue, frontendContractBefore, FRONTEND_CONTRACTS for Neyvia's UI state and behavior. | agents |
| [surface.neyviaHarnessBatchModel](modules/surface.neyviaHarnessBatchModel/README.md) | Provides parseBatchPrompts for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaLiveMessages](modules/surface.neyviaLiveMessages/README.md) | Provides noteLiveMessage, isLiveMessage, forgetLiveMessage for Neyvia's UI state and behavior. | proofs |
| [surface.neyviaMarketplace](modules/surface.neyviaMarketplace/README.md) | Styles neyviaMarketplace with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaMarketplaceModel](modules/surface.neyviaMarketplaceModel/README.md) | Provides MARKETPLACE_UNAVAILABLE, marketplaceCompatibility, MARKETPLACE_BACKEND_COMMANDS, marketplaceStateTone for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaMcpBroker](modules/surface.neyviaMcpBroker/README.md) | Styles neyviaMcpBroker with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaMissionProjection](modules/surface.neyviaMissionProjection/README.md) | Provides NEYVIA_MISSION_PROJECTION_SCHEMA, MISSION_EVENT_WINDOW, missionIdOf, missionEventId for Neyvia's UI state and behavior. | mission-plan |
| [surface.neyviaModeStarters](modules/surface.neyviaModeStarters/README.md) | Provides NEYVIA_CHAT_STARTERS, NEYVIA_ORCHESTRATION_STARTERS, NEYVIA_DEFAULT_ORCHESTRATION_ROLES, normalizeNeyviaOrchestrationRoleIds for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaMotion](modules/surface.neyviaMotion/README.md) | Provides NEYVIA_REDUCE_MOTION_ATTR, NEYVIA_REDUCE_MOTION_FALLBACK_ATTR, applyNeyviaReduceMotion, isNeyviaMotionReduced for Neyvia's UI state and behavior. | settings |
| [surface.neyviaNativeStudios](modules/surface.neyviaNativeStudios/README.md) | Styles neyviaNativeStudios with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaOfficeSuite](modules/surface.neyviaOfficeSuite/README.md) | Styles neyviaOfficeSuite with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaOfficeSuiteModel](modules/surface.neyviaOfficeSuiteModel/README.md) | Provides OFFICE_SUITE_TOOL_IDS, OFFICE_SUITE_DEFAULT_TOOL_ID, OFFICE_COMMON_FIELDS_BY_OPERATION, OFFICE_PANDOC_COMMON_OUTPUT_FORMATS for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaPcHost](modules/surface.neyviaPcHost/README.md) | Provides PC_OFFLINE_MESSAGE, PcHostError, runsInDesktopApp, usePcHostStatus for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaPersonalMeshModel](modules/surface.neyviaPersonalMeshModel/README.md) | Provides MESH_UNAVAILABLE, asList, routeTone, settledValue for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaPresentationContracts](modules/surface.neyviaPresentationContracts/README.md) | Provides checkPresentationAction for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaProductMode](modules/surface.neyviaProductMode/README.md) | Provides PRODUCT_MODE_CHAT, PRODUCT_MODE_ORCHESTRATION, PRODUCT_MODE_STORAGE_KEY, MANAGED_CLI_RUNTIME_OPTIONS for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaRecovery](modules/surface.neyviaRecovery/README.md) | Styles neyviaRecovery with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaRunActivity](modules/surface.neyviaRunActivity/README.md) | Provides safeReceiptHref, runDurationLabel, visibleRunActivityEvents, presentRunActivity for Neyvia's UI state and behavior. | agents |
| [surface.neyviaRuntimeInvocation](modules/surface.neyviaRuntimeInvocation/README.md) | Provides NEYVIA_RUNTIME_INVOCATION_SCHEMA, NEYVIA_INVOCATION_MODES, normalizeInvocationMode, invocationModeMeta for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaRuntimeStore](modules/surface.neyviaRuntimeStore/README.md) | Provides getRuntimeRegistry, subscribeRuntimeRegistry, loadRuntimeReadiness, getRuntimeReadiness for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaSchemaArguments](modules/surface.neyviaSchemaArguments/README.md) | Provides asSchemaRecord, schemaArgumentProperties, schemaRequiredArguments, buildSchemaArguments for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaSecurityRuntime](modules/surface.neyviaSecurityRuntime/README.md) | Styles neyviaSecurityRuntime with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaShellPreferences](modules/surface.neyviaShellPreferences/README.md) | Provides NEYVIA_SHELL_PREFERENCES_KEY, NEYVIA_SHELL_SURFACES, NEYVIA_UI_PRESETS, NEYVIA_APPEARANCE_THEMES for Neyvia's UI state and behavior. | settings |
| [surface.neyviaSignIn](modules/surface.neyviaSignIn/README.md) | Styles neyviaSignIn with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaSourceStore](modules/surface.neyviaSourceStore/README.md) | Styles neyviaSourceStore with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaSourceStoreModel](modules/surface.neyviaSourceStoreModel/README.md) | Provides shortVersion, storeState, kindLabel, sourceLabel for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaStorage](modules/surface.neyviaStorage/README.md) | Provides createNeyviaStorage, neyviaStorage for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaSubagents](modules/surface.neyviaSubagents/README.md) | Provides SUBAGENT_STATES, SUBAGENT_STATE_LABELS, BLOCKING_STATES, normalizeSubagent for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaSunMarkData](modules/surface.neyviaSunMarkData/README.md) | Provides NEYVIA_SUN_MARK for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaTasteReview](modules/surface.neyviaTasteReview/README.md) | Styles neyviaTasteReview with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaToolAvailability](modules/surface.neyviaToolAvailability/README.md) | Provides NEYVIA_WAVE1_TOOL_IDS, NEYVIA_CU_TOOL_IDS, NEYVIA_AVAILABILITY_FILTERS, classifyNeyviaToolTier for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaToolCallPresentation](modules/surface.neyviaToolCallPresentation/README.md) | Provides readJsonStringField, repairUtf16Text, toolFamily, parseUnifiedDiff for Neyvia's UI state and behavior. | agents |
| [surface.neyviaToolGlyphs](modules/surface.neyviaToolGlyphs/README.md) | Provides NeyviaGlyphResearch, NeyviaGlyphPdf, NeyviaGlyphTranslate, NeyviaGlyphGrammar for Neyvia's UI controls. | neyvia |
| [surface.neyviaToolVisuals](modules/surface.neyviaToolVisuals/README.md) | Provides NEYVIA_APP_ICON_PATHS, NEYVIA_FILE_TYPE_VISUALS, NEYVIA_TOOL_PHASE_CLASSES, NEYVIA_PANEL_ENTER_CLASSES for Neyvia's UI state and behavior. | agents |
| [surface.neyviaToolVisualsInventory](modules/surface.neyviaToolVisualsInventory/README.md) | Provides NEYVIA_INVENTORY_TOOL_VISUALS for Neyvia's UI state and behavior. | neyvia |
| [surface.neyviaWelcome](modules/surface.neyviaWelcome/README.md) | Styles neyviaWelcome with Neyvia's shared theme tokens. | neyvia |
| [surface.neyviaWorkflows](modules/surface.neyviaWorkflows/README.md) | Provides REQUIREMENT_LABELS, WORKFLOWS, suggestWorkflows, workflowAvailability for Neyvia's UI state and behavior. | neyvia |
| [surface.nxAccounts](modules/surface.nxAccounts/README.md) | Styles nxAccounts with Neyvia's shared theme tokens. | neyvia |
| [surface.nxAccountsModel](modules/surface.nxAccountsModel/README.md) | Provides USERNAME_PATTERN, PASSWORD_MIN, STRENGTH_LABELS, initials for Neyvia's UI state and behavior. | neyvia |
| [surface.nxAgentsApi](modules/surface.nxAgentsApi/README.md) | Provides conductorList, conductorGet, conductorControl, conductorPlan for Neyvia's UI state and behavior. | neyvia |
| [surface.nxAgentsOverview](modules/surface.nxAgentsOverview/README.md) | Styles nxAgentsOverview with Neyvia's shared theme tokens. | neyvia |
| [surface.nxAgentsOverviewApi](modules/surface.nxAgentsOverviewApi/README.md) | Provides useAgentsOverview, stopOverviewAgent for Neyvia's UI state and behavior. | neyvia |
| [surface.nxAgentsOverviewModel](modules/surface.nxAgentsOverviewModel/README.md) | Provides SOURCE_NAMES, STATE_NAMES, overviewGroups for Neyvia's UI state and behavior. | neyvia |
| [surface.nxAmplify](modules/surface.nxAmplify/README.md) | Styles nxAmplify with Neyvia's shared theme tokens. | neyvia |
| [surface.nxAmplifyModel](modules/surface.nxAmplifyModel/README.md) | Provides AUTO_SEND_MS, DEBOUNCE_MS, MIN_CHARS, MAX_TEXT for Neyvia's UI state and behavior. | neyvia |
| [surface.nxAnnounce](modules/surface.nxAnnounce/README.md) | Provides announce, useRunAnnouncer for Neyvia's UI state and behavior. | neyvia |
| [surface.nxApi](modules/surface.nxApi/README.md) | Provides isDesktopApp, backendBase, NxError, subscribeEvents for Neyvia's UI state and behavior. | neyvia |
| [surface.nxAppSkinModel](modules/surface.nxAppSkinModel/README.md) | Provides SKINS, THEME_IDS, skinTone, skinFor for Neyvia's UI state and behavior. | design |
| [surface.nxAppSkins](modules/surface.nxAppSkins/README.md) | Styles nxAppSkins with Neyvia's shared theme tokens. | neyvia |
| [surface.nxApps](modules/surface.nxApps/README.md) | Provides PLAN_SUITES, SHELL_APPS, normalizeRegistry, useApps for Neyvia's UI state and behavior. | neyvia |
| [surface.nxArrange](modules/surface.nxArrange/README.md) | Styles nxArrange with Neyvia's shared theme tokens. | neyvia |
| [surface.nxAutopilot](modules/surface.nxAutopilot/README.md) | Styles nxAutopilot with Neyvia's shared theme tokens. | neyvia |
| [surface.nxAutopilotModel](modules/surface.nxAutopilotModel/README.md) | Provides READ_TOOLS, SCOPES, statusOf, isLive for Neyvia's UI state and behavior. | autopilot |
| [surface.nxAwareness](modules/surface.nxAwareness/README.md) | Provides loadWorkBoard, releaseClaim, claimFiles, checkImpact for Neyvia's UI state and behavior. | neyvia |
| [surface.nxBrowser](modules/surface.nxBrowser/README.md) | Styles nxBrowser with Neyvia's shared theme tokens. | neyvia |
| [surface.nxBrowserApi](modules/surface.nxBrowserApi/README.md) | Provides useBrowser, useFastPoll, attachRuntime, setSlot for Neyvia's UI state and behavior. | neyvia |
| [surface.nxBrowserModel](modules/surface.nxBrowserModel/README.md) | Provides SEARCH_URL, parseAddress, hostOf, displayUrl for Neyvia's UI state and behavior. | neyvia |
| [surface.nxBubbles](modules/surface.nxBubbles/README.md) | Styles nxBubbles with Neyvia's shared theme tokens. | neyvia |
| [surface.nxBuilder](modules/surface.nxBuilder/README.md) | Styles nxBuilder with Neyvia's shared theme tokens. | neyvia |
| [surface.nxBus](modules/surface.nxBus/README.md) | Provides busClientId, approveUiRequest, ackPane, subscribeTimers for Neyvia's UI state and behavior. | neyvia |
| [surface.nxBusMock](modules/surface.nxBusMock/README.md) | Provides startMock, mockRegistry for Neyvia's UI state and behavior. | neyvia |
| [surface.nxChecklist](modules/surface.nxChecklist/README.md) | Styles nxChecklist with Neyvia's shared theme tokens. | neyvia |
| [surface.nxCommentAnchors](modules/surface.nxCommentAnchors/README.md) | Provides TARGET_ATTR, quoteOf, slashes, targetsIn for Neyvia's UI state and behavior. | neyvia |
| [surface.nxComments](modules/surface.nxComments/README.md) | Provides getComments, loadTarget, ensureTargets, useTargetComments for Neyvia's UI state and behavior. | neyvia |
| [surface.nxCommentsFixture](modules/surface.nxCommentsFixture/README.md) | Provides surface / nxCommentsFixture in Neyvia. | neyvia |
| [surface.nxComposerModel](modules/surface.nxComposerModel/README.md) | Provides MAX_IMAGES, MAX_IMAGE_CHARS, MAX_IMAGES_TOTAL_CHARS, IMAGE_TYPES for Neyvia's UI state and behavior. | neyvia |
| [surface.nxConductor](modules/surface.nxConductor/README.md) | Styles nxConductor with Neyvia's shared theme tokens. | neyvia |
| [surface.nxConductorModel](modules/surface.nxConductorModel/README.md) | Provides PROFILES, phaseOf, taskTone, conductorOf for Neyvia's UI state and behavior. | conductor |
| [surface.nxConnections](modules/surface.nxConnections/README.md) | Styles nxConnections with Neyvia's shared theme tokens. | neyvia |
| [surface.nxConnectionsModel](modules/surface.nxConnectionsModel/README.md) | Provides describeStep, mergeProof, connectionTone, connectionHeadline for Neyvia's UI state and behavior. | neyvia |
| [surface.nxCuaApi](modules/surface.nxCuaApi/README.md) | Provides demoRequested, switchToDemoDriver, isMissing for Neyvia's UI state and behavior. | neyvia |
| [surface.nxCuaFixture](modules/surface.nxCuaFixture/README.md) | Provides createDemoDriver for Neyvia's UI state and behavior. | neyvia |
| [surface.nxCuaModel](modules/surface.nxCuaModel/README.md) | Provides boxStyle, agentName, entryText, effectLabel for Neyvia's UI state and behavior. | computer-use |
| [surface.nxDashboard](modules/surface.nxDashboard/README.md) | Styles nxDashboard with Neyvia's shared theme tokens. | neyvia |
| [surface.nxDashboardModel](modules/surface.nxDashboardModel/README.md) | Provides WORKING, limitsByApp, limitPercent, providerStatus for Neyvia's UI state and behavior. | agents |
| [surface.nxDevFixtures](modules/surface.nxDevFixtures/README.md) | Provides surface / nxDevFixtures in Neyvia. | neyvia |
| [surface.nxDevVoiceFixture](modules/surface.nxDevVoiceFixture/README.md) | Provides fixtureVoice for Neyvia's UI state and behavior. | neyvia |
| [surface.nxDevicesModel](modules/surface.nxDevicesModel/README.md) | Provides LOCAL_DRAG, REMOTE_DRAG, dragSource, hasDrag for Neyvia's UI state and behavior. | cross-pc |
| [surface.nxDictation](modules/surface.nxDictation/README.md) | Provides RATE, prepareAudio, releaseMicNow, redecodeDictation for Neyvia's UI state and behavior. | neyvia |
| [surface.nxDictationContracts](modules/surface.nxDictationContracts/README.md) | Provides DictationContractError, DICTATION_CONTRACTS, checkedDictationAction for Neyvia's UI state and behavior. | neyvia |
| [surface.nxDictationEdit](modules/surface.nxDictationEdit/README.md) | Provides COMMAND_LABELS, LANGUAGE_LABELS, shiftAnchor, endsMidSentence for Neyvia's UI state and behavior. | dictation |
| [surface.nxDictationProviders](modules/surface.nxDictationProviders/README.md) | Provides providerChoices, providerSummary for Neyvia's UI state and behavior. | dictation |
| [surface.nxDictationReveal](modules/surface.nxDictationReveal/README.md) | Provides wordsShown, createReveal for Neyvia's UI state and behavior. | dictation |
| [surface.nxDockDrag](modules/surface.nxDockDrag/README.md) | Styles nxDockDrag with Neyvia's shared theme tokens. | neyvia |
| [surface.nxDocs](modules/surface.nxDocs/README.md) | Styles nxDocs with Neyvia's shared theme tokens. | design |
| [surface.nxDocsApi](modules/surface.nxDocsApi/README.md) | Provides notesCall, filesCall, devicesCall, deviceRawUrl for Neyvia's UI state and behavior. | neyvia |
| [surface.nxEmbedRoute](modules/surface.nxEmbedRoute/README.md) | Provides EMBED_EVENT, embeddedRoute for Neyvia's UI state and behavior. | neyvia |
| [surface.nxEvolver](modules/surface.nxEvolver/README.md) | Styles nxEvolver with Neyvia's shared theme tokens. | neyvia |
| [surface.nxEvolverModel](modules/surface.nxEvolverModel/README.md) | Provides splitDomain, familyInfo, groupFamilies, shortHash for Neyvia's UI state and behavior. | neyvia |
| [surface.nxFeedback](modules/surface.nxFeedback/README.md) | Styles nxFeedback with Neyvia's shared theme tokens. | neyvia |
| [surface.nxFeedbackModel](modules/surface.nxFeedbackModel/README.md) | Provides VERDICTS, MAX_REASON, asksFeedback, verdictLabel for Neyvia's UI state and behavior. | neyvia |
| [surface.nxFrameVisibility](modules/surface.nxFrameVisibility/README.md) | Provides frameVisibility for Neyvia's UI state and behavior. | neyvia |
| [surface.nxGameDev](modules/surface.nxGameDev/README.md) | Styles nxGameDev with Neyvia's shared theme tokens. | neyvia |
| [surface.nxGameDevModel](modules/surface.nxGameDevModel/README.md) | Provides ENGINE_TABS, APP_TABS, engineState, isBrowserScene for Neyvia's UI state and behavior. | game-dev |
| [surface.nxHome](modules/surface.nxHome/README.md) | Styles nxHome with Neyvia's shared theme tokens. | design |
| [surface.nxIdentities](modules/surface.nxIdentities/README.md) | Styles nxIdentities with Neyvia's shared theme tokens. | neyvia |
| [surface.nxLauncher](modules/surface.nxLauncher/README.md) | Styles nxLauncher with Neyvia's shared theme tokens. | neyvia |
| [surface.nxLauncherModel](modules/surface.nxLauncherModel/README.md) | Provides STARTABLE, score, parseNewChat, searchLauncher for Neyvia's UI state and behavior. | neyvia |
| [surface.nxLaya](modules/surface.nxLaya/README.md) | Styles nxLaya with Neyvia's shared theme tokens. | neyvia |
| [surface.nxLayaModel](modules/surface.nxLayaModel/README.md) | Provides formatTokens, formatMs, serviceView, stripView for Neyvia's UI state and behavior. | efficiency |
| [surface.nxLayoutModel](modules/surface.nxLayoutModel/README.md) | Provides REGIONS, REGION_LABELS, LIMITS, MAIN_MIN for Neyvia's UI state and behavior. | design |
| [surface.nxLegal](modules/surface.nxLegal/README.md) | Provides MARKS_NOTICE for Neyvia's UI state and behavior. | neyvia |
| [surface.nxLiveModel](modules/surface.nxLiveModel/README.md) | Provides POLL_MS, MAX_WAIT_TICKS, initialWatch, tick for Neyvia's UI state and behavior. | neyvia |
| [surface.nxLook](modules/surface.nxLook/README.md) | Styles nxLook with Neyvia's shared theme tokens. | neyvia |
| [surface.nxLookApi](modules/surface.nxLookApi/README.md) | Provides measure, useBackgroundImage, useLookView, lookAttributes for Neyvia's UI state and behavior. | neyvia |
| [surface.nxLookModel](modules/surface.nxLookModel/README.md) | Provides FONTS, FONT_IDS, TEXT_SIZES, BACKGROUND_KINDS for Neyvia's UI state and behavior. | neyvia |
| [surface.nxMemory](modules/surface.nxMemory/README.md) | Styles nxMemory with Neyvia's shared theme tokens. | neyvia |
| [surface.nxMissions](modules/surface.nxMissions/README.md) | Styles nxMissions with Neyvia's shared theme tokens. | neyvia |
| [surface.nxMissionsModel](modules/surface.nxMissionsModel/README.md) | Provides HARNESSES, harnessLabel, markForHarness, emptyDraft for Neyvia's UI state and behavior. | mission-plan |
| [surface.nxMobileStudio](modules/surface.nxMobileStudio/README.md) | Styles nxMobileStudio with Neyvia's shared theme tokens. | neyvia |
| [surface.nxModelContracts](modules/surface.nxModelContracts/README.md) | Provides ModelContractError, ACCOUNT_CONTRACTS, PDF_CONTRACTS, checkedModelAction for Neyvia's UI state and behavior. | neyvia |
| [surface.nxMorph](modules/surface.nxMorph/README.md) | Provides fadeTheme, morph for Neyvia's UI state and behavior. | neyvia |
| [surface.nxMotion](modules/surface.nxMotion/README.md) | Styles nxMotion with Neyvia's shared theme tokens. | neyvia |
| [surface.nxMotionFeatures](modules/surface.nxMotionFeatures/README.md) | Provides surface / nxMotionFeatures in Neyvia. | neyvia |
| [surface.nxNightShift](modules/surface.nxNightShift/README.md) | Styles nxNightShift with Neyvia's shared theme tokens. | neyvia |
| [surface.nxNightShiftApi](modules/surface.nxNightShiftApi/README.md) | Provides nightshift, useNightShift for Neyvia's UI state and behavior. | nightshift |
| [surface.nxNightShiftModel](modules/surface.nxNightShiftModel/README.md) | Provides STATES, OWNER_FOR, PERMISSIONS, MODEL_HINTS for Neyvia's UI state and behavior. | nightshift |
| [surface.nxOnboarding](modules/surface.nxOnboarding/README.md) | Styles nxOnboarding with Neyvia's shared theme tokens. | neyvia |
| [surface.nxOnboardingModel](modules/surface.nxOnboardingModel/README.md) | Provides STEPS, STEP_LABELS, stepFor, UNLOCKS for Neyvia's UI state and behavior. | onboarding |
| [surface.nxOs](modules/surface.nxOs/README.md) | Styles nxOs with Neyvia's shared theme tokens. | neyvia |
| [surface.nxOsStore](modules/surface.nxOsStore/README.md) | Provides DENSITIES, PANE_KINDS, holdSettingsLook, initialOsState for Neyvia's UI state and behavior. | design |
| [surface.nxOtherPcs](modules/surface.nxOtherPcs/README.md) | Styles nxOtherPcs with Neyvia's shared theme tokens. | neyvia |
| [surface.nxOutcomeObservation](modules/surface.nxOutcomeObservation/README.md) | Provides pdfOutcome, shellOutcomes for Neyvia's UI state and behavior. | design |
| [surface.nxOutputs](modules/surface.nxOutputs/README.md) | Styles nxOutputs with Neyvia's shared theme tokens. | neyvia |
| [surface.nxOutputsApi](modules/surface.nxOutputsApi/README.md) | Provides OUTPUT_KINDS, KIND_LABELS, KIND_ONE, outputsCall for Neyvia's UI state and behavior. | neyvia |
| [surface.nxOutputsModel](modules/surface.nxOutputsModel/README.md) | Provides layerForOutput, outline, approxTokens, perceptionTarget for Neyvia's UI state and behavior. | outputs |
| [surface.nxPaneObserve](modules/surface.nxPaneObserve/README.md) | Provides HEARTBEAT_MS, SETTLE_MS, normalizeText, projectText for Neyvia's UI state and behavior. | neyvia |
| [surface.nxPanes](modules/surface.nxPanes/README.md) | Styles nxPanes with Neyvia's shared theme tokens. | neyvia |
| [surface.nxPanesApi](modules/surface.nxPanesApi/README.md) | Provides panesCall, terminalStreamUrl, backendUrl, isUrl for Neyvia's UI state and behavior. | neyvia |
| [surface.nxParallel](modules/surface.nxParallel/README.md) | Styles nxParallel with Neyvia's shared theme tokens. | neyvia |
| [surface.nxParallelApi](modules/surface.nxParallelApi/README.md) | Provides surface / nxParallelApi in Neyvia. | neyvia |
| [surface.nxParallelFixture](modules/surface.nxParallelFixture/README.md) | Provides fixtureParallelRead, fixtureParallelAction for Neyvia's UI state and behavior. | neyvia |
| [surface.nxParallelModel](modules/surface.nxParallelModel/README.md) | Provides RUN_LABEL, RUN_TONE, LANE_LABEL, LANE_TONE for Neyvia's UI state and behavior. | neyvia |
| [surface.nxPdf](modules/surface.nxPdf/README.md) | Styles nxPdf with Neyvia's shared theme tokens. | neyvia |
| [surface.nxPdfModel](modules/surface.nxPdfModel/README.md) | Provides loadPdfjs, rectsForText, toBox, selectionRects for Neyvia's UI state and behavior. | pdf |
| [surface.nxPlacement](modules/surface.nxPlacement/README.md) | Styles nxPlacement with Neyvia's shared theme tokens. | design |
| [surface.nxPlacementModel](modules/surface.nxPlacementModel/README.md) | Provides PLACEMENTS, PLACEMENT_LABELS, MAX_BUBBLES, prefKey for Neyvia's UI state and behavior. | design |
| [surface.nxPlanModel](modules/surface.nxPlanModel/README.md) | Provides applyPlanOp, planOf, planProgress, showChecklist for Neyvia's UI state and behavior. | agents |
| [surface.nxPopout](modules/surface.nxPopout/README.md) | Provides POPOUT_HINT, POPOUT_KEY, usePopout, getPopout for Neyvia's UI state and behavior. | neyvia |
| [surface.nxPreview](modules/surface.nxPreview/README.md) | Styles nxPreview with Neyvia's shared theme tokens. | neyvia |
| [surface.nxPrimitives](modules/surface.nxPrimitives/README.md) | Provides portalLook, useFocusTrap, Icon, Button for Neyvia's UI controls. | design |
| [surface.nxProofsEContracts](modules/surface.nxProofsEContracts/README.md) | Provides ProofsEContractError, same, PROOFS_E_MODEL_CONTRACTS, observeProofsEModels for Neyvia's UI state and behavior. | neyvia |
| [surface.nxProofsEShellContracts](modules/surface.nxProofsEShellContracts/README.md) | Provides checkSidebar, checkInitial, checkOverrides, checkUiAction for Neyvia's UI state and behavior. | neyvia |
| [surface.nxProviderMarkContracts](modules/surface.nxProviderMarkContracts/README.md) | Provides checkProviderRegistry, checkProviderResolution, checkProviderTree, checkProviderSvg for Neyvia's UI state and behavior. | design |
| [surface.nxRemote](modules/surface.nxRemote/README.md) | Styles nxRemote with Neyvia's shared theme tokens. | neyvia |
| [surface.nxRemoteApi](modules/surface.nxRemoteApi/README.md) | Provides RemoteError, remoteCall, remoteState, remoteTargets for Neyvia's UI state and behavior. | neyvia |
| [surface.nxRemoteModel](modules/surface.nxRemoteModel/README.md) | Provides REMOTE_KEYS, remoteKey, textBoxAt, scrollerAt for Neyvia's UI state and behavior. | neyvia |
| [surface.nxReplay](modules/surface.nxReplay/README.md) | Styles nxReplay with Neyvia's shared theme tokens. | neyvia |
| [surface.nxReplayModel](modules/surface.nxReplayModel/README.md) | Provides SPEEDS, IDLE_CAP_MS, buildTimeline, visibleCount for Neyvia's UI state and behavior. | agents |
| [surface.nxRuntimeModel](modules/surface.nxRuntimeModel/README.md) | Provides POLICY_APPS, CEILINGS, mergeRuntimes, runtimeSummary for Neyvia's UI state and behavior. | settings |
| [surface.nxSessions](modules/surface.nxSessions/README.md) | Styles nxSessions with Neyvia's shared theme tokens. | neyvia |
| [surface.nxSettings](modules/surface.nxSettings/README.md) | Styles nxSettings with Neyvia's shared theme tokens. | neyvia |
| [surface.nxSettingsApi](modules/surface.nxSettingsApi/README.md) | Provides INITIATIVE, backendThemeLabel, explainSettingsError, saveSettings for Neyvia's UI state and behavior. | outputs |
| [surface.nxShell](modules/surface.nxShell/README.md) | Styles nxShell with Neyvia's shared theme tokens. | design |
| [surface.nxShellLauncher](modules/surface.nxShellLauncher/README.md) | Provides launcherProjects, launcherActions, runInterfaceAction for Neyvia's UI state and behavior. | neyvia |
| [surface.nxShellObserve](modules/surface.nxShellObserve/README.md) | Provides shellDelivered, shellReady, useShellObservation for Neyvia's UI state and behavior. | design |
| [surface.nxSidebar](modules/surface.nxSidebar/README.md) | Styles nxSidebar with Neyvia's shared theme tokens. | neyvia |
| [surface.nxSidebarModel](modules/surface.nxSidebarModel/README.md) | Provides DEFAULT_CLEANUP, CLI_BRANCH, cliBranch, basename for Neyvia's UI state and behavior. | sidebar |
| [surface.nxSidebarObserve](modules/surface.nxSidebarObserve/README.md) | Provides useObserved, getObserved, rememberFolders, observeRows for Neyvia's UI state and behavior. | neyvia |
| [surface.nxSpring](modules/surface.nxSpring/README.md) | Provides SPRING for Neyvia's UI state and behavior. | neyvia |
| [surface.nxStore](modules/surface.nxStore/README.md) | Provides isRunActive, useNx, getNx, insertItem for Neyvia's UI state and behavior. | neyvia |
| [surface.nxSun](modules/surface.nxSun/README.md) | Provides SUN_TICK_MS, useSunState, useShownTheme, useSunSetting for Neyvia's UI state and behavior. | neyvia |
| [surface.nxSunModel](modules/surface.nxSunModel/README.md) | Provides BLEND_MINUTES, minutesOfDay, dayPartAt, daylightAt for Neyvia's UI state and behavior. | neyvia |
| [surface.nxSurfaceSize](modules/surface.nxSurfaceSize/README.md) | Provides COMPACT_PX, SurfaceSize, useSurfaceSize for Neyvia's UI state and behavior. | neyvia |
| [surface.nxThemeRegistry](modules/surface.nxThemeRegistry/README.md) | Provides THEME_REGISTRY, THEMES, DEFAULT_THEME, THEME_LABELS for Neyvia's UI state and behavior. | neyvia |
| [surface.nxThemes](modules/surface.nxThemes/README.md) | Styles nxThemes with Neyvia's shared theme tokens. | design |
| [surface.nxTokens](modules/surface.nxTokens/README.md) | Styles nxTokens with Neyvia's shared theme tokens. | design |
| [surface.nxToolScreens](modules/surface.nxToolScreens/README.md) | Styles nxToolScreens with Neyvia's shared theme tokens. | neyvia |
| [surface.nxToolShared](modules/surface.nxToolShared/README.md) | Styles nxToolShared with Neyvia's shared theme tokens. | neyvia |
| [surface.nxTransparencyModel](modules/surface.nxTransparencyModel/README.md) | Provides TRANSPARENCY_LEVELS, TRANSPARENCY_LABELS, stripAnsi, toolFailed for Neyvia's UI state and behavior. | neyvia |
| [surface.nxTree](modules/surface.nxTree/README.md) | Styles nxTree with Neyvia's shared theme tokens. | neyvia |
| [surface.nxUsage](modules/surface.nxUsage/README.md) | Styles nxUsage with Neyvia's shared theme tokens. | neyvia |
| [surface.nxUsageModel](modules/surface.nxUsageModel/README.md) | Provides RANGES, APP_ORDER, appName, agentName for Neyvia's UI state and behavior. | neyvia |
| [surface.nxVoice](modules/surface.nxVoice/README.md) | Provides VOICE_GRAMMAR, voiceContext, isVoiceUnavailable, loadVoiceCommands for Neyvia's UI state and behavior. | neyvia |
| [surface.nxWorkspace](modules/surface.nxWorkspace/README.md) | Styles nxWorkspace with Neyvia's shared theme tokens. | neyvia |
| [surface.nxWorkspaceHooks](modules/surface.nxWorkspaceHooks/README.md) | Provides rememberCommit, recallCommit, useWorkspace, useFileDiff for Neyvia's UI state and behavior. | neyvia |
| [surface.nxWorkspaceModel](modules/surface.nxWorkspaceModel/README.md) | Provides statusOf, isCommittable, splitPath, splitPathTail for Neyvia's UI state and behavior. | neyvia |
| [surface.pollingModel](modules/surface.pollingModel/README.md) | Provides createPoller for Neyvia's UI state and behavior. | neyvia |
| [surface.promptFileImport](modules/surface.promptFileImport/README.md) | Provides MAX_PROMPT_CHARACTERS, MAX_PROMPT_FILE_BYTES for Neyvia's UI state and behavior. | neyvia |
| [surface.proofsBViewContracts](modules/surface.proofsBViewContracts/README.md) | Provides checkHarnessView for Neyvia's UI state and behavior. | proofs-b-browser |
| [surface.providerMark](modules/surface.providerMark/README.md) | Styles providerMark with Neyvia's shared theme tokens. | neyvia |
| [surface.providerMarkModel](modules/surface.providerMarkModel/README.md) | Provides serializeSvgNode, describeProviderMark, providerMarkSvgString for Neyvia's UI state and behavior. | design |
| [surface.providerMarksData](modules/surface.providerMarksData/README.md) | Provides PROVIDER_MARKS, providerMarkIds, resolveProviderMarkId for Neyvia's UI state and behavior. | design |
| [surface.providerModelCatalog](modules/surface.providerModelCatalog/README.md) | Provides OPENCODE_GO_CATALOG_SOURCE, OPENCODE_GO_CATALOG_CHECKED_AT, MANAGED_CLI_CATALOG_CHECKED_AT, ASTRA_CATALOG_CHECKED_AT for Neyvia's UI state and behavior. | neyvia |
| [surface.transcriptVisibility](modules/surface.transcriptVisibility/README.md) | Provides REAL_AGENT_DIALOGUE_SOURCES, REAL_RUNTIME_REPLY_SOURCES, TRANSCRIPT_ROLES, isRealAgentDialogueSource for Neyvia's UI state and behavior. | agents |
| [surface.useGameDevReceipts](modules/surface.useGameDevReceipts/README.md) | Provides useReceipts for Neyvia's UI state and behavior. | neyvia |
| [surface.usePoller](modules/surface.usePoller/README.md) | Provides usePoller for Neyvia's UI state and behavior. | neyvia |
| [surface.workspaceModel](modules/surface.workspaceModel/README.md) | Provides WORKSPACE_SURFACES, WORKSPACE_SURFACE_IDS, AGENT_STATUS_DEFINITIONS, ROUTE_ROLE_OPTIONS for Neyvia's UI state and behavior. | agents |
| [surface.workspaceToolAccess](modules/surface.workspaceToolAccess/README.md) | Provides WORKSPACE_PERMISSION_MODES, WORKSPACE_PERMISSION_STORAGE_KEY, normalizeWorkspacePermissionMode, workspacePermissionAllowsTools for Neyvia's UI state and behavior. | workspace |
| [template.latex.neyvia-study.examples.course-example](modules/template.latex.neyvia-study.examples.course-example/README.md) | Provides template / latex / neyvia-study / examples / course-example in Neyvia. | neyvia |
| [template.latex.neyvia-study.examples.sheet-example](modules/template.latex.neyvia-study.examples.sheet-example/README.md) | Provides template / latex / neyvia-study / examples / sheet-example in Neyvia. | neyvia |
| [template.latex.neyvia-study.fonts.Inter-ExtraBold](modules/template.latex.neyvia-study.fonts.Inter-ExtraBold/README.md) | Provides template / latex / neyvia-study / fonts / Inter-ExtraBold in Neyvia. | neyvia |
| [template.latex.neyvia-study.fonts.Inter-ExtraBoldItalic](modules/template.latex.neyvia-study.fonts.Inter-ExtraBoldItalic/README.md) | Provides template / latex / neyvia-study / fonts / Inter-ExtraBoldItalic in Neyvia. | neyvia |
| [template.latex.neyvia-study.fonts.Inter-Italic](modules/template.latex.neyvia-study.fonts.Inter-Italic/README.md) | Provides template / latex / neyvia-study / fonts / Inter-Italic in Neyvia. | neyvia |
| [template.latex.neyvia-study.fonts.Inter-Regular](modules/template.latex.neyvia-study.fonts.Inter-Regular/README.md) | Provides template / latex / neyvia-study / fonts / Inter-Regular in Neyvia. | neyvia |
| [template.latex.neyvia-study.neyvia-study](modules/template.latex.neyvia-study.neyvia-study/README.md) | Provides template / latex / neyvia-study / neyvia-study in Neyvia. | neyvia |
| [template.latex.neyvia-study.ports.la-course-ch1](modules/template.latex.neyvia-study.ports.la-course-ch1/README.md) | Provides template / latex / neyvia-study / ports / la-course-ch1 in Neyvia. | neyvia |
| [template.latex.neyvia-study.ports.la-sheet-ch1](modules/template.latex.neyvia-study.ports.la-sheet-ch1/README.md) | Provides template / latex / neyvia-study / ports / la-sheet-ch1 in Neyvia. | neyvia |
| [template.neyvia-app.host-contract](modules/template.neyvia-app.host-contract/README.md) | Provides template / neyvia-app / host-contract in Neyvia. | neyvia |
| [template.neyvia-app.manual](modules/template.neyvia-app.manual/README.md) | Provides template / neyvia-app / manual in Neyvia. | neyvia |
| [template.neyvia-app.neyvia.app](modules/template.neyvia-app.neyvia.app/README.md) | Provides template / neyvia-app / neyvia / app in Neyvia. | neyvia |
| [template.neyvia-app.www.app](modules/template.neyvia-app.www.app/README.md) | Provides template / neyvia-app / www / app in Neyvia. | neyvia |
| [template.neyvia-app.www.index](modules/template.neyvia-app.www.index/README.md) | Provides template / neyvia-app / www / index in Neyvia. | neyvia |
| [template.neyvia-module.greeting](modules/template.neyvia-module.greeting/README.md) | Example optional mod: deterministic personal greeting, without side effects. | neyvia |
| [template.neyvia-module.host-contract](modules/template.neyvia-module.host-contract/README.md) | Provides template / neyvia-module / host-contract in Neyvia. | neyvia |
| [template.neyvia-module.manual](modules/template.neyvia-module.manual/README.md) | Provides template / neyvia-module / manual in Neyvia. | neyvia |
| [template.neyvia-module.neyvia.module](modules/template.neyvia-module.neyvia.module/README.md) | Provides template / neyvia-module / neyvia / module in Neyvia. | neyvia |
| [tool.card-console.server](modules/tool.card-console.server/README.md) | Card Console -- read-only bench dashboard for NFC/RFID hardware. | neyvia |
| [tool.card-console.static.app](modules/tool.card-console.static.app/README.md) | Provides tool / card-console / static / app in Neyvia. | neyvia |
| [tool.card-console.static.index](modules/tool.card-console.static.index/README.md) | Provides tool / card-console / static / index in Neyvia. | neyvia |
| [tool.card-console.static.styles](modules/tool.card-console.static.styles/README.md) | Styles styles with Neyvia's shared theme tokens. | neyvia |
| [tool.cua-driver-win.NativeWorker](modules/tool.cua-driver-win.NativeWorker/README.md) | Provides tool / cua-driver-win / NativeWorker in Neyvia. | neyvia |
| [tool.cua-driver-win.c1-probe](modules/tool.cua-driver-win.c1-probe/README.md) | Provides tool / cua-driver-win / c1-probe in Neyvia. | neyvia |
| [tool.cua-driver-win.driver](modules/tool.cua-driver-win.driver/README.md) | Provides tool / cua-driver-win / driver in Neyvia. | neyvia |
| [tool.cua-driver-win.json-host](modules/tool.cua-driver-win.json-host/README.md) | Provides tool / cua-driver-win / json-host in Neyvia. | neyvia |
| [tool.cua-driver-win.parked-hook](modules/tool.cua-driver-win.parked-hook/README.md) | Provides tool / cua-driver-win / parked-hook in Neyvia. | neyvia |
| [tool.cua-driver-win.parked-probe](modules/tool.cua-driver-win.parked-probe/README.md) | Provides tool / cua-driver-win / parked-probe in Neyvia. | neyvia |
| [tool.cua-driver-win.probe](modules/tool.cua-driver-win.probe/README.md) | Provides tool / cua-driver-win / probe in Neyvia. | neyvia |
| [tool.cua-driver-win.remote-indicator](modules/tool.cua-driver-win.remote-indicator/README.md) | Provides tool / cua-driver-win / remote-indicator in Neyvia. | neyvia |
| [tool.cua-driver-win.remote-probe](modules/tool.cua-driver-win.remote-probe/README.md) | Provides tool / cua-driver-win / remote-probe in Neyvia. | neyvia |
| [tool.cua-driver-win.stdio-host](modules/tool.cua-driver-win.stdio-host/README.md) | Provides tool / cua-driver-win / stdio-host in Neyvia. | neyvia |
| [tool.dictation_stream_timeline](modules/tool.dictation_stream_timeline/README.md) | Feed a recorded 16 kHz mono WAV through Neyvia's dictation stream as if it were a live microphone and print | neyvia |
| [tool.laya.calibration-base](modules/tool.laya.calibration-base/README.md) | Provides tool / laya / calibration-base in Neyvia. | neyvia |
| [tool.laya.capabilities.component-notes](modules/tool.laya.capabilities.component-notes/README.md) | Provides tool / laya / capabilities / component-notes in Neyvia. | neyvia |
| [tool.laya.capabilities.components](modules/tool.laya.capabilities.components/README.md) | Provides tool / laya / capabilities / components in Neyvia. | neyvia |
| [tool.laya.capabilities.layout-head](modules/tool.laya.capabilities.layout-head/README.md) | Provides tool / laya / capabilities / layout-head in Neyvia. | neyvia |
| [tool.laya.capabilities.manual-router](modules/tool.laya.capabilities.manual-router/README.md) | Provides tool / laya / capabilities / manual-router in Neyvia. | neyvia |
| [tool.laya.capabilities.receipt-outcome](modules/tool.laya.capabilities.receipt-outcome/README.md) | Provides tool / laya / capabilities / receipt-outcome in Neyvia. | neyvia |
| [tool.laya.laya.__init__](modules/tool.laya.laya.__init__/README.md) | Laya: Fast, non-autoregressive System 1 decision engine with calibrated probabilities. | neyvia |
| [tool.laya.laya.agent](modules/tool.laya.laya.agent/README.md) | High-level inference runtime for laya System 1 decision models. | neyvia |
| [tool.laya.laya.common](modules/tool.laya.laya.common/README.md) | Core model architecture, token sequence construction, and confidence estimation for laya. | neyvia |
| [tool.laya.laya.email](modules/tool.laya.laya.email/README.md) | Email utilities for cleaning and structuring email inputs in laya. | neyvia |
| [tool.laya.laya.lang](modules/tool.laya.laya.lang/README.md) | Dependency-free language/script detection used to route between Laya checkpoints. | neyvia |
| [tool.laya.laya.presets](modules/tool.laya.laya.presets/README.md) | Ready-to-use question presets for common production decision workflows. | neyvia |
| [tool.laya.laya.router](modules/tool.laya.laya.router/README.md) | Route a request to the Laya checkpoint best suited to it. | neyvia |
| [tool.laya.laya_system1.__init__](modules/tool.laya.laya_system1.__init__/README.md) | Local, frozen-weight LAYA typed decisions and scoped instant adaptation. | neyvia |
| [tool.laya.laya_system1.browser_client](modules/tool.laya.laya_system1.browser_client/README.md) | Small adapter for the merged T20 two-argument advisory provider hook. | neyvia |
| [tool.laya.laya_system1.contracts](modules/tool.laya.laya_system1.contracts/README.md) | Versioned typed decisions and an injectable T20 hook; no app dependencies. | neyvia |
| [tool.laya.laya_system1.evolved_state](modules/tool.laya.laya_system1.evolved_state/README.md) | Executable R3 descendants with conditional, distilled typed heads. | neyvia |
| [tool.laya.laya_system1.memory](modules/tool.laya.laya_system1.memory/README.md) | Append-only correction log and deterministic, checkpoint-scoped memory views. | neyvia |
| [tool.laya.laya_system1.round5_state](modules/tool.laya.laya_system1.round5_state/README.md) | Train-bound R5 CPU heads, solved-case retrieval and frozen R2 corrections. | neyvia |
| [tool.laya.laya_system1.runtime](modules/tool.laya.laya_system1.runtime/README.md) | Prepared frozen LAYA inference, with option-aligned adaptation fingerprints. | neyvia |
| [tool.laya.laya_system1.service](modules/tool.laya.laya_system1.service/README.md) | Local System One HTTP service. Frozen model predictions plus reversible memory. | neyvia |
| [tool.laya.laya_system1.shared_state](modules/tool.laya.laya_system1.shared_state/README.md) | CPU shared-state typed evidence network; no runtime transformer or downloads. | neyvia |
| [tool.laya.route_vocab](modules/tool.laya.route_vocab/README.md) | Provides tool / laya / route_vocab in Neyvia. | neyvia |
| [tool.neyvia-iroh-cache.Cargo](modules/tool.neyvia-iroh-cache.Cargo/README.md) | Provides tool / neyvia-iroh-cache / Cargo in Neyvia. | neyvia |
| [tool.neyvia-iroh-cache.src.main](modules/tool.neyvia-iroh-cache.src.main/README.md) | Provides tool / neyvia-iroh-cache / src / main in Neyvia. | neyvia |
| [web.basePackGate](modules/web.basePackGate/README.md) | Provides web / basePackGate in Neyvia. | neyvia |
| [web.main](modules/web.main/README.md) | Provides web / main in Neyvia. | neyvia |
| [web.pwa](modules/web.pwa/README.md) | Provides web / pwa in Neyvia. | neyvia |
| [web.workspace](modules/web.workspace/README.md) | Provides web / workspace in Neyvia. | neyvia |
