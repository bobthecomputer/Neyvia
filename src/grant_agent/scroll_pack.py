"""Scroll Study's untrusted pack boundary; source spans use Unicode character offsets."""
from __future__ import annotations

from .subprocess_utils import hidden_windows_subprocess_kwargs

import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator
from .scroll_study_format import TEACH as STUDY_TEACH, GRADED as STUDY_GRADED

ROOT = Path(__file__).resolve().parents[2]
TEACH = {'fact', 'explainer', 'worked', 'recap'} | STUDY_TEACH
RECALL = {'flashcard', 'cloze', 'why', 'order', 'spot'} | STUDY_GRADED
KINDS = TEACH | RECALL | {'truefalse', 'mcq'}


def is_graded(card):
    return card.get('type') not in TEACH or (card.get('type') == 'worked' and card.get('fade', 0) > 0)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in {'id', 'type', 'chapter', 'subject', 'lang', 'source', 'provenance', 'concepts', 'figure', 'media', 'status', 'answerCheck', 'symbolicCheck', 'flag'}:
                yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _safe_name(name):
    path = PurePosixPath(name)
    return bool(name) and '\\' not in name and ':' not in name and not path.is_absolute() and '..' not in path.parts


def validate_pack(pack: dict, source_texts: dict[str, str], media_root: Path | None = None) -> dict:
    errors, warnings = [], []
    def fail(card, rule, message):
        errors.append({'cardId': card, 'rule': rule, 'message': message})
    schema = json.loads((ROOT / 'config/scroll-study-pack.schema.json').read_text(encoding='utf-8'))
    for error in Draft202012Validator(schema).iter_errors(pack):
        fail(None, 'schema', f"{'/'.join(map(str, error.absolute_path))}: {error.message}")
    # Invalid structures cannot be walked safely; schema errors remain actionable.
    if errors:
        return {'ok': False, 'errors': errors, 'warnings': warnings}
    concepts = {item['id']: item for item in pack['concepts']}
    if len(concepts) != len(pack['concepts']):
        fail(None, 'concept-id', 'Concept ids must be unique.')
    sources = {item['id']: item for item in pack['sources']}
    if len(sources) != len(pack['sources']):
        fail(None, 'source-id', 'Source ids must be unique.')
    for doc, source in sources.items():
        text = source_texts.get(doc)
        if not isinstance(text, str):
            fail(None, 'source', f'Source text is missing for {doc}; re-import the source.')
        else:
            encoded = text.encode('utf-8')
            text_hash = hashlib.sha256(encoded).hexdigest()
            raw_hashes = {text_hash, hashlib.sha256(b'\xef\xbb\xbf' + encoded).hexdigest()}
            if source['sha256'] not in raw_hashes or source.get('textSha256', text_hash) != text_hash:
                fail(None, 'source-hash', f'Source SHA-256 differs for {doc}; re-import and regenerate spans.')
    visiting, visited = set(), set()
    def visit(cid):
        if cid in visiting:
            fail(None, 'dag', f'Prerequisite cycle includes {cid}.')
            return
        if cid in visited:
            return
        visiting.add(cid)
        for prereq in concepts[cid]['prereqs']:
            if prereq not in concepts:
                fail(None, 'dag', f'{cid} requires missing concept {prereq}.')
            else:
                visit(prereq)
        visiting.remove(cid)
        visited.add(cid)
    for cid in concepts:
        visit(cid)
    taught = {cid for card in pack['cards'] if card['type'] in TEACH and not is_graded(card) for cid in card['concepts']['teaches']}
    for cid in concepts:
        if cid not in taught:
            fail(None, 'teach', f'Concept {cid} has no teaching card.')
    seen_ids, math_items, chapters = set(), [], {}
    for card in pack['cards']:
        cid, kind = card['id'], card['type']
        if cid in seen_ids:
            fail(cid, 'card-id', 'Card id is duplicated.')
        seen_ids.add(cid)
        if not re.fullmatch(r'.+\.' + re.escape(kind) + r'\.\d{2,}(?:\.f[12])?', cid):
            fail(cid, 'card-id', 'Expected stable <concept>.<type>.<nn> id (optional .f1/.f2).')
        for role, refs in card['concepts'].items():
            for ref in refs:
                if ref not in concepts:
                    fail(cid, 'concept-reference', f'{role} references missing concept {ref}.')
                if role in {'requires', 'tests'} and ref not in taught:
                    fail(cid, 'teach', f'{role} references {ref} with no teaching card.')
        graded = is_graded(card)
        if graded and set(card['concepts']['tests']) & set(card['concepts']['teaches']):
            fail(cid, 'graded-overlap', 'A graded card cannot test what it teaches.')
        if graded and not card['concepts']['tests']:
            fail(cid, 'graded-tests', 'A graded card must identify the concepts it tests.')
        if graded and not card.get('explanation', '').strip():
            fail(cid, 'explanation', 'Every graded card needs an explanation.')
        if kind != 'recap':
            source = card.get('source', {})
            text = source_texts.get(source.get('doc'))
            span = source.get('span', [])
            if source.get('doc') not in sources or not isinstance(text, str) or len(span) != 2 or not 0 <= span[0] < span[1] <= len(text):
                fail(cid, 'source-span', 'Source span must be nonempty and inside the hashed source text.')
        strings = list(_strings(card))
        words = len(re.findall(r'\S+', ' '.join(strings)))
        budget = 60 if kind == 'fact' else 120 if kind == 'explainer' else None
        if budget and words > budget:
            fail(cid, 'length', f'{kind} contains {words} words; maximum {budget}.')
        if words > max(20, card['seconds'] * 4):
            fail(cid, 'read-time', 'Text exceeds the 240 words/minute reading budget for its seconds.')
        if kind == 'mcq':
            options = card['options']
            if sum(option.get('correct', False) is True for option in options) != 1:
                fail(cid, 'mcq', 'MCQ must have exactly one correct option.')
            if any(not option.get('correct') and not option.get('why', '').strip() for option in options):
                fail(cid, 'mcq', 'Every distractor needs a why-not explanation.')
            if len({option['text'].strip().casefold() for option in options}) != len(options):
                fail(cid, 'mcq', 'MCQ options must be distinct.')
        if kind == 'spot' and card['spot']['wrong'] >= len(card['spot']['lines']):
            fail(cid, 'spot', 'Wrong-line index is outside the solution.')
        if kind == 'worked' and card.get('fade', 0) > 0:
            base_id = cid.rsplit('.f', 1)[0]
            if not cid.endswith(f".f{card['fade']}") or not any(c['id'] == base_id and c.get('fade', 0) == 0 for c in pack['cards']):
                fail(cid, 'fade', 'A faded worked card must reference its full .f0-free base card.')
        figures = card.get('media', []) + ([card['figure']] if card.get('figure') else [])
        if len(set(figures)) > 1:
            fail(cid, 'figure', 'At most one meaningful figure is allowed per card.')
        for figure in figures:
            if not _safe_name(figure) or not figure.startswith('media/') or Path(figure).suffix.lower() not in {'.svg', '.png'}:
                fail(cid, 'figure', 'Figure must be a safe media/ SVG or PNG path.')
            elif media_root is None:
                fail(cid, 'figure', 'Media root is required to verify a referenced figure.')
            else:
                target = (media_root / figure).resolve()
                if not target.is_relative_to(media_root.resolve()) or not target.is_file():
                    fail(cid, 'figure', f'Missing or unsafe figure: {figure}.')
                elif target.suffix.lower() == '.svg':
                    svg = target.read_text(encoding='utf-8')
                    if re.search(r'<\s*(script|foreignObject)\b|\bon\w+\s*=|(?:href|src)\s*=\s*[\"\']\s*(?:https?:|javascript:|data:)', svg, re.I):
                        fail(cid, 'figure', 'SVG contains active or external content.')
        for string in strings:
            for match in re.finditer(r'(?<!\\)\$\$([\s\S]+?)(?<!\\)\$\$|(?<![\\$])\$(?!\$)(.+?)(?<!\\)\$(?!\$)|\\\[([\s\S]+?)\\\]|\\\((.+?)\\\)', string):
                math_items.append({'cardId': cid, 'tex': next(group for group in match.groups() if group is not None)})
            stripped = re.sub(r'(?<!\\)\$\$[\s\S]+?(?<!\\)\$\$|(?<![\\$])\$(?!\$).+?(?<!\\)\$(?!\$)', '', string)
            if re.search(r'(?<!\\)\$', stripped):
                fail(cid, 'math', 'Unclosed math delimiter.')
        if graded:
            chapters.setdefault(card['chapter'], []).append(card)
    for chapter, cards in chapters.items():
        recall = sum(c['type'] in RECALL or (c['type'] == 'worked' and c.get('fade', 0) > 0) for c in cards)
        if recall / len(cards) < .5:
            fail(None, 'mix', f'{chapter}: recall-type graded cards must be at least 50%.')
        if sum(c['type'] == 'truefalse' for c in cards) / len(cards) > .2:
            fail(None, 'mix', f'{chapter}: true/false cards must be at most 20%.')
    if pack['meta'].get('studyFormat') == 'paul-seven-part.v1':
        from .scroll_study_format import validate_format
        errors.extend(validate_format(pack, source_texts))
    if math_items:
        node = shutil.which('node')
        if not node:
            fail(None, 'math-parser', 'Node is required for KaTeX validation.')
        else:
            try:
                checked = subprocess.run([node, str(ROOT / 'scripts/scroll_math_validate.mjs')], input=json.dumps(math_items), text=True, capture_output=True, timeout=30, check=True, **hidden_windows_subprocess_kwargs())
                errors.extend(json.loads(checked.stdout))
            except (subprocess.SubprocessError, ValueError) as error:
                fail(None, 'math-parser', f'KaTeX validation could not complete: {type(error).__name__}.')
    return {'ok': not errors, 'errors': errors, 'warnings': warnings}


