"""Final voice transcripts use the existing workspace bus; never launch a run.

No model calls or shell execution. Ambiguous names refuse. Durable request IDs
make retries safe, including a retry after a process dies during an action.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import time
import unicodedata
import uuid
from pathlib import Path

from .ui_command_bus import now

COMMANDS = frozenset({"voice_command_command", "voice_commands_command"})
TEXT = {"type": "string"}
DEFINITIONS = [
    ("voice.command", "Resolve a final voice command through the UI bus. New chat opens a draft, never starts a run. Use dryRun to inspect; reuse requestId for retries. Approval requires the owner's voice UI.",
     {"text": {"type": "string", "maxLength": 500}, "language": TEXT, "context": {"type": "object"},
      "dryRun": {"type": "boolean"}, "final": {"type": "boolean"}, "requestId": TEXT}, ["text"]),
    ("voice.commands", "Read supported voice commands and registered apps without recording anything.", {}, []),
    ("app.open", "Open a ready app through the shared UI bus; refuses unfinished apps.", {"app": TEXT, "target": TEXT}, ["app"]),
]
GRAMMAR = [
    ("app.open", "Open an app", ["open notes", "ouvre les notes", "show files", "open mobile studio"]),
    ("pane.show", "Open settings or runtimes", ["open settings", "show runtimes", "accounts", "tidy my chats", "ouvre les réglages"]),
    ("stage.close", "Return to your chat", ["close the app", "go home", "back to the chat", "retour"]),
    ("launcher.open", "Find an app", ["open the launcher", "search for notes", "cherche fichiers"]),
    ("dashboard.open", "See working agents", ["show agents", "what's running", "open the dashboard", "qu'est-ce qui tourne"]),
    ("session.open", "Open a chat by title", ["open chat voice review", "go to voice review chat", "ouvre la conversation revue"]),
    ("newchat.open", "Prepare a new chat", ["new codex chat", "new codex chat in dictation", "new chat in neyvia about review my code", "nouvelle conversation codex dans dictation"]),
    ("composer.send", "Send what is in your box", ["send", "send it", "envoie"]),
    ("run.answer", "Answer the visible approval", ["approve", "allow it", "yes approve", "deny", "reject", "approuve", "refuse"]),
    ("run.stop", "Stop the visible run", ["stop", "stop the run", "cancel that", "arrête"]),
    ("view.theme", "Change the theme", ["dark theme", "light theme", "sunset theme", "night green theme", "terminal theme", "paper theme", "ember theme", "forest", "morning", "thème sombre"]),
    ("view.layout", "Change density", ["calm", "workshop", "grove mode"]),
    ("sidebar.toggle", "Show or hide the sidebar", ["hide the sidebar", "show the sidebar", "cache la barre"]),
    ("dictation.start", "Dictate into your box or Notes", ["dictate", "start dictation", "take a note", "dicte", "prends une note"]),
    ("voice.help", "See voice commands", ["help", "what can I say", "aide", "qu'est-ce que je peux dire"]),
]
ALIASES = {"notes": ["note", "les notes"], "files": ["fichiers", "les fichiers"],
           "pdf": ["pdf reader"], "image-studio": ["images", "image studio"],
           "mobile-studio": ["mobile", "mobile studio", "studio mobile"],
           "doc-editor": ["documents", "document editor"]}
HARNESSES = {"codex": "Codex", "claude": "Claude", "neyvia": "Neyvia", "opencode": "OpenCode"}
PANE_APPS = {name: name for name in ("outputs", "perception", "file", "diff", "artifact", "terminal", "runtime", "settings", "accounts", "browser", "mission", "replay", "builder")}
# These implemented tool screens are hosted by the single shell.
# Accepted navigation is an event request; only a rendered UI ack proves opening.
TOOL_APPS = {
    "agent": "canopy", "builder-review": "workshop", "notebook": "shadow",
    "lab": "workshop", "library": "shadow", "phone": "workshop",
    "preview": "workshop", "harnesses": "roots", "skills": "roots",
    "rule-sets": "roots", "image-playground": "shadow", "app-factory": "workshop",
    "ios-studio": "workshop", "lumaforge": "workshop", "frameweave": "workshop",
    "citecraft": "workshop", "aegis-range": "workshop", "cueledger": "workshop",
    "marketplace": "workshop", "office-suite": "workshop", "personal-mesh": "workshop",
    "security": "workshop", "mcp-broker": "workshop",
}


class Refusal(ValueError):
    def __init__(self, message, status="refused", choices=None):
        super().__init__(message)
        self.status, self.choices = status, choices or []


def clean(text):
    text = unicodedata.normalize("NFKC", text).replace("’", "'").strip()
    prefix = r"^(?:please|can you|could you|hey neyvia|neyvia|ok(?:ay)?|um|uh|s'il te pla[iî]t|peux[- ]tu)[,\s:]+"
    for _ in range(8):
        updated = re.sub(prefix, "", text, count=1, flags=re.I)
        if updated == text:
            break
        text = updated
    # A trailing "please" inside an explicit new-chat prompt is content.
    if not (re.match(r"^(?:new|start|create|nouvelle conversation)\b", text, re.I)
            and re.search(r"[,;:\s]+(?:about|saying|to|pour|qui dit)[\s:]+", text, re.I)):
        text = re.sub(r"[,\s]+(?:please|s'il te pla[iî]t)[.!?]*$", "", text, flags=re.I)
    return text.strip()


def normalized(text):
    text = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w']+", " ", text).split())


def parse(text, *, final=True):
    if not isinstance(text, str) or len(text) > 500:
        raise Refusal("Give a voice command of at most 500 characters")
    if final is not True:
        raise Refusal("Wait for the final transcript")
    raw, exact = clean(text), {}
    phrase = normalized(raw)
    groups = [
        ("stage.close", {}, ["close", "close the app", "go home", "back to the chat", "ferme", "retour"]),
        ("launcher.open", {"query": ""}, ["open the launcher", "open launcher"]),
        ("dashboard.open", {}, ["show agents", "what's running", "open the dashboard", "qu'est ce qui tourne"]),
        ("composer.send", {}, ["send", "send it", "envoie"]),
        ("sidebar.toggle", {"hidden": True}, ["hide the sidebar", "cache la barre"]),
        ("sidebar.toggle", {"hidden": False}, ["show the sidebar", "montre la barre"]),
        ("voice.help", {}, ["help", "what can i say", "aide", "qu'est ce que je peux dire"]),
        ("run.answer", {"decision": "approve"}, ["approve", "approve that", "allow it", "yes approve", "approuve", "autorise"]),
        ("run.answer", {"decision": "deny"}, ["deny", "decline", "reject", "refuse"]),
        ("run.stop", {}, ["stop", "stop the run", "cancel that", "arrete"]),
        ("dictation.start", {"target": "composer"}, ["dictate", "start dictation", "dicte"]),
        ("dictation.start", {"target": "notes"}, ["take a note", "prends une note"]),
    ]
    for theme, names in {"dark": ["dark", "forest", "sombre"], "light": ["light", "morning", "clair"],
                         "sunset": ["sunset"], "night": ["night", "night green"],
                         "terminal": ["terminal", "matrix"], "paper": ["paper"], "ember": ["ember"]}.items():
        groups.append(("view.theme", {"theme": theme}, [word for name in names for word in [name, name + " theme", "theme " + name]]))
    for level in ["calm", "workshop", "grove"]:
        groups.append(("view.layout", {"level": level}, [level, level + " mode"]))
    for intent, args, words in groups:
        exact.update({word: (intent, args) for word in words})
    if phrase in exact:
        intent, args = exact[phrase]
        return {"intent": intent, "args": dict(args)}
    match = re.fullmatch(r"(?:search for|find|cherche) (.+)", phrase)
    if match:
        return {"intent": "launcher.open", "args": {"query": match[1]}}
    match = re.fullmatch(r"(?:open chat|open conversation|ouvre la conversation) (.+)|go to (.+) chat", phrase)
    if match:
        return {"intent": "session.open", "args": {"name": match[1] or match[2]}}
    if re.match(r"^(?:(?:new|start|create)(?: a)? |nouvelle conversation )", phrase):
        prompt = re.search(r"[,;:\s]+(?:about|saying|to|pour|qui dit)[\s:]+(.+)$", raw, re.I)
        main = normalized(raw[:prompt.start()] if prompt else raw)
        pattern = (r"(?:new|start|create)(?: a)?(?: (codex|claude(?: code)?|neyvia|opencode))? chat"
                   r"(?: (?:in|dans) (.+))?|nouvelle conversation(?: (codex|claude(?: code)?|neyvia|opencode))?(?: dans (.+))?")
        match = re.fullmatch(pattern, main)
        if match:
            app, project = match[1] or match[3], match[2] or match[4]
            if not app and project in HARNESSES:
                app, project = project, None
            args = {"dictate": not bool(prompt)}
            if app:
                args["app"] = "claude" if app.startswith("claude") else app
            if project:
                args["project"] = project
            if prompt:
                args["prompt"] = prompt[1]
            return {"intent": "newchat.open", "args": args}
    target = re.sub(r"^(?:open|show|go to|ouvre|ouvrir|va dans) (?:the |les |le |la )?", "", phrase)
    panes = {"settings": ("settings", ""), "reglages": ("settings", ""), "runtime": ("runtime", ""),
             "runtimes": ("runtime", ""), "accounts": ("accounts", ""), "comptes": ("accounts", ""), "tidy my chats": ("settings", "tidy")}
    if target in panes:
        kind, target = panes[target]
        return {"intent": "pane.show", "args": {"kind": kind, "target": target}}
    if target != phrase:
        return {"intent": "app.open", "args": {"name": target}}
    examples = [row for _, _, rows in GRAMMAR for row in rows]
    nearest = difflib.get_close_matches(phrase, [normalized(row) for row in examples], n=5, cutoff=.3)
    raise Refusal("I didn't recognize that command. Try open Notes or what can I say.", "no_match",
                  [{"label": row, "text": row} for row in examples if normalized(row) in nearest][:5])


def catalog():
    registry = Path(__file__).resolve().parents[2] / "config" / "neyvia_apps.json"
    suites = json.loads(registry.read_text(encoding="utf-8"))["suites"]
    apps = [{"id": row["id"], "label": row["name"], "suite": suite["id"],
             "aliases": [row["id"], row["name"], *ALIASES.get(row["id"], [])], "ready": row.get("status") == "ready"}
            for suite in suites for row in suite["apps"]]
    for name, kind in PANE_APPS.items():
        apps = [row for row in apps if row['id'] != name]
        apps.append({"id": name, "label": name.title(), "suite": "workspace", "aliases": [name], "ready": True, "pane": kind})
    for name, suite in TOOL_APPS.items():
        # One stable app id cannot be both an implemented classic screen and
        # an unfinished registry placeholder. Keep ready registry owners.
        if any(row['id'] == name and row['ready'] for row in apps):
            continue
        apps = [row for row in apps if row['id'] != name]
        apps.append({"id": name, "label": name.replace("-", " ").title(), "suite": suite,
                     "aliases": [name, name.replace("-", " ")], "ready": True})
    return {"commands": [{"intent": intent, "description": description, "examples": examples} for intent, description, examples in GRAMMAR],
            "apps": apps,
            "harnesses": [{"id": identity, "label": label} for identity, label in HARNESSES.items()]}


def choose(needle, rows, aliases, phrase):
    wanted = normalized(needle)
    tokens = set(wanted.split())
    scored = []
    for row in rows:
        names = [normalized(value) for value in aliases(row) if value]
        score = max((3 if name == wanted else 2 if name.startswith(wanted + " ") else
                     1 if tokens and tokens <= set(name.split()) else 0 for name in names), default=0)
        if score:
            scored.append((score, row))
    best = max((score for score, _ in scored), default=0)
    winners = [row for score, row in scored if score == best]
    if len(winners) == 1:
        return winners[0]
    raise Refusal("Choose which one you mean." if winners else "I couldn't find that name.",
                  "ambiguous" if winners else "no_match",
                  [{"label": row["label"], "text": phrase(row)} for row in (winners or rows)[:5]])


def sessions(service):
    rows, offset = [], 0
    while True:
        page = service.broker().list_sessions(limit=500, offset=offset, observe=False, include_harness=True)
        batch = page.get("sessions", [])
        rows.extend(batch)
        offset += len(batch)
        if len(batch) < 500 or offset >= page.get("total", offset):
            return rows
        if offset >= 5000:
            raise Refusal("Too many chats to match safely. Open the chat on screen first.")


def resolve(service, parsed, context):
    intent, args = parsed["intent"], dict(parsed["args"])
    if intent == "app.open":
        if not isinstance(args.get("target", ""), str):
            raise Refusal("App targets must be text.")
        row = choose(args.pop("name", args.get("app", "")), catalog()["apps"], lambda row: row["aliases"], lambda row: "open " + row["label"])
        if not row["ready"]:
            raise Refusal(row["label"] + " isn't ready yet.")
        if row.get("pane"):
            intent, args = "pane.show", {"kind": row["pane"], "target": args.get("target", "")}
        else:
            args.update(app=row["id"], suite=row["suite"])
    elif intent == "newchat.open" and args.get("project"):
        project = args.pop("project")
        folders = {path: {"path": path, "label": row.get("name") or Path(path).name} for path, row in service.bus.get("projects", {}).items()}
        # Resolve from every known folder, so a registered/recent collision cannot guess.
        for session in sessions(service):
            path = session.get("cwd")
            if path:
                folders.setdefault(path, {"path": path, "label": Path(path).name})
        row = choose(project, list(folders.values()), lambda row: [row["label"], Path(row["path"]).name],
                     lambda row: "new " + args.get("app", "") + " chat in " + row["label"])
        args["folder"] = {"path": row["path"], "name": row["label"]}
    elif intent == "session.open":
        rows = [{**row, "label": row.get("title") or "Untitled chat"} for row in sessions(service) if not row.get("archived")]
        row = choose(args["name"], rows, lambda row: [row["label"]], lambda row: "open chat " + row["label"])
        args = {"id": row["id"], "title": row["label"]}
    elif intent == "composer.send":
        if context.get("view") not in {"chat", "new"} or (context["view"] == "chat" and not context.get("sessionId")):
            raise Refusal("Open a chat with text in its box first.")
        args["sessionId"] = "new" if context["view"] == "new" else context["sessionId"]
    elif intent in {"run.answer", "run.stop"}:
        if context.get("sessionId"):
            run = service.broker().latest_run(context["sessionId"])
            if run and run.get("sessionId") == context["sessionId"]:
                if intent == "run.stop" and run.get("state") in {"queued", "running", "waiting_approval", "waiting_input"}:
                    return intent, {"runId": run["runId"]}
                pending = run.get("pendingRequest")
                if intent == "run.answer" and isinstance(pending, dict) and pending.get("kind") == "approval":
                    return intent, {**args, "runId": run["runId"], "requestId": pending["requestId"]}
        if intent == "run.stop":
            raise Refusal("There is no live run in this chat.")
        ids = context.get("approvalIds") or []
        if not isinstance(ids, list) or any(not isinstance(identity, str) for identity in ids):
            raise Refusal("Approval context must list the visible request IDs.")
        pending_ids = []
        for identity in dict.fromkeys(ids):
            saved = service.bus.get("approval:" + identity)
            if saved and not service.bus.get("grant:" + saved["key"], False) and not service.bus.get("denied:" + saved["key"], False):
                pending_ids.append(identity)
        if len(pending_ids) > 1:
            raise Refusal("More than one approval is visible. Choose one on screen.", "ambiguous")
        if not pending_ids:
            raise Refusal("Nothing here is waiting for your approval.")
        args["approvalId"] = pending_ids[0]
    if intent in {"composer.send", "dictation.start"}:
        if not isinstance(context.get("clientId"), str) or not 1 <= len(context["clientId"]) <= 128:
            raise Refusal("Use voice control in the window where you want to send or dictate.")
        args["clientId"] = context["clientId"]
    elif intent == "newchat.open" and context.get("clientId"):
        args["clientId"] = context["clientId"]
    return intent, args


def execute(service, intent, args):
    events, receipt = [], None
    def emit(action, payload):
        events.append(service.bus.emit(action, payload))
    if intent == "run.answer":
        if args.get("runId"):
            receipt = service.broker().answer(args["runId"], args["requestId"], {"decision": args["decision"]})
        elif args["decision"] == "approve":
            receipt = service.approve(args["approvalId"])
        else:
            receipt = service.decline(args["approvalId"])
            if receipt.get("event"):
                events.append(receipt["event"])
        say = "Approved." if args["decision"] == "approve" else "Declined."
        emit("notify", {"level": "success", "message": say})
    elif intent == "run.stop":
        receipt = service.broker().stop(args["runId"])
        say = "Stop requested."
        emit("notify", {"level": "info", "message": say})
    else:
        if intent in {"pane.show", "view.layout", "view.theme"}:
            receipt = service.call(intent, args)
            events.append(receipt["event"])
        elif intent == "dictation.start" and args["target"] == "notes":
            _, opened = resolve(service, {"intent": "app.open", "args": {"app": "notes"}}, {})
            emit("app.open", opened)
            emit(intent, args)
        else:
            emit(intent, args)
        say = {"app.open": "Opened " + args.get("app", "app") + ".", "newchat.open": "New " + HARNESSES.get(args.get("app"), "") + " chat" + (" in " + args["folder"]["name"] if args.get("folder") else "") + ".",
               "stage.close": "Back to your chat.", "composer.send": "Send requested.",
               "dictation.start": "Dictation requested.", "voice.help": "Here are the voice commands."}.get(intent, "Command sent.")
    return events, receipt, say


def append_audit(root, entry):
    log = root / ".neyvia" / "voice-commands.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as output:
        output.write(json.dumps(entry, ensure_ascii=False) + "\n")


def command(service, payload, *, owner=False):
    started = time.perf_counter()
    if not isinstance(payload, dict):
        raise ValueError("Voice payload must be an object")
    text = payload.get("text", "")
    request_id = payload.get("requestId") or uuid.uuid4().hex
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        raise ValueError("Use a requestId of at most 128 characters")
    context = payload.get("context") or {}
    if not isinstance(context, dict):
        raise ValueError("Voice context must be an object")
    if any(key in payload and not isinstance(payload[key], bool) for key in ("dryRun", "final")):
        raise ValueError("dryRun and final must be booleans")
    fingerprint = hashlib.sha256(json.dumps({"owner": owner, **{key: payload.get(key) for key in ("text", "context", "dryRun", "final", "language")}}, sort_keys=True).encode()).hexdigest()
    key = "voice-request:" + request_id
    result = {"requestId": request_id, "text": text[:500] if isinstance(text, str) else "", "normalized": normalized(clean(text)) if isinstance(text, str) else "",
              "intent": None, "args": {}, "events": []}
    interrupted = {**result, "ok": False, "status": "refused", "say": "This command is in progress or was interrupted. Check the screen before trying again.", "error": "Check state before using a fresh request ID"}
    # One SQLite claim across processes, before any effect. Never hold a DB
    # transaction across broker calls; a dead claimant cannot repeat an action.
    with service.bus.connect() as db:
        inserted = db.execute("INSERT OR IGNORE INTO state(key,value) VALUES(?,?)",
                              (key, json.dumps({"fingerprint": fingerprint, "result": interrupted}))).rowcount
        saved = json.loads(db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()[0])
    if not inserted:
        if saved["fingerprint"] != fingerprint:
            raise ValueError("requestId was already used for a different voice command")
        if saved["result"].get("auditPending"):
            try:
                append_audit(service.bus.root, saved["result"]["auditPending"])
                saved["result"].pop("auditPending")
                saved["result"].pop("warning", None)
                service.bus.put(key, saved)
            except OSError:
                pass  # The saved receipt still names the pending audit entry.
        return {**saved["result"], "replayed": True}
    try:
        parsed = parse(text, final=payload.get("final", True))
        result["intent"] = parsed["intent"]
        if parsed["intent"] == "run.answer" and not owner and not payload.get("dryRun"):
            raise Refusal("Use the owner's voice control to answer an approval.")
        intent, args = resolve(service, parsed, context)
        result.update(intent=intent, args=args)
        if payload.get("dryRun"):
            result.update(status="dry_run", say="Ready: " + intent.replace(".", " "))
        else:
            events, receipt, say = execute(service, intent, args)
            result.update(status="done", events=events, say=say)
            if receipt is not None:
                result["receipt"] = receipt
    except Refusal as exc:
        result.update(status=exc.status, error=str(exc), say=str(exc), choices=exc.choices)
    except Exception as exc:
        result.update(status="failed", error=str(exc)[:500], say="That command couldn't finish.")
    result["ok"] = result["status"] in {"done", "dry_run"}
    result["ms"] = round((time.perf_counter() - started) * 1000, 2)
    service.bus.put(key, {"fingerprint": fingerprint, "result": result})
    entry = {"at": now(), "text": result["text"], "language": str(payload.get("language") or "")[:20],
             "intent": result["intent"], "status": result["status"], "ms": result["ms"]}
    try:
        append_audit(service.bus.root, entry)
    except OSError:
        # Losing the audit destination must not lose the action's durable receipt
        # or turn an already-performed send into a tempting fresh retry.
        result.update(auditPending=entry, warning="The action receipt is saved; its audit file is unavailable.")
        service.bus.put(key, {"fingerprint": fingerprint, "result": result})
    return result


def call(service, name, args):
    if name == "voice.commands":
        return catalog()
    if name == "voice.command":
        return command(service, args)
    if name == "app.open":
        intent, payload = resolve(service, {"intent": name, "args": dict(args)}, {})
        if intent == "pane.show":
            from .cl.renderer_effects import show
            result = show(service, payload)
        else:
            result = service.result(intent, payload)
        return {**result, "app": payload.get("app", payload.get("kind"))}
    raise ValueError("Unknown voice command")


def handle_command(root_or_backend, name, payload, *, owner=False):
    from .neyvia_workspace_tools import workspace_for
    backend = root_or_backend if hasattr(root_or_backend, "root") else None
    root = backend.root if backend is not None else Path(root_or_backend)
    if name not in COMMANDS:
        raise ValueError("Unknown voice command")
    return catalog() if name == "voice_commands_command" else command(workspace_for(root, backend), payload, owner=owner)


def forward_command(root, name, payload):
    """Desktop child processes use the persistent owner's authenticated route."""
    import http.cookiejar
    import urllib.error
    import urllib.request
    from .connected_sessions.forward import service_port
    base = f"http://127.0.0.1:{service_port()}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def post(path, value):
        request = urllib.request.Request(base + path, data=json.dumps(value).encode(), headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=60) as response:
            return json.load(response)
    try:
        post("/api/auth/local-session", {})
        inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
        answer = post("/api/ui/voice", {**inner, "command": name, "_expectedStateRoot": str(root)})
        return answer.get("data") if answer.get("ok") else answer
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "code": "voice_service_unavailable", "error": "The voice service couldn't be reached: " + str(exc)[:200]}
    finally:
        try:
            post("/api/auth/logout", {})
        except (urllib.error.URLError, OSError, ValueError):
            pass
