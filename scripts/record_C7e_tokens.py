"""Record bounded numeric usage from this session and directly linked children."""
import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def usage(path):
    with path.open('rb') as stream:
        stream.seek(0, 2)
        stream.seek(max(0, stream.tell() - 2 * 1024 * 1024))
        lines = stream.read().splitlines()
    latest = None
    for line in lines:
        if b'"token_count"' not in line:
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        payload = value.get('payload', {})
        if value.get('type') == 'event_msg' and payload.get('type') == 'token_count':
            info = payload.get('info') or {}
            latest = info.get('total_token_usage') or latest
    return latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--thread-id', required=True)
    parser.add_argument('--session-dir', dest='session_dirs', type=Path, action='append', required=True,
                        help='Session log directory; may be repeated to include additional date folders')
    args = parser.parse_args()
    session_dirs = []
    seen_dirs = set()
    for directory in args.session_dirs:
        directory = directory.resolve()
        if not directory.is_dir():
            parser.error('Each --session-dir must name an existing directory')
        if directory not in seen_dirs:
            seen_dirs.add(directory)
            session_dirs.append(directory)

    # Keep only the newest copy when callers include overlapping date folders.
    # This prevents a copied JSONL session from being counted twice.
    candidates = {}
    seen_paths = set()
    for session_dir in session_dirs:
        for path in session_dir.glob('*.jsonl'):
            path = path.resolve()
            if path in seen_paths:
                continue
            seen_paths.add(path)
            with path.open('rb') as stream:
                first = stream.readline(65536)
            try:
                header = json.loads(first)
            except ValueError:
                continue
            meta = header.get('payload', {})
            if header.get('type') != 'session_meta':
                continue
            identity = meta.get('id')
            is_root = identity == args.thread_id
            linked = args.thread_id in json.dumps(meta.get('source', {}))
            if not is_root and not linked:
                continue
            key = identity if isinstance(identity, str) else str(path)
            previous = candidates.get(key)
            if previous is None or path.stat().st_mtime_ns > previous[0].stat().st_mtime_ns:
                candidates[key] = (path, identity, is_root)

    records = []
    for path, identity, is_root in sorted(candidates.values(), key=lambda item: str(item[1])):
        records.append({'threadId': identity, 'root': is_root, 'usage': usage(path)})
    if not any(row['root'] and row['usage'] for row in records):
        raise ValueError('Root numeric usage unavailable')
    totals = {}
    for row in records:
        for name, count in (row['usage'] or {}).items():
            if isinstance(count, int):
                totals[name] = totals.get(name, 0) + count
    totals['uncachedInputPlusOutput'] = totals.get('input_tokens', 0) - totals.get('cached_input_tokens', 0) + totals.get('output_tokens', 0)
    report = {'schema': 'neyvia.c7e-token-usage.v1', 'records': records, 'loggedTotals': totals,
              'linkedChildLogs': sum(not row['root'] for row in records),
              'scannedSessionDirectories': len(session_dirs),
              'boundary': 'Numeric log snapshot through this checkpoint, including cached input; unlinked/unavailable child usage is not estimated. No message, environment or credential contents emitted.'}
    target = REPO / 'scripts/evidence/C7e-tokens.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'loggedTotals': totals, 'linkedChildLogs': report['linkedChildLogs']}))


if __name__ == '__main__':
    main()
