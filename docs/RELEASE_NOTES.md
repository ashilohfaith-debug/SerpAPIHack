# RELAY — release notes

## 0.3.3 — Palette, one Sarvam key, fastest AI routes, exe verified end to end

- **On-screen palette** at the top of the screen: a status light (ready, listening,
  working, speaking, off), "You: …" (what Relay heard) and "Relay: …" (its answer), and
  On/Off, Talk and Close buttons. It never takes keyboard focus. "stop listening" /
  "start listening", "hide the palette" / "show the palette".
- **One Sarvam key** turns on both the Bulbul voice and Saaras recognition
  (`SARVAM_STT=off` keeps only the voice).
- **Fastest AI routes:** `relay --llm-tune` (and the app, in the background every few
  days) times the router's models with a real Relay request and races the fastest that
  follow Relay's rules — on this laptop gemini-3.5-flash-lite (≈1.25 s to the first
  word) and qwen3.7-flash (≈1.5 s), with the router's own `auto:fast` as the backup.
  Rate-limited routes are rested and routed around.
- **Electron and Chromium apps** (Claude, VS Code / Antigravity, Brave, WhatsApp,
  Spotify): Relay now sees their buttons ("what are my options" in Claude lists its
  toolbar instead of one item).
- `relay --do "…"` behaves exactly like saying it (Start-menu apps and the AI assistant
  included). The packaged app has a double-click **Install Relay**.
- Fixes: the palette was missing from the packaged exe (Tkinter was excluded from the
  build); the build's clean-profile check left a 600 MB copy in %TEMP% every time (4 GB
  freed on C:).
- **Installed exe tested end to end on this laptop:** version, the full check (offline
  parts, Sarvam voice and recognition, AI router), 15 real commands through the exe
  (time, date, battery, storage, network, Bluetooth, brightness, weather, sums, an AI
  question, "open andy gravity" → Antigravity, a two-step command with Calculator,
  closing it, screenshot, new folder), and the running app: Ctrl+Alt+R starts it with
  the microphone listening and presses again to close it.

## 0.3.2 — Do things on the laptop, one step or many

A sweep of 106 things a blind user says on a laptop found 43 that failed or did the
wrong thing. All are handled now; details in the user guide (sections 4a, 4b).

- **App names as speech recognition spells them.** "Antigravity" heard as "anti
  gravity", "Andy gravity" or "and gravity"; "what sapp", "spot if i", "vs code" — all
  match now (spacing-free and sound-alike matching). A weak match is offered ("Did you
  mean Antigravity?"), never launched. Apps already open but not on the Start menu are
  switched to.
- **Laptop controls:** Bluetooth / Wi-Fi on-off and status, brightness, dark mode,
  screenshot, shut down / restart / sleep / sign out (spoken confirmation; shut down
  waits a minute and can be cancelled), storage, IP and Wi-Fi name, Windows Update, any
  Settings page, the Recycle Bin, the weather (wttr.in, no key), alarms.
- **File Explorer actions** on the selected item: rename, move, copy, delete (to the
  Recycle Bin, confirmed), new folder; "close all windows" (confirmed); email via Gmail.
- **Several steps in one request** ("open Notepad, type …, then save it as …"): the plan
  is said first, steps run in order, and the run stops at the first failure. Free text
  is never split, so a sentence being typed can't turn into a command.
- **AI plans** (with FreeLLMAPI): the assistant can return up to 8 steps, each checked
  against RELAY's own commands — all or nothing, never a confirmation phrase.
- **FreeLLMAPI desktop app found automatically:** it listens on port 31415 (Docker and
  source use 3001); a local router address with the wrong port is corrected.
- **Fixes found by testing live on a real laptop:** "open file explorer" opened a file
  named "explorer"; "close all windows" looked for a window called "all windows"; "set an
  alarm for 6 am" wasn't understood and "wake me up at 7" meant 7 pm; a document search
  fallback could open a similarly named file (e.g. calculator3d.html for "calculator") —
  it now needs you to say it's a document or an exact name, and never runs while the app
  list is still loading.
- **Safety fix after a live-test incident:** Windows 11 Notepad reopens earlier tabs,
  including unsaved ones, so "open Notepad and type …" could type into someone's
  document. RELAY now opens a new blank page first, and types nothing if it can't.
- Tests: 351 pass. Live on this laptop: weather, storage, Bluetooth status, network,
  brightness, screenshot, new folder, "andy gravity" → Antigravity, two steps (open
  Calculator + the time) and closing it — all passed.

## 0.3.1 — Headphones, closing by keyboard, FreeLLMAPI on its own

### Headphones and earphones
- RELAY now plays and listens through Windows' **current default device** (the Sound
  Mapper) instead of the device that was default when it started — so headphones plugged
  in later (wired, USB, Bluetooth) get RELAY's voice straight away, and it says so.
