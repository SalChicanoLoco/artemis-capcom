"""Loopback HTTP and read-only WebSocket snapshots with bounded client queues."""
import base64
import hashlib
import json
from pathlib import Path
import queue
import select
import socket
import struct
import threading
import secrets
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = Path(__file__).resolve().parent

def ws_frame(payload, opcode=1):
    payload = payload if isinstance(payload, bytes) else payload.encode("utf-8")
    n = len(payload)
    header = bytes([0x80 | opcode, n]) if n < 126 else (
        bytes([0x80 | opcode, 126]) + struct.pack("!H", n) if n < 65536 else
        bytes([0x80 | opcode, 127]) + struct.pack("!Q", n))
    return header + payload


def read_exact(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ConnectionError("WebSocket closed")
        data += chunk
    return data


class TelemetryServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port=8765):
        self.clients = set()
        self.lock = threading.Lock()
        self.latest = None
        self.runtime = None
        self.control_token = secrets.token_urlsafe(24)
        super().__init__(("127.0.0.1", port), TelemetryHandler)

    def broadcast(self, event):
        payload = json.dumps(event, allow_nan=False)
        with self.lock:
            self.latest = payload
            for mailbox in self.clients:
                if mailbox.full():
                    mailbox.get_nowait()
                mailbox.put_nowait(payload)


class TelemetryHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def do_GET(self):
        self.path = urlsplit(self.path).path
        if self.path in ("/", "/lunar_hud.html"):
            body, mime = (ROOT / "lunar_hud.html").read_bytes(), "text/html; charset=utf-8"
        elif self.path == "/control":
            body = (ROOT / "director.html").read_text().replace("__CONTROL_TOKEN__", self.server.control_token).encode()
            mime = "text/html; charset=utf-8"
        elif self.path == "/sites":
            body, mime = (ROOT / "fixtures/sites.json").read_bytes(), "application/json"
        elif self.path == "/health":
            status = self.server.runtime.status() if self.server.runtime else {}
            body, mime = json.dumps(dict(ok=True, **status)).encode(), "application/json"
        elif self.path == "/telemetry":
            with self.server.lock:
                body = (self.server.latest or "null").encode()
            mime = "application/json"
        elif self.path in ("/ws", "/") and self.headers.get("Upgrade", "").lower() == "websocket":
            return self.websocket()
        else:
            self.send_error(404)
            return
        # Root URL also accepts the OBS ws://127.0.0.1:8765 handshake.
        if self.path == "/" and self.headers.get("Upgrade", "").lower() == "websocket":
            return self.websocket()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.close_connection = True
        origin = self.headers.get("Origin")
        allowed = (None, f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}")
        if (self.path != "/command" or origin not in allowed or
                not secrets.compare_digest(self.headers.get("X-CapCom-Control", ""), self.server.control_token)):
            self.send_error(403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096 or self.headers.get_content_type() != "application/json":
                raise ValueError("Expected a small JSON command")
            self.connection.settimeout(2)
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict) or not isinstance(data.get("command"), str):
                raise ValueError("Expected a command string")
            if self.server.runtime is None:
                raise ValueError("Director unavailable in this mode")
            user = data.get("viewer", "director")
            if not isinstance(user, str) or not user.isalnum() or len(user) > 25:
                raise ValueError("Use a short alphanumeric rehearsal viewer name")
            self.server.runtime.submit(data["command"], user=user)
            body = b'{"accepted":true}'
            code = 202
        except (ValueError, UnicodeError, OSError) as exc:
            body, code = json.dumps({"error": str(exc)}).encode(), 400
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def websocket(self):
        key = self.headers.get("Sec-WebSocket-Key", "")
        origin = self.headers.get("Origin")
        port = self.server.server_port
        if origin not in (None, "null", f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            self.send_error(403)
            return
        try:
            if len(base64.b64decode(key, validate=True)) != 16:
                raise ValueError
            if self.headers.get("Sec-WebSocket-Version") != "13":
                raise ValueError
        except ValueError:
            self.send_error(400)
            return
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        mailbox = queue.Queue(maxsize=32)
        with self.server.lock:
            if len(self.server.clients) >= 16:
                self.connection.sendall(ws_frame(b"", 8))
                self.close_connection = True
                return
            if self.server.latest:
                mailbox.put(self.server.latest)
            self.server.clients.add(mailbox)
        self.connection.settimeout(.5)
        try:
            while True:
                try:
                    self.connection.sendall(ws_frame(mailbox.get_nowait()))
                except queue.Empty:
                    pass
                if select.select([self.connection], [], [], .05)[0]:
                    first, second = read_exact(self.connection, 2)
                    opcode, length = first & 15, second & 127
                    if not first & 128 or first & 112 or not second & 128:
                        break
                    if length == 126:
                        length = struct.unpack("!H", read_exact(self.connection, 2))[0]
                    elif length == 127:
                        length = struct.unpack("!Q", read_exact(self.connection, 8))[0]
                    if length > 4096 or (opcode >= 8 and length > 125):
                        break
                    mask = read_exact(self.connection, 4)
                    payload = bytes(c ^ mask[i % 4] for i, c in enumerate(read_exact(self.connection, length)))
                    if opcode == 8:
                        self.connection.sendall(ws_frame(b"", 8))
                        break
                    if opcode == 9:
                        self.connection.sendall(ws_frame(payload, 10))
                    elif opcode not in (1, 2, 10):
                        break
        except (OSError, ConnectionError):
            pass
        finally:
            with self.server.lock:
                self.server.clients.discard(mailbox)
            self.close_connection = True


