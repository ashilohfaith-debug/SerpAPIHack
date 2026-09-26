"""Deterministic intent parsing — no LLM.

Maps a spoken/typed utterance to a structured Intent with slots. This is the
Essential-mode understanding layer: a bounded grammar of the commands a blind user
actually needs day to day, matched by patterns, so RELAY works fully offline. The
utterance is normalised first (fillers, politeness, recogniser punctuation), and
dictated payloads are taken from the raw text so their words are preserved. Anything
it can't map returns UNKNOWN, and the assistant asks rather than guessing.

Order matters: phrases that CONTAIN a control word ("stop dictation", "pause the
music", "cancel my reminders", "search for bus stop") are matched before the control
words themselves, and control words only match at the start of a short utterance.

Reference slots ("the second link", "that", "it") are extracted here and resolved
against live state later, so RELAY binds words to observed elements rather than
acting on a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from relay.audio.wake import Command, match_command  # reuse control-command matcher
from relay.intent.normalize import normalize, payload_after

ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "last": -1,
}


class Kind:
    DESCRIBE_SCREEN = "describe_screen"
    WHERE_AM_I = "where_am_i"
    WHAT_CHANGED = "what_changed"
    LIST_OPTIONS = "list_options"
    READ_FOCUS = "read_focus"
    OPEN_APP = "open_app"
    ACTIVATE = "activate"
    TYPE = "type"
    PRESS_KEY = "press_key"
    HOTKEY = "hotkey"
    SHORTCUT = "shortcut"
    SAVE = "save"
    GO_BACK = "go_back"
    SCROLL = "scroll"
    SWITCH_APP = "switch_app"
    HELP = "help"
    CONTROL = "control"     # stop/pause/continue/cancel/emergency/repeat
    READ_DIALOG = "read_dialog"
    NEXT_ELEMENT = "next_element"
    PREV_ELEMENT = "prev_element"
    SPELL = "spell"
    SET_MODE = "set_mode"
    CAPABILITIES = "capabilities"
    # memory (L3/L5) voice operations
    REMEMBER = "remember"
    WHAT_REMEMBER = "what_remember"
    WHY_REMEMBER = "why_remember"
    FORGET = "forget"
    CLEAR_HISTORY = "clear_history"
    EXPORT_PREFS = "export_prefs"
    WHAT_DOING = "what_doing"
    # everyday system
    TIME = "time"
    DATE = "date"
    BATTERY = "battery"
    INTERNET = "internet"
    STATUS = "status"
    VOLUME = "volume"
    MEDIA = "media"
    CALCULATE = "calculate"
    # web / files / windows
    WEB_SEARCH = "web_search"
    YOUTUBE = "youtube"
    FIND_FILE = "find_file"
    OPEN_FILE = "open_file"
    LIST_WINDOWS = "list_windows"
    WINDOW_OP = "window_op"
    SHOW_DESKTOP = "show_desktop"
    # reading
    READ_ALL = "read_all"
    READ_NEXT = "read_next"
    READ_PREV = "read_prev"
    READ_TITLE = "read_title"
    READ_CLIPBOARD = "read_clipboard"
    LIST_LINKS = "list_links"
    LIST_HEADINGS = "list_headings"
    OCR_READ = "ocr_read"
    # notes / reminders
    TAKE_NOTE = "take_note"
    READ_NOTES = "read_notes"
    DELETE_NOTES = "delete_notes"
    SET_REMINDER = "set_reminder"
    LIST_REMINDERS = "list_reminders"
    CANCEL_REMINDERS = "cancel_reminders"
    # assistant settings
    SPEECH_RATE = "speech_rate"
    DICTATION = "dictation"
    LANGUAGE = "language"
    WAKE_WORD = "wake_word"
    HEADPHONES = "headphones"      # "headphone mode on/off/automatic", "I'm using headphones"
    AUDIO_STATUS = "audio_status"  # "where is the sound going", "am I using headphones"
    QUIT = "quit"
    PICK = "pick"           # "open the second one" — from the last list RELAY read out
    SEND = "send"           # send the message being written (always read back + confirmed)
    ASK = "ask"             # a question for the conversational assistant
    SUMMARIZE = "summarize" # "summarise this page" — the page text goes to the assistant
    # laptop controls (relay/system/control.py)
    RADIO = "radio"                # bluetooth / wifi: on | off | status
    BRIGHTNESS = "brightness"      # up | down | set | get
    DARK_MODE = "dark_mode"
    SCREENSHOT = "screenshot"
    POWER = "power"                # shutdown | restart | sleep | signout | cancel
    STORAGE = "storage"
    NETWORK_INFO = "network_info"
    CHECK_UPDATES = "check_updates"
    SETTINGS_PAGE = "settings_page"
    RECYCLE_BIN = "recycle_bin"    # open | empty
    WEATHER = "weather"
    NEW_FOLDER = "new_folder"
    FILE_OP = "file_op"            # rename | move | copy | delete — the selected item
    CLOSE_ALL = "close_all"
    HEADING_NAV = "heading_nav"    # next / previous heading on a page
    EMAIL = "email"                # check | compose
    UNKNOWN = "unknown"


@dataclass
class Intent:
    kind: str
    slots: dict = field(default_factory=dict)
    raw: str = ""


def _ordinal_in(text: str) -> int | None:
    for word, n in ORDINALS.items():
        if re.search(rf"\b{word}\b", text):
            return n
    m = re.search(r"\b(?:number\s+)?(\d+)(?:st|nd|rd|th)?\b", text)
    return int(m.group(1)) if m else None


_LANG_WORDS = ("english", "hindi", "telugu", "tamil", "kannada", "malayalam", "marathi",
               "gujarati", "bengali", "bangla", "punjabi", "odia", "oriya")
_LANG_RE = "|".join(_LANG_WORDS)

# ---- keys -------------------------------------------------------------------
_MODIFIERS = {"ctrl", "alt", "shift", "win"}
_KEY_WORDS = {
    "control": "ctrl", "ctrl": "ctrl", "ctl": "ctrl", "alt": "alt", "alter": "alt",
    "shift": "shift", "windows": "win", "window": "win", "win": "win", "start": "win",
    "escape": "esc", "esc": "esc", "enter": "enter", "return": "enter", "tab": "tab",
    "space": "space", "spacebar": "space", "backspace": "backspace", "delete": "delete",
    "del": "delete", "home": "home", "end": "end", "pageup": "pageup",
    "pagedown": "pagedown", "up": "up", "down": "down", "left": "left", "right": "right",
    "insert": "insert", "capslock": "capslock", "printscreen": "printscreen",
    "plus": "=", "equals": "=", "minus": "-", "dash": "-", "period": ".", "dot": ".",
    "comma": ",", "slash": "/", "menu": "apps",
}
_KEY_JOIN = [(r"page\s+up", "pageup"), (r"page\s+down", "pagedown"),
             (r"back\s+space", "backspace"), (r"caps\s+lock", "capslock"),
             (r"print\s+screen", "printscreen"), (r"space\s+bar", "space"),
             (r"\b(up|down|left|right)\s+arrow\b", r"\1"),
             (r"\barrow\s+(up|down|left|right)\b", r"\1"),
             (r"\bf\s+(\d{1,2})\b", r"f\1"), (r"\bfunction\s+(\d{1,2})\b", r"f\1")]
_COUNT = {"once": 1, "twice": 2, "two times": 2, "three times": 3, "thrice": 3,
          "four times": 4, "five times": 5}


def parse_keys(text: str) -> tuple[list[str], int] | None:
    """'control shift t' -> (['ctrl','shift','t'], 1); 'down arrow 3 times' ->
    (['down'], 3). None if any token isn't a key."""
    t = text.lower().strip()
    count = 1
    m = re.search(r"\b(once|twice|thrice|(?:two|three|four|five) times|(\d+) times)$", t)
    if m:
        count = int(m.group(2)) if m.group(2) else _COUNT.get(m.group(1), 1)
        t = t[:m.start()].strip()
    t = re.sub(r"^(?:the\s+)", "", t)
    t = re.sub(r"\s*(?:\+|-|\band\b|\bthen\b)\s*", " ", t)
    for pat, rep in _KEY_JOIN:
        t = re.sub(pat, rep, t)
    t = re.sub(r"\b(key|button|keys)\b", " ", t)
    keys: list[str] = []
    for tok in t.split():
        if tok in _KEY_WORDS:
            keys.append(_KEY_WORDS[tok])
        elif re.fullmatch(r"f(?:[1-9]|1[0-2])", tok) or re.fullmatch(r"[a-z0-9]", tok):
            keys.append(tok)
        else:
            return None
    if not keys:
        return None
    return keys, max(1, min(count, 20))


