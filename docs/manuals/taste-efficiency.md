# Taste efficiency

## State observers
- `scripts/c13_run.py`: host-owned R6 task text, selected model, policy, concept/research stamps and sealed review state.
- `<arm>/<task>/**/usage.json`: authoritative CLI input, cached input, output, list-price cost, call time and admission state; unknown usage is explicitly incomplete.
- `<arm>/<task>/evidence/*/round-*/render/report.json`: raw Obscura pixels, pointer/keyboard/touch effects, overflow and runtime errors.
- `<arm>/<task>/**/context-metrics.json` and `packet` images: exact text-token count and hash-bound, at-most-640px region crops. These projections never replace raw completion evidence.

## Typed actions
- `scripts/c13_run.py T1|T2 --port <48801-48808> --model gpt-6-luna|gpt-6.1-sol --output-root <fresh arm> --max-rounds 6 --max-tokens 1000000`: fresh native CL harness run; adjacent Obscura port is explicit and validated.
- `--resume`: recover the same draft and host seals; retain paid/rejected attempts and their spend. No provider substitution or automatic budget increase.
- `review-admissions.json` persists attempted review rounds before execution, including failed reviews; resume recovers older model receipts so failures cannot reset the ceiling.
- Existing CL actions `taste.record_concept`, `taste.record_research`, `workspace.write`, `workspace.patch`, `taste.record_repair`, `taste.review` and `done` remain the only mutation/completion path.

## Executable checks
- `node --test tests/c13-budget.test.mjs tests/c13-context.test.mjs tests/c13_taste_gate.test.mjs`: reservations, cached/total accounting, missing usage, capacity retry, exact section spans, cropped geometry, rubric preservation and existing refusal/seal invariants.
- `node scripts/c13_render.mjs --html <absolute HTML> --out <absolute evidence> --port <assigned port>`: real Obscura rendering and every input mode; a dead control must produce `passed:false` and a nonzero exit.
- `done` requires a current globally rendered review, all ten axes at least 3/4, anchor tie/win, brief fidelity, no difference gap >=2, no untested or dead controls, and unchanged evidence hashes.

## Procedures
- Research and concept are produced once with the fresh draft, stamped before file creation and cached per task. Repairs do not search again.
- Review the full independent page once, then send only changed section source windows and measured region crops. Carry unobserved open differences forward. After those pass, perform one global verification and stop immediately when `done` succeeds.
- Apply unique, disjoint literal OLD/NEW edits through hash-checked workspace patches; parse scripts before mutation and restore original content if repair attestation fails.
- Reuse C4 `TurnContext` for durable raw handles and measured text admission; oversized unresolved live context is refused rather than silently truncated.

## Judgement points
- The selected model scores actual pixels and mechanisms. Host arithmetic computes quality from the frozen ten-axis rubric; projections and model assertions alone cannot complete a task.
- Cost targets are at most $0.45 landing and $1.10 rare UI per arm, using observed cached/uncached/output tokens at repository standard list prices. These are equivalents, not invoices.

## Pitfalls
- Codex CLI emits usage after a turn. Round and next-call admission are strict; an in-flight turn can exceed its reservation. Overshoot or unknown usage closes further admission and remains visible. This is not an exact provider token cap.
- Only an explicit pre-inference capacity rejection with no model/tool activity is zero; allow one same-model retry. Partial/network failures remain unknown and block paid continuation.
- No visible browser, private credentials, NAS, public service, dependency install or provider fallback is used.

## Frontier
- Meeting the price target with all quality and interaction gates must be established by each actual run. A cheap unfinished draft is not success.
- A provider-side exact token/output cap is not exposed by the installed `codex exec` transport and remains unimplemented.
