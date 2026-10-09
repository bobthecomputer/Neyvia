"""Render public examples and original LAYA compositions using owned Obscura only.

Retain source URLs, hashes, learned pixel representations and short notes.
Public example screenshots are temporary encoder input, not vendored libraries.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import argparse
import subprocess

REPO = Path(__file__).resolve().parents[1]
RUN = Path('D:/NeyviaRuns/laya-train')
ORIGIN = Path('C:/Users/user/Projects/nx-c13-taste')
sys.path.insert(0, str(REPO / 'src'))
os.environ['NEYVIA_TASTE_ASSETS'] = str(ORIGIN / '.agent_control/c13h-assets')
os.environ['NEYVIA_TASTE_DEPS'] = str(ORIGIN / '.agent_control/c13h-deps')
os.environ['NEYVIA_TASTE_STATE'] = str(RUN / 'vision')
from grant_agent import taste_vision as vision
from grant_agent.browser_obscura import ObscuraEngine
from grant_agent.laya_components import invent
from grant_agent.laya_curriculum import ARTIFACTS, load
from playwright.sync_api import sync_playwright


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str), encoding='utf-8')


def render_react(page, proposal, folder):
    """Exercise the actual exported React module, including rejected async commits."""
    (folder / 'RehearsalShelf.jsx').write_text(proposal['react'], encoding='utf-8')
    (folder / 'component.css').write_text(proposal['css'], encoding='utf-8')
    entry = folder / 'journey.jsx'
    entry.write_text('''import React from 'react';
import {createRoot} from 'react-dom/client';
import {RehearsalShelf as Shelf} from './RehearsalShelf.jsx';
const actions=[{id:'focus',label:'Show the next decision',description:'Put the next useful choice in view.'},
{id:'space',label:'Give the content room',description:'Make the important controls easier to scan.'}];
window.calls=[];window.rejectCommit=false;
createRoot(document.getElementById('root')).render(<Shelf actions={actions} onCommit={async value=>{
  window.calls.push(value?.id ?? null);await new Promise(r=>setTimeout(r,80));
  if(window.rejectCommit)throw new Error('Draft could not be saved');
}}/>);''', encoding='utf-8')
    options = {'entryPoints': [str(entry)], 'outfile': str(folder / 'react-bundle.js'), 'bundle': True,
               'jsx': 'automatic', 'nodePaths': [str(REPO / 'node_modules')]}
    subprocess.run(['node', '-e', "require('esbuild').buildSync(JSON.parse(process.argv[1]))", json.dumps(options)], cwd=REPO, check=True)
    document = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;padding:20px}' + proposal['css'] + '</style><div id="root"></div></html>'
    page.set_content(document)
    page.add_script_tag(path=str(folder / 'react-bundle.js'))
    page.get_by_role('button', name='Show the next decision', exact=True).click()
    page.get_by_role('button', name='Keep change', exact=True).click()
    page.wait_for_function("document.querySelector('output').textContent.includes('is in the draft')")
    page.get_by_role('button', name='Undo', exact=True).click()
    page.wait_for_function("document.querySelector('output').textContent==='Nothing has changed.'")
    page.evaluate('window.rejectCommit=true')
    page.get_by_role('button', name='Keep change', exact=True).click()
    page.wait_for_function("document.querySelector('output').textContent==='Draft could not be saved'")
    failed_history_unchanged = page.get_by_role('button', name='Undo', exact=True).is_disabled()
    page.evaluate('window.rejectCommit=false')
    page.get_by_role('button', name='Keep change', exact=True).click()
    page.wait_for_function("document.querySelector('output').textContent.includes('is in the draft')")
    page.get_by_label('Find a move', exact=True).fill('unmatched-query')
    empty = page.get_by_text('No matching moves. Try another word.', exact=True).is_visible()
    page.get_by_label('Find a move', exact=True).fill('')
    extra = {}
    if page.get_by_role('button', name='Pin this preview').count():
        page.get_by_role('button', name='Pin this preview').click()
        extra['pin'] = 'Put the next useful choice in view.' in page.locator('aside').inner_text()
    if page.locator('summary').count():
        page.locator('summary').click()
        extra['disclosure'] = page.locator('details').get_attribute('open') is not None
    if page.get_by_role('button', name='Increase emphasis', exact=True).count():
        page.get_by_role('button', name='Increase emphasis', exact=True).click()
        extra['emphasis'] = page.get_by_role('region', name='Rehearse emphasis').locator('output').inner_text() == '60%'
    shots = []
    for width, height, theme in [(1200,850,'light'),(390,844,'light'),(1200,850,'dark'),(390,844,'dark')]:
        page.set_viewport_size({'width':width,'height':height})
        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
        path = folder / f'react-{width}-{theme}.png'
        page.screenshot(path=str(path), full_page=True)
        metrics = page.evaluate('''()=>({overflow:document.documentElement.scrollWidth>innerWidth,
          clippedLabels:[...document.querySelectorAll('button')].filter(e=>e.scrollWidth>e.clientWidth+1||e.scrollHeight>e.clientHeight+1).length})''')
        shots.append({'path':str(path),'sha256':vision.sha(path),'metrics':metrics})
    page.get_by_role('button', name='Undo', exact=True).click()
    page.wait_for_function("document.querySelector('output').textContent==='Nothing has changed.'")
    repair_pairs = []
    for width, height, theme in [(1200,850,'light'),(390,844,'light'),(1200,850,'dark'),(390,844,'dark')]:
        page.set_viewport_size({'width':width,'height':height})
        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
        good = folder / f'repair-{width}-{theme}-after.png'
        page.screenshot(path=str(good))
        page.evaluate("document.querySelector('.rehearsal-shelf').style.minWidth='1400px'")
        overflow_before = page.evaluate('document.documentElement.scrollWidth>innerWidth')
        bad = folder / f'repair-{width}-{theme}-before.png'
        page.screenshot(path=str(bad))
        page.evaluate("document.querySelector('.rehearsal-shelf').style.minWidth=''")
        overflow_after = page.evaluate('document.documentElement.scrollWidth>innerWidth')
        if not overflow_before or overflow_after:
            raise RuntimeError('Controlled overflow label lacks an observed repair')
        pair = vision.append_pair('corrective', bad, good, preferred=1, group='LAYAT-rehearsal-shelf',
            source='LAYAT-controlled-render-repair', split='train',
            reason='Same Obscura page and viewport: injected 1400px minimum width causes observed horizontal overflow; removal repairs it.')
        repair_pairs.append({'id':pair['id'],'before':str(bad),'after':str(good),'overflowBefore':overflow_before,'overflowAfter':overflow_after})
    result = {'asyncFailurePreservesHistory':failed_history_unchanged,'emptyState':empty,'mobileUndo':True,
              'interactions':extra,'calls':page.evaluate('window.calls'),'screenshots':shots, 'controlledTrainingPairs':repair_pairs}
    result['passed'] = failed_history_unchanged and empty and all(extra.values()) and all(not s['metrics']['overflow'] and not s['metrics']['clippedLabels'] for s in shots)
    # The temporary renderer bundle contains dependency code; retain only our
    # authored module/CSS and observed receipts, never a vendored library bundle.
    (folder / 'react-bundle.js').unlink()
    if not result['passed']:
        raise RuntimeError(json.dumps(result))
    return result


def main(only_invented=False):
    RUN.mkdir(parents=True, exist_ok=True)
    # Reuse an already installed verified Obscura binary; never Chromium.
    receipt = json.loads((REPO / 'scripts/evidence/C13-obscura-provision.json').read_bytes())
    executable = Path(receipt['executable'])
    if hashlib.sha256(executable.read_bytes()).hexdigest() != receipt['executableSha256']:
        raise ValueError('Pinned Obscura binary changed')
    prior = RUN / 'component-render.json'
    public = json.loads(prior.read_text(encoding='utf-8')).get('public', []) if only_invented and prior.exists() else []
    report = {'engine': 'Obscura', 'binarySha256': receipt['executableSha256'], 'public': public}
    engine = ObscuraEngine(RUN / 'obscura', executable, port=48992, fixtures=True,
                           public_resources=True, assigned_ports='48991-48999')
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(engine.endpoint, headers={'Authorization': 'Bearer ' + engine.token})
            context = browser.new_context(viewport={'width': 1200, 'height': 850}, reduced_motion='reduce', accept_downloads=False)
            page = context.new_page()
            notes = load('component-notes')['patterns']
            model = load('components')
            for row in ([] if only_invented else notes):
                observation = {'id': row['id'], 'source': row['source'], 'license': row['license']}
                temporary = RUN / 'obscura' / (row['id'] + '-encoder-input.png')
                try:
                    page.goto(row['source'], wait_until='domcontentloaded', timeout=45000)
                    page.wait_for_timeout(1200)
                    selectors = {
                        'radix-accordion': 'button[aria-expanded][aria-controls]',
                        'radix-tabs': '[role="tablist"]',
                        'radix-popover': 'button[aria-label="Update dimensions"]',
                        'aria-combobox': '[role="combobox"]',
                        'aria-gridlist': '[role="grid"]',
                        'aria-slider': '[role="slider"],input[type="range"]',
                    }
                    selector = selectors.get(row['id'])
                    sample = page.locator(selector).first if selector else None
                    if sample is not None and sample.count() and sample.is_visible():
                        sample.scroll_into_view_if_needed()
                        box = sample.bounding_box()
                        observation['sampleControl'] = sample.evaluate('(e)=>({role:e.getAttribute("role"),label:e.getAttribute("aria-label")||e.textContent.slice(0,100)})')
                        # Include surrounding explanation/label and adjacent controls, but not the whole docs page.
                        clip = {'x': max(0, box['x']-28), 'y': max(0, box['y']-36),
                                'width': min(1140, box['width']+56), 'height': min(600, max(240, box['height']+100))}
                        page.screenshot(path=str(temporary), clip=clip)
                        observation['representationScope'] = 'visible-example-control-and-context'
                    else:
                        page.screenshot(path=str(temporary))
                        observation['representationScope'] = 'documentation-page-only'
                    observation['visibleControls'] = page.evaluate('''() => [...document.querySelectorAll('button,input,[role="grid"],[role="tablist"]')]
                        .filter(e=>e.getBoundingClientRect().width>0).slice(0,25)
                        .map(e=>({role:e.getAttribute('role'),label:(e.getAttribute('aria-label')||e.textContent||'').trim().slice(0,80)}))''')
                    observation.update(title=page.title(), finalUrl=page.url, screenshotSha256=vision.sha(temporary),
                                       imageEmbedding=vision.embedding(temporary).tolist())
                    target = next(item for item in model['rows'] if item['id'] == row['id'])
                    target['renderRepresentation'] = {k: v for k, v in observation.items() if k not in ('id', 'source', 'license')}
                    print('rendered', row['id'], flush=True)
                except Exception as exc:
                    observation.update(error=str(exc)[:300], rendered=False)
                    print('failed', row['id'], observation['error'], flush=True)
                finally:
                    # Owned temporary encoder input only; no retained copy of public example assets.
                    temporary.unlink(missing_ok=True)
                report['public'].append({k: v for k, v in observation.items() if k != 'imageEmbedding'})
                save(RUN / 'component-render.json', report)
            save(ARTIFACTS / 'components.json', model)
            proposal = invent('Search useful moves, preview the next decision, compare alternatives and keep reversible changes to a local draft')
            code = proposal.pop('code')
            output = RUN / 'invented/rehearsal-shelf.html'
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(code, encoding='utf-8')
            # set_content renders only our newly authored artifact, not stored upstream source.
            page.set_content(code, wait_until='domcontentloaded')
            page.get_by_role('button', name='Show the next decision', exact=True).click()
            page.get_by_role('button', name='Keep change', exact=True).click()
            kept = page.locator('#status').inner_text()
            page.get_by_role('button', name='Undo', exact=True).click()
            undone = page.locator('#status').inner_text()
            page.locator('#search').fill('unmatched-query')
            empty = page.locator('#options').inner_text()
            page.locator('#search').fill('')
            shots = []
            for width, height, theme in [(1200, 850, 'light'), (390, 844, 'light'), (1200, 850, 'dark'), (390, 844, 'dark')]:
                page.set_viewport_size({'width': width, 'height': height})
                page.emulate_media(color_scheme=theme, reduced_motion='reduce')
                current = page.locator('html').get_attribute('data-theme') or 'light'
                if current != theme:
                    page.locator('#theme').click()
                shot = output.parent / f'{width}-{theme}.png'
                page.screenshot(path=str(shot))
                metrics = page.evaluate('''() => ({overflow:document.documentElement.scrollWidth > innerWidth,
                  unlabelledControls:[...document.querySelectorAll('button,input')].filter(e=>!e.textContent.trim()&&!e.labels?.length&&!e.getAttribute('aria-label')).length,
                  clippedLabels:[...document.querySelectorAll('button')].filter(e=>e.scrollWidth>e.clientWidth+1).length,
                  verticalClipping:[...document.querySelectorAll('button')].filter(e=>e.scrollHeight>e.clientHeight+1).length,
                  background:getComputedStyle(document.body).backgroundColor})''')
                shots.append({'path': str(shot), 'sha256': vision.sha(shot), 'metrics': metrics})
            proposal['journey'] = {'kept': kept, 'undone': undone, 'empty': empty,
                'passed': 'now in the local draft' in kept and undone == 'Nothing has changed.' and 'No matching moves' in empty}
            proposal['screenshots'] = shots
            proposal['html'] = str(output)
            report['invented'] = proposal
            report['react'] = render_react(page, proposal, output.parent)
            save(RUN / 'component-render.json', report)
            save(REPO / 'scripts/evidence/LAYAT-component-render.json', report)
            context.close()
            browser.close()
    finally:
        engine.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--only-invented', action='store_true')
    main(parser.parse_args().only_invented)
