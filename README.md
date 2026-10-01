<p align="center">
  <img src="app/frontend/logo.png" alt="Relay" width="420" />
</p>

<h3 align="center">Use your Windows PC by talking.</h3>

<p align="center">
  A voice assistant that actually works — built for blind and low-vision people,<br>
  useful for everyone. Free, open source, runs offline on basic hardware.
</p>

<p align="center">
  <a href="https://github.com/nagasaipradhyumnapoola/relay/releases"><strong>⬇ Download</strong></a> ·
  <a href="#what-can-relay-do">Features</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#how-it-works">How It Works</a> ·
  <a href="#voice-commands">Commands</a> ·
  <a href="#online-ai">AI Mode</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-blue" alt="Windows 10 | 11" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License" />
  <img src="https://img.shields.io/badge/offline-100%25%20core-orange" alt="Offline Ready" />
  <img src="https://img.shields.io/badge/RAM-4%20GB%20OK-purple" alt="4 GB RAM" />
</p>

---

## What is Relay?

Relay is a voice assistant that lets you control your entire Windows computer by speaking to it.

You say things like:
- *"Open Chrome"*
- *"Write hello world"*
- *"Read the screen"*
- *"What's the capital of France?"*
- *"Set the volume to 50"*
- *"Close this window"*

And Relay does it. For real. Not a demo — it actually opens the app, types the text, reads back what's on screen, and confirms what happened.

**It was built for people who can't see the screen**, but it's genuinely useful for anyone who wants to use their PC hands-free.

### What makes it different

| Others say | Relay actually does |
|---|---|
| "I opened the app" | Opens the app, waits for the window, reads the title back to you, confirms it's ready |
| "I typed your text" | Types it, reads back what's now in the text field, tells you the cursor position |
| "Here's what's on screen" | Uses Windows UI Automation to read real control names, not guessing from screenshots |
| "Requires internet" | Works 100% offline with local speech recognition and voice synthesis |
| "Needs 16 GB RAM + GPU" | Runs on a basic laptop with 4 GB RAM and no GPU |

---

## What Can Relay Do?

### 🗣️ Talk to Your PC
Open any app, type in any text field, click buttons, navigate menus, manage windows — all by voice. Multi-step commands work too: *"open Notepad and write hello world"* does both.

### 🧠 Ask Anything (AI Mode)
When connected to a free AI provider, Relay becomes a conversational assistant. Ask it anything — general knowledge, math, explanations — and it speaks the answer in a natural voice. Response time: **0.16 seconds**.

### 👁️ Screen Reading
Relay reads your screen using Windows UI Automation — the same system screen readers use. It sees real buttons, menus, text fields, and document content. No screenshots, no guessing, no AI hallucinating what's on screen.

### ✈️ Works Fully Offline
The core runs without internet. Speech recognition (Whisper) and voice (Piper) run locally. No cloud account. No data leaves your PC. If you want AI features, you can optionally connect free providers.

### 🛡️ Safe by Design
Risky things (deleting files, sending emails, shutting down) require spoken confirmation. Relay verifies every action and tells you what actually happened — never claims success without proof.

### 📝 Documents
Open Word, Notepad, or any text editor and dictate. Relay types your words, reads back what it wrote, and tells you the line and column. Read documents back with *"read the screen"*.

### 🔊 Natural Voice
Connect a free Sarvam AI key for a natural Indian English voice (Bulbul model). Falls back to clear offline voice when there's no connection.

### 🔄 Auto-Updates
When you push a new version to GitHub, every PC running Relay can update with a voice command: *"Relay, check for updates"* or run `relay --update` from the terminal.

---

## Quick Start

### Option A: Download (recommended)

