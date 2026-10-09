# Connected Language (CL) 1.1

Normative, 3 Oct 2026. This document supersedes CL 1.0 (`../connected-language.md`, kept as history; Codex receipts hash it) wherever the two differ. Where 1.1 is silent, 1.0 governs the **host contract**: the type system and JSON Schema mapping (1.0 §4), handles, projections and diffs (§7), versioning (§9) and the token-measured choices (§11). Claude owns this spec and the primer. Codex proposals are resolved in §9.

## 0. Why 1.1 exists

The canonical cohort (`docs/evidence/cl-benchmark.md`) failed both gates.

- **Start context was 45% larger**, not 50% smaller. Two causes: the 1,401-token primer was charged on every task, and the full L2 manuals grew 89% because 1.0 wrote impact, checks and awareness into them.
- **Luna succeeded 3/5 with CL** against 5/5 with JSON. The failures were a quoted handle placed in a version slot, guessed CAS stamps, broken byte preservation, and a run that stopped before the final Apply even though its local fill check passed.
- **What worked:** runtime handles and diffs (web −85%) and L1 signatures (−18%).

1.1 keeps what worked and moves cost and risk from the model to the host. The model sees only a short core primer, a one-line index, familiar calls, procedures with goals, and results. Everything 1.0 required for awareness and verification still exists, but the host generates it at the moment of action.

## 1. Two surfaces

| Surface | Who writes | Who reads | Contents |
|---|---|---|---|
| **Model view** | host renders | agent | primer, L0, L1 on demand, observations, results |
| **Host contract** | compiled manual (archival JSON ↔ CL) | host runtime, validator | full `A` types, auto parameters, `C`, `P` steps, `I` sources, `X`, `F`, `M`, `V`, permission and ask rules |

The host contract keeps all of 1.0's semantics: R2 (an impact for every action), R3 (observer checks for every mutation), observers, undo and ask. **Nothing in it is deleted to win tokens; it is just not preloaded.** Today, a manual is the host contract plus its model view; the JSON manual files remain the compiled archive.

## 2. Context loading

- **Cold start** = the core primer (`primer.md`, ≤ 300 o200k tokens; now 275) + the L0 index, one line per layer, each ≤ 20 tokens. The host preloads nothing else.
- **First touch.** The first time an agent context calls or observes a layer, the host prepends that layer's L1 once, before the first `R`. `help("layer")` loads it explicitly. L1 lists the layer's procedures first, then their `J` choices, then its actions, then at most 3 `X` lines.
- **On demand.** `help("layer", 2)` returns the rest of the model view (all `X F M V`). The host also attaches a matching `X` line to a failing `R`.
- **Accounting.** Benchmarks report cold-start, first-touch and amortized counts separately. Gates use the **per-fresh-task** count: the primer and L0 are charged on every task, and L1 for every layer touched.

## 3. Familiar surface

**3.1 Calls.** An action is a Python-style call, one per line: `notes.read(path="Ideas.md")`, `web.fill(e2, value="42 units")`. A procedure call is prefixed with `run`. Positional arguments come first, in signature order, then keyword arguments `name=value`. The 1.0 forms (`do f(a:1)`) are still accepted. Prose and fenced code around call lines are transport text, never errors.

**3.2 Literals** follow Python/JSON: strings are always `"quoted"` (JSON escapes; `"""…"""` for multi-line text), plus numbers, `true` `false` `null` (`True` `False` `None` are accepted), `[lists]` and `{dicts}`. **There are no barewords.** A bare identifier is always a ref.

**3.3 Refs.** `e1` (element), `h1` (state), `r1` (receipt), `w1` (window) and `c1` (claim) are written bare and never quoted. They come from the newest observation, and the host re-binds element refs after each observation. One fallback is allowed: for a parameter typed `ref`, a quoted string that exactly equals a live ref is accepted, and the `R` line carries `quoted-ref` to teach the canonical form. Any other string in a ref slot is refused with the ref names the host would accept.

**3.4 Host-filled parameters.** In the host contract, a parameter marked `=auto(expr)` (CAS stamps such as `expectedModified`, DOM `revision`, `browserId`, `window_id`, `pid`, `sessionId`, element tokens) is filled from the newest matching observation. **The agent never sees or writes it.** If the agent passes one anyway, the call is refused. A CAS conflict is handled by the host: it re-reads, returns the other writer's `D` lines, and leaves the decision to retry with the agent.

