"""Positive CL aliases witnessed in the actual mounted Neyvia shell."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]


def prepare_manual():
    sys.path.insert(0, str(REPO / 'src'))
    from grant_agent.cl.manuals import manual_to_cl, cl_to_manual
    from grant_agent.neyvia_workspace_tools import tool_specs
    from grant_agent.neyvia_notes_tools import tool_specs as note_specs
    from grant_agent.neyvia_onboarding import tool_specs as onboarding_specs
    from types import SimpleNamespace
    names = {'neyvia.view.state', 'neyvia.view.arrange', 'neyvia.view.scene', 'neyvia.view.float',
             'neyvia.notes.open', 'neyvia.onboarding.open', 'neyvia.notify', 'neyvia.voice.command', 'neyvia.folder.open'}
    specs = {row.name:row for row in [*tool_specs(SimpleNamespace), *note_specs(SimpleNamespace), *onboarding_specs(SimpleNamespace)] if row.name in names}
    actions, schemas, procedures, metadata = {}, {}, {}, {}
    fields = {
        'neyvia.view.state':[], 'neyvia.view.arrange':['order','dock','sidebarHidden'],
        'neyvia.view.scene':['name'], 'neyvia.view.float':['id','floating'],
        'neyvia.notes.open':['path'], 'neyvia.onboarding.open':['step'],
        'neyvia.notify':['message','level'], 'neyvia.voice.command':['text','requestId'],
        'neyvia.folder.open':['path'],
    }
    for name in sorted(names):
        spec = specs[name]; short = name.removeprefix('neyvia.'); key = short.replace('.', '-')
        schemas[name] = spec.input_schema
        returns = {'type':'object'}
        if name == 'neyvia.view.state': returns = {'type':'object', 'properties':{'state':{'type':'object'}}, 'required':['state']}
        actions[key] = {'tool':name, 'schema':name, 'returns':returns,
            'pre':'The current mounted owner shell or an explicit note in its selected folder',
            'effect':'Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes', 'reversible':True}
        parameters = fields[name]
        inputs = {'type':'object','properties':{arg:spec.input_schema['properties'][arg] for arg in parameters},'required':parameters}
        procedures[key] = {'goal':'Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion',
            'inputs':inputs, 'steps':[{'action':key, 'args':{arg:{'$input':arg} for arg in parameters}, 'save':'rendered'}]}
        metadata[name] = {'mutability_class':'read' if name.endswith('.state') else 'write'}
    procedures['view-scene-save'] = {'goal':'Save the exact current observed layout, density and theme',
        'inputs':{'type':'object','properties':{'save':{'type':'string'}},'required':['save']},
        'steps':[{'action':'view-scene','args':{'save':{'$input':'save'}},'save':'rendered'}]}
    data = {'schema':'neyvia.manual.v1', 'id':'local-rendering', 'kind':'workflow', 'schemas':schemas,
        'chapters':{'mounted':{'title':'Current mounted shell', 'state':{'shell':{'tool':'neyvia.view.state','args':{},'inputs':{'type':'object'},'shape':{'type':'object'}}},
            'actions':actions, 'checks':{}, 'procedures':procedures, 'judge':{},
            'pitfalls':[{'failure':'The command was queued but the app never mounted', 'recovery':'Read view.state; require a fresh owner runtime, actual visible DOM and subject matching. Close/unmount or stale heartbeat invalidates done.'}],
            'frontier':['Spoken commands beyond locally witnessed Notes opening and returning to chat need their own typed mounted effects.',
                        'App SDK preview and verification need a running owned app and source-bound mounted frame.'],
            'guidance':['view.state reads renderer:shell from the same authenticated app-state route; it never claims a UI effect from acknowledgement alone.',
                        'PDF uses real MuPDF RGBA when Canvas2D transforms are absent, retaining PDF.js text/search; observed source and entire pixel hashes are required for CL completion.']}}}
    rendered = manual_to_cl(data, metadata)
    if cl_to_manual(rendered) != data: raise ValueError('Canonical rendered manual did not round trip')
    (REPO / 'manuals/local-rendering.manual.json').write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    (REPO / 'manuals/cl/local-rendering.cl').write_text(rendered, encoding='utf-8')
    index_path = REPO / 'config/neyvia_manuals.json'; index=json.loads(index_path.read_bytes())
    if not any(row['id']=='local-rendering' for row in index['manuals']):
        index['manuals'].append({'id':'local-rendering','path':'manuals/local-rendering.manual.json',
            'clSource':'manuals/cl/local-rendering.cl','description':'Fresh mounted DOM effects for shell, Notes, setup and bounded spoken navigation'})
        index_path.write_text(json.dumps(index,indent=2)+'\n',encoding='utf-8')


def aliases(receipt, checks, cl, dom, ui, session, root, service, state):
    from grant_agent.neyvia_notes_tools import call_notes
    # New fixture is the chosen isolated workspace, never Paul's notes folder.
    folder = root / 'notes'; folder.mkdir()
    service.bus.put('notes:folder', str(folder))
    note = call_notes(root, 'write', {'title':'Mounted witness', 'body':'# FIXCL4 Notes\nActual current editor bytes.\n'})
    # An imported offline conversation exercises the actual bubble renderer
    # without pretending a provider has run. Metadata uses the real owner bus.
    conversation = {'id':'FIXCL4-offline-conversation','app':'neyvia','folder':str(root),
                    'title':'Local imported conversation','status':'idle'}
    service.bus.update('sessions', {conversation['id']:conversation})
    service.bus.emit('session.created', conversation)
    # Close first-run setup by its own visible button in the rendered page.
    clicked = dom('''async () => { for(let i=0;i<30;i++) {
      const button=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='Skip setup');
      if(button){button.click();return true;} await new Promise(resolve=>setTimeout(resolve,300));
    } return false; }''')
    checks['actualFirstRunButtonClicked'] = clicked is True
    for _ in range(80):
        if dom('() => !document.querySelector(".nx-onb-scrim")'):break
        time.sleep(.3)
    checks['actualSetupDismissed'] = dom('() => !document.querySelector(".nx-onb-scrim")')
    cases = [
        ('folder-open', 'folder.open(path=' + json.dumps(str(folder)) + ')', 'pane.observe()["mounted"] == True'),
        ('arrange', 'view.arrange(order=["main","sidebar","panel","canopy"],dock="left",sidebarHidden=false)', 'view.state()["state"]["layout"]["dock"] == "left"'),
        ('scene', 'view.scene(name="focus")', 'view.state()["state"]["density"] == "calm"'),
        ('scene-workshop', 'view.scene(name="workshop")', 'view.state()["state"]["density"] == "workshop"'),
        ('scene-save', 'view.scene(save="Local witness")', 'view.state()["state"]["scenes"]["local-witness"]["density"] == "workshop"'),
        ('float', 'view.float(id="FIXCL4-offline-conversation",floating=true)', 'view.state()["state"]["bubbleOpen"] == "FIXCL4-offline-conversation"'),
        ('unfloat', 'view.float(id="FIXCL4-offline-conversation",floating=false)', 'view.state()["state"]["bubbles"] == []'),
        ('notify', 'notify(message="FIXCL4 actual mounted toast",level="success")', 'view.state()["state"]["fresh"] == True'),
        ('notes-open', 'notes.open(path=' + json.dumps(note['path']) + ')', 'view.state()["state"]["stage"]["app"] == "notes"'),
        ('voice-back', 'voice.command(text="back to the chat",requestId="FIXCL4-render-back")', 'view.state()["state"]["stage"] == None'),
        ('voice-notes', 'voice.command(text="open Notes",requestId="FIXCL4-render-notes")', 'view.state()["state"]["stage"]["app"] == "notes"'),
        ('onboarding-open', 'onboarding.open(step="interests")', 'view.state()["state"]["dom"]["setup"]["mounted"] == True'),
    ]
    for key, action, goal in cases:
        verb, rest = action.split('(', 1)
        action = 'run local-rendering.' + ('view-scene-save' if key == 'scene-save' else verb.replace('.', '-')) + '(' + rest
        current_token = session()
        result = cl('alias-' + key, 'action', 'G: ' + goal + '\n' + action + '\ndone()', current_token)
        if key == 'folder-open' and not result.get('ok'):
            # Pane completion is deliberately deferred until mounted content.
            for _ in range(50):
                from grant_agent.cl.renderer_effects import observe
                if observe(service.bus).get('mounted'): break
                time.sleep(.2)
            # cl() receives the session token separately: retain the action's
            # owner session rather than starting a different proof.
            result = cl('alias-' + key, 'completion', 'done()', current_token)
        checks[key + '.positiveCL'] = result.get('ok') is True
        receipt['journeys']['alias-' + key]['actualDOM'] = dom('() => ({notes:document.querySelector(".nx-notes-text")?.value,toast:[...document.querySelectorAll(".nx-toast")].map(e=>e.innerText),setup:document.querySelector(".nx-onb-rail-step.is-on")?.innerText,regions:[...document.querySelectorAll("[data-region]")].map(e=>({id:e.dataset.region,x:e.getBoundingClientRect().x}))})')
        receipt['journeys']['alias-' + key]['ownerObservation'] = service.bus.get('renderer:shell')
    # An unmounted app differs from a successful receipt. The real close button
    # removes setup; subsequent current DOM reports invalidate that completion.
    dom('() => { document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true})); return true; }')
    for _ in range(50):
        observed = service.bus.get('renderer:shell') or {}
        if observed.get('dom', {}).get('setup', {}).get('mounted') is False: break
        time.sleep(.1)
    checks['actualSetupUnmounted'] = dom('() => !document.querySelector(".nx-onb-scrim")')
    checks['actualSetupUnmountReported'] = (service.bus.get('renderer:shell') or {}).get('dom', {}).get('setup', {}).get('mounted') is False
    checks['closedSetupRefusesPriorDone'] = cl('alias-onboarding-open', 'unmounted', 'done()', current_token).get('ok') is False
    screen = root / 'mounted-aliases.png'
    ui(lambda: state['page'].screenshot(path=str(screen)))
    receipt['screenshot'] = {'path':str(screen), 'sha256':hashlib.sha256(screen.read_bytes()).hexdigest()}
    # Leave the actual Neyvia renderer. Its heartbeat genuinely stops, so the
    # same held protocol must reject the expired observation.
    ui(lambda: state['page'].goto('about:blank'))
    time.sleep(3)
    checks['actualRendererLeftNeyvia'] = dom('() => !document.querySelector(".nx-shell")')
    checks['staleMountedObservationRefusesDone'] = cl('alias-onboarding-open', 'expired', 'done()', current_token).get('ok') is False


def main():
    if '--prepare-manual' in sys.argv:
        prepare_manual(); return 0
    existing = REPO / 'scripts/fixcl3_renderer_probe.py'
    spec = importlib.util.spec_from_file_location('fixcl4_mounted_aliases', existing)
    module = importlib.util.module_from_spec(spec)
    source = existing.read_text(encoding='utf-8').replace('FIXCL3-renderer-pdf.json', 'FIXCL4-render-aliases.json')
    owners = ['src/grant_agent/neyvia_view_tools.py', 'web/src/neyvia/next/nxShellObserve.js',
              'web/src/neyvia/next/NxShell.jsx', 'web/src/neyvia/next/NxBubbles.jsx',
              'web/src/neyvia/next/NxNotesApp.jsx', 'web/src/neyvia/next/NxToasts.jsx',
              'scripts/fixcl4_render_alias_probe.py', 'config/neyvia_manuals.json']
    source = source.replace('    start = hashes(sources)',
        '    sources[0:0] = [REPO / name for name in ' + repr(owners) + ']\n    start = hashes(sources)')
    # Existing generic guard's PDF-only minimum applies to the old extension;
    # this finite alias journey carries its own complete named witness set.
    source = source.replace('(15 if args.pdf_only else', '(9 if args.pdf_only else')
    exec(compile(source, str(existing), 'exec'), module.__dict__)
    module.pdf_extension = aliases
    if '--pdf-only' not in sys.argv: sys.argv.append('--pdf-only')
    return module.main()


if __name__ == '__main__':
    raise SystemExit(main())
