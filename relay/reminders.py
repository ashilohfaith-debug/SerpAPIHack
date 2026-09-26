"""Spoken reminders and timers — "remind me in 10 minutes to call mom".

Reminders are stored in the RELAY database so none is silently lost: one that came
due while RELAY was closed is announced as missed on the next start. A single
scheduler thread waits for the next due time and hands the reminder to ``on_due``,
which speaks it. This is still user-initiated — RELAY only speaks a reminder the
user explicitly asked for.
"""

from __future__ import annotations

import datetime as _dt
import re
import sqlite3
import threading
import time
from typing import Callable

from relay.diagnostics import get_logger

log = get_logger("reminders")

_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "ninety": 90,
}
_TENS_UNITS = re.compile(r"\b(twenty|thirty|forty|fifty)[\s-]+"
                         r"(one|two|three|four|five|six|seven|eight|nine)\b")
_ONE_WORD = re.compile(r"\b(" + "|".join(_NUM_WORDS) + r")\b")


def _numwords(t: str) -> str:
    """'twenty five minutes' -> '25 minutes' (words only; punctuation untouched)."""
    t = _TENS_UNITS.sub(lambda m: str(_NUM_WORDS[m.group(1)] + _NUM_WORDS[m.group(2)]), t)
    return _ONE_WORD.sub(lambda m: str(_NUM_WORDS[m.group(1)]), t)

_UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1}
_DUR = re.compile(r"(\d+(?:\.\d+)?|an?|half an?|half)\s*"
                  r"(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b")
_DUR_BLOCK = re.compile(r"\b(?:in|for|after)\s+((?:(?:\d+(?:\.\d+)?|an?|half an?|half)\s*"
                        r"(?:hours?|hrs?|minutes?|mins?|seconds?|secs?)\s*(?:and\s*)?)+)")
_AT = re.compile(r"\bat\s+(\d{1,2})(?:\s*[:.]\s*(\d{2})|\s+(\d{2})(?!\s*(?:hours?|minutes?)))?"
                 r"\s*(a\s?m|p\s?m|in the morning|in the afternoon|in the evening|at night|"
                 r"tonight)?\b")


def _duration_seconds(block: str) -> float:
    total = 0.0
    for num, unit in _DUR.findall(block):
        if num.startswith("half"):
            val = 0.5
        elif num in ("a", "an"):
            val = 1.0
        else:
            val = float(num)
        total += val * _UNIT_SECONDS[unit[0]]
    return total


def parse_reminder(text: str, now: _dt.datetime | None = None
                   ) -> tuple[_dt.datetime, str, bool] | None:
    """Return (due, message, is_timer) or None if no time could be understood."""
    now = now or _dt.datetime.now()
    t = text.lower().strip().rstrip(".!?")
    t = re.sub(r"(\d)\s*:\s*(\d)", r"\1:\2", t)
    t = _numwords(t)
    t = re.sub(r"\ba\s*\.\s*m\b\.?", "am", t)
    t = re.sub(r"\bp\s*\.\s*m\b\.?", "pm", t)
    t = re.sub(r"\b(\d{1,2})\s*(am|pm)\b", r"\1 \2", t)
    # "set an alarm for 6", "wake me up for 7:30" -> "... at 6"
    t = re.sub(r"\b(alarm|wake me(?: up)?)\s+(?:for|to)\s+(?=\d)", r"\1 at ", t)
    alarm = bool(re.search(r"\b(?:alarm|wake me)\b", t))
    is_timer = bool(re.search(r"\btimer\b", t))
    due = None
    m = _DUR_BLOCK.search(t)
    if m:
        secs = _duration_seconds(m.group(1))
        if secs > 0:
            due = now + _dt.timedelta(seconds=secs)
            t = t[:m.start()] + " " + t[m.end():]
    if due is None:
        m = _AT.search(t)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2) or m.group(3) or 0)
            mer = (m.group(4) or "").replace(" ", "")
            if hour > 23 or minute > 59:
                return None
            if mer in ("pm", "intheafternoon", "intheevening", "atnight", "tonight") \
                    and hour < 12:
                hour += 12
            elif mer in ("am", "inthemorning") and hour == 12:
                hour = 0
            day = now.date() + (_dt.timedelta(days=1) if "tomorrow" in t else _dt.timedelta())
            due = _dt.datetime.combine(day, _dt.time(hour, minute))
            if not mer and "tomorrow" not in t and not alarm:
                # no am/pm: the next time it will be that o'clock
                while due <= now and hour < 12:
                    due += _dt.timedelta(hours=12)
            # an alarm / "wake me up at 7" with no am/pm means the morning
            if due <= now:
                due += _dt.timedelta(days=1)
            t = t[:m.start()] + " " + t[m.end():]
    if due is None:
        return None
    msg = re.sub(r"^(?:please\s+)?(?:remind me|set (?:a |an )?(?:reminder|timer|alarm)|"
                 r"start (?:a )?timer|timer|reminder|wake me up|wake me)\b", " ", t.strip())
    msg = re.sub(r"\btomorrow\b", " ", msg)
    msg = re.sub(r"\s+", " ", msg).strip()
    msg = re.sub(r"^(?:for|to|about|that|of)\s+", "", msg)
    msg = re.sub(r"\s+(?:to|for)$", "", msg).strip()
    if not msg:
        msg = ("your timer is done" if is_timer else "this is your alarm" if alarm
               else "this is your reminder")
    return due, msg, is_timer


