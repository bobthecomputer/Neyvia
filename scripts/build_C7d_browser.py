"""Offline source-bound native probe build; never starts the application."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
def main():
    from grant_agent.proof_contracts import source_digest
    sources=['scripts/build_C7d_browser.py','scripts/browser-probe/Cargo.toml','scripts/browser-probe/Cargo.lock','scripts/browser-probe/src/main.rs','src-tauri/src/browser_runtime.rs','src-tauri/src/browser_projection.js']
    before={p:source_digest(REPO/p) for p in sources}
    cache=REPO/'.agent_control/C7d/native-build';cache.mkdir(parents=True,exist_ok=True)
    with (cache/'owned-build.log').open('wb') as log:
        completed=subprocess.run([r'C:\Users\user\.cargo\bin\cargo.exe','build','--offline','--manifest-path',str(REPO/'scripts/browser-probe/Cargo.toml'),'--target-dir',str(cache)],cwd=REPO,env={**os.environ,'CARGO_INCREMENTAL':'0'},stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW,timeout=600)
    if completed.returncode or before!={p:source_digest(REPO/p) for p in sources}: raise RuntimeError('Offline native build failed or source changed')
    source=cache/'debug/browser-proof.exe';target=REPO/'.agent_control/C7d/browser-proof.exe'
    shutil.copyfile(source,target)
    sha=hashlib.sha256(target.read_bytes()).hexdigest()
    if sha!=hashlib.sha256(source.read_bytes()).hexdigest(): raise ValueError('Native build copy differs')
    receipt={'schema':'neyvia.c7d-native-build.v1','ok':True,'offline':True,'downloads':0,'sourceBindings':before,'exe':str(target),'exeSha256':sha,'bytes':target.stat().st_size,'boundary':'Built production browser runtime in task-only probe; no app startup, credential inspection, supervisor or visible window'}
    (REPO/'scripts/evidence/C7d-native-build.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'ok':True,'sha256':sha,'bytes':target.stat().st_size}))
if __name__=='__main__': main()
