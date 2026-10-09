"""Migrate only legacy app-authored workspace descriptions, never user prompts."""

WORKSPACE_DESCRIPTION = "Settings for agent actions and approvals in the selected local workspace."
LEGACY_DESCRIPTIONS = {
    WORKSPACE_DESCRIPTION + " These settings do not describe an organization or establish ownership of connected hardware.",
    "Defines what agents can do, when approval is required, and what scope the permissions apply to across the organization.",
}


def normalize_workspace_context(context: str) -> str:
    lines = context.splitlines(keepends=True)
    for index, line in enumerate(lines):
        value = line.rstrip("\r\n")
        if value in {"Workflow intent: " + text for text in LEGACY_DESCRIPTIONS}:
            lines[index] = "Workflow intent: " + WORKSPACE_DESCRIPTION + line[len(value):]
    return "".join(lines)


def normalize_replay_context(items):
    """Repair old generated envelopes in memory; leave the durable archive intact."""
    if not isinstance(items, list):
        return items
    result = []
    for item in items:
        if isinstance(item, dict) and item.get("role") == "user" and isinstance(item.get("content"), str):
            request, marker, context = item["content"].rpartition("\n\nCurrent workspace context:\n")
            if marker and context.startswith("Workspace:") and "\nWorkspace path:" in context:
                # Quoted history is not generated workspace metadata.
                metadata, history_marker, history = context.partition("\n\nRecent conversation:")
                cleaned = normalize_workspace_context(metadata)
                if cleaned != metadata:
                    item = {**item, "content": request + marker + cleaned + history_marker + history}
        result.append(item)
    return result
