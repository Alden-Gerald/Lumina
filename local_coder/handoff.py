"""Compact loopback client for handing a coding task to Local Coder."""
from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from .settings import DATA_ROOT


DEFAULT_SERVICE_URL = "http://127.0.0.1:8787"
RUN_ID = re.compile(r"^[0-9a-f]{32}$")
ACTIVE = {"queued", "preparing", "reading_images", "reading_files", "planning", "working", "optimizing", "reviewing", "applying"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_IMAGE_BYTES = 4 * 1024 * 1024


def _run_id(value: str) -> str:
    if not isinstance(value, str) or not RUN_ID.fullmatch(value):
        raise ValueError("Invalid Local Coder task ID")
    return value


def attachment_path(value: str) -> Path:
    """Allow only Codex clipboard images from the OS temporary directory."""
    if not isinstance(value, str):
        raise ValueError("Attachment paths must be strings")
    try:
        path = Path(value).resolve(strict=True)
    except OSError as exc:
        raise ValueError("A Codex image attachment is no longer available; attach it again and retry") from exc
    if path.parent != Path("/tmp") or not path.name.startswith("codex-clipboard-") or path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError("Only Codex clipboard images in /tmp may be forwarded automatically")
    if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Codex image attachments must be files no larger than 4MB")
    return path


def compact_status(state: dict) -> dict:
    """Return only the evidence Codex needs, not the local model transcript."""
    status = state.get("status", "unknown")
    result = {
        "run_id": state.get("id"),
        "status": status,
        "message": str(state.get("message", ""))[:500],
        "profile": state.get("profile"),
        "step": state.get("step", 0),
        "changed_files": list(state.get("changed_files") or [])[:20],
        "origin": state.get("origin"),
        "dashboard": DEFAULT_SERVICE_URL + ("/#" + str(state.get("id")) if state.get("id") else ""),
    }
    validation = state.get("validation")
    if isinstance(validation, dict):
        result["checks"] = {
            "ok": bool(validation.get("ok")),
            "summary": str(validation.get("summary", ""))[:500],
        }
    review = state.get("review")
    if isinstance(review, dict):
        result["review"] = {
            "approved": bool(review.get("approved")),
            "findings": [str(item)[:400] for item in (review.get("findings") or [])[:5]],
        }
    if state.get("result"):
        result["result"] = str(state["result"])[:500]
    if state.get("commit"):
        result["workspace_commit"] = str(state["commit"])
    if status in ACTIVE:
        result["next_step"] = "Local AI is working. End the Codex turn; check status only when the user asks."
    elif status == "completed":
        result["next_step"] = "Local AI finished. The user can inspect and apply the verified task from the Local Coder dashboard."
    elif status == "needs_attention":
        result["next_step"] = "Local AI stopped and needs help. Inspect the bounded diff before deciding whether Codex should continue."
    elif status == "cancelled":
        result["next_step"] = "The local task was cancelled."
    return result


def compact_diff(payload: dict, max_characters: int = 12000) -> dict:
    diff = str(payload.get("diff", ""))
    truncated = len(diff) > max_characters
    return {
        "diff": diff[:max_characters],
        "truncated": truncated,
        "characters": len(diff),
        "note": "Use the Local Coder dashboard for the complete diff." if truncated else "Complete diff returned.",
    }


class HandoffClient:
    """Talk to the already-running dashboard so all inference shares one lock."""

    def __init__(self, base_url: str = DEFAULT_SERVICE_URL, token_path: Path | None = None):
        if base_url.rstrip("/") not in {"http://127.0.0.1:8787", "http://localhost:8787"}:
            raise ValueError("The handoff service URL must be the loopback Local Coder dashboard")
        self.base_url = base_url.rstrip("/")
        self.token_path = Path(token_path or DATA_ROOT / "server-token")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _token(self) -> str:
        try:
            token = self.token_path.read_text().strip()
        except OSError as exc:
            raise ValueError("Local Coder is not running. Start the local-coder service, then retry the handoff.") from exc
        if not token:
            raise ValueError("Local Coder session token is empty; restart the local-coder service")
        return token

    def _open(self, request: urllib.request.Request) -> dict:
        try:
            with self.opener.open(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("error", str(exc))
            except (ValueError, UnicodeDecodeError):
                detail = str(exc)
            raise ValueError(f"Local Coder rejected the handoff: {detail}") from None
        except (OSError, urllib.error.URLError) as exc:
            raise ValueError("Local Coder is unavailable on 127.0.0.1:8787. Start the service and retry.") from exc

    def _request(self, path: str, body: dict | None = None) -> dict:
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers.update({"Content-Type": "application/json", "X-Local-Coder-Token": self._token()})
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers)
        return self._open(request)

    def upload_attachment(self, value: str) -> dict:
        path = attachment_path(value)
        request = urllib.request.Request(self.base_url + "/api/attachments", data=path.read_bytes(), headers={
            "Content-Type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "X-Local-Coder-Token": self._token(),
            "X-Upload-Name": urllib.parse.quote(path.name, safe=""),
        })
        return self._open(request)

    def _profile(self, requested: str) -> tuple[str, str | None]:
        info = self._request("/api/info")
        profiles = info.get("profiles") or {}
        if profiles.get(requested, {}).get("installed"):
            return requested, None
        for fallback in ("quality", "power", "balanced"):
            if profiles.get(fallback, {}).get("installed"):
                return fallback, f"Requested profile {requested!r} was unavailable; used installed profile {fallback!r}."
        raise ValueError("No installed Local Coder model is available")

    def start(self, task: str, source: Path, profile: str = "quality", acceptance: str = "",
              test_commands: list[list[str]] | None = None, team: bool = True,
              attachment_paths: list[str] | None = None, auto_apply: bool = True) -> dict:
        selected_profile, notice = self._profile(profile)
        attachments = [self.upload_attachment(path)["id"] for path in (attachment_paths or [])]
        state = self._request("/api/runs", {
            "task": task,
            "source": str(source),
            "profile": selected_profile,
            "acceptance": acceptance,
            "test_commands": test_commands or [],
            "team": team,
            "attachments": attachments,
            "origin": "codex",
            "auto_apply": auto_apply,
            "desktop_followup": auto_apply,
        })
        result = compact_status(state)
        result["source"] = str(source)
        result["attachments_forwarded"] = len(attachments)
        if notice:
            result["profile_notice"] = notice
        return result

    def status(self, run_id: str) -> dict:
        return compact_status(self._request("/api/runs/" + _run_id(run_id)))

    def diff(self, run_id: str, max_characters: int = 12000) -> dict:
        return compact_diff(self._request("/api/runs/" + _run_id(run_id) + "/diff"), max_characters)

    def cancel(self, run_id: str) -> dict:
        return self._request("/api/runs/" + _run_id(run_id) + "/cancel", {})
