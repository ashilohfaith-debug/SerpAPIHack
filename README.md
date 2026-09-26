# RELAY

A voice assistant that lets a blind or low-vision person use a Windows PC for
everyday life — by talking. RELAY reads the screen through Windows UI Automation,
tells you what is there, does what you ask, checks that it worked, and tells you what
changed. It is a **transparent operator, not an autonomous agent**: it acts only when
you ask, announces every action before doing it, and never claims success it didn't
observe.

**Works with no keys, no accounts, no cloud.** Everything — speech recognition, the
voice, screen reading — runs on the laptop, offline, and is built for basic hardware:
~35 MB idle, ~400 MB peak, and about 2.5 s from the end of a spoken command to the first
word of the answer on an emulated budget dual-core laptop (measured; see
`docs/PERFORMANCE.md`).

**Optional online extras, set up once by the developer** (users never need a key):
ChatGPT-style spoken answers to anything through FreeLLMAPI or any OpenAI-compatible
router, and Sarvam's natural Indian voice. Copy `.env.example` to `.env`, paste the
keys — see **[docs/AI_AND_VOICE.md](docs/AI_AND_VOICE.md)**. If the internet or a
service fails, RELAY carries on offline.

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
| Ask anything (AI extra) | "what's a good name for a cat" · "explain what an index fund is" · "summarise this page" · "ask why is the sky blue" |

Full list: **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**. English only for now.

## Talking to RELAY
- **Ctrl+Alt+R** — start RELAY (after `RELAY.cmd --install`). It says "Starting Relay" at once.
- **Ctrl+Alt+Space** — talk key, from any app (chirp, then speak). Also interrupts RELAY.
- Or say **"Relay"** first (hands-free wake word; "turn off the wake word" for talk-key only).
- **Ctrl+Alt+Period** — stop talking / pause reading. **Ctrl+Alt+Backspace** — emergency stop.

RELAY never hears itself: the microphone is ignored while it speaks.

## Set up (one time, by the user or a sighted helper)
```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev,voice,percept,daily]"
uv run python -m relay --setup-models
RELAY.cmd --install
RELAY.cmd --check
```
`--setup-models` downloads the voice and speech model once (~140 MB); after that RELAY
never needs the internet. `--check` tests every part on this computer and says the result.
Then press **Ctrl+Alt+R** from anywhere. `RELAY.cmd --autostart on` starts it at sign-in.
A packaged build (no Python needed) is described in `docs/PACKAGING.md`.

## Checks you can run
```bash
uv run python -m relay --check               # this computer: models, voice, mic, keys, screen, offline (+ online extras if set)
uv run python -m relay --llm-check           # AI answers: first token / first sentence / first audio
uv run pytest -m "not integration"          # unit/behaviour tests
uv run python scripts/e2e_voice.py           # speech in -> action -> speech out, no mic
uv run python scripts/bench_basic_laptop.py  # emulated low-end laptops (CPU + 1 GB caps)
uv run python scripts/acceptance.py          # offline acceptance suite
uv run python -m relay --demo-daily          # everyday skills, nothing on screen changes
```

## Design
PERCEIVE (UIA, OCR fallback) → UNDERSTAND (offline grammar) → PLAN → ACT (single
permission gate) → VERIFY (re-observe) → NARRATE (announce before, changes after) →
RECOVER. Details: `docs/SECURITY.md`, `docs/ACCEPTANCE.md`, `docs/PERFORMANCE.md`,
`docs/PACKAGING.md`.

## Reused code (attribution)
See `NOTICE`. Small components adapted from MIT-licensed screen-use and clacky.
