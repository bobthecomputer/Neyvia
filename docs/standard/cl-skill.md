# CL-Skill 1.0: skills that are checked, not hoped

Status: normative draft, 2 Oct 2026 (plan 15 T23). Sibling of `connected-language.md` (CL 1.0); it uses the CL grammar (§3) and line types (§5) unchanged and adds a profile for skills. Owner: Claude. Reference runner: `src/grant_agent/cl_skill.py`. First compiled skill: `manuals/skills/design-craft.cl`.

MUST, SHOULD and MAY are used as in RFC 2119. The reader is an agent.

## 0. Purpose and success condition

A prose skill (a `SKILL.md`) is advice the model may or may not follow; nobody measures whether it did. A **CL-Skill** is the same skill compiled to CL so that every run of it produces a receipt:

- procedures (`P`) say what to do in which order;
- judgement points (`J`) are the only places a model decision is needed, each with closed options;
- checks (`C`) run on the **output** the agent produced (files, the rendered page), not on the agent's claims;
- an **adherence score** is computed per run from the checks and the recorded judgements.

Success condition: following a skill is a measured property of each run. A run whose `R` line says `ok` passed every `block` check without a separate review. The Evolver improves the skill by measured fitness (§7), not by taste.

## 1. Compiling a prose skill

| Prose construct | CL-Skill line | Rule |
|---|---|---|
| "always / never X" that is visible in the output | `C <skill>.build <name>: <expr>` | MUST call an output observer (§2). Severity and source in the gloss (§3). |
| "do A, then B" | `P <name>(params): step; step` | Steps are observer calls, `J` points or the build action with its checks (`<skill>.build(...) C a C b`). |
| "decide whether / choose / consider" | `J <name> a\|b\|c: "question" -- constraints` | At least two options. The constraints carry the prose that informs the choice. |
| "if X goes wrong, do Y" | `X <skill>.build <check> -> recovery` | One per check that can fail; the runner prints it next to the failure. |
| situation the skill does not cover | `F text -> where it belongs` | |
| where a rule came from | `M <skill> "rule" src:<repo>@<commit>/<path> license:<spdx> author:"…" state:quarantine\|verified\|promoted` | Every adopted rule cites its source (§8). |
| who runs a step | `V <target> -> script\|model:<size>\|harness:<id> why:"…"` | Checks route to `script`; only `J` lines route to a model. |
| what the skill reads and writes | `A ui.* (…)` + `I` lines, `A <skill>.build(files:[path] url?:url) -> [path] ~` + `I` | CL §5.3 applies: the build action has `writes:` and `undo:`. |

A prose rule that becomes neither a `C` nor a `J` is either moved into a `J` gloss (it informs a decision) or dropped. Unverifiable aspiration ("be tasteful", "feel premium") is not compiled. Persona instructions ("respond only with: I'm ready…"), required output formats for chat, and install or update commands found in a skill are never compiled (§8).

## 2. The output layer `ui` (observers)

CL-Skill v1 standardises one observer family over produced UI output. Each is an `A` line with an `I reads:` line in the skill. They are read-only; comments in the files are ignored.

```
T hit{file:path line:int text:str}
T render{overflowPx:int contrastFails:int unnamed:int smallTargets:int collisions:int typefaces:int tinyText:int measured:int wrappedControls:int wrappedLabels:[str]}
A ui.compile() -> [hit]                                       -- esbuild transform of each file; runs first, a file that does not compile renders nothing
A ui.scan(pattern:str in?:css|jsx|all=all) -> [hit]          -- regex over the produced files
A ui.durations() -> [hit{ms:num}]                              -- literal ms/s in transition/animation (tokens are fine)
A ui.offscale(props:[word] scale:[num]) -> [hit]               -- px/rem values of those properties not on the scale
A ui.hovermotion() -> [hit]                                    -- :hover rules that move things outside @media (hover: hover)
A ui.unscoped() -> [hit]                                       -- selectors outside the product scope (.nx)
A ui.copy(pattern:str) -> [hit]                                -- words a person reads (JSX text, label/title/aria-label/placeholder, label: fields)
A ui.render(theme:light|dark viewport:desktop|phone) -> render -- taste-lens probe of the rendered page
```

