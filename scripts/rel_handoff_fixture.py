"""Loopback owner hand-off fixture. This is not a CAPTCHA solver."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Page(BaseHTTPRequestHandler):
    cleared = False
    def do_GET(self):
        title, body = ('REL task result', 'Ready: REL task result') if Page.cleared else (
            'REL human-check fixture', 'CAPTCHA fixture: verify you are human. The owner clears this controlled fixture externally.')
        payload = ('<!doctype html><html><title>'+title+'</title><body style="font:24px system-ui;background:#f5f5ef;padding:40px"><h1>'+title+'</h1><p>'+body+'</p><button onclick="location.reload()">Refresh owner page</button></body></html>').encode()
        self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(payload)))
        self.end_headers(); self.wfile.write(payload)
    def do_POST(self):
        if self.path not in {'/owner-clear','/reset'}:
            self.send_error(404); return
        Page.cleared = self.path == '/owner-clear'
        self.send_response(204); self.end_headers()
    def log_message(self,*args): pass

print('REL controlled owner fixture: http://127.0.0.1:48965',flush=True)
ThreadingHTTPServer(('127.0.0.1',48965),Page).serve_forever()
