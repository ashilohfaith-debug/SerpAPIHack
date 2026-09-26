# RELAY — live demo script

A 6–8 minute demo that tells one story: **a blind person's day on a basic Windows
laptop, by voice — the user never needs an account or a key, the core works with no
internet at all — and they always know what's happening.** With the optional extras
set up in `.env` (docs/AI_AND_VOICE.md), RELAY also speaks in Sarvam's natural Indian
voice and answers anything, ChatGPT-style.

## Before you go on stage (5 minutes)
0. For the online extras: `.env` filled in, FreeLLMAPI running, then
   `RELAY.cmd --llm-check` — "first audio" should be about a second or less.
1. `RELAY.cmd --check` — every line should say OK, and it says "All checks passed"
   (with `.env`, three online checks appear at the end).
2. `RELAY.cmd --install` done once → **Ctrl+Alt+R** starts RELAY.
3. Laptop volume ~60%. A headset mic helps in a noisy hall (speakers are fine: RELAY
   ignores its own voice).
4. Close anything private. Have a browser, WhatsApp desktop, and one PDF in Downloads
   (e.g. `electricity bill.pdf`).
5. Optional for the audience: `RELAY.cmd --start --with-panel` shows what RELAY hears
   and says (the blind user never needs it).
6. To prove the core needs no cloud: turn Wi-Fi **off** for steps 1–3 (RELAY says once
   that it's using its offline voice), then on for steps 4 and 7.
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

**7. Ask anything — instant spoken answers** *(Wi-Fi on; needs the `.env` extras)*
- "Relay, what's a good name for a golden retriever?" → the answer starts in about a
  second, spoken sentence by sentence while it's still being written.
- "Relay, and for a black cat?" → it remembers the conversation.
- On a web page or email: "Relay, summarise this page."
- "Relay, could you check the clock for me?" → *"I understood that as: what time is
  it."* — an AI suggestion still goes through RELAY's own safe commands.
- Start a long answer and say "stop" → silence at once.
- Point out the voice: Sarvam's natural Indian voice; passwords and codes are always
  spoken by the offline voice and never sent anywhere.

**Close:** "Relay, goodbye." → *"Closing Relay. Goodbye."*

## Talking points
- **The user needs no key, no account**: speech recognition (Whisper tiny, int8), the
  voice (Piper) and screen reading (Windows UI Automation) all run on the laptop.
  `--check` proves the offline parts make no network lookups. The online extras use the
  developer's keys, set up once, and fall back to offline automatically.
- **Instant answers by design**: streamed, spoken per sentence, synthesis overlapped with
  playback, persistent connections, two routes raced (hedging) — RELAY adds about 0.3 s
  on top of the model's first token.
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
- Venue Wi-Fi down → RELAY says it's using its offline voice / can't reach the AI; every
  built-in command still works. Skip step 7.
