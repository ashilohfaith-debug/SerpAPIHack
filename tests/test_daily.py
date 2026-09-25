"""Everyday-use features: normaliser, grammar coverage, keys, calculator, reminders,
notes, reader, speech callbacks, the half-duplex push-to-talk loop, the dispatcher,
app/web/file/window helpers, hotkeys, and Session turn-taking. Headless — nothing
here touches the user's desktop."""

from __future__ import annotations

import datetime as dt
import threading
import time
import zipfile

import numpy as np
import pytest

from relay.intent import Kind, parse
from relay.intent.normalize import apply_spoken_punctuation, normalize


# ---------------------------------------------------------------- normaliser
def test_normalize_strips_fillers_politeness_and_punctuation():
    assert normalize("Um, can you open Chrome for me, please?") == "open chrome"
    assert normalize("So what time is it now?") == "what time is it"
    assert normalize("OK stop.") == "stop"
    assert normalize("help me open notepad") == "open notepad"
    assert normalize("help me with reading") == "help me with reading"
    assert normalize("what is 1,200 plus 5") == "what is 1,200 plus 5"
    assert normalize("type thank you", strip_trailing=False) == "type thank you"


def test_spoken_punctuation():
    assert apply_spoken_punctuation("hello comma how are you question mark") == \
        "hello, how are you?"
    assert apply_spoken_punctuation("first line new line second") == "first line\nsecond"
    assert apply_spoken_punctuation("done full stop") == "done."


# ---------------------------------------------------------------- grammar table
@pytest.mark.parametrize("utt,kind,slots", [
    ("Um, can you open Chrome for me, please?", Kind.OPEN_APP, {"app": "chrome"}),
    ("What's the time?", Kind.TIME, {}),
    ("what is today's date", Kind.DATE, {}),
    ("How much battery do I have?", Kind.BATTERY, {}),
    ("Am I connected to the internet?", Kind.INTERNET, {}),
    ("what is 25 times 4", Kind.CALCULATE, {}),
    ("search for bus stop near me", Kind.WEB_SEARCH, {"query": "bus stop near me"}),
    ("Play Arijit Singh songs on YouTube.", Kind.YOUTUBE, {"query": "arijit singh songs"}),
    ("what apps are open", Kind.LIST_WINDOWS, {}),
    ("close notepad", Kind.WINDOW_OP, {"op": "close", "target": "notepad"}),
    ("close tab", Kind.SHORTCUT, {"keys": ["ctrl", "w"]}),
    ("press control s", Kind.HOTKEY, {"keys": ["ctrl", "s"]}),
    ("press down arrow 3 times", Kind.PRESS_KEY, {"key": "down", "count": 3}),
    ("read this page in Hindi", Kind.READ_ALL, {"language": "hindi"}),
    ("next paragraph", Kind.READ_NEXT, {}),
    ("stop reading", Kind.CONTROL, {"command": "stop_talking"}),
    ("pause music", Kind.MEDIA, {"action": "play_pause"}),
    ("set the volume to 40 percent", Kind.VOLUME, {"action": "set", "level": 40}),
    ("take a note buy milk", Kind.TAKE_NOTE, {"text": "buy milk"}),
    ("remind me in 10 minutes to call mom", Kind.SET_REMINDER, {}),
    ("cancel my reminders", Kind.CANCEL_REMINDERS, {}),
    ("stop dictation", Kind.DICTATION, {"on": False}),
    ("turn on connected mode", Kind.CONNECTED, {"on": True}),
    ("speak in Telugu", Kind.LANGUAGE, {"language": "telugu"}),
    ("find my resume", Kind.FIND_FILE, {"name": "resume"}),
    ("read the pdf electricity bill", Kind.OPEN_FILE, {"name": "electricity bill"}),
    ("click the second link", Kind.ACTIVATE, {"ordinal": 2, "role": "link"}),
    ("open the second one", Kind.PICK, {"ordinal": 2}),
    ("save as project report", Kind.SAVE, {"name": "project report"}),
    ("quit relay", Kind.QUIT, {}),
    ("help me with reading", Kind.HELP, {"topic": "reading"}),
])
def test_grammar_routes_daily_commands(utt, kind, slots):
    i = parse(utt)
    assert i.kind == kind, (utt, i.kind, i.slots)
    for k, v in slots.items():
        assert i.slots.get(k) == v, (utt, k, i.slots)


