"""Browser adapter for the situation protocol, using existing origin and action gates."""
import uuid
import base64
import hashlib
import json
import time
from pathlib import Path
from .situation_interface import SituationStore, ACTIONS, digest, text
from .action_receipts import NativeActionStore


class SituationBrowser:
    def __init__(self, server):
        self.server = server
        self.page_identity = None
        self.attachment_id = None

    def tool_result(self, payload):
        result = self.server._tool_result(payload,is_error=payload.get("ok") is False)
        crop = (payload.get("vision") or {}).get("crop") or {}
        if crop.get("ok") and crop.get("path"):
            path = Path(crop["path"]).resolve()
            path.relative_to(self.server.root / ".agent_control" / "mission_artifacts" / "situations")
            if path.stat().st_size > 2_000_000:
                raise ValueError("Vision crop exceeds two megabytes")
            pixels = path.read_bytes()
            if hashlib.sha256(pixels).hexdigest()!=crop.get("sha256"):
                raise ValueError("Vision artifact changed after capture")
            result["content"].append({"type":"image","mimeType":"image/png","data":base64.b64encode(pixels).decode()})
        return result

    def capture(self, store, *, url=None):
        server = self.server
        page = server.ui_tools.attached_page
        if url and (page is None or page.url != url):
            attached = server._run_workspace_browser({"operation":"inspect","url":url,"missionId":store.work_id})
            if attached.get("ok") is False:
                raise RuntimeError("Browser attachment failed: " + str(attached.get("status") or attached.get("message") or "inspect failed"))
            page = server.ui_tools.attached_page
        if page is None:
            raise ValueError("No attached browser. Use observe with arguments.url set to an approved Preview URL")
        server._preflight_browser_mutation({})  # Same approved-origin boundary also applies to observations.
        server.ui_tools.observe_page(page)
        server._preflight_browser_mutation({})
        # Navigation back to the same URL must invalidate old object handles too.
        epoch = page.evaluate("() => performance.timeOrigin")
        if page.url != server.ui_tools.graph.url:
            raise ValueError("Page navigated during observation; refresh before using it")
        identity = (id(page), page.url, epoch)
        if identity != self.page_identity:
            self.page_identity, self.attachment_id = identity, uuid.uuid4().hex
        return store.capture(server.ui_tools.graph, self.attachment_id)

    def call(self, verb, work_id, args, *, may_change=False):
        store = SituationStore(self.server.root, work_id)
        if not isinstance(args, dict) or len(str(args))>64000:
            raise ValueError("Situation arguments must be a bounded object")
        if verb == "observe":
            # Reject invalid view requests before navigation or artifact creation.
            store.view(focus=args.get("focus",""), presentation=args.get("presentation","structured"),
                       max_characters=args.get("maxCharacters",6000))
            freshness = args.get("freshness", "required")
            age_limit = args.get("maxAgeSeconds", 5)
            dependencies = args.get("dependsOn", [])
            if freshness not in {"required", "bounded"} or type(age_limit) not in {int, float} or not 0 <= age_limit <= 30:
                raise ValueError("Choose required or bounded freshness and a maximum age from 0 to 30 seconds")
            if not isinstance(dependencies, list) or len(dependencies) > 32 or any(not isinstance(item, str) or len(item) > 160 for item in dependencies):
                raise ValueError("dependsOn must contain at most 32 observed object identities")
            frame = store.frame()
            contract = store._read()["contract"]
            reusable = bool(freshness == "bounded" and frame and contract
                and 0 <= time.time()-frame["observedAt"] <= age_limit
                and frame["contractHash"] == digest(contract)
                and (not args.get("url") or frame["url"] == args["url"])
                and set(dependencies).issubset({row["objectId"] for row in frame["objects"]}))
            if not reusable:
                self.capture(store,url=args.get("url"))
            result = store.view(focus=args.get("focus",""), presentation=args.get("presentation","structured"),
                                max_characters=args.get("maxCharacters",6000),action_authorized=may_change and not reusable)
            result["observationSource"] = "saved_frame" if reusable else "fresh_capture"
            if reusable:
                # Bounded-age evidence is useful for planning. Its age never
                # establishes current DOM state, attachment or action readiness.
                result.update(observationCurrent=False, executionReady=False,
                              refreshBeforeAction=True)
            budget = args.get("maxCharacters",6000)
            while result.get("objects") and len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > budget:
                result["objects"].pop()
                result["omittedObjects"] = result.get("omittedObjects", 0) + 1
            if len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > budget:
                return {"status": "protected_context_overflow", "workId": work_id, "executionReady": False,
                        "nextAction": {"verb": "inspect", "facet": "contract"}}
            return result
        if verb == "recall":
            # A saved observation cannot establish a currently attached browser.
            return store.view(focus=args.get("focus",""), presentation=args.get("presentation","structured"),
                              max_characters=args.get("maxCharacters",6000),frame_id=args.get("frameId"),action_authorized=False)
        if verb == "inspect":
            if args.get("facet") == "action":
                actions = NativeActionStore(self.server.root, "situation:"+work_id)
                return actions.inspect(args["actionId"]) if args.get("actionId") else actions.list()
            result = store.inspect(args.get("frameId"),args.get("objectId"),args.get("facet","object"))
            if args.get("vision"):
                saved = store.frame(args.get("frameId"))
                fresh = self.capture(store)
                if saved["graphHash"]!=fresh["graphHash"] or saved["attachmentId"]!=fresh["attachmentId"]:
                    raise ValueError("Visual reference is stale; observe again")
                node = store.object(fresh,args["objectId"])
                if {"protected","password"}.intersection(node["states"]):
                    raise ValueError("Protected controls cannot be captured through this interface")
                page = self.server.ui_tools.attached_page
                locator = page.get_by_role(node["role"],name=node["name"],exact=True)
                if locator.count()!=1:
                    raise ValueError("Visual target is absent or ambiguous")
                box = locator.bounding_box(timeout=3000)
                if not box:
                    raise ValueError("Visual target has no visible bounds")
                target = self.server.ui_tools.graph.get(node["nodeId"])
                path = store.root / ".agent_control" / "mission_artifacts" / "situations" / store.base.name / ("crop-"+uuid.uuid4().hex+".png")
                crop = self.server.ui_tools.observer.capture_node_crop(target,page=page,path=path,clip=box)
                checked = self.capture(store)
                if checked["graphHash"]!=fresh["graphHash"] or checked["attachmentId"]!=fresh["attachmentId"]:
                    raise ValueError("Page changed during visual capture; observe again")
                if crop.get("ok"):
                    crop["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                result["vision"] = {"frameId":fresh["frameId"],"crop":crop,"ok":crop.get("ok",False)}
            result["revision"] = store._read()["revision"]
            return result
        if verb == "compare":
            return store.compare(args["before"],args["after"])
        if verb == "assert":
            frame = self.capture(store)
            before = store.frame(args["beforeFrameId"]) if args.get("beforeFrameId") else None
            checks = args.get("checks", [])
            if not checks:
                raise ValueError("At least one assertion is required")
            result = store.verify_effects(frame, checks, before=before)
            result["taskComplete"] = result["matched"]
            return result
        if verb == "verify":
            frame = self.capture(store)
            return store.verify(frame,args["objectId"],args["expected"])
        if verb == "journey":
            operation = args.get("operation")
            if operation == "save":
                return {"status":"saved", "journey":store.save_journey(args.get("journeyId"),args.get("steps"),
                    args.get("acceptance"),args.get("sourceDigest"))}
            if operation == "inspect":
                journey_id = text(args.get("journeyId"),96)
                if args.get("runId") is not None:
                    record = store.journey_run(journey_id,text(args.get("runId"),96))
                    return record if record else {"status":"not_found","journeyId":journey_id,"runId":args["runId"]}
                journey = store.journey(journey_id)
                return journey if journey else {"status":"not_found","journeyId":journey_id}
            if operation != "replay":
                raise ValueError("Journey operation must be save, inspect or replay")
            if not may_change:
                raise PermissionError("Browser mutation authority is not granted to this situation interface")
            journey_id, run_id = text(args.get("journeyId"),96), text(args.get("runId"),96)
            journey = store.journey(journey_id)
            if not journey:
                raise ValueError("Save the journey before replaying it")
            if journey.get("sourceDigest") and args.get("sourceDigest") != journey["sourceDigest"]:
                raise ValueError("Source digest does not match the saved journey; proof is stale")
            reload_after = args.get("reload", False)
            if type(reload_after) is not bool:
                raise ValueError("reload must be boolean")
            reload_checks = args.get("reloadAssertions", [])
            store.validate_assertions(reload_checks)
            if reload_after and not reload_checks:
                raise ValueError("Reload verification requires at least one reload assertion")
            run = {"journeyId":journey_id,"runId":run_id,"sourceDigest":journey.get("sourceDigest"),
                   "taskContractHash":journey.get("taskContractHash"),
                   "startedAt":time.time(),"steps":[],"status":"running","accepted":False,
                   "reloadRequested":reload_after}
            store.save_journey_run(journey_id,run_id,run)
            for index, step in enumerate(journey["steps"]):
                before = self.capture(store)
                matches = [row for row in before["objects"] if row["role"] == step["target"]["role"] and row["name"] == step["target"]["name"]]
                if len(matches) != 1:
                    outcome = {"ok":False,"status":"target_absent_or_ambiguous","target":step["target"],"matchCount":len(matches)}
                else:
                    journey_run_key = digest([journey_id,run_id])[:32]
                    step_action_id = f"journey:{journey_run_key}:{index}"
                    existing_action = NativeActionStore(self.server.root,"situation:"+work_id).inspect(step_action_id)
                    if existing_action.get("status") == "completed":
                        check = store.verify_effects(before,step["assertions"])
                        outcome = {"ok":check["matched"],"status":"previous_action_rechecked" if check["matched"] else "prior_effect_unproven",
                                   "duplicateSuppressed":True,"freshVerification":check,
                                   "toolResult":{"before":before["frameId"],"after":before["frameId"],
                                       "actionReceiptPath":existing_action.get("actionReceiptPath"),"taskComplete":False}}
                    elif existing_action.get("status") in {"pending","uncertain"}:
                        outcome = {"ok":False,"status":"action_uncertain","actionId":step_action_id,
                                   "actionReceiptPath":existing_action.get("actionReceiptPath"),
                                   "message":"A prior attempt may have changed state; inspect and recover explicitly."}
                    else:
                        action_args = {"frameId":before["frameId"],"objectId":matches[0]["objectId"],
                        "target":step["target"],"action":step["action"],"actionId":step_action_id,
                        "assertions":step["assertions"],**step["args"]}
                        outcome = self.call("change",work_id,action_args,may_change=True)
                run["steps"].append({"index":index,"target":step["target"],"beforeFrameId":before["frameId"],"result":outcome,
                    "afterFrameId":(outcome.get("toolResult") or {}).get("after")})
                run["status"] = "running" if outcome.get("ok") is True else "failed"
                store.save_journey_run(journey_id,run_id,run)
                if outcome.get("ok") is not True:
                    run["finishedAt"] = time.time()
                    store.save_journey_run(journey_id,run_id,run)
                    return run
            acceptance_frame = self.capture(store)
            acceptance = store.verify_effects(acceptance_frame,journey["acceptance"])
            run.update(acceptance=acceptance,acceptanceFrameId=acceptance_frame["frameId"],status="verified" if acceptance["matched"] else "acceptance_failed")
            if reload_after and acceptance["matched"]:
                page = self.server.ui_tools.attached_page
                current_url = acceptance_frame["url"]
                self.server._preflight_browser_mutation({"url":current_url})
                action_store = NativeActionStore(self.server.root,"situation:"+work_id)
                reload_id = f"journey:{digest([journey_id,run_id])[:32]}:reload"
                def reload_page():
                    page.reload(wait_until="domcontentloaded",timeout=5000)
                    if page.url != current_url:
                        return {"ok":False,"status":"reload_navigated_away","finalUrl":page.url}
                    return {"ok":True,"status":"reloaded","url":page.url}
                reload_result = action_store.execute(reload_id,"situation.journey.reload",{"journeyId":journey_id,"runId":run_id,"url":current_url},reload_page,
                    preflight=lambda:self.server._preflight_browser_mutation({"url":current_url}))
                run["reload"] = reload_result
                if reload_result.get("ok") is True:
                    after_reload = self.capture(store)
                    proof = store.verify_effects(after_reload,reload_checks)
                    run.update(reloadFrameId=after_reload["frameId"],reloadAcceptance=proof,
                               status="verified" if proof["matched"] else "persistence_failed")
                else:
                    run["status"] = "reload_unproven"
            run["accepted"] = run["status"] == "verified" and acceptance["matched"] and (not reload_after or (run.get("reloadAcceptance") or {}).get("matched") is True)
            run["taskComplete"] = run["accepted"]
            run["finishedAt"] = time.time()
            store.save_journey_run(journey_id,run_id,run)
            return run
        if verb != "change":
            raise ValueError("Unknown situation verb")
        if not may_change:
            raise PermissionError("Browser mutation authority is not granted to this situation interface")
        action_id = text(args.get("actionId"),160)
        action = args.get("action")
        if action not in ACTIONS:
            raise ValueError("Unsupported situation action")
        for key in ACTIONS[action]["arguments"]:
            if not isinstance(args.get(key),str) or len(args[key])>16000:
                raise ValueError("Action requires bounded string argument: "+key)
        saved = store.frame(args["frameId"])
        if not saved:
            raise ValueError("Observe the browser before requesting a change")
        # Validate the postcondition's shape before entering an uncertain mutation.
        object_id = args.get("objectId")
        if args.get("target") is not None:
            target_selector = args["target"]
            if not isinstance(target_selector,dict) or set(target_selector)!={"role","name"}:
                raise ValueError("target requires exact role and name")
            text(target_selector["role"],160); text(target_selector["name"],2000)
            matched = [row for row in saved["objects"] if row["role"] == target_selector["role"] and row["name"] == target_selector["name"]]
            if len(matched) != 1:
                raise ValueError("Observed role/name target is absent or ambiguous")
            if object_id and object_id != matched[0]["objectId"]:
                raise ValueError("objectId does not match the selected role/name target")
            object_id = matched[0]["objectId"]
        checks = args.get("assertions")
        if args.get("expected") is not None:
            store.verify(saved,object_id,args["expected"])
        elif checks is not None:
            store.validate_assertions(checks)
            if not checks:
                raise ValueError("An action requires at least one post-action assertion")
        else:
            raise ValueError("An action requires expected or assertions")
        self.server._preflight_browser_mutation({"url":saved["url"]})
        actions = NativeActionStore(self.server.root,"situation:"+work_id)
        prepared = {}
        def preflight():
            fresh = self.capture(store)
            node = store.validate_change(saved,fresh,object_id,action)
            prepared.update(fresh=fresh,node=node)
        def execute():
            fresh, node = prepared["fresh"], prepared["node"]
            arguments = {"id":node["nodeId"],"ifRev":fresh["graphRevision"],"ifHash":self.server.ui_tools.graph.semantic_hash}
            for key in ACTIONS[action]["arguments"]:
                arguments[key] = args[key]
            effect = self.server._run_workspace_browser({"operation":action,"arguments":arguments,
                "url":fresh["url"],"missionId":work_id,"actionId":"situation-"+digest([work_id,action_id])[:48]})
            after = self.capture(store)
            verification = (store.verify(after,object_id,args["expected"]) if args.get("expected") is not None
                            else store.verify_effects(after,checks,before=saved))
            passed = effect.get("ok") is True and verification["matched"]
            return {"ok":passed,"status":"verified" if passed else "postcondition_unproven",
                    "toolResult":{"before":saved["frameId"],"after":after["frameId"],"verification":verification,
                                  "actionReceiptPath":effect.get("actionReceiptPath"),"taskComplete":False}}
        result = actions.execute(action_id,"situation.change",args,execute,preflight=preflight)
        # A saved result describes that action, not the current application state.
        return {**result,"freshVerificationRequired":bool(result.get("duplicateSuppressed"))}
