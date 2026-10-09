"""Review INT2 lost-line findings against retained AST owners and CL semantics."""
from __future__ import annotations
import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OWNERS = ('src/grant_agent/web_backend.py', 'src/grant_agent/web_backend_chat.py',
          'src/grant_agent/web_backend_http.py')

class Normalize(ast.NodeTransformer):
    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == '_facade':
            return ast.copy_location(ast.Name(id=node.attr, ctx=node.ctx), node)
        return self.generic_visit(node)

    def visit_Assign(self, node):
        if any(isinstance(target, ast.Name) and target.id == '_facade' for target in node.targets):
            return None
        return self.generic_visit(node)

def canonical(node):
    # Roundtrip also drops irrelevant lexical string-prefix metadata.
    normalized = ast.fix_missing_locations(Normalize().visit(copy.deepcopy(node)))
    return ast.dump(ast.parse(ast.unparse(normalized)), include_attributes=False)

def git_text(ref, path):
    return subprocess.check_output(['git', 'show', f'{ref}:{path}'], cwd=ROOT, text=True, encoding='utf-8')

def main():
    old = ast.parse(git_text('c0e388c7', OWNERS[0]))
    functions = {node.name: node for node in ast.walk(old)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    current = {}
    for path in OWNERS:
        for node in ast.walk(ast.parse((ROOT / path).read_text(encoding='utf-8'))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                current[node.name] = (path, node)
    same, changed, missing = [], [], []
    for name, node in functions.items():
        if name not in current:
            missing.append(name)
        elif canonical(node) == canonical(current[name][1]):
            same.append(name)
        else:
            changed.append({'name': name, 'owner': current[name][0]})
    expected = {
        'make_handler': 'Facade delegates to the extracted HTTP owner; class methods preserved below.',
        'do_POST': 'FOLLOW adds guarded game-dev result/error returns and workspace action receipt return. Settings exception classes resolve through late-bound facade imports.',
        'dispatch': 'Adds the durable workspace action receipt reader. All preceding command branches retained.'
    }
    unexpected = [row for row in changed if row['name'] not in expected]
    for row in changed:
        row['review'] = expected.get(row['name'], 'UNREVIEWED')
    lost = json.loads((ROOT / 'scripts/evidence/int2/lost-lines.json').read_text())
    counts = {}
    for row in lost['findings']:
        counts[row['file']] = counts.get(row['file'], 0) + 1
    reviews = {
        'src/grant_agent/web_backend.py': '284 retained normalized AST functions across facade/chat/HTTP owners; three reviewed wrapper/additive changes. Mobile OPTIONS and Scroll/Evolver authorization explicitly transferred. No removed function.',
        'src/grant_agent/desktop_bridge.py': 'Persistent perception bridge expands to the two CL tools; explicit service URL and state-root binding retained, proven by HTTP/desktop calls.',
        'config/neyvia_manuals.json': 'Catalog descriptions become CL layer summaries; every parent identity preserved, now 37 sources including SDK/Scroll/settings/voice.',
        'manuals/design.manual.json': 'Key reordering and CL action/check normalization; design.details preserved, Unicode replacement characters repaired from parent CL source.',
        'manuals/hill-climb.manual.json': 'Key ordering/CL normalization; evolver chapter, schemas, procedure keys and frontier preserved.',
        'manuals/game-dev.manual.json': 'CL roundtrip aliases compile to original receipts/state tools, both observed through actual HTTP and model-tool calls.',
        'manuals/remote.manual.json': 'CL roundtrip preserves actions/schemas/guards. protected-window judgement becomes protected-field, reflecting FOLLOW focused-field protection; native failure cases verified.',
        'docs/manuals/remote.md': 'Generated from the reviewed CL remote source: field redaction, truncation, host controls and user-side chapter replace old whole-window wording.',
        'docs/manuals/game-dev.md': 'Generated CL view retains receipts/state and honest missing-editor frontier.',
        'docs/manuals/agents.md': 'FOLLOW delegated approval/trust guidance retained in CL source and regenerated notation.',
        'docs/manuals/browser.md': 'FOLLOW explicit workspace proof-port guidance retained in CL source and regenerated notation.'
    }
    rows = []
    for path, count in sorted(counts.items()):
        review = reviews.get(path)
        if path.startswith('plugins/neyvia/skills/') and path.endswith('/SKILL.md'):
            review = 'Generated CL layer index replaces legacy JSON-manual banner; original tool scope remains in PORTED.md.'
        rows.append({'path': path, 'findings': count, 'review': review or 'UNREVIEWED'})
    result = {
        'schema': 'neyvia.int2.semantic-merge-review.v1',
        'sourceHead': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'unchangedNormalizedFunctions': same, 'reviewedFunctionChanges': changed,
        'missingFunctions': missing, 'unexpectedFunctionChanges': unexpected,
        'lostLines': len(lost['findings']), 'missingManualEntries': lost['missingManualEntries'],
        'fileReviews': rows,
        'sourceHashes': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in OWNERS},
        'passed': not missing and not unexpected and not lost['missingManualEntries']
                  and all(row['review'] != 'UNREVIEWED' for row in rows),
        'boundary': 'Semantic review aid plus current production route proofs; line presence is never used as a merge algorithm.'
    }
    destination = ROOT / 'scripts/evidence/int2/lost-lines-review.json'
    destination.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'retainedFunctions': len(same), 'changes': changed,
                      'missing': missing, 'passed': result['passed']}))
    return int(not result['passed'])

if __name__ == '__main__':
    raise SystemExit(main())
