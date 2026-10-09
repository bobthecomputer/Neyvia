"""Admit the integrator's explicit ports in the authored C7 campaign schema."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.proof_ports import C7_PORT_SCHEMA

changed = []
for source in sorted((ROOT / 'manuals/cl').glob('*.cl')):
    text = source.read_text(encoding='utf-8')
    if 'neyvia.verify.edges' not in text:
        continue
    data = cl_to_manual(text)
    touched = False
    for chapter in data['chapters'].values():
        for action in chapter['actions'].values():
            if action['tool'] == 'neyvia.verify.edges':
                schema = data['schemas'][action['schema']]
                if schema['properties']['port'] != C7_PORT_SCHEMA:
                    schema['properties']['port'] = C7_PORT_SCHEMA
                    touched = True
    if touched:
        header = next(line for line in text.splitlines() if line.startswith('-- @manual '))
        metadata = json.loads(header[len('-- @manual '):]).get('tool_metadata', {})
        source.write_text(manual_to_cl(data, metadata), encoding='utf-8', newline='\n')
        changed.append(source.name)
print(json.dumps({'updated': changed}))
