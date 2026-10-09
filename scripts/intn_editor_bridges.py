"""Exercise real project-scoped editor bridges in hidden batch processes."""
from pathlib import Path
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
import argparse
import hashlib
import ctypes
from urllib.request import Request, build_opener, HTTPCookieProcessor, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(r'D:\NeyviaRuns\INTN\editors')
PORT, WS = 48877, 48878
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
UNITY = Path(r'C:\Program Files\Unity\Hub\Editor\6000.6.4f1\Editor\Unity.exe')
BLENDER = Path(r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe')
GODOT = Path(r'C:\Users\user\AppData\Local\Microsoft\WinGet\Packages\GodotEngine.GodotEngine_Microsoft.Winget.Source_8wekyb3d8bbwe\Godot_v4.7.2-stable_win64_console.exe')


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def main():
    global OUT, PORT, WS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', default='current')
    parser.add_argument('--build-dir', type=Path, default=Path(r'D:\NeyviaRuns\INTN\build-c13'))
    parser.add_argument('--engines', default='blender,godot,unity')
    parser.add_argument('--debug-threads', action='store_true')
    parser.add_argument('--local-small-state', action='store_true', help='Keep small runtime databases and bytecode in this worktree; projects and proof output remain on D')
    parser.add_argument('--project-root', type=Path, help='Reuse an owned D:\\NeyviaRuns\\INTN\\editors project with its existing import cache')
    parser.add_argument('--backend-port', type=int, choices=range(48871,48890), default=PORT)
    parser.add_argument('--bridge-port', type=int, choices=range(48871,48890), default=WS)
    parser.add_argument('--unity-probe-timeout', type=int, default=900)
    parser.add_argument('--unity-editor-probe', type=Path, help='Reuse a successful owned editor probe after verifying its log and project')
    options = parser.parse_args()
    PORT, WS = options.backend_port, options.bridge_port
    if PORT == WS:
        parser.error('Backend and bridge require separate owned ports')
    selected = options.engines.split(',')
    if not selected or len(set(selected)) != len(selected) or set(selected) - {'blender', 'godot', 'unity'}:
        parser.error('Select unique native engines: blender,godot,unity')
    label = options.label
    if not label.replace('-', '').isalnum():
        parser.error('Invalid run label')
    OUT = OUT / label
    OUT.mkdir(parents=True, exist_ok=True)
    project_root = options.project_root.resolve() if options.project_root else OUT
    if not project_root.is_relative_to(Path(r'D:\NeyviaRuns\INTN\editors').resolve()):
        parser.error('Reusable projects must stay under the integrator-owned editor run folder')
    state = ROOT / '.agent_control/INTN/editor-state' / label if options.local_small_state else OUT / 'backend-state'
    cache = ROOT / '.agent_control/INTN/bytecode' / ('native-' + label) if options.local_small_state else Path(r'D:\NeyviaRuns\INTN\bytecode')
    state.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ('TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'API_KEY', 'AUTH_FILE'))}
    project_scope = OUT if project_root == OUT else OUT.parent
    env.update(NEYVIA_WEB_PORT=str(PORT), NEYVIA_GAMEDEV_WS_PORT=str(WS), NEYVIA_GAMEDEV_WORKSPACE=str(project_scope),
        NEYVIA_GAMEDEV_UNITY=str(UNITY), NEYVIA_GAMEDEV_GODOT=str(GODOT), NEYVIA_GAMEDEV_BLENDER=str(BLENDER),
        NEYVIA_MOBILE_PROBE_DEVICES='0', NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0', NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_RUNTIME_AUTO_UPDATE='0',
        FLUXIO_LOCAL_SESSION_BOOTSTRAP='1', PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1', PYTHONFAULTHANDLER='1', PYTHONPATH=str(ROOT / 'src'),
        PYTHONPYCACHEPREFIX=str(cache), NEYVIA_PROVISIONING_ROOT=str(state / 'provisioning'), NEYVIA_UI_STATE_ROOT=str(state),
        TIKTOKEN_CACHE_DIR=r'D:\NeyviaRuns\INTN\python\tokenizer-rerun\tokenizer-cache')
    # Backend homes are disposable. Editor child homes remain native: Unity owns
    # its existing sign-in; this runner never reads or copies its licence data.
    backend_env = env.copy()
    for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'HERMES_HOME', 'TEMP', 'TMP'):
        folder = OUT / 'backend-home' / key.lower()
        folder.mkdir(parents=True, exist_ok=True)
        backend_env[key] = str(folder)
    processes, streams = [], []
    private_name = 'Neyvia-INTN-' + uuid.uuid4().hex
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.CreateDesktopW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    user32.CreateDesktopW.restype = ctypes.c_void_p
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]
    user32.CloseDesktop.restype = ctypes.c_int
    desktop = user32.CreateDesktopW(private_name, None, None, 0, 0x01FF, None)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    report = {'schema': 'neyvia.intn.native-editor-roundtrip.v1', 'started': time.time(), 'ports': [PORT, WS], 'results': {},
              'runtimeStateRoot':str(state), 'bytecodeRoot':str(cache), 'largeOutputsRoot':str(OUT), 'projectRoot':str(project_root),
              'privateDesktop':private_name, 'desktopSwitchPerformed':False}
    sources = [*sorted((ROOT / 'scripts/gamedev').rglob('*.cs')),
               *sorted((ROOT / 'scripts/gamedev').rglob('*.py')),
               *sorted((ROOT / 'scripts/gamedev').rglob('*.gd')),
               ROOT / 'src/grant_agent/neyvia_gamedev.py', ROOT / 'src/grant_agent/cl/gamedev_effects.py',
               ROOT / 'src/grant_agent/cl/host.py', ROOT / 'src/grant_agent/cl/protocol.py']
    sources = sorted(set([*sources, *sorted((ROOT / 'src/grant_agent/cl').glob('*.py')),
        ROOT / 'manuals/cl/game-dev.cl', ROOT / 'config/fixcl_manual_cache.json', Path(__file__).resolve()]))
    report['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    report['sourceHashes'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    cookies = http.cookiejar.CookieJar()
    client = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
    def request(route, body=None):
        started = time.monotonic()
        progress = {'route': route, 'tool': (body or {}).get('tool'), 'started': time.time()}
        if progress['tool'] == 'neyvia.cl':
            progress['cl'] = body['arguments']['lines'][:600]
        write(OUT / 'request-progress.json', progress)
        with client.open(Request(f'http://127.0.0.1:{PORT}' + route, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'}), timeout=180) as response:
            result = json.load(response)
        progress.update(finished=time.time(), seconds=round(time.monotonic()-started, 3))
        write(OUT / 'request-progress.json', progress)
        return result
    def tool(name, args=None):
        row = request('/api/ui/tools/call', {'tool': 'neyvia.gamedev.' + name, 'arguments': args or {}})
        data = row.get('data', {})
        if (not row.get('ok') or not data.get('ok')) and data.get('status') not in ('unknown', 'pending'):
            raise RuntimeError(str(row))
        return data.get('result', data)
    def cl(lines):
        row = request('/api/ui/tools/call', {'tool': 'neyvia.cl', 'arguments': {'lines': lines, 'actionId': 'INTN-' + uuid.uuid4().hex}})
        data = row.get('data', {})
        if (not row.get('ok') or not data.get('ok')) and data.get('status') not in ('unknown', 'pending'):
            raise RuntimeError(str(row))
        return data.get('result', data)
    def launch(command, name, selected_env=env):
        stream = (OUT / (name + '.log')).open('wb')
        streams.append(stream)
        startup = None
        if name in ('unity','unity-activation','godot','blender'):
            startup = subprocess.STARTUPINFO()
            startup.lpDesktop = 'winsta0\\' + private_name
        child = subprocess.Popen(command, cwd=ROOT, env=selected_env, stdout=stream, stderr=subprocess.STDOUT, creationflags=HIDDEN, startupinfo=startup)
        processes.append(child)
        report.setdefault('processes', []).append({'name':name, 'pid':child.pid, 'desktop':private_name if startup else None})
        return child
    def action(sid, operation, args):
        rid = 'INTN-' + uuid.uuid4().hex
        project_args = 'engine=' + json.dumps(connected[0]['engine']) + ',projectPath=' + json.dumps(connected[0]['projectPath'])
        lines = 'G project: gamedev.project_status(' + project_args + ')["configured"] == True\ngamedev.sessions(' + project_args + ',context="Edit")\ngamedev.action(action=' + json.dumps(operation) + ',args=' + json.dumps(args) + ',requestId=' + json.dumps(rid) + ')'
        submitted = cl(lines)
        write(OUT / 'receipts' / (rid + '-cl.json'), submitted)
        until = time.monotonic() + 180
        while time.monotonic() < until:
            row = tool('receipt', {'requestId': rid})
            if row['status'] in ('succeeded', 'failed', 'timed_out'):
                write(OUT / 'receipts' / (rid + '.json'), row)
                if row['status'] != 'succeeded':
                    raise RuntimeError(str(row))
                row['clCompletion'] = cl('G complete: gamedev.receipt(requestId=' + json.dumps(rid) + ')["status"] == "succeeded"\nrun game-dev.review-completed-action(requestId=' + json.dumps(rid) + ')\ndone()')
                return row
            time.sleep(.3)
        raise TimeoutError('Native request did not complete: ' + rid)
    try:
        if 'unity' in selected and options.unity_editor_probe:
            probe_path = options.unity_editor_probe.resolve()
            probe_path.relative_to(Path(r'D:\NeyviaRuns\INTN\editors').resolve())
            probe_result = json.loads(probe_path.read_text(encoding='utf-8'))
            command = probe_result['command']
            log_path = Path(probe_result['logFile']).resolve()
            log_path.relative_to(Path(r'D:\NeyviaRuns\INTN\editors').resolve())
            project = Path(command[command.index('-createProject') + 1]).resolve()
            project.relative_to(Path(r'D:\NeyviaRuns\INTN\editors').resolve())
            if (command[0] != str(UNITY) or not {'-batchmode', '-nographics', '-quit'}.issubset(command)
                    or probe_result.get('exitCode') != 0 or probe_result.get('ok') is not True
                    or hashlib.sha256(log_path.read_bytes()).hexdigest() != probe_result['logSha256']
                    or not (project / 'Assets').is_dir() or not (project / 'ProjectSettings').is_dir()):
                raise RuntimeError('The supplied editor probe does not prove the installed Unity editor created its project')
            report['unityEditorProbe'] = {**probe_result, 'reusedReceipt': str(probe_path)}
        elif 'unity' in selected:
            # The editor owns licence validation; never infer activation from
            # licence files or copy the account's protected storage.
            probe_project = OUT / 'unity-activation-project'
            probe_log = OUT / 'unity-activation.log'
            if probe_project.exists():
                raise RuntimeError('Unity activation probe requires a fresh run label')
            # A minimal package-free project avoids template/package resolution
            # during licence validation. Unity still creates Assets/settings.
            write(probe_project / 'Packages/manifest.json', {'dependencies': {}})
            native_env = os.environ.copy()
            native_temp = OUT / 'native-temp'
            native_temp.mkdir(exist_ok=True)
            native_env.update(TEMP=str(native_temp), TMP=str(native_temp))
            command = [str(UNITY), '-batchmode', '-nographics', '-quit',
                       '-logFile', str(probe_log), '-createProject', str(probe_project)]
            editor = launch(command, 'unity-activation', native_env)
            code = editor.wait(timeout=options.unity_probe_timeout)
            log_bytes = probe_log.read_bytes() if probe_log.exists() else b''
            probe_result = {'command': command, 'exitCode': code,
                            'logFile': str(probe_log), 'logBytes': len(log_bytes),
                            'logSha256': hashlib.sha256(log_bytes).hexdigest(),
                            'projectCreated': (probe_project / 'Assets').is_dir()
                                and (probe_project / 'ProjectSettings').is_dir(),
                            'licenceFilesReadOrCopied': False}
            probe_result['ok'] = code == 0 and bool(log_bytes) and probe_result['projectCreated']
            report['unityEditorProbe'] = probe_result
            write(OUT / 'unity-editor-probe.json', probe_result)
            if not probe_result['ok']:
                raise RuntimeError('Unity editor project probe failed; inspect ' + str(probe_log))
        # Refuse occupied ports; never attach to or stop another owner's service.
        import socket
        for port in (PORT, WS):
            with socket.socket() as probe:
                if os.name == 'nt':
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind(('127.0.0.1', port))
        entry = str(ROOT / 'scripts/run_web_backend.py')
        if options.debug_threads:
            wrapper = OUT / 'backend-debug.py'
            wrapper.write_text('import faulthandler,runpy\nfrom pathlib import Path\nstream=Path(' + repr(str(OUT / 'backend-threads.log')) + ').open("w")\nfaulthandler.dump_traceback_later(60,repeat=True,file=stream)\nrunpy.run_path(' + repr(entry) + ',run_name="__main__")\n', encoding='utf-8')
            entry = str(wrapper)
        backend = launch([sys.executable, '-B', entry, '--host', '127.0.0.1', '--port', str(PORT), '--root', str(state), '--static-root', str(options.build_dir.resolve()), '--skip-runtime-auto-update', '--skip-proof-self-check'], 'backend', backend_env)
        for _ in range(240):
            if backend.poll() is not None:
                raise RuntimeError('Owned backend exited')
            try:
                if request('/api/health').get('ok'):
                    break
            except OSError:
                time.sleep(.25)
        else:
            raise TimeoutError('Owned backend health')
        # A competing backend may win the interval between probe and startup.
        # Health alone must never authorize mutation of somebody else's state.
        owner = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
            f'(Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort {PORT} -ErrorAction Stop).OwningProcess'],
            capture_output=True, text=True, check=True, timeout=20, creationflags=HIDDEN)
        if backend.poll() is not None or set(owner.stdout.split()) != {str(backend.pid)}:
            raise RuntimeError('The healthy listener is not the owned backend')
        report['verifiedBackendOwnerPid'] = backend.pid
        request('/api/auth/local-session', {})
        for engine, executable in (('blender', BLENDER), ('godot', GODOT), ('unity', UNITY)):
            if engine not in selected:
                continue
            # Each journey owns a fresh authenticated interpreter. A deliberately
            # failed native operation remains failed in its original task.
            cookies.clear()
            request('/api/auth/local-session', {})
            row = {'executable': str(executable), 'ok': False}
            report['results'][engine] = row
            # Unity benefits from the retained Library import cache. Blender
            # and Godot start inexpensive fresh projects, preserving old bridge
            # code rather than trying to replace an installed project plugin.
            reuse_project = options.project_root is not None and engine == 'unity'
            project = (project_root if reuse_project else OUT) / engine
            project.mkdir(exist_ok=True)
            row['projectPath'] = str(project)
            if reuse_project:
                # This disposable project belonged to another owned backend.
                # Preserve its capability before setup issues a fresh grant;
                # never accept the old grant under a different backend key.
                capability_path = project / '.neyvia/gamedev-bridge.json'
                if capability_path.is_file():
                    previous = capability_path.with_name('gamedev-bridge.previous-' + label + '.json')
                    if previous.exists():
                        raise RuntimeError('Refusing to overwrite a preserved project capability')
                    capability_path.rename(previous)
                    row['preservedPriorCapability'] = str(previous)
            (project / 'finish').write_text('waiting', encoding='utf-8')
            child = None
            try:
                if engine == 'unity':
                    (project / 'Assets/Editor').mkdir(parents=True, exist_ok=True)
                    (project / 'Packages').mkdir(exist_ok=True)
                    (project / 'ProjectSettings').mkdir(exist_ok=True)
                    write(project / 'Packages/manifest.json', {'dependencies': {}})
                    (project / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.6.4f1\n', encoding='utf-8')
                    (project / 'Assets/Editor/IntnScene.cs').write_text('using UnityEditor; using UnityEditor.SceneManagement; using UnityEngine; public static class IntnScene { public static void Start() { EditorSceneManager.NewScene(NewSceneSetup.EmptyScene); var cube=GameObject.CreatePrimitive(PrimitiveType.Cube); cube.name="Cube"; EditorSceneManager.SaveScene(cube.scene,"Assets/Intn.unity"); var end=EditorApplication.timeSinceStartup+600; EditorApplication.update+=()=>{if(EditorApplication.timeSinceStartup>end) EditorApplication.Exit(0);}; }}', encoding='utf-8')
                if engine == 'godot':
                    (project / 'project.godot').write_text('config_version=5\n[application]\nconfig/name="INTN"\nrun/main_scene="res://main.tscn"\n[editor_plugins]\nenabled=PackedStringArray("res://addons/neyvia_bridge/plugin.cfg")\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n', encoding='utf-8')
                    (project / 'main.tscn').write_text('[gd_scene load_steps=2 format=3]\n[sub_resource type="BoxMesh" id="Box"]\n[node name="Scene" type="Node3D"]\n[node name="Cube" type="MeshInstance3D" parent="."]\nmesh=SubResource("Box")\n', encoding='utf-8')
                setup_args = 'engine=' + json.dumps(engine) + ',projectPath=' + json.dumps(str(project))
                row['setup'] = cl('G setup: gamedev.project_status(' + setup_args + ')["configured"] == True\nrun game-dev.setup-project(' + setup_args + ')\ndone()')
                if row['setup'].get('ok') is not True:
                    raise RuntimeError('CL setup did not pass: ' + str(row['setup']))
                if engine == 'blender':
                    bootstrap = project / 'roundtrip.py'
                    bootstrap.write_text('import sys,time,bpy\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).parent/".neyvia/blender"))\nimport neyvia_bridge\nneyvia_bridge.register()\nbpy.context.scene.neyvia_project_path=str(Path(__file__).parent)\nassert bpy.ops.neyvia.connect()=={"FINISHED"}\nend=time.monotonic()+600\nwhile time.monotonic()<end and (Path(__file__).parent/"finish").read_text()!="finish":\n neyvia_bridge._tick(); time.sleep(.1)\nbpy.ops.wm.save_as_mainfile(filepath=str(Path(__file__).parent/"roundtrip.blend"))\nneyvia_bridge.unregister()\n', encoding='utf-8')
                    command = [str(executable), '--background', '--factory-startup', '--python', str(bootstrap)]
                elif engine == 'godot':
                    command = [str(executable), '--headless', '--editor', '--path', str(project), 'res://main.tscn']
                else:
                    command = [str(executable), '-batchmode', '-nographics', '-projectPath', str(project), '-executeMethod', 'IntnScene.Start', '-logFile', str(OUT / 'unity-native.log')]
                child = launch(command, engine)
                until = time.monotonic() + 480
                while time.monotonic() < until:
                    if child.poll() is not None:
                        raise RuntimeError(f'Native editor exited {child.returncode}; inspect {engine}.log')
                    sessions = tool('sessions')['sessions']
                    connected = [s for s in sessions if s['engine'] == engine and s['projectPath'] == str(project) and s['status'] == 'connected' and s['context'] == 'Edit']
                    if connected:
                        break
                    time.sleep(.5)
                else:
                    raise TimeoutError('Native bridge did not connect')
                sid = connected[0]['sessionId']
                row['session'] = connected[0]
                capability = json.loads((project / '.neyvia/gamedev-bridge.json').read_text())
                registration = {key: connected[0][key] for key in ('engine', 'projectPath', 'context', 'capabilities', 'clientId')}
                registration['studio_id'] = connected[0].get('studio_id')
                with client.open(Request(f'http://127.0.0.1:{PORT}/api/gamedev/bridge/register',
                    data=json.dumps(registration).encode(), headers={'Content-Type':'application/json',
                    'Authorization':'Bearer ' + capability['token']}), timeout=30) as response:
                    repeated = json.load(response)
                row['registrationRetrySameSession'] = repeated['data']['sessionId'] == sid
                if not row['registrationRetrySameSession']:
                    raise RuntimeError('Registration retry created another native session')
                scope_args = 'engine=' + json.dumps(engine) + ',projectPath=' + json.dumps(str(project))
                row['uniqueSessionContract'] = cl('G native: gamedev.project_status(' + scope_args + ')["configured"] == True\nrun game-dev.inspect-one-editor-session(' + scope_args + ')\ndone()')
                inspect_args = {'path': 'Cube'} if engine == 'unity' else {}
                row['before'] = action(sid, 'inspect', inspect_args)
                scene = row['before']['result']
                scene_objects = scene.get('objects',[]) if engine == 'unity' else [o['name'] for o in scene['objects']] if engine == 'blender' else [o['name'] for o in scene['tree']['children']]
                row['sceneListsCube'] = 'Cube' in scene_objects
                if not row['sceneListsCube']:
                    raise RuntimeError('The actual scene inspection did not list Cube')
                edit_args = {'object': 'Cube', 'location': [1,2,3]} if engine == 'blender' else {'node': 'Cube', 'property': 'position', 'value': [1,2,3]} if engine == 'godot' else {'path': 'Cube', 'component': 'Transform', 'property': 'm_LocalPosition', 'vector': [1,2,3], 'save': True}
                row['edit'] = action(sid, 'edit', edit_args)
                row['after'] = action(sid, 'inspect', inspect_args)
                native = row['after']['result']
                location = native.get('position') if engine == 'unity' else next(o for o in native['objects'] if o['name']=='Cube')['location'] if engine == 'blender' else next(o for o in native['tree']['children'] if o['name']=='Cube')['position']
                if location != [1,2,3]:
                    raise RuntimeError('Native readback differs: ' + str(location))
                # An invalid object is a real failure, never a successful edit.
                try:
                    action(sid, 'edit', {**edit_args, ('object' if engine == 'blender' else 'node' if engine == 'godot' else 'path'): 'DoesNotExist'})
                except RuntimeError:
                    row['missingObjectRefused'] = True
                else:
                    raise RuntimeError('Missing native object was not refused')
                row['ok'] = True
            except Exception as exc:
                row.update(error=str(exc), traceback=traceback.format_exc())
            finally:
                (project / 'finish').write_text('finish', encoding='utf-8')
                if child and child.poll() is None:
                    if engine == 'blender':
                        try: child.wait(timeout=10)
                        except subprocess.TimeoutExpired: child.terminate()
                    else:
                        child.terminate()
                write(OUT / 'receipt.json', report)
                print(json.dumps({'engine': engine, 'ok': row['ok'], 'error': str(row.get('error') or '')[:250], 'receipt':str(OUT / 'receipt.json')}), flush=True)
    finally:
        report['processExitCodesBeforeCleanup'] = {item['name']:child.poll() for item,child in zip(report.get('processes',[]),processes)}
        for child in reversed(processes):
            if child.poll() is None:
                child.terminate()
                try: child.wait(timeout=10)
                except subprocess.TimeoutExpired: child.kill()
        for stream in streams: stream.close()
        report['privateDesktopHandleClosed'] = bool(user32.CloseDesktop(desktop))
        report.update(finished=time.time(), selectedEngines=selected, ok=len(report['results']) == len(selected) and all(row['ok'] for row in report['results'].values()))
        report['sourceChangedDuringRun'] = [name for name, digest in report['sourceHashes'].items()
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
        report['ok'] = report['ok'] and not report['sourceChangedDuringRun']
        report['runtimeStateBytes'] = sum(p.stat().st_size for p in state.rglob('*') if p.is_file())
        write(OUT / 'receipt.json', report)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
