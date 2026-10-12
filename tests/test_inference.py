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
        self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.end_headers()
        self.server.headers_sent.set()
        self.server.release.wait(3)
        try:
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
