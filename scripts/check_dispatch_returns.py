"""Check handler imports in guarded name dispatches have executable calls."""
from __future__ import annotations
import argparse
import ast
import json
from pathlib import Path

HANDLERS = {'call', 'handle', 'handle_command', 'serve_http', 'respond', 'respond_command', 'dispatch', 'run_command',
            'forward_command', 'forward_connected_command', 'forward_desktop'}

def handler(name):
    return name in HANDLERS or name.startswith(('call_', 'handle_', 'dispatch_'))
def guarded(test):
    return any((isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'name' and node.func.attr == 'startswith')
               or (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
                   and node.left.id == 'normalized' and any(isinstance(op, ast.In) for op in node.ops))
               for node in ast.walk(test))
def inspect(path):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    rows = []
    for branch in ast.walk(tree):
        if not isinstance(branch, ast.If) or not guarded(branch.test):
            continue
        nodes = [child for statement in branch.body for child in ast.walk(statement)]
        calls = [node.func for node in nodes if isinstance(node, ast.Call)]
        for node in nodes:
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                if not handler(alias.name):
                    continue
                name = alias.asname or alias.name
                invoked = any(isinstance(call, ast.Name) and call.id == name for call in calls)
                rows.append({'file':path.as_posix(), 'line':branch.lineno, 'handler':name, 'called':invoked})
    return rows

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    rows = [row for path in Path('src/grant_agent').rglob('*.py') for row in inspect(path)]
    result = {'checked':len(rows), 'missing':[row for row in rows if not row['called']], 'dispatches':rows}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'checked':result['checked'], 'missing':result['missing']}, indent=2))
    return int(bool(result['missing']))

if __name__ == '__main__':
    raise SystemExit(main())
