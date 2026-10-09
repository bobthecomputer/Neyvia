# Desktop Performance Report (M1)

This report tracks the M1 overlay budgets from day one instrumentation.

## Metrics captured

- Cold start time (`cold_start_ms`)
- Hold-hotkey to overlay-open latency (`last_hotkey_latency_ms` and rolling average)
- Idle RAM snapshot (`idle_ram_mb`)

## How to sample

1. Start the app: `npm run tauri:dev`
2. Trigger overlay open/close with the configured hold key (`Ctrl+Space` or fallback `Ctrl+Shift+Space`).
3. Open tray menu -> **Performance snapshot** or click **Perf** in the overlay.
4. Read current values in the overlay panel and in app logs.

## Latest local sample

Not captured in this commit (code instrumentation only).

## Budget targets

- Hotkey-to-overlay perceived latency: `< 80ms`
- Idle RAM: `< 80MB` (stretch `< 50MB`)
- Idle CPU: near-zero

## Neyvia release-gate runtime evidence

The release budget in `config/neyvia_performance_budgets.json` is separate from
the M1 overlay snapshot above. Record evidence for an already-built `web/dist`
with:

```powershell
python scripts/record_runtime_performance.py `
  --build-dir web/dist `
  --ready-url http://127.0.0.1:4173/health `
  --app-url http://127.0.0.1:4173/ `
  --bootstrap-url http://127.0.0.1:4173/api/summary/bootstrap `
  --samples 5 `
  -- python -m your_runtime_entrypoint
```

The runtime command must stay in the foreground, become ready at the configured
URL, and support a clean restart on the same address for every sample. The
recorder does not retain the command, URLs, local paths, response bodies, or
process output.

Recorded measurements:

- startup p95 is spawn-to-readiness time over the configured bounded runs;
- bootstrap payload is the largest decoded response-body byte count;
- initial network bytes are the largest HTML plus same-origin initial
  script/stylesheet/preload response-body total;
- on Windows, memory is the summed working set of the active job process tree
  and CPU is job-wide accounting; Linux currently records root-process p95
  samples through procfs;
- battery is `null` and explicitly `unproven` unless bounded raw samples and one
  enumerated source ID are supplied. Repeat
  `--battery-drain-percent-per-hour VALUE` for every raw sample and choose
  `external-power-meter`, `os-battery-telemetry`, or
  `windows-energy-report`.

Response-body bytes are not wire-level compressed transfer bytes. Linux
root-process metrics do not claim child-process totals. These limitations are
included in the metric source instead of being hidden.

All three HTTP(S) endpoints are loopback-only and must share the exact scheme,
host, and port. Redirects must remain on that same origin. There is no
non-loopback override, and system proxy settings are not used.
Readiness must be unavailable before each spawn and unavailable again after the
recorder terminates the complete launched process tree. Otherwise startup
evidence remains unproven.

On Windows the runtime starts suspended, is assigned through its retained
process handle to a kill-on-close job, and is resumed only after assignment.
Cleanup never sends a tree-kill command to a reusable PID. On Linux the runtime
uses its own process session. Uncertain tree cleanup fails the capture.
Windows endpoint checks use the TCP listener table, so normal `TIME_WAIT`
connections are not mistaken for a live conflicting runtime. After teardown,
the recorder allows a bounded two-second listener-table settle window for
terminated child servers; the pre-spawn conflict check remains immediate.

One monotonic wall-clock deadline covers all samples, readiness polling,
post-ready sampling, HTTP requests, redirects, and teardown checks. Individual
request timeouts are clamped to the time remaining. Bounded raw samples are
retained so the verifier can recompute every claimed p95 or maximum.

The recorder returns `0` only when every metric, including battery, was
measured. A useful but incomplete capture is still written and returns `1`.
Invalid configuration, missing build output, or a capture failure returns `2`.

Verify the evidence against the exact build:

```powershell
python scripts/verify_performance_budget.py `
  --build-dir web/dist `
  --runtime-evidence .agent_control/performance/runtime-latest.json `
  --output .agent_control/performance/latest-budget-report.json
```

The verifier rejects stale or future-dated captures, excessive capture duration
or sample counts, missing per-metric provenance, and a mismatched build
fingerprint or budget-configuration fingerprint. It also rejects negative or
non-finite values, deleted required budgets, aggregate/raw-sample mismatches,
missing manifest assets, unsupported source IDs, and changed evidence contents.
A numeric value paired with `unproven` provenance is not accepted.

Every visited Vite manifest record must declare a non-empty resolvable `file`.
Its `imports` and `css` values, when present, must be arrays containing only
non-empty strings, and every import key and asset must resolve. HTML fallback
uses the standard-library HTML parser, including unquoted attributes, and
rejects unresolved initial script, stylesheet, preload, image, or linked asset
references. Invalid build or runtime inputs are represented by stable error
codes rather than copied exception text.

The SHA-256 evidence digest is a local tamper-evidence checksum over canonical
JSON. It detects accidental or post-capture edits when the verifier recomputes
it. It is not a signature, remote attestation, trusted timestamp, or proof that
an authorized recorder produced the file; anyone who can rewrite the evidence
can also recompute the checksum.

Accordingly, a successful local comparison is reported as
`localBudgetStatus: pass`, while the ordinary `status` remains `unproven` and
`promotionEligible` remains `false`. Promotion requires a separately
provisioned verifier signature or attestation path, which this recorder does
not implement or claim.

Reports use opaque `pathRef` values rather than emitting local build or evidence
paths. Bounded diagnostics redact Windows drive paths, UNC paths, Synology
`/volume1/...` paths, slash-style drive paths, `/mnt`, `/workspace`, `/opt`,
and `/srv` paths, bearer credentials, and quoted or unquoted token assignments.
