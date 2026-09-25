# RELAY — release acceptance (0.2.0)

Each promise, how it is verified, and its honest status. "Verified" means a check was
actually run on the development laptop (Windows 11, 15.3 GB) and passed; "mocked"
means the logic is tested with a fake of an external service; "not run" means the check
exists or is specified but needs something this machine/session doesn't have.

## Run the checks
```
uv run pytest -m "not integration"            # 194 unit/behaviour tests
uv run python scripts/acceptance.py            # offline acceptance suite (6 checks)
uv run python scripts/e2e_voice.py             # speech in -> action -> speech out
uv run python scripts/live_app_check.py        # the real app: hotkeys, mic, quit
uv run python scripts/live_window_check.py      # desktop control (own test window)
uv run python -m relay --demo-daily            # everyday skills with real system data
uv run python -m relay --sarvam-selftest       # Connected mode (needs a Sarvam key)
```

## Matrix

| # | Requirement | How verified | Status |
|---|---|---|---|
| 1 | Transparent operator: acts only on command, announces before acting, reports changes, idles between tasks | runner/skills tests; live window check (every action announced, result + changes narrated) | **Verified** |
| 2 | Start without looking (Ctrl+Alt+R), spoken greeting, spoken start-up problems, single instance | shortcut + hotkey created and read back; live app check (greeting, second instance refused) | **Verified** (shortcut written to a temp folder, not the user's desktop) |
| 3 | Talk from any app: global talk key with earcon; wake word "Relay" | live app check: real RegisterHotKey x3 + simulated key press -> listening chirp; e2e voice (wake word 5/5) | **Verified** |
| 4 | RELAY never hears itself; ambient speech ignored; wake word only at start | e2e voice (half-duplex + unaddressed speech ignored); unit tests | **Verified** |
| 5 | Speech recognition of the wake word | measured: tiny.en heard "Relay" as "Really" ~1/3 of the time; with the "Hey Relay." prompt 10/10, and the prompt echoes nothing on silence/noise/hum | **Verified** (synthetic voice; real voices/accents still to test) |
| 6 | Stop / cancel / pause / emergency stop are instant, even mid-command; "continue" clears an emergency | dispatcher test (stop jumps the queue); live app check (emergency key, stop key, "continue") | **Verified** |
| 7 | Everyday status: time, date, battery, internet/Wi-Fi, volume | `--demo-daily` read real values from this laptop | **Verified** |
| 8 | Spoken maths incl. Indian number words (lakh/crore, "5 into 3") | 11 calculator tests | **Verified** |
| 9 | Notes and reminders (persist; missed reminders announced; timers) | unit tests + e2e voice ("take a note", "read my notes") + demo | **Verified** |
| 10 | Open any installed app by name (classic or Store) and verify it opened | live: catalogue of 233 Start-menu apps, "open calculator" -> window verified -> "close calculator" | **Verified** |
| 11 | Windows: list, switch, minimize/maximize, close (never force-kill; save prompts read out) | live window check (switch + close by name); unit tests | **Verified** |
| 12 | Read documents and web pages with a cursor (stop / continue / next / previous / repeat) | live window check (UIA document read, 3 parts); reader tests; Chromium TextPattern measured (30k chars in 0.09 s) | **Verified** |
| 13 | Web pages: headings, links (deep inside the page), open link N | native UIA search measured on a live browser (617 links in 0.35 s, invokable); unit tests | **Verified** (listing); **clicking a live web link not run** (avoided touching the user's browser) |
| 14 | Web search / open site / YouTube in the default browser | URL building tested | **Not run live** (would open tabs in the user's browser) — try "search for weather" |
| 15 | Files: open known folders (OneDrive-aware), find files, read PDF/Word/text aloud | unit tests (search, .docx, .txt); known-folder lookup | **Verified** (PDF extraction relies on pypdf; scanned PDFs have no text and RELAY says so) |
| 16 | Typing, dictation with spoken punctuation, keys and shortcuts with honest results (copy verified via clipboard, paste/select-all checked) | session dictation test; runner tests | **Verified** (headless input backend) |
| 17 | High-risk actions need an action-specific phrase: dangerous buttons, sending messages (draft read back), Delete in Explorer; payments/installs keyboard-only | live window check (Delete Everything NOT clicked, phrase required); send/delete guard tests; confirm tests | **Verified** |
| 18 | No fabricated success (verify by re-observation; cancelled actions never "done"; uncertain actions not auto-repeated after crash) | verifier fix test (cancelled stays cancelled); reconcile tests | **Verified** |
| 19 | Five-layer memory persists, refuses secrets, episodic opt-in | acceptance suite + memory tests | **Verified** |
| 20 | Optional panel is locked down (loopback, token, whitelist); panel commands use the same ordered queue | IPC tests | **Verified** |
| 21 | Connected mode (Sarvam): Indian-language speech in/out, translate-and-read, free-form requests | request/response shapes, fallbacks, consent phrase, NLU validation — mocked (18 tests) | **Mocked only — live API not run (no key here).** Run `relay --sarvam-selftest` with a key |
| 22 | Connected-mode privacy: consent phrase; ambient speech stays on device; secrets never sent; offline fallback | privacy-gate test (cloud never called for ambient speech); secret test; fallback test | **Verified** (mocked service) |
| 23 | Memory/CPU fits a 4 GB laptop | measured in 0.1: idle ~35 MB, Essential peak ~330-406 MB, ran under a hard 1 GB cap | **Measured** here; 4 GB hardware latency not certified |
| 24 | Packaged one-folder build runs offline on a clean machine | spec + build script (two launchers, models beside exe) | **Not run** — needs a clean VM |
| 25 | Coexists with NVDA / JAWS | detection code only | **Not run** — no screen reader installed |
| 26 | Usable by blind people in daily life | the checks above are proxies | **Not run** — needs supervised sessions with blind users |
| 27 | Signed installer | — | **Not done** — needs a certificate |

## What "done" honestly means today
Rows 1-20 and 22 were run on this laptop and pass. Row 21 is complete in code and
tested against a fake Sarvam service, but the real API has not been called from here —
the first live call should be `relay --sarvam-selftest` with the team's key. Rows 13-14
avoided opening tabs in the user's own browser. Rows 24-27 need a clean VM, NVDA,
blind testers and a certificate. Nothing in this document claims a result that wasn't
observed.
