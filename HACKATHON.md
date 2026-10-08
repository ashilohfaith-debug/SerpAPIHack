# Relay — SerpApi India Hackathon 2026 Submission

> **The voice interface to the live world.**  
> *Voice → Intent → Search Plan → SerpApi → Evidence → Decision → Action*

---

## 1. Problem

Today's voice assistants are conversational but fundamentally unreliable when decisions depend on the live world.

- Prices change continuously.
- Flights and hotel availability fluctuate by the minute.
- Local businesses open, close, and update operating hours.
- Breaking news and product releases evolve in real time.
- Ratings and user reviews shift over time.

An LLM's static training memory or hallucinated guesses are **not enough**. When a user asks an assistant to plan a trip, compare laptop prices, or find an open restaurant, guessing current facts leads to broken real-world decisions.

---

## 2. Core Insight

**Separate reasoning from reality.**

```
┌─────────────────────────────────────────────────────────────┐
│  LLM       →  Knows how to reason                           │
│  SerpApi   →  Knows what is true right now                  │
│  Relay     →  Knows how to act                             │
└─────────────────────────────────────────────────────────────┘
```

Relay enforces a strict architectural boundary: **The reasoning layer MUST NOT provide an answer for live facts until SerpApi returns usable evidence.**

---

## 3. System Architecture

```
User Voice Input
       │
       ▼
 ┌───────────┐
 │ STT Engine│  (Whisper / Sarvam)
 └─────┬─────┘
       │
       ▼
┌───────────────┐
│LiveWorldRouter│  (Deterministic & intent classifier)
└──────┬────────┘
       │
       ├─────────────────────────────────────────┐
       │ (requiresLiveData = False)              │ (requiresLiveData = True)
       ▼                                         ▼
┌─────────────┐                        ┌──────────────────┐
│Local Skills │                        │ LiveWorldBroker  │
│  & Actions  │                        └────────┬─────────┘
└─────────────┘                                 │
                                                ▼
                                       ┌──────────────────┐
                                       │  Search Planner  │
                                       └────────┬─────────┘
                                                │
                                                ▼
                                       ┌──────────────────┐
                                       │ SerpApi Engines  │ (Parallel Execution)
                                       └────────┬─────────┘
                                                │
                                                ▼
                                       ┌──────────────────┐
                                       │ Normalization &  │
                                       │ Evidence Store   │
                                       └────────┬─────────┘
                                                │
                                                ▼
                                       ┌──────────────────┐
                                       │ Decision Engine  │ (Grounded reasoning)
                                       └────────┬─────────┘
                                                │
                                                ▼
                                       ┌──────────────────┐
                                       │ Action Provenance│
                                       └────────┬─────────┘
                                                │
                                                ▼
                                       Grounded Voice Answer
                                      + Interactive Result UI
                                      + Action Execution
```

---

## 4. Why SerpApi is Essential

Relay **fails closed** if `SERPAPI_API_KEY` is missing or SerpApi is unreachable.

If live-world data is required and SerpApi cannot be reached, Relay explicitly announces:

> *"I understood the request, but live-world access is unavailable, so I can't verify current results."*

Relay **never silently falls back to LLM memory for live facts.**

If SerpApi disappears, Relay completely loses its connection to the live world.

---

## 5. SerpApi Engines Implemented

Relay integrates official SerpApi endpoints across 6 specialized search engines:

1. **`google_flights`**: Real-time airline flight schedules, prices, departure/arrival times, nonstop status, and direct booking URLs.
2. **`google_hotels`**: Live hotel nightly rates, overall ratings, review counts, location areas, and property details.
3. **`google_maps`**: Local business listings, addresses, user review counts, star ratings, and operating status.
4. **`google_shopping`**: Real-time product prices across e-commerce merchants, inline deals, and store links.
5. **`google_news`**: Breaking news headlines, publisher sources, and publication timestamps.
6. **`google`**: General organic web search for specification verification, reviews, and primary sources.

---

## 6. Signature Original Features

### 1. Speculative Voice Search
To eliminate voice latency, search execution begins **before the user finishes speaking** as soon as intent and key constraints (origin, destination, budget, location) stabilize during STT transcript streaming. If the finalized request matches the speculative search, evidence is reused instantly. If intent changes, in-flight searches are cleanly cancelled using cancellation tokens.

### 2. Multi-Engine Search Planning
Relay plans targeted searches across multiple SerpApi engines concurrently within a strict search budget (maximum 6 calls per request, typical 2–4 calls).

### 3. Grounded Evidence & Citation Integrity
Every current-world factual claim in the decision must cite an `evidenceId` stored in the `EvidenceStore`. Any hallucinated or invalid citation ID is rejected by the decision verifier.

### 4. Action Provenance UI
Before Relay executes an external action (e.g. opening a flight result or maps business), it presents an explicit provenance card explaining **WHY** the option was selected, **LIVE EVIDENCE** sources, and **FRESHNESS**.

---

## 7. Existing Project Disclosure

Relay existed prior to the hackathon as a Windows-first, offline-first voice control assistant designed for accessibility.

**Added during the SerpApi India Hackathon 2026:**
- The entire `relay.liveworld` subsystem (`LiveWorldBroker`, `LiveWorldRouter`, `SearchPlanner`, `SerpApiClient`, `EvidenceStore`, `GroundedDecisionEngine`, `ProvenanceGenerator`, `SpeculativeSearchManager`)
- SerpApi multi-engine integration (`google_flights`, `google_hotels`, `google_maps`, `google_shopping`, `google_news`, `google`)
- Live evidence normalization & citation verification system
- Action provenance UI & Live World Web Panel components
- Developer demo disconnect toggle mode for SerpApi offline testing
- Hackathon test suite and benchmark integration

---

## 8. AI Tools Used

- **Claude / Gemini (via Antigravity AI coding assistant)**: Used for architecture design, refactoring, writing normalizer functions, UI styling, and automated unit test generation.
