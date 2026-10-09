"""Loopback static host and CAS bridge for generated apps; no implicit port."""
from __future__ import annotations
import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .app_sdk import state_api,commit_api,descriptor,build_app


def serve(project,port):
    project=Path(project).resolve();descriptor(project)
    if type(port) is not int or not 1<=port<=65535:raise ValueError('Explicit port required')
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(project/'www'),**kwargs)
        def log_message(self,*args):pass
        def end_headers(self):self.send_header('Cache-Control','no-store');super().end_headers()
        def send_json(self,value,status=200):
            body=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if urlsplit(self.path).path=='/__neyvia/state':self.send_json(state_api(project));return
            if any(part.startswith('.') for part in urlsplit(self.path).path.split('/') if part):self.send_error(403);return
            super().do_GET()
        def do_POST(self):
            if urlsplit(self.path).path!='/__neyvia/commit':self.send_error(404);return
            if self.headers.get('X-Neyvia-App')!='1':self.send_json({'ok':False,'error':'SDK request required'},403);return
            origin=self.headers.get('Origin')
            if origin and origin not in {f'http://127.0.0.1:{port}',f'http://localhost:{port}'}:self.send_json({'ok':False,'error':'Origin denied'},403);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=65536:raise ValueError('Body must be 1..65536 bytes')
                value=commit_api(project,json.loads(self.rfile.read(length)))
                self.send_json(value)
            except (ValueError,TypeError,KeyError) as error:self.send_json({'ok':False,'error':str(error)},409)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    try:server.serve_forever()
    finally:server.server_close()


def main(project):
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int);parser.add_argument('--build',action='store_true');args=parser.parse_args()
    if args.build:print(json.dumps(build_app(project,{'project':'.','platform':'web'})));return
    if args.port is None:parser.error('--port is required')
    serve(project,args.port)
