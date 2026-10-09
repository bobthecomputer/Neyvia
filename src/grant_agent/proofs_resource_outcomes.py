"""Observe real lease contention, bounded log capture and owned memory termination."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

CONTRACT = 'p22.trace-resource-boundaries'


def self_check(scratch):
    from .contract_gate import wants
    from . import contract_resources as resource_api
    from .contract_resources import capture_resource_bounded, heavy_slot
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    from unittest.mock import patch

    root = Path('D:/NeyviaRuns/P22/resource-outcomes') / uuid.uuid4().hex
    root.mkdir(parents=True)
    cases = []
    started = time.perf_counter()
    if wants(CONTRACT):
        contender = None
        try:
            # A stale Windows PPID can attach an older foreign tree to a new
            # worker whose numeric PID was recycled. Real newer descendants
            # must remain owned, including after the root exits.
            parents = {101: 100, 102: 101, 103: 100, 104: 103, 105: 101}
            births = {101: 11, 102: 12, 103: 3, 104: 4, 105: 8}
            owned = resource_api._created_descendants(parents, 100, 10, births.get)
            if owned != [101, 102]:
                raise AssertionError('Creation-time ownership lost real children or admitted stale PPIDs')
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
            # This fixture tests the process governor, not a third trace process.
            for key in list(env):
                if key.startswith('NEYVIA_P22_TRACE_'): env.pop(key)
            repo = Path(__file__).resolve().parents[2]
            env['PYTHONPATH'] = str(repo/'src')
            env['TEMP'] = env['TMP'] = str(root)
            ready = root/'second-slot.json'
            release = root/'release'
            code = ('import json,sys,time; from pathlib import Path; '
                    'from grant_agent.contract_resources import heavy_slot; '
                    'ready,release=map(Path,sys.argv[1:]); '
                    '\nwith heavy_slot(timeout=4) as slot:\n'
                    ' ready.write_text(json.dumps({"slot":slot}),encoding="utf-8")\n'
                    ' deadline=time.monotonic()+5\n'
                    ' while not release.exists() and time.monotonic()<deadline: time.sleep(.02)\n')
            with heavy_slot(timeout=4) as first_slot:
                contender = subprocess.Popen([sys.executable, '-B', '-c', code, str(ready), str(release)],
                                             cwd=repo, env=env, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, **hidden_windows_subprocess_kwargs())
                deadline = time.monotonic()+4
                while not ready.exists() and contender.poll() is None and time.monotonic()<deadline: time.sleep(.02)
                if not ready.is_file(): raise AssertionError('The second owned process never acquired its slot')
                second_slot = json.loads(ready.read_text())['slot']
                if first_slot == second_slot: raise AssertionError('Two processes were admitted under one slot')
                refused = capture_resource_bounded([sys.executable, '-B', '-c', 'raise SystemExit(99)'],
                                                   cwd=repo, env=env, input_text=None, timeout=.15,
                                                   logs_root=root/'blocked')
                if (refused.get('reason') != 'slot-timeout' or refused.get('returncode') is not None
                        or refused.get('processReturncode') is not None):
                    raise AssertionError('A third heavy process was not refused by the shared governor')
                release.write_text('release', encoding='utf-8')
                contender.wait(timeout=4)
                if contender.returncode != 0: raise AssertionError('The admitted lease fixture failed')
            captured = capture_resource_bounded([sys.executable, '-B', '-c', 'import time; print("scope✓",flush=True); time.sleep(.3)'],
                                                cwd=repo, env=env, input_text=None, timeout=4, logs_root=root/'positive')
            if captured['returncode'] != 0 or captured.get('memoryExceeded') or 'scope✓' not in captured['stdout']:
                raise AssertionError('The bounded D-drive log capture lost the actual child result')
            retained_queries = None
            if os.name == 'nt':
                from .proofs_b_harness import _OwnedProcessDacl
                query_child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(8)'],
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                               **hidden_windows_subprocess_kwargs())
                query_watch, fence = None, None
                try:
                    query_watch = resource_api.MemoryWatch(query_child.pid, logs_root=root/'query-rights',
                                                          process=query_child).start()
                    # Both the outer capture and this watcher observe the owned
                    # child before its deliberately temporary access fence.
                    time.sleep(.6)
                    fence = _OwnedProcessDacl(query_child)
                    fence.deny(0x00100000 | 0x1000 | 0x0400 | 0x0010)
                    time.sleep(.6)
                    if not query_watch.available or query_watch.reason is not None or not query_watch.peak_private_bytes:
                        raise AssertionError('Retained owned query handles lost actual memory observation under a DACL fence')
                    retained_queries = {'actualDaclFence': True, 'memoryStillObserved': True,
                                        'peakPrivateBytes': query_watch.peak_private_bytes}
                    fence.close()
                    fence = None
                    query_child.terminate()
                    query_child.wait(timeout=3)
                    query_child._handle.Close()
                    import ctypes
                    from ctypes import wintypes
                    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                    opened = kernel.OpenProcess
                    opened.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                    opened.restype = wintypes.HANDLE
                    close = kernel.CloseHandle
                    close.argtypes = [wintypes.HANDLE]
                    deadline = time.monotonic() + 3
                    while True:
                        handle = opened(0x00100000, False, query_child.pid)
                        error = ctypes.get_last_error()
                        if handle: close(handle)
                        if not handle and error == 87: break
                        if time.monotonic() >= deadline:
                            raise AssertionError('Exited query handles prevented positive dead-PID evidence')
                        time.sleep(.05)
                    retained_queries['releasedAfterExit'] = True
                finally:
                    if fence is not None: fence.close()
                    if query_watch is not None: query_watch.stop()
                    if query_child.poll() is None: query_child.terminate()
                    query_child.wait(timeout=3)
            limited = capture_resource_bounded([sys.executable, '-B', '-c', 'import time; time.sleep(3)'],
                                               cwd=repo, env=env, input_text=None, timeout=4,
                                               logs_root=root/'memory', limit_bytes=1)
            if not limited.get('memoryExceeded') or limited['returncode'] == 0 or not limited.get('processTreeStopped'):
                detail = {key: limited.get(key) for key in ('memoryExceeded', 'returncode', 'processReturncode', 'processTreeStopped', 'reason')}
                raise AssertionError('The actual tiny-threshold cutoff did not pass: '+json.dumps(detail))
            enumerate_tree = resource_api._descendant_pids
            def fail_child_enumeration(pid):
                # Keep the live tracer's own guard intact while failing only
                # the controlled child's enumeration API.
                if pid == os.getpid():
                    return enumerate_tree(pid)
                raise OSError('injected process enumeration failure')
            with patch.object(resource_api, '_descendant_pids', side_effect=fail_child_enumeration):
                unavailable = capture_resource_bounded([sys.executable, '-B', '-c', 'import time; time.sleep(3)'],
                                                       cwd=repo, env=env, input_text=None, timeout=5,
                                                       logs_root=root/'enumeration-failure')
            if (unavailable.get('reason') != 'memorywatch-unavailable'
                    or unavailable.get('memoryExceeded')
                    or not unavailable.get('rootProcessStopped')
                    or unavailable.get('processReturncode') in (None, 0)):
                detail = {key: unavailable.get(key) for key in
                          ('reason', 'memoryExceeded', 'returncode', 'processReturncode',
                           'rootProcessStopped', 'processTreeStopped')}
                raise AssertionError('Enumeration failure did not stop the owned root: '+json.dumps(detail))
            cases.append({'id': CONTRACT, 'contracts': [CONTRACT], 'ok': True,
                          'observed': {'distinctSlots': [first_slot, second_slot], 'thirdProcessRefused': True,
                                       'cutoffReason': limited.get('reason'), 'cutoffPeakPrivateBytes': limited.get('peakPrivateBytes'),
                                       'positivePeakPrivateBytes': captured.get('peakPrivateBytes'),
                                       'enumerationFailureInjected': True,
                                       'enumerationFailureProcessReturncode': unavailable.get('processReturncode'),
                                       'enumerationFailureRootStopped': unavailable.get('rootProcessStopped'),
                                       'creationTimeOwnedDescendants': owned,
                                       'recycledParentIdsRefused': [103, 104, 105],
                                       'retainedOwnedQueryRights': retained_queries,
                                       'logsRoot': str(root), 'noLargeAllocation': True}})
        except Exception as error:
            cases.append({'id': CONTRACT, 'contracts': [CONTRACT], 'ok': False,
                          'error': type(error).__name__+': '+str(error)})
        finally:
            if contender is not None and contender.poll() is None:
                release.write_text('release', encoding='utf-8')
                try: contender.wait(timeout=2)
                except subprocess.TimeoutExpired: contender.kill(); contender.wait(timeout=2)
    return {'ok': bool(cases) and all(row['ok'] for row in cases), 'cases': cases,
            'contracts': [CONTRACT] if cases and cases[0]['ok'] else [],
            'durationMs': round((time.perf_counter()-started)*1000, 2)}
