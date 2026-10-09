# Relay Master Audit

Audit date: 2026-10-09. Workspace: `D:\SERP API HACKTHON`.

## Verdict

The source implementation passes its automated suite and machine health checks.
It is not certified to perform every desktop task or complete ticket purchases.
Real SerpApi searches remain unverified because no SerpApi key was configured.
The existing Windows release binaries were not rebuilt in this audit.

## Verified Results

| Check | Result | Scope |
| --- | --- | --- |
| Full pytest suite | 538 passed in 128.99 seconds | Voice, routing, safety, provider fixtures, delta, desktop contracts, real UIA integration |
| Ruff | Passed | Repository lint |
| JavaScript syntax | Passed | Companion panel script |
| Core selftest | Passed | Event bus, permissions, journal, emergency wiring |
| Offline voice selftest | Passed | Real Piper audio -> local base.en recognition -> wake/command extraction |
| Machine health check | All passed | Microphone capture, speakers, keys, real UIA, models, database, online providers |
| Live Sarvam synthesis | Passed | Saved kavya voice on Bulbul v3; 0.68 seconds in this run |
| Live Sarvam recognition | Passed | Synthesized English sentence recognized by Saaras v4; 0.29 seconds |
| Configured AI router | Passed | First token 0.17 seconds in this run |
| Desktop panel | Passed | 1440x900, actual Session -> loopback IPC -> SSE -> DOM |
| Mobile panel | Passed | 320x844, no horizontal overflow, including 200% text size |
| Result transitions | Passed | Travel -> shopping -> offline refusal; stale rows/actions cleared |
| Evidence drawer | Passed | Focus entry/trap, Escape, focus restoration, inert background, descriptive links |
| Panel controls | Passed | Authenticated request form, command categories, theme, audio setting, text-size increase |
| 200% zoom | Passed | 1440x900 viewport, no horizontal overflow |
| Browser console | Qualified | Initial flows had no errors; extended run logged three SSE network-suspension/change errors |

Timings are observations from one run, not performance guarantees. Browser searches
used fixture providers; online Sarvam and AI health checks used configured services.
Screenshots are in the ignored `output/playwright` directory.

## Defects Repaired

- Voice compatibility: a saved v3 voice previously received a v4 Flash request and
  failed with HTTP 400. Model inference now preserves legacy voices; new settings
  default to the v4 companion persona. Explicit model choices remain unchanged.
- Recognition: local base.en INT8, beam search and command hints replace the less
  accurate tiny-model default. Wake gating still protects ambient conversation.
- Emergency controls: emergency stop preempts captured replies and confirmations;
  new searches and link-opening requests are blocked until continue clears it.
  Stop/cancel also preempt captured replies, and a stopped booking lookup cannot
  open its returned provider handoff.
- Travel clarification: short city, airport-code and date replies update structured
  pending intent rather than reparsing a contradictory concatenated request.
- Routing: shorthand routes request flights; fresh explicit routes cannot be
  replaced by old follow-up context. News and current research remain live queries.
- Provider contracts: one-way flight parameters, date handling, ISO departure times,
  numeric validation and HTTP(S)-only evidence links are covered by regressions.
- Constraint integrity: unsupported opening hours are not inferred from open-now
  status. Hotel area, rating, flight time, exclusions and available budget components
  are enforced. Partial engine failure does not invent a complete trip total.
- Action grounding: only stored, cited evidence supplies actions. Opening the hotel
  selects the hotel, not an old flight. Browser failures are not reported as success.
  A new booking route cannot accidentally open the previously selected flight.
- Booking: flight booking tokens resolve provider options; verified URLs or form
  handoffs can be opened. Passenger data and payment are not automatically submitted.
- Speculation: debounced requests, obsolete-result cancellation, exact parameter
  matching and single-use consumption prevent stale route reuse.
- Delta narration: stable identity, background updates, removals and control-state
  changes are reported with bounded verbosity. Protected values stay private.
  Dialog suggestions do not automatically choose the first potentially risky button.
- Panel: authenticated assets and SSE, source evidence, generic result text, stale
  state clearing, narrow-screen layout and keyboard-accessible modal interaction.
  Missing companion CSS classes are restored, screen-reader-only content is hidden
  visually, and formerly unwired request/accessibility controls are connected.
- UIA resilience: serial observations and a bound on abandoned COM workers prevent
  unlimited replacement-thread growth when a desktop provider repeatedly hangs.
  WinEvent filtering no longer schedules observations for every event in a broad range.

The extended audit encountered an intermittent real-desktop UIA timeout and Windows
COM disconnection diagnostics, as well as browser SSE network-suspension errors.
These are not hidden by the earlier passing health check. Worker growth is now
bounded and the panel announces reconnection; long-duration desktop stability still
needs testing on the user's active applications. A subsequent full run before the
final worker changes exposed an outdated key-template assertion; that assertion
now matches the requested blank template. The final post-fix full run passed all
538 tests, including the real UIA integration check.

## Remaining Acceptance Work

1. Configure `SERPAPI_API_KEY` in the existing ignored `.env`. Run live search,
   constraint, exclusion and booking-token flows with actual provider responses.
2. Incremental microphone transcripts are not connected to speculative retrieval.
   Current offline recognition delivers final utterances. Do not claim streaming
   partial-transcript search in the demo.
3. Evaluate naturalness and recognition with blind users, multiple accents,
   real microphone speech, noise, interruptions, NVDA and JAWS. Synthetic speech
   round trips do not establish human usability or recognition accuracy.
4. Verify specific airline/provider checkout forms and their current inventories.
   Search evidence and opening a page are not purchase or reservation confirmation.
5. Expand unsupported tasks deliberately. Research currently exposes source
   snippets; it is not comprehensive cross-source reasoning or arbitrary automation.
6. Package and retest a Windows installer before distributing these source changes.

## Reproduction

```powershell
uv run --extra voice --extra daily --extra percept --extra dev pytest -q
uv run --extra voice --extra daily --extra percept --extra dev ruff check .
node --check frontend/app.js
uv run python -m relay --selftest
uv run --extra voice --extra daily --extra percept python -m relay --voice-selftest
uv run --extra voice --extra daily --extra percept python -m relay --check --quiet
```

Start the actual assistant using the installed dependencies:

```powershell
uv run python -m relay --start --with-panel
```

## GSD Use

The requested GSD repository was installed, and its review/verification guidance
was used with focused regression tests and recorded evidence. An attempted
independent final reviewer could not complete because of the account usage limit;
the final verification above was performed locally. This is not a claim that a
separate reviewer approved the project. GSD's installer also reported unreplaced
Claude-path references in its own agent templates; Relay runtime is independent
of those templates.