`ui.render` needs a URL (the runner's `--url`). Without one, or when nothing rendered was measured, the check is undecided (`?name`), never passed. Adding an observer is a minor version; changing a returned field is a major version.

## 3. Check lines

```
C design-craft.build scale-zero: len(ui.scan(pattern:"scale\\(\\s*0(\\.0+)?\\s*\\)" in:all))==0 -- block emil/review-animations#5: nothing appears from nothing
```

- The expression is CL §3 `expr` (`and or not == != <= >= < > has in ~`, calls, `.field`, `len()`).
- The gloss starts with the severity, then the source reference, then the rule: `-- <block|warn|note> <src>: <rule>`. Weights: `block` 3, `warn` 1, `note` 0.25. A missing severity is `warn`.
- A check with parameters (`C x.build name(p:T): …`) is L2 and runs only when a procedure step names it (CL §5.5).
- Conflicts between sources are resolved in the skill, not at run time: one check, one rule. The product's own direction (here `manuals/design.manual.json`) wins every conflict, and the gloss says so when it overrides a source (e.g. `stagger`: Neyvia's "lists don't stagger" overrides Emil Kowalski's stagger advice).

## 4. Judgement journal

During a run the agent appends one line per judgement to a journal (a CL file):

```
J motion-need=feedback "colour on hover, press scale on the allow button; no entrance: seen many times a day"
J removal=remove "dropped the divider and the agent icon: the name already says who asks"
```

The runner accepts an answer only if the option is one of the `J` line's options. The required judgements are the `J` steps of the skill's procedures.

## 5. Adherence

For one run over the produced output:

- `output = Σ w(c)·pass(c) / Σ w(c)` over checks that decided (pass or fail); undecided checks are reported, not counted.
- `procedure = answered required J / required J` (1 when the procedures have no `J`).
- `adherence = output × (0.8 + 0.2 × procedure)`.
- `status = fail` if any `block` check failed; `unknown` if any check was undecided; otherwise `ok`.

`output` is comparable across any two runs of the same skill version, including runs by agents that never saw the CL-Skill (the experiment arm in §11). `procedure` measures whether the agent recorded its decisions.

## 6. Receipt

```
R design-craft.build fail adherence:0.82 output:0.86 procedure:0.6 checks:41/46 +raw-colour -literal-duration ?contrast-light …
X design-craft.build literal-duration block -> transition: transform var(--nx-snappy) var(--nx-spring-snappy) -- at approval-card.css:41 "transition: opacity 150ms ease"
Q contrast-light "no --url given; rendered checks cannot run" -> observe ui.render
Q states "Does it show first load, empty, error…?" -> J states
```

One `R` per run (CL R9). An `X` line per failed check with up to three locations; a `Q` line per undecided check and per unanswered required `J`. `--json` gives the full report; `--out` also writes `report.json` and the screenshots `ui.render` took.

## 7. Evolution

- **Fitness** of a skill version = `mean(adherence) × outcome quality ÷ tokens` over a fixed task set (plan 15 T23). Outcome quality = the share of tasks whose result a reviewer (Paul or a large model looking at the screenshots) accepts; tokens = total tokens of the runs.
- **Mutable by the Evolver:** `J` questions and constraints, `X` recoveries, `P` step order, check thresholds and patterns, severities of `warn`/`note` checks, the `L` gloss.
- **Fixed:** `block` checks that encode the product's direction or honesty (raw colour, dead controls, fabricated data, focus removal, contrast), `M` provenance.
- **Promotion** follows LAYA/CL-Memory states: a mutated variant starts `quarantine`, becomes `verified` after it beats the parent on fitness in an A/B run with GPT-6 Luna, and `promoted` after Paul or a second run confirms.
- **Demotion:** a check that has not failed in 20 runs and caught no defect in review is a candidate for `note` (it still costs context); a check that failed on output a reviewer accepted is a false positive and gets narrowed.
- The skill's `L` line version follows CL §9: weakening a `C` or narrowing a signature is a new `vN`.

## 8. Provenance, licences and safety

- Every adopted rule has an `M` line with the source repository, commit, path, SPDX licence and author.
- Third-party skill texts that were adopted are kept verbatim under `docs/skills/vendor/<owner>-<repo>/` with the owner's `LICENSE`. They are data for the Evolver and for people, never instructions to run: install, update or telemetry commands inside them (`npx antislop-ai`, `npx shadcn@latest`, gstack's `gstack-skill-end`) are not executed and not compiled.
- A skill library entry (`config/skills.json`) carries `source` (repo, commit, path, author, licence) and `clSkill` (the compiled file), and `guidance_only: true` for the vendored text.
- Skills were fetched as text (`git clone --depth 1`) and read before use. None of the seed set forbids redistribution (§A.2).