**3.5 Signatures in the model view.** The form is `A name(p, q?, r?: "a"|"b", n?: 1..500) -> view[col col] ~|!`. A parameter without a type is a `str`. `-> view[cols]` names the columns that observations of this result will show. Parameter names are the tool's real names, except where the real name is a Python keyword. In that case the host contract declares an alias (`source:path=from`).

**3.6 Expressions** (in `G` and `C`) are a Python subset: `== != < <= > >=`, `in`, `not in`, `and`, `or`, `not`, attribute access, indexing, list comprehensions over observed lists, the string methods `startswith endswith lower strip count`, and the built-ins `len base count matches(value, Type)`. Calls are allowed only to read-only actions. A call that fails evaluates to `null`.

**3.7 Observations.** An observation is a header, `S name ref #n [columns]`, followed by `E` rows that are positional by those columns. The header carries the columns, so no `T` line is needed in context. UI trees are `E role "label" ref key=value…`, with one space of indentation per level. Coordinates and other `^` fields stay behind the ref, and `project(ref, path, start, count)` reads them.

## 4. Awareness is host-generated

Manuals no longer author `I`, `K` or `Q`. The host generates them at the moment of action:

- **`I` (realized).** After every `~` or `!` call, the host writes what was actually written, emitted and touched, plus the undo, from the impact map (`neyvia.impact`), bus events and the tool's host contract.
- **`K` (preflight).** Before a `~` or `!` call, the host injects `K` lines when the work board, connected sessions, the T16 shared log or pending approvals touch the same resource. If nothing overlaps, it adds no lines and costs no tokens.
- **`Q`.** The host emits a `Q` when a check returns `?`, when a projection is truncated, or when an observation's certainty is below "observed". Agents MAY write `Q` lines in their plans.
- **ask.** An approval-gated call returns `R name ask` followed by `K approval …`.

## 5. Goals: no separate tests

- **`G` line:** `G [name]: expr`. Every `P` in a host contract MUST have a `G`. `run p(…)` returns `+G` or `-G`, and the run's status is `ok` only if `G` passes.
- **Every task has a `G`.** It comes from the task author (benchmark task, scheduled job, mission) or from the intent checklist's `doneWhen`. If neither exists, the agent writes `G: expr` before its first mutation. The host rejects a `G` that reads no observer.
- **`done("summary")`** is the only way to finish. The host evaluates the task's `G`. If it fails, the host returns `R done refused -G` with the failing sub-expressions and their observed values, and the agent continues. A task with no `G` can only end as `R done unverified`, which is reported as a failure in benchmarks.
- **Coverage.** This closes 1.0's gap: in the Luna run, the local fill check passed but Apply was never clicked. Under 1.1 the task `G` (`"Applied: …" in win.text()`) refuses `done`.

## 6. Procedures first

- **Preferred move.** The agent's preferred action is `run layer.proc(args)`. Single actions are the fallback, used when no procedure fits. The host contract holds each procedure's steps; the model view shows only the signature, `G` and choices.
- **Choices as arguments.** A `J` choice is an optional keyword argument (`capture="append"`). If the agent omits it, the run pauses with `R p ask J capture "append"|"leave": "question"`. Repeating the call with the choice resumes from the pause: the host keys the paused run by its arguments and does not repeat completed effects (action identity, §9 P4).
- **Compiled scripts.** A procedure compiled from N identical verified runs (`manual.compile`) executes with zero model calls. Its `V` route is host policy and appears only when it changes who acts.

## 7. Grammar changes against 1.0 §3

```ebnf
call_line = [ "do" SP | "run" SP ] qname "(" [ args ] ")" ;      (* "run" only for procedures *)
args      = arg { [ "," ] [ SP ] arg } ;   arg = [ key "=" ] value | [ key ":" ] value ;  (* ":" = 1.0 compat *)
value     = string | raw | number | "true" | "false" | "null" | "True" | "False" | "None"
          | ref | list | dict | qty | time ;                    (* no barewords *)
ref       = letter { letter } digit { digit } ;                  (* e1, h12, r3, w1, c2 *)
dict      = "{" [ string ":" value { "," value_pair } ] "}" ;
attr      = key "=" value | word ;                               (* model view uses "=" *)
goal      = "G" [ SP name ] ":" SP pyexpr ;
signature = "A" SP qname "(" [ mparam { "," SP mparam } ] ")" [ SP "->" SP name [ "[" cols "]" ] ] [ SP ( "~" | "!" ) ] [ gloss ] ;
mparam    = key [ "?" ] [ ":" SP type ] [ SP "=" SP value ] ;
qname     = name { "." ( name | digit { digit } ) } ;           (* accepts step.1 (P3) *)
```

