# RELAY — user guide

RELAY is a voice assistant for using a Windows computer without looking at the screen.
You talk; RELAY tells you what it is about to do, does it, checks it worked, and tells
you what changed. It only acts when you ask. This guide is written to be read aloud —
copy it into Documents and say "read the file user guide".

## 1. Starting and stopping
- **Start:** press **Control Alt R**. You'll hear "Relay is ready." (The very first time,
  a short introduction.)
- **Close:** press **Control Alt R again**, or say "quit Relay", "close Relay" or
  "goodbye Relay". RELAY says "Closing Relay. Goodbye." The same key turns it on and
  off, like Narrator's Control Windows Enter.
- **Start automatically:** a helper runs `RELAY.cmd --autostart on` once.

## 2. Talking to RELAY
- Press **Control Alt Space** from any program. You hear a rising chirp — speak your
  request. A single soft beep means "got it". A falling chirp means it heard nothing.
- Or say **"Relay"** and your request in one breath: "Relay, what time is it?" You can
  also say just "Relay", wait for the chirp, then speak.
- Pressing the talk key while RELAY is speaking interrupts it and listens.
- Turn the wake word off (talk key only) with "turn off the wake word".
- On the speakers, RELAY ignores the microphone while it is talking, so it never obeys
  its own voice.

### With headphones or earphones
- Plug them in (wired, USB or Bluetooth) at any time: RELAY moves its voice to them by
  itself and says so, for example "boAt Rockerz 450 headphones connected".
- **Interrupt just by talking.** With headphones RELAY can't hear itself, so it keeps
  listening while it talks: say "stop" to silence it, or "Relay" and a new request.
  Other conversation around you is still ignored.
- **Take them off mid-reading and RELAY pauses**, so nothing private is read out loud
  to the room: "Headphones disconnected, so I've paused. Say continue to carry on."
- A Bluetooth headset's own microphone would turn its sound into phone-call quality,
  so RELAY keeps using the laptop's microphone and your headphones stay clear.
- "where is the sound going" — which speaker and microphone RELAY is using.
- "headphone mode on" / "headphone mode off" / "headphone mode automatic" — if your
  earphones are in the laptop's own jack, Windows may report them as speakers; say
  "I'm using headphones" to turn voice-interrupt on.

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

## 13. Privacy and working offline
Everything RELAY does happens on this computer: no account, no API key, no cloud
service. Speech recognition and the voice run locally, nothing you say is recorded or
sent anywhere, and passwords or codes are never read aloud, stored or written to the log.
RELAY only uses the internet when *you* ask for something on the web — and then it is
your own browser that goes online. It speaks English for now; if you ask it to speak
another language it tells you so plainly.

If whoever set up RELAY turned on the online extras (section 13a), the only things that
leave the computer are: questions RELAY's own commands can't answer, the page text when
you say "summarise this page", and — with Sarvam recognition on — what you say right
after "Relay" or the talk key. Never passwords or codes, never room conversation.

## 13a. Asking anything (if the AI assistant is set up)
Ask RELAY anything its built-in commands don't cover, the way you'd ask a person:
"what's a good name for a cat" · "explain what an index fund is" · "how do I make
lemon rice" · "ask why is the sky blue". The answer usually starts within a second or
two and is spoken sentence by sentence; "stop" cuts it off, "repeat" says it again.
Follow-up questions work ("and in winter?").
- "summarise this page" / "what is this email about" — a short spoken summary of what's
  on screen.
- If you ask it to *do* something ("could you check the clock for me"), RELAY says
  "I understood that as: what time is it" and does it the normal, safe way.
- If the internet is down, RELAY says so and all its own commands keep working.

## 14. Getting help
"help" · "help with reading" · "help with the web" · "help with typing" · "help with
apps" · "help with files" · "help with system" · "help with notes" · "what apps do
you support".

## 15. If something goes wrong (for a helper)
- **First, run `RELAY.cmd --check`.** It tests the models, voice, speech recognition,
  microphone, speakers, the three global keys, screen reading, the app list, volume and
  the database, confirms nothing used the network, and says the result aloud.
- **Silence at start:** RELAY speaks start-up problems (for example, no microphone, or
  another program using Control Alt Space). The log is `%LOCALAPPDATA%\RELAY\relay.log`.
- **Talk key taken:** change `push_to_talk_hotkey` in `%LOCALAPPDATA%\RELAY\config.toml`.
- **Mis-hearing:** speak after the chirp; say "Relay" clearly; a headset microphone helps.
- **An app isn't readable:** RELAY says so plainly; try "read with OCR".
- Screen reader users: RELAY is designed to run alongside NVDA, JAWS or Narrator, but
  this has **not yet been tested with a screen reader running** (see ACCEPTANCE.md).
