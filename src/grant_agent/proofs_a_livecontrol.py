"""Authenticated report truth contracts; DOM evidence stays distinct from APIs."""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import importlib.util
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


def require(condition, identity, message):
    if not condition:
        raise ValueError(f"Contract {identity}: {message}")


def check_url(source, result):
    original, target = urlsplit(source), urlsplit(result)
    query = dict(parse_qsl(target.query, keep_blank_values=True))
    expected = dict(parse_qsl(original.query, keep_blank_values=True))
    expected.update(mode="builder", surface="builder")
    expected.pop("fixture", None)
    expected.pop("preview-control", None)
    require((target.scheme, target.netloc, target.path, target.fragment) ==
            (original.scheme, original.netloc, original.path or "/control", "")
            and query == expected, "livecontrol.builder-url", "live route changed authority or retained fixture mode")


def check_redaction(result, secrets):
    visible = result.replace("[REDACTED]", "")
    require(len(result) <= 1200 and result == " ".join(result.split())
            and all(not value or str(value) not in visible for value in secrets),
            "livecontrol.redaction", "explicit secret or unbounded diagnostic escaped")
    for match in re.finditer(r"(?i)(?:authorization\s*[:=]\s*bearer\s+|(?:api[_-]?key|token|password)\s*[:=]\s*)([^\s,;]+)", result):
        require(match[1] == "[REDACTED]" or match.end() == len(result) and "[REDACTED]".startswith(match[1]),
                "livecontrol.redaction", "labeled credential escaped")


def check_report(report, with_browser, dom_ids):
    rows = report["checks"]
    measured = [r for r in rows if r.get("measured") is True]
    failed = [r for r in rows if r.get("status") == "failed"]
    skipped = [r for r in rows if r.get("status") == "skipped"]
    dom = [r for r in rows if r.get("checkId") in dom_ids]
    summary = report["summary"]
    require(len(dom) == len(dom_ids) and {r["checkId"] for r in dom} == set(dom_ids),
            "livecontrol.report-truth", "browser claims missing or duplicated")
    require(summary["measuredCheckCount"] == len(measured)
            and summary["failedCheckCount"] == len(failed)
            and summary["skippedCheckCount"] == len(skipped)
            and report["ok"] == (bool(measured) and not failed)
            and report["complete"] == (report["ok"] and not skipped),
            "livecontrol.report-truth", "aggregate status overstates measured evidence")
    require(summary["browserProofRequested"] is bool(with_browser)
            and summary["browserProofComplete"] == (bool(with_browser) and bool(dom) and all(r.get("status") != "skipped" for r in dom)),
            "livecontrol.report-truth", "browser aggregation changed requested observation status")
    if not with_browser:
        require(all(r.get("status") == "skipped" and r.get("measured") is False
                    and r.get("passed") is None for r in dom)
                and not summary["browserProofRequested"] and not summary["browserProofComplete"]
                and not report["complete"], "livecontrol.api-not-dom", "API-only run claimed DOM proof")


def check_provider(rows, visible_count, texts, minimax_lines):
    joined = "\n".join(texts).lower()
    require(rows[0]["passed"] == (visible_count > 0 and "admission" in joined and "quota" in joined),
            "livecontrol.provider-dom", "admission truth was inferred without visible semantics")
    lane = " ".join(minimax_lines).lower()
    expected = ("blocked" if any(s in lane for s in ("auth missing", "auth required", "needs setup", "blocked"))
                else "admitted" if any(s in lane for s in ("authenticated", "admission ready", "ready"))
                else "declared" if minimax_lines else "not-rendered")
    require(rows[1]["admissionState"] == expected
            and rows[1]["passed"] == (visible_count > 0 and expected in {"admitted", "blocked"}),
            "livecontrol.provider-dom", "explanatory prose or an unclassified lane became admission proof")


def check_hermes(rows, visible, attribute, text):
    expected = visible and attribute == "true" and "backend route is proven" in text.lower() and "hermes/m3 runtime proof" in text.lower()
    require(rows[0]["passed"] == visible and rows[1]["passed"] == expected,
            "livecontrol.hermes-dom", "absent or pending rendered receipt became runtime proof")


def check_browser_failure(rows, completed_login, dom_ids):
    dom = [row for row in rows if row.get("checkId") in dom_ids]
    require(len(dom) == len(dom_ids) and all(row.get("status") == "skipped"
            and row.get("measured") is False and row.get("passed") is None for row in dom)
            and (completed_login is None or completed_login in rows),
            "livecontrol.browser-failure-truth", "failed DOM measurement lost completed login or admitted unobserved claims")


