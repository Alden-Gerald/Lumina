from pathlib import Path
import tempfile
import unittest
from local_coder.sandbox import Sandbox
from local_coder.validation import validate
from local_coder.settings import TOOLCHAIN

class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Sandbox.doctor().get("cgroup"):raise unittest.SkipTest("Cgroup sandbox required")
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.repo=self.base/"repo";self.repo.mkdir()
        self.sandbox=Sandbox(self.repo,self.base/"logs",readonly_workspace=True,
            extra_ro_mounts={TOOLCHAIN:"/opt/local-coder-toolchain"})
    def tearDown(self):self.tmp.cleanup()
    def test_python_syntax_failure_is_reported_without_execution(self):
        (self.repo/"test.py").write_text("def broken(:\n    pass\n")
        result=validate(self.repo,self.sandbox,profile="generic")
        self.assertFalse(result["ok"],result);self.assertEqual(result["diagnostics"][0]["check"],"Python syntax")
        (self.repo/"test.py").write_text("raise RuntimeError('must not execute')\n")
        self.assertTrue(validate(self.repo,self.sandbox,profile="generic")["ok"])
    def test_qml_parser_rejects_invalid_syntax(self):
        (self.repo/"Example.qml").write_text("import QtQuick\nItem { property int value: 1 }\n")
        self.assertTrue(validate(self.repo,self.sandbox)["ok"])
        (self.repo/"Example.qml").write_text("import QtQuick\nItem { property int value: }\n")
        result=validate(self.repo,self.sandbox)
        self.assertFalse(result["ok"],result);self.assertEqual(result["diagnostics"][0]["check"],"QML syntax")
    def test_command_workspace_is_readonly(self):
        result=self.sandbox.run(["touch","unauthorized.py"])
        self.assertFalse(result["ok"]);self.assertFalse((self.repo/"unauthorized.py").exists())

if __name__=="__main__":unittest.main()
