"""Private, sanitized coding preference pairs for later offline adapter training."""
from __future__ import annotations
import datetime
import collections
import json
import os
from pathlib import Path
import re

SAFE_ARGUMENTS={"path","cwd","start_line","line_count","offset","occurrence","timeout_seconds"}

def _config_path(root):return Path(root)/"training"/"preferences-config.json"

def preference_settings(root):
    path=_config_path(root)
    if not path.exists():return {"collection_enabled":True,"migrated_default":True}
    data=json.loads(path.read_text(encoding="utf-8"))
    return {"collection_enabled":bool(data.get("collection_enabled",True)),"migrated_default":False}

def set_preference_settings(root,enabled):
    if not isinstance(enabled,bool):raise ValueError("Collection setting must be true or false")
    path=_config_path(root);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps({"collection_enabled":enabled},indent=2));os.chmod(temporary,0o600);os.replace(temporary,path)
    return {"collection_enabled":enabled,"migrated_default":False}

def preference_records(root):
    path=Path(root)/"training"/"coding-preferences.jsonl";rows=[]
    if not path.exists():return rows
    for index,line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        try:record=json.loads(line);record["id"]=str(index);rows.append(record)
        except (TypeError,ValueError):continue
    return rows

def replace_preference_records(root,records):
    path=Path(root)/"training"/"coding-preferences.jsonl";path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_suffix('.tmp');temporary.write_text(''.join(json.dumps(record,ensure_ascii=False)+'\n' for record in records),encoding='utf-8');os.chmod(temporary,0o600);os.replace(temporary,path)

def delete_preference_record(root,record_id=None):
    records=preference_records(root)
    if record_id is None:
        replace_preference_records(root,[]);return {"deleted":len(records)}
    if not isinstance(record_id,str) or not record_id.isdigit():raise ValueError("Invalid preference record ID")
    index=int(record_id)
    if index<0 or index>=len(records):raise ValueError("Preference record not found")
    records.pop(index)
    for record in records:record.pop('id',None)
    replace_preference_records(root,records);return {"deleted":1}

def redact_preference_records(root):
    records=preference_records(root)
    patterns=[re.compile(r'(?i)(?:token|password|secret|api[_ -]?key)\s*[:=]\s*\S+'),re.compile(r'\b[A-Fa-f0-9]{32,}\b')]
    changes=0
    for record in records:
        record.pop('id',None)
        for key in ('task','acceptance'):
            value=str(record.get(key,''));clean=value
            for pattern in patterns:clean=pattern.sub('[REDACTED]',clean)
            if clean!=value:record[key]=clean;changes+=1
    replace_preference_records(root,records);return {"records":len(records),"fields_redacted":changes}

def safe_action(action):
    arguments=action.get("arguments",{}) if isinstance(action,dict) else {}
    safe={key:value for key,value in arguments.items() if key in SAFE_ARGUMENTS and isinstance(value,(str,int))}
    if isinstance(arguments.get("argv"),list) and arguments["argv"]:
        safe["command"]=str(arguments["argv"][0])[:120]
    return {"summary":str(action.get("summary",""))[:240],"tool":str(action.get("tool",""))[:40],"arguments":safe}

def failure_label(observation):
    text=str(observation.get("error",observation.get("summary",observation.get("stderr","check_failed")))).lower()
    for needle,label in [("stale","stale_hash"),("does not exist","missing_path"),("match exactly","ambiguous_patch"),
                         ("syntax","validation_failure"),("repeated","repeated_action"),("review","review_rejection"),
                         ("scope","scope_limit"),("timeout","timeout")]:
        if needle in text:return label
    return "tool_or_check_failure"

def append_pair(root,state,rejected,observation,chosen):
    if not preference_settings(root)["collection_enabled"]:return {"skipped":True,"reason":"Preference collection is disabled"}
    directory=Path(root)/"training";directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=directory/"coding-preferences.jsonl"
    record={"format":"lumina-coding-preference-v1",
            "created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "profile":state.get("profile"),"task":str(state.get("task",""))[:2000],
            "acceptance":str(state.get("acceptance",""))[:1000],
            "failure":failure_label(observation),"rejected":safe_action(rejected),"chosen":safe_action(chosen),
            "privacy":"Local sanitized actions; patch text, file contents, attachments and command arguments omitted."}
    with path.open("a",encoding="utf-8") as handle:handle.write(json.dumps(record,ensure_ascii=False)+"\n")
    os.chmod(path,0o600)
    return {"path":str(path),"failure":record["failure"]}

def preference_guidance(root,limit=100):
    """Return bounded, non-user-authored recovery patterns from local pairs."""
    if not preference_settings(root)["collection_enabled"]:return "",0
    path=Path(root)/"training"/"coding-preferences.jsonl"
    if not path.exists():return "",0
    patterns=collections.Counter()
    try:lines=path.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:return "",0
    for line in lines:
        try:record=json.loads(line)
        except (TypeError,ValueError):continue
        failure=str(record.get("failure",""))
        rejected=str(record.get("rejected",{}).get("tool",""))
        chosen=str(record.get("chosen",{}).get("tool",""))
        if failure and rejected and chosen and rejected!=chosen:
            patterns[(failure,rejected,chosen)]+=1
    if not patterns:return "",0
    rows=["Local successful recovery preferences (advisory; current evidence still wins):"]
    for (failure,rejected,chosen),count in patterns.most_common(6):
        rows.append(f"- After {failure} from {rejected}, prefer gathering evidence with {chosen} ({count} local example{'s' if count!=1 else ''}).")
    return "\n".join(rows),sum(patterns.values())
