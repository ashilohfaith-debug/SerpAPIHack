# Relay: The Voice Interface to the Live World

Relay is a Windows voice assistant for blind and low-vision users. The live-world
extension separates speech, retrieval, evidence-based decisions, and desktop actions.
Removing SerpApi removes current-world retrieval; local commands continue working.

## Architecture

```text
Microphone -> local wake gate -> Whisper or Saaras -> Session
  Local command -> existing safety gate -> UIA executor -> re-observe -> delta narration
  Live command  -> LiveWorldBroker -> router -> bounded search plan
    -> SerpApi engines in parallel -> normalized evidence -> constraint filtering
    -> cited decision -> spoken answer / companion panel -> verified result handoff
```

The engines are Google Search, Shopping, Maps, Flights, Hotels, and News. Keys stay
in the Python process. The browser receives decisions over a loopback, token-authenticated
SSE connection. HTML, CSS, JavaScript, and command requests all require that token.

Search plans contain at most six searches. Identical engine/parameter combinations
use a five-minute in-memory cache. Results are ranked deterministically against
supported explicit constraints. General research currently presents retrieved
source snippets; it does not implement a comprehensive LLM comparison of every source.

## Setup

Follow the source setup in README.md. Configure `SERPAPI_API_KEY` in the ignored
`.env` file. `SARVAM_API_KEY` optionally enables Saaras v4 recognition and Bulbul
v4 Flash speech with the `aparna_en_companion` persona. Without it, recognition
uses local `base.en` INT8 and speech uses Piper with a Windows SAPI fallback.
Existing legacy voices such as `kavya` automatically use Bulbul v3 unless a model
is explicitly configured. Existing `.env` settings are not overwritten.

Start `uv run python -m relay --start --with-panel`. Use the URL printed by Relay;
its token is required. Never put real keys into browser code, recordings, or screenshots.

## Three-Minute Demo

1. Speak: "Relay, find the cheapest nonstop flight from Chennai to Bangalore tomorrow
   after 5 PM, and a hotel under 4000 near Indiranagar. Keep everything under 10000."
2. Inspect the retrieved flights/hotels, prices, constraints, and cited evidence.
   If no combination qualifies, Relay reports that instead of inventing a plan.
3. Ask "find another cheaper option" to exercise retained context and stable exclusions.
4. Ask "open the hotel", then "open the flight". Each action uses that component's
   cited link, rather than whichever link was last selected.
5. Ask "book the flight". Relay resolves the returned flight booking token into
   provider options and opens the selected handoff. Passenger details and payment
   remain at the provider. An opened handoff is not a completed booking.
6. Disconnect Live World in the panel. Repeat the search and observe the refusal.
   A supported local command such as "what time is it" continues working.

The original Bangalore prompt omits the departure city. Relay asks for it; a short
reply such as "Chennai" completes the pending request. Unsupported city names
require an airport code before a Flights request is issued.

## Honest Limits

- No real SerpApi credential was configured during the audit. Search and booking
  provider tests use fixtures and mock HTTP responses. A live SerpApi demo still
  requires valid credentials; fixture success is not live-provider verification.
- The configured Sarvam credential was tested against the live service. Bulbul v3
  with the saved `kavya` voice and Saaras v4 recognition both passed the machine
  health check. The new v4 Flash persona has fixture coverage, not a live listening test.
- Search results are not a guarantee of ticket inventory or completed payment.
- A restaurant's "open now" observation cannot prove future opening hours. Relay
  rejects a claimed tonight/arrival-time match when its schedule is not verified.
- The speculative manager supports debounce, cancellation, cache reuse, and exact
  parameter matching. The current offline voice loop supplies finalized utterances;
  actual incremental microphone transcription is not connected to that manager.
- In-flight standard-library HTTP requests cannot be forcibly aborted. Cancellation
  discards obsolete results and prevents subsequent requests; timeouts bound the call.
- Naturalness, accents, noise, barge-in, and screen-reader ergonomics require tests
  with the intended users on their actual microphones and Windows applications.
- Extended testing encountered intermittent desktop COM timeouts and SSE network
  suspension. UIA replacement workers are now bounded and the panel announces
  reconnection. The final 538-test suite passed, but soak testing remains necessary.

## Provider References

- [Google Flights parameters](https://serpapi.com/google-flights-api)
- [Flight booking-token options](https://serpapi.com/google-flights-booking-options)
- [Sarvam Bulbul models](https://docs.sarvam.ai/api/getting-started/models/bulbul)
- [Bulbul v4 Flash guide](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/best-practice-guide-for-bulbul-v-4-flash)
