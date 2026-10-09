# Native prompt integrity and Hermes integration

The private user prompt was not read, copied, edited, or used for verification.

## Changes

- Native validates its frozen instructions before every Agents SDK model call,
  including tool rounds and session replay. Competing system/developer history
  or changed instructions raises `prompt_contract_violation` before that call.
  Receipts expose hashes, validated/rejected call counts, and the SDK boundary.
- Native's non-streaming Codex subprocess explicitly clears inherited developer
  instructions, matching the app-server path. Planner/verifier prompts no longer
  receive hard-coded persona/task suffixes after the saved role instructions.
- Hermes receives saved instructions through its session system overlay, using
  a hash-checked file and its own interpreter. The child-process adapter binds
  the installed personality resolver without editing Hermes source or shared
  configuration. This handles long Windows prompts without putting them in argv
  or environment variables. Unknown resolver versions fail visibly.
- The real Hermes plugin CLI inventory appears under composer **+ → Tools &
  integrations → Connections**, with descriptions, search, and activation state.
  This preserves Hermes' own plugin loader; it does not convert plugins into
  Native tools or automatically enable them.

## Verification

- Six Native protocol scenarios: exact prompt through both API transports and
  tool rounds; real local file reads; visible tool/provider failures; competing
  system/developer replay blocked with zero provider requests.
- Existing scoped prompt and runtime-dispatch verifiers passed (11 and 10 checks).
- Real DeepSeek V4.1 Flash / OpenCode Go Native call, synthetic authorized
  red-team greeting: exact expected reply, one validated call, no rejection.
- Real Hermes call through the file-backed bridge, same synthetic greeting and
  provider/model: expected reply observed, exit 0.
- Hermes bridge accepts 46,500-character instructions; changed file hash is
  rejected. This large-prompt check loads the CLI, not a large model request.
- Frontend build passed; existing chunk-size warning remains. Runtime inventory
  check passed. Running local UI displayed 58 real Hermes plugin entries and
  their disabled status. Chrome was unavailable; used the in-app browser.

Machine-readable evidence is in `proof/prompt-integrity-20260927/`. JBHEAVEN
installation/discovery evidence is in
`C:/Users/example/Projects/Jbheaven/proof/hermes-jbheaven-20260927/`.

JBHEAVEN's package/installer incorrectly used `skills/bundles`; Hermes scans
`skill-bundles`. The packager, installer and simulation now use that directory.
Backup-preserving installation passed 7/7 checks, live installed verification
16/16, package simulation 19/19, and deterministic capability smoke 21/21.
Hermes resolved all four bundle skills with its own skill loading APIs. This
proves installation, discovery and deterministic operations, not model-directed
use of every skill or arbitrary plugin compatibility.

## Limits

The integrity check proves local SDK input, not undisclosed instructions inside
the remote provider. A provider/model may still refuse a system prompt. These
synthetic greetings do not reproduce or diagnose the private prompt's refusal.
Hermes overlays remain additive to its base prompt. Each plugin retains its
platform, dependency, credential, activation, and runtime requirements; universal
plugin compatibility is not claimed. Tempest/always have not been identified.

Source and the local responsive UI were checked. No new desktop installer was
released, no public service was restarted, and no public current was promoted.

Publication note: local account paths and network identifiers in this document are neutral examples.
