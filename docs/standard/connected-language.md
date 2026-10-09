# Connected Language (CL) 1.0

Normative draft, 2 Oct 2026. Claude owns the grammar and the primer. The reference implementation (`src/grant_agent/cl/`) is Codex's. Syntax changes only through measurement (§11), and proposals go in `CHANGES-from-codex.md`. MUST, SHOULD and MAY follow RFC 2119. The reader of CL is an agent; a human view is just a renderer.

## 0. Purpose

CL is one notation for reading and acting on every Neyvia layer: OS, windows, web, images, apps, files, tools, manuals, runs and agents. An agent learns it once, from `primer.md`, and never needs a per-tool schema in context.

- **Success condition: no separate tests.** Every action carries its executable checks (`C`) and its impact (`I`), so verification happens as part of acting. A `do` completes only after its checks have run, and its receipt (`R`) reports every check result, the observed diff (`D`) and the impact that actually occurred.
- **Principle.** An action in Neyvia must be cheaper, better verified and more impact-aware than the same action in Claude Code, Codex or Cursor alone. The comparison is made action by action (R15).

## 1. The family: one grammar, six standards

| Standard | Covers | Tags |
|---|---|---|
| CL-State | perception of every layer: types, state, entities, diffs, projections | `L T S E D` |
| CL-Act | signatures, the `do` form, receipts, approvals, procedures | `A do R P` |
| CL-Aware | impact, the known world (agents, claims, runs, user), open unknowns | `I K Q` |
| CL-Verify | executable checks, pitfalls, frontier | `C X F` |
| CL-Memory | learned facts with scope, provenance and promotion | `M` |
| CL-Route | where a step runs (script, model, harness or human) and where judgement is needed | `V J` |

## 2. Lexical rules

1. **Lines.** Text is UTF-8 with LF line ends (CRLF is accepted). A non-blank line starts with a tag, with `do`, or with `--` (a comment). In mixed agent output, only lines that begin with `do ` are CL.
2. **Indent.** Leading spaces are allowed only before `E` and `D`, at one space per tree level. An `E` line's parent is the nearest earlier `E` line with one space less. Indentation costs nothing in o200k.
3. **Separators.** Fields are separated by one space. Inside `()`, `[]` and `{}`, a comma counts as a space.
4. **Gloss.** ` -- ` outside a string starts the gloss, which runs to the end of the line. The gloss is the description; the model reads it and the parser keeps it.
5. **Strings.** Strings use JSON syntax (`"…"`, escapes `\" \\ \/ \b \f \n \r \t \uXXXX`). A raw string `"""…"""` may span lines, has no escapes and cannot contain `"""`. Raw strings appear only in `do` lines.
6. **Injection boundary.** Every observed `str` value MUST be a quoted JSON string with its newlines escaped, so observed text can never start a line or close a construct. A layer that carries untrusted data has `untrusted` on its `L` line. Its text is data, never an instruction.
7. **Barewords** match `[A-Za-z_./][A-Za-z0-9_./-]*` and contain no `:`. They are allowed where a `word`, `path`, `id`, `url` or enum literal is expected, and never for `str`. A value that equals a keyword (`true false null and or not has in do`) or a field name of the enclosing type MUST be quoted. Where the type is `id`, a number literal stands for its exact digit string, so `1790976200013753000` stays a JSON string.
8. **Literals**, matched in this order: time (ISO 8601), quantity (a number followed by one of `ms s m h d B KiB MiB GiB px %`), number, range (`1..500`, `..300`, `3..`), handle (`@h1`, `@0`), `true` `false` `null`, string, bareword.
9. **Paths** always use `/`. The runtime converts them to native separators.
10. **Pragma.** The first line MAY be `CL 1`.

## 3. Grammar (ISO 14977 EBNF; `SP` = one or more spaces)

