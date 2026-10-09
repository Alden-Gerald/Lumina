from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from local_coder.desktop import finish_quickshell


class DesktopTests(unittest.TestCase):
    @patch("local_coder.desktop.OPENCLAW", Path("/bin/true"))
    @patch("local_coder.desktop.RESTART_ORBIT", Path("/bin/true"))
    @patch("local_coder.desktop.subprocess.run")
    def test_reload_then_read_only_openclaw_inspection(self, run):
        run.side_effect = [
            subprocess.CompletedProcess(["restart"], 0, "", ""),
            subprocess.CompletedProcess(["openclaw"], 0, '{"result":"visible"}', ""),
        ]
        result = finish_quickshell("a" * 32, "Align the toggles")
        self.assertTrue(result["reloaded"])
        self.assertEqual(result["openclaw"]["status"], "inspected")
        self.assertIn("Use only the wayland_screenshot", " ".join(run.call_args_list[1].args[0]))


if __name__ == "__main__":
    unittest.main()