- **Interrupt by voice with headphones:** RELAY can't hear itself, so it keeps listening
  while it talks — "stop", or "Relay" and a new request. Room conversation is still
  ignored. Automatic for headphones/headsets, and for USB/Bluetooth audio that has its
  own microphone on the same device (USB-C earphones and adapters — e.g. an "AB13X USB
  Audio" adapter that Windows calls "Speakers"; RELAY says it's guessing). "headphone
  mode on/off/automatic" and "I'm using headphones" correct it **for that device only**,
  remembered — the laptop's own speakers stay half-duplex.
- **Unplugged mid-reading → paused**, not read aloud to the room ("Headphones
  disconnected, so I've paused. Say continue to carry on.").
- A Bluetooth headset's hands-free microphone is avoided (it forces phone-call audio
  quality); RELAY keeps the laptop microphone. "where is the sound going" reports both.
- Cost on a basic laptop: one device-ID query every half second, about 0.25 ms of CPU
  (device names are read only when something changes). No extra playback latency
  (Sound Mapper 0.18 s vs 0.19 s to open and play a clip, measured).

### Closing RELAY
- **Ctrl+Alt+R again closes RELAY** (the shortcut now runs `relay --toggle`), like
  Narrator's Ctrl+Win+Enter — a keyboard way out when speaking isn't possible. Voice
  still works: "quit Relay", "close Relay", "goodbye Relay".

### Fixes
- The talk key and a spoken "Relay, …" now cancel a streaming AI answer too; before,
  only the current sentence stopped and the answer carried on.
- The screen-reading thread now initialises Windows COM itself; it used to depend on
  being the first to load it, which breaks as soon as another part (audio devices,
  volume) loads it first.

### Setup
- FreeLLMAPI alone is enough: `.env.example` lists it first; Sarvam is optional and its
  extra settings are commented out. A test proves no Sarvam call happens without its key.
- One `.env` for both copies: the installed app's `.env` can hold just
  `RELAY_ENV_FILE=<path to the project's .env>`.
- Tests: 271 pass. Live: the assembled app saw the real devices and closed 0.6 s after
  the Ctrl+Alt+R signal, saying goodbye. Headphone hot-plugging itself is covered by
  unit tests only (no plug/unplug was performed here).

## 0.3.0 — Instant AI answers and the Sarvam voice (optional, one `.env` file)

Still works with no keys, fully offline. New, and only when the developer fills in
`.env` once (users never need a key of their own — this is not bring-your-own-key):

### Ask anything, answered like a conversation
- Anything the built-in commands don't cover goes to an AI router — FreeLLMAPI or any
  OpenAI-compatible `/v1` endpoint — and the answer is **spoken sentence by sentence
  while it is still being written**. "summarise this page" / "what is this email about"
  summarise what's on screen; follow-up questions keep context; "ask …" forces a question.
- Latency first: streaming, persistent connections opened at start-up, synthesis of the
  next sentence while the current one plays, and **hedged routing** (race `auto:fast`
  and `auto`; fail over at once on errors; rest a rate-limited route; give up after 6 s
  and keep working offline). With a simulated 0.35 s router, first audio is ready in
  **0.65–0.73 s**; `relay --llm-check` measures real providers.
- An AI-suggested action (`DO: …`) must parse with the offline grammar, can never be a
  confirmation / emergency / quit / delete phrase, is announced, and still passes the
  permission gate.

### Sarvam voice and recognition
- `SARVAM_API_KEY` switches RELAY's voice to Sarvam Bulbul (any failure falls back to
  the offline voice for that sentence, and RELAY says so once). Passwords and codes are
  always spoken by the offline voice.
- `SARVAM_STT=on` adds Saaras recognition (Indian accents; Indian languages translated
  to English commands). The wake word is checked on the laptop first, so room
  conversation is never uploaded.
- `SARVAM_BASE_URL` lets a public build talk to your own gateway instead of carrying
  the real key.

### Also
- `.env.example` (tracked) → `.env` (git-ignored, bundled by `build.ps1` with a warning).
  `RELAY_OFFLINE=1` ignores every key.
- `relay --check` adds Sarvam voice, Sarvam recognition and AI router checks when
  configured, after proving the offline parts use no network.
- Fixed: after "stop", an online-voice request still in flight no longer keeps the
  microphone deaf; the router cancels a losing stream by closing its socket at once.
- The public-domain voice `en_US-ljspeech-medium` is now downloaded and active.
- Tests: 244 pass, including the real wire formats against local mock servers.
  Live checks: end-to-end voice 9/9 (with an AI answer), assembled app 11/11 offline
  and 11/11 with online services (mocked), window operations 7/7.

## 0.2.1 — No keys, basic laptops, works when opened

