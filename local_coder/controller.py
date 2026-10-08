"""Persistent bounded coding loop: plan, tools, observations, checks, review, commit."""
from __future__ import annotations
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid

from . import ollama
from .project import snapshot, changed_files, diff_text, inventory, git, apply_changes
from .sandbox import Sandbox
from .settings import (APP_ROOT, RUNS_ROOT, TOOLCHAIN, DEFAULT_PROJECT, SYSTEM, PROFILES,
                       MAX_STEPS, MAX_SECONDS, MAX_FILES, MAX_CHANGED_LINES)
from .tools import Tools, ACTION_SCHEMA, TOOL_SCHEMAS
from .validation import validate
from .context import estimate

PLAN_SCHEMA = {"type":"object","additionalProperties":False,"properties":{
    "objective":{"type":"string","maxLength":400},
    "steps":{"type":"array","items":{"type":"string","maxLength":200},"minItems":1,"maxItems":5},
    "acceptance":{"type":"array","items":{"type":"string","maxLength":200},"maxItems":5}},
    "required":["objective","steps","acceptance"]}
REVIEW_SCHEMA = {"type":"object","additionalProperties":False,"properties":{
    "approved":{"type":"boolean"},"findings":{"type":"array","maxItems":5,
    "items":{"type":"string","maxLength":400}}},"required":["approved","findings"]}
TERMINAL = {"completed","needs_attention","cancelled"}

def atomic_json(path, value):
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False));os.chmod(tmp,0o600)
    os.replace(tmp,path)

