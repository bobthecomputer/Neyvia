# Manual recovery benchmark

Six fixed Notes/Files tasks, two isolated repeats, actual `claude-haiku-4-5-20251001` at low effort through the installed Claude CLI. Same tasks, raw tool schemas, authority and scratch backend in both arms. Only the environment manual differs. Scoring inspects file/note state and tool arguments, not final prose.

| Arm | Full protocol success | Semantic state success | Reported model tokens |
|---|---:|---:|---:|
| Haiku without manual | 1/12 | 9/12 | 197,490 |
| Haiku initial compact manual | 1/12 | 11/12 | 355,520 |
| Haiku typed manual | 12/12 | 12/12 | 294,137 |
| Deterministic `neyvia.manual.run` | 12/12 | 12/12 | 0 |

Tasks: reviewed staging, pending-review stop, stale-write reconciliation, collision hold, duplicate capture, and restoring a selected draft after another Files operation. Pending and collision paths retain originals; stale capture keeps a real concurrent editor's paragraph; scoped restore preserves the later unrelated move. Every new receipt requires guarded append and pin. Full protocol scoring checks these environment conventions; semantic scoring separates state preservation from exact method compliance.

The initial compact manual could lose: it produced 1/12 protocol successes. Its renderer hid typed step arguments and workflow guidance, so Haiku used guarded replacement instead of append and one run moved a pending draft. The renderer now emits typed STEPS and GUIDANCE. Two fresh with-manual repeats passed 12/12; unchanged baseline receipts are retained, not retried. This is a development benchmark repaired on these cases, not a held-out generalization result. The manual supplies environment knowledge; no model-weight improvement is claimed.

Provider cumulative input + cache creation + cache read + output are counted, including repeated context. The corrected manual consumed 294,137 tokens versus 197,490 without it (49% more); success improved, token cost did not. Initial failed manual runs cost another 355,520 tokens; all six model runs total 847,147. Zero-token procedures used predeclared explicit judge choices; human/model decision cost is excluded, so zero is execution cost, not autonomous judgement cost.

One scoring bug initially threw on a file the baseline moved. It was repaired to score absent files false; original model logs were rescored without rerunning that model. Traces and raw receipt paths are in `scripts/evidence/manual-recovery.json`; both failed initial manual runs remain in that final evidence; the original snapshot is also preserved locally at `.agent_control/proofs/r-manual-ambient-20261002/manual-recovery-v1.json`. The receipt records the preserved local scratch location after relocation. All source manuals validate; an existing design-manual `workspace.read` schema was refreshed to include live line/hash fields. Rendered UI is outside this backend benchmark.
