from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from local_coder.lan_gateway import Gateway, password_hash


class BackendHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        body = json.dumps({"host": self.headers.get("Host"), "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GatewayTests(unittest.TestCase):
    def test_login_guards_all_dashboard_data_and_proxies_after_sign_in(self):
        with tempfile.TemporaryDirectory() as folder:
            salt = bytes.fromhex("00112233445566778899aabbccddeeff")
            credentials = Path(folder) / "login.json"
            credentials.write_text(json.dumps({"username": "lumina", "salt": salt.hex(), "hash": password_hash("correct horse", salt)}))
            (Path(folder) / "lumina-ca.crt").write_bytes(b"public test CA")
            backend = ThreadingHTTPServer(("127.0.0.1", 0), BackendHandler)
            gateway = Gateway(("127.0.0.1", 0), lan="127.0.0.0/8", credentials=credentials,
                              backend_port=backend.server_address[1])
            threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (backend, gateway)]
            for thread in threads:
                thread.start()
            host = f"lumina.local:{gateway.server_address[1]}"
            def request(path, body=None, headers=None):
                connection = HTTPConnection("127.0.0.1", gateway.server_address[1], timeout=3)
                connection.request("POST" if body is not None else "GET", path, body, {"Host": host, **(headers or {})})
                response = connection.getresponse()
                result = response.status, dict(response.getheaders()), response.read()
                connection.close()
                return result
            try:
                status, headers, _ = request("/")
                self.assertEqual((status, headers["Location"]), (303, "/login"))
                self.assertEqual(request("/api/chats")[0], 401)
                status, _, body = request("/lumina-ca.crt")
                self.assertEqual((status, body), (200, b"public test CA"))
                status, _, body = request("/login", b"username=lumina&password=wrong", {"Content-Type": "application/x-www-form-urlencoded"})
                self.assertEqual(status, 200)
                self.assertIn(b"Incorrect username", body)
                status, headers, _ = request("/login", b"username=lumina&password=correct+horse", {"Content-Type": "application/x-www-form-urlencoded"})
                self.assertEqual(status, 303)
                cookie = headers["Set-Cookie"].split(";", 1)[0]
                status, _, body = request("/api/chats", headers={"Cookie": cookie})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["host"], f"127.0.0.1:{backend.server_address[1]}")
                self.assertEqual(request("/api/chats", headers={"Cookie": cookie, "Origin": "https://evil.example"})[0], 403)
                self.assertEqual(request("/api/chats", headers={"Cookie": cookie, "Host": "evil.example"})[0], 403)
            finally:
                for server in (gateway, backend):
                    server.shutdown()
                    server.server_close()
                for thread in threads:
                    thread.join()


if __name__ == "__main__":
    unittest.main()
