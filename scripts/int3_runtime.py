"""Authenticated production HTTP journeys for the INT3 integrated mechanisms."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import site
import time
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


class Client:
    def __init__(self, port, root, observations, secret):
        self.base = f"http://127.0.0.1:{port}"
        self.root = root
        self.secret = secret
        self.observations = observations
        self.browser = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, route, payload=None):
        started = time.perf_counter()
        request = urllib.request.Request(self.base + route,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Origin": self.base, "Content-Type": "application/json"})
        try:
            with self.browser.open(request, timeout=1800) as response:
                status, value = response.status, json.load(response)
        except urllib.error.HTTPError as error:
            status, value = error.code, json.loads(error.read())
        # Payloads/cookies are intentionally never retained, including login.
        safe_json = json.dumps(value).replace(self.secret, "[redacted]")
        safe_json = re.sub(r'(/api/ui/(?:scroll/download|mobile-preview)/)[A-Za-z0-9_-]+', r'\1[redacted]', safe_json)
        sanitized = json.loads(safe_json)
        if (payload or {}).get('tool') == 'neyvia.scroll.send':
            safe_result = sanitized.get('data', {}).get('result', {})
            if safe_result.get('url'):
                safe_result['url'] = self.base + '/api/ui/scroll/download/[redacted]'
            safe_result.pop('qrSvg', None)
        if (payload or {}).get('tool') == 'neyvia.scroll.preview':
            safe_result = sanitized.get('data', {}).get('result', {})
            if safe_result.get('preview', {}).get('url'):
                safe_result['preview']['url'] = '/api/ui/mobile-preview/[redacted]/'
        self.observations.append({"route": route, "method": "POST" if payload is not None else "GET",
            "tool": (payload or {}).get("tool"), "command": (payload or {}).get("command"),
            "status": status, "response": sanitized, "durationMs": round((time.perf_counter() - started) * 1000, 3)})
        return status, value

    def good(self, route, payload=None):
        status, value = self.request(route, payload)
        assert status == 200 and value.get("ok", True), (route, status, value)
        return value.get("data", value)

    def tool(self, name, arguments=None):
        value = self.good("/api/ui/tools/call", {"tool": name, "arguments": arguments or {}, "_expectedStateRoot": str(self.root)})
        assert value.get("ok") is True and value.get("status", "completed") == "completed", value
        return value["result"]

    def command(self, name, arguments=None):
        return self.good("/api/backend", {"command": name, "payload": {"_expectedStateRoot": str(self.root), **(arguments or {})}})

    def refused(self, route, payload):
        status, response = self.request(route, payload)
        value = response.get("data", response)
        assert status >= 400 or value.get("ok") is False or value.get("status") in {"failed", "denied", "blocked"}, (status, response)
        return {"httpStatus": status, "error": value.get("error"), "status": value.get("status")}

    def read_bytes(self, route, *, capability=False):
        request = urllib.request.Request(self.base + route, headers={'Origin': self.base})
        try:
            with self.browser.open(request, timeout=30) as response:
                status, body, kind = response.status, response.read(), response.headers.get('Content-Type')
        except urllib.error.HTTPError as error:
            status, body, kind = error.code, error.read(), error.headers.get('Content-Type')
        self.observations.append({'route': '/api/ui/scroll/download/[redacted]' if capability else re.sub(r'(/api/ui/mobile-preview/)[^/]+', r'\1[redacted]', route),
                                  'method': 'GET', 'status': status, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(), 'contentType': kind})
        return status, body


def workflow(client, root):
    started = time.perf_counter()
    process = subprocess.run([sys.executable, "-I", "-c", "print('INT3 real workflow action')"],
                             capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert process.returncode == 0 and process.stdout.strip() == "INT3 real workflow action"
    measurement = {"success": process.returncode == 0, "exitCode": process.returncode,
                   "stdout": process.stdout, "latencyMs": (time.perf_counter() - started) * 1000,
                   "boundary": "Actual disposable Python process; no independently scored model quality"}
    path = root / "int3-proof/workflow-process.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(measurement, sort_keys=True).encode()
    path.write_bytes(content)
    arguments = {"manual": "research", "outcomeQuality": 0, "tokens": 1,
        "evidence": {"process": {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(content).hexdigest()}},
        "report": {"events": [
            {"stage": "question", "data": {"question": "Does real executable evidence survive workflow HTTP validation and recording?"}},
            {"stage": "prior-art", "data": {"sources": [
                {"source": "workflow_manuals.py", "finding": "Requires chronological stages and hash-bound evidence."},
                {"source": "int3_runtime.py", "finding": "Records real process outcome before HTTP calls."}]}},
            {"stage": "claim", "data": {"prediction": "Host accepts matching actual process evidence", "falsifier": "Tampered digest is accepted"}},
            {"stage": "test", "data": {"receipt": "process"}},
            {"stage": "result", "data": {"supported": True, "limitations": ["No independent model outcome scoring"]}}]}}
    checked = client.tool("neyvia.workflow.check", arguments)
    assert checked["accepted"] is True and checked["fitness"] == 0
    recorded = client.tool("neyvia.workflow.record", arguments)
    persisted = Path(recorded["receipt"])
    assert persisted.is_relative_to(root) and hashlib.sha256(persisted.read_bytes()).hexdigest() == recorded["sha256"]
    library = client.tool("neyvia.workflow.details", {"query": ""})
    assert isinstance(library["patterns"], list) and library["patterns"]
    wrong_order = deepcopy(arguments)
    wrong_order["report"]["events"].reverse()
    rejected = client.tool("neyvia.workflow.check", wrong_order)
    assert rejected["accepted"] is False and rejected["errors"]
    failed_record = client.refused("/api/ui/tools/call", {"tool": "neyvia.workflow.record", "arguments": wrong_order})
    path.write_bytes(content + b" ")
    try:
        tamper = client.refused("/api/ui/tools/call", {"tool": "neyvia.workflow.check", "arguments": arguments})
    finally:
        path.write_bytes(content)
    escape = deepcopy(arguments)
    escape["evidence"]["process"]["path"] = "../outside.json"
    confined = client.refused("/api/ui/tools/call", {"tool": "neyvia.workflow.check", "arguments": escape})
    return {"record": recorded, "detailsPatterns": len(library["patterns"]), "failedOrder": rejected,
            "failedRecord": failed_record, "tamper": tamper, "pathEscape": confined}


def intent(client):
    text = "Plan the browser change, and also check the light team. No actually keep the old browser; plan only the theme. Prepare the GitHub push, we push later. You can spoon agents."
    checklist = client.tool("neyvia.intent.checklist", {"text": text})
    assert checklist["providerCalls"] == 0 and text in checklist["prompt"]
    assert checklist.get("paulManual", {}).get("applied") is True, "R2 rich Paul manual was not applied"
    assert "items" in checklist["schema"]["properties"] and "dropped" in checklist["schema"]["properties"]
    steps = [{"step": "Plan the theme change", "status": "pending"},
             {"step": "Prepare the GitHub push without publishing", "status": "pending"}]
    published = client.tool("neyvia.plan.update", {"sessionId": "int3-intent", "plan": steps})
    assert published["providerCalls"] == 0 and len(published["plan"]["items"]) == 2
    completed = deepcopy(steps)
    completed[0]["status"] = "completed"
    result = client.tool("neyvia.plan.update", {"sessionId": "int3-intent", "plan": completed})
    bad = [{"step": "First", "status": "in_progress"}, {"step": "Second", "status": "in_progress"}]
    invalid = client.refused("/api/ui/tools/call", {"tool": "neyvia.plan.update", "arguments": {"plan": bad}})
    empty = client.refused("/api/ui/tools/call", {"tool": "neyvia.intent.checklist", "arguments": {"text": ""}})
    return {"manual": checklist["paulManual"], "publication": result, "multipleActiveRefusal": invalid,
            "emptyMessageRefusal": empty, "boundary": "Actual rich-clause prompt/schema and explicitly authored two-ask plan publication. No model extraction call or intent benchmark quality claimed."}


def evolver(client, root):
    from int3_laya_proof import run
    binding = run(root)
    domain = binding["domain"]
    outcomes = {}
    for operation, arguments in [("state", {}), ("state", {"domain": domain}),
        ("lineage", {"domain": domain}), ("genome", {"domain": domain, "genome": binding["candidate"]}),
        ("receipt", {"domain": domain, "trial": 1})]:
        tool = client.tool("neyvia.evolver." + operation, arguments)
        command = client.command("evolver_" + operation + "_command", arguments)
        assert tool == command, operation
        outcomes[operation + ("-all" if not arguments else "")] = tool
    assert outcomes["receipt"]["receipt"] == binding["trial"]
    assert outcomes["lineage"]["incumbent"] == binding["candidate"]
    assert outcomes['state'] == client.good('/api/ui/evolver?domain=' + domain)
    assert outcomes['lineage'] == client.good('/api/ui/evolver', {
        'operation': 'lineage', 'domain': domain, '_expectedStateRoot': str(root)})
    guards = []
    for operation, arguments in [("state", {"domain": "missing-int3"}),
        ("receipt", {"domain": domain, "trial": True}),
        ("genome", {"domain": domain, "genome": "missing-int3"}),
        ("state", {"domain": domain, "judges": []})]:
        guards.append(client.refused("/api/backend", {"command": "evolver_" + operation + "_command", "payload": arguments}))
    guards.append(client.refused("/api/backend", {"command": "evolver_state_command",
        "payload": {"_expectedStateRoot": str(root.parent / "foreign")}}))
    guards.append(client.refused('/api/ui/evolver', {'operation': 'state',
        'domain': domain, '_expectedStateRoot': str(root.parent/'foreign')}))
    guards.append(client.refused('/api/ui/tools/call', {'tool': 'neyvia.evolver.run',
        'arguments': {'domain': domain, 'requestId': 'int3-binding-no-training'}}))
    return {"observations": outcomes, "failureGuards": guards, "bindingReceipt": "scripts/evidence/int3/runtime/laya-binding.json"}


def scroll_study(client, root):
    """Actual HTTP operations on the retained model-generated pack; no new model call."""
    from grant_agent import neyvia_scroll as owner
    archive = REPO / 'scripts/evidence/MS-runs/study'
    pack = json.loads((archive / 'pack.json').read_text(encoding='utf-8'))
    texts = json.loads((archive / 'sources.json').read_text(encoding='utf-8'))
    assert len(pack['cards']) == 54 and pack['meta']['studyFormat'] == 'paul-seven-part.v1'
    note = root / 'int3-proof/course.md'
    note.parent.mkdir(parents=True, exist_ok=True)
    assert len(texts) == 1
    note.write_bytes(next(iter(texts.values())).encode('utf-8'))
    pack_id = 'int3-study-replay'
    imported = client.tool('neyvia.scroll.import', {'paths': [str(note)], 'packId': pack_id, 'title': 'INT3 retained course replay', 'subject': 'maths'})
    assert imported['pack']['meta']['studyFormat'] == 'paul-seven-part.v1'
    replayed = client.command('scroll_import_command', {'paths': [str(note)], 'packId': pack_id, 'subject': 'maths'})
    assert replayed['replayed'] is True
    failures = {}
    failures['generationWithoutConcepts'] = client.refused('/api/ui/tools/call', {'tool': 'neyvia.scroll.generate', 'arguments': {'pack': pack_id, 'requestId': 'int3-no-concepts'}})
    failures['unknownJob'] = client.refused('/api/backend', {'command': 'scroll_job_command', 'payload': {'requestId': 'int3-missing-job'}})
    failures['unknownConceptPack'] = client.refused('/api/ui/tools/call', {'tool': 'neyvia.scroll.concepts', 'arguments': {'pack': 'int3-missing-pack'}})
    failures['importEscape'] = client.refused('/api/ui/tools/call', {'tool': 'neyvia.scroll.import', 'arguments': {'paths': ['../outside.md']}})
    # Seed through the production storage owner with the real retained result;
    # this is historical model output replay, not evidence of fresh generation.
    row = owner.load(root, pack_id)
    assert set(row['sources']['source_texts']) == set(texts)
    assert row['sources']['source_texts'] == texts
    seeded = deepcopy(pack)
    seeded['meta']['id'] = pack_id
    row['value'] = seeded
    row['value']['status'] = 'review'
    flagged = seeded['cards'][0]['id']
    row['review'] = {card['id']: {'status': 'flagged' if card['id'] == flagged else 'pending', **({'flag': 'INT3 explicit review gate'} if card['id'] == flagged else {})} for card in seeded['cards']}
    owner.save(root, row)
    historic_log = archive / 'runtime/.neyvia/scroll/ms-course/generation.jsonl'
    if historic_log.is_file():
        destination = root / '.neyvia/scroll' / pack_id / 'generation.jsonl'
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(historic_log, destination)
    args = {'pack': pack_id}
    selected = client.tool('neyvia.scroll.state', args)
    assert selected == client.command('scroll_state_command', args)
    assert selected == client.good('/api/ui/scroll?pack=' + pack_id)
    assert selected == client.good('/api/ui/scroll/state', {'operation': 'state', **args, '_expectedStateRoot': str(root)})
    failures['routeWorkspaceMismatch'] = client.refused('/api/ui/scroll', {
        'operation': 'state', **args, '_expectedStateRoot': str(root.parent/'foreign')})
    assert len(selected['active']['graph']['concepts']) == len(pack['concepts'])
    validation = client.tool('neyvia.scroll.validate', args)
    assert validation['ok'] and validation == client.command('scroll_validate_command', args)
    statistics = client.tool('neyvia.scroll.stats', args)
    assert statistics == client.command('scroll_stats_command', args) and statistics['cards'] == 54
    failures['pendingExport'] = client.refused('/api/ui/tools/call', {'tool': 'neyvia.scroll.pack', 'arguments': args})
    failures['invalidReview'] = client.refused('/api/backend', {'command': 'scroll_review_command', 'payload': {**args, 'decisions': [{'cardId': 'missing-card', 'action': 'approve'}]}})
    failures['editedId'] = client.refused('/api/ui/tools/call', {'tool': 'neyvia.scroll.review', 'arguments': {**args, 'decisions': [{'cardId': flagged, 'action': 'edit', 'card': {'id': 'replacement-id'}}]}})
    for chapter in dict.fromkeys(card['chapter'] for card in seeded['cards']):
        client.command('scroll_review_command', {**args, 'chapter': chapter, 'action': 'approve'})
    failures['flaggedExport'] = client.refused('/api/backend', {'command': 'scroll_pack_command', 'payload': args})
    reviewed = client.tool('neyvia.scroll.review', {**args, 'decisions': [{'cardId': flagged, 'action': 'approve'}]})
    assert sum(card['status'] == 'approved' for chapter in reviewed['active']['review']['chapters'] for card in chapter['cards']) == 54
    exported = client.tool('neyvia.scroll.pack', args)
    exported_path = Path(exported['path'])
    assert exported_path.is_relative_to(root) and exported['cards'] == 54
    assert hashlib.sha256(exported_path.read_bytes()).hexdigest() == exported['sha256']
    # A changed source must fail the same actual HTTP validator, then restore.
    row = owner.load(root, pack_id)
    original = deepcopy(row['sources'])
    doc = next(iter(texts))
    row['sources']['source_texts'][doc] += 'tampered source'
    owner.save(root, row)
    try:
        tamper_status, tamper_response = client.request('/api/ui/tools/call', {
            'tool': 'neyvia.scroll.validate', 'arguments': args, '_expectedStateRoot': str(root)})
        assert tamper_status == 200 and tamper_response['ok'] is False
        adverse = tamper_response['data']['result']
        assert adverse['ok'] is False and any(error['rule'] == 'source-hash' for error in adverse['errors'])
        failures['sourceTamper'] = adverse
    finally:
        restored = owner.load(root, pack_id)
        restored['sources'] = original
        owner.save(root, restored)
    assert client.tool('neyvia.scroll.validate', args)['ok']
    preview = client.tool('neyvia.scroll.preview', args)
    assert preview['preview']['ready'] and preview['preview']['mode'] == 'static'
    preview_route = preview['preview']['url']
    html_status, html = client.read_bytes(preview_route)
    assert html_status == 200 and b'load-pack.js' in html
    data_status, data = client.read_bytes(preview_route + 'generated-pack.json')
    assert data_status == 200 and len(json.loads(data)['cards']) == 54
    sent = client.tool('neyvia.scroll.send', args)
    assert sent['downloads'] == 1 and sent['lanReachable'] is False and sent['url'].startswith(client.base + '/api/ui/scroll/download/')
    route = sent['url'].removeprefix(client.base)
    status, downloaded = client.read_bytes(route, capability=True)
    assert status == 200 and hashlib.sha256(downloaded).hexdigest() == hashlib.sha256(exported_path.read_bytes()).hexdigest()
    second_status, _ = client.read_bytes(route, capability=True)
    assert second_status == 410
    # Execute the production scheduler against the exported actual model pack.
    folder = exported_path.parent
    process = subprocess.run(['node', str(REPO / 'scripts/prove_ms_study_feed.cjs'), str(folder)], cwd=REPO,
                             capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert process.returncode == 0, process.stderr[-2000:]
    feed = json.loads((folder / 'feed-proof.json').read_text(encoding='utf-8'))
    assert feed['ok'] and feed['strictEightCardLag'] and feed['supportingPartsTaught']
    return {'archivedPackSha256': hashlib.sha256((archive / 'pack.json').read_bytes()).hexdigest(), 'cards': 54,
            'validation': validation, 'stats': statistics, 'export': exported, 'feed': feed,
            'previewFilesServed': True, 'singleUseDownload': {'first': status, 'second': second_status}, 'failures': failures,
            'boundary': 'Actual authenticated import/state/validate/review/stats/export/preview/send/download routes and production feed on retained 54-card Luna output. Fresh provider generation, DOM rendering, phone installation and physical-device delivery are not claimed.'}


def inventory(tools):
    """Static route/command declarations, separately labelled from real HTTP calls."""
    routes, commands = set(), set()
    for path in (REPO / "src/grant_agent").glob("*.py"):
        if not (path.name.startswith(("web_backend", "neyvia_"))):
            continue
        source = path.read_text(encoding="utf-8")
        routes.update(re.findall(r"[\"'](/api/[^\"'\s]+)[\"']", source))
        commands.update(re.findall(r"[\"']([a-z][a-z0-9_]*_command)[\"']", source))
    return {"tools": tools, "routeDeclarations": sorted(routes), "commandDeclarations": sorted(commands),
            "boundary": "Tools are actual authenticated production catalog registrations; route/command names are static declaration inventory, not successful execution evidence."}


def wire_inventory(client, root, registered, port):
    """Exercise every advertised name's owner gate and every literal API path.

    These are transport/authority failure-path observations. Positive domain
    behavior is established separately by the production journeys and verifier.
    """
    tools = []
    for row in registered['tools']:
        status, value = client.request('/api/ui/tools/call', {
            'tool': row['name'], 'arguments': {},
            '_expectedStateRoot': str(root / 'foreign-workspace')})
        assert status == 409 and value.get('ok') is False, row['name']
        tools.append(row['name'])
    unsigned = Client(port, root, client.observations, client.secret)
    routes = []
    for route in registered['routeDeclarations']:
        status, body = unsigned.read_bytes(route)
        assert status < 500, (route, status)
        routes.append({'route': route, 'status': status, 'bytes': len(body)})
    return {'advertisedToolsAttempted': tools, 'literalRouteCalls': routes,
            'boundary': 'Actual port48651 HTTP calls: tool requests reject a foreign state root before dispatch; route requests use no login or capability. This does not claim positive execution of every registered tool or dynamic route.'}


def launch_server(port, root, secret, log):
    """Own exactly one child; refuse an occupied port instead of stopping it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    from grant_agent.proof_ports import INT3_PORT_MAP, PORT_ENV
    guard = root/'int3-child-guard'
    guard.mkdir(parents=True, exist_ok=True)
    (guard/'sitecustomize.py').write_text(
        'import os\nfrom pathlib import Path\nfrom int3_server import install_guard\n'
        'install_guard(Path(os.environ["INT3_RUNTIME_ROOT"]))\n'
        'from intcl_socketpair import install_explicit_socketpair\ninstall_explicit_socketpair()\n', encoding='utf-8')
    environment = dict(os.environ, SYNTELOS_ACCOUNT_USER="int3-proof", SYNTELOS_ACCOUNT_PASSWORD=secret,
                       NEYVIA_COORDINATOR_AUTOSTART="0", FLUXIO_WATCHDOG_AUTOSTART="0",
                       FLUXIO_RUNTIME_AUTO_UPDATE="0", NEYVIA_TOOL_AUTO_UPDATE="0",
                       PYTHON=sys.executable, NEYVIA_SYSTEM_PYTHON=sys.executable,
                       INT3_RUNTIME_ROOT=str(root),
                       NODE_OPTIONS='--require ' + str(REPO/'scripts/int3_node_guard.cjs'),
                       INT3_STRICT_PORTS='1',
                       NEYVIA_PROOF_BUILD_ROOT=str(REPO/'.agent_control/int3/build'),
                       NEYVIA_PROOF_SOCKETPAIR_PORTS='48654,48655,48656,48657,48658,48659',
                       PYTHONPATH=os.pathsep.join((str(guard), str(REPO/'scripts'), str(REPO/'src'), site.getusersitepackages())))
    environment[PORT_ENV] = json.dumps(INT3_PORT_MAP)
    temporary = root / "temporary"
    temporary.mkdir(parents=True, exist_ok=True)
    environment.update(TEMP=str(temporary), TMP=str(temporary))
    tokenizer_cache = REPO / ".agent_control/int3/dependencies/tiktoken"
    if tokenizer_cache.is_dir():
        environment["TIKTOKEN_CACHE_DIR"] = str(tokenizer_cache)
    return subprocess.Popen([sys.executable, str(REPO / "scripts/int3_server.py"), "--port", str(port), "--root", str(root)],
                            cwd=REPO, env=environment, stdout=log, stderr=subprocess.STDOUT,
                            **hidden_windows_subprocess_kwargs())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--proofs", action="store_true", help="Run merged manual verifier via real HTTP model tool")
    parser.add_argument("--proof-area", action="append")
    parser.add_argument("--reuse", action="store_true", help="Use an explicitly owned server with the same ephemeral account environment; no lifecycle control")
    parser.add_argument("--wire-inventory", action="store_true",
                        help="Call every advertised tool owner gate and every literal route without login")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.port != 48651 or not root.is_relative_to(REPO / ".agent_control/int3"):
        parser.error("INT3 proof uses explicit port48651 and task-owned root")
    if not args.reuse:
        number = len([path for path in root.glob('http-run-*') if path.is_dir()]) + 1
        root = root/f'http-run-{number:02d}'
    from int3_server import install_guard
    install_guard(root)
    secret = os.environ.get("SYNTELOS_ACCOUNT_PASSWORD") if args.reuse else secrets.token_urlsafe(32)
    if not secret:
        parser.error("--reuse requires the owning parent's ephemeral SYNTELOS_ACCOUNT_PASSWORD environment")
    observations = []
    client = Client(args.port, root, observations, secret)
    child, log = None, None
    report = {"schema": "neyvia.int3.runtime.v1", "ok": False, "port": args.port, 'workspace':str(root),
              "observations": observations, "checks": {}, "limitations": ["CPU model training absent", "Full route inventory is not blanket native-device or provider execution proof"]}
    try:
        if not args.reuse:
            root.mkdir(parents=True, exist_ok=True)
            log = (root / "int3-server.log").open("w", encoding="utf-8")
            child = launch_server(args.port, root, secret, log)
            deadline = time.monotonic() + 180
            while True:
                if child.poll() is not None:
                    raise RuntimeError("Owned backend exited during startup; inspect task-local server log")
                try:
                    client.good("/api/health")
                    break
                except urllib.error.URLError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Owned backend startup deadline expired")
                    time.sleep(.1)
        unauthorized, _ = client.request("/api/ui/tools")
        assert unauthorized == 401
        client.good("/api/auth/login", {"username": os.environ.get("SYNTELOS_ACCOUNT_USER", "int3-proof") if args.reuse else "int3-proof", "password": secret})
        client.good("/api/health")
        tools = client.good("/api/ui/tools")["tools"]
        report["registrationInventory"] = inventory(tools)
        if args.wire_inventory:
            report['checks']['wireInventory'] = wire_inventory(client, root, report['registrationInventory'], args.port)
        names = {row["name"] for row in tools}
        expected = {"neyvia.workflow.check", "neyvia.workflow.record", "neyvia.workflow.details",
                    "neyvia.evolver.state", "neyvia.evolver.lineage", "neyvia.evolver.genome", "neyvia.evolver.receipt",
                    "neyvia.intent.checklist", "neyvia.plan.update"}
        expected.update('neyvia.scroll.' + op for op in ('import', 'concepts', 'generate', 'job', 'validate', 'review', 'pack', 'preview', 'send', 'stats', 'state'))
        assert expected <= names, sorted(expected - names)
        for name, journey in [("workflow", lambda: workflow(client, root)), ("intent", lambda: intent(client)),
                              ("evolver", lambda: evolver(client, root)), ('scrollStudy', lambda: scroll_study(client, root))]:
            report["checks"][name] = journey()
            print(name + " production journey passed", flush=True)
        if args.proofs:
            assert {"neyvia.verify", "neyvia.verify.status"} <= names
            report["checks"]["manualVerifierBefore"] = client.tool("neyvia.verify.status")
            status, envelope = client.request('/api/ui/tools/call', {
                'tool': 'neyvia.verify', 'arguments': {'areas': args.proof_area} if args.proof_area else {},
                '_expectedStateRoot': str(root)})
            receipt = envelope.get('data', {})
            verification = receipt.get('result', {})
            report['checks']['manualVerifierNativeReceipt'] = {
                'httpStatus': status, 'ok': receipt.get('ok'), 'status': receipt.get('status'),
                'receiptPath': receipt.get('receipt_path')}
            report["checks"]["manualVerifier"] = verification
            assert status == 200 and verification.get('contractsOk') is True, (
                'Merged manual self-checks failed; inspect retained manualVerifier report')
            if not verification.get("complete"):
                report["limitations"].append("Manual verifier reports remaining migration frontier")
        report["ok"] = True
    except Exception as error:
        report["failure"] = {"type": type(error).__name__, "message": str(error).replace(secret, "[redacted]")[:3000]}
        raise
    finally:
        if child is not None:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=15)
            report["ownedServer"] = {"pid": child.pid, "exitCode": child.returncode, "stopped": child.poll() is not None}
        if log is not None:
            log.close()
        report["checkedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report["sourceSha256"] = {name: hashlib.sha256((REPO / "scripts" / name).read_bytes()).hexdigest()
                                   for name in ("int3_server.py", "int3_runtime.py", "int3_laya_proof.py")}
        destination = REPO / "scripts/evidence/int3/runtime/http-journeys.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        number = len(list(destination.parent.glob('http-attempt-*.json'))) + 1
        attempt = destination.parent/f'http-attempt-{number:02d}.json'
        attempt.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
