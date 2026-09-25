# RELAY — live demo script (Sarvam build)

A 6–8 minute demo that tells one story: **a blind person's day on a Windows laptop,
by voice, in their own language — and they always know what's happening.**

## Before you go on stage (5 minutes)
1. Laptop volume ~60%, a USB/headset mic if possible (speakers are fine: RELAY is
   half-duplex and ignores its own voice).
2. `RELAY.cmd --install` done once → **Ctrl+Alt+R** starts RELAY.
3. Sarvam key saved in `%LOCALAPPDATA%\RELAY\sarvam_key.txt`, then run
   `RELAY.cmd --sarvam-selftest` — all four lines should say OK.
4. Close anything private. Have Chrome/Edge signed in (for YouTube), WhatsApp desktop
   installed, one PDF in Downloads (e.g. `electricity bill.pdf`).
5. Optional panel for the audience: `RELAY.cmd --start --with-panel` shows what RELAY
   hears and says (the blind user never needs it).
6. Dry run the whole script once.

## The demo
**0. Start (no screen needed)** — press Ctrl+Alt+R.
> RELAY: "Relay is ready. Press Control Alt Space, or say Relay, to talk to me."

Point out: *everything from here is voice; eyes closed if you like.*

**1. Morning basics (offline, instant)**
- "Relay, what time is it?" → "It's 9:40 AM."
- "Relay, how's my battery?" · "Relay, am I connected to the internet?"
- "Relay, what's 15 percent of 2 lakh?" → "…is 30000."

**2. Transparency — the core idea**
- "Relay, open Calculator." → *"I'm going to open Calculator." … "Calculator is open."*
- Explain: RELAY announces **before** every action, checks the result by looking again,
  and reports what changed. It never runs on its own.

**3. The web, read aloud**
- "Relay, search for today's weather in Hyderabad." → results open, RELAY confirms.
- "Relay, list the headings" / "Relay, read the page." → reading starts.
- "Stop." … "Continue." … "Next paragraph." — a real reading cursor.

**4. Indian languages with Sarvam** *(the Sarvam moment)*
- "Relay, turn on connected mode." → RELAY explains exactly what is sent to Sarvam, and
  waits for the consent phrase → "confirm connect".
- Press **Ctrl+Alt+Space** and speak Hindi: *"abhi kitne baje hain?"* → answered in
  Hindi (Saaras STT → offline grammar → Mayura → Bulbul). (Saying "Relay, …" first also
  works: the wake word is checked on the laptop, and only speech addressed to RELAY is
  sent to Sarvam — room conversation never leaves the device.)
- "Relay, read this page in Telugu." → the English web page, read aloud in Telugu.
- Free-form request: *"Relay, mujhe YouTube pe koi gaana sunao"* → *"I understood that
  as: search youtube for songs."* → still gated and narrated.

**5. Safety a blind user can trust**
- Open WhatsApp, pick a chat ("Relay, open WhatsApp" … "click <contact name>").
- "Relay, start dictation." → "see you at five full stop" → RELAY reads back what it typed.
- "Relay, stop dictation." → "Relay, send it." →
  *"I'm about to send this message: see you at five. To confirm, say: confirm send."*
  Say "yeah" → nothing happens. Say "confirm send" → sent.
- "Relay, emergency stop." → everything halts. "Continue." → ready again.

**6. Daily life**
- "Relay, remind me in 2 minutes to take my medicine." (let it go off later in the demo)
- "Relay, take a note: call the bank tomorrow." · "Relay, read my notes."
- "Relay, read the PDF electricity bill."

**Close:** "Relay, goodbye." → *"Closing Relay. Goodbye."*

## Talking points
- Offline-first: the whole English experience runs on the laptop (≈35 MB idle,
  ≈330–400 MB peak, measured). Sarvam adds Indian languages only after consent.
- Not an autonomous agent: user-directed, one step at a time, verified, interruptible.
- Honest by design: "I couldn't confirm that" instead of fake success; a casual "yeah"
  never sends a message or deletes a file.
- Tested: 196 automated tests; end-to-end voice test (speech in → action → speech out);
  live desktop checks; live app lifecycle with real global hotkeys.

## If something goes wrong on stage
- Mis-heard → press Ctrl+Alt+Space and repeat, closer to the mic.
- Network drops → RELAY says so and continues in offline English — show that as a feature.
- Anything odd → "emergency stop", then "continue".
