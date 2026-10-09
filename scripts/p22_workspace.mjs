// C7/CL workspace-selection cases invoke the production helpers directly.
import { reconcileWorkspaceSelection, resolveAgentLaunchWorkspace, selectedWorkspace } from '../web/src/neyvia/missionHelpers.js';
const workspaces = [
  {workspace_id:'ws-selected',name:'Selected',default_runtime:'hermes',user_profile:'builder'},
  {workspace_id:'ws-busy',name:'Busy',default_runtime:'openclaw',user_profile:'advanced'},
];
const snapshot={workspaces,missions:[{mission_id:'mission-busy',workspace_id:'ws-busy',updated_at:'2026-07-16T12:00:00Z',state:{status:'running'}}]};
const require=(value,message)=>{if(!value)throw Error(message);};
require(selectedWorkspace(snapshot,'ws-selected')?.workspace_id==='ws-selected','Explicit selection changed');
require(selectedWorkspace(snapshot,'ws-missing')==null,'Missing explicit selection fell back');
require(selectedWorkspace(snapshot,null)?.workspace_id==='ws-busy','Automatic selection lost the busy workspace');
for(const rows of [workspaces,[],[workspaces[1]]])
  require(reconcileWorkspaceSelection({workspaces:rows,currentWorkspaceId:'ws-selected',preferredWorkspaceId:'ws-busy',preserveMissing:true})==='ws-selected','Refresh replaced explicit selection');
require(reconcileWorkspaceSelection({workspaces,currentWorkspaceId:'ws-selected',routeWorkspaceId:'ws-busy',preferredWorkspaceId:'ws-selected',preserveMissing:true})==='ws-busy','Explicit route did not override selection');
const args={selectedWorkspaceId:'ws-selected',formWorkspaceId:'ws-busy',workspace:workspaces[1],workspaces};
const launched=resolveAgentLaunchWorkspace(args);
require(launched.workspaceId==='ws-selected' && launched.workspace.default_runtime==='hermes' && launched.workspace.user_profile==='builder','Launch changed selected workspace or profile');
const missing=resolveAgentLaunchWorkspace({...args,selectedWorkspaceId:'ws-missing'});
require(missing.workspaceId==='ws-missing' && missing.workspace===null,'Missing launch selection silently fell back');
console.log(JSON.stringify({ok:true,observed:['explicit and automatic selection','refresh preserves selection','route override','exact launch profile','missing launch fails closed']}));
