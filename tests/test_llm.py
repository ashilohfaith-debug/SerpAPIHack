"""AI assistant: OpenAI-compatible streaming client, hedged router, spoken assistant.

A local mock server speaks the real wire format (HTTP/1.1, chunked Server-Sent
Events, like FreeLLMAPI), so the client, the router's hedging / failover /
cool-down and connection reuse are tested for real — no internet needed.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from relay.llm import Assistant, LLMClient, NoRoute, Route, RouteError, Router, validate_command

# model name -> behaviour of the mock server
SCRIPTS = {
    "fast": {"delay": 0.0, "chunks": ["Paris is the ", "capital of France. ", "It is lovely."]},
    "slow": {"delay": 1.5, "chunks": ["Slow answer."]},
    "drip": {"delay": 0.0, "chunks": [f"word{i} " for i in range(40)], "gap": 0.1},
    "cmd": {"delay": 0.0, "chunks": ["DO: what time", " is it\n"]},
    "unsafe": {"delay": 0.0, "chunks": ["DO: delete my notes\n"]},
    "empty": {"delay": 0.0, "chunks": []},
}


class MockLLM(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    log = []                        # (path, client port, headers, body)

    def log_message(self, *a):      # keep test output quiet
        pass

    def _record(self, body=None):
        MockLLM.log.append((self.path, self.client_address[1], dict(self.headers), body))

    def do_GET(self):
        self._record()
        data = json.dumps({"data": [{"id": "auto"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self._record(body)
        model = body["model"]
        if model == "err500":
            return self._plain(500, b'{"error":"upstream failed"}')
        if model == "rate429":
            return self._plain(429, b'{"error":"rate limited"}', {"Retry-After": "30"})
        if model == "stall":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.flush()
            time.sleep(3.0)
            return
        script = SCRIPTS[model]
        time.sleep(script["delay"])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            for text in script["chunks"]:
                ev = {"choices": [{"index": 0, "delta": {"content": text}}]}
                self._chunk(f"data: {json.dumps(ev)}\n\n".encode())
                time.sleep(script.get("gap", 0.0))
            self._chunk(b"data: [DONE]\n\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except OSError:
            pass                    # the client cancelled this stream

    def _chunk(self, data: bytes) -> None:
        self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
        self.wfile.flush()

    def _plain(self, status, data, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), MockLLM)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


def _route(url, model, **kw):
    return Route(name=model, base_url=url, api_key="freellmapi-test-key", model=model, **kw)


def _msgs(text="What is the capital of France?"):
    return [{"role": "user", "content": text}]


# ---------------------------------------------------------------- client
def test_client_streams_deltas_with_bearer_key(server):
    MockLLM.log.clear()
    out = list(LLMClient().stream_chat(_route(server, "fast"), _msgs()))
    assert "".join(out) == "Paris is the capital of France. It is lovely."
    path, _port, headers, body = MockLLM.log[-1]
    assert path == "/v1/chat/completions"
    assert headers["Authorization"] == "Bearer freellmapi-test-key"
    assert body["stream"] is True and body["model"] == "fast"


def test_client_reuses_one_connection(server):
    MockLLM.log.clear()
    client = LLMClient()
    route = _route(server, "fast")
    client.warm(route)
    list(client.stream_chat(route, _msgs()))
    list(client.stream_chat(route, _msgs()))
    ports = {port for _path, port, _h, _b in MockLLM.log}
    assert len(MockLLM.log) == 3 and len(ports) == 1     # warm + 2 requests, one socket


def test_client_http_error_carries_status_and_retry_after(server):
    with pytest.raises(RouteError) as e:
        list(LLMClient().stream_chat(_route(server, "rate429"), _msgs()))
    assert e.value.status == 429 and e.value.retry_after == 30.0


def test_client_unreachable_is_a_route_error():
    route = Route(name="down", base_url="http://127.0.0.1:9/v1", model="x", timeout=2)
    with pytest.raises(RouteError) as e:
        list(LLMClient().stream_chat(route, _msgs()))
    assert e.value.status == 0


def test_route_repr_hides_key(server):
    assert "freellmapi-test-key" not in repr(_route(server, "fast"))


# ---------------------------------------------------------------- router
def test_router_hedges_a_slow_route(server):
    router = Router([_route(server, "slow"), _route(server, "fast")], min_hedge=0.3)
    router.health["slow"].ttft = 0.1            # looks fastest, so it is tried first
    router.health["fast"].ttft = 0.5
    t0 = time.monotonic()
    text = "".join(router.stream(_msgs()))
    took = time.monotonic() - t0
    assert text.startswith("Paris") and router.last_route == "fast"
    assert took < 1.2                           # did not wait for the 1.5 s route


def test_router_fails_over_at_once_on_error(server):
    router = Router([_route(server, "err500"), _route(server, "fast")], min_hedge=5.0)
    router.health["err500"].ttft = 0.1
    t0 = time.monotonic()
    text = "".join(router.stream(_msgs()))
    assert text.startswith("Paris") and time.monotonic() - t0 < 1.0   # no hedge wait
    assert router.health["err500"].failures == 1


def test_router_cools_down_a_rate_limited_route(server):
    router = Router([_route(server, "rate429"), _route(server, "fast")])
    router.health["rate429"].ttft = 0.1
    "".join(router.stream(_msgs()))
    assert [r.name for r in router.ordered()] == ["fast"]      # skipped for Retry-After


def test_router_raises_noroute_when_everything_fails(server):
    router = Router([_route(server, "err500")])
    with pytest.raises(NoRoute):
        list(router.stream(_msgs()))
    with pytest.raises(NoRoute):                # an empty answer is a failure too
        list(Router([_route(server, "empty")]).stream(_msgs()))


def test_router_gives_up_on_a_stalled_route_quickly(server):
    router = Router([_route(server, "stall")], first_token_timeout=0.6)
    t0 = time.monotonic()
    with pytest.raises(NoRoute):
        list(router.stream(_msgs()))
    assert time.monotonic() - t0 < 1.5


def test_router_stops_streaming_when_cancelled(server):
    router = Router([_route(server, "drip")])
    cancel = threading.Event()
    got = []
    t0 = time.monotonic()
    for delta in router.stream(_msgs(), cancel=cancel):
        got.append(delta)
        if len(got) == 3:
            cancel.set()                        # the user said "stop"
    assert len(got) <= 4 and time.monotonic() - t0 < 1.5     # 40 words would take 4 s


def test_router_connection_is_reused_across_questions(server):
    MockLLM.log.clear()
    router = Router([_route(server, "fast")])
    for _ in range(3):
        "".join(router.stream(_msgs()))
    assert len({port for _p, port, _h, _b in MockLLM.log}) == 1


# ---------------------------------------------------------------- assistant
class ScriptRouter:
    """Stands in for the router: yields scripted deltas with a delay between them."""

    def __init__(self, deltas, gap=0.0, fail: Exception | None = None):
        self.deltas, self.gap, self.fail = deltas, gap, fail
        self.calls = []
        self.finished_at = None

    def stream(self, messages, max_tokens=300, cancel=None):
        self.calls.append(messages)
        for d in self.deltas:
            if cancel is not None and cancel.is_set():
                return
            time.sleep(self.gap)
            yield d
        if self.fail is not None:
            raise self.fail
        self.finished_at = time.monotonic()


def test_first_sentence_is_spoken_before_the_answer_finishes():
    router = ScriptRouter(["An index fund ", "is a basket of shares. ", "It tracks ",
                           "a market ", "index ", "like the ", "Nifty fifty."], gap=0.1)
    spoken = []
    kind, text = Assistant(router).respond(
        "what is an index fund", lambda s: spoken.append((s, time.monotonic())))
    assert kind == "answer"
    assert spoken[0][0] == "An index fund is a basket of shares."
    assert spoken[0][1] < router.finished_at - 0.3        # long before the stream ended
    assert spoken[-1][0] == "It tracks a market index like the Nifty fifty."


def test_numbers_are_not_split_at_the_decimal_point():
    router = ScriptRouter(["It costs about 3.", "5 lakh rupees. ", "That is a lot."])
    spoken = []
    Assistant(router).respond("how much", spoken.append)
    assert spoken == ["It costs about 3.5 lakh rupees.", "That is a lot."]


def test_markdown_and_links_are_not_read_out():
    router = ScriptRouter(["**Paris** is the capital. ", "See https://example.com now."])
    spoken = []
    Assistant(router).respond("capital of france", spoken.append)
    assert spoken == ["Paris is the capital.", "See a link now."]


def test_do_command_is_validated_before_running():
    kind, cmd = Assistant(ScriptRouter(["DO: what time", " is it\n", "extra"])).respond(
        "tell me the time please", lambda s: None)
    assert (kind, cmd) == ("command", "what time is it")
    spoken = []
    kind, text = Assistant(ScriptRouter(["DO: delete my notes\n"])).respond(
        "wipe everything", spoken.append)
    assert kind == "answer" and spoken == ["I'm not able to do that one."]


def test_validate_command_rejects_unsafe_and_unknown():
    assert validate_command("DO: open notepad") == "open notepad"
    assert validate_command("DO: confirm delete") is None
    assert validate_command("DO: emergency stop") is None
    assert validate_command("DO: quit relay") is None
    assert validate_command("DO: type my password is hunter2") is None
    assert validate_command("DO: juggle three oranges") is None


def test_offline_when_no_route_answers():
    kind, text = Assistant(ScriptRouter([], fail=NoRoute("down"))).respond(
        "what is the weather", lambda s: None)
    assert (kind, text) == ("offline", "")


def test_secrets_are_never_sent():
    router = ScriptRouter(["never"])
    spoken = []
    kind, _ = Assistant(router).respond("my password is Hunter2!", spoken.append)
    assert router.calls == [] and kind == "answer" and "password" in spoken[0]


def test_page_text_is_sent_only_when_given_and_capped():
    router = ScriptRouter(["Short summary."])
    Assistant(router).respond("summarize this page", lambda s: None, page_text="q" * 9000)
    user = router.calls[0][-1]["content"]
    assert "summarize this page" in user and user.count("q") == 6000
    Assistant(router).respond("capital of france", lambda s: None)
    assert "screen" not in router.calls[1][-1]["content"]


def test_follow_up_questions_keep_recent_turns():
    router = ScriptRouter(["Paris."])
    a = Assistant(router, max_turns=2)
    for q in ("capital of france", "and germany", "and italy"):
        a.respond(q, lambda s: None)
    history = router.calls[-1][1:-1]            # between system prompt and new question
    assert [m["content"] for m in history if m["role"] == "user"] == [
        "capital of france", "and germany"]


def test_next_sentence_is_synthesised_while_the_last_one_plays():
    """Streamed answers arrive sentence by sentence; synthesis must overlap playback
    or every sentence adds a gap."""
    import numpy as np

    from relay.audio.speech import SpeechQueue

    class SlowTTS:
        def synth_to_array(self, text):
            time.sleep(0.4)
            return np.zeros(160, dtype=np.float32), 16000

    q = SpeechQueue(SlowTTS(), player=lambda a, sr, stop: stop.wait(0.4))
    try:
        t0 = time.monotonic()
        for s in ("One.", "Two.", "Three."):
            q.say(s)
        assert q.wait_idle(5.0)
        took = time.monotonic() - t0
    finally:
        q.shutdown()
    assert took < 2.1                     # serial would be 2.4 s; pipelined about 1.6 s


def test_stop_frees_the_microphone_even_while_an_online_voice_request_is_in_flight():
    import numpy as np

    from relay.audio.speech import SpeechQueue

    class NetworkTTS:                     # a 2 s online request that can't be aborted
        def synth_to_array(self, text):
            time.sleep(2.0)
            return np.zeros(160, dtype=np.float32), 16000

    q = SpeechQueue(NetworkTTS(), player=lambda a, sr, stop: stop.wait(0.1))
    try:
        q.say("A long answer.")
        time.sleep(0.2)
        assert q.is_speaking
        q.interrupt()                     # the user pressed stop
        assert not q.is_speaking          # mic may listen again immediately
    finally:
        q.shutdown()


# ---------------------------------------------------------------- session
class FakeAssistant:
    def __init__(self, result, sentences=()):
        self.result, self.sentences = result, sentences
        self.questions = []

    def respond(self, question, speak, context="", page_text="", cancel=None):
        self.questions.append(question)
        for s in self.sentences:
            speak(s)
        return self.result


def _session(assistant):
    from relay.session import Session
    spoken = []
    return Session(speak=spoken.append, db_path=":memory:", assistant=assistant), spoken


def test_unknown_request_goes_to_the_assistant():
    fa = FakeAssistant(("answer", "A tabby cat."), ["A tabby cat."])
    s, spoken = _session(fa)
    try:
        s.handle("what's a good name for a striped kitten")
        assert fa.questions == ["what's a good name for a striped kitten"]
        assert "A tabby cat." in spoken and s.runner.last_said == "A tabby cat."
    finally:
        s.close()


def test_known_commands_never_reach_the_assistant():
    fa = FakeAssistant(("answer", "x"))
    s, spoken = _session(fa)
    try:
        s.handle("what time is it")
        assert fa.questions == []
    finally:
        s.close()


def test_assistant_command_is_announced_then_run_offline():
    fa = FakeAssistant(("command", "what time is it"))
    s, spoken = _session(fa)
    try:
        s.handle("could you check the clock for me")
        joined = " ".join(spoken)
        assert "I understood that as: what time is it." in joined
        assert "It's" in joined or ":" in joined           # the time was spoken
    finally:
        s.close()


def test_offline_assistant_says_so_plainly():
    s, spoken = _session(FakeAssistant(("offline", "")))
    try:
        s.handle("tell me a joke about cats")
        assert any("can't reach the AI assistant" in t for t in spoken)
    finally:
        s.close()


def test_stop_cancels_a_streaming_answer():
    s, spoken = _session(FakeAssistant(("answer", "")))
    try:
        s.stop_speaking()
        assert s._answer_cancel.is_set()
    finally:
        s.close()


def test_without_assistant_unknown_is_still_explained():
    s, spoken = _session(None)
    try:
        s.handle("what's a good name for a striped kitten")
        assert any("didn't understand" in t for t in spoken)
    finally:
        s.close()


def test_routes_from_env_override_config(monkeypatch, tmp_path):
    from relay.config import Config
    from relay.llm import routes_from_config
    monkeypatch.setenv("RELAY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RELAY_OFFLINE")
    assert routes_from_config(Config()) == []                 # off by default
    monkeypatch.setenv("RELAY_LLM_URL", "http://localhost:3001/v1")
    monkeypatch.setenv("RELAY_LLM_KEY", "freellmapi-abc")
    routes = routes_from_config(Config())
    assert [r.model for r in routes] == ["auto:fast", "auto"]
    assert all(r.api_key == "freellmapi-abc" for r in routes)
    dev = routes[0].extra_headers["X-Relay-Device"]
    assert len(dev) == 32 and routes_from_config(Config())[0].extra_headers[
        "X-Relay-Device"] == dev                              # stable per install


def test_local_router_on_another_port_is_found(monkeypatch):
    """The FreeLLMAPI desktop app uses port 31415, Docker/source 3001: a local URL with
    the wrong port finds the one that is actually listening. Remote URLs are left alone."""
    import socket

    import relay.llm as llm
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        monkeypatch.setattr(llm, "_LOCAL_PORTS", (port,))
        assert llm._local_router("http://localhost:9/v1") == f"http://127.0.0.1:{port}/v1"
        here = f"http://127.0.0.1:{port}/v1"
        assert llm._local_router(here) == here
        assert llm._local_router("https://gw.example.com/v1") == "https://gw.example.com/v1"
    finally:
        srv.close()
