# RELAY — supervised testing with blind and low-vision users

Automated checks prove RELAY's parts work; only people who use a computer without
sight can tell us whether RELAY is *usable*. This is a ready-to-run protocol for
5–8 participants, ~60 minutes each.

## Before the session
- Laptop set up with `RELAY.cmd --install` and `RELAY.cmd --check` passing.
- A **fresh user profile** for RELAY data: set `RELAY_DATA_DIR` to a new folder, so the
  first-run introduction plays and nobody else's notes appear.
- A headset microphone and a spare pair of speakers; a quiet room.
- Consent: explain the goal, that RELAY runs entirely on the laptop, that nothing is
  recorded except the observer's notes and RELAY's own log (`relay.log`, no speech
  audio, no typed text), and that they can stop at any time. Get verbal consent on record.
- Ask (and note): screen reader normally used (NVDA / JAWS / Narrator / none), years of
  computer use, typical daily tasks, and whether they'd like their screen reader on.
- Observer never touches the keyboard or mouse; only reads the task card aloud.

## Tasks (read each card aloud; don't coach the exact words)
| # | Task card | Success = |
|---|---|---|
| 1 | "Start Relay without the mouse." | Relay started with Ctrl+Alt+R and the user knew it was ready |
| 2 | "Find out the time and how much battery is left." | both answered |
| 3 | "Open Notepad and write two sentences about your day." | text is in Notepad |
| 4 | "Save it as 'my day' in Documents." | file exists; any overwrite question handled |
| 5 | "Search the web for the weather in your city and find the temperature." | temperature heard |
| 6 | "Read the second paragraph of that page again." | used continue / next / previous / repeat |
| 7 | "Set a reminder for two minutes from now." | reminder spoken on time |
| 8 | "Take a note, then hear all your notes." | note read back |
| 9 | "Open the PDF in Downloads and hear the first page." | text read aloud |
| 10 | "Send a message to [test contact] in WhatsApp — but first make RELAY read it back to you." | message read back; sent only after "confirm send" |
| 11 | "Stop Relay in the middle of reading. Then make it carry on." | stop + continue worked |
| 12 | "Close Relay." | quit by voice |

## Measure, per task
- **Completed** (yes / with help / no) and **time** to complete.
- **Errors**: misheard commands (what they said vs. what RELAY heard — see the log's
  intent line), wrong actions, and any time RELAY acted without being asked (**must be 0**).
- **Awareness**: after each task ask "What's on the screen right now?" — can they answer
  correctly from what RELAY told them? (RELAY's core promise.)
- **Confidence** 1–5: "How sure were you about what Relay was doing?"

## After all tasks
- System Usability Scale (10 questions, read aloud) — target ≥ 70.
- Three open questions: What was hardest? What would you use every day? What did Relay
  say that was confusing, too long or too short?
- With a screen reader user: did RELAY and their screen reader talk over each other?
  Which keys clashed? (RELAY stops repeating focus changes when NVDA/JAWS/Narrator runs.)

## Release bar
- Tasks 1–4, 7, 8, 11, 12 completed unaided by ≥ 80% of participants.
- Zero actions RELAY took without being asked; zero messages sent without "confirm send".
- Median SUS ≥ 70. Every "confusing" phrase fixed or explained in `USER_GUIDE.md`.

## Record keeping
One sheet per participant (no names — P1, P2, …), plus `relay.log` from their
`RELAY_DATA_DIR`. Delete the data folder after copying the log if the participant asks.
