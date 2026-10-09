"""Neyvia's tools for Claude Code: a stdio MCP server that calls the local Neyvia service. Standard library only.

Each tool is a ``neyvia.*`` tool of the running Neyvia backend, named with underscores for MCP
(``neyvia.pdf.open`` is ``pdf_open``). Calls go to ``POST /api/ui/tools/call`` on a loopback address, signed in
with the PC's local session, exactly as Neyvia's own UI does; the backend keeps every approval it already asks for.
Nothing here approves anything, and no Claude credential is read or sent.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

VERSION = "0.2.0"
# With the Claude Code mod loaded, Neyvia's tools are native tools and this server lists nothing (no duplicates).
# Hosts without the mod (older Claude Code, other tools) set NEYVIA_MCP=1 to get the tools from this server.
MOD_OWNS_TOOLS = os.environ.get("NEYVIA_MCP", "") != "1"
DEFAULT_BACKEND = "http://127.0.0.1:47881"
MAX_TEXT = 60_000

# The neyvia.* tools this plugin offers. PORTED.md says why the others are left out.
PORTED = frozenset({
    "verify", "verify.status",
    "browser.state", "browser.open", "browser.tab", "browser.observe", "browser.action", "browser.history", "browser.downloads", "browser.decide", "browser.receipt", "browser.promote", "browser.capture", "browser.wait",
    "browser.task.pause",
    "onboarding.state", "onboarding.recommend", "onboarding.open",
    "cl", "cl.describe", "state", "attention.list", "notify", "manual.index", "manual.load", "manual.observe", "manual.run", "manual.validate", "manual.frontier", "manual.patches",
    "manual.project", "manual.versions", "manual.patch.apply", "manual.demote", "manual.recovery.bind", "manual.recover", "manual.compile", "manual.compiled", "manual.script.run",
    "autopilot.start", "autopilot.get", "autopilot.list", "autopilot.stop", "autopilot.resume",
    "folder.list", "folder.open", "folder.create", "project.create",
    "artifact.publish", "artifact.list", "artifact.get", "artifact.open", "app.open",
    "remote.state", "remote.windows", "remote.snapshot", "remote.log",
    "gamedev.status", "gamedev.sessions", "gamedev.receipt", "gamedev.receipts", "gamedev.state", "gamedev.asset_validate",
    "session.new", "session.rename", "session.pin", "session.move", "session.archive", "session.cluster",
    "pane.show", "pane.observe", "view.state", "view.place", "view.layout", "view.arrange", "view.scene", "view.float", "view.theme", "view.transparency", "view.transparency.state", "terminal.list", "terminal.read",
    "settings.get", "settings.propose", "settings.setup", "settings.network_check",
    "schedule.create", "schedule.list", "schedule.cancel", "schedule.after",
    "watch.create", "watch.list", "watch.cancel",
    "time.now", "time.budget", "timer.start", "timer.read", "timer.lap", "timer.stop", "timer.list",
    "mission.list", "mission.create", "mission.control", "runtime.list", "lab.state",
    "evolver.state", "evolver.lineage", "evolver.receipt", "evolver.genome", "evolver.run", "evolver.job",
    "scroll.import", "scroll.concepts", "scroll.generate", "scroll.job", "scroll.validate", "scroll.review", "scroll.pack", "scroll.preview", "scroll.send", "scroll.stats", "scroll.state",
    "pdf.state", "pdf.open", "pdf.goto", "pdf.search", "pdf.highlight", "pdf.extract_text", "pdf.zoom",
    "image.state", "image.open", "image.crop", "image.resize", "image.composite", "image.export",
    "claude.runs", "work.claim", "work.release", "work.list", "impact", "intent.checklist", "plan.update",
    "agents.state", "agents.limits",
    "modules.list", "modules.get", "modules.source", "modules.validate",
    "marketplace.list", "marketplace.get", "marketplace.read", "marketplace.install", "marketplace.set", "marketplace.update",
    "efficiency.laya_verify",
})
INSTRUCTIONS = ("Read manual_load(id='neyvia',chapter='overview') first, then a relevant chapter. "
                "Use tools_search, tools_describe(name='neyvia.<name>'), then tools_call(tool='neyvia.<name>',arguments={...}). "
                "Tool schemas are deferred; existing Neyvia approvals apply." "Before editing files other agents may touch, call work_list or work_claim when they are listed.")
INSTRUCTIONS += (" For a multi-ask message, start with intent_checklist, fill its schema yourself, apply later corrections only to what they name, "
                 "and publish asks with plan_update(plan=[{step,status}]) or TaskCreate/TaskUpdate (TodoWrite on older Claude Code) before implementation. "
                 "Keep the plan updated after verified progress; blocked asks stay pending with an explanation. No hidden model call.")


def mcp_name(tool: str) -> str:
    return tool.removeprefix("neyvia.").replace(".", "_")


class Backend:
    def __init__(self, base: str | None = None):
        self.base = (base or os.environ.get("NEYVIA_UI_BACKEND_URL") or DEFAULT_BACKEND).rstrip("/")
        parsed = urlparse(self.base)
        self.refusal = None if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"} else (
            "Neyvia's plugin only talks to a Neyvia service on this PC (http://127.0.0.1:<port>)")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.signed_in = False

    def _sign_in(self) -> None:
        request = urllib.request.Request(self.base + "/api/auth/local-session", data=b"{}",
                                         headers={"Content-Type": "application/json"})
        self.opener.open(request, timeout=15).close()
        self.signed_in = True

    def request(self, path: str, body: dict | None = None, timeout: float = 90) -> dict:
        if self.refusal:
            raise ValueError(self.refusal)
        for attempt in (0, 1):
            if not self.signed_in:
                self._sign_in()
            data = None if body is None else json.dumps(body).encode()
            request = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
            try:
                with self.opener.open(request, timeout=timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and attempt == 0:
                    self.signed_in = False
                    continue
                try:
                    return json.load(exc)
                except ValueError:
                    return {"ok": False, "error": f"Neyvia answered HTTP {exc.code}"}
        return {"ok": False, "error": "Neyvia did not accept the local sign-in"}


class Server:
    def __init__(self, backend: Backend):
        self.backend = backend
        self.names: dict[str, str] = {}  # MCP name -> neyvia.* name
        self.catalog: dict[str, dict] = {}

    def core(self):
        # Keep the distributable plugin stdlib-only: grounded schemas come from
        # its authenticated backend catalog, not a second copy of the contracts.
        # CL 1.1 starts with L0; the archival manual/state schemas remain
        # discoverable through the same deferred catalog after first touch.
        names = ["cl", "cl.describe"]
        rows = [{"name": name.replace(".", "_"), "description": self.catalog["neyvia." + name]["description"], "inputSchema": self.catalog["neyvia." + name]["inputSchema"]} for name in names]
        text = {"type": "string"}
        for name, description, properties, required in [
            ("tools_search", "Find tool names and purposes; schemas load on describe.", {"query": text, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"]),
            ("tools_describe", "Load one exact tool schema and call target.", {"name": text}, ["name"]),
            ("tools_call", "Call a discovered tool; existing approvals apply.", {"tool": text, "arguments": {"type": "object"}}, ["tool", "arguments"])]:
            rows.append({"name": name, "description": description, "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}})
        return rows

    def tools(self) -> list[dict]:
        if MOD_OWNS_TOOLS:
            return []
        try:
            answer = self.backend.request("/api/ui/tools", timeout=30)
        except (OSError, ValueError) as exc:
            self.names = {}
            return [{"name": "status", "description": "Neyvia is not reachable right now (" + str(exc)[:120] +
                     "). Call this to check again once the Neyvia app runs.", "inputSchema": {"type": "object", "properties": {}}}]
        rows = (answer.get("data") or {}).get("tools") or []
        listed = []
        self.names = {}
        self.catalog = {}
        for row in rows:
            name = str(row.get("name") or "")
            short = name.removeprefix("neyvia.")
            trusted_mod = bool(re.fullmatch(r"mod\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", short))
            if (short not in PORTED and not trusted_mod) or row.get("available") is False:
                continue
            self.names[mcp_name(name)] = name
            self.catalog[name] = row
            schema = row.get("inputSchema") if isinstance(row.get("inputSchema"), dict) else {"type": "object", "properties": {}}
            tool = {"name": mcp_name(name), "description": str(row.get("description") or "")[:1000], "inputSchema": schema}
            if row.get("mutability") == "read":
                tool["annotations"] = {"readOnlyHint": True}
            listed.append(tool)
        return self.core()

    def call(self, name: str, arguments: dict) -> dict:
        if name == "status":
            listed = self.tools()
            ok = bool(self.names)
            return text_result(f"Neyvia is reachable; {len(listed)} tools are ready (restart the session to list them)." if ok
                               else "Neyvia is still not reachable on this PC.", not ok)
        if not self.names:
            self.tools()
        if name == "tools_search":
            query = str(arguments.get("query") or "").casefold().strip()
            limit = max(1,min(int(arguments.get("limit") or 8),20))
            found = sorted(self.catalog.values(), key=lambda row:(row["name"].casefold()!=query, row["name"]))
            terms = query.split()
            found = [row for row in found if all(term in (row["name"]+" "+row.get("description","")).casefold() for term in terms)][:limit]
            return text_result(json.dumps({"tools":[{"name":row["name"],"description":row.get("description",""),"callTarget":"tools_call"} for row in found],"next":"tools_describe"}),False)
        if name == "tools_describe":
            tool = str(arguments.get("name") or "")
            row = self.catalog.get(tool)
            if row is None:
                return text_result("Unknown exact tool name; use tools_search.",True)
            return text_result(json.dumps({**row,"callTarget":"tools_call","callArguments":{"tool":tool},"callInstructions":"Put schema fields in arguments; approval requirements remain enforced."}),False)
        tool = str(arguments.get("tool") or "") if name == "tools_call" else self.names.get(name)
        if name == "tools_call":
            arguments = arguments.get("arguments")
            if not isinstance(arguments,dict):
                return text_result("arguments must be an object.",True)
            if tool not in self.catalog:
                return text_result("Unknown exact tool name; describe a discovered tool first.",True)
        if tool is None:
            return text_result(f"{name} is not a Neyvia tool this plugin offers.", True)
        try:
            if tool in {"neyvia.autopilot.start", "neyvia.autopilot.resume"}:
                allowed = set(self.catalog)
                scope = arguments.get("scopeTools")
                if scope is None and tool.endswith(".resume"):
                    retained = self.backend.request("/api/ui/autopilot?runId=" + str(arguments.get("runId", "")))
                    scope = retained["data"]["run"]["scopeTools"]
                if any(t not in allowed for t in scope or []):
                    return text_result("Autopilot needs tools outside this plugin's PORTED scope; use the owning Native harness and its grants.", True)
                arguments = {**arguments, "scopeTools": scope or []}
            if tool in {"neyvia.manual.script.run", "neyvia.manual.recover"}:
                arguments = {**arguments, "scopeTools": sorted(self.catalog)}
            if tool in {"neyvia.manual.run", "neyvia.manual.observe"}:
                # A deterministic procedure must not turn an excluded file,
                # shell or provider tool into a hidden second permission path.
                grounding = self.backend.request("/api/ui/tools/call", {"tool": "neyvia.manual.validate", "arguments": {"id": arguments.get("id")}})
                manuals = result_value(grounding).get("manuals", [])
                entries = [entry for manual in manuals for entry in manual["procedures" if tool.endswith("run") else "observers"]
                           if (not arguments.get("chapter") or entry["chapter"] == arguments["chapter"])
                           and entry["procedure" if tool.endswith("run") else "state"] == arguments.get("procedure" if tool.endswith("run") else "state")]
                if len(entries) != 1 or any(target not in self.catalog for target in entries[0]["tools"]):
                    return text_result("This procedure/observer needs tools outside this plugin's PORTED scope; use the owning harness and its grants.", True)
                arguments = {**arguments, "scopeTools": sorted(self.catalog)}
            if tool == "neyvia.cl":
                arguments = {**arguments, "scopeTools": sorted(self.catalog)}
            answer = self.backend.request("/api/ui/tools/call", {"tool": tool, "arguments": arguments or {}})
        except (OSError, ValueError) as exc:
            return text_result("Neyvia is not reachable right now: " + str(exc)[:200], True)
        receipt = answer.get("data") if isinstance(answer.get("data"), dict) else {}
        # Owner CL routes return the value directly; older gateway routes wrap
        # it in a tool receipt. Preserve both, including CL failures and text.
        result = result_value(answer)
        if tool in {"neyvia.cl", "neyvia.cl.describe"} and isinstance((result or {}).get("text"), str):
            return text_result(result["text"], result.get("ok") is False)
        status = receipt.get("status") or ("completed" if answer.get("ok") else "failed")
        if status == "approval_required":
            return text_result("Waiting for the person to approve this in Neyvia" +
                               (f" (approval {result.get('approvalId')})" if result and result.get("approvalId") else "") +
                               ". Ask them to press Approve there, then call again with the same arguments.", True)
        if not answer.get("ok") or receipt.get("ok") is False:
            message = receipt.get("error") or answer.get("error") or (result or {}).get("error") or "The tool failed"
            return text_result(str(message)[:2000], True)
        payload = {key: value for key, value in (result or {}).items() if key != "event"}
        return text_result(json.dumps(payload, ensure_ascii=False, default=str)[:MAX_TEXT], False)

    def handle(self, message: dict) -> dict | None:
        method, identity = message.get("method"), message.get("id")
        if identity is None:
            return None  # a notification (initialized, cancelled): nothing to answer
        params = message.get("params") or {}
        try:
            if method == "initialize" and MOD_OWNS_TOOLS:
                result = {"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                          "capabilities": {"tools": {}}, "serverInfo": {"name": "neyvia", "version": VERSION}}
            elif method == "initialize":
                context = self.backend.request("/api/ui/tools/call", {"tool":"neyvia.cl.describe", "arguments":{"primer":True}})
                instructions = result_value(context).get("text")
                if not isinstance(instructions, str):
                    raise ValueError("The backend does not expose the approved CL primer; use a matching local build")
                result = {"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                          "capabilities": {"tools": {}}, "serverInfo": {"name": "neyvia", "version": VERSION},
                          "instructions": instructions}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.tools()}
            elif method == "tools/call":
                result = self.call(str(params.get("name") or ""), params.get("arguments") or {})
            else:
                return {"jsonrpc": "2.0", "id": identity, "error": {"code": -32601, "message": f"Unknown method {method}"}}
        except Exception as exc:  # one bad call must not end the server
            return {"jsonrpc": "2.0", "id": identity, "error": {"code": -32603, "message": str(exc)[:500]}}
        return {"jsonrpc": "2.0", "id": identity, "result": result}


def result_value(answer: dict) -> dict:
    receipt = answer.get("data") if isinstance(answer.get("data"), dict) else {}
    return receipt["result"] if isinstance(receipt.get("result"), dict) else receipt


def text_result(text: str, is_error: bool) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def main() -> int:
    server = Server(Backend())
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = server.handle(message) if isinstance(message, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
