# RELAY — live demo script

A 6–8 minute demo that tells one story: **a blind person's day on a basic Windows
laptop, by voice — no internet account, no API keys, no cloud — and they always know
what's happening.**

## Before you go on stage (5 minutes)
1. `RELAY.cmd --check` — every line should say OK, and it says "All checks passed".
2. `RELAY.cmd --install` done once → **Ctrl+Alt+R** starts RELAY.
3. Laptop volume ~60%. A headset mic helps in a noisy hall (speakers are fine: RELAY
   ignores its own voice).
4. Close anything private. Have a browser, WhatsApp desktop, and one PDF in Downloads
   (e.g. `electricity bill.pdf`).
5. Optional for the audience: `RELAY.cmd --start --with-panel` shows what RELAY hears
   and says (the blind user never needs it).
6. To prove "no cloud": turn Wi-Fi **off** before starting (everything except the web
   search step works offline).
7. Dry run the whole script once.

## The demo
**0. Start without looking** — press Ctrl+Alt+R.
> "Starting Relay. One moment." … "Relay is ready. Press Control Alt Space, or say Relay."

**1. Morning basics (instant, offline)**
- "Relay, what time is it?" · "Relay, how's my battery?" · "Relay, status."
- "Relay, what's 15 percent of 2 lakh?" → "…is 30000."

**2. Transparency — the core idea**
- "Relay, open Calculator." → *"I'm going to open Calculator." … "Calculator is open."*
- Explain: RELAY announces **before** every action, checks the result by looking again,
  and reports what changed. It never runs on its own.

**3. Reading like a screen reader, by voice**
- "Relay, read the PDF electricity bill." → reading starts.
- "Stop." … "Continue." … "Next paragraph." … "Repeat." — a real reading cursor.

**4. The web** *(Wi-Fi on for this step only)*
- "Relay, search for today's weather in Hyderabad." → results open, RELAY confirms.
- "Relay, list the headings." / "Relay, read the page."

**5. Safety a blind user can trust**
- "Relay, open WhatsApp", pick a chat ("Relay, click <contact name>").
- "Relay, start dictation." → "see you at five full stop" → RELAY reads back what it typed.
- "Relay, stop dictation." → "Relay, send it." →
  *"I'm about to send this message: see you at five. To confirm, say: confirm send."*
  Say "yeah" → nothing happens. Say "confirm send" → sent.
- "Relay, emergency stop." → everything halts. "Continue." → ready again.

**6. Daily life**
- "Relay, remind me in 2 minutes to take my medicine." (let it go off during the demo)
- "Relay, take a note: call the bank tomorrow." · "Relay, read my notes."

**Close:** "Relay, goodbye." → *"Closing Relay. Goodbye."*

## Talking points
- **No keys, no accounts, no cloud**: speech recognition (Whisper tiny, int8), the voice
  (Piper) and screen reading (Windows UI Automation) all run on the laptop. `--check`
  proves no network lookups happen.
- **Built for basic laptops** (measured, emulated with Windows Job Objects): ~2.4 s from
  the end of a command to the start of the answer on a budget dual-core, ~3.3 s on a
  Celeron-class chip; ~2% CPU while waiting for "Relay"; ~400 MB peak under a 1 GB cap.
- Not an autonomous agent: user-directed, one step at a time, verified, interruptible.
- Honest by design: "I couldn't confirm that" instead of fake success; a casual "yeah"
  never sends a message or deletes a file.

## If something goes wrong on stage
- Mis-heard → press Ctrl+Alt+Space and repeat, closer to the mic.
- Hall too noisy for the wake word → "turn off the wake word" and use Ctrl+Alt+Space.
- Anything odd → "emergency stop", then "continue".
