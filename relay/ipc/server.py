"""Local authenticated IPC for the optional panel — HTTP + Server-Sent Events.

The optional frontend must MIRROR the engine, never be required by it, and must not
open an automation hole. So this server:
  * binds to loopback only (127.0.0.1);
  * requires a random per-session token on every request (constant-time compared);
  * validates the Host header is localhost (rejects DNS-rebinding / remote origins);
  * exposes a NARROW command set — high-level intents through the SAME safety
    pipeline as voice (handle / set_mode / onboard / ping), never raw click/type/xy;
  * streams a whitelist of state events (voice/task state, perception change,
    narration) to the panel over SSE.
Closing the panel just drops the SSE connection; the core keeps running.

Stdlib only (no web framework, no websockets dep) — keeps the offline core light.
"""

from __future__ import annotations

import json
import queue
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from relay.diagnostics import get_logger

log = get_logger("ipc")

# Only these bus event types are forwarded to the panel.
_FORWARD_EVENTS = {
    "voice.state",
    "task.state",
    "perception.change",
    "narration.say",
    "reading.start",
    "reading.part",
    "reading.end",
    "reminder.due",
}
# Only these commands are accepted from the panel (all go through the safety pipeline).
_ALLOWED_COMMANDS = {"handle", "set_mode", "onboard", "ping"}

_FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
_PANEL_HTML = _FRONTEND_DIR / "panel.html"


def token_ok(supplied: str, expected: str) -> bool:
    """Constant-time token check."""
    return bool(supplied) and secrets.compare_digest(str(supplied), str(expected))


def host_ok(host_header: str) -> bool:
    """Only accept requests addressed to loopback (defeats DNS-rebinding)."""
    h = (host_header or "").split(":")[0].strip().lower()
    return h in ("127.0.0.1", "localhost", "::1")


def command_allowed(command: str) -> bool:
    return command in _ALLOWED_COMMANDS


class IpcServer:
    def __init__(self, session, bus, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.session = session
        self.bus = bus
        self.host = host
        self.port = port
        self.token = secrets.token_urlsafe(18)
        self._clients: set[queue.Queue] = set()
        self._clients_lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        if bus is not None:
            for et in _FORWARD_EVENTS:
                bus.subscribe(et, self._on_event)

    # --- bus -> SSE fan-out ---
    def _on_event(self, event) -> None:
        payload = json.dumps({"type": event.type, "data": event.data})
        with self._clients_lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass

    def _add_client(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._clients_lock:
            self._clients.add(q)
        return q

    def _remove_client(self, q: queue.Queue) -> None:
        with self._clients_lock:
            self._clients.discard(q)

    # --- command dispatch (narrow, safe) ---
    def dispatch(self, command: str, args: dict) -> dict:
        if not command_allowed(command):
            return {"ok": False, "error": "command not allowed"}
        if command == "ping":
            return {"ok": True, "pong": True}
        if command == "set_mode":
            mode = str(args.get("mode", "")).lower()
            if mode not in ("quick", "detailed", "guided", "quiet"):
                return {"ok": False, "error": "bad mode"}
            self.session.handle(f"{mode} mode")
            return {"ok": True}
        if command == "onboard":
            self.session.onboard()
            return {"ok": True}
        if command == "handle":
            text = str(args.get("text", "")).strip()
            if not text:
                return {"ok": False, "error": "empty command"}
            # run like a spoken command, through the full safety pipeline
            self.session.handle(text)
            return {"ok": True}
        return {"ok": False, "error": "unknown command"}

    # --- lifecycle ---
    def start(self) -> str:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass  # quiet

            def _auth(self) -> bool:
                q = parse_qs(urlparse(self.path).query)
                if not host_ok(self.headers.get("Host", "")):
                    self._json(403, {"error": "bad host"})
                    return False
                if not token_ok((q.get("token") or [""])[0], server.token):
                    self._json(403, {"error": "unauthorized"})
                    return False
                return True

            def _json(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urlparse(self.path).path
                if path in ("/", "/panel.html", "/index.html"):
                    if not self._auth():
                        return
                    try:
                        html = _PANEL_HTML.read_bytes()
                    except OSError:
                        html = b"<h1>RELAY panel missing</h1>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html)))
                    self.end_headers()
                    self.wfile.write(html)
                    return
                if path in ("/style.css", "/app.js"):
                    if not self._auth():
                        return
                    static_file = _FRONTEND_DIR / path.lstrip("/")
                    try:
                        data = static_file.read_bytes()
                    except OSError:
                        self._json(404, {"error": "not found"})
                        return
                    ctype = (
                        "text/css; charset=utf-8"
                        if path.endswith(".css")
                        else "application/javascript; charset=utf-8"
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if path == "/events":
                    if not self._auth():
                        return
                    self._stream_events()
                    return
                self._json(404, {"error": "not found"})

            def do_POST(self):
                if urlparse(self.path).path != "/command" or not self._auth():
                    if urlparse(self.path).path != "/command":
                        self._json(404, {"error": "not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    data = json.loads(self.rfile.read(length) or b"{}")
                except (ValueError, json.JSONDecodeError):
                    self._json(400, {"error": "bad json"})
                    return
                result = server.dispatch(str(data.get("command", "")), data)
                self._json(200 if result.get("ok") else 400, result)

            def _stream_events(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                q = server._add_client()
                try:
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()
                    while True:
                        try:
                            payload = q.get(timeout=15)
                            self.wfile.write(f"data: {payload}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")  # keep the connection warm
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass  # panel closed — the core keeps running
                finally:
                    server._remove_client(q)

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="ipc-http", daemon=True
        )
        self._thread.start()
        url = f"http://{self.host}:{self.port}/?token={self.token}"
        log.info("panel available at %s", url)
        return url

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None
