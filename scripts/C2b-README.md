# C2b recorded boundary

The resident g3-c2 CPU family now answers a bounded factual browser profile through
the actual owner-authenticated Neyvia browser route. Styled same-origin iframe
effects work in Obscura and the real shared WebView2 browser runtime. This is a
partial C2/C3 result: action selection and paired external comparisons remain open.

| Run | Recorded outcome |
| --- | --- |
| Frozen CPU decision replay | 40 fitting decisions; threshold 0.6903756260871887 frozen before 426 held-out decisions |
| Accepted held-out decisions | 94/94 correct before postcheck; 22.07% overall coverage; 94/104 supported page fields accepted |
| Warm latency | HTTP p50/p95 5.70/27.53 ms; model 2.46/4.89 ms |
| Determinism | 466/466 cases have identical distributions/answers across three actual uncached calls |
| Action selection | 283/312 raw correct on fresh controls; no action grants accepted or activated |
| Native/iframe journey | 13 actual checks passed; final native startup 1346 ms; lead inspected screenshot |
| Live browser decision route | 9 checks passed, including wrong candidate postcheck, unsupported instruction and action refusal |
| Public task subset | 20/21 extracted-field checks passed; two acquisition calls/task; p50/p95 2557/2881 ms |
| Claude-in-Chrome | Lead CLI probe failed expired authentication; no paired task score |
| OpenAI Codex exec browsing | Tool was exposed but trusted Node process failed twice; no paired task score |

`evidence/C2b.json` is the independently checked receipt index. The canonical
research ledger has five appended C2b rows. No source was published or promoted.

## Scope and evaluation protocol

The exact public questions come from WebVoyager's Cambridge Dictionary subset.
`evidence/C2-tasks.json` preserves the questions, entry URLs, checks and adaptation
for every arm. The run supplies each entry URL, opens it through Neyvia and obtains
an actual observation; `c2b_public_answers.cjs` extracts the requested fields.
This proves live acquisition and field checks, with zero paid provider calls.
Local compute cost is unmeasured. Meaning count is explicitly unsupported rather
than inferred from duplicated dictionary sections. Cryptocurrency example-context
semantics still need independent grading. This is not autonomous WebVoyager success.

The first mixed corpus contained 206 ambiguous normalized control targets. Its
attempt receipts remain available, but its statistics do not authorize actions.
The fit-only action representation probe also failed. The final factual scope was
declared before fresh held-out inference, and the threshold was frozen after 40
earlier page-field decisions. The fresh panel contains 26 distinct document pages,
312 independently checked unique control choices and 104 page-field questions.
Ten older Notepad UIA facts are clearly marked historical replay; no new physical
computer-use journey or general UIA accuracy is claimed. Observations within pages
are correlated, and population precision is not guaranteed by the observed result.

The deployed `public_observed_fields@1` profile supports only title, hostname, URL
and document loading state with exact declared prompts on finitely evaluated hosts.
It binds model/client identity, candidate sequence and confidence, then independently
checks the selected description against the fresh observed field. It returns an
advisory decision and never an action grant. The action gate remains disabled.
Large CPU models cannot enter the browser hot path; frozen GPU identities are
eligible for admission, but no GPU run or larger-model improvement was measured.

Native startup repair is in the isolated probe's event-loop setup. The probe uses
the production browser runtime directly; this does not prove full production shell
startup. The native capture shows a styled iframe with its actual saved value;
false postconditions and authentication stop paths pass in both engines. Native
startup and effect latencies still exceed earlier headless microbenchmark targets.
Cross-origin grants, canvas/closed-shadow perception and complex semantic CSS
cascades remain outside this evidence.

## Reproduce within an isolated checkout

The commands below produce receipts: preserve the committed evidence before a new
acquisition. Existing local model and Obscura artifacts are used; there are no
downloads or dependency installs. Do not redirect this workflow to a public runtime.

```powershell
$pythonC2b = 'C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe'
& $pythonC2b scripts/c2b_laya_service.py --port 48724 --project C:/Users/user/Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement
# In a separate shell, for retained frozen observations:
& $pythonC2b scripts/c2b_laya_evaluate.py --port 48724 --cases scripts/evidence/C2b-decisions-advisory.jsonl --output scripts/evidence/C2b-laya-advisory.json --calibration scripts/evidence/C2b-laya-calibration.json --repeats 3
node scripts/c2b_live_loop.cjs
& $pythonC2b scripts/seal_c2b.py
```

For fresh public acquisition, `node scripts/c2b_public_benchmark.cjs` uses explicit
48721/48722/48723. Fresh control capture is `node scripts/c2b_action_capture.cjs`,
then `c2b_corpus_align.py --cases scripts/evidence/C2b-action-decisions.jsonl` and
`c2b_laya_advisory_corpus.py`. Preserve separate fitting and held-out page groups.

For native proof use the existing offline Rust toolchain and an owned build target
outside the dependency junction. The final executable is recorded under
`D:/CodexScratch/nx-c2-browser-C2b-native/debug/browser-proof.exe`. Set
`C2B_NATIVE_BACKEND_PORT=48725`, `C2B_NATIVE_FIXTURE_PORT=48726`,
`C2B_NATIVE_ENGINE_PORT=48727`, and `C2B_NATIVE_EXE` to that executable before running
`node scripts/c2b_native_benchmark.cjs`. The earlier task-owned native build was
recoverably moved to D: after C: filled; `C2b-local-preservation.json` binds it to
the retained original binary hash. Both build folders remain recoverable.

Paul must restore Claude authentication and a working Codex browser runtime to
complete the matched comparison. The CLI probe `c2b_comparator_probe.cjs` records
actual availability first. No provider retrieval fallback is counted as browsing.
All task-owned proof services have stopped; the CPU cleanup receipt records PID
76940 and the absence of its listener. Unowned occupied ports are left alone.