# ---- named shortcuts ----------------------------------------------------------
SHORTCUTS: list[tuple[str, tuple[str, ...], str]] = [
    (r"select (?:all|everything)(?: the text)?", ("ctrl", "a"), "select all"),
    (r"copy(?: that| this| it| the text| the selection)?", ("ctrl", "c"), "copy"),
    (r"paste(?: it| that| here| the text)?", ("ctrl", "v"), "paste"),
    (r"cut(?: that| this| it)?", ("ctrl", "x"), "cut"),
    (r"undo(?: that| it| the last (?:thing|change))?", ("ctrl", "z"), "undo"),
    (r"redo(?: that)?", ("ctrl", "y"), "redo"),
    (r"(?:open )?(?:a )?new tab", ("ctrl", "t"), "open a new tab"),
    (r"close (?:this |the |current )?tab", ("ctrl", "w"), "close this tab"),
    (r"(?:reopen|restore)(?: the)?(?: closed| last)? tab", ("ctrl", "shift", "t"),
     "reopen the closed tab"),
    (r"(?:next|switch) tab", ("ctrl", "tab"), "go to the next tab"),
    (r"previous tab", ("ctrl", "shift", "tab"), "go to the previous tab"),
    (r"(?:refresh|reload)(?: the| this)?(?: page)?", ("f5",), "reload the page"),
    (r"zoom in", ("ctrl", "="), "zoom in"),
    (r"zoom out", ("ctrl", "-"), "zoom out"),
    (r"(?:reset|normal) zoom|reset the zoom", ("ctrl", "0"), "reset the zoom"),
    (r"find (?:on|in) (?:this |the )?page|search (?:on |in )?this page",
     ("ctrl", "f"), "open find on the page"),
    (r"go forward|forward", ("alt", "right"), "go forward"),
    (r"(?:go to |focus )?(?:the )?address bar", ("ctrl", "l"), "go to the address bar"),
    (r"(?:open )?(?:a )?new window", ("ctrl", "n"), "open a new window"),
    (r"(?:create |open )?(?:a )?new (?:document|file)", ("ctrl", "n"), "create a new document"),
    (r"print(?: this| it| the page| the document)?", ("ctrl", "p"), "open the print dialog"),
    (r"(?:make (?:it|that) )?bold", ("ctrl", "b"), "toggle bold"),
    (r"(?:make (?:it|that) )?italic", ("ctrl", "i"), "toggle italic"),
    (r"underline(?: it| that)?", ("ctrl", "u"), "toggle underline"),
    (r"delete (?:the )?(?:last|previous) word|delete that word", ("ctrl", "backspace"),
     "delete the last word"),
    (r"backspace", ("backspace",), "press backspace"),
    (r"(?:go to (?:the )?)?(?:top|beginning|start) of (?:the )?(?:page|document|text)"
     r"|go to (?:the )?top", ("ctrl", "home"), "go to the top"),
    (r"(?:go to (?:the )?)?(?:bottom|end) of (?:the )?(?:page|document|text)"
     r"|go to (?:the )?(?:bottom|end)", ("ctrl", "end"), "go to the end"),
    (r"next field", ("tab",), "move to the next field"),
    (r"previous field", ("shift", "tab"), "move to the previous field"),
    (r"alt tab|switch windows?", ("alt", "tab"), "switch to the previous window"),
    (r"escape|close (?:the |this )?(?:dialog|pop ?up|menu)|cancel (?:the |this )?dialog",
     ("esc",), "press escape"),
    (r"(?:open )?(?:the )?start menu", ("win",), "open the Start menu"),
    (r"(?:open )?(?:the )?(?:notifications|notification center|action center)",
     ("win", "n"), "open notifications"),
    (r"lock (?:the |my )?(?:computer|pc|laptop|screen)", ("win", "l"), "lock the computer"),
    (r"(?:open )?task manager", ("ctrl", "shift", "esc"), "open Task Manager"),
    (r"(?:open )?(?:windows )?search", ("win", "s"), "open Windows search"),
    (r"(?:open )?(?:the )?file menu", ("alt", "f"), "open the File menu"),
]
_SHORTCUT_RES = [(re.compile(rf"^(?:{p})$"), k, d) for p, k, d in SHORTCUTS]


