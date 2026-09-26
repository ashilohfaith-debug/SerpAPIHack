# AI answers and the Sarvam voice (optional online extras)

RELAY works fully offline with no keys. Two optional extras need the internet, and
both are switched on by **one file the developer fills in once** — end users never
need a key or an account:

| Extra | What the user gets | Service |
|---|---|---|
| **AI answers** | Anything RELAY's built-in commands don't cover — "what's a good name for a cat", "explain what an index fund is", "summarise this page" — is answered in a natural spoken reply, streamed sentence by sentence | [FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi) (or any OpenAI-compatible `/v1` router) |
| **Sarvam voice** | Everything RELAY says, in Sarvam's natural Indian voice (Bulbul) | Sarvam AI text-to-speech |
| **Sarvam recognition** (off by default) | Better understanding of Indian accents; Hindi, Tamil and other Indian languages are translated into English commands | Sarvam AI speech-to-text (Saaras) |

If a service is down, slow, out of quota or the laptop is offline, RELAY carries on with
its offline voice, recogniser and commands, and says once, plainly, what happened.

## Set up (one copy-paste)

1. In the RELAY folder (next to `RELAY.cmd`, or next to `relay.exe` in a packaged
   build) copy `.env.example` to `.env`.
2. Paste the keys and save:
   ```ini
   SARVAM_API_KEY=sk_...                    # dashboard.sarvam.ai -> API keys
   RELAY_LLM_URL=http://localhost:3001/v1   # FreeLLMAPI on this PC
   RELAY_LLM_KEY=freellmapi-...             # the unified key from FreeLLMAPI's dashboard
   ```
   Optional: `SARVAM_SPEAKER=` (a Bulbul voice name), `SARVAM_STT=on`.
