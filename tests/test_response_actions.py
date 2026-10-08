import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from local_coder.chat import Chats, SYSTEM
from local_coder.settings import PROFILES


class ResponseTests(unittest.TestCase):
    def wait(self,c):
        c.worker.join(3);self.assertFalse(c.worker.is_alive())

    def test_feedback_is_persistent_exact_and_clearable_without_training(self):
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            def infer(messages,*args):calls.append(copy.deepcopy(messages));return 'A checkable answer.',{'options':{'num_gpu':16}}
            c=Chats(Path(d)/'chats',infer);s=c.start('Explain voltage',deep=False,model='fast');self.wait(c)
            s=c.get(s['id']);m=s['messages'][-1]
            c.feedback(s['id'],m['id'],'down','Include units.')
            restarted=Chats(c.root,infer)
            record=restarted.export_feedback(s['id'],m['id'])
            self.assertEqual(record['messages'],calls[-1]);self.assertTrue(record['context_complete'])
            self.assertEqual(record['feedback']['note'],'Include units.')
            self.assertEqual(record['generation']['options']['num_gpu'],16)
            self.assertEqual(len(calls),1);self.assertEqual(record['answer'],m['content'])
            c.feedback(s['id'],m['id'],None)
            self.assertNotIn('feedback',c.get(s['id'])['messages'][-1])
            with self.assertRaises(ValueError):c.export_feedback(s['id'],m['id'])
            for args in [(m['id'],'bad',''),(m['id'],'up','x'*2001),('unknown','up','')]:
                with self.assertRaises(ValueError):c.feedback(s['id'],*args)

    def test_redo_keeps_original_and_files_but_excludes_original_answer_and_future(self):
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            def infer(messages,*args):calls.append(messages);return 'ORIGINAL answer.' if len(calls)==1 else 'Revised answer.',{}
            c=Chats(Path(d)/'chats',infer);file=c.files.save(b'Calibration voltage is 37.5 volts.','lecture.txt')
            s=c.start('What is the calibration voltage?',attachments=[file['id']],model='fast',deep=False);self.wait(c)
            original=c.get(s['id']);response=original['messages'][-1]
            c.feedback(s['id'],response['id'],'down','Explain the unit.')
            c.start('Future follow-up must not appear in earlier retry',id=s['id'],model='fast',deep=False);self.wait(c)
            before=c.get(s['id'])
            redo=c.branch(s['id'],response['id'],redo=True,model='fast',deep=False,web=False);self.wait(c)
            revised=c.get(redo['id']);self.assertEqual(revised['status'],'idle')
            text=json.dumps(calls[-1]);self.assertIn('37.5',text);self.assertIn('Explain the unit.',text)
            self.assertNotIn('ORIGINAL answer.',text);self.assertNotIn('Future follow-up',text)
            self.assertEqual(c.get(s['id']),before)
            self.assertEqual(revised['parent']['message_id'],response['id'])
            self.assertEqual(revised['messages'][0]['attachments'][0]['id'],file['id'])
            self.assertNotEqual(revised['messages'][-1]['id'],response['id'])
            self.assertNotIn('feedback',revised['messages'][-1])
            c.start('New unrelated follow-up',id=redo['id'],model='fast',deep=False);self.wait(c)
            self.assertNotIn('User feedback for this retry',calls[-1][-1]['content'])

    def test_branch_is_independent_and_failed_redo_preserves_original(self):
        with tempfile.TemporaryDirectory() as d:
            c=Chats(Path(d)/'chats',lambda *_:('Saved answer.',{}));s=c.start('Original question');self.wait(c)
            original=c.get(s['id']);response=original['messages'][-1]
            branch=c.branch(s['id'],response['id']);self.assertEqual(len(branch['messages']),2)
            self.assertEqual(branch['messages'][-1]['content'],'Saved answer.')
            c.feedback(branch['id'],branch['messages'][-1]['id'],'up')
            self.assertNotIn('feedback',c.get(s['id'])['messages'][-1])
            c.inference=lambda *_:('',{})
            retry=c.branch(s['id'],response['id'],redo=True);self.wait(c)
            self.assertEqual(c.get(retry['id'])['status'],'failed');self.assertEqual(c.get(s['id']),original)

    def test_active_feedback_and_redo_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            c=Chats(Path(d)/'chats',lambda *_:('Answer.',{}));s=c.start('Question here');self.wait(c)
            original=c.get(s['id']);response=original['messages'][-1];ready=threading.Event();release=threading.Event()
            def infer(*args):ready.set();release.wait(2);return 'New answer.',{}
            c.inference=infer;c.start('Follow up here',id=s['id']);self.assertTrue(ready.wait(1))
            try:
                with self.assertRaises(ValueError):c.feedback(s['id'],response['id'],'up')
                with self.assertRaises(ValueError):c.branch(s['id'],response['id'],redo=True)
            finally:release.set();self.wait(c)

    def test_legacy_ids_are_stable_and_export_does_not_invent_context(self):
        with tempfile.TemporaryDirectory() as d:
            c=Chats(Path(d)/'chats',lambda *_:('Old answer.',{}));s=c.start('Old question');self.wait(c);s=c.get(s['id'])
            for m in s['messages']:m.pop('id',None);m.pop('request_context',None);m.pop('generation',None)
            c.save(s);s=c.get(s['id']);id=s['messages'][-1]['id']
            self.assertEqual(c.get(s['id'])['messages'][-1]['id'],id)
            c.feedback(s['id'],id,'up');record=c.export_feedback(s['id'],id)
            self.assertFalse(record['context_complete']);self.assertIsNone(record['messages'])

    def test_optimization_fits_budget_and_preserves_full_saved_history(self):
        with tempfile.TemporaryDirectory() as d:
            c=Chats(Path(d)/'chats',lambda *_:('Answer.',{}));s=c.start('Initial question');self.wait(c);s=c.get(s['id'])
            s['messages']=[]
            for i in range(10):
                s['messages'].extend([{'role':'user','id':f'u{i}','content':f'Voltage question {i}: '+'background '*170},
                    {'role':'assistant','id':f'a{i}','content':f'Voltage is measured in volts, exchange {i}.\n'+'explanation '*170}])
            s['messages'].append({'role':'user','id':'latest','content':'What unit measures voltage?'})
            s['route']={'profile':'_chat_fast'};saved=copy.deepcopy(s['messages'])
            def count(messages,*_):return 100+sum(len(m['content'])//4 for m in messages)
            cfg={**PROFILES['_chat_fast'],'num_ctx':6500}
            with patch.dict(PROFILES,{'_chat_fast':cfg}),patch('local_coder.chat.estimate',side_effect=count):
                messages=c.context(s,'')
                self.assertLessEqual(count(messages),1500)
            self.assertEqual(s['messages'],saved);self.assertEqual(messages[0]['content'],SYSTEM)
            self.assertEqual(messages[-1]['content'],'What unit measures voltage?')
            self.assertTrue(s['optimization']['memory']);self.assertIn('volts',s['optimization']['memory'])
            self.assertTrue(any(e['phase']=='optimizing' for e in s['activity']))
            self.assertGreater(s['optimization']['older_exchanges'],0)

    def test_oversized_latest_question_fails_without_erasing_history(self):
        with tempfile.TemporaryDirectory() as d:
            c=Chats(Path(d)/'chats',lambda *_:('Answer.',{}));s=c.start('Small question');self.wait(c);s=c.get(s['id'])
            s['messages'].append({'role':'user','content':'x'*20000});saved=copy.deepcopy(s['messages'])
            with patch('local_coder.chat.estimate',return_value=999999):
                with self.assertRaises(ValueError):c.context(s,'')
            self.assertEqual(s['messages'],saved)
