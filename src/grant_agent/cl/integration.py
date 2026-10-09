"""Adapt the grounded manual archive and original gateway to CL 1.1."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
import json
import hashlib
from pathlib import Path
import re

from .host import HostContext, AUTO_FIELDS, unwrap
from .tokens import count_tokens
from .measured_context import INDEX_LINES, INDEX_O200K_TOKENS, MANUAL_DESCRIPTIONS_SHA256


def index_lines():
    from ..neyvia_manuals import compiled_index_lines, records
    cached = compiled_index_lines()
    if cached is not None:
        return cached
    lines = []
    for record in records():
        words = record['description'].replace('\n',' ').split()
        line = 'L ' + ('cua' if record['id']=='computer-use' else record['id']) + ' v2 -- '
        while words and count_tokens(line + ' '.join(words)) > 20: words.pop()
        lines.append(line + ' '.join(words))
    return lines


def _expression(value):
    if isinstance(value, dict) and len(value) == 1:
        if '$input' in value or '$path' in value: return str(next(iter(value.values())))
        if '$result' in value: return str(value['$result'])
    if isinstance(value, dict): return '{' + ', '.join(json.dumps(k)+': '+_expression(v) for k,v in value.items()) + '}'
    if isinstance(value, list): return '['+', '.join(_expression(v) for v in value)+']'
    return repr(value)


def _call(tool, arguments):
    return tool + '(' + ', '.join(key+'='+_expression(value) for key,value in arguments.items()) + ')'


def _goal(check):
    observer = _call(check['tool'].removeprefix('neyvia.'),{key:value for key,value in check['args'].items() if key not in AUTO_FIELDS})
    rule = check['expect']
    path = rule.get('path','')
    if isinstance(path,str): path = [part for part in path.split('.') if part]
    for part in path:
        observer += '['+_expression(part)+']'
    if rule['op'] == 'exists': return observer + ' != None'
    if rule['op'] == 'schema': return 'matches('+observer+', '+_expression(rule.get('schema', rule.get('value',{})))+')'
    value = _expression(rule.get('value'))
    if rule['op'] == 'eq': return observer+' == '+value
    if rule['op'] in {'contains','includes'}: return value+' in '+observer
    raise ValueError('Unknown grounded goal predicate: '+str(rule['op']))


def make_host(protocol):
    from ..neyvia_manuals import records, get_manual
    gateway = protocol.gateway
    tools = []
    from ..proofs_d_native import check_catalog
    for spec in gateway.native._specs.values():
        if spec.name in {'neyvia.cl','neyvia.cl.describe'}: continue
        row = {field.name:getattr(spec,field.name) for field in fields(spec)}
        row['inputSchema'] = spec.input_schema
        row.pop('input_schema', None)
        check_catalog(row, spec, True)
        name = spec.name.removeprefix('neyvia.')
        # Exact argument-dependent classification runs when the tool is read or
        # called. Building an unrelated catalog must not import every observer.
        tools.append({**row,'name':name,'annotations':{'readOnlyHint':spec.mutability_class == 'read'}})
    procedures, pitfalls = {}, {}
    for record in records():
        if record['id'] not in protocol.manual_documents:
            continue
        model_layer = 'cua' if record['id']=='computer-use' else record['id']
        data = protocol.manual_documents[record['id']]
        for chapter_name,chapter in data['chapters'].items():
            for row in chapter['pitfalls']:
                line = 'X '+row['failure'].replace('\n',' ')+' -> '+row['recovery'].replace('\n',' ')
                for key in AUTO_FIELDS:
                    line = re.sub(r'\b'+re.escape(key)+r'\b', 'host-managed value', line)
                pitfalls.setdefault(model_layer,[]).append(line)
            for name,proc in chapter['procedures'].items():
                inputs = deepcopy(proc['inputs'])
                for key in list(inputs.get('properties',{})):
                    if key in AUTO_FIELDS:
                        inputs['properties'].pop(key)
                        inputs['required'] = [x for x in inputs.get('required',[]) if x != key]
                choices = {}
                choice_aliases = {key:key.replace('-', '_') for key in chapter['judge']}
                steps, goals = [], []
                for step in proc['steps']:
                    if 'judge' in step:
                        row = chapter['judge'][step['judge']]
                        key = choice_aliases[step['judge']]
                        choices[key] = {'options':row['options'],'question':row['question']}
                        inputs['properties'][key] = {'type':'string','enum':row['options']}
                        steps.append({'judge':key})
                    else:
                        action = chapter['actions'][step['action']]
                        tool = action['tool'].removeprefix('neyvia.')
                        # Step values stay structured: the normal resolver handles
                        # references to saved results without model-visible stamps.
                        args = {k:v for k,v in step['args'].items() if k not in AUTO_FIELDS}
                        compiled = {'tool':tool,'args':args,'procedure':model_layer+'.'+name,**{k:v for k,v in step.items() if k in {'save','when'}}}
                        if compiled.get('when'):
                            compiled['when'] = {**compiled['when'], 'judge':choice_aliases[compiled['when']['judge']]}
                        steps.append(compiled)
                        if step.get('check'):
                            check = chapter['checks'][step['check']]
                            compiled['check_factory'] = (lambda args, environment, check=check, step=step:
                                protocol.bound_check(step, check, {**environment, **args}))
                            goal = _goal(check)
                            if compiled.get('when'):
                                gate = compiled['when']
                                goal = '('+gate['judge']+' != '+repr(gate['option'])+' or ('+goal+'))'
                            goals.append(goal)
                # An unmapped procedure is refused; no existence-only invented G.
                procedures[model_layer+'.'+name] = {'inputs':inputs,'steps':steps,'choices':choices,
                    'goal':' and '.join('('+g+')' for g in goals) if goals else None,
                    'layers':{model_layer, *[step['tool'].split('.')[0] for step in steps if 'tool' in step]},
                    'summary':proc['goal'],'root':gateway.root}
                from .effects import supported
                mutations = [step for step in steps if 'tool' in step and protocol._mutating(protocol.resolve_name(step['tool']), step['args'])]
                procedures[model_layer+'.'+name]['effect_goal'] = bool(mutations) and all(
                    supported(protocol.resolve_name(step['tool'])) for step in mutations)
    dispatched = {}
    def dispatch(name,args,action_id=''):
        exact = protocol.resolve_name(name)
        if protocol.scope is not None and exact not in protocol.scope:
            raise ValueError('Action is outside this adapter\'s existing tool scope: '+exact)
        if protocol._mutating(exact,args) and (not gateway.allow_mutations or gateway.allowed_mutation_tools is not None and exact not in gateway.allowed_mutation_tools):
            return {'ok':False,'status':'ask','error':'Existing caller mutation grant required; no action ran'}
        if exact == 'neyvia.perception.observe' and args.get('layer') == 'app':
            observer = args.get('source',{}).get('tool')
            if observer and protocol.scope is not None and observer not in protocol.scope:
                raise ValueError('App observer is outside this adapter scope')
        result = gateway.call_native(exact,args,action_id=action_id)
        if exact == 'terminal.exec': dispatched[exact] = deepcopy(result)
        return protocol.action_output(exact, result)
    def context_session(args, latest):
        if not gateway.work_scope:
            raise ValueError('Context operations require the current scoped session')
        return gateway.work_scope

    def host_session(args, latest):
        # Managed host sessions are a different identity from the chat session.
        # Fill it only from a real current host observation, never a guessed ID.
        if isinstance(latest, dict) and isinstance(latest.get('session'), dict):
            return latest['session']['sessionId']
        sessions = latest.get('sessions', []) if isinstance(latest, dict) else []
        if len(sessions) != 1 or not sessions[0].get('sessionId'):
            raise ValueError('Observe one exact managed host session before controlling it')
        return sessions[0]['sessionId']

    def contracts(name):
        exact = protocol.resolve_name(name)
        schema = gateway.native._specs[exact].input_schema
        authored = protocol.contracts.get(exact,{})
        action = authored.get('action',{})
        from .effects import supported
        result = {'checks_factory':lambda args:protocol._checks(exact,args), 'verified':supported(exact),
                'default_goal':lambda args:protocol.default_goal(exact,args),
                'mutating_factory':lambda args:protocol._mutating(exact,args),
                'manual_layers':[binding['manual'] for binding in protocol.manual_actions.get(exact, [])],
                'manual_factory':lambda args, procedure=None, identity='':protocol.manual_use(exact,args,procedure=procedure,identity=identity),
                'manual_record':protocol.record_manual_use,
                'auto':{'sessionId':lambda args, latest:gateway.work_scope or 'unscoped'} if exact in {'neyvia.plan.update', 'skill.live.iterate'} else
                       {'sessionId': host_session} if exact in {'host.status', 'host.stop', 'host.inspect_preview', 'neyvia.gamedev.action'} else
                       {'sessionId': context_session} if exact.startswith('context.') else {},
                'snapshot':lambda args:protocol._snapshot(exact,args),
                'after_snapshot':lambda args, before:protocol._snapshot(exact,args,previous=before,after=True),
                'window_selection':name.startswith('cua.') and 'window_id' in schema.get('properties',{}),
                'literal_targets':exact == 'neyvia.pane.show',
                'impact':{'writes':action.get('effect',name),'undo':'files.undo()' if name in {'files.move','files.mkdir','files.trash'} else 'none','ask':'existing-gateway'},
                'refs':[key for key in ('target','window') if key in schema.get('properties',{})
                        and not (exact == 'neyvia.pane.show' and key == 'target')]}
        if exact == 'terminal.exec':
            from .terminal_receipts import observe, verified
            result['checks_factory'] = lambda args: [*protocol._checks(exact,args), {
                'name':'native-command-receipt','observer':True,
                'check':lambda args,value,before:verified(gateway,dispatched.get(exact),args,value)}]
            # The terminal effect observer needs the journal's request hash
            # and prior record set. Keep that snapshot; this check rereads the
            # dispatched native receipt independently.
            result['verified'] = True
        return result
    from .protocol import MANUAL_ALIASES
    host = HostContext(tools,dispatch,contracts=contracts,procedures=procedures,root=gateway.root,index=index_lines(),procedure_aliases=MANUAL_ALIASES,
                       task_text=getattr(gateway, 'cl_task_text', None), readonly=lambda name, args: not protocol._mutating(protocol.resolve_name(name), args))
    host.task_id = getattr(gateway, 'cl_task_id', None)
    host.memory_context = getattr(gateway, 'memory_context', None)
    host.lesson_root = Path(getattr(gateway, 'task_goal_root', gateway.root))
    from ..ui_command_bus import bus_for
    from ..neyvia_awareness import board_list, overlaps
    from ..neyvia_impact import impact_enrichment, REPO
    bus = bus_for(gateway.root)
    cursors = {}
    def resources(name,args):
        paths = [str(args[key]) for key in ('path','from','to') if args.get(key)]
        if name.startswith('notes.'):
            folder = bus.get('notes:folder')
            if folder:
                paths.extend(str(Path(folder)/path) for path in list(paths) if not Path(path).is_absolute())
        return list(dict.fromkeys(paths))
    def awareness(name,args,*,after=False,result=None,paths=None):
        paths = resources(name,args)
        if not after:
            with bus.connect() as db:
                cursors[name] = db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
                approvals = [json.loads(r['value']) for r in db.execute("SELECT value FROM state WHERE key LIKE 'approval:%'").fetchall()]
            rows = []
            for claim in board_list(gateway.root,{'files':paths}).get('claims',[]) if paths else []:
                rows.append({'kind':'K','value':{'claim':host._put(claim,'c'), 'agent':claim['agent'],
                                                  'intent':claim['intent'],'files':claim['files']}})
            for session in bus.get('sessions',{}).values():
                folder = session.get('folder') or session.get('project')
                if folder and any(overlaps(str(folder),path) for path in paths):
                    rows.append({'kind':'K','value':{'session':host._put(session,'h'),
                        'title':session.get('title','connected session'),'resource':str(folder)}})
            for approval in approvals:
                details = approval.get('details') or {}
                subjects = [str(details[k]) for k in ('path','from','to','folder') if isinstance(details,dict) and details.get(k)]
                if any(overlaps(a,b) for a in subjects for b in paths):
                    rows.append({'kind':'K','value':{'approval':approval.get('description','pending approval'),'resources':subjects}})
            # Read the existing T16 receipt files without constructing its native
            # service (which could start a driver or monitor).
            cua = gateway.root / '.neyvia' / 'cua'
            if name.startswith('cua.') and cua.is_dir():
                for filename in ('sessions.json','log.json'):
                    file = cua / filename
                    if file.exists():
                        data = json.loads(file.read_text(encoding='utf-8'))
                        rows.append({'kind':'K','value':{'sharedLog':host._put(data,'h'),'source':'T16 '+filename}})
            return rows
        success = not (isinstance(result,dict) and result.get('ok') is False)
        events = bus.since(cursors.get(name,0))
        realized = resources(name,{**args, **({'path':result['path']} if isinstance(result,dict) and result.get('path') else {})}) if success else []
        if success and name == 'notes.pin':
            folder = bus.get('notes:folder')
            realized = [str(Path(folder)/'.neyvia-notes.json')] if folder else []
        mapped = []
        for path in realized:
            candidate = Path(path)
            candidate = candidate if candidate.is_absolute() else gateway.root/candidate
            try: mapped.append(candidate.resolve().relative_to(REPO).as_posix())
            except ValueError: pass
        # App data normally lives outside source control. Include the action's
        # real owning manual view to obtain current UI/handler/test dependencies
        # from the merged impact map without pretending its source was written.
        owner = protocol.contracts.get(protocol.resolve_name(name), {}).get('manual')
        manual_path = 'docs/manuals/'+owner+'.md' if owner else None
        if manual_path and (REPO/manual_path).is_file(): mapped.append(manual_path)
        mapped = list(dict.fromkeys(mapped))
        enrichment = impact_enrichment(mapped)
        return [{'kind':'I','value':{'wrote':realized,'touched':[e['action'] for e in events],
                                     'emitted':[e['action'] for e in events],
                                     'undo':contracts(name)['impact']['undo'],
                                     'impact':enrichment.get('files', []),
                                     'enrichment':{key:value for key,value in enrichment.items() if key != 'files'}}}]
    host.awareness = awareness
    def manual_view(layer,level):
        lines = protocol.host._signatures(layer).splitlines()
        owners = {('computer-use' if layer=='cua' else layer)} if ('computer-use' if layer=='cua' else layer) in protocol.manual_documents else set()
        owners.update(binding['manual'] for exact,bindings in protocol.manual_actions.items()
                      if host.layer(exact)==layer for binding in bindings)
        relevant = [line for owner in sorted(owners) for line in pitfalls.get('cua' if owner=='computer-use' else owner, [])]
        lines += relevant[:3] if level == 1 else relevant
        if level == 2:
            for owner in sorted(owners):
                for chapter in protocol.manual_documents[owner]['chapters'].values():
                    lines.extend('F '+line for line in chapter['frontier'])
                    lines.extend('M '+owner+' '+json.dumps(line) for line in chapter['guidance'])
        return '\n'.join(lines)
    host.manual_view = manual_view
    return host
