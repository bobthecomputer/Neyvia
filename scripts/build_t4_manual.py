"""Generate the T4 executable manual from its live native tool schemas."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.neyvia_manuals import render, validate


def build():
    with tempfile.TemporaryDirectory(prefix="t4-manual-") as root:
        registry = NativeToolRegistry(root)
        names = ["workspace.read", "workspace.search", "workspace.patch", "web.fetch", "web.read", "web.passages", "web.cite"]
        schemas = {name: registry.describe(name)["inputSchema"] for name in names}
        digest = {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"}
        handle = schemas["web.read"]["properties"]["document"]
        obj = lambda props: {"type": "object", "properties": props, "required": list(props)}
        returns = {"workspace.read": obj({"sha256": digest, "content": {"type": "string"}}),
                   "workspace.patch": {"type": "object"},
                   "web.fetch": obj({"document": handle}), "web.read": obj({"document": handle}),
                   "web.passages": {"type": "object"}, "web.cite": {"type": "object"},
                   "workspace.search": {"type": "object"}}
        effect = {"workspace.read": "Read bounded character or inclusive line ranges with the original-byte hash; optional expectedSha256 refuses mixed snapshots",
                  "workspace.search": "Search confined eligible text with ripgrep, or reported Python fallback; incomplete results stay marked incomplete",
                  "workspace.patch": "Apply all ranges against one hash-checked snapshot; serialize cooperative writers, atomically persist and verify bytes",
                  "web.fetch": "Fetch at most 2 MiB, cache an immutable handle; reuse recent URL observations unless refresh=true",
                  "web.read": "Continue cached text by character offset without a network call",
                  "web.passages": "Search literal text, returning bounded quote ranges, source URLs, hashes and continuation",
                  "web.cite": "Return an exact observed source quote; expectedText mismatch fails"}
        actions = {name: {"tool": name, "schema": name, "returns": returns[name],
                          "pre": "Workspace write grant and stable actionId through the model gateway" if name == "workspace.patch" else "Selected workspace; use returned hashes/handles for later observations",
                          "effect": effect[name], "reversible": name != "workspace.patch"} for name in names}
        empty = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
        file_inputs = {"type": "object", "additionalProperties": False, "properties": {
            "path": {"type": "string", "minLength": 1}, "edits": copy.deepcopy(schemas["workspace.patch"]["properties"]["edits"]),
            "expectedContent": {"type": "string", "maxLength": 100000}}, "required": ["path", "edits", "expectedContent"]}
        web_inputs = {"type": "object", "additionalProperties": False, "properties": {
            "url": {"type": "string"}, "query": schemas["web.passages"]["properties"]["query"]}, "required": ["url", "query"]}
        chapter = {"title": "Hash-bound edits and cited cached research", "state": {
            "file": {"tool": "workspace.read", "args": {"path": {"$input": "path"}},
                     "inputs": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, "shape": returns["workspace.read"]},
            "document": {"tool": "web.read", "args": {"document": {"$input": "document"}, "maxChars": 512},
                         "inputs": {"type": "object", "properties": {"document": handle}, "required": ["document"]}, "shape": returns["web.read"]}},
            "actions": actions, "checks": {
                "persisted-text": {"tool": "workspace.read", "args": {"path": {"$input": "path"}, "maxChars": 100000},
                                   "expect": {"path": "", "op": "schema", "schema": {
                                       "type": "object", "required": ["content", "truncated"],
                                       "properties": {"content": {"const": {"$input": "expectedContent"}},
                                                      "truncated": {"const": False}}}}},
                "cached-document": {"tool": "web.read", "args": {"document": {"$result": "fetched.document"}, "maxChars": 512},
                                    "expect": {"path": "document", "op": "eq", "value": {"$result": "fetched.document"}}}},
            "procedures": {
                "guarded-edit": {"goal": "Observe a file, approve the supplied snapshot ranges, patch and verify fresh persisted text (up to 100000 characters)",
                                 "inputs": file_inputs, "steps": [
                                     {"action": "workspace.read", "args": {"path": {"$input": "path"}}, "save": "observed"},
                                     {"judge": "review-edit"},
                                     {"action": "workspace.patch", "args": {"path": {"$input": "path"}, "expectedSha256": {"$result": "observed.sha256"}, "edits": {"$input": "edits"}},
                                      "save": "patched", "check": "persisted-text", "when": {"judge": "review-edit", "option": "apply"}}]},
                "cited-research": {"goal": "Fetch a source, verify its cached identity and find quote-backed passages",
                                   "inputs": web_inputs, "steps": [
                                       {"action": "web.fetch", "args": {"url": {"$input": "url"}, "maxChars": 512}, "save": "fetched", "check": "cached-document"},
                                       {"action": "web.passages", "args": {"document": {"$result": "fetched.document"}, "query": {"$input": "query"}, "limit": 3}, "save": "passages"},
                                       {"judge": "source-relevance"}]}},
            "judge": {
                "review-edit": {"question": "Do the proposed character ranges match the observed file and intended edit?", "options": ["apply", "leave"],
                                "constraints": "Ranges refer to Unicode characters in this exact snapshot. A hash conflict requires a fresh read; judge decisions grant no additional permission."},
                "source-relevance": {"question": "Do these exact passages support the answer?", "options": ["use", "search-more"],
                                     "constraints": "Use the returned URL and quote ranges; partial responseTruncated sources are not complete documents. Cite only a nonempty returned range."}},
            "pitfalls": [{"failure": "File changed or range overlaps", "recovery": "Read the new snapshot and recompute ranges; never reuse the old hash"},
                         {"failure": "Search incomplete or fallback reported", "recovery": "Narrow includeGlob and inspect engine, skipped and fallbackReason"},
                         {"failure": "Source changed after refresh", "recovery": "Old handles retain their old quotes; use the new handle for current claims"}],
            "frontier": ["Arbitrary external file writers cannot participate in the cooperative edit lock",
                         "HTTP text extraction does not execute JavaScript or extract PDF bytes",
                         "MCP verification proves one validated call, not every tool or external-provider certification"],
            "guidance": ["Coordinates count Unicode characters, including original CRLF; workspace.read returns absolute offset for selected line ranges.",
                         "MCP readiness comes from existing mcp.servers/search/describe/call; configured, connected, discovered, verified, failing. Simulation never verifies.",
                         "Existing model.tools.feedback and model.tools.feedback.record use incremental SQLite aggregates; recorded success is evidence of a tool call, not task completion."]}
        data = {"schema": "neyvia.manual.v1", "id": "tools-depth", "kind": "environment", "chapters": {"tools": chapter}, "schemas": schemas}
        validate(data, registry)
        (REPO / "manuals/tools-depth.manual.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (REPO / "docs/manuals/tools-depth.md").write_text("# Tools depth\n\nGenerated from manuals/tools-depth.manual.json.\n\n" + render(chapter, schemas).rstrip() + "\n", encoding="utf-8")
        existing = REPO / "manuals/workspace.manual.json"
        workspace = json.loads(existing.read_text(encoding="utf-8"))
        for name in ("workspace.read", "workspace.search"):
            workspace["schemas"][name] = schemas[name]
        validate(workspace, registry)
        existing.write_text(json.dumps(workspace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        index_path = REPO / "config/neyvia_manuals.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if not any(row["id"] == "tools-depth" for row in index["manuals"]):
            index["manuals"].append({"id": "tools-depth", "path": "manuals/tools-depth.manual.json", "description": "Ripgrep, guarded range edits and cached web passages with citations"})
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"tools-depth": "grounded", "workspace": "grounded"}))


if __name__ == "__main__":
    build()