3. Start FreeLLMAPI on the same PC — on Windows the simplest is its desktop app (`.exe`
   on the project's Releases page); from source it is `npm install && npm run dev`
   (API on port 3001). In its dashboard add the free provider keys you want, then copy
   the unified `freellmapi-…` key from the Keys page into `RELAY_LLM_KEY`.
4. Check:
   ```bash
   RELAY.cmd --check        # adds "Sarvam voice", "Sarvam speech recognition", "AI assistant router"
   RELAY.cmd --llm-check    # time to first token, first sentence and first AUDIO, per question
   ```

`.env` is git-ignored. A value set in the real environment wins over the file, and
`RELAY_OFFLINE=1` ignores every key (nothing leaves the PC).

## How the replies are made fast

A blind user hears silence while waiting, so the whole path is built around the time
to the **first spoken word**:

- **Streaming.** The answer is read from the router token by token (Server-Sent Events).
- **Sentence-level speech.** Each sentence is handed to the voice the moment it ends,
  while the model is still writing the next one. A sentence counts as finished only when
  the next character is a space, so "3.5 lakh" is never split at the decimal point.
- **Synthesis overlaps playback.** The speech queue synthesises sentence 2 while
  sentence 1 plays (`relay/audio/speech.py`), so there are no gaps between sentences.
- **Persistent connections.** Router and Sarvam connections stay open (no TCP/TLS
  handshake per request) and are opened at start-up (`warm()`).
- **Hedged routing.** Two routes are raced — FreeLLMAPI's `auto:fast` and `auto` by
  default (`llm_models` in `config.toml`). If the faster route has no first token
  within about 1.5× its usual time (at least 0.5 s), the next route starts too; the first
  to speak wins and the other is cancelled. Errors fail over at once; a rate-limited
  (429) route rests for its Retry-After (at least 20 s). If nothing answers within 6 s
  RELAY says so and keeps working offline — it never hangs.
- **A thinking tick.** If the first word takes longer than 1.2 s, a soft earcon plays
  so the user knows RELAY is on it.
- **Stop works instantly.** "stop" or Ctrl+Alt+Period cancels the stream and closes its
  socket; an online-voice request still in flight never keeps the microphone deaf.

Measured on this development laptop with a **simulated** router whose first token takes
0.35 s (then ~65 tokens/s) — this isolates RELAY's own overhead, it is not a real
provider:

| Voice | First token | First sentence complete | **First audio ready** |
|---|---|---|---|
| Piper (offline voice) | 0.34–0.36 s | 0.46–0.53 s | **0.65–0.73 s** |
| Sarvam (simulated 0.25 s round trip) | 0.34–0.36 s | 0.46–0.53 s | **0.72–0.78 s** |

So RELAY adds roughly 0.3–0.4 s to whatever the router's first token takes. Real free
providers vary from about 0.2 s to several seconds; hedging cuts the slow tail. Run
`RELAY.cmd --llm-check` for real numbers with your keys.

## What is sent, and when (privacy)

- **Built-in commands never touch the network.** Only a request the offline grammar
  can't handle goes to the router — the words the user said, the name of the app in
  front, and the last few turns of the conversation.
- **Screen text only when asked.** "summarise this page" sends the page text (up to
  6,000 characters) with lines that look like passwords or codes removed.
- **Secrets are never sent.** A request or sentence that looks like a password, OTP or
  code is refused (assistant) or spoken by the offline voice (Sarvam voice).
- **Room conversation is never uploaded.** With Sarvam recognition on, the wake word is
  checked on the laptop by the offline recogniser first; only speech addressed to RELAY
  (or spoken after the talk key) is sent. A near-miss like "Really, …" counts only when
  the rest is a real command, so everyday talk that starts with "really" stays local.
- **An AI-suggested action is treated as untrusted.** The assistant can only suggest one
  command from RELAY's own list (`DO: open notepad`); it must parse with the offline
  grammar, can never be a confirmation, emergency, quit or delete phrase, is announced
  ("I understood that as: …") and then goes through the normal permission gate.
- Each install sends an anonymous random id (`X-Relay-Device`) so a gateway can rate-limit
  per device. It contains nothing about the user.
- Logs record the command type only, never what was said or answered.

## One key for every user — read before shipping

Using one developer key for all users (instead of each user bringing their own) works
technically, but:

1. **`localhost` only reaches the same PC.** For other people's laptops, FreeLLMAPI (or
   your own gateway) must run on a server they can reach, and `RELAY_LLM_URL` must point
   there (https).
2. **FreeLLMAPI describes itself as local-first, single-user, for personal
   experimentation.** Serving many users from it may break the free-tier terms of the
   providers behind it. Check each provider's terms, or use a paid plan for a public
   release.
3. **A key inside a distributed app can be extracted** by anyone who has the app.
   `packaging/build.ps1` warns when it bundles `.env`. For a public release keep real
   keys on a server: point `RELAY_LLM_URL` at your gateway and set
   `SARVAM_BASE_URL=https://your-gateway/sarvam` — the gateway adds the real Sarvam key,
   rate-limits by `X-Relay-Device`, and `.env` only carries a revocable app token.

For the demo laptop, keys in `.env` on that machine are fine.

## Files

| File | Role |
|---|---|
| `.env.example` → `.env` | the one file the developer fills in |
| `relay/envfile.py` | loads `.env` (app folder, then the user data folder) |
| `relay/llm/client.py` | OpenAI-compatible SSE streaming, persistent connections, abort |
| `relay/llm/router.py` | latency-first hedged routing, failover, cool-down |
| `relay/llm/assistant.py` | spoken, sentence-streamed answers; safe `DO:` commands |
| `relay/sarvam/client.py` | Sarvam text-to-speech / speech-to-text (stdlib only) |
| `relay/sarvam/voice.py` | Sarvam voice and recogniser with offline fallback |
| `tests/test_llm.py`, `tests/test_sarvam.py`, `tests/test_envfile.py` | real wire format against local mock servers |
