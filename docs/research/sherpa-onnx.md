# Research: sherpa-onnx Architecture & Techniques

## 1. What the Project Does
`sherpa-onnx` is a multi-platform, offline speech toolkit developed by the Next-Gen Kaldi team (`k2-fsa`). It provides streaming and non-streaming speech-to-text (ASR), voice activity detection (VAD), keyword spotting (wake words), and text-to-speech (TTS), all powered by the ONNX Runtime engine.

## 2. Core Architecture
- **Unified Engine**: Uses Microsoft ONNX Runtime as the single computational backend for C++, Python, Go, and C# wrappers.
- **True Streaming ASR**: Unlike Whisper (an encoder-decoder model requiring audio chunks of at least 1–3 seconds), sherpa-onnx supports **Zipformer** and **Conformer transducers**, which process audio incrementally frame-by-frame (e.g. 100 ms chunks) and emit partial tokens in real time.
- **Dedicated Keyword Spotter (KWS)**: Contains acoustic models specifically trained to spot single wake words (e.g., *"Relay"* or *"Hey Computer"*) with tiny model footprints (~5 MB to 15 MB) and less than 1% CPU utilization at idle.
- **Multi-Model TTS**: Supports VITS, Piper, and Kokoro models directly inside ONNX Runtime.

## 3. Comparative Analysis: whisper.cpp vs. sherpa-onnx

| Dimension | whisper.cpp | sherpa-onnx |
|---|---|---|
| **Primary Architecture** | Transformer Encoder-Decoder | Transducer / CTC / Transformer |
| **Streaming Mechanism** | Simulated (sliding window chunks) | Native (frame-by-frame streaming) |
| **Idle Wake-Word Spotting** | Heavy (runs Whisper passes) | Ultra-lightweight (dedicated KWS model) |
| **Vocabulary Flexibility** | Open-vocabulary English | Pre-defined lexicon or BPE tokens |
| **Model Size** | 42 MB – 140 MB | 5 MB (KWS) – 80 MB (Zipformer) |
| **Ecosystem & Runtime** | GGML (pure C/C++) | ONNX Runtime (C++ / shared libs) |
| **License** | MIT | Apache-2.0 |

## 4. Techniques Worth Adopting in RELAY
1. **Dedicated Keyword Spotting (KWS)**: Using a dedicated KWS model for the *"Relay"* wake word rather than feeding rolling audio buffers into a Whisper model. This drops idle CPU from ~6% down to < 1.5% and prevents Whisper hallucination on background noise.
2. **Unified ONNX Runtime Deployment**: Leveraging ONNX Runtime allows combining Silero VAD, Keyword Spotter, and Piper TTS into a single runtime footprint.

## 5. Techniques NOT Worth Adopting
1. **Multi-Model Sprawl**: sherpa-onnx supports dozens of model families (Paraformer, Wenet, SenseVoice, Nemo). RELAY should avoid model fragmentation and standardize on one proven English STT model.
2. **Custom Transducer Training**: Training custom Zipformer models requires large external datasets; using standard pre-trained models is much safer and lower maintenance.

## 6. Licensing & References
- **License**: Apache License 2.0 (Permissive, fully compatible with RELAY).
- Source Repository: https://github.com/k2-fsa/sherpa-onnx
