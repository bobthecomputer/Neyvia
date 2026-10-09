"""Fresh producer/effect checks for C8e's former empty status-read passes.

The report producer is always the authenticated candidate tool. This module
never manufactures a proof report or converts a model fixture into UI proof.
The caller retains the returned checks and gates the journey on ``passed``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time


def _check(identity, passed, observed, **details):
    return {"id": identity, "passed": bool(passed), "observed": observed,
            "fresh": True, **details}


def apply(bindings):
    """Merge the dedicated overlay without changing the source-bound catalog."""
    path = Path(__file__).resolve().parents[1] / "config/inception_c8e_effects.json"
    overlay = json.loads(path.read_text(encoding="utf-8"))["bindings"]
    unknown = set(overlay) - set(bindings)
    if unknown:
        raise ValueError("Unknown C8e effect identities: " + ", ".join(sorted(unknown)))
    for identity, additions in overlay.items():
        bindings[identity].update(additions)
        effect = additions.get('c8eEffect', {})
        if effect.get('waitingFor') == 'C11':
            bindings[identity]['nativeOnly'] = {'needs': 'C11', 'tool': 'neyvia.verify',
                'step': 'Prove the authored native defining effect on the isolated C11 desktop',
                'reason': effect['missingPrerequisite']}
    return bindings


def before_manual(worker, binding, inputs, root):
    """Produce real proof data before the authored reader consumes it.

    A separate returned production report is kept on the worker. In particular,
    ``ok:false`` and ``complete:false`` survive; neither is relabelled success.
    """
    effect = binding.get("c8eEffect")
    if not effect:
        return None
    worker.c8e_effect = {"checks": [], "startedAt": time.time(),
                         "producerCallStart": len(worker.calls)}
    if effect.get("renderedWitness") == "c8e-browser":
        from c8e_browser_checks import before_manual as actual_capacity
        actual_capacity(worker, binding, inputs, root)
    if effect.get("waitingFor"):
        worker.c8e_effect["missingPrerequisite"] = effect["missingPrerequisite"]
        return worker.c8e_effect
    areas = effect.get("producerAreas", [])
    if not areas:
        worker.c8e_effect["missingPrerequisite"] = effect["missingPrerequisite"]
        return worker.c8e_effect
    # The backend owns process admission. Do not bypass its refusal by importing
    # the candidate adapter here, or by running an unguarded alternate script.
    if effect.get("producerAdmission") not in {"safe-frontend-computation", "scoped-production-chapters", "scoped-production-host"}:
        worker.c8e_effect["missingPrerequisite"] = effect.get("missingPrerequisite") or (
            "Explicit scoped admission for this production proof runner and its actual local installed adapter prerequisites")
        return worker.c8e_effect
    try:
        arguments = {"areas": areas, "includeManuals": False}
        if effect.get('adapterChapters'):
            arguments['adapterChapters'] = effect['adapterChapters']
        report = worker.tool("neyvia.verify", arguments)
        worker.c8e_effect.update(producer=report, producerCallEnd=len(worker.calls))
    except Exception as error:
        # The verifier reports ok:false when the overall migration is incomplete,
        # even after a real selected area returned. Preserve that original report
        # rather than misclassifying its honest incomplete result as no launch.
        # unwrap() intentionally refuses ok:false, so inspect the original receipt
        # envelope without changing any returned field or calling another route.
        reply = getattr(error, "reply", None)
        if reply is None and worker.calls and worker.calls[-1].get("tool") == "neyvia.verify":
            reply = worker.calls[-1]
        report = None
        if isinstance(reply, dict) and reply.get("httpStatus") == 200:
            value = reply.get("body", {}).get("data")
            while isinstance(value, dict) and "tool" in value and isinstance(value.get("result"), dict):
                value = value["result"]
            if (isinstance(value, dict) and value.get("schema") == "neyvia.proofs.v1"
                    and isinstance(value.get("areas"), list)):
                report = value
        if report is not None:
            worker.c8e_effect.update(producer=report, producerReportedIncomplete=report.get("ok") is False,
                                     producerResponseError=str(error), producerCallEnd=len(worker.calls))
        else:
            # A real gateway/launch refusal remains failed; no alternate producer.
            worker.c8e_effect.update(producerError=str(error), producerCallEnd=len(worker.calls))
    return worker.c8e_effect


def _rendered_witness(worker, effect, root):
    """Exercise an actual mounted candidate surface where a local route exists.

    Each complete witness covers the exact source contracts applicable to its
    authored chapter. Partial witnesses keep the remaining contracts unproved.
    """
    witness = effect.get("renderedWitness")
    observations, checks = {}, []
    if isinstance(witness, str) and witness.startswith('c8e-ui-'):
        from c8e_ui_effects import run_effects
        checks, observations = run_effects(worker, worker.args.binding, {}, root)
    elif witness == 'c8e-host':
        from c8e_host_effects import witness as host_witness
        checks, observations = host_witness(worker, effect, root)
    elif isinstance(witness, str) and witness.startswith('c8e-state-'):
        from c8e_state_effects import run_effects
        checks, observations = run_effects(worker, worker.args.binding, {}, root)
    elif witness == "runtime-catalog":
        checks, observations = _runtime_witness(worker)
    elif witness == "settings-scenes":
        checks, observations = _settings_witness(worker, root)
    elif witness == "outputs-refresh":
        checks, observations = _outputs_witness(worker, root)
    elif witness == "c8f-sidebar":
        from c8f_sidebar import witness as sidebar_witness
        checks, observations = sidebar_witness(worker, effect, root)
    elif witness == "theme-and-sidebar":
        worker.tool("neyvia.view.theme", {"theme": "sunset"})
        worker.page.locator('.nx-root[data-nx-theme="sunset"]').wait_for(timeout=15000)
        first = worker.observe()
        worker.page.reload(wait_until="domcontentloaded")
        worker.page.locator('.nx-root[data-nx-theme="sunset"]').wait_for(timeout=15000)
        after = worker.observe()
        checks.append(_check("c8e.rendered-theme-after-reload", True,
                             {"before": first["revision"], "after": after["revision"], "theme": "sunset"},
                             boundary="Mounted candidate DOM and persisted theme; no synthetic reducer"))
        worker.tool("neyvia.view.theme", {"theme": "dark"})
        worker.page.locator('.nx-root[data-nx-theme="dark"]').wait_for(timeout=15000)
        checks.append(_check("c8e.rendered-theme-reversible", True, {"theme": "dark"}))
        observations["rendered"] = {"witness": witness, "url": worker.page.url,
                                    "artifact": worker.screenshot("effect-theme")}
    elif witness == "publication-bytes":
        marker = "Fresh C8e publication " + worker.args.run_id
        path = Path(root) / "c8e/publication.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(marker, encoding="utf-8")
        produced = worker.tool("neyvia.artifact.publish", {"path": str(path), "kind": "file",
                              "title": "C8e actual publication", "requestId": "c8e-effect-publication"})
        artifact = produced.get("artifact", produced)
        identity = artifact.get("id", produced.get("id"))
        if not identity:
            raise ValueError("Production artifact.publish returned no artifact identity")
        current = worker.tool("neyvia.artifact.get", {"id": identity})
        worker.tool("neyvia.artifact.open", {"id": identity})
        worker.observe()
        # A queued event is insufficient. Retain a mounted pane witness only if
        # the rendered candidate itself displays these exact freshly written bytes.
        seen = worker.page.get_by_text(marker, exact=False).count() > 0
        row = current.get("artifact", current)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checks.append(_check("c8e.publication-fresh-hash", row.get("sha256") == digest,
                             {"expectedSha256": digest, "artifact": current}))
        checks.append(_check("c8e.publication-mounted-content", seen,
                             {"marker": marker, "url": worker.page.url},
                             boundary="Candidate mounted content, not pane queue acknowledgement"))
        observations["rendered"] = {"witness": witness, "artifact": worker.screenshot("effect-publication")}
    return checks, observations


def _outputs_witness(worker, root):
    """Prove artifact.published by its real registry and mounted Outputs effect."""
    worker.tool("neyvia.voice.command", {"text": "go home", "final": True,
                                         "requestId": "c8e-output-home"})
    title1, title2 = "C8e first actual output", "C8e second actual output"
    base = Path(root) / "c8e"
    base.mkdir(parents=True, exist_ok=True)
    paths = [base / "first.txt", base / "second.txt"]
    for index, path in enumerate(paths, 1):
        path.write_text(f"C8e actual publication {index} {worker.args.run_id}", encoding="utf-8")
    first = worker.tool("neyvia.artifact.publish", {"path": str(paths[0]), "title": title1,
                        "kind": "file", "requestId": "c8e-output-first"})
    worker.page.get_by_text("New output: " + title1, exact=True).wait_for(timeout=15000)
    notice = worker.page.get_by_text("New output: " + title1, exact=True).inner_text()
    worker.tool("neyvia.app.open", {"app": "outputs"})
    worker.page.locator(".nx-out-rows").get_by_text(title1, exact=True).wait_for(timeout=15000)
    list_before = worker.page.locator(".nx-out-rows").inner_text()
    second_started = time.monotonic()
    second = worker.tool("neyvia.artifact.publish", {"path": str(paths[1]), "title": title2,
                         "kind": "file", "requestId": "c8e-output-second"})
    notifications = []
    for _ in range(60):
        notifications.append(worker.page.locator(".nx-toasts").all_text_contents())
        if worker.page.locator(".nx-out-rows").get_by_text(title2, exact=True).count():
            break
        worker.page.wait_for_timeout(50)
    elapsed = time.monotonic() - second_started
    mounted = worker.page.locator(".nx-out-rows").get_by_text(title2, exact=True).count() == 1
    quiet = elapsed < 4 and not any(title2 in text for frame in notifications for text in frame)
    checks = [_check("c8e.output-offscreen-announced", notice == "New output: " + title1,
                      {"notice": notice}, boundary="rendered-user-action"),
              _check("c8e.output-mounted-refresh", mounted and quiet,
                      {"before": list_before, "after": worker.page.locator(".nx-out-rows").inner_text(),
                       "notifications": notifications, "seconds": elapsed}, boundary="rendered-user-action")]
    identities, publications = [], []
    for path, produced in zip(paths, (first, second)):
        artifact = produced.get("artifact", produced)
        identities.append(artifact.get("id"))
        current = worker.tool("neyvia.artifact.get", {"id": artifact.get("id")})
        expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        publications.append(current)
        checks.append(_check("c8e.output-exact-bytes-" + path.name,
                             current.get("availability") == "available" and current.get("currentSha256") == expected_hash,
                             {"expectedSha256": expected_hash, "current": current}, boundary="production-state"))
    before = worker.tool("neyvia.artifact.list", {})
    refusal = None
    try:
        worker.tool("neyvia.artifact.publish", {"path": str(base / "absent.txt"), "title": "C8e refused output",
                                               "requestId": "c8e-output-missing"})
    except Exception as error:
        refusal = getattr(error, "reply", str(error))
    after = worker.tool("neyvia.artifact.list", {})
    checks.append(_check("c8e.output-invalid-publication-no-effect", refusal is not None and before == after,
                         {"refusal": refusal, "before": before, "after": after}, boundary="production-state"))
    checks.append(_check("c8e.output-production-identities", all(identities) and len(set(identities)) == 2,
                         {"ids": identities}, boundary="production-state"))
    worker.observe()
    return checks, {"contractEffects": [{"id": "proofs-e.shell.reducer", "fresh": True,
                   "passed": all(c["passed"] for c in checks), "boundary": "rendered-user-action",
                   "observed": {"applicability": "Outputs chapter artifact.published identity, refresh signal and offscreen-only notice",
                                "checks": checks, "publications": publications,
                                "artifact": worker.screenshot("effect-outputs")}}],
                   "rendered": {"witness": "outputs-refresh", "url": worker.page.url}}


def _settings_witness(worker, root):
    """Exercise every bus action named by Settings' shell-proof guidance."""
    import sqlite3
    checks = []
    def visible_state():
        return worker.page.locator(".nx-root").evaluate("""e=>({theme:e.dataset.nxTheme,
          density:e.dataset.nxDensity,regions:Array.from(document.querySelectorAll('.nx-region')).map(r=>r.dataset.region)})""")
    def await_saved_look(label, theme, density):
        # The rapid commands above intentionally overlap pending saves. Only
        # the final exact canonical owner state permits the reload proof.
        canonical_theme = {"dark": "forest", "light": "morning", "sunset": "sunset", "night": "night-green"}[theme]
        deadline = time.monotonic() + 60
        canonical = None
        while time.monotonic() < deadline:
            canonical = worker.tool('neyvia.settings.get', {})
            mounted = visible_state()
            if (canonical['settings']['theme'] == canonical_theme
                    and canonical['settings']['density'] == density
                    and mounted['theme'] == theme and mounted['density'] == density):
                checks.append(_check('c8e.settings-durable-look-' + label, True,
                                     {'canonical': canonical, 'mounted': mounted}, boundary='production-state'))
                return canonical
            worker.page.wait_for_timeout(100)
        raise RuntimeError(f'Actual {label} look was not durably saved: expected {canonical_theme}/{density}; observed {canonical}')
    for theme in ("light", "sunset", "night", "dark"):
        worker.tool("neyvia.view.theme", {"theme": theme})
        worker.page.locator(f'.nx-root[data-nx-theme="{theme}"]').wait_for(timeout=15000)
        checks.append(_check("c8e.settings-theme-" + theme, True, visible_state(), boundary="rendered-user-action"))
    for scene, density in (("focus", "calm"), ("workshop", "workshop"), ("cockpit", "grove")):
        worker.tool("neyvia.view.scene", {"name": scene})
        worker.page.locator(f'.nx-root[data-nx-density="{density}"]').wait_for(timeout=15000)
        checks.append(_check("c8e.settings-scene-" + scene, True, visible_state(), boundary="rendered-user-action"))
    worker.tool("neyvia.view.theme", {"theme": "sunset"})
    worker.page.locator('.nx-root[data-nx-theme="sunset"]').wait_for(timeout=15000)
    worker.tool("neyvia.view.scene", {"save": "C8e Settings"})
    worker.page.wait_for_function("""() => Object.values(JSON.parse(localStorage.getItem('nx.os.scenes') || '{}'))
      .some(scene => scene.label === 'C8e Settings' && scene.theme === 'sunset' && scene.density === 'grove')""", timeout=15000)
    worker.tool("neyvia.view.scene", {"name": "focus"})
    worker.page.locator('.nx-root[data-nx-density="calm"]').wait_for(timeout=15000)
    worker.tool("neyvia.view.theme", {"theme": "dark"})
    worker.page.locator('.nx-root[data-nx-theme="dark"]').wait_for(timeout=15000)
    worker.tool("neyvia.view.scene", {"name": "C8e Settings"})
    worker.page.locator('.nx-root[data-nx-theme="sunset"][data-nx-density="grove"]').wait_for(timeout=15000)
    restored = visible_state()
    await_saved_look('restored-scene-before-reload', 'sunset', 'grove')
    worker.page.reload(wait_until="domcontentloaded")
    worker.page.locator('.nx-root[data-nx-theme="sunset"][data-nx-density="grove"]').wait_for(timeout=15000)
    checks.append(_check("c8e.settings-saved-scene-reload", visible_state() == restored,
                         {"restored": restored, "reloaded": visible_state()}, boundary="rendered-user-action"))
    for name, args in (("neyvia.view.theme", {"theme": "invalid-c8e"}),
                       ("neyvia.view.arrange", {"order": ["main", "main"]}),
                       ("neyvia.view.scene", {"save": "Focus"})):
        prior = visible_state()
        refusal = None
        try:
            worker.tool(name, args)
        except Exception as error:
            refusal = getattr(error, "reply", str(error))
        checks.append(_check("c8e.settings-refused-" + name + str(args), refusal is not None and visible_state() == prior,
                             {"refusal": refusal, "prior": prior, "after": visible_state()}, boundary="production-state"))
    prior = visible_state()
    unknown = worker.tool("neyvia.view.scene", {"name": "nonexistent-c8e"})
    event = unknown.get("event", {})
    acknowledged = []
    db_path = Path(root) / ".agent_control/ui_commands.sqlite3"
    for _ in range(30):
        worker.page.wait_for_timeout(100)
        with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as db:
            acknowledged = db.execute("SELECT ok,error FROM acks WHERE event_id=?", (event.get("id"),)).fetchall()
        if acknowledged:
            break
    refused = bool(acknowledged) and all(ok == 0 and "Unknown scene" in error for ok, error in acknowledged)
    checks.append(_check("c8e.settings-unknown-scene-ui-refusal", refused and visible_state() == prior,
                         {"realEvent": event, "actualUiAcknowledgements": acknowledged,
                          "prior": prior, "after": visible_state()}, boundary="production-state"))
    worker.observe()
    contract = {"id": "proofs-e.shell.reducer", "fresh": True, "passed": all(c["passed"] for c in checks),
                "boundary": "rendered-user-action", "observed": {
                    "applicability": "Settings chapter: themes/scenes; malformed layout, unknown scene and invalid theme refusals",
                    "actions": checks, "artifact": worker.screenshot("effect-settings-scenes")}}
    return checks, {"contractEffects": [contract], "rendered": {"witness": "settings-scenes", "url": worker.page.url}}


