import json
from pathlib import Path
import tempfile
import unittest
import io
from PIL import Image
from local_coder.controller import Manager
from local_coder.project import digest
from local_coder.sandbox import Sandbox

class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Sandbox.doctor().get("cgroup"):raise unittest.SkipTest("Cgroup sandbox required")
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.source=self.base/"source";self.source.mkdir();(self.source/"calc.py").write_text("def add(a, b):\n    return a - b\n")
    def tearDown(self):self.temp.cleanup()
    def fake(self,messages,schema,profile,flag,deadline,limit,progress):
        if "objective" in schema["properties"]:
            return {"objective":"Fix addition","steps":["Read","Patch","Check"],"acceptance":["Addition works"]},{}
        if "approved" in schema["properties"]:return {"approved":True,"findings":[]},{}
        n=self.calls;self.calls+=1
        if n==0:return {"summary":"Read calculator","tool":"read_file","arguments":{"path":"calc.py"}},{}
        if n==1:
            result=json.loads(messages[-1]["content"].split(": ",1)[1])["result"]
            return {"summary":"Repair addition","tool":"file_patch","arguments":{"path":"calc.py","expected_sha256":result["sha256"],"old_text":"return a - b","new_text":"return a + b"}},{}
        if n==2:return {"summary":"Check behavior","tool":"verify","arguments":{}},{}
        return {"summary":"Addition now works","tool":"finish","arguments":{}},{}
    def test_complete_check_commit_apply_and_source_conflict(self):
        self.calls=0;m=Manager(self.base/"runs",inference=self.fake)
        state=m.start("Fix the addition function",source=self.source,project_profile="generic",
            test_commands=[["python3","-c","from calc import add; assert add(3,2)==5"]],background=False)
        self.assertEqual(state["status"],"completed",state["message"])
        self.assertTrue(state["commit"])
        self.assertIn("a - b",(self.source/"calc.py").read_text())
        self.assertIn("+    return a + b",m.diff(state["id"]))
        (self.source/"calc.py").write_text("changed by user\n")
        with self.assertRaisesRegex(ValueError,"Source changed"):m.apply(state["id"])
        (self.source/"calc.py").write_text("def add(a, b):\n    return a - b\n")
        result=m.apply(state["id"])
        self.assertEqual(result["applied"],["calc.py"])
        self.assertIn("a + b",(self.source/"calc.py").read_text())
    def test_failure_observation_drives_a_different_patch(self):
        count=0
        def inference(messages,schema,profile,flag,deadline,limit,progress):
            nonlocal count
            if "objective" in schema["properties"]:return {"objective":"Fix","steps":["Inspect","Repair"],"acceptance":[]},{}
            if "approved" in schema["properties"]:return {"approved":True,"findings":[]},{}
            count+=1
            if count==1:return {"summary":"Read","tool":"read_file","arguments":{"path":"calc.py"}},{}
            if count==2:
                sha=json.loads(messages[-1]["content"].split(": ",1)[1])["result"]["sha256"]
                return {"summary":"Patch","tool":"file_patch","arguments":{"path":"calc.py","expected_sha256":sha,"old_text":"return a - b","new_text":"return a +"}},{}
            if count==3:return {"summary":"Check","tool":"verify","arguments":{}},{}
            if count==4:
                self.assertIn("Source checks failed",messages[-1]["content"])
                return {"summary":"Reread failed code","tool":"read_file","arguments":{"path":"calc.py"}},{}
            if count==5:
                sha=json.loads(messages[-1]["content"].split(": ",1)[1])["result"]["sha256"]
                return {"summary":"Repair observed syntax","tool":"file_patch","arguments":{"path":"calc.py","expected_sha256":sha,"old_text":"return a +","new_text":"return a + b"}},{}
            return {"summary":"Done","tool":"finish","arguments":{}},{}
        m=Manager(self.base/"runs",inference=inference)
        state=m.start("Fix the calculator",source=self.source,project_profile="generic",
            test_commands=[["python3","-c","from calc import add; assert add(3,2)==5"]],background=False)
        self.assertEqual(state["status"],"completed",state["message"])
        self.assertTrue(state["failed_attempts"])
    def test_repeated_actions_stop_without_commit(self):
        def inference(messages,schema,*args):
            if "objective" in schema["properties"]:return {"objective":"Read","steps":["Read"],"acceptance":[]},{}
            return {"summary":"Repeat","tool":"read_file","arguments":{"path":"calc.py"}},{}
        m=Manager(self.base/"runs",inference=inference)
        state=m.start("Inspect and improve calculator",source=self.source,background=False)
        self.assertEqual(state["status"],"needs_attention")
        self.assertIn("Repeated identical",state["message"])
        self.assertNotIn("commit",state)
    def test_visual_description_reaches_plan_and_coding_without_raw_image(self):
        self.calls=0;seen=[]
        def inference(messages,schema,profile,*args):
            seen.append(profile)
            if profile=='_vision':
                self.assertIn('images',messages[-1])
                return {'description':'Blue rectangle marked ADD','visible_text':['ADD'],'design_details':[],'uncertainties':[]},{}
            if 'objective' in schema['properties']:self.assertIn('Blue rectangle marked ADD',messages[-1]['content'])
            else:self.assertNotIn('images',messages[-1])
            return self.fake(messages,schema,profile,*args)
        m=Manager(self.base/'runs',inference=inference)
        buf=io.BytesIO();Image.new('RGB',(20,10),'blue').save(buf,format='PNG')
        a=m.image_store.save(buf.getvalue(),'reference.png')
        state=m.start('Fix addition using the reference',source=self.source,attachments=[a['id']],
            test_commands=[['python3','-c','from calc import add; assert add(3,2)==5']],background=False)
        self.assertEqual(state['status'],'completed',state['message'])
        self.assertEqual(seen[0],'_vision');self.assertEqual(state['visual_observations'][0]['analysis']['visible_text'],['ADD'])
    def test_document_reference_reaches_plan_without_using_vision(self):
        self.calls=0;seen=[]
        def inference(messages,schema,profile,*args):
            seen.append(profile)
            if 'objective' in schema['properties']:self.assertIn('Add the two arguments',messages[-1]['content'])
            return self.fake(messages,schema,profile,*args)
        m=Manager(self.base/'runs',inference=inference)
        file=m.image_store.save(b'Feature specification: Add the two arguments rather than subtracting them.','spec.txt')
        state=m.start('Fix addition according to the attached specification',source=self.source,attachments=[file['id']],
            test_commands=[['python3','-c','from calc import add; assert add(3,2)==5']],background=False)
        self.assertEqual(state['status'],'completed',state['message']);self.assertNotIn('_vision',seen)
        self.assertTrue(state['file_passages'])

if __name__=="__main__":unittest.main()
