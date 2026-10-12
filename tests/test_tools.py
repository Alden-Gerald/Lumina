import hashlib
from pathlib import Path
import tempfile
import unittest
from local_coder.tools import Tools

class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.root.mkdir()
        (self.root/"a.py").write_text("value = 1\n")
        (self.root/".git").mkdir();(self.root/".git/config").write_text("protected")
        self.tools=Tools(self.root,None)
    def tearDown(self):self.temp.cleanup()
    def test_existing_node_behavior_tests_cannot_be_weakened(self):
        for name in ['test-battery.cjs','battery.test.cjs','battery.spec.mjs']:
            (self.root/name).write_text('assert.equal(label(75,true),"⚡ 75%");')
        tools=Tools(self.root,None)
        for name in ['test-battery.cjs','battery.test.cjs','battery.spec.mjs']:
            before=tools.read_file(name)
            with self.assertRaisesRegex(ValueError,'protected'):
                tools.file_patch(name,before['sha256'],'assert.equal','console.log')
    def test_stale_and_ambiguous_patches_are_rejected(self):
        data=self.tools.read_file("a.py")
        with self.assertRaisesRegex(ValueError,"hash"):self.tools.file_patch("a.py","wrong","1","2")
        with self.assertRaisesRegex(ValueError,"exactly once"):self.tools.file_patch("a.py",data["sha256"],"missing","2")
        result=self.tools.file_patch("a.py",data["sha256"],"value = 1","value = 2")
        self.assertEqual((self.root/"a.py").read_text(),"value = 2\n")
        self.assertEqual(result["sha256"],hashlib.sha256(b"value = 2\n").hexdigest())
        with self.assertRaisesRegex(ValueError,"hash"):self.tools.file_patch("a.py",data["sha256"],"2","3")
    def test_metadata_secret_and_symlink_paths_are_rejected(self):
        (self.root/"alias").symlink_to(self.root/".git/config")
        for path in ["../outside","/etc/passwd",".git/config",".env","alias"]:
            with self.assertRaises((ValueError,FileNotFoundError)):self.tools.read_file(path)
    def test_unknown_dispatch_and_create_overwrite_rejected(self):
        with self.assertRaises(ValueError):self.tools.dispatch("eval",{"content":"bad"})
        with self.assertRaises(ValueError):self.tools.create_file("a.py","overwrite")
        self.tools.create_file("new/test.py","answer = 42\n")
        self.assertEqual(self.tools.read_file("new/test.py")["text"],"answer = 42\n")
    def test_line_ranges_and_literal_search(self):
        self.assertEqual(self.tools.search_code("VALUE")["matches"][0]["path"],"a.py")
        with self.assertRaises(ValueError):self.tools.read_file("a.py",0)
        with self.assertRaises(ValueError):self.tools.read_file("a.py",line_count=1000)
    def test_existing_tests_cannot_be_weakened(self):
        (self.root/"tests").mkdir()
        (self.root/"tests/test_value.py").write_text("assert value == 1\n")
        tools=Tools(self.root,None)
        result=tools.read_file("tests/test_value.py")
        with self.assertRaisesRegex(ValueError,"protected"):
            tools.file_patch("tests/test_value.py",result["sha256"],"assert value == 1","pass")
        tools.create_file("tests/test_new.py","assert True\n")

if __name__=="__main__":unittest.main()
