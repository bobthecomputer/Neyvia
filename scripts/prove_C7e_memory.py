"""Observe a held real reader and concurrent production memory append."""
import argparse
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import hashlib
import json
from pathlib import Path
import sys
import threading
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error('Explicit assigned port required')
    args.output.resolve().relative_to(REPO / 'scripts/evidence')
    root = REPO / '.agent_control/proofs/c7e-memory' / uuid.uuid4().hex
    root.mkdir(parents=True)
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent.memory import MemoryStore
    path = root / 'memory.json'
    store = MemoryStore(path)
    first = store.add('owned-first', 'owned concurrency', 'first', [], 'note')
    opened, release, writer_started = threading.Event(), threading.Event(), threading.Event()
    original = MemoryStore._load
    def held_read(selected):
        if threading.current_thread().name.startswith('c7e-reader'):
            with selected.open('rb'):
                opened.set()
                if not release.wait(10):
                    raise TimeoutError('Reader release was not delivered')
                return original(selected)
        return original(selected)
    def append():
        writer_started.set()
        return store.add('owned-second', 'owned concurrency', 'second', [], 'note')
    blocked = False
    MemoryStore._load = staticmethod(held_read)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='c7e-reader') as readers, ThreadPoolExecutor(max_workers=1, thread_name_prefix='c7e-writer') as writers:
            reader = readers.submit(MemoryStore, path)
            if not opened.wait(5):
                raise TimeoutError('Real memory reader did not open')
            writer = writers.submit(append)
            if not writer_started.wait(5):
                raise TimeoutError('Writer did not start')
            try:
                writer.result(timeout=.25)
            except TimeoutError:
                blocked = True
            finally:
                release.set()
            observed = reader.result(timeout=5)
            second = writer.result(timeout=5)
    finally:
        release.set()
        MemoryStore._load = staticmethod(original)
    actual = MemoryStore(path)
    if not blocked or [r.id for r in observed.items] != [first.id] or {r.id for r in actual.items} != {first.id, second.id}:
        raise ValueError('Reader/writer serialization or preserved records failed')
    sources = ('src/grant_agent/memory.py', 'src/grant_agent/durability.py', 'src/grant_agent/harness_jobs.py')
    from grant_agent.proof_contracts import source_digest
    report = {'schema':'neyvia.c7e-memory-reader.v1', 'ok':True, 'explicitPort':args.port,
              'readerHeldRealFile':True, 'writerWaitedUntilReaderClosed':blocked, 'readerRecords':len(observed.items), 'finalRecords':len(actual.items),
              'sourceBindings':{name:source_digest(REPO / name) for name in sources},
              'retainedFile':{'path':path.relative_to(REPO).as_posix(), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},
              'boundary':'Actual production MemoryStore and filesystem sharing; supplied owned local records, no model/provider/rendered claim'}
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok':True, 'writerWaitedUntilReaderClosed':blocked, 'finalRecords':2}))


if __name__ == '__main__':
    main()
