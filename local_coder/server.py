"""Loopback-only dashboard API with a per-service CSRF token."""
from __future__ import annotations
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shlex
import subprocess
from urllib.parse import urlparse, unquote, quote, parse_qs
import threading
import time

from .awake import AwakeManager as Manager, AwakeChats as Chats, sleep_inhibitor
from . import ollama
from .settings import APP_ROOT, DATA_ROOT, PROFILES, DEFAULT_PROJECT
from .sandbox import Sandbox
from .attachments import FileStore, MAX_UPLOAD_BYTES, is_image
from .artifacts import extract_artifact
from .model_selection import CHAT_MODELS
from .themes import theme_snapshot
from .user_control import DatasetStore,BackupStore,change_credentials
from .preferences import (preference_settings,set_preference_settings,preference_records,
                          delete_preference_record,redact_preference_records)
from .work_queue import WorkQueue

PROFILE_ROLES = {
    '_helper': 'Read-only assistant', '_chat_fast': 'Quick chat',
    '_chat': 'Study and reasoning', '_vision': 'Image reader',
    'roadmap': 'Automatic coding builder', 'power': 'Coding builder',
    'quality': 'Coding builder', 'balanced': 'Balanced builder',
}

def model_catalog(installed_names):
    """Return one honest UI record per configured model image."""
    catalog = {}
    for key, profile in PROFILES.items():
        model = profile['model']
        item = catalog.setdefault(model, {
            'model': model, 'labels': [], 'roles': [], 'contexts': [],
            'installed': model in installed_names,
            'architecture': 'mixture-of-experts' if 'MoE' in profile['label'] else None,
        })
        if profile['label'] not in item['labels']:
            item['labels'].append(profile['label'])
        role = PROFILE_ROLES.get(key, key.lstrip('_').replace('_', ' ').title())
        if role not in item['roles']:
            item['roles'].append(role)
        if profile['num_ctx'] not in item['contexts']:
            item['contexts'].append(profile['num_ctx'])
    return sorted(catalog.values(), key=lambda item: item['model'].lower())

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address):
        self.manager=Manager();self.chats=Chats(DATA_ROOT/'chats');self.activity_lock=threading.RLock();self.token=secrets.token_hex(32)
        self.files=FileStore(DATA_ROOT/'attachments');self.upload_slots=threading.BoundedSemaphore(2);self.helper_probe_lock=threading.Lock()
        self.memories=self.chats.memories;self.knowledge=self.chats.knowledge
        self.datasets=DatasetStore(DATA_ROOT/'datasets');self.backups=BackupStore(DATA_ROOT)
        self.queue=WorkQueue(DATA_ROOT/'work-queue.json');self.queue_stop=threading.Event()
        DATA_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
        token=DATA_ROOT/"server-token";token.write_text(self.token);token.chmod(0o600)
        super().__init__(address,Handler)
        self.queue_thread=threading.Thread(target=self._dispatch_queue,daemon=True);self.queue_thread.start()

    def active_work(self):
        if self.manager.worker and self.manager.worker.is_alive():return {'kind':'code','label':'Coding task owns the local model'}
        if self.chats.worker and self.chats.worker.is_alive():return {'kind':'chat','label':'Chat reply owns the local model'}
        return None

    def _dispatch_queue(self):
        while not self.queue_stop.wait(.25):
            if self.active_work():continue
            item=self.queue.claim()
            if not item:continue
            try:
                with self.activity_lock:
                    result=self.manager.start(**item['payload']) if item['kind']=='code' else self.chats.start(**item['payload'])
                self.queue.finish(item['id'],result.get('id'))
            except Exception as exc:self.queue.finish(item['id'],error=exc)

    def server_close(self):
        self.queue_stop.set()
        if hasattr(self,'queue_thread'):self.queue_thread.join(1)
        super().server_close()

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

    def _send(self,status,body,mime="application/json",headers=None,csp=None):
        data=json.dumps(body,ensure_ascii=False).encode() if mime=="application/json" else body.encode() if isinstance(body,str) else body
        self.send_response(status);self.send_header("Content-Type",mime)
        self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy",csp or "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        for name,value in (headers or {}).items():self.send_header(name,value)
        self.end_headers();self.wfile.write(data)

    def do_GET(self):
        try:
            self._check_host();parsed=urlparse(self.path);path=parsed.path;query=parse_qs(parsed.query)
            if path=="/":
                html=(APP_ROOT/"local_coder/web/index.html").read_text().replace("__TOKEN__",self.server.token)
                return self._send(200,html,"text/html; charset=utf-8")
            if path in {"/app.js","/response-actions.js","/theme-picker.js","/settings.js","/style.css","/theme.css","/settings.css","/time-format.js"}:
                mime="text/javascript" if path.endswith(".js") else "text/css"
                return self._send(200,(APP_ROOT/"local_coder/web"/path[1:]).read_bytes(),mime)
            if path.startswith('/assets/'):
                root=(APP_ROOT/'local_coder/web/assets').resolve();asset=(root/path[len('/assets/'):]).resolve()
                if not asset.is_relative_to(root) or not asset.is_file():raise ValueError('Invalid asset')
                mime={'.js':'text/javascript','.css':'text/css','.woff2':'font/woff2'}.get(asset.suffix)
                if not mime:return self._send(404,{'error':'Not found'})
                return self._send(200,asset.read_bytes(),mime)
            if path=="/api/theme":return self._send(200,theme_snapshot())
            if path=="/api/info":
                try:models=ollama.api("/api/tags").get("models",[]);error=None
                except OSError as exc:models=[];error=str(exc)
                names={m["name"] for m in models}
                return self._send(200,{"project":str(DEFAULT_PROJECT),"profiles":{
                    k:{**v,"installed":v["model"] in names} for k,v in PROFILES.items() if not v.get('auxiliary')},
                    "models":model_catalog(names),
                    "vision":{"model":PROFILES['_vision']['model'],'installed':PROFILES['_vision']['model'] in names},
                    "chat_model":{"model":PROFILES['_chat']['model'],'installed':PROFILES['_chat']['model'] in names},
                    "chat_models":{k:{**v,'model':PROFILES[v['profile']]['model'],'installed':PROFILES[v['profile']]['model'] in names} for k,v in CHAT_MODELS.items()},
                    "gpu":ollama.gpu_usage(),"ram_budget_gib":16,"error":error,
                    "sleep_protection":sleep_inhibitor.status(),
                    "maintenance":(DATA_ROOT/'maintenance').exists(),
                    "team":{"builder_gpu":"RX 6600","helper_gpu":"GTX 1050 Ti",
                            "helper_model":PROFILES['_helper']['model'],'helper_installed':PROFILES['_helper']['model'] in names,
                            "aggregate_ram_gib":16,"helpers_parallel_with_builder":True},
                    "hardware":__import__('local_coder.gpu_policy',fromlist=['builder_policy']).builder_policy()})
            if path=="/api/runs":return self._send(200,self.server.manager.list())
            if path=='/api/chats':
                return self._send(200,self.server.chats.list(page=int(query.get('page',['1'])[0]),page_size=int(query.get('page_size',['50'])[0]),
                    query=query.get('query',[''])[0],archived=query.get('archived',['false'])[0].lower()=='true'))
            if path=='/api/activity':return self._send(200,{'active':self.server.active_work(),'queue':self.server.queue.list()})
            if path=='/api/queue':return self._send(200,self.server.queue.list())
            if path=='/api/attachments':return self._send(200,self.server.files.inventory(query.get('archived',['true'])[0].lower()=='true'))
            if path=='/api/memories':return self._send(200,self.server.memories.list(query.get('project',[None])[0]))
            if path=='/api/knowledge':return self._send(200,self.server.knowledge.list(query.get('project',[None])[0]))
            if path=='/api/datasets':return self._send(200,{'items':self.server.datasets.list(),'training':self.server.datasets.training_capability()})
            if path=='/api/preferences':return self._send(200,{'settings':preference_settings(DATA_ROOT),'records':preference_records(DATA_ROOT)})
            if path=='/api/backup':return self._send(200,self.server.backups.export(),headers={'Content-Disposition':'attachment; filename="lumina-backup.json"'})
            if path=='/api/account':
                credentials=DATA_ROOT/'lan/login.json'
                if not credentials.exists():return self._send(200,{'configured':False})
                saved=json.loads(credentials.read_text());return self._send(200,{'configured':True,'username':saved.get('username'),'updated_at':saved.get('updated_at')})
            parts=path.strip('/').split('/')
            if len(parts)==4 and parts[:2]==['api','chats'] and parts[3]=='continuation':
                return self._send(200,self.server.chats.continuation_preview(parts[2]))
            if len(parts)==3 and parts[:2]==['api','datasets']:
                return self._send(200,self.server.datasets.get(parts[2]))
            if len(parts)==6 and parts[:2]==['api','chats'] and parts[3]=='artifacts' and parts[5]=='preview':
                state=self.server.chats.get(parts[2]);_,message=self.server.chats.response(state,parts[4])
                artifact=extract_artifact(message['content'])
                if not artifact:return self._send(404,{'error':'Artifact unavailable'})
                return self._send(200,artifact['html'],'text/html; charset=utf-8',csp=(
                    "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
                    "style-src 'unsafe-inline'; img-src data:; font-src data:; "
                    "connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'"))
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
            limit=2*1024*1024 if path in {'/api/backup/restore','/api/datasets/import'} else 20000
            if not 0<size<=limit:raise ValueError("Request is empty or too large")
            if self.headers.get_content_type()!="application/json":raise ValueError("JSON required")
            data=json.loads(self.rfile.read(size));path=urlparse(self.path).path
            parts=path.strip('/').split('/')
            if path=='/api/account/credentials':
                if not isinstance(data,dict) or set(data)-{'current_password','username','new_password','invalidate_sessions'}:raise ValueError('Unknown credential fields')
                return self._send(200,change_credentials(DATA_ROOT,data.get('current_password'),data.get('username'),data.get('new_password'),data.get('invalidate_sessions',True)))
            if path=='/api/memories':
                if not isinstance(data,dict) or set(data)-{'id','text','scope','project','source','enabled'}:raise ValueError('Unknown memory fields')
                return self._send(200,self.server.memories.save(data.get('text'),item_id=data.get('id'),scope=data.get('scope','global'),project=data.get('project'),source=data.get('source','user'),enabled=data.get('enabled',True)))
            if len(parts)==4 and parts[:2]==['api','memories'] and parts[3]=='delete':return self._send(200,self.server.memories.delete(parts[2]))
            if path=='/api/knowledge':
                if not isinstance(data,dict) or set(data)-{'attachment_id','scope','project','label','source'}:raise ValueError('Unknown knowledge fields')
                return self._send(201,self.server.knowledge.add(**data))
            if len(parts)==4 and parts[:2]==['api','knowledge']:
                if parts[3]=='update':return self._send(200,self.server.knowledge.update(parts[2],**data))
                if parts[3]=='delete':return self._send(200,self.server.knowledge.delete(parts[2]))
            if path=='/api/datasets/import':
                if not isinstance(data,dict) or set(data)-{'name','rows','provenance','evaluation_percent'}:raise ValueError('Unknown dataset fields')
                return self._send(201,self.server.datasets.import_rows(data.get('name'),data.get('rows'),data.get('provenance','user import'),data.get('evaluation_percent',20)))
            if len(parts)==4 and parts[:2]==['api','datasets']:
                if parts[3]=='delete':return self._send(200,self.server.datasets.delete(parts[2]))
                if parts[3]=='train':raise ValueError(self.server.datasets.training_capability()['reason'])
            if path=='/api/preferences/settings':return self._send(200,set_preference_settings(DATA_ROOT,data.get('collection_enabled')))
            if path=='/api/preferences/redact':return self._send(200,redact_preference_records(DATA_ROOT))
            if path=='/api/preferences/delete':return self._send(200,delete_preference_record(DATA_ROOT,data.get('id')))
            if path=='/api/backup/restore':return self._send(200,self.server.backups.restore(data))
            if len(parts)==4 and parts[:2]==['api','attachments']:
                if parts[3]=='archive':return self._send(200,self.server.files.archive(parts[2],data.get('archived',True)))
                if parts[3]=='delete':return self._send(200,self.server.files.delete(parts[2]))
            if len(parts)==4 and parts[:2]==['api','queue']:
                if parts[3]=='cancel':return self._send(200,self.server.queue.cancel(parts[2]))
                if parts[3] in {'up','down'}:return self._send(200,self.server.queue.move(parts[2],parts[3]))
            if len(parts)==4 and parts[:2]==['api','chats']:
                chat_id,action=parts[2],parts[3]
                if action=='rename':return self._send(200,self.server.chats.rename(chat_id,data.get('title')))
                if action=='archive':return self._send(200,self.server.chats.archive(chat_id,data.get('archived',True)))
                if action=='continue-new':return self._send(201,self.server.chats.continue_from(chat_id,data.get('context')))
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
            if path=="/api/gpu/helper/check":
                if not self.server.helper_probe_lock.acquire(blocking=False):
                    return self._send(409,{"error":"A GTX helper check is already running"})
                try:
                    from .gpu_policy import builder_policy,prepare_helper
                    try:result=prepare_helper()
                    except (OSError,RuntimeError,subprocess.SubprocessError) as exc:
                        result={"available":False,"reason":"GTX helper check failed","error":str(exc)}
                    result["hardware"]=builder_policy()
                    return self._send(200,result)
                finally:self.server.helper_probe_lock.release()
            if path=="/api/runs":
                if (DATA_ROOT/'maintenance').exists():raise ValueError('Brief local maintenance; try again shortly. Saved work is preserved.')
                command=data.pop("check_command","")
                if command:
                    data["test_commands"]=[shlex.split(command)]
                allowed={"task","source","profile","project_profile","test_commands","acceptance","attachments","team","origin","auto_apply","desktop_followup"}
                if set(data)-allowed:raise ValueError("Unknown task fields")
                with self.server.activity_lock:
                    if self.server.active_work():
                        if self.headers.get('X-Lumina-Queue')!='true':raise ValueError('The local model is busy. Use the dashboard queue or wait for the active work.')
                        return self._send(202,{**self.server.queue.add('code',data,data.get('task','Coding task')),'queued':True})
                    return self._send(202,self.server.manager.start(**data))
            if path=='/api/chats':
                if (DATA_ROOT/'maintenance').exists():raise ValueError('Brief local maintenance; try again shortly. Saved work is preserved.')
                if set(data)-{'text','id','deep','web','attachments','model','structured'}:raise ValueError('Unknown chat fields')
                with self.server.activity_lock:
                    if self.server.active_work():
                        if self.headers.get('X-Lumina-Queue')!='true':raise ValueError('The local model is busy. Use the dashboard queue or wait for the active work.')
                        return self._send(202,{**self.server.queue.add('chat',data,data.get('text','Chat reply')),'queued':True})
                    return self._send(202,self.server.chats.start(**data))
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
                if parts[3]=="continue":
                    if (DATA_ROOT/'maintenance').exists():raise ValueError('Brief local maintenance; try again shortly. Saved work is preserved.')
                    with self.server.activity_lock:
                        if self.server.chats.worker and self.server.chats.worker.is_alive():raise ValueError('Chat is using the model. Stop it or wait for the reply before continuing.')
                        instructions=data.get('instructions','')
                        return self._send(202,self.server.manager.resume(parts[2],instructions=instructions) if instructions else self.server.manager.resume(parts[2]))
                if parts[3]=="follow-up":
                    if (DATA_ROOT/'maintenance').exists():raise ValueError('Brief local maintenance; try again shortly. Saved work is preserved.')
                    with self.server.activity_lock:
                        if self.server.chats.worker and self.server.chats.worker.is_alive():raise ValueError('Chat is using the model. Stop it or wait before creating a follow-up.')
                        return self._send(202,self.server.manager.followup(parts[2],data.get('instructions','')))
                if parts[3]=="auto-solve":
                    if (DATA_ROOT/'maintenance').exists():raise ValueError('Brief local maintenance; try again shortly. Saved work is preserved.')
                    with self.server.activity_lock:
                        if self.server.chats.worker and self.server.chats.worker.is_alive():raise ValueError('Chat is using the model. Stop it or wait for the reply before auto-solving.')
                        return self._send(202,self.server.manager.resume(parts[2],auto=True))
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
        sleep_inhibitor.close()
        server.server_close()
