"""Explicit non-stealth Obscura CDP process, with no Chromium fallback.

Each profile owns a CDP connection/worker (independent V8 isolate upstream).
User profiles are never imported. Storage exports travel only to the native
runtime in memory; they are never returned in agent observations.
"""
from __future__ import annotations

import atexit
import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout, wait
from pathlib import Path

from .perception_browser import DOM, origin
from .browser_verification import validate_expect

UA = "NeyviaAgent/1.0 (Automation; Obscura)"

# Obscura 0.2.4 advertises this Chromium-shaped CDP identity but its Worker
# constructor ignores the type option. Probe that option in an empty page;
# a newer implementation which reads it must keep its native module workers.
WORKER_CAPABILITY = r"""() => {
 let optionRead=false, worker=null;
 const url=URL.createObjectURL(new Blob(['self.onmessage=e=>self.postMessage(e.data)'],{type:'text/javascript'}));
 try {
  worker=new Worker(url,{get type(){optionRead=true;return 'module'}});
  return {typeOptionRead:optionRead,constructorCreated:true};
 } catch(error) {
  return {typeOptionRead:optionRead,constructorCreated:false,error:String(error)};
 } finally { worker?.terminate(); URL.revokeObjectURL(url); }
}"""
MODULE_WORKER_UNAVAILABLE = r"""(() => {
 const NativeWorker=globalThis.Worker;
 globalThis.Worker=new Proxy(NativeWorker,{construct(target,args,newTarget){
  if(args[1]?.type==='module') throw new DOMException(
   'This Obscura runtime does not implement module Workers; use a main-thread module fallback.',
   'NotSupportedError');
  return Reflect.construct(target,args,newTarget);
 }});
})()"""
# Whether the constructor reads `pull` says nothing about whether a read
# calls it: Neyvia's patched engine reads it lazily and its own streamed fetch
# bodies depend on it. Probe the behaviour: one read must reach the producer.
# Bridging an engine that already pulls doubles every pull and starves
# incremental bodies such as EventSource.
STREAM_CAPABILITY = r"""async () => {
 let optionRead=false, pulled=0;
 try {
  const stream=new ReadableStream({get pull(){optionRead=true;return controller=>{pulled+=1;controller.enqueue(7);controller.close()}}});
  const reader=stream.getReader();
  const result=await Promise.race([reader.read(),new Promise(resolve=>setTimeout(()=>resolve(null),500))]);
  return {pullOptionRead:optionRead,pullHonored:!!result&&result.value===7&&pulled===1,constructorCreated:!!stream};
 } catch(error) {return {pullOptionRead:optionRead,pullHonored:false,constructorCreated:false,error:String(error)}}
}"""
STREAM_PULL_BRIDGE = r"""(() => {
 const NativeStream=globalThis.ReadableStream;
 globalThis.ReadableStream=new Proxy(NativeStream,{construct(target,args,newTarget){
  const source=args[0]||{}, pull=source.pull;
  if(typeof pull!=='function')return Reflect.construct(target,args,newTarget);
  const state={closed:false,pulling:false,again:false,controller:null,started:null};
  const wrapped={...source,start(controller){
   state.controller=new Proxy(controller,{get(target,key){
    const value=Reflect.get(target,key,target);
    if(key==='close'||key==='error')return (...values)=>{state.closed=true;return value.apply(target,values)};
    return typeof value==='function'?value.bind(target):value;
   }});
   state.started=Promise.resolve(typeof source.start==='function'?source.start.call(source,state.controller):undefined);
   return state.started;
  }};
  const stream=Reflect.construct(target,[wrapped,args[1]],newTarget);
  const getReader=stream.getReader.bind(stream);
  const requestPull=async()=>{
   if(state.closed)return;
   if(state.pulling){state.again=true;return;}
   state.pulling=true;
   try {await state.started;if(!state.closed)await pull.call(source,state.controller);}
   catch(error){if(!state.closed)state.controller.error(error);}
   finally{state.pulling=false;if(state.again){state.again=false;void requestPull();}}
  };
  Object.defineProperty(stream,'getReader',{value:function(options){
   const reader=getReader(options), read=reader.read.bind(reader), cancel=reader.cancel.bind(reader);
   Object.defineProperty(reader,'read',{value:function(){const result=read();void requestPull();return result;}});
   Object.defineProperty(reader,'cancel',{value:function(reason){state.closed=true;return cancel(reason);}});
   return reader;
  }});
  return stream;
 }});
})()"""


