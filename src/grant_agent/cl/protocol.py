"""The single CL tool over the existing native permission and manual seams."""
from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from pathlib import Path
import re
import threading
import uuid
from .measured_context import PRIMER_O200K_SHA256, PRIMER_O200K_TOKENS

REPO = Path(__file__).resolve().parents[3]
MANUAL_ALIASES = {'image':'image-studio', 'app_sdk':'app-sdk', 'artifact':'outputs', 'gamedev':'game-dev',
                  'timer':'neyvia-reference', 'schedule':'neyvia-reference', 'watch':'neyvia-reference',
                  'work':'awareness', 'plan':'agents', 'view':'neyvia', 'cua':'computer-use',
                  'pane':'neyvia-reference', 'terminal':'workspace', 'mission':'mission-plan'}
ADAPTIVE_WORK_TOOLS = {'work.focus', 'work.problem', 'work.constraint', 'work.update_problem'}


# Layers that exist to prove the product (generated contract cases, proof families, edge fixtures). An agent never picks
# one from the menu to do a person's task, so each line was ~20 tokens of every request for nothing. They fold into one
# line; help("<name>") still loads any of them.
_CONTRACT_LAYER = re.compile(r"^L (C7e-|proofs-|local-)")


def agent_index_lines(lines):
    kept, folded = [], []
    for line in lines:
        (folded if _CONTRACT_LAYER.match(line) else kept).append(line)
    if folded:
        kept.append('L contract-layers v2 -- %d test layers: C7e, proofs-b, local' % len(folded))
    return kept


def primer_context():
    from .integration import index_lines
    primer = (REPO / "docs/standard/1.1/primer.md").read_text(encoding="utf-8").strip()
    if hashlib.sha256(primer.encode("utf-8")).hexdigest() != PRIMER_O200K_SHA256:
        raise ValueError("CL primer changed; run scripts/build_cl_context.py before use")
    if PRIMER_O200K_TOKENS > 300:
        raise ValueError("CL 1.1 R16: primer exceeds 300 tokens")
    return primer + "\n" + "\n".join(agent_index_lines(index_lines())) + "\n"


def unwrap(value):
    from ..neyvia_manuals import unwrap as native_unwrap
    return native_unwrap(value)


