"""CL 1.1 host context over existing dispatch, permissions and observer contracts.

The model view is deliberately not the archival contract. Only this host owns
stamps, ref bindings, action identities, checks, impact and completion status.
"""
from __future__ import annotations

from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import re
import os
import threading
import time
import uuid

from jsonschema import Draft202012Validator
from .goals import evaluate_goal
from .parser import Action, BareWord, Handle, logical_lines, parse_action
from .renderer import IDENTIFIERS, StaleHandleError

REPO = Path(__file__).resolve().parents[3]
AUTO_FIELDS = {'expectedModified', 'revision', 'browserId', 'window_id', 'windowId',
               'pid', 'sessionId', 'element_token', 'snapshot_id', 'capture_id'}
REF = re.compile(r'[a-zA-Z]+[0-9]+$')


def model_value(value):
    """Hide transport fields; redact IDs only in observed accessibility trees.

    Ordinary note bodies, quoted control values, and business identifiers are
    data. Goal comparisons can repeat a tree outside its observation dictionary,
    so identify native tree strings before projecting the complete response.
    """
    native_text = {}
    def collect(item):
        if isinstance(item, dict):
            native = ('tree_markdown' in item or isinstance(item.get('elements'), list) and
                      any(isinstance(row, dict) and 'element_token' in row for row in item['elements']))
            if native:
                for key in ('text', 'tree_markdown'):
                    tree = item.get(key)
                    if isinstance(tree, str):
                        native_text[tree] = re.sub(r'("(?:[^"\\]|\\.)*")|(\s+id=\d+\b)',
                                                  lambda match: match.group(1) or '', tree)
            for child in item.values(): collect(child)
        elif isinstance(item, list):
            for child in item: collect(child)
    collect(value)
    def project(item):
        if isinstance(item, dict):
            return {key:project(child) for key,child in item.items()
                    if key not in IDENTIFIERS | AUTO_FIELDS | {'session'}}
        if isinstance(item, list): return [project(child) for child in item]
        if isinstance(item, str): return native_text.get(item, item)
        return item
    return project(value)


def unwrap(value):
    while isinstance(value, dict) and (isinstance(value.get('toolResult'), dict) or
                                      isinstance(value.get('result'), dict) and 'tool' in value):
        if value.get('ok') is False:
            return {'ok':False, 'status':value.get('status','fail'),
                    'error':value.get('error') or value.get('failure') or 'Native tool failed',
                    'failure':deepcopy(value.get('failure'))}
        value = value['toolResult'] if isinstance(value.get('toolResult'), dict) else value['result']
    if isinstance(value,dict) and isinstance(value.get('structuredContent'),dict):
        if value.get('isError'): return {**value['structuredContent'],'ok':False,'status':'fail'}
        value = value['structuredContent']
    return value