1. **[Download Relay](https://github.com/nagasaipradhyumnapoola/relay/releases)** (ZIP, ~353 MB)
2. Unzip anywhere on your PC
3. Double-click **Install Relay.cmd**
4. Relay starts talking immediately

That's it. No Python, no pip, no terminal commands.

### Option B: From Source

```bash
git clone https://github.com/nagasaipradhyumnapoola/relay.git
cd relay/app
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[voice,dev]"
python -m relay --setup-models
python -m relay --start
```

### First Time

When Relay starts, it speaks to you:

> *"Hi, I'm Relay. I can help you use your computer by voice. Say 'Relay' followed by what you'd like to do."*

Press **Ctrl+Alt+Space** anytime to talk to Relay. Or just say *"Relay"* — it's always listening for the wake word.

---

## Voice Commands

### Opening Things
| You say | What happens |
|---|---|
| *"Open Chrome"* | Opens Google Chrome |
| *"Open Notepad"* | Opens Notepad |
| *"Open Word"* | Opens Microsoft Word |
| *"Open Settings"* | Opens Windows Settings |
| *"Open File Explorer"* | Opens File Explorer |

### Typing & Dictation
| You say | What happens |
|---|---|
| *"Write hello world"* | Types "hello world" in the focused text field |
| *"Type my name is Relay"* | Types the text |
| *"Open Notepad and write meeting notes"* | Opens Notepad, then types the text |

### Screen Reading
| You say | What happens |
|---|---|
| *"Read the screen"* | Reads the current window content aloud |
| *"Describe the screen"* | Describes what's on screen via UI Automation |
| *"What's on screen?"* | Same as above |

### Window Management
| You say | What happens |
|---|---|
| *"Close this window"* | Closes the current window |
| *"Minimize"* / *"Maximize"* | Minimizes or maximizes |
| *"Switch to Chrome"* | Switches to Chrome |

### System
| You say | What happens |
|---|---|
| *"Volume up"* / *"Volume 50"* | Adjusts volume |
| *"What time is it?"* | Tells the current time |
| *"What's the battery?"* | Reports battery percentage |
| *"Mute"* / *"Unmute"* | Toggles mute |

### AI / General Knowledge
| You say | What happens |
|---|---|
| *"What's the capital of Japan?"* | *"The capital of Japan is Tokyo."* |
| *"Explain photosynthesis simply"* | Gives a spoken explanation |
| *"What's 47 times 83?"* | *"47 times 83 is 3,901."* |

### Keyboard Shortcuts
| Key | What it does |
|---|---|
| **Ctrl+Alt+Space** | Start talking to Relay |
| **Ctrl+Alt+R** | Toggle Relay on/off |
| **Ctrl+Alt+.** | Stop speaking |
| **Ctrl+Alt+Backspace** | Emergency stop everything |

---

## Online AI (Optional)

Relay works fully offline, but you can optionally connect free AI providers for conversational features. Create a `.env` file:

```env
# Free local AI router (fastest — 0.16s response)
RELAY_LLM_URL=http://127.0.0.1:31415/v1
RELAY_LLM_KEY=your-freellmapi-key

# Google AI Studio (free tier)
GEMINI_API_KEY=your-google-ai-studio-key

# Natural voice (optional, free tier available)
SARVAM_API_KEY=your-sarvam-key
SARVAM_SPEAKER=kavya
SARVAM_LANGUAGE=en-IN
```

**Supported free providers:**
- [FreeLLMAPI](https://freellmapi.com) — local router, fastest
- [Google AI Studio](https://aistudio.google.com) — free Gemini access
- [Groq](https://groq.com) — fast inference
- [Sarvam AI](https://www.sarvam.ai) — natural Indian English voice

All keys are encrypted with Windows DPAPI and never leave your machine.

---

## How It Works

```
You speak → Whisper (local) → Intent Parser → Safety Check → UI Automation → Verify → Speak result
              ↓                                                    ↓
         Sarvam STT (online)                              Re-observe screen
         if available                                     to confirm changes
```

1. **You speak** — Relay listens via your microphone
2. **Speech → text** — Whisper (local) or Sarvam (online) converts speech
3. **Intent parsing** — Your words become a structured command (no AI needed for commands)
4. **Safety gate** — Risky actions require verbal confirmation
5. **Execute** — Relay uses Windows UI Automation to act on the real desktop
6. **Verify** — Relay re-reads the screen to confirm what changed
7. **Speak result** — Tells you what happened, honestly

For AI/general knowledge questions, steps 3-6 are replaced by routing to the configured LLM provider with speculative hedged routing for minimum latency.

---

## System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| **OS** | Windows 10 (1903+) | Windows 11 |
| **RAM** | 4 GB | 8 GB |
| **CPU** | Any dual-core x64 | Any modern CPU |
| **GPU** | Not needed | Not needed |
| **Disk** | 600 MB | 1 GB |
| **Internet** | Not required | Optional (for AI features) |
| **Microphone** | Any | USB headset |

---

## Auto-Updates Across PCs

When you push changes to this repository, any PC running Relay can update:

**Via voice:**
> *"Relay, check for updates"*

**Via terminal:**
```bash
relay --update
```

**How it works:**
- **Git installs** → runs `git pull --ff-only` automatically
- **Packaged installs** → checks GitHub Releases for newer `relay.exe`, downloads and replaces in-place
- Zero downtime — Relay restarts itself after updating

---

## Project Structure

```
relay/
├── app/
│   ├── relay/              # Core Python package
│   │   ├── audio/          # Microphone, TTS, STT
│   │   ├── core/           # Event bus, state machines, safety
│   │   ├── intent/         # Natural language → structured commands
│   │   ├── llm/            # AI assistant, hedged routing
│   │   ├── memory/         # Preferences, notes, DPAPI secrets
│   │   ├── perception/     # UI Automation screen reading
│   │   ├── planner/        # Multi-step execution engine
│   │   ├── sarvam/         # Online voice (Sarvam Bulbul)
│   │   ├── system/         # Windows APIs (volume, apps, keys)
│   │   ├── skills.py       # All voice command implementations
│   │   ├── session.py      # Live voice loop
│   │   └── update.py       # Auto-update mechanism
│   ├── frontend/           # Website & download portal
│   ├── packaging/          # PyInstaller build scripts
│   ├── tests/              # 460+ tests, 52 end-to-end chains
│   └── scripts/            # Benchmarks, health checks
├── logo.png
└── README.md
```

---

## Health Check

Run anytime to verify everything works:

```bash
relay --check
```

Output:
```
RELAY 0.3.3 — checking this computer

  [OK ] Data folder writable               C:\Users\you\AppData\Local\RELAY
  [OK ] Models present                     all present
  [OK ] Voice (text to speech)             0.23s to synthesise a sentence
  [OK ] Speech recognition                 heard 'What time is it?' in 0.52s
  [OK ] Microphone                         33 audio frames in 1 second
  [OK ] Screen reading (UI Automation)     reading explorer.exe: 65 controls
  [OK ] Installed apps list                237 apps on the Start menu
  [OK ] Sarvam voice (online)              bulbul:v3 kavya: 0.58s per sentence
  [OK ] AI assistant router (online)       first token 0.61s via auto:fast

All checks passed. Relay is ready to use.
```

---

## Contributing

Relay is open source under the MIT license. Contributions welcome.

```bash
git clone https://github.com/nagasaipradhyumnapoola/relay.git
cd relay/app
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[voice,dev]"
pytest -q                    # 460+ tests pass
python -m relay --selftest   # core wiring check
python -m relay --check      # full system check
```

---

## License

MIT — free for personal and commercial use.

---

<p align="center">
  <img src="app/frontend/logo.png" alt="Relay" width="120" /><br>
  <strong>Relay</strong> — because your computer should listen to you.<br>
  <sub>Made with ❤️ for accessibility.</sub>
</p>
