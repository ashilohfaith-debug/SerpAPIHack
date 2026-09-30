# RELAY — release acceptance (0.2.1)

Each promise, how it is verified, and its honest status. **Verified** means the check
was actually run on the development laptop (Windows 11) and passed; **not run** means
it needs something this machine doesn't have (a clean VM, a screen reader, people, a
certificate). Nothing here claims a result that wasn't observed.

## Run the checks
```
uv run python -m relay --check                 # this computer, spoken result
uv run pytest -m "not integration"            # 389 unit/behaviour tests (+2 need an unlocked, interactive desktop)
uv run python scripts/acceptance.py            # offline acceptance suite (8 checks)
uv run python scripts/e2e_voice.py             # speech in -> action -> speech out
uv run python scripts/live_app_check.py        # the real app: hotkeys, mic, quit
uv run python scripts/live_window_check.py     # desktop control (own test window)
uv run python scripts/bench_basic_laptop.py    # emulated low-end laptops
uv run python scripts/clean_machine_check.py   # packaged app on a clean profile
uv run python scripts/sbom.py                  # licences + pinned versions
```

## The six release gates

| Gate | What was done | Status |
|---|---|---|
| **1. Packaged app on a clean offline machine** | PyInstaller build (597 MB with models) passes `clean_machine_check.py`: no Python on PATH, fresh data folder, dead proxies; 129 imported DLLs all bundled or part of Windows (incl. VC++ runtime); `--check` passes; windowless `relay.exe` starts, stays up, logs no errors, opens no internet connections | **Verified on a clean profile** here. A real clean VM (other Windows builds, no prior setup) **not run** — Windows 11 Home has no Sandbox/Hyper-V |
| **2. NVDA coexistence** | RELAY detects NVDA/JAWS/Narrator (cached) and stops repeating focus changes they announce; talk/stop/emergency keys don't overlap NVDA's default keys | Behaviour **tested in code**; **not run** with a real screen reader (NVDA not installed; see below) |
| **3. 4 GB / basic-laptop performance** | Job Object emulation, limits verified enforced: budget dual-core **2.4 s** wait, Celeron-class **3.3 s**; voice 4x faster than playback; ~2% idle CPU; **402 MB peak under a 1 GB cap** | **Verified by emulation**; a real low-end laptop **not run** |
| **4. Code signing** | `packaging/sign.ps1` (signtool, SHA-256, timestamped, verify) | **Not done** — needs a code-signing certificate |
| **5. Blind-user testing** | `docs/USER_TESTING.md`: 12 tasks, success measures, release bar | **Not run** — needs participants |
| **6. Voice licence + SBOM** | SBOM of 45 runtime packages from their own metadata; voice licences checked at the source | **Done** — findings: release voice must be `en_US-ljspeech-medium` (public domain); **piper-tts is GPL-3.0** (distribution decision pending) |

## Everything else

| # | Requirement | How verified | Status |
|---|---|---|---|
| 1 | Transparent operator: acts only on command, announces before acting, reports changes | runner/skills tests; live window check | **Verified** |
| 2 | Start without looking (Ctrl+Alt+R), instant "Starting Relay", spoken problems, single instance | live app check; clean-profile start | **Verified** |
| 3 | Talk from any app (talk key + earcons), wake word | live app check (real hotkeys + simulated presses); e2e voice | **Verified** |
| 4 | Never hears itself; ignores room noise and unaddressed speech | e2e voice (half-duplex, unaddressed ignored); noise-gate test; idle CPU measured | **Verified** |
| 5 | Stop / cancel / pause / emergency instant; "continue" clears emergency | dispatcher test; live app check | **Verified** |
| 6 | Everyday status, maths, notes, reminders | `--demo-daily` with real system values; unit tests; works with networking blocked | **Verified** |
| 7 | Open any installed app; windows list/switch/min/max/close (never kill) | live Calculator open/close; live window check | **Verified** |
| 8 | Read documents/pages with a cursor; links and headings deep in pages | live window check; native UIA search on a live browser | **Verified** (clicking a live web link not run) |
| 9 | Web search / sites / YouTube in the default browser | URL building tested | **Not run live** (would open tabs in your browser) |
| 10 | Files: known folders, search, read PDF/Word/text | unit tests | **Verified** |
| 11 | Typing, dictation, keys, shortcuts with honest results | session tests; real SendInput reaches Windows | **Verified** |
| 12 | Risky actions need a phrase: dangerous buttons, send (draft read back), Explorer delete | live window check; guard tests | **Verified** |
| 13 | No fabricated success; no auto-repeat of uncertain actions after a crash | verifier + reconcile tests | **Verified** |
| 14 | No keys, no accounts, no cloud; no network at start | `--check` network spy; blocked-network test; clean-profile connection check | **Verified** |
| 15 | Memory persists, refuses secrets | acceptance suite + memory tests | **Verified** |
| 16 | Optional panel locked down (loopback, token, whitelist) | IPC tests | **Verified** |

## Screen-reader test when possible
With NVDA installed (or Narrator on: Ctrl+Win+Enter), run RELAY and check: both voices
don't clash on focus moves; Ctrl+Alt+Space/Period/Backspace still reach RELAY; RELAY's
reading and NVDA's reading can be interrupted independently. Record results here.