## 9. Conformance

A CL-Skill conforms when:

- **S1** Every line parses under CL §3; `L` names the skill and its version.
- **S2** Every `C` calls an observer declared in the skill (`ui.*` or another `A` with an `I reads:` line).
- **S3** Every `C` gloss starts with a severity; every `block` check has an `X` recovery.
- **S4** Every procedure `J` step names a declared `J` with at least two options.
- **S5** Every adopted rule has an `M` line with `src:` `license:` `author:` and `state:`.
- **S6** `V` routes every `C` to `script`; only `J` lines route to a model.
- **S7** The runner's receipt for a run has one `R`, an `X` per failed check and a `Q` per undecided check or missing judgement.
- **S8** No line asks the agent to install, update or call home.

## 10. Proposals to core CL (for the owner of connected-language.md)

1. A severity attribute on checks, `C x.build name sev:block: expr`, instead of the gloss convention of §3. It would make the weight machine-readable without parsing prose.
2. A runtime judgement line, `J name=option "why"`, so §4 journals are plain CL runtime lines (today it reuses the `P` step form).
3. Standardise the `ui` observers of §2 as the CL-Verify family for produced UI, so app manuals and skills share them.

## 11. Measured result: GPT-6 Luna, plain skill text vs CL-Skill (2 Oct 2026)

