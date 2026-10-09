# Experience note contract

Use an existing compatible project schema if available. This is a content contract, not a requirement to add a database, serialization format, or service.

A useful note carries:

- Identity and revision; owning task/workspace and allowed sharing scope.
- Situation or failure signature; relevant tool, application, runtime version, and state.
- Observed problem or useful pattern; diagnosis distinguished from hypothesis.
- Mechanism changed or successful operation; concise instructions for applicable reuse.
- Evidence references with observed time and artifact identity/hash where available.
- Preconditions, invalidation conditions, uncertainties, and required fresh checks.
- Status such as proposed, validated within a stated scope, superseded, or retired.
- Authority required for an action; the note never supplies that authority.

Keep the core lesson to a short paragraph when possible. A note can index a larger proof capsule without copying its logs into every prompt. Retain direct user constraints in working state even when optional lesson detail is omitted.

Example: a page refresh changed transient text-node IDs while the relevant semantic control stayed unchanged. A useful note identifies the affected observer/version, the evidence for instability, the normalization that was actually verified, and the changed-state check required before acting. It must not recommend ignoring all document changes or retrying a prior click blindly.

Two conflicting notes should remain visible with their scopes and dates until current evidence resolves them. Do not quietly promote the newest note to truth. Missing evidence or an inaccessible retrieval path lowers the usable claim; it is not permission to invent the omitted details.

For product integration, prove the full path separately: finish work, preserve an authorized note, start or resume a different agent, retrieve the applicable note, demonstrate the effect on its action, then invalidate the note with a changed environment. If that path was not run, report storage/retrieval checks only.
