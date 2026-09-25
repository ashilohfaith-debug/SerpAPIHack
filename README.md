# RELAY

A voice assistant that lets a blind or low-vision person use a Windows PC for
everyday life — by talking. RELAY reads the screen through Windows UI Automation,
tells you what is there, does what you ask, checks that it worked, and tells you what
changed. It is a **transparent operator, not an autonomous agent**: it acts only when
you ask, announces every action before doing it, and never claims success it didn't
observe.

Essential mode is **fully offline** (English). Optional **Connected mode** adds Indian
languages — Hindi, Telugu, Tamil, Kannada, Malayalam, Marathi, Gujarati, Bengali,
Punjabi, Odia — through [Sarvam AI](https://www.sarvam.ai), only after a spoken
consent phrase.

## What a user can do (examples)
| Need | Say |
|---|---|
| Know the basics | "what time is it" · "what's the date" · "how's my battery" · "am I online" · "status" |
| Open anything | "open WhatsApp" · "open Word" · "open my downloads" · "open YouTube" |
| Web | "search for today's weather" · "play Arijit Singh on YouTube" · "list the links" · "open the third link" |
| Read | "read the page" (stop / continue / next paragraph / repeat) · "read the PDF electricity bill" · "read the clipboard" · "read with OCR" |
| Write | "type Hello, how are you?" · "start dictation" … "stop dictation" · "select all" · "copy" · "undo" |
| Windows | "what windows are open" · "switch to Chrome" · "minimize" · "close Notepad" · "show desktop" |
| Everyday | "what is 15 percent of 2 lakh" · "take a note buy milk" · "read my notes" · "remind me in 10 minutes to call mom" |
| Control | "volume up" · "set volume to 40 percent" · "pause music" · "next track" · "speak slower" |
| Safety | "stop" · "cancel" · "emergency stop" · risky actions need a spoken phrase ("confirm send", "confirm delete") |
| Languages | "turn on connected mode" · "speak in Hindi" · "read this page in Telugu" |

Full list: **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**.

## Talking to RELAY
- **Ctrl+Alt+Space** — talk key, from any app (chirp, then speak). Also interrupts RELAY.
- Or say **"Relay"** first (hands-free wake word; can be turned off).
- **Ctrl+Alt+Period** — stop talking / pause reading. **Ctrl+Alt+Backspace** — emergency stop.
- **Ctrl+Alt+R** — start RELAY (after `RELAY.cmd --install`).

RELAY never hears itself: the microphone is ignored while it speaks.

## Set up (one time, by the user or a sighted helper)
```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev,voice,percept,daily]"
uv run python -m relay --setup-models
RELAY.cmd --install
```
Then press **Ctrl+Alt+R** from anywhere. `RELAY.cmd --autostart on` starts it at sign-in.
Connected mode: put a Sarvam API key in `%LOCALAPPDATA%\RELAY\sarvam_key.txt` (or the
`SARVAM_API_KEY` environment variable), then say "turn on connected mode".

## Checks you can run
```bash
uv run pytest -m "not integration"          # 196 unit/behaviour tests
uv run python scripts/e2e_voice.py           # speech in -> action -> speech out, no mic
uv run python scripts/acceptance.py          # offline acceptance suite
uv run python -m relay --demo-daily          # everyday skills, nothing on screen changes
uv run python -m relay --sarvam-selftest     # Connected mode, needs your key
```

## Design
PERCEIVE (UIA, OCR fallback) → UNDERSTAND (offline grammar; Sarvam chat only as a
validated fallback) → PLAN → ACT (single permission gate) → VERIFY (re-observe) →
NARRATE (announce before, changes after) → RECOVER. Details: `docs/SECURITY.md`,
`docs/ACCEPTANCE.md`, `docs/PERFORMANCE.md`, `docs/PACKAGING.md`.

## Reused code (attribution)
See `NOTICE`. Small components adapted from MIT-licensed screen-use and clacky.
