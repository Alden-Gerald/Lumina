"""HTTPS, password-protected LAN entrance to the loopback dashboard."""
from __future__ import annotations

import hashlib
import hmac
from http import HTTPStatus
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import secrets
import ssl
import threading
import time
from urllib.parse import parse_qs, urlsplit


LOGIN_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in to Lumina</title><style>
body{font:16px system-ui;background:#101923;color:#f5f7fa;display:grid;place-items:center;min-height:100vh;margin:0}
main{width:min(340px,calc(100vw - 48px));background:#1b2935;padding:32px;border-radius:18px}
h1{margin:0 0 8px}p{color:#b8c5ce}label{display:block;margin:20px 0 6px}
input,button{box-sizing:border-box;width:100%;padding:12px;border-radius:8px;font:inherit}
input{background:#101923;color:white;border:1px solid #5b707e}
button{margin-top:24px;background:#9fe4c5;border:0;color:#14251d;font-weight:700;cursor:pointer}
.error{color:#ffb1a7}
</style><main><h1>Lumina</h1><p>Your local AI</p>__ERROR__
<form method="post" action="/login"><label for="username">Username</label>
<input id="username" name="username" autocomplete="username" required autofocus>
<label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Sign in</button></form></main></html>"""


def password_hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()


class Gateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, *, lan: str, credentials: Path, backend_port: int = 8787):
        self.lan = ipaddress.ip_network(lan, strict=False)
        self.credentials_path = credentials
        self.credentials = json.loads(credentials.read_text())
        self.credentials_mtime = credentials.stat().st_mtime_ns
        self.backend_port = backend_port
        self.sessions: dict[str, float] = {}
        self.failures: dict[str, tuple[int, float]] = {}
        self.lock = threading.Lock()
        super().__init__(address, GatewayHandler)


class GatewayHandler(BaseHTTPRequestHandler):
    server: Gateway
    server_version = "Lumina/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, body: bytes, content_type: str, extra: dict[str, str] | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        self.send_header("Strict-Transport-Security", "max-age=31536000")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _allowed(self):
        try:
            peer = ipaddress.ip_address(self.client_address[0])
            host = self.headers.get("Host", "").lower()
            port = self.server.server_address[1]
            allowed_hosts = {f"lumina.local:{port}", f"{self.server.server_address[0]}:{port}"}
            origin = self.headers.get("Origin")
            return (peer in self.server.lan and host in allowed_hosts
                    and (not origin or origin.lower() in {f"https://{h}" for h in allowed_hosts}))
        except ValueError:
            return False

    def _session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie["lumina_session"].value
        except (KeyError, ValueError):
            return False
        with self.server.lock:
            self._reload_credentials()
            saved = self.server.sessions.get(token, (0, -1))
            expiry,version = saved if isinstance(saved,tuple) else (saved,1)
            if expiry <= time.time():
                self.server.sessions.pop(token, None)
                return False
            return version == int(self.server.credentials.get("version",1))

    def _reload_credentials(self):
        try:mtime=self.server.credentials_path.stat().st_mtime_ns
        except OSError:return
        if mtime!=self.server.credentials_mtime:
            self.server.credentials=json.loads(self.server.credentials_path.read_text())
            self.server.credentials_mtime=mtime

    def _login_page(self, error=False):
        message = '<p class="error">Incorrect username or password.</p>' if error else ""
        self._send(200, LOGIN_PAGE.replace("__ERROR__", message).encode(), "text/html; charset=utf-8")

    def _redirect(self, path, cookie=None):
        headers = {"Location": path}
        if cookie:
            headers["Set-Cookie"] = cookie
        self._send(HTTPStatus.SEE_OTHER, b"", "text/plain", headers)

    def _proxy(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 12 * 1024 * 1024:
            return self._send(413, b"Request too large", "text/plain")
        body = self.rfile.read(length) if length else None
        headers = {}
        excluded = {"host", "origin", "connection", "content-length", "transfer-encoding", "cookie", "accept-encoding"}
        for key, value in self.headers.items():
            if key.lower() not in excluded:
                headers[key] = value
        headers["Host"] = f"127.0.0.1:{self.server.backend_port}"
        if self.headers.get("Origin"):
            headers["Origin"] = f"http://127.0.0.1:{self.server.backend_port}"
        connection = HTTPConnection("127.0.0.1", self.server.backend_port, timeout=60)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in {"connection", "keep-alive", "transfer-encoding", "content-length", "server", "date"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Strict-Transport-Security", "max-age=31536000")
            self.end_headers()
            self.wfile.write(data)
        finally:
            connection.close()

    def do_GET(self):
        if not self._allowed():
            return self._send(403, b"Forbidden", "text/plain")
        path = urlsplit(self.path).path
        if path == "/lumina-ca.crt":
            try:
                certificate = (self.server.credentials_path.parent / "lumina-ca.crt").read_bytes()
            except OSError:
                return self._send(404, b"Certificate unavailable", "text/plain")
            return self._send(200, certificate, "application/x-x509-ca-cert",
                              {"Content-Disposition": 'attachment; filename="lumina-ca.crt"'})
        if path == "/login":
            return self._redirect("/") if self._session() else self._login_page()
        if not self._session():
            return self._redirect("/login") if path == "/" else self._send(401, b"Sign in required", "text/plain")
        try:
            self._proxy()
        except (OSError, ValueError):
            self._send(502, b"Lumina is temporarily unavailable", "text/plain")

    def do_POST(self):
        if not self._allowed():
            return self._send(403, b"Forbidden", "text/plain")
        path = urlsplit(self.path).path
        if path == "/login":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    return self._send(400, b"Invalid login request", "text/plain")
                values = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"), keep_blank_values=True)
                username, password = values.get("username", [""])[0], values.get("password", [""])[0]
                address = self.client_address[0]
                with self.server.lock:
                    count, locked_until = self.server.failures.get(address, (0, 0))
                    if locked_until > time.time():
                        return self._send(429, b"Too many attempts. Try again later.", "text/plain")
                with self.server.lock:self._reload_credentials();saved = self.server.credentials
                expected = saved["hash"]
                actual = password_hash(password, bytes.fromhex(saved["salt"]))
                valid = hmac.compare_digest(username, saved["username"]) and hmac.compare_digest(actual, expected)
                if not valid:
                    with self.server.lock:
                        count += 1
                        self.server.failures[address] = (count, time.time() + 60 if count >= 5 else 0)
                    return self._login_page(error=True)
                token = secrets.token_urlsafe(32)
                with self.server.lock:
                    self.server.failures.pop(address, None)
                    self.server.sessions[token] = (time.time() + 12 * 3600,int(saved.get("version",1)))
                return self._redirect("/", f"lumina_session={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=43200")
            except (ValueError, KeyError, IndexError):
                return self._send(400, b"Invalid login request", "text/plain")
        if path == "/logout":
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                token = cookie["lumina_session"].value
                with self.server.lock:
                    self.server.sessions.pop(token, None)
            except (KeyError, ValueError):
                pass
            return self._redirect("/login", "lumina_session=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0")
        if not self._session():
            return self._send(401, b"Sign in required", "text/plain")
        try:
            self._proxy()
        except (OSError, ValueError):
            self._send(502, b"Lumina is temporarily unavailable", "text/plain")


def serve(bind: str, lan: str, credentials: Path, cert: Path, key: Path, port: int = 8443):
    server = Gateway((bind, port), lan=lan, credentials=credentials)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"Lumina: https://lumina.local:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    from .settings import DATA_ROOT
    folder = DATA_ROOT / "lan"
    serve("192.168.18.5", "192.168.18.0/24", folder / "login.json", folder / "cert.pem", folder / "key.pem")