### No keys, no accounts, no cloud
The optional Sarvam "Connected mode" added in 0.2.0 needed an API key, which is against
what RELAY is for. It is **removed** — code, commands and docs. Every feature runs on
the laptop. `relay --check` proves no network lookups happen, and a test runs the
everyday commands with networking blocked.

### Built for basic laptops (measured with emulated low-end CPUs, 1 GB cap enforced)
- End of a spoken command → first word of the answer: **2.4 s** on a budget dual-core,
  **3.3 s** on a Celeron-class chip (were 10.6 s / 10.7 s). The voice now generates
  4x faster than it plays (it stuttered before).
- The model runtimes no longer start a spinning thread per core or busy-wait; threads
  match the cores really available.
- Waiting for the wake word costs ~2% of one core (was 19–47%): room noise is screened
  before it reaches the speech model. Talk-key-only mode: 0.1%.
- Start-up says "Starting Relay. One moment." instantly, so a 6–10 s start is never silent.
- The speech model no longer contacts the model hub at every start.
- Correction: the old "survived a 1 GB cap" figure came from a helper with a handle bug
  that may never have applied the cap. Fixed and verified; re-measured peak is 402 MB.

### Works when opened
- `relay --check`: models, voice, speech recognition, microphone, speakers, the three
  global keys, screen reading, app list, volume, database, single instance, and "no
  network used" — printed and spoken.
- The packaged app passes a clean-profile check (`scripts/clean_machine_check.py`): no
  Python on PATH, empty data folder, dead proxies; all 129 DLLs it imports are bundled or
  part of Windows (incl. the Visual C++ runtime); `--check` passes; the windowless
  `relay.exe` starts, stays up, logs no errors and opens no internet connections.
- Microphone muted or blocked → after two silent talk-key presses RELAY says so.

### Licences and SBOM
- `docs/SBOM.md` + `packaging/requirements.lock` generated from package metadata.
- **piper-tts is GPL-3.0** (embeds espeak-ng; the old docs said MIT). A packaged build
  with Piper must be distributed under GPL-3.0 terms — decision pending (see THIRD_PARTY).
- pyautogui (which pulled in two GPL-3.0 packages) replaced by direct Win32 SendInput.
- The voice RELAY used (Lessac) is licensed for research only. The release voice is now
  `en_US-ljspeech-medium` (public domain, trained from scratch); the build warns if it
  has to fall back to the research-only voice.

### Screen readers
With NVDA, JAWS or Narrator running, RELAY no longer repeats focus changes they already
announce (it still reports everything else). Tested in code; not yet with a real screen
reader running.

### Also
Code-signing script (`packaging/sign.ps1`, needs a certificate), blind-user testing
protocol (`docs/USER_TESTING.md`), command-type-only logging (never the spoken words).

## 0.2.0 — Daily life, end to end

Built from an end-to-end audit from a blind user's point of view: "could someone who
can't see the screen start RELAY, talk to it, and get through a normal day?" In 0.1.0
the answer was no. The fixes and additions:

### Blockers fixed (found by the audit)
- **No talk key existed** although onboarding promised one → global talk key
  (Ctrl+Alt+Space), stop key (Ctrl+Alt+Period), emergency key (Ctrl+Alt+Backspace), with
  earcons (listening chirp, "got it", "heard nothing", error, reminder).
- **RELAY could hear and obey its own voice** through the speakers (its greeting says
  "Relay") → half-duplex microphone.
- **"Relay" was mis-heard as "Really"** about a third of the time → measured, fixed with a
  non-actionable recogniser prompt (10/10 on the test set).
- **First syllable clipped** (no pre-roll); **unbounded utterances** → 300 ms pre-roll, 15 s cap.
- **"stop" did nothing** (the handler was a stub) → stops speech and pauses reading.
- **Memory commands would crash** from the voice thread (SQLite thread binding) and
  **commands could run concurrently** → one ordered dispatcher; stop/cancel/emergency
  jump the queue.
- **A cancelled or blocked action could be announced as "Done"** if the screen happened to
  match → verifier keeps CANCELLED/FAILED outcomes as they are.
- **"switch to X" launched a second copy** of the app → switches to the existing window.
- **"click the second link" counted by control size**, not reading order → reading order,
  with role words (link/button/result).
- **Reading stopped at 200 characters** → whole documents and web pages, with a cursor.
- **Emergency stop was permanent** until restart → "continue" clears it.
- **Wake word anywhere in a sentence triggered** ("the relay race…") → start only.
- **A blind user couldn't start RELAY** (needed a terminal) → desktop shortcut with
  Ctrl+Alt+R, Start-menu entry, optional start at sign-in, windowless launch, spoken
  start-up errors, spoken "already running".
- Frozen builds looked for models in the wrong folder; versions were inconsistent.

