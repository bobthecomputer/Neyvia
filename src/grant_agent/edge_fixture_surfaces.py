"""Generative presentation-model and local control fixtures.

Node calls the actual frontend reducers with observed state assertions. This
proves the model claims named by those contracts, never rendered UI, focus,
pixels, native interaction or remote browser behavior.
"""
from __future__ import annotations
from .subprocess_utils import hidden_windows_subprocess_kwargs

import base64
import hashlib
import json
import os
import subprocess
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

TEXTS = {"empty": "", "huge": "long " * 14000, "unicode": "雪🙂e\u0301\u202e العربية"}
LAYOUT = {"layout." + name for name in ("normalizeLayout", "moveRegion", "nudgeRegion", "setWidth", "keyWidth", "sideOf", "fitLayout", "moveWidget", "nudgeWidget", "cycleWidgetSize", "removeWidget", "addWidget", "hiddenWidgets")}
EMBED = {"embed." + name for name in ("host", "open", "mount", "collapse", "focus", "expand", "fullscreen", "restore", "visible", "close")}
QUESTIONS = {"control.questions-durable", "control.questions-session", "control.questions-immutable"}
PURE = {"control.approval-policy", "control.approval-description", "control.context-budget", "control.context-compaction", "control.chrome-policy", "control.chrome-grant", "d-ui.ocr-quality", "d-ui.ocr-route", "sv.suite.summary"}
LOCAL = {"control.attachments-content", "control.attachments-message", "sv.suite.artifacts"}

