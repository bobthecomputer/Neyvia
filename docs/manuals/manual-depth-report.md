# Manual depth: verified content and small comparison

14 manuals / 26 chapters now carry tool-specific guards and effects, real goals and decisions, concrete recovery and explicit frontier. Generic inspect procedures and duplicated reference chapters were removed. JSON remains the editable source; build_grounded_manuals.py validates and renders instead of recreating template content.

Each manual was committed separately on track/manual-depth. Edits are confined to manuals/, docs/manuals/, config/neyvia_manuals.json and scripts/. No src edits, push, merge, live service, protected tree or Tailscale access. The disposable backend used 47970 with its own --root and is stopped. No installs/downloads.

## Evidence

- neyvia.manual.validate: all 14; authored-content audit and generated-view check pass.
- Four real executions cover three apps: Notes capture-tagged-idea; Files tidy-with-undo plus undo-last-tidy; PDF find-and-highlight. Explicit judge resumes and fresh checks passed.
- Stale note writes, existing destination collisions and missing PDF phrases were refused without changing protected fixture bytes.
- 21 gateway contracts pass: typed references, schema drift, failed verifier, scope/read-only denial, non-replayed judge resume, quarantined patches and authorized CAS readback.
- Dictation Markdown is still absent on night/neyvia, so conditional conversion was not applicable.

## Plan 08 comparison

One fixed task per app; matching tool schemas and same-shaped fixtures. Official Claude CLI at low effort; no built-in tools or fallback. Haiku receives only its relevant chapter; Opus receives no manual. Latest small runs use final chapter hashes; earlier small results are retained, and unchanged large baselines are reused.

| Task | Haiku with final manual: success / tokens | Opus without manual: success / tokens |
|---|---:|---:|
| notes | pass / 22,660 | pass / 12,293 |
| files | pass / 38,055 | pass / 31,004 |
| pdf | pass / 24,506 | pass / 9,290 |

Models: claude-haiku-4-5-20251001 and claude-opus-5-5.

Totals: Haiku 3/3, 85,221 tokens; Opus 3/3, 52,587 tokens. Tokens are cumulative provider-reported input + cache creation + cache reads + output, including repeated context. No efficiency win is established by this three-task sample.

The original Files scorer incorrectly compared Windows CRLF fixture bytes to an LF-only literal. Initial results were corrected against the full pre-move stat preview and restored bytes, with successful move/undo receipts; final runs compare raw before/after buffers. Corrections and original attempts remain in the JSON receipt.

PDF evidence proves real text search and highlight event emission, with source bytes preserved. Viewer rendering was not claimed; verify-visible-highlight checks observed source and the selected highlight after a real user app reports it. Cross-PC is grounded and registered, but no real peer/network transfer was attempted in this protected task scope.

Full receipts: [manual-depth.evidence.json](manual-depth.evidence.json). Gateway checks: [manual_first_contracts.json](manual_first_contracts.json).
