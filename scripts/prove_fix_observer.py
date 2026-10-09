"""Real CL calls and Windows background value readback, scoped to disposable state."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('baseline', 'read', 'write', 'native', 'typed'), required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    os.environ.update(NEYVIA_COORDINATOR_AUTOSTART='0', NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_WATCHDOG_AUTOSTART='0')
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.neyvia_cua import service_for
    root = REPO / '.agent_control/fix-observer' / (args.phase + '-' + uuid.uuid4().hex)
    root.mkdir(parents=True)
    rows, checks, process, service, failure = [], {}, None, None, None
    gateway = NeyviaToolGateway(root, allow_mutations=True, allowed_mutation_tools={'workspace.write', 'neyvia.cua.action'}, permission_mode='full-access')
    def call(lines, selected=gateway):
        response = selected.call_native('neyvia.cl', {'lines':lines})
        rows.append({'lines':lines, 'response':response})
        return response
    def gate(name, passed):
        checks[name] = bool(passed)
        if not passed: raise RuntimeError('Failed live gate: ' + name)
    try:
        if args.phase == 'read':
            (root / 'valid.txt').write_text('reasonable phrase', encoding='utf8')
            valid = call('run workspace.read-and-confirm(path="valid.txt", phrase="reasonable")')
            gate('own_phrase_and_goal_pass', valid['ok'] and valid['results'][0]['checks'] == [{'name':'has-text','passed':True}, {'name':'G','passed':True}])
            wrong = call('run workspace.read-and-confirm(path="valid.txt", phrase="absent")')
            gate('missing_phrase_refused', not wrong['ok'])
            direct = call('workspace.read(path="valid.txt")')
            gate('plain_text_read_no_unrelated_predicates', direct['ok'] and not direct['results'][0]['checks'])
            missing = call('run workspace.read-and-confirm(path="absent.txt", phrase="reasonable")')
            gate('missing_file_refused', not missing['ok'])
            # Same transport reaches the ordinary typed manual runner too.
            manual = gateway.call_native('neyvia.manual.run', {'id':'workspace','chapter':'files','procedure':'read-and-confirm','inputs':{'path':'valid.txt','phrase':'reasonable'}})
            rows.append({'tool':'neyvia.manual.run','response':manual})
            gate('typed_manual_runner_same_phrase', manual['ok'] and manual['checks'][0]['passed'])
        if args.phase == 'typed':
            content = 'French: éàç\nexact UTF-8'
            for procedure, inputs in [('create-and-confirm', {'path':'typed.txt','content':content}),
                                      ('read-and-confirm', {'path':'typed.txt','phrase':'absent'})]:
                response = gateway.call_native('neyvia.manual.run', {'id':'workspace','chapter':'files',
                    'procedure':procedure, 'inputs':inputs})
                rows.append({'tool':'neyvia.manual.run', 'procedure':procedure, 'response':response})
                if procedure == 'create-and-confirm':
                    gate('typed_create_and_confirm', response['ok'] and response['status'] == 'completed' and response['checks'][0]['passed'])
                    gate('persisted_exact_utf8', (root/'typed.txt').read_bytes() == content.encode('utf8'))
                else:
                    gate('typed_missing_phrase_refused', not response['ok'])
        if args.phase == 'write':
            gate('unknown_mutation_actionable', 'G:' in call('notes.pin(path="absent.md")')['text'])
            initial = call('workspace.write(path="first.txt", content="French: éàç\\nexact UTF-8")')
            gate('first_write_without_model_goal', initial['ok'])
            gate('persisted_exact_bytes', (root/'first.txt').read_bytes() == 'French: éàç\nexact UTF-8'.encode('utf8'))
            done = call('done("saved")')
            gate('default_goal_observed_done', done['ok'] and 'workspace.read' in done['results'][0]['goalChecks'][0]['observed'])
            second = call('workspace.write(path="second.txt", content="second artifact")')
            gate('second_simple_write_goal_added', second['ok'])
            old_hash = hashlib.sha256((root/'first.txt').read_bytes()).hexdigest()
            replacement = call('workspace.write(path="first.txt", content="reviewed replacement", expectedSha256="'+old_hash+'")')
            gate('CAS_replacement_updates_default_goal',replacement['ok'] and call('done("both files")')['ok'])
            procedure = call('run workspace.create-and-confirm(path="procedure.txt", content="Manual French: éàç\\nsecond line")')
            gate('source_authored_create_procedure',procedure['ok'])
            boundary_content = 'é'*20000
            boundary = call('workspace.write(path="boundary.txt", content='+json.dumps(boundary_content)+')')
            gate('twenty_thousand_unicode_character_boundary',boundary['ok'] and (root/'boundary.txt').read_bytes()==boundary_content.encode('utf8'))
            oversize = call('workspace.write(path="oversize.txt", content='+json.dumps('x'*20001)+')')
            gate('larger_write_actionable_no_mutation',not oversize['ok'] and '20000' in oversize['text'] and not (root/'oversize.txt').exists())
            (root/'first.txt').write_text('another writer',encoding='utf8')
            tampered = call('done("stale")')
            gate('changed_source_refuses_done', not tampered['ok'] and any(not goal['passed'] and "first.txt" in str(goal['observations']) for goal in tampered['results'][0]['goalChecks']))
            (root/'keeper.txt').write_text('keep these bytes',encoding='utf8')
            overwrite = call('workspace.write(path="keeper.txt", content="unreviewed overwrite")')
            gate('existing_file_requires_CAS', not overwrite['ok'] and (root/'keeper.txt').read_text(encoding='utf8')=='keep these bytes')
            read_only = NeyviaToolGateway(root, allow_mutations=False)
            denied = call('workspace.write(path="denied.txt", content="no")', read_only)
            gate('read_only_grant_preserved', not denied['ok'] and not (root/'denied.txt').exists())
        if args.phase in {'native','baseline'}:
            framework = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319')
            binary = root/'FixObserverProbe.exe'
            source = root/'NativeProbe.cs'
            source.write_text((REPO/'tools/cua-driver-win/probe.cs').read_text(encoding='utf8').replace('var output = new Label { Text = "Waiting",',
                              'var output = new Label { AccessibleName = "Task input", Text = "Waiting",'),encoding='utf8',newline='\n')
            build = subprocess.run([str(framework/'csc.exe'),'/nologo','/target:winexe','/out:'+str(binary),str(source),
                                    '/reference:'+str(framework/'System.Windows.Forms.dll'),'/reference:'+str(framework/'System.Drawing.dll')],
                                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            gate('installed_dotnet_native_build',build.returncode == 0)
            state = root/'native-window'
            process = subprocess.Popen([str(binary),str(state)],creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic()+15
            while not state.exists() and time.monotonic()<deadline: time.sleep(.1)
            gate('native_window_opened', state.exists())
            window_id = int(state.read_text())
            service = service_for(root)
            session = service.new_session([str(binary)], {'chatId':'native','app':'neyvia'})
            windows = call('cua.windows()')
            window = next(alias for alias in gateway._cl_protocol.host.live_refs() if alias.startswith('w') and gateway._cl_protocol.host.refs[alias]['raw'].get('window_id') == window_id)
            goal = 'G: cua.verify('+window+', expect=[{"element":{"selector":{"role":"Edit","label_contains":"Task input"},"value_equals":"French: éàç"}}], timeout_ms=3000).status == "satisfied"'
            gate('authored_native_value_goal',call(goal)['ok'])
            observation = call('cua.inspect('+window+')')
            gate('native_tree_observed',observation['ok'])
            independent = service.native.request('inspect',{'windowId':str(window_id),'maxDepth':12,'maxNodes':2000})
            gate('real_duplicate_label_distinct_roles',len({e['role'] for e in independent['tree'] if e.get('name')=='Task input'})>=2)
            host = gateway._cl_protocol.host
            element = next(alias for alias in host.live_refs() if alias.startswith('e') and host.refs[alias]['value'].get('label') == 'Task input')
            before = service.native.request('status')
            mutation = 'cua.action(tool="set_value", args={"element":'+element+', "value":"French: éàç"})'
            if args.phase == 'native':
                literal = call('cua.action(tool="set_value", args={"element_token":"invented", "value":"wrong"})')
                gate('literal_native_token_refused',literal['status']=='refused')
                scoped = gateway.call_native('neyvia.cl',{'lines':mutation,'scopeTools':['neyvia.cua.action']})
                rows.append({'lines':mutation,'scopeTools':['neyvia.cua.action'],'response':scoped})
                gate('observer_scope_required_before_mutation',scoped['status']=='frontier')
                unchanged = service.native.request('inspect',{'windowId':str(window_id),'maxDepth':12,'maxNodes':2000})
                gate('denials_preserve_native_value',any(e.get('name')=='Task input' and e.get('role')=='Edit' and e.get('value')=='initial' for e in unchanged['tree']))
            changed = call(mutation)
            if args.phase == 'baseline':
                gate('original_frontier_reproduced',changed['status']=='frontier')
            else:
                gate('native_ref_action_and_automatic_observer',changed['ok'] and any(row.get('passed') for row in changed['results'][0].get('checks',[])))
                readback = service.native.request('inspect',{'windowId':str(window_id),'maxDepth':12,'maxNodes':2000})
                rows.append({'independentWindowsUIA':readback})
                gate('independent_native_exact_french_value',any(e.get('name')=='Task input' and e.get('value')=='French: éàç' for e in readback['tree']))
                gate('native_goal_done',call('done("value saved")')['ok'])
                call('cua.inspect('+window+')')
                stale = call(mutation)
                gate('stale_element_ref_refused',stale['status']=='stale')
                after = service.native.request('status')
                gate('foreground_and_cursor_preserved',before['foregroundWindowId']==after['foregroundWindowId'] and before['cursor']==after['cursor'])
                rows.append({'preservationBefore':before,'preservationAfter':after})
            service.request('end',{'sessionId':session['id']},owner=True)
    except Exception as exc:
        failure = str(exc)
    finally:
        if service: service.shutdown()
        if process and process.poll() is None:
            process.terminate(); process.wait(timeout=10)
        receipt = {'schema':'neyvia.fix.observer.real-calls.v1','phase':args.phase,'root':str(root),'allPassed':bool(checks) and all(checks.values()) and failure is None,
                   'checks':checks,'error':failure,'calls':rows,'boundary':'Production CL gateway and typed manual runner; native phase uses real Windows UI Automation and pinned MIT Cua runtime against an owned background WinForms application. No browser, public release or remote PC claim.'}
        args.receipt.parent.mkdir(parents=True,exist_ok=True)
        args.receipt.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
    print(json.dumps({'allPassed':receipt['allPassed'],'checks':checks,'error':failure,'receipt':str(args.receipt)},ensure_ascii=True))
    return int(not receipt['allPassed'])


if __name__ == '__main__': raise SystemExit(main())
