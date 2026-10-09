"""P10: the optional panel's IPC — token/host auth, narrow command whitelist, and
event fan-out. Real local server on an ephemeral port (no GUI needed)."""

import json
import urllib.error
import urllib.request

from relay.core import EventBus
from relay.ipc import IpcServer, command_allowed, host_ok, token_ok


class FakeSession:
    def __init__(self):
        self.calls = []

    def handle(self, text):
        self.calls.append(("handle", text))
        return []

    def onboard(self):
        self.calls.append(("onboard",))

    def close(self):
        pass


# ---- pure security helpers ----
def test_security_helpers():
    assert token_ok("abc", "abc") and not token_ok("abc", "abd") and not token_ok("", "x")
    assert host_ok("127.0.0.1:8765") and host_ok("localhost") and not host_ok("evil.com")
    assert command_allowed("handle") and not command_allowed("click_at")


# ---- dispatch is narrow and routes through the session ----
def test_dispatch_whitelist_and_routing():
    fs = FakeSession()
    srv = IpcServer(fs, bus=None)
    assert srv.dispatch("ping", {})["pong"] is True
    assert srv.dispatch("set_mode", {"mode": "quiet"})["ok"]
    assert ("handle", "quiet mode") in fs.calls
    assert not srv.dispatch("set_mode", {"mode": "nope"})["ok"]
    assert srv.dispatch("handle", {"text": "open notepad"})["ok"]
    assert ("handle", "open notepad") in fs.calls
    assert srv.dispatch("handle", {"args": {"text": "read the page"}})["ok"]
    assert ("handle", "read the page") in fs.calls
    assert not srv.dispatch("handle", {"text": ""})["ok"]
    assert not srv.dispatch("click_at", {"x": 1})["ok"]  # raw automation refused


# ---- live server: auth enforced on every route + event fan-out ----
def _get(url):
    return urllib.request.urlopen(url, timeout=5)


def _post(url, obj):
    req = urllib.request.Request(
        url,
        data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=5)


def test_live_server_auth_and_events():
    fs = FakeSession()
    bus = EventBus()
    srv = IpcServer(fs, bus, port=0)
    url = srv.start()  # http://127.0.0.1:PORT/?token=TOK
    base, token = url.split("/?")[0], url.split("token=")[1]
    try:
        # panel without a token -> 403
        try:
            _get(base + "/")
            raise AssertionError("expected 403")
        except urllib.error.HTTPError as e:
            assert e.code == 403
        # panel with token -> 200 HTML
        r = _get(base + "/?token=" + token)
        html = r.read()
        assert r.status == 200 and b"RELAY" in html
        assert f'/style.css?token={token}'.encode() in html
        assert f'/app.js?token={token}'.encode() in html
        assert _get(base + "/style.css?token=" + token).status == 200
        assert _get(base + "/app.js?token=" + token).status == 200
        # ping command with token -> ok
        assert json.loads(_post(base + "/command?token=" + token, {"command": "ping"}).read())["ok"]
        # disallowed command -> 400
        try:
            _post(base + "/command?token=" + token, {"command": "click_at"})
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400
        # command without token -> 403
        try:
            _post(base + "/command", {"command": "ping"})
            raise AssertionError("expected 403")
        except urllib.error.HTTPError as e:
            assert e.code == 403
        # a whitelisted bus event is fanned out to a connected client
        q = srv._add_client()
        bus.emit("narration.say", text="hello from relay")
        assert "hello from relay" in q.get(timeout=2)
        # a non-whitelisted event is NOT forwarded
        srv._on_event  # exists
        bus.emit("secret.internal", data=1)
        assert q.empty()
    finally:
        srv.stop()
