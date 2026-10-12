import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import io
from PIL import Image
from unittest.mock import patch
from local_coder.chat import Chats,SYSTEM,fit_synthesis_context
from local_coder.search import public_url,relevant,search

class ChatTests(unittest.TestCase):
    def wait(self,c):
        c.worker.join(3);self.assertFalse(c.worker.is_alive())
    def test_local_followup_retains_context_and_never_searches(self):
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            def infer(messages,deep,flag,deadline,progress):
                calls.append(messages);progress({'answer':'partial','elapsed_seconds':1,'thinking_characters':10})
                return 'Eigenvalues are 1 and 3.',{'truncated':False}
            c=Chats(Path(d)/'chats',infer,lambda *_:self.fail('Offline chat searched the web'))
            s=c.start('Explain this matrix',deep=True);self.wait(c);s=c.get(s['id'])
            self.assertEqual(s['status'],'idle');self.assertEqual(len(s['messages']),2)
            c.start('Explain the second eigenvalue',id=s['id'],deep=False);self.wait(c)
            self.assertEqual(len(calls[-1]),4);self.assertIn('Eigenvalues',calls[-1][2]['content'])
            self.assertEqual(c.get(s['id'])['history_pairs_used'],1)
            self.assertIn('untrusted',SYSTEM)

    def test_structured_answer_decomposes_solves_and_synthesizes_with_7b_route(self):
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            def infer(messages,deep,flag,deadline,progress):
                calls.append(messages);system=messages[0]['content']
                if 'Create an answer roadmap' in system:
                    return json.dumps({'goal':'Explain the combined training design','subproblems':[
                        {'question':'What should supervised training teach?','purpose':'Define core behavior'},
                        {'question':'What should preferences improve?','purpose':'Define ranking behavior'}],
                        'final_checks':['Connect both stages']}),{}
                if 'Solve exactly one bounded subproblem' in system:
                    part='Supervised training teaches demonstrations.' if 'supervised' in messages[-1]['content'].lower() else 'Preferences rank better answers.'
                    return json.dumps({'answer':part,'limitations':[]}),{}
                if 'Synthesize one coherent final answer' in system:
                    return json.dumps({'answer':'Use supervised examples first, then preference pairs to improve answer selection.','covered':[1,2]}),{}
                self.fail('Unexpected direct generation')
            c=Chats(Path(d)/'chats',infer)
            s=c.start('Explain how supervised training and preference tuning should work together in Lumina',
                deep=True,structured=True);self.wait(c);result=c.get(s['id'])
            self.assertEqual(result['status'],'idle',result['message'])
            self.assertEqual(result['route']['choice'],'structured')
            self.assertEqual(len(calls),4)
            answer=result['messages'][-1]
            self.assertEqual(answer['generation']['workflow'],'decompose-solve-synthesize')
            self.assertEqual(answer['answer_plan']['covered'],[1,2])
            self.assertTrue(all(part['status']=='done' for part in answer['answer_plan']['subproblems']))
            self.assertIn('preference pairs',answer['content'])

    def test_structured_answer_bypasses_short_greeting(self):
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            def infer(messages,*args):calls.append(messages);return 'Hello!',{}
            c=Chats(Path(d)/'chats',infer);s=c.start('Hello there',deep=True,structured=True);self.wait(c)
            result=c.get(s['id']);self.assertEqual(result['route']['choice'],'study')
            self.assertEqual(result['messages'][-1]['generation']['workflow'],'direct')
            self.assertEqual(len(calls),1)

    def test_synthesis_keeps_all_parts_inside_a_small_context_window(self):
        messages=[{'role':'system','content':'Combine the results.'},{'role':'user','content':'Explain the topic.'}]
        packet={'goal':'Explain','final_checks':['Cover every part'],
            'subproblem_results':[{'part':i,'question':f'Part {i}','purpose':'Explain',
                'answer':'evidence '*300,'limitations':[]} for i in range(1,6)]}
        def count(items,*_):return sum(len(item['content']) for item in items)
        with patch('local_coder.chat.estimate',side_effect=count):
            fitted,compact=fit_synthesis_context(messages,packet,'roadmap',2100)
        self.assertLessEqual(count(fitted),2100)
        self.assertEqual([part['part'] for part in compact['subproblem_results']],[1,2,3,4,5])
        self.assertTrue(all(part['answer'] for part in compact['subproblem_results']))
        self.assertEqual(len(packet['subproblem_results'][0]['answer']),2700)
    def test_live_activity_records_phases_but_no_private_thinking(self):
        with tempfile.TemporaryDirectory() as d:
            ready=threading.Event();release=threading.Event()
            def infer(messages,deep,flag,deadline,progress):
                progress({'answer':'','thinking_characters':20});ready.set();release.wait(2)
                progress({'answer':'Hello','thinking_characters':20});return 'Hello there.',{}
            c=Chats(Path(d)/'chats',infer);s=c.start('Hello there',deep=False)
            self.assertTrue(ready.wait(1));live=c.get(s['id'])
            self.assertNotIn(live['status'],{'idle','failed','cancelled'})
            self.assertEqual(live['route']['choice'],'fast');self.assertIsNone(live['finished_at'])
            self.assertEqual(live['generation_phase'],'thinking')
            release.set();self.wait(c);result=c.get(s['id'])
            self.assertEqual(result['status'],'idle');self.assertIsNotNone(result['finished_at'])
            self.assertGreaterEqual(result['elapsed_seconds'],0)
            events=result['messages'][-1]['work']['activity']
            self.assertEqual(events[0]['message'],'Received your question')
            self.assertEqual(events[-1]['phase'],'idle')
            self.assertIn('Writing your answer',[event['message'] for event in events])
            self.assertNotIn('thinking_characters',json.dumps(events))
            c.start('Continue',id=s['id'],model='study');self.wait(c)
            self.assertEqual(c.get(s['id'])['messages'][1]['work']['activity'],events)
    def test_document_passages_reach_tutor_and_remain_available_for_followups(self):
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            def infer(messages,*args):calls.append(messages);return 'The constant is 37.5 volts [F1: Lines 1–1].',{}
            c=Chats(Path(d)/'chats',infer)
            file=c.files.save(b'The calibration constant is 37.5 volts.','lecture.txt')
            s=c.start('Hello, explain this file',deep=False,attachments=[file['id']]);self.wait(c)
            result=c.get(s['id']);self.assertEqual(result['status'],'idle')
            self.assertEqual(result['route']['choice'],'study');self.assertIn('37.5',calls[0][-1]['content'])
            self.assertIn('untrusted data',calls[0][-1]['content']);self.assertTrue(result['messages'][-1]['file_passages'])
            c.start('What units does that constant use?',id=s['id'],deep=False);self.wait(c)
            self.assertIn('37.5',calls[-1][-1]['content']);self.assertEqual(c.get(s['id'])['status'],'idle')
    def test_web_sources_are_supplied_and_persisted_without_shell_tools(self):
        with tempfile.TemporaryDirectory() as d:
            seen=[]
            def infer(messages,*args):seen.append(messages);return 'Read MIT [1].',{}
            source={'title':'MIT notes','url':'https://ocw.mit.edu/course','snippet':'Eigenvalues are roots of a polynomial','engines':['yahoo']}
            c=Chats(Path(d)/'chats',infer,lambda *_:{'results':[source],'warnings':['Google unavailable']})
            with patch('local_coder.chat.ollama.complete',return_value=({'queries':['MIT eigenvalue lecture']},{})):
                s=c.start('Find MIT eigenvalue lectures',web=True);self.wait(c)
            result=c.get(s['id']);self.assertEqual(result['status'],'idle')
            self.assertEqual(result['messages'][-1]['sources'],[source]);self.assertIn('Google unavailable',result['warnings'])
            self.assertIn('Search snippets',seen[0][-1]['content']);self.assertIn('no file-editing or shell tools',seen[0][0]['content'])
    def test_cancellation_and_repeated_empty_output_are_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            attempts=[]
            def empty(*args):attempts.append(1);return '',{'truncated':True}
            c=Chats(Path(d)/'chats',empty);s=c.start('Question here');self.wait(c)
            self.assertEqual(len(attempts),2);self.assertEqual(c.get(s['id'])['status'],'failed')
            failed=c.get(s['id']);self.assertEqual(failed['messages'][-1]['failed_work']['status'],'failed')
            self.assertIsNotNone(failed['finished_at'])
            ready=threading.Event()
            def blocked(messages,deep,flag,*args):ready.set();flag.wait(2);raise ValueError('Cancelled')
            c.inference=blocked;s=c.start('Another question');self.assertTrue(ready.wait(1));c.cancel(s['id']);self.wait(c)
            self.assertEqual(c.get(s['id'])['status'],'cancelled')
            self.assertEqual(c.get(s['id'])['messages'][-1]['failed_work']['status'],'cancelled')
    def test_invalid_inputs_and_restart_preserve_conversation(self):
        with tempfile.TemporaryDirectory() as d:
            c=Chats(Path(d)/'chats',lambda *_:('Answer',{}))
            for args in [{'text':'x'},{'text':'valid question','deep':'yes'},{'text':'valid question','attachments':['../escape']}]:
                with self.assertRaises(ValueError):c.start(**args)
            s=c.start('Valid question');self.wait(c);s=c.get(s['id']);s['status']='answering';s['started_at']=time.time()-70;c.save(s)
            restarted=Chats(Path(d)/'chats',lambda *_:('Answer',{}))
            recovered=restarted.get(s['id'])
            self.assertEqual(recovered['status'],'failed');self.assertEqual(len(restarted.list()),1)
            self.assertGreaterEqual(recovered['elapsed_seconds'],70)
            self.assertEqual(recovered['messages'][-1]['work']['activity'][-1]['phase'],'failed')
    def test_search_rejects_private_links_and_unrelated_results(self):
        for url in ['http://localhost/','http://127.0.0.1/','http://169.254.169.254/','file:///etc/passwd','https://x@y.com/','javascript:alert(1)','http://router.local/']:
            self.assertFalse(public_url(url),url)
        self.assertTrue(public_url('https://ocw.mit.edu/courses'))
        self.assertFalse(relevant('MIT eigenvalues lecture',{'title':'Popular quotes','snippet':'Goodreads quotes','url':'https://goodreads.com'}))
        self.assertTrue(relevant('MIT eigenvalues lecture',{'title':'MIT eigenvalues lecture','snippet':'Course notes','url':'https://ocw.mit.edu'}))
    def test_study_image_is_read_then_unloaded_and_retained_for_followups(self):
        with tempfile.TemporaryDirectory() as d:
            order=[];calls=[]
            def infer(messages,*args):order.append('chat');calls.append(messages);return 'The equation is x + 1 = 2.',{}
            c=Chats(Path(d)/'chats',infer);buf=io.BytesIO();Image.new('RGB',(30,20),'white').save(buf,format='PNG')
            image=c.images.save(buf.getvalue(),'lecture.png')
            def vision(messages,*args):
                order.append('vision');self.assertIn('university study material',messages[0]['content'])
                return {'description':'Lecture exercise','visible_text':['x + 1 = 2'],'design_details':[],'uncertainties':[]},{}
            with patch('local_coder.chat.ollama.complete',side_effect=vision),patch('local_coder.chat.ollama.unload',side_effect=lambda *_:order.append('unload')):
                s=c.start('Explain this equation',attachments=[image['id']]);self.wait(c)
            self.assertEqual(order,['vision','unload','chat']);self.assertIn('x + 1 = 2',calls[0][-1]['content'])
            self.assertFalse(any('images' in m for m in calls[0]))
            c.start('What is its solution?',id=s['id']);self.wait(c)
            self.assertIn('x + 1 = 2',calls[-1][1]['content'])
