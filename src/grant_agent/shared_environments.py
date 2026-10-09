"""Pinned isolated environments with a shared uv cache and durable execution receipts."""
from __future__ import annotations
import hashlib, json, os, platform, subprocess, time, shutil, re, uuid
from pathlib import Path
from .durability import atomic_write_json
from .harness_jobs import _exclusive_job_lock
from .subprocess_utils import hidden_windows_subprocess_kwargs

def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()

class SharedEnvironmentStore:
    def __init__(self, root, uv=None):
        self.root=Path(root).resolve()
        self.base=self.root/".agent_control"/"environments"
        self.base.mkdir(parents=True,exist_ok=True)
        self.uv=str(uv or shutil.which("uv") or "")
        self.cache=self.root/".agent_control"/"environment_download_cache"

    def _command(self, command, timeout):
        return subprocess.run(command,cwd=self.root,capture_output=True,text=True,
            timeout=max(1,min(int(timeout),300)),**hidden_windows_subprocess_kwargs())

    def _load(self, path):
        path=Path(path).resolve()
        path.relative_to(self.base)
        value=json.loads(path.read_text(encoding="utf-8"))
        if value.get("integritySha256") != _hash({k:v for k,v in value.items() if k!="integritySha256"}) or value.get("ready") is not True:
            raise ValueError("Environment manifest integrity failed")
        expected=path.parent/"venv"/("Scripts/python.exe" if os.name=="nt" else "bin/python")
        if Path(value["manifestPath"]).resolve()!=path or Path(value["python"]).absolute()!=expected.absolute() or not expected.is_file():
            raise ValueError("Environment interpreter or manifest identity mismatch")
        if hashlib.sha256((path.parent/"requirements.lock").read_bytes()).hexdigest()!=value["lockSha256"]:
            raise ValueError("Pinned environment lock changed")
        return value

    def create(self, environment_id, *, lock_path, interpreter, timeout=120):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}",environment_id):
            raise ValueError("Unsafe environment identity")
        lock=Path(lock_path).resolve()
        lock.relative_to(self.root)
        data=lock.read_bytes()
        probe=self._command([str(interpreter),"-c","import json,sys; print(json.dumps({'executable':sys.executable,'version':sys.version,'implementation':sys.implementation.name}))"],10)
        if probe.returncode: raise ValueError("Interpreter identity probe failed")
        identity=json.loads(probe.stdout)
        lock_hash=hashlib.sha256(data).hexdigest()
        fp=_hash({"lockSha256":lock_hash,"interpreter":identity,"platform":platform.platform()})
        dest=self.base/environment_id/fp
        dest.mkdir(parents=True,exist_ok=True)
        manifest=dest/"manifest.json"
        with _exclusive_job_lock(manifest):
            if manifest.exists(): return {**self._load(manifest),"reused":True}
            if (dest/"venv").exists(): raise ValueError("Incomplete environment preserved; use a new identity for clean creation")
            if not self.uv: raise RuntimeError("uv executable is unavailable")
            pinned=dest/"requirements.lock"
            pinned.write_bytes(data)
            py=dest/"venv"/("Scripts/python.exe" if os.name=="nt" else "bin/python")
            started=time.monotonic()
            try:
                for command in ([self.uv,"venv","--python",str(interpreter),str(dest/"venv")],
                    [self.uv,"pip","sync","--require-hashes","--cache-dir",str(self.cache),"--python",str(py),str(pinned)]):
                    result=self._command(command,timeout)
                    if result.returncode: raise RuntimeError(f"Environment setup failed ({result.returncode}): {result.stderr[-3000:]}")
                value={"schema":"neyvia.environment.v1","environmentId":environment_id,"fingerprint":fp,
                    "lockSha256":lock_hash,"interpreter":identity,"platform":platform.platform(),"python":str(py),
                    "manifestPath":str(manifest),"cachePath":str(self.cache),"createdAt":time.time(),
                    "createSeconds":time.monotonic()-started,"ready":True}
                value["integritySha256"]=_hash(value)
                atomic_write_json(manifest,value)
                return {**value,"reused":False}
            except Exception as error:
                atomic_write_json(dest/"setup-failure.json",{"status":"failed","ready":False,"error":str(error)})
                raise

    def run(self, manifest, args, timeout=30, outputs=None):
        if not isinstance(args,list) or any(not isinstance(arg,str) for arg in args):
            raise ValueError("Interpreter arguments must be strings")
        disk=Path(str(manifest.get("manifestPath") or "")).resolve()
        saved=self._load(disk)
        if {k:v for k,v in manifest.items() if k!="reused"}!=saved:
            raise ValueError("Forged or stale environment manifest")
        command = [saved['python'], *args]
        executable_hash = hashlib.sha256(Path(saved['python']).read_bytes()).hexdigest()
        script = None
        if args and not args[0].startswith('-'):
            script_path = (self.root / args[0]).resolve()
            script_path.relative_to(self.root)
            if script_path.is_file() and not script_path.is_symlink() and script_path.stat().st_size <= 4_000_000:
                script = {'path': str(script_path), 'sha256': hashlib.sha256(script_path.read_bytes()).hexdigest()}
        started=time.monotonic()
        receipt_path=disk.parent/f"run-{uuid.uuid4().hex}.json"
        try:
            proc=self._command([saved["python"],*args],timeout)
            receipt={"status":"completed" if proc.returncode==0 else "failed","exitCode":proc.returncode,
                "stdout":proc.stdout[:20000],"stderr":proc.stderr[:20000],"outputTruncated":len(proc.stdout)>20000 or len(proc.stderr)>20000}
        except subprocess.TimeoutExpired:
            receipt={"status":"timed_out","exitCode":None,"stdout":"","stderr":"Interpreter exceeded bounded execution time"}
        receipt.update(durationSeconds=time.monotonic()-started,python=saved["python"],fingerprint=saved["fingerprint"],receiptPath=str(receipt_path),
                       command=command, arguments=args, interpreterSha256=executable_hash, script=script,
                       declaredOutputs=list(outputs or []), requestHash=_hash({'manifestPath':str(disk),'fingerprint':saved['fingerprint'],
                           'arguments':args,'script':script,'interpreterSha256':executable_hash,'declaredOutputs':list(outputs or [])}))
        atomic_write_json(receipt_path,receipt)
        return receipt