def _control(low: str) -> str | None:
    """Control words: only at the START of a short utterance ("stop", "stop it",
    "cancel that"), so "search for bus stop" is not a stop command."""
    if "emergency" in low or low in ("halt", "abort", "abort everything"):
        return Command.EMERGENCY_STOP
    words = low.split()
    if not words or len(words) > 4:
        return None
    cmd = match_command(low)
    if cmd is None:
        return None
    starts = ("stop", "cancel", "never", "nevermind", "pause", "wait", "hold", "quiet",
              "be", "shush", "continue", "carry", "go", "resume", "keep", "repeat",
              "say", "again", "one")
    return cmd if words[0] in starts else None


_DEV = r"(?:the\s+)?(?:computer|laptop|pc|system|machine|windows)"
_KNOWN_DIRS = r"(desktop|documents|downloads|pictures|photos|music|videos|home)"
_THIS = r"(?:this|it|that|the selected|the (?:file|folder|item)|this (?:file|folder|item)|" \
        r"the selected (?:file|folder|item)|selected (?:file|folder|item))"


def _laptop_control(low: str, keep: str):
    """Everyday laptop controls. Returns (Kind, slots) or None."""
    # Bluetooth / Wi-Fi
    radio = r"(bluetooth|wi-?\s?fi|wireless)"
    m = re.search(rf"\b(?:turn|switch)\s+(on|off)\s+(?:the\s+|my\s+)?{radio}\b|"
                  rf"\b(enable|disable|start|stop)\s+(?:the\s+|my\s+)?{radio}\b|"
                  rf"^{radio}\s+(on|off)$|^(?:turn|switch)\s+(?:the\s+|my\s+)?{radio}\s+(on|off)$",
                  low)
    if m:
        g = [x for x in m.groups() if x]
        state = next(x for x in g if x in ("on", "off", "enable", "disable", "start", "stop"))
        dev = next(x for x in g if x not in ("on", "off", "enable", "disable", "start", "stop"))
        return Kind.RADIO, {"device": "bluetooth" if dev.startswith("blue") else "wifi",
                            "state": "on" if state in ("on", "enable", "start") else "off"}
    m = re.search(rf"^(?:is|are)\s+(?:the\s+|my\s+)?{radio}\s+(?:on|off|enabled|working)\b|"
                  rf"\b{radio}\s+status\b|\bis\s+{radio}\s+(?:on|off)\b", low)
    if m:
        dev = next(x for x in m.groups() if x)
        return Kind.RADIO, {"device": "bluetooth" if dev.startswith("blue") else "wifi",
                            "state": "status"}
    # network / IP
    if re.search(r"\b(?:what(?:'s| is)|tell me)\s+my\s+ip\b|\bip address\b|"
                 r"\bwhich\s+(?:wi-?\s?fi|network)\b|\bwhat\s+(?:wi-?\s?fi|network)\s+am i\b|"
                 r"\bnetwork (?:name|details|info)\b", low):
        return Kind.NETWORK_INFO, {}
    # brightness
    m = re.search(r"\b(?:set|change|put|make)\s+(?:the\s+)?(?:screen\s+)?brightness\s+(?:to|at)\s+"
                  r"(\d{1,3})|\bbrightness\s+(?:to\s+)?(\d{1,3})\s*(?:percent|%)?$", low)
    if m:
        return Kind.BRIGHTNESS, {"action": "set", "level": int(m.group(1) or m.group(2))}
    if re.search(r"\b(?:increase|raise|turn up|more)\s+(?:the\s+)?(?:screen\s+)?brightness\b|"
                 r"\bbrightness\s+up\b|\b(?:make\s+(?:the\s+)?screen\s+)?brighter$", low):
        return Kind.BRIGHTNESS, {"action": "up"}
    if re.search(r"\b(?:decrease|lower|reduce|turn down|dim)\s+(?:the\s+)?(?:screen\s+)?"
                 r"brightness\b|\bbrightness\s+down\b|\b(?:make\s+(?:the\s+)?screen\s+)?"
                 r"(?:dimmer|darker)$|^dim (?:the )?screen$", low):
        return Kind.BRIGHTNESS, {"action": "down"}
    if re.search(r"\bwhat(?:'s| is)\s+the\s+(?:screen\s+)?brightness\b|^brightness$", low):
        return Kind.BRIGHTNESS, {"action": "get"}
    # dark mode
    m = re.search(r"\b(?:turn|switch)\s+(on|off)\s+(?:the\s+)?dark\s+(?:mode|theme)\b|"
                  r"\bdark\s+(?:mode|theme)\s+(on|off)\b|\b(enable|disable)\s+dark\s+mode\b|"
                  r"\b(?:switch|change|go)\s+to\s+(dark|light)\s+(?:mode|theme)\b|"
                  r"^(dark|light)\s+(?:mode|theme)$", low)
    if m:
        v = next(g for g in m.groups() if g)
        return Kind.DARK_MODE, {"on": v in ("on", "enable", "dark")}
    # screenshot
    if re.search(r"\b(?:take|capture|grab|save)\s+(?:a\s+)?(?:screen\s*shot|screen\s+capture|"
                 r"picture of (?:the|my) screen)\b|^screen\s*shot$|^print\s*screen$|"
                 r"\bcapture (?:the |my )?screen\b", low):
        return Kind.SCREENSHOT, {}
    # power
    if re.search(r"\bcancel\s+(?:the\s+)?(?:shut\s*down|restart|reboot)\b|"
                 r"\b(?:don't|do not|stop the)\s+(?:shut\s*down|restart)\b|"
                 r"\babort shutdown\b", low):
        return Kind.POWER, {"action": "cancel"}
    if re.search(rf"^(?:shut\s*down|switch off|turn off|power off)(?:\s+{_DEV})?$|"
                 rf"^(?:shut|switch|turn|power)\s+{_DEV}\s+(?:down|off)$", low):
        return Kind.POWER, {"action": "shutdown"}
    if re.search(rf"^(?:restart|reboot)(?:\s+{_DEV})?$|^(?:restart|reboot)\s+{_DEV}\b", low):
        return Kind.POWER, {"action": "restart"}
    if re.search(rf"\b(?:put|send)\s+{_DEV}\s+to\s+sleep\b|^sleep\s+(?:mode|{_DEV})$|"
                 rf"^(?:go to )?sleep mode$|^hibernate$", low):
        return Kind.POWER, {"action": "sleep"}
    if re.search(rf"^(?:sign|log)\s*(?:out|off)(?:\s+(?:of\s+)?{_DEV})?$", low):
        return Kind.POWER, {"action": "signout"}
    # storage / updates
    if re.search(r"\bhow much\s+(?:storage|space|disk space|disk|free space|memory space)\b|"
                 r"\b(?:storage|disk space|free space)\s+(?:left|free|remaining)\b|"
                 r"^(?:storage|disk space|free space)$|\bis my (?:disk|drive|storage) full\b", low):
        return Kind.STORAGE, {}
    if re.search(r"\bcheck\s+for\s+(?:windows\s+)?updates?\b|^update windows$|"
                 r"^(?:windows )?updates?$|\binstall (?:windows )?updates\b", low):
        return Kind.CHECK_UPDATES, {}
    # settings pages ("open bluetooth settings", "display settings", "go to sound settings")
    m = re.match(r"^(?:open|show|go to|launch)?\s*(?:the\s+|my\s+)?(.+?)\s+settings?$|"
                 r"^(?:open\s+)?settings?\s+(?:for|of)\s+(?:the\s+|my\s+)?(.+)$", low)
    if m:
        from relay.system.control import settings_uri
        topic = next(g for g in m.groups() if g)
        uri = settings_uri(topic)
        if uri:
            return Kind.SETTINGS_PAGE, {"uri": uri, "topic": topic}
    if re.search(r"\bnight\s+light\b", low):
        return Kind.SETTINGS_PAGE, {"uri": "ms-settings:nightlight", "topic": "night light"}
    # recycle bin
    if re.search(r"\b(?:empty|clear|clean)\s+(?:the\s+|my\s+)?(?:recycle\s*bin|trash|bin)\b", low):
        return Kind.RECYCLE_BIN, {"action": "empty"}
    if re.search(r"\b(?:open|show|go to)\s+(?:the\s+|my\s+)?(?:recycle\s*bin|trash)\b|"
                 r"^(?:recycle\s*bin|trash)$", low):
        return Kind.RECYCLE_BIN, {"action": "open"}
    # weather
    # only real requests: "nice weather today" in a room conversation is not one
    m = re.search(r"^(?:what(?:'s| is)|how(?:'s| is)|tell me|check|get|give me)\s+(?:the\s+)?"
                  r"(?:weather|forecast|weather forecast)(?:\s+(?:like\s+)?(?:in|at|for)\s+"
                  r"([a-z .'-]+?))?(?:\s+(?:like|today|now|right now|outside|tomorrow))*$|"
                  r"^(?:the\s+)?weather(?:\s+(?:forecast|report))?(?:\s+(?:in|at|for)\s+"
                  r"([a-z .'-]+?))?(?:\s+(?:today|now))?$|"
                  r"^(?:will it|is it going to)\s+rain(?:\s+(?:in|at)\s+([a-z .'-]+?))?"
                  r"(?:\s+today|\s+tomorrow)?$|"
                  r"^what(?:'s| is)\s+the\s+temperature(?:\s+(?:outside|in\s+([a-z .'-]+)))?$",
                  low)
    if m and not re.search(r"\b(?:search|google|youtube|play)\b", low):
        place = next((g for g in m.groups() if g), "").strip()
        return Kind.WEATHER, {"place": re.sub(r"\s+(?:today|now)$", "", place)}
    # new folder
    m = re.search(r"\b(?:create|make|add|new)\s+(?:a\s+)?(?:new\s+)?folder\b"
                  r"(?:\s+(?:called|named))?\s*(.*?)(?:\s+(?:on|in)\s+(?:the\s+|my\s+)?"
                  rf"{_KNOWN_DIRS}(?:\s+folder)?)?$", low)
    if m:
        name = (m.group(1) or "").strip()
        name = re.sub(r"^(?:called|named)\s+", "", name)
        return Kind.NEW_FOLDER, {"name": name, "where": m.group(2) or ""}
    # the selected item in File Explorer
    m = re.match(rf"^rename\s+{_THIS}\s+(?:to|as)\s+(.+)$", keep)
    if m:
        return Kind.FILE_OP, {"op": "rename", "to": m.group(1).strip().strip(".")}
    m = re.match(rf"^(move|copy)\s+{_THIS}\s+(?:to|into)\s+(?:the\s+|my\s+)?"
                 rf"{_KNOWN_DIRS}(?:\s+folder)?$", low)
    if m:
        return Kind.FILE_OP, {"op": m.group(1), "to": m.group(2)}
    if re.fullmatch(rf"(?:delete|remove|trash)\s+{_THIS}", low):
        return Kind.FILE_OP, {"op": "delete"}
    # headings on a page
    m = re.fullmatch(r"(?:go to |read )?(?:the )?(next|previous|prev|first)\s+heading", low)
    if m:
        return Kind.HEADING_NAV, {"step": -1 if m.group(1).startswith("prev") else 1,
                                  "first": m.group(1) == "first"}
    # close every window
    if re.fullmatch(r"close\s+(?:all|every|all the|all my|everything)(?:\s+(?:windows|apps|"
                    r"applications|programs|open windows))?", low):
        return Kind.CLOSE_ALL, {}
    # email (in the browser: Gmail)
    if re.search(r"\b(?:check|read|open|show)\s+(?:my\s+)?(?:new\s+|latest\s+|last\s+)?"
                 r"(?:e-?mails?|mails?|inbox|gmail)\b|^(?:my\s+)?(?:e-?mails?|inbox)$", low):
        return Kind.EMAIL, {"action": "check"}
    m = re.search(r"\b(?:send|write|compose|new)\s+(?:an?\s+)?(?:e-?mail|mail)"
                  r"(?:\s+to\s+(.+))?$", low)
    if m:
        return Kind.EMAIL, {"action": "compose", "to": (m.group(1) or "").strip()}
    return None


