"""Keep the host awake only while the local AI has active work.

The logind inhibitor covers ``sleep`` only.  Idle/display handling remains with
the desktop, so the monitor can still dim, lock, or turn off normally.
"""
from __future__ import annotations

from contextlib import contextmanager
import logging
import select
import shutil
import subprocess
import sys
import threading

from .chat import Chats
from .controller import Manager


_LOG = logging.getLogger(__name__)
_READY = b"READY\n"
_HOLDER = (
    'import sys; '
    'sys.stdout.buffer.write(b"READY\\n"); sys.stdout.buffer.flush(); '
    'sys.stdin.buffer.read()'
)


def _start_inhibitor():
    command = shutil.which("systemd-inhibit")
    if not command:
        raise OSError("systemd-inhibit is unavailable; AI work will continue without sleep protection")
    # The child is started only after logind grants the inhibitor. Its stdin is
    # a pipe: if Lumina crashes, EOF makes it exit and releases the inhibitor.
    process = subprocess.Popen(
        [command, "--what=sleep", "--mode=block", "--who=Lumina",
         "--why=Local AI task in progress", sys.executable, "-u", "-c", _HOLDER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    try:
        readable, _, _ = select.select([process.stdout], [], [], 2.0)
        if not readable or process.stdout.readline() != _READY:
            raise OSError("logind did not confirm the sleep inhibitor")
        process.stdout.close()
        return process
    except Exception:
        _stop_inhibitor(process)
        raise


def _stop_inhibitor(process):
    if process.stdin and not process.stdin.closed:
        process.stdin.close()
    if process.stdout and not process.stdout.closed:
        process.stdout.close()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


class SleepInhibitor:
    """One process-wide logind inhibitor shared by overlapping AI jobs."""

    def __init__(self, start=None, stop=None):
        self._lock = threading.RLock()
        self._start = start or _start_inhibitor
        self._stop = stop or _stop_inhibitor
        self._process = None
        self._jobs = 0
        self._error = None
        self._closed = False

    def acquire(self):
        with self._lock:
            if self._closed:
                return
            self._jobs += 1
            if self._process is None:
                try:
                    self._process = self._start()
                    self._error = None
                except Exception as exc:
                    self._error = str(exc)[:240]
                    _LOG.warning("Sleep protection unavailable: %s", self._error)

    def release(self):
        with self._lock:
            if self._closed:
                return
            if self._jobs <= 0:
                raise RuntimeError("Sleep inhibitor released without an active AI job")
            self._jobs -= 1
            if self._jobs == 0 and self._process is not None:
                process, self._process = self._process, None
                try:
                    self._stop(process)
                except Exception as exc:
                    self._error = str(exc)[:240]
                    _LOG.warning("Could not release sleep protection cleanly: %s", self._error)

    @contextmanager
    def hold(self):
        self.acquire()
        try:
            yield
        finally:
            self.release()

    def status(self):
        with self._lock:
            return {"active_jobs": self._jobs,
                    "sleep_blocked": self._process is not None,
                    "error": self._error}

    def close(self):
        with self._lock:
            self._closed = True
            self._jobs = 0
            if self._process is not None:
                process, self._process = self._process, None
                try:
                    self._stop(process)
                except Exception as exc:
                    _LOG.warning("Could not close sleep protection cleanly: %s", exc)


sleep_inhibitor = SleepInhibitor()


class AwakeManager(Manager):
    def _run(self, *args, **kwargs):
        with sleep_inhibitor.hold():
            return super()._run(*args, **kwargs)

    def _retry_desktop(self, *args, **kwargs):
        with sleep_inhibitor.hold():
            return super()._retry_desktop(*args, **kwargs)


class AwakeChats(Chats):
    def run(self, *args, **kwargs):
        with sleep_inhibitor.hold():
            return super().run(*args, **kwargs)
