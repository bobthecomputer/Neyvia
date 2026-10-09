
## Measurement proposals from Codex (provisional, 2 Oct)

These proposals do not alter the Claude-owned grammar. The exact o200k meter
found `->` at 15 tokens vs `→` at 16 in the same action example; `<h:nt1>` at
14 vs `⟨h:nt1⟩` at 18 in the same state example; colon fields without optional
spacing at 18 vs spaced fields at 21. Prefer ASCII spellings and compact canonical
spacing, while retaining human-readable aliases only if the spec defines them.

Lossless JSON carriers are useful archival bridge data, but must not be the
model's normal context: all25 manuals cost69854 compact JSON tokens; deduplicated
schema declarations plus JSON-quoted CL carriers cost73492 (+5.2%). Put opaque
external constraints in explicit progressive metadata and express operational
checks/procedures/signatures as compact CL. Do not claim the signature-only
46.8% reduction (21886 ->11640 tool tokens) is lossless or equal semantics.

Raw receipt: `.agent_control/cl/provisional-meter.json`. Claude estimates use
UTF-8 bytes/3.5 and cannot decide tokenizer-specific syntax or provider billing.

## Final-spec implementation measurements (3 Oct)

1. The approved primer costs 1,401 o200k tokens. With the same five-layer fixture
   knowledge, full primer and interfaces, serialized starting context is a=2,088,
   b=3,091, c=1,289 tokens. Production example manuals yield a=5,135, b=6,488,
   c=1,371. Request a separately approved compact machine primer and an explicit
   distinction between learning-once cost and every-run starting context. All
   acceptance counts continue to include the full approved primer until changed.
2. Exact archival MCP roundtrip preserves all 293 original tools. The readable
   L1 projection costs 17,924 versus 21,886 compact JSON tokens (18.1% reduction).
   Full generated CL manuals cost 63,518 versus 33,514 existing rendered manual
   tokens (+89.5%); declarations, impacts and checks add information absent from
   the old render. Type dedup alone cannot establish the 50% benchmark gate.
3. `codex-run.cl` uses `R step.1`, but the grammar's qname disallows numeric
   segments. Propose allowing `[A-Za-z0-9_-]+` after the first dot for receipt
   subjects. The current parser reports the conflict; the spec is unchanged.
4. Define stable action identity for mutations and interrupted batches. The
   current transport accepts optional actionId outside `lines`, and generates
   one per fresh call if absent. A caller must reuse its explicit identity after
   interruption; a generated identity cannot guarantee retry suppression.
5. The archival manual codec uses per-record CL comments to retain JSON-only
   conditional bindings and schema predicates. Visible CL and archival metadata
   must agree; this is exact source compilation, but it is not yet independent
   execution of arbitrary pure-CL procedures. Approve a schema check builtin or
   typed predicate extension before projecting schema checks as executable CL.
6. 49 effectful manual actions lack authored automatic observers. Q records
   expose the gaps and are not conformance substitutes. The runtime refuses
   unverified direct mutations; legacy non-CL entry points remain available
   until equivalent grounded contracts exist for every managed operation.
7. Treat prose/fences around emitted `do` lines as transport text, not an action
   parser error. Run ordered calls and stop after the first non-ok. Error output
   must not advance the native/window observation generation or stale handles.

These are proposals and observed limitations, not edits to the approved spec.

## Canonical cohort decision (3 Oct)

All 30 matched cases completed with supported developer instructions. Luna a/b/c
success is 5/3/3 of five; Sol is 5/5/5. CL starting context is approximately 45.4%
larger, not 50% smaller. Luna CL totals 594,500 provider tokens versus Sol
no-manual 231,544. The approved full primer is counted on every fresh task.

Request a compact machine primer and shared type/action declarations loaded once
per retained agent context, with cold-start and amortized counts reported separately.
Keep full observer and impact semantics: deleting those fields to obtain a token
win would change the comparison. Typed identifier examples should explicitly show
unquoted handles versus quoted literal strings; Luna failures exposed this distinction.
Whole-task completion needs an authored end condition or executable procedure:
a correct textbox fill check cannot prove a later Apply click happened.

The current implementation reports frontier before unverified effects or procedures.
Its archival conditional/schema checks still compile through the existing JSON runner;
general pure-CL procedures and full expression typing need a defined executable
contract before legacy gateways can be retired. The strict conformance receipt
retains these failures. No syntax or primer changes were made without the spec owner.
