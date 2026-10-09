"""Local research search outcome through the production workspace-search path."""
from __future__ import annotations

import json
from pathlib import Path


def local_workspace_search(root):
    """Run a user-shaped local search and retain only its observed source rows."""
    from .research import search_workspace_detailed

    root = Path(root).resolve()
    workspace = root / "research-workspace"
    notes = workspace / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    expected = notes / "field-record.md"
    expected.write_text(
        "Field notes\nZoë's café research records the façade survey.\n",
        encoding="utf-8",
    )
    (notes / "unrelated.md").write_text("A different subject.\n", encoding="utf-8")

    query = "Zoë's café research"
    result = search_workspace_detailed(
        workspace, query, "**/*.md", max_results=10,
        case_sensitive=True, time_budget=5, engine="python",
    )
    rows = result["matches"]
    rows = [{**row, "path": row["path"].replace("\\", "/")} for row in rows]
    if not result["complete"] or result["timedOut"] or result["truncated"]:
        raise AssertionError("A bounded local search reported incomplete evidence")
    if len(rows) != 1 or (rows[0]["path"], rows[0]["line"]) != ("notes/field-record.md", 2):
        raise AssertionError(f"The local search did not return the exact matching source: {rows!r}")
    if query not in rows[0]["snippet"]:
        raise AssertionError("The local source citation lost the exact Unicode query")

    before = expected.read_bytes()
    try:
        search_workspace_detailed(
            workspace, query, "../**/*.md", max_results=10,
            case_sensitive=True, time_budget=5, engine="python",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("A search glob escaped the selected workspace")
    if expected.read_bytes() != before:
        raise AssertionError("A refused search changed the source record")

    return {
        "query": query,
        "matches": rows,
        "complete": result["complete"],
        "sourceBytesPreservedAfterRefusal": True,
        "boundary": "Actual local workspace search and file/line evidence; no durable research-record, public web, provider, or semantic-fact claim",
    }


def self_check(root):
    observed = local_workspace_search(root)
    return {"contracts": ["p22.research-workspace-search"], "ok": True, **observed}
