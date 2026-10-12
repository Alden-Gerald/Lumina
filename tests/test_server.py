import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock
import urllib.request
import urllib.error
from local_coder.server import Server
from PIL import Image
import io

class ServerTests(unittest.TestCase):
    def test_response_downloads_contain_exact_answer_and_feedback_context(self):
        with tempfile.TemporaryDirectory() as d,patch('local_coder.server.DATA_ROOT',Path(d)),patch('local_coder.server.Manager'):
            server=Server(('127.0.0.1',0));server.chats.inference=lambda *_:('Voltage is measured in volts.',{})
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_address[1]}';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                s=server.chats.start('Name the voltage unit',model='fast',deep=False);server.chats.worker.join(3)
                s=server.chats.get(s['id']);m=s['messages'][-1]
                prefix=base+'/api/chats/'+s['id']+'/responses/'+m['id']+'/'
                with opener.open(prefix+'response.md',timeout=3) as r:
                    self.assertEqual(r.read().decode(),m['content']);self.assertIn('attachment;',r.headers['Content-Disposition'])
                with self.assertRaises(urllib.error.HTTPError) as e:opener.open(prefix+'feedback.json',timeout=3)
                self.assertEqual(e.exception.code,400);e.exception.close()
                server.chats.feedback(s['id'],m['id'],'up','UI test record')
                with opener.open(prefix+'feedback.json',timeout=3) as r:
                    record=json.load(r);self.assertEqual(record['feedback']['rating'],'up')
                    self.assertEqual(record['messages'],m['request_context']);self.assertTrue(record['context_complete'])
                    self.assertEqual(r.headers.get_content_type(),'application/octet-stream');self.assertIn('.json',r.headers['Content-Disposition'])
            finally:server.shutdown();server.server_close();thread.join()

    def test_chat_and_code_share_one_inference_slot(self):
        with tempfile.TemporaryDirectory() as d, patch('local_coder.server.DATA_ROOT',Path(d)), patch('local_coder.server.Manager') as manager, patch('local_coder.server.Chats') as chats:
            server=Server(('127.0.0.1',0));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));base=f'http://127.0.0.1:{server.server_address[1]}'
            def post(path,data):
                req=urllib.request.Request(base+path,json.dumps(data).encode(),{'Content-Type':'application/json','X-Local-Coder-Token':server.token})
                return opener.open(req,timeout=3)
            try:
                manager.return_value.worker.is_alive.return_value=True
                with self.assertRaises(urllib.error.HTTPError) as e:post('/api/chats',{'text':'Study question'})
                self.assertEqual(e.exception.code,400);e.exception.close();chats.return_value.start.assert_not_called()
                with self.assertRaises(urllib.error.HTTPError) as e:post('/api/chats/'+'a'*32+'/redo',{'message_id':'b'*32})
                self.assertEqual(e.exception.code,400);e.exception.close();chats.return_value.branch.assert_not_called()
                manager.return_value.worker=None;chats.return_value.worker.is_alive.return_value=True
                with self.assertRaises(urllib.error.HTTPError) as e:post('/api/runs',{'task':'Build feature'})
                self.assertEqual(e.exception.code,400);e.exception.close();manager.return_value.start.assert_not_called()
                chats.return_value.worker=None;chats.return_value.start.return_value={'id':'a'*32}
                with post('/api/chats',{'text':'Study question','web':False}) as r:self.assertEqual(r.status,202)
                chats.return_value.start.assert_called_once_with(text='Study question',web=False)
                chats.return_value.branch.return_value={'id':'c'*32}
                with post('/api/chats/'+'a'*32+'/redo',{'message_id':'b'*32,'model':'fast','deep':False,'web':False}) as r:self.assertEqual(r.status,202)
                chats.return_value.branch.assert_called_once_with('a'*32,redo=True,message_id='b'*32,model='fast',deep=False,web=False)
                with self.assertRaises(urllib.error.HTTPError) as e:post('/api/chats/'+'a'*32+'/feedback',{'message_id':'b'*32,'rating':'up','extra':True})
                self.assertEqual(e.exception.code,400);e.exception.close();chats.return_value.feedback.assert_not_called()
            finally:server.shutdown();server.server_close();thread.join()
    def test_authenticated_upload_preview_and_invalid_file(self):
        with tempfile.TemporaryDirectory() as d, patch('local_coder.server.DATA_ROOT',Path(d)), patch('local_coder.server.Manager'):
            server=Server(('127.0.0.1',0));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_address[1]}'
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            buf=io.BytesIO();Image.new('RGB',(40,20),'blue').save(buf,format='PNG')
            try:
                request=urllib.request.Request(base+'/api/attachments',buf.getvalue(),{'X-Local-Coder-Token':server.token,'X-Upload-Name':'picture.png','Content-Type':'image/png'})
                with opener.open(request,timeout=3) as r:metadata=json.load(r);self.assertEqual(r.status,201)
                with opener.open(base+metadata['url'],timeout=3) as r:self.assertEqual(r.headers.get_content_type(),'image/jpeg');self.assertTrue(r.read().startswith(b'\xff\xd8'))
                invalid=urllib.request.Request(base+'/api/attachments',b'bad',{'X-Local-Coder-Token':server.token})
                with self.assertRaises(urllib.error.HTTPError) as error:opener.open(invalid,timeout=3)
                self.assertEqual(error.exception.code,400);error.exception.close()
            finally:server.shutdown();server.server_close();thread.join()
    def test_host_origin_and_csrf_guards_prevent_task_execution(self):
        with tempfile.TemporaryDirectory() as d, patch('local_coder.server.DATA_ROOT',Path(d)), patch('local_coder.server.Manager') as manager:
            server=Server(('127.0.0.1',0))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url=f'http://127.0.0.1:{server.server_address[1]}/api/runs'
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                for headers,expected in [({},403),({'Host':'evil.example'},400),
                    ({'X-Local-Coder-Token':server.token,'Origin':'http://evil.example'},400)]:
                    req=urllib.request.Request(url,json.dumps({'task':'Do a task'}).encode(),{'Content-Type':'application/json',**headers})
                    with self.assertRaises(urllib.error.HTTPError) as error:opener.open(req,timeout=3)
                    self.assertEqual(error.exception.code,expected)
                    error.exception.close()
                manager.return_value.start.assert_not_called()
            finally:server.shutdown();server.server_close();thread.join()
    def test_document_upload_download_and_kind_are_preserved(self):
        with tempfile.TemporaryDirectory() as d,patch('local_coder.server.DATA_ROOT',Path(d)),patch('local_coder.server.Manager'):
            server=Server(('127.0.0.1',0));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_address[1]}';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            data=b'The calibration constant is 37.5 volts.'
            try:
                req=urllib.request.Request(base+'/api/attachments',data,{'X-Local-Coder-Token':server.token,'X-Upload-Name':'lecture.txt','Content-Type':'text/plain'})
                with opener.open(req,timeout=5) as r:metadata=json.load(r)
                self.assertEqual(metadata['kind'],'document');self.assertGreater(metadata['characters'],0)
                with opener.open(base+metadata['url'],timeout=3) as r:
                    self.assertEqual(r.read(),data);self.assertEqual(r.headers.get_content_type(),'application/octet-stream')
                    self.assertIn('attachment;',r.headers['Content-Disposition'])
            finally:server.shutdown();server.server_close();thread.join()
