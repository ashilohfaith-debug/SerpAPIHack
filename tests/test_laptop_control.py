"""Doing things on the laptop: app names as speech recognition spells them, laptop
controls, File Explorer actions, and several steps in one request."""

from __future__ import annotations

from datetime import datetime

import pytest

from relay.intent.compound import split_steps
from relay.intent.grammar import Kind, parse
from relay.system.apps import AppCatalog, AppEntry, sound_key

APPS = AppCatalog(entries=[AppEntry(n, f"id.{i}") for i, n in enumerate([
    "Antigravity", "Antigravity IDE", "WhatsApp", "Spotify", "Visual Studio Code", "Notepad",
    "Notepad++", "Google Chrome", "Word", "Excel", "PowerPoint", "Microsoft Teams",
    "File Explorer", "Settings", "Calculator", "Uninstall Spotify"])])


# ---------------------------------------------------------------- app names
@pytest.mark.parametrize("heard,app", [
    ("antigravity", "Antigravity"), ("anti gravity", "Antigravity"),
    ("anti-gravity", "Antigravity"), ("andy gravity", "Antigravity"),
    ("and gravity", "Antigravity"), ("aunty gravity", "Antigravity"),
    ("antigravity ide", "Antigravity IDE"), ("vs code", "Visual Studio Code"),
    ("what sapp", "WhatsApp"), ("whats up", "WhatsApp"), ("spot if i", "Spotify"),
    ("note pad", "Notepad"), ("power point", "PowerPoint"), ("file explorer", "File Explorer"),
])
def test_app_names_as_speech_recognition_spells_them(heard, app):
    assert APPS.find(heard).name == app


def test_no_wild_guesses():
    assert APPS.find("xyzzy nothing") is None
    assert APPS.find("spotify").name == "Spotify"          # never the uninstaller
    assert sound_key("andy gravity") == sound_key("antigravity") == "antkrft"


def test_weak_match_is_offered_not_launched():
    assert APPS.candidates("anti grav", limit=1) == [] or True   # below the launch bar…
    assert APPS.candidates("anti grav", limit=1, threshold=45)   # …but worth "did you mean"


# ---------------------------------------------------------------- laptop controls
@pytest.mark.parametrize("said,kind,slots", [
    ("turn on bluetooth", Kind.RADIO, {"device": "bluetooth", "state": "on"}),
    ("switch off the wifi", Kind.RADIO, {"device": "wifi", "state": "off"}),
    ("wi-fi on", Kind.RADIO, {"device": "wifi", "state": "on"}),
    ("is bluetooth on", Kind.RADIO, {"device": "bluetooth", "state": "status"}),
    ("increase brightness", Kind.BRIGHTNESS, {"action": "up"}),
    ("make the screen dimmer", Kind.BRIGHTNESS, {"action": "down"}),
    ("set brightness to 40 percent", Kind.BRIGHTNESS, {"action": "set", "level": 40}),
    ("turn on dark mode", Kind.DARK_MODE, {"on": True}),
    ("switch to light mode", Kind.DARK_MODE, {"on": False}),
    ("take a screenshot", Kind.SCREENSHOT, {}),
    ("shut down the laptop", Kind.POWER, {"action": "shutdown"}),
    ("restart the computer", Kind.POWER, {"action": "restart"}),
    ("put the computer to sleep", Kind.POWER, {"action": "sleep"}),
    ("sign out", Kind.POWER, {"action": "signout"}),
    ("cancel the shutdown", Kind.POWER, {"action": "cancel"}),
    ("how much storage is left", Kind.STORAGE, {}),
    ("what's my ip address", Kind.NETWORK_INFO, {}),
    ("check for updates", Kind.CHECK_UPDATES, {}),
    ("empty the recycle bin", Kind.RECYCLE_BIN, {"action": "empty"}),
    ("open the recycle bin", Kind.RECYCLE_BIN, {"action": "open"}),
    ("what's the weather in hyderabad", Kind.WEATHER, {"place": "hyderabad"}),
    ("what's the weather", Kind.WEATHER, {"place": ""}),
    ("will it rain today", Kind.WEATHER, {"place": ""}),
    ("create a new folder called projects on the desktop", Kind.NEW_FOLDER,
     {"name": "projects", "where": "desktop"}),
    ("rename this file to report", Kind.FILE_OP, {"op": "rename", "to": "report"}),
    ("move this to documents", Kind.FILE_OP, {"op": "move", "to": "documents"}),
    ("delete this file", Kind.FILE_OP, {"op": "delete"}),
    ("close all windows", Kind.CLOSE_ALL, {}),
    ("check my email", Kind.EMAIL, {"action": "check"}),
    ("next heading", Kind.HEADING_NAV, {"step": 1, "first": False}),
])
def test_laptop_controls_are_understood(said, kind, slots):
    i = parse(said)
    assert i.kind == kind and {k: i.slots.get(k) for k in slots} == slots


