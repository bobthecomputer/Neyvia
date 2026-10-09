"""neyvia app new/describe/state/action/build/verify/serve, explicit ports only."""
from pathlib import Path
import argparse
import json
import os
import sys
os.environ['PYTHONDONTWRITEBYTECODE']='1'
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from grant_agent import app_sdk

def main():
    parser=argparse.ArgumentParser(prog='neyvia app');sub=parser.add_subparsers(dest='operation',required=True)
    new=sub.add_parser('new');new.add_argument('kind',choices=sorted(app_sdk.KINDS));new.add_argument('--path',required=True);new.add_argument('--name',required=True)
    for name in ('describe','state','action','build','verify','serve','preview'):
        command=sub.add_parser(name);command.add_argument('--project',required=True)
        if name in {'action','verify'}:command.add_argument('--url',required=True)
        if name=='action':command.add_argument('--name',required=True);command.add_argument('--arguments',type=json.loads,default={})
        if name=='build':command.add_argument('--platform',choices=['web','pwa','desktop','expo'],default='web')
        if name=='verify':command.add_argument('--cl-source',dest='clSource');command.add_argument('--native',type=json.loads)
        if name in {'serve','preview'}:command.add_argument('--port',required=True,type=int)
    args=vars(parser.parse_args());operation=args.pop('operation');root=Path.cwd()
    if operation in {'serve','preview'}:
        from grant_agent.app_sdk_server import serve
        serve(app_sdk.confined(root,args['project']),args['port']);return
    try:result=getattr(app_sdk,operation+'_app')(root,args)
    except Exception as error:result={'ok':False,'status':'refused','error':str(error)}
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result.get('ok') else 1

if __name__=='__main__':raise SystemExit(main())
