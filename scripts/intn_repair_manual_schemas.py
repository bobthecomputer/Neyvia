"""Repair the exact manual declaration failures observed by INTN's startup run."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.neyvia_manuals import validate
from build_grounded_manuals import refresh_schemas


def main():
    registry = NativeToolRegistry(ROOT / '.agent_control/INTN/manual-schema')
    selected = {'autopilot': [('fixcl4-real','verify-autopilot-start')],
        'conductor': [('fixcl4-real','verify-conductor-plan')],
        'local-host': [('host','codex-plugins-call'),('host','host-launch'),('host','host-launch_file')],
        'browser': [], 'proofs': [], 'local-browser-sdk': []}
    prepared, receipts = [], []
    for name, procedures in selected.items():
        path = ROOT / 'manuals/cl' / (name + '.cl')
        original = path.read_text(encoding='utf-8')
        header = json.loads(next(line[len('-- @manual '):] for line in original.splitlines() if line.startswith('-- @manual ')))
        data = cl_to_manual(original)
        changes = []
        if name in {'autopilot','conductor','local-host'}:
            procedures = [(chapter, procedure) for chapter, content in data['chapters'].items()
                          for procedure in content['procedures']]
        for chapter, procedure in procedures:
            row = data['chapters'][chapter]['procedures'][procedure]
            # These verification procedures forward every argument explicitly.
            # Require the caller's values instead of inventing an app goal,
            # plugin payload, runtime budget or process command arguments.
            required = row['inputs'].setdefault('required', [])
            for step in row['steps']:
                for value in step.get('args', {}).values():
                    if isinstance(value, dict) and set(value) == {'$input'}:
                        key = value['$input']
                        if key not in required and 'default' not in row['inputs']['properties'][key]:
                            required.append(key)
                            changes.append({'procedure':chapter+'/'+procedure,'requiredInput':key})
        if name in {'browser','proofs','local-browser-sdk'}:
            refresh_schemas(data, registry)
        if name == 'local-browser-sdk':
            data['chapters']['evidence']['procedures']['browser-decide']['inputs']['properties']['context'] = (
                registry.describe('neyvia.browser.decide')['inputSchema']['properties']['context'])
            changes.append({'procedure':'evidence/browser-decide','inputSchema':'context',
                            'source':'live neyvia.browser.decide'})
        print('Validate ' + name, flush=True)
        grounded = validate(data, registry)
        output = manual_to_cl(data, tool_metadata=header.get('tool_metadata', {}))
        prepared.append((path, output))
        receipts.append({'manual':name,'beforeSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'afterSha256':hashlib.sha256(output.encode()).hexdigest(),'declarationChanges':changes,
            'grounded':grounded['grounded']})
    # No partial rewrite if any selected manual still fails live grounding.
    for path, output in prepared:
        path.write_text(output, encoding='utf-8', newline='\n')
    target = Path('D:/NeyviaRuns/INTN/manual-schema-repairs.json')
    target.write_text(json.dumps({'ok':True,'manuals':receipts},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'ok':True,'manuals':len(receipts),'receipt':str(target)}))


if __name__ == '__main__':
    main()
