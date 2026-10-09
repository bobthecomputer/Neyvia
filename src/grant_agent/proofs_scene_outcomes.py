"""Shared judge and rendered-video outcome owners, with fresh receipts."""
from __future__ import annotations

import importlib.util
import json
import os
from unittest.mock import patch
from pathlib import Path
import uuid

REPO=Path(__file__).resolve().parents[2]


def sdk(root):
    import sys
    sys.path.insert(0,str(REPO/'scripts'))
    spec=importlib.util.spec_from_file_location('gate_core_sdk',REPO/'scripts/core_sdk_seam_proof.py')
    owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
    from .proof_ports import proof_port
    owner.RUN=root;owner.PORT=proof_port(48461)
    local=owner.in_process()
    import placement_shots as shots
    original_env=shots.isolated_env
    def isolated_env():
        env=original_env()
        # This proof needs source imports, not the shared tour bytecode cache.
        # Disable cache writes and use the existing source-side read cache.
        env.pop('PYTHONPYCACHEPREFIX',None)
        env['PYTHONDONTWRITEBYTECODE']='1'
        return env
    with patch.object(shots,'isolated_env',isolated_env):remote=owner.over_http()
    refusal=remote.get('refusal') or {}
    checks={'inProcessFindings':local['findings']==sorted(owner.EXPECTED),
            'inProcessRefusals':all(v!='ACCEPTED' for v in local['refused'].values()),
            'sdkHttpFindings':remote.get('findings')==sorted(owner.EXPECTED),
            'sameSceneBinding':remote.get('sceneSha256')==local['sceneSha256'],
            'sdkHttpRefusal':refusal.get('accepted') is False and 'Unknown predicate operator' in str(refusal.get('reason')),
            'codeTextRemainsData':('code-as-data','feed') not in [tuple(p) for p in remote.get('findings') or []]}
    assert all(checks.values()), json.dumps({'checks':checks,'remote':remote})
    return {'checks':checks,'local':local,'sdk':remote,'boundary':'Actual Python SDK over authenticated owned HTTP into the shared scene judge'}


def video(root):
    from .video_contracts import proof
    # Home isolation must not trigger a fresh renderer download. Bind the
    # installed public tool bytes explicitly; preserve isolated browser state.
    resource_home=Path(os.environ['NEYVIA_GATE_RESOURCE_HOME'])
    binaries=sorted((resource_home/'.cache/puppeteer').glob('chrome-headless-shell/*/chrome-headless-shell-win64/chrome-headless-shell.exe'))
    if not binaries:binaries=sorted((resource_home/'.cache/hyperframes/chrome').glob('chrome-headless-shell/*/chrome-headless-shell-win64/chrome-headless-shell.exe'))
    assert binaries,'Installed HyperFrames headless renderer is unavailable'
    with patch.dict(os.environ,{'NEYVIA_HEADLESS_SHELL':str(binaries[-1]),'HYPERFRAMES_BROWSER_PATH':str(binaries[-1])}):result=proof(root)
    assert result['passed'],json.dumps(result)
    return result


def self_check(scratch):
    from .contract_gate import wants
    scratch=Path(scratch);cases=[]
    for identity,action in [('core.sdk-seam',sdk),('video.outcome-contracts',video)]:
        if not wants(identity):continue
        root=scratch/uuid.uuid4().hex;root.mkdir(parents=True)
        try: cases.append({'id':identity,'contracts':[identity],'ok':True,'observed':action(root)})
        except Exception as error:
            import traceback
            cases.append({'id':identity,'contracts':[identity],'ok':False,'error':type(error).__name__+': '+str(error),'traceback':traceback.format_exc()})
    return {'ok':bool(cases) and all(case['ok'] for case in cases),'cases':cases,
            'contracts':[case['id'] for case in cases if case['ok']]}