def _runtime_witness(worker):
    """Compare every mounted Runtime row with its real authoritative sources."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    skip = worker.page.get_by_role('button', name='Skip setup', exact=True)
    try:
        skip.wait_for(timeout=6000)
    except PlaywrightTimeout:
        pass  # An already completed profile has no setup dialog.
    else:
        skip.click()
        worker.page.locator('.nx-onb-scrim').wait_for(state='hidden', timeout=15000)
    worker.tool("neyvia.pane.show", {"kind": "runtime", "target": "runtime"})
    worker.page.locator(".nx-rt-row").first.wait_for(timeout=45000)
    worker.page.get_by_role("button", name="Check again", exact=True).wait_for(timeout=45000)
    worker.page.wait_for_function("() => !document.querySelector('.nx-rt-head button')?.disabled", timeout=60000)
    policy_before = worker.page.evaluate("""async () => {
      const r=await fetch('/api/ui/runtime'); return await r.json();
    }""")
    policy_transport = worker.page.evaluate("""async () => {
      const r=await fetch('/api/ui/runtime',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'policy',app:'neyvia',permissionCeiling:'read-only',allowedModels:[]})});
      return {httpStatus:r.status,body:await r.json()};
    }""")
    invalid_policy = worker.page.evaluate("""async () => {
      const r=await fetch('/api/ui/runtime',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'policy',app:'neyvia',permissionCeiling:'unsupported-c8e',allowedModels:[]})});
      return {httpStatus:r.status,body:await r.json()};
    }""")
    policy_proof = worker.directory / 'runtime-policy-effects.json'
    policy_proof.write_text(json.dumps({'target': worker.page.url, 'before': policy_before,
                            'write': policy_transport, 'invalid': invalid_policy}, indent=2) + '\n', encoding='utf-8')
    worker.observe()
    worker.page.get_by_role("button", name="Check again", exact=True).click()
    worker.page.wait_for_function("() => !document.querySelector('.nx-rt-head button')?.disabled", timeout=60000)
    catalog = worker.tool("backend:get_harness_catalog_command", {})
    matrix_transport = worker.page.evaluate("""async () => {
      const r = await fetch('/api/ui/runtime'); return {httpStatus:r.status,body:await r.json()};
    }""")
    if matrix_transport["httpStatus"] != 200 or matrix_transport["body"].get("ok") is False:
        raise ValueError("Actual runtime matrix refused the owned session")
    matrix = matrix_transport["body"].get("data", matrix_transport["body"])
    (worker.directory / 'runtime-matrix.json').write_text(json.dumps({'target': worker.page.url,
                        'transport': matrix_transport}, indent=2) + '\n', encoding='utf-8')
    worker.observe()
    aliases = {"neyvia": "neyvia-agent", "kimi": "kimi-code", "grok": "grok-build"}
    runtime_by_catalog = {aliases.get(r["id"], r["id"]): r for r in matrix.get("runtimes", [])}
    harnesses = catalog.get("harnesses", [])
    joined, used = [], set()
    for h in harnesses:
        r = runtime_by_catalog.get(h["harnessId"])
        if r:
            used.add(r["id"])
        joined.append((h, r))
    joined.extend((None, r) for r in matrix.get("runtimes", []) if r["id"] not in used)
    modes = {"native": "Native", "connected": "Connected", "wrapped": "Wrapped", "planned": "Not wired yet"}
    auth_labels = {"authenticated-live": "Signed in", "account-action-required": "Sign-in needed",
                   "provider-setup-required": "Provider setup needed", "route-setup-required": "Route setup needed",
                   "route-dependent": "Uses the chosen model's sign-in", "security-scope-required": "Security profile needed",
                   "not-installed": "Not installed", "unverified": "Not checked"}
    expected, observed = [], []
    for h, r in joined:
        h, r = h or {}, r or {}
        installed = bool(h.get("installed", r.get("installed")))
        ready = bool(r.get("connected") or h.get("readiness") == "ready")
        name = h.get("label") or r.get("id")
        version = h.get("version") or r.get("version") or "—"
        mode = modes.get(r.get("kind"), r.get("kind")) if r else "Catalog only"
        cells = ["Found" if installed else "Not found", version, mode,
                 "Yes" if r.get("capabilities", {}).get("start") else "No",
                 "Ready" if ready else "Installed, not usable yet" if installed else "Not installed"]
        # Match text exactly; aliases must join once rather than create duplicates.
        line = worker.page.locator(".nx-rt-line").filter(has=worker.page.get_by_text(name, exact=True))
        count = line.count()
        actual_cells = line.locator(".nx-rt-cell").all_text_contents() if count == 1 else []
        expected.append({"name": name, "cells": cells, "installed": installed, "ready": ready})
        observed.append({"name": name, "count": count, "cells": actual_cells})
        if count == 1:
            line.click()
            row = line.locator("..")
            caps = [item["label"] for item in h.get("capabilities", [])]
            actual_caps = row.locator(".nx-rt-caps li").all_text_contents()
            auth_state = h.get("authState") or ("authenticated-live" if r.get("auth", {}).get("authenticated")
                                                or r.get("auth", {}).get("loggedIn") else None)
            auth_expected = auth_labels.get(auth_state, auth_state) if auth_state else (
                r.get("auth", {}).get("status") if r.get("auth", {}).get("status") not in {None, "unknown", ""} else "Not checked")
            facts = dict(zip(row.locator(".nx-rt-facts dt").all_text_contents(),
                             row.locator(".nx-rt-facts dd").all_text_contents()))
            auth_actual = row.locator(".nx-rt-facts dd").first.evaluate("e=>e.childNodes[0].textContent")
            models = r.get("options", {}).get("models", [])
            show_all = row.get_by_role("button", name=f"Show all {len(models)}", exact=True)
            if show_all.count():
                show_all.click()
            model_labels = row.locator(".nx-rt-models li > span, .nx-rt-models li > label > span").all_text_contents()
            expected_model_labels = [m.get("label") or m["id"] for m in models]
            policy = matrix.get("policies", {}).get(r.get("id"), {})
            active_ceiling = row.locator('.nx-rt-save [role="radio"][aria-checked="true"]').all_text_contents()
            ceiling_expected = {"read-only": "Read only", "workspace": "Workspace", "full-access": "Full access"}.get(policy.get("permissionCeiling"))
            details_ok = (auth_actual == auth_expected and sorted(model_labels) == sorted(expected_model_labels)
                          and active_ceiling == ([ceiling_expected] if ceiling_expected else []))
            observed[-1].update(capabilities=actual_caps, capabilitiesExpected=caps,
                                facts=facts, auth=auth_actual, expectedAuth=auth_expected,
                                models=model_labels, expectedModels=expected_model_labels,
                                activeCeiling=active_ceiling, expectedCeiling=ceiling_expected, detailsMatch=details_ok)
    merged_ok = (bool(expected) and len(expected) == worker.page.locator(".nx-rt-row").count()
                 and all(o["count"] == 1 and o["cells"] == e["cells"]
                         and o.get("capabilities") == o.get("capabilitiesExpected") and o.get("detailsMatch")
                         for e, o in zip(expected, observed)))
    ready_count = sum(e["ready"] for e in expected)
    found_count = sum(e["installed"] for e in expected)
    expected_summary = f"{ready_count} ready to use, {found_count} found on this PC, {len(expected)} known."
    summary = worker.page.locator(".nx-rt-head p").inner_text()
    saved_policy = matrix.get("policies", {}).get("neyvia")
    policy_preserved = saved_policy == {"permissionCeiling": "read-only", "allowedModels": []}
    adverse_ok = (invalid_policy["httpStatus"] >= 400 or invalid_policy["body"].get("ok") is False) and policy_preserved
    checks = [_check("c8e.runtime-authoritative-join", merged_ok,
                      {"expected": expected, "mounted": observed}, boundary="rendered-user-action"),
              _check("c8e.runtime-counts-from-actual-rows", summary == expected_summary,
                      {"summary": summary, "expected": expected_summary}, boundary="rendered-user-action"),
              _check("c8e.runtime-invalid-policy-refused", adverse_ok,
                      {"invalid": invalid_policy, "savedPolicy": saved_policy}, boundary="production-state")]
    contracts = [{"id": "runtime.mergeRuntimes", "passed": merged_ok, "fresh": True,
                  "boundary": "rendered-user-action", "observed": {"catalog": catalog, "matrix": matrix,
                                                                             "mounted": observed}},
                 {"id": "runtime.runtimeSummary", "passed": summary == expected_summary, "fresh": True,
                  "boundary": "rendered-user-action", "observed": {"summary": summary,
                                                                             "expected": expected_summary}}]
    worker.observe()
    return checks, {"contractEffects": contracts, "rendered": {"witness": "runtime-catalog",
                   "artifact": worker.screenshot("effect-runtime"), "url": worker.page.url}}


def after_manual(worker, inputs, root, *, witness=None):
    """Re-read producer outputs and report strict source-specific effect gaps."""
    binding = worker.args.binding
    effect = binding.get("c8eEffect")
    if not effect:
        return None
    state = getattr(worker, "c8e_effect", {})
    checks, observed = list(state.get("checks", [])), {}
    if state.get("producerError"):
        checks.append(_check("c8e.real-producer-refused", False, state["producerError"],
                             boundary="Actual candidate gateway refusal; no alternate producer"))
    if state.get("missingPrerequisite"):
        checks.append(_check("c8e.defining-effect", False,
                             {"missingPrerequisite": state["missingPrerequisite"],
                              "waitingFor": effect.get("waitingFor")},
                             boundary=effect["boundary"]))
        partial = (getattr(worker, "effect_evidence", None) or {}) if effect.get("renderedWitness") == "c8e-browser" else {}
        return {"passed": False, "checks": partial.get("checks", []) + checks,
                "contractEffects": partial.get("contractEffects", []),
                "observed": {**partial.get("observed", {}), **checks[-1]["observed"]},
                "boundary": effect["boundary"], "missingPrerequisite": state["missingPrerequisite"]}
    report = state.get("producer", {})
    status = worker.tool("neyvia.verify.status", {})
    required_fields = ("complete", "contractsOk", "coverage", "failures", "blocked", "durationMs")
    exact_status = (status.get("available") is True and all(key in report and status.get(key) == report[key]
                                                            for key in required_fields))
    checks.append(_check("c8e.fresh-status-matches-real-producer", exact_status,
                         {"status": status, "producerAt": report.get("at"),
                          "producerAreas": [a.get("area") for a in report.get("areas", [])]},
                         tool="neyvia.verify.status", boundary="Exact fresh candidate producer receipt read"))
    # Independent persistence check: bytes created by the real candidate producer,
    # not a success fixture, and still identical after the authored reader ran.
    path = Path(root) / ".agent_control/proofs/latest.json"
    durable = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    checks.append(_check("c8e.real-report-persisted", durable == report,
                         {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()
                          if path.is_file() else None, "producerAt": report.get("at")},
                         boundary="Real production persistence independently re-read"))
    wanted = set(effect.get("producerAreas", []))
    areas = report.get("areas", [])
    actual = {a.get("area") for a in areas}
    area_passed = bool(wanted) and actual == wanted and all(a.get("ok") is True for a in areas)
    checks.append(_check("c8e.producer-contract-actions", area_passed,
                         {"areas": areas, "sourceStable": report.get("sourceStable")},
                         boundary=effect["producerBoundary"]))
    witness_checks, witness_observed = (witness or _rendered_witness)(worker, effect, root)
    checks.extend(witness_checks)
    observed.update(witness_observed)
    # F10: pure model, fixture, reducer or hash evidence must never satisfy a
    # rendered/device/provider contract. An additive witness cannot stand in for
    # the remaining named invariant cases, even if the area runner reports ok.
    contract_effects = witness_observed.get("contractEffects", [])
    required_ids = set(effect.get("requiredContractIds", []))
    covered_ids = {c["id"] for c in contract_effects if c.get("passed") is True}
    actual_mechanism = bool(required_ids) and covered_ids == required_ids
    missing = [] if actual_mechanism else effect.get("unprovedDefiningMechanisms", [])
    mechanism_passed = area_passed and report.get("sourceStable") is True and actual_mechanism and not missing
    checks.append(_check("c8e.defining-effect", mechanism_passed,
                         {"unprovedDefiningMechanisms": missing,
                          "requiredContractIds": effect.get("requiredContractIds", []),
                          "computationProcedurePassed": area_passed and exact_status},
                         boundary=effect["boundary"]))
    observed.update(producerAt=report.get("at"), producerCallStart=state.get("producerCallStart"),
                    producerCallEnd=state.get("producerCallEnd"),
                    computationProcedurePassed=area_passed and exact_status,
                    unprovedDefiningMechanisms=missing)
    missing_prerequisite = None
    if not actual_mechanism:
        missing_prerequisite = (effect.get('missingPrerequisite') or observed.get('unprovedReason')
            or '; '.join(observed.get('missingSourceCases', []))
            or 'Fresh real defining effects remain unproved for: ' + ', '.join(sorted(required_ids - covered_ids)))
    return {"passed": all(check["passed"] for check in checks), "checks": checks, "contractEffects": contract_effects,
            "observed": observed, "boundary": effect["boundary"], "missingPrerequisite": missing_prerequisite}


def run_effects(worker, binding, inputs, root):
    """Compatibility hook when the caller cannot bracket the authored reader.

    Prefer before_manual/after_manual so the reader itself consumes the report.
    """
    if not binding.get("c8eEffect"):
        return None
    if not hasattr(worker, "c8e_effect"):
        before_manual(worker, binding, inputs, root)
    return after_manual(worker, inputs, root)
