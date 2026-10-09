CL 1
L language v1 -- Authored executable manual
-- @manual {"chapters":{"overview":{"title":"Words in UI and reports: no decorative dashes, hype, filler, noise labels or padding; numbers over adjectives"}},"clVersion":"1.1","id":"language","kind":"workflow","schema":"neyvia.manual.v1","schemas":{"neyvia.language.check":"t1"},"tool_metadata":{"neyvia.language.check":{"mutability_class":"read"}}}
T t1{path?:str paths?:[str]#..40 text?:str kind?:json:"{\"type\":\"string\",\"enum\":[\"report\",\"ui\"]}" ..}
T t2{path:str}
T t3{ok:bool clean:bool verdict?:str blocking:int warnings:int words?:int failed:json:"{\"type\":\"array\"}" cl?:str ..}
T t4{text:str}
L language.overview v1 -- Words in UI and reports: no decorative dashes, hype, filler, noise labels or padding; numbers over adjectives
-- @record {"chapter":"overview","data":{"args":{"path":{"$input":"path"}},"inputs":{"$cl_type":"t2"},"shape":{"$cl_type":"t3"},"tool":"neyvia.language.check"},"key":"file","section":"state"}
S language.file:{ok:bool clean:bool verdict?:str blocking:int warnings:int words?:int failed:json:"{\"type\":\"array\"}" cl?:str ..}=neyvia.language.check(path:path)
-- @record {"chapter":"overview","data":{"effect":"Run the no-slop CL-Skill checks on files or text; return each hit with file, line, match and fix","pre":"Paths inside the workspace (or absolute) to Markdown, text, HTML or JSX; or inline text","returns":{"$cl_type":"t3"},"reversible":true,"schema":"neyvia.language.check","tool":"neyvia.language.check"},"key":"language.check","section":"actions"}
A neyvia.language.check(path?:str paths?:[str]#..40 text?:str kind?:json:"{\"type\":\"string\",\"enum\":[\"report\",\"ui\"]}") -> {ok:bool clean:bool verdict?:str blocking:int warnings:int words?:int failed:json:"{\"type\":\"array\"}" cl?:str ..} ! -- Run the no-slop CL-Skill checks on files or text; return each hit with file, line, match and fix
C neyvia.language.check clean:neyvia.language.check(path:path) .blocking == 0
C neyvia.language.check clean-text:neyvia.language.check(text:text) .blocking == 0
-- @record {"chapter":"overview","data":{"args":{"path":{"$input":"path"}},"expect":{"op":"eq","path":"blocking","value":0},"tool":"neyvia.language.check"},"key":"clean","section":"checks"}
C neyvia.language.check clean:neyvia.language.check(path:path) .blocking == 0
-- @record {"chapter":"overview","data":{"args":{"text":{"$input":"text"}},"expect":{"op":"eq","path":"blocking","value":0},"tool":"neyvia.language.check"},"key":"clean-text","section":"checks"}
C neyvia.language.check clean-text:neyvia.language.check(text:text) .blocking == 0
-- @record {"chapter":"overview","data":{"goal":"A report or UI file passes every block check of the no-slop skill","inputs":{"$cl_type":"t2"},"steps":[{"action":"language.check","args":{"path":{"$input":"path"}},"check":"clean","save":"result"}]},"key":"check-file","section":"procedures"}
P check-file(path:str):result=neyvia.language.check(path:path) C clean -- A report or UI file passes every block check of the no-slop skill
V P check-file -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"A summary, label or message passes every block check before it is sent","inputs":{"$cl_type":"t4"},"steps":[{"action":"language.check","args":{"text":{"$input":"text"}},"check":"clean-text","save":"result"}]},"key":"check-text","section":"procedures"}
P check-text(text:str):result=neyvia.language.check(text:text) C clean-text -- A summary, label or message passes every block check before it is sent
V P check-text -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"constraints":"Removal test: if cutting the sentence loses no fact, number, step or decision, cut it. Openers that restate the task and closers that restate the body or offer help are cuts.","options":["keep","cut"],"question":"Does each flagged sentence carry a fact, a number, a step or a decision the reader needs?"},"key":"cut","section":"judge"}
J cut keep|cut:"Does each flagged sentence carry a fact, a number, a step or a decision the reader needs?" -- Removal test: if cutting the sentence loses no fact, number, step or decision, cut it. Openers that restate the task and closers that restate the body or offer help are cuts.
V J cut -> human:operator why:"explicit choice required"
-- @record {"chapter":"overview","data":{"constraints":"give = write the measured number with its unit next to the claim (37 ms, 4 of 6, $0.02); drop = delete the size word. Never invent a number.","options":["give","drop"],"question":"For each size or speed word: is the measured number known?"},"key":"number","section":"judge"}
J number give|drop:"For each size or speed word: is the measured number known?" -- give = write the measured number with its unit next to the claim (37 ms, 4 of 6, $0.02); drop = delete the size word. Never invent a number.
V J number -> human:operator why:"explicit choice required"
-- @record {"chapter":"overview","data":{"failure":"An em dash, en dash or spaced hyphen joins two thoughts or decorates a heading","recovery":"Full stop for two thoughts, colon for a result or list, brackets for an aside; a tight en dash stays only in number or day ranges"},"key":"0","section":"pitfalls"}
X An em dash, en dash or spaced hyphen joins two thoughts or decorates a heading -> Full stop for two thoughts, colon for a result or list, brackets for an aside; a tight en dash stays only in number or day ranges
-- @record {"chapter":"overview","data":{"failure":"Hype or filler words (seamless, powerful, in order to, it's worth noting, breathing room) stand where a fact belongs","recovery":"Delete the phrase; name the effect and its size"},"key":"1","section":"pitfalls"}
X Hype or filler words (seamless, powerful, in order to, it's worth noting, breathing room) stand where a fact belongs -> Delete the phrase; name the effect and its size
-- @record {"chapter":"overview","data":{"failure":"A UI label is chatty or soothing (Your plan eyebrow, comfortably, just, simply, let's)","recovery":"A label is the noun, the verb or the state: Plan limits, Slow down, 62% used"},"key":"2","section":"pitfalls"}
X A UI label is chatty or soothing (Your plan eyebrow, comfortably, just, simply, let's) -> A label is the noun, the verb or the state: Plan limits, Slow down, 62% used
-- @record {"chapter":"overview","data":{"failure":"A report opens with Here is or closes with Let me know / In summary","recovery":"Start with the answer; stop when it is said"},"key":"3","section":"pitfalls"}
X A report opens with Here is or closes with Let me know / In summary -> Start with the answer; stop when it is said
-- @record {"chapter":"overview","data":{"failure":"much faster, a lot cheaper, several, significantly with no number in the sentence","recovery":"Give the measured number or delete the word"},"key":"4","section":"pitfalls"}
X much faster, a lot cheaper, several, significantly with no number in the sentence -> Give the measured number or delete the word
-- @record {"chapter":"overview","data":{"failure":"done() is refused with X language lines","recovery":"Rewrite exactly the quoted lines, run language.check(path=...) on the file, then done() again"},"key":"5","section":"pitfalls"}
X done() is refused with X language lines -> Rewrite exactly the quoted lines, run language.check(path=...) on the file, then done() again
-- @record {"chapter":"overview","data":"Tone that is clean by these checks but cold or rude needs a reader; word lists are English, dash and number rules apply to every language.","key":"0","section":"frontier"}
F Tone that is clean by these checks but cold or rude needs a reader; word lists are English, dash and number rules apply to every language.
-- @record {"chapter":"overview","data":"The host gate checks prose and UI files written during the task (.md .txt .html .jsx .tsx) and the done() summary; code comments and quoted sources are not checked.","key":"1","section":"frontier"}
F The host gate checks prose and UI files written during the task (.md .txt .html .jsx .tsx) and the done() summary; code comments and quoted sources are not checked.
-- @record {"chapter":"overview","data":"Plain short sentences, 30 words or fewer; UI lines 14 words or fewer.","key":"0","section":"guidance"}
M language "Plain short sentences, 30 words or fewer; UI lines 14 words or fewer." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"No em dash or en dash as punctuation, in headings too: 'Weekend plan: final note', not 'Weekend plan — final note'.","key":"1","section":"guidance"}
M language "No em dash or en dash as punctuation, in headings too: 'Weekend plan: final note', not 'Weekend plan — final note'." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"No hype (seamless, powerful, cutting-edge, leverage, unlock, elevate, delve, robust as praise) and no filler (in order to, it's worth noting, basically, essentially, at the end of the day).","key":"2","section":"guidance"}
M language "No hype (seamless, powerful, cutting-edge, leverage, unlock, elevate, delve, robust as praise) and no filler (in order to, it's worth noting, basically, essentially, at the end of the day)." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"UI labels name the thing, the action or the state; no eyebrow that repeats the title, no soothing words (comfortably, gently, breathing room, all set, just, simply).","key":"3","section":"guidance"}
M language "UI labels name the thing, the action or the state; no eyebrow that repeats the title, no soothing words (comfortably, gently, breathing room, all set, just, simply)." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Numbers over adjectives: 7x cheaper ($0.15 to $0.02), not much cheaper; 4 of 6 tests, not most tests. With no number, drop the adjective.","key":"4","section":"guidance"}
M language "Numbers over adjectives: 7x cheaper ($0.15 to $0.02), not much cheaper; 4 of 6 tests, not most tests. With no number, drop the adjective." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"One hedge per sentence at most; say what is known and what is not.","key":"5","section":"guidance"}
M language "One hedge per sentence at most; say what is known and what is not." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Reports start with the result and stop when it is said: no 'Here is', 'Let me know', 'In summary', 'I hope this helps'.","key":"6","section":"guidance"}
M language "Reports start with the result and stop when it is said: no 'Here is', 'Let me know', 'In summary', 'I hope this helps'." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Before done(), run language.check on every report and UI file you wrote; the host refuses done() while a block check fails and names each line.","key":"7","section":"guidance"}
M language "Before done(), run language.check on every report and UI file you wrote; the host refuses done() while a block check fails and names each line." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"The full rule set with sources is the CL-Skill manuals/skills/no-slop.cl; its checks are the same code the host runs.","key":"8","section":"guidance"}
M language "The full rule set with sources is the CL-Skill manuals/skills/no-slop.cl; its checks are the same code the host runs." src:"authored manual" state:verified
