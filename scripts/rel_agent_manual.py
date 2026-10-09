"""Author the release action directory from executable CL and registered contracts."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.cl.schema import SchemaGraph, schema_to_type, type_to_schema

def chapter(title):
    return dict(title=title, state={}, actions={}, checks={}, procedures={}, judge={}, pitfalls=[], frontier=[], guidance=[])

def load(identity):
    path = REPO / 'manuals/cl' / (identity + '.cl')
    return path, cl_to_manual(path.read_text(encoding='utf-8'))

def save(path, data):
    # JSON schema fallbacks must keep one canonical key order in both the
    # visible CL type and its executable record.
    graph = SchemaGraph()
    def type_value(value):
        canonical = type_to_schema(schema_to_type(value))
        return deepcopy(graph.declarations[graph.add(canonical)])
    data['schemas'] = {key: type_value(value) for key, value in data['schemas'].items()}
    def normalize(value):
        if isinstance(value, list): return [normalize(item) for item in value]
        if not isinstance(value, dict): return value
        return {key: type_value(item) if key in {'inputs','shape','returns'} else normalize(item) for key,item in value.items()}
    data = normalize(data)
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError('Lossless CL round trip failed: ' + str(path))
    path.write_text(source, encoding='utf-8')

def synchronize_schemas(data, registry):
    for section in data['chapters'].values():
        for action in section['actions'].values():
            spec = registry._specs.get(action['tool'])
            if spec:
                data['schemas'][action['schema']] = deepcopy(spec.input_schema)

def main():
    registry = NativeToolRegistry(Path('D:/NeyviaRuns/REL/manual-runtime'))
    existing = {}
    for path in sorted((REPO / 'manuals/cl').glob('*.cl')):
        source = path.read_text(encoding='utf-8')
        if '\n-- @manual ' not in source:
            continue  # CL-Skill sources use their owning skill parser.
        data = cl_to_manual(source)
        for section in data['chapters'].values():
            for action in section['actions'].values():
                existing.setdefault(action['tool'], (deepcopy(action), deepcopy(data['schemas'][action['schema']]), data['id']))
    path, core = load('neyvia-core')
    for key in list(core['chapters']):
        if key.startswith('actions-'): del core['chapters'][key]
    families = {}
    for name, spec in sorted(registry._specs.items()):
        if name in {'neyvia.cl', 'neyvia.cl.describe'}: continue
        family = name.removeprefix('neyvia.').split('.')[0]
        key = 'actions-' + family.replace('_', '-')
        section = core['chapters'].setdefault(key, chapter(family + ': exact agent actions'))
        schema_id = 'rel_' + name.replace('.', '_')
        prior = existing.get(name)
        schema = deepcopy(spec.input_schema)
        core['schemas'][schema_id] = schema
        action = deepcopy(prior[0]) if prior else {
            'tool': name, 'returns': {'type':'object'}, 'pre': 'Existing workspace scope, owner grants and provider/runtime readiness apply.',
            'effect': spec.description, 'reversible': False,
        }
        action['schema'] = schema_id
        section['actions'][name.removeprefix('neyvia.')] = action
        families.setdefault(family, []).append(name)
        owner = prior[2] if prior else None
        reference = ('Load ' + owner + ' for its observer checks and procedures. ') if owner and owner != 'neyvia-core' else ''
        section['guidance'].append(name + ': ' + reference + 'Authority=' + spec.mutability_class + ( '; approval required.' if spec.requires_approval else '.'))
    for section in core['chapters'].values():
        if ': exact agent actions' in section['title']:
            section['frontier'] = ['A listed action is a registered capability, not proof of runtime availability. CL refuses unmapped mutations; use its owning manual and fresh effects. MCP adapters retain their own exposed scope.']
    synchronize_schemas(core, registry)
    save(path, core)

    path, main_manual = load('neyvia')
    directory = chapter('Agent guide: chats, apps, windows and every exact action')
    directory['guidance'] = [
        'Begin with a specific goal. Read this guide, then load only the owning manual chapter. Use CL help at L1, run named procedures, keep refs/stamps host managed, and finish with a fresh observer G.',
        'Chats: session.new starts a CLI or native chat; session rename/pin/move/archive change the same user-visible state. Read agents and runtime-provider for provider turns, limits and recovery.',
        'Apps: app.open opens a real app or pane; read its app manual. Window ids come from view.state. view.place uses main (beside chat), side (left/right), full, bubble or close without remounting.',
        'Browser: browser opens, observes and acts on owned tabs. CAPTCHA/bot checks stop automation for the owner; never solve or bypass. Owner resumes after a fresh page check.',
        'Computer use and agent view: computer-use grants scoped native control on the agent desktop; agent-view observes, steers and replays recorded work. Owner consent remains required.',
        'LAYA: efficiency.laya_verify and cua.verify inspect evidence with the local verifier. Its answer is advisory; an unavailable model never becomes a made-up approval.',
        'Images: image-studio covers provider generation with explicit requests, local pixel edits, protected regions and exports. Inspect the live preview and generation receipt; provider availability is separate.',
        'App Factory: app-sdk creates/builds/inspects applications and frames; preview observes running apps. Native toolchains and permission checks apply.',
        '3D Studio and connectors: gamedev and game-dev expose editor sessions, actual bridge actions and asset validation. Installed Unity/Roblox/Godot/Blender connectors must report availability before use.',
        'Dictation: dictation covers status, local streaming transcription and named text processing. It uses the shared engine and reports fallback/availability honestly.',
        'Files, notes and PDF: files uses scoped paths, recoverable trash and undo; notes reads/writes the same notes folder; pdf opens/searches/annotates and extracts actual document text.',
        'Terminal and research: workspace covers bounded reads/writes and permitted terminal execution. research uses provider-backed cited answers and receipts. External actions never gain authority from this manual.',
        'Look and placement are reversible user choices. Keep chat drafts, source files and existing app instances while changing the view.',
    ]
    for family, names in sorted(families.items()):
        directory['guidance'].append('Exact contracts: neyvia-core/actions-' + family.replace('_','-') + ' — ' + ', '.join(names))
    directory['frontier'] = ['The exact contract directory includes every registered native action. Runtime, provider, desktop and MCP-scope readiness must still be observed; no listed action claims a completed journey.']
    main_manual['chapters']['agent-guide'] = directory
    panes = main_manual['chapters']['panes']
    spec = registry._specs['neyvia.view.place']
    main_manual['schemas']['rel_view_place'] = deepcopy(spec.input_schema)
    main_manual['schemas']['rel_view_state'] = {'type':'object','properties':{}}
    panes['actions']['place-window'] = {'tool':'neyvia.view.place','schema':'rel_view_place','pre':'Read view.state; id must be an open window in a fresh mounted shell. side only applies to side placement.',
        'effect':'Move or close the existing app/pane window through the placement model. CL verifies the delivered event and actual mounted placement before completion.', 'returns':{'type':'object'}, 'reversible':True}
    panes['actions']['window-state'] = {'tool':'neyvia.view.state','schema':'rel_view_state','pre':'The shell reports state after React commits; fresh=false means unavailable.',
        'effect':'Read current windows, ids, placements, mounted DOM geometry and delivered events.', 'returns':{'type':'object'},'reversible':True}
    panes['checks']['shell-mounted'] = {'tool':'neyvia.view.state','args':{},'expect':{'path':'state.dom.mounted','op':'eq','value':True}}
    panes['procedures']['place-window'] = {'goal':'Place an existing window and verify the actual rendered effect; unknown or stale windows refuse before dispatch.',
        'inputs':deepcopy(spec.input_schema), 'steps':[{'action':'place-window','args':{'id':{'$input':'id'},'placement':{'$input':'placement'},'side':{'$input':'side'}},'save':'placed','check':'shell-mounted'}]}
    # Optional inputs are omitted by the typed runner; no default side is silently imposed.
    panes['procedures']['place-window']['steps'][0]['args'].pop('side')
    panes['procedures']['place-window']['inputs']['properties'].pop('side')
    panes['procedures']['place-right-panel'] = {'goal':'Place an existing window in the right side pane and witness its mounted effect.',
        'inputs':{'type':'object','properties':{'id':{'type':'string'}},'required':['id']},
        'steps':[{'action':'place-window','args':{'id':{'$input':'id'},'placement':'side','side':'right'},'save':'placed','check':'shell-mounted'}]}
    synchronize_schemas(main_manual, registry)
    save(path, main_manual)
    report = {'actions':len(registry._specs)-2,'families':len(families),'registeredActions':sorted(name for name in registry._specs if name not in {'neyvia.cl','neyvia.cl.describe'})}
    Path('D:/NeyviaRuns/REL/action-directory.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':report['actions'],'families':len(families),'roundTrip':True}))

if __name__ == '__main__': main()
