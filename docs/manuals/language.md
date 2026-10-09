<!-- Generated from manuals/cl/language.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# language

## overview
CL 1
L language v1 -- Words in UI and reports: no decorative dashes, hype, filler, noise labels or padding; numbers over adjectives
T t1{ok:bool clean:bool verdict?:str blocking:int warnings:int words?:int failed:json:"{\"type\":\"array\"}" cl?:str ..}
T t2 [str]#..40
T t3 json:"{\"type\":\"string\",\"enum\":[\"report\",\"ui\"]}"
S language.file:t1=neyvia.language.check(path:path)
A neyvia.language.check(path?:str paths?:t2 text?:str kind?:t3) -> t1 ! -- Run the no-slop CL-Skill checks on files or text; return each hit with file, line, match and fix
C neyvia.language.check clean:neyvia.language.check(path:path) .blocking == 0
C neyvia.language.check clean-text:neyvia.language.check(text:text) .blocking == 0
C neyvia.language.check clean:neyvia.language.check(path:path) .blocking == 0
C neyvia.language.check clean-text:neyvia.language.check(text:text) .blocking == 0
P check-file(path:str):result=neyvia.language.check(path:path) C clean -- A report or UI file passes every block check of the no-slop skill
V P check-file -> script why:"typed manual runner; stops at every judgement"
P check-text(text:str):result=neyvia.language.check(text:text) C clean-text -- A summary, label or message passes every block check before it is sent
V P check-text -> script why:"typed manual runner; stops at every judgement"
J cut keep|cut:"Does each flagged sentence carry a fact, a number, a step or a decision the reader needs?" -- Removal test: if cutting the sentence loses no fact, number, step or decision, cut it. Openers that restate the task and closers that restate the body or offer help are cuts.
V J cut -> human:operator why:"explicit choice required"
J number give|drop:"For each size or speed word: is the measured number known?" -- give = write the measured number with its unit next to the claim (37 ms, 4 of 6, $0.02); drop = delete the size word. Never invent a number.
V J number -> human:operator why:"explicit choice required"
X An em dash, en dash or spaced hyphen joins two thoughts or decorates a heading -> Full stop for two thoughts, colon for a result or list, brackets for an aside; a tight en dash stays only in number or day ranges
X Hype or filler words (seamless, powerful, in order to, it's worth noting, breathing room) stand where a fact belongs -> Delete the phrase; name the effect and its size
X A UI label is chatty or soothing (Your plan eyebrow, comfortably, just, simply, let's) -> A label is the noun, the verb or the state: Plan limits, Slow down, 62% used
X A report opens with Here is or closes with Let me know / In summary -> Start with the answer; stop when it is said
X much faster, a lot cheaper, several, significantly with no number in the sentence -> Give the measured number or delete the word
X done() is refused with X language lines -> Rewrite exactly the quoted lines, run language.check(path=...) on the file, then done() again
F Tone that is clean by these checks but cold or rude needs a reader; word lists are English, dash and number rules apply to every language.
F The host gate checks prose and UI files written during the task (.md .txt .html .jsx .tsx) and the done() summary; code comments and quoted sources are not checked.
M language "Plain short sentences, 30 words or fewer; UI lines 14 words or fewer." src:"authored manual" state:verified
M language "No em dash or en dash as punctuation, in headings too: 'Weekend plan: final note', not 'Weekend plan — final note'." src:"authored manual" state:verified
M language "No hype (seamless, powerful, cutting-edge, leverage, unlock, elevate, delve, robust as praise) and no filler (in order to, it's worth noting, basically, essentially, at the end of the day)." src:"authored manual" state:verified
M language "UI labels name the thing, the action or the state; no eyebrow that repeats the title, no soothing words (comfortably, gently, breathing room, all set, just, simply)." src:"authored manual" state:verified
M language "Numbers over adjectives: 7x cheaper ($0.15 to $0.02), not much cheaper; 4 of 6 tests, not most tests. With no number, drop the adjective." src:"authored manual" state:verified
M language "One hedge per sentence at most; say what is known and what is not." src:"authored manual" state:verified
M language "Reports start with the result and stop when it is said: no 'Here is', 'Let me know', 'In summary', 'I hope this helps'." src:"authored manual" state:verified
M language "Before done(), run language.check on every report and UI file you wrote; the host refuses done() while a block check fails and names each line." src:"authored manual" state:verified
M language "The full rule set with sources is the CL-Skill manuals/skills/no-slop.cl; its checks are the same code the host runs." src:"authored manual" state:verified
