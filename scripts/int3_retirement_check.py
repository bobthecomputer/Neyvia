"""Check every retired Python test function against the reconciled inventory."""
import argparse
import ast
import json
from pathlib import Path
import subprocess
import sys

from int3_contracts import REPO, deleted_tests


def test_names(tree, prefix=""):
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            yield from test_names(node, prefix + node.name + ".")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            yield prefix + node.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--through', choices=list('abcde'), required=True)
    args = parser.parse_args()
    import int3_contracts
    int3_contracts.SHARES = int3_contracts.SHARES[:'abcde'.index(args.through)+1]
    inventory = {row['path']: row for row in json.loads((REPO/'config/proofs/test-inventory.json').read_text())['files']}
    rows = []
    for name in sorted(deleted_tests()):
        if not name.endswith('.py'):
            continue
        result = subprocess.run(['git','show','HEAD:'+name],cwd=REPO,capture_output=True,text=True,encoding='utf-8')
        if result.returncode:
            continue  # Already retired in an earlier checked merge.
        functions = set(test_names(ast.parse(result.stdout)))
        known = {case['name'] for case in inventory[name]['cases']}
        rows.append({'path':name,'functions':len(functions),'unmapped':sorted(functions-known)})
    receipt = {'through':args.through,'files':rows,'ok':all(not row['unmapped'] for row in rows)}
    destination = REPO/'scripts/evidence/int3'/('retirement-functions-'+args.through+'.json')
    destination.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'through':args.through,'files':len(rows),'ok':receipt['ok'],
                      'unmapped': [row for row in rows if row['unmapped']]}))
    return int(not receipt['ok'])


if __name__ == '__main__':
    sys.exit(main())
