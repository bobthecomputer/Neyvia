"""Bounded compiled-family replay on independent private Neyvia desktops."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from prove_C7d_browser import PrivateDesktopProcess

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.proof_ports import c7_port_block


def port_listeners(ports):
    """Read Windows listener ownership without connecting to another service."""
    import ctypes
    import socket
    api = ctypes.WinDLL('iphlpapi').GetExtendedTcpTable
    api.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_bool,
                    ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
    api.restype = ctypes.c_uint32
    found = {}
    for family, stride, port_offset, state_offset, pid_offset in ((2, 24, 8, 0, 20), (23, 56, 20, 48, 52)):
        size = ctypes.c_uint32()
        result = api(None, ctypes.byref(size), False, family, 5, 0)
        if result not in (0, 122):
            raise OSError(result, 'Inspect task port ownership')
        buffer = ctypes.create_string_buffer(size.value)
        result = api(buffer, ctypes.byref(size), False, family, 5, 0)
        if result:
            raise OSError(result, 'Inspect task port ownership')
        raw = buffer.raw
        for index in range(int.from_bytes(raw[:4], 'little')):
            row = raw[4 + index * stride:4 + (index + 1) * stride]
            port = socket.ntohs(int.from_bytes(row[port_offset:port_offset+4], 'little') & 65535)
            if int.from_bytes(row[state_offset:state_offset+4], 'little') == 2 and port in ports:
                found[port] = int.from_bytes(row[pid_offset:pid_offset+4], 'little')
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family', action='append', required=True)
    parser.add_argument('--ports', required=True, help='Distinct primary worker ports, comma separated')
    parser.add_argument('--max-workers', type=int, help='Limit active desktops while preserving all port-affine slots')
    parser.add_argument('--local-fixtures', action='store_true', help='Run existing generated local cases without repeated compiled admission')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    ports = [int(port) for port in args.ports.split(',')]
    maximum = args.max_workers or len(ports)
    if not 1 <= maximum <= len(ports):
        parser.error('Worker limit must fit the assigned slots')
    blocks = [set(c7_port_block(port)) for port in ports]
    if len(set(args.family)) != len(args.family) or any(a & b for i,a in enumerate(blocks) for b in blocks[i+1:]):
        parser.error('Families and worker port blocks must be disjoint')
    occupied = port_listeners(set.union(*blocks))
    if occupied:
        parser.error('Assigned block already has listeners; no processes were stopped: ' + json.dumps(occupied))
    output = args.output.resolve(); output.relative_to(REPO / '.agent_control/C7e')
    output.parent.mkdir(parents=True, exist_ok=True)
    pending, active, finished = list(args.family), {}, []

    def record():
        value = {'schema': 'neyvia.c7e-family-pool.v1', 'pending': pending, 'active': [row for _,row in active.values()],
                 'finished': finished, 'privateDesktops': True, 'maximumWorkers': maximum, 'sourceMutationForbidden': True}
        from grant_agent.durability import atomic_write_json
        atomic_write_json(output, value)

    try:
        while pending or active:
            for port in ports:
                if port not in active and pending and len(active) < maximum:
                    # Reuse an admitted script on its exact original inputs.
                    # Prefer port-affine completed families before assigning
                    # fresh ones, so integration repairs need only a replay.
                    affine = []
                    fresh = []
                    for candidate in pending:
                        previous_path = REPO / 'scripts/evidence' / ('C7e-' + candidate + '-compiled.json')
                        previous = json.loads(previous_path.read_bytes()) if previous_path.exists() else {}
                        if args.local_fixtures:
                            previous = {}
                        if previous.get('explicitPort') == port:
                            affine.append(candidate)
                        elif not previous or previous.get('explicitPort') not in ports:
                            fresh.append(candidate)
                    choices = affine or fresh
                    if not choices:
                        continue
                    family = choices[0]
                    pending.remove(family)
                    process = PrivateDesktopProcess(sys.executable, {**os.environ, 'NEYVIA_C7_PORT': str(port),
                        'PYTHONIOENCODING': 'utf-8', 'NEYVIA_TOOL_AUTO_UPDATE': '0', 'FLUXIO_WATCHDOG_AUTOSTART': '0',
                        'NEYVIA_COORDINATOR_AUTOSTART': '0'}, [REPO / 'scripts' / ('run_C7e_local_worker.py' if args.local_fixtures else 'run_C7e_family_worker.py'), '--family', family, '--port', str(port)])
                    row = {'family': family, 'port': port, 'ports': sorted(c7_port_block(port)), 'pid': process.pid,
                           'privateDesktop': process.name, 'startedEpoch': time.time()}
                    active[port] = process, row
                    print(json.dumps({**row, 'state': 'running'}), flush=True)
            for port,(process,row) in list(active.items()):
                code = process.poll()
                if code is not None:
                    report_path = REPO / 'scripts/evidence' / ('C7-final-' + row['family'] + '.json' if args.local_fixtures else 'C7e-' + row['family'] + '-compiled.json')
                    entry = {**row, 'exitCode': code, 'finishedEpoch': time.time(), 'ok': code == 0 and report_path.is_file()}
                    if entry['ok']:
                        report = json.loads(report_path.read_bytes())
                        entry.update(report=report_path.relative_to(REPO).as_posix(), sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(),
                                     cases=len(report['rows']) if args.local_fixtures else report['finalStatus']['familyCases'],
                                     counts=report['counts'] if args.local_fixtures else report['finalStatus']['familyCounts'])
                    entry['remainingOwnedPidsBeforeClose'] = process.pids()
                    process.terminate()
                    end = time.monotonic() + 5
                    while process.pids() and time.monotonic() < end:
                        time.sleep(.05)
                    entry['remainingOwnedPidsAfterClose'] = process.pids()
                    if entry['remainingOwnedPidsAfterClose']:
                        entry['ok'] = False
                    finished.append(entry); process.close(); del active[port]
                    print(json.dumps({**entry, 'state': 'completed'}), flush=True)
            record()
            time.sleep(1)
    finally:
        for process,_ in active.values():
            process.terminate(); process.wait(20); process.close()
        record()


if __name__ == '__main__':
    main()
