"""Compile a selected existing C7 builder into its executable CL family manual."""
import argparse
import json
from pathlib import Path
from generate_C7e_pure import build_manual, REPO
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.edge_fixture_catalog import BUILDERS
from grant_agent.manual_contracts import validate_structure


def generate(family):
    if family not in BUILDERS:
        raise ValueError('Unknown existing C7 family')

    def replace(value):
        if isinstance(value, str):
            return value.replace('pure', family)
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {replace(key): replace(item) for key, item in value.items()}
        return value

    data = replace(build_manual())
    data['chapters'] = {'campaign': next(iter(data['chapters'].values()))}
    validate_structure(data)
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError('Family CL compilation changed its contract')
    (REPO / 'manuals/cl' / (data['id'] + '.cl')).write_text(source, encoding='utf8', newline='\n')
    (REPO / 'manuals' / (data['id'] + '.manual.json')).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf8', newline='\n')
    print(json.dumps({'id': data['id'], 'clRoundtrip': True, 'family': family, 'procedure': 'run-family'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family', choices=tuple(BUILDERS), required=True)
    generate(parser.parse_args().family)
