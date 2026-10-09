"""Run the compiled taste-harness CL contracts through the existing CL-Skill evaluator."""
from pathlib import Path
import argparse
import json
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.cl_skill import Output,_parse_skill,run_checks,receipt_lines
from grant_agent.taste_contracts import Contracts
class ContractOutput(Output):
    def __init__(self,manual,out):
        super().__init__([manual],out_dir=out)
        self.contracts=Contracts(out/'scratch')
    def calls(self):
        return {**super().calls(),'taste.observe':self.contracts.observe}
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',required=True)
    parser.add_argument('--manual',type=Path,default=REPO/'manuals/cl/taste-harness.cl')
    parser.add_argument('--out',type=Path,default=REPO/'scripts/evidence/C13g-contracts/check')
    parser.add_argument('--only', help='Comma-separated authored check names for a scoped procedure')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    skill=_parse_skill(args.manual);output=ContractOutput(args.manual,args.out)
    result=run_checks(skill,output,only=set(args.only.split(',')) if args.only else None)
    result['observations']=output.contracts.cache
    result['manualSha256']=__import__('hashlib').sha256(args.manual.read_bytes()).hexdigest()
    (args.out/'report.json').write_text(json.dumps(result,indent=1),encoding='utf-8')
    print(receipt_lines(skill,result))
    return 0 if result['status']=='ok' else 1
if __name__=='__main__':raise SystemExit(main())
