"""Installed-application catalog — "open WhatsApp" works for any app on the Start menu.

Windows lists every launchable app (classic and Store/UWP alike) through the Start
menu's AppsFolder; ``Get-StartApps`` returns each app's display name and AppID, and
``explorer shell:AppsFolder\\<AppID>`` launches it — the same way the Start menu does.
The list is cached to the per-user data dir so startup is instant, and refreshed in
the background. Matching is forgiving (aliases, word overlap, fuzzy ratio) but has a
threshold: RELAY says it couldn't find an app rather than launching a wrong one.
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from relay.config import user_data_dir
from relay.diagnostics import get_logger

log = get_logger("system.apps")


@dataclass(frozen=True)
class AppEntry:
    name: str
    app_id: str


ALIASES = {
    "files": "file explorer", "explorer": "file explorer", "my computer": "file explorer",
    "this pc": "file explorer", "file manager": "file explorer",
    "calc": "calculator", "ms word": "word", "microsoft word": "word",
    "ms excel": "excel", "microsoft excel": "excel", "powerpoint": "powerpoint",
    "chrome": "google chrome", "google chrome browser": "google chrome",
    "edge": "microsoft edge", "edge browser": "microsoft edge",
    "whatsapp desktop": "whatsapp", "whats app": "whatsapp",
    "mail": "outlook", "email": "outlook", "store": "microsoft store",
    "command prompt": "command prompt", "cmd": "command prompt", "terminal": "terminal",
    "control panel": "control panel", "task manager": "task manager",
    "photos": "photos", "camera": "camera",
    "word pad": "wordpad", "note pad": "notepad", "ms paint": "paint",
    "vs code": "visual studio code", "vscode": "visual studio code",
    "visual code": "visual studio code", "code editor": "visual studio code",
    "the file explorer": "file explorer", "windows explorer": "file explorer",
    "settings app": "settings", "windows settings": "settings",
    "google": "google chrome", "browser": "google chrome", "web browser": "google chrome",
}
# how a word SOUNDS, so speech-recognition spellings still match: "Andy gravity" and
# "and gravity" both sound like "Antigravity"
_SOUND = [(r"ph", "f"), (r"ck", "k"), (r"[cq]", "k"), (r"x", "ks"), (r"z", "s"),
          (r"d", "t"), (r"b", "p"), (r"g", "k"), (r"v", "f")]


def sound_key(s: str) -> str:
    s = re.sub(r"[^a-z]", "", s.lower())
    for a, b in _SOUND:
        s = re.sub(a, b, s)
    s = s[:1] + re.sub(r"[aeiouyhw]", "", s[1:])        # keep the first letter
    return re.sub(r"(.)\1+", r"\1", s)
_NOISE = re.compile(r"\b(?:the|my|app|application|program|software|please)\b")
_JUNK = ("uninstall", "readme", "help", "documentation", "release notes", "license",
         "website", "manual", "support")


def _clean(s: str) -> str:
    s = _NOISE.sub(" ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _cache_path() -> Path:
    return user_data_dir() / "apps_cache.json"


def _load_from_windows(timeout: float = 20.0) -> list[AppEntry]:
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
           "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                         encoding="utf-8", errors="replace",
                         creationflags=0x08000000).stdout  # CREATE_NO_WINDOW
    data = json.loads(out or "[]")
    if isinstance(data, dict):
        data = [data]
    return [AppEntry(d["Name"], d["AppID"]) for d in data
            if d.get("Name") and d.get("AppID")]


class AppCatalog:
    def __init__(self, entries: list[AppEntry] | None = None, loader=None) -> None:
        self._entries: list[AppEntry] = list(entries or [])
        self._loader = loader or _load_from_windows
        self._lock = threading.Lock()
        self._ready = threading.Event()
        if entries is not None:
            self._ready.set()

    # ---- loading ----
    def load_cached(self) -> None:
        try:
            data = json.loads(_cache_path().read_text(encoding="utf-8"))
            with self._lock:
                self._entries = [AppEntry(d["name"], d["app_id"]) for d in data]
            if self._entries:
                self._ready.set()
        except Exception:
            pass

    def refresh(self) -> None:
        try:
            entries = self._loader()
        except Exception as e:
            log.warning("could not list installed apps: %s", e)
            self._ready.set()
            return
        with self._lock:
            self._entries = entries
        self._ready.set()
        try:
            _cache_path().write_text(json.dumps([e.__dict__ for e in entries]),
                                     encoding="utf-8")
        except OSError:
            pass

    def start(self) -> None:
        """Instant start from cache, then refresh in the background."""
        self.load_cached()
        threading.Thread(target=self.refresh, name="app-catalog", daemon=True).start()

    def wait_ready(self, timeout: float = 25.0) -> bool:
        return self._ready.wait(timeout)

    @property
    def entries(self) -> list[AppEntry]:
        with self._lock:
            return list(self._entries)

    # ---- matching ----
    def find(self, query: str) -> AppEntry | None:
        best = self.candidates(query, limit=1)
        return best[0] if best else None

    def candidates(self, query: str, limit: int = 3, threshold: float = 62
                   ) -> list[AppEntry]:
        q = _clean(query)
        if not q:
            return []
        q = ALIASES.get(q, q)
        q_tokens = set(q.split())
        q_flat = q.replace(" ", "").replace("-", "")
        q_sound = sound_key(q)
        scored: list[tuple[float, AppEntry]] = []
        for e in self.entries:
            n = e.name.lower()
            if any(j in n for j in _JUNK) and not any(j in q for j in _JUNK):
                continue
            n_clean = _clean(n)
            n_flat = n_clean.replace(" ", "").replace("-", "")
            if n_clean == q or n == q:
                score = 100.0
            elif n_flat == q_flat:                          # "anti gravity" = Antigravity
                score = 96.0
            elif n_clean.startswith(q + " ") or n_clean.startswith(q):
                score = 90.0 - min(len(n_clean) - len(q), 20) * 0.2
            elif q_tokens and q_tokens <= set(n_clean.split()):
                score = 82.0 - len(n_clean.split()) * 0.5
            elif len(q_sound) >= 4 and sound_key(n_clean) == q_sound:
                score = 78.0 - min(len(n_clean), 30) * 0.05  # sounds the same
            else:
                score = max(difflib.SequenceMatcher(None, q, n_clean).ratio(),
                            difflib.SequenceMatcher(None, q_flat, n_flat).ratio()) * 75
            scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for s, e in scored if s >= threshold][:limit]

    # ---- launching ----
    @staticmethod
    def launch(entry: AppEntry) -> None:
        """Launch exactly as the Start menu does (works for classic and Store apps)."""
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{entry.app_id}"],
                         creationflags=0x08000000)
