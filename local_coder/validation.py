"""Run source checks inside the sandbox and preserve legacy lint baselines."""
from __future__ import annotations
import json
from pathlib import Path

SCANNER = r'''
import ast,collections,json,pathlib,subprocess,sys
root=pathlib.Path('/workspace')
selection=json.loads(sys.argv[1])
paths=sorted(root.rglob('*')) if selection is None else [root/p for p in selection]
diagnostics=[]; counts=collections.Counter(); warnings={}; failed=0
tools=pathlib.Path('/opt/local-coder-toolchain/usr/lib64/qt6/bin')
def error(p,check,message):
 global failed
 failed+=1
 if len(diagnostics)<12: diagnostics.append({'path':str(p.relative_to(root)),'check':check,'message':message[:550]})
for p in paths:
 if not p.is_file() or p.is_symlink() or any(x in p.relative_to(root).parts for x in ['.git','node_modules','.venv','__pycache__']): continue
 if p.stat().st_size>524288: continue
 name=str(p.relative_to(root)); suffix=p.suffix.lower()
 try:
  if suffix=='.qml':
   counts['qml']+=1
   parser=tools/'qmlformat'
   if not parser.exists(): error(p,'QML syntax','Matching Qt qmlformat tool is unavailable');continue
   r=subprocess.run([str(parser),'--ignore-settings',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=15)
   if r.returncode: error(p,'QML syntax',r.stderr.decode('utf-8','replace'));continue
   r=subprocess.run([str(tools/'qmllint'),'--ignore-settings','-I','/usr/lib64/qt6/qml','--json','-',str(p)],capture_output=True,timeout=20)
   try: lint=json.loads(r.stdout)
   except ValueError: error(p,'QML lint',r.stderr.decode('utf-8','replace') or 'Invalid lint output');continue
   subtotal=collections.Counter()
   for f in lint.get('files',[]):
    for w in f.get('warnings',[]):
     kind=w.get('type',''); ident=w.get('id','');message=w.get('message','')
     if kind in ['critical','error']: error(p,'QML lint',message)
     elif kind=='warning': subtotal[ident]+=1
   if subtotal: warnings[name]=dict(subtotal)
  elif suffix=='.py':
   counts['python']+=1
   try: compile(p.read_text(),name,'exec')
   except (SyntaxError,UnicodeError) as e: error(p,'Python syntax',str(e))
  elif suffix=='.js':
   counts['javascript']+=1
   text='\n'.join(x for x in p.read_text().splitlines() if not x.lstrip().startswith(('.pragma ','.import ')))
   r=subprocess.run(['node','--check','-'],input=text.encode(),capture_output=True,timeout=10)
   if r.returncode: error(p,'JavaScript syntax',r.stderr.decode('utf-8','replace'))
  elif suffix in ['.sh','.bash'] or (p.stat().st_mode&0o111 and p.open('rb').read(90).startswith(b'#!/') and b'sh' in p.open('rb').readline()):
   counts['shell']+=1
   r=subprocess.run(['bash','-n',str(p)],capture_output=True,timeout=10)
   if r.returncode: error(p,'Shell syntax',r.stderr.decode('utf-8','replace'))
 except (OSError,subprocess.TimeoutExpired) as e: error(p,'Check execution',str(e))
print(json.dumps({'ok':failed==0,'counts':dict(counts),'error_count':failed,'diagnostics':diagnostics,'warning_counts':warnings},separators=(',',':')))
'''

def validate(workspace: Path, sandbox, changed_paths: list[str] | None = None,
             baseline: dict | None = None, cancel_event=None,
             profile: str = "quickshell") -> dict:
    selected = None if changed_paths is None else [p for p in changed_paths if (workspace / p).exists()]
    result = sandbox.run(["python3", "-c", SCANNER, json.dumps(selected)],
                         timeout_seconds=120, cancel_event=cancel_event)
    if not result["ok"] or result["output_truncated"]:
        return {"ok": False, "summary": "Validation did not complete", "checks": [],
                "diagnostics": [{"message": result["stderr"] or "Check output exceeded its limit"}],
                "execution": result}
    try:
        report = json.loads(result["stdout"])
    except ValueError:
        return {"ok": False, "summary": "Invalid validator output", "checks": [],
                "diagnostics": [{"message": result["stdout"][:1000]}]}
    new_warnings = []
    if baseline:
        old = baseline.get("warning_counts", {})
        for path, counters in report["warning_counts"].items():
            for code, count in counters.items():
                if count > old.get(path, {}).get(code, 0) and code not in {"unqualified", "signal-handler-parameters"}:
                    new_warnings.append({"path": path, "code": code, "count": count-old.get(path,{}).get(code,0)})
    report["new_warnings"] = new_warnings[:20]
    report["checks"] = [{"check": kind+" syntax", "files": count} for kind,count in report["counts"].items()]
    report["summary"] = ("Source checks passed" if report["ok"] else "Source checks failed")
    report["summary"] += "; " + ", ".join(f"{count} {kind}" for kind,count in report["counts"].items())
    if new_warnings:
        report["summary"] += f"; {len(new_warnings)} new lint warning groups need review"
    return report
