"""Real hidden system-Python commands, exact terminal effects and corrupt receipt refusal."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys
import time

from fixcl_verify import REPO, environment


def add_procedure():
    from grant_agent.cl.manuals import cl_to_manual, _source_lines
    source = REPO/'manuals/cl/workspace.cl'
    artifact = REPO/'manuals/workspace.manual.json'
    text = source.read_text(encoding='utf-8')
    data = cl_to_manual(text)
    if data != json.loads(artifact.read_bytes()):
        raise ValueError('Existing workspace canonical source/artifact mismatch')
    chapter = data['chapters']['terminal']
    key = 'execute-scoped-command'
    if key in chapter['procedures']:
        return
    schema = data['schemas']['terminal.exec']
    procedure = {'goal':'Execute one explicitly permitted bounded local command; fresh command completion and authored observer G must both pass',
        'inputs':schema,'steps':[{'action':'terminal.exec',
            'args':{field:{'$input':field} for field in schema['properties']},'save':'execution'}]}
    # Optional inputs cannot be referenced by a compiled procedure unless the
    # caller supplies them. This procedure exposes every field explicitly.
    procedure['inputs'] = {**schema,'required':list(schema['properties'])}
    procedure = json.loads(json.dumps(procedure,sort_keys=True))
    chapter['procedures'][key] = procedure
    metadata = json.loads(next(line[len('-- @manual '):] for line in text.splitlines() if line.startswith('-- @manual ')))['tool_metadata']
    additions = ['-- @record '+json.dumps({'chapter':'terminal','section':'procedures','key':key,'data':procedure},sort_keys=True,separators=(',',':'))]
    additions += _source_lines('procedures',key,procedure,chapter,data['schemas'],data['id'],metadata,version='1.1')
    marker = '\nL workspace.terminal v1 -- '
    start = text.index(marker)+1
    end = text.find('\nL workspace.',start+len(marker))
    if end < 0:
        end = len(text)
    text = text[:end].rstrip('\n')+'\n'+'\n'.join(additions)+'\n'+text[end:].lstrip('\n')
    if cl_to_manual(text) != data:
        raise ValueError('Terminal procedure does not round-trip exactly')
    source.write_text(text,encoding='utf-8',newline='\n')
    artifact.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--prepare-manual',action='store_true')
    args = parser.parse_args()
    if args.port != 48822:
        parser.error('This probe owns explicit port 48822')
    if args.prepare_manual:
        add_procedure()
        print('Workspace terminal manual prepared')
        return 0
    root = REPO/'.agent_control/proofs'/('FIXCL2-terminal-'+str(time.time_ns()))
    root.mkdir(parents=True)
    environment(root,args.port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL',None)
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(root); install_hidden_subprocess_default(); prepare_broker_fixture(root)
    good = "from pathlib import Path; Path('proof.log').write_text('actual terminal effect',encoding='utf-8'); print('FIXCL2 real stdout')"
    nonzero = "import sys; print('FIXCL2 nonzero stdout'); sys.exit(7)"
    calls = []
    commands = [[str(Path(sys.executable).resolve()), '-c', code] for code in (good, nonzero)]
    windows_commands = {subprocess.list2cmdline(command): command for command in commands}
    def audit(event, arguments):
        if event == 'subprocess.Popen':
            command = arguments[1]
            # Windows audits the already quoted command line, POSIX the argv.
            if isinstance(command, str):
                command = windows_commands.get(command)
            if command not in commands:
                raise PermissionError('Terminal proof admits only its exact two hidden Python commands')
            calls.append(list(command))
        if event in {'socket.bind','socket.connect'}:
            address = arguments[1]
            if isinstance(address,tuple) and (address[0] not in {'127.0.0.1','localhost','::1'} or address[1] != args.port):
                raise PermissionError('Terminal proof admits only its assigned port')
    sys.addaudithook(audit)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    (root/'proof.log').write_bytes(b'original')
    source_hashes = sources()
    gateway = NeyviaToolGateway(root,allow_mutations=True,action_scope='FIXCL2-terminal',
        permission_mode='full-access',allowed_mutation_tools={'terminal.exec'})
    proof = {'schema':'neyvia.FIXCL2.terminal.v1','root':str(root),'port':args.port,
        'boundary':'Actual hidden system-Python process and integrity-checked completed native action; file bytes independently establish requested effect.',
        'sourceHashesAtStart':source_hashes,'checks':{},'transcripts':{}}
    fields = {'command':good,'shell':'python','cwd':str(root),'timeoutMs':5000,'maxOutputChars':1000}
    lines = 'G: workspace.read(path="proof.log").content == "actual terminal effect"\nterminal.exec('+','.join(key+'='+json.dumps(value) for key,value in fields.items())+')\ndone()'
    protocol = Protocol(gateway)
    completed = protocol.run(lines,action_id='owned-terminal')
    proof['transcripts']['terminal'] = completed
    proof['checks']['actualCommandAndExactFile'] = completed.get('ok') is True and (root/'proof.log').read_bytes() == b'actual terminal effect' and len(calls)==1
    rows = completed.get('text','').splitlines()
    proof['checks']['typedTerminalProjection'] = all(any(line.startswith('E terminal-command ') and '"'+field+'"' in line for line in rows) for field in ('command','exitCode','stdout','stderr'))
    replay = protocol.run(lines,action_id='owned-terminal')
    proof['transcripts']['replay'] = replay
    proof['checks']['sameIdentityNeverExecutesAgain'] = replay.get('ok') is True and len(calls)==1
    recovered = Protocol(gateway).run(lines, action_id='owned-terminal')
    proof['transcripts']['freshInterpreterReplay'] = recovered
    proof['checks']['freshInterpreterReplayNeverExecutesAgain'] = recovered.get('ok') is True and len(calls)==1
    action_record = gateway.actions._path('owned-terminal:1')
    result_path = action_record.with_suffix('.result')
    original = result_path.read_bytes()
    result_path.write_bytes(b'{"ok":true,"toolResult":{"stdout":"invented"}}')
    corrupted = protocol.completion()
    proof['transcripts']['corruptedResult'] = corrupted
    proof['checks']['changedReceiptRefusesCompletion'] = corrupted.get('status')=='incomplete'
    result_path.write_bytes(original)
    (root/'proof.log').write_bytes(b'other writer')
    proof['checks']['changedTaskEffectRefusesCompletion'] = protocol.completion()['status']=='incomplete'
    failed = Protocol(gateway)
    failure = failed.run('G: time.now()["unixSeconds"] > 0\nterminal.exec(command='+json.dumps(nonzero)+',shell="python",cwd='+json.dumps(str(root))+')\ndone()',action_id='nonzero-terminal')
    proof['transcripts']['nonzero'] = failure
    proof['checks']['realNonzeroBlocksDone'] = not failure.get('ok') and not failed.run('done()')['ok'] and len(calls)==2
    limited = NeyviaToolGateway(root,allow_mutations=True,permission_mode='workspace',allowed_mutation_tools={'terminal.exec'})
    blocked = limited.call_native('terminal.exec',fields,action_id='workspace-terminal')
    proof['transcripts']['workspaceDenied'] = blocked
    proof['checks']['workspaceModeNeverLaunchesCommand'] = blocked.get('status')=='approval_required' and len(calls)==2
    from grant_agent.verified_operations import VerifiedOperationStore
    callback_count = root/'callback-count.txt'
    callback_count.write_bytes(b'0')
    def uncertain_effect():
        callback_count.write_bytes(str(int(callback_count.read_bytes()) + 1).encode())
        raise ValueError('FIXCL2 deliberate effect error')
    store = VerifiedOperationStore(root, 'FIXCL2-callback')
    uncertainty = store.execute('one-effect', 'fixture.counter', authority=True, effect=uncertain_effect)
    replay_uncertainty = store.execute('one-effect', 'fixture.counter', authority=True, effect=uncertain_effect)
    proof['transcripts']['uncertainCallback'] = uncertainty
    proof['transcripts']['uncertainCallbackReplay'] = replay_uncertainty
    proof['checks']['callbackBodyErrorPreserved'] = uncertainty.get('status') == 'unknown_side_effects' and 'FIXCL2 deliberate effect error' in uncertainty.get('error','')
    proof['checks']['uncertainEffectNeverRetried'] = replay_uncertainty.get('status') == 'unknown_side_effects' and callback_count.read_bytes() == b'1'
    proof['executedCommands'] = calls
    proof['sourceHashesAtEnd'] = sources()
    proof['checks']['sourceUnchanged'] = proof['sourceHashesAtEnd']==source_hashes
    output = REPO/'scripts/evidence/FIXCL2-terminal.json'
    output.write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'receipt':str(output),'checks':proof['checks']}))
    return 0 if all(proof['checks'].values()) else 1


def sources():
    paths = list((REPO/'src/grant_agent/cl').glob('*.py'))
    paths += [REPO/'src/grant_agent/neyvia_agent.py',REPO/'src/grant_agent/native_commands.py',REPO/'src/grant_agent/verified_operations.py',
        REPO/'manuals/cl/workspace.cl',REPO/'manuals/workspace.manual.json']
    gateway = REPO/'src/grant_agent/neyvia_gateway.py'
    if gateway.exists():
        paths.append(gateway)
    return {str(path.relative_to(REPO)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


if __name__ == '__main__':
    raise SystemExit(main())
