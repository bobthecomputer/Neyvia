# FrontierAgent integration audit — 2026-08-25

## Decision

Neyvia should reuse FrontierAgent's strongest supervision contracts, not embed a second product shell or copy its workflow engine. FrontierAgent is a Python 3.12 runtime/TUI whose native workflows are Stateful ReAct and Agent Team. Neyvia already owns the durable mission graph, attention inbox, runtime adapters, context reader, receipts, and desktop/mobile shell. Running both schedulers inside one mission would create competing sources of truth.

Source reviewed: <https://github.com/ApodexAI/FrontierAgent>

## Accepted mappings

| FrontierAgent idea | Neyvia implementation | Evidence |
| --- | --- | --- |
| Live task board with pending, active, completed, blocked, and cancelled states | Attention inbox plus orchestration constellation/timeline | `NeyviaAttentionInbox.jsx`, `NeyviaProductModePanels.jsx` |
| Task-scoped read-only inputs, working files, and controlled outputs | Direct read-only mirror versus orchestration workspace writes | `harness_jobs.py`, `harness_job_worker.py`, Harness control mode selector |
| Local action trace and persistent deliverables | Durable harness job record, terminal receipt, mission events, artifacts | Harness control durable queue and receipt console |
| Approval before mutations | Neyvia approval modes and security-only campaign acknowledgement | Rook acknowledgement and existing approval gates |
| Retry/recovery without losing the original request | Terminal run restores its saved objective into the composer for an explicit new run | Harness control **Retry** action |
| Bounded coordinator plus independent executor/verifier evidence | Four-lane route: Neyvia context reader, GPT-5.6 Sol planner, selected harness executor, GPT-5.6 Sol verifier | Harness control route strip and durable request route overrides |

## Deliberately deferred

- **True checkpoint resume:** Neyvia's current Harness control can restore and retry a terminal request, but it cannot yet resume inside an arbitrary external CLI turn. The UI must continue to say **Retry**, not **Resume**, until an adapter returns a verified checkpoint identifier and the worker can reattach to it.
- **Safe-boundary live steering:** FrontierAgent queues new instructions at a safe turn boundary. Neyvia has operator steering concepts elsewhere, but Harness control has no durable per-job steering command yet. No steering button should appear until the backend owns an inbox record and acknowledges which step consumed it.
- **Importing FrontierAgent as another default harness:** the current release targets macOS/Linux and WSL2 for Windows. It is useful as an optional future adapter, not a required Windows desktop dependency.
- **Copying its benchmark scores into Neyvia claims:** upstream benchmark results describe Apodex configurations, not Neyvia. Neyvia must produce its own comparable receipts before making performance claims.

## Release gates derived from the audit

1. A run labelled `running` must have a live worker or a durable recovery state.
2. Every retry creates a new run id; it never rewrites an earlier receipt.
3. Direct mode remains unable to write into the registered workspace.
4. Security-only harnesses require explicit authorization and stay in the executor lane.
5. Model/provider labels come from the recorded route; missing metadata is shown as not recorded.
6. Resume and live steering remain absent until proved end to end.

## OpenCode Go route status

Local workstation authentication is not authoritative for the NAS runtime. A direct NAS verification on 2026-08-25 found `hermes auth status opencode-go` logged in, exposed the current `opencode-go/*` catalog including `opencode-go/deepseek-v4-pro`, and completed a genuine DeepSeek V4 Pro marker turn with exit code 0. The secret remained in the gitignored NAS provider store and was not printed; `.agent_control/runtime_proof/nas-opencode-go-auth-live.json` contains the redacted receipt. OpenRouter was not substituted. Tool-call and multi-turn acceptance remain distinct proof gates and must not be inferred from the successful single-turn route check.