### New everyday abilities
Time, date, battery, internet/Wi-Fi, status · volume (exact level read back) and media
keys · spoken maths with lakh/crore · open any installed app (Start-menu catalogue,
classic and Store apps) · list/switch/minimize/maximize/close windows · web search,
YouTube, known sites and spoken domains · headings and links on web pages (native UIA
search, deep in the page) · continuous reading with stop/continue/next/previous/repeat ·
reading PDFs, Word and text files · OCR reading of a window · clipboard · dictation mode
with spoken punctuation · named shortcuts (copy, paste, undo, new tab…) and any key
combination · notes · reminders and timers that survive restarts · speech speed ·
yes/no follow-ups ("Should I search the web instead?") · "open the second one" from any
list RELAY read out · topic help.

### Safety for real use
Enter in chat apps reads the message back and needs "confirm send"; Delete in File
Explorer needs "confirm delete"; window-frame buttons and background windows are no
longer read out as if they mattered.

### Connected mode (removed in 0.2.1)
An opt-in Sarvam AI mode for Indian languages; it required an API key and was removed.

### Verification (all run on the development laptop)
196 unit/behaviour tests; end-to-end voice test 8/8 (synthesized speech → VAD → STT →
wake word → action → narration, incl. half-duplex); live desktop test 7/7 on a test
window; live app lifecycle 11/11 with real global hotkeys and microphone; live app
launch + close via the Start-menu catalogue. Not yet: clean-VM install, NVDA, blind-user
sessions, signing (see `docs/ACCEPTANCE.md`).

## 0.1.0 — Essential mode (first end-to-end build)

RELAY is a Windows-first, **offline-first, voice-first** accessibility layer for blind
and low-vision users. It is a **transparent operator, not an autonomous agent**: it acts
only when asked, announces each action before doing it, reports every change it causes,
and idles between tasks — the user always knows what is on screen and what just happened.

### What works in this build (verified offline)
- **Voice loop, wake-gated.** Mic → VAD → faster-whisper (tiny.en, int8) → dispatch.
  RELAY acts only on utterances addressed to it ("relay …"); push-to-talk is always
  available and never depends on recognition working. Barge-in interrupts speech.
- **Transparent narration.** Announce-before-acting, then a change-delta after; verbosity
  modes (quick / detailed / guided / quiet).
- **Windows control via UI Automation** on a dedicated worker thread, with window
  find/activate, an honest per-app capability matrix, and on-demand OCR fallback.
- **Safety chokepoint** separate from any model: 6-tier risk classification; high-risk
  actions require an **action-specific spoken phrase** (never a bare "yes"); the most
  sensitive require keyboard/Windows-auth and are declined by voice. **Emergency stop**
  is independent of the workers. RELAY **never force-closes apps** or does destructive
  cleanup.
- **No fabricated success.** Actions are verified by re-observation; after a crash,
  uncertain irreversible actions are reported and **never auto-repeated**.
- **Five-layer memory** (live screen / task / preferences / workflows / opt-in episodic)
  on SQLite (WAL + FTS5) with an append-only action journal; **refuses to store secrets**;
  episodic capture is off by default.
- **Privacy by default.** No screenshots retained, no network in Essential mode, secret
  redaction in logs, protected fields never read.
- **Optional accessible panel** ("what's working") over a locked-down loopback IPC
  (token auth + narrow command whitelist); voice can operate everything without it.
- **Single-instance** lifecycle; spoken onboarding; clean shutdown.

### Footprint (measured on the dev machine, not estimated)
Idle ~35 MB; Essential-mode peak ~330–406 MB; survived a hard 1 GB memory cap; lazy
unload frees ~176 MB. Fits comfortably in a 4 GB machine's budget.

### Packaging
One-folder PyInstaller build (`packaging/relay.spec`, `build.ps1`) with models bundled
beside the exe for offline start. See `docs/PACKAGING.md`.

### Not done yet — real-world release gates (require hardware/people/certs)
These are specified and scripted as far as possible but are **not** claimed as passed:
- Building and running the packaged app on a **clean, offline Windows VM**.
- **NVDA coexistence** testing (NVDA not installed here).
- **4 GB-hardware** latency certification.
- **Code-signing** the exe/installer (no certificate available).
- **Supervised testing with blind users.**
- Confirm the Piper voice's redistribution license and pin an SBOM
  (see `docs/THIRD_PARTY.md`).

### How to try it
```
uv run python -m relay --voice-selftest      # offline TTS->STT round-trip
uv run python -m relay --capabilities        # what RELAY can/can't drive
uv run python -m relay --demo-confirm        # spoken high-risk confirmation
uv run python scripts/acceptance.py          # offline acceptance suite
```
`relay --start` runs the live spoken onboarding + voice loop (not auto-run for safety).

See `docs/ACCEPTANCE.md` for the full requirement-by-requirement status and
`docs/SECURITY.md` for the privacy/safety guarantees with file references.
