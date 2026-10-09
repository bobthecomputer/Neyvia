L app v1 -- Scroll Study
P app.scroll.study() G: app.state().ended and app.state().done >= app.state().goal and app.checks().G1 and app.checks().G2 and app.checks().G3 and app.checks().G4 and app.checks().G5 and app.checks().G6 and app.checks().G7 and app.checks().G8 and app.checks().G9 and app.checks().G10 and app.checks().G11
G complete: app.state().ended and app.state().done >= app.state().goal and app.checks().G1 and app.checks().G2 and app.checks().G3 and app.checks().G4 and app.checks().G5 and app.checks().G6 and app.checks().G7 and app.checks().G8 and app.checks().G9 and app.checks().G10 and app.checks().G11
A app.state() -> state[index seen done goal run streakDays ended card ledger upcoming]
A app.act(name: "next"|"prev"|"seeNow"|"knowThis"|"reveal"|"swipe"|"answer"|"more"|"finish"|"restart", arguments?: dict) ~
A app.checks() -> checks[G1 G2 G3 G4 G5 G6 G7 G8 G9 G10 G11]
A web.text() -> text
X fast-flick -> exposure stays unseen; wait at least the teaching threshold or finish all worked steps
X instant-reveal -> reveal under one second cannot receive Easy
X unknown-prerequisite -> show a prerequisite teaching card before any graded question
X no-legal-card -> end honestly; do not invent exposure to fill a block
X failed-goal -> inspect actual card, ledger and rendered feedback; repair before done
X stale-write -> observe current state and retry with a fresh host stamp
F G6 may be impossible in a sparse pack when alternate-card lag, subject, adjacency and format quotas conflict; retain that conditional frontier explicitly
F mastery requires correct recall in three separate sessions on at least two different days; self-claim does not constitute mastery
F local browser proof does not establish installed Android or iOS behavior
