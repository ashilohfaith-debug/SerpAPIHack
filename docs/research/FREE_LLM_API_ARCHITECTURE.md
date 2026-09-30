# RELAY Free LLM API Architecture

## The Problem
Currently, RELAY is heavily optimized for a single external provider (Sarvam for voice, FreeLLMAPI/OpenAI-compatibles for routing). However, relying on a single free-tier provider creates a single point of failure. If the provider goes down or limits the user, the assistant becomes unavailable (falling back to offline-only). 

## End-to-End Goal
Transform RELAY's LLM architecture from a single-provider setup to a multi-provider, resilient fallback network. RELAY should dynamically route requests across multiple free-tier APIs (e.g., Groq, Gemini Free Tier, Together AI, local endpoints) based on real-time latency, quota status, and availability.

## Architecture

### 1. Unified Model Registry (Router)
- **Concept:** Instead of statically fetching `RELAY_LLM_URL` and `RELAY_LLM_KEY` for a single endpoint, the `Router` will maintain a registry of configured providers.
- **Provider Interface:** Each provider config requires:
  - `Base URL`
  - `API Key` (Securely stored via DPAPI)
  - `Supported Models` (e.g., `llama-3-8b-instruct`, `gemini-1.5-flash`)
  - `Rate Limit State` (Tracks 429s)

### 2. The Hedged Routing Strategy
- The current `Router` in `relay/llm/router.py` will be expanded to race multiple providers:
  - **Latency Hedging:** If Provider A (Groq) takes longer than its P90 Time-To-First-Token, immediately spawn a request to Provider B (Gemini). Whichever yields the first token wins.
  - **Failover:** If Provider A returns a `429 Too Many Requests` or `503 Service Unavailable`, instantly failover to Provider B without notifying the user, ensuring uninterrupted conversational flow.

### 3. Voice-Accessible Setup
- The `onboarding.py` loop has been updated to request the first LLM API key via the clipboard.
- We will add a "Provider Management" voice command: *"Relay, add a new API key for Groq"*. 
- The system will read the clipboard, validate the key by hitting the /models endpoint, and add it to DPAPI storage.

### 4. Zero-Downtime Offline Fallback
- If all cloud providers are exhausted (or network is lost), RELAY falls back to the local NLP parser for predefined offline commands, ensuring the user is never left without basic accessibility controls.

## Implementation Plan (Next Steps)
1. Update `relay/llm/__init__.py`'s `routes_from_config` to parse multiple endpoints from `secrets.py`.
2. Expand `Router._race()` to distribute requests across the registered provider URLs.
3. Update `settings()` in `relay/sarvam/voice.py` to gracefully degrade if the primary TTS provider is offline.