def managed_executable():
    """Resolve the locally admitted engine; never download or select Chromium."""
    repo = Path(__file__).resolve().parents[2]
    receipt = repo / "scripts/evidence/browser-context-engine-admission.json"
    if not receipt.is_file():
        receipt = repo / "scripts/evidence/C2h-engine-admission.json"
    if not receipt.is_file():
        receipt = repo / "scripts/evidence/C2g-engine-fragment-admission.json"
    if not receipt.is_file():
        receipt = repo / "scripts/evidence/C2g-engine-admission.json"
    if not receipt.is_file():
        receipt = repo / "scripts/evidence/C2f-engine-admission.json"
    if not receipt.is_file():
        receipt = repo / "scripts/evidence/C2d-resource-proof.json"
    admission = json.loads(receipt.read_text(encoding="utf-8"))
    admitted = admission["engineBinary"]
    candidate = repo / admitted["path"]
    if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).hexdigest() != admitted["sha256"]:
        raise FileNotFoundError("The admitted local Obscura engine is absent or changed")
    if admission.get("workerBinary"):
        worker = admission["workerBinary"]
        worker_path = repo / worker["path"]
        if worker_path.parent != candidate.parent or not worker_path.is_file() or hashlib.sha256(worker_path.read_bytes()).hexdigest() != worker["sha256"]:
            raise FileNotFoundError("The admitted Obscura companion is absent or changed")
    return candidate


def connect_owned_playwright(playwright, directory, *, executable=None, port=None, local_control=False):
    """Connect Playwright's protocol client to an owned Obscura process.

    `local_control` lets the engine reach loopback addresses (its
    --allow-private-network switch). Only callers that themselves confine the
    page to an approved local Neyvia origin set it; the engine refuses private
    and internal addresses otherwise.
    """
    import socket
    from contextlib import ExitStack
    assigned = proof_ports()
    candidates = [port] if port is not None else sorted(assigned)
    selected = None
    for candidate in candidates:
        if candidate not in assigned:
            raise ValueError('Obscura port is outside the explicit proof scope')
        try:
            with socket.socket() as probe:
                if os.name == 'nt': probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind(('127.0.0.1', candidate))
            selected = candidate
            break
        except OSError:
            continue
    if selected is None:
        raise RuntimeError('No owned Obscura port is available')
    stack = ExitStack()
    try:
        engine = ObscuraEngine(Path(directory), Path(executable or os.environ.get('NEYVIA_OBSCURA_EXE') or managed_executable()), port=selected, fixtures=bool(local_control), assigned_ports=assigned)
        stack.callback(engine.close)
        browser = playwright.chromium.connect_over_cdp(engine.endpoint, headers={'Authorization': 'Bearer ' + engine.token}, timeout=15000)
        stack.callback(browser.close)
        return browser, stack
    except BaseException:
        stack.close()
        raise
READER = r"""() => {
 const rows=t=>[...t.querySelectorAll('tr')].filter(r=>r.parentElement===t||r.parentElement?.parentElement===t);
 const cells=r=>[...r.querySelectorAll('th,td')].filter(c=>c.parentElement===r);
 const all=[...document.querySelectorAll('table')];
 return {title:document.title,url:location.href,readerHtml:document.body.innerHTML,
   elements:[],totalElements:0,readerMode:true,
   tables:all.slice(0,20).map(t=>rows(t).slice(0,100).map(r=>cells(r).slice(0,100).map(c=>c.innerHTML))),
   tablesTruncated:all.length>20||all.slice(0,20).some(t=>rows(t).length>100)};
}"""



def proof_ports(extra=None):
    """Ports this process may use for local fixtures and its own engine.

    The default is the shared proof range. A caller states the ports it owns
    through NEYVIA_BROWSER_PROOF_PORTS or `extra` ("48811-48819" or a list);
    browser_ports.parse_ports applies the safety limits, so no per-track
    allowlist edit is needed.
    """
    from .browser_ports import parse_ports
    configured = os.environ.get("NEYVIA_BROWSER_PROOF_PORTS", "")
    ports = parse_ports(configured) if configured else set(range(48321, 48330))
    if extra is not None:
        ports = ports | parse_ports(extra)
    return ports


class Timeouts:
    """Request budgets derived from one caller-set page request timeout.

    The engine fetch limit and navigation limit, the engine's per-command
    watchdog and the Python-side waits must all move together: raising only
    one of them fails at the next-lowest layer (a 30 s fetch limit inside the
    engine, a 40 s wait in this module). The defaults keep the historical
    30 s request budget. `request_timeout_ms` raises it up to 15 minutes.
    """
    DEFAULT_MS, MIN_MS, MAX_MS = 30000, 1000, 900000

    def __init__(self, request_timeout_ms=None):
        if request_timeout_ms is None:
            request_timeout_ms = self.DEFAULT_MS
        if type(request_timeout_ms) is not int or not self.MIN_MS <= request_timeout_ms <= self.MAX_MS:
            raise ValueError("request_timeout_ms must be an integer from %d to %d" % (self.MIN_MS, self.MAX_MS))
        self.request_ms = request_timeout_ms
        extra = max(0, request_timeout_ms - self.DEFAULT_MS)
        self.navigation_ms = 20000 + extra
        # Playwright gives up on a navigation only after the engine's own
        # deadline has returned, so the engine ends the load (partial pages
        # included) instead of leaving its settle phase running while the
        # next command queues behind it.
        self.client_navigation_ms = self.navigation_ms + 8000
        self.command_ms = 60000 + extra
        self.call_s = (40000 + extra) / 1000

    def engine_env(self):
        return {"OBSCURA_FETCH_TIMEOUT_MS": str(self.request_ms), "OBSCURA_NAV_TIMEOUT_MS": str(self.navigation_ms),
                "OBSCURA_CDP_COMMAND_TIMEOUT_MS": str(self.command_ms), "OBSCURA_SCRIPT_DEADLINE_MS": "15000"}


