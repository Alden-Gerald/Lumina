"""Select available Vulkan devices at task boundaries; respect VM ownership."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .settings import DATA_ROOT

POLICY=DATA_ROOT/"gpu-policy.json"
HELPER_POLICY=DATA_ROOT/"helper-gpu-policy.json"
RESERVED=DATA_ROOT/"vm-gpu-reserved"

def inspect(sys_root=Path("/sys/bus/pci/devices"), vulkan_text=None):
    devices=[]
    for p in sys_root.glob("*"):
        try:
            vendor=p.joinpath("vendor").read_text().strip()
            klass=p.joinpath("class").read_text().strip()
            if not klass.startswith("0x03") or vendor not in {"0x1002","0x10de"}:continue
            driver=p.joinpath("driver").resolve().name if p.joinpath("driver").exists() else "unbound"
            devices.append({"pci":p.name,"vendor":vendor,"device":p.joinpath("device").read_text().strip(),"driver":driver})
        except OSError:continue
    if vulkan_text is None:
        try:
            r=subprocess.run(["vulkaninfo","--summary"],capture_output=True,text=True,timeout=8,
                env={"PATH":"/usr/bin:/bin","HOME":str(Path.home()),"LANG":"C"})
            vulkan_text=r.stdout
        except (OSError,subprocess.TimeoutExpired):vulkan_text=""
    visible=[]
    for match in re.finditer(r"GPU(\d+):\s*(.*?)(?=\nGPU\d+:|\Z)",vulkan_text,re.S):
        block=match.group(2)
        if "PHYSICAL_DEVICE_TYPE_DISCRETE_GPU" not in block:continue
        name=re.search(r"deviceName\s*=\s*(.+)",block)
        vendor=re.search(r"vendorID\s*=\s*(0x[0-9a-fA-F]+)",block)
        if name and vendor:visible.append({"index":int(match.group(1)),"name":name.group(1).strip(),"vendor":vendor.group(1).lower()})
    amd=[d for d in visible if d["vendor"]=="0x1002" and "6600" in d["name"]]
    nvidia=[d for d in visible if d["vendor"]=="0x10de" and ("1050" in d["name"] or "GP107" in d["name"])]
    owned=any(d["vendor"]=="0x10de" and d["driver"]=="vfio-pci" for d in devices)
    dual=bool(amd and nvidia and not owned and not RESERVED.exists())
    selected=amd+nvidia if dual else amd
    status={"mode":"dual-vulkan" if dual else "rx6600-ram","pci_devices":devices,
            "vulkan_devices":visible,"selected_indices":[d["index"] for d in selected],
            "nvidia_reserved":RESERVED.exists(),"nvidia_vfio":owned,
            "dual_available":dual,"dual_measured":False,
            "explanation":"GTX 1050 Ti belongs to VFIO/VM" if owned else
                "Both cards are host-visible through Vulkan; dual mode needs a live performance qualification" if dual else
                "RX 6600 plus CPU/RAM offload"}
    status["signature"]=json.dumps([status["mode"],status["selected_indices"],[(d["pci"],d["driver"]) for d in devices]],sort_keys=True)
    return status

def current():
    try:return json.loads(POLICY.read_text())
    except (OSError,ValueError):return inspect()

def helper_devices(status=None):
    status=status or inspect()
    if status['nvidia_reserved'] or status['nvidia_vfio']:return []
    return [d['index'] for d in status['vulkan_devices'] if d['vendor']=='0x10de'
            and ('1050' in d['name'] or 'GP107' in d['name'])]

def builder_policy(status=None):
    status=dict(status or inspect())
    status['selected_indices']=[d['index'] for d in status['vulkan_devices']
                                if d['vendor']=='0x1002' and '6600' in d['name']]
    status['helper_indices']=helper_devices(status)
    status['mode']='rx6600-helper' if status['helper_indices'] else 'rx6600-ram'
    # NVIDIA ownership changes must never restart an active RX builder.
    status['signature']=json.dumps(['rx-builder',status['selected_indices']])
    status['explanation']='RX 6600 builder with CPU offload; separate optional GTX helper'
    return status

def launch(helper=False):
    status=inspect() if helper else builder_policy()
    indices=helper_devices(status) if helper else status['selected_indices']
    if not indices:raise RuntimeError('Assigned GPU unavailable; refusing CPU fallback')
    DATA_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=HELPER_POLICY if helper else POLICY
    status['selected_indices']=indices
    path.write_text(json.dumps(status,indent=2));path.chmod(0o600)
    env=dict(os.environ)
    # Use a common Vulkan backend for mixed vendors; no CUDA/ROCm pooling claim.
    env["CUDA_VISIBLE_DEVICES"]="-1";env["ROCR_VISIBLE_DEVICES"]="-1"
    env["GGML_VK_VISIBLE_DEVICES"]=",".join(map(str,indices))
    os.execve("/usr/local/bin/ollama",["ollama","serve"],env)

def prepare():
    actual=builder_policy();prior=current()
    running=subprocess.run(["systemctl","--user","is-active","--quiet","local-coder-ollama.service"],capture_output=True).returncode==0
    if not running or actual["signature"]!=prior.get("signature"):
        subprocess.run(["systemctl","--user","restart","local-coder-ollama.service"],check=True,timeout=15)
        from .ollama import api
        for _ in range(30):
            try:api("/api/version",timeout=2);break
            except OSError:time.sleep(.2)
        else:raise RuntimeError("Inference service did not become ready after GPU discovery")
    return current()

def prepare_helper():
    status=inspect();indices=helper_devices(status)
    if not indices:return {'available':False,'reason':'GTX reserved or unavailable'}
    try:prior=json.loads(HELPER_POLICY.read_text())
    except (OSError,ValueError):prior={}
    unit='local-coder-helper.service'
    running=subprocess.run(['systemctl','--user','is-active','--quiet',unit],capture_output=True).returncode==0
    if not running or prior.get('selected_indices')!=indices:
        subprocess.run(['systemctl','--user','restart',unit],check=True,timeout=15)
    from .ollama import api
    from .settings import HELPER_URL,PROFILES
    for _ in range(30):
        if RESERVED.exists():return {'available':False,'reason':'GTX reserved for VM'}
        try:
            names={m['name'] for m in api('/api/tags',base=HELPER_URL,timeout=2)['models']}
            if PROFILES['_helper']['model'] not in names:return {'available':False,'reason':'2B helper model is not installed'}
            return {'available':True,'indices':indices,'model':PROFILES['_helper']['model']}
        except OSError:time.sleep(.2)
    return {'available':False,'reason':'GTX worker did not become ready'}

def reserve():
    DATA_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700);RESERVED.touch(mode=0o600)
    status=current()
    subprocess.run(["systemctl","--user","stop","local-coder-helper.service"],check=True,timeout=30)
    if status.get("mode")=="dual-vulkan":
        # Stop only our private service before a VM takes the card. No PCI rebinding.
        subprocess.run(["systemctl","--user","stop","local-coder-ollama.service"],check=True,timeout=30)
    return {"reserved":True,"inference_stopped":status.get("mode")=="dual-vulkan",
            "message":"NVIDIA card reserved for VM; subsequent tasks use RX 6600 and RAM"}

def release():
    RESERVED.unlink(missing_ok=True)
    return {"reserved":False,"message":"Host-visible GPUs will be rediscovered before the next task"}

if __name__=="__main__":
    if sys.argv[1:]==["launch"]:launch()
    elif sys.argv[1:]==["launch-helper"]:launch(helper=True)
    else:print(json.dumps(inspect(),indent=2))
