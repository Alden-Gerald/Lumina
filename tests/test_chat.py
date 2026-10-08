import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import io
from PIL import Image
from unittest.mock import patch
from local_coder.chat import Chats,SYSTEM
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
            ready=threading.Event()
            def blocked(messages,deep,flag,*args):ready.set();flag.wait(2);raise ValueError('Cancelled')
            c.inference=blocked;s=c.start('Another question');self.assertTrue(ready.wait(1));c.cancel(s['id']);self.wait(c)
            self.assertEqual(c.get(s['id'])['status'],'cancelled')
    def test_invalid_inputs_and_restart_preserve_conversation(self):
        with tempfile.TemporaryDirectory() as d:
            c=Chats(Path(d)/'chats',lambda *_:('Answer',{}))
            for args in [{'text':'x'},{'text':'valid question','deep':'yes'},{'text':'valid question','attachments':['../escape']}]:
                with self.assertRaises(ValueError):c.start(**args)
            s=c.start('Valid question');self.wait(c);s=c.get(s['id']);s['status']='answering';c.save(s)
            restarted=Chats(Path(d)/'chats',lambda *_:('Answer',{}))
            self.assertEqual(restarted.get(s['id'])['status'],'failed');self.assertEqual(len(restarted.list()),1)
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