ACTION = "a => {globalThis.__neyviaProjection.act(a);return {ok:true};}"
# True when the focused element is a password, card or one-time-code field.
SECRET_FOCUS = "() => {const e=document.activeElement;return !!e&&(e.type==='password'||/password|cc-number|cc-csc|one-time-code/.test(e.autocomplete||''));}"


class _GoalTimeout(Exception):
    """The observed goal did not appear before the verification deadline."""


class ProfileWorker:
    def __init__(self, endpoint, token, fixtures, directory, public_resources=False, color_scheme="light", reduced_motion="reduce", assigned_ports=None, request_timeout_ms=None, render_profile=None):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="obscura-profile")
        self.endpoint, self.token, self.fixtures = endpoint, token, fixtures
        self.public_resources = public_resources
        self.color_scheme, self.reduced_motion = color_scheme, reduced_motion
        self.assigned_ports = proof_ports(assigned_ports)
        self.timeouts = Timeouts(request_timeout_ms)
        self.public_hosts = {}
        self.browser = self.context = self.playwright = None
        self.pages = {}
        self.viewport = None
        self.pending = 0
        self.activity_lock = threading.Lock()
        self.directory = Path(directory)
        self.storage_path = self.directory / "storage.json"
        self.runtime_capabilities = {}
        self.render_profile = render_profile
        self.asset_bytes = 0

    def run(self, method, *args):
        try:
            return self.submit(method, *args).result(timeout=self.timeouts.call_s)
        except FutureTimeout:
            raise TimeoutError(f"Obscura {method} exceeded {self.timeouts.call_s:g} s; the engine thread is still busy, observe again before acting") from None

    def submit(self, method, *args):
        # A timed-out caller does not mean its CDP operation stopped. Keep the
        # worker busy until that actual future completes, including queued work.
        with self.activity_lock:
            self.pending += 1
        try:
            future = self.executor.submit(getattr(self, "_" + method), *args)
        except Exception:
            self._completed(None)
            raise
        future.add_done_callback(self._completed)
        return future

    def _completed(self, _future):
        with self.activity_lock:
            self.pending -= 1

    def idle(self):
        with self.activity_lock:
            return self.pending == 0 and not self.pages

    def _connect(self):
        if self.browser is not None:
            return
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(self.endpoint,
            headers={"Authorization": "Bearer " + self.token}, timeout=15000)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.context = self.browser.new_context(user_agent=UA, accept_downloads=False, service_workers="block",
            color_scheme=self.color_scheme, reduced_motion=self.reduced_motion,
            **({"storage_state": str(self.storage_path)} if self.storage_path.exists() else {}))
        # This advertises automation; it never hides webdriver or fingerprints.
        self.context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>true,configurable:true});")
        session = self.browser.new_browser_cdp_session()
        try:
            version = session.send("Browser.getVersion")
        finally:
            session.detach()
        probe = self.context.new_page()
        try:
            worker = probe.evaluate(WORKER_CAPABILITY)
            stream = probe.evaluate(STREAM_CAPABILITY)
        finally:
            probe.close()
        fingerprint = (version.get("product") == "Chrome/145.0.0.0" and
                    version.get("jsVersion") == "14.5.0.0" and
                    version.get("revision") == "@" + "0" * 40)
        affected = fingerprint and worker.get("constructorCreated") is True and worker.get("typeOptionRead") is False
        ignored_pull = fingerprint and stream.get("constructorCreated") is True and stream.get("pullHonored") is False
        self.runtime_capabilities = {"browserVersion": version, "workerProbe": worker,
                                     "streamProbe": stream, "moduleWorkerRejected": affected,
                                     "readableStreamPullBridged": ignored_pull}
        if affected:
            # Throw at construction so PDFjs and other callers can use their
            # actual parser fallback. No worker response or app state is mocked.
            self.context.add_init_script(MODULE_WORKER_UNAVAILABLE)
        if ignored_pull:
            # Native streams still own queues/read results. This only calls the
            # actual underlying producer's ignored pull callback on demand.
            self.context.add_init_script(STREAM_PULL_BRIDGE)
        self.context.add_init_script("globalThis.__NEYVIA_OBSCURA_CAPABILITIES__=" +
                                     json.dumps(self.runtime_capabilities, separators=(",", ":")) + ";")
        self.context.add_init_script(Path(__file__).with_name("browser_capabilities.js").read_text(encoding="utf-8"))
        if self.render_profile:
            adapter = Path(__file__).with_name("browser_render_profile.js").read_text(encoding="utf-8")
            self.context.add_init_script("(" + adapter + ")(" + json.dumps(self.render_profile) + ");")

    def _open(self, tab_id, url, reader_mode=False):
        self._connect()
        granted = origin(url)
        if granted[1] in {"localhost", "127.0.0.1", "::1"} and (not self.fixtures or granted[2] not in self.assigned_ports):
            raise ValueError("Local Obscura pages need an owner fixture grant on assigned ports")
        page = self.context.new_page()
        blocked = {}
        # Public site dependencies do not grant agent access to their documents.
        # The owner must opt in; anonymous profiles and explicit automation remain.
        def route(request):
            try:
                requested = origin(request.request.url)
                allowed = requested == granted
                # Only an explicitly owned loopback fixture page may load
                # another declared loopback fixture. Public pages cannot use
                # this grant to reach private services.
                if not allowed and self.fixtures and granted[1] in {"localhost", "127.0.0.1", "::1"}:
                    allowed = requested[1] in {"localhost", "127.0.0.1", "::1"} and requested[2] in self.assigned_ports
                if not allowed and self.public_resources and request.request.resource_type != "document":
                    hostname = requested[1]
                    if hostname not in self.public_hosts:
                        try:
                            addresses = socket.getaddrinfo(hostname, requested[2], type=socket.SOCK_STREAM)
                            self.public_hosts[hostname] = bool(addresses) and all(ipaddress.ip_address(row[4][0]).is_global for row in addresses)
                        except OSError:
                            self.public_hosts[hostname] = False
                    allowed = self.public_hosts[hostname]
                if not allowed:
                    key = f"{requested[0]}://{requested[1]}:{requested[2]}"
                    if key in blocked or len(blocked) < 30:
                        blocked[key] = blocked.get(key, 0) + 1
            except ValueError:
                allowed = False
            if allowed:
                request.continue_()
            elif self.render_profile and self.render_profile.get("allowPublicSubresources"):
                from .browser_render_assets import fetch_asset
                try:
                    status, headers, data = fetch_asset(request.request.url)
                    if self.asset_bytes + len(data) > 200_000_000:
                        raise ValueError("Render profile exceeded 200 MB total resource budget")
                    self.asset_bytes += len(data)
                    request.fulfill(status=status, headers=headers, body=data)
                except (ValueError, OSError):
                    request.abort()
            else:
                request.abort()
        page.route("**/*", route)
        if self.viewport:
            # The owner's pane is the screen: a page opened later fits it from its first frame.
            self._fit(page)
        self.pages[tab_id] = {"page": page, "origin": granted, "blocked": blocked, "readerMode": reader_mode}
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeouts.client_navigation_ms)
            if self.render_profile:
                page.evaluate("async()=>{await Promise.allSettled([...document.fonts].map(face=>face.load()));await document.fonts.ready;}")
            return self._observe(tab_id)
        except Exception as error:
            # A load deadline may leave a real, useful document. Return that
            # actual projection with the timeout visible; it is never a goal bit.
            if type(error).__module__.startswith("playwright.") and type(error).__name__ == "TimeoutError":
                try:
                    observation = self._observe(tab_id)
                    if observation.get("url", "").startswith(("http://", "https://")) and observation.get("text", "").strip():
                        observation["navigation"] = {"status": "partial_after_timeout", "error": str(error)[:1000], "goalVerified": False}
                        return observation
                except Exception:
                    pass
            page.close()
            self.pages.pop(tab_id, None)
            raise ValueError("Obscura navigation failed; no effect replay: " + str(error)[:1000]) from error

    def _dom(self, tab_id, args):
        from .neyvia_browser_dom import read_headless_dom
        observed = read_headless_dom(self.pages[tab_id]["page"], args)
        observed.update(tabId=tab_id, revision=hashlib.sha256(
            json.dumps(observed, sort_keys=True).encode()).hexdigest())
        return observed

    def _observe(self, tab_id):
        began = time.monotonic()
        page = self.pages[tab_id]["page"]
        if self.pages[tab_id].get("readerMode"):
            value = page.evaluate(READER if self.pages[tab_id].get("readerMode") else DOM)
            if self.pages[tab_id].get("readerMode"):
                # Parse only HTML read from the actual owned DOM. Obscura's
                # innerText includes script/style bodies; no page mutation or
                # second HTTP fetch is used to clean the read-only projection.
                from .native_tools import _ReadableHtmlParser
                def readable(html):
                    parser = _ReadableHtmlParser()
                    parser.feed(html)
                    parser.close()
                    return parser.readable_text()
                text = readable(value.pop("readerHtml"))
                value.update(text=text[:100000], truncated=len(text) > 100000)
                tables = [[[readable(cell) for cell in row] for row in table] for table in value["tables"]]
                value["tablesTruncated"] = value["tablesTruncated"] or any(
                    len(cell) > 4000 for table in tables for row in table for cell in row)
                value["tables"] = [[[cell[:4000] for cell in row] for row in table] for table in tables]
            secrets_in_page = page.locator('input[type="password"],input[autocomplete="one-time-code"],input[autocomplete="cc-number"],input[autocomplete="cc-csc"]').evaluate_all("es=>es.map(e=>e.value).filter(Boolean)")
            # Mask secret substrings across text/title/tables as well as field values.
            raw = json.dumps(value, ensure_ascii=False)
            for secret in sorted(set(secrets_in_page), key=len, reverse=True):
                raw = raw.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[redacted]")
            value = json.loads(raw)
            value.update(engine="obscura", readyState=page.evaluate("document.readyState"),
                         automation=page.evaluate("({userAgent:navigator.userAgent,webdriver:navigator.webdriver})"),
                         frontier=["Independent Obscura engine: long-tail web APIs, cross-origin frames and visual content are not guaranteed."])
            value["revision"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
            return value
    

        # Obscura can expose semantic controls with zero-sized layout boxes.
        # Geometry is explicitly marked; clicks target the DOM, never coordinates.
        value = page.evaluate(DOM, {"geometryRequired": False})
        # The shared snapshot masks all documents before truncation. One CDP
        # evaluation binds content, readiness and automation to the same instant.
        value.update(engine="obscura", runtimeCapabilities=self.runtime_capabilities)
        # Keep the DOM executor's semantic CAS identity; geometry can fluctuate.
        value["networkPolicy"] = {"publicResources": self.public_resources,
                                  "blockedOrigins": dict(self.pages[tab_id]["blocked"])}
        value["latencyMs"] = {"pageToCl": round((time.monotonic() - began) * 1000, 3),
            "scope": "Fresh CDP DOM evaluation through masked semantic projection; excludes navigation"}
        if self.render_profile:
            value["renderProfile"] = page.evaluate("()=>({profile:window.__neyviaRenderProfile,dark:matchMedia('(prefers-color-scheme:dark)').matches,reducedMotion:matchMedia('(prefers-reduced-motion:reduce)').matches,background:getComputedStyle(document.body).backgroundColor,scrollY,fonts:[...document.fonts].map(face=>({family:face.family,status:face.status}))})")
        return value

    def _capture(self, tab_id, raw_path=None, full_page=False):
        """Capture this existing native page; changed DOM refuses publication."""
        if raw_path is None:
            return self._view_capture(tab_id)
        from PIL import Image
        captures = self.directory.parent.parent / 'captures'
        if captures.is_symlink() or captures.is_junction():
            raise ValueError('Native captures need an ordinary owning directory')
        path = Path(raw_path).resolve()
        path.relative_to(captures.resolve())
        if path.exists() or path.is_symlink() or path.is_junction():
            raise ValueError('Browser capture never overwrites an existing artifact')
        before = self._observe(tab_id)
        page = self.pages[tab_id]['page']
        page_identity = str(id(page))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.capture.tmp')
        if temporary.exists():
            raise ValueError('Browser capture temporary subject already exists')
        protected = page.locator('input[type="password"],input[autocomplete="one-time-code"],input[autocomplete="cc-number"],input[autocomplete="cc-csc"]')
        try:
            pixels = page.screenshot(type='png', full_page=bool(full_page), mask=[protected] if protected.count() else [])
            if not pixels.startswith(b'\x89PNG\r\n\x1a\n') or len(pixels) > 32 * 1024 * 1024:
                raise ValueError('Native screenshot did not return a bounded PNG')
            with temporary.open('xb') as stream:
                stream.write(pixels)
                stream.flush()
                os.fsync(stream.fileno())
            with Image.open(temporary) as image:
                width, height = image.size
                image.verify()
            after = self._observe(tab_id)
            if before['revision'] != after['revision'] or self.pages[tab_id]['page'] is not page:
                raise ValueError('Page changed during native capture; observe and capture again')
            # Windows rename refuses an already existing destination.
            temporary.rename(path)
            return {'path':str(path),'sha256':hashlib.sha256(pixels).hexdigest(),
                    'bytes':len(pixels),'width':width,'height':height,'mime':'image/png',
                    'tabId':tab_id,'pageIdentity':page_identity,'observation':after,
                    'sourceRevision':before['revision'],'engine':'obscura'}
        finally:
            if temporary.exists():
                temporary.unlink()

    def _action(self, tab_id, args):
        validate_expect(args)
        if self.pages[tab_id].get("readerMode"):
            return {"ok": False, "status": "action_unavailable"}
        observation = self._observe(tab_id)
        if observation.get("authentication", {}).get("required"):
            return {"ok": False, "status": "auth_required", "needs": "Paul", "observation": observation}
        if args["revision"] != observation["revision"]:
            return {"ok": False, "status": "stale_projection", "observation": observation}
        row = next((e for e in observation["elements"] if str(e["id"]) == str(args["element"])), None)
        if not row or row.get("secret") or not row.get("enabled") or args["action"] not in row.get("actions", []):
            return {"ok": False, "status": "action_unavailable"}
        page = self.pages[tab_id]["page"]
        dispatched_at = time.monotonic()
        try:
            page.evaluate(ACTION, args)
        except Exception as error:
            # Navigation may destroy the context after the one dispatched effect.
            # Never replay it; only a fresh observation can confirm completion.
            if not any(term in str(error).lower() for term in ("context was destroyed", "navigation", "context is not available")):
                raise
        verification = {"verified": False, "check": "fresh_observation_unavailable"}
        after = observation
        # Wait on the actual goal across navigation, never a fixed settling sleep.
        # The old two-second timer lost submits whose document loaded in ~3s.
        predicate = "payload => { const after = (" + DOM + ")({geometryRequired:false});" + r"""
            const verification = globalThis.__neyviaProjection.verify(payload.before, after, payload.args);
            if (!payload.args.expect && ['click','submit'].includes(payload.args.action))
                verification.verified = payload.before.revision !== after.revision;
            return verification.verified ? {after, verification} : false;
        }"""
        try:
            # Poll with short synchronous evaluations. An awaited in-page wait
            # (wait_for_function) cannot be cancelled by its client timeout:
            # the engine holds the isolate until its own 30 s await limit, so
            # an action with no visible effect used to block the session for
            # 30-34 s and every later command queued behind it.
            checked = self._poll_goal(page, predicate, {"before": observation, "args": args}, 8.0)
            if checked is None:
                raise _GoalTimeout()
            after = checked["after"]
            after.update(engine="obscura", networkPolicy={"publicResources": self.public_resources,
                         "blockedOrigins": dict(self.pages[tab_id]["blocked"])})
            verification = checked["verification"]
        except Exception as error:
            if not isinstance(error, _GoalTimeout):
                raise
            try:
                after = self._observe(tab_id)
            except Exception:
                pass  # Original state is explicitly unconfirmed, never success.
        if origin(after["url"]) != self.pages[tab_id]["origin"]:
            return {"ok": False, "status": "origin_boundary", "observation": after}
        verification.update(beforeRevision=observation["revision"], afterRevision=after["revision"])
        return {"ok": verification["verified"], "status": "verified" if verification["verified"] else "effect_unconfirmed",
                "verification": verification, "observation": after,
                "latencyMs": {"actionToVerified": round((time.monotonic() - dispatched_at) * 1000, 3) if verification["verified"] else None,
                    "scope": "Single dispatch to independently verified fresh state; uncertain effects have no verified latency"}}

    @staticmethod
    def _poll_goal(page, predicate, arg, timeout_s):
        """Evaluate `predicate` every 50 ms until it returns a truthy value or the deadline passes."""
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                value = page.evaluate(predicate, arg)
            except Exception as error:
                # A navigation replaces the execution context; wait for the new one.
                if not any(term in str(error).lower() for term in ("context was destroyed", "navigation", "context is not available", "target closed")):
                    raise
                value = False
            if value:
                return value
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.05)
    def _view_capture(self, tab_id):
        """The page's pixels for the owner's agent view (never returned to the agent)."""
        page = self.pages[tab_id]["page"]
        size = page.viewport_size or {}
        try:
            image = page.screenshot(type="jpeg", quality=82)
        except Exception:
            image = page.screenshot(type="png")
        return {"image": image, "width": size.get("width"), "height": size.get("height")}

    def _navigate(self, tab_id, url):
        row = self.pages[tab_id]
        if origin(url) != row["origin"]:
            raise ValueError("Headless navigation must stay in the explicitly opened origin")
        row["page"].goto(url, wait_until="domcontentloaded", timeout=self.timeouts.navigation_ms)
        return self._observe(tab_id)

    def _reload(self, tab_id):
        self.pages[tab_id]["page"].reload(wait_until="domcontentloaded", timeout=self.timeouts.navigation_ms)
        return self._observe(tab_id)

    def _back(self, tab_id):
        self.pages[tab_id]["page"].go_back(wait_until="domcontentloaded", timeout=self.timeouts.navigation_ms)
        return self._observe(tab_id)

    def _forward(self, tab_id):
        self.pages[tab_id]["page"].go_forward(wait_until="domcontentloaded", timeout=self.timeouts.navigation_ms)
        return self._observe(tab_id)

    def _export(self, tab_id):
        page = self.pages[tab_id]["page"]
        storage = self.context.storage_state()
        storage["forms"] = page.locator("input[id],textarea[id],select[id]").evaluate_all(r"""es=>es.filter(e=>e.type!=='password' && !/password|cc-number|cc-csc|one-time-code/.test(e.autocomplete||'')).map(e=>({selector:'#'+CSS.escape(e.id),value:e.value,checked:e.checked}))""")
        storage["url"] = page.url
        storage["formsOrigin"] = page.evaluate("location.origin")
        return storage

    def _fit(self, page):
        size = self.viewport
        page.set_viewport_size({"width": size["width"], "height": size["height"]})
        if size["scale"] > 1:
            # Same CSS size, more pixels: the frame stays sharp on a high-density screen.
            session = self.context.new_cdp_session(page)
            try:
                session.send("Emulation.setDeviceMetricsOverride", {"width": size["width"], "height": size["height"],
                                                                    "deviceScaleFactor": size["scale"], "mobile": False})
            finally:
                session.detach()

    def _viewport(self, tab_id, width, height, scale=1):
        """Make the headless page the size of the owner's pane, so its frame is the page at 1:1."""
        self.viewport = {"width": int(width), "height": int(height), "scale": max(1, min(3, int(scale)))}
        page = self.pages[tab_id]["page"]
        try:
            self._fit(page)
        except Exception:  # noqa: BLE001 - a page that can't take the density still takes the size
            self.viewport["scale"] = 1
            page.set_viewport_size({"width": self.viewport["width"], "height": self.viewport["height"]})
        applied = page.viewport_size or self.viewport
        return {"width": applied.get("width"), "height": applied.get("height"), "scale": self.viewport["scale"]}

    def _frame(self, tab_id):
        page = self.pages[tab_id]["page"]
        observation = self._observe(tab_id)
        session = self.context.new_cdp_session(page)
        try:
            captured = session.send("Page.captureScreenshot", {"format": "png"})
            size = page.viewport_size or {}
            return {"dataUrl": "data:image/png;base64," + captured["data"], "url": page.url,
                    "width": size.get("width"), "height": size.get("height"), "scale": (self.viewport or {}).get("scale", 1),
                    "revision": observation["revision"], "capturedAt": time.time(), "observation": observation}
        finally:
            session.detach()

    def _input(self, tab_id, args):
        before = self._observe(tab_id)
        if before.get("authentication", {}).get("required"):
            raise ValueError("Owner sign-in is required before streamed page input")
        if args.get("revision") != before["revision"]:
            raise ValueError("Streamed input requires the current page revision")
        page = self.pages[tab_id]["page"]
        kind = args.get("kind", "click")
        if kind not in {"click", "type", "key"}:
            raise ValueError("Streamed input kind must be click, type or key")
        if kind == "click" or "x" in args or "y" in args:
            x, y = float(args.get("x", -1)), float(args.get("y", -1))
            if not 0 <= x <= 20000 or not 0 <= y <= 20000:
                raise ValueError("Streamed input coordinates must fit the headless frame")
            # A real pointer sequence at the point: pointermove, down and up.
            # It focuses the field under it, so typing needs no extra step.
            page.mouse.click(x, y)
        if kind in {"type", "key"}:
            # Keystrokes go to whatever the page focused. A secret field is
            # refused before a single key is sent, never typed and hidden.
            if page.evaluate(SECRET_FOCUS):
                raise ValueError("Streamed typing is refused in secret fields; the owner types those")
            if kind == "type":
                text = args.get("text")
                if not isinstance(text, str) or not 0 < len(text) <= 2000:
                    raise ValueError("Streamed typing needs 1 to 2000 characters of text")
                page.keyboard.type(text)
            else:
                key = args.get("key")
                if not isinstance(key, str) or not re.fullmatch(r"(?:(?:Control|Shift|Alt|Meta)\+)*(?:[A-Za-z0-9]|Enter|Tab|Escape|Backspace|Delete|Arrow(?:Up|Down|Left|Right)|Home|End|PageUp|PageDown|Space)", key):
                    raise ValueError("Streamed key needs a plain key name such as Enter or Control+A")
                page.keyboard.press(key)
        after = self._observe(tab_id)
        return {"observation": after, "verification": {"verified": before["revision"] != after["revision"],
            "check": "observed_state_changed", "beforeRevision": before["revision"], "afterRevision": after["revision"]}}

    def _close(self, tab_id):
        self.pages.pop(tab_id)["page"].close()


    def _render_input(self, tab_id, args):
        if not self.render_profile:
            raise ValueError("Synthetic browser input requires the explicit render profile")
        if args.get("type") == "wheel":
            applied = self.pages[tab_id]["page"].evaluate("args=>window.__neyviaDispatchWheel(args)", args)
            return {"ok": bool(applied), "engine": "obscura", "transport": "profile-dom-wheel", "trusted": False}
        if args.get("type") not in {"touchStart", "touchMove", "touchEnd", "touchCancel"}:
            raise ValueError("Unsupported render-profile touch input")
        applied = self.pages[tab_id]["page"].evaluate("args=>window.__neyviaDispatchTouch(args)", args)
        return {"ok": bool(applied), "engine": "obscura", "transport": "profile-dom-touch", "trusted": False}

    def _shutdown(self):
        if self.context:
            self.context.storage_state(path=str(self.storage_path))
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def close(self):
        try:
            self.run("shutdown")
        finally:
            self.executor.shutdown(wait=False, cancel_futures=True)


