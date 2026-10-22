"""Shared fixtures for real-host smoke tests: a real OpenAPE HTTP engine and a
synthetic model endpoint (Anthropic Messages + OpenAI Chat Completions shapes).

The synthetic endpoint records every request body so tests can prove which style
text reached the model transport. It is NOT a live LLM; results are lifecycle
evidence only, never behavioural evidence.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
MARKER='Style preferences only.'

def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

class Engine:
    def __init__(self,tmp,token,personas,users=(),scopes=('persona:express','persona:admin','observations:write','feedback:write','training:admin')):
        self.port=free_port();self.url=f'http://127.0.0.1:{self.port}';self.token=token;self.tmp=Path(tmp)
        self.env={**os.environ,'OPENAPE_CREDENTIALS':json.dumps([dict(token=token,tenant='local',actor='host-smoke',scopes=list(scopes),personas=list(personas),users=list(users))])}
        self.log=open(self.tmp/'engine.log','a')
        self.proc=subprocess.Popen([sys.executable,'-m','sdk.cli.main','serve','--port',str(self.port),'--data',str(self.tmp/'engine-data')],cwd=ROOT,env=self.env,stdout=self.log,stderr=self.log)
        self.http=httpx.Client(base_url=self.url,headers={'Authorization':'Bearer '+token},trust_env=False,timeout=10)
        for _ in range(200):
            try:
                if self.http.get('/health/ready').status_code==200:break
            except httpx.TransportError:pass
            time.sleep(.05)
        else:raise RuntimeError('engine startup timed out')
    def post(self,path,body):
        r=self.http.post(path,json={'protocol_version':'upap/1',**body});r.raise_for_status();return r.json()
    def rows(self,sql):
        import sqlite3
        db=sqlite3.connect(self.tmp/'engine-data'/'openape.sqlite');db.row_factory=sqlite3.Row
        try:return [dict(r) for r in db.execute(sql)]
        finally:db.close()
    def stop(self):
        if self.proc.poll() is None:self.proc.terminate();self.proc.wait(timeout=10)
    def close(self):
        self.stop();self.http.close();self.log.close()

class SyntheticModel:
    """Minimal model endpoint. Records request bodies; answers with fixed text."""
    def __init__(self,reply='Synthetic host transport response.'):
        self.requests=[];outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def _json(self,code,obj):
                body=json.dumps(obj).encode();self.send_response(code);self.send_header('content-type','application/json');self.send_header('content-length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_GET(self):
                if self.path.rstrip('/').endswith('/models'):return self._json(200,{'object':'list','data':[{'id':'synthetic-model','object':'model','owned_by':'synthetic'}]})
                self._json(404,{'error':{'type':'not_found','message':'synthetic endpoint'}})
            def do_POST(self):
                raw=self.rfile.read(int(self.headers.get('content-length') or 0))
                try:body=json.loads(raw or b'{}')
                except ValueError:body={}
                outer.requests.append(dict(path=self.path,body=body))
                if 'count_tokens' in self.path:return self._json(200,{'input_tokens':10})
                if self.path.split('?')[0].endswith('/messages'):return self.anthropic(body)
                if self.path.split('?')[0].endswith('/chat/completions'):return self.openai(body)
                self._json(404,{'error':{'type':'not_found','message':'synthetic endpoint'}})
            def anthropic(self,body):
                model=body.get('model','synthetic-model');usage={'input_tokens':10,'output_tokens':5}
                msg={'id':'msg_synthetic','type':'message','role':'assistant','model':model,'content':[{'type':'text','text':reply}],'stop_reason':'end_turn','stop_sequence':None,'usage':usage}
                if not body.get('stream'):return self._json(200,msg)
                self.send_response(200);self.send_header('content-type','text/event-stream');self.send_header('cache-control','no-cache');self.end_headers()
                events=[('message_start',{'type':'message_start','message':{**msg,'content':[],'stop_reason':None}}),
                    ('content_block_start',{'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}}),
                    ('content_block_delta',{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':reply}}),
                    ('content_block_stop',{'type':'content_block_stop','index':0}),
                    ('message_delta',{'type':'message_delta','delta':{'stop_reason':'end_turn','stop_sequence':None},'usage':{'output_tokens':5}}),
                    ('message_stop',{'type':'message_stop'})]
                for name,data in events:self.wfile.write(f'event: {name}\ndata: {json.dumps(data)}\n\n'.encode());self.wfile.flush()
            def openai(self,body):
                model=body.get('model','synthetic-model');created=int(time.time())
                if not body.get('stream'):
                    return self._json(200,{'id':'chatcmpl-synthetic','object':'chat.completion','created':created,'model':model,'choices':[{'index':0,'message':{'role':'assistant','content':reply},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}})
                self.send_response(200);self.send_header('content-type','text/event-stream');self.end_headers()
                chunks=[{'role':'assistant','content':''},{'content':reply}]
                for delta in chunks:
                    self.wfile.write(('data: '+json.dumps({'id':'chatcmpl-synthetic','object':'chat.completion.chunk','created':created,'model':model,'choices':[{'index':0,'delta':delta,'finish_reason':None}]})+'\n\n').encode())
                self.wfile.write(('data: '+json.dumps({'id':'chatcmpl-synthetic','object':'chat.completion.chunk','created':created,'model':model,'choices':[{'index':0,'delta':{},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}})+'\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
        self.server=ThreadingHTTPServer(('127.0.0.1',free_port()),Handler);self.url=f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
    def model_requests(self):
        return [r for r in self.requests if r['path'].split('?')[0].endswith(('/messages','/chat/completions'))]
    def close(self):self.server.shutdown()

def count_marker(obj):
    return json.dumps(obj).count(MARKER)

def write_report(name,report):
    path=ROOT/'docs/reports'/f'{name}.json';path.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
