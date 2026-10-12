"""Loopback-only dashboard API with a per-service CSRF token."""
from __future__ import annotations
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shlex
from urllib.parse import urlparse, unquote, quote
import threading

from .controller import Manager
from . import ollama
from .settings import APP_ROOT, DATA_ROOT, PROFILES, DEFAULT_PROJECT
from .sandbox import Sandbox
from .attachments import FileStore, MAX_UPLOAD_BYTES, is_image
from .chat import Chats
from .model_selection import CHAT_MODELS

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address):
        self.manager=Manager();self.chats=Chats(DATA_ROOT/'chats');self.activity_lock=threading.RLock();self.token=secrets.token_hex(32)
        self.files=FileStore(DATA_ROOT/'attachments');self.upload_slots=threading.BoundedSemaphore(2)
        DATA_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
        token=DATA_ROOT/"server-token";token.write_text(self.token);token.chmod(0o600)
        super().__init__(address,Handler)

class Handler(BaseHTTPRequestHandler):
    server_version="LocalCoder/0.1"
    def log_message(self,fmt,*args):pass

    def _check_host(self):
        host=self.headers.get("Host","")
        port=self.server.server_address[1]
        if host not in {f"127.0.0.1:{port}",f"localhost:{port}"}:
            raise ValueError("Invalid local Host header")
        origin=self.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{port}",f"http://localhost:{port}"}:
            raise ValueError("Cross-origin access is disabled")

    def _send(self,status,body,mime="application/json",headers=None):
        data=json.dumps(body,ensure_ascii=False).encode() if mime=="application/json" else body.encode() if isinstance(body,str) else body
        self.send_response(status);self.send_header("Content-Type",mime)
        self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        for name,value in (headers or {}).items():self.send_header(name,value)
        self.end_headers();self.wfile.write(data)

    def do_GET(self):
        try:
            self._check_host();path=urlparse(self.path).path
            if path=="/":
                html=(APP_ROOT/"local_coder/web/index.html").read_text().replace("__TOKEN__",self.server.token)
                return self._send(200,html,"text/html; charset=utf-8")
            if path in {"/app.js","/response-actions.js","/style.css","/time-format.js"}:
                mime="text/javascript" if path.endswith(".js") else "text/css"
                return self._send(200,(APP_ROOT/"local_coder/web"/path[1:]).read_bytes(),mime)
            if path.startswith('/assets/'):
                root=(APP_ROOT/'local_coder/web/assets').resolve();asset=(root/path[len('/assets/'):]).resolve()
                if not asset.is_relative_to(root) or not asset.is_file():raise ValueError('Invalid asset')
                mime={'.js':'text/javascript','.css':'text/css','.woff2':'font/woff2'}.get(asset.suffix)
                if not mime:return self._send(404,{'error':'Not found'})
                return self._send(200,asset.read_bytes(),mime)
            if path=="/api/info":
                try:models=ollama.api("/api/tags").get("models",[]);error=None
                except OSError as exc:models=[];error=str(exc)
                names={m["name"] for m in models}
                return self._send(200,{"project":str(DEFAULT_PROJECT),"profiles":{
                    k:{**v,"installed":v["model"] in names} for k,v in PROFILES.items() if not v.get('auxiliary')},
                    "vision":{"model":PROFILES['_vision']['model'],'installed':PROFILES['_vision']['model'] in names},
                    "chat_model":{"model":PROFILES['_chat']['model'],'installed':PROFILES['_chat']['model'] in names},
                    "chat_models":{k:{**v,'model':PROFILES[v['profile']]['model'],'installed':PROFILES[v['profile']]['model'] in names} for k,v in CHAT_MODELS.items()},
                    "gpu":ollama.gpu_usage(),"ram_budget_gib":16,"error":error,
                    "maintenance":(DATA_ROOT/'maintenance').exists(),
                    "team":{"builder_gpu":"RX 6600","helper_gpu":"GTX 1050 Ti",
                            "helper_model":PROFILES['_helper']['model'],'helper_installed':PROFILES['_helper']['model'] in names,
                            "aggregate_ram_gib":16,"helpers_parallel_with_builder":True},
                    "hardware":__import__('local_coder.gpu_policy',fromlist=['builder_policy']).builder_policy()})
            if path=="/api/runs":return self._send(200,self.server.manager.list())
            if path=='/api/chats':return self._send(200,self.server.chats.list())
            parts=path.strip('/').split('/')
            if len(parts)==6 and parts[:2]==['api','chats'] and parts[3]=='responses':
                id,message_id,kind=parts[2],parts[4],parts[5]
                if kind=='feedback.json':
                    body=json.dumps(self.server.chats.export_feedback(id,message_id),ensure_ascii=False,indent=2)
                elif kind=='response.md':
                    state=self.server.chats.get(id);_,m=self.server.chats.response(state,message_id)
                    body=m['content']
                    if m.get('sources'):body+='\n\nSources\n'+'\n'.join(f"[{i+1}] {source['title']}: {source['url']}" for i,source in enumerate(m['sources']))
                else:raise ValueError('Unknown download format')
                name,extension=('response','md') if kind=='response.md' else ('feedback','json')
                return self._send(200,body,'application/octet-stream',{'Content-Disposition':f'attachment; filename="{name}-{message_id[:8]}.{extension}"'})
            if path.startswith('/api/chats/'):return self._send(200,self.server.chats.get(path[len('/api/chats/'):]))
            if path.startswith('/api/attachments/'):
                image_id=path[len('/api/attachments/'):]
                metadata=self.server.files.load(image_id)
                if is_image(metadata):return self._send(200,self.server.files.path(image_id).read_bytes(),'image/jpeg')
                # Documents download as data; the browser must not execute their content.
                return self._send(200,self.server.files.path(image_id).read_bytes(),'application/octet-stream',
                    {'Content-Disposition':"attachment; filename*=UTF-8''"+quote(metadata['name'],safe='')})
            parts=path.strip("/").split("/")
            if len(parts)>=3 and parts[:2]==["api","runs"]:
                run_id=parts[2]
                if len(parts)==3:return self._send(200,self.server.manager.get(run_id))
                if parts[3]=="events":return self._send(200,self.server.manager.events(run_id))
                if parts[3]=="diff":return self._send(200,{"diff":self.server.manager.diff(run_id)})
            self._send(404,{"error":"Not found"})
        except (OSError,ValueError,KeyError) as exc:self._send(400,{"error":str(exc)})
        except (BrokenPipeError,ConnectionResetError):pass

    def do_POST(self):
        try:
            self._check_host()
            if not hmac.compare_digest(self.headers.get("X-Local-Coder-Token",""),self.server.token):
                return self._send(403,{"error":"Missing local session token"})
            size=int(self.headers.get("Content-Length","0"))
            path=urlparse(self.path).path
            if path=='/api/attachments':
                if not 0<size<=MAX_UPLOAD_BYTES:raise ValueError('Choose a file under 10MB; images under 4MB')
                if not self.server.upload_slots.acquire(blocking=False):return self._send(429,{'error':'Another file is uploading; try again shortly'})
                try:
                    self.connection.settimeout(15)
                    return self._send(201,self.server.files.save(self.rfile.read(size),unquote(self.headers.get('X-Upload-Name','Attachment'))))
                finally:self.server.upload_slots.release()
            if not 0<size<=20000:raise ValueError("Request is empty or too large")
            if self.headers.get_content_type()!="application/json":raise ValueError("JSON required")
            data=json.loads(self.rfile.read(size));path=urlparse(self.path).path
            if path=="/api/gpu/reserve":
                from .gpu_policy import reserve,current
                active=self.server.manager.worker
                if current().get("mode")=="dual-vulkan" and active and active.is_alive():
                    for flag in self.server.manager.cancel_flags.values():flag.set()
                if current().get('mode')=='dual-vulkan':
                    for flag in self.server.chats.flags.values():flag.set()
                return self._send(200,reserve())
            if path=="/api/gpu/release":
                from .gpu_policy import release
                return self._send(200,release())
            if path=="/api/runs":
                if (DATA_ROOT/'maintenance').exists():raise ValueError('Brief local maintenance; try again shortly. Saved work is preserved.')
                command=data.pop("check_command","")
                if command:
                    data["test_commands"]=[shlex.split(command)]
                allowed={"task","source","profile","project_profile","test_commands","acceptance","attachments","team"}
                if set(data)-allowed:raise ValueError("Unknown task fields")
                with self.server.activity_lock:
                    if self.server.chats.worker and self.server.chats.worker.is_alive():raise ValueError('Chat is using the model. Stop it or wait for the reply before coding.')
                    return self._send(202,self.server.manager.start(**data))
            if path=='/api/chats':
                if (DATA_ROOT/'maintenance').exists():raise ValueError('Brief local maintenance; try again shortly. Saved work is preserved.')
                if set(data)-{'text','id','deep','web','attachments','model'}:raise ValueError('Unknown chat fields')
                with self.server.activity_lock:
                    if self.server.manager.worker and self.server.manager.worker.is_alive():raise ValueError('A coding task is using the model. Stop it or wait for completion before chatting.')
                    return self._send(202,self.server.chats.start(**data))
            parts=path.strip("/").split("/")
            if len(parts)==4 and parts[:2]==['api','chats'] and parts[3]=='cancel':return self._send(200,self.server.chats.cancel(parts[2]))
            if len(parts)==4 and parts[:2]==['api','chats']:
                action=parts[3];id=parts[2]
                if action=='redo' and (DATA_ROOT/'maintenance').exists():raise ValueError('Brief local maintenance; try again shortly.')
                allowed={'feedback':{'message_id','rating','note'},'feedback-export':{'message_id'},
                    'branch':{'message_id'},'redo':{'message_id','model','deep','web'}}
                if action not in allowed:raise ValueError('Unknown response action')
                if not isinstance(data,dict) or set(data)-allowed[action]:raise ValueError('Unknown response fields')
                if action=='feedback':return self._send(200,self.server.chats.feedback(id,**data))
                if action=='feedback-export':return self._send(200,self.server.chats.export_feedback(id,**data))
                with self.server.activity_lock:
                    if action=='redo' and self.server.manager.worker and self.server.manager.worker.is_alive():raise ValueError('A coding task is using the model. Wait for completion before redoing this reply.')
                    return self._send(202 if action=='redo' else 201,self.server.chats.branch(id,redo=action=='redo',**data))
            if len(parts)==4 and parts[:2]==["api","runs"]:
                if parts[3]=="cancel":return self._send(200,self.server.manager.cancel(parts[2]))
                if parts[3]=="apply":return self._send(200,self.server.manager.apply(parts[2]))
            self._send(404,{"error":"Not found"})
        except (OSError,ValueError,KeyError,TypeError) as exc:self._send(400,{"error":str(exc)})
        except (BrokenPipeError,ConnectionResetError):pass

def serve(host="127.0.0.1",port=8787):
    if host not in {"127.0.0.1","localhost"}:raise ValueError("The dashboard must bind to loopback")
    server=Server((host,port))
    print(f"Local Coder: http://{host}:{port}",flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        for flag in server.manager.cancel_flags.values():flag.set()
        for flag in server.chats.flags.values():flag.set()
        server.server_close()