def test_control_words_only_at_start_of_short_utterance():
    assert parse("stop").kind == Kind.CONTROL
    assert parse("search for bus stop").kind == Kind.WEB_SEARCH
    assert parse("cancel").slots["command"] == "cancel_task"
    assert parse("emergency stop").slots["command"] == "emergency_stop"


def test_type_keeps_dictated_words():
    assert parse("type thank you").slots["text"] == "thank you"
    assert parse("Type Hello, how are you?").slots["text"] == "Hello, how are you?"


def test_parse_keys():
    from relay.intent.grammar import parse_keys
    assert parse_keys("control shift t") == (["ctrl", "shift", "t"], 1)
    assert parse_keys("alt f 4") == (["alt", "f4"], 1)
    assert parse_keys("page down twice") == (["pagedown"], 2)
    assert parse_keys("the second button") is None


# ---------------------------------------------------------------- calculator
@pytest.mark.parametrize("q,expect", [
    ("what is 25 times 4", "100"), ("what's 10 percent of 250", "25"),
    ("5 into 3", "15"), ("square root of 144", "12"), ("twenty five plus five", "30"),
    ("2 lakh by 12", "16666.6667"), ("one point five times two", "3"),
    ("5 squared", "25"), ("1,200 minus 200", "1000"),
])
def test_calculator(q, expect):
    from relay.system import calc
    ans = calc.answer(q)
    assert ans is not None and ans.endswith(f"is {expect}."), ans


def test_calculator_rejects_non_maths_and_handles_zero():
    from relay.system import calc
    assert calc.answer("what is on my screen") is None
    assert calc.answer("open 2 notepads") is None
    assert "divide by zero" in calc.answer("5 divided by 0")


# ---------------------------------------------------------------- reminders
NOW = dt.datetime(2026, 9, 25, 15, 0, 0)


def test_parse_reminder_relative_absolute_timer():
    from relay.reminders import parse_reminder
    due, msg, timer = parse_reminder("remind me in 10 minutes to call mom", NOW)
    assert due == NOW + dt.timedelta(minutes=10) and msg == "call mom" and not timer
    due, msg, _ = parse_reminder("remind me to take medicine at 5 pm", NOW)
    assert (due.hour, due.minute, due.date()) == (17, 0, NOW.date()) and msg == "take medicine"
    due, msg, _ = parse_reminder("remind me tomorrow at 9 am to submit the form", NOW)
    assert due == dt.datetime(2026, 9, 26, 9, 0) and msg == "submit the form"
    due, _, timer = parse_reminder("set a timer for five minutes", NOW)
    assert timer and due == NOW + dt.timedelta(minutes=5)
    due, _, _ = parse_reminder("remind me in half an hour to stretch", NOW)
    assert due == NOW + dt.timedelta(minutes=30)
    assert parse_reminder("remind me to call mom", NOW) is None


def test_reminder_scheduler_fires_once_and_cancels():
    from relay.memory.db import connect
    from relay.reminders import ReminderScheduler
    fired = []
    clock = {"t": 1000.0}
    sch = ReminderScheduler(connect(":memory:"), on_due=lambda t, late: fired.append(t),
                            clock=lambda: clock["t"])
    sch.add("call mom", 1010.0)
    sch.add("later", 5000.0)
    assert sch.check_now() == [] and fired == []
    clock["t"] = 1011.0
    assert [t for t, _ in sch.check_now()] == ["call mom"]
    assert sch.check_now() == []                     # never fires twice
    assert sch.cancel_all() == 1 and sch.pending() == []


# ---------------------------------------------------------------- notes
def test_notes_add_list_refuse_secret_delete():
    from relay.memory.db import connect
    from relay.memory.notes import NotesStore
    n = NotesStore(connect(":memory:"))
    assert n.add("buy milk")
    assert not n.add("my password is hunter2")
    assert n.count() == 1 and "Note 1: buy milk." in n.spoken()
    assert n.delete_all() == 1 and "don't have any notes" in n.spoken()


# ---------------------------------------------------------------- reader
def test_split_parts_merges_tiny_lines_and_splits_long_paragraphs():
    from relay.reading import split_parts
    long = " ".join(f"Sentence number {i} is here." for i in range(60))
    parts = split_parts("Home\nNews\nSports\n\n" + long)
    assert parts[0].startswith("Home") and "Sports" in parts[0]
    assert all(len(p) <= 440 for p in parts) and len(parts) > 3


