"""Run the real local pack staging owner in a confined hidden child."""
import argparse
import json
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--root', required=True)
parser.add_argument('--pack-id', choices=('base', 'pack.creator-sdk'), required=True)
args = parser.parse_args()
source = Path(os.environ['NEYVIA_C8_SOURCE']).resolve()
root = Path(args.root).resolve()
root.relative_to(source / '.agent_control/proofs/C8')
sys.path.insert(0, str(source / 'src'))
from grant_agent.proof_credential_guard import install as credentials
from c8_scope import install
credentials(root)
install(allow_children=False, writable_root=root)
from grant_agent.neyvia_onboarding import run_download, load_pack_manifest, load_manifest, manifest_source
manifest = load_manifest(manifest_source()) if args.pack_id == 'base' else load_pack_manifest(args.pack_id)
if any(not str(row['url']).startswith('file:') for row in manifest['files']):
    raise PermissionError('C8e permits only installed local pack payloads')
result = run_download(root, manifest, pack_id=None if args.pack_id == 'base' else args.pack_id)
print(json.dumps(result), flush=True)
