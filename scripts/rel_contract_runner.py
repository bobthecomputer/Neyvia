"""Run bounded, authored CL procedure cases through this checkout's real MCP adapter."""
import argparse
import json
from pathlib import Path
from rel_harness import server

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('cases', type=Path)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
receipts = []
for case in json.loads(a.cases.read_text(encoding='utf-8-sig')):
    # CL goals belong to a conversation; independent cases need independent
    # authenticated conversations so earlier goals cannot constrain later ones.
    adapter = server()
    adapter.tools()
    result = adapter.call('tools_call', {'tool':'neyvia.cl','arguments':{'lines':case['lines']}})
    text = '\n'.join(block['text'] for block in result.get('content',[]) if block.get('type') == 'text')
    passed = bool(result.get('isError')) == bool(case.get('expectError')) and all(mark in text for mark in case.get('requires',[]))
    receipts.append({'id':case['id'],'passed':passed,'result':result,'lines':case['lines']})
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(receipts,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'id':case['id'],'passed':passed,'tail':text[-220:]}),flush=True)
    if not passed: raise SystemExit(1)
