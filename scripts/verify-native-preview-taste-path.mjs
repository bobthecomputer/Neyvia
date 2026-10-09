import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {existsSync, readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {tmpdir} from 'node:os';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = resolveNeyviaPython(repo).python;
const extended = value => {
  const full = path.resolve(value);
  return full.startsWith('\\\\') ? `\\\\?\\UNC\\${full.slice(2)}` : `\\\\?\\${full}`;
};
const extendedRoot = extended(repo);
const stamp = Date.now();
const outputDir = path.join(repo, '.agent_control', 'mission_artifacts', 'native_tools', 'taste', `path-proof-${stamp}`);
const common = {
  url: 'http://127.0.0.1:8877/neyvia-tool-proof-20260925.html',
  goal: 'Click Mark verified and confirm the page changes',
  viewports: ['desktop'],
  delayMs: 0,
  includeImageData: false,
  journey: {
    ready: [{kind:'selector_text', selector:'#result', value:'Ready'}],
    actions: [{kind:'click', label:'Mark verified', expect:[{kind:'selector_text', selector:'#result', value:'Verified by Laya'}]}],
    expect: [{kind:'selector_text', selector:'#result', value:'Verified by Laya'}],
  },
};

function call(argumentsValue, actionId) {
  const command = ['-m','grant_agent.neyvia_mcp_stdio','--root',extendedRoot,'--session-id','preview-taste-path-proof',
    '--native-mutation-tool','preview.taste'];
  const request = {jsonrpc:'2.0', id:1, method:'tools/call', params:{name:'neyvia.native.call', arguments:{
    toolId:'preview.taste', arguments:argumentsValue, actionId,
  }}};
  const run = spawnSync(python, command, {cwd:repo, env:{...process.env, PYTHONPATH:path.join(repo,'src')},
    encoding:'utf8', input:JSON.stringify(request)+'\n', timeout:180000});
  assert.equal(run.status, 0, run.stderr || run.stdout);
  const response = JSON.parse(run.stdout.trim().split(/\r?\n/).at(-1));
  if (response.error) throw new Error(response.error.message);
  return response.result.structuredContent;
}

const result = call({...common, outputDir}, `preview-taste-path-${stamp}`);
assert.equal(result.ok, true, JSON.stringify(result));
assert.equal(result.operationStatus, 'unverified', JSON.stringify(result));
assert.equal(result.toolResult?.journey?.passed, true, JSON.stringify(result.toolResult?.journey));
assert.ok(result.toolResult?.screenshots?.desktop?.path);
assert.ok(result.toolResult?.report);
assert.equal(result.toolResult?.artifacts?.length, 2);
assert.ok(result.toolResult.artifacts.every(value => path.isAbsolute(value)), JSON.stringify(result.toolResult.artifacts));
const imagePath = result.toolResult.screenshots.desktop.path;
assert.ok(existsSync(imagePath));
assert.equal(createHash('sha256').update(readFileSync(imagePath)).digest('hex'), result.toolResult.screenshots.desktop.sha256);
const report = JSON.parse(readFileSync(result.toolResult.report, 'utf8'));
assert.equal(report.journeyReceipt.execution_performed, true);
assert.equal(report.journeyReceipt.passed, true);
assert.equal(report.journeyReceipt.receipt.verification.length, 1);
assert.equal(report.journeyReceipt.receipt.verification[0].passed, true);
const operationReceipt = JSON.parse(readFileSync(result.operationReceiptPath, 'utf8'));
assert.equal(operationReceipt.status, 'unverified');
assert.equal(operationReceipt.result.artifacts.length, 2);
assert.equal(operationReceipt.result.artifacts[0].sha256, result.toolResult.screenshots.desktop.sha256);
assert.equal(operationReceipt.result.artifacts[1].sha256, createHash('sha256').update(readFileSync(result.toolResult.report)).digest('hex'));

const outside = path.join(tmpdir(), `neyvia-preview-taste-escape-${stamp}`);
const rejected = call({...common, outputDir:outside}, `preview-taste-outside-${stamp}`);
assert.equal(rejected.ok, false);
assert.equal(rejected.operationStatus, 'failed');
const failureReceipt = JSON.parse(readFileSync(rejected.operationReceiptPath, 'utf8'));
assert.match(String(failureReceipt.result.effect.error), /inside the workspace root/i);
assert.equal(existsSync(outside), false);

console.log(JSON.stringify({passed:true, route:'actual stdio MCP + operation receipt',
  extendedWorkspaceRoot:true, ordinaryOutputPathAccepted:true, absoluteArtifactPathsPreserved:true,
  artifactHashesChecked:operationReceipt.result.artifacts.length, journeyPassed:result.toolResult.journey.passed,
  layaExecutionPerformed:report.journeyReceipt.execution_performed, screenshot:imagePath,
  screenshotSha256:result.toolResult.screenshots.desktop.sha256, report:result.toolResult.report,
  outsideOutputPathRejected:true, outsideDirectoryCreated:false}));
