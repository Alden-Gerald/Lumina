from __future__ import annotations
import argparse
import json
from pathlib import Path
import shlex
import sys
import time
import urllib.request

from .settings import DATA_ROOT, DEFAULT_PROJECT, PROFILES

def request(path,body=None):
    headers={"Content-Type":"application/json"}
    if body is not None:headers["X-Local-Coder-Token"]=(DATA_ROOT/"server-token").read_text().strip()
    req=urllib.request.Request("http://127.0.0.1:8787/api"+path,
        None if body is None else json.dumps(body).encode(),headers)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=30) as r:return json.load(r)

def main():
    p=argparse.ArgumentParser(description="Local Coder — bounded local coding tasks")
    sub=p.add_subparsers(dest="command",required=True)
    s=sub.add_parser("serve");s.add_argument("--port",type=int,default=8787)
    sub.add_parser("doctor");sub.add_parser("list")
    sub.add_parser("gpu-status");sub.add_parser("vm-reserve");sub.add_parser("vm-release")
    for name in ["show","diff","cancel","apply"]:
        sub.add_parser(name).add_argument("run_id")
    r=sub.add_parser("run");r.add_argument("task");r.add_argument("--source",default=str(DEFAULT_PROJECT))
    r.add_argument("--profile",choices=[k for k,v in PROFILES.items() if not v.get('auxiliary')],default="power")
    r.add_argument("--acceptance",default="");r.add_argument("--check",action="append",default=[])
    r.add_argument("--no-wait",action="store_true")
    m=sub.add_parser("mcp");m.add_argument("--source",default=str(DEFAULT_PROJECT))
    m.add_argument("--http",action="store_true");m.add_argument("--port",type=int,default=8001)
    args=p.parse_args()
    try:
        if args.command=="gpu-status":
            from .gpu_policy import inspect
            print(json.dumps(inspect(),indent=2));return
        if args.command in {"vm-reserve","vm-release"}:
            try:result=request("/gpu/"+("reserve" if args.command=="vm-reserve" else "release"),{})
            except OSError:
                from .gpu_policy import reserve,release
                result=reserve() if args.command=="vm-reserve" else release()
            print(json.dumps(result,indent=2));return
        if args.command=="serve":
            from .server import serve
            return serve(port=args.port)
        if args.command=="mcp":
            from .mcp_server import serve
            return serve(Path(args.source),args.http,args.port)
        if args.command=="doctor":
            from .sandbox import Sandbox
            from . import ollama
            report={"sandbox":Sandbox.doctor(),"gpu":ollama.gpu_usage(),"profiles":PROFILES,"inference_ram_limit_gib":16}
            try:report["models"]=sorted(ollama.ensure_available())
            except Exception as exc:report["inference_error"]=str(exc)
            print(json.dumps(report,indent=2));return
        if args.command=="list":print(json.dumps(request("/runs"),indent=2));return
        if args.command=="run":
            state=request("/runs",{"task":args.task,"source":args.source,"profile":args.profile,
                "acceptance":args.acceptance,"test_commands":[shlex.split(c) for c in args.check]})
            print("Task:",state["id"])
            if args.no_wait:return
            previous=""
            while state["status"] not in {"completed","needs_attention","cancelled"}:
                if state["message"]!=previous:print(state["message"],flush=True);previous=state["message"]
                time.sleep(1);state=request("/runs/"+state["id"])
            print(json.dumps({k:state.get(k) for k in ["id","status","message","changed_files","commit"]},indent=2))
            return 0 if state["status"]=="completed" else 2
        path="/runs/"+args.run_id
        if args.command=="diff":print(request(path+"/diff")["diff"]);return
        result=request(path+"/"+args.command,{}) if args.command in {"cancel","apply"} else request(path)
        print(json.dumps(result,indent=2))
    except (OSError,ValueError) as exc:
        print("Local Coder:",str(exc),file=sys.stderr);return 2

if __name__=="__main__":sys.exit(main())