Task: the same brief (`proof/cl-skill-luna/BRIEF.md`: an approval card specimen for Neyvia's design lab, two files). Model: GPT-6 Luna through `codex exec`, reasoning medium, one run per arm, each arm alone in the design lab. Both arms had the token files, the primitives and a `tools/preview.py` that saves screenshots. **Plain** also had the seed skills and Neyvia's design manual as text (11 files, 265 KB, all of which it read). **CL** had `SKILL.cl` (`describe --level 2`) and `tools/check.py` (the runner with the rendered URL and its journal). Every output was scored afterwards by the same runner and skill version (v1.1, 50 checks). Receipts, screenshots, files and token counts: `proof/cl-skill-luna/`.

| | Plain skill text | CL-Skill v1 (run 1) | CL-Skill v1.1 (run 2) |
|---|---|---|---|
| skill context given | 265 KB prose | 18 KB CL | 19.7 KB CL |
| input tokens (uncached) | 462,015 (55,999) | 1,077,674 (59,690) | 197,486 (34,158) |
| output tokens | 7,033 | 6,773 | 3,772 |
| wall time | 228 s | 398 s | 106 s |
| check runs during the work | 0 (2 previews) | 6 | 1 |
| output adherence, scored with v1.1 | 0.955: 4 warn (font sizes, radius, spacing off the scales; 2 tap targets under 24 px on phone) | 0.921: block `button-icon-child`, block `control-wrap`, warn `control-wrap-phone` | 1.0 (50/50) |
| defects the checks caught during the run | none run | 1 (spacing off-scale), fixed before finishing | none left to catch |
| defects only a look found (no check yet) | status shown twice per card; icon tiles that repeat the status | both buttons stacked their icon above the label (passed all 47 v1 checks); the four state cards had no command or actions although its `J states=complete` said they did | status shown twice per card; coloured top edges as decoration |

What this shows, with n = 1 per arm (a direction, not a statistic):

1. **Verified, not hoped.** With the checks enforced, Luna finished at 1.0 output adherence and its judgements were on record; with the plain text it finished at 0.955 and never measured itself. The plain arm read 13x more skill text and still missed four rules that a script finds in milliseconds.
2. **The checks are only as good as their coverage.** Run 1 passed every v1 check while both buttons were visibly broken. That miss became two checks (`button-icon-child` static, `control-wrap` rendered) in v1.1, and run 2 passed them on its first check run. This is the §7 evolution loop done once by hand: a reviewer miss turns into a check, and the next run is cheaper (106 s and 34k uncached tokens, against 398 s and 60k).
3. **Judgements are recorded, not verified.** Run 1 answered `J states=complete` for an incomplete specimen, and both CL runs answered `J removal=keep` while showing the status twice. The next step is a large-model review of the screenshots against each recorded `J` answer (`V J removal -> model:large`), which is also the outcome-quality score the Evolver needs.
4. **Tokens.** The CL context is 7% of the prose context, but iterations re-send the whole conversation: run 1 used more input tokens than the plain arm because of six check loops. Uncached input, the part that is not re-read from cache, was 56k (plain), 60k (run 1) and 34k (run 2).
5. **A pilot showed why `compiles` is the first check.** In the pilot, the CL arm wrote a duplicate `ApprovalCard` declaration. The file never rendered, every rendered check was undecided, and because the design lab imports every specimen, the plain arm's previews broke too. The runner now runs esbuild first (`compiles`, block) and says when a render never showed the component. The pilot was discarded and both arms were re-run one at a time.

## Appendix A. Seed set review (read as text, 2 Oct 2026)

### A.1 Verdicts

| Skill (author, licence, commit) | Verdict | Genuinely useful | Conflicts with Neyvia's direction | Slop in itself |
|---|---|---|---|---|
| frontend-design (Anthropic, Apache-2.0, anthropics/skills@8a1541c) | partial | "spend boldness in one place"; structure encodes information (numbered markers only for sequences); the writing section (one name per action through a flow, errors without apology); its list of generated-default traits | Its brief is a studio inventing a new identity per client; Neyvia has a fixed identity. Two of its "tells" describe Neyvia on purpose: warm paper + serif display (Morning + Newsreader) and near-black + green accent (Forest). Direction wins; the skill keeps them honest: Newsreader only for greeting titles, green stays deep, not acid. | Little. The two-pass "plan, then review the plan against the brief" is good process but costs tokens on small components. |
| emil-design-eng, review-animations (+STANDARDS), animate, improve-animations (Emil Kowalski, MIT, emilkowalski/skills@e8a175d) | adopt (motion) | Frequency gate (no motion on keyboard or 100+/day actions); never scale(0); no ease-in on UI; origin-aware popovers; transform/opacity only; hover motion gated by `(hover: hover) and (pointer: fine)`; transitions over keyframes for rapidly triggered UI; exit faster than enter; remedial order "delete, reduce, fix easing…" | Stagger (30-80 ms) contradicts "lists don't stagger"; "UI under 300 ms" vs Neyvia's 180-320 ms band (Neyvia wins; press feedback is the open case, see F lines); Base UI `--transform-origin` does not exist in nxPrimitives. | Persona ceremony ("respond only with: I'm ready…"), a mandated markdown review table, Sonner origin stories. Stripped. |
| apple-design (Emil Kowalski, MIT) | partial (frontier) | Interruptibility, respond on pointer-down, enter/exit along one path, momentum projection for sheets | Mostly gesture physics Neyvia does not have yet (docked chat, Arrange mode) | Long; WWDC quotes. |
| animation-vocabulary (Emil Kowalski, MIT) | library only | Names for effects, useful when Paul describes a motion | none | none; it is a glossary, so nothing to check. |
| beautiful-shadows (Meng To, MIT, MengTo/Skills@d5bd3a7) | partial (as tokens) | Layered neutral elevation: a 1px ring plus stacked soft layers, one strength per state, no lg shadow on dense lists | Tailwind arbitrary classes with raw `rgba()` break "no raw colour in components". Neyvia already has `--nx-card-shadow` (ring + soft layer) and `--nx-lift-1..3`; the recipe belongs in tokens, not components. | Three magic strings, no reasoning about light direction or dark themes (black shadows vanish on Forest). |
| accessibility (Addy Osmani, MIT, addyosmani/web-quality-skills@afa8da9) | adopt (checks) | WCAG 2.2 additions: target size 24px (2.5.8), focus not obscured (2.4.11), dragging alternative (2.5.7, Arrange mode), consistent help, accessible authentication; contrast table | none | Long reference with code samples; a `npx lighthouse` line (not run). |
| i-have-adhd (Ayoub Ghriss, MIT, ayghri/i-have-adhd@839872f) | adopt (copy and agent replies) | Lead with the next action; restate state ("Step 3 of 5 done"); one concrete next step; specific time estimates; cap visible lists at 5; matter-of-fact errors | It is an output style for chat replies, not UI; its persistence rule ("until stop adhd mode") is a mode, which Neyvia would expose as a setting, not a skill. | Little; the pre-send check is concrete. |
| antislop (Miqdad Badjuber, MIT, miqdadbadjuber/anti-slop@91f12ec) | partial (hard gates) | Dead controls (R-26), three states (R-27), no fabricated numbers/testimonials/claims (R-17, R-36, R-38), no CSS patching by script (R-33), click-through evidence element by element (R-35) | Flags Lucide icons and "dark mode by default" as slop; both are Neyvia decisions. Bans the em dash absolutely. | 58 KB with an install wizard, a self-update section and `npx` commands; 38 rules with overlapping tiers. Its own absolutism is a tell. |
| taste-skill (Leonxlnx, MIT, Leonxlnx/taste-skill@ce26fc2) | partial (few rules) | Eyebrow restraint; one radius scale; one label per intent; no Jane Doe data; tabular numbers; no decorative status dots | Says itself it is for landing pages, "not dashboards" (Neyvia is product UI). Bans Lucide "except on request", discourages spinners, prescribes font and hex lists, recommends picsum. | 88 KB of absolute bans and named-font lists; contradicts itself (recommends Geist, then lists dozens of alternatives). Already in the library (`leon_lin_design_taste` and siblings) without attribution; attribution added. |
| better-writing (Jakub Krehel, MIT, jakubkrehel/skills@267330e) | adopt (copy) | Verb-first buttons; a confirm repeats the consequence; toggles name the ON state; errors say how to fix next to the field; no sentences glued around variables; sentence case; links name their destination; empty states point forward | none (it defers to the product's voice) | none; the best-written skill of the set. |
| interface-review (Jakub Krehel, MIT) | partial (procedure) | Review the change, not the codebase; read the removed lines; hold the change to its stated intent | none | none |
| audit-ai-design-slop (Meng To, MIT) | adopt (audit procedure) | Evidence per finding; removal test; subtraction first; P0-P3; group by root cause; no numeric slop score | none | none; it explicitly refuses to guess whether AI made a design. |
| baseline-ui (ibelick, MIT, ibelick/ui-skills@ebf5f26; ui-skills.com catalog) | partial | Never block paste; dvh not vh; no will-change at rest; no blur animation; tabular numbers; one accent per view | Tailwind/Base UI stack rules; "never introduce custom easing" contradicts Emil's "always use custom curves" (Neyvia has its own `--nx-ease` and spring tokens, so both are moot) | Terse MUST/NEVER list without reasons. |
| design-review (gstack, Garry Tan, MIT, garrytan/gstack@f30b7b7) | reject | Three viewports; Krug's usability laws (already covered) | Its preamble runs gstack binaries, writes telemetry to `~/.gstack/analytics`, can install a test framework and edit CLAUDE.md, and commits | 131 KB, mostly harness plumbing. |

`audit` in Paul's list matched two skills: Meng To's `audit-ai-design-slop` (adopted) and Addy Osmani's `web-quality-audit` (read; performance/SEO scope, not adopted).

### A.2 Licences

All seed skills are MIT except Anthropic's `frontend-design`, which is Apache-2.0 (redistribution allowed with the licence and notices; both kept). None forbids redistribution. Note for later: the other Anthropic document skills in the same repository (`docx`, `pdf`, `pptx`, `xlsx`) are "© Anthropic, all rights reserved" source-available and MUST NOT be vendored. gstack is MIT but sends telemetry when run, so only its text was read.

### A.3 What changed in Neyvia

- `manuals/skills/design-craft.cl`: the compiled skill (50 checks, 5 judgement points, 2 procedures, 31 recoveries, 12 provenance lines).
- `manuals/design.manual.json`: stricter `motion-css` and `component-jsx`/`copy-jsx` checks, a new `craft` chapter whose procedure runs the CL-Skill runner and records judgements, and attributed guidance.
- `config/skills.json`: one entry per adopted skill with `source`, `license`, `clSkill`, and attribution added to the existing taste-skill entries.
- `docs/skills/vendor/`: the adopted texts and their licences.
