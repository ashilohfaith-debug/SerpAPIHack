# Research: Local LLM Runtime Architecture

## 1. Overview & Architectural Role
In RELAY, an LLM is **never required** for core operating system tasks (opening windows, reading text, typing, system settings, or daily math). Those tasks are handled deterministically by the offline grammar in `< 1 ms`.

However, for open-ended conversational queries (*"Why is the sky blue?"*, *"Summarize this article"*, *"Draft an email apologizing for the delay"*), an embedded or local LLM runtime provides complete offline privacy, zero subscription fees, and no cloud dependency.

## 2. Technical Requirements for Assistive Desktop Environments
1. **Strict Hardware Budget**:
   - Laptop RAM Target: Must run within available system RAM without paging to disk. Models must be bounded to 1B–3B parameters with 4-bit quantization (Q4_K_M), requiring ~800 MB to 1.8 GB RAM.
2. **Streaming Spoken Narration**:
   - The user must hear spoken audio within 300 ms of the first generated sentence. The runtime must emit tokens via a stream generator, allowing a sentence-splitter to dispatch completed sentences to the TTS pipeline immediately.
3. **Constrained Generation (Grammar Sampling)**:
   - When the LLM is asked to suggest actions, its output must be strictly constrained (e.g. via GBNF grammar or JSON schema) to prevent hallucinated commands or invalid syntax.

## 3. Candidate Small Language Models (SLMs)
| Model | Parameters | Quantization | RAM Footprint | Inference Speed (CPU) |
|---|---|---|---|---|
| **SmolLM2-1.7B-Instruct** | 1.7B | Q4_K_M | ~1.1 GB | ~24 tok/s |
| **Qwen2.5-1.5B-Instruct** | 1.5B | Q4_K_M | ~1.0 GB | ~28 tok/s |
| **Llama-3.2-1B-Instruct** | 1.2B | Q4_K_M | ~850 MB | ~32 tok/s |
| **Llama-3.2-3B-Instruct** | 3.2B | Q4_K_M | ~2.1 GB | ~14 tok/s |

## 4. Privacy & Security Boundaries
- **Zero Network Egress**: With a local runtime (such as llama.cpp), private documents, emails, and spoken conversation never leave the laptop.
- **Untrusted Output Policy**: Any action suggested by the local LLM (`DO: <action>`) remains untrusted. It must pass through the deterministic grammar parser and the Permission Engine risk gate before execution.