Host-contract lines keep the 1.0 grammar and add `param=auto(expr)` and `key:type=alias` (an alias for a Python keyword).

## 8. Conformance changes

R1–R15 of 1.0 apply to the **host contract**. The model view adds:

- **R16:** Cold start is at most 300 (primer) plus 20 per layer o200k tokens, and nothing else is preloaded.
- **R17:** No model-view line shows an auto parameter, a raw id or a quoted ref.
- **R18:** Every `P` has a `G`; every benchmark task has a `G`; `done` without a passing `G` is never `ok`.
- **R19:** Model-view `I`, `K` and `Q` come only from the host at the moment of action, and manuals contain none.
- **R20:** For every layer, L1 lists procedures before actions, and every frequent multi-step task in the benchmark has a procedure.

## 9. Codex proposals: resolutions

| # | Proposal | Decision | Reason |
|---|---|---|---|
| P0a | ASCII and compact spacing | **accept** | it was already measured in 1.0 §11; the model view keeps `->` and adds `, ` only where Python form needs it |
| P0b | lossless JSON carriers are archival, not context | **accept** | this is now the host contract / model view split (§1) |
| P0c | do not claim the signature-only 46.8% as lossless | **accept** | 1.1 claims no lossless model view; losslessness lives in the host contract |
| P1 | compact machine primer; learning-once vs every-run counts | **accept** | 275-token core primer; cold, first-touch and amortized counts are reported separately (§2) |
| P2 | full L2 is +89.5% because of added declarations, impacts and checks | **accept** | they move into the host contract; model-view L1 averages 162 tokens per layer here |
| P3 | numeric qname segments (`R step.1`) | **accept** | grammar §7 |
| P4 | stable action identity for mutations and interrupted batches | **accept** | the host assigns `(batchId, line)`, and an explicit transport `actionId` overrides it; the agent never invents ids; resuming reuses the identity, so effects are not repeated |
| P5 | schema check built-in or typed predicate | **accept** | `matches(value, Type)` (§3.6); visible CL and archival metadata must agree, enforced by R7 |
| P6 | 49 effectful actions lack observers; refuse unverified mutations | **accept** | the host refuses them until their contracts gain observers; they are listed as `F`; `Q` is never a substitute |
| P7 | prose and fences around actions are transport | **accept** | §3.1; errors never advance the observation generation |
| C1 | separately approved compact primer | **accept** | `primer.md` 1.1 |
| C2 | shared declarations loaded once per retained context | **accept** | L1 loads once per context on first touch (§2) |
| C3 | keep full observer and impact semantics; do not delete for tokens | **accept** | they stay in the host contract (§1) |
| C4 | typed examples: unquoted handles vs quoted strings | **accept** | primer and §3.3; R17 |
| C5 | whole-task end condition or executable procedure | **accept** | `G` and `done` (§5), procedures first (§6) |

No proposal is rejected. One is accepted with a narrowing: for P4, retry suppression is guaranteed only for host-assigned or explicit identities, never for identities generated per fresh call.

## 10. Measurements (o200k_base, `examples/measure.py`)

| layer | today start (manual + schemas) | 1.1 start (primer + L0 + L1) | today runtime | 1.1 runtime |
|---|---:|---:|---:|---:|
| notes | 1446 | 616 | 414 | 174 |
| files | 1230 | 579 | 2097 | 975 |
| window (T16) | 1615 | 564 | 1109 | 347 |
| web (T18) | 983 | 525 | 3973 | 212 |
| chart (T18) | 866 | 455 | 1122 | 168 |
| codex run | 340 | 471 | 572 | 293 |
| **total** | **6480** | **3210 (−50.5%)** | **9287** | **2169 (−77%)** |

- **Strict per-task count.** Today is credited with loading only the touched layer's manual, and 1.1 is charged its full cold start every time.
- **Benchmark setup.** In the benchmark's setup, arm (a) preloads every layer's manual: 6,480 here, against 373 for 1.1's cold start plus about 162 for one layer's L1. That is about −92%.
- **Codex run is the exception.** Today's baseline for it has no manual at all, so the fixed 373 makes 1.1 more expensive there.
- **Required validation.** These numbers are text counts. `benchmark.md` defines the runs that must confirm success and provider tokens.
