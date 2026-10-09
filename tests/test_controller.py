import json
from pathlib import Path
import tempfile
import unittest
import io
import time
from PIL import Image
from unittest.mock import patch
from local_coder.controller import Manager
from local_coder.preferences import preference_guidance
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
            test_commands=[["python3","-c","from calc import add; assert add(3,2)==5"]],background=False,origin="codex")
        self.assertEqual(state["status"],"completed",state["message"])
        self.assertEqual(state["origin"],"codex");self.assertEqual(m.list()[0]["origin"],"codex")
        self.assertTrue(state["commit"])
        self.assertIn("a - b",(self.source/"calc.py").read_text())
        self.assertIn("+    return a + b",m.diff(state["id"]))
        (self.source/"calc.py").write_text("changed by user\n")
        with self.assertRaisesRegex(ValueError,"Source changed"):m.apply(state["id"])
        (self.source/"calc.py").write_text("def add(a, b):\n    return a - b\n")
        result=m.apply(state["id"])
        self.assertEqual(result["applied"],["calc.py"])
        self.assertIn("a + b",(self.source/"calc.py").read_text())
    def test_codex_auto_apply_writes_verified_result(self):
        self.calls=0;m=Manager(self.base/"runs",inference=self.fake)
        state=m.start("Fix the addition function",source=self.source,project_profile="generic",
            test_commands=[["python3","-c","from calc import add; assert add(3,2)==5"]],
            background=False,origin="codex",auto_apply=True)
        self.assertEqual(state["status"],"completed",state["message"])
        self.assertEqual(state["applied"]["applied"],["calc.py"])
        self.assertIn("a + b",(self.source/"calc.py").read_text())
    def test_codex_auto_apply_blocks_new_warnings(self):
        self.calls=0;m=Manager(self.base/"runs",inference=self.fake)
        verify=m._verify
        def warned(*args,**kwargs):
            report=verify(*args,**kwargs)
            report["new_warnings"]=[{"path":"calc.py","code":"new-warning","count":1}]
            args[0]["validation"]=report
            return report
        m._verify=warned
        state=m.start("Fix the addition function",source=self.source,project_profile="generic",
            test_commands=[["python3","-c","from calc import add; assert add(3,2)==5"]],
            background=False,origin="codex",auto_apply=True)
        self.assertEqual(state["status"],"needs_attention")
        self.assertIn("introduced new source warnings",state["message"])
        self.assertIn("a - b",(self.source/"calc.py").read_text())

    def test_review_cannot_approve_its_own_correctness_findings(self):
        self.calls=0
        def contradictory(messages,schema,profile,flag,deadline,limit,progress):
            if "approved" in schema["properties"]:
                return {"approved":True,"findings":["Required UI behavior is missing."]},{}
            return self.fake(messages,schema,profile,flag,deadline,limit,progress)
        manager=Manager(self.base/"runs",inference=contradictory)
        state=manager.start("Fix the addition function",source=self.source,project_profile="generic",
            test_commands=[["python3","-c","from calc import add; assert add(3,2)==5"]],
            background=False,origin="codex",auto_apply=True)
        self.assertEqual(state["status"],"needs_attention")
        self.assertFalse(state["review"]["approved"])
        self.assertIn("cannot approve",state["review"]["consistency_error"])
        self.assertNotIn("commit",state)
        self.assertIn("a - b",(self.source/"calc.py").read_text())
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
        self.assertGreaterEqual(state["preference_pairs"],1)
        preferences=self.base/"training"/"coding-preferences.jsonl"
        self.assertTrue(preferences.exists())
        pair=json.loads(preferences.read_text().splitlines()[-1])
        self.assertEqual(pair["format"],"lumina-coding-preference-v1")
        self.assertNotIn("return a +",preferences.read_text())
        guidance,count=preference_guidance(self.base)
        self.assertGreaterEqual(count,1)
        self.assertIn("prefer gathering evidence",guidance)

    def test_roadmap_profile_persists_checked_plan_and_defaults_to_auto_solve(self):
        self.calls=0;m=Manager(self.base/"runs",inference=self.fake)
        state=m.start("Fix the addition function",source=self.source,profile="roadmap",project_profile="generic",
            test_commands=[["python3","-c","from calc import add; assert add(3,2)==5"]],background=False)
        self.assertEqual(state["status"],"completed",state["message"])
        self.assertFalse(state["auto_solve"])
        roadmap=self.base/"runs"/state["id"]/"roadmap.md"
        self.assertTrue(roadmap.exists())
        self.assertIn("# Local task roadmap",roadmap.read_text())
        self.assertNotIn("- [ ]",roadmap.read_text())
        self.assertTrue(state["validation"]["ok"])
    def test_context_compaction_is_logged_and_keeps_latest_observation_and_task(self):
        self.calls=0;seen=[]
        def infer(messages,*args):
            seen.append(json.dumps(messages));return self.fake(messages,*args)
        m=Manager(self.base/'runs',inference=infer)
        # Simulate a full window after two action/observation pairs.
        with patch('local_coder.controller.estimate',side_effect=lambda messages,*_:999999 if len(messages)>4 else 100):
            state=m.start('Fix the addition function',source=self.source,project_profile='generic',
                test_commands=[['python3','-c','from calc import add; assert add(3,2)==5']],background=False)
        self.assertEqual(state['status'],'completed',state['message'])
        events=m.events(state['id']);self.assertTrue(any(e['kind']=='optimized' for e in events))
        self.assertTrue(any('Reading file' in e['message'] for e in events))
        self.assertTrue(any('Editing file' in e['message'] for e in events))
        self.assertIn('Fix the addition function',seen[-2]);self.assertIn('Recent failed attempts',seen[-2])
    def test_repeated_actions_stop_without_commit(self):
        def inference(messages,schema,*args):
            if "objective" in schema["properties"]:return {"objective":"Read","steps":["Read"],"acceptance":[]},{}
            return {"summary":"Repeat","tool":"read_file","arguments":{"path":"calc.py"}},{}
        m=Manager(self.base/"runs",inference=inference)
        state=m.start("Inspect and improve calculator",source=self.source,background=False)
        self.assertEqual(state["status"],"needs_attention")
        self.assertIn("Repeated identical",state["message"])
        self.assertNotIn("commit",state)

    def test_needs_attention_can_resume_preserved_workspace(self):
        failing=True;actions=0;plan_calls=0
        def inference(messages,schema,*args):
            nonlocal failing,actions,plan_calls
            if "objective" in schema["properties"]:
                plan_calls+=1
                return {"objective":"Fix addition","steps":["Inspect","Repair","Check"],"acceptance":["Addition works"]},{}
            if "approved" in schema["properties"]:return {"approved":True,"findings":[]},{}
            if failing:return {"summary":"Cannot proceed","tool":"stop","arguments":{"reason":"Temporary tool failure"}},{}
            actions+=1
            if actions==1:return {"summary":"Read preserved calculator","tool":"read_file","arguments":{"path":"calc.py"}},{}
            if actions==2:
                result=json.loads(messages[-1]["content"].split(": ",1)[1])["result"]
                return {"summary":"Repair addition","tool":"file_patch","arguments":{"path":"calc.py","expected_sha256":result["sha256"],"old_text":"return a - b","new_text":"return a + b"}},{}
            if actions==3:return {"summary":"Check repair","tool":"verify","arguments":{}},{}
            return {"summary":"Finish repair","tool":"finish","arguments":{}},{}
        m=Manager(self.base/"runs",inference=inference)
        stopped=m.start("Fix the addition function",source=self.source,project_profile="generic",
            test_commands=[["python3","-c","from calc import add; assert add(3,2)==5"]],background=False)
        self.assertEqual(stopped["status"],"needs_attention")
        workspace=m._dir(stopped["id"])/"workspace";self.assertTrue(workspace.is_dir())
        failing=False
        resumed=m.resume(stopped["id"],background=False)
        self.assertEqual(resumed["status"],"completed",resumed["message"])
        self.assertEqual(resumed["resume_count"],1);self.assertEqual(plan_calls,1)
        self.assertIn("a + b",(workspace/"calc.py").read_text())
        self.assertTrue(any(e["kind"]=="resuming" for e in m.events(stopped["id"])))
        with self.assertRaisesRegex(ValueError,"Only a task that needs attention"):
            m.resume(stopped["id"],background=False)

    def test_auto_solve_retries_until_recovery_passes(self):
        action_calls=0
        def inference(messages,schema,*args):
            nonlocal action_calls
            if "objective" in schema["properties"]:
                return {"objective":"Fix addition","steps":["Inspect","Repair","Check"],"acceptance":["Addition works"]},{}
            if "approved" in schema["properties"]:return {"approved":True,"findings":[]},{}
            action_calls+=1
            if action_calls<=2:return {"summary":"Blocked attempt","tool":"stop","arguments":{"reason":"Recoverable temporary failure"}},{}
            if action_calls==3:return {"summary":"Read calculator","tool":"read_file","arguments":{"path":"calc.py"}},{}
            if action_calls==4:
                result=json.loads(messages[-1]["content"].split(": ",1)[1])["result"]
                return {"summary":"Repair addition","tool":"file_patch","arguments":{"path":"calc.py","expected_sha256":result["sha256"],"old_text":"return a - b","new_text":"return a + b"}},{}
            if action_calls==5:return {"summary":"Check repair","tool":"verify","arguments":{}},{}
            return {"summary":"Finish repair","tool":"finish","arguments":{}},{}
        m=Manager(self.base/"runs",inference=inference)
        stopped=m.start("Fix the addition function",source=self.source,project_profile="generic",
            test_commands=[["python3","-c","from calc import add; assert add(3,2)==5"]],background=False)
        self.assertEqual(stopped["status"],"needs_attention")
        m.resume(stopped["id"],auto=True)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            state=m.get(stopped["id"])
            if state["status"]=="completed":break
            time.sleep(.02)
        self.assertEqual(state["status"],"completed",state["message"])
        self.assertEqual(state["resume_count"],2);self.assertFalse(state["auto_solve"])
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
