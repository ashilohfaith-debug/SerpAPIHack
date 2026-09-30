# Research: llama.cpp Architecture & Techniques

## 1. What the Project Does
`llama.cpp` is a high-efficiency C/C++ engine for local LLM inference, created by Georgi Gerganov and the GGML team. It runs quantized transformer language models across CPUs and GPUs with minimal dependencies and exceptional memory efficiency.

## 2. Core Architecture
- **GGUF Format**: A unified single-file binary container storing model architecture, hyperparameters, tokenizer vocabularies, and tensor weights.
- **Memory-Mapped Loading (`mmap`)**: Models are loaded via OS memory-mapping. Pages are faulted into physical RAM only as accessed, allowing near-instantaneous startup.
- **Advanced Quantization (k-quants)**:
  - Quantizes non-critical weight matrices aggressively while preserving precision in critical attention layers.
  - `Q4_K_M`: 4-bit medium quantization, standard sweet spot for quality vs. speed.
  - `IQ3_XXS` / `IQ2_XS`: Extreme sub-3-bit quantization for ultra-low-RAM targets.
- **KV Cache Optimization**: Employs rolling/sliding-window KV caches and context-shifting to cap memory usage during extended conversations.

## 3. Constrained Sampling: GBNF Grammars
A standout feature of `llama.cpp` is **GBNF (GGML BNF) Grammar-Constrained Sampling**:
- During each auto-regressive step, logits of tokens that violate a specified context-free grammar are masked out (set to $-\infty$).
- **Impact for RELAY**: Guarantees that any action suggested by the LLM strictly matches valid syntax (e.g. valid JSON or `DO: open Notepad`), eliminating syntax parsing failures.

## 4. Drop-in Integration: `llama-server`
`llama.cpp` includes a lightweight, single-binary HTTP server (`llama-server`):
- Exposes standard OpenAI-compatible endpoints: `POST /v1/chat/completions`.
- Supports Server-Sent Events (SSE) token streaming.
- **Seamless RELAY Compatibility**: RELAY's existing `OpenAIClient` ([`relay/llm/client.py`](file:///d:/RELAY/app/relay/llm/client.py)) can connect directly to `http://127.0.0.1:8080/v1` without any architectural refactoring!

## 5. Techniques Worth Adopting in RELAY
1. **Memory-Mapped Model Loading (`mmap`)**: Instantaneous app launch without waiting for gigabytes of weights to be copied into heap memory.
2. **GBNF Constrained Decoding**: Forcing tool-use actions to conform to the deterministic offline grammar.
3. **OpenAI Endpoint Compatibility**: Integrating with `llama-server` allows seamless toggling between FreeLLMAPI, local llama.cpp, or remote routers through the same client abstraction.

## 6. Techniques NOT Worth Adopting
1. **Massive Context Allocations (32k+)**: Allocating huge KV caches consumes 1–2 GB of RAM solely for context. Capping context to 2,048 tokens preserves RAM for the operating system and voice pipeline.
2. **Persistent GPU VRAM Reservation**: Reserving VRAM continuously drains laptop battery; allow memory to be paged or freed when idle.

## 7. Licensing & References
- **License**: MIT License (Permissive, completely compatible with RELAY).
- Source Repository: https://github.com/ggml-org/llama.cpp
