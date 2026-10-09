import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=process.env.NEYVIA_PYTHON || 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const code=String.raw`
import asyncio,json,sys
from pathlib import Path
from agents import RunContextWrapper
from agents.tool_context import ToolContext
from grant_agent.neyvia_agent import NeyviaAgentConfig,build_neyvia_agent
from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
from grant_agent.manual_first import deferred_tools
from PIL import Image
root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
async def check():
 agent,_,gateway=build_neyvia_agent(NeyviaAgentConfig(root=root,session_id='sdk-bindings'),provider=None)
 context=RunContextWrapper(context=None)
 before=[tool.name for tool in await agent.get_all_tools(context)]
 describe=next(tool for tool in agent.tools if tool.name=='neyvia_tools_describe')
 await describe.on_invoke_tool(ToolContext(context=None,tool_name=describe.name,tool_call_id='describe-proof',tool_arguments='{}'),json.dumps({'tool_id':'neyvia_view_image'}))
 after=[tool.name for tool in await agent.get_all_tools(context)]
 Image.new('RGB',(16,16),(40,180,90)).save(root/'view.png')
 vision=next(tool for tool in agent.tools if tool.name=='neyvia_view_image')
 output=await vision.on_invoke_tool(ToolContext(context=None,tool_name=vision.name,tool_call_id='vision-proof',tool_arguments='{}'),json.dumps({'path':'view.png'}))
 return {'before':before,'after':after,'visionOutput':type(output).__name__,'actualPixels':str(getattr(output,'image_url','')).startswith('data:image/png;base64,')}
sdk=asyncio.run(check())
server=CompactNeyviaMCPServer(root,read_only=True,session_id='read-gate')
def rpc(tool,args):return server.handle({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':tool,'arguments':args}})
listed=server.handle({'jsonrpc':'2.0','id':1,'method':'tools/list'})['result']['tools']
contracts={name:rpc('neyvia.tools.describe',{'name':name}) for name in ['neyvia.operations.inspect','neyvia.terminal.exec','neyvia.workspace.prove','neyvia.situation']}
recover=rpc('neyvia.tools.invoke',{'tool':'neyvia.operations.inspect','arguments':{}})
denied=rpc('neyvia.native.call',{'toolId':'workspace.write','arguments':{'path':'forbidden.txt','content':'must not exist'},'actionId':'deny-proof'})
unknown=rpc('neyvia.tools.invoke',{'tool':'neyvia.not-real','arguments':{}})
print(json.dumps({'sdk':sdk,'mcpInitialNames':[row['name'] for row in listed],'contracts':contracts,'recovery':recover,'denied':denied,'unknown':unknown,'forbiddenExists':(root/'forbidden.txt').exists()},default=str))
`;
const run=spawnSync(python,['-c',code,path.join(repo,'.manual-first-proof','structural')],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:60000});
assert.equal(run.status,0,run.stderr);
const proof=JSON.parse(run.stdout.trim());
assert(!proof.sdk.before.includes('neyvia_view_image'));
assert(proof.sdk.after.includes('neyvia_view_image'));
assert(proof.sdk.actualPixels);
assert(!proof.mcpInitialNames.includes('neyvia.terminal.exec'));
for(const [name,row] of Object.entries(proof.contracts)) assert(!row.error,`${name}: ${JSON.stringify(row.error)}`);
assert(!proof.recovery.error);
assert(proof.denied.error || proof.denied.result?.structuredContent?.ok===false || proof.denied.result?.isError,JSON.stringify(proof.denied));
assert(proof.unknown.error);
assert.equal(proof.forbiddenExists,false);
console.log(JSON.stringify({passed:true,...proof},null,2));
