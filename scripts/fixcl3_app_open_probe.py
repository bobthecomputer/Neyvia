"""Real app-open journeys, called inside the owned Neyvia renderer harness."""
from __future__ import annotations

import hashlib
import json
import time


def app_open_extension(receipt, checks, cl, dom, ui, session, root, service, state):
    from grant_agent.cl.renderer_effects import observe
    from grant_agent.cl.app_open_effects import SUPPORTED

    receipt['appOpenBoundary'] = 'Actual mounted Neyvia file editor and text artifact preview, real HTTP CL/manual execution and renderer POST acknowledgements; no synthetic renderer state.'
    receipt['manualReceipts'] = []
    receipt['appOpenRemainingGaps'] = {
        'neyvia.notes.open': 'notes.open queues standalone notes app; production PaneObserver does not receive its event or acknowledge mounted note text.',
        'neyvia.onboarding.open': 'onboarding.open controls setup overlay; no production mounted step/runtime/content acknowledgement.',
        'neyvia.app_sdk.preview': 'mobile.preview queues Mobile Studio app; no production phone-frame app/runtime/content acknowledgement.',
        'otherAppKinds': 'Only the retained file-editor and plain artifact text projections are admitted by this layer.',
        'binaryArtifact': 'Binary preview content projections require separate retained positive witnesses.'}
    cases = [('neyvia.app.open', {'app': 'file', 'target': str(root / 'app-open.txt')}),
             ('neyvia.artifact.open', None)]
    if {name for name, _ in cases} != SUPPORTED:
        raise ValueError('Every admitted adapter requires a retained renderer witness')
    app_path = root / 'app-open.txt'
    artifact_path = root / 'publication-open.txt'
    app_path.write_text('Actual app alias editor text\n', encoding='utf-8', newline='\n')
    artifact_path.write_text('Actual registered publication editor text\n', encoding='utf-8', newline='\n')
    published = service.call('artifact.publish', {'path': str(artifact_path), 'title': 'Disposable text publication'})
    receipt['appOpenPublication'] = published
    if published.get('ok') is not True:
        raise ValueError('Disposable artifact publication failed')
    cases[1] = (cases[1][0], {'id': published['artifact']['id']})

    def wait(event_id, predicate, seconds=25):
        stop = time.time() + seconds
        value = observe(service.bus, event_id)
        while time.time() < stop and not predicate(value):
            time.sleep(.25)
            value = observe(service.bus, event_id)
        return value

    projection = """() => { const el=document.querySelector('.nx-pane-observed'); const editor=el?.querySelector('textarea');
      return el ? {paneId:el.dataset.paneId,runtimeId:el.dataset.runtimeId,contentHash:el.dataset.contentHash,
        observation:el.dataset.observation,editorText:editor?.value ?? el.querySelector('.nx-ap-text')?.textContent ?? null} : null; }"""
    for name, payload in cases:
        key = name.removeprefix('neyvia.')
        token = session()
        path = app_path if key == 'app.open' else artifact_path
        saved = path.read_bytes()
        digest = hashlib.sha256(saved).hexdigest()
        inputs = ','.join(k + '=' + json.dumps(v) for k, v in payload.items())
        old_event_ids = {row['id'] for row in service.bus.since(0) if row['action'] == 'pane.show'}
        result = cl(key, 'manualOpen', 'G: pane.observe().visible == True\nrun local-app-open.open-' + name.replace('.', '-') + '(' + inputs + ')', token)
        events = [row for row in service.bus.since(0) if row['action'] == 'pane.show']
        event = events[-1]
        if event['id'] in old_event_ids:
            raise ValueError(name + ' did not dispatch a new pane request; cannot reuse a previous positive renderer')
        observed = wait(event['id'], lambda row: row.get('acknowledged') and row.get('visible'))
        rendered = dom(projection)
        receipt['journeys'][key].update(event=event, observed=observed, rendered=rendered,
                                        expectedHash=digest, sourcePath=str(path))
        checks[key + '.pendingUntilMounted'] = result.get('ok') is False
        checks[key + '.actualMountedVisible'] = all(observed.get(k) is True for k in ('acknowledged', 'mounted', 'visible', 'fresh', 'current', 'contentMatches'))
        checks[key + '.exactDisplayedText'] = bool(rendered and rendered.get('editorText') is not None and
            hashlib.sha256(rendered['editorText'].encode()).hexdigest() == digest == observed.get('contentHash') == rendered.get('contentHash'))
        checks[key + '.exactMountedRuntime'] = bool(rendered and rendered.get('paneId') == observed.get('paneId') == event['payload'].get('paneId') and
            rendered.get('runtimeId') == observed.get('runtimeId') and observed.get('runtimeId', '').startswith('file-editor:' if key == 'app.open' else 'artifact-text:'))
        checks[key + '.doneAfterRealAck'] = cl(key, 'doneAfterAck', 'done()', token).get('ok') is True
        uses = [row['payload'] for row in service.bus.since(0) if row['action'] == 'cl.manual.use' and
                row['payload'].get('tool') == name and row['payload'].get('manual') == 'local-app-open']
        receipt['journeys'][key]['manualReceipts'] = uses
        receipt['manualReceipts'].extend(uses)
        checks[key + '.manualReceipt'] = len(uses) == 1 and uses[0].get('status') == 'admitted' and bool(uses[0].get('effectChecks'))
        checks[key + '.freshDoneAgain'] = cl(key, 'freshDoneAgain', 'done()', token).get('ok') is True
        path.write_bytes(saved + b'Independent source byte drift\n')
        receipt['journeys'][key]['afterByteDrift'] = observe(service.bus, event['id'])
        checks[key + '.byteDriftDoneRefused'] = cl(key, 'byteDrift', 'done()', token).get('ok') is False
        path.write_bytes(saved)
        if key == 'artifact.open':
            closed = dom('() => { const b=document.querySelector(\'.nx-stage-head button[aria-label^="Close"]\'); if(b)b.click(); return !!b; }')
            gone = wait(event['id'], lambda row: row.get('mounted') is False and row.get('fresh'))
            receipt['journeys'][key]['afterUnmount'] = gone
            checks[key + '.actualUnmount'] = bool(closed and gone.get('mounted') is False and gone.get('visible') is False)
            checks[key + '.unmountedDoneRefused'] = cl(key, 'unmountedDone', 'done()', token).get('ok') is False
    # The same real UI goes away. A new request cannot complete from queue delivery.
    ui(lambda: state['page'].close())
    token = session()
    result = cl('app.open.missingRenderer', 'request', 'G: pane.observe().visible == True\nrun local-app-open.open-neyvia-app-open(app="file",target=' + json.dumps(str(app_path)) + ')', token)
    event = next(row for row in reversed(service.bus.since(0)) if row['action'] == 'pane.show')
    missing = observe(service.bus, event['id'])
    receipt['journeys']['app.open.missingRenderer'].update(event=event, observed=missing)
    checks['app.open.missingRenderer.pending'] = result.get('ok') is False and missing.get('acknowledged') is False
    checks['app.open.missingRenderer.doneRefused'] = cl('app.open.missingRenderer', 'done', 'done()', token).get('ok') is False
    receipt['appOpenCheckCount'] = len([name for name in checks if name.startswith(('app.open.', 'artifact.open.'))])
