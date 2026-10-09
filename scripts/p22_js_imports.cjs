#!/usr/bin/env node
'use strict';

// One bounded parser process serves an entire source graph. Python sends one
// JSONL row per reachable file; this worker never reads files or writes state.
const readline = require('node:readline');
const parserPath = process.env.P22_BABEL_PARSER_PATH;
if (!parserPath) throw new Error('P22_BABEL_PARSER_PATH is required');
const { parse } = require(parserPath);
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });

function literal(node) {
  if (!node) return null;
  if (node.type === 'StringLiteral' || node.type === 'Literal') {
    return typeof node.value === 'string' ? node.value : null;
  }
  if (node.type === 'TemplateLiteral' && node.expressions.length === 0 && node.quasis.length === 1) {
    return node.quasis[0].value.cooked ?? node.quasis[0].value.raw;
  }
  return null;
}

function collect(source, filename) {
  const ext = filename.toLowerCase().split('.').pop();
  const plugins = ['jsx', 'decorators-legacy', 'importAttributes', 'topLevelAwait'];
  if (['ts', 'tsx', 'mts', 'cts'].includes(ext)) plugins.push('typescript');
  const ast = parse(source, { sourceType: 'unambiguous', sourceFilename: filename,
    allowAwaitOutsideFunction: true, plugins });
  const found = new Map();
  const add = (kind, node) => {
    const value = literal(node);
    const row = { kind, specifier: value, line: node?.loc?.start?.line ?? null,
      column: node?.loc?.start?.column ?? null };
    const key = JSON.stringify(row);
    found.set(key, row);
  };
  const stack = [ast];
  while (stack.length) {
    const node = stack.pop();
    if (!node || typeof node !== 'object') continue;
    if (Array.isArray(node)) { for (let i = node.length - 1; i >= 0; i--) stack.push(node[i]); continue; }
    switch (node.type) {
      case 'ImportDeclaration': add('import', node.source); break;
      case 'ExportNamedDeclaration':
      case 'ExportAllDeclaration': if (node.source) add('export-from', node.source); break;
      case 'ImportExpression': add('dynamic-import', node.source); break;
      case 'CallExpression':
        if (node.callee?.type === 'Import') add('dynamic-import', node.arguments?.[0]);
        else if (node.callee?.type === 'Identifier' && node.callee.name === 'require' && node.arguments?.length === 1)
          add('require', node.arguments[0]);
        break;
    }
    for (const [key, value] of Object.entries(node)) {
      if (key === 'loc' || key === 'start' || key === 'end' || key === 'extra' || key === 'tokens' || key === 'comments') continue;
      if (value && typeof value === 'object') stack.push(value);
    }
  }
  return [...found.values()].sort((a, b) => (a.line ?? 0) - (b.line ?? 0) || (a.column ?? 0) - (b.column ?? 0) || a.kind.localeCompare(b.kind));
}

input.on('line', line => {
  let request;
  try {
    request = JSON.parse(line);
    if (request.close === true) { input.close(); return; }
    if (!Number.isInteger(request.id) || typeof request.path !== 'string' || typeof request.source !== 'string')
      throw new Error('request needs integer id, path and source strings');
    const specifiers = collect(request.source, request.path);
    process.stdout.write(JSON.stringify({ id: request.id, specifiers }) + '\n');
  } catch (error) {
    process.stdout.write(JSON.stringify({ id: request?.id ?? null,
      error: `${error.name || 'Error'}: ${error.message || error}` }) + '\n');
  }
});
