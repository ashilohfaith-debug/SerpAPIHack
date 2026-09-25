# RELAY — security & privacy

RELAY observes and operates a user's computer, so privacy and safety are core, not
add-ons. This documents the guarantees the code actually implements (with file
references) and the honest limits.

## Privacy (implemented)
- **Local by default.** No screenshots, audio, documents or activity are transmitted
  anywhere. Essential mode has no network dependency at all. (Status questions like
  "am I online" ask Windows locally — no packets are sent.)
- **No keys, no accounts, no cloud.** RELAY contains no API client and needs no key or
  sign-in. Speech recognition (faster-whisper), the voice (Piper) and screen reading
  (UI Automation) all run locally. Once the models are on disk the speech model is loaded
  with `local_files_only` so start-up makes no network request (`relay/audio/stt.py`);
  `relay --check` verifies that no network lookup happens, and a test runs the everyday
  commands with networking blocked (`tests/test_daily.py`).
- **No screenshot retention.** Screen state (L1) lives in RAM and is replaced, not
  stored (`relay/perception/worker.py`). OCR captures are used and discarded.
- **Secret redaction in logs.** The logger drops password/OTP/token-shaped values
  (`relay/diagnostics/logging.py`).
- **Protected fields never read.** Password/OTP/PIN/CVV fields are detected and their
  values are never read aloud, logged, or stored (`relay/safety/policy.py::is_protected_field`,
  `relay/perception/uia.py`).
- **Memory refuses secrets.** The memory store rejects credential-shaped content
  (`relay/memory/store.py::looks_sensitive`); episodic capture is **opt-in** and off by
  default; deletion purges the FTS index too.
- **Per-user data.** Preferences/journal/memory live under `%LOCALAPPDATA%\RELAY`
  (`relay/config.py`).

## Safety (implemented)
- **Single permission chokepoint**, separate from any model: every action is classified
  and gated before the executor (`relay/safety/policy.py`, `relay/executor/executor.py`).
- **Accessible strong confirmation:** high-risk actions require an action-specific spoken
  phrase (never a bare "yes"); the most sensitive (purchase/install/security) require a
  keyboard/Windows-auth confirm and are declined by voice (`relay/accessibility/confirm.py`,
  `relay/session.py`). A demo: `relay --demo-confirm`.
- **Emergency stop** independent of any worker; flushes queued input and speech
  (`relay/core/emergency.py`).
- **No fabricated success:** actions are verified by re-observation; uncertain irreversible
  actions are never auto-repeated after a crash (`relay/verifier`, `relay/memory/reconcile.py`).
- **Untrusted content isolation:** text read from screens/pages/docs is data, never a
  command, and can't change permissions.
- **No force-closing apps / no destructive cleanup** (policy adopted after an early demo
  incident): RELAY never kills an app that may hold unsaved work. "Close" posts
  WM_CLOSE — the window's own X button — so the app's "save changes?" prompt appears
  and is read out (`relay/system/windows.py::request_close`).
- **Messages are read back before sending.** Enter in a chat/mail app (WhatsApp, Teams,
  Telegram, Slack, Discord, Signal, Outlook) is treated as *send*: RELAY reads the draft
  aloud and requires "confirm send" (`relay/skills.py::_send_guard`) — a speech-
  recognition slip can't silently send the wrong text.
- **Delete in File Explorer needs "confirm delete"** (`_explorer_delete_guard`).
- **RELAY never obeys its own voice.** The microphone is ignored while RELAY speaks
  (half-duplex, `relay/loop.py`), and the recogniser's bias prompt ("Hey Relay.")
  contains no command, so even a prompt echo on noise could not trigger an action
  (measured: silence, noise and hum transcribe to nothing).
- **Wake word only at the start.** "Relay" mid-sentence ("the relay race…") is not a
  command (`relay/audio/wake.py::detect_wake`); in open-mic dictation, recogniser
  hallucinations on noise ("Thank you.") are dropped, not typed.
- **Serialized commands, instant stop.** Commands run one at a time; stop / cancel /
  pause / emergency stop bypass the queue (`relay/loop.py::Dispatcher`). After an
  emergency stop nothing runs until the user says "continue".

## IPC (optional panel) — locked down
`relay/ipc/server.py`:
- Binds **loopback only** (127.0.0.1); Host header validated (anti DNS-rebind).
- **Per-session random token**, constant-time compared on every request.
- **Narrow command whitelist** (`handle`/`set_mode`/`onboard`/`ping`) routed through the
  same safety pipeline — **no raw click/type/coordinate automation is exposed**.
- Streams only a whitelist of state events.

## Windows boundaries (honest limits)
- Runs at the user's integrity level: it **cannot** drive elevated/admin apps or the UAC
  secure desktop, and does not try to. It says so rather than failing silently.
- No administrator privileges are requested by default.

## Input injection
Keys and clicks go through Win32 `SendInput` directly (`relay/executor/input_backend.py`),
behind the same permission gate as everything else — no third-party input library. If a
window running as administrator is in front, Windows refuses injected input and RELAY
says so instead of pretending the key was pressed.

## Global hotkeys
Registered with Win32 `RegisterHotKey` (`relay/audio/hotkeys.py`) — no keyboard hooks,
no keystroke logging, no admin rights. If a combination is owned by another program,
RELAY says so at start-up instead of silently having no talk key.

## Not yet done (release gates)
- Code signing (needs a certificate) — see `docs/PACKAGING.md`.
- A formal external security review and pinned SBOM.
- Optional at-rest encryption of the preference DB via Windows DPAPI (design noted; not
  implemented — no passwords are stored there regardless).
