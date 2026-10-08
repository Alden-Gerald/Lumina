"""Harmless live namespace tests; no GPU, network traffic or host edits."""
import errno
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

from local_coder.sandbox import Sandbox


class SandboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        status = Sandbox.doctor()
        if not status["bubblewrap"] or not status["cgroup"]:
            raise unittest.SkipTest("Bubblewrap + user systemd scopes required: " + str(status))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="local-coder-sandbox-test-")
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        (self.repo / "example.txt").write_text("hello\n")
        self.sandbox = Sandbox(self.repo, self.base / "logs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_isolation_and_writable_checkout(self):
        program = r'''
import os, pathlib, socket, json
r = {"home": sorted(os.listdir('/home')), "runtime_hidden": not pathlib.Path('/run/user').exists(),
     "gpu_hidden": not pathlib.Path('/dev/dri').exists(), "host_pid_hidden": len(list(pathlib.Path('/proc').glob('[0-9]*'))) < 10,
     "secret_env_hidden": 'LOCAL_CODER_TEST_SECRET' not in os.environ,
     "dbus_hidden": 'DBUS_SESSION_BUS_ADDRESS' not in os.environ,
     "wayland_hidden": 'WAYLAND_DISPLAY' not in os.environ}
for label, path in [('usr_readonly', '/usr/local-coder-test'), ('git_readonly', '/workspace/.git/agent-test')]:
    try: pathlib.Path(path).write_text('x'); r[label] = False
    except OSError as exc: r[label] = exc.errno
s = socket.socket(); s.settimeout(0.2)
try: s.connect(('1.1.1.1', 80)); r['no_network'] = False
except OSError as exc: r['no_network'] = exc.errno
pathlib.Path('changed.txt').write_text('allowed')
print(json.dumps(r))
'''
        os.environ["LOCAL_CODER_TEST_SECRET"] = "must-not-cross-boundary"
        try:
            result = self.sandbox.run(["python3", "-c", program])
        finally:
            os.environ.pop("LOCAL_CODER_TEST_SECRET", None)
        self.assertTrue(result["ok"], result)
        observation = json.loads(result["stdout"])
        self.assertEqual(observation["home"], ["agent"])
        self.assertEqual(observation["usr_readonly"], errno.EROFS)
        self.assertEqual(observation["git_readonly"], errno.EROFS)
        self.assertEqual(observation["no_network"], errno.ENETUNREACH)
        for field in ("runtime_hidden", "gpu_hidden", "host_pid_hidden", "secret_env_hidden", "dbus_hidden", "wayland_hidden"):
            self.assertTrue(observation[field], field)
        self.assertEqual((self.repo / "changed.txt").read_text(), "allowed")
        self.assertEqual(result["resource_limits"], "cgroup")

    def test_output_is_bounded_and_pipes_keep_draining(self):
        result = self.sandbox.run(["python3", "-c", "import sys;sys.stdout.write('x'*2000000);sys.stderr.write('y'*2000000)"])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["output_truncated"])
        self.assertTrue(result["log_truncated"])
        self.assertLessEqual(len(result["stdout"]) + len(result["stderr"]), 12000)
        for path in result["log_paths"].values():
            self.assertLessEqual(Path(path).stat().st_size, 1024 * 1024)

    def test_nonzero_exit_is_an_observation(self):
        result = self.sandbox.run(["python3", "-c", "import sys;print('diagnostic', file=sys.stderr);sys.exit(7)"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], 7)
        self.assertIn("diagnostic", result["stderr"])

    def test_timeout_kills_descendants(self):
        program = "import subprocess,time;subprocess.Popen(['python3','-c',\"import pathlib,time;time.sleep(2);pathlib.Path('escaped.txt').write_text('bad')\"]);time.sleep(10)"
        result = self.sandbox.run(["python3", "-c", program], timeout_seconds=1)
        self.assertTrue(result["timed_out"], result)
        self.assertFalse(result["ok"])
        time.sleep(1.3)
        self.assertFalse((self.repo / "escaped.txt").exists())

    def test_cancel_even_when_command_closes_output(self):
        cancelled = threading.Event()
        timer = threading.Timer(0.3, cancelled.set)
        timer.start()
        start = time.monotonic()
        result = self.sandbox.run(["python3", "-c", "import os,time;os.close(1);os.close(2);time.sleep(10)"], cancel_event=cancelled)
        timer.join()
        self.assertTrue(result["cancelled"], result)
        self.assertFalse(result["timed_out"])
        self.assertLess(time.monotonic() - start, 4)

    def test_symlink_and_parent_cwd_escape_rejected(self):
        (self.repo / "outside").symlink_to(self.base, target_is_directory=True)
        for cwd in ("../", "outside", "/tmp"):
            result = self.sandbox.run(["true"], cwd=cwd)
            self.assertFalse(result["ok"])
            self.assertIsNone(result["exit_code"])

    def test_extra_toolchain_mapping_is_readonly(self):
        source = self.base / "toolchain"
        source.mkdir()
        (source / "version").write_text("test")
        sandbox = Sandbox(self.repo, self.base / "logs", extra_ro_mounts={source: "/opt/local-coder-toolchain"})
        result = sandbox.run(["python3", "-c", "from pathlib import Path; print(Path('/opt/local-coder-toolchain/version').read_text())"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["stdout"].strip(), "test")
        result = sandbox.run(["touch", "/opt/local-coder-toolchain/unwanted"])
        self.assertFalse(result["ok"])
        self.assertFalse((source / "unwanted").exists())

    def test_unavailable_cgroup_fails_closed(self):
        self.sandbox.doctor = lambda: {"bubblewrap": True, "cgroup": False, "prlimit": True, "errors": []}
        result = self.sandbox.run(["touch", "must-not-exist"])
        self.assertFalse(result["ok"])
        self.assertIn("cgroup", result["stderr"])
        self.assertFalse((self.repo / "must-not-exist").exists())


if __name__ == "__main__":
    unittest.main()
