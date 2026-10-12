import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from local_coder.artifacts import extract_artifact
from local_coder.server import Server


HTML = '<!doctype html><html><body><button onclick="document.body.append(7)">Try it</button></body></html>'
WRAPPED = ('Here is your tool.\n<local_artifact identifier="demo" title="Demo tool" type="web_app">'
           '\n```html\n' + HTML + '\n```\n</local_artifact>')


class ArtifactTests(unittest.TestCase):
    def test_only_complete_bounded_html_is_extracted(self):
        self.assertEqual(extract_artifact(WRAPPED)['html'], HTML)
        self.assertIsNone(extract_artifact(WRAPPED[:-18]))
        self.assertIsNone(extract_artifact(WRAPPED.replace('type="web_app"', 'type="text"')))
        self.assertIsNone(extract_artifact(WRAPPED.replace(HTML, '<p>fragment</p>')))
        self.assertIsNone(extract_artifact(WRAPPED.replace(HTML, '<html>' + 'a' * 250_001 + '</html>')))

    def test_preview_serves_saved_assistant_html_with_isolated_csp(self):
        with tempfile.TemporaryDirectory() as directory, patch('local_coder.server.DATA_ROOT', Path(directory)), patch('local_coder.server.Manager'):
            server = Server(('127.0.0.1', 0))
            server.chats.inference = lambda *_: (WRAPPED, {})
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            base = f'http://127.0.0.1:{server.server_address[1]}'
            try:
                state = server.chats.start('Build a demo tool', model='fast', deep=False)
                server.chats.worker.join(3)
                state = server.chats.get(state['id'])
                message = state['messages'][-1]
                url = base + f"/api/chats/{state['id']}/artifacts/{message['id']}/preview"
                with opener.open(url, timeout=3) as response:
                    self.assertEqual(response.read().decode(), HTML)
                    csp = response.headers['Content-Security-Policy']
                    self.assertIn('sandbox allow-scripts', csp)
                    self.assertIn("connect-src 'none'", csp)
                    self.assertIn("frame-ancestors 'self'", csp)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    opener.open(base + f"/api/chats/{state['id']}/artifacts/{state['messages'][0]['id']}/preview", timeout=3)
                self.assertEqual(error.exception.code, 400)
                error.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join()
