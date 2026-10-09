CL 1
-- no-slop: CL-Skill for words in UI and reports (plan 20 C5). Compiled from Paul's round-1 blind-test tells
-- (filler language, decorative dashes, noise words in UI and reports), the design manual's copy rules and the
-- sources in the M lines. Paul's style wins every conflict.
-- Runner: python -m grant_agent.neyvia_language check <files> ; tool: neyvia.language.check(path|paths|text)
-- The CL host runs every block check on the task's new text files and the done() summary before it accepts done().

-- L0
L no-slop v1 tools:language.check src:plans/20-revolutionise-computer-and-browser-use.md#C5 -- plain words in UI strings and reports: no decorative dashes, hype, filler, padding; numbers over adjectives

-- L1
T hit{file:path line:int text:str match:str}
A text.match(pattern:str in?:prose|ui|heading|all=all words?:int) -> [hit] -- regex over words a person reads; words: only segments up to that many words (labels)
I text.match reads:files
A text.dashes(in?:prose|ui|all=all) -> [hit] -- em/en dashes and spaced hyphens used as punctuation; tight ranges (3-5, Mon-Fri) are data
I text.dashes reads:files
A text.vague(pattern:str in?:prose|ui|all=all) -> [hit] -- the pattern inside a sentence that has no number and no code
I text.vague reads:files
A text.stacked(pattern:str min:int in?:prose|ui|all=all) -> [hit] -- sentences with at least min matches
I text.stacked reads:files
A text.edges(opening:str closing:str) -> [hit] -- a preamble as a file's first sentence, a sign-off anywhere
I text.edges reads:files
A text.long(max:int in?:prose|ui|all=prose) -> [hit] -- sentences longer than max words
I text.long reads:files
A text.repeats(in?:ui|all=ui) -> [hit] -- the same visible words twice (eyebrow echoing the title)
I text.repeats reads:files
A no-slop.write(files:[path]) -> [path] ~ -- write or rewrite the text; every check below runs on the result
I no-slop.write writes:files deps:[manuals/skills/no-slop.cl] undo:"keep the previous text until the rewrite passes"