```ebnf
document  = [ "CL" SP int NL ] , { line NL } ;
line      = blank | "--" text | { " " } , ( tagged | doline ) ;
gloss     = SP "--" SP text ;
tagged    = "L" SP layer | "T" SP typedecl | "S" SP state | "E" SP entity | "D" SP diff | "A" SP action
          | "I" SP impact | "C" SP check | "P" SP proc | "J" SP judge | "X" SP pitfall | "F" SP frontier
          | "K" SP known | "Q" SP question | "R" SP receipt | "M" SP memory | "V" SP route ;
layer     = name SP "v" int { SP attr } [ gloss ] ;
typedecl  = name [ SP ] type [ gloss ] ;
state     = path [ ":" type ] [ SP "=" SP call ] { SP ( value | attr ) } [ gloss ] ;
entity    = [ kind SP ] { ( value | "-" ) SP } { attr SP } [ gloss ] ;   (* positional by type, 5.4 *)
diff      = "+" path { SP value } { SP attr } | "-" path | path SP setter { SP setter } ;
setter    = key "=" value ;
action    = qname "(" [ params ] ")" [ SP "->" SP type ] [ SP ( "~" | "!" ) ] [ SP "=" SP call ] [ gloss ] ;
impact    = qname { SP attr } [ gloss ] ;
check     = qname SP name [ "(" params ")" ] ":" SP expr [ gloss ] ;
proc      = name "(" [ params ] ")" ":" SP step { ";" SP step } [ gloss ] ;
step      = [ name "=" ] call { SP "C" SP name } | "J" SP name [ "=" word ] ;
judge     = name SP word { "|" word } ":" SP string [ gloss ] ;
pitfall   = text SP "->" SP text ;                       (* starts with the qname when bound *)
frontier  = text [ SP "->" SP text ] ;
known     = word SP value { SP attr } [ gloss ] ;
question  = name SP string SP "->" SP resolver { SP attr } [ gloss ] ;
resolver  = call | "J" SP name | "ask" SP word | "observe" SP word ;
receipt   = qname SP status { SP ( qty | handle | checkres | attr ) } [ gloss ] ;
status    = "ok" | "fail" | "ask" | "stale" | "refused" | "unknown" | "frontier" | "skipped" ;
checkres  = ( "+" | "-" | "?" ) name ;
memory    = word SP string { SP attr } ;
route     = [ ( "P" | "J" ) SP ] qname SP "->" SP ( "script" | "model" | "harness" | "human" ) [ ":" word ] { SP attr } ;
doline    = "do" SP call { SP "C" SP name [ "(" args ")" ] } ;
call      = qname "(" [ args ] ")" ;           args = arg { sep arg } ;   arg = [ key ":" ] value ;
params    = param { sep param } ;              param = key [ "?" ] ":" type [ "=" value ] ;
attr      = key ":" value | word ;                        (* bare word = true flag *)
value     = time | qty | number | range | handle | "true" | "false" | "null" | string | raw
          | bareword | list | record | call ;
list      = "[" [ value { sep value } ] "]" ;
record    = "{" [ field_v { sep field_v } ] "}" ;   field_v = key ":" value | value ;
path      = ( name | handle ) { "." ( key | int ) | "[" value "]" } ;
expr      = conj { SP "or" SP conj } ;          conj = neg { SP "and" SP neg } ;
neg       = [ "not" [ SP ] ] cmp ;              cmp = sum [ [ SP ] op [ SP ] sum ] ;
sum       = term { "+" term } ;                 op = "==" | "!=" | "<=" | ">=" | "<" | ">" | "has" | "in" | "~" ;
term      = value | path | call { "." key } | "(" expr ")" ;
qname     = name { "." name } ;   name = letter { letter | digit | "_" | "-" } ;   kind = name ;
handle    = "@" ( letter | digit ) { letter | digit } ;
```

## 4. Types and the CL ↔ JSON Schema mapping

```ebnf
type  = alt { "|" alt } ;
alt   = base | name [ "{" field { sep field } "}" ] | literal | range | base count | "str~" string
      | "[" type "]" [ count ] | "{" [ field { sep field } ] [ sep ".." ] "}" | "json:" string ;
field = [ "^" ] key [ "?" ] ":" type [ "=" value ] ;   count = "#" range ;
```

A type is declared once with `T` and is then referenced by name. Type names are scoped to their layer; another layer's type is written `layer.Type`. The compiler is lossless in both directions: CL → JSON → CL is byte-identical, and JSON → CL → JSON is equal in canonical JSON.

