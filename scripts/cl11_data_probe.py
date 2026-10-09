"""Actual stdio Notes content must preserve ordinary business identifiers."""
from pathlib import Path
import json
import sys
import uuid
import argparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from prove_cl import Client
from grant_agent.neyvia_notes_tools import call_notes

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--after', action='store_true')
args = parser.parse_args()
root = REPO/'.agent_control/cl11/data-probe'/uuid.uuid4().hex
root.mkdir(parents=True)
call_notes(root,'folder',{'folder':str(root/'notes')},source='ui')
call_notes(root,'write',{'path':'invoice.md','body':'Invoice id=42\nKeep this identifier intact.'},source='ui')
client = Client(root)
try:
    client.request('initialize',{'protocolVersion':'2024-11-05','clientInfo':{'name':'CL11-data-proof','version':'1.1'},'capabilities':{}})
    result = client.act('notes.read(path="invoice.md")')
    preserved = 'Invoice id=42' in result['text']
    path = REPO/('scripts/evidence/CL11-data-after.json' if args.after else 'scripts/evidence/CL11-data-before.json')
    path.write_text(json.dumps({'preservedBusinessIdentifier':preserved,'result':result,'transcript':client.rows},indent=2),
                    encoding='utf-8',newline='\n')
    print(json.dumps({'preservedBusinessIdentifier':preserved,'receipt':str(path)}))
    if args.after and not preserved: raise SystemExit(1)
finally:
    client.close()