def write_scrollpack(path: Path, pack: dict, source_texts: dict[str, str], media_root: Path | None = None) -> dict:
    result = validate_pack(pack, source_texts, media_root)
    if not result['ok']:
        raise ValueError(json.dumps(result))
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        def member(name, body):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, body)
        member('pack.json', json.dumps(pack, ensure_ascii=False, sort_keys=True))
        # Hash filenames instead of accepting source ids as archive paths.
        index = {}
        for doc, text in sorted(source_texts.items()):
            name = 'sources/' + hashlib.sha256(doc.encode()).hexdigest() + '.txt'
            member(name, text.encode('utf-8'))
            index[doc] = name
        member('sources/index.json', json.dumps(index, sort_keys=True))
        for name in sorted({m for c in pack['cards'] for m in c.get('media', []) + ([c['figure']] if c.get('figure') else [])}):
            member(name, (media_root / name).read_bytes())
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size, 'cards': len(pack['cards'])}


def read_scrollpack(path: Path) -> tuple[dict, dict[str, str]]:
    """Read without extraction; reject bombs, symlinks, duplicates and unsafe paths."""
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 10000 or sum(item.file_size for item in infos) > 50_000_000:
            raise ValueError('Pack exceeds archive limits.')
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or any(not _safe_name(item.filename) or not _safe_name(item.orig_filename) for item in infos):
            raise ValueError('Duplicate or unsafe archive path.')
        if any((item.external_attr >> 16) & 0o170000 == 0o120000 for item in infos):
            raise ValueError('Archive symlinks are not allowed.')
        pack = json.loads(archive.read('pack.json'))
        index = json.loads(archive.read('sources/index.json'))
        if not isinstance(index, dict) or any(not isinstance(name, str) or not _safe_name(name) or not name.startswith('sources/') or name == 'sources/index.json' for name in index.values()):
            raise ValueError('Unsafe source index.')
        sources = {doc: archive.read(name).decode('utf-8') for doc, name in index.items()}
        import tempfile
        with tempfile.TemporaryDirectory(prefix='scroll-media-') as directory:
            root = Path(directory)
            for name in names:
                if name.startswith('media/') and not name.endswith('/'):
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))
            result = validate_pack(pack, sources, root)
        if not result['ok']:
            raise ValueError(json.dumps(result))
        return pack, sources
