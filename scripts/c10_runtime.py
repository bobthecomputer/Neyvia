"""Owned CPU LAYA launcher; system Python, existing frozen local weights only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

REPO = Path(__file__).resolve().parents[1]
SYSTEM_PYTHON = Path('C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe')
SOURCE = Path('C:/Users/user/Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement')
MODEL = Path('C:/Users/user/Documents/Codex/2026-09-20/laya-c-est-l-alternative-open/work/models/laya-english')


def health(port):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/health', timeout=3) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    if args.port not in range(48771, 48780):
        parser.error('Only explicit C10 assigned ports48771-48779 are allowed')
    if Path(sys.executable).resolve() != SYSTEM_PYTHON.resolve():
        parser.error('Run this launcher with the explicitly assigned system Python313')
    directory = REPO / '.agent_control/C10/laya'
    directory.mkdir(parents=True, exist_ok=True)
    if args.probe:
        print(json.dumps(health(args.port)))
        return
    for path in [SOURCE / 'laya_system1/service.py', MODEL / 'model.safetensors',
                 MODEL / 'rl_agent_config.json', SOURCE / 'calibration/system1.json']:
        if not path.is_file():
            raise FileNotFoundError(f'Required existing local LAYA artifact missing: {path}')
    dependencies = REPO / '.agent_control/C10/laya-deps'
    pins = {'transformers': '4.57.6', 'huggingface_hub': '0.36.2'}
    for package, version in pins.items():
        if not (dependencies / f'{package}-{version}.dist-info/METADATA').is_file():
            raise FileNotFoundError(f'Task-local dependency missing: {package}=={version}')
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(dependencies), str(SOURCE)]),
           'CUDA_VISIBLE_DEVICES': '', 'LAYA_CUDA_GRAPHS': '0', 'LAYA_WEIGHT_DTYPE': 'float32',
           'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'USE_TF': '0'}
    command = [str(SYSTEM_PYTHON), '-m', 'laya_system1.service', '--model', str(MODEL),
               '--device', 'cpu', '--port', str(args.port), '--database', str(directory / 'system1.sqlite'),
               '--question-sets', str(SOURCE / 'question_sets'),
               '--calibration', str(SOURCE / 'calibration/system1.json')]
    receipt = {'schema': 'neyvia.C10.runtime.v1', 'port': args.port, 'device': 'cpu',
               'systemPython': str(SYSTEM_PYTHON), 'source': str(SOURCE), 'model': str(MODEL),
               'dependencyBoundary': str(dependencies), 'weightsCopied': False, 'training': False,
               'dependencies': pins,
               'command': command, 'status': 'starting'}
    receipt_path = directory / 'runtime.json'
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    with (directory / 'service.log').open('ab') as log:
        process = subprocess.Popen(command, cwd=REPO, env=env, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        receipt['pid'] = process.pid
        try:
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    value = health(args.port)
                    if value.get('status') == 'ready':
                        receipt.update(status='ready', health=value)
                        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
                        print(json.dumps({'status': 'ready', 'port': args.port, 'pid': process.pid}), flush=True)
                        return_code = process.wait()
                        receipt.update(status='stopped', exitCode=return_code)
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(.5)
            else:
                receipt.update(status='failed', exitCode=process.poll(), reason='CPU service did not become ready')
                raise RuntimeError(receipt['reason'])
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
