"""Small model-facing core; full catalogs remain behind discovery."""
from __future__ import annotations

from .cl.protocol import primer_context
INSTRUCTIONS = primer_context()

def core_tools(*, plugin=False, ask_user=False):
    def row(name, description, properties=None, required=None, read=True):
        return {"name": name.replace("neyvia.", "").replace(".", "_") if plugin else name,
                "description": description,
                "inputSchema": {"type":"object", "properties":properties or {}, "required":required or [], "additionalProperties":False},
                "annotations":{"readOnlyHint":read}}
    text = {"type":"string"}
    rows = [
        row("neyvia.cl", "Use CL 1.1 Python-style calls; prefer run procedures. Host fills stamps; done requires observer G. Existing approvals apply.",
            {"lines": text, "actionId": text}, ["lines"], False),
        row("neyvia.cl.describe", "Read CL signatures, checks and procedures progressively.",
            {"level":{"type":"integer","minimum":0,"maximum":2},"layer":text,"chapter":text,"name":text,"primer":{"type":"boolean"}}),
        row("neyvia.manual.index", "List manuals and chapter names."),
        row("neyvia.manual.load", "Read one manual chapter before discovering tools.",
            {"id":text,"chapter":text,"offset":{"type":"integer","minimum":0},"maxChars":{"type":"integer","minimum":512,"maximum":20000}}, ["id"]),
        row("neyvia.tools.search", "Find tools by name or purpose; schemas load on describe.",
            {"query":text,"limit":{"type":"integer","minimum":1,"maximum":20}}, ["query"]),
        row("neyvia.tools.describe", "Load one exact tool schema and its call target.", {"name":text}, ["name"]),
    ]
    from .neyvia_manuals import DEFINITIONS
    for name, description, properties, required in DEFINITIONS:
        if name in {"manual.observe", "manual.run", "manual.frontier", "manual.project"}:
            rows.insert(2, row("neyvia." + name, description, properties, required, name != "manual.frontier"))
    if plugin:
        rows += [row("neyvia.tools.call", "Call a discovered neyvia.* tool; existing approvals apply.",
                    {"tool":text,"arguments":{"type":"object"}}, ["tool","arguments"], False),
                 row("neyvia.state", "Observe current project, panes and app state.")]
    else:
        rows += [row("neyvia.native.call", "Call a native tool by exact ID. Reuse stable actionId for mutations.",
                    {"toolId":text,"arguments":{"type":"object"},"actionId":text}, ["toolId","arguments"], False),
                 row("neyvia.tools.invoke", "Call a described deferred managed gateway; original authority checks apply.",
                    {"tool":text,"arguments":{"type":"object"}}, ["tool","arguments"], False),
                 row("neyvia.access.context", "Observe this run's effective permissions and local capabilities."),
                 row("neyvia.actions.inspect", "Recover saved action receipts without replaying actions.", {"actionId":text,"after":text})]
        if ask_user:
            rows += [row("neyvia.ask_user", "Ask a necessary question, then stop for the real reply.",
                         {"question":text,"options":{"type":"array","items":text,"maxItems":3},"context":text}, ["question"], False)]
    # Archival manuals remain callable and discoverable; startup exposes only
    # the CL surface and the established deferred gateways, never layer schemas.
    return [item for item in rows if not item["name"].startswith("manual_" if plugin else "neyvia.manual.")]

def deferred_tools():
    """Wrapper-owned tools that are absent from the managed server's catalog."""
    return [
        {"name":"neyvia.operations.inspect","description":"Inspect retained verified-operation evidence without replay.",
         "inputSchema":{"type":"object","properties":{"operationId":{"type":"string"},"limit":{"type":"integer"}}},"annotations":{"readOnlyHint":True}},
        {"name":"neyvia.terminal.exec","description":"Execute a bounded local command through the original Native authority gate; reuse actionId.",
         "inputSchema":{"type":"object","properties":{"command":{"type":"string","minLength":1},"shell":{"type":"string","enum":["auto","powershell","python","bash","cmd"]},"cwd":{"type":"string"},"timeoutMs":{"type":"integer","minimum":1,"maximum":120000},"maxOutputChars":{"type":"integer","minimum":128,"maximum":50000},"actionId":{"type":"string","maxLength":160}},"required":["command","actionId"],"additionalProperties":False},"annotations":{"readOnlyHint":False}},
    ]