class ObscuraEngine:
    def __init__(self, directory, executable, *, port=48324, fixtures=False, public_resources=False, color_scheme="light", reduced_motion="reduce", assigned_ports=None, request_timeout_ms=None, render_profile=None):
        self.directory = Path(directory)
        self.executable = Path(executable).resolve()
        if not self.executable.is_file():
            raise FileNotFoundError("Configure the explicit task-local Obscura executable; no engine fallback")
        self.engine_sha256 = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        self.timeouts = Timeouts(request_timeout_ms)
        self.request_timeout_ms = request_timeout_ms
        self.assigned_ports = proof_ports(assigned_ports)
        if port not in self.assigned_ports:
            raise ValueError("Obscura needs an assigned local port; pass assigned_ports=\"low-high\" or set NEYVIA_BROWSER_PROOF_PORTS")
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", port))
        finally:
            probe.close()
        self.token = secrets.token_urlsafe(36)
        self.session_id = secrets.token_urlsafe(18)
        self.endpoint = "http://127.0.0.1:" + str(port)
        self.fixtures = fixtures
        self.public_resources = public_resources
        if not isinstance(color_scheme, str) or not isinstance(reduced_motion, str) or color_scheme not in {"light", "dark", "no-preference"} or reduced_motion not in {"reduce", "no-preference"}:
            raise ValueError("Browser preferences need an explicit supported color scheme and motion value")
        self.color_scheme, self.reduced_motion = color_scheme, reduced_motion
        if render_profile and not fixtures:
            raise ValueError("Render profiles require explicit local fixture authorization")
        self.render_profile = render_profile
        self.profiles = {}
        self._closed = False
        self.lock = threading.RLock()
        self.directory.mkdir(parents=True, exist_ok=True)
        args = [str(self.executable), "serve", "--host", "127.0.0.1", "--port", str(port), "--user-agent", UA, "--max-connections", "8"]
        if fixtures:
            args.append("--allow-private-network")
        self.args = args
        self.log = (self.directory / "engine.log").open("ab")
        self.process = subprocess.Popen(args, stdout=self.log, stderr=self.log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env={**os.environ, "OBSCURA_CDP_TOKEN": self.token, "OBSCURA_ROTATE_PROFILE": "0", **self.timeouts.engine_env()})
        atexit.register(self.close)
        import urllib.request
        for _ in range(100):
            if self.process.poll() is not None:
                raise RuntimeError("Obscura exited before CDP startup")
            try:
                request = urllib.request.Request(self.endpoint + "/json/version", headers={"Authorization": "Bearer " + self.token})
                with urllib.request.urlopen(request, timeout=0.3) as response:
                    json.load(response)
                break
            except OSError:
                time.sleep(0.1)
        else:
            self.close()
            raise TimeoutError("Obscura did not become ready")

    def run(self, profile_id, method, *args):
        if self.process.poll() is not None:
            raise RuntimeError("Obscura runtime is unavailable")
        with self.lock:
            if profile_id not in self.profiles:
                if len(self.profiles) >= 8:
                    idle = next(((key, worker) for key, worker in self.profiles.items() if worker.idle()), None)
                    if idle is None:
                        raise ValueError("Obscura profile worker limit is 8; close an active profile's tabs first")
                    key, old_worker = idle
                    # Save native storage and disconnect before admitting a new
                    # CDP connection. Active pages and pending effects never evict.
                    old_worker.close()
                    del self.profiles[key]
                self.profiles[profile_id] = ProfileWorker(self.endpoint, self.token, self.fixtures, self.directory / profile_id, self.public_resources, self.color_scheme, self.reduced_motion, self.assigned_ports, self.request_timeout_ms, self.render_profile)
            worker = self.profiles[profile_id]
            future = worker.submit(method, *args)
        try:
            return future.result(timeout=self.timeouts.call_s)
        except FutureTimeout:
            raise TimeoutError(f"Obscura {method} exceeded {self.timeouts.call_s:g} s; the engine thread is still busy, observe again before acting") from None

    def close(self):
        with self.lock:
            if self._closed:
                return
            self._closed = True
            workers = list(self.profiles.values())
            self.profiles.clear()
        # Give all owned profiles one shared grace period, rather than forty
        # seconds each. A blocked CDP worker must not strand the owned engine.
        futures = [worker.executor.submit(worker._shutdown) for worker in workers]
        try:
            wait(futures, timeout=5)
        finally:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            for worker in workers:
                worker.executor.shutdown(wait=False, cancel_futures=True)
            self.log.close()

    def status(self):
        return {"connected": self.process.poll() is None, "engine": "obscura", "stealth": False,
                "binarySha256": self.engine_sha256,
                "sessionId": self.session_id,
                "automationUserAgent": UA, "profileWorkers": len(self.profiles), "port": int(self.endpoint.rsplit(":", 1)[1]),
                "preferences": {"colorScheme": self.color_scheme, "reducedMotion": self.reduced_motion},
                "requestTimeoutMs": self.timeouts.request_ms, "assignedPorts": sorted(self.assigned_ports)}