| CL | JSON Schema |
|---|---|
| `str int num bool null any` | `string integer number boolean null`, `{}` |
| `time` / `dur` / `url` | string with `format` `date-time` / `duration` (`12s` ↔ `"PT12S"`) / `uri` |
| `path id word handle` | `{"type":"string","x-cl":"<name>"}`; `word` also has `pattern ^[A-Za-z_][A-Za-z0-9_-]*$` |
| `rect` | array of 4 numbers (x,y,w,h), `"x-cl":"rect"` |
| `color` / `bytes` | string with `pattern ^#[0-9a-fA-F]{6}$` / `contentEncoding base64` |
| `1..500` | `{"type":"integer","minimum":1,"maximum":500}` (`number` if either bound has a `.`) |
| `str#1..300`, `[T]#..100`, `str~"re"` | `minLength`/`maxLength`, `minItems`/`maxItems`, `pattern` |
| `a\|b` literals, `"x"` / `T\|U` / `T\|null` | `enum`, `const` / `anyOf` / `"type":[T,"null"]` |
| `[T]` | `{"type":"array","items":T}` |
| `{a:T b?:U=v}` | object with `properties`, `required:["a"]`, `default`, `additionalProperties:false` |
| `{… ..}` | the same, but open (no `additionalProperties`) |
| `note{body:str}` | `allOf:[{$ref note},{…}]` |
| `^f` | `"x-cl-level":2`: the field is not rendered and is read through `project` |
| gloss | `description` |
| `A f(params) -> T` | `inputSchema` (params as an object) and `outputSchema` T |
| none / `~` / `!` | MCP `readOnlyHint:true` / `readOnlyHint:false` / `readOnlyHint:false, destructiveHint:true` |
| `json:"…"` | the schema verbatim: the escape hatch for `if`, `patternProperties`, recursive `$ref` |

Objects are closed by default. For an open schema, JSON → CL writes `..`, so round trips stay exact. Neyvia's own tools SHOULD become closed, which saves one token per signature and rejects misspelled arguments.

## 5. Line types

| Tag | Family | Level | Meaning |
|---|---|---|---|
| `L` | State | 0 | layer: name, version, `tools:` binding prefix, `untrusted`, `src:`, `sha:`, gloss (≤ 30 tokens) |
| `T` `S` | State | 1 | a type; a state declaration with its observer (`S notes:notes = notes.list()`) |
| `S` `E` `D` | State | runtime | observation header, entities, changes since the last observation of the stream |
| `A` | Act | 1 | action signature, which is the schema |
| `do` `R` | Act | runtime | an emitted action and its receipt |
| `P` | Act | 2 | procedure (a proven chain of steps) |
| `I` | Aware | 1 | impact, **required for every `A`** |
| `K` | Aware | runtime | known world: agents, claims, runs, user control, approvals, locks, budgets |
| `Q` | Aware | 2 / runtime | an unknown, its cheapest resolver, and what it blocks |
| `C` | Verify | 1 | executable check bound to an action |
| `X` `F` | Verify | 2 | pitfall `failure -> recovery`; frontier (not mapped yet) |
| `M` | Memory | 2 | fact with `src:` and `state:quarantine\|verified\|promoted` (LAYA promotion) |
| `V` `J` | Route | 2 | route a `P`, `J`, step or `A`; a judgement point (the only place a model decides) |

**5.1 `A`.** `A qname(params) -> T effect = binding`. With no effect marker the action is read-only. `~` changes state and can be undone. `!` changes state and cannot be undone automatically. Parameter names are the tool's real names: CL never renames, so the signature *is* the schema. By default the action binds to the `L` line's `tools:` prefix plus the action's last segment. An explicit binding is a call template in which a bareword naming a parameter is replaced by its value, for example `= cua.action(tool:type_text args:{el text})`. A `handle` argument expands into the identifying arguments its observation recorded: `window_id pid element_token` for T16, and `browserId revision element` for T18.

**5.2 `I`.** The keys are `reads writes emits ui deps undo ask net cost bounds`. Every `A` has at least one `I`. A `~` or `!` action needs `writes:` and `undo:`, where `undo:` is an inverse call, with `previous.<field>` meaning the value observed before the call, or `none`. A `!` action needs `ask:` naming who approves and when, or `ask:none` with a gloss explaining why. `deps:` lists whatever relies on the written state: tests, manuals, links, claims and users. After a `do`, the runtime emits the realized `I` with concrete values.

**5.3 `C`.** A check's free names bind to the action's arguments, to `result`, to `previous` (the state of the subject before the call) and to procedure inputs. The only built-in functions are `len bytes lower count now`. A path applied to a list maps over its items. `has` tests substring or member containment; on a list of records it compares the first field. `~` is a regex match. Inside a check, a call that fails evaluates to `null`. A check with all its names bound runs after every successful `do`. A check named `pre` runs before the call and refuses the call when it fails. A check that takes its own parameters runs only when a `P` step or a `do` line attaches it (`do win.click(@1) C shows(text:"…")`). A check MUST read through an observer, and a handle path such as `el.value` reads the post-action observation, which counts as an observer read. The only exception is a check whose subject is the result itself (`result.status!="conflict"`).

