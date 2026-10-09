"""Run port admission parsers only; no socket or HTTP request to the extra range."""
import json
import os
from pathlib import Path
import sys

repo=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(repo/'src'))
from grant_agent.browser_obscura import proof_ports
from grant_agent.local_browser_authority import approved_browser_url

root=repo/'.agent_control/C2g/port-contract'
(root/'config').mkdir(parents=True,exist_ok=True)
ports=list(range(48801,48810))+list(range(48811,48820))
(root/'config/neyvia_browser_authority.json').write_text(json.dumps({'schema':'neyvia.browser-authority.v1','proofPorts':ports}),encoding='utf-8')
old=os.environ.get('NEYVIA_BROWSER_PROOF_PORTS')
os.environ['NEYVIA_BROWSER_PROOF_PORTS']=','.join(map(str,ports))
try:
    admitted=proof_ports()
    parsed=[approved_browser_url(root,'http://127.0.0.1:'+str(port)+'/control',legacy_ports=()) for port in ports]
    denied=False
    os.environ['NEYVIA_BROWSER_PROOF_PORTS']='1'
    try:proof_ports()
    except ValueError:denied=True
    checks=[{'name':'Extra explicitly owned range admitted by engine port parser','ok':admitted==set(ports)},
            {'name':'Extra owned range admitted by local browser route parser','ok':len(parsed)==len(ports)},
            {'name':'Unassigned port refused before connection','ok':denied}]
    report={'schema':'neyvia.C2g.browser-port-contract@1','checks':checks,'ports':ports,'parsedUrls':parsed,
            'boundary':'Admission parsers only; zero sockets or HTTP requests to the extra port range','networkRequests':0}
    (repo/'scripts/evidence/C2g-browser-port-contract.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if not all(row['ok'] for row in checks):raise AssertionError(checks)
    print(json.dumps(report))
finally:
    if old is None:os.environ.pop('NEYVIA_BROWSER_PROOF_PORTS',None)
    else:os.environ['NEYVIA_BROWSER_PROOF_PORTS']=old
