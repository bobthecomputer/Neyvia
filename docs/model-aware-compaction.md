# Native chat context policy

Native SDK chats read `config/neyvia_context_policy.json` from the control workspace
when the next run starts. Existing running chats are not interrupted. CLI harnesses
continue to own their context management.

`mode: "capacity"` (default) preserves context until the selected route approaches
its capacity. `mode: "avoid-price-increase"` also compacts before a documented
context-price tier. Flat token rates, peak-hour rates, and a higher absolute model
price do not by themselves trigger this optional policy. Larger prompts still use
more tokens at a flat rate; these modes do not promise a fixed bill or net savings.
Summarization costs tokens and can invalidate cached prefixes.

Example: preserve full context generally, but avoid Luna's higher context tier:

```json
{
  "schema": "neyvia.context-policy.v1",
  "mode": "capacity",
  "routes": {
    "opencode-go/gpt-6-luna": {"mode": "avoid-price-increase"}
  }
}
```

The selected provider/model is matched exactly in the existing Models.dev cache.
The receipt records its fetch date and source. Refresh the provider catalog when
limits/prices change. Only explicit `cost.tiers[].tier.size` context tiers with an
increased rate qualify; the legacy `context_over_200k` alias is ambiguous and is
ignored. Local route overrides may supply `contextTokens` and `inputLimitTokens`
for custom endpoints. Unknown routes use a labeled 32,768-token conservative
fallback, rather than claiming an unverified million-token window.

Capacity compaction starts at 85% of the advertised context, or earlier if the
input limit or output reservation requires it. The optional price policy starts
at 90% of the first increased-price tier. The retained target is 65% of the trigger,
allowing more work between compactions. There is no record-count trigger.

Instructions and tool schemas contribute to estimated input size. An unspecified
output maximum gets a matching SDK maximum and reservation: 10% of context,
between 4,096 and 64,000 tokens, limited by the model's output maximum. Explicit
output limits are preserved. Text measurements are estimates, not native model
tokenizer counts. Non-ASCII content is conservatively weighted; actual provider
input usage replaces the estimate for an identical prefix during a run.

Full durable history remains intact. If it fits the current policy, it is replayed
in full even if an older policy had already summarized it. Otherwise the existing
checkpoint, speaker provenance, exact latest request, and complete tool pairs are
preserved. System instructions are never summarized or rewritten.

Pricing reviewed 2026-09-28:
- https://dev.opencode.ai/docs/go/ — explicit Luna/Grok/Qwen context-price tiers;
  DeepSeek peak/off-peak rates are time-based.
- https://api-docs.deepseek.com/quick_start/pricing/ — DeepSeek context capacity.

Verification: `node scripts/verify-context-policy.mjs` and
`node scripts/verify-session-compaction.mjs`.
