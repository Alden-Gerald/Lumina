from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import queue
import threading
import time
import unittest
from unittest.mock import patch
from local_coder import ollama

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        self.server.payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.end_headers()
        self.server.headers_sent.set()
        self.server.release.wait(3)
        try:
            if getattr(self.server,'thinking',False):self.wfile.write((json.dumps({'message':{'thinking':'Private test reasoning'}})+'\n').encode())
            self.wfile.write((json.dumps({'message':{'content':'{"answer":42}'}})+'\n'+
                json.dumps({'done':True,'done_reason':self.server.reason,'eval_count':5})+'\n').encode())
            self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):pass

class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.server.reason='stop';self.server.headers_sent=threading.Event();self.server.release=threading.Event()
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.address=patch('local_coder.ollama.OLLAMA_URL',f'http://127.0.0.1:{self.server.server_address[1]}');self.address.start()
    def tearDown(self):
        self.server.release.set();self.server.shutdown();self.server.server_close();self.thread.join();self.address.stop()
    def call(self,flag=None):
        return ollama.complete([{'role':'user','content':'Return a number'}],{'type':'object'},'power',flag,time.monotonic()+5)
    def test_complete_and_truncated_json_responses(self):
        self.server.release.set()
        result,metrics=self.call();self.assertEqual(result,{'answer':42})
        self.server.reason='length'
        with self.assertRaisesRegex(ollama.InferenceError,'Output limit'):self.call()
    def test_cancel_interrupts_wait_before_first_generated_token(self):
        flag=threading.Event();out=queue.Queue()
        def worker():
            try:self.call(flag)
            except Exception as exc:out.put(exc)
        thread=threading.Thread(target=worker,daemon=True);thread.start()
        self.assertTrue(self.server.headers_sent.wait(2))
        started=time.monotonic();flag.set();thread.join(1.5)
        self.assertFalse(thread.is_alive(),'Cancellation remained blocked on model output')
        self.assertLess(time.monotonic()-started,1.5)
        self.assertIsInstance(out.get(),ollama.InferenceError)
    def test_chat_accepts_bounded_thinking_without_returning_its_transcript(self):
        self.server.thinking=True;self.server.release.set()
        with patch('local_coder.gpu_policy.current',return_value={'mode':'rx-only'}):
            answer,metrics=ollama.chat([{'role':'user','content':'Compute 6 times 7'}],True,deadline=time.monotonic()+5)
        self.assertEqual(answer,'{"answer":42}');self.assertNotIn('Private',str(metrics)+answer)
        self.assertEqual(self.server.payload['options']['num_predict'],4096)
        self.assertEqual(self.server.payload['options']['num_gpu'],24)
        self.assertEqual(self.server.payload['options']['num_ctx'],16384)
        self.assertTrue(self.server.payload['think'])
        with self.assertRaisesRegex(ollama.InferenceError,'Unexpected thinking'):self.call()
    def test_chat_model_override_keeps_profile_context_and_gpu_limits(self):
        self.server.release.set()
        with patch('local_coder.gpu_policy.current',return_value={'mode':'dual-vulkan'}):
            answer,metrics=ollama.chat([{'role':'user','content':'Hello'}],False,deadline=time.monotonic()+5,profile='_chat_fast')
        self.assertEqual(self.server.payload['model'],'qwen3.5:4b')
        self.assertEqual(self.server.payload['options']['num_ctx'],8192)
        self.assertEqual(self.server.payload['options']['num_gpu'],16)
        self.assertEqual(self.server.payload['options']['num_predict'],2048)
        self.assertFalse(self.server.payload['think'])
