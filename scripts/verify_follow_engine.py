"""Measure the production engine lifecycle with instrumented dependencies, never ASR."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ENGINE = Path(r'C:\Users\user\Projects\dictation-phonon2\phonon2_engine.py')
SCRIPT = r'''
import importlib.util,json,os,sys,time,types
from pathlib import Path
engine_path, delay, device = sys.argv[1], float(sys.argv[2]), sys.argv[3]
idle_minutes = sys.argv[5]
metrics = Path(sys.argv[4])
counts={'transcribe':0,'warm_transcribe':0,'decode_transcribe':0,'warm_graphs':0,'loaded':False,'boundary':'Instrumented dependency only, no ASR/model/GPU'}
def save(): metrics.write_text(json.dumps(counts),encoding='utf-8')
class Runner:
 def __init__(self,model_dir,device=None):
  time.sleep(delay)
  self.device=types.SimpleNamespace(type=device)
  self.loaded_from='disposable lifecycle fixture';self.use_graphs=False;self.fast_decoder=True;self.dtype='float32'
  counts['loaded']=True;counts['loadedAt']=time.time();save()
 def transcribe(self,audio,**kwargs):
  counts['transcribe']+=1
  if module.ENGINE.state=='ready':
   counts['decode_transcribe']+=1;counts['decoding']=True;save();time.sleep(3)
   counts['decoding']=False;counts['decodeFinishedAt']=time.time()
  else: counts['warm_transcribe']+=1
  save();return ''
 def warm_graphs(self,seconds): counts['warm_graphs']+=1;save();return 0
runner=types.ModuleType('phonon2_runner');runner.PhononRunner=Runner;runner.GRAPH_BUCKET=200;runner.GRAPH_MAX_FRAMES=3000
sys.modules['phonon2_runner']=runner;sys.modules['transformers']=types.ModuleType('transformers')
spec=importlib.util.spec_from_file_location('measured_engine',engine_path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
raise SystemExit(module.main(['--port','48447','--device',device,'--idle-exit-minutes',idle_minutes]))
'''

def health():
    try:
        with urllib.request.urlopen('http://127.0.0.1:48447/v1/health', timeout=.3) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', action='store_true')
parser.add_argument('--engine-path', type=Path, default=ENGINE)
parser.add_argument('--idle-minutes', type=float, default=.02)
parser.add_argument('--load-delay', type=float, default=2)
args = parser.parse_args()
ORIGINAL = ENGINE
ENGINE = args.engine_path.resolve()
candidate = ENGINE != ORIGINAL.resolve()
if candidate:
    ENGINE.relative_to(Path('.agent_control/FOLLOW-engine/candidate').resolve())
    assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == '172b282b61b0f1bd861ac45a77190d8ff2203f8bf805970028fc2516979674a8', 'Original engine changed; candidate patch must be reviewed'
idle_seconds = args.idle_minutes * 60
if health() is not None:
    raise SystemExit('48447 already serving; never replace an existing engine')
receipt = {'schema': 'neyvia.FOLLOW.dictation-lifecycle.v1', 'engineSource': str(ENGINE), 'engineSha256': hashlib.sha256(ENGINE.read_bytes()).hexdigest(), 'boundary': 'Actual production engine HTTP/main/load/idle code in real subprocess, delayed instrumented runner dependency; not ASR or weights/GPU latency evidence', 'checks': []}
receipt['installed'] = False if candidate else 'unmodified original baseline'
receipt['originalEngineSha256'] = hashlib.sha256(ORIGINAL.read_bytes()).hexdigest()
if candidate:
    receipt['patch'] = 'scripts/evidence/FOLLOW-engine.patch'
    receipt['patchSha256'] = hashlib.sha256(Path(receipt['patch']).read_bytes()).hexdigest()
root = Path('.agent_control/FOLLOW-engine').resolve()
root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='fixture-', dir=root) as directory:
    scratch = Path(directory)
    fixture = scratch / 'runner.py'
    fixture.write_text(SCRIPT, encoding='utf-8')
    cases = [('cpu', 32), ('cpu', .1)] if args.baseline else [('cpu', args.load_delay), ('cuda', .1)]
    for device, delay in cases:
        metrics = scratch / (device + '.json')
        began = time.monotonic()
        proc = subprocess.Popen([sys.executable, str(fixture), str(ENGINE), str(delay), device, str(metrics), str(args.idle_minutes)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        ready_at = None
        samples = []
        decode_request = None
        decode_outcome = {}
        def exercise_decode():
            try:
                with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:48447/v1/transcribe', data=b'\0\0'*3200), timeout=10) as response:
                    decode_outcome['httpStatus'] = response.status
                    decode_outcome['returnedAt'] = time.time()
            except Exception as error:
                decode_outcome['error'] = str(error)
        try:
            while proc.poll() is None and time.monotonic() - began < max(70, delay + idle_seconds + 65):
                state = health()
                if state:
                    samples.append({'elapsed': round(time.monotonic()-began,3), 'state': state['state'], 'warm_ms': state.get('warm_ms'), 'load_ms': state.get('load_ms')})
                    if state['state'] == 'ready' and ready_at is None:
                        ready_at = time.monotonic()
                        if candidate and device == 'cpu':
                            decode_request = threading.Thread(target=exercise_decode)
                            decode_request.start()
                        if args.baseline and delay < 1:
                            with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:48447/v1/shutdown', data=b''), timeout=2) as response:
                                assert json.load(response)['ok']
                time.sleep(.1)
            if proc.poll() is None:
                raise RuntimeError('Owned lifecycle subprocess did not idle out within the measured load and idle deadline plus observation interval')
            output = proc.stdout.read().decode('utf-8', errors='replace')
            counts = json.loads(metrics.read_text()) if metrics.exists() else {'loaded': False}
            elapsed = time.monotonic() - began
            idle_after_ready = None if ready_at is None else time.monotonic() - ready_at
            row = {'device': device, 'loadFixtureDelaySeconds': delay, 'elapsedSeconds': round(elapsed,3), 'idleAfterReadySeconds': None if idle_after_ready is None else round(idle_after_ready,3), 'idleSettingSeconds': idle_seconds, 'effectiveMinimumIdleSeconds': idle_seconds, 'pollIntervalSeconds': min(30, max(.05, args.idle_minutes * 15)) if candidate else 30, 'metrics': counts, 'healthSamples': samples, 'output': output, 'returnCode': proc.returncode}
            if args.baseline:
                row['reproducedExitBeforeReady'] = ready_at is None and counts['loaded'] is False
                if delay > 1:
                    assert row['reproducedExitBeforeReady'], row
                else:
                    row['reproducedCPUWarmup'] = counts.get('transcribe') == 8 and counts.get('warm_graphs') == 1
                    assert row['reproducedCPUWarmup'], row
            else:
                assert ready_at is not None and proc.returncode == 0, row
                assert idle_after_ready >= idle_seconds - .15, row
                if device == 'cpu':
                    assert counts['warm_transcribe'] == 0 and counts['warm_graphs'] == 0, row
                    assert counts['decode_transcribe'] == 1 and decode_outcome.get('httpStatus') == 200, (row, decode_outcome)
                    assert time.time() - counts['decodeFinishedAt'] >= idle_seconds - .15, row
                    row['activeDecode'] = decode_outcome
                    row['idleAfterDecodeSeconds'] = round(time.time() - counts['decodeFinishedAt'], 3)
                else:
                    assert counts['transcribe'] == 8 and counts['warm_graphs'] == 1, row
                row['passed'] = True
            receipt['checks'].append(row)
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
            if decode_request is not None:
                decode_request.join(timeout=10)
name = 'FOLLOW-engine-baseline.json' if args.baseline else 'FOLLOW-engine-candidate.json' if candidate else 'FOLLOW-engine.json'
Path('scripts/evidence', name).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'receipt': name, 'checks': [{key: value for key, value in row.items() if key not in ['output','healthSamples']} for row in receipt['checks']]}))
