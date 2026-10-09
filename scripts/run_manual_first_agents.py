"""Run authorized real Codex MCP and Claude plugin acceptance journeys in scratch roots."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYTHON = str(Path(sys.executable))

def run(which):
    scratch = REPO / ".manual-first-proof" / which
    scratch.mkdir(parents=True, exist_ok=True)
    evidence = REPO / "docs/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "NEYVIA_UI_BACKEND_URL":"http://127.0.0.1:47931", "NEYVIA_PYTHON":PYTHON,
           "PYTHONPATH":str(REPO / "src"), "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC":"1"}
    if which == "codex":
        (scratch / "receipt-input.txt").write_text("manual-first proof: cobalt orchard 739.\n", encoding="utf-8")
        prompt = ("Use only the neyvia MCP server for tools. Do not use shell, file tools, browser or other servers. "
                  "Read neyvia.manual.load(id='neyvia',chapter='overview') first, then manual.index and relevant chapters. "
                  "Complete these three real tasks using non-core tools, searching and describing each exact tool before calling: "
                  "1 Load workspace/files and run manual.run(id='workspace',chapter='files',procedure='read-and-confirm',inputs={'path':'receipt-input.txt','phrase':'cobalt orchard'}), report phrase/hash and verifier result. "
                  "2 Search the workspace for 'cobalt orchard' via workspace.search and report matched path. "
                  "3 Load neyvia-reference/time and run its clock procedure; report actual UTC/local time and verifier. "
                  "Non-core means no individual schema for that task appears in MCP tools/list; catalogCore marks registry membership, not startup schemas. "
                  "Finish with each task's observed evidence. No code edits, no installs, no outside accesses.")
        executable = shutil.which("codex.cmd") or shutil.which("codex")
        command = [executable,"exec","--ignore-user-config","--ignore-rules","--ephemeral","--skip-git-repo-check",
                   "--sandbox","read-only","--json","--cd",str(scratch),
                   "-c",'mcp_servers.neyvia.command='+json.dumps(PYTHON),
                   "-c",'mcp_servers.neyvia.args='+json.dumps(["-m","grant_agent.neyvia_mcp_stdio","--root",str(scratch),"--read-only"]),
                   "-c",'mcp_servers.neyvia.env.PYTHONPATH='+json.dumps(str(REPO / "src")),
                   "-c",'mcp_servers.neyvia.startup_timeout_sec=60',
                   "-c",'mcp_servers.neyvia.tool_timeout_sec=60',
                   "-c",'mcp_servers.neyvia.tools={"neyvia.native.call"={approval_mode="approve"}}',
                   "-c",'base_instructions="Use the Neyvia MCP manual and tools only. Never access other directories or services."',prompt]
    else:
        prompt = ("Use only the Neyvia plugin MCP tools; no built-in tools, shell, or other services. "
                  "Call manual_load(id='neyvia',chapter='overview') first, then manual_index and the neyvia-reference Time chapter. "
                  "Complete three real tasks by executable procedures, loading the named chapter first: "
                  "1 Run manual_run(id='neyvia-reference',chapter='time',procedure='clock',inputs={}) and report actual UTC/local time/check. "
                  "2 Run start-timer in the same manual/chapter with inputs id='manual-executable-claude-verified' label='Grounded manual proof'; report retained state/check. "
                  "3 Run lap-and-stop in that manual/chapter with inputs id='manual-executable-claude-verified',lapId='grounded-lap',label='Executable manual'; report stopped state/check. "
                  "For each non-core tool, tools_search then tools_describe(name='neyvia.<name>') before tools_call. "
                  "Do not create subagents, edit files, install anything, or ask the person for reversible timer work. "
                  "Finish with the three observed results.")
        executable = shutil.which("claude.cmd") or shutil.which("claude")
        prompt = prompt.replace("manual-executable-claude-verified", "manual-executable-" + uuid.uuid4().hex[:12])
        plugin_mcp = {"mcpServers":{"plugin_neyvia_neyvia":{"command":PYTHON,"args":[str(REPO / "plugins/neyvia/mcp/neyvia_mcp.py")],
                                                          "env":{"NEYVIA_UI_BACKEND_URL":"http://127.0.0.1:47931"}}}}
        command = [executable,"--print","--verbose","--output-format","stream-json","--plugin-dir",str(REPO / "plugins/neyvia"),
                   "--strict-mcp-config","--mcp-config",json.dumps(plugin_mcp),"--setting-sources","","--tools","",
                   "--permission-mode","dontAsk","--allowedTools","mcp__plugin_neyvia_neyvia__*","--",prompt]
    with (evidence / f"manual_first_{which}_agent.jsonl").open("w",encoding="utf-8") as out, (evidence / f"manual_first_{which}_agent.stderr.txt").open("w",encoding="utf-8") as err:
        result = subprocess.run(command,cwd=scratch,env=env,stdout=out,stderr=err,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    print(json.dumps({"harness":which,"exitCode":result.returncode,"receipt":f"docs/evidence/manual_first_{which}_agent.jsonl"}))
    return result.returncode

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("harness",choices=["codex","claude"])
    raise SystemExit(run(parser.parse_args().harness))
