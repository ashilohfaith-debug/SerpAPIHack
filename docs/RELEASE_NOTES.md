# RELAY — release notes

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

### Connected mode — Indian languages via Sarvam AI (opt-in)
Saaras speech-to-text (commands translated to English for the same offline grammar and
safety gate; dictation kept in the user's own script), Mayura translation, Bulbul
voices, and the Sarvam chat model as a validated fallback for free-form requests.
Spoken consent phrase to enable; ambient speech never leaves the device (wake word is
checked locally first); secrets never sent; automatic offline fallback.
**Tested against a fake service only — run `relay --sarvam-selftest` with a key.**

### Verification (all run on the development laptop)
196 unit/behaviour tests; end-to-end voice test 8/8 (synthesized speech → VAD → STT →
wake word → action → narration, incl. half-duplex); live desktop test 7/7 on a test
window; live app lifecycle 11/11 with real global hotkeys and microphone; live app
launch + close via the Start-menu catalogue. Not yet: clean-VM install, NVDA, blind-user
sessions, live Sarvam calls, signing (see `docs/ACCEPTANCE.md`).

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
