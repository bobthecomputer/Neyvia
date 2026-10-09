"""Owned hidden Obscura lifecycle for the host-side render driver; no browser fallback."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

WT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WT / 'src'))
from grant_agent.subprocess_utils import install_hidden_subprocess_default
from grant_agent.neyvia_browser import BrowserService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--root', required=True)
    parser.add_argument('--executable')
    args = parser.parse_args()
    if not 48801 <= args.port <= 48809:
        raise ValueError('Explicit C13 Obscura port must be 48801-48809')
    from grant_agent.browser_obscura import managed_executable
    admitted = managed_executable()
    executable = args.executable or os.environ.get('NEYVIA_OBSCURA_EXE') or str(admitted)
    import hashlib
    if hashlib.sha256(Path(executable).read_bytes()).digest() != hashlib.sha256(admitted.read_bytes()).digest():
        raise ValueError('C13 requires the admitted color-scheme Obscura engine; obsolete override refused')
    os.environ['NEYVIA_OBSCURA_EXE'] = executable
    install_hidden_subprocess_default()
    service = BrowserService(args.root)
    try:
        service.request('headless.start', {'port': args.port, 'assignedPorts': '48801-48809', 'allowLocalFixtures': True}, owner=True)
        print(json.dumps({'engine':'obscura', 'endpoint':service.headless.endpoint,
                          'token':service.headless.token, 'executable':executable}), flush=True)
        # The opaque process capability stays between the trusted host and driver.
        for line in sys.stdin:
            if json.loads(line).get('op') == 'close':
                break
    finally:
        service.request('headless.stop', owner=True)


if __name__ == '__main__':
    main()
