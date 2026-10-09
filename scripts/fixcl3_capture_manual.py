"""Add exact HTTP-byte and native-PNG procedures to canonical existing manuals."""
from pathlib import Path
import json
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.cl.manuals import _source_lines, cl_to_manual

ROWS={'tools-depth':[('web.fetch','fetch-owned-http-body','Fetch the exact HTTP response and verify retained original bytes and parsed document')],
      'browser':[('neyvia.browser.capture','capture-owned-native-page','Capture the existing Obscura page and verify actual PNG bytes, engine identity and fresh DOM')]}

def main():
    for layer, rows in ROWS.items():
        path=REPO/'manuals'/(layer+'.manual.json'); clpath=REPO/'manuals/cl'/(layer+'.cl')
        data=json.loads(path.read_bytes()); text=clpath.read_text(encoding='utf-8')
        if cl_to_manual(text)!=data: raise ValueError(layer+' canonical manual differs')
        metadata=json.loads(text.splitlines()[2][len('-- @manual '):])['tool_metadata']
        for tool,procedure,goal in rows:
            key,chapter,action_key,action=next((key,chapter,ak,a) for key,chapter in data['chapters'].items()
                for ak,a in chapter['actions'].items() if a['tool']==tool)
            if procedure in chapter['procedures']: continue
            inputs=data['schemas'][action['schema']]
            row=json.loads(json.dumps({'goal':goal,'inputs':inputs,'steps':[{'action':action_key,
                'args':{name:{'$input':name} for name in inputs['properties']},'save':'observed'}]},sort_keys=True))
            chapter['procedures'][procedure]=row
            additions=['-- @record '+json.dumps({'chapter':key,'section':'procedures','key':procedure,'data':row},sort_keys=True,separators=(',',':'))]
            additions.extend(_source_lines('procedures',procedure,row,chapter,data['schemas'],layer,metadata,version='1.1'))
            start=text.index('L '+layer+'.'+key+' v1 --'); end=text.find('\nL '+layer+'.',start+1)
            if end<0: end=len(text)
            text=text[:end].rstrip('\n')+'\n'+'\n'.join(additions)+'\n'+text[end:].lstrip('\n')
        if cl_to_manual(text)!=data: raise ValueError(layer+' appended records do not roundtrip')
        for target,content in ((path,json.dumps(data,indent=2,ensure_ascii=False)+'\n'),(clpath,text)):
            ending='\r\n' if b'\r\n' in target.read_bytes() else '\n'
            target.write_bytes(content.replace('\n',ending).encode())
    print(json.dumps({'ok':True,'layers':list(ROWS)}))

if __name__=='__main__': main()
