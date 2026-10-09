"""JSON stdin adapter used by the Node parser acceptance check (not pytest)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from grant_agent.scroll_pack import validate_pack, write_scrollpack, read_scrollpack
from grant_agent.scroll_cost import derive_stats

request = json.load(sys.stdin)
operation = request.get('operation', 'validate')
if operation == 'archive-attack':
    import tempfile
    import zipfile
    with tempfile.TemporaryDirectory(prefix='scroll-archive-probe-') as directory:
        path = Path(directory) / 'unsafe.scrollpack'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, content in request['entries']:
                info = zipfile.ZipInfo()
                info.filename = name  # Preserve malicious backslashes on Windows.
                archive.writestr(info, content)
        try:
            read_scrollpack(path)
            result = {'ok': True}
        except (ValueError, KeyError) as error:
            result = {'ok': False, 'error': str(error)}
elif operation == 'stats':
    result = derive_stats(request['rows'], request['cards'], request.get('review'), request.get('prices'))
elif operation == 'archive':
    try:
        pack, sources = read_scrollpack(Path(request['path']))
        result = {'ok': True, 'cards': len(pack['cards']), 'sources': list(sources)}
    except (ValueError, KeyError) as error:
        result = {'ok': False, 'error': str(error)}
elif operation == 'roundtrip':
    import tempfile
    with tempfile.TemporaryDirectory(prefix='scroll-pack-probe-') as directory:
        path = Path(directory) / 'sample.scrollpack'
        receipt = write_scrollpack(path, request['pack'], request['sources'])
        pack, sources = read_scrollpack(path)
        result = {'ok': pack == request['pack'] and sources == request['sources'], 'receipt': receipt}
else:
    result = validate_pack(request['pack'], request['sources'])
print(json.dumps(result))
