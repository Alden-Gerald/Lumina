"""Bounded streaming inference, with offload and context profiles fixed by code."""
from __future__ import annotations
import json
import asyncio
import socket
import time
import urllib.error
import urllib.request

from .settings import OLLAMA_URL, PROFILES

HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

class InferenceError(RuntimeError):
    pass

async def _stream_chat(payload,cancel_event,deadline,progress,allow_thinking=False):
    import httpx
    pieces=[];final=None;started=time.monotonic();last_progress=0;thinking_characters=0;last_signature=None
    async def reader():
        nonlocal final,thinking_characters
        async with httpx.AsyncClient(trust_env=False,timeout=httpx.Timeout(900,connect=5)) as client:
            async with client.stream('POST',OLLAMA_URL+'/api/chat',json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:continue
                    if len(line.encode())>65536:raise InferenceError('Oversized inference chunk')
                    chunk=json.loads(line)
                    if chunk.get('error'):raise InferenceError(chunk['error'])
                    thinking=chunk.get('message',{}).get('thinking','')
                    thinking_characters+=len(thinking)
                    if thinking_characters>60000:raise InferenceError('Reasoning budget exhausted')
                    if thinking and not allow_thinking:
                        raise InferenceError('Unexpected thinking output; bounded action mode is required')
                    pieces.append(chunk.get('message',{}).get('content',''))
                    if sum(map(len,pieces))>24000:raise InferenceError('Action output is oversized')
                    if chunk.get('done'):final=chunk;return
    task=asyncio.create_task(reader())
    try:
        while True:
            if cancel_event and cancel_event.is_set():raise InferenceError('Cancelled')
            now=time.monotonic()
            if (deadline and now>=deadline) or now-started>=900:
                raise InferenceError('Task time budget exhausted')
            signature=(sum(map(len,pieces)),bool(thinking_characters))
            interval=.25 if allow_thinking and signature!=last_signature else 5
            if progress and now-last_progress>=interval:
                details={'generated_characters':sum(map(len,pieces)),'elapsed_seconds':round(now-started)}
                if allow_thinking:details.update(answer=''.join(pieces),thinking_characters=thinking_characters)
                progress(details)
                last_progress=now;last_signature=signature
            done,_=await asyncio.wait({task},timeout=.25)
            if done:
                await task
                return pieces,final
    except (httpx.HTTPError,ValueError) as exc:
        raise InferenceError('Local inference failed: '+str(exc)) from exc
    finally:
        if not task.done():
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass

def api(path: str, body: dict | None = None, timeout=15, base=OLLAMA_URL):
    req = urllib.request.Request(base+path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with HTTP.open(req, timeout=timeout) as response:
        return json.load(response)

def gpu_usage() -> dict:
    from pathlib import Path
    for p in Path("/sys/class/drm").glob("card[0-9]*/device/mem_info_vram_total"):
        try:
            total = int(p.read_text()); used = int(p.with_name("mem_info_vram_used").read_text())
            if total > 1024**3:
                return {"total_bytes": total, "used_bytes": used}
        except (OSError, ValueError):
            continue
    return {}

def ensure_available():
    # Other local applications may use the original service; don't compete with them.
    try:
        external = api("/api/ps", base="http://127.0.0.1:11434", timeout=3)
        if external.get("models"):
            raise InferenceError("A model is loaded in your original Ollama service. Unload it before using Local Coder.")
    except (urllib.error.URLError, TimeoutError):
        pass
    models = api("/api/tags").get("models", [])
    return {m["name"] for m in models}

def ensure_host_capacity(profile):
    from pathlib import Path
    fields=dict(line.split(":",1) for line in Path("/proc/meminfo").read_text().splitlines())
    available=int(fields["MemAvailable"].split()[0])*1024
    required=(16 if profile=="power" else 12 if profile=='_chat' else 8)*1024**3
    if available<required:
        raise InferenceError("Too little available host RAM for this profile. Close memory-heavy apps or use the 14B profile while the VM is running.")
    return {"available_bytes":available,"minimum_available_bytes":required}

def unload(model):
    try:
        api("/api/generate", {"model": model, "keep_alive": 0}, timeout=15)
    except (OSError, urllib.error.URLError):
        pass

def complete(messages, schema, profile="quality", cancel_event=None, deadline=None,
             token_limit=None, progress=None):
    cfg = PROFILES[profile]
    from .context import estimate
    estimated=estimate(messages,schema,profile)
    if estimated > cfg["num_ctx"]-2500:
        raise InferenceError("Prompt exceeds the safe context budget")
    options = {"num_ctx": cfg["num_ctx"], "num_gpu": cfg["num_gpu"],
               "num_predict": token_limit or cfg["num_predict"], "num_batch": 128,
               "num_thread": 8, "temperature": 0.15, "presence_penalty": 0,
               "repeat_penalty": 1.08}
    from .gpu_policy import current
    if current().get("mode")=="dual-vulkan":
        options["num_gpu"]=cfg["dual_num_gpu"]
    payload = {"model":cfg["model"],"messages":messages,"format":schema,
               "stream":True,"think":False,"keep_alive":"30s","options":options}
    started=time.monotonic()
    pieces,final=asyncio.run(_stream_chat(payload,cancel_event,deadline,progress))
    if not final: raise InferenceError("Inference ended without a complete response")
    if final.get("done_reason")=="length":
        raise InferenceError("Output limit reached. Nothing was executed; use a smaller action.")
    text="".join(pieces)
    # Reject degenerate repetitions before any tool can execute.
    if len(text)>1200 and any(text.count(text[i:i+120])>5 for i in range(0,len(text)-120,120)):
        raise InferenceError("Repeated output rejected. Nothing was executed.")
    try: parsed=json.loads(text)
    except ValueError as exc: raise InferenceError("Invalid action JSON; nothing was executed") from exc
    return parsed, {"model":cfg["model"],"eval_count":final.get("eval_count",0),
                    "prompt_eval_count":final.get("prompt_eval_count",0),"estimated_input_tokens":estimated,
                    "seconds":round(time.monotonic()-started,2),"gpu":gpu_usage(),"options":options}

def chat(messages, deep, cancel_event=None, deadline=None, progress=None,profile='_chat'):
    """Text chat has no file/command tools; thinking and output share a fixed token cap."""
    cfg=PROFILES[profile]
    from .context import estimate
    estimated=estimate(messages,None,profile)
    if estimated>cfg['num_ctx']-5000:raise InferenceError('Conversation exceeds the safe context budget')
    from .gpu_policy import current
    options={'num_ctx':cfg['num_ctx'],'num_gpu':cfg['dual_num_gpu'] if current().get('mode')=='dual-vulkan' else cfg['num_gpu'],
             'num_predict':4096 if deep else 2048,'num_batch':128,'num_thread':8,'temperature':.6,'repeat_penalty':1.08}
    payload={'model':cfg['model'],'messages':messages,'think':bool(deep),'stream':True,'keep_alive':'30s','options':options}
    started=time.monotonic()
    pieces,final=asyncio.run(_stream_chat(payload,cancel_event,deadline,progress,allow_thinking=True))
    if not final:raise InferenceError('Local model ended without a complete response')
    answer=''.join(pieces).strip()
    return answer,{'model':cfg['model'],'seconds':round(time.monotonic()-started,2),'eval_count':final.get('eval_count',0),
        'prompt_eval_count':final.get('prompt_eval_count',0),'estimated_input_tokens':estimated,
        'truncated':final.get('done_reason')=='length','gpu':gpu_usage(),'options':options}