-- dashes (Paul R4: decorative dashes were a tell in 5 of 8 Luna outputs he spotted)
C no-slop.write decorative-dash: len(text.dashes(in:all))==0 -- block paul/r4-blind#dashes: no em dash, en dash or spaced hyphen as punctuation; use a full stop, comma, colon or brackets
-- hype and filler (Paul R4 + antislop + taste-skill 9.D)
C no-slop.write hype: len(text.match(pattern:"(?i)\\b(seamless(ly)?|effortless(ly)?|cutting[- ]edge|state[- ]of[- ]the[- ]art|best[- ]in[- ]class|world[- ]class|game[- ]chang(er|ing)|revolutionar(y|ise|ize)|supercharg\\w*|unleash\\w*|elevate[sd]?|empower\\w*|leverag(e|es|ed|ing)|delv(e|es|ing)|powerful|blazing(ly)?|lightning[- ]fast|next[- ]gen\\w*|synerg\\w*|holistic|transformative|magical(ly)?|delightful(ly)?|stunning|sleek|unparalleled|groundbreaking|turbocharg\\w*|world-changing|unlock(s|ing)? (the|your|new))\\b" in:all))==0 -- block antislop+taste-skill#9.D: no marketing words; say what it does and how much
C no-slop.write filler: len(text.match(pattern:"(?i)(\\b(it'?s|it is|it’s) (worth noting|important to note)|\\bneedless to say|\\bat the end of the day|\\bin today'?s|\\blet'?s dive|\\bdive (in|into)\\b|\\bfeel free to|\\bi hope (this|that) helps|\\bhappy to help|\\bgreat question|\\brest assured|\\bwithout further ado|\\bin the realm of|\\bwhen it comes to|\\ba wide (range|variety) of|\\bplays? a (crucial|key|vital|pivotal) role|\\bfirst and foremost|\\blast but not least|\\bsimply put|\\bin order to\\b|\\bbasically\\b|\\bessentially\\b|\\bliterally\\b|\\bbreathing room|\\beverything ahead|\\bpeace of mind|\\bto the next level|\\bin a nutshell|\\bthe bottom line is|\\bat its core\\b)" in:all))==0 -- block strunk#13+paul/r4-blind#filler: omit needless words; the sentence must still carry its fact
C no-slop.write ui-noise: len(text.match(pattern:"(?i)\\b(simply|easily|just|smart(ly)?|magic|awesome|amazing|oops|hooray|yay|voil[aà]|comfortabl[ye]|gentl[ey]|breathing room|all set|good to go|no worries|journey|hassle[- ]free|at a glance|welcome (back|to)|let'?s)\\b|^(your|my) (plan|account|dashboard|space|workspace|overview|limits|usage)$" in:ui words:12))==0 -- block paul/r4-blind#noise-words+neyvia/design#copy: a UI label names the thing or the state; no chatty or soothing words
-- warnings: numbers over adjectives, hedges, padding, length
C no-slop.write vague-size: len(text.vague(pattern:"(?i)\\b(significantly|substantially|considerably|dramatically|drastically|noticeably|vastly|massively|hugely|greatly|much (faster|cheaper|smaller|larger|better|more|less|quicker|lower|higher|sooner)|far (faster|cheaper|better|more|less)|a lot|lots of|tons of|numerous|several|various|a few|a bit|slightly|huge|massive|tiny|enormous|negligible|minimal|quick(ly)?|fast(er)?|cheap(er)?|expensive|slow(er|ly)?)\\b" in:all))==0 -- warn paul/style#numbers: a size, speed or amount word needs the number next to it, or goes
C no-slop.write inflated: len(text.match(pattern:"(?i)\\b(robust|comprehensive|crucial|pivotal|vital|paramount|essential|key (insight|takeaway|benefit)s?|actionable|deterministic|meaningful|holistically|thoughtful(ly)?)\\b" in:all))==0 -- warn antislop#inflation: replace the adjective with the fact that earns it
C no-slop.write intensifier: len(text.match(pattern:"(?i)\\b(really|very|quite|truly|totally|definitely|clearly|obviously|extremely|incredibly|super|actually)\\b" in:all))==0 -- warn strunk#13: drop the intensifier or give the number
C no-slop.write hedge-stack: len(text.stacked(pattern:"(?i)\\b(may|might|could|possibly|potentially|perhaps|generally|typically|usually|often|likely|arguably|somewhat|depends? on|depending on|in some cases|to some extent|illustrative|roughly|approximately|tends? to)\\b" min:2 in:all))==0 -- warn paul/style#direct: one hedge per sentence at most; say what is known and what is not
C no-slop.write padding: len(text.edges(opening:"(?i)^(here('s| is| are)\\b|below (is|are|you'?ll find)|this (document|report|file|plan|note|summary|page) (describes|explains|outlines|contains|covers|provides)|i('ve| have) (created|written|made|prepared|put together|completed)|sure[,!.]|certainly[,!.]|absolutely[,!.]|great[,!.]|of course)" closing:"(?i)\\b(let me know|hope (this|that|it) helps|feel free|happy to help|in summary|to summari[sz]e|in conclusion|all in all|overall,)"))==0 -- warn jakub/better-writing#plain: start with the answer, stop when it is said
C no-slop.write long-sentence: len(text.long(max:30 in:prose))==0 -- warn paul/style#short: sentences of 30 words or fewer
C no-slop.write wordy-label: len(text.long(max:14 in:ui))==0 -- warn neyvia/design#copy: UI lines of 14 words or fewer
C no-slop.write ui-repeat: len(text.repeats(in:ui))==0 -- warn MengTo/audit-ai-design-slop#removal: the same words twice on one screen; drop the echo
C no-slop.write exclaim: len(text.match(pattern:"!(\\s|$)" in:all))==0 -- warn neyvia/design#copy: no exclamation marks
C no-slop.write emoji: len(text.match(pattern:"[\\u2600-\\u27BF\\U0001F300-\\U0001FAFF]" in:all))==0 -- warn neyvia/design#copy: no emoji