**5.4 `S` and `E`.** An `E` row fills its type's fields **positionally, in declaration order**. `-` skips a field. Trailing fields can be omitted, and an absent field takes its default. A true bool may appear as a bare flag, and `key:value` pairs may follow in any order. `^` fields are not rendered. A list of records may use pair form, `[cl:1 neyvia:1]`, when only the first two fields differ from their defaults. An `E` line may begin with a kind, the name of a type in the same layer (`E series …`); a kind is required when the parent holds more than one list. Otherwise the line is positional data of the parent's item type (`E button "Apply" @1`), and the validator flags any role that equals a type name. In UI element types, roles are lowercase and `enabled` is omitted because only `disabled` is written.

**5.5 `P` `J` `V` `K` `Q` `X` `F` `M`.** A `P` step is a call, optionally saved (`b=notes.read(path)`) and optionally followed by `C name` checks, or it is `J name=option`. That step stops at the judgement and continues only on `option`; any other option ends the procedure `ok`. `V target -> script | model:<id> | harness:<codex|claude|neyvia> | human:<who> why:… cost:…`. The core `K` kinds are `agent claim run user approval lock budget env`, sourced from the work board, `state()`, connected sessions, approvals and the T16 log. `Q` names an unknown, its resolver and `blocks:`. Agents write `Q` lines in their plans, and manuals list the typical ones at L2.

## 6. Levels

`describe(level, layer?, chapter?)` returns CL, and the lines at L(n) are a subset of those at L(n+1).

- **L0**, the index, is always loaded: one `L` line per layer. All 25 manuals SHOULD fit in 600 o200k tokens.
- **L1** is enough to act: `T` (only the types referenced), `S`, `A`, `I` and auto `C`. Every call is then correct, checked and impact-aware.
- **L2** is enough to judge and recover: `P J X F Q M V`, `^` fields, and checks that take parameters.
- **Runtime** lines (`S E D R K`, and agent-written `Q`) have no level and are bounded by budget. An observation over 4000 characters becomes a header (`S x #n @h3`) that is read through `project`.

## 7. Handles, projections, diffs

- **Handles** are runtime aliases, unique within one agent context: `@h1` state, `@r1` receipt, `@c1` claim, and so on. Raw ids never reach the model: a 32-hex state handle is 23 o200k tokens, while `@h1` is 3. Digit-only handles (`@0`) are **element handles**, valid only against the newest observation of their layer stream (a T16 `s00000001:0` costs 6 tokens; `@0` costs 2). Using a stale one returns `R … stale` with fresh `D` lines, and nothing takes effect.
- **Projection.** `do project(@h1 items 10..20)` returns `S`/`E` lines for that slice. Paths are dotted (`items.3.title`), and `[x]` selects the element whose first field is `x`. A projection reads an immutable observation, never live state.
- **Diffs.** A repeat observation returns `S <path> @h2 from:@h1` followed by `D path k=v`, `D +path …` or `D -path`. These map one to one to JSON Patch `replace`, `add` and `remove`. An unchanged observation returns `S … from:@h1 same`.

## 8. The `do` form and its result

Neyvia exposes one tool, `cl(lines:str)`. Harnesses without tools write `do` lines in text. The lines run in order, and after the first status that is not `ok` the rest return `R … skipped`. The parser:

1. resolves the qname through `A`,
2. binds positional arguments in signature order,
3. expands handles,
4. type-checks,
5. runs the `pre` checks,
6. passes Neyvia's existing permission gates (CL adds no authority),
7. calls the tool.

Each `do` returns:

```
R notes.write ok 9ms @r1 +cas +saved      -- status, duration, receipt handle, each check
D notes.items[Ideas.md] modified=1790976200225377900   -- observed effect
I notes.write writes:"C:/Users/example/Neyvia Notes/Ideas.md" emits:notes.changed   -- realized impact
```

`X` and `Q` lines are added when a known pitfall matched or a new unknown appeared.

- `ok` means the tool succeeded **and** every automatic check passed.
- A tool success with a failed check gives `fail` and `-name`.
- An undecided check gives `?name` and `unknown`.
- `ask` means approval is pending, and a `K approval` line follows.
- `frontier` means no manual covers the situation, and an `M` patch is quarantined.

The full JSON stays behind `@r1`.

## 9. Versioning

- **Pragma.** `CL 1` is the major version. Minor versions only add tags, attributes, base types or units.
- **Unknown tags.** A strict validator rejects them; lenient rendering for models keeps them. Unknown attributes are always kept and ignored.
- **Layer `vN`** increments when an `A` narrows, renames or removes anything, or when an `I` or `C` weakens. Adding optional parameters, actions, `X`, `M` or `Q` does not change it.

## 10. Conformance