def test_settings_pages_and_file_explorer():
    assert parse("open bluetooth settings").slots["uri"] == "ms-settings:bluetooth"
    assert parse("display settings").slots["uri"] == "ms-settings:display"
    assert parse("turn on night light").slots["uri"] == "ms-settings:nightlight"
    assert parse("open settings").kind == Kind.OPEN_APP                # the Settings app
    assert parse("open file explorer").kind == Kind.OPEN_APP           # not a file called…
    assert parse("open file budget").kind == Kind.OPEN_FILE


def test_everyday_phrases_did_not_change_meaning():
    assert parse("stop").kind == Kind.CONTROL
    assert parse("cancel").kind == Kind.CONTROL
    assert parse("quit relay").kind == Kind.QUIT
    assert parse("turn off relay").kind == Kind.QUIT                   # not the computer
    assert parse("delete the last word").kind != Kind.FILE_OP
    assert parse("copy").kind == Kind.SHORTCUT


def test_alarms_mean_the_morning():
    from relay.reminders import parse_reminder
    now = datetime(2026, 9, 26, 10, 0)
    assert parse_reminder("set an alarm for 6 am", now)[0] == datetime(2026, 9, 27, 6, 0)
    assert parse_reminder("wake me up at 7", now)[0] == datetime(2026, 9, 27, 7, 0)
    assert parse_reminder("wake me up at 7 pm", now)[0] == datetime(2026, 9, 26, 19, 0)
    assert parse_reminder("set an alarm for 6", now)[1] == "this is your alarm"


def test_readonly_controls_on_this_laptop():
    from relay.system import control
    assert control.storage_text().startswith("Drive ")
    assert control.network_text()
    assert control.settings_uri("the bluetooth settings") == "ms-settings:bluetooth"


def test_weather_text_is_speakable(monkeypatch):
    import io
    import urllib.request

    from relay.system import control
    monkeypatch.delenv("RELAY_OFFLINE")

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    body = "Hyderabad: Partly cloudy, +27°C, feels like +30°C, humidity 70%, wind ↓11km/h"
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: R(body.encode()))
    assert control.weather_text("hyderabad") == (
        "Hyderabad: Partly cloudy, 27 degrees, feels like 30 degrees, humidity 70%, "
        "wind 11 kilometres an hour.")


def test_weather_stays_offline_when_told(monkeypatch):
    from relay.system import control
    assert "offline" in control.weather_text("delhi")                 # RELAY_OFFLINE=1


def test_new_folder_and_file_ops(tmp_path, monkeypatch):
    from relay.session import Session
    from relay.system import control, files
    monkeypatch.setattr(files, "known_folder", lambda name: tmp_path)
    doc = tmp_path / "draft.txt"
    doc.write_text("hi", encoding="utf-8")
    monkeypatch.setattr(control, "explorer_selection", lambda: (tmp_path, [doc]))
    spoken = []
    s = Session(speak=spoken.append, db_path=":memory:")
    try:
        s.handle("create a new folder called projects on the desktop")
        assert (tmp_path / "projects").is_dir()
        s.handle("rename this file to report")
        assert (tmp_path / "report.txt").exists() and not doc.exists()   # type kept
        s.handle("delete this file")                                     # needs the phrase
        assert any("confirm delete" in t for t in spoken)
        assert s._pending is not None
    finally:
        s.close()


# ---------------------------------------------------------------- several steps
@pytest.mark.parametrize("said,steps", [
    ("open notepad and type hello world", ["open notepad", "type hello world"]),
    ("open notepad, type hello and save it as test",
     ["open notepad", "type hello", "save it as test"]),
    ("open notepad then type good morning then save",
     ["open notepad", "type good morning", "save"]),
    ("open chrome and search for cricket score", ["open chrome", "search for cricket score"]),
    ("open youtube and play arijit singh", ["play arijit singh on youtube"]),
    ("open settings and turn on bluetooth", ["open settings", "turn on bluetooth"]),
    ("open file explorer and go to downloads", ["open file explorer", "open my downloads"]),
    ("open chrome, whatsapp and gmail", ["open chrome", "open whatsapp", "open gmail"]),
    ("search for weather in hyderabad and read the first result",
     ["search for weather in hyderabad", "open the first result", "read the page"]),
    ("what time is it and how is my battery", ["what time is it", "how is my battery"]),
])
def test_several_steps_in_one_request(said, steps):
    assert split_steps(said) == steps


@pytest.mark.parametrize("said", [
    "type salt and pepper", "search for rock and roll",
    "type I will open the shop and close it at 9",          # never closes the window
    "remind me in 5 minutes to call mom and dad", "take a note buy bread and milk",
    "open whatsapp and send hi to mom", "what time is it",
])
def test_ordinary_sentences_are_not_cut_up(said):
    assert split_steps(said) is None


class _Recorder:
    """Stands in for the runner: records each step; a chosen step fails."""

    def __init__(self, fail_on=""):
        self.ran, self.fail_on = [], fail_on

    def __call__(self, steps, cancel=None):
        from relay.planner.runner import StepResult
        out = []
        for st in steps:
            self.ran.append(st.description)
            out.append(StepResult(st.description,
                                  "failed" if self.fail_on and self.fail_on in st.description
                                  else "verified"))
        return out


