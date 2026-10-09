import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

function candidate(root) {
  const bin = process.platform === 'win32' ? path.join(root, '.venv', 'Scripts', 'python.exe') : path.join(root, '.venv', 'bin', 'python');
  if (!fs.existsSync(bin) || !fs.existsSync(path.join(root, 'src', 'grant_agent'))) return null;
  return { root, python: bin };
}

function authoritativeStart(start) {
  let current = path.resolve(start);
  const parts = current.split(path.sep);
  const marker = parts.findIndex(item => item.toLowerCase() === '.agent_control');
  const readOnly = marker >= 0 && parts[marker + 1]?.toLowerCase() === 'read_only_workspaces';
  if (readOnly) return path.resolve(parts.slice(0, marker).join(path.sep) || path.parse(current).root);
  return current;
}

function validateOverride(explicit, found) {
  const resolved = path.resolve(explicit);
  if (!found || resolved !== path.resolve(found.python)) {
    throw new Error(`NEYVIA_VERIFY_PYTHON must be the authoritative project venv executable: ${resolved}`);
  }
  const probe = spawnSync(resolved, ['-c', 'import json,sys; print(json.dumps({"executable":sys.executable,"prefix":sys.prefix}))'], {encoding: 'utf8', timeout: 10000});
  if (probe.status !== 0) throw new Error(`NEYVIA_VERIFY_PYTHON failed validation: ${probe.stderr || probe.error?.message || 'interpreter failed'}`);
  let identity;
  try { identity = JSON.parse(probe.stdout); } catch { throw new Error('NEYVIA_VERIFY_PYTHON returned invalid identity'); }
  if (path.resolve(identity.executable) !== resolved || path.resolve(identity.prefix) !== path.resolve(path.dirname(path.dirname(resolved)))) {
    throw new Error('NEYVIA_VERIFY_PYTHON is not the authoritative project venv interpreter');
  }
  return {root: found.root, python: resolved};
}

function validateExplicitSystem(explicit, root) {
  const resolved = path.resolve(explicit);
  if (!path.isAbsolute(explicit) || !fs.existsSync(path.join(root, 'src', 'grant_agent'))) {
    throw new Error(`NEYVIA_VERIFY_PYTHON must be the authoritative project venv executable or an explicit installed Python: ${resolved}`);
  }
  const probe = spawnSync(resolved, ['-c', 'import json,sys,jsonschema; print(json.dumps({"executable":sys.executable,"isVenv":sys.prefix!=sys.base_prefix}))'], {encoding:'utf8', timeout:10000});
  let identity;
  try { identity = JSON.parse(probe.stdout); } catch { /* handled below */ }
  if (probe.status !== 0 || !identity || path.resolve(identity.executable) !== resolved || identity.isVenv) {
    throw new Error(`NEYVIA_VERIFY_PYTHON must be the authoritative project venv executable or an explicit installed Python: ${resolved}`);
  }
  return {root, python:resolved, interpreterAuthority:'explicit-system'};
}

export function resolveNeyviaPython(start = process.cwd()) {
  const explicit = process.env.NEYVIA_VERIFY_PYTHON?.trim().replace(/[\"']/g, '');
  const system = process.env.NEYVIA_VERIFY_SYSTEM_PYTHON?.trim();
  let current = authoritativeStart(start);
  let found = null;
  let project = null;
  while (true) {
    if (!project && fs.existsSync(path.join(current, 'src', 'grant_agent')) && fs.existsSync(path.join(current, 'package.json'))) project = current;
    found = candidate(current);
    if (found) break;
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  // An operator can explicitly select an installed interpreter for isolated
  // worktrees without a venv. Never infer that choice from PATH or a mirror.
  if (system && !explicit) {
    if (!project || !path.isAbsolute(system)) throw new Error('NEYVIA_VERIFY_SYSTEM_PYTHON requires an absolute interpreter and an authoritative project');
    const resolved = path.resolve(system);
    const probe = spawnSync(resolved, ['-c', 'import json,sys; print(json.dumps({"executable":sys.executable}))'], {encoding: 'utf8', timeout: 10000});
    if (probe.error || probe.status !== 0) throw new Error(`NEYVIA_VERIFY_SYSTEM_PYTHON failed validation: ${probe.error?.message || probe.stderr}`);
    let identity;
    try { identity = JSON.parse(probe.stdout); } catch { throw new Error('NEYVIA_VERIFY_SYSTEM_PYTHON returned invalid identity'); }
    if (path.resolve(identity.executable) !== resolved) throw new Error('NEYVIA_VERIFY_SYSTEM_PYTHON interpreter identity differs');
    return {root: project, python: resolved, source: 'explicit-system'};
  }
  if (!found && explicit) return validateExplicitSystem(explicit, project || authoritativeStart(start));
  if (!found) throw new Error(`No authoritative Neyvia workspace with .venv found from ${start}; set NEYVIA_VERIFY_PYTHON to the explicitly selected installed Python`);
  return explicit ? validateOverride(explicit, found) : found;
}
