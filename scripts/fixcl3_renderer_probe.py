"""Current-source mounted panes and PDF in Neyvia's own headless browser."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
import socket
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]


def pdf_fixture():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R',
        b'', b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R',
        b'', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    objects[2] += b' >>'; objects[4] += b' >>'
    for i, text in ((3, 'FIXCL3 first page exact text'), (5, 'FIXCL3 second page exact text')):
        stream = ('BT /F1 18 Tf 50 700 Td (' + text + ') Tj ET\n').encode()
        objects[i] = b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'endstream'
    output = bytearray(b'%PDF-1.4\n'); offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(output)); output += str(i).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    xref = len(output)
    output += b'xref\n0 8\n0000000000 65535 f \n'
    for offset in offsets[1:]: output += f'{offset:010d} 00000 n \n'.encode()
    output += f'trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return bytes(output)


def pdf_extension(receipt, checks, cl, dom, ui, session, root, service, state):
    dom("() => { const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='Skip setup'); if(b)b.click(); return true; }")
    for _ in range(80):
        if dom('() => !document.querySelector(".nx-onb-scrim")'): break
        time.sleep(.25)
    checks['pdf.setupDismissed'] = dom('() => !document.querySelector(".nx-onb-scrim")')
    receipt['obscuraCapabilities'] = dom('() => globalThis.__NEYVIA_OBSCURA_CAPABILITIES__ || null')
    path = root / 'fixture.pdf'
    path.write_bytes(pdf_fixture())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    operations = [
        ('open', 'pdf.open(source=' + json.dumps(str(path)) + ',page=1)',
         'pdf.state()["state"]["page"] == 1'),
        ('goto', 'pdf.goto(page=2)', 'pdf.state()["state"]["page"] == 2'),
        ('zoom', 'pdf.zoom(scale=1.25)', 'pdf.state()["state"]["scale"] == 1.25'),
        ('search', 'pdf.search(query="FIXCL3")', 'pdf.state()["state"]["search"]["hits"] == 2'),
        ('highlight', 'pdf.highlight(page=2,text="FIXCL3",note="Local rendered witness")',
         'pdf.state()["state"]["page"] == 2')]
    for key, action, goal in operations:
        token = session()
        result = cl('pdf-' + key, 'action', 'G: ' + goal + '\n' + action + '\ndone()', token)
        checks['pdf.' + key + '.freshCL'] = result.get('ok') is True
        rendered = dom('() => ({text:document.querySelector(".nx-stage")?.innerText || document.body.innerText, canvases:document.querySelectorAll("canvas").length, iframes:document.querySelectorAll("iframe").length})')
        receipt['journeys']['pdf-' + key]['rendered'] = rendered
        receipt['journeys']['pdf-' + key]['ownerState'] = service.bus.get('app:pdf')
        if not result.get('ok'):
            time.sleep(15)
            receipt['journeys']['pdf-' + key]['lateOwnerState'] = service.bus.get('app:pdf')
            receipt['journeys']['pdf-' + key]['lateRendered'] = dom('() => ({text:document.querySelector(".nx-stage")?.innerText || document.body.innerText, canvases:document.querySelectorAll("canvas").length})')
            break
        checks['pdf.' + key + '.sourceConserved'] = hashlib.sha256(path.read_bytes()).hexdigest() == digest
    opened = service.bus.get('app:pdf') or {}
    checks['pdf.actualTwoPages'] = opened.get('pages') == 2
    checks['pdf.actualReady'] = opened.get('status') == 'ready'
    visual = dom('() => ({canvasCount:document.querySelectorAll("canvas").length, error: /getTransform is not a function|rendering failed/i.test(document.body.innerText), textLayer:[...document.querySelectorAll(".textLayer span")].map(e=>e.innerText).join(" ")})')
    receipt['pdfVisualObservation'] = visual
    receipt['pdfVisualChecks'] = {'twoActualCanvases':visual['canvasCount'] == 2, 'noCanvasRuntimeError':visual['error'] is False, 'actualTextLayer': 'FIXCL3 first page exact text' in visual['textLayer']}
    receipt['pdfVisualReady'] = all(receipt['pdfVisualChecks'].values())
    if all(checks.get('pdf.' + op[0] + '.freshCL') for op in operations):
        path.write_bytes(pdf_fixture().replace(b'first page', b'alter page'))
        checks['pdf.sourceDriftDoneRefused'] = cl('pdf-highlight', 'afterByteDrift', 'done()', token).get('ok') is False
        path.write_bytes(pdf_fixture())


def hashes(paths):
    return {path.relative_to(REPO).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-port', type=int, required=True)
    parser.add_argument('--ui-port', type=int, required=True)
    parser.add_argument('--pane-port', type=int, required=True)
    parser.add_argument('--fixture-port', type=int, required=True)
    parser.add_argument('--ipc-port', type=int, action='append', required=True)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--obscura', type=Path, required=True)
    parser.add_argument('--wave', choices=['FIXCL3','FIXCL4','FIXCL5','FIXCL6','FIXCL7'], default='FIXCL3')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--pdf-only', action='store_true', help='Run just the mounted PDF diagnosis with normal cleanup')
    modes.add_argument('--app-open-only', action='store_true', help='Run just the mounted app/artifact open journeys with normal cleanup')
    args = parser.parse_args()
    ports = [args.backend_port, args.ui_port, args.pane_port, args.fixture_port]
    owned_ports = [*ports, *args.ipc_port]
    allowed = range(48781, 48790) if args.wave in {'FIXCL6','FIXCL7'} else range(48821, 48830)
    if len(set(owned_ports)) != len(owned_ports) or any(port not in allowed for port in owned_ports):
        parser.error('Distinct assigned ports required, including Windows asyncio IPC')
    forbidden = [Path(r'C:\Users\user\Projects\Neyvia'), Path(r'C:\Users\user\Projects\Neyvia-next')]
    for supplied in (args.dist, args.obscura):
        if any(supplied.resolve().is_relative_to(path) for path in forbidden):
            parser.error('Protected tree is outside this task')
    if not args.dist.is_dir() or not args.obscura.is_file():
        parser.error('Existing built UI and installed Neyvia browser required')
    for port in owned_ports:
        with socket.socket() as candidate:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                candidate.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            candidate.bind(('127.0.0.1', port))
    sources = [*(REPO / 'src/grant_agent/cl').glob('*.py'),
               *(REPO / 'manuals/cl').glob('*.cl'), *(REPO / 'manuals').glob('*.manual.json')]
    sources += [REPO / 'src/grant_agent' / name for name in
                ('neyvia_cl.py', 'neyvia_ui_api.py', 'neyvia_gateway.py', 'neyvia_panes.py',
                 'neyvia_workspace_tools.py', 'ui_command_bus.py', 'native_tools.py',
                 'neyvia_manuals.py', 'proof_contracts.py', 'browser_obscura.py',
                 'neyvia_pdf_tools.py', 'pdf_document_worker.py')]
    if args.app_open_only:
        sources += [REPO / 'scripts/fixcl3_app_open_probe.py', REPO / 'src/grant_agent/neyvia_voice.py', REPO / 'src/grant_agent/neyvia_outputs.py']
    sources += [*sorted((REPO / 'web/src/neyvia/next').glob('Nx*Pane*.jsx')),
                REPO / 'web/src/neyvia/next/nxPaneObserve.js',
                REPO / 'web/src/neyvia/next/nxBus.js',
                REPO / 'web/src/neyvia/next/nxOsStore.js',
                REPO / 'web/src/neyvia/next/NxStage.jsx',
                REPO / 'web/src/neyvia/next/nxShellObserve.js',
                REPO / 'web/src/neyvia/next/nxFrameVisibility.js',
                REPO / 'web/src/neyvia/next/NxMobileStudio.jsx',
                REPO / 'web/src/neyvia/next/NxPhone.jsx',
                REPO / 'src/grant_agent/neyvia_mobile_studio.py',
                REPO / 'src/grant_agent/neyvia_mobile_preview_helper.js',
                REPO / 'web/src/neyvia/next/nxMobileStudio.css',
                REPO / 'web/proof/FIXCL-renderer/renderer_probe.py', Path(__file__)]
    start = hashes(sources)
    built = {path.relative_to(args.dist).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in args.dist.rglob('*') if path.is_file()}
    output_name = 'FIXCL3-renderer-pdf.json' if args.pdf_only else 'FIXCL3-app-open.json' if args.app_open_only else 'FIXCL3-renderer.json'
    output_name = output_name.replace('FIXCL3-', args.wave + '-')
    output = REPO / 'scripts/evidence' / output_name
    output.parent.mkdir(parents=True, exist_ok=True)
    attempted = REPO / '.agent_control/proofs' / ('FIXCL2-renderer-run-' + str(time.time_ns()) + '.json')
    attempted.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO / 'src'))
    import os
    os.environ['NEYVIA_BROWSER_PROOF_PORTS'] = ','.join(map(str, owned_ports))
    from grant_agent.proof_credential_guard import install
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(attempted.parent)
    install_hidden_subprocess_default()
    import playwright
    driver = Path(playwright.__file__).parent / 'driver/node.exe'
    admitted_executables = {args.obscura.resolve(), driver.resolve()}
    ipc_ports = iter(args.ipc_port)
    # Windows implements socketpair through a temporary TCP listener. Preserve
    # that mechanism while assigning its listener instead of binding port zero.
    def assigned_socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        if family not in (socket.AF_INET, socket.AF_INET6) or type != socket.SOCK_STREAM or proto != 0:
            raise ValueError('Unsupported asyncio IPC socket shape')
        address = '127.0.0.1' if family == socket.AF_INET else '::1'
        client = server = None
        with socket.socket(family, type, proto) as listener:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((address, next(ipc_ports)))
            listener.listen(1)
            try:
                client = socket.socket(family, type, proto)
                client.setblocking(False)
                try:
                    client.connect(listener.getsockname())
                except (BlockingIOError, InterruptedError):
                    pass
                client.setblocking(True)
                server, _ = listener.accept()
                if server.getsockname() != client.getpeername() or client.getsockname() != server.getpeername():
                    raise ConnectionError('Unexpected asyncio IPC peer')
                return server, client
            except BaseException:
                if server is not None: server.close()
                if client is not None: client.close()
                raise
    if sys.platform == 'win32':
        socket.socketpair = assigned_socketpair
    def audit(event, values):
        if event in {'socket.bind', 'socket.connect'}:
            address = values[1]
            if isinstance(address, tuple) and (address[0] not in {'127.0.0.1', 'localhost', '::1'} or address[1] not in owned_ports):
                raise PermissionError('Renderer proof uses only its assigned loopback ports')
        if event == 'subprocess.Popen':
            command = values[1]
            if isinstance(command, (list, tuple)):
                admitted = Path(command[0]).resolve() in admitted_executables
            else:
                admitted = any(command.startswith(subprocess.list2cmdline([str(executable)]) + ' ')
                               or command == subprocess.list2cmdline([str(executable)])
                               for executable in admitted_executables)
            pdf_commands = [[sys.executable, '-c', 'import pypdf'],
                            [sys.executable, str(REPO / 'src/grant_agent/pdf_document_worker.py')]]
            admitted = admitted or any(command == expected or command == subprocess.list2cmdline(expected)
                                        for expected in pdf_commands)
            bundle_script = str(REPO / 'scripts/build_app_sdk_runtime.mjs')
            if isinstance(command, str):
                import shlex
                bundle_argv = [value.strip('"') for value in shlex.split(command, posix=False)]
            else:
                bundle_argv = list(command)
            if (len(bundle_argv) == 3 and Path(bundle_argv[0]).resolve() == Path(shutil.which('node')).resolve()
                    and bundle_argv[1] == bundle_script
                    and Path(bundle_argv[2]).resolve().is_relative_to(REPO / '.agent_control/proofs')):
                admitted = True
            if not admitted:
                raise PermissionError('Renderer proof refuses an unowned process')
    sys.addaudithook(audit)
    spec = importlib.util.spec_from_file_location('fixcl_owned_renderer', sources[-2])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = sources[-2].read_text(encoding='utf-8')
    anchor = '        # 11. Stale heartbeat:'
    if original.count(anchor) != 1:
        raise ValueError('Renderer harness extension anchor changed')
    module.pdf_extension = pdf_extension
    extension = '        pdf_extension(receipt, checks, cl, dom, ui, session, root, service, state)\n'
    if args.app_open_only:
        from fixcl3_app_open_probe import app_open_extension
        module.app_open_extension = app_open_extension
        extension += '        app_open_extension(receipt, checks, cl, dom, ui, session, root, service, state)\n'
    extended = original.replace(anchor, extension + '\n' + anchor)
    if args.pdf_only or args.app_open_only:
        early = '        # 1. Missing ACK:'
        if extended.count(early) != 1:
            raise ValueError('Renderer PDF-only harness anchor changed')
        extended = extended.replace(early,
            '        open_ui(session())\n'
            + ('        app_open_extension(receipt, checks, cl, dom, ui, session, root, service, state)\n' if args.app_open_only else
               '        pdf_extension(receipt, checks, cl, dom, ui, session, root, service, state)\n')
            + '        raise StopIteration\n\n' + early)
    # Extend only the evidence harness; all mounted UI, owners and checks are
    # unchanged production code. Retain both script source hashes in the receipt.
    exec(compile(extended, str(sources[-2]), 'exec'), module.__dict__)
    module.PORT, module.UI_ENGINE, module.PANE_ENGINE, module.FIXTURE = ports
    # The existing production journey receives assigned ports through its globals.
    # Its mounted panes, event store, HTTP calls and ACK mechanism are unchanged.
    sys.argv = [str(sources[-2]), '--dist', str(args.dist), '--obscura', str(args.obscura),
                '--out', str(attempted)]
    failure = None
    try:
        module.main()
    except Exception as exc:
        failure = exc
    if not attempted.exists():
        if failure: raise failure
        raise RuntimeError('Renderer journey did not produce a receipt')
    proof = json.loads(attempted.read_bytes())
    proof['sourceHashesAtStart'] = start
    proof['assignedPorts'] = owned_ports
    proof['sourceHashesAtEnd'] = hashes(sources)
    proof['checks']['sourceUnchanged'] = start == proof['sourceHashesAtEnd']
    proof['builtArtifactHashes'] = built
    proof['checks']['builtArtifactUnchanged'] = built == {
        path.relative_to(args.dist).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in args.dist.rglob('*') if path.is_file()}
    proof['buildBoundary'] = 'Independent execution of Claude-supplied built artifact against current source-bound backend; no new frontend build claimed.'
    proof['diagnosticOnly'] = args.pdf_only or args.app_open_only
    proof['ok'] = failure is None and len(proof['checks']) >= (15 if args.pdf_only else 22 if args.app_open_only else 47) and all(value is True for value in proof['checks'].values())
    proof['passed'] = proof['ok']
    if failure: proof['runError'] = type(failure).__name__ + ': ' + str(failure)
    output.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'receipt': str(output), 'ok': proof['ok'], 'checks': len(proof['checks'])}))
    if failure: raise failure
    return 0 if proof['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
