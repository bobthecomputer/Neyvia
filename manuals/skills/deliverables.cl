CL 1
-- deliverables: CL-Skill for what makes a result feel finished (plan 20 C9.1). Compiled from Paul's round-2 reasons
-- (he spotted Claude 9 of 10 times: a real report as the deliverable, a title on the first line that names the thing,
-- a small summary table, a structure that helps him read, finish and taste; the one miss was a simple task where he
-- still expected structure). Runs next to no-slop.cl; the CL host applies both before done() (plans/15-handoff.md ## C9).
-- Reference observers and calibration on the 18 preference pairs: proof/c9-deliverables/prototype.py

-- L0
L deliverables v1 tools:language.check src:plans/20-revolutionise-computer-and-browser-use.md#C9 -- a result is a named file with a title, the answer first, a table when 3+ facts compare, and what is missing

-- L1
T hit{file:path line:int text:str match:str}
T doc{file:path kind:md|html|code|text words:int title:str|null headings:[str] tables:int comparableFacts:int lead:str}
A deliverable.docs() -> [doc] -- the task's deliverables: text, report and UI files written during the task (same set the no-slop gate reads), code files listed but not judged
I deliverable.docs reads:files
A deliverable.chatdump(max:int) -> [hit] -- the done() summary is longer than max words and the task wrote no deliverable file
I deliverable.chatdump reads:done-summary,files
A deliverable.untitled(generic:str) -> [hit] -- a report whose first non-empty line is not a heading (or bold line), a UI page without <title> and <h1>, or a title matching generic
I deliverable.untitled reads:files
A deliverable.tableless(min:int) -> [hit] -- a report with at least min comparable numeric facts (list items or label: value lines with numbers) and no table
I deliverable.tableless reads:files
A deliverable.buried(verdict:str) -> [hit] -- the first sentence after the title holds no number, no code, no file and no verdict word
I deliverable.buried reads:files
A deliverable.flat(words:int) -> [hit] -- a report of at least words words with fewer than 2 sections (a section is a heading or a bold lead such as **Mechanism.**)
I deliverable.flat reads:files
A deliverable.unstructured(words:int) -> [hit] -- a report of at least words words with no heading, table or list at all
I deliverable.unstructured reads:files
A deliverable.silent(words:int pattern:str) -> [hit] -- a report of at least words words that never says what is missing, assumed or unproven
I deliverable.silent reads:files
A deliverable.unfinished(need:[word]) -> [hit] -- a UI page missing one of: dark (prefers-color-scheme: dark), focus (:focus-visible), motion (prefers-reduced-motion), title
I deliverable.unfinished reads:files
A deliverable.oversized(ratio:int floor:int) -> [hit] -- a simple ask (one ask, under 60 words) answered with more than max(floor, ratio x task words) words; undecided when the host has no task text
I deliverable.oversized reads:task,files
A deliverables.finish(files:[path]) -> [path] ~ -- the finishing pass; every check below runs on the result
I deliverables.finish writes:files deps:[manuals/skills/no-slop.cl manuals/skills/design-craft.cl] undo:"keep the previous file until the pass is green"

-- the deliverable is a named thing
C deliverables.finish named-file: len(deliverable.chatdump(max:150))==0 -- block paul/r5-blind#real-report: a result longer than a short reply is a file (report.md, the page, the code), not a chat dump
C deliverables.finish titled: len(deliverable.untitled(generic:"(?i)^(answer|report|summary|results?|output|notes?|document|untitled|plan|idea|readme|task|response|draft)\\.?$"))==0 -- block paul/r5-blind#names-things: the first line is a title that names the thing (Close the sink: five tubs, no commons), not Answer or Report
C deliverables.finish no-placeholder: len(text.match(pattern:"(?i)lorem ipsum|\\bTODO\\b|\\bTBD\\b|\\[insert|\\bplaceholder text\\b|xx+ ?(ms|%|\\$)" in:all))==0 -- block antislop#R-17: nothing unfinished or invented ships
C deliverables.finish ui-finished: len(deliverable.unfinished(need:[dark focus title]))==0 -- block neyvia/design#check-loop: a UI deliverable works in light and dark, shows focus and has a title
-- structure that helps him read (warnings: the host reports them; they do not refuse done)
C deliverables.finish summary-table: len(deliverable.tableless(min:3))==0 -- warn paul/r5-blind#summary-table: 3 or more comparable facts go in a small table (before, after, change)
C deliverables.finish result-first: len(deliverable.buried(verdict:"(?i)\\b(passed|failed|faster|slower|fixed|works|reached|from .+ to|down from|up from|cut|saved|best|wins?|is the)\\b"))==0 -- warn paul/r5-blind#structure: the answer comes first (5976 ms to 2.4 ms), evidence after
C deliverables.finish sections: len(deliverable.flat(words:120))==0 -- warn paul/r5-blind#structure: a report of 120+ words has sections (headings or bold leads) in a stable order: result, evidence, what is missing
C deliverables.finish some-structure: len(deliverable.unstructured(words:40))==0 -- warn paul/r5-blind#miss: even a short deliverable gets a title plus one structure device (a list, a table or a heading)
C deliverables.finish says-what-is-missing: len(deliverable.silent(words:250 pattern:"(?i)\\b(missing|not done|not covered|limit\\w*|risk\\w*|caveats?|assumptions?|open (questions|items)|unknowns?|unproven|next steps?|fails? if|kills? it|not (yet )?(proven|tested|measured|checked))\\b"))==0 -- warn working-with-paul#done: a long report names what is not done or not proven
C deliverables.finish ui-motion: len(deliverable.unfinished(need:[motion]))==0 -- warn neyvia/design#motion: motion respects prefers-reduced-motion
C deliverables.finish proportion: len(deliverable.oversized(ratio:12 floor:250))==0 -- warn paul/r5-blind#proportion: a simple ask gets a short, still-structured answer

-- L2
J proportion simple|report: "Is this one simple ask, or work whose result he will read as a report?" -- simple: title, 1-5 lines or a short list, no padding; report: title, result line, table if 3+ facts, evidence, what is missing. When unsure choose report: his one miss was a simple task where he expected structure.
J name keep|rename: "Does the first line name this exact thing so he could find it among 50 others?" -- name the object and its distinctive trait (Coil: a napkin snake game; Plan limits card), never the genre (Story, Answer, Report).
J table table|list|prose: "Do 3 or more facts share the same columns (before/after, option/cost, check/result)?" -- table when they do; list when they are steps; prose for one argument.
J finish ship|polish: "Read it once as Paul: is there one thing that looks unfinished, generic or out of order?" -- polish fixes that one thing (the order, a vague line, a missing unit, a cramped UI state) and runs the checks again; then ship.
P finish(files:[path]): J proportion; deliverables.finish(files) C named-file C titled C no-placeholder C ui-finished; language.check(paths:files); J name; J table; J finish
P review(files:[path]): deliverable.docs(); J proportion; J name; J table -- review only: list each finding with file:line and the fix
X deliverables.finish named-file -> write the result to a file named after the thing (sink-lids.md, run-card.html) and keep the done summary to 1-3 lines that point at it
X deliverables.finish titled -> first line "# <the thing and its trait>": "# Close the sink: five tubs, no commons", "# count_primes: 6.6 s to 0.4 ms"
X deliverables.finish no-placeholder -> replace the placeholder with the real value from the run's receipts, or remove the line
X deliverables.finish ui-finished -> add the dark tokens under @media (prefers-color-scheme: dark), a :focus-visible ring and a <title> that names the page
X deliverables.finish summary-table -> a 3-6 row table: | Change | Before | After | with units; keep the prose for the why
X deliverables.finish result-first -> move the measured result to the first line under the title
X deliverables.finish sections -> headings or bold leads in this order: result, how, evidence, what is missing
X deliverables.finish some-structure -> add a 2-4 item list or a 2-row table; keep it short
X deliverables.finish says-what-is-missing -> one short section: what was not done, not measured or assumed, in plain words
X deliverables.finish proportion -> cut to the result, one line of evidence and the structure device
F taste beyond these checks (an apt name, a niche detail, a polished UI state) is judged by the pairwise judge calibrated on his votes -> plans/20 C9.3
F a deliverable he asked to be a chat reply (a quick question) has no file -> J proportion=simple and the chat answer is the deliverable
M deliverables "Claude adds a small summary table; produces a real report as the deliverable; the report's structure helps; finish and taste; names things well (title on the first line)" src:plans/20-revolutionise-computer-and-browser-use.md#round-2-result author:Paul state:verified
M deliverables "the one miss: a simple task where Claude kept it simple and Paul expected structure" src:plans/20-revolutionise-computer-and-browser-use.md#round-2-result author:Paul state:verified
M deliverables "static checks prefer his pick in 6 of 10 decided pairs (8 ties) on the 18 R4+R5 pairs: necessary finish, not the whole of taste" src:proof/c9-deliverables/prototype.py author:Claude state:quarantine
M deliverables "removal test and evidence per finding" src:github.com/MengTo/Skills@d5bd3a7/agent-skills/ui/audit-ai-design-slop/SKILL.md license:MIT author:"Meng To" state:verified
V C deliverables.finish -> script why:"structure, titles, tables and theme rules are parsable"
V J finish -> model:small why:"one read-through with the four questions"