def when_text(due: _dt.datetime, now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now()
    secs = int(round((due - now).total_seconds()))
    clock = due.strftime("%I:%M %p").lstrip("0")
    if secs < 3600:
        mins, s = divmod(max(secs, 0), 60)
        rel = (f"in {mins} minute{'s' if mins != 1 else ''}" if mins
               else f"in {s} second{'s' if s != 1 else ''}")
        return f"{rel}, at {clock}"
    day = "tomorrow " if due.date() > now.date() else ""
    return f"{day}at {clock}"


class ReminderScheduler:
    def __init__(self, conn: sqlite3.Connection, on_due: Callable[[str, float], None],
                 clock: Callable[[], float] = time.time) -> None:
        self.conn = conn
        self.on_due = on_due
        self.clock = clock
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def add(self, text: str, due_ts: float) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO reminders (text, due, created) VALUES (?,?,?)",
                (text, due_ts, self.clock()))
        self._wake.set()
        return int(cur.lastrowid)

    def pending(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, text, due FROM reminders WHERE done=0 ORDER BY due").fetchall()
        return [dict(r) for r in rows]

    def cancel_all(self) -> int:
        with self._lock:
            n = self.conn.execute("UPDATE reminders SET done=2 WHERE done=0").rowcount
        self._wake.set()
        return n

    def check_now(self, now: float | None = None) -> list[tuple[str, float]]:
        """Fire every due reminder; returns [(text, seconds_overdue)]."""
        now = self.clock() if now is None else now
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, text, due FROM reminders WHERE done=0 AND due<=? ORDER BY due",
                (now,)).fetchall()
            for r in rows:
                self.conn.execute("UPDATE reminders SET done=1 WHERE id=?", (r["id"],))
        fired = [(r["text"], now - r["due"]) for r in rows]
        for text, late in fired:
            try:
                self.on_due(text, late)
            except Exception as e:
                log.warning("reminder callback failed: %s", e)
        return fired

    def _next_due(self) -> float | None:
        row = self.conn.execute(
            "SELECT MIN(due) d FROM reminders WHERE done=0").fetchone()
        return row["d"] if row and row["d"] is not None else None

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.check_now()
            nxt = self._next_due()
            wait = 30.0 if nxt is None else max(0.2, min(30.0, nxt - self.clock()))
            self._wake.wait(wait)
            self._wake.clear()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="reminders", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def spoken_pending(self) -> str:
        items = self.pending()
        if not items:
            return "You have no reminders set."
        now = _dt.datetime.now()
        parts = [f"{r['text']}, {when_text(_dt.datetime.fromtimestamp(r['due']), now)}"
                 for r in items[:8]]
        n = len(items)
        return f"You have {n} reminder{'s' if n != 1 else ''}: " + "; ".join(parts) + "."
