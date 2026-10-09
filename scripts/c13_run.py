"""Re-run the two R6 briefs with real Luna calls and the production CL completion host."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import time

WT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WT / 'src'))
from grant_agent.subprocess_utils import install_hidden_subprocess_default
from grant_agent.taste_model import invoke, object_schema, REPAIR_SCHEMA, successful_call
from grant_agent.taste_gate import digest, save

CONCEPT_SCHEMA = object_schema({
    'idea': {'type': 'string', 'minLength':1}, 'subject': {'type': 'string','minLength':1},
    'vernacular': {'type': 'array', 'minItems':3, 'maxItems':8, 'items': {'type': 'string'}}, 'bold': {'type': 'string','minLength':1},
    'plannedElements': {'type':'array','items':{'type':'string','minLength':1}},
    'quiet': {'type': 'array','minItems':1, 'items': {'type': 'string'}}, 'motion': {'type': 'string'},
    'rejected': {'type': 'array','minItems':1, 'items': {'type': 'string'}}})
RESEARCH_SCHEMA = object_schema({
    'name': {'type': 'string'}, 'used': {'type': 'boolean'}, 'source': {'type': 'string'},
    'sourceKind': {'type': 'string'}, 'why': {'type': 'string'}})
DRAFT_SCHEMA = object_schema({'html': {'type': 'string', 'minLength':1500}, 'concept': CONCEPT_SCHEMA,
    'research': {'type': 'array', 'items': RESEARCH_SCHEMA}})
REPLACEMENT_SCHEMA = object_schema({'alternatives': {'type': 'array', 'minItems': 2,
    'items': object_schema({'rowId': {'type': 'string'}, 'name': {'type': 'string'},
        'primarySource': {'type': 'string', 'pattern': '^https://'},
        'author': {'type': 'string'}, 'venue': {'type': 'string'}, 'year': {'type': 'integer'},
        'mechanism': {'type': 'string'}, 'implementation': {'type': 'string'},
        'evidence': {'type': 'string'}})}})
OUT = {'T1': 'landing.html', 'T2': 'rare-ui.html'}


def tasks():
    text = (WT / 'proof/r6-blind/tasks.md').read_text(encoding='utf-8')
    parts = re.split(r'^## (T\d) · [^\n]*\n', text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def script_syntax_errors(html):
    """Parse inline executable scripts without executing any candidate code."""
    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__(); self.current = None; self.rows = []
        def handle_starttag(self, tag, attrs):
            if tag == 'script':
                values = dict(attrs)
                kind = values.get('type', '').lower()
                if not values.get('src') and kind in ('', 'text/javascript', 'application/javascript', 'module'):
                    self.current = [kind, '']
        def handle_data(self, data):
            if self.current is not None: self.current[1] += data
        def handle_endtag(self, tag):
            if tag == 'script' and self.current is not None:
                self.rows.append(self.current); self.current = None
    parser = Scripts(); parser.feed(html)
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    errors = []
    for index, (kind, source) in enumerate(parser.rows, 1):
        args = ['node', '--input-type=module', '--check'] if kind == 'module' else [
            'node', '--input-type=module', '--eval',
            "import {Script} from 'node:vm';import{readFileSync}from'node:fs';new Script(readFileSync(0,'utf8'));"
        ]
        checked = subprocess.run(args, input=source, text=True, encoding='utf-8', capture_output=True,
                                 timeout=10, **hidden_windows_subprocess_kwargs())
        if checked.returncode:
            errors.append('Inline script '+str(index)+' syntax refusal (source not executed): '+checked.stderr[:2000])
    return errors


def native_host(root, policy):
    """Reuse native workspace handlers without a browser/desktop runtime or backend URL."""
    from grant_agent.native_tools import NativeToolRegistry
    from grant_agent.cl.host import HostContext
    registry = NativeToolRegistry(root)
    names = ['workspace.read', 'workspace.write', 'workspace.patch']
    tools = [{**registry.describe(name), 'name': name,
              'annotations': {'readOnlyHint': name == 'workspace.read'}} for name in names]
    def dispatch(name, args, action_id=''):
        if name not in names:
            raise ValueError('C13 runner grants workspace read/write/patch only')
        return registry._handlers[name](args)
    def contracts(name):
        if name == 'workspace.read':
            return {}
        def checked(args, value, before):
            if value.get('ok') is False:
                return False
            observed = registry._workspace_read({'path': args['path'], 'maxChars': 1000000})
            return observed['sha256'] == value['sha256']
        return {'checks': [{'name': 'workspace-readback', 'observer': True, 'check': checked}]}
    host = HostContext(tools, dispatch, contracts=contracts, root=root)
    from grant_agent.taste_gate import TasteGate
    host.taste = TasteGate(root, host.started, policy=policy)
    return host


def execute(host, call):
    result = host.execute(call)
    if not result['ok']:
        if 'Run budget cannot admit' in result['text'] or 'future calls blocked' in result['text']:
            from grant_agent.taste_budget import BudgetExceeded
            raise BudgetExceeded(result['text'])
        raise RuntimeError(result['text'])
    return result


def replacement_research(host, current, folder, target, research_rows, brief, content):
    # A wrong link label does not need another search when the current sealed
    # registry already verifies the originally researched mechanism's DOI.
    # Reject wrong-paper candidates; never rename a mechanism to fit an unrelated DOI.
    from grant_agent.taste_gate import Sections
    from grant_agent.taste_sources import verify_papers
    latest=host.taste.rounds[str(current.resolve())][-1]
    registered={x['source']:x for x in latest['fidelity'].get('citationEvidence',[]) if x.get('registered')}
    known={}
    for candidate in host.taste.research['record'] if host.taste.research else []:
        url=candidate.get('source')
        if url not in registered:continue
        checked=verify_papers([{'name':candidate['name'],'source':url,'used':True}],host.taste.out()/'citation-metadata')
        if checked and all(x['matches'] is True for x in checked):
            observed=registered[url]
            metadata=Path(observed['metadataPath'])
            known[url]={'primarySource':url,**observed['registered'],
                        'metadataPath':str(metadata),'metadataSha256':digest(metadata)}
    owners=Sections(content).records
    citation_only=all(re.search(r'citation|credit',d['repair'],re.I) for d in research_rows)
    covered=citation_only and bool(research_rows)
    urls=set()
    for diff in research_rows:
        for selector in diff['selector'].split(','):
            terms=set(re.findall(r'[#.][\w-]+',selector))
            matches=[record for record in owners if terms and terms<=record['selectors']]
            links=set().union(*(record['links'] for record in matches)) if matches else set()
            present=links.intersection(known)
            if not present:covered=False
            urls.update(present)
    if covered:
        return {'citationCorrections':[known[url] for url in sorted(urls)],
                'provenance':'Current sealed review registry plus matching pre-layout research candidate; correcting displayed labels only, no new source/algorithm admission.'}
    unused = [alternative for record in host.taste._valid_research_addenda() for alternative in record['alternatives']
                  if re.split(r'[(/·]', alternative['name'], maxsplit=1)[0].strip().lower() not in content.lower()]
    from grant_agent.taste_sources import verify_papers
    unused=[a for a in unused if all(r['matches'] is True for r in verify_papers(
        [{'name':a['name'],'source':a['primarySource'],'used':True}],host.taste.out()/'citation-metadata'))]
    if unused:
        return {'alternatives':unused, 'provenance':'Previously bound actual web-search receipts; current repair still needs exact current difference rowIds'}
    research_prompt = ('Use the LIVE WEB SEARCH tool available in this call. Read-only sandbox forbids '\
        'filesystem mutations, not web research. Research at least two independent uncommon HCI '\
        'mechanisms to resolve the research difference rows. Exclude mechanisms already used by the '\
        'candidate OR anchor. Read primary author/paper pages, verify exact authors, venue, year '\
        'and primary HTTPS URLs. Each returned URL must actually occur as a searched/opened result URL '\
        'in THIS call; open a DOI if you return it, otherwise return the exact opened author/paper URL. '\
        'Exclude pressure/force sensing, physical devices, OS cursor manipulation or other unavailable '\
        'hardware requirements. The defining software algorithm must genuinely work with ordinary '\
        'pointer, keyboard and touch input. Explain that algorithm and feasible implementation. '\
        'Keep the existing subject and illustrations. These are research proposals, not proof of '\
        'working implementation or permission for a rewrite. Return only verified alternatives mapped '\
        'to an exact difference rowId.\nBRIEF:\n' + brief + '\nRESEARCH DIFFERENCES:\n' +
        json.dumps(research_rows))
    bounded=host.taste.policy.get('contextMode')=='bounded'
    if bounded:
        from grant_agent.taste_context import source_projection, compact_manual
        inventory=[{'heading':x['heading'],'sources':x['sources'],'text':x['text'][:240]}
                   for x in source_projection(content)['sections']]
        anchor_summary=next(iter(host.taste.anchor_projections.values()),[])
        research_prompt=research_prompt.replace('Exclude mechanisms already used by the candidate OR anchor. ',
            'Correct existing candidate citations and avoid copying the anchor mechanism majority. ')
        research_prompt=compact_manual(host.taste.manual()[1],brief=brief)+'\n'+research_prompt+(
            '\nCorrect mismatched citations for existing mechanisms when that is the difference; '
            'do not invent a DOI or replace a working mechanism just to alter a credit. '
            'Return exactly TWO fully verified proposals. Use at most two searches and open each exact returned URL in this call. '
            'Do not return an unverified third alternative, a search-only citation, or an unrelated DOI. '
            'Also propose a missing declared mechanism if required. Return exact authors, venue, year and opened URL. '
            '\nCURRENT SECTION INVENTORY:\n'+json.dumps(inventory,separators=(',',':'))+
            '\nKNOWN SOURCE REGISTRATION ISSUES:\n'+json.dumps(host.taste.rounds[str(current.resolve())][-1]['fidelity']['issues'])+
            '\nANCHOR SUMMARY:\n'+json.dumps([{'heading':x['heading'],'text':x['text'][:180]} for x in anchor_summary],separators=(',',':')))
    else:
        research_prompt+='\nCURRENT HTML:\n'+content+'\nANCHOR HTML:\n'+Path(host.taste.policy['anchor']).read_text(encoding='utf-8')
    schema = deepcopy(REPLACEMENT_SCHEMA)
    if bounded:schema['properties']['alternatives']['maxItems']=2
    schema['properties']['alternatives']['items']['properties']['rowId'] = {'type':'string','enum':[r['rowId'] for r in research_rows]}
    for attempt in range(1, 4):
        destination = target / 'research' if attempt == 1 else target / 'research' / ('contract-attempt-' + str(attempt))
        if (destination / 'response.json').exists() and successful_call(destination) and not (destination/'contract-error.json').exists() and json.loads((destination/'response-schema.json').read_text())==schema:
            researched = json.loads((destination / 'response.json').read_text(encoding='utf-8'))
        else:
            researched, _ = invoke(research_prompt, destination, schema, search=True,
                bounded=bounded,model=host.taste.policy.get('model','gpt-6-luna'),effort='high' if bounded else 'medium',
                budget=host.taste.model_budget if bounded else None)
        try:
            execute(host, 'taste.record_research_addendum(' + json.dumps(current.name) + ',' + json.dumps(str(destination)) + ')')
        except RuntimeError as error:
            save(destination / 'contract-error.json', {'error':str(error),'sourceChanged':False})
            if attempt == 3:
                raise
            research_prompt += '\nHOST SOURCE CONTRACT REFUSAL:\n' + str(error) + '\nCorrect these proposals with a fresh actual lookup/open of each exact returned primary URL:\n' + json.dumps(researched)
            continue
        save(folder / 'host-state.json', host.taste.export_state())
        return researched


def _legacy_repair_round(host, current, folder, number, row, brief, manual):
    repair_started = time.monotonic()
    repair_started_at = datetime.now(timezone.utc).isoformat()
    content = current.read_text(encoding='utf-8')
    report = row['interaction']
    from grant_agent.taste_gate import driver_view
    current_fidelity = host.taste.fidelity(brief, row['critique'], content, report, Path(host.taste.policy['anchor']).read_text(encoding='utf-8'))
    target = folder / ('repair-' + str(number))
    research_rows = [r for r in row['critique']['differences'] if r['cause'] == 'research' and r['gap'] >= 2]
    researched = replacement_research(host, current, folder, target, research_rows, brief, content) if research_rows and re.search(r'\brare\b|\buncommon\b', brief, re.I) else None
    overlap_rows = [r for r in research_rows if re.search(r'overlap|imitat|copied|shared', json.dumps(r), re.I)]
    priority = ('This round must implement ONE verified alternative by replacing ONE mechanism the critic identifies '\
                'as shared with the anchor. Replace its section, actual handlers and source credit with mapped edits; '\
                'do not only rename it. Replacing a non-shared mechanism does not repair overlap. Preserve the '\
                'remaining page; subsequent rounds will fix remaining controls.\n') if overlap_rows else ''
    last_done = folder / ('done-' + str(number) + '.json')
    refusal = json.loads(last_done.read_text(encoding='utf-8')).get('text', '') if last_done.exists() else ''
    history = [{'round':previous['round'], 'quality':previous['critique']['quality'],
                'openDifferences':[{key:gap[key] for key in ('axis','selector','ours','repair')}
                    for gap in previous['critique']['differences'] if gap['gap'] >= 2],
                'appliedEdits':[{key:edit[key][:1200] for key in ('old','new')}
                    for edit in (previous.get('change') or {}).get('edits',[])[:8]]}
               for previous in host.taste.rounds.get(str(current.resolve()),[])[-3:]]
    prompt = (priority + 'You are the same Luna builder. LOOK at your own rendered images attached first, and the better '
              'anchor images after them. Apply only targeted repairs to the HTML. Return literal unique OLD/NEW '
              'substring edits with rowId from prior differences. The host applies these through workspace.patch; '\
              'you do not need filesystem write tools. Preserve the good parts. All edits must map to '
              'an actionable difference row; do not rewrite, overlap edits or touch over45% of characters/lines. '
              'Every control needs actual pointer/keyboard/touch effects. Avoid fake defects. If the critic passes '
              'choose a meaningful finishing improvement from its differences. Follow the explicit round priority; '\
              'without one, fix driver failures first. '
              'Use the reported input action: crossing uses Enter, drag uses ArrowRight, hold uses Space; '\
              'data-c13-key can declare a different actual keyboard equivalent. Scroll fields are exercised with '\
              'wheel, touch pan and PageDown. Declare data-c13-action as one exact lowercase word (drag, cross, hold, or click) on every gesture field '
              'so the driver exercises its advertised gesture rather than ordinary activation. '
              'Respect state preconditions: unavailable destinations must be '\
              'disabled until armed, and selected choices must visibly express their selection. Do not fake '\
              'an interaction with a counter or unrelated status change. '
              'Preserve existing keyboard handlers when repairing pointer input, and include every boundary, '
              'including the last one. Repair the mechanism described in the primary paper, not just the '
              'reported label. OrthoZoom requires independent perpendicular zoom and along-axis pan; '
              'combined drag distance is not orthogonal zoom. Use data-c13-path for its actual two-axis '
              'demonstration. Wrapped navigation must retain the wrapped cursor position when selecting '
              'a station; resetting it to the center hides wrapping. A hover preview must remain distinct '
              'from activation. For gathered proxies, keep local selection ordinals distinct from original '
              'event IDs so keyboard and pointer select the same actual event. '
              'Theme captures happen at rest before controls are exercised. Initialize the actual theme '\
              'from matchMedia(prefers-color-scheme: dark), then allow the theme button to override it. '\
              'Changing dark CSS alone cannot fix a page initialized unconditionally to light. '
              'If normal-motion frame hashes are unchanged, declared CSS or SVG motion is unproven in this '\
              'browser. Repair with observable requestAnimationFrame attribute updates respecting reduced motion, '\
              'or remove decorative motion and use an intentional static design. Do not keep editing unobserved '\
              'CSS/SMIL declarations. Current primary-credit URLs may already be repaired: read current HTML, '\
              'not the historical initial research URLs. LIVE WEB SEARCH is available for rare tasks; the '\
              'read-only sandbox does not prevent research. Verified alternative proposals below should '\
              'be implemented with small section/handler edits mapped to their research row, preserving '\
              'the remaining page. Return only real changes. Read the recent real feedback below: '
              'a mapped edit is not evidence that its visual or functional gap was removed. When the same '
              'material cause survives several reviews, change the repair approach within that section '
              'instead of repeating small text additions. For a readability/composition gap, consider the '
              'existing section layout, rendered text size and actual input-to-output example together; '
              'targeted CSS and section markup edits are permitted within the same churn limit.\n'
              'RECENT RENDERED FEEDBACK AND APPLIED EDITS:\n' + json.dumps(history) + '\n'
              'BRIEF:\n' + brief + '\nMANUAL:\n' + manual + '\nIMAGE CRITIQUE:\n' + json.dumps(row['critique']) +
              '\nVERIFIED RESEARCH PROPOSALS (must still implement and prove):\n' + json.dumps(researched) +
              '\nHOST COMPLETION REFUSAL:\n' + refusal +
              '\nHOST FIDELITY CHECKS:\n' + json.dumps(current_fidelity) +
              '\nINTERACTION REPORT:\n' + json.dumps(driver_view(report)) + '\nHTML:\n' + content)
    # Use the exact critic image packet, including readable tiles and gesture states.
    images = row['usage']['images']
    eligible = [r['rowId'] for r in row['critique']['differences'] if r['cause'] != 'keep']
    schema = deepcopy(REPAIR_SCHEMA)
    schema['properties']['edits']['items']['properties']['rowId'] = {'type': 'string', 'enum': eligible}
    for attempt in range(1, 9):
        destination = target if attempt == 1 else target / ('contract-attempt-' + str(attempt))
        if (destination / 'response.json').exists() and successful_call(destination):
            repair = json.loads((destination / 'response.json').read_text(encoding='utf-8'))
            usage = json.loads((destination / 'usage.json').read_text(encoding='utf-8'))
        else:
            repair, usage = invoke(prompt, destination, schema, images=images, search=bool(re.search(r'\brare\b|\buncommon\b', brief, re.I)), effort='high')
        errors = []
        for edit in repair['edits']:
            if edit['old'] == edit['new']:
                errors.append('Verification-only OLD == NEW is not a repair; remove that edit and retain actual fixes')
            if edit['rowId'] not in eligible:
                errors.append('Choose ONE exact actionable rowId: ' + json.dumps(eligible))
            if not edit['old'] or content.count(edit['old']) != 1:
                import difflib
                fragments = re.findall(r'<[^>]+>[^<]*', content) + content.splitlines()
                close = difflib.get_close_matches(edit['old'], fragments, n=2, cutoff=.35)
                errors.append('OLD must match once; found '+str(content.count(edit['old']))+' matches for '+json.dumps(edit['old'])+'. Closest exact source fragments: '+json.dumps(close))
        if not repair['edits']:
            errors.append('Supply a meaningful targeted repair')
        spans=sorted((content.index(edit['old']),content.index(edit['old'])+len(edit['old']),edit['old']) for edit in repair['edits'] if edit['old'] and content.count(edit['old'])==1)
        for left,right in zip(spans,spans[1:]):
            if left[1]>right[0]:
                errors.append('Literal edits overlap. Combine them into one unique OLD/NEW edit or remove one: '+json.dumps([left[2],right[2]]))
        if not errors:
            proposed = content
            for edit in repair['edits']:
                proposed = proposed.replace(edit['old'], edit['new'], 1)
            errors.extend(script_syntax_errors(proposed))
        if not errors:
            break
        save(destination / 'contract-error.json', {'errors': errors, 'sourceChanged': False})
        if attempt == 8:
            raise ValueError('Literal repair contract invalid after eight preserved attempts: ' + '; '.join(errors))
        prompt += ('\nHOST CONTRACT ERRORS:\n' + json.dumps(errors) +
                   '\nCorrect the literal edit contract below; preserve valuable targeted fixes, choose one exact rowId '
              'per edit and use the ORIGINAL HTML above. Do not combine IDs with slash. Prefer one or two small '\
                   'edits only when that is sufficient. Retain every independently valid repair verbatim; '
                   'correct or merge only the failing edits rather than dropping the other fixes. The host '
                   'applies all valid literal edits, so the read-only model sandbox is not a blocker.\n' + json.dumps(repair))
    edits = []
    for edit in repair['edits']:
        if not edit['old'] or content.count(edit['old']) != 1:
            raise ValueError('Repair must match one unique, nonempty old substring')
        start = content.index(edit['old'])
        edits.append({'start': start, 'end': start + len(edit['old']), 'text': edit['new'], 'expectedText': edit['old']})
    # Check literal substitutions before the host write; gate rejection rolls back
    # through the same hash-checked workspace API.
    expected = content
    for edit in repair['edits']:
        expected = expected.replace(edit['old'], edit['new'], 1)
    if expected == content:
        raise ValueError('Repair made no observable source change')
    call = {'path': current.name, 'expectedSha256': digest(current), 'edits': edits}
    execute(host, 'workspace.patch(' + ','.join(k + '=' + json.dumps(v, ensure_ascii=False) for k, v in call.items()) + ')')
    try:
        execute(host, 'taste.record_repair(' + json.dumps(current.name) + ',' + json.dumps(repair['edits'], ensure_ascii=False) + ')')
    except Exception:
        restore = {'path': current.name, 'expectedSha256': digest(current), 'content': content}
        execute(host, 'workspace.write(' + ','.join(k + '=' + json.dumps(v, ensure_ascii=False) for k, v in restore.items()) + ')')
        raise
    save(folder / 'host-state.json', host.taste.export_state())
    save(target / 'timing.json', {'startedAtUtc':repair_started_at,
         'finishedAtUtc':datetime.now(timezone.utc).isoformat(), 'elapsedSec':time.monotonic()-repair_started,
         'scope':'Full repair stage: source research, preserved contract retries, literal patch, host attestation and checkpoint',
         'beforeSha256':row['sha256'],'afterSha256':digest(current)})
    return usage


def repair_round(host, current, folder, number, row, brief, manual):
    if host.taste.policy.get('contextMode')!='bounded':
        return _legacy_repair_round(host,current,folder,number,row,brief,manual)
    from grant_agent.taste_context import SourceIndex, ContextBudgetError, bounded_prompt, driver_projection, image_packet, compact_manual
    started=time.monotonic()
    content=current.read_text(encoding='utf-8')
    target=folder/('repair-'+str(number));target.mkdir(parents=True,exist_ok=True)
    differences=[r for r in row['critique']['differences'] if r['cause']!='keep']
    differences.sort(key=lambda r:(r['gap']<2, {'research':0,'broken':1}.get(r['cause'],2),-r['gap']))
    from grant_agent.taste_laya import repair_route
    if host.taste.policy.get('requireLaya'):
        from grant_agent.laya_hooks import triage_taste, verify
        routing = {'route':'live-taste-triage','decision':None}
        routing['liveTriage'] = triage_taste(current.parent, row['pageChecks'])
        routing['liveVerify'] = verify('taste_triage', 'repair_first', row['pageChecks'], root=current.parent)
        if routing['liveTriage']['route'] == 'unavailable':
            raise RuntimeError('Live LAYA required before repair')
    else:
        routing=repair_route(current.parent,differences)
    save(target/'laya-repair-route.json',routing)
    if routing.get('route')=='laya':
        differences.sort(key=lambda d:d['rowId']!=routing['decision'])
    selected=[];windows=[]
    for diff in differences:
        diff=dict(diff)
        if diff['cause']=='broken' and ',' in diff['selector']:
            parts=[part.strip() for part in diff['selector'].split(',')]
            observed=driver_projection(row['interaction'])['controls']
            diff['selector']=next((part for part in parts if any(c['selector']==part for c in observed)),parts[0])
        try:
            proposed=SourceIndex(content).windows([d['selector'] for d in selected+[diff]])
        except ContextBudgetError:
            continue
        if windows and proposed==windows:continue
        selected.append(diff);windows=proposed
        if len(selected)>=1:break
    if not selected:raise ValueError('No bounded actionable section; preserve result and narrow difference selector')
    research_rows=[d for d in selected if d['cause']=='research']
    verified_research=replacement_research(host,current,folder,target,research_rows,brief,content) if research_rows else None
    selectors=[d['selector'] for d in selected]
    images,manifest=image_packet(row['interaction'],'Repair',target/'packet',selectors=selectors,actions=True,max_actions=2,rotation=number-1,max_images=4)
    from grant_agent.taste_checks import prompt_view
    data={'differences':selected,'sourceWindows':windows,'images':manifest,
          'observedChecks':prompt_view(row['pageChecks']),
          'driver':driver_projection(row['interaction'],selectors),
          'completionRefusal':json.loads((folder/('done-'+str(number)+'.json')).read_text(encoding='utf-8')).get('text','')[:600],
          'cachedResearch':host.taste.research['record'] if research_rows and host.taste.research else [],
          'verifiedRepairResearch':verified_research}
    instruction=('Repair only selected differences using unique literal OLD/NEW edits, rowId exact. '
                 'All OLD text must lie inside supplied sourceWindows; no rewrite or whole-file return. '
                 'A grouped difference may mention multiple mechanisms: repair ONLY the selected selector and its filtered driver failures in this call; other mechanisms have later rounds. '
                 'Preserve unaffected markup, CSS and handlers. Correct mechanisms and every input mode, not status alone. Do not replace a defining hold/drag/cross gesture with click merely to pass activation; marking menus need real dwell and quick directional strokes, drag-and-pop needs real dragging toward a reachable proxy. '
                 'If CSS transitions yield identical intermediate and settled frames under Obscura, use finite guarded requestAnimationFrame updates of actual visible attributes and palette tokens (350-450ms), and draw final states immediately under reduced motion. Adding probe attributes alone is not motion. '
                 'Crossing detects coordinate boundaries, drag uses ArrowRight, hold Space; data-c13-key overrides. Space means event.code===Space or event.key is one space; never compare event.key to the word Space. data-c13-action must be exactly one lowercase word: drag, cross, hold, or click. It is a protocol enum, never a sentence or pipe-separated list; put human instructions in visible text. '
                 'data-c13-path is JSON containing 2-16 normalized [x,y] pairs relative to the actual control box, not SVG or screen pixel coordinates. Each value is within -.25..1.25 and the first point inside 0..1; divide desired local coordinates by the owning control dimensions. '
                 'Reader captures theme at rest from matchMedia; honor reduced motion. '
                 'Prefer 1-4 small exact edits. Do not invent defects or re-research the concept. '
                 'Use verifiedRepairResearch first for a research defect: correct an existing credit or implement its verified alternative in the affected section. '
                 'Otherwise use a suitable cachedResearch proposal; never invent a DOI or change a title to match an unrelated paper. No new search during this repair call. '
                 'If context is insufficient, return no edits and request a precise source page with readRequests '
                 '(start,count<=6000), confined to the same affected section or its helper definitions. '
                 'No shell/browser/tools. Host applies hash-checked patches and verifies JS syntax.\n')
    schema=deepcopy(REPAIR_SCHEMA)
    schema['required'].append('readRequests')
    schema['properties']['readRequests']={'type':'array','maxItems':2,'items':object_schema({
        'start':{'type':'integer','minimum':0},'count':{'type':'integer','minimum':1,'maximum':6000}})}
    schema['properties']['edits']['items']['properties']['rowId']={'type':'string','enum':[d['rowId'] for d in selected]}
    errors=[]
    for attempt in range(1,4):
        destination=target/('attempt-'+str(attempt))
        prompt=bounded_prompt(brief,instruction+json.dumps(data,ensure_ascii=False,separators=(',',':'))+
                              '\nCONTRACT ERRORS:'+json.dumps(errors),destination,budget=16000,stable=compact_manual(manual,brief=brief)+'\nCONCEPT:\n'+json.dumps(host.taste.concept['record'],separators=(',',':')))
        cached_schema=destination/'response-schema.json'
        can_reuse=(successful_call(destination) and cached_schema.exists() and
            json.loads(cached_schema.read_text(encoding='utf-8'))==schema and digest(current)==row['sha256'] and
            (destination/'prompt.txt').exists() and (destination/'prompt.txt').read_text(encoding='utf-8')==prompt)
        if can_reuse:
            repair=json.loads((destination/'response.json').read_text(encoding='utf-8'))
            usage=json.loads((destination/'usage.json').read_text(encoding='utf-8'))
        else:
            repair,usage=invoke(prompt,destination,schema,images=images,effort='medium',bounded=True,
                model=host.taste.policy.get('model','gpt-6-luna'),budget=host.taste.model_budget)
        if repair['readRequests']:
            for request in repair['readRequests']:
                a,b=request['start'],min(len(content),request['start']+request['count'])
                # Paging is explicit and durable, but does not enlarge edit authority.
                data.setdefault('requestedPages',[]).append({'start':a,'end':b,'source':content[a:b],
                    'editAuthority':'Read-only page; changes remain confined to original section windows'})
            errors=['Requested pages supplied; return actual edits and empty readRequests'];continue
        errors=[];spans=[]
        for edit in repair['edits']:
            old=edit['old']
            if not old or old==edit['new'] or content.count(old)!=1:
                errors.append('OLD must match exactly once and differ from NEW: '+old[:180]);continue
            a=content.index(old);b=a+len(old)
            if not any(w['start']<=a and b<=w['end'] for w in windows):errors.append('OLD outside affected section windows')
            if any(a<end and b>start for start,end in spans):errors.append('OLD edits overlap')
            spans.append((a,b))
        if not repair['edits']:errors.append('Return an actual targeted edit')
        expected=content
        if not errors:
            for edit in repair['edits']:expected=expected.replace(edit['old'],edit['new'],1)
            errors+=script_syntax_errors(expected)
        if not errors:break
        save(destination/'contract-error.json',{'errors':errors,'sourceChanged':False})
        data['invalidEdits']=repair['edits']
    if errors:raise ValueError('Bounded repair contract failed: '+'; '.join(errors))
    edits=[{'start':content.index(e['old']),'end':content.index(e['old'])+len(e['old']),
            'text':e['new'],'expectedText':e['old']} for e in repair['edits']]
    call={'path':current.name,'expectedSha256':digest(current),'edits':edits}
    execute(host,'workspace.patch('+','.join(k+'='+json.dumps(v,ensure_ascii=False) for k,v in call.items())+')')
    try:
        execute(host,'taste.record_repair('+json.dumps(current.name)+','+json.dumps(repair['edits'],ensure_ascii=False)+')')
    except Exception:
        restore={'path':current.name,'expectedSha256':digest(current),'content':content}
        execute(host,'workspace.write('+','.join(k+'='+json.dumps(v,ensure_ascii=False) for k,v in restore.items())+')');raise
    save(folder/'host-state.json',host.taste.export_state())
    save(target/'scope.json',{'selectors':selectors,'windows':[{'start':w['start'],'end':w['end']} for w in windows],
         'sourceCharacters':sum(w['end']-w['start'] for w in windows),'wholeFileCharacters':len(content),
         'edits':repair['edits'],'beforeSha256':row['sha256'],'afterSha256':digest(current),'searchEnabled':False})
    save(target/'timing.json',{'elapsedSec':time.monotonic()-started,'scope':'Bounded repair including retries, patch and attestation'})
    return usage


def measured_usage(folder):
    from grant_agent.taste_model import rejected_before_inference
    rows=[]
    for path in folder.rglob('usage.json'):
        receipt=json.loads(path.read_text(encoding='utf-8'))
        events=path.parent/'events.jsonl'
        # Classify old transport's pre-inference rejection without rewriting raw
        # evidence. Generic failures and partial responses stay unknown.
        if not receipt.get('usageComplete') and events.exists() and rejected_before_inference(events.read_text(encoding='utf-8')):
            receipt={**receipt,'usageComplete':True,'costUsd':0,'rejectedBeforeInference':True,
                'usage':{'input_tokens':0,'cached_input_tokens':0,'output_tokens':0,'total_tokens':0},
                'derivedFrom':str(path),'classificationEventsSha256':digest(events)}
        rows.append(receipt)
    return rows


def counted_review_admissions(folder, admissions, stem):
    """A projection refusal with no provider-attempt directory is not a paid round."""
    ordinals={}
    count=0
    for admission in admissions:
        n=admission.get('acceptedRoundIndex')
        if n is None:
            count+=1;continue
        ordinal=ordinals.get(n,0)+1;ordinals[n]=ordinal
        suffix='' if ordinal==1 else '-attempt-'+str(ordinal)
        critic=folder/'evidence'/stem/('round-'+str(n)+suffix)/'critic'
        metrics=critic/'context-metrics.json'
        rendered=critic.parent/'render/report.json'
        preflight=(metrics.is_file() or rendered.is_file()) and not any(critic.glob('attempt-*'))
        if preflight:
            evidence=metrics if metrics.is_file() else rendered
            admission.update(countAgainstRoundBudget=False,refusal='Host preflight before provider invocation',
                             evidence=str(evidence),evidenceSha256=digest(evidence))
        else:
            admission['countAgainstRoundBudget']=True;count+=1
    return count


def check_budget(folder,args):
    ceiling=args.max_cost if args.max_cost is not None else (.45 if args.task=='T1' else 1.10)
    calls=measured_usage(folder)
    if any(r.get('costUsd') is None or r.get('usageComplete') is False for r in calls):
        raise ValueError('Unknown provider usage; fail closed and preserve receipts')
    spent=sum(r['costUsd'] for r in calls)
    tokens=sum(r['usage']['input_tokens']+r['usage']['output_tokens'] for r in calls)
    if spent>=ceiling or tokens>=args.max_tokens:raise ValueError('Run budget exhausted; preserve output and report incomplete')


def run(task, args):
    brief, name = tasks()[task], OUT[task]
    folder = (WT / args.output_root / task).resolve()
    workspace = folder / 'work'
    workspace.mkdir(parents=True, exist_ok=True)
    if not args.resume and (folder/'draft/usage.json').exists():
        raise ValueError('Fresh run requires a fresh output root; existing paid evidence is preserved')
    from grant_agent.taste_budget import TasteBudget
    budget=TasteBudget(max_rounds=args.max_rounds,max_tokens=args.max_tokens,
        max_usd=args.max_cost if args.max_cost is not None else (.45 if task=='T1' else 1.10),
        max_call_tokens=500000,max_call_usd=.85 if task=='T2' else .35)
    if args.fusion:
        budget.protected_usd = .04
    prior_draft=WT/('proof/r10' if args.r11 else 'proof/r8')/('arm-sol' if args.model=='gpt-6.1-sol' else 'arm-luna')/task/'draft/usage.json'
    if prior_draft.exists():
        prior=json.loads(prior_draft.read_text(encoding='utf-8'))
        if prior.get('model')==args.model and prior.get('usageComplete'):
            budget.calibration=[prior]
    if args.resume:
        for receipt in measured_usage(folder):
            # Rehydrate observed spend without creating a fictitious new call.
            budget.calls.append(receipt)
            if receipt.get('rejectedBeforeInference'):
                budget.capacity_rejections+=1
                budget.retry_model=args.model
                if budget.capacity_rejections>1:budget.closed_reason='Same-model capacity retry exhausted'
            elif receipt.get('budget',{}).get('closedReason'):
                budget.closed_reason=receipt['budget']['closedReason']
        if args.reconcile_reservation and budget.closed_reason=='Measured call exceeded its reservation; future calls blocked':
            totals=budget.snapshot()
            if (totals['usageComplete'] and totals['costUsd']<budget.limits['maxUsd'] and totals['totalTokens']<budget.limits['maxTokens']
                and all(r['costUsd']<=budget.limits['maxCallUsd'] and r['usage']['total_tokens']<=budget.limits['maxCallTokens'] for r in budget.calls)):
                save(folder/'reservation-reconciliation.json',{'previousReason':budget.closed_reason,
                    'observed':totals,'runCeilingsUnchanged':True,
                    'reason':'Explicitly reconcile an underestimated planning reservation inside the declared per-call and run ceilings; all raw receipts remain unchanged'})
                budget.closed_reason=None
    manual_path = WT / 'manuals/cl/taste.cl'
    manual = manual_path.read_text(encoding='utf-8')
    policy = {**json.loads((WT / 'config/c13-taste.json').read_text(encoding='utf-8')), 'required': True,
              'files': [name], 'brief': brief, 'port': args.port, 'manual': str(manual_path),
              'enginePort':args.engine_port or args.port+1,
              'anchor': str(WT / 'proof/r6-blind/arm-c' / name),
              'judge': str(WT / 'config/c13-judge.json'), 'evidenceDir': str(folder / 'evidence'),
              'contextMode': args.context_mode, 'model':args.model,
              'contextTokenBudget':16000, 'critiqueAttempts':2,
              'requireLaya':args.r11, 'correctiveChecks':args.r11, 'fusion':args.fusion,
              'budget':budget.limits}
    save(folder / 'policy.json', policy)
    (folder / 'task.txt').write_text(brief, encoding='utf-8')
    host = native_host(workspace, policy)
    host.taste.model_budget=budget
    manual_path, manual = host.taste.manual()
    receipts = []
    draft_path = folder / 'draft/response.json'
    if args.resume and draft_path.is_file() and len(json.loads(draft_path.read_text(encoding='utf-8')).get('html',''))>=1500:
        draft = json.loads(draft_path.read_text(encoding='utf-8'))
        usage = json.loads((folder / 'draft/usage.json').read_text(encoding='utf-8'))
    else:
        reading = None
        if args.fusion:
            from grant_agent.taste_fusion import read_brief
            reading_path = folder / 'reading/response.json'
            reading = json.loads(reading_path.read_bytes()) if args.resume and reading_path.exists() else read_brief(task, brief, manual, folder, budget)
        specific=(
            'T1 is an AI assistant presentation landing page: who you are, real capabilities, why use you. '
            'Keep the landing focused on its three questions. Return research: [] and concept.plannedElements: []. '
            'Use substantial illustrated sections and only controls that help the visitor. '
            'One simple working example can show a concrete capability; label sample data honestly. '
            'Choose a striking visual idea with detailed subject illustration, specific copy and thoughtful typography. '
            'The page should feel complete without a giant feature inventory.\n' if task=='T1' else
            'T2 requires LIVE SEARCH of GitHub and the web ONCE. In a few focused searches/openings read primary HCI sources; '
            'For concept.plannedElements name every mechanism you intend to implement; this is the brief quantity commitment, not a preset count. Choose and declare a substantial set of genuinely uncommon mechanisms that fits one specific subject outside fungi/woodland. Research twice as many candidates as you plan to implement. '
            'Return the researched candidate records with sourceKind paper/archive/author-repo/demo/article/pattern-library/docs. '
            'Credit every implemented element IN ITS SECTION with exact paper title, author, venue, year, primary HTTPS URL. '
            'An ordinary button/counter renamed after a paper does not implement the mechanism. All used algorithms must really work '
            'with pointer, touch and declared keyboard equivalents. Avoid hardware-only techniques and source overlap with common examples. '
            'Show useful subject data at rest in every mechanism. Do not repeat research during implementation.\n')
        prompt=('Complete the unchanged task below. Return one self-contained inline HTML file and the concept record. '
            'One strong specific idea; no generic slogans, invented proof or decorative watermarks. Plain, specific, honest voice: short sentences, tone fits the subject. Show input, work and output instead of selling benefits. No pitch phrases, promises or invented details. Preserve useful demonstrations and uncertainty. '
            'Concept: idea <=25 words, subject, three to six vernacular terms the page copy actually uses, one bold focus, quiet supporting choices, meaningful motion, rejected defaults. '
            'All controls work by actual pointer, keyboard and touch. Initialize light/dark from matchMedia and provide button data-c13-theme-toggle with a smooth 250ms theme transition. One observable entrance plus meaningful demo change and hover/press states; mark the demonstration control data-c13-motion-probe. At least two meaningful observed transitions. Respect reduced motion by drawing final states immediately, no animation loops or transitions. Responsive phone and visible focus. '
            'Prefer inline assets and system fonts. No file inputs, visible browser or shell tools. '
            'Give every section and control an id; section CSS/JS go in separate style/script blocks with data-c13-section="section-id". '
            'Obscura may not advance CSS transitions: use finite requestAnimationFrame updates of actual visible attributes and theme tokens when needed for observed intermediate frames (350-450ms); reduced motion draws the final state immediately. Do not use a decorative proxy animation. '
            'Shared helpers stay small. Custom gesture containers are focusable and declare data-c13-action as exactly one lowercase word (drag, cross, hold, or click), never an instruction sentence or pipe-separated list, '
            'data-c13-target when needed, keyboard equivalence, and data-c13-path for a two-axis demonstration. '
            'Use ordinary DOM or inline SVG with observable attribute updates. Avoid CSS-only/SMIL motion claims; '
            'requestAnimationFrame only for meaningful motion honoring reduced motion. Buttons must fit their labels. '
            'The host will render, critique, patch selected regions and verify completion.\n'+specific+
            'MANUAL:\n'+manual+'\nTASK (unchanged):\n'+brief)
        if args.context_mode=='bounded':
            from grant_agent.taste_context import compact_manual
            rubric=compact_manual(manual,rare=task=='T2')
            prompt=rubric+'\nTASK (unchanged):\n'+brief+'\n'+prompt.replace('MANUAL:\n'+manual+'\nTASK (unchanged):\n'+brief,'')
        check_budget(folder,args)
        draft_schema=deepcopy(DRAFT_SCHEMA)
        if task=='T2':draft_schema['properties']['concept']['properties']['plannedElements']['minItems']=1
        if reading:
            prompt += '\nLUNA READING (use these checked sources; no new search):\n' + json.dumps(reading) + '\nKeep the complete HTML under 18000 characters landing / 30000 rare UI. Sol owns concept and ambitious illustration; Luna will implement the many repairs.'
        draft, usage = invoke(prompt, folder / 'draft', draft_schema, search=task == 'T2' and not args.fusion,bounded=args.context_mode=='bounded',
            model='gpt-6.1-sol' if args.fusion else args.model,budget=budget,effort='low' if task=='T1' else 'medium',
            reservation_tokens=40000 if args.fusion else None,
            reservation_usd=(.10 if task=='T1' else .20) if args.fusion else None)
    receipts.append(usage)
    if args.generate_only:
        print(json.dumps({'task': task, 'draftGenerated': True, 'usage': usage}), flush=True)
        return
    save(folder / 'concept.json', {'concept': draft['concept'], 'research': draft['research'],
                                 'draftSha256': hashlib.sha256(draft['html'].encode()).hexdigest()})
    state_path = folder / 'host-state.json'
    if args.resume and state_path.exists():
        host.taste.restore_state(json.loads(state_path.read_text(encoding='utf-8')))
        host.taste.policy.update(port=args.port,enginePort=args.engine_port or args.port+1)
    elif not (workspace / name).exists():
        execute(host, 'taste.record_concept(' + json.dumps(draft['concept'], ensure_ascii=False) + ')')
        execute(host, 'taste.record_research(' + json.dumps(draft['research'], ensure_ascii=False) + ')')
    # Establish the grounded goal even before the deliverable exists.
    host.goals.append("'<!doctype html' in workspace.read(path=" + repr(name) + ")['content'].lower()")
    current = workspace / name
    if not current.exists():
        payload = {'path': name, 'content': draft['html']}
        execute(host, 'workspace.write(' + ','.join(k + '=' + json.dumps(v, ensure_ascii=False) for k, v in payload.items()) + ')')
        save(state_path, host.taste.export_state())
    if not (folder / 'before-done.json').exists():
        pre_done = host.execute('done("Draft ready")')
        save(folder / 'before-done.json', pre_done)
        if pre_done['ok']:
            raise RuntimeError('C13 incorrectly accepted a first draft')
    if args.draft_only:
        save(folder / 'draft-only.json', {'draftComplete': True, 'doneRefused': True, 'usage': usage})
        print(json.dumps({'task': task, 'draftComplete': True, 'doneRefused': True}), flush=True)
        return
    prior_rounds = host.taste.rounds.get(str(current.resolve()), [])
    # Failed reviews are rounds too. Bootstrap older receipts without erasing them,
    # then persist admission before rendering/inference so resume cannot reset it.
    admissions_path=folder/'review-admissions.json'
    if admissions_path.exists():
        admissions=json.loads(admissions_path.read_text(encoding='utf-8'))
    else:
        admissions=[{'recoveredUsage':str(p),'completedOrFailed':True} for p in sorted((folder/'evidence').rglob('usage.json'))
                    if p.parent.name=='attempt-1' or p.parent.name.startswith('attempt-1-resume-')]
        save(admissions_path,admissions)
    budget.rounds=max(len(prior_rounds),counted_review_admissions(folder,admissions,current.stem))
    if args.final_only:
        prior_rounds = []  # Final crop inspection uses the retained host state, without another repair admission.
    save(admissions_path,admissions)
    done = host.execute('done("' + name + ' is ready")')
    from grant_agent.taste_budget import BudgetExceeded
    try:
        if not done['ok'] and prior_rounds and prior_rounds[-1].get('manualSha256')==digest(WT/'manuals/cl/taste.cl') and prior_rounds[-1].get('interaction',{}).get('observer_sha256')==digest(WT/'scripts/c13_observed.mjs') and digest(current) == prior_rounds[-1]['sha256'] and (prior_rounds[-1].get('reviewScope')!='sections' or not (prior_rounds[-1]['critique']['passes'] and prior_rounds[-1]['interaction']['passed'] and prior_rounds[-1]['fidelity']['passed'] and not any(d['gap']>=2 for d in prior_rounds[-1]['critique']['differences']))) and not host.taste.pending_inspections(current,prior_rounds[-1]):
            check_budget(folder,args)
            receipts.append(repair_round(host, current, folder, len(prior_rounds), prior_rounds[-1], brief, manual))
        # Completed host rounds are recovered only from sealed evidence.
        for number in range(len(prior_rounds) + 1, args.max_rounds + 1):
            if done['ok'] or args.final_only:
                break
            print(json.dumps({'task': task, 'stage': 'review', 'round': number}), flush=True)
            check_budget(folder,args)
            budget.start_round()
            admissions.append({'acceptedRoundIndex':number,'admittedAt':time.time(),'attemptIndex':budget.rounds})
            save(admissions_path,admissions)
            execute(host, 'taste.review(' + json.dumps(name) + ')')
            row = host.taste.rounds[str(current.resolve())][-1]
            if args.r11:
                from grant_agent.taste_fusion import rollback_if_worse
                row = rollback_if_worse(host, current, row, folder)
            save(state_path, host.taste.export_state())
            receipts.append(row['usage'])
            done = host.execute('done("' + name + ' is ready")')
            save(folder / ('done-' + str(number) + '.json'), done)
            if done['ok'] or number == args.max_rounds:
                break
            if row.get('reviewScope')=='sections' and row['critique']['passes'] and row['interaction']['passed'] and row['fidelity']['passed'] and not any(d['gap']>=2 for d in row['critique']['differences']):
                continue
            check_budget(folder,args)
            receipts.append(repair_round(host, current, folder, number, row, brief, manual))
    except BudgetExceeded as error:
        save(folder/'budget-stop.json', {'reason':str(error),'budget':budget.snapshot(),
             'completionRefused':True,'evidencePreserved':True})
        done = {**done,'ok':False,'budgetStop':str(error)}
        retained=host.taste.rounds.get(str(current.resolve()),[])
        if retained and digest(current)!=retained[-1]['sha256']:
            save(folder/'unreviewed-budget-stop.json', {'sha256':digest(current),'restoredSha256':retained[-1]['sha256']})
            (folder/'unreviewed-budget-stop.html').write_bytes(current.read_bytes())
            current.write_bytes((Path(retained[-1]['folder'])/'artifact.html').read_bytes())
    if args.fusion:
        from grant_agent.taste_fusion import final_pass
        try:
            final = final_pass(host, current, folder, brief)
            if final['verdict'] != 'ready':
                done = {**done, 'ok':False, 'solFinalPass':final}
        except BudgetExceeded as error:
            done = {**done,'ok':False,'solFinalPassUnavailable':str(error)}
            save(folder/'sol-final/admission-stop.json', {'reason':str(error),'budget':budget.snapshot(),
                 'artifactSha256':digest(current),'completionRefused':True})
    receipts = measured_usage(folder)
    result = {'schema': 'neyvia.C13-run.v1', 'task': task, 'brief': brief, 'doneOk': done['ok'],
              'doneStatus': host.done_status, 'rounds': len(host.taste.rounds[str(current.resolve())]),
              'qualityByRound': [r['critique']['quality'] for r in host.taste.rounds[str(current.resolve())]],
              'usage': receipts, 'costUsd': sum(r['costUsd'] for r in receipts),
              'modelElapsedSec': sum(r['elapsedSec'] for r in receipts),
              'taskElapsedSec': time.time() - ((folder / 'draft/usage.json').stat().st_mtime - usage['elapsedSec']),
              'outputSha256': digest(current),
              'differenceReport': str(folder / 'evidence/rounds.json')}
    result.update(model=args.model,budget=budget.snapshot(),
        tokens={k:sum(r['usage'].get(k,0) for r in receipts) for k in ('input_tokens','cached_input_tokens','output_tokens','total_tokens')})
    final = WT / args.output_root / name
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(current.read_bytes())
    save(folder / 'result.json', result)
    print(json.dumps({k: result[k] for k in ('task', 'doneOk', 'rounds', 'qualityByRound', 'costUsd')}), flush=True)


if __name__ == '__main__':
    install_hidden_subprocess_default()
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_WATCHDOG_AUTOSTART='0', NEYVIA_COORDINATOR_AUTOSTART='0')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', choices=['T1', 'T2'])
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--engine-port',type=int,choices=range(48801,48810))
    parser.add_argument('--max-rounds', type=int, default=6, help='Hard review round budget including final global check')
    parser.add_argument('--max-cost', type=float, help='USD list-price equivalent admission ceiling; default .45/1.10')
    parser.add_argument('--max-tokens', type=int, default=1000000, help='Total input plus output admission budget, cached included')
    parser.add_argument('--model',choices=['gpt-6-luna','gpt-6.1-sol'],default='gpt-6-luna')
    parser.add_argument('--fusion', action='store_true', help='Sol draft/final crops, Luna reading and repairs')
    parser.add_argument('--r11', action='store_true', help='Require live LAYA, staged corrective checks and score rollback')
    parser.add_argument('--final-only', action='store_true', help='Use the protected Sol final-crop reservation after repair admission closes')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--reconcile-reservation',action='store_true',help='Explicitly recover an underestimated call reservation only inside unchanged run/per-call ceilings')
    parser.add_argument('--output-root', default='proof/r8/arm-luna', help='Separate evidence/output root; prior work remains intact')
    parser.add_argument('--context-mode', choices=['bounded', 'legacy'], default='bounded')
    parser.add_argument('--draft-only', action='store_true')
    parser.add_argument('--generate-only', action='store_true', help='Generate one draft while host/browser work continues; resume never regenerates it')
    args = parser.parse_args()
    if args.fusion:
        args.model = 'gpt-6-luna'
        args.r11 = True
    if args.r11:
        os.environ['NEYVIA_LAYA_URL'] = 'http://127.0.0.1:48809'
    if args.port not in range(48801, 48809) or args.max_rounds < 1:
        parser.error('Assigned port 48801-48808 (adjacent engine port) and positive review budget required')
    try:
        run(args.task, args)
    except Exception as exc:
        folder=(WT/args.output_root/args.task).resolve()
        calls=measured_usage(folder)
        rounds_path=folder/'evidence/rounds.json'
        rounds=json.loads(rounds_path.read_text(encoding='utf-8')) if rounds_path.exists() else {}
        rows=next(iter(rounds.values()),[])
        result={'schema':'neyvia.C13-run.v1','task':args.task,'model':args.model,'doneOk':False,
            'error':str(exc),'rounds':len(rows),'qualityByRound':[r['critique']['quality'] for r in rows],
            'usage':calls,'costUsd':sum(r.get('costUsd') or 0 for r in calls),
            'tokens':{k:sum(r.get('usage',{}).get(k,0) for r in calls) for k in ('input_tokens','cached_input_tokens','output_tokens','total_tokens')},
            'modelElapsedSec':sum(r.get('elapsedSec',0) for r in calls),'usageComplete':all(r.get('usageComplete') for r in calls)}
        current=folder/'work'/OUT[args.task]
        if current.exists():
            (WT/args.output_root/OUT[args.task]).write_bytes(current.read_bytes())
            result['outputSha256']=digest(current)
        if rows:
            result.update(differenceReport=str(rounds_path),screenshots=rows[-1]['interaction']['screenshots'],
                latestCritique=rows[-1]['critique'],driverPass=rows[-1]['interaction']['passed'],fidelity=rows[-1]['fidelity'])
        save(folder/'failure.json',result)
        print(json.dumps({k:result[k] for k in ('task','model','error','rounds','costUsd')}),flush=True)
        raise