def parse(utterance: str) -> Intent:
    raw = utterance.strip()
    low = normalize(raw)
    keep = normalize(raw, strip_trailing=False)
    if not low:
        return Intent(Kind.UNKNOWN, raw=raw)

    def I(kind, **slots):  # noqa: E743 - tiny local constructor
        return Intent(kind, slots, raw)

    if "emergency" in low:
        return I(Kind.CONTROL, command=Command.EMERGENCY_STOP)

    # Explicit narration-mode change ("quiet mode", "set narration to detailed") is
    # matched before control words so "quiet mode" isn't caught by the "quiet" stop
    # command. Excluded when it's a "remember ... narration" preference.
    if not low.startswith("remember"):
        mode_m = re.search(r"\b(quick|detailed|guided|quiet)\s+(?:mode|narration)\b", low)
        if mode_m is None:
            mode_m = re.match(r"set (?:narration|verbosity) to (?:the )?"
                              r"(quick|detailed|guided|quiet)", low)
        if mode_m:
            return I(Kind.SET_MODE, mode=mode_m.group(1))

    # ---- multi-word commands that contain control words (before control) ----
    if re.search(r"\b(?:start|begin|enable|turn on|switch on)\s+(?:the\s+)?"
                 r"(?:dictation|dictating|typing mode)\b|^dictation(?: mode)?$|^dictate$", low):
        return I(Kind.DICTATION, on=True)
    if re.search(r"\b(?:stop|end|finish|exit|turn off|disable|cancel)\s+(?:the\s+)?"
                 r"(?:dictation|dictating|typing mode)\b", low):
        return I(Kind.DICTATION, on=False)
    hp = r"(?:head\s*phones?|head\s*sets?|ear\s*phones?|ear\s*buds?|air\s*pods|ear\s*pods)"
    m = re.search(rf"\b(?:turn|switch)\s+(on|off)\s+(?:the\s+)?{hp}\s+mode\b|"
                  rf"\b(enable|disable)\s+(?:the\s+)?{hp}\s+mode\b|"
                  rf"\b{hp}\s+mode\s+(on|off|auto|automatic)\b|"
                  rf"\b{hp}\s+mode\s+to\s+(on|off|auto|automatic)\b", low)
    if m:
        v = next(g for g in m.groups() if g)
        return I(Kind.HEADPHONES, mode={"enable": "on", "disable": "off",
                                        "automatic": "auto"}.get(v, v))
    if re.fullmatch(rf"(?:i'm|i am|im)\s+(?:using|wearing|on|listening (?:on|with|through))\s+"
                    rf"(?:my\s+|the\s+)?{hp}|{hp}\s+(?:are\s+)?on", low):
        return I(Kind.HEADPHONES, mode="on")
    if re.fullmatch(rf"(?:i'm|i am|im)\s+(?:not\s+(?:using|wearing)\s+(?:my\s+|the\s+|any\s+)?"
                    rf"{hp}|using\s+(?:the\s+)?speakers?)|(?:i\s+)?took\s+off\s+(?:my\s+)?{hp}"
                    rf"|{hp}\s+(?:are\s+)?off|speaker\s+mode", low):
        return I(Kind.HEADPHONES, mode="off")
    if re.search(rf"\b(?:detect|find)\s+(?:the\s+)?{hp}\s+automatically\b", low):
        return I(Kind.HEADPHONES, mode="auto")
    if re.search(rf"\bwhere(?:'s| is)\s+(?:the\s+)?(?:sound|audio|voice)\s+(?:going|playing|"
                 rf"coming\s+from)\b|\bwhich\s+(?:speaker|audio device|sound device|"
                 rf"microphone|mic)\b|\bam i (?:using|on|wearing)\s+(?:my\s+)?{hp}\b|"
                 rf"\b(?:are|is)\s+(?:my\s+)?{hp}\s+(?:connected|working|on)\b|"
                 rf"\b(?:audio|sound)\s+(?:device|output)\b", low):
        return I(Kind.AUDIO_STATUS)
    m = re.search(r"\b(?:turn|switch)\s+(on|off)\s+(?:the\s+)?wake\s*word\b|"
                  r"\b(enable|disable)\s+(?:the\s+)?wake\s*word\b|"
                  r"\bwake\s*word\s+(on|off)\b", low)
    if m:
        v = next(g for g in m.groups() if g)
        return I(Kind.WAKE_WORD, on=v in ("on", "enable"))
    if re.search(r"\b(?:cancel|delete|clear|remove|stop)\s+(?:all\s+)?(?:of\s+)?(?:my\s+|the\s+)?"
                 r"(?:reminders?|timers?|alarms?)\b", low):
        return I(Kind.CANCEL_REMINDERS)
    m = re.match(r"^(?:(play|pause|resume|stop|start)\s+(?:the\s+)?(?:music|song|songs|video|"
                 r"media|playback|track|audio|podcast)|(next|previous|last)\s+(?:song|track|video)"
                 r"|skip\s+(?:this\s+)?(?:song|track)|play pause|(play))$", low)
    if m:
        verb = next((g for g in m.groups() if g), "skip")
        action = {"next": "next", "skip": "next", "previous": "previous", "last": "previous",
                  "stop": "stop"}.get(verb, "play_pause")
        return I(Kind.MEDIA, action=action)
    if re.fullmatch(r"(?:quit|exit|close|shut down|turn off|switch off|goodbye|bye)\s+relay"
                    r"|quit|exit|goodbye(?: relay)?|good night relay|close yourself", low):
        return I(Kind.QUIT)

    # ---- laptop controls (before control words: "cancel shutdown" isn't "cancel") ----
    hit = _laptop_control(low, keep)
    if hit is not None:
        kind, slots = hit
        return I(kind, **slots)

    # ---- control words (stop / pause / continue / cancel / repeat) ----
    cmd = _control(low)
    if cmd is not None:
        return I(Kind.CONTROL, command=cmd)

    # ---- everyday status ----
    if re.search(r"\bwhat(?:'s| is)?\s+the\s+time\b|\bwhat time is it\b|^time$|"
                 r"\btell me the time\b|\bcurrent time\b|^what time$|^time now$", low):
        return I(Kind.TIME)
    if re.search(r"\bwhat(?:'s| is)\s+(?:the\s+|today's\s+)?(?:date|day)(?: today)?$|"
                 r"\bwhat day is (?:it|today)\b|\btoday's (?:date|day)\b|^(?:date|day)$|"
                 r"\bwhich day is (?:it|today)\b|^what is today$|\bwhat(?:'s| is) today\b|"
                 r"\bwhat(?:'s| is) the date\b", low):
        return I(Kind.DATE)
    if re.search(r"\bbattery\b|\bam i (?:plugged in|charging)\b|\bis (?:it|the laptop) charging\b"
                 r"|\bcharging status\b|\bhow much charge\b", low):
        return I(Kind.BATTERY)
    if re.fullmatch(r"(?:system )?status(?: report)?|how(?:'s| is) (?:my|the) "
                    r"(?:computer|pc|laptop|system)(?: doing)?", low):
        return I(Kind.STATUS)
    if re.search(r"\b(?:am i|are we|is (?:the )?(?:internet|wi-?fi|network|computer))\s+"
                 r"(?:connected|online|working|on)\b|\binternet (?:status|connection)\b|"
                 r"\bwi-?fi (?:status|name|network)\b|\bwhich wi-?fi\b|"
                 r"\bcheck (?:the |my )?(?:internet|wi-?fi|connection)\b|"
                 r"^(?:internet|wi-?fi)$|\bis there internet\b|\bdo i have internet\b", low):
        return I(Kind.INTERNET)

    # ---- help / capabilities / options ----
    m = re.search(r"^help(?: me)?(?: with)?(?: (reading|the web|web|internet|browsing|typing|"
                  r"writing|windows|apps|files|system|reminders|notes|languages?|keys|"
                  r"keyboard|music|media))?$|\bwhat can (?:you do|i say)\b|"
                  r"\bhow do i use you\b|\bwhat commands\b|\bwhat can i ask\b", low)
    if m:
        topic = (m.group(1) or "") if m.lastindex else ""
        return I(Kind.HELP, topic=topic)
    if re.search(r"\b(?:what|which) (?:apps|programs|applications) (?:do|can) you\b|"
                 r"\bwhat can you (?:control|operate)\b|"
                 r"\bwhat (?:apps|programs) do you support\b", low):
        return I(Kind.CAPABILITIES)

    # ---- notes / reminders ----
    if re.match(r"^(?:take|make|add|write|save|create)(?:\s+(?:a|an|me a))?\s+note\b|"
                r"^note(?:\s+(?:that|down))?\s+\S", keep):
        text = payload_after(raw, r"note(?:\s+(?:that|down|saying|of|to))?|note:")
        return I(Kind.TAKE_NOTE, text=text or "")
    if re.search(r"\b(?:read|list|what are|tell me|show|say)(?: me)?(?: all)?(?: of)? my notes\b"
                 r"|^my notes$|\bwhat notes (?:do i have|have i)\b|\bany notes\b", low):
        return I(Kind.READ_NOTES)
    if re.search(r"\b(?:delete|clear|erase|remove) (?:all )?(?:of )?my notes\b", low):
        return I(Kind.DELETE_NOTES)
    if re.match(r"^(?:remind me|set (?:a |an )?(?:reminder|timer|alarm)|start (?:a )?timer|"
                r"timer for|wake me)\b", low):
        return I(Kind.SET_REMINDER, text=raw)
    if re.search(r"\b(?:what are|list|read|tell me|show)(?: me)?(?: all)? (?:my |the )?"
                 r"(?:reminders|timers|alarms)\b|\bdo i have (?:any )?(?:reminders|timers)\b|"
                 r"^(?:my )?reminders$", low):
        return I(Kind.LIST_REMINDERS)

    # ---- the conversational assistant ----
    m = re.match(r"^(?:ask|question|ask relay|ask the (?:ai|assistant))[\s:,]+(.+)$", keep)
    if m:
        return I(Kind.ASK, text=payload_after(raw, r"ask(?: relay| the ai| the assistant)?"
                                                   r"|question") or m.group(1))
    if re.search(r"\b(?:summari[sz]e|sum up|give me (?:a |the )?summary of|tl ?;? ?dr)\b|"
                 r"\bwhat(?:'s| is) this (?:page|article|email|mail|document|pdf|message)"
                 r"(?: all)? about\b|\bexplain (?:this|the) (?:page|article|email|mail|"
                 r"document|pdf|message|screen)\b", low):
        return I(Kind.SUMMARIZE, request=raw)

    # ---- reading ----
    if re.search(r"\b(?:read|what(?:'s| is) (?:in|on)) (?:the |my )?clipboard\b|"
                 r"\bwhat did i copy\b", low):
        return I(Kind.READ_CLIPBOARD)
    if re.search(r"\b(?:read|what(?:'s| is)) (?:the )?(?:window |page )?title\b|"
                 r"\bwhat (?:window|app|application|program|page) (?:is this|am i (?:in|on))\b",
                 low):
        return I(Kind.READ_TITLE)
    if re.search(r"\b(?:list|read|what are|show|tell me)(?: me)?(?: all)?(?: the)? links\b|"
                 r"\blinks on (?:this|the) page\b|^links$", low):
        return I(Kind.LIST_LINKS)
    if re.search(r"\b(?:list|read|what are|show|tell me)(?: me)?(?: all)?(?: the)? headings\b|"
                 r"\bheadings on (?:this|the) page\b|^headings$", low):
        return I(Kind.LIST_HEADINGS)
    if re.search(r"\bocr\b|\bscan (?:the )?screen\b|\bread (?:the )?(?:text )?(?:in|on|from) "
                 r"(?:the )?(?:image|picture|photo)\b|\bread the (?:image|picture)\b|"
                 r"\bwhat does (?:the |this )?(?:image|picture|photo) say\b", low):
        return I(Kind.OCR_READ)
    m = re.search(rf"\b(?:read|say)(?: out| aloud)?(?: the| this| that| my| it)?"
                  rf"(?: whole| entire| full)?"
                  rf"(?: (?:page|document|doc|article|email|mail|message|text|file|screen|window|"
                  rf"everything|all|it all|story|news|pdf))?(?: (?:to me|aloud|out loud))?"
                  rf"(?: in ({_LANG_RE}))?$", low)
    if m and (m.group(1) or re.search(r"\b(?:page|document|doc|article|email|mail|message|"
                                      r"text|screen|window|everything|all|story|news|pdf)\b|"
                                      r"aloud|out loud", low)) \
            and not re.search(r"\b(?:dialog|selection|focus|title|notes)\b", low):
        return I(Kind.READ_ALL, language=m.group(1) or "")
    if re.search(r"^(?:say all|read from (?:the )?(?:top|start|beginning)|read it all|"
                 r"start reading|read everything)$", low):
        return I(Kind.READ_ALL, language="", from_top=True)
    if re.fullmatch(r"(?:next|skip)(?: (?:paragraph|sentence|part|section|line))?|skip|"
                    r"skip (?:ahead|this)|read (?:the )?next(?: (?:paragraph|part|section))?",
                    low) and low not in ("next",):
        return I(Kind.READ_NEXT)
    if re.fullmatch(r"(?:previous|go back a|back one|last)(?: (?:paragraph|sentence|part|section))"
                    r"|read (?:the )?previous(?: (?:paragraph|part|section))?", low):
        return I(Kind.READ_PREV)
    if re.search(r"\b(?:continue|keep|resume|carry on) reading\b|^read more$|^keep going$", low):
        return I(Kind.CONTROL, command=Command.CONTINUE)

    # ---- information about the screen ----
    if re.search(r"\b(what(?:'s| is)? (on|happening)|describe|what am i looking at|"
                 r"what(?:'s| is) in front of me)\b", low):
        return I(Kind.DESCRIBE_SCREEN)
    if re.search(r"\bwhere am i\b", low):
        return I(Kind.WHERE_AM_I)
    if re.search(r"\bwhat(?:'s| has)? changed|what(?:'s| is)? different\b", low):
        return I(Kind.WHAT_CHANGED)
    if re.search(r"\b(?:what|which)(?: are)?(?: my)? options\b|\bwhat can i (?:click|choose|press)"
                 r"\b|\bwhat buttons\b", low):
        return I(Kind.LIST_OPTIONS)
    if re.search(r"\b(read (this|it|that|the selection|the focus|selected text)|"
                 r"what('?s| is) selected)\b", low):
        return I(Kind.READ_FOCUS)
    if low in ("help", "what can you do"):
        return I(Kind.HELP, topic="")

    # ---- calculator ----
    from relay.system.calc import to_expression
    if re.search(r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|hundred|"
                 r"thousand|lakh|crore|half|square root)\b", low) and to_expression(low):
        return I(Kind.CALCULATE, text=low)

    # ---- volume / speech rate / language ----
    m = re.search(r"\b(?:set|change|put|make)\s+(?:the\s+)?(?:volume|sound)\s+(?:to|at)\s+"
                  r"(\d{1,3})|\bvolume\s+(?:to\s+|at\s+)?(\d{1,3})\s*(?:percent|%)?$", low)
    if m:
        return I(Kind.VOLUME, action="set", level=int(m.group(1) or m.group(2)))
    if re.search(r"\b(?:max(?:imum)?|full) volume\b|\bvolume (?:to )?(?:max|full)\b", low):
        return I(Kind.VOLUME, action="set", level=100)
    if re.fullmatch(r"unmute(?: (?:the )?(?:sound|volume|audio|computer|speakers))?|"
                    r"turn (?:the )?sound (?:back )?on|sound on", low):
        return I(Kind.VOLUME, action="unmute")
    if re.fullmatch(r"mute(?: (?:the )?(?:sound|volume|audio|computer|speakers))?|"
                    r"turn (?:the )?sound off|sound off", low):
        return I(Kind.VOLUME, action="mute")
    if re.search(r"\b(?:volume|sound)\s+up\b|\b(?:increase|raise|turn up)\s+(?:the\s+)?"
                 r"(?:volume|sound)\b|^louder$|^turn it up$|\bspeak louder\b", low):
        return I(Kind.VOLUME, action="up")
    if re.search(r"\b(?:volume|sound)\s+down\b|\b(?:decrease|lower|reduce|turn down)\s+(?:the\s+)?"
                 r"(?:volume|sound)\b|^(?:quieter|softer)$|^turn it down$", low):
        return I(Kind.VOLUME, action="down")
    if re.search(r"\bwhat(?:'s| is) the volume\b|\bvolume level\b|\bhow loud\b|^volume$", low):
        return I(Kind.VOLUME, action="get")
    if re.search(r"\b(?:speak|talk|read|say it)(?: a bit| a little)? (?:faster|quicker)\b|"
                 r"^(?:speed up|faster)$|\bincrease (?:the )?(?:speech|speaking) (?:rate|speed)\b",
                 low):
        return I(Kind.SPEECH_RATE, change="faster")
    if re.search(r"\b(?:speak|talk|read|say it)(?: a bit| a little)? (?:slower|more slowly)\b|"
                 r"^(?:slow down|slower)$|\bdecrease (?:the )?(?:speech|speaking) (?:rate|speed)\b",
                 low):
        return I(Kind.SPEECH_RATE, change="slower")
    if re.search(r"\b(?:normal|default) (?:speed|rate|speech)\b|\breset (?:the )?speech\b", low):
        return I(Kind.SPEECH_RATE, change="normal")
    m = re.search(rf"\b(?:speak|talk|reply|respond|answer)(?: to me)?(?: only)? in ({_LANG_RE})\b|"
                  rf"\b(?:switch|change)(?: the)?(?: language)? to ({_LANG_RE})\b|"
                  rf"\buse ({_LANG_RE})(?: language)?$|^({_LANG_RE})(?: please)?$|"
                  rf"\b(?:set|change) (?:the |my )?language to ({_LANG_RE})\b", low)
    if m:
        return I(Kind.LANGUAGE, language=next(g for g in m.groups() if g))
    if re.search(r"\b(?:auto(?:matic)?|same) language\b|\breply in the language i speak\b", low):
        return I(Kind.LANGUAGE, language="auto")

    # ---- web ----
    m = re.match(r"^(?:search|look up|find)\s+(?:on\s+)?youtube\s+(?:for\s+)?(.+)$|"
                 r"^youtube\s+(?:search\s+)?(?:for\s+)?(.+)$|"
                 r"^(?:play|watch|search|find|open)\s+(.+?)\s+on\s+youtube$", keep)
    if m:
        q = re.sub(r"\s+please$", "", next(g for g in m.groups() if g).strip())
        return I(Kind.YOUTUBE, query=q)
    m = re.match(r"^(?:search|google|look up|web search|search online|search the (?:web|internet))"
                 r"(?:\s+(?:the web|google|online|the internet|on google|in google))?"
                 r"(?:\s+(?:for|about))?\s+(.+)$", keep)
    if m and not re.match(r"^(?:search|look)\s+(?:my|for my)\s+(?:files|computer|pc|documents|"
                          r"folders?|laptop)\b", keep):
        q = re.sub(r"\s+please$", "", m.group(1).strip())
        if q and q not in ("the web", "google", "online", "the internet"):
            return I(Kind.WEB_SEARCH, query=q)

    # ---- windows ----
    if re.search(r"\b(?:what|which) (?:windows|apps|applications|programs) (?:are )?"
                 r"(?:open|running)\b|\blist (?:the |all )?(?:open )?(?:windows|apps)\b|"
                 r"\bopen windows\b|\bwhat(?:'s| is) open\b|^(?:list )?windows$", low):
        return I(Kind.LIST_WINDOWS)
    if re.search(r"\b(?:show|go to) (?:the )?desktop\b|\bminimi[sz]e (?:all|everything)\b", low):
        return I(Kind.SHOW_DESKTOP)
    m = re.fullmatch(r"(close|minimi[sz]e|maximi[sz]e|restore)(?: (?:this|the|current|my))?"
                     r"(?: (?:window|app|application|program|one|it))?", low)
    if m:
        op = m.group(1)[:3]
        return I(Kind.WINDOW_OP, op={"clo": "close", "min": "minimize", "max": "maximize",
                                     "res": "restore"}[op], target="")
    m = re.fullmatch(r"(close|minimi[sz]e|maximi[sz]e)\s+(?:the\s+)?(.+?)(?:\s+window)?", low)
    if m and not re.search(r"\b(?:tab|dialog|pop ?up|menu)\b", low):
        op = {"clo": "close", "min": "minimize", "max": "maximize"}[m.group(1)[:3]]
        return I(Kind.WINDOW_OP, op=op, target=m.group(2).strip())

    # ---- named shortcuts ----
    for rx, keys, desc in _SHORTCUT_RES:
        if rx.match(low):
            return I(Kind.SHORTCUT, keys=list(keys), description=desc)

    if re.fullmatch(r"send(?: (?:the|this|my|that))?(?: (?:message|reply|text|it))?(?: now)?",
                    low):
        return I(Kind.SEND)

    # ---- keys ----
    if low in ("enter", "press enter", "hit enter"):
        return I(Kind.PRESS_KEY, key="enter", count=1)
    m = re.match(r"^(?:press|hit|push|tap|use)\s+(?:the\s+)?(.+)$", low)
    if m:
        parsed = parse_keys(m.group(1))
        if parsed:
            keys, count = parsed
            if len(keys) == 1:
                return I(Kind.PRESS_KEY, key=keys[0], count=count)
            if any(k in _MODIFIERS for k in keys[:-1]):
                return I(Kind.HOTKEY, keys=keys, count=count)
            return I(Kind.HOTKEY, keys=keys, count=count, sequence=True)

    # ---- pick from the last list RELAY read out ----
    m = re.fullmatch(r"(?:(open|read|play|switch to|go to|use|pick)\s+)?"
                     r"(?:the\s+)?((?:first|second|third|fourth|fifth|sixth|seventh|eighth|"
                     r"ninth|tenth|last)(?: one| file| window| document)?|"
                     r"(?:number|no\.?)\s*\d+|\d+(?:st|nd|rd|th)?(?: one)?)", low)
    if m:
        return I(Kind.PICK, verb=(m.group(1) or "open"), ordinal=_ordinal_in(m.group(2)) or 1)

    # ---- files ----
    m = re.match(r"^(?:find|locate|where is|where's|look for|search (?:my )?(?:files|computer|pc|"
                 r"documents|laptop)\s+for)\s+(?:my\s+|the\s+|a\s+)?(?:file\s+|document\s+|"
                 r"folder\s+)?(?:called\s+|named\s+)?(.+)$", low)
    if m and not re.search(r"\bon (?:this |the )?page\b", low):
        return I(Kind.FIND_FILE, name=m.group(1).strip())
    m = re.match(r"^(?:open|read)\s+(?:the\s+|my\s+)?(?:file|document|pdf)\s+"
                 r"(?:called\s+|named\s+)?(.+)$", low)
    if m and not re.match(r"^open\s+(?:the\s+)?file\s+(?:explorer|manager)$", low):
        verb = "read" if low.startswith("read") else "open"
        return I(Kind.OPEN_FILE, name=m.group(1).strip(), then=verb)

    # ---- memory (L3/L5) voice operations ----
    if re.search(r"\bwhat do you remember|what have you remembered\b", low):
        return I(Kind.WHAT_REMEMBER)
    if re.search(r"\bwhy (did|do) you remember\b", low):
        return I(Kind.WHY_REMEMBER)
    if re.search(r"\bforget (this|that|it)\b", low):
        return I(Kind.FORGET)
    if re.search(r"\bclear (my )?(task )?history\b|\bforget (my )?history\b", low):
        return I(Kind.CLEAR_HISTORY)
    if re.search(r"\bexport (my )?(preferences|settings|prefs)\b", low):
        return I(Kind.EXPORT_PREFS)
    if re.search(r"\bwhat (were we|was i) doing\b|\bwhat did we do\b", low):
        return I(Kind.WHAT_DOING)
    m = re.match(r"remember (?:that )?i (?:prefer|like|want) "
                 r"(quick|detailed|guided|quiet) narration(?:\s+(?:in|for)\s+(?:the\s+)?(.+))?",
                 low)
    if m:
        slots = {"mode": m.group(1)}
        if m.group(2):
            slots["app"] = m.group(2).strip()
        return Intent(Kind.REMEMBER, slots, raw)
    m = re.match(r"remember (?:that )?(.+)", keep)
    if m:
        fact = payload_after(raw, r"remember(?:\s+that)?") or m.group(1).strip()
        return I(Kind.REMEMBER, fact=fact)

    # ---- accessibility read / navigate / spell ----
    if re.search(r"\bread the dialog|what does the dialog say|read dialog\b", low):
        return I(Kind.READ_DIALOG)
    if re.fullmatch(r"(next|next (element|control|one|item))", low):
        return I(Kind.NEXT_ELEMENT)
    if re.fullmatch(r"(previous|prev|go back one|previous (element|control|one|item))", low):
        return I(Kind.PREV_ELEMENT)
    if re.search(r"\bspell (that|it|this|the selection)\b|^spell$", low):
        return I(Kind.SPELL)

    # ---- actions ----
    m = re.match(r"(?:open|launch|start|run)\s+(?:up\s+)?(?:the\s+)?(.+)", low)
    if m and not re.search(r"\b(?:result|link|button)\b", m.group(1)):
        return I(Kind.OPEN_APP, app=m.group(1).strip())
    m = re.match(r"(?:switch to|go to|focus(?: on)?|bring up|show me)\s+(?:the\s+)?(.+)", low)
    if m and not re.search(r"\b(?:result|link|button|field)\b", m.group(1)):
        return I(Kind.SWITCH_APP, app=m.group(1).strip())
    m = re.match(r"(?:type|write|enter|dictate|insert)\s+(?:in\s+)?(.+)", keep)
    if m:
        text = payload_after(raw, r"type(?:\s+in)?|write|enter|dictate|insert") or m.group(1)
        return I(Kind.TYPE, text=text.strip())
    m = re.match(r"^save(?: (?:this|it|the file|the document))?\s+as\s+(.+)$", low)
    if m:
        name = payload_after(raw, r"as") or m.group(1)
        return I(Kind.SAVE, name=name.strip())
    if re.search(r"\bsave\b", low):
        return I(Kind.SAVE)
    if re.search(r"\bgo back|^back$", low):
        return I(Kind.GO_BACK)
    m = re.search(r"\bscroll (up|down)\b|\bpage (up|down)\b", low)
    if m:
        return I(Kind.SCROLL, direction=m.group(1) or m.group(2))

    # activate a target (click/select/open the <ordinal> <role>/<name>)
    m = re.match(r"(?:click|select|activate|choose|open|press|tap|follow)\s+(?:on\s+)?(?:the\s+)?"
                 r"(.+)", low)
    if m:
        target = m.group(1).strip()
        slots: dict = {"target": target}
        rm = re.search(r"\b(link|button|result|heading|item|option|checkbox|check box|tab|"
                       r"menu item|field)s?\b", target)
        ordinal = _ordinal_in(target)
        if ordinal is not None:
            slots["ordinal"] = ordinal
        if rm:
            slots["role"] = rm.group(1).replace("check box", "checkbox")
        return Intent(Kind.ACTIVATE, slots, raw)

    return I(Kind.UNKNOWN)
