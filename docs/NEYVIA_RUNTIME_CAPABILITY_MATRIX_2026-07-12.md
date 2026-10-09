# Neyvia runtime capability matrix, July 12, 2026

Legend: `yes` means verified in the implementation, `linked` means available
through a selected worker, `partial` means some contract is implemented but an
end-to-end gate remains, and `no` means it should not be claimed.

| Capability | Neyvia | Codex | Hermes | OpenClaw | OpenCode | Neyvia decision |
| --- | --- | --- | --- | --- | --- | --- |
| Typed compact orchestration IR | yes | no public equivalent | no public equivalent | no public equivalent | no public equivalent | Keep `NEYVIA/1` as the provider-independent control contract |
| Validated dependency DAG | yes | thread goals/forks | delegated tasks | multi-agent routing | parent/child sessions | Compile before dispatch; keep runtime delegation bounded |
| Durable full-history ledger | yes | persisted threads | persisted sessions | on-disk transcript | persisted sessions | Keep provider-independent SQLite evidence |
| Protected recent context | yes | compaction | yes | yes | yes | Preserve a token tail, not only a message count |
| Archived-context retrieval | yes | paged thread reads | session search/context engines | memory and context engines | plugin ecosystem | Search archived evidence by query, id, and hash |
| Tool-output pruning/spill | yes | partial through compaction | yes | yes | configurable pruning | Spill full output to artifacts and send bounded previews |
| Pluggable compaction | yes, Python strategy | app-server compaction trigger | yes | yes | plugin hook | Keep local strategy pluggable and provider compaction optional |
| Server-side OpenAI compaction | yes, optional request field | yes | provider-dependent | documented integration | provider-dependent | Preserve opaque items exactly when this route is selected |
| Prompt-cache-aware assembly | partial | provider-managed | yes | yes | provider options | Stable prefix is identified; general cache-control emission remains |
| Progressive tool schemas | yes | tool search | yes | yes | tool registry | Search metadata first, describe exactly one schema next |
| Progressive skills | yes, metadata-first | yes | yes | yes | yes | Never inject 132 full imported skill bodies into one prompt |
| Personal Codex skill import | yes | source | no | no | Claude compatibility only | Snapshot safely, disabled until reviewed |
| Codex plugin discovery | yes, linked metadata | yes | separate plugin system | separate plugin system | separate plugin system | Do not pretend cached plugins are native Neyvia tools |
| Apps/connectors | partial | yes | MCP/plugins | channels/plugins | MCP/plugins | Add adapters only with callable auth and receipts |
| MCP status and calls | linked | yes | yes | yes | yes | Current importer records names only; native broker remains a gap |
| Lifecycle hooks | partial existing runtime events | yes | yes | yes | yes | Add one policy-governed hook bus rather than runtime-specific hooks |
| LSP/code intelligence | linked through OpenCode | coding tools | tools/plugins | tools/plugins | yes | Keep OpenCode as the current LSP worker |
| Worktree isolation | yes | yes | yes | workspace-based | session/worktree context | Continue proof-gated isolated mutation |
| Snapshots and rollback | partial | thread fork/rollback | checkpoints | successor transcripts | file snapshots | Add plan-stage checkpoint rollback receipts |
| Browser and screenshots | yes | yes | yes | yes | tool-dependent | Keep native deterministic screenshot proof |
| Video understanding bridge | yes | image input, no direct video for GPT-5.6 Sol | native video tool | tools/plugins | tool-dependent | Keep filtered storyboard plus transcript and optional semantic worker |
| Fast NAS artifacts/messages | yes | no project-specific equivalent | no project-specific equivalent | no project-specific equivalent | no project-specific equivalent | Keep content-addressed resumable transport |

## Highest-priority remaining gaps

1. Feed exact provider-reported prompt token usage into every context ledger.
2. Add a policy-governed hook bus for pre/post tool, pre/post model, compaction,
   checkpoint, and verifier events.
3. Broker callable Codex apps and MCP servers with auth-state and approval
   receipts instead of metadata-only linking.
4. Execute `NEYVIA/1` stages directly in the scheduler with best-checkpoint
   rollback when a repair decreases verification score.
5. Add route-neutral prompt-cache emission while preserving each provider's
   cache semantics.
6. Benchmark the same long-horizon mission across Neyvia native, Codex App
   Server, Hermes, OpenClaw, and OpenCode under equal budgets.