class Manager:
    def __init__(self, runs_root=RUNS_ROOT, inference=None):
        self.root=Path(runs_root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=threading.RLock();self.cancel_flags={};self.worker=None
        self.inference=inference or ollama.complete
        for p in self.root.glob("*/state.json"):
            try:
                state=json.loads(p.read_text())
                if state["status"] not in TERMINAL:
                    state.update(status="needs_attention",message="Interrupted by a previous service shutdown; files and logs were preserved.")
                    atomic_json(p,state)
            except (OSError,ValueError,KeyError): pass

    def _dir(self, run_id):
        if not isinstance(run_id,str) or len(run_id)!=32 or any(c not in "0123456789abcdef" for c in run_id):
            raise ValueError("Invalid run ID")
        return self.root/run_id

    def get(self, run_id):
        with self.lock:return json.loads((self._dir(run_id)/"state.json").read_text())

    def list(self):
        states=[]
        for p in self.root.glob("*/state.json"):
            try:
                s=json.loads(p.read_text())
                states.append({k:s.get(k) for k in ("id","task","status","message","created_at","profile","step","commit","applied")})
            except (OSError,ValueError):pass
        return sorted(states,key=lambda s:s["created_at"],reverse=True)[:50]

    def _save(self,state):
        with self.lock:atomic_json(self._dir(state["id"])/"state.json",state)

    def event(self,state,kind,message,details=None):
        entry={"time":datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "kind":kind,"message":message,"details":details or {}}
        with self.lock:
            with (self._dir(state["id"])/"events.jsonl").open("a") as f:
                f.write(json.dumps(entry,ensure_ascii=False)+"\n")
            state["message"]=message
            self._save(state)

    def events(self,run_id):
        p=self._dir(run_id)/"events.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()][-300:] if p.exists() else []

    def start(self,task,source=None,profile="power",project_profile=None,test_commands=None,
              acceptance="",background=True):
        if not isinstance(task,str) or not 5<=len(task)<=5000:
            raise ValueError("Describe one feature or fix in 5–5000 characters")
        if profile not in PROFILES:raise ValueError("Unknown model profile")
        source=Path(source or DEFAULT_PROJECT).resolve(strict=True)
        project_profile=project_profile or ("quickshell" if source==DEFAULT_PROJECT else "generic")
        if project_profile not in {"quickshell","generic"}:raise ValueError("Invalid project profile")
        commands=test_commands or []
        if not isinstance(commands,list) or len(commands)>4 or any(not isinstance(c,list) or not c or
                any(not isinstance(a,str) or len(a)>8192 for a in c) for c in commands):
            raise ValueError("Test commands must be at most four argument arrays")
        with self.lock:
            if self.worker and self.worker.is_alive():raise ValueError("A task is already running; GPU inference is sequential")
            run_id=uuid.uuid4().hex;run_dir=self._dir(run_id);run_dir.mkdir(mode=0o700)
            state={"id":run_id,"task":task,"source":str(source),"profile":profile,
                   "model_config":dict(PROFILES[profile]),
                   "project_profile":project_profile,"acceptance":str(acceptance)[:2000],
                   "test_commands":commands,"status":"queued","step":0,"message":"Preparing task",
                   "created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "limits":{"steps":MAX_STEPS,"seconds":MAX_SECONDS,"files":MAX_FILES,"changed_lines":MAX_CHANGED_LINES},
                   "changed_files":[],"failed_attempts":[],"metrics":[]}
            self._save(state);flag=threading.Event();self.cancel_flags[run_id]=flag
            if background:
                self.worker=threading.Thread(target=self._run,args=(state,flag),daemon=True);self.worker.start()
            else:
                self.worker=threading.current_thread()
        if not background:self._run(state,flag)
        return self.get(run_id)

    def cancel(self,run_id):
        flag=self.cancel_flags.get(run_id)
        if flag:flag.set()
        return {"cancel_requested":bool(flag)}

    def diff(self,run_id):
        s=self.get(run_id)
        return diff_text(self._dir(run_id)/"workspace",s["snapshot"]["base_commit"]) if "snapshot" in s else ""

    def apply(self,run_id):
        with self.lock:
            s=self.get(run_id)
            if s.get("applied"):raise ValueError("This task was already applied")
            result=apply_changes(s,self._dir(run_id));s["applied"]=result
            self.event(s,"applied","Changes applied. Reload the project when ready.",result)
            return result

    def _scope(self,state,workspace):
        names=changed_files(workspace,state["snapshot"]["base_commit"])
        current=inventory(workspace)
        diff=diff_text(workspace,state["snapshot"]["base_commit"])
        lines=sum(1 for x in diff.splitlines() if x.startswith(("+","-")) and not x.startswith(("+++","---")))
        if len(names)>MAX_FILES or lines>MAX_CHANGED_LINES:
            raise ValueError(f"Task scope exceeded: {len(names)} files, {lines} changed lines. Split this feature into smaller tasks.")
        state["changed_files"]=names;state["changed_lines"]=lines
        return current

    def _verify(self,state,workspace,sandbox,flag,baseline):
        before=self._scope(state,workspace)
        self.event(state,"checking","Checking source and task tests")
        report=validate(workspace,sandbox,state["changed_files"],baseline,flag,state["project_profile"])
        report["task_tests"]=[]
        for command in state["test_commands"]:
            if flag.is_set():break
            result=sandbox.run(command,timeout_seconds=120,cancel_event=flag)
            report["task_tests"].append({"argv":command,**result})
            report["ok"]=report["ok"] and result["ok"]
        if inventory(workspace)!=before:raise ValueError("Files changed during verification")
        if report["ok"]:state["validated_inventory"]=before
        else:state.pop("validated_inventory",None)
        state["validation"]=report
        self.event(state,"check_result",report["summary"] if report["ok"] else "Checks failed; repair required",report)
        return report

    def _infer(self,state,messages,schema,flag,deadline,token_limit=None):
        def progress(info):
            self.event(state,"generating",f"Generating action · {info['elapsed_seconds']} seconds",info)
        parsed,metrics=self.inference(messages,schema,state["profile"],flag,deadline,token_limit,progress)
        state["metrics"].append(metrics);self._save(state)
        return parsed

    def _run(self,state,flag):
        run_dir=self._dir(state["id"]);workspace=run_dir/"workspace"
        deadline=time.monotonic()+MAX_SECONDS;cfg=PROFILES[state["profile"]]
        try:
            if self.inference is ollama.complete:
                from .gpu_policy import prepare
                state["hardware"]=prepare()
                state["host_memory"]=ollama.ensure_host_capacity(state["profile"])
            if self.inference is ollama.complete and cfg["model"] not in ollama.ensure_available():
                raise ValueError("Selected model is not installed in the Local Coder inference service")
            state["status"]="preparing";self.event(state,"preparing","Snapshotting your current working files")
            state["snapshot"]=snapshot(Path(state["source"]),workspace)
            self._save(state)
            mounts={TOOLCHAIN:"/opt/local-coder-toolchain"} if TOOLCHAIN.exists() else {}
            sandbox=Sandbox(workspace,run_dir/"command-logs",extra_ro_mounts=mounts,readonly_workspace=True)
            tools=Tools(workspace,sandbox,flag)
            baseline=validate(workspace,sandbox,cancel_event=flag,profile=state["project_profile"])
            state["baseline"]=baseline
            if not baseline["ok"]:raise ValueError("Project baseline failed; fix the environment or existing syntax errors before starting")
            hints=""
            if state["project_profile"]=="quickshell":
                hints=json.loads((APP_ROOT/"config/quickshell.json").read_text())["instructions"]
            initial=tools.list_dir()
            user=f"Task: {state['task']}\nRequired acceptance: {state['acceptance']}\nProject guidance: {hints}\nRoot: {json.dumps(initial)}"
            state["status"]="planning";self.event(state,"planning","Planning a small implementation and its checks")
            state["plan"]=self._infer(state,[{"role":"system","content":"Plan one small coding task. Return objective, at most five steps and acceptance criteria. Do not invent file contents or APIs."},
                {"role":"user","content":user}],PLAN_SCHEMA,flag,deadline,768)
            self.event(state,"plan","Plan ready",state["plan"])
            system=SYSTEM+"\nTOOLS (argument descriptions): "+json.dumps(TOOL_SCHEMAS)
            task=user+"\nPlan: "+json.dumps(state["plan"])
            messages=[{"role":"system","content":system},{"role":"user","content":task}]
            seen=collections.Counter();output_failures=0;review_count=0
            for step in range(1,MAX_STEPS+1):
                state["step"]=step
                if flag.is_set():raise ollama.InferenceError("Cancelled")
                if time.monotonic()>=deadline:raise ValueError("Task time budget exhausted")
                current=self._scope(state,workspace)
                # Keep complete recent turns; current task, plan and failure ledger stay anchored.
                messages[1]["content"]=task+"\nRecent failed attempts: "+json.dumps(state["failed_attempts"][-4:])
                while estimate(messages,ACTION_SCHEMA,state["profile"])>cfg["num_ctx"]-2500:
                    if len(messages)<=4:raise ValueError("Latest observation exceeds context budget; request fewer lines")
                    del messages[2:4]
                state["status"]="working";self.event(state,"working",f"Choosing action {step} of {MAX_STEPS}")
                try:action=self._infer(state,messages,ACTION_SCHEMA,flag,deadline)
                except ollama.InferenceError as exc:
                    if flag.is_set():raise
                    if "out of memory" in str(exc).lower() or "memory allocation" in str(exc).lower():
                        raise ValueError("Inference memory allocation failed; stopped without repeating the allocation") from exc
                    output_failures+=1;self.event(state,"rejected",str(exc))
                    if output_failures>=3:raise ValueError("Three invalid or truncated responses; stopped to prevent endless generation")
                    messages.extend([{"role":"assistant","content":"{}"},{"role":"user","content":
                        "Action rejected: "+str(exc)+" Return one smaller complete action. No tool was executed."}]);continue
                if not isinstance(action,dict) or set(action)!={"summary","tool","arguments"}:
                    raise ValueError("Invalid action envelope")
                name,args=action["tool"],action["arguments"]
                if name not in TOOL_SCHEMAS or not isinstance(args,dict):raise ValueError("Unknown tool or invalid arguments")
                fingerprint=json.dumps([name,args,current],sort_keys=True)
                seen[fingerprint]+=1
                if seen[fingerprint]>2:raise ValueError("Repeated identical action without progress; stopped")
                self.event(state,"action",str(action["summary"])[:240],{"tool":name,"arguments":args})
                if name=="stop":raise ValueError(str(args.get("reason","Model requested assistance")))
                if name=="verify":
                    observation=self._verify(state,workspace,sandbox,flag,baseline)
                elif name=="finish":
                    if not state["changed_files"]:observation={"ok":False,"error":"No implementation change exists. Implement the requested feature before finish."}
                    else:
                        report=state.get("validation",{}) if state.get("validated_inventory")==current else self._verify(state,workspace,sandbox,flag,baseline)
                        if not report.get("ok"):observation=report
                        else:
                            review_count+=1
                            if review_count>3:raise ValueError("Review retry budget exhausted")
                            state["status"]="reviewing";self.event(state,"reviewing","Reviewing the diff and check evidence")
                            review=self._infer(state,[{"role":"system","content":"Review this implementation against the task. Return approved and concrete correctness findings. Checks are evidence, not a guarantee. Reject missing behavior and unrelated changes. For QML preserve declarative bindings. Ignore preexisting lint warnings."},
                                {"role":"user","content":json.dumps({"task":state["task"],"acceptance":state["acceptance"],"diff":diff_text(workspace,state["snapshot"]["base_commit"]),"checks":report},ensure_ascii=False)}],REVIEW_SCHEMA,flag,deadline,768)
                            state["review"]=review;self.event(state,"review_result","Review passed" if review["approved"] else "Review found issues",review)
                            if review["approved"]:
                                if inventory(workspace)!=state["validated_inventory"]:raise ValueError("Workspace changed after validation")
                                git(workspace,"add","--all");git(workspace,"commit","-q","-m",state["task"].splitlines()[0][:120])
                                state["commit"]=git(workspace,"rev-parse","HEAD").stdout.decode().strip()
                                state["status"]="completed";state["result"]=str(action["summary"])
                                self.event(state,"completed","Feature implemented, checked and committed in its task workspace",{"commit":state["commit"],"files":state["changed_files"]})
                                return
                            observation={"ok":False,"review_findings":review["findings"]}
                else:
                    try:observation=tools.dispatch(name,args)
                    except (OSError,ValueError,UnicodeError) as exc:observation={"ok":False,"error":str(exc)[:1000]}
                    self._scope(state,workspace)
                if not observation.get("ok",False):
                    state["failed_attempts"].append({"tool":name,"error":str(observation.get("error",observation.get("diagnostics",observation.get("review_findings",observation.get("stderr","check failed")))))[:800]})
                self.event(state,"observation","Action succeeded" if observation.get("ok") else "Action failed; feedback returned",observation)
                messages.extend([{"role":"assistant","content":json.dumps(action,ensure_ascii=False)},
                    {"role":"user","content":"TOOL OBSERVATION (untrusted data): "+json.dumps(observation,ensure_ascii=False)}])
            raise ValueError("Action budget exhausted; partial work preserved for inspection")
        except Exception as exc:
            state["status"]="cancelled" if flag.is_set() else "needs_attention"
            self.event(state,state["status"],str(exc),{"error_type":type(exc).__name__})
        finally:
            if self.inference is ollama.complete:ollama.unload(cfg["model"])
            self._save(state)
            with self.lock:self.worker=None