def self_check(root, *, page=None, dom_port=None, category="unicode"):
    if page is not None:
        return _self_check(root, page=page, dom_port=dom_port, category=category)
    # Own the actual admitted headless runtime and keep its origin explicit.
    from .neyvia_browser import BrowserService
    from .neyvia_browser_dom import NeyviaDOMPage
    service = BrowserService(Path(root) / "owned-dom")
    dom_port = proof_port(48467)
    engine_port = proof_port(48466)
    origin = f"http://127.0.0.1:{dom_port}"
    class OwnedPage(NeyviaDOMPage):
        def goto(self, url, **kwargs):
            if self.tab_id == "pending-owned":
                self.tab_id = service.request("tab.open", {"url": url, "engine": "obscura"}, owner=True)["tabId"]
            return super().goto(url, **kwargs)
    page = OwnedPage(lambda op, args: service.request(op, args, owner=True),
                     "pending-owned", allowed_origin=origin)
    try:
        service.request("headless.start", {"port": engine_port, "assignedPorts": [dom_port, engine_port],
                        "allowLocalFixtures": True}, owner=True)
        report = _self_check(root, page=page, dom_port=dom_port, category=category)
        report["observations"] = page.observations
        report["engine"] = "obscura"
        return report
    finally:
        try:
            if page.tab_id != "pending-owned":
                service.request("tab.close", {"tabId": page.tab_id}, owner=True)
        finally:
            service.request("headless.stop", {}, owner=True)


