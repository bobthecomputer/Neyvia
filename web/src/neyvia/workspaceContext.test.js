import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeWorkspaceRule, WORKSPACE_DESCRIPTION} from './workspaceContext.js';
test('migrates default wording without changing permission settings or custom descriptions', () => {
 const original={id:'workspace-access-policy',name:'Workspace Access Policy',description:WORKSPACE_DESCRIPTION+' These settings do not describe an organization or establish ownership of connected hardware.',requiresApproval:['Deploy'],autonomyMode:'Balanced'};
 const result=normalizeWorkspaceRule(original);
 assert.equal(result.description,WORKSPACE_DESCRIPTION);
 assert.equal(result.name,'Personal Workspace Settings');
 assert.deepEqual(result.requiresApproval,original.requiresApproval);
 assert.equal(result.autonomyMode,original.autonomyMode);
 assert.match(original.description,/ownership/);
 assert.equal(normalizeWorkspaceRule({...original,description:'My own workflow rules'}).description,'My own workflow rules');
 assert.equal(normalizeWorkspaceRule({...original,id:'custom'}).description,original.description);
});