NODE = r'''
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const [repo,category]=process.argv.slice(1);
const l=await import(pathToFileURL(path.join(repo,'web/src/neyvia/next/nxLayoutModel.js')));
const e=await import(pathToFileURL(path.join(repo,'web/src/neyvia/neyviaEmbeddedWorkspace.js')));
const text=category==='empty'?'':category==='huge'?'long '.repeat(14000):'雪🙂e\u0301\u202e العربية';
const rows=[];
function record(id,fn){try{fn();rows.push({contract:id,status:'passed',detail:'Actual exported reducer executed; independent state conservation/assertions passed.'})}catch(error){rows.push({contract:id,status:'failed',detail:String(error.stack||error)})}}
if(category!=='permissions'){
const source={order:[text,'panel','panel'],widths:{sidebar:-900,panel:900000,[text]:20},canopy:text,dock:text,widgets:[{id:text,size:text},{id:'usage',size:text},{id:'usage',size:'s'}]};
let model=l.normalizeLayout(source);
record('layout.normalizeLayout',()=>{assert.equal(new Set(model.order).size,4);assert.deepEqual([...model.order].sort(),[...l.REGIONS].sort());assert.equal(model.widths.sidebar,220);assert.equal(model.widths.panel,600);assert.deepEqual(model.widgets,[{id:'usage',size:'s'}]);assert.equal(model.dock,'right');});
model=l.normalizeLayout({widths:{sidebar:300,panel:440},widgets:[{id:'usage',size:'s'},{id:'projects',size:'m'}]});
const original=JSON.stringify(model);
record('layout.moveRegion',()=>{let result=l.moveRegion(model,'panel',-99999);assert.equal(result.order[0],'panel');assert.deepEqual(result.widths,model.widths);assert.equal(JSON.stringify(model),original);assert.equal(l.moveRegion(model,'panel',99999).order.at(-1),'panel');});
record('layout.nudgeRegion',()=>{assert.equal(l.nudgeRegion(model,'sidebar',99999).order.at(-1),'sidebar');assert.deepEqual(l.nudgeRegion(model,text,1),model);});
record('layout.setWidth',()=>{for(const [id,[minimum,maximum]] of Object.entries(l.LIMITS)){let result=l.setWidth(model,id,-99999);assert.equal(result.widths[id],minimum);assert.equal(l.setWidth(model,id,99999).widths[id],maximum);assert.deepEqual(result.order,model.order);}assert.equal(JSON.stringify(model),original);});
record('layout.keyWidth',()=>{assert.equal(l.keyWidth('sidebar',300,'ArrowRight'),316);assert.equal(l.keyWidth('sidebar',300,'ArrowLeft',true),252);assert.equal(l.keyWidth('sidebar',300,'Home'),220);assert.equal(l.keyWidth('sidebar',300,'End'),440);assert.equal(l.keyWidth('sidebar',300,text),null);});
record('layout.sideOf',()=>{for(const order of [model.order,[...model.order].reverse()])for(const id of ['sidebar','canopy','panel'])assert.equal(l.sideOf(order,id),order.indexOf(id)<order.indexOf('main')?'start':'end');});
record('layout.fitLayout',()=>{const config={present:{sidebar:true,panel:true,canopy:true},defaults:{sidebar:300,panel:440,canopy:300,dock:440}};for(const viewport of [0,600,1000,1800,100000]){const fit=l.fitLayout(model,{...config,viewport});assert.ok(fit.widths.sidebar>=220);assert.ok(fit.widths.panel>=300);if(viewport===1800)assert.deepEqual(fit.dropped,[]);if(viewport===0)assert.equal(fit.floatPanel,true);}assert.equal(JSON.stringify(model),original);});
record('layout.moveWidget',()=>{let result=l.moveWidget(model,'usage','projects');assert.deepEqual(result.widgets.map(x=>x.id),['projects','usage']);assert.deepEqual(result.widths,model.widths);assert.deepEqual(l.moveWidget(model,text,'projects'),model);});
record('layout.nudgeWidget',()=>{assert.deepEqual(l.nudgeWidget(model,'usage',99999).widgets.map(x=>x.id),['projects','usage']);assert.deepEqual(l.nudgeWidget(model,text,1),model);});
record('layout.cycleWidgetSize',()=>{const result=l.cycleWidgetSize(model,'usage');assert.equal(result.widgets[0].size,'m');assert.deepEqual(result.widgets[1],model.widgets[1]);assert.equal(l.cycleWidgetSize(result,'usage').widgets[0].size,'s');});
record('layout.removeWidget',()=>{assert.deepEqual(l.removeWidget(model,'usage').widgets,[model.widgets[1]]);assert.deepEqual(l.removeWidget(model,text),model);});
record('layout.addWidget',()=>{let result=l.addWidget(l.removeWidget(model,'usage'),'usage');assert.equal(result.widgets.filter(x=>x.id==='usage').length,1);assert.deepEqual(l.addWidget(result,'usage'),result);assert.deepEqual(l.addWidget(model,text),model);});
record('layout.hiddenWidgets',()=>{assert.deepEqual(l.hiddenWidgets(model).sort(),Object.keys(l.WIDGETS).filter(id=>!['usage','projects'].includes(id)).sort());assert.equal(JSON.stringify(model),original);});
}
if(category==='permissions'){
e.registerEmbeddedAdapter({id:'fixture-permission',requiredPermissions:['fixture.read'],retainsState:true,presentations:['inline-card','fullscreen']});
const denied=e.createEmbeddedWorkspace({adapterId:'fixture-permission',permissions:{grants:[]},context:{artifactId:'fixture'}});
record('embed.host',()=>{const host=e.createEmbeddedWorkspaceHost();assert.deepEqual(host.workspaces,[]);assert.equal(host.focusedId,null);});
record('embed.collapse',()=>{const h=e.openEmbeddedWorkspace(e.createEmbeddedWorkspaceHost(),denied);const result=e.collapseEmbeddedWorkspace(h,denied.workspaceId);assert.equal(result.workspaces[0].state,'blocked');assert.equal(result.focusedId,null);assert.equal(e.shouldMountEmbeddedWorkspace(result,denied.workspaceId),false);});
record('embed.focus',()=>{const h=e.openEmbeddedWorkspace(e.createEmbeddedWorkspaceHost(),denied);const result=e.focusEmbeddedWorkspace(h,denied.workspaceId);assert.equal(result.workspaces[0].state,'blocked');assert.equal(result.focusedId,null);assert.equal(e.shouldMountEmbeddedWorkspace(result,denied.workspaceId),false);});
record('embed.fullscreen',()=>{const h=e.openEmbeddedWorkspace(e.createEmbeddedWorkspaceHost(),denied);assert.equal(e.fullscreenEmbeddedWorkspace(h),null);});
record('embed.close',()=>{const h=e.openEmbeddedWorkspace(e.createEmbeddedWorkspaceHost(),denied);const result=e.closeEmbeddedWorkspace(h,denied.workspaceId,'missing adapter grant');assert.equal(result.workspaces[0].state,'closed');assert.equal(result.focusedId,null);assert.deepEqual(result.workspaces[0].contentRef,denied.contentRef);});
record('embed.open',()=>{const h=e.openEmbeddedWorkspace(e.createEmbeddedWorkspaceHost(),denied);assert.equal(h.workspaces[0].state,'blocked');assert.equal(h.focusedId,null);assert.equal(e.shouldMountEmbeddedWorkspace(h,denied.workspaceId),false);});
record('embed.mount',()=>{const h=e.openEmbeddedWorkspace(e.createEmbeddedWorkspaceHost(),denied);assert.equal(e.shouldMountEmbeddedWorkspace(h,denied.workspaceId),false);});
record('embed.visible',()=>{const h=e.openEmbeddedWorkspace(e.createEmbeddedWorkspaceHost(),denied);assert.deepEqual(e.visibleEmbeddedWorkspaces(h),[]);});
record('embed.expand',()=>{const h=e.openEmbeddedWorkspace(e.createEmbeddedWorkspaceHost(),denied);const expanded=e.expandEmbeddedWorkspace(h,denied.workspaceId,'fullscreen');assert.equal(expanded.workspaces[0].state,'blocked','expansion must not acquire a missing adapter grant');assert.equal(e.shouldMountEmbeddedWorkspace(expanded,denied.workspaceId),false);});
record('embed.restore',()=>{const h=e.openEmbeddedWorkspace(e.createEmbeddedWorkspaceHost(),denied);const restored=e.restoreEmbeddedWorkspace(h,denied.workspaceId);assert.equal(restored.workspaces[0].state,'blocked','restoration must not acquire a missing adapter grant');assert.equal(e.shouldMountEmbeddedWorkspace(restored,denied.workspaceId),false);});
} else {
let host=e.createEmbeddedWorkspaceHost({retainedLimit:2});
const rec=e.createEmbeddedWorkspace({adapterId:'runtime-window',title:text,parentSessionId:'session'+text,parentMissionId:'mission'+text,originEventId:'event'+text,originInvocationId:'invocation'+text,contentRef:{path:'file'+text},context:{artifactId:'artifact'+text},presentation:'dock-right'});
record('embed.host',()=>{assert.deepEqual(host.workspaces,[]);assert.equal(host.retainedLimit,2);});
host=e.openEmbeddedWorkspace(host,rec);
record('embed.open',()=>{let duplicate=e.openEmbeddedWorkspace(host,e.createEmbeddedWorkspace({...rec,context:rec.context,presentation:'dock-right'}));assert.equal(duplicate.workspaces.length,1);assert.equal(duplicate.workspaces[0].workspaceId,rec.workspaceId);assert.deepEqual(duplicate.workspaces[0].lineage,rec.lineage);let crowded=host;for(let i=0;i<(category==='huge'?1000:4);i++)crowded=e.openEmbeddedWorkspace(crowded,e.createEmbeddedWorkspace({adapterId:'runtime-window',context:{artifactId:String(i)}}));assert.equal(crowded.workspaces.filter(x=>e.isEmbedRetained(x.state)).length,2);});
record('embed.mount',()=>{assert.equal(e.shouldMountEmbeddedWorkspace(host,rec.workspaceId),true);assert.equal(e.shouldMountEmbeddedWorkspace(e.collapseEmbeddedWorkspace(host,rec.workspaceId),rec.workspaceId),true);assert.equal(e.shouldMountEmbeddedWorkspace(e.closeEmbeddedWorkspace(host,rec.workspaceId),rec.workspaceId),false);});
record('embed.collapse',()=>{const next=e.collapseEmbeddedWorkspace(host,rec.workspaceId);assert.equal(next.workspaces[0].state,'collapsed');assert.equal(next.focusedId,null);assert.deepEqual(next.workspaces[0].contentRef,rec.contentRef);assert.deepEqual(next.workspaces[0].lineage,rec.lineage);});
record('embed.focus',()=>{const next=e.focusEmbeddedWorkspace(e.collapseEmbeddedWorkspace(host,rec.workspaceId),rec.workspaceId);assert.equal(next.workspaces[0].state,'open');assert.equal(next.focusedId,rec.workspaceId);});
record('embed.expand',()=>{let next=e.expandEmbeddedWorkspace(host,rec.workspaceId,'fullscreen');assert.equal(next.workspaces[0].presentation,'fullscreen');assert.equal(next.workspaces[0].restorePresentation,'dock-right');});
record('embed.fullscreen',()=>{let next=e.expandEmbeddedWorkspace(host,rec.workspaceId);assert.equal(e.fullscreenEmbeddedWorkspace(next).workspaceId,rec.workspaceId);assert.equal(e.fullscreenEmbeddedWorkspace(host),null);});
record('embed.restore',()=>{let next=e.restoreEmbeddedWorkspace(e.expandEmbeddedWorkspace(host,rec.workspaceId),rec.workspaceId);assert.equal(next.workspaces[0].presentation,'dock-right');assert.deepEqual(next.workspaces[0].context,rec.context);});
record('embed.visible',()=>{assert.equal(e.visibleEmbeddedWorkspaces(host,{parentSessionId:rec.parentSessionId}).length,1);assert.equal(e.visibleEmbeddedWorkspaces(host,{parentSessionId:'foreign'}).length,0);});
record('embed.close',()=>{let next=e.closeEmbeddedWorkspace(host,rec.workspaceId,text);assert.equal(next.workspaces[0].state,'closed');assert.equal(next.focusedId,null);assert.deepEqual(e.pruneClosedWorkspaces(next).workspaces,[]);});
}
console.log(JSON.stringify(rows));
'''


