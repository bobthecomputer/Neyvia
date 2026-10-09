"""Execute one source-bound manual journey through an owned headless web page."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

from c8_journey import Journey, UnsupportedRoute, write


class ToolFailure(RuntimeError):
    def __init__(self, tool, reply):
        self.tool, self.reply = tool, reply
        super().__init__(tool + ': ' + json.dumps(reply, ensure_ascii=False))


class Waiting(RuntimeError):
    pass


def procedure_request(row, manual, inputs, root):
    """Bind source-authored postconditions before the real CL procedure runs."""
    from grant_agent.neyvia_manuals import resolve
    from grant_agent.cl.integration import _goal
    from grant_agent.cl import effects
    from c8_journey import _readonly_tool
    chapter = manual['chapters'][row['chapter']]
    scope, goals = set(), []
    for contract in row.get('checkContracts', {}).values():
        try:
            resolved = resolve(contract, inputs, {}, root)
        except (KeyError, TypeError, ValueError) as error:
            raise UnsupportedRoute('Postcondition requires a result not yet observed: ' + row['id']) from error
        goals.append(_goal(resolved))
        scope.add(contract['tool'])
    # These input-bound local records have stronger owner effect contracts:
    # exact revision/event persistence and conservation of unrelated fields.
    # The explicit G names the requested content; the host verifies all of
    # those owning invariants independently before it can finish.
    if not goals and row['manual'] == 'adaptive-work':
        path = '.agent_control/adaptive_work/' + inputs['workId'] + '.json'
        goals = [repr(json.dumps(inputs['text'])) + ' in workspace.read(path=' + repr(path) + ').content']
        scope.add('workspace.read')
    elif not goals and row['manual'] == 'creative-records':
        from grant_agent.cl.creative_effects import _identity
        identity = _identity(inputs['workId'])
        if row['procedure'] == 'record-situation-define':
            from grant_agent.situation_interface import digest
            path = '.agent_control/situations/' + digest(identity)[:24] + '/state.json'
            intended = inputs['task']
        elif row['procedure'] == 'record-attention-create':
            path = '.agent_control/contextual_learning/' + identity + '-attention.json'
            intended = inputs['arguments']['variant_input']
        else:
            raise UnsupportedRoute('Local effect requires its own input-bound observer goal: ' + row['id'])
        goals = [repr(json.dumps(intended)) + ' in workspace.read(path=' + repr(path) + ').content']
        scope.add('workspace.read')
    if not goals:
        raise UnsupportedRoute('No source-authored or owning input-bound postcondition: ' + row['id'])

    class ScopeGateway:
        def __init__(self):
            self.root = root
        def call_native(self, name, arguments):
            raise UnsupportedRoute('Scope derivation never dispatches tools')

    probe = type('ScopeProbe', (), {'scope': None, 'gateway': ScopeGateway()})()
    for step in row['steps']:
        action = chapter['actions'][step['action']]
        name = action['tool']
        scope.add(name)
        try:
            arguments = resolve(step['args'], inputs, {}, root)
        except (KeyError, TypeError, ValueError) as error:
            raise UnsupportedRoute('Effect scope requires a result not yet observed: ' + row['id']) from error
        if not _readonly_tool(name, arguments):
            checks = effects.checks_for(probe, name, arguments)
            if not checks:
                raise UnsupportedRoute('CL has no executable owning effect goal for ' + name)
            scope.update(check['observerTool'] for check in checks if check.get('observerTool'))
    scope.update(tool.removeprefix('neyvia.') for tool in list(scope))
    layer = 'cua' if row['manual'] == 'computer-use' else row['manual']
    parameters = ', '.join(f'{key}:{json.dumps(value, ensure_ascii=False, separators=(",", ":"))}' for key, value in inputs.items())
    procedure = f'{layer}.{row["procedure"]}({parameters})'
    return '\n'.join('G: ' + goal for goal in goals) + f'\nrun {procedure}\ndone(summary:"C8 source-bound procedure {row["id"]}")', sorted(scope), procedure


class ManualJourney(Journey):
    def tool(self, name, arguments):
        # This is the product's authenticated web tool path, using the page's
        # own session and origin. No private Python dispatch replaces the call.
        row = self.page.evaluate("""async ({tool, arguments: args}) => {
          const command = tool.startsWith('backend:') ? tool.slice(8) : null;
          const native = !tool.startsWith('neyvia.');
          const response = await fetch(native ? '/api/backend' : '/api/ui/tools/call', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify(command ? {command,payload:args} : native ? {command:'call_native_tool_command',payload:{tool,arguments:args}} : {tool, arguments:args})});
          return {httpStatus:response.status, bodyText:await response.text()};
        }""", {"tool": name, "arguments": arguments})
        # JSON.parse in the renderer rounds nanosecond timestamps past 2**53.
        # Preserve the actual wire text and decode it in Python, retaining the
        # same authenticated browser request and exact source receipt values.
        wire = row.pop('bodyText')
        raw = self.directory / f'call-{len(self.calls):03d}.body.json'
        raw.write_bytes(wire.encode('utf-8'))
        row.update(body=json.loads(wire), bodyWireProof=str(raw),
                   bodyWireSha256=hashlib.sha256(raw.read_bytes()).hexdigest())
        path = write(self.directory / f'call-{len(self.calls):03d}.json',
                     {"target": self.args.candidate_url, "tool": name, "arguments": arguments, **row})
        self.calls.append({"tool": name, "arguments": arguments, "receipt": str(path),
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **row})
        body = row['body']
        data = body.get('data', {})
        if name == 'neyvia.settings.propose' and self.args.binding.get('ownerApproval'):
            from grant_agent.neyvia_manuals import unwrap
            requested = data.get('result', data)
            if requested.get('status') == 'approval_required':
                from c8e_prerequisites import owner
                approved = owner(self, '/api/ui/approve', {'id': requested['approvalId']})
                return approved.get('data', approved)
        requested = data.get('result', data)
        if data.get('ok') is False and data.get('status') == 'approval_required' and name in self.args.binding.get('ownerApprove', []):
            if name not in {'neyvia.image.export', 'neyvia.nightshift.resources', 'neyvia.settings.propose', 'neyvia.files.trash'}:
                raise PermissionError('C8e owner grant is not an authored disposable action')
            approval = self.page.evaluate("""async id => {const r=await fetch('/api/ui/approve',
                {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
                return {httpStatus:r.status,body:await r.json()}}""", requested['approvalId'])
            proof = write(self.directory / f'call-{len(self.calls):03d}.json',
                          {'target': self.args.candidate_url, 'tool': 'owner.approve', 'arguments': {'id': requested['approvalId']}, **approval})
            self.calls.append({'tool': 'owner.approve', 'arguments': {'id': requested['approvalId']}, 'receipt': str(proof),
                               'sha256': hashlib.sha256(proof.read_bytes()).hexdigest(), **approval})
            if approval['httpStatus'] != 200 or not approval['body'].get('ok'):
                raise ToolFailure('owner.approve', approval)
            approved = approval['body'].get('data', {})
            if name == 'neyvia.settings.propose' and 'data' in approved:
                return approved['data']
            return self.tool(name, arguments)
        if row['httpStatus'] != 200 or not body.get('ok') or data.get('ok') is False:
            raise ToolFailure(name, row)
        from grant_agent.neyvia_manuals import unwrap
        return unwrap(data)

    def _effect_action(self, name, arguments, *, receipt_name):
        raise UnsupportedRoute('C8 mutations must run through the source-bound CL procedure, not a raw tool call: ' + name)

    def execute(self):
        from grant_agent.neyvia_manuals import get_manual, resolve
        from jsonschema import Draft202012Validator
        binding = self.args.binding
        row = binding['row']
        self.calls, self.checks, self.step_results = [], [], {}
        inputs = expand(binding.get('inputs', {}), self.args)
        root = Path(self.args.state_root)
        _, digest, tester_manual = get_manual(row['manual'])
        manual = binding['manual']
        self.observe()
        chapter = manual['chapters'][row['chapter']]
        # A setup read is safe and its returned shape remains tied to the CL
        # action. Any setup mutation needs its own authored P procedure; never
        # turn a callback into an alternate CL host.
        setup_actions = []
        for entry in binding.get('setup', []):
            arguments = resolve(expand(entry.get('args', {}), self.args), inputs, self.step_results, root)
            action = next((item for item in chapter['actions'].values() if item.get('tool') == entry['tool']), None)
            if action is None:
                raise ValueError('Setup action is absent from the pinned CL chapter')
            Draft202012Validator(manual['schemas'][action['schema']]).validate(arguments)
            from c8_journey import _readonly_tool
            if not _readonly_tool(action['tool'], arguments):
                raise UnsupportedRoute('Setup mutation needs its own authored CL procedure: ' + action['tool'])
            setup_actions.append((entry, action, arguments))
        for entry, action, arguments in setup_actions:
            value = self.tool(action['tool'], arguments)
            Draft202012Validator(action['returns']).validate(value)
            self.step_results[entry['save']] = value
        for field, reference in binding.get('dynamicInputs', {}).items():
            inputs[field] = resolve(reference, inputs, self.step_results, root)
        Draft202012Validator(row['inputs']).validate(inputs)

        lines, scope, procedure = procedure_request(row, manual, inputs, root)

        # Candidate inventory is read through the authenticated candidate
        # session; a different manual hash blocks before the source procedure.
        inventory_result = self.tool('neyvia.inception.inventory', {})
        if inventory_result.get('manualHashes', {}).get(row['manual']) != row['sourceHash']:
            raise UnsupportedRoute('Candidate CL manual hash differs from the pinned binding')
        cl_result = self.tool('neyvia.cl', {'lines': lines, 'scopeTools': scope,
                                             'actionId': 'c8-' + self.args.run_id + '-' + hashlib.sha256(row['id'].encode()).hexdigest()[:12]})
        results = cl_result.get('results', []) if isinstance(cl_result, dict) else []
        if cl_result.get('ok') is not True or not results:
            raise ToolFailure('neyvia.cl', cl_result)
        for ordinal, result in enumerate(results):
            for contract in result.get('checks', []):
                passed = contract.get('passed')
                self.checks.append({'id': f'cl:{ordinal}:{contract.get("name", "check")}',
                                    'passed': passed is True, 'fresh': True, 'observed': contract})
            goal = result.get('goal', {})
            for contract in goal.get('effects', []):
                self.checks.append({'id': f'cl:{ordinal}:{contract.get("name", "effect")}',
                                    'passed': contract.get('passed') is True,
                                    'fresh': contract.get('observed') is True, 'observed': contract})
            for contract in result.get('goalChecks', []):
                self.checks.append({'id': f'cl:{ordinal}:{contract.get("name", "goal")}',
                                    'passed': contract.get('passed') is True,
                                    'fresh': contract.get('observed') is True, 'observed': contract})
        if not self.checks or any(check['passed'] is not True for check in self.checks):
            raise ToolFailure('neyvia.cl-observers', {'checks': self.checks, 'response': cl_result})
        self.page.reload(wait_until='domcontentloaded')
        self.page.locator('.nx-root').wait_for(timeout=45000)
        after = self.observe()
        # Effect witnesses may restore preferences with a real final reload.
        # Wait for the actual shell, then capture its final state rather than
        # mistaking the boot document for a completed rendered journey.
        self.page.locator('.nx-root .nx-os').wait_for(timeout=45000)
        completed = self.observe()
        # A completed tool procedure is proven within the shared web command
        # boundary. Render-specific goals remain separate from this boundary.
        return {'inputs': inputs, 'decisions': binding.get('decisions', {}),
                'checks': self.checks, 'stepResults': self.step_results,
                'testerManualHash': digest, 'candidateManualHash': row['sourceHash'],
                'goals': [{'passed': bool(self.checks) and all(c['passed'] for c in self.checks),
                           'observed': {'completedSteps': len(results),
                                        'freshCheckCount': len(self.checks), 'url': after['url'],
                                        'candidateManualHash': inventory_result['manualHashes'][row['manual']],
                                        'procedureResult': results, 'revisionAfterReload': after['revision'],
                                        'revisionAfterEffects': completed['revision'],
                                        'boundary': 'Manual procedure through authenticated web tool bus; rendered shell reload observed'}}],
                'clProcedure': {'procedure': procedure, 'scopeTools': sorted(scope), 'result': cl_result},
                'artifacts': [self.screenshot()]}

    def check(self, identity, contract, inputs, root):
        from grant_agent.neyvia_manuals import resolve, expect
        pdf_load = (contract['tool'] == 'neyvia.pdf.state'
                    and self.args.binding.get('id', '').endswith('/verify-visible-highlight'))
        deadline = time.monotonic() + (60 if identity == 'terminal-open' else 45 if pdf_load else 0)
        while True:
            observed = self.tool(contract['tool'], resolve(contract['args'], inputs, self.step_results, root))
            passed = expect(observed, contract['expect'], inputs, self.step_results, root)
            loading = pdf_load and (observed.get('state') or {}).get('status') == 'loading'
            if time.monotonic() >= deadline:
                passed = passed and not loading
                break
            if not loading and (passed or identity != 'terminal-open'):
                break
            time.sleep(.2)
        self.checks[:] = [check for check in self.checks if check['id'] != identity]
        self.checks.append({'id': identity, 'passed': passed, 'observed': observed, 'contract': contract})
        if not passed:
            raise ToolFailure(contract['tool'], {'goalCheck': identity, 'expected': contract['expect'], 'observed': observed})


def expand(value, args):
    if isinstance(value, str):
        if value == '${port}':
            from urllib.parse import urlsplit
            return urlsplit(args.candidate_url).port
        return value.replace('${root}', args.state_root).replace('${url}', args.candidate_url).replace('${peerUrl}', getattr(args, 'binding', {}).get('peerUrl', ''))
    if isinstance(value, dict):
        return {key: expand(item, args) for key, item in value.items()}
    if isinstance(value, list):
        return [expand(item, args) for item in value]
    return value


def classify(error, binding_id=None):
    if (isinstance(error, ToolFailure) and error.tool == 'defining-effect'
            and error.reply.get('missingPrerequisite')):
        return 'environment'
    text = str(error).lower()
    # These refusals name absent authentic runtime context. They do not prove
    # a product defect and must not be repaired with invented run identities.
    missing_context = {
        'neyvia.autopilot.get': 'runid must be a returned autopilot identity',
        'neyvia.conductor.get': 'invalid harness job id.',
        'neyvia.conductor.plan': 'configure planner, executor and verifier routing profiles first',
        'neyvia.mobile.build': 'android build tools are missing on this pc.',
        'neyvia.watch.create': 'that run was not found.',
    }
    if isinstance(error, ToolFailure) and missing_context.get(error.tool, '\0') in text:
        return 'environment'
    if (binding_id == 'neyvia-reference/proactivity/verify-retained-status'
            and isinstance(error, ToolFailure) and error.tool == 'neyvia.watch.list'
            and error.reply.get('goalCheck') == 'selected-id'
            and error.reply.get('observed', {}).get('watches') == []):
        return 'environment'
    environmental = ('scope', 'permission', 'credential', 'not installed', 'unavailable',
                     'no receipt', 'missing receipt', 'no latest', 'not configured', 'no such file',
                     'browser engine', 'no active', 'no live', 'not found: receipt', 'not ready',
                     'connection refused', 'download', 'driver', 'missing dependency',
                     'codex visual extraction could not start')
    if isinstance(error, Waiting):
        return 'environment'
    if any(word in text for word in environmental):
        return 'environment'
    if isinstance(error, (KeyError, ValueError)) or 'validationerror' in type(error).__name__.lower():
        return 'journey bug'
    if 'timeout' in type(error).__name__.lower():
        return 'environment'
    return 'product bug'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stable-source', 'candidate-url', 'run-id', 'journey', 'output', 'state-root'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    envelope = json.load(sys.stdin)
    args.binding, args.session_cookies = envelope['binding'], envelope['cookies']
    import os
    if os.environ.get('NEYVIA_C8H_TRACE_THREADS') == '1':
        import faulthandler
        faulthandler.dump_traceback_later(30, repeat=False)
    from c8_scope import install
    install()
    started = time.time()
    worker = None
    result = {'id': args.binding['id'], 'sourceHash': args.binding['sourceHash'],
              'journey': args.journey, 'startedAt': started, 'status': 'failed', 'executionMode': 'headless'}
    try:
        if args.journey in {'notes', 'settings'}:
            worker = Journey.__new__(Journey)
            worker.__init__(args)
            result.update(worker.run())
        else:
            worker = ManualJourney.__new__(ManualJourney)
            worker.__init__(args)
            result.update(worker.execute())
        result['status'] = 'passed' if all(c['passed'] for c in result.get('checks', []) + result.get('goals', [])) else 'failed'
        if result['status'] == 'failed':
            result.update(error='Authored manual goal check failed', failureClassification='product bug')
        if worker.page_errors:
            raise RuntimeError('Candidate page raised an unhandled error: ' + str(worker.page_errors))
    except Waiting as error:
        native = args.binding['nativeOnly']
        result.update(status='waiting', waitingFor='C11', waitingStep=native['step'], error=str(error), failureClassification='environment')
    except Exception as error:
        result.update(status='failed', error=str(error), failureClassification=classify(error, args.binding['id']), traceback=traceback.format_exc())
    finally:
        if worker:
            if args.binding.get('videoFixture'):
                from PIL import Image
                frames = []
                for path in (Path(args.state_root) / '.neyvia/perception-video').glob('frame-*/frame.png'):
                    with Image.open(path) as image:
                        frames.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                       'size': list(image.size), 'format': image.format})
                result['prerequisiteEvidence'] = {'productionDecodedFrames': frames,
                    'boundary': 'Actual production FFmpeg stage before the retained visual transport refusal; no visual interpretation proof'}
            result.update(t18=getattr(worker, 't18', []), t16=[], checks=result.get('checks', getattr(worker, 'checks', [])),
                          calls=getattr(worker, 'calls', []), currentStep=getattr(worker, 'current_step', None),
                          pageErrors=getattr(worker, 'page_errors', []))
            if getattr(worker, 'effect_evidence', None) is not None:
                result['effectEvidence'] = worker.effect_evidence
            if hasattr(worker, 'page') and not worker.page.is_closed():
                try:
                    result.setdefault('artifacts', [worker.screenshot('final-' + result['status'])])
                except Exception as error:
                    result['captureError'] = str(error)
            try:
                worker.close()
            except Exception as error:
                result['cleanupError'] = str(error)
                if result['status'] == 'passed':
                    result.update(status='failed', error='Owned browser cleanup failed: ' + str(error), failureClassification='environment')
        result.update(finishedAt=time.time(), durationMs=round((time.time() - started) * 1000))
        write(Path(args.output) / 'result.json', result)
    print(json.dumps({key: result.get(key) for key in ('id', 'status', 'failureClassification', 'error', 'durationMs')}), flush=True)
    return 0 if result['status'] in {'passed', 'waiting'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
