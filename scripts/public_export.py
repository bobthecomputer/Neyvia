"""Export a pinned release file tree, never its private Git history.

The receipt lives outside the output tree and records every omission, rewritten
file and output hash. Existing output directories must be empty.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'.gitattributes', '.gitignore', 'LICENSE', 'README.md', 'MODULES.md',
              'THIRD_PARTY_NOTICES.md', 'package.json', 'package-lock.json',
              'pyproject.toml', 'uv.lock', 'vite.config.mjs',
              '.github/workflows/publish-desktop-release.yml'}
ROOT_DIRS = {'src', 'web', 'manuals', 'config', 'scripts', 'plugins', 'tools',
             'src-tauri', 'docs', 'apps', 'native', 'packages', 'rust', 'sdk',
             'specs', 'templates', 'third_party', 'modules', '.claude-plugin', '.codex'}
PRIVATE_PARTS = {'proof', 'evidence', '.neyvia', '.agent_control', 'plans',
                 '.ui-memory', 'node_modules', '__pycache__', '.venv', 'target',
                 'screenshots', 'transcripts', 'sessions', 'corpora'}
PRIVATE_NAMES = {'working-with-paul.cl', 'working-with-paul.manual.json'}
PROFILE_STUB = '''"""Public distribution: no bundled personal profile or learned messages."""
from pathlib import Path
MANUAL = Path(__file__).resolve().parents[2] / "config/user_profile.json"
BRIEF_MIN_P = 0.7
def laplace(n: int, c: int) -> float:
    return (n + 1) / (n + c + 2)
def profile(path=MANUAL) -> dict:
    return {"rules": [], "judgements": []}
def validate(path=MANUAL) -> list[str]:
    return []
def brief(level=2, min_p=BRIEF_MIN_P, path=MANUAL) -> str:
    return ""
'''


def exclusion(path: str) -> str | None:
    p = PurePosixPath(path)
    lower = path.lower()
    if lower == 'config/neyvia_secret_broker.json' or re.search(r'\.(key|pem|p12|pfx)$', lower):
        return 'protected credential/key storage'
    if p.parts[0] not in ROOT_DIRS and path not in ROOT_FILES:
        return 'outside release roots'
    if set(p.parts) & PRIVATE_PARTS or 'working-with-paul' in lower:
        return 'private records/profile or generated runtime state'
    if p.parts[0] == '.codex' and not lower.startswith('.codex/skills/'):
        return 'local agent configuration'
    if re.search(r'\.sqlite[^/]*$|\.(jsonl|db|pyc|pyo|zip|tar|gz|7z|log)$', lower):
        return 'database, transcript, archive or run log'
    if lower.startswith('config/paul_intent/') or '/personal' in lower:
        return 'personal intent/profile data'
    if lower.startswith(('docs/research/', 'docs/verification/', 'docs/standard/examples/today/')):
        return 'recorded private research or run observations'
    if p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.mp4', '.pdf'}:
        if not lower.startswith(('web/', 'src-tauri/icons/', 'apps/', 'templates/')):
            return 'unreviewed screenshot or captured document/media'
    if re.search(r'(^|/)(auth\.json|credentials[^/]*|\.env(?!\.example)|id_rsa|id_ed25519)', lower):
        return 'saved credentials'
    if p.parts[0] == 'scripts' and re.search(r'(c14|paul_intent)', p.name, re.I):
        return 'private intent benchmark helper'
    return None


def scrub_json(value):
    """Remove the excluded profile's catalog/cache entries, including projections."""
    if isinstance(value, dict):
        return {k: scrub_json(v) for k, v in value.items()
                if 'working-with-paul' not in k and k != 'paul_intent'
                and not (isinstance(v, str) and 'working-with-paul' in v)}
    if isinstance(value, list):
        return [scrub_json(v) for v in value
                if not (isinstance(v, dict) and v.get('id') == 'working-with-paul')
                and not (isinstance(v, str) and 'working-with-paul' in v)]
    return value


def public_bytes(path: str, data: bytes) -> bytes:
    # Scanner patterns describe identifiers to remove, rather than owner data.
    # Rewriting this policy would change its meaning when someone reruns it.
    if path == 'scripts/public_export.py':
        return data
    if path == 'src/grant_agent/paul_manual.py':
        return PROFILE_STUB.encode()
    if b'\0' in data[:8192]:
        return data
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return data
    if path.endswith('.json') and 'working-with-paul' in text:
        text = json.dumps(scrub_json(json.loads(text)), indent=2, ensure_ascii=False) + '\n'
    # Public examples/defaults retain their structure without the owner's identity.
    text = re.sub(r'(?i)psch850(?:@gmail\.com|gmail\.com)?', 'user@example.invalid', text)
    text = re.sub(r'(?i)([A-Z]:[\\/]+Users[\\/]+)paul\b', r'\1user', text)
    text = re.sub(r'(?i)(/(?:Users|home)/)paul\b', r'\1user', text)
    text = re.sub(r'(?i)sysnology(?:\.tail602108\.ts\.net)?', 'nas.example.invalid', text)
    text = re.sub(r'(?i)tail602108(?:\.ts\.net)?', 'example.invalid', text)
    text = re.sub(r'(?i)\bCodex2\b', 'nas-user', text)
    text = text.replace('192.168.1.49', '192.0.2.10')
    # This public protocol network is a guard invariant, not a private host.
    def public_address(match):
        if match[0] == '100.64.0.0' and text[match.end():match.end() + 3] == '/10':
            return match[0]
        return '192.0.2.10'
    text = re.sub(r'\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b', public_address, text)
    return text.encode('utf-8')