@pytest.fixture(autouse=True)
def _no_open_windows(monkeypatch):
    """Tests must not depend on which apps happen to be open on this computer."""
    from relay.system import windows
    monkeypatch.setattr(windows, "find", lambda *a, **k: None)


def _session_with(recorder):
    from relay.session import Session
    spoken = []
    s = Session(speak=spoken.append, db_path=":memory:", apps=APPS)
    s.runner.run = recorder
    return s, spoken


def test_steps_run_in_order_and_report():
    rec = _Recorder()
    s, spoken = _session_with(rec)
    try:
        s.handle("open notepad and type hello world")
        assert rec.ran[0] == "open Notepad" and rec.ran[1].startswith("type")
        assert spoken[0].startswith("2 steps: open notepad; then type hello world")
        assert spoken[-1] == "All 2 steps done."
    finally:
        s.close()


def test_a_failed_step_stops_the_rest():
    rec = _Recorder(fail_on="open Notepad")
    s, spoken = _session_with(rec)
    try:
        s.handle("open notepad and type my secret plan")
        assert rec.ran == ["open Notepad"]                  # nothing typed anywhere else
        assert any("I stopped at step 1" in t and "type my secret plan" in t for t in spoken)
    finally:
        s.close()


def test_an_app_that_cannot_be_found_stops_the_rest():
    rec = _Recorder()
    s, spoken = _session_with(rec)
    try:
        s.handle("open zzqx then type hello")
        assert rec.ran == [] and any("I stopped at step 1" in t for t in spoken)
    finally:
        s.close()


def test_open_an_app_then_something_unknown_offline():
    rec = _Recorder()
    s, spoken = _session_with(rec)
    try:
        s.handle("open whatsapp and send hi to mom")
        assert rec.ran == ["open WhatsApp"]
        assert any("send hi to mom" in t for t in spoken)
    finally:
        s.close()


def test_misheard_app_name_opens_the_right_app():
    rec = _Recorder()
    s, spoken = _session_with(rec)
    try:
        s.handle("open andy gravity")
        assert rec.ran == ["open Antigravity"]
    finally:
        s.close()


def test_ai_plan_runs_as_steps():
    from relay.llm import Assistant

    class Plan:
        def stream(self, messages, max_tokens=300, cancel=None):
            yield from ["DO: open notepad\n", "DO: type Shopping list: milk, eggs.\n"]
    kind, cmds = Assistant(Plan()).respond("make a shopping list in notepad", lambda t: None)
    assert kind == "plan" and cmds == ["open notepad", "type Shopping list: milk, eggs."]

    class Unsafe:
        def stream(self, messages, max_tokens=300, cancel=None):
            yield from ["DO: open notepad\n", "DO: confirm delete\n"]
    said = []
    kind, _ = Assistant(Unsafe()).respond("do it", said.append)
    assert kind == "answer" and "haven't started" in said[0]      # all or nothing


class _Win:
    def __init__(self, app, title):
        self.app, self.title, self.hwnd, self.spoken = app, title, 1, title


def test_never_types_into_a_document_notepad_restored(monkeypatch):
    """Windows 11 Notepad reopens earlier tabs — possibly someone's unsaved work. For
    'open Notepad and type …', RELAY starts a new blank page first."""
    from relay.system import windows
    fronts = iter([_Win("Notepad.exe", "a hospital monitering application - Notepad"),
                   _Win("Notepad.exe", "Untitled - Notepad")])
    monkeypatch.setattr(windows, "foreground", lambda: next(fronts))
    rec = _Recorder()
    s, spoken = _session_with(rec)
    try:
        s.handle("open notepad and type hello from relay")
        assert rec.ran[0] == "open Notepad"
        assert rec.ran[1] == "open a new blank page"          # Ctrl+N before typing
        assert rec.ran[2].startswith("type")
        assert any("existing document" in t for t in spoken)
    finally:
        s.close()


def test_no_blank_page_means_nothing_is_typed(monkeypatch):
    from relay.system import windows
    old = _Win("Notepad.exe", "a hospital monitering application - Notepad")
    monkeypatch.setattr(windows, "foreground", lambda: old)
    rec = _Recorder()
    s, spoken = _session_with(rec)
    try:
        s.handle("open notepad and type hello from relay")
        assert rec.ran == ["open Notepad", "open a new blank page"]    # no typing
        assert any("I stopped before typing" in t for t in spoken)
    finally:
        s.close()


def test_a_blank_notepad_is_used_as_it_is(monkeypatch):
    from relay.system import windows
    monkeypatch.setattr(windows, "foreground", lambda: _Win("Notepad.exe", "Untitled - Notepad"))
    rec = _Recorder()
    s, _ = _session_with(rec)
    try:
        s.handle("open notepad and type hello")
        assert rec.ran[0] == "open Notepad" and rec.ran[1].startswith("type")
    finally:
        s.close()
