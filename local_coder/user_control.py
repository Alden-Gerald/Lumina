"""User-controlled memory, knowledge, datasets, credentials, and backups."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import uuid

from .attachments import FileStore, is_image
from .lan_gateway import password_hash


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _atomic(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _identifier(value, label="ID"):
    if not isinstance(value, str) or len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"Invalid {label}")
    return value


def _tokens(text):
    stop = {"the", "and", "for", "with", "that", "this", "from", "your", "what", "how"}
    return {word for word in re.findall(r"[\w-]{3,}", str(text).lower()) if word not in stop}


class MemoryStore:
    def __init__(self, root):
        self.path = Path(root) / "memories.json"

    def _load(self):
        if not self.path.exists():
            return {"version": 1, "items": []}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("items"), list):
            raise ValueError("Unsupported memory library format")
        return data

    def list(self, project=None):
        items = self._load()["items"]
        if project is not None:
            items = [item for item in items if item.get("scope") == "global" or item.get("project") == project]
        return items

    def save(self, text, *, item_id=None, scope="global", project=None, source="user", enabled=True):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
            raise ValueError("Memory text must be 1–2000 characters")
        if scope not in {"global", "project"} or scope == "project" and (not isinstance(project, str) or not project.strip()):
            raise ValueError("Choose global scope or provide a project")
        if not isinstance(enabled, bool):
            raise ValueError("Memory enabled must be true or false")
        data = self._load(); now = _now()
        if item_id:
            _identifier(item_id, "memory ID")
            item = next((row for row in data["items"] if row["id"] == item_id), None)
            if not item:
                raise ValueError("Memory not found")
            item.update(text=text.strip(), scope=scope, project=project.strip() if scope == "project" else None,
                        source=str(source)[:120], enabled=enabled, updated_at=now)
        else:
            item = {"id": uuid.uuid4().hex, "text": text.strip(), "scope": scope,
                    "project": project.strip() if scope == "project" else None,
                    "source": str(source)[:120], "enabled": enabled, "created_at": now, "updated_at": now}
            data["items"].append(item)
        _atomic(self.path, data)
        return item

    def delete(self, item_id):
        _identifier(item_id, "memory ID"); data = self._load()
        before = len(data["items"]); data["items"] = [item for item in data["items"] if item["id"] != item_id]
        if len(data["items"]) == before:
            raise ValueError("Memory not found")
        _atomic(self.path, data)
        return {"deleted": item_id}

    def select(self, question, project=None, limit=6):
        terms = _tokens(question); ranked = []
        scoped=[item for item in self._load()["items"] if item.get("scope")=="global" or project is not None and item.get("project")==project]
        for item in scoped:
            if not item.get("enabled", True):
                continue
            score = len(terms & _tokens(item["text"]))
            if score or item.get("scope") == "global":
                ranked.append((score, item.get("updated_at", ""), item))
        return [item for _, _, item in sorted(ranked, key=lambda row: (row[0], row[1]), reverse=True)[:limit]]


class KnowledgeStore:
    def __init__(self, root, files: FileStore):
        self.path = Path(root) / "knowledge.json"; self.files = files

    def _load(self):
        if not self.path.exists():
            return {"version": 1, "items": []}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("items"), list):
            raise ValueError("Unsupported knowledge library format")
        return data

    def list(self, project=None):
        items = self._load()["items"]
        if project is not None:
            items = [item for item in items if item.get("scope") == "global" or item.get("project") == project]
        return items

    def add(self, attachment_id, *, scope="global", project=None, label=None, source="user import"):
        meta = self.files.load(attachment_id)
        if is_image(meta):
            raise ValueError("Knowledge imports must be readable documents")
        if scope not in {"global", "project"} or scope == "project" and not str(project or "").strip():
            raise ValueError("Choose global scope or provide a project")
        data = self._load()
        if any(item["attachment_id"] == attachment_id and item.get("project") == project for item in data["items"]):
            raise ValueError("This document is already in the selected knowledge scope")
        item = {"id": uuid.uuid4().hex, "attachment_id": attachment_id,
                "label": str(label or meta["name"])[:120], "scope": scope,
                "project": str(project).strip() if scope == "project" else None,
                "source": str(source)[:240], "created_at": _now(), "enabled": True,
                "bytes": meta["bytes"], "characters": meta.get("characters", 0)}
        data["items"].append(item); _atomic(self.path, data); return item

    def update(self, item_id, *, enabled=None, label=None):
        _identifier(item_id, "knowledge ID"); data = self._load()
        item = next((row for row in data["items"] if row["id"] == item_id), None)
        if not item: raise ValueError("Knowledge item not found")
        if enabled is not None:
            if not isinstance(enabled, bool): raise ValueError("Enabled must be true or false")
            item["enabled"] = enabled
        if label is not None:
            if not isinstance(label, str) or not label.strip(): raise ValueError("Knowledge label is required")
            item["label"] = label.strip()[:120]
        item["updated_at"] = _now(); _atomic(self.path, data); return item

    def delete(self, item_id):
        _identifier(item_id, "knowledge ID"); data = self._load()
        before = len(data["items"]); data["items"] = [item for item in data["items"] if item["id"] != item_id]
        if len(data["items"]) == before: raise ValueError("Knowledge item not found")
        _atomic(self.path, data); return {"deleted": item_id, "source_attachment_preserved": True}

    def select(self, question, project=None, limit=6):
        terms = _tokens(question); passages = []
        scoped=[item for item in self._load()["items"] if item.get("scope")=="global" or project is not None and item.get("project")==project]
        for number, item in enumerate(scoped, 1):
            if not item.get("enabled", True): continue
            try: sections = self.files.sections(item["attachment_id"])
            except (OSError, ValueError): continue
            for section in sections:
                for offset in range(0, len(section["text"]), 1000):
                    text = section["text"][offset:offset + 1200]
                    score = len(terms & _tokens(text))
                    passages.append({"score": score, "citation": f"[K{number}: {section['location']}]",
                        "knowledge_id": item["id"], "name": item["label"], "source": item["source"], "text": text})
        selected = sorted(passages, key=lambda row: row["score"], reverse=True)[:limit]
        return [{k: v for k, v in row.items() if k != "score"} for row in selected if row["score"] or not terms][:limit]


class DatasetStore:
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, dataset_id):
        return self.root / (_identifier(dataset_id, "dataset ID") + ".json")

    def list(self):
        rows = []
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8")); rows.append(data["metadata"])
            except (OSError, ValueError, KeyError): pass
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)

    def import_rows(self, name, rows, provenance="user import", evaluation_percent=20):
        if not isinstance(name, str) or not name.strip() or len(name) > 120: raise ValueError("Dataset name is required")
        if not isinstance(rows, list) or not 2 <= len(rows) <= 10000: raise ValueError("Dataset must contain 2–10,000 rows")
        if not isinstance(evaluation_percent, int) or not 10 <= evaluation_percent <= 50: raise ValueError("Evaluation split must be 10–50 percent")
        valid = []; rejected = []; seen = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict): rejected.append({"row": index + 1, "reason": "not an object"}); continue
            if {"prompt", "response"} <= row.keys():
                cleaned = {"type": "supervised", "prompt": str(row["prompt"]).strip(), "response": str(row["response"]).strip()}
            elif {"prompt", "chosen", "rejected"} <= row.keys():
                cleaned = {"type": "preference", "prompt": str(row["prompt"]).strip(), "chosen": str(row["chosen"]).strip(), "rejected": str(row["rejected"]).strip()}
            else: rejected.append({"row": index + 1, "reason": "expected prompt/response or prompt/chosen/rejected"}); continue
            if any(not value or len(value) > 20000 for key, value in cleaned.items() if key != "type"):
                rejected.append({"row": index + 1, "reason": "empty or oversized text"}); continue
            digest = hashlib.sha256(json.dumps(cleaned, sort_keys=True).encode()).hexdigest()
            if digest in seen: rejected.append({"row": index + 1, "reason": "duplicate"}); continue
            seen.add(digest); cleaned["sha256"] = digest; valid.append(cleaned)
        if len(valid) < 2: raise ValueError("Dataset has fewer than two valid unique rows")
        valid.sort(key=lambda row: row["sha256"])
        eval_count = max(1, round(len(valid) * evaluation_percent / 100)); evaluation = valid[:eval_count]; training = valid[eval_count:]
        if not training: raise ValueError("Evaluation split leaves no training rows")
        dataset_id = uuid.uuid4().hex
        metadata = {"id": dataset_id, "name": name.strip(), "created_at": _now(), "provenance": str(provenance)[:500],
            "rows": len(valid), "training_rows": len(training), "evaluation_rows": len(evaluation), "rejected_rows": len(rejected),
            "sha256": hashlib.sha256("".join(row["sha256"] for row in valid).encode()).hexdigest()}
        _atomic(self._path(dataset_id), {"version": 1, "metadata": metadata, "training": training, "evaluation": evaluation, "rejected": rejected[:200]})
        return {**metadata, "rejected": rejected[:20]}

    def get(self, dataset_id):
        return json.loads(self._path(dataset_id).read_text(encoding="utf-8"))

    def delete(self, dataset_id):
        path = self._path(dataset_id)
        if not path.exists(): raise ValueError("Dataset not found")
        path.unlink(); return {"deleted": dataset_id}

    @staticmethod
    def training_capability():
        executables = [name for name in ("llamafactory-cli", "mlx_lm.lora", "axolotl") if shutil.which(name)]
        if not executables:
            return {"available": False, "reason": "No supported local adapter trainer is installed. Dataset validation and evaluation remain available; importing data does not train a model."}
        return {"available": False, "reason": "A trainer was detected but Lumina has no validated, rollback-safe adapter pipeline for it yet.", "detected": executables}


def change_credentials(root, current_password, username, new_password, invalidate_sessions=True):
    path = Path(root) / "lan" / "login.json"
    if not path.exists(): raise ValueError("Home-network sign in is not configured")
    if not isinstance(current_password, str) or not isinstance(new_password, str): raise ValueError("Passwords are required")
    if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
        raise ValueError("Username must be 3–40 letters, numbers, dots, dashes, or underscores")
    if len(new_password) < 12 or len(new_password) > 256: raise ValueError("New password must be 12–256 characters")
    saved = json.loads(path.read_text(encoding="utf-8"))
    actual = password_hash(current_password, bytes.fromhex(saved["salt"]))
    if not secrets.compare_digest(actual, saved["hash"]): raise ValueError("Current password is incorrect")
    salt = secrets.token_bytes(16); version = int(saved.get("version", 1)) + (1 if invalidate_sessions else 0)
    payload = {"username": username, "salt": salt.hex(), "hash": password_hash(new_password, salt),
               "version": version, "updated_at": _now()}
    _atomic(path, payload)
    return {"username": username, "sessions_invalidated": bool(invalidate_sessions), "updated_at": payload["updated_at"]}


class BackupStore:
    """Versioned metadata backup. Credentials, model artifacts and attachment bytes are excluded."""
    def __init__(self, data_root): self.root = Path(data_root)

    def export(self):
        payload = {"format": "lumina-user-backup-v1", "created_at": _now(), "memories": [], "knowledge": [], "chats": [], "preferences": []}
        for key, path in [("memories", self.root / "user" / "memories.json"), ("knowledge", self.root / "user" / "knowledge.json")]:
            if path.exists(): payload[key] = json.loads(path.read_text(encoding="utf-8")).get("items", [])
        for path in (self.root / "chats").glob("*/state.json"):
            try: payload["chats"].append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError): pass
        preference = self.root / "training" / "coding-preferences.jsonl"
        if preference.exists():
            for line in preference.read_text(encoding="utf-8").splitlines():
                try: payload["preferences"].append(json.loads(line))
                except ValueError: pass
        return payload

    def restore(self, payload):
        if not isinstance(payload, dict) or payload.get("format") != "lumina-user-backup-v1": raise ValueError("Unsupported backup format")
        backup = self.root / "backups" / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-pre-restore")
        backup.mkdir(parents=True, mode=0o700)
        for source in [self.root / "user" / "memories.json", self.root / "user" / "knowledge.json", self.root / "training" / "coding-preferences.jsonl"]:
            if source.exists(): shutil.copy2(source, backup / source.name)
        for key, filename in [("memories", "memories.json"), ("knowledge", "knowledge.json")]:
            items = payload.get(key, [])
            if not isinstance(items, list): raise ValueError("Backup contains invalid " + key)
            _atomic(self.root / "user" / filename, {"version": 1, "items": items})
        preferences=payload.get("preferences",[])
        if not isinstance(preferences,list):raise ValueError("Backup contains invalid preferences")
        preference_path=self.root/"training"/"coding-preferences.jsonl";preference_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        preference_path.write_text(''.join(json.dumps(record,ensure_ascii=False)+'\n' for record in preferences if isinstance(record,dict)),encoding='utf-8');os.chmod(preference_path,0o600)
        restored = 0
        for state in payload.get("chats", []):
            if not isinstance(state, dict): continue
            chat_id = _identifier(state.get("id"), "conversation ID")
            path = self.root / "chats" / chat_id / "state.json"
            if path.exists(): continue
            _atomic(path, state); restored += 1
        return {"restored_chats": restored, "safety_backup": str(backup)}
