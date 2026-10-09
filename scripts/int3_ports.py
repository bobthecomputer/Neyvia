"""Review/apply explicit fixture-port selection to Python and JS proof sources."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.proof_ports import INT3_PORT_MAP, REQUIRED_PORTS, _PORT_PATTERN

PY_IMPORT = 'from .proof_ports import proof_port, proof_text\n'
JS_MARKER = '// Explicit proof fixture port selection (int3_ports.py).'
JS_HELPER = '''// Explicit proof fixture port selection (int3_ports.py).
import { execFileSync as proofExecFileSync } from 'node:child_process';
import { fileURLToPath as proofFileURLToPath } from 'node:url';
const proofPortSelection = process.env.NEYVIA_PROOF_PORT_MAP === undefined ? null : JSON.parse(proofExecFileSync(
  process.env.NEYVIA_SYSTEM_PYTHON || process.env.PYTHON || 'python',
  [proofFileURLToPath(new URL('../src/grant_agent/proof_ports.py', import.meta.url))],
  { encoding: 'utf8', env: process.env }).trim());
function proofPort(original) { return proofPortSelection === null ? original : proofPortSelection[String(original)]; }
function proofText(text) { return text.replace(/(?<!\\d)(PORT_ALTERNATION)(?!\\d)/g, value => String(proofPort(Number(value)))); }
'''.replace('PORT_ALTERNATION', '|'.join(map(str, REQUIRED_PORTS)))


def python_source(source):
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    encoded = source.encode('utf-8')
    lines = encoded.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    changes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Constant, ast.JoinedStr)):
            continue
        parent = parents.get(node)
        if isinstance(parent, (ast.JoinedStr, ast.FormattedValue)):
            continue
        if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) and parent.func.id in ('proof_port', 'proof_text'):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and isinstance(parent, ast.Expr):
            grandparent = parents.get(parent)
            if isinstance(grandparent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and grandparent.body[0] is parent:
                continue  # Preserve Python docstring semantics.
        begin = offsets[node.lineno - 1] + node.col_offset
        end = offsets[node.end_lineno - 1] + node.end_col_offset
        literal = encoded[begin:end].decode('utf-8')
        if isinstance(node, ast.Constant) and type(node.value) is int and node.value in REQUIRED_PORTS:
            changes.append((begin, end, 'proof_port(' + literal + ')'))
        elif ((isinstance(node, ast.Constant) and isinstance(node.value, str)) or isinstance(node, ast.JoinedStr)) and _PORT_PATTERN.search(literal):
            changes.append((begin, end, 'proof_text(' + literal + ')'))
    # A joined string owns its embedded numeric expressions; never overlap edits.
    chosen = []
    for row in sorted(changes, key=lambda row: (row[0], -row[1])):
        if not chosen or row[0] >= chosen[-1][1]:
            chosen.append(row)
    for begin, end, replacement in reversed(chosen):
        encoded = encoded[:begin] + replacement.encode('utf-8') + encoded[end:]
    result = encoded.decode('utf-8')
    if chosen and PY_IMPORT not in result:
        updated = ast.parse(result)
        insertion = 0
        for node in updated.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) or isinstance(node, ast.ImportFrom) and node.module == '__future__':
                insertion = node.end_lineno
            else:
                break
        split = result.splitlines(keepends=True)
        split.insert(insertion, PY_IMPORT)
        result = ''.join(split)
    ast.parse(result)
    return result, len(chosen)


def javascript_source(source):
    if JS_MARKER in source:
        # Refresh the generated helper and unwrap only its literal calls before
        # adapting a newly discovered fixture port. This stays idempotent.
        end = source.index('\nfunction proofText(text)')
        end = source.index('\n', end + 1) + 1
        original = source
        hashbang = source.splitlines(keepends=True)[0] if source.startswith('#!') else ''
        source = hashbang + source[end:]
        source = re.sub(r'\bproofPort\((\d+)\)', r'\1', source)
        literal = r'(?:"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`)'
        source = re.sub(r'\bproofText\((' + literal + r')\)', r'\1', source)
        refreshed, count = javascript_source(source)
        return refreshed, count if refreshed != original else 0
    # Match comments first, then complete string/template literals, then numbers.
    token = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|\b\d+\b')
    count = 0
    def replace(match):
        nonlocal count
        value = match.group()
        if value.startswith(('//', '/*')):
            return value
        if value.isdecimal() and int(value) in REQUIRED_PORTS:
            count += 1
            return 'proofPort(' + value + ')'
        if value[:1] in ('"', "'", '`') and _PORT_PATTERN.search(value):
            count += 1
            return 'proofText(' + value + ')'
        return value
    result = token.sub(replace, source)
    if count and result.startswith('#!'):
        hashbang, remainder = result.split('\n', 1)
        result = hashbang + '\n' + JS_HELPER + remainder
    elif count:
        result = JS_HELPER + result
    return (result if count else source), count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Write inspected adaptations; default is read-only inventory')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--map-only', action='store_true', help='Print complete INT3 environment map without editing')
    args = parser.parse_args()
    if args.map_only:
        print(json.dumps(INT3_PORT_MAP, sort_keys=True))
        return
    paths = sorted((REPO / 'src/grant_agent').glob('proofs_*.py')) + sorted((REPO / 'scripts').glob('proofs*.mjs'))
    rows = []
    for path in paths:
        source = path.read_text(encoding='utf-8')
        proposed, replacements = python_source(source) if path.suffix == '.py' else javascript_source(source)
        if replacements:
            rows.append({'file': path.relative_to(REPO).as_posix(), 'replacements': replacements,
                         'beforeSha256': hashlib.sha256(source.encode()).hexdigest(), 'afterSha256': hashlib.sha256(proposed.encode()).hexdigest()})
            if args.apply:
                path.write_text(proposed, encoding='utf-8', newline='')
    result = {'applied': args.apply, 'files': rows, 'portMap': INT3_PORT_MAP,
              'boundary': 'Source-selected listener/URL/env/generated-code literals. No socket remapping, network calls or fixture execution. Original defaults retained when map environment is absent.'}
    if args.json:
        destination = args.json.resolve()
        if not destination.is_relative_to(REPO):
            parser.error('receipt must remain inside task workspace')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'applied': args.apply, 'files': len(rows), 'replacements': sum(row['replacements'] for row in rows)}))


if __name__ == '__main__':
    main()
