"""Small allowlisted file tools; model-selected commands always use Sandbox."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from .project import allowed
from .settings import MAX_FILE_BYTES

TOOL_SCHEMAS = {
    "list_dir": {"path": "relative directory, default .", "offset": "integer, default 0"},
    "search_code": {"query": "literal search string", "path": "relative directory, default ."},
    "read_file": {"path": "relative file", "start_line": "integer, default 1", "line_count": "integer, max 160"},
    "file_patch": {"path": "relative file", "expected_sha256": "hash from read_file", "old_text": "unique exact text", "new_text": "replacement text"},
    "create_file": {"path": "new relative file", "content": "UTF-8 source text"},
    "run_command": {"argv": "array of strings", "cwd": "relative directory, default .", "timeout_seconds": "integer, max 120"},
    "verify": {}, "finish": {}, "stop": {"reason": "why progress is blocked"},
}
ACTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "summary": {"type": "string", "maxLength": 240},
        "tool": {"type": "string", "enum": list(TOOL_SCHEMAS)},
        "arguments": {"type": "object", "properties": {
            "path": {"type": "string"}, "offset": {"type": "integer"},
            "query": {"type": "string"}, "start_line": {"type": "integer"},
            "line_count": {"type": "integer"}, "expected_sha256": {"type": "string"},
            "old_text": {"type": "string"}, "new_text": {"type": "string"},
            "content": {"type": "string"}, "argv": {"type": "array", "items": {"type": "string"}},
            "cwd": {"type": "string"}, "timeout_seconds": {"type": "integer"},
            "reason": {"type": "string"}}, "additionalProperties": False},
    }, "required": ["summary", "tool", "arguments"],
}

class Tools:
    def __init__(self, workspace, sandbox, cancel_event=None):
        self.root = Path(workspace).resolve(strict=True)
        self.sandbox = sandbox
        self.cancel_event = cancel_event
        # Preserve existing tests as independent evidence. New tests may be added.
        self.protected_tests = {p.relative_to(self.root).as_posix() for p in self.root.rglob("*")
            if p.is_file() and any(part.casefold() in {"test", "tests", "__tests__"}
                or part.casefold().startswith(("test_", "tst_", "test-", "tst-"))
                or part.casefold().endswith((".test.js", ".spec.js", ".test.ts", ".spec.ts",
                                           ".test.cjs", ".spec.cjs", ".test.mjs", ".spec.mjs"))
                for part in p.relative_to(self.root).parts)}

    def _path(self, relative: str, *, new=False):
        if not isinstance(relative, str) or not relative or len(relative) > 512 or not allowed(relative):
            raise ValueError("Use an allowed workspace-relative path")
        path = self.root / relative
        resolved = path.resolve(strict=not new)
        if not resolved.is_relative_to(self.root) or not allowed(resolved.relative_to(self.root).as_posix()):
            raise ValueError("Path escapes the editable workspace")
        # Reject symlinks at every component, including internal metadata links.
        current = self.root
        for part in Path(relative).parts:
            current /= part
            if current.is_symlink():
                raise ValueError("File tools cannot follow symlinks")
        return path

    def list_dir(self, path=".", offset=0):
        if type(offset) is not int or not 0 <= offset <= 3000:
            raise ValueError("Invalid directory offset")
        p = self._path(path)
        if not p.is_dir():
            raise ValueError("Expected a directory")
        names = sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir()
                       if allowed((x.relative_to(self.root)).as_posix()))
        return {"entries": names[offset:offset+60], "next_offset": offset+60 if len(names)>offset+60 else None}

    def read_file(self, path, start_line=1, line_count=120):
        if type(start_line) is not int or start_line < 1 or type(line_count) is not int or not 1 <= line_count <= 160:
            raise ValueError("Invalid line range")
        p = self._path(path)
        if not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Expected a regular source file under 512 KiB")
        data = p.read_bytes()
        if b"\0" in data:
            raise ValueError("Binary files are not exposed to the model")
        lines = data.decode("utf-8").splitlines(keepends=True)
        selected = "".join(lines[start_line-1:start_line-1+line_count])
        truncated = len(selected) > 14000
        return {"path": path, "sha256": hashlib.sha256(data).hexdigest(),
                "start_line": start_line, "total_lines": len(lines), "text": selected[:14000],
                "truncated": truncated or start_line-1+line_count < len(lines)}

    def search_code(self, query, path="."):
        if not isinstance(query, str) or not 1 <= len(query) <= 160:
            raise ValueError("Search for a short literal string")
        p = self._path(path)
        files = sorted(p.rglob("*")) if p.is_dir() else [p]
        matches = []
        for item in files:
            name = item.relative_to(self.root).as_posix()
            if not allowed(name) or item.is_symlink() or not item.is_file() or item.stat().st_size > MAX_FILE_BYTES:
                continue
            try:
                content = item.read_text(encoding="utf-8")
            except UnicodeError:
                continue
            for n, line in enumerate(content.splitlines(), 1):
                if query.casefold() in line.casefold():
                    matches.append({"path": name, "line": n, "text": line[:350]})
                    if len(matches) == 40:
                        return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": False}

    def _write(self, path, data: bytes, mode=0o644):
        if len(data) > MAX_FILE_BYTES or b"\0" in data:
            raise ValueError("Source file is oversized or binary")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".local-coder-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data); handle.flush(); os.fsync(handle.fileno())
            os.chmod(temp, mode)
            os.replace(temp, path)
        finally:
            Path(temp).unlink(missing_ok=True)
        return hashlib.sha256(data).hexdigest()

    def file_patch(self, path, expected_sha256, old_text, new_text):
        p = self._path(path)
        if p.relative_to(self.root).as_posix() in self.protected_tests:
            raise ValueError("Existing tests are protected. Repair the implementation or add a separate regression test.")
        if not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Expected a small regular source file")
        data = p.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if expected_sha256 != actual:
            raise ValueError("Stale or incorrect hash. Read this file again and copy its sha256 exactly.")
        if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
            raise ValueError("old_text must be nonempty and new_text must be text")
        if len(old_text) + len(new_text) > 18000 or new_text.count("\n") > 160:
            raise ValueError("Patch too large. Split the edit into smaller changes.")
        text = data.decode("utf-8")
        if text.count(old_text) != 1:
            raise ValueError("old_text must match exactly once. Read a more specific source range.")
        if old_text == new_text:
            raise ValueError("Patch makes no change")
        updated = text.replace(old_text, new_text, 1).encode("utf-8")
        sha = self._write(p, updated, stat.S_IMODE(p.stat().st_mode))
        return {"path": path, "sha256": sha, "changed": True}

    def create_file(self, path, content):
        p = self._path(path, new=True)
        if p.exists():
            raise ValueError("File exists. Use read_file and file_patch.")
        if not isinstance(content, str) or len(content) > 18000:
            raise ValueError("Create a small UTF-8 file")
        return {"path": path, "sha256": self._write(p, content.encode()), "created": True}

    def run_command(self, argv, cwd=".", timeout_seconds=60):
        return self.sandbox.run(argv, cwd, timeout_seconds, self.cancel_event)

    def dispatch(self, tool: str, arguments: dict):
        if tool not in TOOL_SCHEMAS or tool in {"verify", "finish", "stop"}:
            raise ValueError("Unsupported executable tool")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        try:
            result = getattr(self, tool)(**arguments)
        except TypeError as exc:
            raise ValueError("Invalid tool arguments: " + str(exc)) from exc
        if tool == "run_command":
            return result
        return {"ok": True, "result": result}
