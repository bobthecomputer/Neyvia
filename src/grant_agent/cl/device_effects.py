"""Completed paired-PC file effects, proved from both endpoints afresh.

CL admission is intentionally narrower than the native copy engine: explicit
destination folders and regular files up to 64 MiB. A queued transfer, saved
digest or peer's acknowledgement alone cannot establish the requested effect.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from urllib.parse import urlencode

SUPPORTED = {'neyvia.devices.files.fetch', 'neyvia.devices.files.send'}
MAX_BYTES = 64 * 1024 * 1024


def readonly(name, args):
    if name == 'neyvia.devices.transfers':
        return True
    return None


def _owner(protocol):
    from ..neyvia_devices import devices_for
    return devices_for(protocol.gateway.root)


def _local_file(protocol, value):
    from ..neyvia_devices import _local
    path = _local(protocol.gateway.root, value)
    if path.is_symlink() or path.is_junction() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('CL paired-PC effects require a regular file <=64 MiB')
    return {'path': str(path), 'size': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _remote_file(service, peer, value):
    from ..neyvia_devices import CHUNK
    row = service.remote(peer, 'files/stat', body={'path': value, 'hash': True})
    if (row.get('kind') != 'file' or not isinstance(row.get('size'), int)
            or not 0 <= row['size'] <= MAX_BYTES or len(row.get('sha256', '')) != 64):
        raise ValueError('CL paired-PC effects require a hashed regular remote file <=64 MiB')
    # The peer's metadata digest may be cached by size/mtime. Independently
    # hash fresh ranges so a restored timestamp cannot hide changed bytes.
    digest, offset, mtime = hashlib.sha256(), 0, None
    while offset < row['size'] or offset == 0:
        length = min(CHUNK, row['size'] - offset)
        data, headers = service.remote(peer, 'files/raw?' + urlencode(
            {'path': value, 'offset': offset, 'length': length}), raw=True)
        stamp = headers['X-Neyvia-Mtime']
        if (len(data) != length or int(headers['X-Neyvia-Size']) != row['size']
                or mtime is not None and stamp != mtime
                or hashlib.sha256(data).hexdigest() != headers['X-Neyvia-Chunk-Sha256']):
            raise ValueError('Remote file changed during fresh effect observation')
        mtime = stamp
        digest.update(data)
        offset += len(data)
        if offset == row['size']:
            break
    measured = digest.hexdigest()
    if measured != row['sha256']:
        raise ValueError('Remote metadata digest disagrees with freshly read bytes')
    return {'path': value, 'size': row['size'], 'sha256': measured}


def _folder(service, peer, value, remote):
    from ..neyvia_devices import _local
    if remote:
        row = service.remote(peer, 'files/list', body={'path': value, 'showHidden': True})
        entries = row.get('entries', [])
        if len(entries) > 128 or row.get('truncated'):
            raise ValueError('CL destination observation admits at most 128 entries')
        return {'path': row['path'], 'existing': [entry['path'] for entry in entries]}
    path = _local(service.root, value)
    if path.is_symlink() or path.is_junction() or path.exists() and not path.is_dir():
        raise ValueError('CL Take destination must be a regular folder')
    entries = list(path.iterdir()) if path.exists() else []
    if len(entries) > 128:
        raise ValueError('CL destination observation admits at most 128 entries')
    return {'path': str(path), 'existing': [str(entry) for entry in entries]}


def snapshot_for(protocol, name, args):
    if name not in SUPPORTED:
        return None
    service = _owner(protocol)
    peer = service.peer(args['device'])
    remote_source = name.endswith('.fetch')
    source = (_remote_file(service, peer, args['from']) if remote_source
              else _local_file(protocol, args['from']))
    destination = _folder(service, peer, args['to'], not remote_source)
    with service.state() as state:
        existing = list(state['transfers'])
    return {'source': source, 'destination': destination, 'existingTransfers': existing}


def _check(protocol, name, args, value, before):
    if not before:
        return False
    service = _owner(protocol)
    returned = value.get('transfer', {})
    identity = returned.get('id')
    if not identity or identity in before['existingTransfers']:
        return False
    with service.state() as state:
        row = deepcopy(state['transfers'].get(identity, {}))
    source = before['source']
    sending = name.endswith('.send')
    if (row.get('device') != args['device'] or row.get('direction') != ('send' if sending else 'take')
            or row.get('from') != args['from'] or row.get('status') != 'done'
            or row.get('kind') != 'file' or row.get('size') != source['size']
            or row.get('done') != source['size'] or row.get('sha256') != source['sha256']
            or row.get('files') != {'done': 1, 'total': 1}
            or len(row.get('plan', [])) != 1 or not row.get('finishedAt')
            or any(returned.get(key) != row.get(key) for key in ('id', 'device', 'from', 'to', 'direction', 'status', 'sha256'))):
        return False
    target = row['to']
    destination = before['destination']
    if target in destination['existing'] or Path(target).parent != Path(destination['path']):
        return False
    peer = service.peer(args['device'])
    origin = (_local_file(protocol, args['from']) if sending else _remote_file(service, peer, args['from']))
    received = (_remote_file(service, peer, target) if sending else _local_file(protocol, target))
    return all(row['sha256'] == source['sha256'] and row['size'] == source['size'] for row in (origin, received))


def checks_for(protocol, name, args):
    if name not in SUPPORTED or not args.get('to'):
        return []
    required = {'neyvia.devices.transfers', 'neyvia.devices.files.stat'}
    if protocol.scope is not None and not required <= protocol.scope:
        return []
    return [{'name': 'effect-' + name.removeprefix('neyvia.').replace('.', '-'),
             'observer': True, 'effect': True,
             'subjectKey': 'paired-file:' + args['device'] + ':' + args['from'],
             'bindSubject': lambda arguments, value, previous: 'paired-file-transfer:' + value['transfer']['id'],
             'observerTool': 'neyvia.devices.transfers+neyvia.devices.files.stat',
             'subject': {key: args[key] for key in ('device', 'from', 'to')},
             'expectation': 'Fresh completed exact single-file transfer; both endpoint SHA-256 and size agree; source conserved and destination not overwritten',
             'check': lambda arguments, value, previous: _check(protocol, name, arguments, value, previous)}]
