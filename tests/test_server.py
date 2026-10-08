import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock
import urllib.request
import urllib.error
from local_coder.server import Server

class ServerTests(unittest.TestCase):
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
