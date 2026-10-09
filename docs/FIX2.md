# FIX2 release blockers

The five requested audit blockers have real production-call receipts in
`scripts/evidence/FIX2.json`. Each original blocker has a separate commit.
Browser workspace revisions are integers; page observation revisions remain strings.
LAYA is attached through its shipped client, and the cascade accepted a real French
decision above its unchanged 0.95 gate. Service-down decisions do not queue capture.
Fresh SDK apps bundle the A2 manifest, kit, model and credits; web/PWA controls use
the kit. The checkout-local pinned Windows driver is ready. Local-only search uses
bounded in-process matching before any child launch.

For another checkout, run the driver setup in `tools/cua-driver-win/README.md`.
Start the existing CPU LAYA service and set the backend's explicit endpoint as in
`docs/LAYA_SETUP.md`. Its existing compatible environment is necessary; the supplied
system Python's Transformers version cannot load that service. The proof services
are stopped after verification. Their ports were 48683–48686; HTTP replay used 48689.

Node's existing resolver needs a checkout-local venv. This run created one from the
supplied Python, with no dependency installation or download:

```powershell
& 'C:\Users\example\AppData\Local\Programs\Python\Python313\python.exe' -m venv --system-site-packages --without-pip .venv
node --test tests/*.mjs
```

Full `neyvia verify` is **not green**: 32/40 areas pass, 9 failures and 207 blocked
manual entries remain. The retained `fix2-verifier.json` records the source-bound
run. Blockers include missing system-Python Pillow, missing tokenizer cache (its
external fetch was refused), missing task-local Syncthing, Windows internal
socket-pair allocation outside the assigned port range, remote proof-port admission,
and the native-runtime manual procedure. Those broader areas were not repaired by
this five-item scope. The four selected affected-area checks all pass, but their
verifier still exits 1 because the full coverage gate is false; `--allow-frontier`
does not hide that failure. Browser completion judgement remains 1/2 with escalation,
and this work makes no general model-quality or whole-release readiness claim.

To repeat the bounded full check with its assigned fixture ports:

```powershell
$env:NEYVIA_PYTHON='C:\Users\example\AppData\Local\Programs\Python\Python313\python.exe'
$env:NEYVIA_SYSTEM_PYTHON=$env:NEYVIA_PYTHON
$guardPath=Join-Path (Get-Location) '.agent_control/FIX2/guard'
New-Item -ItemType Directory -Path $guardPath -Force | Out-Null
$scriptPath=Join-Path (Get-Location) 'scripts'
('import sys; sys.path.insert(0, ' + (ConvertTo-Json $scriptPath -Compress) + '); import fix2_scope') | Set-Content (Join-Path $guardPath 'sitecustomize.py')
$env:PYTHONPATH=$guardPath+';'+(Join-Path (Get-Location) 'src')
$env:NEYVIA_FIX2_SCOPE='1'
$env:NEYVIA_PROOF_BUILD_ROOT=Join-Path (Get-Location) '.agent_control/FIX2/build'
node scripts/fluxio-cli.mjs verify --root . --fixture-ports 48681,48682,48683,48684,48685,48686,48687,48688,48689 --output scripts/evidence/fix2-verifier.json
```

The original run additionally installed `scripts/fix2_scope.py` via the owned
scratch `sitecustomize.py`: it refused protected-tree access and every unassigned
socket before the operation. `verify_fix2_http.py` uses the production handler and
ephemeral in-memory owner authentication; its first attempt used the wrong UI-tool
route for `workspace.search`, then the actual backend/native-tool route passed.

Publication note: local account paths and network identifiers in this document are neutral examples.
