# RELAY — release notes

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
