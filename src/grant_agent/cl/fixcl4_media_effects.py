"""Fresh byte-bound preview, video and skill revision effects.

Rendering measurements prove the retained capture and measured report, never a
beauty verdict. All artifacts remain scoped to the native owner's workspace.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .creative_effects import _owned
from .effects import _measure_file

SUPPORTED = {'preview.screenshot', 'preview.annotate', 'preview.taste',
             'video.digest', 'skill.live.iterate'}


def supported(name, args=None):
    return name in SUPPORTED


def _path(protocol, raw):
    path = Path(raw).expanduser()
    return _owned(protocol, path if path.is_absolute() else Path(protocol.gateway.root) / path)


def _file(protocol, raw, digest=None):
    path = _path(protocol, raw)
    observed = _measure_file(path)
    if observed.get('kind') != 'file' or observed.get('bytes', 0) == 0:
        raise ValueError('Media effect requires a nonempty retained file')
    if digest is not None and observed['sha256'] != digest:
        raise ValueError('Media evidence bytes changed')
    return path, observed


def _json(protocol, raw):
    path, _ = _file(protocol, raw)
    return json.loads(path.read_text(encoding='utf-8'))


def snapshot_for(protocol, name, args):
    if name not in SUPPORTED:
        return None
    if name == 'video.digest':
        path, source = _file(protocol, args['path'])
        return {'source':source}
    if name == 'skill.live.iterate':
        from ..skill_iteration import resolve_codex_skill_file, validate_codex_skill_markdown
        _, path = resolve_codex_skill_file(args)
        # The resolver admits only the local skill root; do not follow links.
        current = path
        while current != current.parent:
            if current.is_symlink() or current.is_junction():
                raise ValueError('Skill effects refuse linked subjects')
            current = current.parent
        measured = _measure_file(path)
        original = path.read_text(encoding='utf-8')
        validation = validate_codex_skill_markdown(args['content'])
        ledger = _path(protocol, '.agent_control/skill_revision_receipts.jsonl')
        return {'path':str(path), 'source':measured, 'original':original,
                'expected':validation['content'], 'validation':validation,
                'ledger':ledger.read_text(encoding='utf-8') if ledger.exists() else ''}
    output = args.get('outputPath') if name == 'preview.screenshot' else args.get('outputDir')
    if output:
        _path(protocol, output)
    return {'url':str(args['url']).strip()}


def _screenshot(protocol, args, value, before):
    from ..native_tools import NativeToolRegistry
    path, measured = _file(protocol, value['path'], value['sha256'])
    if args.get('outputPath') and path != _path(protocol, args['outputPath']):
        return False
    width, height = NativeToolRegistry._png_dimensions(path)
    return (value['url'] == before['url'] and width == value['width'] > 0 and
            height == value['height'] > 0 and measured['bytes'] == value['sizeBytes'] and
            value['artifacts'] == [str(path)] and bool(value['engine']))


def _annotation(protocol, args, value, before):
    from ..native_tools import NativeToolRegistry
    from ..proofs_d_native import check_annotation
    rectangle = NativeToolRegistry._normalize_percentage_rectangle(args['rectangle'])
    paths = [_file(protocol, raw, value['sha256'][Path(raw).name])[0] for raw in value['artifacts']]
    receipt = next(path for path in paths if path.name == 'annotation.json')
    annotation = _json(protocol, receipt)
    check_annotation(annotation, rectangle, paths)
    return (value['url'] == before['url'] == annotation['target']['source'] and
            value['rectangle'] == rectangle and annotation == value['annotation'] and
            value['paths'] == annotation['evidence'] and value['viewport'] == annotation['viewport'] and
            annotation['body']['value'] == value['comment'] == (str(args.get('comment') or 'Selected UI region').strip() or 'Selected UI region') and
            set(value['paths'].values()) == {str(p) for p in paths if p.suffix == '.png'})


def _taste(protocol, args, value, before):
    from ..taste_lens import VIEWPORTS, evaluate
    report = _json(protocol, value['report'])
    requested = [str(v) for v in (args.get('viewports') or ['desktop', 'phone']) if str(v) in VIEWPORTS] or ['desktop', 'phone']
    if set(report['measurements']) != set(requested) or set(report['screenshots']) != set(requested):
        return False
    for viewport, shot in report['screenshots'].items():
        path, _ = _file(protocol, shot['path'], shot['sha256'])
        from ..native_tools import NativeToolRegistry
        if NativeToolRegistry._png_dimensions(path) != VIEWPORTS[viewport]:
            return False
        if report['measurements'][viewport].get('error'):
            return False
        returned = {k:v for k,v in value['screenshots'][viewport].items() if k != 'dataUrl'}
        if returned != shot:
            return False
    if report['url'] != before['url'] or report['colorScheme'] != ('light' if args.get('colorScheme') == 'light' else 'dark'):
        return False
    for key in report:
        if key not in {'journeyReceipt', 'screenshots'} and value.get(key) != report[key]:
            return False
    measured = evaluate(report['measurements'])
    if not args.get('journey'):
        if any(report[k] != measured[k] for k in ('gate', 'score', 'counts', 'firstGlance', 'boundary')):
            return False
        if report['findings'] != measured['findings'][:24]:
            return False
    elif not report.get('journey') or not report.get('journeyReceipt'):
        return False
    return value['artifacts'] == [shot['path'] for shot in report['screenshots'].values()] + [value['report']]


def _video(protocol, args, value, before):
    from ..video_tools import VIDEO_DIGEST_SCHEMA, _timecode
    source, observed = _file(protocol, args['path'], before['source']['sha256'])
    manifest = _json(protocol, value['manifestPath'])
    output = _path(protocol, value['outputDir'])
    if args.get('outputDir') and output != _path(protocol, args['outputDir']):
        return False
    if manifest['schema'] != VIDEO_DIGEST_SCHEMA or manifest['source']['path'] != str(source) or manifest['source']['sha256'] != observed['sha256']:
        return False
    if manifest['source']['sizeBytes'] != observed['bytes'] or value['path'] != str(source):
        return False
    frames, selected, scenes = (manifest[k] for k in ('frames', 'selectedFrames', 'sceneFrames'))
    for items in (frames, selected, scenes):
        for frame in items:
            p, _ = _file(protocol, frame['path'], frame['sha256'])
            if p.parent != output or frame['timecode'] != _timecode(frame['timestampSeconds']):
                return False
    for frame in selected:
        _file(protocol, frame['selectedPath'], frame['selectedSha256'])
        if frame['selectedSha256'] != frame['sha256'] or frame['quality']['selected'] is not True:
            return False
    storyboard, _ = _file(protocol, manifest['storyboard']['path'], manifest['storyboard']['sha256'])
    if value['storyboardPath'] != str(storyboard):
        return False
    for key in ('audio', 'transcription'):
        if value[key] != manifest[key]:
            return False
        row = manifest[key]
        if row.get('path'):
            _file(protocol, row['path'], row.get('sha256'))
    expected_artifacts = [str(storyboard), *[f['selectedPath'] for f in selected],
                          *[f['path'] for f in frames], *[f['path'] for f in scenes]]
    expected_artifacts += [manifest[k]['path'] for k in ('audio', 'transcription') if manifest[k].get('path')]
    expected_artifacts += [str(output / 'video-digest.json'), str(output / 'MODEL_README.md')]
    if value['artifacts'] != expected_artifacts:
        return False
    for raw in expected_artifacts:
        path, _ = _file(protocol, raw)
        if path.parent != output:
            return False
    return (value['frameCount'] == manifest['sampling']['selectedFrameCount'] == len(selected) > 0 and
            value['sampledFrameCount'] == manifest['sampling']['uniformFrameCount'] == len(frames) and
            value['sceneFrameCount'] == manifest['sampling']['sceneFrameCount'] == len(scenes))


def _skill(protocol, args, value, before):
    from ..skill_iteration import resolve_codex_skill_file
    _, path = resolve_codex_skill_file(args)
    if str(path) != before['path'] or value['path'] != str(path) or not before['validation']['ok']:
        return False
    actual = path.read_text(encoding='utf-8')
    current = _measure_file(path)
    if value['beforeSha256'] != before['source']['sha256'] or value['afterSha256'] != current['sha256']:
        return False
    expected_sha = args.get('expectedSha256')
    if expected_sha and expected_sha.lower() != before['source']['sha256']:
        return False
    unchanged = before['original'].replace('\r\n', '\n').rstrip() == before['expected'].rstrip()
    if unchanged:
        return value.get('unchanged') is True and actual == before['original'] and value['content'] == actual
    receipt = _json(protocol, value['receiptPath'])
    backup, _ = _file(protocol, value['backupPath'])
    ledger = _path(protocol, '.agent_control/skill_revision_receipts.jsonl').read_text(encoding='utf-8')
    # Later revisions may append; this exact version must still be present.
    suffix = ledger[len(before['ledger']):] if ledger.startswith(before['ledger']) else ''
    rows = [json.loads(line) for line in suffix.splitlines() if line]
    return (value.get('unchanged') is False and actual == before['expected'] == value['content'] and
            backup.read_text(encoding='utf-8') == before['original'] and receipt in rows and
            all(value.get(k) == v for k,v in receipt.items()) and
            receipt['sessionId'] == args['sessionId'] and receipt['beforeSha256'] == before['source']['sha256'] and
            value['artifacts'] == [value['receiptPath'], value['backupPath']])


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    handlers = {'preview.screenshot':_screenshot, 'preview.annotate':_annotation,
                'preview.taste':_taste, 'video.digest':_video, 'skill.live.iterate':_skill}
    subject = name + ':' + str(args.get('path') or args.get('url'))
    retained = None
    def check(arguments, value, previous):
        nonlocal retained
        try:
            if not isinstance(value, dict) or not isinstance(previous, dict) or not handlers[name](protocol, arguments, value, previous):
                return False
            measured = {raw:_file(protocol, raw)[1] for raw in value.get('artifacts', [])}
            if retained is None:
                retained = measured
            return measured == retained
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            return False
    return [{'name':'effect-' + name.replace('.', '-'), 'observer':True, 'effect':True,
             'subjectKey':subject, 'bindSubject':lambda arguments,value,previous:subject,
             'observerTool':'fresh-owner-artifact-bytes', 'subject':dict(args),
             'expectation':'Exact retained owner artifacts, hashes, input binding and persisted receipt remain consistent',
             'check':check}]