class FakeSpeech:
    """Speaks instantly unless 'hold' is set; records parts and completion."""

    def __init__(self):
        self.spoken = []
        self.pending = []

    def speak_part(self, text, on_done):
        self.spoken.append(text)
        if on_done is not None:
            self.pending.append(on_done)

    def finish_one(self, completed=True):
        cb = self.pending.pop(0)
        cb(completed)


def _reader(fs, said):
    from relay.reading import Reader
    return Reader(speak_part=fs.speak_part, say=said.append,
                  interrupt=lambda: [cb(False) for cb in list(fs.pending)] and
                  fs.pending.clear())


def test_reader_say_all_stop_resume_next_prev_repeat():
    fs, said = FakeSpeech(), []
    r = _reader(fs, said)
    text = "\n\n".join(f"Paragraph {i} " + "word " * 20 for i in range(1, 5))
    assert r.load(text, title="Doc") == 4
    r.read_all()
    assert fs.spoken[-1].startswith("Paragraph 1")
    fs.finish_one(True)                       # part 1 done -> part 2 starts
    assert fs.spoken[-1].startswith("Paragraph 2")
    r.stop()                                  # user says stop during part 2
    assert r.pos == 1 and not r.reading
    r.resume()                                # continue -> part 2 again, from the start
    assert fs.spoken[-1].startswith("Paragraph 2")
    fs.finish_one(True)
    assert fs.spoken[-1].startswith("Paragraph 3")
    r.step(-1)
    assert fs.spoken[-1].startswith("Paragraph 2")
    r.repeat()
    assert fs.spoken[-1].startswith("Paragraph 2")
    r.step(+1)
    r.step(+1)
    r.step(+1)                                # past the end
    assert any("last part" in s for s in said)


# ---------------------------------------------------------------- speech queue
def test_speech_on_done_completed_and_interrupted():
    from relay.audio.speech import SpeechQueue

    class TTS:
        def synth_to_array(self, text):
            return np.ones(1600, dtype=np.float32), 16000

    gate = threading.Event()

    def player(audio, sr, stop):
        if not gate.is_set():
            stop.wait(2.0)

    q = SpeechQueue(TTS(), player=player)
    try:
        results = []
        gate.set()
        q.say("quick", on_done=results.append)
        assert q.wait_idle(3.0) and results == [True]
        gate.clear()
        q.say("long", on_done=results.append)
        q.say("queued", on_done=results.append)
        time.sleep(0.2)
        q.interrupt()
        assert q.wait_idle(3.0)
        assert results[1:] == [False, False] or sorted(results[1:]) == [False, False]
        played = []
        q.play(np.zeros(100, dtype=np.float32), 16000, on_done=played.append)
        gate.set()
        assert q.wait_idle(3.0) and played == [True]
    finally:
        q.shutdown()


# ---------------------------------------------------------------- voice loop
class ScriptSeg:
    """Segmenter that reports speech start/end from a list of booleans per frame."""

    def __init__(self, script):
        self.script = script
        self._in = False
        self.i = 0

    def push(self, frame):
        speech = self.script[self.i] if self.i < len(self.script) else False
        self.i += 1
        if not self._in and speech:
            self._in = True
            return "start"
        if self._in and not speech:
            self._in = False
            return "end"
        return None

    @property
    def in_speech(self):
        return self._in


class FakeSpeechQ:
    def __init__(self):
        self.is_speaking = False
        self.last_active = 0.0
        self.interrupted = 0

    def interrupt(self):
        self.interrupted += 1


