import asyncio
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from mcp import Client, StdioServerParameters

class MCPTests(unittest.TestCase):
    def test_real_stdio_discovery_patch_and_isolated_command(self):
        async def check(source):
            params=StdioServerParameters(command=sys.executable,args=["-m","local_coder.cli","mcp","--source",str(source)])
            async with Client(params) as client:
                listing=await client.list_tools()
                self.assertIn("file_patch",{t.name for t in listing.tools})
                r=await client.call_tool("read_file",{"path":"example.py"})
                self.assertFalse(r.is_error)
                patch=await client.call_tool("file_patch",{"path":"example.py",
                    "expected_sha256":hashlib.sha256(b"answer = 41\n").hexdigest(),
                    "old_text":"answer = 41","new_text":"answer = 42"})
                self.assertFalse(patch.is_error,patch)
                command=await client.call_tool("run_command",{"argv":["python3","-c","from example import answer; assert answer == 42"]})
                self.assertFalse(command.is_error,command)
                self.assertIn('"ok": true',command.content[0].text)
                self.assertEqual((source/"example.py").read_text(),"answer = 41\n")
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/"example.py").write_text("answer = 41\n")
            asyncio.run(check(p))

    def test_handoff_stdio_advertises_only_orchestration_tools(self):
        async def check(source):
            params=StdioServerParameters(command=sys.executable,
                args=["-m","local_coder.cli","handoff-mcp","--source",str(source)])
            async with Client(params) as client:
                listing=await client.list_tools()
                self.assertEqual({t.name for t in listing.tools},{
                    "handoff_to_local_ai","get_handoff_status","get_handoff_diff","cancel_handoff"})
                handoff=next(t for t in listing.tools if t.name=="handoff_to_local_ai")
                self.assertIn("attachment_paths",handoff.input_schema["properties"])
                self.assertIn("source_path",handoff.input_schema["properties"])
                self.assertIn("auto_apply",handoff.input_schema["properties"])
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(check(Path(d)))