class HostContext:
    def __init__(self, tools, dispatch, *, contracts=None, procedures=None, goals=None,
                 root=None, index=None, manual_view=None, awareness=None, types=None, procedure_aliases=None, readonly=None,
                 observation_mode='full', task_text=None, lesson_provider=None, memory_context=None):
        if observation_mode not in {'full', 'diff'}:
            raise ValueError('observation_mode must be full or diff')
        self.observation_mode = observation_mode
        self.tools = {row['name']: deepcopy(row) for row in tools}
        self.dispatch, self.contracts = dispatch, contracts or (lambda name: {})
        self.readonly_classifier = readonly
        self.procedures = procedures or {}
        self.procedure_aliases = procedure_aliases or {}
        self.root = Path(root).resolve() if root else None
        self.manual_view, self.awareness, self.types = manual_view, awareness, types or {}
        self.index = index or ['L ' + layer + ' v2 -- ' + layer for layer in sorted({self.layer(n) for n in self.tools})]
        if not any(line.startswith('L taste ') for line in self.index):
            self.index = [*self.index, 'L taste v1 -- render, compare, repair; host gates done']
        self.loaded, self.refs, self.latest, self.reads = set(), {}, {}, {}
        self.counts, self.generations, self.identities, self.paused = {}, {}, {}, {}
        self.completed_procedures = {}
        self.goals, self.done_status = [], None
        self.default_goals = {}
        self.task_goals = []
        self.task_active = False
        self.completion_generation = 0
        self.done_generation = None
        self.goal_states = {}
        self.effect_bindings = {}
        self.pending_actions = {}
        self.goal_observers = {}
        self.subject_generations = {}
        self.observation_subjects = {}
        self.observation_states = {}
        self.observation_snapshots = {}
        self.observation_baselines = {}
        self.metrics = {'actions': 0, 'procedures': 0, 'checks': 0, 'I': 0, 'K': 0, 'Q': 0, 'goalRefusals': 0}
        # Changed deliverables are checked by every configured finishing skill before done().
        # Existing inputs belong to the reader, even when created immediately
        # before this task. Do not backdate the output gate into their lifetime.
        self.started = time.time()
        self.language_refusals = {}
        from ..taste_gate import TasteGate
        self.taste = TasteGate(self.root, self.started)
        self.task_text, self.lesson_provider = task_text, lesson_provider
        self.laya_route_verdict = None
        self.laya_route_learned = False
        self.memory_context = memory_context
        self.memory_packet = None
        self.memory_tokens = 0
        self.skill_receipts = {}
        self.output_paths, self.lesson_fires = [], set()
        self.lock = threading.RLock()
        from .codecs import SemanticCodecs
        self.codecs = SemanticCodecs(self)
        for goal in ([goals] if isinstance(goals, (str, dict)) else goals or []):
            self.goal(goal)

    @staticmethod
    def layer(name):
        return name.removeprefix('neyvia.').split('.')[0]

    def cold_start(self):
        from .tokens import count_tokens
        primer = (REPO / 'docs/standard/1.1/primer.md').read_text(encoding='utf-8').strip()
        if count_tokens(primer) > 300:
            raise ValueError('R16: core primer exceeds 300 o200k tokens')
        if any(count_tokens(line) > 20 or not line.startswith('L ') for line in self.index):
            raise ValueError('R16: each L0 line must be at most 20 tokens')
        return primer + '\n' + '\n'.join(self.index) + '\n' + self._lesson_context() + self._routed_layer_text() + self.refresh_memory().get('section', '')

    def refresh_memory(self, layer='', args=None):
        """One current projection. Source facts never become executable CL lines."""
        if self.memory_context is None or not self.task_text:
            return {}
        from ..memory_recall import recall
        from ..cue_memory import CueMemoryStore
        situation = {'intent': str(self.task_text), 'layer': layer}
        paths = []
        for key in ('path', 'from', 'to'):
            if isinstance((args or {}).get(key), str):
                try:
                    path = Path(args[key])
                    paths.append((path if path.is_absolute() else self.memory_context.project_path / path).resolve()
                                 .relative_to(self.memory_context.project_path).as_posix())
                except ValueError:
                    pass
        if paths:
            situation['files'] = paths
        packet = recall(self.memory_context, situation, destination=self.memory_context.channel)
        if self.memory_packet and packet['generation'] != self.memory_packet['generation']:
            # Retire all old handles, including nested memory projections. The
            # original provider transcript cannot be unlearned by a store edit.
            self.refs.clear()
            self.reads.clear()
            self.latest.clear()
            self.completed_procedures.clear()
            self.identities.clear()
            self.effect_bindings = {key: value for key, value in self.effect_bindings.items() if not key.startswith('memory:')}
        self.memory_packet = packet
        self.memory_tokens += packet['tokens']
        return packet

    def route(self, task_text=None):
        """LAYA's routing verdict for the task: {"route": "laya", "layer": name} when it confirms one layer, else None.
        Silent (no receipt, no call) when LAYA is not running, the task has no text, or routing is switched off."""
        text = task_text or self.task_text
        if not text or self.root is None or os.environ.get('NEYVIA_CL_LAYA_ROUTE', '1') == '0':
            return None
        try:
            from ..laya_hooks import laya_ready, route_layer
            if not laya_ready():
                return None
            verdict = route_layer(self.root, str(text))
            self.laya_route_verdict = verdict
        except Exception:
            return None
        known = {self.layer(n) for n in self.tools} | {'cua'}
        return verdict if verdict.get('route') == 'laya' and verdict.get('layer') in known else None

    def _routed_layer_text(self):
        """Pre-load the routed layer's help so the model skips the lookup turn; empty when LAYA does not confirm."""
        verdict = self.route()
        if not verdict:
            return ''
        layer = verdict['layer']
        try:
            help_text = self.help(layer)
            self.routed_by_laya = layer
            return '-- routed to layer ' + layer + ' by LAYA (verified learned route)\n' + help_text
        except Exception:
            return ''

    def _lesson_context(self, layer=None, level=1):
        from ..cl_deliverables import lesson_service
        service = lesson_service(getattr(self, 'lesson_root', self.root))
        if service is None:
            return ''
        manuals = ['skill:no-slop', 'skill:deliverables'] if layer is None else ['skill:' + ('no-slop' if layer == 'language' else layer)]
        rows = [row for manual in manuals for row in service.active_lines(manual=manual, task_id=getattr(self, 'task_id', None))]
        lines, fired = [], []
        for row in rows:
            kind, line = row.get('kind'), row.get('line', '')
            if kind == 'guidance':
                lines.append('F lesson.' + row['id'] + ' ' + json.dumps(line, ensure_ascii=False))
                fired.append(row['id'])
            elif layer and level == 2 and kind in {'judge', 'pitfall'}:
                lines.append(line)
        self.lesson_fires.update(fired)
        return '\n'.join(lines) + ('\n' if lines else '')

    def readonly(self, name, args=None):
        tool = self.tools.get(name)
        if tool and self.readonly_classifier is not None:
            return self.readonly_classifier(name, args or {})
        contract = self._contract(name) if tool and args is not None else {}
        if contract.get('mutating_factory'):
            return not contract['mutating_factory'](args)
        return bool(tool and tool.get('effect') not in {'~', '!'} and
                    tool.get('annotations', {}).get('readOnlyHint') is True)

    def _schema(self, name):
        tool = self.tools[name]
        return tool.get('inputSchema', tool.get('input_schema'))

    def _contract(self, name):
        return self.contracts(name) if callable(self.contracts) else self.contracts.get(name, {})

    def _auto(self, name):
        contract = self._contract(name)
        return {**{key: None for key in self._schema(name).get('properties', {}) if key in AUTO_FIELDS},
                **contract.get('auto', {})}

    def help(self, layer, level=1):
        if level not in {1, 2}: raise ValueError('help level is 1 or 2')
        if layer == 'taste':
            self.loaded.add(layer)
            return ('A taste.record_concept(record) -- before the first page write\n'
                    'A taste.record_research(rows) -- primary-source candidates before draft\n'
                    'A taste.record_research_addendum(path, folder) -- bind actual web research to a research difference\n'
                    'A taste.record_repair(path, edits) -- attest mapped edits after workspace.patch\n'
                    'A taste.admit_lesson(id, evidence) -- C9 source and frozen-suite gate; task-local manual overlay\n'
                    'A taste.review(path) -- Neyvia Obscura render + Luna image difference/critique\n'
                    'C done: draft review, two targeted repair reviews, controls, brief and anchor pass\n'
                    'X unchanged output -> repair reported differences before another review\n')
        if self.manual_view:
            text = self.manual_view(layer, level)
            # Awareness is never pre-authored in model context.
            text = '\n'.join(line for line in text.splitlines() if not line.startswith(('I ', 'K ', 'Q ', '-- @')))
        else:
            text = self._signatures(layer)
        self.loaded.add(layer)
        return text.rstrip() + '\n' + self._lesson_context(layer, level)

    def _signatures(self, layer):
        def field_type(field):
            names = {'integer':'int', 'number':'num', 'boolean':'bool', 'array':'list', 'object':'dict', 'null':'None', 'string':'str'}
            kind = field.get('type')
            return '|'.join(names.get(item, 'str') for item in kind) if isinstance(kind, list) else names.get(kind, 'str')
        lines = []
        for name, proc in self.procedures.items():
            if layer not in proc.get('layers', {self.layer(name)}): continue
            schema = proc['inputs']
            args = []
            for key, field in schema.get('properties', {}).items():
                arg = key + ('' if key in schema.get('required', []) else '?')
                if field.get('enum'): arg += ': ' + '|'.join(json.dumps(x) for x in field['enum'])
                elif field.get('type') != 'string': arg += ': ' + field_type(field)
                args.append(arg)
            if not proc.get('goal') and not proc.get('effect_goal'):
                lines.append('F ' + name + ' lacks a grounded procedure G; unavailable')
                continue
            lines.append('P ' + name + '(' + ', '.join(args) + ') G: ' + str(proc['goal'] or 'fresh action effect predicates'))
            for choice, row in proc.get('choices', {}).items():
                lines.append('J ' + choice + ' ' + '|'.join(json.dumps(o) for o in row['options']) + ': ' + json.dumps(row['question']))
        for name in self.tools:
            contract, schema = self._contract(name), self._schema(name)
            if self.layer(name) != layer and layer not in contract.get('manual_layers', []): continue
            alias = {real: model for model, real in contract.get('aliases', {}).items()}
            args = ['window?: ref'] if contract.get('window_selection') else []
            for key, field in schema.get('properties', {}).items():
                if key in self._auto(name): continue
                param = alias.get(key, 'source' if key == 'from' else key)
                param += '' if key in schema.get('required', []) else '?'
                if key in contract.get('refs', []) or key == 'target' and not contract.get('literal_targets'): param += ': ref'
                elif field.get('enum'): param += ': ' + '|'.join(json.dumps(x) for x in field['enum'])
                elif field.get('type') != 'string': param += ': ' + field_type(field)
                args.append(param)
            lines.append('A ' + name + '(' + ', '.join(args) + ')' + ('' if self.readonly(name) else ' !'))
            if not self.readonly(name) and contract.get('verified') is False:
                lines.append('F ' + name + ' has no grounded observer; host refuses the effect')
        return '\n'.join(lines)

    def _put(self, value, kind='h', layer=None, raw=None, subject=None):
        self.counts[kind] = self.counts.get(kind, 0) + 1
        alias = kind + str(self.counts[kind])
        self.refs[alias] = {'value': deepcopy(value), 'raw': deepcopy(raw if raw is not None else value),
                            'layer': layer, 'generation': self.generations.get(layer, 0),
                            'subject': subject,
                            'subjectGeneration': self.subject_generations.get(subject, 0)}
        return alias

    def _ref_current(self, alias, row):
        if not alias.startswith('e'): return True
        if row.get('subject') is not None:
            return row.get('subjectGeneration') == self.subject_generations.get(row['subject'], 0)
        return row['generation'] == self.generations.get(row['layer'], 0)

    def resolve(self, alias):
        row = self.refs.get(str(alias))
        if row is None: raise ValueError('Unknown live ref; available: ' + ', '.join(self.live_refs()))
        if not self._ref_current(str(alias), row):
            current = []
            for live in self.live_refs():
                binding = self.refs[live]
                if live.startswith('e') and binding['layer'] == row['layer'] and binding.get('subject') == row.get('subject'):
                    element = binding['value']
                    label = element.get('label', element.get('name', '')) if isinstance(element, dict) else ''
                    current.append(live + ' ' + json.dumps(str(label)[:60], ensure_ascii=False))
            recovery = ('; current ' + str(row['layer']) + ' refs: ' + ', '.join(current[:8]) +
                        ('; more refs in the latest observation' if len(current) > 8 else '') +
                        '; use a current ref') if current else '; observe again'
            raise StaleHandleError('Element ref is stale' + recovery)
        return deepcopy(row['raw'])

    def live_refs(self):
        return [alias for alias, row in self.refs.items() if self._ref_current(alias, row)]

    def _subject(self, layer, observer=None, args=None):
        """Observer identity and resolved inputs distinguish windows, notes and tabs."""
        stable = {key: value for key, value in (args or {}).items()
                  if key not in {'snapshot_id', 'capture_id', 'revision', 'expectedModified'}}
        return json.dumps([layer, observer or layer, stable], sort_keys=True,
                          ensure_ascii=False, separators=(',', ':'), default=str)

    def acknowledge_observations(self, state_refs=None, *, replace=False):
        """Advance delta baselines after delivery, never merely after observing.

        Pass the stateRef handles actually delivered to a model. With no argument
        acknowledge the current snapshots, suitable after context_snapshot().
        An older acknowledged snapshot cannot replace a newer baseline.
        replace=True means this list is the complete current model view; drop
        baselines compacted out of that view rather than issuing hidden deltas.
        """
        with self.lock:
            aliases = state_refs if state_refs is not None else [row['stateRef'] for row in self.observation_states.values()]
            if isinstance(aliases, str): aliases = [aliases]
            aliases = list(aliases)
            if any(alias not in self.observation_snapshots for alias in aliases):
                raise ValueError('Unknown observation stateRef in acknowledgement')
            if replace: self.observation_baselines = {}
            acknowledged = []
            for alias in aliases:
                row = self.observation_snapshots.get(alias)
                if row is None: raise ValueError('Unknown observation stateRef: ' + str(alias))
                old = self.observation_baselines.get(row['subject'])
                if old is None or row['sequence'] >= old['sequence']:
                    self.observation_baselines[row['subject']] = deepcopy(row)
                    acknowledged.append(alias)
            return acknowledged

    def context_snapshot(self, *, compact=False):
        """Current state and actionable refs, without replaying archival receipts.

        Compact snapshots retain each full state's project handle. Native refs
        remain explicit; the context builder refuses a budget too small for them.
        """
        with self.lock:
            states = []
            for row in self.observation_states.values():
                item = {key: deepcopy(row[key]) for key in ('observer', 'inputs', 'stateRef', 'sequence', 'subjectRef')}
                item['layer'] = row['layer']
                item['refs'] = {ref: row['refPaths'][ref] for ref in row['liveRefs'] if ref in self.refs and self._ref_current(ref, self.refs[ref])}
                if not compact: item['state'] = deepcopy(row['visible'])
                else: item['read'] = 'project(' + row['stateRef'] + ')'
                states.append(item)
            live = {alias: {'layer': row['layer'], 'subjectRef': self.observation_subjects.get(row.get('subject')),
                            'role': row['value'].get('role', 'element'),
                            'label': row['value'].get('label', row['value'].get('name', ''))}
                    for alias, row in self.refs.items() if alias.startswith('e') and self._ref_current(alias, row)}
            windows = {alias: model_value(row['value']) for alias, row in self.refs.items() if alias.startswith('w')}
            return {'states': states, 'liveRefs': {**windows, **live},
                    'goals': list(dict.fromkeys([*self.task_goals, *self.goals])),
                    'doneStatus': self.done_status}

    def _goal_state_text(self):
        return ''.join(self._state(self.layer(name), value, observer=name, args=args)
                       for subject, value in self.goal_states.items()
                       for name, args in [self.goal_observers[subject]])

    def _model_arguments(self, args):
        visible = model_value(args or {})
        for key in ('target', 'window'):
            if key not in visible: continue
            alias = next((ref for ref, row in reversed(list(self.refs.items()))
                          if ref.startswith(('e', 'w')) and row['raw'] == args[key]), None)
            visible[key] = alias or 'host-bound target'
        return visible

    def _remember(self, name, args, value):
        layer = self.layer(name)
        self.latest[layer] = deepcopy(value)
        if isinstance(value, dict) and type(value.get('window_id')) is int:
            # The observed window outlives this observation: an action or a
            # verify result replaces latest but the agent still means that window.
            self.latest[layer + ':window'] = {'window_id': value['window_id']}
        self.reads[(name, json.dumps(args, sort_keys=True))] = deepcopy(value)

    def _observer(self, name, positional, kwargs):
        if not self.readonly(name): raise ValueError('Not a read-only observer: ' + name)
        contract = self._contract(name)
        def ref_argument(value):
            if isinstance(value, (dict, str, int)):
                # Native element tokens can be reused by later observations.
                # Bind their current published ref, never an older stale alias.
                for alias in reversed(self.live_refs()):
                    row = self.refs[alias]
                    if value == row['raw']:
                        self.resolve(alias)  # Retain the original stale-ref check.
                        return BareWord(alias)
            return value
        kwargs = {key: ref_argument(value) if key in contract.get('refs', []) or key == 'target' and not contract.get('literal_targets') else value
                  for key, value in kwargs.items()}
        positional = list(positional)
        if contract.get('window_selection') and positional:
            positional[0] = ref_argument(positional[0])
        action = Action(name, kwargs, positional)
        args, _ = self._arguments(action)
        if not self.readonly(name, args):
            raise ValueError('Observer arguments would mutate: ' + name)
        output = self.dispatch(name, args, action_id='')
        if isinstance(output, dict) and output.get('ok') is False:
            raise ValueError(str(output.get('error') or output.get('failure') or output.get('status') or output))
        value = unwrap(output)
        if isinstance(value, dict) and value.get('ok') is False: raise ValueError(str(value.get('error', value)))
        self._remember(name, args, value)
        subject = self._subject(self.layer(name), name, args)
        self.goal_states[subject] = deepcopy(value)
        self.goal_observers[subject] = (name, deepcopy(args))
        return value

    def evaluate(self, expression, environment=None):
        if isinstance(expression, dict): expression = expression['expression']
        bindings = {alias: self.resolve(alias) for alias in self.live_refs()}
        return evaluate_goal(expression, self._observer, self.readonly, {**bindings, **(environment or {})}, self.types)

    def completion_bindings(self):
        names = set()
        for expression in [*self.task_goals, *self.goals]:
            names.update(node.id for node in ast.walk(ast.parse(expression, mode='eval')) if isinstance(node, ast.Name))
        return {'refs': {alias: deepcopy(row) for alias, row in self.refs.items() if alias in names and row.get('layer') != 'memory'},
                'generations': deepcopy(self.generations), 'latest': deepcopy(self.latest),
                'counts': deepcopy(self.counts), 'effects':deepcopy({key: value for key, value in self.effect_bindings.items() if not key.startswith('memory:')}),
                'pendingActions':deepcopy(self.pending_actions), 'subject_generations':deepcopy(self.subject_generations)}

    def restore_completion_bindings(self, bindings):
        for key in ('refs', 'generations', 'latest', 'counts', 'subject_generations'):
            setattr(self, key, deepcopy(bindings.get(key, {})))
        self.effect_bindings = deepcopy(bindings.get('effects', {}))
        self.pending_actions = deepcopy(bindings.get('pendingActions', {}))

    def evaluate_effects(self):
        """Recheck final requested effects, replacing superseded subject writes."""
        # A renderer may acknowledge after the dispatch reply. Recheck only
        # the saved effect binding; never re-dispatch an action to resume it.
        for identity, pending in list(self.pending_actions.items()):
            binding = pending.get('deferredEffect')
            if binding is None:
                continue
            contract = self._contract(binding['name'])
            rows = contract['checks_factory'](binding['args'])
            rows = [row for row in rows if row.get('effect')]
            try:
                passed = bool(rows) and all(row.get('deferred') and
                    row['check'](binding['args'], binding['value'], binding['before']) is True for row in rows)
            except Exception:
                passed = False
            if passed:
                self.effect_bindings[binding['subjectKey']] = binding
                self.pending_actions.pop(identity, None)
        checks = [{'name':row['name'], 'passed':False, 'observed':False,
                   'reason':'Requested action has not passed its effect checks', 'actionIdentity':identity}
                  for identity,row in self.pending_actions.items()]
        for binding in self.effect_bindings.values():
            contract = self._contract(binding['name'])
            rows = contract['checks_factory'](binding['args']) if contract.get('checks_factory') else []
            rows = [row for row in rows if row.get('effect')]
            passed, error = False, None
            try:
                passed = bool(rows) and all(row['check'](binding['args'], binding['value'], binding['before']) for row in rows)
            except Exception as exc:
                error = str(exc)
            checks.append({'name':binding['name'], 'subjectKey':binding['subjectKey'], 'passed':bool(passed),
                           'observed':bool(rows), **({'observerError':error} if error else {})})
        return checks

    def _goal_feedback(self, checks):
        checks = model_value(checks)
        failures = [comparison for check in checks for comparison in check.get('comparisons', [])
                    if not comparison.get('passed')]
        failures += [{'observerError': error} for check in checks for error in check.get('observerErrors', [])]
        detail = self._put(checks)
        compact = []
        for failure in failures[:8]:
            compact.append({key: (value[:240] + '...' if isinstance(value, str) and len(value) > 240 else value)
                            for key, value in model_value(failure).items()})
        text = 'Q G ' + json.dumps(compact, ensure_ascii=False, separators=(',', ':')) + ' detail=' + detail + '\n'
        # Internal goal observers can invalidate UI tokens. Rebind and publish
        # their newest elements, so recovery never acts on hidden stale refs.
        text += self._goal_state_text()
        self.metrics['Q'] += 1
        return text

    def _language_gate(self, summary):
        """Configured CL skills on the done() summary and the task's changed deliverables.

        Returns (verdict, CL lines): True clean, False refused, None not run. A block hit refuses done();
        the same unchanged hits refused twice pass the third time with a Q line, so a quoted source can't trap a run."""
        if os.environ.get('NEYVIA_LANGUAGE_GATE', '1') == '0':
            return None, ''
        self.skill_receipts, self.output_paths = {}, []
        try:
            from ..cl_deliverables import configured_gate
            result = configured_gate(self.root, self.started, summary, self.task_text, lesson_provider=self.lesson_provider,
                                     task_id=getattr(self, 'task_id', None), lesson_root=getattr(self, 'lesson_root', self.root))
        except Exception as exc:
            return False, 'X skills unavailable ' + json.dumps(str(exc)[:160]) + ' -> repair the configured gate\n'
        self.metrics['languageBlocking'] = result['blocking']
        self.metrics['languageWarnings'] = result['warnings']
        self.skill_receipts = result['reports']
        self.output_paths = result['files']
        self.lesson_fires.update(result['lessonFires'])
        if not result['blocking']:
            return True, result['cl']
        key = json.dumps(result['signature'])
        count = self.language_refusals.get(key, 0) + 1
        self.language_refusals[key] = count
        # A repeated identical refusal is accepted only when every blocking hit is cited text (quote, code, blockquote):
        # a quoted source must not trap a run, but the agent's own words never pass on a retry counter (audit F9).
        hits = []
        for entry in result['signature']:
            try: hits.append(json.loads(entry)[2])
            except Exception: hits.append({})
        if count >= 3 and hits and all(isinstance(hit, dict) and hit.get('quoted') for hit in hits):
            return True, result['cl'] + 'Q language unresolved block:' + str(result['blocking']) + ' accepted: every hit is quoted source text\n'
        self.metrics['languageRefusals'] = self.metrics.get('languageRefusals', 0) + 1
        return False, result['cl'] + 'Q language rewrite the lines above in the files (or the summary), then done() again\n'

    def goal(self, expression):
        if isinstance(expression, dict): expression = expression['expression']
        self.invalidate_done()
        self.goal_states = {}
        checked = self.evaluate(expression)
        if not checked['observed']: raise ValueError('G must read a grounded observer')
        self.goals.append(expression)
        return checked

    def invalidate_done(self):
        self.task_active = True
        self.completion_generation += 1
        self.done_status = None
        self.done_generation = None

    def _arguments(self, action, *, internal=False, environment=None):
        name, schema = action.name, self._schema(action.name)
        contract, autos = self._contract(name), self._auto(name)
        aliases = {'source': 'from'} if 'from' in schema.get('properties', {}) else {}
        aliases.update(contract.get('aliases', {}))
        exposed = [key for key in schema.get('properties', {}) if key not in autos]
        args = {aliases.get(k, k): v for k, v in action.arguments.items()}
        positional = list(action.positional)
        if contract.get('window_selection') and positional:
            if 'window' in args: raise ValueError('Duplicate argument: window')
            args['window'] = positional.pop(0)
        selected_window = None
        if contract.get('window_selection') and 'window' in args:
            value = args.pop('window')
            if isinstance(value,(BareWord,Handle)) or isinstance(value,str) and value in self.live_refs():
                selected_window = self.resolve(str(value).lstrip('@'))
            if not isinstance(selected_window,dict): raise ValueError('window requires a live window ref')
        expected = len(action.arguments) + (1 if contract.get('window_selection') and action.positional else 0)
        if len(args) + (1 if selected_window else 0) != expected: raise ValueError('Duplicate alias and real argument')
        if len(positional) > len(exposed): raise ValueError('Too many positional arguments')
        for key, value in zip(exposed, positional):
            if key in args: raise ValueError('Duplicate argument: ' + key)
            args[key] = value
        if name == 'cua.action' and isinstance(args.get('args'), dict) and 'element' in args['args']:
            nested = dict(args['args'])
            if 'element_token' in nested: raise ValueError('Supply either element or element_token, not both')
            nested['element_token'] = nested.pop('element')
            args['args'] = nested
        if not internal and autos.keys() & args.keys():
            raise ValueError('Host-filled parameters are forbidden: ' + ', '.join(sorted(autos.keys() & args.keys())))
        flags = []
        def bind(value, field, key):
            if not internal and name == 'cua.action' and key == 'element_token':
                alias = str(value).lstrip('@')
                row = self.refs.get(alias)
                if not isinstance(value, (BareWord, Handle)) or not alias.startswith('e') or not row or row['layer'] != 'cua':
                    raise ValueError('Native element requires a fresh cua e-ref from cua.inspect(window); use args={element:e1, value:"text"}')
                return self.resolve(alias)
            if not internal and key in AUTO_FIELDS:
                raise ValueError('Host-filled parameters are forbidden: '+key)
            if isinstance(value, BareWord):
                if internal and environment is not None and str(value) in environment: return environment[str(value)]
                if REF.fullmatch(str(value)): return self.resolve(value)
                raise ValueError('Bare identifiers are refs, strings must be quoted: ' + str(value))
            if isinstance(value, Handle): return self.resolve(str(value).lstrip('@'))
            if key in contract.get('refs', []) or key == 'target' and not contract.get('literal_targets'):
                if isinstance(value, str) and value in self.live_refs():
                    flags.append('quoted-ref')
                    return self.resolve(value)
                if not internal: raise ValueError('Expected live ref; available: ' + ', '.join(self.live_refs()))
            if isinstance(value, dict): return {k: bind(v, field.get('properties', {}).get(k, {}), k) for k, v in value.items()}
            if isinstance(value, list): return [bind(v, field.get('items', {}), key) for v in value]
            if isinstance(value, Action): raise ValueError('Nested calls are not arguments')
            return value
        args = {key: bind(value, schema.get('properties', {}).get(key, {}), key) for key, value in args.items()}
        for key, field in schema.get('properties', {}).items():
            if key not in args and 'default' in field: args[key] = deepcopy(field['default'])
        for key, rule in autos.items():
            if callable(rule): args[key] = rule(args, self.latest.get(self.layer(name)))
            elif isinstance(rule, str):
                args[key] = self.evaluate(rule.removeprefix('auto(').removesuffix(')') if rule.startswith('auto(') else rule, args)['value']
            elif key == 'expectedModified':
                if args.get('path'):
                    observer = name.rsplit('.', 1)[0] + '.read'
                    prior = self.reads.get((observer, json.dumps({'path': args['path']}, sort_keys=True)))
                    if not isinstance(prior, dict) or 'modified' not in prior:
                        try: prior = self._observer(observer, [], {'path': args['path']})
                        except (OSError, ValueError):
                            # Creating a missing note has no previous CAS stamp.
                            prior = None
                    if prior is not None:
                        if 'modified' not in prior:
                            raise ValueError('Fresh Notes observer has no native CAS stamp')
                        args[key] = prior['modified']
            else:
                latest = self.latest.get(self.layer(name), {})
                candidates = selected_window or latest
                if isinstance(candidates,dict) and key in candidates: args[key] = candidates[key]
                elif key == 'window_id' and isinstance(candidates,dict) and 'windowId' in candidates: args[key] = int(candidates['windowId'])
                elif key == 'sessionId' and isinstance(latest,dict) and isinstance(latest.get('session'),str): args[key] = latest['session']
                elif isinstance(latest,dict) and isinstance(latest.get('windows'),list) and len(latest['windows'])==1 and key in latest['windows'][0]: args[key] = latest['windows'][0][key]
                elif key == 'window_id' and isinstance(self.latest.get(self.layer(name) + ':window'), dict): args[key] = self.latest[self.layer(name) + ':window']['window_id']
                elif key in schema.get('required', []): raise ValueError('Observe before host can fill ' + key)
        Draft202012Validator(schema).validate(args)
        return args, flags

    def _state(self, layer, value, *, observer=None, args=None):
        subject = self._subject(layer, observer, args)
        if subject not in self.observation_subjects:
            self.observation_subjects[subject] = 'o' + str(len(self.observation_subjects) + 1)
        # A native observation invalidates refs for its window/tab even when
        # produced by a mutation's observer rather than a direct observer call.
        selection = {key: (args or {}).get(key, value.get(key))
                     for key in ('window_id', 'windowId', 'browserId', 'sessionId', 'path')
                     if isinstance(value, dict) and (args or {}).get(key, value.get(key)) is not None}
        ref_subject = None
        if self.observation_mode == 'diff':
            target_scope = next((row.get('subject') for ref, row in reversed(list(self.refs.items()))
                                 if ref.startswith('e') and row['raw'] == (args or {}).get('target') and row.get('subject')), None)
            ref_subject = target_scope or self._subject(layer, 'native', selection or args)
        self.generations[layer] = self.generations.get(layer, 0) + 1
        if isinstance(value, dict) and isinstance(value.get('elements'), list):
            self.subject_generations[ref_subject] = self.subject_generations.get(ref_subject, 0) + 1
        alias = self._put(value, layer=layer)
        lines = []
        current_refs = []
        ref_paths = {}
        def clean(row):
            if isinstance(row, dict): return {k: clean(v) for k, v in row.items() if k not in IDENTIFIERS}
            if isinstance(row, list): return [clean(v) for v in row]
            return row
        if isinstance(value,dict) and isinstance(value.get('windows'),list):
            lines.append('S '+layer+' '+alias+' #'+str(len(value['windows']))+' [title process ref]')
            for index, row in enumerate(value['windows']):
                ref = next((key for key, binding in self.refs.items()
                            if key.startswith('w') and binding['layer'] == layer and binding['raw'] == row), None)
                ref = ref or self._put(row,'w',layer)
                current_refs.append(ref)
                ref_paths[ref] = '/windows/' + str(index)
                lines.append('E '+json.dumps(row.get('title',''))+' '+json.dumps(row.get('process',row.get('processName','')))+' '+ref)
        elif isinstance(value, dict) and isinstance(value.get('elements'), list):
            lines.append('S ' + layer + ' ' + alias + ' #' + str(self.generations[layer]) + ' [role label ref value]')
            for index, row in enumerate(value['elements']):
                token = row.get('element_token', row.get('target', row.get('id')))
                if token is None: continue
                ref = self._put(row, 'e', layer, token, subject=ref_subject)
                current_refs.append(ref)
                ref_paths[ref] = '/elements/' + str(index)
                lines.append('E ' + json.dumps(row.get('role', 'element')) + ' ' + json.dumps(row.get('label', row.get('name', ''))) + ' ' + ref + ' value=' + json.dumps(row.get('value', ''), ensure_ascii=False))
            extra = clean({k:v for k,v in model_value(value).items() if k != 'elements'})
            if extra: lines.append('E ' + json.dumps(extra, ensure_ascii=False, separators=(',', ':')))
        else:
            # The diff owner still retains the exact snapshot below. Its full
            # model view uses authored scalar/reference codecs, not JSON cells.
            lines.extend(self.codecs.render(layer, model_value(value)).rstrip().splitlines())
        visible = clean(model_value(value))
        snapshot = {'subject': subject, 'subjectRef': self.observation_subjects[subject],
                    'layer': layer, 'observer': observer or layer, 'inputs': self._model_arguments(args or {}),
                    'stateRef': alias, 'sequence': self.observation_states.get(subject, {}).get('sequence', 0) + 1,
                    'visible': deepcopy(visible), 'liveRefs': current_refs, 'refPaths': ref_paths}
        self.observation_states[subject] = snapshot
        self.observation_snapshots[alias] = deepcopy(snapshot)
        text = self._diff_state(snapshot) if self.observation_mode == 'diff' else '\n'.join(lines) + '\n'
        if self.observation_mode != 'diff' and len(text) > 4000:
            text = lines[0] + '\nQ projection truncated ref=' + alias + ' use=project\n'
            self.metrics['Q'] += 1
        raw = json.dumps(value, ensure_ascii=False)
        if any('"' + marker + '"' in raw for marker in ('inferred', 'unknown', 'uncertain', 'transcribed')):
            text += 'Q observation certainty below observed ref=' + alias + '\n'
            self.metrics['Q'] += 1
        return text

    @staticmethod
    def _observation_changes(before, after, path=''):
        """Lossless JSON Patch, including explicit removals from shrinking lists."""
        from ..manual_state import changes
        if isinstance(before, list) and isinstance(after, list):
            rows = [{'op': 'remove', 'path': path + '/' + str(index)}
                    for index in range(len(before) - 1, len(after) - 1, -1)]
            for index, (old, new) in enumerate(zip(before, after)):
                rows.extend(HostContext._observation_changes(old, new, path + '/' + str(index)))
            rows.extend({'op': 'add', 'path': path + '/' + str(index), 'value': deepcopy(after[index])}
                        for index in range(len(before), len(after)))
            return rows
        if isinstance(before, dict) and isinstance(after, dict):
            def pointer(key): return key.replace('~', '~0').replace('/', '~1')
            rows = [{'op': 'remove', 'path': path + '/' + pointer(key)} for key in sorted(before.keys() - after.keys())]
            for key in sorted(after):
                child = path + '/' + pointer(key)
                rows.extend(HostContext._observation_changes(before[key], after[key], child)
                            if key in before else [{'op': 'add', 'path': child, 'value': deepcopy(after[key])}])
            return rows
        return changes(before, after, path)

    def _diff_state(self, snapshot):
        """Model projection only; raw snapshots and dispatch receipts are intact."""
        encode = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        baseline = self.observation_baselines.get(snapshot['subject'])
        prefix = 'S ' + snapshot['layer'] + ' ' + snapshot['stateRef'] + ' #' + str(snapshot['sequence']) + ' subject=' + snapshot['subjectRef']
        if baseline is None:
            text = prefix + ' full\nE ' + encode(snapshot['visible']) + '\n'
            metric = 'observationFull'
        else:
            patch = self._observation_changes(baseline['visible'], snapshot['visible'])
            mode = 'delta' if patch else 'refresh' if any(ref.startswith('e') for ref in snapshot['liveRefs']) else 'unchanged'
            text = prefix + ' ' + mode + ' base=' + baseline['stateRef'] + '\n'
            if patch: text += 'D ' + snapshot['layer'] + ' ' + encode(patch) + '\n'
            metric = 'observation' + mode.title()
        self.metrics[metric] = self.metrics.get(metric, 0) + 1
        if snapshot['liveRefs']:
            # New aliases are always published, even if all visible UI values
            # stayed equal. Old element refs must never silently survive refresh.
            # Explicit source indices preserve duplicate visually equal rows.
            text += 'E refs=' + encode(snapshot['refPaths']) + '\n'
        return text

    def _snapshot_identity(self, name, args):
        """Contracts may name the grounded snapshot observer and resolved inputs.

        This prevents write bodies becoming observation subjects/model context.
        Without that optional identity, separate action.snapshot streams still
        retain their selection arguments and lossless archived state.
        """
        authored = self._contract(name).get('observation_identity')
        if authored:
            observer, inputs = authored(args) if callable(authored) else authored
            return observer, inputs
        if name == 'notes.write': return 'notes.read', {'path': args['path']}
        inputs = {key: value for key, value in args.items()
                  if key in {'path', 'from', 'to', 'window_id', 'windowId', 'browserId', 'sessionId', 'target'}}
        return name + '.snapshot', inputs

    def _awareness(self, name, args, contract, after=False, result=None):
        resources = contract.get('resources')
        paths = resources(args) if callable(resources) else resources or [str(args[k]) for k in ('path', 'from', 'to') if args.get(k)]
        if self.awareness: return self.awareness(name, args, after=after, result=result, paths=paths)
        if not after:
            if self.root and paths:
                from ..neyvia_awareness import board_list
                return [{'kind':'K', 'value':row} for row in board_list(self.root, {'files':paths}).get('claims', [])]
            return []
        impact = contract.get('impact', {})
        undo = impact.get('undo', 'none')
        wrote = paths if result is not None and not (isinstance(result, dict) and result.get('ok') is False) else []
        row = {'wrote':wrote, 'touched':impact.get('writes', self.layer(name)), 'undo':undo}
        events = contract.get('events')
        if callable(events): row['emitted'] = events()
        elif events: row['emitted'] = events
        if self.root and paths:
            from ..neyvia_impact import impact as impact_map
            in_repo = []
            for path in paths:
                try:
                    candidate = Path(path)
                    candidate = candidate if candidate.is_absolute() else self.root / candidate
                    relative = candidate.resolve().relative_to(REPO)
                    # Task state is not implementation source. Building the
                    # repository wiring index for every scratch write adds no
                    # dependencies and can dominate a small-model turn.
                    if relative.parts and relative.parts[0] not in {'.agent_control','.neyvia'}:
                        in_repo.append(relative.as_posix())
                except ValueError: continue
            if in_repo: row['dependencies'] = impact_map(in_repo, gaps=False)['files']
        return [{'kind':'I', 'value':row}]

    def _lines(self, rows):
        text = ''
        for row in rows or []:
            if isinstance(row, str):
                kind, _, body = row.partition(' ')
            else:
                kind = row['kind']
                value = row['value']
                body = json.dumps(model_value(value), ensure_ascii=False, separators=(',', ':'))
                if len(body) > 800:
                    detail = self._put(value)
                    visible = {key: value[key] for key in ('wrote','touched','emitted','undo','approval','agent','intent') if key in value}
                    body = json.dumps(model_value(visible), ensure_ascii=False, separators=(',', ':')) + ' detail=' + detail
            if kind not in {'I', 'K', 'Q'}: raise ValueError('Invalid host awareness kind')
            self.metrics[kind] += 1
            text += kind + ' ' + body + '\n'
        return text

    def _action(self, action, identity, *, internal=False, environment=None, procedure=None, procedure_check=None):
        name = action.name
        if name not in self.tools: raise ValueError('Unknown action: ' + name)
        contract = self._contract(name)
        fingerprint = hashlib.sha256(json.dumps([name,action.arguments,action.positional,environment if internal else None], sort_keys=True, default=str).encode()).hexdigest()
        if identity in self.identities:
            prior = self.identities[identity]
            if prior['fingerprint'] != fingerprint: raise ValueError('Action identity reused for different arguments')
            return deepcopy(prior['value'])
        args, flags = self._arguments(action, internal=internal, environment=environment)
        mutation = not self.readonly(name, args)
        self.task_active = True
        if mutation:
            self.invalidate_done()
            # Track all requested writes, including those with an authored G.
            # Deferred effects must survive without a generated default goal.
            self.pending_actions[identity] = {'name':name}
        generated = ''
        defaults_only = not self.goals or all(goal in self.default_goals.values() for goal in self.goals)
        if mutation and not self.task_goals and defaults_only and contract.get('default_goal'):
            default = contract['default_goal'](args)
            if default:
                subject, expression = default
                previous = self.default_goals.get(subject)
                if previous in self.goals: self.goals.remove(previous)
                self.goal(expression)
                self.default_goals[subject] = expression
                generated = 'Q host goal: G: ' + expression + '\n'
        manual = contract['manual_factory'](args, procedure, identity) if contract.get('manual_factory') else None
        if mutation and contract.get('manual_factory') and manual is None:
            return {'ok':False, 'status':'frontier', 'cl':'R '+name+' frontier\nF no applicable current executable manual procedure; no action ran\n'}
        if mutation and not (self.goals or self.task_goals): raise ValueError('Author observer-based G before the first mutation')
        checks = contract['checks_factory'](args) if contract.get('checks_factory') else contract.get('checks', [])
        if procedure_check:
            checks = [*checks, procedure_check(args, environment)]
        automatic = [row for row in checks if not row.get('parameters')]
        if mutation and not any(row.get('observer') for row in automatic):
            return {'ok':False, 'status':'frontier', 'cl':'R ' + name + ' frontier\nF no grounded observer; no action ran\n'}
        if manual:
            manual['effectChecks'] = [{key:row[key] for key in ('name','observerTool','subject','expectation') if key in row}
                                      for row in automatic if row.get('effect')]
            manual['checkIds'] = sorted(set(manual.get('checkIds', [])) | {row['name'] for row in automatic if row.get('effect')})
        prefix = generated + (self._lines(self._awareness(name,args,contract)) if mutation else '')
        observe = (lambda: contract['snapshot'](args)) if contract.get('snapshot') else contract.get('observe')
        before = observe() if mutation and observe else None
        for row in automatic:
            if row.get('pre') and not row['check'](args,None,before):
                return {'ok':False, 'status':'refused', 'cl':prefix + 'R ' + name + ' refused -' + row['name'] + '\n'}
        if manual and contract.get('manual_record'):
            contract['manual_record'](manual)
        output = self.dispatch(name, args, action_id=identity)
        value = unwrap(output)
        if mutation:
            subjects = []
            for row in automatic:
                if not row.get('effect'): continue
                try:
                    subject = row['bindSubject'](args,value,before) if row.get('bindSubject') else row['subjectKey']
                    if subject is not None: subjects.append(subject)
                except (KeyError, TypeError, ValueError):
                    pass  # Unbound failed requests cannot be superseded safely.
            self.pending_actions[identity]['subjectKeys'] = subjects
        if name == 'terminal.exec' and isinstance(value, dict):
            # Bind recovery to the exact host intent, including a completed
            # gateway action returned after a fresh interpreter is created.
            value['terminalActionId'] = identity
        if mutation and isinstance(value,dict) and value.get('ok') is not False:
            self.taste.observe_write(args.get('path'))
        status = 'ok'
        if isinstance(value,dict) and value.get('ok') is False:
            marker = str(value.get('status', 'fail'))
            status = 'ask' if 'approval' in marker or marker == 'ask' else 'stale' if marker in {'conflict','stale'} or 'stale' in marker else marker
        if name == 'mobile.create' and status == 'ask' and value.get('status') == 'approval_required' and observe:
            # This refusal precedes starter creation. Clear only an approval
            # attempt whose exact target is freshly observed to be unchanged.
            approval_after = contract['after_snapshot'](args,before) if contract.get('after_snapshot') else observe()
            if before is not None and approval_after == before:
                self.pending_actions.pop(identity, None)
        marks, after = [], None
        if status == 'ok' and mutation and observe:
            after = contract['after_snapshot'](args,before) if contract.get('after_snapshot') else observe()
            self._remember(name, args, after)
            if name.endswith('notes.write') and args.get('path') and isinstance(after, dict):
                self._remember(name.rsplit('.', 1)[0] + '.read', {'path':args['path']}, after)
        if status == 'ok':
            for row in automatic:
                if row.get('pre'): continue
                try: passed = row['check'](args,value,before)
                except Exception: passed = None
                marks.append({'name':row['name'], 'passed':None if passed is None else bool(passed)})
            if any(row['passed'] is False for row in marks): status = 'fail'
            elif any(row['passed'] is None for row in marks): status = 'unknown'
        if not mutation and status == 'ok': self._remember(name,args,value)
        if mutation and status == 'ok':
            completed_subjects = set()
            for row in automatic:
                if row.get('effect'):
                    subject = row['bindSubject'](args,value,before) if row.get('bindSubject') else row['subjectKey']
                    self.effect_bindings[subject] = {'name':name,'args':deepcopy(args),'value':deepcopy(value),
                        'before':deepcopy(before),'subjectKey':subject}
                    completed_subjects.add(subject)
            # A fresh verified correction supersedes only failed effects on
            # these exact subjects. Unrelated requests still block completion.
            for pending_id, pending in list(self.pending_actions.items()):
                subjects = pending.get('subjectKeys', [])
                if subjects and set(subjects).issubset(completed_subjects):
                    self.pending_actions.pop(pending_id, None)
            self.pending_actions.pop(identity, None)
        elif mutation and status == 'unknown' and automatic and all(row.get('deferred') for row in automatic):
            # Deferred renderer checks remain incomplete until an authenticated
            # content report passes. The pending binding survives MCP recovery.
            row = automatic[0]
            self.pending_actions[identity]['deferredEffect'] = {
                'name':name, 'args':deepcopy(args), 'value':deepcopy(value),
                'before':deepcopy(before), 'subjectKey':row['subjectKey']}
        receipt = self._put({'name':name,'arguments':args,'result':output,'checks':marks,'before':before,'after':after,'manualUse':manual},'r')
        text = prefix + 'R ' + name + ' ' + status + ' ' + receipt + ''.join(' ' + ('+' if m['passed'] is True else '-' if m['passed'] is False else '?') + m['name'] for m in marks)
        text += (' ' + ' '.join(flags) if flags else '') + '\n'
        if mutation:
            text += self._lines(self._awareness(name,args,contract,True,value))
            if status == 'ask': text += self._lines([{'kind':'K','value':{'approval':name}}])
            if after is not None:
                if self.observation_mode == 'full':
                    from ..manual_state import changes
                    delta = model_value(changes(model_value(before), model_value(after)))
                    text += 'D ' + self.layer(name) + ' ' + json.dumps(delta,ensure_ascii=False,separators=(',', ':')) + '\n' if len(json.dumps(delta)) < 2000 else 'D ' + self.layer(name) + ' ' + self._put(delta) + '\n'
                observer, inputs = self._snapshot_identity(name, args)
                text += self._state(self.layer(name), after, observer=observer, args=inputs)
            elif status == 'stale' and name.endswith('notes.write') and args.get('path'):
                fresh = self._observer(name.rsplit('.',1)[0]+'.read',[],{'path':args['path']})
                text += 'D notes other-writer\n' + self._state('notes',fresh, observer=name.rsplit('.',1)[0]+'.read', args={'path':args['path']})
        elif status == 'ok': text += self._state(self.layer(name),value, observer=name, args=args)
        # A read whose postcondition failed still shows what it observed (e.g. the hits behind -clean).
        elif status == 'fail' and value is not None: text += self._state(self.layer(name),value, observer=name, args=args)
        if any(m['passed'] is None for m in marks): text += self._lines([{'kind':'Q','value':{'check':'unknown','action':name}}])
        if status != 'ok':
            for line in (self.help(self.layer(name), 2).splitlines() if self.manual_view else []):
                if line.startswith('X ') and (name in line or self.layer(name) in line): text += line + '\n'; break
        self.metrics['actions'] += 1
        self.metrics['checks'] += len(marks)
        result = {'ok':status=='ok','status':status,'name':name,'arguments':args,'result':output,'receipt':receipt,'checks':marks,'manualUse':manual,'cl':text}
        self._learn_route_result(name, result)
        # Unknown dispatches are never blindly replayed under the same identity.
        if mutation and status not in {'ask','stale','paused_by_user'}:
            self.identities[identity] = {'fingerprint':fingerprint,'value':deepcopy(result)}
        return result

    def _learn_route_result(self, name, result):
        if self.root is None or not self.task_text or result.get('status') != 'ok' or self.laya_route_learned:
            return
        # A model's successful selected tool layer is the observation. A route
        # preselected by LAYA cannot independently confirm its own prediction.
        if getattr(self, 'routed_by_laya', None):
            return
        from ..laya_hooks import learn_route
        try:
            from ..durability import atomic_write_json
            evidence = {'task': str(self.task_text), 'tool': name, 'actualLayer': self.layer(name),
                        'status': result['status'], 'hostReceipt': str(result['receipt']),
                        'resultSha256': hashlib.sha256(json.dumps(result.get('result'), sort_keys=True, default=str).encode()).hexdigest()}
            receipt_path = self.root / '.neyvia/laya/route-outcomes' / (hashlib.sha256(
                json.dumps(evidence, sort_keys=True).encode()).hexdigest() + '.json')
            atomic_write_json(receipt_path, evidence)
            learned = learn_route(self.root, str(self.task_text), self.layer(name),
                                  str(receipt_path), verdict=self.laya_route_verdict)
            self.laya_route_learned = bool(learned.get('learned'))
        except Exception:
            pass  # Learning never changes the action receipt or its checks.

    def _procedure_key(self, name):
        if name in self.procedures: return name
        layer, _, procedure = name.rpartition('.')
        return self.procedure_aliases.get(layer, layer) + '.' + procedure

    def _procedure(self, action, identity):
        name, proc = action.name, self.procedures[self._procedure_key(action.name)]
        fingerprint = hashlib.sha256(json.dumps([name,action.arguments,action.positional],sort_keys=True,default=str).encode()).hexdigest()
        if identity in self.completed_procedures:
            previous = self.completed_procedures[identity]
            if previous['fingerprint'] != fingerprint: raise ValueError('Procedure identity reused for different arguments')
            return deepcopy(previous['value'])
        if not proc.get('goal') and not proc.get('effect_goal'): raise ValueError('R18: procedure has no G')
        inputs = dict(action.arguments)
        for key,value in zip(proc['inputs'].get('properties',{}),action.positional):
            if key in inputs: raise ValueError('Duplicate procedure argument')
            inputs[key] = value
        for key,value in list(inputs.items()):
            if isinstance(value,(BareWord,Handle)):
                alias = str(value).lstrip('@')
                if not REF.fullmatch(alias): raise ValueError('Procedure strings must be quoted')
                inputs[key] = self.resolve(alias)
        choices = proc.get('choices',{})
        base = {key:value for key,value in inputs.items() if key not in choices}
        key = json.dumps([name,base],sort_keys=True)
        state = self.paused.setdefault(key, {'step':0,'identity':identity,'inputs':{},'results':[]})
        inputs = {**state['inputs'],**inputs}
        for field, schema in proc['inputs'].get('properties', {}).items():
            if field not in inputs and 'default' in schema: inputs[field] = deepcopy(schema['default'])
        Draft202012Validator(proc['inputs']).validate({k:v for k,v in inputs.items() if k in proc['inputs'].get('properties',{})})
        state['inputs'] = inputs
        self.metrics['procedures'] += 1
        while state['step'] < len(proc['steps']):
            step = proc['steps'][state['step']]
            if 'judge' in step:
                choice = step['judge']; row = choices.get(choice,step)
                if choice not in inputs:
                    return {'ok':False,'status':'ask','cl':''.join(r['cl'] for r in state['results'])+'R '+name+' ask J '+choice+' '+'|'.join(json.dumps(x) for x in row['options'])+': '+json.dumps(row['question'])+'\n'}
                if inputs[choice] not in row['options']: raise ValueError('Invalid judgement choice')
            elif step.get('when') and inputs.get(step['when']['judge']) != step['when']['option']:
                pass
            elif 'call' in step or 'tool' in step:
                if 'tool' in step:
                    from ..neyvia_manuals import resolve
                    args = resolve(step['args'],inputs,inputs,proc.get('root',self.root))
                    call = Action(step['tool'],args)
                else:
                    call = parse_action(step['call'])
                result = self._action(call,state['identity']+':step:'+str(state['step']),internal=True,environment=inputs,procedure=step.get('procedure'),procedure_check=step.get('check_factory'))
                state['results'].append(result)
                if not result['ok']:
                    return {**result,'cl':''.join(r['cl'] for r in state['results'])+'R '+name+' '+result['status']+'\n'}
                if step.get('save'): inputs[step['save']] = unwrap(result['result'])
            else: raise ValueError('Unrecognized host procedure step')
            state['step'] += 1
        self.goal_states = {}
        if proc.get('goal'):
            checked = self.evaluate(proc['goal'],inputs)
            if proc.get('effect_goal'):
                checked['effects'] = self.evaluate_effects()
                checked['passed'] = checked['passed'] and all(row['passed'] for row in checked['effects'])
        else:
            effects = self.evaluate_effects()
            checked = {'passed':bool(effects) and all(row['passed'] for row in effects),
                       'observed':[row['name'] for row in effects if row['observed']], 'effects':effects}
        passed = checked['passed'] and bool(checked['observed'])
        text = ''.join(row['cl'] for row in state['results']) + 'R '+name+(' ok +G\n' if passed else ' refused -G\n')
        if not passed: text += self._goal_feedback([checked])
        else:
            text += self._goal_state_text()
        step_checks = [check for row in state['results'] for check in row.get('checks', [])]
        result = {'ok':passed,'status':'ok' if passed else 'refused','checks':step_checks+[{'name':'G','passed':passed}], 'goal':checked,'cl':text}
        if passed:
            self.paused.pop(key,None)
            self.completed_procedures[identity] = {'fingerprint':fingerprint,'value':deepcopy(result)}
        return result

    def _execute_one(self, source, identity):
        self.refresh_memory()
        if source.startswith('G'):
            expression = source.split(':',1)[1].strip()
            self.goal(expression)
            return {'ok':True,'status':'ok','cl':'R G ok\n'+self._goal_state_text()}
        action = parse_action(source)
        self.refresh_memory(layer=self.layer(action.name), args=action.arguments)
        if action.name == 'help':
            layer = action.positional[0] if action.positional else action.arguments['layer']
            level = action.positional[1] if len(action.positional)>1 else action.arguments.get('level',1)
            return {'ok':True,'status':'ok','cl':self.help(layer,level)}
        if action.name == 'done':
            self.task_active = True
            self.goal_states = {}
            summary = action.positional[0] if action.positional else action.arguments.get('summary', '')
            language, language_text = self._language_gate(str(summary or ''))
            taste, taste_text = self.taste.gate()
            checks = [self.evaluate(goal) for goal in [*self.task_goals, *self.goals]] + self.evaluate_effects()
            goals_passed = bool(checks) and all(row['passed'] and row['observed'] for row in checks)
            passed = goals_passed and language is not False and taste is not False
            self.done_status = 'ok' if passed else 'refused' if checks or language is False or taste is False else 'unverified'
            self.done_generation = self.completion_generation if passed else None
            if passed:
                from ..cl_deliverables import lesson_service
                service = lesson_service(getattr(self, 'lesson_root', self.root))
                if service:
                    service.record_fires(sorted(self.lesson_fires), getattr(self, 'task_id', None))
            if not passed: self.metrics['goalRefusals'] += 1
            marks = (' +G' if goals_passed else ' -G') + ('' if language is None else ' +language' if language else ' -language') + ('' if taste is None else ' +taste' if taste else ' -taste')
            feedback = self._goal_feedback(checks) if not goals_passed else self._goal_state_text()
            return {'ok':passed,'status':self.done_status,'goalChecks':checks,'language':language,'taste':taste,'skillReceipts':deepcopy(self.skill_receipts),'outputPaths':list(self.output_paths),
                    'cl':'R done '+self.done_status+marks+'\n'+language_text+taste_text+feedback}
        if action.name in {'taste.record_concept', 'taste.record_research', 'taste.record_research_addendum', 'taste.record_repair', 'taste.admit_lesson'}:
            self.invalidate_done()
            if action.name == 'taste.admit_lesson':
                identity = action.positional[0] if action.positional else action.arguments['id']
                evidence = action.positional[1] if len(action.positional) > 1 else action.arguments['evidence']
                value = self.taste.admit_lesson(identity,evidence)
            elif action.name == 'taste.record_research_addendum':
                name = action.positional[0] if action.positional else action.arguments['path']
                folder = action.positional[1] if len(action.positional) > 1 else action.arguments['folder']
                value = self.taste.record_research_addendum(name, folder)
            elif action.name == 'taste.record_repair':
                name = action.positional[0] if action.positional else action.arguments['path']
                edits = action.positional[1] if len(action.positional) > 1 else action.arguments['edits']
                value = self.taste.record_repair(name, edits)
            else:
                key = 'record' if action.name == 'taste.record_concept' else 'rows'
                value = getattr(self.taste, action.name.split('.')[1])(action.positional[0] if action.positional else action.arguments[key])
            return {'ok':True, 'status':'ok', 'result':value, 'cl':'R '+action.name+' ok\nS taste '+json.dumps(value,ensure_ascii=False)+'\n'}
        if action.name == 'taste.review':
            name = action.positional[0] if action.positional else action.arguments['path']
            self.invalidate_done()
            row = self.taste.review(name)
            if row.get('criticSkipped'):
                return {'ok': False, 'status': 'repair_required', 'result': row,
                        'cl': 'R taste.review repair_required\nS taste ' + json.dumps(row, ensure_ascii=False) + '\n'}
            compact = {key:row[key] for key in ('round','sha256','folder','critique','fidelity','pairwise','change','qualityGain','usage')}
            compact['interactionPassed'] = row['interaction']['passed']
            return {'ok':True,'status':'ok','result':compact,
                    'cl':'R taste.review ok\nS taste '+json.dumps(compact,ensure_ascii=False)+'\n'}
        if action.name == 'project':
            values = dict(action.arguments)
            for key,val in zip(('ref','path','start','count'),action.positional): values.setdefault(key,val)
            alias = values.get('ref',values.get('handle'))
            self.resolve(str(alias).lstrip('@'))  # Apply the same live-ref guard as actions.
            value = model_value(self.refs[str(alias).lstrip('@')]['value'])
            path = str(values.get('path',''))
            parts = [p.replace('~1','/').replace('~0','~') for p in path[1:].split('/')] if path.startswith('/') else [p for p in path.split('.') if p]
            for part in parts:
                value = value[int(part)] if isinstance(value,list) else value[part]
            start, count = values.get('start',values.get('offset',0)), values.get('count',values.get('limit',100))
            if type(start) is not int or start < 0 or type(count) is not int or not 1 <= count <= 4000:
                raise ValueError('project requires start >= 0 and count from 1 to 4000')
            total = len(value) if isinstance(value,(dict,list,str)) else 1
            if isinstance(value,dict): value = dict(list(value.items())[start:start+count])
            elif isinstance(value,(list,str)): value = value[start:start+count]
            page = {'start':start,'total':total,'nextStart':start+count if start+count < total else None}
            rendered = value
            if isinstance(value,dict):
                rendered = {}
                pointer = '/'+'/'.join(part.replace('~','~0').replace('/','~1') for part in parts) if parts else ''
                for key,child in value.items():
                    if len(json.dumps(child,ensure_ascii=False)) > 1000:
                        child_path = pointer+'/'+str(key).replace('~','~0').replace('/','~1')
                        rendered[key] = {'Q':'large field; value available by page',
                                         'read':'project('+str(alias)+',path='+json.dumps(child_path)+',start=0,count=400)'}
                    else: rendered[key] = child
            # A projection is a readable page, not another growing live subject.
            return {'ok':True,'status':'ok','cl':'R project ok '+json.dumps(page,separators=(',',':'))+'\nE '+json.dumps(rendered,ensure_ascii=False,separators=(',',':'))+'\n','result':deepcopy(value),'page':page}
        layer = self.layer(action.name)
        prefix = self.help(layer) if layer not in self.loaded else ''
        if source.startswith('run '):
            if self._procedure_key(action.name) not in self.procedures: raise ValueError('Unknown procedure: '+action.name)
            result = self._procedure(action,identity)
        else: result = self._action(action,identity)
        result['cl'] = prefix + result['cl']
        return result

    def execute(self, text, *, action_id='', batch_id=''):
        with self.lock:
            identity = action_id or batch_id or 'cl-'+uuid.uuid4().hex
            results = []
            try:
                sources = list(logical_lines(text))
                for ordinal,raw in enumerate(sources):
                    source = raw.strip()
                    if not re.match(r'(?:do |run )?[A-Za-z_][\w.-]*\(',source) and not re.match(r'G(?:\s+[\w.-]+)?:',source): continue
                    try: result = self._execute_one(source,identity+':'+str(ordinal))
                    except Exception as exc:
                        status = 'stale' if isinstance(exc,StaleHandleError) else 'refused'
                        result = {'ok':False,'status':status,'error':str(exc),'cl':'R batch '+status+'\nX batch -> '+json.dumps(str(exc))+'\n'}
                    results.append(result)
                    if not result['ok']: break
            except ValueError as exc:
                results.append({'ok':False,'status':'refused','error':str(exc),'cl':'R batch refused\nX batch -> '+json.dumps(str(exc))+'\n'})
            return {'ok':bool(results) and all(r['ok'] for r in results),'status':results[-1]['status'] if results else 'refused',
                    'text':''.join(row['cl'] for row in results),'results':results,'doneStatus':self.done_status}
