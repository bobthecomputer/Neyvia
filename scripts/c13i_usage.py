"""Read only this task's orchestration token counter; no unrelated transcript output."""
from pathlib import Path
import json
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.taste_fewshot import save


def main():
    roots=[Path.home()/'.codex/sessions/2026/10/05',Path.home()/'.codex/sessions/2026/10/06']
    paths=sorted([p for root in roots if root.exists() for p in root.glob('*.jsonl')],key=lambda p:p.stat().st_mtime,reverse=True)[:25]
    # Tool-free provider calls create newer session files. Retain the already
    # identified exact root log rather than losing it from the bounded window.
    receipt_path=REPO/'proof/r12/orchestration-usage.json'
    if receipt_path.exists():
        prior=json.loads(receipt_path.read_bytes())
        known=Path(prior['sourcePath'])
        base=(Path.home()/'.codex/sessions').resolve()
        if known.is_file() and known.resolve().is_relative_to(base) and prior['session'] in known.name:
            paths=[known]+[p for p in paths if p!=known]
    needle='Round 11 failed its main goal'
    for path in paths:
        own=False;usage=None;meta=None;timestamp=None
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                # No transcript text is printed or retained in the receipt.
                if needle in line:own=True
                if 'session_meta' in line or 'token_count' in line:
                    try:event=json.loads(line)
                    except ValueError:continue
                    if event.get('type')=='session_meta':meta=event.get('payload',{})
                    payload=event.get('payload',{})
                    if payload.get('type')=='token_count' and payload.get('info'):
                        usage=payload['info'].get('total_token_usage');timestamp=event.get('timestamp')
        if own and usage:
            receipt={'schema':'neyvia.own-orchestration-usage.v1','session':meta.get('id') if meta else None,
                     'sourcePath':str(path),'timestamp':timestamp,'usage':usage,
                     'scope':'Last observed cumulative counter for this root session; includes repeated input/cache tokens. Current unfinished turn may not be flushed.'}
            save(REPO/'proof/r12/orchestration-usage.json',receipt)
            print(json.dumps(receipt));return
    print(json.dumps({'available':False,'reason':'No token counter for this exact task found in bounded recent local session logs.'}))


if __name__=='__main__':main()
