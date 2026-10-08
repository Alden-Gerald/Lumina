"""Linux command isolation for an agent-owned disposable checkout.

Only the checkout is writable on the host. Linux namespaces isolate networking,
processes, devices and IPC; a user systemd scope bounds aggregate resources.
This shares the host kernel and is not a virtual machine or a disk quota.
"""
from __future__ import annotations

import os
from pathlib import Path
import selectors
import signal
import subprocess
import threading
import time
import uuid


_PROBE_LOCK = threading.Lock()
_PROBE: dict | None = None
_LOG_BYTES = 1024 * 1024  # Per stream, while always continuing to drain pipes.
_VIEW_BYTES = 2980  # Head plus tail + marker stays below 6000 characters/stream.


def _launcher_env() -> dict[str, str]:
    """The launcher needs the user's bus; the command receives a cleared env."""
    keep = ("HOME", "USER", "LOGNAME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
    result = {key: os.environ[key] for key in keep if key in os.environ}
    # MCP stdio launchers often omit session variables. Recover our own bus only.
    runtime = Path(f"/run/user/{os.getuid()}")
    if runtime.is_dir() and runtime.stat().st_uid == os.getuid() and (runtime / "bus").exists():
        result.setdefault("XDG_RUNTIME_DIR", str(runtime))
        result.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    result.update(PATH="/usr/bin:/bin", LANG="C.UTF-8")
    return result


def _scope_prefix(unit: str, memory_mb: int, tasks_max: int, cpu_quota: int) -> list[str]:
    return [
        "/usr/bin/systemd-run", "--user", "--scope", "--quiet", "--collect",
        f"--unit={unit}", "-p", f"MemoryMax={memory_mb}M", "-p", "MemorySwapMax=0",
        "-p", f"TasksMax={tasks_max}", "-p", f"CPUQuota={cpu_quota}%",
        "-p", "OOMPolicy=kill",
    ]


def _base_bwrap() -> list[str]:
    return [
        "/usr/bin/bwrap", "--unshare-all", "--unshare-user", "--disable-userns",
        "--assert-userns-disabled", "--die-with-parent", "--new-session",
        "--cap-drop", "ALL", "--clearenv", "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin", "--symlink", "usr/sbin", "/sbin",
        "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
        "--proc", "/proc", "--dev", "/dev", "--size", str(256 * 1024 * 1024),
        "--tmpfs", "/tmp", "--dir", "/home/agent", "--dir", "/run",
    ]


class _Capture:
    def __init__(self, log):
        self.log = log
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0
        self.logged = 0

    def feed(self, data: bytes) -> None:
        self.total += len(data)
        if self.logged < _LOG_BYTES:
            chunk = data[:_LOG_BYTES - self.logged]
            self.log.write(chunk)
            self.logged += len(chunk)
        head_needed = _VIEW_BYTES - len(self.head)
        self.head.extend(data[:head_needed])
        self.tail.extend(data[head_needed:])
        if len(self.tail) > _VIEW_BYTES:
            del self.tail[:-_VIEW_BYTES]

    def text(self) -> str:
        marker = b"\n... output truncated ...\n" if self.total > 2 * _VIEW_BYTES else b""
        return (bytes(self.head) + marker + bytes(self.tail)).decode("utf-8", "replace")


class Sandbox:
    """Run bounded commands; never silently fall back to host execution.

    extra_ro_mounts is trusted operator configuration, never model input. Only
    /opt and /usr/local destinations may be mounted. Aggregate cgroup limits are
    required by default. An explicit require_cgroup=False permits per-process
    POSIX limits if the user bus is unavailable, and reports that weaker mode.
    """

    def __init__(self, workspace: Path, output_dir: Path, *, memory_mb: int = 4096,
                 tasks_max: int = 128, cpu_quota: int = 200,
                 extra_ro_mounts: dict[Path, str] | tuple[Path, ...] = (),
                 require_cgroup: bool = True, readonly_workspace: bool = False):
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("Workspace must be a directory")
        self.output_dir = Path(output_dir).resolve()
        if self.output_dir.is_relative_to(self.workspace):
            raise ValueError("Command logs must live outside the editable workspace")
        self.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.memory_mb = min(max(int(memory_mb), 256), 16384)
        self.tasks_max = min(max(int(tasks_max), 16), 512)
        self.cpu_quota = min(max(int(cpu_quota), 10), 800)
        self.require_cgroup = require_cgroup
        self.readonly_workspace = readonly_workspace
        self.extra_ro_mounts = []
        mounts = extra_ro_mounts.items() if isinstance(extra_ro_mounts, dict) else ((p, str(p)) for p in extra_ro_mounts)
        for source, target in mounts:
            path = Path(source).resolve(strict=True)
            destination = Path(target)
            if ".." in destination.parts or not any(destination.is_relative_to(base) for base in (Path("/opt"), Path("/usr/local"))):
                raise ValueError("Extra toolchain destinations must be inside /opt or /usr/local")
            self.extra_ro_mounts.append((path, destination))

    @staticmethod
    def doctor(refresh: bool = False) -> dict:
        """Actually probe namespace setup and user cgroup creation, once/process."""
        global _PROBE
        with _PROBE_LOCK:
            if _PROBE is not None and not refresh:
                return dict(_PROBE)
            result = {"bubblewrap": False, "cgroup": False, "errors": []}
            if not Path("/usr/bin/bwrap").is_file():
                result["errors"].append("/usr/bin/bwrap is missing; host execution is disabled")
            else:
                try:
                    check = subprocess.run(_base_bwrap() + ["/usr/bin/true"],
                                           env=_launcher_env(), capture_output=True, timeout=5)
                    result["bubblewrap"] = check.returncode == 0
                    if check.returncode:
                        result["errors"].append(check.stderr.decode("utf-8", "replace")[:1000])
                except (OSError, subprocess.TimeoutExpired) as exc:
                    result["errors"].append(str(exc))
            if all(Path(p).is_file() for p in ("/usr/bin/systemd-run", "/usr/bin/systemctl")):
                try:
                    check = subprocess.run(
                        _scope_prefix("local-coder-probe-" + uuid.uuid4().hex, 256, 32, 100)
                        + ["/usr/bin/true"], env=_launcher_env(), capture_output=True, timeout=5)
                    result["cgroup"] = check.returncode == 0
                    if check.returncode:
                        result["errors"].append(check.stderr.decode("utf-8", "replace")[:1000])
                except (OSError, subprocess.TimeoutExpired) as exc:
                    result["errors"].append(str(exc))
            else:
                result["errors"].append("systemd user scope support is missing")
            result["prlimit"] = Path("/usr/bin/prlimit").is_file()
            _PROBE = result
            return dict(result)

    def _argv(self, argv: list[str], cwd: str, timeout_seconds: int,
              unit: str, use_scope: bool) -> list[str]:
        if not isinstance(argv, list) or not 1 <= len(argv) <= 64:
            raise ValueError("argv must have 1–64 strings")
        if any(not isinstance(arg, str) or "\0" in arg or len(arg) > 8192 for arg in argv):
            raise ValueError("Invalid or oversized argv element")
        if sum(map(len, argv)) > 65536:
            raise ValueError("argv is too large")
        if not argv[0] or argv[0].startswith("-"):
            raise ValueError("Invalid executable")
        if not isinstance(cwd, str) or Path(cwd).is_absolute():
            raise ValueError("cwd must be relative to the workspace")
        working = (self.workspace / cwd).resolve(strict=True)
        if not working.is_relative_to(self.workspace) or not working.is_dir():
            raise ValueError("cwd escapes the workspace or is not a directory")
        prefix = _scope_prefix(unit, self.memory_mb, self.tasks_max, self.cpu_quota) if use_scope else []
        if Path("/usr/bin/prlimit").is_file():
            # Not a replacement for the aggregate memory and PID cgroup limits.
            prefix += ["/usr/bin/prlimit", "--core=0", "--fsize=67108864", "--nofile=256:256",
                       f"--cpu={timeout_seconds + 2}:{timeout_seconds + 3}"]
            if not use_scope:
                prefix += [f"--as={self.memory_mb * 1024 * 1024}", f"--nproc={self.tasks_max}"]
            prefix += ["--"]
        bwrap = _base_bwrap()
        for system_path in ("/etc/ld.so.cache", "/etc/os-release", "/etc/fonts"):
            if Path(system_path).exists():
                bwrap += ["--ro-bind", system_path, system_path]
        for source, target in self.extra_ro_mounts:
            bwrap += ["--ro-bind", str(source), str(target)]
        bwrap += ["--ro-bind" if self.readonly_workspace else "--bind", str(self.workspace), "/workspace"]
        git_dir = self.workspace / ".git"
        if git_dir.exists():
            if git_dir.is_symlink():
                raise ValueError("The workspace .git must not be a symlink")
            bwrap += ["--ro-bind", str(git_dir), "/workspace/.git"]
        environment = {
            "PATH": "/usr/bin:/bin", "HOME": "/home/agent", "LANG": "C.UTF-8",
            "TMPDIR": "/tmp", "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
            "LIBGL_ALWAYS_SOFTWARE": "1", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_ATTR_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/dev/null",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_ADDOPTS": "-p no:cacheprovider",
            "CARGO_TARGET_DIR": "/tmp/cargo-target", "XDG_CACHE_HOME": "/tmp/cache",
        }
        for name, value in environment.items():
            bwrap += ["--setenv", name, value]
        bwrap += ["--chdir", "/workspace/" + working.relative_to(self.workspace).as_posix(), "--"]
        return prefix + bwrap + argv

    @staticmethod
    def _kill(process: subprocess.Popen, unit: str | None) -> None:
        # The namespace's PID 1 kills remaining descendants on exit. Killing the
        # scope also covers descendants that escaped the launcher's process group.
        if unit:
            try:
                subprocess.run(["/usr/bin/systemctl", "--user", "kill", "--signal=KILL",
                                "--kill-whom=all", unit + ".scope"], env=_launcher_env(),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def run(self, argv: list[str], cwd: str = ".", timeout_seconds: int = 60,
            cancel_event: threading.Event | None = None) -> dict:
        start = time.monotonic()
        result = {"ok": False, "exit_code": None, "timed_out": False, "cancelled": False,
                  "stdout": "", "stderr": "", "output_truncated": False, "duration_ms": 0}
        job = "local-coder-job-" + uuid.uuid4().hex
        process = None
        used_scope = False
        try:
            if cancel_event and cancel_event.is_set():
                result["cancelled"] = True
                return result
            if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 120:
                raise ValueError("timeout_seconds must be an integer in 1–120")
            capabilities = self.doctor()
            if not capabilities["bubblewrap"]:
                raise RuntimeError("Namespace sandbox is unavailable: " + "; ".join(capabilities["errors"]))
            used_scope = capabilities["cgroup"]
            if not used_scope and self.require_cgroup:
                raise RuntimeError("Aggregate cgroup limits unavailable; command execution is disabled")
            if not used_scope and not capabilities["prlimit"]:
                raise RuntimeError("No resource limiter is available; command execution is disabled")
            command = self._argv(argv, cwd, timeout_seconds, job, used_scope)
            result["resource_limits"] = "cgroup" if used_scope else "per-process-posix-only"
            log_paths = {stream: self.output_dir / f"{job}.{stream}.log" for stream in ("stdout", "stderr")}
            with log_paths["stdout"].open("xb") as out_log, log_paths["stderr"].open("xb") as err_log:
                os.chmod(log_paths["stdout"], 0o600)
                os.chmod(log_paths["stderr"], 0o600)
                captures = {"stdout": _Capture(out_log), "stderr": _Capture(err_log)}
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, env=_launcher_env(), start_new_session=True)
                with selectors.DefaultSelector() as selector:
                    for name in ("stdout", "stderr"):
                        stream = getattr(process, name)
                        os.set_blocking(stream.fileno(), False)
                        selector.register(stream, selectors.EVENT_READ, name)
                    deadline = time.monotonic() + timeout_seconds
                    killed = False
                    drain_deadline = None
                    while selector.get_map() or process.poll() is None:
                        now = time.monotonic()
                        cancelled = cancel_event is not None and cancel_event.is_set()
                        if not killed and (cancelled or now >= deadline):
                            result["cancelled"] = cancelled
                            result["timed_out"] = not cancelled
                            self._kill(process, job if used_scope else None)
                            killed = True
                            drain_deadline = time.monotonic() + 2
                        if drain_deadline is not None and now >= drain_deadline:
                            break
                        for key, _ in selector.select(timeout=0.1):
                            chunk = os.read(key.fileobj.fileno(), 65536)
                            if chunk:
                                captures[key.data].feed(chunk)
                            else:
                                selector.unregister(key.fileobj)
                    try:
                        result["exit_code"] = process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        result["cancelled"] = bool(cancel_event and cancel_event.is_set())
                        result["timed_out"] = not result["cancelled"]
                        self._kill(process, job if used_scope else None)
                        result["exit_code"] = process.wait(timeout=3)
                for name in ("stdout", "stderr"):
                    result[name] = captures[name].text()
                    getattr(process, name).close()
                result["output_truncated"] = any(c.total > 2 * _VIEW_BYTES for c in captures.values())
                result["log_truncated"] = any(c.total > _LOG_BYTES for c in captures.values())
                result["log_paths"] = {name: str(path) for name, path in log_paths.items()}
                result["ok"] = result["exit_code"] == 0 and not result["timed_out"] and not result["cancelled"]
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            if process is not None and process.poll() is None:
                self._kill(process, job if used_scope else None)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
            result["stderr"] = str(exc)[:6000]
        finally:
            result["duration_ms"] = round((time.monotonic() - start) * 1000)
        return result
