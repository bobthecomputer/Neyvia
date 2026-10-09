"""Align authored proof interfaces with the complete integrated dispatcher."""
import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))


def main():
    from grant_agent.proof_verifier import ADAPTERS, RUNNERS
    from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
    areas = sorted(set(ADAPTERS)|set(RUNNERS))
    path = ROOT/'src/grant_agent/neyvia_manuals.py'
    source = path.read_text(encoding='utf-8')
    lines = source.splitlines(keepends=True)
    changed = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith(('("verify",', "('verify',")):
            row = ast.literal_eval(line.strip().removesuffix(','))
            row[2]['areas']['items']['enum'] = areas
            lines[index] = '    ' + repr(row) + ',\n'
            changed = True
    assert changed, 'Host verify registration missing'
    path.write_text(''.join(lines), encoding='utf-8', newline='\n')
    path = ROOT/'manuals/cl/proofs.cl'
    source = path.read_text(encoding='utf-8')
    header = json.loads(next(line[11:] for line in source.splitlines() if line.startswith('-- @manual ')))
    manual = cl_to_manual(source)
    manual['schemas']['neyvia.verify']['properties']['areas']['items']['enum'] = areas
    text = manual_to_cl(manual, tool_metadata=header['tool_metadata'])
    assert cl_to_manual(text) == manual
    path.write_text(text, encoding='utf-8', newline='\n')
    from grant_agent.neyvia_evolver import DEFINITIONS
    definition = next(row for row in DEFINITIONS if row[0] == 'evolver.run')
    path = ROOT/'manuals/cl/hill-climb.cl'
    source = path.read_text(encoding='utf-8')
    header = json.loads(next(line[11:] for line in source.splitlines() if line.startswith('-- @manual ')))
    manual = cl_to_manual(source)
    schema = manual['schemas']['neyvia.evolver.run']
    schema['properties'] = definition[2]
    schema['required'] = definition[3]
    text = manual_to_cl(manual, tool_metadata=header['tool_metadata'])
    assert cl_to_manual(text) == manual
    path.write_text(text, encoding='utf-8', newline='\n')
    report = {'areas':areas, 'count':len(areas), 'hostSchemaAndAuthoredCLAligned':True,
              'settingsLegacyExecutableEntriesRetained': True,
              'evolverRunDomains': definition[2]['domain']['enum'],
              'existingChapterChangeReview': 'C orchestration guidance changed only through mojibake; retained current CL guidance.'}
    (ROOT/'scripts/evidence/int3/interface-alignment.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'areas':len(areas), 'aligned':True}))


if __name__ == '__main__':
    main()
