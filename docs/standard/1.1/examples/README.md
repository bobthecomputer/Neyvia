# CL 1.1 examples

The six layers and real runs are the same as in 1.0 (`../../examples/`, whose `today/` payloads are reused as the baseline). Each `.cl` file has these sections:

| Section | What it is | Sent to the model |
|---|---|---|
| `L0` | the always-loaded index line | yes |
| `L1` | what `help("layer")` or first touch loads: procedures with goals, choices, actions, at most 3 pitfalls | yes |
| `runtime` | the real observation, the call the agent writes, and the host's result | yes |
| `host` | the compiled host contract: auto parameters, checks, procedure steps, and where impact comes from | no, and not counted |

`python docs/standard/1.1/examples/measure.py` counts o200k exactly (tiktoken).

| layer | today start | 1.1 start (primer 275 + L0 98 + L1) | today runtime | 1.1 runtime |
|---|---:|---:|---:|---:|
| notes | 1446 | 616 | 414 | 174 |
| files | 1230 | 579 | 2097 | 975 |
| window (T16) | 1615 | 564 | 1109 | 347 |
| web (T18) | 983 | 525 | 3973 | 212 |
| chart (T18) | 866 | 455 | 1122 | 168 |
| codex run | 340 | 471 | 572 | 293 |
| **total** | **6480** | **3210 (−50.5%)** | **9287** | **2169 (−77%)** |

These counts are a strict per-fresh-task comparison: today loads only the touched layer's manual, and 1.1 pays its full cold start every time. With the canonical cohort's arm (a), which preloads all manuals, the saving is about −92%.

Caveats:

- **Chart.** The default chart view shows the chart only. Its 14 text boxes, 4 objects and the layout stay behind `h1` (one `E more` line points to them). 1.0 rendered all of them.
- **Files.** The files runtime grew by 116 tokens over 1.0 (975 against 859) because 1.1 quotes every string.
- **Window.** The T16 runtime combines the real Luna run's inspect, set, Apply and verify into one `run` result. The underlying values are real; the single-call procedure is the 1.1 design, not something that was run.
