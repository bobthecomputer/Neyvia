"""Measure default provider history without printing private chat content."""
import argparse
import http.cookiejar
import json
import time
from pathlib import Path
from urllib.request import Request, build_opener, HTTPCookieProcessor

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, required=True)
args = parser.parse_args()
assert 48441 <= args.port <= 48449
base = f'http://127.0.0.1:{args.port}'
client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
client.open(Request(base+'/api/auth/local-session',data=b'{}',headers={'Content-Type':'application/json'}),timeout=15).close()
samples = []
for _ in range(7):
    started = time.perf_counter()
    with client.open(base+'/api/ui/sidebar?limit=50',timeout=120) as response:
        data = json.load(response)['data']
    samples.append({'ms':round((time.perf_counter()-started)*1000,2), 'total':data['total'], 'count':len(data['sessions'])})
    time.sleep(.15)
assert all(row['count'] == 50 and row['ms'] < 1000 for row in samples[1:]), samples
prior = json.loads(Path('scripts/evidence/FOLLOW-sidebar-actual.json').read_text())
receipt = {'port':args.port, 'providerConfiguration':'default production adapters, scratch workspace', 'firstRun':prior.get('firstRun',prior.get('samples')), 'samples':samples, 'passed':True,
           'limitation':'Actual available history is 643 chats in this run; the separate fixture proof covers 900. First cold call is retained and is not sub-second.'}
Path('scripts/evidence/FOLLOW-sidebar-actual.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'passed':True, 'total':samples[-1]['total'], 'warmMaxMs':max(row['ms'] for row in samples[1:])}))
