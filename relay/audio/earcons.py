"""Earcons — short sounds that tell a blind user what state RELAY is in.

A sighted user sees a "listening" indicator; a blind user needs to hear it. Tones are
generated (no audio files to ship) and played on the speech output path, so they
never collide with speech and are silenced by "stop" like everything else.

  listen   rising two-note chirp  — "I'm listening, speak now"
  heard    single soft note       — "got it, working on it"
  nothing  falling two-note       — "I didn't hear anything / cancelled"
  error    low double buzz        — "that didn't work"
  alert    three-note chime       — a reminder is due
"""

from __future__ import annotations

import numpy as np

SR = 22050


def _tone(freq: float, ms: int, vol: float = 0.25) -> np.ndarray:
    n = int(SR * ms / 1000)
    t = np.arange(n) / SR
    wave = np.sin(2 * np.pi * freq * t)
    fade = min(n // 4, int(SR * 0.012))           # click-free edges
    env = np.ones(n)
    if fade:
        env[:fade] = np.linspace(0, 1, fade)
        env[-fade:] = np.linspace(1, 0, fade)
    return (wave * env * vol).astype(np.float32)


def _gap(ms: int) -> np.ndarray:
    return np.zeros(int(SR * ms / 1000), dtype=np.float32)


def _seq(*parts) -> np.ndarray:
    return np.concatenate(parts).astype(np.float32)


EARCONS = {
    "listen": _seq(_tone(660, 70), _gap(15), _tone(990, 90)),
    "heard": _tone(880, 60, 0.18),
    "nothing": _seq(_tone(740, 70), _gap(15), _tone(494, 110)),
    "error": _seq(_tone(220, 110, 0.3), _gap(40), _tone(220, 110, 0.3)),
    "alert": _seq(_tone(784, 120), _gap(30), _tone(988, 120), _gap(30), _tone(1319, 180)),
}


def earcon(name: str) -> tuple[np.ndarray, int]:
    return EARCONS[name], SR
