"""Host-bound native application tools for grounded manual learning.

These are application object-model/file commands, never UI Automation or pixels.
Every session owns a new hidden process and disposable files; its guard remains
active until close. No user document or existing Office instance is admitted.
"""
from pathlib import Path
import atexit
import gzip
import hashlib
import html
import json
import os
import re
import subprocess
import queue
import threading
import uuid
from xml.etree import ElementTree as ET
from .cua_guard import ZeroDisturbanceGuard
from .cua_office import OfficeSession, APPS, _artifact

TEXT = {"type": "string"}
SHELLS = {'Command Prompt': ['C:/Windows/System32/cmd.exe', '/d', '/q', '/c'],
    'Windows PowerShell': ['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command']}
XOURNAL = Path('C:/Program Files/Xournal++/bin/xournalpp.exe')
GIT = Path('C:/Program Files/Git/cmd/git.exe')
RENDERERS = {'Mozilla Firefox': Path('C:/Program Files/Mozilla Firefox/firefox.exe'),
    'Zen Browser': Path('C:/Program Files/Zen Browser/zen.exe')}
APPLICATIONS = [*APPS, *SHELLS, 'Xournal++', 'Git', *RENDERERS]
SCHEMAS = {
    "open": {"type": "object", "properties": {"app": {"enum": APPLICATIONS}}, "required": ["app"], "additionalProperties": False},
    "edit": {"type": "object", "properties": {"sessionId": TEXT, "value": TEXT}, "required": ["sessionId", "value"], "additionalProperties": False},
    "persist": {"type": "object", "properties": {"sessionId": TEXT}, "required": ["sessionId"], "additionalProperties": False},
    "observe": {"type": "object", "properties": {"sessionId": TEXT, "expected": TEXT, "persisted": {"type": "boolean"}}, "required": ["sessionId", "expected", "persisted"], "additionalProperties": False},
    "close": {"type": "object", "properties": {"sessionId": TEXT}, "required": ["sessionId"], "additionalProperties": False},
}


