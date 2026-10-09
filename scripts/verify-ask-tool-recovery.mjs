import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=resolveNeyviaPython(root).python;
const program=String.raw`
import json, sys
import tempfile
from types import SimpleNamespace
from grant_agent.neyvia_agent import (
    AskQuestionContext, AskQuestionOptions, AskQuestionText, _ask_user_tool_behavior,
)
from agents import ToolsToFinalOutputResult, function_tool
from grant_agent.agent_questions import request_question, list_questions

def tool(name):
    return SimpleNamespace(name=name)
def result(name, output):
    return SimpleNamespace(tool=tool(name), output=output)
def ask_schema(question: AskQuestionText, options: AskQuestionOptions = None,
               context: AskQuestionContext = "") -> str:
    return ""

schema = function_tool(ask_schema).params_json_schema["properties"]
assert schema["question"]["maxLength"] == 1000
assert schema["options"]["anyOf"][0]["maxItems"] == 3
assert schema["options"]["anyOf"][0]["items"]["maxLength"] == 200
assert schema["context"]["maxLength"] == 2000

with tempfile.TemporaryDirectory(prefix="neyvia-ask-recovery-") as folder:
    try:
        request_question(folder, "session-failed", "Choose", ["x" * 201])
    except ValueError as exc:
        error = f"An error occurred while running the tool. Please try again. Error: {exc}"
    else:
        raise AssertionError("Overlong option unexpectedly passed durable question validation")
    failed = _ask_user_tool_behavior(None, [result("neyvia_ask_user", error)])
    assert isinstance(failed, ToolsToFinalOutputResult) and not failed.is_final_output
    durable = request_question(folder, "session-success", "Choose", ["Keep current", "Change it"])
    assert len(list_questions(folder, "session-success")) == 1
    pending = _ask_user_tool_behavior(None, [result("neyvia_ask_user", json.dumps(durable))])
    assert pending.is_final_output
structured_failure = _ask_user_tool_behavior(None, [result("neyvia_ask_user", json.dumps({"ok": False, "error": "bad option"}))])
assert not structured_failure.is_final_output

assert not _ask_user_tool_behavior(None, [result("neyvia_ask_user", json.dumps({"questionId": "q-test", "status": "answered"}))]).is_final_output
assert not _ask_user_tool_behavior(None, [result("workspace.read", "ok")]).is_final_output
print(json.dumps({"ok": True, "failedAskContinues": True, "pendingQuestionStops": True,
                  "limits": {"question": 1000, "option": 200, "optionCount": 3, "context": 2000}}))
`;
const proc=spawnSync(python,['-c',program],{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'src')},encoding:'utf8',timeout:30000,maxBuffer:1024*1024});
assert.equal(proc.status,0,proc.stderr||String(proc.error));
const receipt=JSON.parse(proc.stdout.trim());
assert.equal(receipt.ok,true);
console.log(JSON.stringify(receipt));
