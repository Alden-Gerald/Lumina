"""Loopback-only dashboard API with a per-service CSRF token."""
from __future__ import annotations
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shlex
from urllib.parse import urlparse

from .controller import Manager
from . import ollama
from .settings import APP_ROOT, DATA_ROOT, PROFILES, DEFAULT_PROJECT
from .sandbox import Sandbox

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address):
        self.manager=Manager();self.token=secrets.token_hex(32)
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

    def _send(self,status,body,mime="application/json"):
        data=json.dumps(body,ensure_ascii=False).encode() if mime=="application/json" else body.encode() if isinstance(body,str) else body
        self.send_response(status);self.send_header("Content-Type",mime)
        self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers();self.wfile.write(data)

    def do_GET(self):
        try:
            self._check_host();path=urlparse(self.path).path
            if path=="/":
                html=(APP_ROOT/"local_coder/web/index.html").read_text().replace("__TOKEN__",self.server.token)
                return self._send(200,html,"text/html; charset=utf-8")
            if path in {"/app.js","/style.css"}:
                mime="text/javascript" if path.endswith(".js") else "text/css"
                return self._send(200,(APP_ROOT/"local_coder/web"/path[1:]).read_bytes(),mime)
            if path=="/api/info":
                try:models=ollama.api("/api/tags").get("models",[]);error=None
                except OSError as exc:models=[];error=str(exc)
                names={m["name"] for m in models}
                return self._send(200,{"project":str(DEFAULT_PROJECT),"profiles":{
                    k:{**v,"installed":v["model"] in names} for k,v in PROFILES.items()},
                    "gpu":ollama.gpu_usage(),"ram_budget_gib":16,"error":error,
                    "hardware":__import__('local_coder.gpu_policy',fromlist=['inspect']).inspect()})
            if path=="/api/runs":return self._send(200,self.server.manager.list())
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
            if not 0<size<=20000:raise ValueError("Request is empty or too large")
            if self.headers.get_content_type()!="application/json":raise ValueError("JSON required")
            data=json.loads(self.rfile.read(size));path=urlparse(self.path).path
            if path=="/api/gpu/reserve":
                from .gpu_policy import reserve,current
                active=self.server.manager.worker
                if current().get("mode")=="dual-vulkan" and active and active.is_alive():
                    for flag in self.server.manager.cancel_flags.values():flag.set()
                return self._send(200,reserve())
            if path=="/api/gpu/release":
                from .gpu_policy import release
                return self._send(200,release())
            if path=="/api/runs":
                command=data.pop("check_command","")
                if command:
                    data["test_commands"]=[shlex.split(command)]
                allowed={"task","source","profile","project_profile","test_commands","acceptance"}
                if set(data)-allowed:raise ValueError("Unknown task fields")
                return self._send(202,self.server.manager.start(**data))
            parts=path.strip("/").split("/")
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
        server.server_close()
