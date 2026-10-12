import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from local_coder.awake import AwakeChats, AwakeManager, SleepInhibitor, _start_inhibitor
from local_coder.chat import Chats
from local_coder.controller import Manager


class SleepInhibitorTests(unittest.TestCase):
    def test_logind_request_blocks_sleep_only(self):
        class Process:
            stdin = io.BytesIO()
            stdout = io.BytesIO(b'READY\n')

        process = Process()
        with patch('local_coder.awake.shutil.which', return_value='/usr/bin/systemd-inhibit'), \
             patch('local_coder.awake.subprocess.Popen', return_value=process) as launch, \
             patch('local_coder.awake.select.select', return_value=([process.stdout], [], [])):
            self.assertIs(_start_inhibitor(), process)
        command = launch.call_args.args[0]
        self.assertIn('--what=sleep', command)
        self.assertIn('--mode=block', command)
        self.assertNotIn('--what=idle', command)

    def test_overlapping_jobs_hold_one_inhibitor_until_last_finishes(self):
        calls = []
        token = object()
        guard = SleepInhibitor(lambda: calls.append('start') or token,
                               lambda process: calls.append(('stop', process)))
        first_ready = threading.Event()
        first_done = threading.Event()
        release_first = threading.Event()

        def first_job():
            with guard.hold():
                first_ready.set()
                release_first.wait(2)
            first_done.set()

        thread = threading.Thread(target=first_job)
        thread.start()
        self.assertTrue(first_ready.wait(1))
        with guard.hold():
            self.assertEqual(calls, ['start'])
            self.assertEqual(guard.status()['active_jobs'], 2)
            release_first.set()
            self.assertTrue(first_done.wait(1))
            self.assertTrue(guard.status()['sleep_blocked'])
        thread.join(1)
        self.assertEqual(calls, ['start', ('stop', token)])
        self.assertEqual(guard.status()['active_jobs'], 0)

    def test_failure_and_shutdown_release_without_breaking_ai(self):
        calls = []
        guard = SleepInhibitor(lambda: (_ for _ in ()).throw(OSError('no logind')),
                               lambda _: calls.append('stop'))
        with guard.hold():
            self.assertFalse(guard.status()['sleep_blocked'])
            self.assertIn('no logind', guard.status()['error'])
        self.assertEqual(guard.status()['active_jobs'], 0)
        guard = SleepInhibitor(lambda: object(), lambda _: calls.append('stop'))
        with guard.hold():
            guard.close()
            self.assertFalse(guard.status()['sleep_blocked'])
        self.assertEqual(calls, ['stop'])

    def test_chat_and_code_workers_use_the_shared_guard(self):
        calls = []
        guard = SleepInhibitor(lambda: calls.append('start') or object(),
                               lambda _: calls.append('stop'))
        with tempfile.TemporaryDirectory() as directory, patch('local_coder.awake.sleep_inhibitor', guard):
            chats = AwakeChats(Path(directory) / 'chats')
            manager = AwakeManager(Path(directory) / 'runs')
            def check_active(*_args, **_kwargs):
                self.assertTrue(guard.status()['sleep_blocked'])
            with patch.object(Chats, 'run', side_effect=check_active):
                chats.run({}, threading.Event())
            with patch.object(Manager, '_run', side_effect=check_active):
                manager._run({}, threading.Event())
            with patch.object(Manager, '_retry_desktop', side_effect=ValueError('cancelled')):
                with self.assertRaisesRegex(ValueError, 'cancelled'):
                    manager._retry_desktop({}, threading.Event())
        self.assertEqual(calls, ['start', 'stop'] * 3)
        self.assertFalse(guard.status()['sleep_blocked'])


if __name__ == '__main__':
    unittest.main()
