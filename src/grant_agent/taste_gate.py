"""Host-owned C13 draft, rendered difference and targeted repair completion gate.

Only host invocations create review evidence. HTML annotations and model-provided
round counters are never completion evidence. Restored rounds retain host seals.
"""
from __future__ import annotations

from copy import deepcopy
from html.parser import HTMLParser
import difflib
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
from urllib.parse import urlparse

from .subprocess_utils import hidden_windows_subprocess_kwargs
from .taste_model import invoke, CRITIQUE_SCHEMA

REPO = Path(__file__).resolve().parents[2]
AXES = ('fidelity', 'concept', 'content', 'density', 'illustration', 'motion', 'type', 'color', 'spacing', 'finish')
PRIMARY = {'paper', 'archive', 'author-repo'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def driver_view(report):
    """Every control/effect remains visible; omit repeated file hashes from prompts."""
    return {'engine':report.get('engine'),'passed':report['passed'],'errors':report.get('errors',[]),
            'inputProtocol': {'cross':report.get('crossProtocol','Press/start 8px before the left boundary, move across to 8px after it, release.')+' Touch retains the starting element as its event target; pointer capture also retargets to the capture element. Detect boundaries from clientX/clientY plus actual rectangles or hit-testing, not pointerenter or e.target.closest alone.',
                              'drag':'Press at control center and move to a distinct point inside a containing target, or the center of an external target, then release. data-c13-path can declare 2–16 normalized [x,y] points relative to the actual control, within -.25..1.25, starting inside it; the driver sends each segment through real browser input. Use this for advertised perpendicular or edge-crossing gestures, never as an assertion of success.',
                              'hold':'Hold for 900ms, capture the dwell-open state, stroke toward a distinct point if a target/path is declared, then capture release. A second stroke without intentional delay captures quick-result; actual elapsedMs and observedChanges are recorded. Without a target hold remains stationary. gestureStates.input records delivered start/end, moves and holdMs: dwell-open precedes movement, whereas distinct dwell-result endpoints establish a directional stroke. Do not infer a stationary release from a missing data-c13-path when a target is declared. Keyboard uses Space unless data-c13-key overrides.',
                              'activate':'Keyboard uses Space for buttons/focusable controls and Enter for links; data-c13-key can declare the real equivalent.'},
            'motion':report.get('motion'),
            'variants':[{**{key:variant.get(key) for key in ('viewport','theme','passed','coverage_complete','overflow','sections','errors','capabilities')},
                         'controls':[{'selector':control['id'],'label':control.get('label'),'action':control.get('action'),'path':control.get('path'),'target':control.get('target'),
                                      'dead':control.get('dead'),'undecided':control.get('undecided'),
                                      'modes':[{key:mode.get(key) for key in ('mode','action','effect','error','status','hit','preparation','observedChanges','acquisition','gestureStates','gestureInput')} for mode in control.get('modes',[])]}
                                     for control in variant.get('controls',[])]} for variant in report.get('variants',[])]}


class Sections(HTMLParser):
    """Associate credits with the visible element's own semantic section."""
    def __init__(self, source):
        super().__init__()
        self.stack, self.records = [], []
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag in {'section','article','figure'}:
            record = {'tag':tag,'depth':len(self.stack),'selectors':set(),'text':[],'heading':[],'links':set(),'linkTitles':{}}
            self.records.append(record)
        for record in self.records:
            if record['depth'] <= len(self.stack) and record.get('open',True):
                if attrs.get('id'): record['selectors'].add('#'+attrs['id'])
                record['selectors'].update('.'+name for name in attrs.get('class','').split())
                if attrs.get('href'): record['links'].add(attrs['href'])
                if tag == 'a' and attrs.get('href'):
                    record['activeLink'] = attrs['href']
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag == 'a':
            for record in self.records: record.pop('activeLink',None)
        if tag not in self.stack:
            return
        depth = len(self.stack)-1-self.stack[::-1].index(tag)
        for record in self.records:
            if record['depth'] >= depth:
                record['open'] = False
        self.stack = self.stack[:depth]

    def handle_data(self, data):
        if any(tag in self.stack for tag in ('script','style')):
            return
        for record in self.records:
            if record.get('open',True):
                record['text'].append(data)
                if record.get('activeLink'):
                    record['linkTitles'].setdefault(record['activeLink'],[]).append(data)
                if self.stack and self.stack[-1] in {'h1','h2','h3'}:record['heading'].append(data)

    @staticmethod
    def citation_title(record, source):
        title = ' '.join(record['linkTitles'].get(source,[])).strip()
        if re.fullmatch(r'(?:ACM\s+)?DOI|(?:primary\s+)?link|(?:(?:CHI|UIST|ACM)\s+)?(?:paper|source)(?:\s+PDF)?',title,re.I):
            # A transport label is not a paper title. Prefer the actual visible
            # bibliographic quotation in the owning section, not a renamed guess.
            content=' '.join(record['text'])
            citation=content[content.lower().rfind('source:'):] if 'source:' in content.lower() else ''
            quoted=re.findall(r'[“"]([^”"]{12,})[”"]',citation)
            return quoted[-1].strip().rstrip(',.;') if quoted else ' '.join(record['heading']).strip()
        if not title or re.fullmatch(r'(?:read\s+)?(?:the\s+)?(?:(?:primary|original)\s+)?(?:paper|source)(?:\s*\(?PDF\)?)?',title,re.I):
            return ' '.join(record['heading']).strip()
        return title

    def paper_title(self, element):
        selectors = re.findall(r'[#.][\w-]+',element['selector'])
        for record in reversed(self.records):
            if selectors and all(selector in record['selectors'] for selector in selectors):
                title = self.citation_title(record,element['primarySource']) if element['primarySource'] in record['links'] else ''
                if title: return title
        return element['name']

    def credited(self, element):
        selectors = re.findall(r'[#.][\w-]+',element['selector'])
        for record in reversed(self.records):
            if not selectors or not all(selector in record['selectors'] for selector in selectors):
                continue
            content = ' '.join(record['text']).lower()
            if (element['primarySource'] in record['links'] and element['author'].lower() in content
                    and element['venue'].lower() in content and str(element['year']) in content):
                return True
        return False


class TasteGate:
    def __init__(self, root, since, *, policy=None):
        self.root = Path(root).resolve() if root else None
        self.since = since
        policy_path = os.environ.get('NEYVIA_TASTE_POLICY')
        self.policy = policy if policy is not None else (json.loads(Path(policy_path).read_text(encoding='utf-8')) if policy_path else {})
        self.rounds, self.anchor_reports, self.repairs = {}, {}, {}
        self.touched_html = set()
        self.concept, self.research = None, None
        self.research_addenda = []
        self.started = time.monotonic()
        self._seal_key = secrets.token_bytes(32)
        self.manual_overlay = self._select_manual_overlay()
        self.model_budget = None  # Runtime authority; never serialized into sealed policy.
        self.anchor_projections = {}

    def _lesson_registry(self):
        return self.root/'.neyvia/taste/admitted-manuals/index.json' if self.root else None

    def _select_manual_overlay(self):
        """Capture an admitted manual only at a new host/task boundary."""
        registry=self._lesson_registry()
        if not registry or not registry.is_file(): return None
        from .taste_judge import admit_lesson
        try:
            data=json.loads(registry.read_text(encoding='utf-8'))
            if data.get('schema')!='neyvia.admitted-taste-manuals.v1': return None
            records=data['admissions']
            for record in reversed(records):
                if (digest(record['sourceManualPath'])==record['sourceManualSha256']
                        and digest(record['manualOverlay'])==record['manualOverlaySha256']
                        and admit_lesson(record['admissionEvidence'])['accepted']):
                    return deepcopy(record)
        except (OSError,KeyError,TypeError,ValueError):
            pass
        return None

    def _seal(self, value):
        return hmac.new(self._seal_key, canonical({k: v for k, v in value.items() if k != 'hostSeal'}), hashlib.sha256).hexdigest()

    def export_state(self):
        """For the host's persisted completion bus, never the model projection."""
        return {'schema': 'neyvia.taste-host-state.v1', 'sealKey': self._seal_key.hex(),
                'policy': deepcopy(self.policy), 'rounds': deepcopy(self.rounds),
                'anchorReports': deepcopy(self.anchor_reports),
                'manualOverlay':deepcopy(self.manual_overlay),
                'researchAddenda':deepcopy(self.research_addenda),
                'touchedHtml': sorted(self.touched_html),
                'concept': deepcopy(self.concept), 'research': deepcopy(self.research), 'repairs': deepcopy(self.repairs)}

    def restore_state(self, state):
        if state.get('schema') != 'neyvia.taste-host-state.v1':
            raise ValueError('Unsealed legacy taste state cannot complete a task; review again')
        self._seal_key = bytes.fromhex(state['sealKey'])
        self.policy = deepcopy(state['policy'])
        self.rounds, self.repairs = deepcopy(state['rounds']), deepcopy(state.get('repairs', {}))
        self.anchor_reports = deepcopy(state.get('anchorReports',{}))
        self.manual_overlay=deepcopy(state.get('manualOverlay'))
        self.research_addenda=deepcopy(state.get('researchAddenda', []))
        self.touched_html = set(state.get('touchedHtml', []))
        self.concept, self.research = deepcopy(state.get('concept')), deepcopy(state.get('research'))
        for records in self.rounds.values():
            for row in records:
                if not hmac.compare_digest(row.get('hostSeal', ''), self._seal(row)):
                    raise ValueError('Restored taste review seal mismatch')

    def files(self):
        if not self.root:
            return []
        if self.policy.get('files'):
            return [self.path(name) for name in self.policy['files']]
        observed = {self.path(name) for name in self.touched_html}
        from .neyvia_language import task_artifacts
        files, complete = task_artifacts(self.root, self.since, suffixes={'.html', '.htm'})
        if not complete:
            raise ValueError('Taste artifact scan incomplete; narrow the task root')
        observed.update(files)
        return sorted(observed)

    def observe_write(self, name):
        if isinstance(name,str) and Path(name).suffix.lower()=='.html':
            path=self.path(name)
            self.touched_html.add(str(path.relative_to(self.root)))

    def path(self, name):
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root) or path.suffix.lower() != '.html':
            raise ValueError('Taste review requires an HTML deliverable inside the task root')
        return path

    def out(self):
        path = Path(self.policy.get('evidenceDir', self.root / '.neyvia/taste')).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _fresh_folder(self, path):
        destination,attempt=Path(path),1
        while destination.exists():
            attempt+=1
            destination=Path(str(path)+'-attempt-'+str(attempt))
        destination.mkdir(parents=True,exist_ok=False)
        return destination

    def manual(self):
        path = Path(self.policy.get('manual', str(REPO / 'manuals/cl/taste.cl')))
        if self.manual_overlay and path.resolve()==Path(self.manual_overlay['sourceManualPath']).resolve():
            if digest(path)!=self.manual_overlay['sourceManualSha256'] or digest(self.manual_overlay['manualOverlay'])!=self.manual_overlay['manualOverlaySha256']:
                raise ValueError('Admitted manual lineage changed; rerun C9 admission')
            path=Path(self.manual_overlay['manualOverlay'])
        if not path.is_file():
            raise ValueError('C13 taste manual missing: ' + str(path))
        return path, path.read_text(encoding='utf-8')

    def _stamp(self, value):
        result = {'record': deepcopy(value), 'writtenAt': time.time(), 'briefSha256': hashlib.sha256(self.policy.get('brief', '').encode()).hexdigest()}
        result['hostSeal'] = self._seal(result)
        return result

    def record_concept(self, record):
        if any(p.exists() for p in self.files()):
            raise ValueError('Concept must be recorded before the first deliverable write')
        if (not isinstance(record, dict) or not all(record.get(key) for key in ('idea', 'subject', 'bold', 'quiet', 'rejected'))
                or len(record['idea'].split()) > 25 or len(set(record.get('vernacular', []))) < 3):
            raise ValueError('Concept requires one idea <=25 words, subject, three or more vernacular terms the page uses, bold, quiet, rejected defaults')
        self.concept = self._stamp(record)
        save(self.out() / 'concept.json', self.concept)
        return deepcopy(self.concept['record'])

    def record_research(self, rows):
        if any(p.exists() for p in self.files()):
            raise ValueError('Research must precede the draft')
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get('name') for row in rows):
            raise ValueError('Research requires named candidate records')
        self.research = self._stamp(rows)
        save(self.out() / 'research.json', self.research)
        return {'candidates': len(rows), 'used': sum(bool(row.get('used')) for row in rows)}

    def record_research_addendum(self, name, folder):
        """Bind repair research without changing the pre-layout candidate stamp."""
        path, folder = self.path(name), Path(folder).resolve()
        if not folder.is_relative_to(self.out().parent.resolve()):
            raise ValueError('Repair research must belong to this task evidence root')
        previous = self.rounds.get(str(path), [])
        if not previous:
            raise ValueError('Repair research requires an observed difference first')
        eligible = {row['rowId'] for row in previous[-1]['critique']['differences']
                    if row['cause'] == 'research' and row['gap'] >= 2}
        response = json.loads((folder/'response.json').read_text(encoding='utf-8'))
        usage = json.loads((folder/'usage.json').read_text(encoding='utf-8'))
        events = [json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        searched = [event['item'] for event in events if event.get('type') == 'item.completed'
                    and event.get('item',{}).get('type') == 'web_search' and event['item'].get('results')]
        if usage.get('model') != self.policy.get('model','gpt-6-luna') or usage.get('exitCode') != 0 or usage.get('timedOut') or not usage.get('searchEnabled') or not searched:
            raise ValueError('Repair research requires a successful actual configured-model web-search call')
        def result_urls(value):
            if isinstance(value, dict):
                return ({value['url']} if isinstance(value.get('url'), str) else set()).union(*(result_urls(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(result_urls(item) for item in value))
            return set()
        searched_urls = result_urls(searched)
        rows = response['alternatives']
        if not rows or any(row['rowId'] not in eligible or not row['primarySource'].startswith('https://')
                           or row['primarySource'] not in searched_urls
                           or not all(row.get(key) for key in ('name','author','venue','year','mechanism','implementation','evidence')) for row in rows):
            raise ValueError('Repair alternatives must map to research rows and actual searched primary URLs')
        from .taste_sources import verify_papers
        registrations=verify_papers([{'name':r['name'],'source':r['primarySource'],'used':True} for r in rows],
                                   self.out()/'citation-metadata',self.policy.get('sourceTimeoutSec',8))
        invalid=[r for r in registrations if r['matches'] is not True]
        if invalid:
            raise ValueError('Repair primary-source registration mismatch/unverified: '+json.dumps(
                [{'claimed':r['name'],'url':r['source'],'registered':r.get('registered',{}).get('title'),
                  'reason':r.get('reason')} for r in invalid]))
        files = [{'path':str(folder/file), 'sha256':digest(folder/file)}
                 for file in ('response.json','usage.json','events.jsonl')]
        record = {'path':str(path),'afterRound':previous[-1]['round'],'alternatives':rows,'evidenceFiles':files}
        record['hostSeal'] = self._seal(record)
        if not any(item['evidenceFiles'] == files for item in self.research_addenda):
            self.research_addenda.append(record)
        save(self.out()/'research-addenda.json', self.research_addenda)
        return {'alternatives':len(rows),'afterRound':record['afterRound'],'implementationProven':False}

    def _valid_research_addenda(self):
        return [record for record in self.research_addenda
                if hmac.compare_digest(record.get('hostSeal',''), self._seal(record))
                and all(Path(file['path']).is_file() and digest(file['path']) == file['sha256'] for file in record['evidenceFiles'])]

    def commonness(self):
        path = Path(self.policy.get('commonness', REPO / 'config/c13/commonness.json'))
        return path, json.loads(path.read_text(encoding='utf-8'))['interactions']

    def _common(self, name):
        _, groups = self.commonness()
        normalized = re.sub(r'[^a-z0-9]+', ' ', name.lower()).strip()
        for group in groups:
            for alias in [group['name'], *group.get('aliases', [])]:
                alias = re.sub(r'[^a-z0-9]+', ' ', alias.lower()).strip()
                if normalized == alias or re.search(r'\b' + re.escape(alias) + r'\b', normalized):
                    return group['name']
        return None

    def render(self, path, out, *, capture_only=False):
        port = int(self.policy.get('port', 0))
        if port not in range(48801, 48810):
            raise ValueError('C13 requires an explicit assigned port 48801-48809')
        if self.policy.get('contextMode')=='bounded':
            # Resume a failed *text* stage without re-exercising unchanged HTML.
            # Changed artifacts never match this cache; raw failures are retained.
            scope='reference-capture' if capture_only else 'candidate-interactions'
            candidates=([*self.out().glob('anchor-'+path.stem+'*/report.json'),
                         *(REPO/'proof/r10').glob('*/T*/evidence/anchor-'+path.stem+'*/report.json')]
                        if capture_only else (self.out()/path.stem).glob('round-*/render/report.json'))
            for prior in sorted(candidates,reverse=True):
                try:
                    report=json.loads(prior.read_text(encoding='utf-8'))
                    if (report.get('html_sha256')!=digest(path) or report.get('scope')!=scope or
                        (not capture_only and report.get('observer_sha256')!=digest(REPO/'scripts/c13_observed.mjs')) or
                        report.get('engine')!='obscura' or report.get('adapter_sha256')!=digest(REPO/'src/grant_agent/browser_render_profile.js')):
                        continue
                    self._image_set(report,'Cached render')
                    self._critique_images(report,'Cached render',actions=not capture_only)
                    report={**report,'reusedFrom':str(prior),'reusedReportSha256':digest(prior)}
                    save(out/'report.json',report)
                    return report
                except (OSError,ValueError,KeyError):
                    continue
        command = ['node', str(REPO / 'scripts/c13_render.mjs'), '--html', str(path), '--out', str(out), '--port', str(port),
                   '--engine-port', str(self.policy.get('enginePort', port+1))]
        if capture_only:
            command += ['--capture-only', 'true', '--reference-only', 'true']
        result = subprocess.run(command,
                                capture_output=True, text=True, encoding='utf-8', timeout=self.policy.get('renderTimeoutSec', 600),
                                **hidden_windows_subprocess_kwargs())
        if not (out / 'report.json').is_file():
            raise ValueError('Neyvia browser render failed: ' + result.stderr[-1200:])
        report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
        if report.get('html_sha256') != digest(path) or 'obscura' not in report.get('engine', '').lower():
            raise ValueError('Render must be hash-bound and produced by Neyvia Obscura')
        self._image_set(report, 'Rendered artifact')
        return report

    def record_repair(self, name, edits):
        """Attest exact edits after workspace.patch, against prior CL difference rows."""
        path = self.path(name)
        previous = self.rounds.get(str(path), [])
        pending = self.repairs.get('triage:' + str(path))
        if pending:
            if pending.get('hostSeal') != self._seal(pending):
                raise ValueError('Host-bound triage evidence changed')
            previous = [pending]
        if not previous:
            raise ValueError('A repair requires a rendered draft and difference report')
        prior = previous[-1]
        old = (Path(prior['folder']) / 'artifact.html').read_text(encoding='utf-8')
        expected = old
        by_id = {row['rowId']: row for row in prior['critique']['differences']}
        touched, spans, changed = [], [], 0
        if not edits:
            raise ValueError('Unchanged output cannot count as a repair')
        for edit in edits:
            row = by_id.get(edit.get('rowId'))
            if not row or row['cause'] == 'keep' or edit.get('old') == edit.get('new'):
                raise ValueError('Each repair must name an actionable prior difference row')
            if not edit.get('old') or expected.count(edit['old']) != 1:
                raise ValueError('Each repair must replace one unique nonempty substring')
            if old.count(edit['old']) != 1:
                raise ValueError('Repair OLD must belong to the reviewed source, not another edit')
            start = old.index(edit['old']); end = start + len(edit['old'])
            if any(start < right and end > left for left,right in spans):
                raise ValueError('Repair spans in the reviewed source must not overlap')
            spans.append((start,end))
            # Exact mapped regions give a conservative source-change bound. A
            # whole-page character diff is quadratic on repetitive inline JS.
            matcher = difflib.SequenceMatcher(None, edit['old'], edit['new'], autojunk=False)
            changed += sum(max(b-a,d-c) for tag,a,b,c,d in matcher.get_opcodes() if tag != 'equal')
            expected = expected.replace(edit['old'], edit['new'], 1)
            touched.append(edit['rowId'])
        if expected != path.read_text(encoding='utf-8'):
            raise ValueError('Artifact contains edits not mapped to the difference report')
        old_lines, new_lines = old.splitlines(), expected.splitlines()
        lines = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
        changed_lines = sum(max(b-a, d-c) for tag,a,b,c,d in lines.get_opcodes() if tag != 'equal')
        record = {'beforeSha256': prior['sha256'], 'afterSha256': digest(path), 'rowsTouched': touched,
                  'charChurn': changed / max(1, len(old)), 'lineChurn': changed_lines / max(1, len(old_lines)),
                  'charChurnBasis':'Conservative sum within disjoint mapped regions of the reviewed source',
                  'unmapped': 0, 'edits': deepcopy(edits)}
        record['targeted'] = record['charChurn'] <= .5 and record['lineChurn'] <= .5
        inherited = pending.get('priorChange') if pending else None
        if inherited:
            record['beforeSha256'] = inherited['beforeSha256']
            record['charChurn'] += inherited['charChurn']
            record['lineChurn'] += inherited['lineChurn']
            record['rowsTouched'] = list(dict.fromkeys(inherited['rowsTouched'] + record['rowsTouched']))
            record['targeted'] = inherited['targeted'] and record['charChurn'] <= .5 and record['lineChurn'] <= .5
        record['hostSeal'] = self._seal(record)
        self.repairs[str(path)] = record
        self.repairs.pop('triage:' + str(path), None)
        save(self.out() / path.stem / ('repair-' + str(len(previous)) + '.json'), record)
        return deepcopy(record)

    def _critique_checks(self, critique):
        quality = critique.get('quality')
        if isinstance(quality, bool) or not isinstance(quality, (int,float)) or not math.isfinite(quality) or not 0 <= quality <= 100:
            raise ValueError('Critic quality must be finite in 0..100')
        rubric = critique.get('rubric', [])
        if len(rubric) != len(AXES) or {row.get('axis') for row in rubric} != set(AXES):
            raise ValueError('Rubric-first judgement requires exactly the ten manual axes')
        for row in rubric:
            if (isinstance(row['score'], bool) or not isinstance(row['score'], (int,float)) or not 0 <= row['score'] <= 4
                    or not row['evidence'] or not all(isinstance(ref,str) and ref.strip() for ref in row['evidence'])):
                raise ValueError('Every rubric score requires finite 0..4 and image/region evidence')
        differences = critique.get('differences', [])
        ids = [row['rowId'] for row in differences]
        if not differences or len(set(ids)) != len(ids):
            raise ValueError('Difference report requires unique actionable CL row IDs')
        for row in differences:
            if not isinstance(row['rowId'],str) or not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]{0,63}',row['rowId']):
                raise ValueError('Difference rowId must be one safe CL identifier')
            if row['axis'] not in AXES or not 0 <= row['gap'] <= 4 or len(row['evidence']) < 2 or not row['ours'] or not row['better']:
                raise ValueError('Each difference must compare observed sides and cite both')
            if row['cause'] != 'keep' and (not row['repair'] or not row['selector']):
                raise ValueError('Actionable differences must name one targeted repair and selector')
            if row['scope'] == 'page' and row['cause'] not in {'concept', 'research', 'keep'}:
                raise ValueError('Page repair allowed only for concept/research')
        for element in critique.get('rareElements', []):
            if not element.get('primarySource','').startswith('https://'):
                raise ValueError('rareElements.primarySource must be the exact HTTPS href, never a prose citation; preserve numeric judgement')

    def _difference_cl(self, path, anchor, number, critique):
        rows = critique['differences']
        lines = [f'S taste.diff #{len(rows)} against=anchor:{json.dumps(str(anchor))} round={number} ours={json.dumps(str(path))}']
        for row in rows:
            fields = [row[key] for key in ('axis','gap','ours','better','evidence','cause','repair','scope')]
            lines.append('E ' + ' '.join(json.dumps(value, ensure_ascii=False) for value in fields) + ' -- rowId=' + row['rowId'])
        for index, lesson in enumerate(critique['lessons'][:3]):
            lines.append('M taste ' + json.dumps(lesson) + f' src:taste-diff-{number}.cl#{min(index+1,len(rows))} check:"C taste.make goal" author:'+self.policy.get('model','gpt-6-luna')+' state:quarantine')
        return '\n'.join(lines) + '\n'

    def _inspection_checks(self, critique, inspections):
        if any('noteId' not in note for record in inspections for note in record['observations']):
            raise ValueError('Review predates explicit inspection dispositions; review again')
        expected = {note['noteId'] for record in inspections for note in record['observations']}
        if not expected: return
        responses = critique.get('inspectionResponses',[])
        if len(responses)!=len(expected) or {row.get('noteId') for row in responses}!=expected:
            observed = {str(row.get('noteId')) for row in responses}
            raise ValueError('Explicit dispositions require exactly '+json.dumps(sorted(expected))+
                             '; missing='+json.dumps(sorted(expected-observed))+
                             '; unexpected='+json.dumps(sorted(observed-expected)))
        differences = {row['rowId']:row for row in critique['differences']}
        for response in responses:
            if len(response.get('evidence',[])) < 2:
                raise ValueError('Inspection disposition requires current render and source/effect evidence')
            if response.get('verdict') not in {'confirmed','resolved','uncertain'}:
                raise ValueError('Invalid inspection disposition')
            if response['verdict']!='resolved':
                row=differences.get(response.get('differenceRowId'))
                if not row or row['gap']<2 or row['cause']=='keep':
                    raise ValueError('Confirmed or uncertain inspection finding requires its differenceRowId to name a non-keep targeted row with gap>=2')

    def _invoke_critique(self, prompt, folder, images, inspections=()):
        """Retry only invalid CL/schema contracts; retain every costly attempt."""
        previous, first, attempts = None, None, []
        maximum = max(1,min(3,int(self.policy.get('critiqueAttempts',3))))
        schema=deepcopy(CRITIQUE_SCHEMA)
        note_ids=sorted({note['noteId'] for record in inspections for note in record['observations']})
        if inspections:
            schema['required'].append('inspectionResponses')
            schema['properties']['inspectionResponses']={'type':'array','minItems':len(note_ids),'maxItems':len(note_ids),'items':{
                'type':'object','additionalProperties':False,
                'required':['noteId','verdict','evidence','differenceRowId'],
                'properties':{'noteId':{'type':'string','enum':note_ids},'verdict':{'type':'string','enum':['confirmed','resolved','uncertain']},
                              'evidence':{'type':'array','minItems':2,'items':{'type':'string'}},'differenceRowId':{'type':'string'}}}}
        for number in range(1,maximum+1):
            destination = folder/('attempt-'+str(number))
            # A resumed failed review does not overwrite the failed model call.
            suffix = 1
            while (destination/'response.json').exists():
                suffix += 1
                destination=folder/('attempt-'+str(number)+'-resume-'+str(suffix))
            question=('CURRENT REQUIRED INSPECTION IDS (exactly once each, no historical IDs): '+json.dumps(note_ids)+'\n' if note_ids else '')+prompt
            if previous:
                question += ('\nHOST CONTRACT VALIDATION FAILED:\n'+previous['error']+
                             '\nCorrect ONLY the schema/CL contract errors in your response below. This is NOT a '
                             'new quality judgement: preserve passes, briefPasses, quality, anchorVerdict and the '
                             'numeric score for every existing rubric axis. Scope page is allowed only for cause '
                             'concept/research; a global color/type/finish edit is scope section, not a page rewrite. '
                             'Preserve actual observed defects. Return the full corrected record.\nINVALID RESPONSE:\n'+
                             json.dumps(previous['response']))
            kwargs={'bounded':True, 'model':self.policy.get('model','gpt-6-luna'),
                    'budget':self.model_budget} if self.policy.get('contextMode')=='bounded' else {}
            critique,receipt=invoke(question,destination,schema,images=images,
                                    timeout=self.policy.get('modelTimeoutSec',1800),**kwargs)
            attempts.append({'folder':str(destination),'receipt':receipt})
            if first is None: first=deepcopy(critique)
            try:
                self._critique_checks(critique)
                self._inspection_checks(critique,inspections)
                if previous:
                    for key in ('passes','briefPasses','quality','anchorVerdict'):
                        if key in first and critique[key]!=first[key]:
                            raise ValueError('Contract repair changed quality verdict: '+key)
                    initial_scores={row['axis']:row['score'] for row in first.get('rubric',[]) if 'axis' in row and 'score' in row}
                    if any(row['score']!=initial_scores.get(row['axis'],row['score']) for row in critique['rubric']):
                        raise ValueError('Contract repair changed an existing rubric score')
            except (KeyError,TypeError,ValueError) as exc:
                previous={'error':str(exc),'response':critique}
                save(destination/'contract-error.json',{'error':str(exc),'qualityRetry':False})
                if number==maximum:
                    raise ValueError('Critique contract invalid after '+str(maximum)+' recorded attempts: '+str(exc)) from exc
                continue
            usage=deepcopy(receipt)
            usage['costUsd']=sum(attempt['receipt'].get('costUsd',0) for attempt in attempts)
            usage['elapsedSec']=sum(attempt['receipt'].get('elapsedSec',0) for attempt in attempts)
            usage['attempts']=deepcopy(attempts)
            usage['usage']={key:sum(attempt['receipt'].get('usage',{}).get(key,0) for attempt in attempts)
                            for key in ('input_tokens','cached_input_tokens','output_tokens')}
            return critique,usage,destination,attempts

    def inspection_notes(self, current_sha, previous, folder=None):
        """Bind bounded supervisor observations; they never replace image judgement."""
        accepted, files = [], []
        permitted = {current_sha}
        if previous: permitted.add(previous['sha256'])
        for source in sorted((self.out()/'inspection-notes').glob('*.json')):
            if source.stat().st_size > 32768:
                raise ValueError('Inspection notes exceed bounded context')
            value = json.loads(source.read_text(encoding='utf-8'))
            if value.get('artifactSha256') not in permitted: continue
            notes = value.get('observations')
            if not isinstance(notes,list) or not 1 <= len(notes) <= 20 or any(
                    not isinstance(note,dict) or not isinstance(note.get('selector'),str) or
                    not isinstance(note.get('observation'),str) or not note['observation'] or
                    len(note['observation']) > 1200 for note in notes):
                raise ValueError('Inspection notes require bounded selector/observation rows')
            value = deepcopy(value)
            for index,note in enumerate(value['observations']): note['noteId']=source.stem+'-'+str(index+1)
            if folder is not None:
                copy = folder/'inspection-notes'/source.name
                save(copy,value)
                files.append(copy)
            accepted.append({**value,'currentArtifact':value['artifactSha256']==current_sha})
        return accepted, files

    def pending_inspections(self, path, last):
        notes, _ = self.inspection_notes(digest(path), None)
        def identity(value):
            return canonical({key:item for key,item in value.items() if key != 'currentArtifact'})
        bound = {identity(value) for value in last.get('inspectionNotes', [])}
        return any(identity(value) not in bound for value in notes)

    def _image_set(self, report, label):
        shots=report.get('screenshots',[])
        required={(viewport,theme) for viewport in ('desktop','phone') for theme in ('light','dark')}
        observed={(row.get('viewport'),row.get('theme')) for row in shots}
        if not required.issubset(observed):
            raise ValueError(label+' requires actual desktop/phone light/dark image sets; missing '+str(sorted(required-observed)))
        images=[]
        for row in shots:
            path=Path(row['path'])
            if not path.is_file() or digest(path)!=row['sha256'] or not path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError(label+' screenshot missing, changed or not PNG: '+str(path))
            images.append(str(path))
        return images

    def _critique_images(self, report, label, *, actions):
        """Send legible viewport tiles; retain hash bindings for every captured image."""
        self._image_set(report,label)
        selected,all_images,manifest=[],[],[]
        def register(row,description,attach=True):
            path=Path(row['path'])
            if not path.is_file() or digest(path)!=row['sha256'] or not path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Invalid '+label+' tile/action image: '+str(path))
            if str(path) not in all_images: all_images.append(str(path))
            if attach and str(path) not in selected:
                selected.append(str(path)); manifest.append({'side':label,'path':str(path),'observation':description})
        for shot in report['screenshots']:
            register(shot,label+' '+shot['viewport']+' '+shot['theme']+' stitched overview',False)
            tiles=shot.get('tiles',[]) or [shot]
            for tile in tiles:
                register(tile,label+' '+shot['viewport']+' '+shot['theme']+' rest tile y='+str(tile.get('y',0)),False)
            if shot['theme']=='light': chosen=range(len(tiles))
            else: chosen=sorted({0,len(tiles)//2,len(tiles)-1})
            for index in chosen:
                register(tiles[index],label+' '+shot['viewport']+' '+shot['theme']+' rest tile y='+str(tiles[index].get('y',0)))
        action_shots=[]
        for variant in report.get('variants',[]):
            for control in variant.get('controls',[]):
                for mode in control.get('modes',[]):
                    for state in mode.get('gestureStates',[]):
                        if state.get('screenshot'):
                            description=label+' '+variant['viewport']+' '+variant['theme']+' '+mode['mode']+' '+state['phase']+' '+control.get('id','')
                            register(state['screenshot'],description,False)
                            if actions and mode['mode']=='pointer':
                                action_shots.append((control.get('id')+':'+state['phase'],state['screenshot'],description))
                    if mode.get('screenshot'):
                        description=label+' '+variant['viewport']+' '+variant['theme']+' '+mode['mode']+' after '+str(control.get('action'))+' '+control.get('id','')
                        register(mode['screenshot'],description,False)
                        if actions and mode['mode']=='pointer' and not control.get('href'):
                            action_shots.append((control.get('id'),mode['screenshot'],description))
        seen=set()
        for identity,shot,description in action_shots:
            if identity in seen: continue
            seen.add(identity); register(shot,description)
            if len(seen)>=64: break
        for frame in report.get('motion',{}).get('frames',[]):
            register(frame,label+' desktop light NORMAL motion frame +'+str(frame['offsetMs'])+'ms',actions)
        return selected,all_images,manifest

    def review(self, name):
        path, brief = self.path(name), self.policy.get('brief')
        if not brief or not path.is_file():
            raise ValueError('Host-bound task brief and HTML deliverable required')
        manual_path, manual = self.manual()
        anchor = Path(self.policy.get('anchor', ''))
        if not anchor.is_file():
            raise ValueError('Credited taste anchor required before image review')
        rounds = self.rounds.setdefault(str(path), [])
        current_sha, previous = digest(path), rounds[-1] if rounds else None
        bounded=self.policy.get('contextMode')=='bounded'
        protocol_verification=bool(previous and (previous.get('manualSha256')!=digest(manual_path) or previous.get('interaction',{}).get('observer_sha256')!=digest(REPO/'scripts/c13_observed.mjs')))
        global_verification=bool(bounded and previous and current_sha==previous['sha256'] and (previous.get('reviewScope')=='sections' or protocol_verification))
        inspection_only = bool(previous and current_sha == previous['sha256'] and (global_verification or self.pending_inspections(path,previous)))
        if previous and current_sha == previous['sha256'] and not inspection_only:
            raise ValueError('Repair reported differences first; unchanged renders do not count')
        change = self.repairs.get(str(path)) if previous and not inspection_only else None
        if previous and not inspection_only and (not change or change['beforeSha256'] != previous['sha256'] or change['afterSha256'] != current_sha
                         or change.get('hostSeal') != self._seal(change) or not change['targeted']):
            raise ValueError('Changed output requires a mapped, host-verified targeted repair')
        number, round_start = len(rounds) + 1, time.monotonic()
        folder = self._fresh_folder(self.out() / path.stem / ('round-' + str(number)))
        text = path.read_text(encoding='utf-8')
        (folder / 'artifact.html').write_bytes(path.read_bytes())
        interaction = self.render(path, folder / 'render')
        # Host-measured, model-free page checks (taste.cl "deterministic page checks"): a light "dark" render,
        # an empty column beside a heading, decorative dashes, stock slogans. They bind the critic and the gate.
        from .taste_checks import page_checks, prompt_view
        page_report = page_checks(path, interaction, corrective=min(number, 3) if self.policy.get('correctiveChecks') else False)
        save(folder / 'page-checks.json', page_report)
        from .laya_hooks import triage_taste
        from .taste_laya import repair_first
        triage = triage_taste(self.root, page_report)
        save(folder / 'laya-check-triage.json', triage)
        deferred = repair_first(self, path, folder, page_report, triage, change)
        if deferred:
            return deferred
        anchor_sha = digest(anchor)
        if anchor_sha not in self.anchor_reports:
            anchor_folder=self._fresh_folder(self.out() / ('anchor-' + anchor.stem))
            anchor_render=self.render(anchor,anchor_folder,capture_only=True)
            anchor_render['hostReportPath']=str(anchor_folder/'report.json')
            self.anchor_reports[anchor_sha] = anchor_render
        anchor_report = self.anchor_reports[anchor_sha]
        if self.policy.get('requireLaya'):
            from .taste_vision import review as vision_review
            vision_review(self.root, interaction, page_report, anchor_report, folder, previous)
        candidate_images,candidate_all,candidate_manifest=self._critique_images(interaction,'Candidate',actions=True)
        anchor_images,anchor_all,anchor_manifest=self._critique_images(anchor_report,'Anchor',actions=False)
        selectors=[]
        if bounded:
            from .taste_context import image_packet,motion_packet
            if change:
                touched=set(change['rowsTouched'])
                selectors=list(dict.fromkeys(d['selector'] for d in previous['critique']['differences'] if d['rowId'] in touched))
            candidate_images,candidate_manifest=image_packet(interaction,'Candidate',folder/'packet',selectors=selectors,actions=True,
                rotation=None if global_verification else number-1,max_images=4 if global_verification or previous else 10,
                overview_only=global_verification)
            motion_images,motion_manifest=motion_packet(interaction,folder/'motion-packet')
            candidate_images+=motion_images;candidate_manifest+=motion_manifest
            # The initial comparison is durable. Section rounds only revisit changed
            # pixels; final global verification reacquires the whole comparison.
            if selectors:
                anchor_images=[]
                anchor_manifest=[]
            else:
                anchor_images,anchor_manifest=image_packet(anchor_report,'Anchor',self.out()/'anchor-packet',actions=False,
                    max_actions=0,rotation=0,max_images=1)
            candidate_all+=candidate_images;anchor_all+=anchor_images
        images=candidate_images+anchor_images
        image_manifest=[{'imageNumber':number,**row} for number,row in enumerate(candidate_manifest+anchor_manifest,1)]
        _, commonness = self.commonness()
        from .taste_sources import verify_papers
        source_sections=Sections(text).records
        # A component's article owns its credits. Ancestor sections repeat all
        # descendant links; a research ledger is not the implemented inventory.
        articles=[section for section in source_sections if section['tag']=='article']
        inventory_sections=articles or [section for section in source_sections if section['tag']=='section']
        from .taste_context import SourceIndex, compact_errors
        owners=SourceIndex(text).find('article' if articles else 'section')
        source_selectors={id(section):('#'+node['attrs']['id'] if node['attrs'].get('id') else node['tag'])
                   for section,node in zip(inventory_sections,owners)}
        current_sources=list({(link,Sections.citation_title(section,link)):
            {'name':Sections.citation_title(section,link),'mechanism':' '.join(section['heading']).strip(),
             'source':link,'used':True,'selector':source_selectors.get(id(section),'')}
            for section in inventory_sections if section['heading'] for link in section['links']}.values())
        citation_observations = verify_papers(current_sources, self.out()/'citation-metadata', self.policy.get('sourceTimeoutSec', 8))
        inspection_notes, inspection_files = self.inspection_notes(current_sha,previous,folder)
        current_urls = {item['source'] for item in current_sources}
        original_rows = self.research['record'] if self.research else []
        research_context = {'preDraftCandidates':len(original_rows), 'preDraftIntendedUsed':sum(bool(item.get('used')) for item in original_rows),
                            'matchingSourceNotes':[item for item in original_rows if item.get('source') in current_urls],
                            'boundRepairSourceNotes':[alternative for record in self._valid_research_addenda() for alternative in record['alternatives']],
                            'inventoryAuthority':'CURRENT HTML and article source inventory; historical research notes are not the current mechanism list'}
        prompt = '' if bounded else ('You are Luna critiquing YOUR rendered draft. First score the ten manual rubric axes using actual image '
                  'tiles/regions, then compare with the better anchor. Do not infer rendering from source. Candidate images '
                  'come first, anchor images second. Give rowId per difference; two evidence refs (ours and better), selector '
                  'and one targeted repair. Keep strengths as gap0 cause=keep repair=leave. Repairs, never rewrites. '
                  'Scope page is allowed only when cause is concept/research/keep; global color/type/finish changes '
                  'are scope section or element, not page. '
                  'A final pass must close every gap>=2, all rubric axes>=3; say passes=false otherwise. '
                  'Set quality in 0..100; the host derives its measured quality from the ten numeric rubric scores. '
                  'For every dead/undecided candidate control in DRIVER include an actionable cause=broken, axis=finish '\
                  'difference with its exact selector; driver failures also force passes=false. '
                  'Address prior host fidelity issues with targeted difference rows too. Rare elements require exact '\
                  'HTTPS credit hrefs, the exact visible author and venue strings, and a visible four-digit year. '\
                  'More than half the rare mechanism names or source URLs shared with the anchor counts as imitation; '\
                  'replace only enough copied mechanisms with independently researched alternatives. '
                  'Judge CURRENT HTML/hrefs. The research stamp predates repairs; do not repeat historical citation '\
                  'mismatches when the current credit URL and primary registration now agree. '
                  'Primary registration checks the visible credited paper title, not a descriptive component '
                  'heading. A heading may describe the subject in plain words; still judge whether the '
                  'credited paper supports the implemented mechanism. '
                  'ONLY IF THE BRIEF SAYS rare/uncommon require uncommon defining mechanisms, primary research and '
                  'actual defining behavior visible in the rendered interaction states. A published name, moving '\
                  'outline, changed status or ordinary button selection alone does not implement its claimed '\
                  'mechanism. For example a lens must actually reveal/transform local subject data, and wrapping '\
                  'navigation must visibly wrap a usable cursor/selection. Set implemented=false and supply an '\
                  'actionable difference when the images, driver and source do not establish that behavior. '
                  'For OrthoZoom, require independent along-axis pan and perpendicular zoom: a hypot(dx,dy) '
                  'distance that zooms during along-axis pan is not orthogonal zoom. For Semantic Pointing, '
                  'a larger motor acquisition region must preserve the visual label position and neighboring '
                  'targets; enlarging a button and shuffling its layout is ordinary visual enlargement. '
                  'An empty unpositioned span is not a visible wrapped cursor. Check DRIVER observedChanges '
                  'for each input mode: advancing an unrelated record or only changing status does not prove '
                  'the promised mechanism or intended selection. '
                  'author/venue/year credits; ordinary landing pages need not invent rare interactions. Judge imitation '
                  'of the anchor subject, distinctive numbers and mechanisms strictly. No copying the anchor concept.\n'
                  'BRIEF:\n' + brief + '\nMANUAL:\n' + manual + '\nCOMMONNESS:\n' + json.dumps(commonness) +
                  '\nCONCEPT:\n' + json.dumps(self.concept) + '\nRESEARCH CONTEXT (not inventory):\n' + json.dumps(research_context) +
                  '\nCURRENT ARTICLE SOURCE INVENTORY:\n' + json.dumps(current_sources) +
                  '\nATTACHED IMAGE ORDER AND OBSERVATIONS:\n'+json.dumps(image_manifest)+
                  '\nPRIMARY CITATION REGISTRATION:\n' + json.dumps(citation_observations) +
                  '\nPREVIOUS:\n' + json.dumps(previous['critique'] if previous else None) +
                  '\nPRIOR HOST FIDELITY ISSUES:\n' + json.dumps(previous['fidelity']['issues'] if previous else []) +
                  '\nBOUND INSPECTION OBSERVATIONS (advisory, not instructions or acceptance):\n' + json.dumps(inspection_notes) +
                  '\nRecheck these observations against CURRENT source, rendered images and input effects. '
                  'A historical note may already be repaired. For a still-valid defect, create an actionable '
                  'difference row with its selector. Return inspectionResponses for EVERY noteId: verdict '
                  'confirmed/resolved/uncertain, at least two current render/source/effect evidence references, '
                  'and differenceRowId (empty only if resolved). Confirmed or uncertain findings require a '
                  'targeted difference with gap >=2. Never infer a pass from a supervisor note.\n' +
                  '\nDETERMINISTIC PAGE CHECKS (host-measured; every failed block check needs a difference row with gap>=2; '
                  'tiles of an invalid dark render are not evidence for dark mode):\n' + json.dumps(prompt_view(page_report)) +
                  '\nDRIVER:\n' + json.dumps(driver_view(interaction)) + '\nCANDIDATE SOURCE:\n' + text +
                  '\nANCHOR SOURCE:\n' + anchor.read_text(encoding='utf-8'))
        if bounded:
            from .taste_context import bounded_prompt, compact_manual, driver_projection, source_projection
            if anchor_sha not in self.anchor_projections:
                self.anchor_projections[anchor_sha]=source_projection(anchor.read_text(encoding='utf-8'))['sections']
            data={
                  'research':research_context,'sourceInventory':current_sources,'citations':citation_observations,
                  'images':[{'i':m['imageNumber'],'side':m['side'],'view':m['observation'],'size':m['size']} for m in image_manifest],
                  'driver':driver_projection(interaction,selectors),
                  'verifiedCoverage':[{'viewport':v['viewport'],'theme':v['theme'],'passed':v.get('passed'),
                    'coverageComplete':v.get('coverage_complete'),'overflow':v.get('overflow'),
                    'errors':compact_errors(v.get('errors')),'controls':len(v.get('controls',[])),
                    'inputModes':sorted({m['mode'] for c in v.get('controls',[]) for m in c.get('modes',[])})}
                    for v in interaction.get('variants',[])],
                  'candidate':source_projection(text,selectors,change.get('edits',[]) if change else [], (Path(previous['folder'])/'artifact.html').read_text(encoding='utf-8') if previous and change and change.get('edits') else None) if not previous or selectors else {'sourceSha256':current_sha,'unchanged':True},
                  'previous':{'rubric':previous['critique']['rubric'],'differences':previous['critique']['differences']} if previous else None,
                  'priorFidelity':previous['fidelity']['issues'] if previous else [],'inspections':inspection_notes,
                  'priorRareElements':previous['critique']['rareElements'] if previous else [],
                  'scope':'sections' if selectors else 'global',
                  'pageChecks':prompt_view(page_report)}
            stable=compact_manual(manual,brief=brief)+'\nCONCEPT:\n'+json.dumps(self.concept['record'],separators=(',',':'))+'\nANCHOR SUMMARY:\n'+json.dumps([{'heading':s['heading'],'text':s['text'][:180]} for s in self.anchor_projections[anchor_sha]],separators=(',',':'))
            instructions=('Score all ten axes 0..4 with image/region evidence; host computes quality. Judge voice within content: short plain specific sentences, no selling or promises; marketing copy caps content at 2. Judge motion ONLY from ordered normal/reduced entrance and interaction sequences; stills and CSS declarations prove no motion. '
                          'YOU are the fresh rendered rubric review, not a reviewer of the harness procedure. Grade the delivered PAGE against BRIEF. '
                          'An independent prior critique is not required. Research candidates are required ONLY when BRIEF says rare/uncommon; ordinary landing research may be empty. '
                          'Scope page is allowed only for concept/research/keep; broken, color, type or finish use section/element even for body CSS. '
                          'Return concise rubric and exact actionable difference rows (two evidence refs, selector, gap0..4). '
                          'Question your own output against the actual differences before suggesting a fast repair. Keep strengths as cause=keep. All scores >=3, no gap>=2, brief fidelity and driver pass are required. '
                          'Compare the independent subject with anchor: no imitation. Failed controls require cause=broken rows. '
                          'Citation defects must name the owning component article selector, not a research ledger or all sources. '
                          'For rare tasks list EVERY credited element with exact primary URL, author, venue/year and genuinely '
                          'implemented uncommon algorithm; a status change alone is insufficient. Ordinary landings need no rare elements. '
                          'For section review use the sealed prior anchor comparison and retain prior scores only for unchanged observed regions, revise changed ones; '
                          'this cannot finish until a fresh global review. Unchanged regions have sealed prior evidence; a crop does not erase it. '
                          'Retain the complete rareElements inventory from current sources and priorRareElements, updating changed mechanisms. '
                          'Missing actual evidence is uncertain and blocking; do not create a code defect merely because this is a section review. '
                          'verifiedCoverage is the host-sealed exhaustive current interaction observation, including every listed input mode and theme. '
                          'Rotating crops deliberately omit unchanged images; use sealed prior observations for those regions. '
                          'Do not label omitted screenshots a broken code defect or prescribe a source change to obtain an image. '
                          'No speculative polish defect when checks/rubric/differences pass. Keep prose under 400 words apart from rareElements. '
                          'For inspections return exact noteIds with confirmed/resolved/uncertain. Unless resolved, differenceRowId must reference a non-keep row with gap>=2.\n')
            from .cl.tokens import count_tokens
            save(folder/'critic/projection-metrics.json',{
                'textTokensByField':{key:count_tokens(json.dumps(value,ensure_ascii=False,separators=(',',':'))) for key,value in data.items()},
                'totalDataTokens':count_tokens(json.dumps(data,ensure_ascii=False,separators=(',',':'))),
                'sourceCharacters':len(text),'rawDriverBytes':len(json.dumps(interaction))})
            text_ceiling=(24000 if not selectors and re.search(r'\brare\b|\buncommon\b',brief,re.I) else self.policy.get('contextTokenBudget',16000))
            prompt=bounded_prompt(brief,instructions+json.dumps(data,ensure_ascii=False,separators=(',',':')),folder/'critic',
                                  budget=text_ceiling,raw=None,stable=stable)
        critique, usage, critic_folder, attempts = self._invoke_critique(prompt,folder/'critic',images,inspection_notes)
        if bounded and selectors:
            # A crop cannot close a defect in an unobserved, unchanged region.
            untouched=[d for d in previous['critique']['differences']
                       if d['gap']>=2 and d['rowId'] not in set(change['rowsTouched'])]
            # Fresh source/metadata may refine an open row's owner; it cannot close
            # an unobserved gap. Keep its cause and blocking severity unchanged.
            refinements={d['rowId']:d for d in critique['differences'] if d['gap']>=2 and d['scope']!='page'}
            untouched=[{**d,'selector':refinements[d['rowId']]['selector']}
                       if d['rowId'] in refinements and refinements[d['rowId']]['cause']==d['cause']
                       and SourceIndex(text).find(refinements[d['rowId']]['selector']) else d for d in untouched]
            retained={d['rowId'] for d in untouched}
            critique['differences']=[d for d in critique['differences'] if d['rowId'] not in retained]+deepcopy(untouched)
            if untouched:critique['passes']=False
        # Deterministic failures always enter the repair loop, even if a critic
        # omits them. Scores remain the model's; these rows are explicitly host-owned.
        from .taste_checks import FIX, _summary
        source_index=SourceIndex(text)
        header=next((n for n in source_index.nodes if n['tag']=='header' and n['attrs'].get('id')),None)
        theme_owner='#'+header['attrs']['id'] if header else 'body'
        demo=next((n for n in source_index.nodes if n['attrs'].get('id')=='example'),None)
        if demo is None:demo=next((n for n in source_index.nodes if n['attrs'].get('data-c13-action') and n['attrs'].get('id')),None)
        if demo is None:demo=next((n for n in source_index.nodes if n['attrs'].get('id')=='who'),None)
        motion_owner=theme_owner+(', #'+demo['attrs']['id'] if demo else '')
        host_rows=[]
        mapping={'motion-sequence':('motion','motion',motion_owner),'theme-toggle':('color','color',theme_owner),
                 'reduced-motion':('motion','motion',theme_owner),'diagram-geometry':('finish','broken',None),
                 'spelling':('finish','broken',None),'text-box-fit':('finish','broken',None),'figure-centering':('finish','broken',None)}
        for check in page_report['checks']:
            if check['passed'] or check['level']!='block' or check['check'] not in mapping:continue
            axis,cause,selector=mapping[check['check']]
            if selector is None:
                selector=next((hit.get('selector') for hit in check['hits'] if hit.get('selector') and source_index.find(hit['selector'])), 'body')
            row_id='host-'+check['check']
            critique['differences']=[d for d in critique['differences'] if d['rowId']!=row_id]
            row={'rowId':row_id,'axis':axis,'gap':3,'ours':_summary(check),'better':FIX[check['check']],
                 'evidence':['page-checks.json '+check['check'],'render/report.json measured '+check['check']],
                 'cause':cause,'repair':FIX[check['check']],'scope':'section','selector':selector}
            critique['differences'].append(row);host_rows.append(row_id)
        if host_rows:critique['passes']=False
        critique['hostDifferenceRows']=host_rows
        critique['reportedQuality']=critique['quality']
        critique['critiqueMean']=sum(row['score'] for row in critique['rubric'])/len(AXES)
        critique['quality']=critique['critiqueMean']*25
        critique['qualityBasis']='Host arithmetic mean of ten 0..4 rubric scores times 25'
        judge_path = Path(self.policy.get('judge', REPO / 'config/c13-judge.json'))
        from .taste_judge import compare
        pairwise = compare(brief, text, anchor.read_text(encoding='utf-8'), json.loads(judge_path.read_text(encoding='utf-8')))
        diff_path = folder / ('taste-diff-' + str(number) + '.cl')
        diff_path.write_text(self._difference_cl(path, anchor, number, critique), encoding='utf-8')
        fidelity = self.fidelity(brief, critique, text, interaction, anchor.read_text(encoding='utf-8'))
        bound_files = [folder/'artifact.html', folder/'render/report.json', folder/'page-checks.json', diff_path,Path(anchor_report['hostReportPath'])]
        bound_files += inspection_files
        for attempt in attempts:
            attempt_folder=Path(attempt['folder'])
            bound_files += [attempt_folder/'response.json',attempt_folder/'usage.json',attempt_folder/'events.jsonl']
        bound_files += [Path(image) for image in candidate_all+anchor_all]
        bound_files += list((self.out()/'citation-metadata').glob('*.json'))
        bound_files += [Path(file['path']) for record in self._valid_research_addenda() for file in record['evidenceFiles']]
        row = {'round': number, 'sha256': current_sha, 'manualSha256': digest(manual_path), 'anchorSha256': anchor_sha,
               'policySha256': hashlib.sha256(canonical(self.policy)).hexdigest(),
               'judgeSha256': digest(judge_path), 'commonnessSha256': digest(self.commonness()[0]), 'folder': str(folder),
               'interaction': interaction, 'critique': critique, 'usage': usage, 'fidelity': fidelity,
               'criticFolder':str(critic_folder),
               'imageManifest':image_manifest,
               'inspectionNotes':inspection_notes,
               'anchorReportPath':anchor_report['hostReportPath'],
               'pairwise': pairwise, 'change': deepcopy(change), 'differenceCl': str(diff_path),
               'qualityGain': None if not previous else critique['quality'] - previous['critique']['quality'],
               'elapsedSec': time.monotonic()-round_start, 'taskElapsedSec': time.monotonic()-self.started,
               'evidenceFiles': [{'path':str(file), 'sha256':digest(file)} for file in bound_files]}
        row['pageChecks'] = page_report
        row['inspectionOnly'] = inspection_only
        row['reviewScope']='sections' if bounded and selectors else 'global'
        row['hostSeal'] = self._seal(row)
        rounds.append(row)
        self.quarantine(row, brief)
        save(folder / 'round.json', row)
        save(self.out() / 'rounds.json', self.rounds)
        self._learn_taste_repair(row, previous, triage)
        return row

    def _learn_taste_repair(self, row, previous, triage):
        from .laya_hooks import learn_outcome, taste_state
        if not previous or not row.get('change', {}).get('targeted') or row['qualityGain'] < 0 or \
                not row['interaction'].get('passed') or row['interaction'].get('observer_sha256') != previous['interaction'].get('observer_sha256'):
            return
        before, after = previous['pageChecks'], row['pageChecks']
        failed_before = {c['check'] for c in before['checks'] if not c['passed']}
        failed_after = {c['check'] for c in after['checks'] if not c['passed']}
        if failed_before and failed_after < failed_before and after.get('renderValid', True):
            learn_outcome(self.root, 'taste_triage', taste_state(before), 'repair_first',
                {'receipt': str(Path(row['folder']) / 'round.json'), 'verifier': 'taste-rendered-repair',
                 'passed': True, 'resolvedChecks': sorted(failed_before - failed_after)})

    def fidelity(self, brief, critique, text, interaction=None, anchor_text=''):
        issues = []
        if not critique.get('briefPasses'):
            issues.append('Image critic rejected brief fidelity')
        if not self.concept or self.concept.get('hostSeal') != self._seal(self.concept):
            issues.append('Missing host-stamped concept before layout')
        rare = bool(re.search(r'\brare\b|\buncommon\b', brief, re.I))
        if rare:
            if len(self._valid_research_addenda()) != len(self.research_addenda):
                issues.append('Repair research evidence or host stamp changed')
            sections = Sections(text)
            planned = self.concept['record'].get('plannedElements',[]) if self.concept else []
            minimum = len(planned) if planned else int(self.policy.get('minRareElements',0))
            elements = critique.get('rareElements', [])
            candidates = self.research['record'] if self.research else []
            active_sources={element['primarySource'] for element in elements}
            reservoir=candidates+[{'source':a['primarySource'],'sourceKind':'paper','name':a['name']}
                for record in self._valid_research_addenda() for a in record['alternatives']]
            used=list({row['source']:row for row in reservoir if row.get('source') in active_sources or active_sources.intersection(row.get('sources',[]))}.values())
            from .taste_sources import verify_papers
            citations = verify_papers([{'name':sections.paper_title(element), 'source':element['primarySource'], 'used':True} for element in elements], self.out()/'citation-metadata', self.policy.get('sourceTimeoutSec', 8))
            issues.extend('Primary citation names a different paper: '+row['name']+' -> '+row['registered']['title']
                          for row in citations if row['matches'] is False)
            issues.extend('Primary DOI registration is unverified: '+row['name']+' -> '+row.get('reason','unavailable')
                          for row in citations if row['matches'] is None)
            if len(elements) < minimum or len(used) < minimum or len(candidates) < 2 * len(used):
                issues.append('Rare brief requires its declared mechanism plan and twice as many researched candidates')
            if len({row['name'].lower() for row in elements}) != len(elements):
                issues.append('Duplicate rare elements cannot count twice')
            for element in elements:
                source = element['primarySource']
                host = urlparse(source).hostname or ''
                primary = host.endswith(('.edu', '.ac.uk')) or host in {'doi.org','dl.acm.org','arxiv.org','ieeexplore.ieee.org'} or 'hci' in host or host in {'worrydream.com','www.billbuxton.com','billbuxton.com'}
                # Critic labels are presentation text; the sealed primary URL identifies the research.
                # All stamped pre-draft candidates are the cached research
                # reservoir. Selecting an unused alternative later does not
                # require a second research call or alter the original stamp.
                researched = any(row.get('sourceKind') in PRIMARY
                                 and (row.get('source') == source or source in row.get('sources', [])) for row in candidates)
                researched = researched or any(alternative['primarySource'] == source
                    for record in self._valid_research_addenda() for alternative in record['alternatives'])
                if (not element['uncommon'] or not element['implemented'] or self._common(element['name']) or
                        not source.startswith('https://') or source not in text or not (primary or researched) or
                        not element.get('selector') or not element.get('mechanism') or not element.get('author') or
                        not element.get('venue') or element.get('year',0) < 1900):
                    issues.append('Unproven uncommon mechanism/source/credit: ' + element['name'])
                if not sections.credited(element):
                    issues.append('Primary source and author/venue/year credit must appear in element section: '+element['name'])
            primary_count = sum(row.get('sourceKind') in PRIMARY for row in used)
            if primary_count < len(used) * .5:
                issues.append('At least half of used research must be primary')
            if self.research and self.research.get('hostSeal') != self._seal(self.research):
                issues.append('Research host stamp changed')
            normalized_anchor=re.sub(r'[^a-z0-9]','',anchor_text.lower())
            anchor_names = [element['name'].lower() for element in elements
                            if re.sub(r'[^a-z0-9]','',element['name'].lower()) in normalized_anchor
                            or element['primarySource'] in anchor_text]
            if elements and len(anchor_names)/len(elements) > .5:
                issues.append('No imitation: more than half the interaction names copied from anchor')
        # Distinctive unit-bearing values rather than ubiquitous years, CSS px and section numbering.
        numbers = set(re.findall(r'\b\d[\d,.]*\s*(?:cm|km|years|m2|m²|mushrooms|specimens|hectares)\b', text.lower()))
        anchor_numbers = set(re.findall(r'\b\d[\d,.]*\s*(?:cm|km|years|m2|m²|mushrooms|specimens|hectares)\b', anchor_text.lower()))
        if numbers and len(numbers & anchor_numbers)/len(numbers) > .2:
            issues.append('No imitation: distinctive anchor numbers reused')
        if self.concept and self.concept['record']['subject'].lower() in {'fungi','fungus','mushrooms','hidden kingdom'} and 'fung' in anchor_text.lower() and rare:
            issues.append('No imitation: anchor subject reused')
        return {'passed': not issues, 'issues': issues, 'citationEvidence': citations if rare else []}

    def quarantine(self, row, brief):
        for index, lesson in enumerate(row['critique']['lessons'][:3]):
            identity = hashlib.sha256((lesson+row['sha256']).encode()).hexdigest()[:16]
            proposal = 'M taste ' + json.dumps(lesson) + f' src:{row["differenceCl"]}#{min(index+1,len(row["critique"]["differences"]))} check:"C taste.make goal" author:'+self.policy.get('model','gpt-6-luna')+' state:quarantine'
            record = {'schema':'neyvia.lesson.v1','id':identity,'state':'quarantined','manual':'skill:taste',
                      'kind':'guidance','cl':proposal,'manualPatchProposal':{'target':'manuals/cl/taste.cl','append':proposal,'applied':False},
                      'evidence':{'taskText':brief,'outputSha256':row['sha256'],'differenceCl':row['differenceCl'],'round':row['round']},
                      'admission':{'sourceTaskRerunRequired':True,'frozenSuiteRerunRequired':True,'noise':0},'evolver':None}
            save(self.out()/'lessons'/(identity+'.json'), record)

    def admit_lesson(self, identity, evidence):
        """C9 admission creates an overlay for a later task, never edits the manual."""
        if not re.fullmatch('[a-f0-9]{16}', identity):
            raise ValueError('Unknown lesson identity')
        path = self.out()/'lessons'/(identity+'.json')
        lesson = json.loads(path.read_text(encoding='utf-8'))
        if hashlib.sha256(Path(evidence['taskPath']).read_bytes()).hexdigest() != hashlib.sha256(lesson['evidence']['taskText'].encode()).hexdigest():
            raise ValueError('Lesson admission must rerun its exact source brief')
        from .taste_judge import admit_lesson
        result = admit_lesson(evidence)
        lesson['evolver'] = result
        if result['accepted']:
            source_path, source = self.manual()
            overlay = self.out()/'admitted-manuals'/(identity+'.cl')
            overlay.parent.mkdir(parents=True,exist_ok=True)
            overlay.write_text(source+'\n'+lesson['cl'].replace('state:quarantine','state:verified')+'\n',encoding='utf-8')
            lesson['state'] = 'verified'
            lesson['manualPatchProposal'].update(admittedOverlay=str(overlay),overlaySha256=digest(overlay))
            result = {**result,'manualOverlay':str(overlay),'manualOverlaySha256':digest(overlay),
                      'scope':'task-local overlay for a subsequent task; authoritative manual unchanged'}
            registry=self._lesson_registry()
            base_path=Path(self.policy.get('manual',REPO/'manuals/cl/taste.cl')).resolve()
            registered=json.loads(registry.read_text(encoding='utf-8')) if registry.is_file() else {'schema':'neyvia.admitted-taste-manuals.v1','admissions':[]}
            registered['admissions'].append({'lessonId':identity,'sourceManualPath':str(base_path),
                                             'sourceManualSha256':digest(base_path),'manualOverlay':str(overlay),
                                             'manualOverlaySha256':digest(overlay),'admissionEvidence':deepcopy(evidence),
                                             'admissionEvidenceSha256':result['evidenceSha256'],'admittedAt':time.time()})
            save(registry,registered)
        save(path,lesson)
        return result

    def gate(self):
        try:
            return self._gate()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return False, 'X taste evidence unavailable or invalid: ' + str(exc) + '\n'

    def _gate(self):
        files = self.files()
        if not files and not self.policy.get('required'):
            return None, ''
        reasons = []
        if not files:
            reasons.append('No required HTML deliverable')
        bounded=self.policy.get('contextMode')=='bounded'
        minimum = 1 if bounded else max(3,int(self.policy.get('minReviews',3)))
        for path in files:
            rounds = self.rounds.get(str(path), [])
            if sum(not row.get('inspectionOnly') for row in rounds) < minimum:
                reasons.append(path.name+': draft review and at least two targeted repair/review rounds required')
                continue
            last = rounds[-1]
            if bounded and last.get('reviewScope')!='global':
                reasons.append(path.name+': final global rendered review required after section repairs')
            try:
                if self.pending_inspections(path,last):
                    reasons.append(path.name+': new artifact-bound inspection findings require an image re-review')
            except (ValueError, OSError) as exc:
                reasons.append(path.name+': inspection evidence unavailable: '+str(exc))
            for number, row in enumerate(rounds,1):
                if row.get('round') != number or row.get('hostSeal') != self._seal(row):
                    reasons.append('Round count or host-owned evidence changed')
                    break
                for artifact in row['evidenceFiles']:
                    if digest(artifact['path']) != artifact['sha256']:
                        reasons.append('Evidence changed: '+artifact['path'])
                usage = row['usage']
                if usage.get('model') != self.policy.get('model','gpt-6-luna') or usage.get('exitCode') != 0 or usage.get('timedOut') or not usage.get('images'):
                    reasons.append('Review requires successful selected-model image-input invocation')
            if digest(path) != last['sha256']:
                reasons.append(path.name+': artifact changed after reviewed render')
            if hashlib.sha256(canonical(self.policy)).hexdigest() != last['policySha256']:
                reasons.append('Host-bound brief or completion policy changed after review')
            if digest(self.manual()[0]) != last['manualSha256'] or digest(self.policy['anchor']) != last['anchorSha256']:
                reasons.append('Manual or anchor changed after review')
            if digest(self.policy.get('judge', REPO/'config/c13-judge.json')) != last['judgeSha256'] or digest(self.commonness()[0]) != last['commonnessSha256']:
                reasons.append('Frozen judge or commonness list changed')
            page_report = last.get('pageChecks')
            if not page_report:
                reasons.append(path.name+': deterministic page checks missing; review again')
            else:
                from .taste_checks import gate_reasons
                reasons.extend(path.name+': '+reason for reason in gate_reasons(page_report))
                if self.policy.get('correctiveChecks') and not {'spelling','text-box-fit','figure-centering'}.issubset({c['check'] for c in page_report['checks']}):
                    reasons.append(path.name+': introduce and verify the remaining corrective requirements one at a time')
            if last['interaction'].get('observer_sha256') != digest(REPO/'scripts/c13_observed.mjs'):
                reasons.append(path.name+': render observation protocol changed; review again')
            if not last['interaction']['passed']:
                reasons.append(path.name+': broken controls/render or browser capability gap')
            fidelity = self.fidelity(self.policy['brief'], last['critique'], path.read_text(encoding='utf-8'), last['interaction'], Path(self.policy['anchor']).read_text(encoding='utf-8'))
            reasons.extend(fidelity['issues'])
            critic = last['critique']
            self._critique_checks(critic)
            try:
                self._inspection_checks(critic,last.get('inspectionNotes',[]))
            except ValueError as exc:
                reasons.append(path.name+': '+str(exc))
            if not critic['passes'] or critic['anchorVerdict'] == 'anchor' or any(row['score'] < 3 for row in critic['rubric']):
                reasons.append(path.name+': rubric-first image critic rejects result or prefers anchor')
            if any(row['gap'] >= 2 for row in critic['differences']):
                reasons.append(path.name+': material difference rows remain open')
            if any(not row.get('change',{}).get('targeted') for row in rounds[1:] if not row.get('inspectionOnly')):
                reasons.append(path.name+': repairs must be targeted and mapped')
            qualifying = sum(row['qualityGain'] >= 0 and row.get('change',{}).get('targeted') for row in rounds[1:] if not row.get('inspectionOnly'))
            if not bounded and (qualifying < 2 or last['qualityGain'] < 0 or last['critique']['quality'] < rounds[0]['critique']['quality']):
                reasons.append(path.name+': need two nonregressing targeted repairs and a final result at least as good as the draft')
            page_repairs = sum(any(diff['scope']=='page' and diff['cause'] != 'keep' and diff['rowId'] in row['change']['rowsTouched']
                                   for diff in prior['critique']['differences']) for prior,row in zip(rounds,rounds[1:]) if not row.get('inspectionOnly'))
            if page_repairs > 1:
                reasons.append('Page-level concept/research repair permitted once per task')
        return not reasons, ''.join('X taste '+reason+' -> targeted repair then taste.review(path)\n' for reason in reasons)
