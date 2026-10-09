"""Prove the authenticated plugin/HTTP CL read path on an owned backend."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.parser import parse_document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=48281)
    args = parser.parse_args()
    if args.port not in range(48281, 48290):
        parser.error("Only task-owned ports 48281-48289 are permitted")
    spec = importlib.util.spec_from_file_location("cl_plugin_proof", REPO / "plugins/neyvia/mcp/neyvia_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    backend = module.Backend("http://127.0.0.1:" + str(args.port))
    folder = REPO / ".agent_control/cl/http-runtime/notes-proof"
    setup = [backend.request("/api/ui/tools/call", {"tool":"neyvia.notes.folder", "arguments":{"folder":str(folder)}}),
             backend.request("/api/ui/tools/call", {"tool":"neyvia.notes.write", "arguments":{"path":"proof.md", "body":"HTTP CL fixture\n42 units"}})]
    server = module.Server(backend)
    initialized = server.handle({"jsonrpc":"2.0", "id":1, "method":"initialize", "params":{"protocolVersion":"2024-11-05"}})
    catalog = server.handle({"jsonrpc":"2.0", "id":2, "method":"tools/list"})
    read = server.handle({"jsonrpc":"2.0", "id":3, "method":"tools/call", "params":{"name":"cl", "arguments":{"lines":'do time.now()'}}})
    native_read = backend.request("/api/ui/tools/call", {"tool":"neyvia.cl", "arguments":{"lines":'do notes.read(path:"proof.md")'}})
    denied = server.handle({"jsonrpc":"2.0", "id":4, "method":"tools/call", "params":{"name":"cl", "arguments":{"lines":'do timer.start(id:"proof" label:"CL proof")'}}})
    excluded = server.handle({"jsonrpc":"2.0", "id":5, "method":"tools/call", "params":{"name":"cl", "arguments":{"lines":'do workspace.read(path:"anything.txt")', "scopeTools":["workspace.read"]}}})
    nested = server.handle({"jsonrpc":"2.0", "id":6, "method":"tools/call", "params":{"name":"cl", "arguments":{"lines":'do neyvia.cl(lines:"do workspace.read(path:\\"anything.txt\\")")'}}})
    excluded_observer = server.handle({"jsonrpc":"2.0", "id":7, "method":"tools/call", "params":{"name":"cl", "arguments":{"lines":'do perception.observe(layer:"app" source:{tool:"neyvia.workspace.read" arguments:{path:"anything.txt"}})'}}})
    def act(lines):
        return backend.request("/api/ui/tools/call", {"tool":"neyvia.cl", "arguments":{"lines":lines}})["data"]["result"]
    source = folder.parent / "observed.txt"
    source.write_text("First source\n42 units", encoding="utf-8")
    observe_call = 'do perception.observe(layer:"file" source:{path:"observed.txt"} stream:"CL-proof")'
    snapshot = act(observe_call[:-1] + ' reset:true)')
    source.write_text("Changed source\n43 units", encoding="utf-8")
    delta = act(observe_call)
    source.write_text("large source " + "x" * 6000, encoding="utf-8")
    large = act(observe_call[:-1] + ' reset:true)')
    handle = re.search(r"S file (@h\d+)", large["text"]).group(1)
    projection = act('do project(handle:' + handle + ' path:"state.text" offset:0 limit:12)')
    manual = act('do manual.observe(id:"notes" state:"current" reset:true)')
    artifacts = act('do artifact.list()')
    observed = backend.request("/api/ui/tools/call", {"tool":"neyvia.notes.read", "arguments":{"path":"proof.md"}})
    text = read.get("result", {}).get("content", [{}])[0].get("text", "")
    denial = denied.get("result", {}).get("content", [{}])[0].get("text", "")
    passed = {"owner_setup":all(row.get("ok") for row in setup),
              "approved_primer": "Connected Language" in initialized.get("result", {}).get("instructions", ""),
              "cl_catalog":any(row["name"] == "cl" for row in catalog.get("result", {}).get("tools", [])),
              "plugin_cl_read": "R neyvia.time.now ok" in text,
              "native_http_cl_read": "HTTP CL fixture" in native_read.get("data", {}).get("result", {}).get("text", ""),
              "plugin_exclusions_preserved":bool(excluded.get("result", {}).get("isError")) and "outside" in excluded.get("result", {}).get("content", [{}])[0].get("text", ""),
              "nested_gateway_refused":bool(nested.get("result", {}).get("isError")),
              "nested_observer_scope_preserved":bool(excluded_observer.get("result", {}).get("isError")),
              "snapshot_actual_source":snapshot["ok"] and "First source" in snapshot["text"],
              "delta_actual_source":delta["ok"] and "D +file" in delta["text"] and "Changed source" in delta["text"],
              "large_state_bounded":large["ok"] and "S file" in large["text"] and len(large["text"]) < 300,
              "large_immutable_projection":projection["ok"] and '"large source"' in projection["text"],
              "manual_observer_actual_state":manual["ok"] and "proof.md" in manual["text"] and "L notes" in manual["text"],
              "artifact_dispatch_returns":artifacts["ok"] and "L artifact" in artifacts["text"],
              "readonly_failure": "ask" in denial and bool(denied.get("result", {}).get("isError")),
              "denied_bytes_unchanged":observed.get("data", {}).get("result", {}).get("body") == "HTTP CL fixture\n42 units"}
    for result in (snapshot, delta, large, projection, manual, artifacts):
        parse_document(result["text"])
    passed["state_output_parseable"] = True
    receipt = {"schema":"neyvia.cl.http-proof.v1", "url":backend.base, "allPassed":all(passed.values()), "passed":passed,
               "transcripts":{"initialize":initialized,"catalog":catalog,"read":read,"native_read":native_read,"denied":denied,"excluded":excluded,"nested":nested,"excluded_observer":excluded_observer,"snapshot":snapshot,"delta":delta,"large":large,"projection":projection,"manual":manual,"artifacts":artifacts,"readback":observed},
               "boundary":"Authenticated task-owned localhost backend and distributable stdlib plugin; public instance untouched"}
    path = REPO / ".agent_control/cl/http-proof.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"allPassed":receipt["allPassed"],"passed":passed,"receipt":str(path)}))
    return int(not receipt["allPassed"])


if __name__ == "__main__":
    raise SystemExit(main())