An app, tool family, manual or perception source conforms when `describe(0..2)` and its runtime output satisfy:

- **R1** Every line parses. The canonical render (single spaces, no optional commas, attributes in declaration order) round-trips byte-identically.
- **R2** Every `A` has an `I`. Every `~` and `!` action has `writes:` and `undo:`, and every `!` action has `ask:`.
- **R3** Every `~` and `!` action has at least one automatic `C` that reads an observer.
- **R4** Every referenced type, action, check, judge, procedure and handle resolves.
- **R5** Every `P` step is a declared action, a saved call or a `J`, and every `J` has at least 2 options.
- **R6** Observed `str` values are quoted, and every untrusted layer is marked `untrusted`.
- **R7** CL ↔ JSON Schema is lossless for every tool in the inventory.
- **R8** Levels are monotonic, and L0 is one line per layer.
- **R9** Every `do` gets exactly one `R` reporting every check that ran. An effectful `ok` is followed by `D` (or `same`) and by the realized `I`.
- **R10** No raw ids appear in model context, and stale element handles never take effect.
- **R11** Over-budget observations become handles plus projections, never dumps unless the agent asks.
- **R12** Before a `~` or `!` action on a resource that a claim or run overlaps, the matching `K` lines are in context.
- **R13** Every `M` has `src:` and `state:`, and only `promoted` memories apply without review.
- **R14** No tests: benchmark arm (b) writes and runs no separate tests. The report counts every error a separate test would have caught that the inline checks missed; the target is 0.
- **R15** Every action is measured against the same action in Claude Code, Codex and Cursor alone, on context tokens to act, checks run, impact known and undo known. CL must be at least as good on each, and every exception is listed.

## 11. Token-aware syntax (o200k_base via tiktoken; whole-line counts)

There is no local Claude tokenizer. When o200k ties, ASCII wins, because multibyte characters cost more bytes on byte-level tokenizers.

| Choice | Measured alternatives | One-line reason |
|---|---|---|
| `->` | `→` 7 = `->` 7 = `=>` 7 | it ties, so ASCII, which every model types reliably |
| `@h1` handle | `⟨h:nt1⟩` 18, `<h:nt1>` 14, `@h1` 11 | 7 tokens fewer per handle than the v0 draft |
| `@0` element | `⟨e:42⟩` 23 vs 16 | short, and distinct from `#` counts |
| one-letter tags | `LAYER ` 3 vs `L ` 2; `ACTION ` 2 = `A ` 2 | never more expensive, and dispatch on the first byte |
| space-separated fields | `{a:x b:y}` 13, commas 15, JSON-spaced 18 | cheapest, and commas are still accepted |
| `[T]` | `T[]` 4 = `[T]` 4 | it ties, and `[T]` mirrors list values |
| `1..500` | `int(1..500)` 8 vs 5 | 3 tokens fewer per bounded parameter |
| `T\|null` | `T\|nil` 3 vs 2 | cheaper, and it is the JSON word |
| `name?:T` | `?name` 6 = `name?` 6, `[name]` 7 | it ties; the suffix reads as "maybe" |
| full `I` keys | `w: ev:` 18 = `writes: emits:` 18 | abbreviations save nothing, so the unambiguous word wins |
| bare flags, defaults omitted | `"enabled": true` 4 → `enabled` 1 → omitted 0 | true defaults are free |
| `[x,y,w,h]` | JSON rect object 17 vs 9 | the order is fixed by the type |
| positional `E` rows | key-per-row JSON | keys are paid once, in `T` |
| pair form | JSON tag objects 40, `{cl 1}` records 18, `[cl:1 …]` 13 | cheapest for two-field records |
| depth by indent | ` E` 2 = `E` 2 vs `parent_index`/`depth` fields | depth costs nothing |
| `D @2 value="42 units"` | JSON Patch op 20 vs 9 | handle-rooted dotted paths |
| `do f(a:"x")` | JSON tool call 19 vs 12 | the action is written the way the signature reads |
| `+c -c ?c` | `c:pass` +1 | three states, one character |
| `/` in paths | `\\` JSON path 15 vs 14 | no escaping |
| `41ms`, `2MiB` | `"ms":41` 4 vs 2 | units live in the literal |
| ` -- ` gloss | `·` `\|` `#` `—` all 10 | it ties, and the ASCII marker is used nowhere else |
| quoted observed `str` | bare 5 vs quoted 7 | +2 tokens buys unambiguity and the injection boundary |

`examples/README.md` compares six real layers with today's format, and `examples/measure.py` reproduces every number.

Publication note: local account paths and network identifiers in this document are neutral examples.
