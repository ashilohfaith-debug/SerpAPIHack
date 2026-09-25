# RELAY — user guide

RELAY is a voice assistant for using a Windows computer without looking at the screen.
You talk; RELAY tells you what it is about to do, does it, checks it worked, and tells
you what changed. It only acts when you ask. This guide is written to be read aloud —
copy it into Documents and say "read the file user guide".

## 1. Starting and stopping
- **Start:** press **Control Alt R**. You'll hear "Relay is ready." (The very first time,
  a short introduction.) If RELAY is already running, it tells you so.
- **Start automatically:** a helper runs `RELAY.cmd --autostart on` once.
- **Quit:** say "quit Relay", or "goodbye Relay".

## 2. Talking to RELAY
- Press **Control Alt Space** from any program. You hear a rising chirp — speak your
  request. A single soft beep means "got it". A falling chirp means it heard nothing.
- Or say **"Relay"** and your request in one breath: "Relay, what time is it?" You can
  also say just "Relay", wait for the chirp, then speak.
- Pressing the talk key while RELAY is speaking interrupts it and listens.
- Turn the wake word off (talk key only) with "turn off the wake word".
- RELAY ignores the microphone while it is talking, so it never obeys its own voice.

## 3. Stopping, cancelling, and safety
| Say or press | What happens |
|---|---|
| "stop" · **Control Alt Period** | stop talking; pauses reading |
| "pause" | pause the task or the reading |
| "continue" | resume reading, or clear an emergency stop |
| "cancel" · "never mind" | stop the current task and forget any question |
| "emergency stop" · **Control Alt Backspace** | halt everything at once; nothing runs until you say "continue" |
| "repeat" | say the last thing again |

**Risky actions need a spoken phrase**, never just "yes":
- clicking Delete / Send / Buy / Submit and similar → "confirm delete", "confirm send"…
- pressing Enter in WhatsApp, Teams, Telegram, Outlook and other chat apps sends a
  message, so RELAY first **reads your message back** and waits for "confirm send";
- pressing Delete in File Explorer → "confirm delete";
- payments, installs and security settings are never done by voice — RELAY asks you to
  confirm with the keyboard or Windows sign-in.

RELAY never force-closes a program: "close Notepad" works like the window's X button,
so unsaved work gets the program's own "save changes?" question, which RELAY reads out.

## 4. Everyday questions
"what time is it" · "what's the date" · "how much battery do I have" · "am I connected to
the internet" · "status" (time, battery and internet together) · "what's the volume".

Sums: "what is 25 times 4" · "what's 15 percent of 2 lakh" · "1200 divided by 12" ·
"square root of 144" · "5 into 3" (times).

## 5. Apps and windows
- "open WhatsApp", "open Word", "open Calculator" — any app on your Start menu. If it's
  already open, RELAY switches to it.
- "what windows are open" — RELAY numbers them; then "switch to 2", or "switch to Chrome".
- "minimize", "maximize", "close this window", "close Notepad", "show desktop".
- "open Notepad", then "type …", "save", or "save as project report".

## 6. The web
- "search for today's weather in Hyderabad" · "google cricket score"
- "open YouTube" · "open Gmail" · "open flipkart dot com"
- "play Arijit Singh songs on YouTube"
- On a page: "read the page", "list the headings", "list the links", then "open the
  third link" or "open the second one". "go back", "reload", "new tab", "close tab".

## 7. Reading
- "read the page" / "read the document" — reads from the top, part by part.
  "stop" pauses; "continue" picks up where you stopped; "next paragraph" / "previous
  paragraph" move; "repeat" reads the part again.
- "read this" — the selection or the focused item. "spell that" — letter by letter.
- "read the title", "read the clipboard", "what's on my screen", "where am I",
  "what changed", "what are my options", "next" / "previous" (move through controls).
- Text inside a picture or an inaccessible app: "read with OCR" (slower, may mis-read).

## 8. Files
- "open my downloads", "open documents", "open desktop".
- "find my resume" — RELAY lists matches; "open the first one" or "read the first one".
- "read the PDF electricity bill", "open the file budget" — PDFs, Word (.docx) and text
  files are read aloud. A scanned PDF has no text; RELAY offers to open it instead.

## 9. Writing and dictation
- "type Hello, how are you?" types at the cursor.
- "start dictation" — everything you say is typed. Say "comma", "full stop", "question
  mark", "new line", "new paragraph" for punctuation. RELAY reads back what it typed.
  "delete the last word", "undo", "select all", "copy", "paste" still work.
  "stop dictation" to finish.
- Keys: "press enter", "press control s", "press alt f4", "press down arrow 3 times".

## 10. Notes and reminders
- "take a note buy milk" · "note that the meeting is at 5" · "read my notes" ·
  "delete my notes" (asks for "confirm delete").
- "remind me in 10 minutes to call mom" · "remind me at 6 pm to take my medicine" ·
  "remind me tomorrow at 9 am to submit the form" · "set a timer for 5 minutes" ·
  "what are my reminders" · "cancel my reminders".
  Reminders survive restarts; one that came due while RELAY was closed is announced
  when it starts.

## 11. Music and sound
"volume up" / "volume down" (10 percent steps, and RELAY tells you the new level) ·
"set volume to 40 percent" · "mute" / "unmute" · "play music" / "pause music" ·
"next track" / "previous track".

## 12. RELAY's voice
"speak faster" · "speak slower" · "normal speed" (remembered) ·
"quiet mode" / "quick mode" / "detailed mode" / "guided mode" (how much RELAY says).

## 13. Indian languages (Connected mode)
Connected mode uses Sarvam AI's servers in India so you can speak and listen in Hindi,
Telugu, Tamil, Kannada, Malayalam, Marathi, Gujarati, Bengali, Punjabi or Odia.
- A helper saves the Sarvam API key once in `%LOCALAPPDATA%\RELAY\sarvam_key.txt`.
- Say "turn on connected mode". RELAY explains what is sent, then waits for
  **"confirm connect"**.
- Speak in your language — RELAY answers in the language you speak, or choose: "speak in
  Hindi", "speak in English", "reply in the language I speak".
- "read this page in Telugu" reads an English page aloud in Telugu.
- In dictation, your words are typed in your own script.
- Requests RELAY's offline commands don't cover are understood with Sarvam's model;
  RELAY says "I understood that as: …" before doing anything, and safety rules still apply.
- Passwords and anything that looks like a code are never sent. If the internet drops,
  RELAY says so and continues in offline English.
- "turn off connected mode" keeps everything on the computer again.

## 14. Getting help
"help" · "help with reading" · "help with the web" · "help with typing" · "help with
apps" · "help with files" · "help with system" · "help with notes" · "help with
languages" · "what apps do you support".

## 15. If something goes wrong (for a helper)
- **Silence at start:** RELAY speaks start-up problems (for example, no microphone, or
  another program using Control Alt Space). The log is `%LOCALAPPDATA%\RELAY\relay.log`.
- **Talk key taken:** change `push_to_talk_hotkey` in `%LOCALAPPDATA%\RELAY\config.toml`.
- **Mis-hearing:** speak after the chirp; say "Relay" clearly; a headset microphone helps.
- **An app isn't readable:** RELAY says so plainly; try "read with OCR".
- Screen reader users: RELAY is designed to run alongside NVDA, JAWS or Narrator, but
  this has **not yet been tested with a screen reader running** (see ACCEPTANCE.md).
