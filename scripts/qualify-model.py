#!/usr/bin/env python3
"""Run an immutable behavior benchmark in a disposable Quickshell snapshot."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from local_coder.cli import request
from local_coder.ollama import gpu_usage
from local_coder.settings import DATA_ROOT, APP_ROOT

parser=argparse.ArgumentParser();parser.add_argument('--profile',default='power');parser.add_argument('--run-id')
args=parser.parse_args()
reference=json.loads((APP_ROOT/'config/benchmark.json').read_text())
run=request('/runs/'+args.run_id) if args.run_id else request('/runs',{k:reference[k] for k in ['task','source','acceptance','test_commands']}|{'profile':args.profile})
samples=[];previous='';started=time.monotonic()
while True:
    s=request('/runs/'+run['id'])
    memory=subprocess.run(['systemctl','--user','show','local-coder-ollama.service','--property=MemoryCurrent','--value'],capture_output=True,text=True)
    samples.append({'seconds':round(time.monotonic()-started,2),'gpu':gpu_usage(),'ram_bytes':int(memory.stdout.strip() or 0)})
    if s['message']!=previous:print(s['message'],flush=True);previous=s['message']
    if s['status'] in {'completed','needs_attention','cancelled'}:break
    time.sleep(2)
report={'run_id':run['id'],'profile':args.profile,'status':s['status'],'seconds':round(time.monotonic()-started,2),
        'context_window':s.get('model_config',{}).get('num_ctx'),
        'peak_gpu_bytes':max(x['gpu'].get('used_bytes',0) for x in samples),
        'peak_cgroup_ram_bytes':max(x['ram_bytes'] for x in samples),'metrics':s['metrics'],'samples':samples}
(DATA_ROOT/f'qualification-{args.profile}.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=2))
raise SystemExit(0 if s['status']=='completed' else 2)
