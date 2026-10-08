import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from local_coder.parallel import AdvisoryHelpers, RevisionChecks, revision
from local_coder.project import inventory
from local_coder import gpu_policy
from local_coder.controller import Manager, atomic_json


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source/'calc.py').write_text('def add(a,b):\n    return a - b\n')
        self.flag = threading.Event()
        self.deadline = time.monotonic()+30

    def tearDown(self):
        self.tmp.cleanup()

    def checker(self, commands=()):
        return RevisionChecks(self.root/'checks', self.flag, self.deadline, {}, 'generic', list(commands), {})

    def test_checks_reject_old_passing_revision_and_check_new_source(self):
        worker=self.checker([['python3','-c','from calc import add; assert add(3,2)==1']])
        try:
            old=worker.request(self.source,['calc.py'])
            self.assertTrue(old['future'].result(timeout=10)['ok'])
            (self.source/'calc.py').write_text('def add(a,b):\n    return a + b\n')
            self.assertIsNone(worker.ready(self.source),'Old passing report approved newer files')
            new=worker.request(self.source,['calc.py'])
            report=new['future'].result(timeout=10)
            self.assertFalse(report['ok'])
            self.assertNotEqual(old['revision'],new['revision'])
            self.assertEqual(report['revision'],revision(inventory(self.source)))
            self.assertFalse(new['path'].exists(),'Completed check snapshot was not cleaned up')
        finally:worker.close()

    def test_checks_cannot_edit_and_cancel_stops_inflight_command(self):
        worker=self.checker([['python3','-c',"open('calc.py','w').write('broken')"]])
        try:
            report=worker.wait(self.source,['calc.py'],lambda:None)
            self.assertFalse(report['ok'])
            self.assertIn('Read-only',report['task_tests'][0]['stderr'])
            self.assertIn('a - b',(self.source/'calc.py').read_text())
        finally:worker.close()
        self.flag.clear()
        worker=self.checker([['python3','-c','import time; time.sleep(20)']])
        job=worker.request(self.source,['calc.py'])
        time.sleep(.4);start=time.monotonic();self.flag.set();worker.close()
        self.assertLess(time.monotonic()-start,3)
        self.assertFalse(job['future'].result()['ok'])

    def test_single_advisory_worker_and_bounded_requests(self):
        lock=threading.Lock();active=0;peak=0;calls=[]
        def infer(messages,schema,profile,flag,deadline,limit,progress):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            calls.append((schema,profile,limit));time.sleep(.08)
            with lock:active-=1
            return {'findings':['Test addition with negative numbers']},{'model':'tiny'}
        helper=AdvisoryHelpers(infer,self.flag,self.deadline)
        try:
            for _ in range(7):helper.submit('Test assistant','Fix calc addition',self.source)
            self.assertEqual(len(helper.jobs),4)
            for future in helper.jobs:future.result(timeout=5)
            self.assertEqual(peak,1)
            self.assertTrue(all(profile=='_helper' and limit==512 and 'tool' not in schema['properties'] for schema,profile,limit in calls))
            self.assertIn('a - b',(self.source/'calc.py').read_text())
        finally:helper.close()

    def test_failed_helper_does_not_retry_or_abort_builder(self):
        def fail(*args):raise RuntimeError('GTX unavailable')
        helper=AdvisoryHelpers(fail,self.flag,self.deadline)
        helper.submit('Scout','Fix addition',self.source)
        helper.jobs[0].result(timeout=5)
        helper.submit('Reviewer','Fix addition',self.source)
        self.assertEqual(len(helper.jobs),1)
        self.assertFalse(self.flag.is_set(),'Helper failure cancelled the builder')
        helper.close()

    def test_builder_runs_while_helper_and_actual_checks_are_busy(self):
        started=threading.Event();builder_progress=threading.Event();calls=0
        def helper(*args):
            started.set()
            if not builder_progress.wait(5):raise RuntimeError('Builder did not run concurrently')
            return {'findings':['Check addition result']},{'model':'2B'}
        def builder(messages,schema,profile,flag,deadline,limit,progress):
            nonlocal calls
            if 'objective' in schema['properties']:
                self.assertTrue(started.wait(3));builder_progress.set()
                return {'objective':'Fix addition','steps':['Read','Patch','Test'],'acceptance':[]},{}
            if 'approved' in schema['properties']:return {'approved':True,'findings':[]},{}
            calls+=1
            if calls==1:return {'summary':'Read','tool':'read_file','arguments':{'path':'calc.py'}},{}
            if calls==2:
                sha=json.loads(messages[-1]['content'].split(': ',1)[1])['result']['sha256']
                return {'summary':'Fix','tool':'file_patch','arguments':{'path':'calc.py','expected_sha256':sha,'old_text':'a - b','new_text':'a + b'}},{}
            return {'summary':'Done','tool':'finish','arguments':{}},{}
        manager=Manager(self.root/'runs',inference=builder,helper_inference=helper)
        result=manager.start('Fix calc addition',source=self.source,background=False,
            test_commands=[['python3','-c','from calc import add; assert add(3,2)==5']])
        self.assertEqual(result['status'],'completed',result['message'])
        self.assertEqual(result['validation']['revision'],revision(result['validated_inventory']))
        events=manager.events(result['id'])
        self.assertTrue(any(e['lane']=='helper' for e in events))
        self.assertTrue(any(e['lane']=='checks' for e in events))
        self.assertIn('a - b',(self.source/'calc.py').read_text(),'Task edited the live source')
        result['cleanup_complete']=False
        atomic_json(manager._dir(result['id'])/'state.json',result)
        with self.assertRaisesRegex(ValueError,'still finishing'):manager.apply(result['id'])
        self.assertIn('a - b',(self.source/'calc.py').read_text())

    def test_gtx_reservation_keeps_rx_service_running(self):
        status={'mode':'rx6600-helper'}
        with patch.object(gpu_policy,'DATA_ROOT',self.root),patch.object(gpu_policy,'RESERVED',self.root/'reserved'),\
             patch.object(gpu_policy,'current',return_value=status),patch.object(gpu_policy.subprocess,'run') as run:
            response=gpu_policy.reserve()
            self.assertFalse(response['inference_stopped'])
            self.assertEqual(run.call_args.args[0],['systemctl','--user','stop','local-coder-helper.service'])
            self.assertTrue((self.root/'reserved').exists())

    def test_builder_signature_does_not_depend_on_vm_ownership(self):
        base={'vulkan_devices':[{'vendor':'0x1002','name':'RX 6600','index':0},
                               {'vendor':'0x10de','name':'GTX 1050 Ti','index':1}],
              'nvidia_reserved':False,'nvidia_vfio':False}
        before=gpu_policy.builder_policy(base)
        after=gpu_policy.builder_policy({**base,'nvidia_reserved':True})
        self.assertEqual(before['signature'],after['signature'])
        self.assertEqual(before['selected_indices'],[0])
        self.assertEqual(after['helper_indices'],[])

    def test_inference_services_share_one_16g_slice(self):
        root=Path(__file__).resolve().parents[1]/'config/systemd'
        for unit in ['local-coder-ollama.service','local-coder-helper.service']:
            self.assertIn('Slice=local-coder-inference.slice',(root/unit).read_text())
        self.assertIn('MemoryMax=16G',(root/'local-coder-inference.slice').read_text())
        self.assertIn('MemorySwapMax=0',(root/'local-coder-inference.slice').read_text())