def _check(value, message):
    if not value:
        raise AssertionError(message)


def _refuses(fn):
    try:
        fn()
    except (ValueError, PermissionError, OSError):
        return
    raise AssertionError("Invalid or foreign operation was accepted")


def _python_env():
    return {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]) + os.pathsep + os.environ.get("PYTHONPATH", "")}


def _questions(root, category):
    from . import agent_questions as q
    path = root / ".agent_control/agent_questions.json"
    if category == "empty":
        for session, question in (("", "question"), ("session", "")):
            _refuses(lambda: q.request_question(root, session, question))
        _check(q.list_questions(root) == [], "invalid request changed store")
        text = "Valid question after empty refusal"
    if category == "huge":
        _refuses(lambda: q.request_question(root, "session", "x" * 1001))
        _refuses(lambda: q.request_question(root, "session", "question", options=["x"] * 4))
        text = "x" * 1000
    elif category != "empty":
        text = TEXTS.get(category, "A real owned question")
    if category == "concurrency":
        gate = Barrier(6)
        def competing(_):
            gate.wait()
            return q.request_question(root, "session", text, conversation_id="conversation")
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(competing, range(6)))
        _check(len({row["questionId"] for row in rows}) == 1, "duplicate pending question after race")
        row = rows[0]
    elif category == "interrupted":
        code = "import os,sys;from pathlib import Path;from grant_agent.agent_questions import request_question;request_question(Path(sys.argv[1]),'session','A real owned question',conversation_id='conversation');os._exit(23)"
        result = subprocess.run([sys.executable, "-c", code, str(root)], timeout=40, capture_output=True, env=_python_env(), **hidden_windows_subprocess_kwargs())
        _check(result.returncode == 23, "owned worker did not reach durable write then interrupt")
        row = q.list_questions(root, "session")[0]
    else:
        row = q.request_question(root, "session", text, conversation_id="conversation")
    before = path.read_bytes()
    if category == "empty":
        _refuses(lambda: q.answer_question(root, row["questionId"], ""))
        _check(path.read_bytes() == before, "empty answer mutated question")
    if category == "huge":
        _refuses(lambda: q.answer_question(root, row["questionId"], "x" * 12001))
        _check(path.read_bytes() == before, "oversized answer mutated question")
    _refuses(lambda: q.request_question(root, "session", "conflicting pending question"))
    _check(path.read_bytes() == before, "refused pending conflict mutated store")
    _check(q.list_questions(root, "foreign") == [], "question session leak")
    if category == "permissions":
        _refuses(lambda: q.answer_question(root, row["questionId"], "answer", conversation_id="foreign"))
        _check(path.read_bytes() == before, "foreign conversation changed question")
    answer = "x" * 12000 if category == "huge" else text or "answer"
    answered = q.answer_question(root, row["questionId"], answer, conversation_id="conversation")
    _check(json.loads(path.read_text(encoding="utf-8")) == [answered], "durable answer differs returned row")
    _check(q.list_questions(root) == [], "answered row still pending")
    before = path.read_bytes()
    _check(q.answer_question(root, row["questionId"], answer) == answered, "idempotent answer changed identity")
    _refuses(lambda: q.answer_question(root, row["questionId"], answer + "changed"))
    _check(path.read_bytes() == before, "immutable answer changed bytes")


