# Unreal Agent assessment (source review, 2026-09-23)

Source: https://github.com/unreallabsai/unreal-agent at commit `b7c9bf1c5c2fa4127255c07727a7c8413e23944a` (MIT). This is a source review, not a performance or reliability win over Neyvia.

## Relevant mechanisms

- The coordinator persists accepted inputs and committed operations; the session store keeps append-only, versioned history with recovery and forks. Its inbox deduplication is explicitly volatile and session scoped.
- Tool translators validate calls and emit serializable operations without doing I/O; a separate operation manager executes those operations. That is a useful boundary for replay and remote sandboxing.
- The context builder reports omitted, truncated, and compacted content alongside the model input. Neyvia's working-memory projection also records omissions; its new `semantic.memory.find` and `semantic.memory.retrieve` tools now provide a model-usable recovery route.
- Its runner has provider clients for OpenAI, OpenAI Codex, OpenRouter, Fireworks, and Ollama. Its Harbor bundle records source revision and binary checksum. These are portability and provenance mechanisms, not evidence of equal behavior across providers.

## Decision

**Experiment with the operation boundary and omission accounting; do not replace Neyvia's harness yet.** Neyvia already has durable conversations, native tool policy, semantic memory, receipts, and user-path verification. A wholesale runner swap would have to preserve those contracts and demonstrate a real improvement.

## Bounded comparison

Use `scripts/run_live_harness_comparison.py` as the Neyvia baseline and a revision-pinned Unreal runner in an isolated workspace. Keep the same model/provider/effort, prompts, tool authority, timeout, and inputs. Test (1) a no-tool reply, (2) a read-only tool journey, (3) one interrupted operation with restart, and (4) long-context omission followed by exact recovery. Record task acceptance separately from process completion, operation idempotency, recovered bytes, tool errors, tokens, latency, and cost. Use a held-out negative case and hashes for all outputs. This comparison requires model calls and was not run in this review.

References: [architecture](https://github.com/unreallabsai/unreal-agent/blob/main/README.md), [provider selection](https://github.com/unreallabsai/unreal-agent/blob/main/cmd/internal/agentrunner/providers.go), [Harbor bundle](https://github.com/unreallabsai/unreal-agent/blob/main/benchmarks/harbor/build.py).