def _frame():
    from relay.audio.vad import FRAME_BYTES
    return b"\x01\x00" * (FRAME_BYTES // 2)


def test_push_to_talk_captures_preroll_and_dispatches_prompted():
    from relay.loop import VoiceLoop
    got, earcons = [], []

    class STT:
        def transcribe(self, audio):
            got.append(len(audio))
            return "open notepad"

    script = [False, False, True, True, True, False]
    clock = {"t": 100.0}
    sq = FakeSpeechQ()
    dispatched = []
    loop = VoiceLoop(dispatched.append, stt=STT(), speech=sq, wake_required=False,
                     segmenter_factory=lambda: ScriptSeg(script),
                     play_earcon=earcons.append, clock=lambda: clock["t"], threaded=False)
    loop.push_to_talk()
    assert sq.interrupted == 1 and earcons == ["listen"]
    for _ in range(len(script)):
        loop.on_frame(_frame())
    assert dispatched == ["open notepad"] and "heard" in earcons
    # preroll: frames before "start" were kept, so audio > the 3 speech frames
    assert got and got[0] >= 5 * 480


def test_half_duplex_ignores_mic_while_relay_speaks():
    from relay.loop import VoiceLoop
    sq = FakeSpeechQ()
    sq.is_speaking = True
    dispatched = []
    loop = VoiceLoop(dispatched.append, stt=object(), speech=sq, wake_required=True,
                     segmenter_factory=lambda: ScriptSeg([True] * 10 + [False]),
                     threaded=False)
    for _ in range(11):
        loop.on_frame(_frame())
    assert dispatched == [] and not loop._in_utt


def test_push_to_talk_times_out_with_earcon():
    from relay.loop import VoiceLoop
    clock = {"t": 0.0}
    earcons = []
    loop = VoiceLoop(lambda t: None, stt=object(), speech=FakeSpeechQ(), wake_required=False,
                     segmenter_factory=lambda: ScriptSeg([False] * 50),
                     play_earcon=earcons.append, clock=lambda: clock["t"], threaded=False)
    loop.push_to_talk()
    clock["t"] = 60.0
    loop.on_frame(_frame())
    assert earcons[-1] == "nothing" and not loop._armed


def test_immediate_control_and_dispatcher_order():
    from relay.loop import Dispatcher, immediate_control
    assert immediate_control("stop") == "stop_talking"
    assert immediate_control("emergency stop") == "emergency_stop"
    assert immediate_control("stop dictation") == "stop_talking"   # still immediate
    assert immediate_control("search for bus stop") is None
    assert immediate_control("open notepad") is None

    order, gate = [], threading.Event()

    class S:
        def handle(self, text):
            if text == "slow":
                gate.wait(2)
            order.append(text)

        def say(self, *a, **k):
            pass

    d = Dispatcher(S())
    d.submit("slow")
    d.submit("second")
    time.sleep(0.1)
    d.submit("stop")                 # jumps the queue while "slow" is still running
    assert order == ["stop"]
    gate.set()
    for _ in range(50):
        if len(order) == 3:
            break
        time.sleep(0.02)
    assert order == ["stop", "slow", "second"]
    d.stop()


def test_hallucination_filter():
    from relay.loop import is_hallucination
    assert is_hallucination("Thank you.") and is_hallucination("  ") and is_hallucination("♪")
    assert not is_hallucination("open notepad")


# ---------------------------------------------------------------- apps / web / windows
def test_app_catalog_matching():
    from relay.system.apps import AppCatalog, AppEntry
    cat = AppCatalog(entries=[
        AppEntry("Word", "w"), AppEntry("WordPad", "wp"), AppEntry("WhatsApp", "wa"),
        AppEntry("Google Chrome", "c"), AppEntry("Uninstall Chrome", "u"),
        AppEntry("File Explorer", "fe"), AppEntry("Calculator", "calc")])
    assert cat.find("word").name == "Word"
    assert cat.find("whatsapp").name == "WhatsApp"
    assert cat.find("chrome").name == "Google Chrome"
    assert cat.find("files").name == "File Explorer"
    assert cat.find("calc").name == "Calculator"
    assert cat.find("zebra stripes") is None


def test_web_helpers():
    from relay.system import web
    assert web.site_url("youtube") == "https://www.youtube.com"
    assert web.site_url("flipkart dot com") == "https://flipkart.com"
    assert web.site_url("notepad") is None
    assert web.search_url("weather in delhi").endswith("q=weather+in+delhi")
    assert "search_query=lofi+music" in web.youtube_url("lofi music")


def test_window_find_and_spoken_list():
    from relay.system.windows import WindowInfo, find, spoken_list
    wins = [WindowInfo(1, "Untitled - Notepad", "notepad.exe"),
            WindowInfo(2, "Inbox - Gmail - Google Chrome", "chrome.exe"),
            WindowInfo(3, "Document1 - Word", "WINWORD.EXE", True)]
    assert find("notepad", wins).hwnd == 1
    assert find("chrome", wins).hwnd == 2
    assert find("gmail", wins).hwnd == 2
    assert find("word", wins).hwnd == 3
    assert find("nothing", wins) is None
    text = spoken_list(wins)
    assert text.startswith("3 windows are open") and "(minimized)" in text


def test_find_and_read_files(tmp_path):
    from relay.system import files
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "My_Resume_2026.txt").write_text("Resume body", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    docx = tmp_path / "letter.docx"
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body><w:p><w:r><w:t>Dear Sir,</w:t></w:r></w:p><w:p><w:r><w:t>Thanks.</w:t>'
           '</w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", xml)
    hits = files.find_files("my resume", roots=[tmp_path])
    assert hits and hits[0].path.name == "My_Resume_2026.txt"
    assert files.read_file_text(hits[0].path) == "Resume body"
    assert files.read_file_text(docx) == "Dear Sir,\n\nThanks."
    assert files.find_files("zebra", roots=[tmp_path]) == []


# ---------------------------------------------------------------- hotkeys
def test_parse_and_speak_combos():
    from relay.audio.hotkeys import MOD_ALT, MOD_CONTROL, parse_combo, spoken_combo
    assert parse_combo("ctrl+alt+space") == (MOD_CONTROL | MOD_ALT, 0x20)
    assert parse_combo("ctrl+alt+period")[1] == 0xBE
    assert spoken_combo("ctrl+alt+space") == "Control Alt Space"
    with pytest.raises(ValueError):
        parse_combo("hyper+q")


def test_real_hotkey_registration_and_delivery():
    """Registers an unusual global hotkey and presses it with SendInput."""
    import ctypes

    from relay.audio.hotkeys import HotkeyManager
    fired = threading.Event()
    hk = HotkeyManager()
    hk.add("ctrl+alt+shift+f11", fired.set)
    ok = hk.start().get("ctrl+alt+shift+f11")
    if not ok:
        hk.stop()
        pytest.skip("combination in use on this machine")
    try:
        ke = ctypes.windll.user32.keybd_event
        for vk in (0x11, 0x12, 0x10, 0x7A):
            ke(vk, 0, 0, 0)
        for vk in (0x7A, 0x10, 0x12, 0x11):
            ke(vk, 0, 2, 0)
        assert fired.wait(2.0)
    finally:
        hk.stop()


# ---------------------------------------------------------------- verifier fix
def test_cancelled_action_is_never_verified():
    from relay.executor.executor import ActionOutcome
    from relay.memory.journal import ExecState
    from relay.verifier import Verifier
    vf = Verifier(worker=None)
    o = ActionOutcome("t.a1", ExecState.CANCELLED, "emergency stop engaged")
    assert vf.verify(o, True).state == ExecState.CANCELLED


# ---------------------------------------------------------------- runner step kinds
def test_runner_system_step_speaks_verified_detail_and_silent_keypress():
    from relay.memory.journal import ExecState
    from relay.memory.task_context import TaskContext
    from relay.perception.semantic import ScreenSnapshot
    from relay.planner.planner import Step
    from relay.planner.runner import TransparentRunner

    class Out:
        def __init__(self, state, detail=""):
            self.state, self.detail = state, detail

    class Ex:
        def system(self, what, fn, label=""):
            return Out(ExecState.EXECUTED if fn() else ExecState.FAILED)

        def press(self, key, count=1):
            return Out(ExecState.EXECUTED, f"pressed {key}")

    class Vf:
        def verify(self, o, ok, detail=""):
            if o.state != ExecState.EXECUTED:
                return o
            return Out(ExecState.VERIFIED if ok else ExecState.UNCERTAIN, detail)

    class W:
        def observe(self, timeout=2):
            return ScreenSnapshot(1, foreground_title="X")

    spoken = []
    ctx = TaskContext("t")
    r = TransparentRunner(Ex(), W(), Vf(), ctx, speak=spoken.append)
    r.run([Step("system", "change the volume", {
        "what": "volume", "do": lambda: True,
        "check": lambda: (True, "Volume is now 60 percent."),
        "announce": "Turning the volume up.", "speak_detail": True})])
    assert spoken == ["Turning the volume up.", "Volume is now 60 percent."]
    spoken.clear()
    r.run([Step("press", "press play/pause", {"key": "playpause",
                                              "announce": "Pressing play/pause.",
                                              "done_text": ""})])
    assert spoken == ["Pressing play/pause."]         # honest: no fake "done"


# ---------------------------------------------------------------- session flows
@pytest.fixture
def session(monkeypatch, tmp_path):
    monkeypatch.setenv("RELAY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    from relay.executor.input_backend import RecordingBackend
    from relay.session import Session
    spoken: list[str] = []
    s = Session(speak=spoken.append, db_path=":memory:")
    s.executor.input = RecordingBackend()
    s.spoken = spoken
    yield s
    s.close()


def test_session_dictation_types_with_punctuation(session):
    session.set_dictation(True)
    session.handle("hello comma world full stop")
    assert ("type_text", "hello, world. ") in session.executor.input.calls
    assert any(t.startswith("Typed: hello, world.") for t in session.spoken)
    session.handle("stop dictation")
    assert session.dictation is False


def test_session_offer_yes_no_and_capture(session):
    ran = []
    session.offer(lambda: ran.append(1))
    session.handle("no thanks")
    assert ran == []
    session.offer(lambda: ran.append(1))
    session.handle("okay")
    assert ran == [1]
    session.handle("take a note")                      # asks what to write
    assert any("What should the note say" in t for t in session.spoken)
    session.handle("call the plumber")
    assert session.notes.count() == 1


def test_session_emergency_then_continue_resets(session):
    session.handle("emergency stop")
    assert session.emergency.is_engaged
    session.handle("continue")
    assert not session.emergency.is_engaged
    assert any("cleared" in t for t in session.spoken)


def test_session_quit_and_reminder_speech(session):
    quit_called = []
    session.on_quit = lambda: quit_called.append(1)
    session.handle("quit relay")
    assert quit_called == [1]
    session._on_reminder("take medicine", 0)
    assert any(t.startswith("Reminder: take medicine") for t in session.spoken)


def test_session_connected_mode_requires_key_then_phrase(session, monkeypatch):
    session.handle("turn on connected mode")
    assert session.connected is None and any("Sarvam" in t for t in session.spoken)
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    session.handle("turn on connected mode")
    assert session._pending is not None and session._pending.phrase == "confirm connect"
    session.handle("yes")                               # a bare yes is not consent
    assert session.connected is None
    session.handle("confirm connect")
    assert session.connected is not None
    session.handle("turn off connected mode")
    assert session.connected is None


def test_session_nlu_fallback_is_validated(session, monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    session._enable_connected()

    class FakeClient:
        def __init__(self, answer):
            self.answer = answer

        def chat(self, *a, **k):
            return self.answer

    session.connected.client = FakeClient("what time is it")
    session.handle("could you tell me what hour it is right now")
    assert any("I understood that as: what time is it" in t for t in session.spoken)
    assert any(t.startswith("It's ") for t in session.spoken)
    session.spoken.clear()
    session.connected.client = FakeClient("confirm delete")      # never accepted
    session.handle("blorp the flarn")
    assert not any("understood" in t for t in session.spoken)


def test_session_speech_rate_persists(session):
    session.handle("speak faster")
    assert session.speech_rate > 1.0
    assert float(session.store.get_pref("speech_rate")) == pytest.approx(session.speech_rate)


def test_send_in_chat_app_reads_back_and_needs_phrase(session, monkeypatch):
    assert parse("send the message").kind == Kind.SEND
    monkeypatch.setattr(session.skills, "_fg_app", lambda: "whatsapp.root.exe")
    monkeypatch.setattr(session.skills, "_focus_value", lambda: "see you at 5")
    session.handle("press enter")
    assert session._pending is not None and session._pending.phrase == "confirm send"
    assert any("see you at 5" in t for t in session.spoken)
    assert ("press", "enter") not in session.executor.input.calls     # not sent yet
    session.handle("yeah")                                            # not the phrase
    assert ("press", "enter") not in session.executor.input.calls


def test_delete_key_in_file_explorer_needs_phrase(session, monkeypatch):
    monkeypatch.setattr(session.skills, "_fg_app", lambda: "explorer.exe")
    session.handle("press delete")
    assert session._pending is not None and session._pending.phrase == "confirm delete"
    assert ("press", "delete") not in session.executor.input.calls
    session.handle("cancel")
    assert session._pending is None


def test_connected_wake_gate_keeps_ambient_speech_on_device():
    from relay.loop import VoiceLoop

    class Local:
        def __init__(self, text):
            self.text = text

        def transcribe(self, audio):
            return self.text

    class Cloud:
        def __init__(self):
            self.calls = 0

        def transcribe(self, audio):
            self.calls += 1
            return "Relay, what time is it?"

    cloud, dispatched = Cloud(), []
    loop = VoiceLoop(dispatched.append, stt=cloud, wake_required=True, threaded=False)
    loop.wake_stt = Local("so I told him about the meeting")
    loop.on_utterance(b"\x01\x00" * 800)
    assert cloud.calls == 0 and dispatched == []        # never left the device
    loop.wake_stt = Local("Relay, abhi kitne baje hain")
    loop.on_utterance(b"\x01\x00" * 800)
    assert cloud.calls == 1 and dispatched == ["what time is it?"]
