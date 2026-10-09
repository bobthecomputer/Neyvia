"""Retained Apple bytes and a fresh authenticated rendered mode journey."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import uuid


def self_check(scratch):
    from .contract_gate import wants
    from .edge_fixture_mobile import run_apple_artifacts, run_apple_preview
    from .proof_verifier import REPO
    # The retained real bundles are independent byte inputs, never copied back.
    retained=Path(os.environ.get('NEYVIA_GATE_APPLE_PROJECT') or REPO.parent/'scroll-study')
    # Public portable compiler bytes are named by the retained build receipt.
    # User homes remain isolated; no global tool installation/config is touched.
    from .apple_targets import latest
    retained_receipt=latest(retained,'ios')
    linker=Path(retained_receipt.get('linker') or '')
    if not (linker.parent/'clang.exe').is_file():
        raise ValueError('Retained Apple receipt has no available public LLVM compiler')
    os.environ['NEYVIA_WINDOWS_IOS_LLVM_BIN']=str(linker.parent)
    scratch=Path(scratch);cases=[]
    for identity in ('mobile-studio.apple-artifact-integrity','mobile-studio.apple-preview-rendered'):
        if not wants(identity):continue
        root=scratch/uuid.uuid4().hex;root.mkdir(parents=True)
        try:
            if identity.endswith('artifact-integrity'):
                rows=run_apple_artifacts(root,retained)
                assert rows and all(row['status']=='passed' for row in rows)
                observed={'rows':rows,'retainedProject':str(retained),'originalsPreserved':True}
            else:
                project=root/'scroll-study';project.mkdir()
                for name in ('www','package.json','neyvia.app.json','host-contract.json','manual.cl'):
                    source=retained/name
                    if source.is_dir():shutil.copytree(source,project/name)
                    elif source.is_file():shutil.copy2(source,project/name)
                assert (project/'www/index.html').is_file(), 'Real retained Scroll Study web export is missing'
                observed=run_apple_preview(project,root/'preview')
                assert observed['status']=='passed'
            cases.append({'id':identity,'contracts':[identity],'ok':True,'observed':observed})
        except Exception as error:
            import traceback
            cases.append({'id':identity,'contracts':[identity],'ok':False,'error':type(error).__name__+': '+str(error),'logs':str(root),'traceback':traceback.format_exc()})
    return {'ok':bool(cases) and all(case['ok'] for case in cases),'cases':cases,
            'contracts':[case['id'] for case in cases if case['ok']]}
