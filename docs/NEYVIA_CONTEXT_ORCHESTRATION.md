# Neyvia context and orchestration runtime

## Outcome

Neyvia now separates durable project continuity from the finite context sent to
one model call.

```text
events, tool output, decisions, and proof
                    |
                    v
          durable context ledger
       full history + hashes + artifacts
                    |
          relevance and policy selection
                    |
                    v
 stable prefix + retrieved evidence + recent tail
                    |
            bounded model context
```

This is the practical meaning of long or effectively unbounded context. The
ledger can keep growing, but every model request still respects that model's
finite input, output, and reasoning-token limit.

## Durable context engine

`DurableContextEngine` stores mission history in SQLite under:

```text
.agent_control/context/<session-id>/ledger.sqlite3
```

It provides:

- API-reported token counts when the caller has them, with a local estimate as
  fallback
- a protected recent-token tail
- pinned goals, contracts, decisions, blockers, risks, verification, and
  checkpoints
- relevance search across active and archived evidence
- content hashes and event identifiers that survive repeated compaction
- large tool-output spill to content-addressed files
- a pluggable compaction strategy interface
- machine-readable compaction receipts
- stable-prefix and complete-bundle cache keys
- a bounded context bundle with provenance for every included item

Compaction archives older events rather than deleting them. A later query can
retrieve an archived tool result or decision into a new context bundle.

The default compactor is deterministic and extractive. A model-backed or remote
lossless compactor can implement the same `ContextCompactionStrategy` protocol
without replacing the ledger or retrieval layer.

## Provider-side compaction

Neyvia's OpenAI request builder can add:

```json
{
  "context_management": [
    {"type": "compaction", "compact_threshold": 180000}
  ]
}
```

This complements the local ledger. OpenAI server-side compaction carries an
opaque compaction item forward, while the Neyvia ledger remains inspectable and
provider-independent. With stateless request chaining, the returned compaction
item must be preserved. With `previous_response_id`, callers should not prune
the server-managed chain manually.

## NEYVIA/1 orchestration language

`NEYVIA/1` is a compact mission IR, not a general programming language. It
exists so planning does not have to be recovered from prose.

It describes:

- one immutable goal
- explicit context, reserve, wall-time, and repair budgets
- runtime/model/effort lanes
- tool and runtime steps
- dependency edges
- mutability and approval requirements
- acceptance criteria and proof outputs
- stop conditions

Example:

```text
NEYVIA/1
GOAL text="Implement reconnect support with proof"
BUDGET context=400000 reserve=20000 wall=3600 repairs=2
LANE planner runtime=codex model=gpt-5.6-sol effort=low permissions=read,search
LANE executor runtime=hermes model=gpt-5.6-sol effort=low permissions=read,write,shell
LANE verifier runtime=codex model=gpt-5.6-luna effort=xhigh permissions=read,shell,browser
STEP inspect lane=planner action=tool tool=workspace.search risk=read args='{"query":"reconnect"}' output=evidence.json
STEP implement lane=executor action=runtime after=inspect risk=workspace_write output=patch.diff accept="AC-1"
VERIFY test lane=verifier after=implement command="pytest tests/reconnect -q" output=test.log
STOP when="all acceptance criteria pass"
```

The compiler rejects unknown lanes, dependencies, duplicate identifiers,
self-dependencies, cycles, invalid risk classes, and tool steps without a tool.
It emits topological execution stages, permission envelopes, proof requirements,
a canonical plan hash, and a compact token estimate.

`mission-start --orchestration-file` attaches the compiled program to the
mission contract and timeline. Workers therefore receive the validated plan
instead of an unverified block of orchestration prose.

## Codex asset import

Neyvia can inventory and import safe parts of the local Codex environment:

- personal `SKILL.md` folders and their safe scripts, references, and assets
- plugin manifests and plugin-skill metadata
- enabled plugin state
- app and MCP presence flags
- MCP server names without commands or environment values
- safe model, effort, personality, approval, sandbox, desktop, and feature
  preferences
- global `AGENTS.md`

The importer deliberately excludes:

- `auth.json`, credentials, keys, and secret-looking files
- MCP commands, arguments, and environment values
- raw sessions, logs, SQLite state, and transcription history
- cached plugin executables and dependency trees
- Codex system skills owned by the installation

Imported personal skills start disabled with `review_required`. Plugin skills
remain `codex_linked` until Neyvia has an equivalent callable app or MCP route.
The Skill Studio prioritizes personal imports and reports linked plugin counts
without flooding the first viewport.

## Commands

```powershell
python scripts/run_grant_agent_cli.py orchestration-compile --root . `
  --source-file examples/neyvia-runtime-upgrade.ney

python scripts/run_grant_agent_cli.py context-status --root . `
  --session-id mission_123 --max-context-tokens 400000

python scripts/run_grant_agent_cli.py context-search --root . `
  --session-id mission_123 --query "reconnect invariant"

python scripts/run_grant_agent_cli.py codex-import-audit --root .
python scripts/run_grant_agent_cli.py codex-import --root .
```

The same operations are available through the native tool catalog as
`context.search`, `context.bundle`, `context.compact`,
`orchestration.compile`, `codex.assets.inspect`, and `codex.assets.import`.

## Current limits

- Provider responses do not all expose or forward exact token usage into the
  ledger yet. Those routes use the estimator.
- Stable-prefix cache keys are available, but provider-specific cache-control
  emission is not yet generalized across every runtime.
- Codex apps and MCP tools are indexed, not automatically re-authenticated or
  exposed as native Neyvia tools.
- Raw Codex sessions and memories are not imported without a separate,
  explicitly authorized privacy design.
- `NEYVIA/1` stages are attached to the mission contract. More scheduler-native
  stage dispatch and rollback receipts remain possible future work.

## Stress verification

The July 12 real stress run retained `385,084` tokens in a ledger with a
`35,000`-token model-visible limit, a ratio of `11.0x`.

- `1,224` total events
- `1,199` archived events
- only `4,323` tokens remained active after checkpoint rotation
- `240` artifact-backed tool outputs
- `12` compaction cycles
- all `12` pinned architectural sentinel decisions retrieved
- final bundle: `19,332 / 30,000` tokens, including retrieved archived evidence
- local runtime: `7.49 seconds`

Proof:
`.agent_control/mission_artifacts/context_stress/context-stress-20260712T190538Z/long-context-stress.json`

The first stress attempt failed at `8.56x` and exposed punctuation-sensitive
identifier tokenization. The gate was kept unchanged; the tokenizer and test
window were corrected before the passing run.

## Primary references

- OpenAI compaction: <https://developers.openai.com/api/docs/guides/compaction>
- OpenAI conversation state: <https://developers.openai.com/api/docs/guides/conversation-state>
- Codex skills: <https://developers.openai.com/codex/skills>
- Codex plugins: <https://developers.openai.com/codex/plugins>
- Codex App Server: <https://developers.openai.com/codex/app-server>
- Hermes context compression: <https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching/>
- Hermes prompt assembly: <https://hermes-agent.nousresearch.com/docs/developer-guide/prompt-assembly>
- Hermes plugins: <https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins>
- OpenClaw compaction: <https://docs.openclaw.ai/concepts/compaction>
- OpenClaw pruning: <https://docs.openclaw.ai/concepts/session-pruning>
- OpenClaw context engine: <https://docs.openclaw.ai/context-engine>
- OpenCode configuration: <https://opencode.ai/docs/config>
