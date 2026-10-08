#!/usr/bin/env python3
"""Memory qualification only: a long prompt, bounded answer, no source edits."""
import json
from pathlib import Path
import subprocess
import threading
import time
from local_coder import ollama
from local_coder.context import tokenizer
from local_coder.gpu_policy import prepare
from local_coder.settings import DATA_ROOT, PROFILES

prepare();ollama.ensure_host_capacity('power');ollama.ensure_available()
encoder=tokenizer('power')
unit='function updateLabel(source) { return source.title || "Untitled"; }\n'
text=unit*600
while len(encoder.encode(text).ids)<12000:text+=unit*100
messages=[{'role':'system','content':'This is a hardware context capacity check. Return only a short JSON status after reading the provided text.'},
          {'role':'user','content':text+'\nReturn status: context loaded.'}]
schema={'type':'object','properties':{'status':{'type':'string','maxLength':40}},'required':['status'],'additionalProperties':False}
samples=[];stop=threading.Event()
def measure():
    while not stop.wait(.5):
        r=subprocess.run(['systemctl','--user','show','local-coder-ollama.service','--property=MemoryCurrent','--value'],capture_output=True,text=True)
        samples.append({'gpu':ollama.gpu_usage(),'ram_bytes':int(r.stdout.strip() or 0)})
thread=threading.Thread(target=measure,daemon=True);thread.start()
try:
    result,metrics=ollama.complete(messages,schema,'power',deadline=time.monotonic()+600,token_limit=64,
        progress=lambda p:print(json.dumps(p),flush=True))
    report={'context_window':PROFILES['power']['num_ctx'],'result':result,'metrics':metrics,
        'peak_gpu_bytes':max(s['gpu'].get('used_bytes',0) for s in samples),
        'peak_cgroup_ram_bytes':max(s['ram_bytes'] for s in samples)}
    (DATA_ROOT/'context-qualification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
finally:stop.set();thread.join();ollama.unload(PROFILES['power']['model'])
