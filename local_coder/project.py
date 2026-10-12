"""Snapshot current files, with independent Git metadata and safe deployment."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

from .settings import MAX_FILE_BYTES, MAX_SNAPSHOT_BYTES

BLOCKED_PARTS = {".git", ".ssh", ".gnupg", "node_modules", ".venv", "__pycache__"}

def allowed(relative: str) -> bool:
    p = Path(relative)
    return (not p.is_absolute() and ".." not in p.parts and
            not any(part in BLOCKED_PARTS for part in p.parts) and
            not any(part == ".env" or part.startswith(".env.") or
                    part.endswith((".pem", ".key")) for part in p.parts))

def digest(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        return "symlink:" + os.readlink(path)
    if not path.is_file():
        raise ValueError("Only regular files are supported: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_ATTR_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c",
        "core.fsmonitor=false", "-c", "user.name=Local Coder", "-c",
        "user.email=local-coder@localhost", "-C", str(repo), *args],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        check=check)

def snapshot(source: Path, workspace: Path) -> dict:
    source = source.resolve(strict=True)
    if not source.is_dir() or source == Path.home() or source == Path("/"):
        raise ValueError("Choose a specific source-code directory")
    workspace.mkdir(parents=True, exist_ok=False, mode=0o700)
    tracked = git(source, "ls-files", "--cached", "--others", "--exclude-standard", "-z", check=False)
    if tracked.returncode == 0:
        names = sorted(set(x.decode("utf-8") for x in tracked.stdout.split(b"\0") if x))
    else:
        names = sorted(p.relative_to(source).as_posix() for p in source.rglob("*")
                       if p.is_file() and allowed(p.relative_to(source).as_posix()))
    manifest, total, skipped = {}, 0, []
    for name in names:
        if not allowed(name):
            skipped.append(name); continue
        origin = source / name
        if not origin.exists():
            continue
        resolved = origin.resolve(strict=True)
        if not resolved.is_relative_to(source) or not resolved.is_file():
            skipped.append(name); continue
        size = resolved.stat().st_size
        if size > MAX_FILE_BYTES:
            skipped.append(name); continue
        total += size
        if total > MAX_SNAPSHOT_BYTES or len(manifest) >= 3000:
            raise ValueError("Project snapshot exceeds the configured size budget")
        destination = workspace / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Dereference only internal symlinks; deployment refuses symlink edits.
        shutil.copy2(resolved, destination)
        manifest[name] = digest(origin)
    if not manifest:
        raise ValueError("No source files were found")
    git(workspace, "init", "-q", "--initial-branch=local-coder/task")
    git(workspace, "add", "--all")
    git(workspace, "commit", "-q", "-m", "Snapshot current working files")
    return {"source": str(source), "manifest": manifest, "skipped": skipped,
            "base_commit": git(workspace, "rev-parse", "HEAD").stdout.decode().strip()}

def changed_files(workspace: Path, base_commit: str) -> list[str]:
    names = git(workspace, "diff", "--name-only", "-z", base_commit, "--").stdout
    untracked = git(workspace, "ls-files", "--others", "--exclude-standard", "-z").stdout
    return sorted(set(x.decode() for x in (names + untracked).split(b"\0") if x))

def diff_text(workspace: Path, base_commit: str) -> str:
    text = git(workspace, "diff", "--no-ext-diff", "--no-textconv", base_commit,
               "--").stdout.decode("utf-8", "replace")
    names = git(workspace, "ls-files", "--others", "--exclude-standard", "-z").stdout
    for name in (x.decode() for x in names.split(b"\0") if x):
        if allowed(name):
            text += git(workspace, "diff", "--no-index", "--no-ext-diff", "--no-textconv",
                        "--", "/dev/null", name, check=False).stdout.decode("utf-8", "replace")
    return text

def inventory(workspace: Path) -> dict:
    result = {}
    for p in workspace.rglob("*"):
        name = p.relative_to(workspace).as_posix()
        if ".git" in p.relative_to(workspace).parts:
            continue
        if p.is_symlink():
            raise ValueError("Agent-created symlinks are not accepted: " + name)
        if p.is_file():
            if not allowed(name) or p.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("Forbidden or oversized file: " + name)
            result[name] = digest(p)
    return result

def apply_changes(state: dict, run_dir: Path) -> dict:
    if state["status"] not in {"completed", "applying"} or not state.get("validated_inventory"):
        raise ValueError("Only a completed and validated run can be applied")
    workspace = run_dir / "workspace"
    if inventory(workspace) != state["validated_inventory"]:
        raise ValueError("The task workspace changed after validation")
    source = Path(state["source"]).resolve(strict=True)
    names = state["changed_files"]
    manifest = state["snapshot"]["manifest"]
    # Validate every source before writing any destination.
    for name in names:
        if not allowed(name):
            raise ValueError("Forbidden deployment path")
        target = source / name
        if target.is_symlink() or not target.parent.resolve().is_relative_to(source):
            raise ValueError("Deployment cannot follow symlinks: " + name)
        if digest(target) != manifest.get(name):
            raise ValueError("Source changed since the run started: " + name)
    backup = run_dir / "source-backup"
    backup.mkdir(mode=0o700, exist_ok=True)
    applied = []
    try:
        for name in names:
            target, edited = source / name, workspace / name
            saved = backup / name
            if target.exists():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not edited.exists():
                target.unlink()
            else:
                fd, temporary = tempfile.mkstemp(prefix=".local-coder-", dir=target.parent)
                os.close(fd)
                try:
                    shutil.copy2(edited, temporary)
                    os.replace(temporary, target)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            applied.append(name)
    except Exception:
        for name in reversed(applied):
            target, saved = source / name, backup / name
            if saved.exists():
                shutil.copy2(saved, target)
            else:
                target.unlink(missing_ok=True)
        raise
    return {"applied": names, "backup": str(backup), "reload_required": True}
