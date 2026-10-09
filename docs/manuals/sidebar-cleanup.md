# Sidebar cleanup

## STATE OBSERVERS
- `neyvia.sidebar.policy()` reads workspace-local retention settings (automatic archiving defaults off) and `lastArchive`: what the last tidy archived, when, and whether it was automatic.
- `neyvia.sidebar.tidy(dryRun=true)` observes current session status, worktree changes and local process jobs before reporting candidates and protected chats.

## TYPED ACTIONS
- `neyvia.session.archive(id, archived=true)` archives only after a fresh safety check; `archived=false` restores the chat.
- `neyvia.sidebar.policy(policy)` saves retention days and `autoArchive`; the same switch is in Settings (`neyvia.pane.show(kind="settings")`) and under Cleanup rules in the sidebar.
- `neyvia.sidebar.tidy(confirmed=true)` applies a summary the person has confirmed; it rechecks every chat it archives.
- `neyvia.sidebar.tidy(undoLast=true)` restores every chat the last tidy archived (manual or automatic) in one call; it reports `restored`.

## EXECUTABLE CHECKS
- `neyvia.sidebar.tidy(dryRun=true)` returns `protected` reasons for dirty worktrees, running jobs, pinned chats, needs-you states and unavailable safety observations.
- `neyvia.sidebar.policy()` returns the saved policy after changing Cleanup rules.

## PROCEDURES
- Call `neyvia.sidebar.tidy(dryRun=true)` to preview its summary, show the candidate count and protected reasons, then call `neyvia.sidebar.tidy(confirmed=true)` after confirmation. `neyvia.pane.show(kind="settings", target="tidy")` opens the same preview for the person.
- Enabling `autoArchive` in `neyvia.sidebar.policy(policy)` authorizes the existing backend maintenance timer to apply the policy every minute, including while the UI is closed; each automatic tidy that archives something shows a notice, and `neyvia.sidebar.tidy(undoLast=true)` puts it back.
- Restore a fallen leaf with `neyvia.session.archive(id, archived=false)`; archiving never deletes provider data or workspace files.

## JUDGEMENT POINTS
- `neyvia.sidebar.tidy` uses seven inactive days for No folder and thirty for recognized projects by default; change these through `neyvia.sidebar.policy` when needed.
- `neyvia.session.move(id, project)` explicitly overrides automatic grouping; otherwise unknown folders belong to No folder until real project metadata is observed.

## PITFALLS
- `neyvia.session.archive` may refuse a chat after a tidy preview because new work or a job started; keep it visible and report the reason.
- `neyvia.sidebar.tidy` treats unavailable folders, missing Git/process observations and fresh failures as protected rather than guessing they are safe.

## FRONTIER
- `neyvia.sidebar.tidy` observes broker runs and operating-system process working folders; jobs that neither source can see remain outside its observation boundary.
- `neyvia.sidebar.policy` is workspace-local; it does not change global configuration or permanently delete anything.
