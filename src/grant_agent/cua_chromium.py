"""DOM fallback for a fresh, job-owned Chromium profile and local document.

The endpoint is reserved at launch, not discovered from a user's browser. No
navigation, profile adoption, input-desktop focus or global keyboard input exists.
The editor shortcut may focus one owned textarea inside the private document.
"""
from __future__ import annotations
import json
from pathlib import Path
import time
from urllib.request import urlopen
from urllib.parse import urlparse


class ChromiumDocument:
    @staticmethod
    def prepare_transport():
        # SDK initialization is service/launch setup, independent of an app's
        # unknown document. Never pay a cold import inside a bounded observation.
        from websockets.sync.client import connect
        return connect

    def __init__(self, desktop, hwnd, port, document):
        self.desktop, self.hwnd, self.port = desktop, hwnd, port
        self.document = Path(document).resolve()
        self.socket = None
        self.sequence = 0

    def command(self, method, params):
        from websockets.sync.client import connect
        if not self.desktop.disposable_target(self.hwnd):
            raise ValueError("disposable_document_expired")
        if self.socket is None:
            with urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=.3) as stream:
                targets = json.load(stream)
            token=self.desktop.disposable_target(self.hwnd)["token"]
            pages = [p for p in targets if p.get("type") == "page" and
                     (p.get("url") == self.document.as_uri() or
                      (p.get("url","").startswith("vscode-file://vscode-app/") and token in p.get("title","")))]
            if len(pages) != 1:
                raise ValueError("owned_document_page_missing_or_ambiguous")
            address = urlparse(pages[0]["webSocketDebuggerUrl"])
            if address.hostname != "127.0.0.1" or address.port != self.port:
                raise ValueError("owned_endpoint_mismatch")
            self.socket = connect(pages[0]["webSocketDebuggerUrl"], open_timeout=.3,
                                  close_timeout=.2, ping_interval=None,
                                  origin=f"http://127.0.0.1:{self.port}", proxy=None)
        self.sequence += 1
        try:
            self.socket.send(json.dumps({"id": self.sequence, "method": method, "params": params}))
            # Editor renderer work can briefly stall while its search widget
            # repaints. This bounds one request; it never replays a dispatched
            # action when the outcome is uncertain.
            deadline = time.monotonic() + (.75 if self.document.suffix.lower() == '.txt' else .3)
            while time.monotonic() < deadline:
                value = json.loads(self.socket.recv(timeout=max(.001, deadline-time.monotonic())))
                if value.get("id") == self.sequence:
                    if "error" in value: raise ValueError(str(value["error"]))
                    return value["result"]
            raise TimeoutError("owned_document_deadline")
        except (TimeoutError, OSError):
            # A late reply belongs to the abandoned command. Never dispatch
            # an action again; a later independent read must use a fresh socket.
            self.socket.close()
            self.socket = None
            raise

    def evaluate(self, expression):
        token=self.desktop.disposable_target(self.hwnd)["token"]
        uri=json.dumps(self.document.as_uri())
        quoted_token=json.dumps(token)
        expression=("(() => { if (!(location.href === "+uri+
            " || (location.href.startsWith('vscode-file://vscode-app/') && document.title.includes("+quoted_token+
            ")))) throw new Error('disposable_document_navigation'); return "+expression+"; })()")
        result = self.command("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        if "exceptionDetails" in result: raise ValueError("document_evaluation_failed")
        return result["result"].get("value")

    def inspect(self, window):
        tree = self.evaluate("""(() => Array.from(document.querySelectorAll('input,textarea,button,select')).map((e,i) => {
          const b=e.getBoundingClientRect(); const label=e.labels?.[0]?.textContent || e.getAttribute('aria-label') || e.textContent || e.name;
          return {id:'dom:'+i,parentId:null,depth:1,role:e.matches('button')?'Button':'Edit',name:label.trim(),
            className:e.tagName,automationId:e.id,enabled:!e.disabled,offscreen:!b.width||!b.height,
            isPassword:e.type==='password',readOnly:!!e.readOnly,value:e.type==='password'?null:e.value,
            patterns:e.matches('button')?['invoke']:['value'],bounds:{x:b.x,y:b.y,width:b.width,height:b.height}};
        }))()""")
        return {"window":window,"tree":tree,"source":"owned-profile.DOM", "truncated":False,
                "revision":time.monotonic_ns()}

    def request(self, op, args, window):
        began=time.perf_counter()
        if op in {"action","remoteAction"} and args.get("action")=="key":
            chord=args.get("key","").upper()
            if chord != "CTRL+F": raise NotImplementedError("Unsupported document shortcut")
            if self.document.suffix.lower() == '.txt' and self.document.parent.name.startswith('Cursor-'):
                self.evaluate("(() => { const fields=Array.from(document.querySelectorAll('textarea')).filter(e=>e.getBoundingClientRect().height>0); if(fields.length!==1) throw new Error('owned_editor_field_ambiguous'); fields[0].focus(); return document.activeElement===fields[0]; })()")
            self.command("Input.dispatchKeyEvent",{"type":"keyDown","modifiers":2,"key":"f","code":"KeyF","windowsVirtualKeyCode":70})
            self.command("Input.dispatchKeyEvent",{"type":"keyUp","modifiers":2,"key":"f","code":"KeyF","windowsVirtualKeyCode":70})
            return {"effect":"unverifiable","mechanism":"owned-profile.CDP.key","elapsedMs":(time.perf_counter()-began)*1000}
        observation=self.inspect(window)
        if op == "inspect": return observation
        if op == "inspectElements":
            wanted=args.get("elementIds",[])
            rows=[r for r in observation["tree"] if r["id"] in wanted]
            if len(rows)!=len(wanted): raise ValueError("stale_element_token")
            return {"windowId":str(self.hwnd),"tree":rows,"source":observation["source"]}
        if op not in {"action","remoteAction","cycle"}: raise NotImplementedError("Unsupported document operation")
        matches=[r for r in observation["tree"] if r["id"]==args.get("elementId")]
        if "selector" in args:
            matches=[r for r in observation["tree"] if all(str(r.get(k,''))==str(v) for k,v in args['selector'].items())]
        if len(matches)!=1: raise ValueError("stale_element_token")
        row=matches[0]
        from .cua_fast import protected, FastClient
        if protected(row) or not row["enabled"] or row["readOnly"] or row["offscreen"]:
            raise ValueError("protected_or_unavailable_field")
        for key, field in (("expectedName","name"),("expectedRole","role"),("expectedClass","className")):
            if key in args and args[key]!=row[field]: raise ValueError("stale_element_token")
        action=args.get("action")
        if action not in {"value","editSetValue","click","buttonClick"}: raise NotImplementedError("Unsupported document action")
        index=int(row["id"].split(":")[1]); text=json.dumps(str(args.get("text",args.get("value",""))))
        body=(f"e.click(); return true;" if action in {"click","buttonClick"} else
              f"const p=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;"
              f"Object.getOwnPropertyDescriptor(p,'value').set.call(e,{text});"
              "e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true})); return e.value;")
        self.evaluate(f"(() => {{const e=document.querySelectorAll('input,textarea,button,select')[{index}]; {body}}})()")
        after=self.inspect(window)
        check=FastClient.check(after['tree'],args.get('expect',[])) if args.get('expect') else None
        effect="confirmed" if check and check['status']=='satisfied' else "unverifiable"
        return {"effect":effect,"mechanism":"owned-profile.DOM","check":check,"observation":after,
                "elapsedMs":(time.perf_counter()-began)*1000,"readback":next((r.get('value') for r in after['tree'] if r['id']==row['id']),None)}

    def close(self):
        if self.socket: self.socket.close()