def _self_check(root, *, page=None, dom_port=None, category="unicode"):
    if category not in {"empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale"}:
        raise ValueError("Unknown live-control fixture category")
    started = time.perf_counter()
    script = Path(__file__).resolve().parents[2] / "scripts/verify_authenticated_live_control.py"
    spec = importlib.util.spec_from_file_location("proofs_livecontrol_host", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    urls = [proof_text("http://127.0.0.1:48467/control?fixture=review&preview-control=1&missionId=owned"),
            proof_text("http://127.0.0.1:48467?tag=a%20b#old"), proof_text("http://127.0.0.1:48467/control?mode=agent&surface=phone")]
    for value in urls:
        module._builder_url(value)
    sentinel = "scratch-private-" + str(time.time_ns())
    redacted = module._redact_text(f"failed password={sentinel} Authorization: Bearer transient-bearer api_key=transient-key", (sentinel,))
    require(all(value not in redacted for value in (sentinel, "transient-bearer", "transient-key")),
            "livecontrol.redaction", "startup redaction lost a protected value")
    # The production report composer is exercised separately from networking:
    # these are classified observations, never fabricated browser measurements.
    skipped = [module._skipped_check(identity, "No browser observation requested") for identity in module.DOM_CHECK_IDS]
    checks = [module._check("account-login", True, "classified observation"), *skipped]
    report = module._assemble_report(checks, {}, {}, with_browser=False, url=urls[0], report_path=Path(root) / "report.json")
    require(not report["complete"] and report["summary"]["skippedCheckCount"] == len(skipped),
            "livecontrol.api-not-dom", "startup API-only report admitted browser proof")
    # A deliberately forged aggregate must be rejected by the host contract.
    forged = {**report, "complete": True}
    try:
        check_report(forged, False, module.DOM_CHECK_IDS)
    except ValueError:
        rejected = True
    else:
        rejected = False
    require(rejected, "livecontrol.report-truth", "forged completeness was accepted")
    check_browser_failure(skipped, None, module.DOM_CHECK_IDS)
    classified_login = module._check("browser-account-login", True, "controlled composition input")
    check_browser_failure([classified_login, *skipped], classified_login, module.DOM_CHECK_IDS)
    try:
        check_browser_failure(skipped, classified_login, module.DOM_CHECK_IDS)
    except ValueError:
        lost_login_rejected = True
    else:
        lost_login_rejected = False
    require(lost_login_rejected, "livecontrol.browser-failure-truth", "composition discarded an already measured login")
    # This is a pure composition truth table over classified inputs, not a
    # browser observation or a claim that any live DOM check actually passed.
    for state in ("passed", "failed", "skipped"):
        classified = [(module._skipped_check(identity, "controlled composition input") if state == "skipped"
                       else module._check(identity, state == "passed", "controlled composition input"))
                      for identity in module.DOM_CHECK_IDS]
        composed = module._assemble_report(classified, {}, {}, with_browser=True, url=urls[0], report_path=Path(root) / "composition.json")
        require(composed["checks"] == classified and composed["summary"]["browserProofRequested"]
                and composed["summary"]["browserProofComplete"] == (state != "skipped")
                and composed["complete"] == (state == "passed"),
                "livecontrol.report-truth", "requested classified inputs were replaced with API-only skips")
    import subprocess
    import sys
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    help_result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, timeout=20,
                                 **hidden_windows_subprocess_kwargs())
    require(help_result.returncode == 0 and "--with-browser" in help_result.stdout,
            "livecontrol.cli-browser-option", "production parser lost the explicit browser verification option")
    # The caller selects an actual Neyvia runtime and an explicit owned port.
    # No browser fallback or saved profile/account is consulted.
    if page is None or type(dom_port) is not int or not 1024 <= dom_port <= 65535 or dom_port == 47881:
        raise RuntimeError("Supply an owned NeyviaDOMPage and explicit DOM fixture port; no browser substitution occurs")
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    documents = {}
    variants = [("MiniMax executor authenticated", "true", "Backend route is proven", True, True),
                ("", "false", "Backend route proof is pending", False, False),
                ("MiniMax executor auth required", "false", "Backend route is proven", True, False)]
    prefix = "雪 café e\u0301 العربية " if category == "unicode" else ""
    suffix = " owned bounded payload" * 4096 if category == "huge" else ""
    for index, (lane, flag, phrase, admitted, proven) in enumerate(variants):
        admission = '<div data-provider-admission-truth="true">Admission and quota are observed separately '+prefix+suffix+'</div>'
        lane_markup = '<article>'+lane+' '+prefix+'</article>'
        documents["/owned-" + str(index)] = ('<main>'+admission*(100 if category == "huge" else 1)
            + ('<div data-task-fit-route-decision="true">'+lane_markup*(100 if category == "huge" else 1)+'</div>' if lane else '<p>MiniMax may require authentication</p>')
            + f'<section data-live-hermes-m3-runtime-proof="true" data-live-hermes-m3-verified="{flag}">Hermes/M3 runtime proof: {phrase} '+prefix+'</section></main>').encode()
    documents["/owned-empty"] = b"<!doctype html><main></main>"
    class Documents(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_GET(self):
            data = documents.get(self.path)
            self.send_response(200 if data is not None else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data or b""))); self.end_headers()
            if data is not None: self.wfile.write(data)
    server = ThreadingHTTPServer(("127.0.0.1", dom_port), Documents)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    classifications = []
    try:
        if category == "empty":
            page.goto(f"http://127.0.0.1:{dom_port}/owned-empty")
            empty_rows = [*module._measure_provider_admission(page, secrets=()), *module._measure_hermes_runtime_proof(page, secrets=())]
            require(not any(row["passed"] for row in empty_rows), "livecontrol.provider-dom", "actual empty rendered document invented a visible admission/runtime receipt")
            classifications.append({"document":"owned-empty","checks":empty_rows})
        for index, (_lane, _flag, _phrase, admitted, proven) in enumerate(variants):
            page.goto(f"http://127.0.0.1:{dom_port}/owned-{index}")
            if category == "concurrency":
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=2) as pool:
                    provider_task = pool.submit(module._measure_provider_admission,page,secrets=())
                    hermes_task = pool.submit(module._measure_hermes_runtime_proof,page,secrets=())
                    provider,hermes = provider_task.result(timeout=30),hermes_task.result(timeout=30)
            else:
                provider = module._measure_provider_admission(page, secrets=())
                hermes = module._measure_hermes_runtime_proof(page, secrets=())
            require(provider[0]["passed"] and provider[1]["passed"] == admitted and hermes[1]["passed"] == proven,
                    "livecontrol.provider-dom", "actual Neyvia DOM classification did not distinguish admitted, blocked and pending")
            classifications.append({"document":"owned-"+str(index),"checks":[*provider,*hermes]})
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        require(not thread.is_alive(), "livecontrol.cli-browser-option", "owned DOM document server survived cleanup")
    return {"ok": True, "contracts": ["livecontrol.builder-url", "livecontrol.redaction", "livecontrol.report-truth", "livecontrol.api-not-dom", "livecontrol.provider-dom", "livecontrol.hermes-dom", "livecontrol.cli-browser-option", "livecontrol.browser-failure-truth"],
            "actualDOMContracts": ["livecontrol.provider-dom", "livecontrol.hermes-dom", "livecontrol.cli-browser-option"],
            "diagnosticContracts": ["livecontrol.builder-url", "livecontrol.redaction", "livecontrol.report-truth", "livecontrol.api-not-dom", "livecontrol.browser-failure-truth"],
            "procedures": ["live-route-projection", "redacted-diagnostics", "api-only-composition-refusal", "rendered-verifier-classification"],
            "category": category, "classifications": classifications,
            "authority": "Production report composition and actual Neyvia native DOM classifier on controlled documents; no actual provider authentication/execution or credential file claimed",
            "durationMs": round((time.perf_counter() - started) * 1000)}