def export(commit: str, output: Path, receipt: Path) -> dict:
    revision = subprocess.check_output(['git', 'rev-parse', '--verify', commit + '^{commit}'], cwd=ROOT).decode().strip()
    subprocess.run(['git', 'merge-base', '--is-ancestor', revision, 'track/rel29'], cwd=ROOT, check=True)
    output, receipt = output.resolve(), receipt.resolve()
    if output == ROOT or output.is_relative_to(ROOT) or ROOT.is_relative_to(output):
        raise ValueError('Output must be outside the source checkout')
    if receipt.is_relative_to(output):
        raise ValueError('Receipt must be outside the publication tree')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output is not empty; preserve it and choose a fresh folder')
    # A private temporary index makes git ls-files independent of dirty/sparse state.
    with tempfile.TemporaryDirectory(prefix='neyvia-public-') as temp:
        env = {**os.environ, 'GIT_INDEX_FILE': str(Path(temp) / 'index')}
        subprocess.run(['git', 'read-tree', revision], cwd=ROOT, env=env, check=True)
        tracked = subprocess.check_output(['git', 'ls-files', '-s', '-z'], cwd=ROOT, env=env)
    output.mkdir(parents=True, exist_ok=True)
    files, omitted = [], []
    selected = []
    for row in tracked.split(b'\0'):
        if not row:
            continue
        meta, rawpath = row.split(b'\t', 1)
        mode, oid, _ = meta.decode().split()
        path = rawpath.decode('utf-8')
        p = PurePosixPath(path)
        if p.is_absolute() or '..' in p.parts or '\\' in path:
            raise ValueError('Unsafe tracked path: ' + path)
        reason = exclusion(path)
        if reason:
            omitted.append({'path': path, 'reason': reason})
        elif mode not in {'100644', '100755'}:
            raise ValueError('Review symlink/submodule before publishing: ' + path)
        else:
            selected.append((path, mode, oid))
    reader = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=ROOT,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    # Keep the Git pipe fed; per-file request/response round trips are slow on Windows.
    def feed():
        try:
            for _, _, oid in selected:
                reader.stdin.write(oid.encode() + b'\n')
            reader.stdin.close()
        except BrokenPipeError:
            pass
    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    writers = ThreadPoolExecutor(max_workers=8)
    pending = []
    def write_file(dest, public, mode):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(public)
        if mode == '100755':
            dest.chmod(0o755)
    try:
        for index, (path, mode, oid) in enumerate(selected):
            header = reader.stdout.readline().split()
            if len(header) != 3 or header[1] != b'blob' or header[0].decode() != oid:
                raise ValueError('Missing blob: ' + path)
            size = int(header[2])
            data = reader.stdout.read(size)
            if len(data) != size or reader.stdout.read(1) != b'\n':
                raise ValueError('Truncated blob: ' + path)
            public = public_bytes(path, data)
            dest = output / path
            pending.append(writers.submit(write_file, dest, public, mode))
            if len(pending) == 64:
                for job in pending:
                    job.result()
                pending.clear()
            files.append({'path': path, 'mode': mode, 'sha256': hashlib.sha256(public).hexdigest(),
                          'bytes': len(public), 'rewritten': public != data})
            if (index + 1) % 1000 == 0:
                print(f'Exported {index + 1}/{len(selected)} files', flush=True)
        for job in pending:
            job.result()
    finally:
        writers.shutdown(wait=True)
        if len(files) != len(selected):
            reader.terminate()
        feeder.join()
        reader.wait()
    result = {'schema': 'neyvia.public-export.v1', 'sourceCommit': revision,
              'files': files, 'excluded': omitted,
              'profile': 'Imported API retained with an empty neutral profile; personal manual omitted.'}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'commit': revision, 'files': len(files), 'bytes': sum(f['bytes'] for f in files),
                      'excluded': len(omitted), 'rewritten': sum(f['rewritten'] for f in files),
                      'exclusionReasons': dict(Counter(f['reason'] for f in omitted))}))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True, help='Pinned commit reachable from track/rel29')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    args = parser.parse_args()
    export(args.commit, args.output, args.receipt)