def _offline(root, name):
    # Socket denial stays in a child so it cannot alter other fixture families.
    # The local feature must still persist/reopen without creating a socket.
    code = "import socket,sys;from pathlib import Path;from grant_agent.edge_fixture_surfaces import FAMILIES;\nclass DeniedSocket(socket.socket):\n def __new__(cls,*a,**k):raise OSError('owned offline fixture blocks network')\nsocket.socket=DeniedSocket\ntry:socket.create_connection(('127.0.0.1',48741),timeout=.1)\nexcept OSError:pass\nelse:raise AssertionError('network denial failed')\nFAMILIES[sys.argv[2]][1](Path(sys.argv[1]),'unicode')"
    result = subprocess.run([sys.executable, "-c", code, str(root), name], timeout=90, capture_output=True, env=_python_env(), **hidden_windows_subprocess_kwargs())
    _check(result.returncode == 0, "offline worker failed: " + result.stderr.decode(errors="replace")[-2000:])


def _approval(root, category):
    from .approval_modes import SessionApprovals, evaluate, describe_modes, MODES, ALWAYS_ASK, ROUTINE
    text = TEXTS.get(category, "fixture")
    descriptions = describe_modes()
    _check(all(mode in json.dumps(descriptions) for mode in MODES), "mode missing from description")
    for mode in MODES:
        session = SessionApprovals(mode=mode)
        for name in ALWAYS_ASK:
            action = {"category": name, "target": text}
            denied = evaluate(action, session)
            _check(not denied.allowed, "protected category allowed without exact grant")
            session.grant(denied, granted_by="owned-fixture")
            _check(evaluate(action, session).allowed, "exact action grant refused")
            _check(not evaluate({**action, "target": text + "different"}, session).allowed, "cross-action grant replay")
        for name in ROUTINE:
            _check(evaluate({"category": name, "target": text}, session).allowed == (mode != "ask"), "routine mode decision differs")
        first = {"category": "read", "mcpServer": "owned-fixture" + text}
        _check(not evaluate(first, session).allowed, "untrusted server allowed")
        session.trust_server(first["mcpServer"])
        _check(evaluate(first, session).allowed == (mode != "ask"), "trusted server routine decision differs")
    _check(SessionApprovals().mode == "safe", "approve-all leaked across sessions")


