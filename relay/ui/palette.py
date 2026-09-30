"""The RELAY palette — a small always-on-top bar at the top of the screen.

For sighted helpers, low-vision users and demos (a blind user never needs it):

    ● Listening — say "Relay" or press Ctrl+Alt+Space        [ On ] [ Talk ] [ ✕ ]
    You: what's the weather in Hyderabad
    Relay: Hyderabad: overcast, 27 degrees…

- the light shows whether RELAY is working: green = ready / listening, amber = heard you
  and working, blue = speaking, grey = off (not listening);
- "You:" is what RELAY heard you say (only speech addressed to RELAY), "Relay:" what it
  answered;
- On/Off turns listening on and off (the talk key still works when off), Talk is the talk
  key, ✕ closes RELAY. Drag the bar to move it.

It never takes keyboard focus (WS_EX_NOACTIVATE), so it can't swallow what you or RELAY
type, and RELAY's own window list ignores it (tool window). Tkinter only — no new
dependency. All Tk calls stay on the palette's own thread; other threads hand it text
through a queue.
"""

from __future__ import annotations

import ctypes
import queue
import threading
from typing import Callable

from relay.diagnostics import get_logger

log = get_logger("ui.palette")

# state -> (light colour, default line)
STATES = {
    "ready": ("#2ea043", "Listening — say “Relay” or press Ctrl+Alt+Space"),
    "listening": ("#3fb950", "Listening… speak now"),
    "hearing": ("#d29922", "Got it…"),
    "working": ("#d29922", "Working on it…"),
    "thinking": ("#d29922", "Thinking…"),
    "speaking": ("#388bfd", "Speaking"),
    "off": ("#6e7681", "Off — not listening. Click On, or press Ctrl+Alt+Space to talk"),
    "stopped": ("#f85149", "Relay has stopped"),
}
_BG, _FG, _DIM = "#161b22", "#f0f6fc", "#9da7b3"


def _shorten(text: str, n: int = 110) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


class Palette:
    def __init__(self, status: Callable[[], str], on_toggle: Callable[[], None],
                 on_talk: Callable[[], None], on_quit: Callable[[], None]) -> None:
        self._status = status              # returns a key of STATES, polled
        self._on_toggle, self._on_talk, self._on_quit = on_toggle, on_talk, on_quit
        self._q: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self.visible = True
        self.ok = False                    # False if Tk isn't available (headless etc.)

    # ---- called from any thread ----
    def heard(self, text: str) -> None:
        self._q.put(("you", text))

    def said(self, text: str) -> None:
        self._q.put(("relay", text))

    def show(self, visible: bool) -> None:
        self._q.put(("show", "1" if visible else "0"))

    def stop(self, timeout: float = 3.0) -> None:
        self._q.put(("quit", ""))
        if self._thread is not None and self._thread.is_alive():
            try:
                self._thread.join(timeout=timeout)
            except Exception:
                pass

    def start(self) -> bool:
        self._thread = threading.Thread(target=self._run, name="palette", daemon=True)
        self._thread.start()
        self._ready.wait(5.0)
        return self.ok

    # ---- the palette's own thread ----
    def _run(self) -> None:
        try:
            import tkinter as tk
        except Exception as e:
            log.info("palette unavailable: %s", e)
            self._ready.set()
            return
        try:
            root = tk.Tk()
        except Exception as e:                   # no display
            log.info("palette unavailable: %s", e)
            self._ready.set()
            return
        self.ok = True
        root.title("Relay palette")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.attributes("-alpha", 0.94)
        except Exception:
            pass
        root.configure(bg=_BG, highlightthickness=1, highlightbackground="#30363d")

        top = tk.Frame(root, bg=_BG)
        top.pack(fill="x", padx=10, pady=(6, 0))
        light = tk.Canvas(top, width=14, height=14, bg=_BG, highlightthickness=0)
        dot = light.create_oval(2, 2, 13, 13, fill=STATES["ready"][0], outline="")
        light.pack(side="left")
        name = tk.Label(top, text="RELAY", bg=_BG, fg=_FG, font=("Segoe UI Semibold", 10))
        name.pack(side="left", padx=(6, 6))
        status = tk.Label(top, text=STATES["ready"][1], bg=_BG, fg=_DIM,
                          font=("Segoe UI", 10), anchor="w")
        status.pack(side="left", fill="x", expand=True)

        def button(text, cmd, width):
            b = tk.Label(top, text=text, bg="#21262d", fg=_FG, font=("Segoe UI", 9),
                         width=width, padx=4, pady=1, cursor="hand2")
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", lambda e: b.configure(bg="#30363d"))
            b.bind("<Leave>", lambda e: b.configure(bg="#21262d"))
            b.pack(side="left", padx=(4, 0))
            return b
        toggle = button("Off", self._on_toggle, 4)
        button("Talk", self._on_talk, 5)
        button("✕", self._on_quit, 2)

        you = tk.Label(root, text="", bg=_BG, fg=_FG, font=("Segoe UI", 10), anchor="w")
        you.pack(fill="x", padx=12)
        relay = tk.Label(root, text="", bg=_BG, fg="#a5d6ff", font=("Segoe UI", 10),
                         anchor="w")
        relay.pack(fill="x", padx=12, pady=(0, 6))

        # size and place: top centre of the main screen
        root.update_idletasks()
        w, h = 640, root.winfo_reqheight()
        x = (root.winfo_screenwidth() - w) // 2
        root.geometry(f"{w}x{h}+{x}+6")

        # never take focus, and stay out of Alt+Tab and RELAY's own window list
        try:
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            gwl_exstyle, noactivate, toolwindow = -20, 0x08000000, 0x00000080
            style = ctypes.windll.user32.GetWindowLongW(hwnd, gwl_exstyle)
            ctypes.windll.user32.SetWindowLongW(hwnd, gwl_exstyle,
                                                style | noactivate | toolwindow)
        except Exception as e:
            log.debug("palette window style: %s", e)

        drag = {"x": 0, "y": 0}

        def press(e):
            drag.update(x=e.x_root - root.winfo_x(), y=e.y_root - root.winfo_y())

        def move(e):
            root.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}")
        for wdg in (root, top, name, status, you, relay):
            wdg.bind("<ButtonPress-1>", press)
            wdg.bind("<B1-Motion>", move)

        self._ready.set()
        last = {"state": ""}

        def tick():
            try:
                while True:
                    kind, text = self._q.get_nowait()
                    if kind == "quit":
                        try:
                            root.quit()
                            root.destroy()
                        except Exception:
                            pass
                        return
                    if kind == "show":
                        self.visible = text == "1"
                        try:
                            root.deiconify() if self.visible else root.withdraw()
                        except Exception:
                            pass
                    elif kind == "you":
                        try:
                            you.configure(text="You: " + _shorten(text))
                        except Exception:
                            pass
                    elif kind == "relay":
                        try:
                            relay.configure(text="Relay: " + _shorten(text))
                        except Exception:
                            pass
            except queue.Empty:
                pass
            try:
                state = self._status()
            except Exception:
                state = "ready"
            if state != last["state"]:
                last["state"] = state
                colour, line = STATES.get(state, STATES["ready"])
                try:
                    light.itemconfigure(dot, fill=colour)
                    status.configure(text=line)
                    toggle.configure(text="On" if state == "off" else "Off")
                except Exception:
                    pass
            try:
                root.after(150, tick)
            except Exception:
                pass

        try:
            root.after(150, tick)
        except Exception:
            pass
        try:
            root.mainloop()
        except Exception as e:
            log.warning("palette stopped: %s", e)
        finally:
            try:
                root.destroy()
            except Exception:
                pass