class NativeApplications:
    def __init__(self, root, *, register_exit=True):
        self.root = Path(root).resolve()
        self.sessions = {}
        self.failed_opens = []
        if register_exit:
            atexit.register(self.shutdown)

    def shutdown(self):
        """Release only this host's admitted sessions even after caller failure."""
        for identity in list(self.sessions):
            try:
                self.close({'sessionId': identity})
            except Exception:
                continue

    def open(self, args):
        identity = uuid.uuid4().hex
        area = self.root / '.agent_control/native-applications' / identity
        area.mkdir(parents=True)
        guard = ZeroDisturbanceGuard().start()
        office = None
        try:
            if not guard.check()['ok']:
                raise RuntimeError('Guard refused application launch')
            if args['app'] == 'Xournal++':
                from .cua_desktop import AgentDesktop
                if not XOURNAL.is_file():
                    raise RuntimeError('Installed Xournal++ executable absent')
                desktop = AgentDesktop(profile_root=area)
                self.sessions[identity] = dict(app=args['app'], guard=guard, root=area,
                    desktop=desktop, input=area / 'note.xopp', path=area / 'note.pdf',
                    persisted=False, processes=[])
                return {'sessionId': identity, 'ownership': {'privateDesktop': desktop.name,
                    'job': desktop.job_name, 'root': str(area)}, 'source': 'real Xournal++ native export of an owned note'}
            if args['app'] == 'Git':
                if not GIT.is_file():
                    raise RuntimeError('Installed Git executable absent')
                row = dict(app='Git', guard=guard, root=area, path=area / 'note.txt',
                    persisted=False, processes=[], revision=0)
                self.sessions[identity] = row
                self.native_process(row, [str(GIT), 'init', '--quiet', str(area)])
                return {'sessionId': identity, 'ownership': {'newProcessPerAction': True,
                    'creationFlags': 'CREATE_NO_WINDOW', 'root': str(area)},
                    'source': 'real Git CLI on owned disposable repository'}
            if args['app'] in RENDERERS:
                if not RENDERERS[args['app']].is_file():
                    raise RuntimeError('Installed headless browser executable absent')
                profile = area / 'browser-profile'
                profile.mkdir()
                (profile / 'user.js').write_text('user_pref("app.update.enabled", false);\n'
                    'user_pref("toolkit.telemetry.enabled", false);\n'
                    'user_pref("browser.shell.checkDefaultBrowser", false);\n', encoding='utf-8')
                self.sessions[identity] = dict(app=args['app'], guard=guard, root=area,
                    input=area / 'note.html', path=None, profile=profile,
                    persisted=False, processes=[], revision=0, color=None)
                return {'sessionId': identity, 'ownership': {'headless': True,
                    'freshProfile': str(profile), 'creationFlags': 'CREATE_NO_WINDOW', 'root': str(area)},
                    'source': 'real headless browser rendering of an owned local note'}
            if args['app'] in SHELLS:
                self.sessions[identity] = dict(app=args['app'], guard=guard, root=area,
                    path=area / 'persisted.txt', persisted=False, processes=[])
                return {'sessionId': identity, 'ownership': {'newProcessPerAction': True,
                    'creationFlags': 'CREATE_NO_WINDOW', 'root': str(area)}, 'source': 'hidden native shell'}
            office = OfficeSession(args['app'], area, guard)
            if args['app'] == 'Microsoft Word':
                doc = office.application.Documents.Add()
            elif args['app'] == 'Microsoft Excel':
                doc = office.application.Workbooks.Add()
                doc.Worksheets(1).Range('B1:B2').Value = ((12,), (25,))
                doc.Worksheets(1).Range('B3').Formula = '=SUM(B1:B2)'
            else:
                doc = office.application.Presentations.Add(False)
                for title in ('Project', 'Decisions', 'Next steps'):
                    slide = doc.Slides.Add(doc.Slides.Count + 1, 12)
                    slide.Shapes.AddTextbox(1, 36, 36, 600, 120).TextFrame.TextRange.Text = title
                slide = None
            office.documents.append(doc)
            self.sessions[identity] = dict(office=office, guard=guard, document=doc,
                path=area / ('document' + APPS[args['app']][2]), persisted=False)
            return {'sessionId': identity, 'ownership': office.ownership, 'source': 'hidden Office COM'}
        except Exception:
            if office:
                office.close()
            self.failed_opens.append({'app': args['app'], 'guard': guard.close()})
            raise

    def session(self, args):
        row = self.sessions[args['sessionId']]
        if not row['guard'].check()['ok']:
            raise RuntimeError('Zero-disturbance guard refused dispatch')
        if 'office' in row:
            row['office'].observe()
        return row

    def shell(self, row, command):
        if row['app'] == 'Command Prompt':
            batch = row['root'] / (uuid.uuid4().hex[:8] + '.cmd')
            batch.write_bytes(('@echo off\r\n' + command + '\r\n').encode('ascii'))
            # Keep the absolute batch name under cmd's legacy path limit.
            command = str(batch)
        argv = SHELLS[row['app']]
        process = subprocess.Popen([str(Path(argv[0])), *argv[1:], command], cwd=row['root'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        row['guard'].register_pid(process.pid)
        output = process.communicate(timeout=10)[0].decode('utf-8', errors='replace')
        row['processes'].append({'pid': process.pid, 'exitCode': process.returncode})
        if process.returncode:
            raise RuntimeError('Native disposable shell failed: ' + output[:200])
        return output

    def native_process(self, row, argv, timeout=20, extra_env=None):
        environment = os.environ.copy()
        environment.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': str(row['root'] / 'empty-gitconfig'),
            'GIT_TERMINAL_PROMPT': '0', 'MOZ_HEADLESS': '1'})
        if extra_env:
            environment.update(extra_env)
        process = subprocess.Popen(argv, cwd=row['root'], env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        row['guard'].register_pid(process.pid)
        try:
            output = process.communicate(timeout=timeout)[0].decode('utf-8', errors='replace')
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            row['processes'].append({'pid': process.pid, 'exitCode': process.returncode, 'timeout': True})
            raise TimeoutError('Owned native process deadline')
        row['processes'].append({'pid': process.pid, 'exitCode': process.returncode})
        if process.returncode:
            raise RuntimeError('Owned native process exited ' + str(process.returncode) + ': ' + output[:200])
        return output

    def edit(self, args):
        row = self.session(args)
        if row.get('app') == 'Git':
            if not 1 <= len(args['value']) <= 1000 or any(ord(ch) < 32 for ch in args['value']):
                raise ValueError('Git note must be one printable line')
            row['revision'] += 1
            row['path'].write_text(args['value'] + '\nRevision: ' + str(row['revision']) + '\n', encoding='utf-8')
            status = self.native_process(row, [str(GIT), 'status', '--porcelain', '--', 'note.txt'])
            row['persisted'] = False
            return {'ok': bool(status.strip()), 'source': 'owned Git repository working-tree status',
                'revision': row['revision']}
        if row.get('app') in RENDERERS:
            if not 1 <= len(args['value']) <= 1000:
                raise ValueError('Rendered note must contain 1-1000 characters')
            color = '#' + hashlib.sha256(args['value'].encode('utf-8')).hexdigest()[:6]
            row['input'].write_text('<!doctype html><meta charset="utf-8"><style>html,body{margin:0;'
                'background:' + color + ';color:white;font:32px Arial}</style><h1>'
                + html.escape(args['value']) + '</h1>', encoding='utf-8')
            row['value'], row['color'], row['persisted'] = args['value'], color, False
            return {'ok': True, 'source': 'owned local browser document input', 'themeColor': color}
        if row.get('app') == 'Xournal++':
            note = ET.Element('xournal', {'creator': 'C11g owned note', 'fileversion': '4'})
            ET.SubElement(note, 'title').text = 'Disposable project note'
            page = ET.SubElement(note, 'page', {'width': '595', 'height': '842'})
            ET.SubElement(page, 'background', {'type': 'solid', 'color': '#ffffffff', 'style': 'plain'})
            layer = ET.SubElement(page, 'layer')
            ET.SubElement(layer, 'text', {'font': 'Arial', 'size': '16', 'x': '36', 'y': '48', 'color': '#000000ff'}).text = args['value']
            with gzip.open(row['input'], 'wb') as stream:
                stream.write(ET.tostring(note, encoding='utf-8', xml_declaration=True))
            row['persisted'] = False
            return {'ok': True, 'source': 'host-authored disposable Xournal note input; export is performed by Xournal++'}
        if 'office' not in row:
            if not re.fullmatch(r'[A-Za-z0-9 ._-]{1,1000}', args['value']):
                raise ValueError('Shell draft admits literal ASCII text only; command syntax refused')
            command = ('>draft.txt echo ' + args['value']) if row['app'] == 'Command Prompt' else (
                "Set-Content -LiteralPath './draft.txt' -Value '" + args['value'] + "' -Encoding UTF8")
            self.shell(row, command)
            row['persisted'] = False
            return {'ok': True, 'source': 'CREATE_NO_WINDOW native shell file edit'}
        doc, app = row['document'], row['office'].app_name
        if app == 'Microsoft Word':
            doc.Content.Text = args['value']
        elif app == 'Microsoft Excel':
            doc.Worksheets(1).Range('A1').Value = args['value']
            row['office'].application.Calculate()
        else:
            doc.Slides(1).Shapes(1).TextFrame.TextRange.Text = args['value']
        row['persisted'] = False
        return {'ok': True, 'source': 'Office COM field edit'}

    def text(self, row):
        if 'office' not in row:
            if row.get('app') == 'Git':
                return row['path'].read_text(encoding='utf-8').splitlines()[0]
            if row.get('app') in RENDERERS:
                return row['value']
            if row.get('app') == 'Xournal++':
                with gzip.open(row['input'], 'rb') as stream:
                    return ET.fromstring(stream.read()).find('page/layer/text').text or ''
            return (row['root'] / 'draft.txt').read_text(encoding='utf-8-sig').removesuffix('\n')
        doc, app = row['document'], row['office'].app_name
        if app == 'Microsoft Word':
            return str(doc.Content.Text).removesuffix('\r')
        if app == 'Microsoft Excel':
            if float(doc.Worksheets(1).Range('B3').Value) != 37.0:
                raise RuntimeError('Native calculated budget does not equal 37')
            return str(doc.Worksheets(1).Range('A1').Value)
        if doc.Slides.Count != 3:
            raise RuntimeError('Deck must retain three slides')
        return str(doc.Slides(1).Shapes(1).TextFrame.TextRange.Text)

    def persist(self, args):
        row = self.session(args)
        if row.get('app') == 'Git':
            self.native_process(row, [str(GIT), 'add', '--', 'note.txt'])
            self.native_process(row, [str(GIT), '-c', 'core.hooksPath=NUL',
                '-c', 'commit.gpgSign=false', '-c', 'user.name=C11 Local',
                '-c', 'user.email=c11@local.invalid', 'commit', '--quiet', '-m',
                'Save owned note revision ' + str(row['revision'])])
            head = self.native_process(row, [str(GIT), 'rev-parse', 'HEAD']).strip()
            row['persisted'] = True
            return {'ok': True, 'artifact': str(row['root'] / '.git'), 'commit': head,
                'source': 'Git add and commit on disposable repository'}
        if row.get('app') in RENDERERS:
            row['revision'] += 1
            destination = row['root'] / ('render-' + str(row['revision']) + '.png')
            self.native_process(row, [str(RENDERERS[row['app']]), '-headless', '-no-remote',
                '-profile', str(row['profile']), '-screenshot', str(destination),
                '-width', '800', '-height', '600', row['input'].as_uri()], timeout=30)
            if not destination.is_file():
                raise RuntimeError('Browser exited without screenshot artifact')
            row['path'], row['persisted'] = destination, True
            return {'ok': True, 'artifact': str(destination),
                'source': row['app'] + ' headless local document screenshot', 'process': row['processes'][-1]}
        if row.get('app') == 'Xournal++':
            process = row['desktop'].launch([str(XOURNAL), '--create-pdf=' + str(row['path']), str(row['input'])],
                cwd=row['root'], env={'APPDATA': str(row['root'] / 'appdata'),
                    'LOCALAPPDATA': str(row['root'] / 'localappdata'), 'XDG_CONFIG_HOME': str(row['root'] / 'config')})
            row['guard'].register_pid(process.pid)
            code = process.wait(20)
            row['processes'].append({'pid': process.pid, 'exitCode': code})
            if code or not row['path'].is_file():
                raise RuntimeError('Real Xournal++ PDF export failed with exit ' + str(code))
            row['persisted'] = True
            return {'ok': True, 'artifact': str(row['path']), 'source': 'Xournal++ --create-pdf on private desktop',
                'process': row['processes'][-1]}
        if 'office' not in row:
            command = 'copy /y draft.txt persisted.txt >nul' if row['app'] == 'Command Prompt' else (
                "Copy-Item -LiteralPath './draft.txt' -Destination './persisted.txt' -Force")
            self.shell(row, command)
            row['persisted'] = row['path'].read_text(encoding='utf-8-sig').removesuffix('\n') == self.text(row)
            return {'ok': row['persisted'], 'artifact': str(row['path']), 'source': 'native shell copy and file reopen'}
        office, doc, path = row['office'], row['document'], row['path']
        expected = self.text(row)
        if office.app_name == 'Microsoft Word':
            doc.SaveAs2(str(path), 16); doc.Close(False)
            row['document'] = office.application.Documents.Open(str(path), False, False, False)
        elif office.app_name == 'Microsoft Excel':
            doc.SaveAs(str(path), 51); doc.Close(False)
            row['document'] = office.application.Workbooks.Open(str(path), 0, False)
        else:
            doc.SaveAs(str(path), 24); doc.Close()
            row['document'] = office.application.Presentations.Open(str(path), False, False, False)
        office.documents.remove(doc)
        office.documents.append(row['document'])
        row['persisted'] = self.text(row) == expected
        return {'ok': row['persisted'], 'artifact': str(path), 'source': 'Office save and native reopen'}

    def observe(self, args):
        row = self.session(args)
        text = self.text(row)
        if row.get('app') == 'Git':
            artifact = None
            ok = text == args['expected']
            if args['persisted']:
                committed = self.native_process(row, [str(GIT), 'show', 'HEAD:note.txt'])
                status = self.native_process(row, [str(GIT), 'status', '--porcelain'])
                artifact = {'commit': self.native_process(row, [str(GIT), 'rev-parse', 'HEAD']).strip(),
                    'path': str(row['path']), 'bytes': row['path'].stat().st_size,
                    'sha256': hashlib.sha256(row['path'].read_bytes()).hexdigest(),
                    'committedText': committed.splitlines()[0], 'clean': not status.strip()}
                ok = ok and row['persisted'] and artifact['committedText'] == args['expected'] and artifact['clean']
            return {'ok': bool(ok), 'observed': text, 'artifact': artifact,
                'source': 'fresh git show plus owned working-tree readback'}
        if row.get('app') in RENDERERS:
            artifact = None
            ok = text == args['expected'] and row['input'].is_file()
            if args['persisted']:
                from PIL import Image
                with Image.open(row['path']) as screenshot:
                    image_size = screenshot.size
                    pixels = screenshot.convert('RGB')
                    sample = pixels.getpixel((0, 0))
                    heading = pixels.crop((0, 30, min(1100, image_size[0]), min(220, image_size[1])))
                    ink_pixels = sum(1 for rgb in heading.getdata() if min(rgb) > 220)
                expected_rgb = tuple(bytes.fromhex(row['color'][1:]))
                data = row['path'].read_bytes()
                artifact = {'path': str(row['path']), 'bytes': len(data),
                    'sha256': hashlib.sha256(data).hexdigest(), 'size': image_size,
                    'cornerRgb': sample, 'expectedRgb': expected_rgb, 'headingInkPixels': ink_pixels}
                ok = ok and row['persisted'] and image_size[0] >= 800 and image_size[1] >= 600 and sample == expected_rgb and ink_pixels > 1000
            return {'ok': bool(ok), 'observed': text, 'artifact': artifact,
                'source': 'owned HTML and independent browser-produced PNG pixel inspection'}
        if row.get('app') == 'Xournal++':
            artifact = None
            ok = text == args['expected']
            if args['persisted']:
                from .pdf_compat import page_count, page_texts
                observed = ''.join(page_texts(row['path'])).strip()
                pages = page_count(row['path'])
                data = row['path'].read_bytes()
                artifact = {'path': str(row['path']), 'sha256': hashlib.sha256(data).hexdigest(),
                    'bytes': len(data), 'extractedText': observed, 'pages': pages}
                ok = ok and row['persisted'] and observed == args['expected'] and pages == 1
            return {'ok': bool(ok), 'observed': text, 'artifact': artifact,
                'source': 'owned Xournal input plus independent rendered PDF text extraction'}
        if 'office' not in row:
            ok = text == args['expected']
            artifact = None
            if args['persisted']:
                saved = row['path'].read_bytes()
                artifact = {'path': str(row['path']), 'sha256': hashlib.sha256(saved).hexdigest(), 'bytes': len(saved)}
                ok = ok and row['persisted'] and saved.decode('utf-8-sig').removesuffix('\r\n').removesuffix('\n') == args['expected']
            return {'ok': bool(ok), 'observed': text, 'artifact': artifact, 'source': 'independent exact file readback'}
        artifact = _artifact(row['path']) if args['persisted'] else None
        ok = text == args['expected']
        if args['persisted']:
            ok = ok and row['persisted'] and args['expected'] in artifact.pop('xmlText')
        return {'ok': bool(ok), 'observed': text, 'artifact': artifact, 'source': 'fresh native COM readback plus saved-package inspection'}

    def close(self, args):
        row = self.sessions.pop(args['sessionId'])
        if 'office' not in row:
            cleanup = row['desktop'].close() if row.get('app') == 'Xournal++' else None
            guard = row['guard'].close()
            return json.loads(json.dumps({'ok': guard['ok'] and all(p['exitCode'] == 0 for p in row['processes']),
                'cleanup': {'processExited': True, 'processes': row['processes'], 'desktop': cleanup}, 'guard': guard}))
        document = row.pop('document')
        if row['office'].app_name == 'Microsoft PowerPoint':
            document.Close()
        else:
            document.Close(False)
        row['office'].documents.clear()
        document = None
        cleanup = row['office'].close()
        guard = row['guard'].close()
        return json.loads(json.dumps({'ok': cleanup['ok'] and guard['ok'], 'cleanup': cleanup, 'guard': guard}))

    def attach(self, registry, spec_type):
        for operation, schema in SCHEMAS.items():
            name = 'neyvia.nativeapp.' + operation
            registry._specs[name] = spec_type(name=name,
                description='Owned hidden native application: ' + operation,
                category='computer-use', input_schema=schema,
                mutability_class='read' if operation == 'observe' else 'workspace_write', parallel_safe=False)
            registry._handlers[name] = getattr(self, operation)
        return self


class HostedNativeApplications:
    """One lazy owner thread per workspace across registry/HTTP call lifetimes."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.requests = queue.Queue()
        self.lock = threading.Lock()
        self.thread = None
        self.closed = False

    def _run(self):
        runtime = NativeApplications(self.root, register_exit=False)
        try:
            while True:
                request = self.requests.get()
                if request is None:
                    break
                operation, arguments, done, outcome = request
                try:
                    if operation == '_sessions':
                        outcome.append({identity: {'processes': list(row.get('processes', []))}
                                        for identity, row in runtime.sessions.items()})
                    elif operation == '_failed_opens':
                        outcome.append(list(runtime.failed_opens))
                    else:
                        outcome.append(getattr(runtime, operation)(arguments))
                except Exception as exc:
                    outcome.append(exc)
                finally:
                    done.set()
        finally:
            # COM objects are released on the apartment which created them.
            runtime.shutdown()

    def request(self, operation, arguments=None):
        with self.lock:
            if self.closed:
                raise RuntimeError('Native application host is closed')
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name='native-applications-owner', daemon=True)
                self.thread.start()
            if not self.thread.is_alive():
                raise RuntimeError('Native application owner thread failed')
            done, outcome = threading.Event(), []
            self.requests.put((operation, arguments, done, outcome))
        if not done.wait(120):
            # No retry is issued: the original operation may still complete.
            raise TimeoutError('Native application outcome unknown; observe before retrying')
        if isinstance(outcome[0], Exception):
            raise outcome[0]
        return outcome[0]

    def __getattr__(self, name):
        if name not in SCHEMAS:
            raise AttributeError(name)
        return lambda arguments: self.request(name, arguments)

    @property
    def sessions(self):
        return self.request('_sessions')

    @property
    def failed_opens(self):
        return self.request('_failed_opens')

    def attach(self, registry, spec_type):
        return NativeApplications.attach(self, registry, spec_type)

    def shutdown(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.thread:
                self.requests.put(None)
        if self.thread:
            self.thread.join(120)


_HOSTS = {}
_HOSTS_LOCK = threading.Lock()


def hosted_native_applications(root):
    identity = str(Path(root).resolve()).casefold()
    with _HOSTS_LOCK:
        if identity not in _HOSTS:
            _HOSTS[identity] = HostedNativeApplications(root)
        return _HOSTS[identity]


def _close_hosts():
    for host in list(_HOSTS.values()):
        host.shutdown()


atexit.register(_close_hosts)
