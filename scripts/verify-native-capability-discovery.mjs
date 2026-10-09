import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const root = mkdtempSync(path.join(tmpdir(), 'neyvia-native-capability-'));
try {
  const result = spawnSync(resolveNeyviaPython().python, ['-c', String.raw`
import asyncio,json,sys
from pathlib import Path
from agents import RunConfig, RunContextWrapper
from grant_agent.neyvia_agent import NeyviaAgentConfig, build_neyvia_agent
from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
from grant_agent.native_access import access_context

root=Path(sys.argv[1]).resolve()
custom='  operator prompt bytes stay authored\r\nSecond line.  '
def build(mode, suffix):
 config=NeyviaAgentConfig(root=root,session_id='capability-'+suffix,permission_mode=mode,enable_specialists=False)
 return build_neyvia_agent(config,provider=None,instructions=custom)[0]

full=build('full-access','full')
readonly=build('read-only','readonly')
def tool(agent,name):
 return next(item for item in agent.tools if getattr(item,'name','')==name)
full_terminal=tool(full,'neyvia_terminal_exec')
ro_terminal=tool(readonly,'neyvia_terminal_exec')
full_schema=getattr(full_terminal,'params_json_schema',{})
checks={
 'sdkTerminalToolPresent': full_terminal is not None,
 'sdkTerminalSchemaUsesNativeFields': all(key in (full_schema.get('properties') or {}) for key in ('command','shell','cwd','timeoutMs','maxOutputChars','action_id')),
 'sdkFullDescriptionHasModeWorkspaceAndPermission': all(token in full_terminal.description for token in ('full-access','Selected workspace:','permitted','PowerShell','Python')),
 'sdkReadOnlyDescriptionSeparatesAvailabilityAndPermission': all(token in ro_terminal.description for token in ('read-only','Detected command routes:','not permitted','availability does not grant execution permission')),
 'customPromptPreserved': full.instructions==custom and readonly.instructions==custom,
}
invoke=getattr(full_terminal,'on_invoke_tool',None)
if invoke:
 ctx=RunContextWrapper(None);ctx.tool_name='neyvia_terminal_exec';ctx.run_config=RunConfig(tracing_disabled=True)
 output=asyncio.run(invoke(ctx,json.dumps({'command':"print('NEYVIA_TERMINAL_EXEC_OK')",'shell':'python','cwd':str(root),'timeoutMs':10000,'maxOutputChars':2000,'action_id':'native-capability-echo'})))
 output=json.loads(output) if isinstance(output,str) else output
 checks['sdkWrapperRunsBenignCommand']=bool(output.get('ok')) and 'NEYVIA_TERMINAL_EXEC_OK' in json.dumps(output)
else:
 output={}
 checks['sdkWrapperRunsBenignCommand']=False
ro_ctx=RunContextWrapper(None);ro_ctx.tool_name='neyvia_terminal_exec';ro_ctx.run_config=RunConfig(tracing_disabled=True)
denied=asyncio.run(ro_terminal.on_invoke_tool(ro_ctx,json.dumps({'command':"print('SHOULD_NOT_RUN')",'shell':'python','cwd':str(root),'timeoutMs':10000,'maxOutputChars':2000,'action_id':'native-capability-denied'})))
denied=json.loads(denied) if isinstance(denied,str) else denied
checks['sdkWrapperPreservesReadOnlyDenial']=denied.get('status')=='approval_required' and not denied.get('ok')

def mcp(mode,suffix):
 return CompactNeyviaMCPServer(root,permission_mode=mode,session_id='mcp-'+suffix)
full_mcp=mcp('full-access','full')
ro_mcp=mcp('read-only','readonly')
full_environment=full_mcp._gateway().call_native('runtime.environment',{})
ro_environment=ro_mcp._gateway().call_native('runtime.environment',{})
full_access=access_context('full-access',environment=full_environment,granted_tools=full_mcp.native_mutation_tools,mutations_allowed=True)
ro_access=access_context('read-only',environment=ro_environment,granted_tools=ro_mcp.native_mutation_tools,mutations_allowed=False)
checks['accessContextSeparatesRuntimeFromPermission']=full_access['effectiveAccess']['localCommandExecution'] and ro_access['capabilities']['commandExecutionPermitted'] is False and ro_access['capabilities']['pythonCommands'] is False and ro_access['capabilities']['pythonAvailable'] is True and ro_access['toolRoutes'][1]['available'] is False and ro_access['toolRoutes'][1]['runtimeAvailable'] is True and ro_access['toolRoutes'][1]['executionPermitted'] is False
def listed(server):
 return server.handle({'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}})['result']['tools']
full_tools=listed(full_mcp);ro_tools=listed(ro_mcp)
full_terminal_schema=next(item for item in full_tools if item['name']=='neyvia.terminal.exec')
ro_terminal_schema=next(item for item in ro_tools if item['name']=='neyvia.terminal.exec')
checks['mcpTerminalSchemaAndRunFacts']=('actionId' in full_terminal_schema['inputSchema']['required'] and 'full-access' in full_terminal_schema['description'] and 'Selected workspace:' in full_terminal_schema['description'])
checks['mcpReadOnlyFactsInDescription']=('read-only' in ro_terminal_schema['description'] and 'not permitted in this run' in ro_terminal_schema['description'])
full_call=full_mcp.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'neyvia.terminal.exec','arguments':{'command':"print('NEYVIA_MCP_ECHO_OK')",'shell':'python','cwd':str(root),'timeoutMs':10000,'maxOutputChars':2000,'actionId':'mcp-capability-echo'}}})
ro_call=ro_mcp.handle({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'neyvia.terminal.exec','arguments':{'command':"print('SHOULD_NOT_RUN')",'shell':'python','cwd':str(root),'timeoutMs':10000,'maxOutputChars':2000,'actionId':'mcp-capability-denied'}}})
checks['mcpWrapperRunsBenignCommand']='NEYVIA_MCP_ECHO_OK' in json.dumps(full_call)
checks['mcpWrapperPreservesReadOnlyDenial']='approval_required' in json.dumps(ro_call)
print(json.dumps({'checks':checks,'sdkExecution':output,'denial':denied,'mcpExecution':full_call,'mcpDenial':ro_call}))
`, root], {env: {...process.env, PYTHONPATH: path.resolve('src')}, encoding: 'utf8', timeout: 60000});
  assert.equal(result.status, 0, result.stderr || result.error?.message || result.stdout);
  const report = JSON.parse(result.stdout);
  for (const [name, passed] of Object.entries(report.checks)) assert.equal(passed, true, name);
  console.log(JSON.stringify({status: 'verified', checks: report.checks, boundary: 'Production SDK and MCP wrappers with disposable workspace receipts; benign local Python commands only; no provider calls.'}));
} finally {
  if (path.dirname(path.resolve(root)) === path.resolve(tmpdir()) && path.basename(root).startsWith('neyvia-native-capability-')) rmSync(root, {recursive: true, force: true});
}