class Protocol:
    def __init__(self, gateway, *, lazy_manuals=False):
        self.gateway = gateway
        self.lazy_manuals = lazy_manuals
        self.contracts = {}
        self.manual_actions = {}
        self.manual_documents = {}
        self.manual_catalog_stamp = None
        from . import effects
        self.effect_source_sha256 = hashlib.sha256(Path(effects.__file__).read_bytes()).hexdigest()
        self.effect_source_bindings = self._effect_sources()
        self.scope = None
        self.lock = threading.RLock()
        if not lazy_manuals:
            self._load_contracts()
        from .integration import make_host
        self.host = make_host(self) if not lazy_manuals else None

    def _ensure_manuals(self, lines="", *, layer=None):
        if not self.lazy_manuals:
            return
        from ..neyvia_manuals import compiled_manual_owners, records, catalog_stamp
        admission_stamp = catalog_stamp(include_manifest=True)
        known = {record['id'] for record in records()}
        requested_procedures = set(re.findall(r'\brun\s+([A-Za-z_][\w.-]*)\s*\(', lines))
        owners = compiled_manual_owners()
        if owners is None:
            from .manual_routing import source_owners
            owners = source_owners()
        selected = set()
        parallel_calls = re.findall(r'\b([A-Za-z_][\w.-]*)\s*\(', lines)
        if owners is None and ((parallel_calls and all(
                name in {'done', 'matches'} or name.startswith(('parallel.', 'neyvia.parallel.'))
                for name in parallel_calls)) or (not parallel_calls and layer == 'parallel')):
            # This new manual may precede the release's global cache regeneration.
            # Its own source, schemas and observers still undergo strict grounding.
            selected = {'parallel'}
        elif owners is None and ((parallel_calls and all(
                name in {'done', 'matches'} or name.startswith(('comments.', 'neyvia.comments.'))
                for name in parallel_calls)) or (not parallel_calls and layer == 'comments')):
            # New comments contracts are strictly grounded before the release cache refresh.
            selected = {'comments'}
        elif owners is None:
            selected = known  # Source/manifest drift keeps the full strict path.
        else:
            tool_owners, procedure_owners = owners
            sources = [lines]
            if layer:
                sources.append(layer + '.inspect()')
            for source in sources:
                for name in re.findall(r'\b([A-Za-z_][\w.-]*)\s*\(', source):
                    if name in {'done', 'matches'}:
                        continue
                    if name in procedure_owners:
                        selected.update(procedure_owners[name])
                        continue
                    try:
                        exact = self.resolve_name(name)
                    except ValueError:
                        selected = known
                        break
                    found = tool_owners.get(exact)
                    if found is None:
                        selected = known
                        break
                    selected.update(found)
            if layer:
                manual_layer = MANUAL_ALIASES.get(layer, layer)
                if manual_layer in known:
                    selected.add(manual_layer)
                selected.update(owner for name, group in procedure_owners.items()
                                if name.startswith(manual_layer + '.') for owner in group)
                selected.update(owner for name, group in tool_owners.items()
                                if name.removeprefix('neyvia.').startswith(layer + '.') for owner in group)
        missing = selected - self.manual_documents.keys()
        loaded_any = bool(missing)
        while missing:
            self._load_contracts(missing)
            dependencies = set()
            for manual_id in missing:
                model_layer = 'cua' if manual_id == 'computer-use' else manual_id
                for chapter in self.manual_documents[manual_id]['chapters'].values():
                    for procedure_name, procedure in chapter['procedures'].items():
                        if model_layer + '.' + procedure_name not in requested_procedures:
                            continue
                        for step in procedure['steps']:
                            if 'action' not in step:
                                continue
                            tool = chapter['actions'][step['action']]['tool']
                            family = tool.removeprefix('neyvia.').split('.')[0]
                            owner = MANUAL_ALIASES.get(family, family)
                            if tool in ADAPTIVE_WORK_TOOLS: owner = 'adaptive-work'
                            if tool == 'neyvia.workspace.patch': owner = 'tools-depth'
                            if tool == 'neyvia.view.transparency': owner = 'transparency'
                            if tool == 'neyvia.sidebar.policy': owner = 'neyvia'
                            if owner in known:
                                dependencies.add(owner)
            missing = dependencies - self.manual_documents.keys()
        if self.host is None or loaded_any:
            from .integration import make_host
            updated = make_host(self)
            if self.host is None:
                self.host = updated
            else:
                # Preserve action identities, refs, goals, effects and pending
                # acknowledgements while adding only new manual procedures.
                self.host.procedures.update(updated.procedures)
                self.host.manual_view = updated.manual_view
        self.manual_catalog_stamp = (admission_stamp if admission_stamp ==
                                     catalog_stamp(include_manifest=True) else None)

    @staticmethod
    def _effect_sources():
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in Path(__file__).parent.glob('*effects.py')}

    @staticmethod
    def completion_key(session, task_id):
        return 'cl:completion:' + json.dumps([session or 'unscoped', task_id], separators=(',', ':'))

    def _goal_bus(self):
        from ..ui_command_bus import bus_for
        return bus_for(getattr(self.gateway, 'task_goal_root', self.gateway.root))

    def _sync_task_goals(self):
        session = self.gateway.work_scope or 'unscoped'
        authored = self._goal_bus().get('cl:task-goals:' + session, [])
        if authored != self.host.task_goals:
            for expression in authored:
                checked = self.host.evaluate(expression)
                if not checked['observed']:
                    raise ValueError('Task doneWhen must read a grounded observer')
            self.host.invalidate_done()
            self.host.task_goals = list(authored)

    def _completion_snapshot(self):
        return {'active': self.host.task_active, 'goals': list(self.host.goals),
                'taskGoals': list(self.host.task_goals), 'doneStatus': self.host.done_status,
                'generation': self.host.completion_generation, 'doneGeneration': self.host.done_generation,
                'tasteState': self.host.taste.export_state(),
                'bindings': self.host.completion_bindings(),
                'skillReceipts': self.host.skill_receipts,
                'outputPaths': list(self.host.output_paths)}

    def _save_completion(self):
        if self.host is None:
            return
        task_id = getattr(self.gateway, 'cl_task_id', '')
        if task_id:
            self._goal_bus().put(self.completion_key(self.gateway.work_scope, task_id), self._completion_snapshot())

    def completion(self, *, saved=None):
        """A product task ends only through explicit done and fresh observer G.

        A saved MCP snapshot is bound to a fresh product-run token by its caller.
        Rechecking never invokes done implicitly or changes ordinary reply status.
        """
        with self.lock:
            if self.lazy_manuals:
                expressions = ([*saved.get('goals', []), *saved.get('taskGoals', [])]
                               if saved is not None else list(self.host.goals) if self.host else [])
                self._ensure_manuals('\n'.join(expressions))
            if saved is not None:
                self.host.restore_completion_bindings(saved.get('bindings', {}))
                if saved.get('tasteState'):
                    try:
                        self.host.taste.restore_state(saved['tasteState'])
                    except (KeyError, TypeError, ValueError) as exc:
                        return {'active': True, 'status': 'incomplete', 'reason': 'Invalid persisted taste evidence: ' + str(exc)}
                elif saved.get('tasteRounds'):
                    return {'active': True, 'status': 'incomplete', 'reason': 'Unsealed legacy taste evidence requires new reviews'}
            self._sync_task_goals()
            snapshot = saved if saved is not None else self._completion_snapshot()
            active = bool(snapshot.get('active') or self.host.task_goals)
            if not active:
                return {'active': False, 'status': 'not_applicable'}
            if (snapshot.get('doneStatus') != 'ok' or snapshot.get('doneGeneration') != snapshot.get('generation')
                    or snapshot.get('taskGoals', []) != self.host.task_goals):
                return {'active': True, 'status': 'incomplete', 'reason': 'Explicit successful done required for the current task',
                        'doneStatus': snapshot.get('doneStatus') or 'unverified'}
            goals = [*snapshot.get('taskGoals', []), *snapshot.get('goals', [])]
            checks = [self.host.evaluate(goal) for goal in goals] + self.host.evaluate_effects()
            passed = bool(checks) and all(row['passed'] and row['observed'] for row in checks)
            taste, taste_text = self.host.taste.gate()
            passed = passed and taste is not False
            if not passed and saved is None:
                self.host.done_status = 'refused'
                self.host.done_generation = None
                self._save_completion()
            return {'active': True, 'status': 'completed' if passed else 'incomplete',
                    'doneStatus': 'ok' if passed else 'refused', 'goalChecks': checks,
                    'taste': taste,
                    'skillReceipts': snapshot.get('skillReceipts', {}), 'outputPaths': snapshot.get('outputPaths', []),
                    'reason': '' if passed else taste_text or 'Current observer G no longer passes'}

    def _load_contracts(self, manual_ids=None):
        from ..neyvia_manuals import records, get_manual
        for record in records():
            if manual_ids is not None and record['id'] not in manual_ids:
                continue
            if record['id'] in self.manual_documents:
                continue
            _, digest, data = get_manual(record["id"], self.gateway.root / ".neyvia")
            self.manual_documents[record["id"]] = data
            source_digest = hashlib.sha256((REPO / record.get("clSource", record["path"])).read_bytes()).hexdigest()
            artifact_digest = hashlib.sha256((REPO / record["path"]).read_bytes()).hexdigest()
            for chapter_name, chapter in data["chapters"].items():
                for action_id, action in chapter["actions"].items():
                    binding = {"manual": record["id"], "source": record.get("clSource", record["path"]),
                               "sourceSha256": source_digest,
                               "artifactSha256": artifact_digest,
                               "artifact":record["path"],
                               "manualSha256": digest, "chapter": chapter_name, "action": action_id,
                               "tool": action["tool"], "procedures": []}
                    for procedure_id, procedure in chapter["procedures"].items():
                        for ordinal, step in enumerate(procedure["steps"]):
                            if step.get("action") == action_id:
                                binding["procedures"].append({"id": procedure_id, "step": ordinal,
                                    "args": step["args"], "check": step.get("check")})
                    self.manual_actions.setdefault(action["tool"], []).append(binding)
                    self.contracts.setdefault(action["tool"], {"action": action, "checks": [], "chapter": chapter,
                        "manual": record["id"], "manualSource": record.get("clSource", record["path"])})
                for procedure in chapter["procedures"].values():
                    for step in procedure["steps"]:
                        if step.get("action") and step.get("check"):
                            action = chapter["actions"][step["action"]]
                            self.contracts[action["tool"]]["checks"].append((step, chapter["checks"][step["check"]], procedure))

    def manual_use(self, name, arguments, *, procedure=None, identity=""):
        """Admit the actual action against a current executable manual procedure."""
        if self._effect_sources() != self.effect_source_bindings:
            return None
        family = name.removeprefix('neyvia.').split('.')[0]
        aliases = MANUAL_ALIASES
        owning = 'neyvia-reference' if name == 'neyvia.mission.create' else aliases.get(family, family)
        if name in ADAPTIVE_WORK_TOOLS: owning = 'adaptive-work'
        if name.removeprefix('neyvia.') == 'workspace.patch': owning = 'tools-depth'
        if name == 'neyvia.view.transparency': owning = 'transparency'
        if name == 'neyvia.sidebar.policy': owning = 'neyvia'
        if procedure:
            prefix, _, procedure_id = procedure.rpartition('.')
            procedure = aliases.get(prefix, prefix) + '.' + procedure_id
        owner = procedure.rsplit('.', 1)[0] if procedure else owning
        bindings = self.manual_actions.get(name, [])
        if owner not in self.manual_documents:
            owners = {binding['manual'] for binding in bindings}
            owner = next(iter(owners)) if len(owners) == 1 else None
        def current(binding):
            if hashlib.sha256((REPO / binding["source"]).read_bytes()).hexdigest() != binding["sourceSha256"]:
                return False
            if hashlib.sha256((REPO / binding['artifact']).read_bytes()).hexdigest() != binding['artifactSha256']:
                return False
            versions = self.gateway.root / '.neyvia/manual-versions'
            pointer = versions / (binding['manual'] + '.json')
            if pointer.exists():
                current_sha = json.loads(pointer.read_text(encoding='utf-8'))['sha256']
                version = versions / binding['manual'] / (current_sha + '.json')
                if current_sha != binding['manualSha256'] or hashlib.sha256(version.read_bytes()).hexdigest() != current_sha:
                    return False
            return True
        owning_bindings = [binding for binding in bindings if binding['manual'] == owning]
        owning_binding = next((binding for binding in owning_bindings if current(binding)), None)
        if owning_bindings and owning_binding is None:
            return None  # An explicit workflow cannot bypass stale owner instructions.
        for binding in bindings:
            if binding['manual'] != owner or not current(binding):
                continue
            applicable = []
            def matches_step(expected, actual):
                if isinstance(expected, dict):
                    if not expected:
                        return actual == {}
                    if len(expected) == 1 and set(expected) & {'$input', '$path', '$result'}:
                        return True
                    return isinstance(actual, dict) and all(key in actual and matches_step(value, actual[key]) for key,value in expected.items())
                if isinstance(expected, list):
                    return isinstance(actual, list) and len(actual) == len(expected) and all(matches_step(a,b) for a,b in zip(expected,actual))
                return expected == actual
            for candidate in binding["procedures"]:
                if procedure and procedure != binding["manual"] + "." + candidate["id"]:
                    continue
                if any(key not in arguments and not (isinstance(value, dict) and set(value) & {'$input', '$path', '$result'})
                       or key in arguments and not matches_step(value, arguments[key])
                       for key,value in candidate['args'].items()):
                    continue
                applicable.append(candidate)
            if self._mutating(name, arguments) and not applicable:
                continue
            receipt = {key: binding[key] for key in ("manual", "source", "sourceSha256", "manualSha256", "chapter", "action", "tool")}
            if owning_binding:
                receipt['owningManual'] = {key:owning_binding[key] for key in ('manual','source','sourceSha256','manualSha256')}
            receipt.update(session=self.gateway.work_scope or "unscoped", actionIdentity=identity,
                           effectSourceSha256=self.effect_source_sha256,
                           effectSourceBindings=self.effect_source_bindings,
                           procedure=procedure or (binding["manual"] + "." + applicable[0]["id"] if applicable else None),
                           checkIds=sorted({row["check"] for row in applicable if row["check"]}),
                           status="admitted", usageId="manual-use-" + uuid.uuid4().hex)
            return receipt
        return None

    def record_manual_use(self, receipt):
        if receipt:
            from ..ui_command_bus import bus_for
            bus_for(self.gateway.root).emit("cl.manual.use", receipt)

    def action_output(self, name, output):
        """Resolve a gateway's metadata receipt for host checks, never as proof.

        The at-most-once gateway deliberately projects away native result data.
        CL needs the saved subject/hash to compare with a fresh owning observer.
        Only the exact registry receipt directory and matching tool are admitted.
        """
        from ..neyvia_manuals import checked_action_output
        return checked_action_output(self.gateway.native, name, output)

    def resolve_name(self, name):
        if name in self.gateway.native._specs:
            return name
        candidate = "neyvia." + name
        if candidate in self.gateway.native._specs:
            return candidate
        # Suite names are not silently converted to an arbitrary operation.
        raise ValueError("Unknown exact CL action: " + name)

    def describe(self, *, level=0, layer=None, chapter=None, name=None, primer=False):
        if self.lazy_manuals:
            self._ensure_manuals((name + '()') if name else '', layer=layer)
        if primer:
            if level != 0 or layer or chapter or name:
                raise ValueError("Primer is the standalone L0 context")
            return self.host.cold_start()
        if layer:
            return self.host.help(layer, level or 1)
        if name:
            layer = self.host.layer(name)
            return '\n'.join(line for line in self.host.help(layer, level or 1).splitlines()
                              if name.removeprefix('neyvia.') in line) + '\n'
        if level != 0:
            raise ValueError("Choose a layer for L1 or L2")
        return '\n'.join(self.host.index) + '\n'

    def _checks(self, name, arguments):
        if not self._mutating(name, arguments):
            if name == 'neyvia.manual.project':
                from .manual_projection_effects import checks_for
                return checks_for(self, name, arguments)
            return []
        from .effects import checks_for
        return checks_for(self, name, arguments)

    def _snapshot(self, name, args, previous=None, after=False):
        from .effects import snapshot_for, _file
        if after and name == 'neyvia.files.undo' and previous and previous.get('action'):
            operation = previous['action']
            path = operation.get('from') if operation['op'] == 'move' else operation['path']
            return {'action':None, 'restored':_file(self,args.get('path') or path)}
        return snapshot_for(self, name, args)
    def _observer_inputs(self, name, arguments):
        """Bind the native value check to the same freshly observed target."""
        if name != 'neyvia.cua.action' or arguments.get('tool') != 'set_value':
            return {}
        nested = arguments.get('args', {})
        token = nested.get('element_token')
        if not token or not isinstance(nested.get('value'), str):
            return {}
        for (observer, encoded), value in reversed(list(self.host.reads.items())):
            if observer != 'cua.inspect' or not isinstance(value, dict): continue
            element = next((row for row in value.get('elements', []) if row.get('element_token') == token), None)
            if element is not None:
                return {'window_id':json.loads(encoded)['window_id'],
                        'label':element.get('label',element.get('name','')), 'role':element.get('role',''), 'expected':nested['value']}
        return {}

    def bound_check(self, step, check, inputs):
        """Run exactly the authored procedure observer within the caller scope."""
        from ..neyvia_manuals import resolve, expect
        if self.scope is not None and check['tool'] not in self.scope:
            raise ValueError('Procedure observer is outside this adapter scope: ' + check['tool'])
        def verify(args, value, previous):
            # A later observer may reference any earlier saved procedure result.
            # Keep that environment and overlay the current step's result.
            results = dict(inputs)
            if step.get('save'): results[step['save']] = value
            observed = unwrap(self.gateway.call_native(check['tool'], resolve(check['args'], inputs, results, self.gateway.root)))
            return expect(observed, check['expect'], inputs, results, self.gateway.root)
        return {'name':step['check'], 'observer':True, 'check':verify}

    def default_goal(self, name, args):
        """Bind the authored simple-write check to the requested full UTF-8 bytes."""
        if name.startswith('neyvia.parallel.') and name != 'neyvia.parallel.state':
            # These procedures have an owning state observer and action-specific
            # effect checks. Bind its run before dispatch; start discovers its ID.
            if self.scope is not None and 'neyvia.parallel.state' not in self.scope:
                raise ValueError('Parallel goal needs neyvia.parallel.state in scopeTools; no action ran')
            if name not in self.contracts:
                return None
            identity = args.get('run')
            expression = (f'parallel.state(run={identity!r}).run.id == {identity!r}'
                          if identity else 'parallel.state().runs != None')
            return identity or 'parallel', expression
        if name != 'workspace.write' or len(args.get('content', '')) > 20000:
            return None
        if self.scope is not None and 'workspace.read' not in self.scope:
            raise ValueError('Simple-write goal needs workspace.read in scopeTools; no action ran')
        authored = self.contracts.get(name, {}).get('chapter', {}).get('checks', {}).get('persisted-hash')
        if not authored:
            return None
        from .integration import _goal
        check = deepcopy(authored)
        check['args'] = {'path':args['path']}
        check['expect']['value'] = hashlib.sha256(args['content'].encode('utf8')).hexdigest()
        path = Path(args['path'])
        path = (path if path.is_absolute() else self.gateway.root / path).resolve()
        subject = path.relative_to(self.gateway.root).as_posix()
        return subject, _goal(check)


    def _mutating(self, name, args):
        if name == "neyvia.agents.overview":
            return False  # cached observer; the read grants no agent control
        from .frontier_effects import readonly
        observed_readonly = readonly(name, args)
        if observed_readonly is not None:
            return not observed_readonly
        # Classification reads registered metadata, never runtime availability
        # (PDF/editor probes belong to the actual dispatch, not each signature).
        row = self.gateway.native._specs[name]
        if name.startswith("neyvia.mod.") or name == "neyvia.efficiency.laya_verify":
            # Installed mod manifests require an explicit mutability class.
            # Their verbs are extensible; a new read verb is still an observer.
            return row.mutability_class != "read"
        contract = self.contracts.get(name)
        readonly_verbs = {"list", "read", "search", "state", "stat", "get", "index", "load", "observe", "project", "validate", "now", "check", "inspect", "windows", "log", "wait", "verify", "status", "describe", "capabilities", "limits", "receipt", "receipts", "history", "downloads", "environment"}
        mutating = row.mutability_class not in {"read", "none"} or bool(contract and name.rsplit(".", 1)[-1] not in readonly_verbs)
        if row.mutability_class == "none" and not contract:
            # Legacy "none" does not attest that this operation has no effects.
            mutating = True
        if name == "neyvia.notes.folder" and not args.get("folder"):
            mutating = False
        return mutating

    def run(self, lines, *, action_id="", scope_tools=None):
        with self.lock, self._goal_bus().connection_scope():
            self.scope = set(scope_tools) if scope_tools is not None else None
            try:
                from .host import model_value
                goals = self._goal_bus().get('cl:task-goals:' + (self.gateway.work_scope or 'unscoped'), []) if self.lazy_manuals else []
                self._ensure_manuals(lines + '\n' + '\n'.join(goals))
                self._sync_task_goals()
                return model_value(self.host.execute(lines, action_id=action_id))
            finally:
                self._save_completion()
                self.scope = None
