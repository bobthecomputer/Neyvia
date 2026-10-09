# Handoff Packet Schema

When context usage crosses rollover thresholds, the engine writes `handoff_packet.json`.

## Core fields

- `schema_version`: packet schema version.
- `generated_at`: UTC timestamp.
- `reason`: why rollover happened.
- `session_id` and `parent_session_id`: lineage identifiers.
- `objective`: original objective.
- `prompt_stack`: constitution, project profile, persona, task brief, step policy.
- `progress`: completed and remaining steps, context usage.
- `changed_files`, `decisions`, `risks`, `acceptance_checks`.
- `verification`: command results and return codes.
- `next_actions` and `resume_instructions`.

Related state data in `state.json` also includes:

- `session_lineage`: all session IDs involved in this run chain.
- `doc_evidence`: per-doc readability and excerpt records.

## Example

```json
{
  "schema_version": "1.0.0",
  "reason": "context_rollover",
  "objective": "Implement feature X",
  "progress": {
    "completed_steps": ["Review docs"],
    "remaining_steps": ["Implement vertical slice"],
    "usage_ratio": 0.86,
    "context_status": "rollover"
  },
  "next_actions": ["Continue remaining plan steps"]
}
```
