# Research: Local Speech Pipeline Architecture

## 1. Overview
The local speech pipeline handles continuous microphone ingestion, audio feature extraction, wake-word activation, voice activity detection (VAD), speech recognition (STT), and text-to-speech (TTS). For an assistive tool running on budget laptops, the speech pipeline must consume under ~5% CPU at idle, start speaking within ~2.5s of an utterance, and run 100% offline.

## 2. Ingestion & Preprocessing Pipeline
```
[Microphone: 16 kHz Mono PCM, 16-bit]
       ↓
[Circular Ring Buffer (Rolling 3–5 seconds)]
       ↓
[Energy Gate / Noise Gate] (Rejects room background noise)
       ↓
[Voice Activity Detection (Silero VAD / WebRTC VAD)]
       ↓
[Wake Word Detection ("Relay") OR Push-to-Talk Hotkey]
       ↓
[Speech Buffer Accumulation (Speech Start -> Silence Hangover ~600ms)]
       ↓
[STT Engine (faster-whisper INT8 / whisper.cpp)]
```

## 3. Wake Word vs. Push-to-Talk (PTT)
- **Wake Word ("Relay")**:
  - Hands-free operation essential for motor-impaired or multi-tasking blind users.
  - Must use lightweight acoustic spotting to avoid spinning up heavy STT constantly.
- **Push-to-Talk (`Ctrl+Alt+Space`)**:
  - Deterministic and instant.
  - Zero chance of false-positive triggers from background television or conversation.
  - Immediately interrupts RELAY's active narration (barge-in).

## 4. Latency Budget Analysis
Budget allocation for a 2.4s end-to-end response on a dual-core laptop:
1. **Silence Hangover Detection**: ~500–600 ms (waiting for speaker to finish sentence).
2. **Audio Chunk Transfer & Mel Spectrogram**: ~20 ms.
3. **STT Transcription (faster-whisper tiny.en INT8)**: ~180–300 ms.
4. **Grammar & Intent Parsing (Deterministic)**: < 1 ms.
5. **UI Automation Action & Verification**: ~150–400 ms.
6. **TTS First-Audio-Packet (Piper)**: ~100–250 ms.
7. **Audio Output Buffer Latency**: ~30 ms.
- **Total Measured Latency**: ~1.0s to 1.8s (well within the 2.5s budget).

## 5. Streaming vs. Chunked Synthesis
- For short commands (*"Notepad opened"*, *"battery 85%"*), full-sentence synthesis is fast enough (<150 ms) and provides better sentence prosody.
- For long document reading or AI Q&A answers, sentence-by-sentence streaming playback is mandatory so the user begins hearing speech within 200 ms while later sentences synthesize in the background.

## 6. References
- OpenAI Whisper Paper: https://arxiv.org/abs/2212.04356
- Silero VAD: https://github.com/snakers4/silero-vad
- Piper Neural TTS: https://github.com/rhasspy/piper
