# Scroll Study backend proof

`scripts/evidence/A3B.json` binds the implementation, original CLI usage receipts,
generated archive, imported notes, rejected attempts and running-player proofs.
The editable proof root remains `.agent_control/a3b/runtime`; its isolated
SQLite snapshot is `scripts/evidence/A3B-runs/raw/scroll-state.sqlite3`.

The backend uses the existing native tools, owner HTTP routes, desktop dispatch,
T14 cascade and grounded manual compilation. `scroll.import` supports UTF-8
Markdown/text and extends a draft without overwriting source history. A generator
worker owns each request identity once. The source-bound review gate blocks
pending or disputed answers; chapter approval preserves deliberate drops.

The prototype template in `apps/scroll-study` loads generated cards through
`load-pack.js`. `scroll.preview` copies that template and the reviewed generated
pack into its Mobile Studio project. Device-local IndexedDB owns progress, and
user controls and A1-style agent actions share the same reducer. The CL completion
goal requires a finished session and all G1–G11 checks, so empty feeds cannot pass.

## Reproduce in this worktree

Use system Python 3.13 and explicit owned ports 48591/48592. Disable coordinator,
watchdog and runtime updates; set `NEYVIA_UI_BACKEND_URL=http://127.0.0.1:48591`
and `NEYVIA_CONNECTED_SERVICE_PORT=48591`. Start:

```powershell
$python3='C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe'
& $python3 scripts/run_web_backend.py --host 127.0.0.1 --port 48591 --root .agent_control/a3b/runtime --skip-runtime-auto-update
# In a separate shell, give the replay a fresh durable job identity:
$requestId='a3b-reproduce-'+[guid]::NewGuid().ToString('N')
node scripts/prove_scroll_backend.mjs --resume --job $requestId --review scripts/evidence/A3B-runs/source-review.json
```

For a new provider run use a fresh request ID. Existing IDs replay their saved
job; unchanged model decisions hit T14's exact source/manual/procedure cache.
The recorded source-review file applies only to its inspected flagged question;
different disputes stop for concrete review. New model calls incur actual usage.
For a completed, already reviewed job use the tools directly to preview it;
the full proof script deliberately requires a fresh pending-review transition.

Run `node scripts/verify_scroll_pack.mjs` for archive/schema/cost failure cases,
`node apps/scroll-study/scripts/property.cjs` for 150 DAGs / 450 sessions and
worked-scaffold gates, and `node scripts/prove_scroll_boundaries.mjs` for owner
HTTP, import/review, restart and one-download QR boundaries.

Serve the generated phone project's `www` using `python -m http.server 48592
--bind 127.0.0.1 --directory <project>/www`. Then run `scripts/prove_scroll_player.py`
with `--url http://127.0.0.1:48592/ --project <project> --preview-url <explicit URL>`.
It uses production T18 headless Chromium because the Chrome plugin was unavailable.
It observes real controls/timers, source text, FSRS, reload, stale revisions,
completion and a disposable mutation of the actual planner. No pytest is used.

The generator manual's validated procedure can compile after three actual runs
using `node scripts/prove_scroll_manual.mjs`; the worker then executes that compiled
validator against current cards. `scripts/seal_A3B.py` snapshots and rehashes only
the task artifacts and emits A4 result specifications. Append a unique new result
through A4's efficiency-log CLI; never append raw stage events into its ledger.

## Boundaries

The receipt lists remaining PDF/OCR, physical-phone/native-platform, full-shell,
math/media player coverage and worker-crash recovery limits. Order/faded cards
derive from the reviewed worked example; independent model solving covers the
five standard question forms. Early misses/sparse packs may end when the hard
ordering constraints and new-concept budget leave no legal card.

The development cost includes every repair attempt. USD values are standard API
list-price equivalents of actual CLI usage, not an invoice. Study hours are based
on card seconds, not observed learner speed. Exact warm replay and local reviews
use zero provider tokens. There is no held-out learning or Paul acceptance claim.
The cumulative big-call rate, including prompt repairs, exceeds the 0.05 target;
the exact cached replay does not establish fresh-pack efficiency.
