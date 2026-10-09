# Agent submission receipt gate

Run this before an external agent's changes are considered for integration:

```powershell
python scripts/validate_agent_submission_receipt.py .agent_control/receipts/phase-1.json --root . --phase-policy .agent_control/receipt-phase-policy.json
```

The command is read-only. A non-zero exit means the submission is not accepted.

The receipt must use `neyvia.agent-submission-receipt.v1` and contain:

- `agent`, `phase`, `lane`, and a reachable `baseline.commit`.
- `changedFiles`, each with a relative path, change type, and before/after SHA-256. Deleted files use `changeType: "deleted"`, retain the baseline `beforeSha256`, and use `afterSha256: null`.
- `allowedFiles` and `forbiddenFiles`; an optional policy further constrains the phase.
- actual command exit codes and `passed`, `failed`, and `skipped` counts.
- hash-pinned proof files. A JSON proof's `sourceHashes` is checked at every nesting level against the accepted source hash.
- explicit `claims.live.claimed` and `claims.physicalDevice.claimed` values. A true claim requires a proof marked `live` or `physical-device`.
- a summary whose counts equal the arrays it describes.

The gate rejects traversal, missing source/proof files, current-file hash drift, baseline drift, stale nested proof hashes, contradictory command/summary counts, forbidden or out-of-phase paths, and unsupported live/device claims. It also requires `changedFiles` to exactly match the in-scope tracked and untracked Git delta from `baseline.commit`, so a modified or deleted source file cannot be omitted. Secret-like receipt keys or credential values are rejected before the validator emits diagnostics, and are never echoed in its result. It deliberately does not turn a receipt into public-live proof: that still requires separate fresh deployment and browser/device verification.