def _context(root, category):
    from .context_manager import ContextWindowManager
    text = TEXTS.get(category, "fixture")
    manager = ContextWindowManager(max_tokens=100)
    manager.record("user", text)
    manager.record("assistant", "owned activity")
    manager.record("user", text + "second")
    _check(manager.used_tokens == sum(max(1, len(event.content) // 4) for event in manager.events), "token accounting mismatch")
    compact = manager.compact_window()
    _check(compact[:2] == [{"role": "user", "content": text}, {"role": "user", "content": text + "second"}], "compaction changed exact user text")
    _check("events=1" in compact[-1]["content"], "activity marker missing")
    for tokens, expected in ((0, "ok"), (70, "warn"), (85, "rollover"), (95, "hard_stop")):
        m = ContextWindowManager(100)
        m.record("user", "a" * (tokens * 4)) if tokens else None
        _check(m.status() == expected, "threshold status differs")


def _attachments(root, category):
    from .connected_sessions.attachments import save_files, with_files, AttachmentError, MAX_FILES
    text = TEXTS[category]
    data = text.encode("utf-8")
    if category == "empty":
        _check(save_files([], root) == [], "empty attachments returned paths")
    if category == "huge":
        _refuses(lambda: save_files([{"name": "x", "data": ""}] * (MAX_FILES + 1), root))
        _check(not list(root.iterdir()), "oversized count left partial attachment")
    raw = [{"name": "../../" + text + ".txt", "data": base64.b64encode(data).decode()}]
    paths = save_files(raw, root)
    _check(len(paths) == 1 and paths[0].parent.resolve() == root.resolve(), "attachment escaped owned folder")
    _check(paths[0].read_bytes() == data, "attachment content differs")
    _check(paths[0].name.startswith(hashlib.sha256(data).hexdigest()[:16]), "path not content addressed")
    _check(save_files(raw, root) == paths and len(list(root.iterdir())) == 1, "retry duplicated attachment")
    result = with_files(text, paths)
    _check(str(paths[0]) in result and (text.rstrip() in result if text else result.startswith("Look at")), "attachment message lost authored text or path")


def _suite(root, category):
    from .suite_report import build_suite_summary, write_suite_artifacts
    text = TEXTS[category]
    count = {"empty": 0, "huge": 3000, "unicode": 5}[category]
    # One huge authored field plus a large list, bounded below 2 MiB total;
    # repeating the huge field in every row would measure allocation instead.
    rows = [{"preset": (text if i == 0 else text[:128]) + str(i), "training_comparison": {"score_delta": i - 5}, "probe": {"resistance_score": i, "status": "pass" if i % 2 else "fail"}} for i in range(count)]
    summary = build_suite_summary(rows)
    _check(summary["preset_count"] == count and summary["presets"] == [r["preset"] for r in rows], "suite summary loses input identity/count")
    _check(summary["probe_pass_rate"] == (round(sum(i % 2 for i in range(count)) / count * 100, 1) if count else 0), "pass denominator differs")
    result = write_suite_artifacts(root, "owned-suite", rows, summary)
    _check(json.loads(Path(result["suite_json_path"]).read_text(encoding="utf-8")) == {"summary": summary, "results": rows}, "suite JSON differs supplied evidence")
    report = Path(result["suite_report_path"]).read_text(encoding="utf-8")
    _check(all(r["preset"] in report for r in rows), "human report omits preset")


def _ocr(root, category):
    from .ocr_benchmark import character_error_rate, word_error_rate, score_ocr_sample, aggregate_scores, select_ocr_route, OcrPageSignals, normalize_ocr_text
    text = TEXTS[category]
    # Distance is quadratic: a huge equal corpus exercises 70k normalization,
    # while bounded 128-character differing samples exercise distance itself.
    equal = text[:128] if category == "huge" else text
    _check(normalize_ocr_text(text) == unicodedata.normalize("NFKC", text).strip(), "normalization differs Unicode-normalized equal corpus")
    if category == "huge":
        # The real metric sees the entire huge corpus. An empty reference makes
        # the independently known insertion distance linear, avoiding a fixture
        # that spends hours on the implementation's quadratic equal-text path.
        _check(character_error_rate("", text) == len(text.strip()), "huge character insertion distance/denominator differs")
        _check(word_error_rate("", text) == len(text.split()), "huge word insertion distance/denominator differs")
    _check(character_error_rate(equal, equal) == 0 and word_error_rate(equal, equal) == 0, "normalized equality nonzero error")
    samples = [score_ocr_sample(reference_text=equal, hypothesis_text=equal, latency_ms=12, peak_vram_mb=20), score_ocr_sample(reference_text=equal, hypothesis_text="different", latency_ms=14, peak_vram_mb=30)]
    actual = aggregate_scores(samples)
    _check(actual["samples"] == 2 and actual["meanLatencyMs"] == 13 and actual["peakVramMb"] == 30, "aggregate changes observations or denominator")
    _check(actual["meanCharacterErrorRate"] == round(sum(s["characterErrorRate"] for s in samples) / 2, 8), "aggregate quality differs sample mean")
    native = select_ocr_route(OcrPageSignals(native_text_characters=100, gpu_available=False))
    _check(native["engine"] == "native-pdf", "native text did not select native route")
    for signals, expected in ((OcrPageSignals(prefer_fast_full_page=True), "glm-ocr-bf16"), (OcrPageSignals(contains_table=True), "paddleocr-vl-1.6"), (OcrPageSignals(), "pp-ocrv6-medium"), (OcrPageSignals(gpu_available=False), "tesseract-fallback")):
        _check(select_ocr_route(signals)["engine"] == expected, "automatic route differs availability/layout")
    _refuses(lambda: select_ocr_route(OcrPageSignals(requested_engine=text or "unknown")))


def _chrome(root, category):
    from .connected_chrome_policy import assess, ensure_approved, grant_approval, ApprovalRequired
    text = TEXTS.get(category, "fixture")
    page = "https://fixture.invalid/" + text
    routine = assess({"kind": "navigate", "url": page}, label="delete", page_url=page)
    _check(not routine.requires_approval, "routine navigation became consequential")
    for label, expected in (("Delete " + text, "destructive"), ("Launch " + text, "consequential"), ("", "consequential")):
        result = assess({"kind": "click", "x": 1, "y": 2}, label=label, page_url=page)
        _check(result.risk == expected and result.requires_approval, "control risk misclassified")
        try:
            ensure_approved(result, None)
        except ApprovalRequired:
            pass
        else:
            raise AssertionError("unapproved consequential action accepted")
        grant = grant_approval(result, granted_by="owned-fixture")
        ensure_approved(result, grant)
        changed = assess({"kind": "click", "x": 3, "y": 2}, label=label, page_url=page)
        try:
            ensure_approved(changed, grant)
        except ApprovalRequired:
            pass
        else:
            raise AssertionError("cross-action browser approval replayed")


def _plan(root, category):
    from .connected_sessions.plan import apply_op, MAX_ITEMS
    text = TEXTS[category]
    items = [{"id": str(i), "text": text + str(i), "status": "pending"} for i in range(MAX_ITEMS if category == "huge" else 4)]
    plan = apply_op(None, {"op": "replace", "items": items, "source": "owned-fixture"}, at="first", seq=1)
    _check(plan["items"] == items and plan["throughSeq"] == 1, "plan replacement loses ordered identity")
    updated = apply_op(plan, {"op": "update", "id": "1", "status": "completed", "source": "owned-fixture"}, at="second", seq=2)
    _check(updated["items"][1]["status"] == "completed" and updated["items"][0] == items[0], "plan update changes unrelated tasks")
    _check(plan["items"] == items, "plan mutation changed original snapshot")
    _check(updated["throughSeq"] == 2 and updated["updatedAt"] == "second", "plan transition loses time/sequence")
    _check(apply_op(updated, {"op": "replace", "items": [], "source": "owned-fixture"}) is None, "empty replacement did not clear plan")


def _prompts(root, category):
    from unittest.mock import patch
    # Honor the production configuration seam while confining every write to
    # the owned fixture; never inherit an operator's configured shared store.
    with patch.dict(os.environ, {"NEYVIA_AGENT_PROMPT_FILE": str((root / ".agent_control/agent_prompts.json").resolve())}):
        return _prompts_owned(root, category)


def _prompts_owned(root, category):
    from . import agent_prompt_library as p
    path = root / ".agent_control/agent_prompts.json"
    current = p.load_prompt_library(root)
    text = TEXTS.get(category, "authored prompt")
    if category == "empty":
        _refuses(lambda: p.save_prompt_library(root, {"common": {"instructions": ""}}, 0))
        _check(not path.exists(), "invalid empty prompt created durable file")
        text = "valid after empty refusal"
    if category == "huge":
        _refuses(lambda: p.save_prompt_library(root, {"common": {"instructions": "x" * 100001}}, 0))
        _check(not path.exists(), "oversized prompt created durable file")
        text = "x" * 100000
    payload = {"common": {"instructions": text}, "roles": {role: {"instructions": role + " " + text[:200]} for role in p.ROLES}}
    if category == "concurrency":
        gate = Barrier(6)
        def race(_):
            gate.wait()
            try:
                return p.save_prompt_library(root, payload, 0)
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            attempts = list(pool.map(race, range(6)))
        _check(sum(row is not None for row in attempts) == 1, "prompt CAS had multiple winners")
        saved = next(row for row in attempts if row is not None)
    elif category == "interrupted":
        code = "import os,sys;from pathlib import Path;from grant_agent.agent_prompt_library import save_prompt_library;save_prompt_library(Path(sys.argv[1]),{'common':{'instructions':'authored prompt'}},0);os._exit(23)"
        result = subprocess.run([sys.executable, "-c", code, str(root)], timeout=40, capture_output=True, env=_python_env(), **hidden_windows_subprocess_kwargs())
        _check(result.returncode == 23, "prompt worker did not reach durable write then interrupt")
        saved = p.load_prompt_library(root)
    else:
        saved = p.save_prompt_library(root, payload, current["revision"])
    _check(saved["revision"] == 1 and p.load_prompt_library(root) == saved, "reopened prompt differs returned revision/state")
    for role in p.ROLES:
        authored = saved["common"]["instructions"] + "\n\n" + saved["roles"][role]["instructions"] if category != "interrupted" else saved["common"]["instructions"]
        _check(saved["hashes"][role] == hashlib.sha256(authored.encode()).hexdigest(), "composed prompt hash differs exact text")
    before = path.read_bytes()
    _refuses(lambda: p.save_prompt_library(root, payload, 0))
    _check(path.read_bytes() == before, "stale prompt save changed bytes")
    reset = p.reset_prompt_library(root, "common", 1)
    _check(reset["revision"] == 2 and p.load_prompt_library(root) == reset, "reset not durable exact next revision")


def _ax(root, category):
    from .ui_observer import flatten_playwright_ax, flatten_cdp_ax_tree
    text = TEXTS[category]
    count = 800 if category == "huge" else 3
    playwright = {"role": "presentation", "children": [{"role": "button", "name": text + str(i), "disabled": i == 1} for i in range(count)] + [{"role": "textbox", "name": "edit", "value": text}, {"role": "presentation", "name": "noise"}]}
    pw_nodes = flatten_playwright_ax(playwright)
    _check(len(pw_nodes) == count + 1, "Playwright normalization retained presentation noise or lost controls")
    _check(len({n.id for n in pw_nodes}) == count + 1, "Playwright control identities collide")
    _check(pw_nodes[-1].value == text.strip(), "editable value changed")
    _check("click" not in pw_nodes[1].actions and "click" in pw_nodes[0].actions, "disabled control exposes click")
    _check([n.id for n in flatten_playwright_ax(playwright)] == [n.id for n in pw_nodes], "Playwright source identity unstable")
    raw = [{"nodeId": str(i), "role": {"value": "button"}, "name": {"value": text + str(i)}, "properties": [{"name": "disabled", "value": {"value": i == 1}}]} for i in range(count)]
    raw.append({"nodeId": "edit", "role": {"value": "textbox"}, "name": {"value": "edit"}, "value": {"value": text}})
    cdp_nodes = flatten_cdp_ax_tree(raw)
    _check(len(cdp_nodes) == count + 1 and cdp_nodes[-1].value == text.strip(), "CDP controls/value lost")
    _check("click" not in cdp_nodes[1].actions and "click" in cdp_nodes[0].actions, "CDP disabled click exposed")
    _check([n.id for n in flatten_cdp_ax_tree(raw)] == [n.id for n in cdp_nodes], "CDP identity unstable")


def _ui(root, category):
    from .ui_graph import UiGraph, UiNode
    from .ui_observer import UiObserver
    from .ui_tools import UiToolSurface, register_with_progressive_surface, register_with_native_registry, TOOL_NAMES
    from .progressive_tools import ProgressiveToolSurface
    from types import SimpleNamespace
    graph = UiGraph()
    # No attach or browser navigation: exact claims are resident graph result,
    # discovery and fail-closed no-page/stale admission, not live interaction.
    observer = UiObserver(graph=graph)
    surface = UiToolSurface(observer=observer, workspace_root=root)
    text = TEXTS.get(category, "fixture")
    count = 800 if category == "huge" else 3
    graph.replace_nodes([UiNode(id=f"owned-{i}", role="button", name=text + str(i), actions=("click",)) for i in range(count)])
    before = graph.snapshot_nodes()
    revision, semantic_hash = graph.revision, graph.semantic_hash
    result = surface.ui_find({"query": "button", "limit": 3})
    _check(result["treeOmitted"] and "tree" not in result and "nodes" not in result, "compact UI result includes full tree")
    _check((result["revision"], result["semanticHash"], result["nodeCount"]) == (revision, semantic_hash, count), "compact result detached from graph")
    for args in ({"id": "owned-0", "ifRev": revision - 1}, {"id": "owned-0", "ifHash": "wrong"}):
        denied = surface.ui_do(args)
        _check(denied["status"] == "stale_state" and not denied["ok"], "stale UI action accepted")
        _check(graph.snapshot_nodes() == before and graph.revision == revision, "stale UI action mutated graph")
    missing_page = surface.ui_do({"id": "owned-0", "ifRev": revision, "ifHash": semantic_hash})
    _check(not missing_page["ok"] and graph.snapshot_nodes() == before, "no-page action manufactured success")
    progressive = ProgressiveToolSurface()
    _check(set(register_with_progressive_surface(progressive, surface)) == set(TOOL_NAMES), "progressive tool registration incomplete")
    register_with_progressive_surface(progressive, surface)
    _check(len(progressive.list_tools()) == len(TOOL_NAMES), "duplicate progressive tool rows")
    _check(all("inputSchema" not in row for row in progressive.search(text, limit=100)), "search leaked full schemas")
    _check(all("inputSchema" in progressive.describe(name) for name in TOOL_NAMES), "describe omitted schema")
    registry = SimpleNamespace(_handlers={}, _specs={})
    _check(set(register_with_native_registry(registry, surface)) == set(TOOL_NAMES), "native registration incomplete")
    register_with_native_registry(registry, surface)
    _check(len(registry._handlers) == len(TOOL_NAMES) and all(callable(fn) for fn in registry._handlers.values()), "native handlers not exact callable set")
    if category == "concurrency":
        from threading import Barrier
        barrier = Barrier(8)
        def register_pair(_):
            barrier.wait(timeout=5)
            progressive_names = register_with_progressive_surface(progressive, surface)
            native_names = register_with_native_registry(registry, surface)
            return progressive_names, native_names
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(register_pair, range(8)))
        expected = set(TOOL_NAMES)
        _check(all(set(progressive_names) == expected and set(native_names) == expected
                   for progressive_names, native_names in results), "concurrent discovery registration returned partial tools")
        _check(len(progressive.list_tools()) == len(expected)
               and set(registry._handlers) == expected and set(registry._specs) == expected,
               "concurrent discovery registration lost or duplicated registry entries")
    surface.close()


def _stream(root, category):
    from .chat_stream import StreamCoalescer, begin_chat_stream, append_chat_stream, last_stream_event
    text = TEXTS[category]
    emitted = []
    coalescer = StreamCoalescer(emitted.append, window=1.0)
    events = [{"kind": "runtime.delta", "message": text[:1000], "data": {"itemId": "first"}, "at": 1.125}, {"kind": "runtime.delta", "message": "second" + text[:1000], "data": {"itemId": "first"}, "at": 2.125}, {"kind": "runtime.delta", "message": "third", "data": {"itemId": "other"}, "at": 3.125}]
    for event in events:
        coalescer.push(event)
    coalescer.flush()
    _check("".join(r["message"] for r in emitted) == "".join(r["message"] for r in events), "coalescer reordered/changed accepted prefix")
    _check(emitted[0]["at"] == events[0]["at"] and emitted[-1]["data"] == events[-1]["data"], "coalescer changed first arrival/item attribution")
    _check(begin_chat_stream(root, "owned-turn"), "owned stream refused")
    path = root / ".agent_control/chat_streams/owned-turn.jsonl"
    append_chat_stream(root, "owned-turn", {"kind": "runtime.delta", "message": text, "data": {"eventType": "target"}, "at": 5.1256})
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    _check("".join(r["message"] for r in rows) == text and all(len(r["message"]) <= 4000 and r["at"] == 5.126 for r in rows), "durable frames lost bytes/bounds/timestamp")
    newest = {"kind": "runtime.delta", "message": "newest" + text[:200], "data": {"eventType": "target"}, "at": 7}
    append_chat_stream(root, "owned-turn", newest)
    append_chat_stream(root, "owned-turn", {"message": "tail" * 5000, "data": {"eventType": "other"}, "at": 8})
    tail = last_stream_event(root, "owned-turn", "target", tail_bytes=127)
    _check(tail["message"] == newest["message"] and tail["at"] == 7, "backward block scan lost newest matching event")


def _advisory(root, category):
    from .sub_agent_receipts import build_sub_agent_receipt
    from dataclasses import asdict
    text = TEXTS[category]
    count = 200 if category == "huge" else 3
    result = asdict(build_sub_agent_receipt(mission_id=text, assignment=text, role=text, status=text, confidence=3, files_inspected=[text + str(i) for i in range(count)], findings=[{"summary": text, "severity": "unknown", "evidence": [text + str(i) for i in range(20)]} for _ in range(count)]))
    _check(result["advisory_only"] is True and result["role"] == "review" and result["status"] == "partial" and result["confidence"] == 1, "subagent receipt manufactured execution authority/normalization")
    _check(len(result["assignment"]) <= 500 and len(result["files_inspected"]) <= 80 and len(result["findings"]) <= 16, "advisory receipt exceeds bounds")
    _check(all(len(row["evidence"]) <= 6 and len(row["summary"]) <= 220 and row["severity"] == "info" for row in result["findings"]), "advisory findings exceed evidence/summary bounds")


def _ladder(root, category):
    from .verification_ladder import build_verification_capacity_policy, build_verification_ladder
    text = TEXTS[category]
    files = [] if category == "empty" else ["src/owned.py", "web/owned.js", "src/owned.py"] + [f"src/{i}-{text[:100]}.py" for i in range(160 if category == "huge" else 2)]
    for gateway in (False, True):
        for operator in (False, True):
            policy = build_verification_capacity_policy(pc_gateway_online=gateway, operator_present=operator, time_budget_seconds=500)
            _check(policy["allowFrontendBuild"] == gateway and policy["allowBrowserVerification"] == (gateway and operator), "capacity invented gateway/operator")
            plan = build_verification_ladder(mission_id=text, changed_files=files, capacity_policy=policy)
            _check(len(plan["changedFiles"]) <= 120 and len(plan["changedFiles"]) == len(set(plan["changedFiles"])), "ladder lost bound/uniqueness")
            _check(plan["requiredStepCount"] == sum(row["required"] for row in plan["steps"]), "required count differs admitted steps")
            _check(plan["capacityGatedStepCount"] == sum(row["capacityGated"] for row in plan["steps"]), "gated count differs steps")
            _check(all(not row["required"] for row in plan["steps"] if row["capacityGated"]), "capacity-gated step still required")


FAMILIES = {
    "questions": (QUESTIONS, _questions, set(TEXTS) | {"concurrency", "interrupted", "permissions", "stale"}),
    "approval": ({"control.approval-policy", "control.approval-description"}, _approval, set(TEXTS) | {"permissions", "stale"}),
    "context": ({"control.context-budget", "control.context-compaction"}, _context, set(TEXTS)),
    "attachments": ({"control.attachments-content", "control.attachments-message"}, _attachments, set(TEXTS)),
    "suite": ({"sv.suite.summary", "sv.suite.artifacts"}, _suite, set(TEXTS)),
    "ocr": ({"d-ui.ocr-quality", "d-ui.ocr-route"}, _ocr, set(TEXTS)),
    "chrome-policy": ({"control.chrome-policy", "control.chrome-grant"}, _chrome, set(TEXTS) | {"permissions", "stale"}),
    "plan": ({"control.plan-transitions"}, _plan, set(TEXTS)),
    "prompts": ({"control.prompts-composition", "control.prompts-durable"}, _prompts, set(TEXTS) | {"concurrency", "interrupted", "stale"}),
    "ax": ({"sv.ui.ax-normalization"}, _ax, set(TEXTS)),
    "ui": ({"sv.ui.compact-result", "sv.ui.action-gates", "sv.ui.discovery"}, _ui, set(TEXTS) | {"stale", "concurrency"}),
    "stream": ({"control.stream-order", "control.stream-frame", "control.stream-tail"}, _stream, set(TEXTS)),
    "advisory": ({"sv.subagent.advisory-bounds"}, _advisory, set(TEXTS)),
    "ladder": ({"sv.ladder.capacity", "sv.ladder.plan"}, _ladder, set(TEXTS)),
}


def run(root, contracts, categories):
    root = Path(root)
    repo = Path(__file__).resolve().parents[2]
    rows = []
    for category in categories:
        if category in set(TEXTS) | {"permissions"}:
            result = subprocess.run(["node", "--input-type=module", "-e", NODE, str(repo), category], capture_output=True, text=True, encoding="utf-8", timeout=90, **hidden_windows_subprocess_kwargs())
            if result.returncode:
                rows.append({"id": f"surfaces:node:{category}", "category": category, "contracts": sorted((LAYOUT | EMBED) & contracts.keys()), "status": "failed", "detail": result.stderr[-4000:], "boundary": "actual frontend model calls; no rendered UI proof"})
            else:
                for case in json.loads(result.stdout):
                    if case["contract"] in contracts:
                        rows.append({"id": f"surfaces:{case['contract']}:{category}", "category": category, "contracts": [case["contract"]], "status": case["status"], "detail": case["detail"], "boundary": "actual frontend presentation model state transitions; no rendered UI proof"})
        for name, (identities, builder, supported) in FAMILIES.items():
            offline = category == "offline" and name in {"questions", "prompts", "attachments", "suite"}
            if (category not in supported and not offline) or not (identities & contracts.keys()):
                continue
            case_root = root / name / category
            case_root.mkdir(parents=True, exist_ok=True)
            try:
                if offline:
                    _offline(case_root, name)
                else:
                    builder(case_root, category)
                status, detail = "passed", "Production feature operations and independently observed state/bytes/returned values passed."
            except Exception as exc:
                status, detail = "failed", f"{type(exc).__name__}: {exc}"
            bound = identities & contracts.keys()
            if category not in TEXTS and name == "approval":
                bound -= {"control.approval-description"}
            if category == "stale" and name == "ui":
                bound -= {"sv.ui.discovery"}
            rows.append({"id": f"surfaces:{name}:{category}", "category": category, "contracts": sorted(bound), "status": status, "detail": detail, "boundary": "network-denied isolated child calling owned local production features" if offline else "owned local production feature calls; no remote/native/rendered claims"})
    return rows


def blocker(contract, category):
    identity = contract.get("id", "")
    if identity in LAYOUT and category not in TEXTS:
        return {"kind": "not_applicable", "reason": f"{identity} is an inspected synchronous immutable layout reducer, with no worker, grant, revision token or network I/O; {category} has no corresponding feature mechanism. Actual rendered resizing remains outside this model contract."}
    if identity in EMBED and category in {"concurrency", "interrupted", "offline", "stale"}:
        return {"kind": "not_applicable", "reason": f"{identity} transforms a supplied immutable host snapshot synchronously; this model has no durable worker, revision admission token or network operation for {category}. Adapter/native/rendered lifecycle requires separate proof."}
    if identity in {"control.context-budget", "control.context-compaction", "sv.ui.compact-result", "sv.ui.discovery"} and category in {"interrupted", "permissions", "offline", "stale"}:
        return {"kind": "not_applicable", "reason": f"{identity} exposes the current local in-memory state without a durable worker, network operation, grant admission or revision precondition for {category}. Shared-state concurrency still needs a real fixture and is not declared impossible."}
    if identity in {"d-ui.ocr-quality", "d-ui.ocr-route", "sv.suite.summary", "control.approval-description", "control.plan-transitions", "sv.subagent.advisory-bounds", "sv.ladder.capacity", "sv.ladder.plan", "sv.ui.ax-normalization"} and category not in TEXTS:
        return {"kind": "not_applicable", "reason": f"{identity} operates on current supplied in-memory data without a network, grant, durable store or interrupted worker; {category} does not apply to this audited transform."}
    if identity in {"control.chrome-policy", "control.chrome-grant"} and category in {"concurrency", "interrupted", "offline"}:
        return {"kind": "not_applicable", "reason": f"{identity} is an inspected synchronous decision on supplied page evidence and exact grant fingerprints. It performs no browser action, network request, shared durable transaction or worker lifecycle for {category}; live Chrome execution requires a separate journey."}
    return None