-- L2
J cut keep|cut: "Does this sentence carry a fact, a number, a step or a decision the reader needs?" -- removal test: if cutting it loses nothing, cut it. Openers that restate the task and closers that restate the body are cuts.
J number give|drop: "This size or speed word: do you have the measured number?" -- give: write the number with its unit next to the claim (37 ms, 4 of 6, $0.02). drop: delete the word; never invent a number.
J dash comma|stop|colon|brackets: "What does the dash join?" -- an aside = brackets or commas; a result or list = colon; two thoughts = full stop. A range keeps a tight en dash only between numbers or days.
J label noun|verb|state: "What is this UI line: the thing, the action or the state?" -- noun for titles (Plan limits), verb for buttons (Slow down), state for status (62% used, resets in 1 h 48 min). No eyebrow that repeats the title.
P write(files:[path]): no-slop.write(files) C decorative-dash C hype C filler C ui-noise; language.check(paths:files); J cut; J number; J dash; J label; language.check(paths:files)
P audit(files:[path]): language.check(paths:files); J cut; J number -- review only: list each hit with file:line and the rewrite
X no-slop.write decorative-dash -> "Weekend plan — final note" becomes "Weekend plan: final note"; "fine — you're within limits" becomes "Fine. You're within your limits."
X no-slop.write hype -> name the effect and its size: "seamless sync" becomes "syncs in 2 s"; "powerful search" becomes "searches 40k notes"
X no-slop.write filler -> delete the phrase and keep the fact: "In order to save" becomes "To save"; "It's worth noting that X" becomes "X"
X no-slop.write ui-noise -> a label is the noun, verb or state: "Your plan" eyebrow goes; "Everything's fine, comfortably within limits" becomes "Within limits"
X no-slop.write vague-size -> "much cheaper" becomes "7x cheaper ($0.15 to $0.02)"; with no measurement, delete the word
X no-slop.write inflated -> "robust error handling" becomes "retries 3 times, then shows the error"; "actionable error" becomes "error that names the file and line"
X no-slop.write intensifier -> delete it; if the strength matters, give the number
X no-slop.write hedge-stack -> keep one hedge, or state the condition: "may typically depend" becomes "depends on the provider (Anthropic: 10%)"
X no-slop.write padding -> delete the first sentence if it says what follows; delete the last if it repeats the body or offers help
X no-slop.write long-sentence -> split at the first "and", "which" or ";"
X no-slop.write wordy-label -> keep the noun or verb and the number; move the explanation to help text
X no-slop.write ui-repeat -> keep the title, delete the eyebrow or label that repeats it
F tone that is technically clean but cold or rude needs a reader -> J cut, critique-review manual
F non-English text: word lists are English; dashes and numbers still apply -> J dash
M no-slop "decorative dashes, filler language and noise words in UI and reports were the tells Paul used to spot one side (3 of 8 spotted)" src:plans/20-revolutionise-computer-and-browser-use.md@2026-10-04 author:Paul state:verified
M no-slop "no em dash in UI words" src:manuals/skills/design-craft.cl#em-dash author:Neyvia state:verified
M no-slop "no marketing words; concrete verbs; no fabricated numbers" src:github.com/Leonxlnx/taste-skill@ce26fc2/skills/taste-skill/SKILL.md license:MIT author:Leonxlnx state:verified
M no-slop "inflation and filler are hard failures in AI copy" src:github.com/miqdadbadjuber/anti-slop@91f12ec/antislop.md license:MIT author:"Miqdad Badjuber" state:verified
M no-slop "lead with the action; plain words; one idea per line" src:github.com/jakubkrehel/skills@267330e/skills/better-writing/SKILL.md license:MIT author:"Jakub Krehel" state:verified
M no-slop "omit needless words (rule 13)" src:"The Elements of Style, 1918" license:public-domain author:"William Strunk Jr." state:verified
M no-slop "removal test for every label and helper line" src:github.com/MengTo/Skills@d5bd3a7/agent-skills/ui/audit-ai-design-slop/SKILL.md license:MIT author:"Meng To" state:verified
V C no-slop.write -> script why:"every C is a regex or a count; no model needed"
V J cut -> model:small why:"one sentence at a time with the removal question"
V J number -> model:small why:"the number is in the run's own receipts or it is dropped"
