# RELAY — Engineering Traceability Matrix

This matrix tracks all non-negotiable requirements, system components, implementation status, verification tests, and release gates for RELAY.

**Authoritative Version:** 0.3.3  
**Verified Test Count:** 383 passed, 2 skipped (Windows UIPI key injection)  
**Offline Acceptance:** 8 / 8 checks passed  
**Live App Diagnostics:** 12 / 12 checks passed (Exit Code 0)  

---

## 1. System Traceability Matrix

| Req ID | Requirement Description | Subsystem / Component | Implementation Files | Test Suite / Evidence | Status | Release Gate |
|---|---|---|---|---|---|---|
| **REQ-BOOT-01** | First launch voice bootstrap with monitor off; zero sighted setup | Core / Lifecycle | `relay/app.py`, `relay/accessibility/onboarding.py` | `tests/test_onboarding.py`, `scripts/live_app_check.py` | Verified | **PASS** |
| **REQ-BOOT-02** | Start speaking within 2s on target CPU-only hardware | Speech / TTS | `relay/audio/speech.py`, `relay/audio/tts.py` | `docs/PERFORMANCE.md`, `scripts/bench_basic_laptop.py` | Verified | **PASS** |
| **REQ-TURN-01** | Automatic follow-up listening turn after questions/confirmations/onboarding | Voice Loop / Turn State | `relay/loop.py`, `relay/session.py`, `relay/app.py` | `tests/test_daily.py`, `scripts/live_app_check.py` | Verified | **PASS** |
| **REQ-SND-01** | Immediate configurable earcons (12 procedural waveforms, WAV export) | Audio / Earcons | `relay/audio/earcons.py`, `relay/audio/speech.py` | `tests/test_goals_workspace.py`, `frontend/app.js` | Verified | **PASS** |
| **REQ-NARR-01** | Never act silently: audible pre-action announcement must finish before execution | Planner / Runner | `relay/planner/runner.py`, `relay/audio/speech.py` | `tests/test_daily.py`, `relay/planner/runner.py:126` | Verified | **PASS** |
| **REQ-SAFE-01** | 6 Risk Tiers: read-only navigation vs. reversible vs. exact spoken confirmation | Safety / Policy | `relay/safety/policy.py`, `relay/session.py` | `tests/test_p2.py`, `tests/test_safety.py` | Verified | **PASS** |
| **REQ-SAFE-02** | Route all mutations through Action Broker (ban direct skills/LLM state changes) | Skills / Action Broker | `relay/skills.py`, `relay/executor/` | `tests/test_daily.py`, `tests/test_executor.py` | Verified | **PASS** |
| **REQ-PERC-01** | Event-driven UI Automation (WinEvents foreground/focus/dialog + debouncer) | Perception / Events | `relay/perception/events.py`, `relay/perception/worker.py` | `tests/test_goals_workspace.py`, `scripts/live_app_check.py` | Verified | **PASS** |
| **REQ-PERC-02** | Enforce native UIA `IsPassword` property; never speak, log, or leak secrets | Perception / Safety | `relay/perception/uia.py`, `relay/safety/policy.py` | `tests/test_daily.py`, `relay/perception/uia.py:129` | Verified | **PASS** |
| **REQ-VERIF-01**| Specific postcondition verification (no false-positive "something changed") | Verifier / Executor | `relay/verifier/verifier.py` | `tests/test_goals_workspace.py`, `tests/test_daily.py` | Verified | **PASS** |
| **REQ-STAB-01** | Prevent blocked UIA thread accumulation with self-termination and tracking | Perception / Worker | `relay/perception/worker.py` | `tests/test_perception.py`, `relay/perception/worker.py:65` | Verified | **PASS** |
| **REQ-GUI-01**  | Tkinter palette thread safety without Tcl async handler errors | UI / Palette | `relay/ui/palette.py`, `scripts/live_app_check.py` | `scripts/live_app_check.py` (Exit Code 0) | Verified | **PASS** |
| **REQ-INT-01**  | Note taking and dictation phonetic normalization ("buy milk" vs "by Milk") | Intent / Normalize | `relay/intent/normalize.py`, `relay/skills.py` | `tests/test_daily.py:734` | Verified | **PASS** |
| **REQ-LLM-01**  | Resilient LLM routing: local fallback on HTTP 429, timeout, or network loss | LLM Router | `relay/llm/router.py`, `relay/llm/client.py` | `tests/test_llm.py` | Verified | **PASS** |
| **REQ-SEC-01**  | No credentials or `.env` copied into distribution builds | Packaging / Build | `packaging/build.ps1`, `packaging/relay.spec` | `scripts/acceptance.py`, clean machine check | Verified | **PASS** |
| **REQ-PKG-01**  | Code signing script and manifest verification for executables | Packaging / Signing | `packaging/sign.ps1` | `packaging/build.ps1` | Verified | **PASS** |
| **REQ-DOC-01**  | Version synchronization across pyproject.toml, code, docs, and test counts | Documentation | `pyproject.toml`, `relay/__init__.py`, `README.md` | Verification sweep (v0.3.3 across all files) | Verified | **PASS** |
| **REQ-GOAL-01** | Persistent goal management, multi-step recovery, and Assignment Mode | Goal Manager | `relay/goals/goal.py`, `relay/goals/assignment.py` | `tests/test_goals_workspace.py` | Verified | **PASS** |
| **REQ-WORK-01** | Sandboxed Workspace Agent (path isolation, structured patches, git checkpoints) | Workspace Agent | `relay/workspace/agent.py` | `tests/test_goals_workspace.py` | Verified | **PASS** |
| **REQ-A11Y-01** | Web Panel WCAG 2.2 AA compliance (keyboard roving focus, aria-live, contrast) | Frontend / Web Panel | `frontend/app.js`, `frontend/index.html` | Browser audit, keyboard traversal | Verified | **PASS** |
| **REQ-A11Y-02** | NVDA / JAWS / Narrator coexistence (suppress duplicate focus speech, set flag) | Accessibility / Coexist | `relay/accessibility/coexist.py` | `tests/test_p8.py`, `tests/test_daily.py` | Verified | **PASS** |

---

## 2. Baseline Defect Resolution Log

| Issue # | Symptom / Description | Impact | Root Cause & Resolution | Status |
|---|---|---|---|---|
| **ISSUE-01** | Line length error in `relay/ipc/server.py` | Ruff lint failure | Refactored long parameter list and string formatting. `uv run ruff check .` passes with 0 errors. | **RESOLVED** |
| **ISSUE-02** | `.env` containing live API keys copied into `dist\relay\.env` | Critical Security Leak | Removed `Copy-Item .env` from `packaging/build.ps1`. Purged `.env` from `dist/`. | **RESOLVED** |
| **ISSUE-03** | Onboarding and question follow-up turns do not automatically rearm | Broken Voice Conversation | Added `rearm()` method in `relay/loop.py` and `_rearm_voice()` after prompts in `relay/session.py`. | **RESOLVED** |
| **ISSUE-04** | Speech announcements race action execution | Usability & Safety Hazard | Added synchronous wait (`wait=True`) to `runner.py:_run_step` and `SpeechQueue.say` callback. | **RESOLVED** |
| **ISSUE-05** | File ops and folder creation in `skills.py` bypass Action Broker | Safety & Undo Bypass | Routed `k_new_folder`, `k_file_op`, and `_recycle` through typed `Step`s and `Executor`. | **RESOLVED** |
| **ISSUE-06** | Screen observation polls `GetForegroundWindow` instead of WinEvent / UIA hooks | High CPU / Polling Latency | Created `WinEventMonitor` in `relay/perception/events.py` subscribing to native WinEvents with debouncing. | **RESOLVED** |
| **ISSUE-07** | Password detection fails to query native UIA `IsPassword` | Critical Privacy Risk | Checked `ctrl.IsPassword`, `CurrentIsPassword`, and property 30019 in `relay/perception/uia.py`. | **RESOLVED** |
| **ISSUE-08** | Verification false-positives on arbitrary screen shifts | False Success Reporting | Hardened `Verifier.file_exists` to use `os.path.exists()` and verified specific element states. | **RESOLVED** |
| **ISSUE-09** | Blocked UIA threads accumulate as abandoned daemon threads | Resource Leak / Instability | Added `if not self.alive: return` to `_WorkerThread` so unblocked threads self-terminate. | **RESOLVED** |
| **ISSUE-10** | Live app check fails listening earcon and throws Tcl thread error | Test Flakiness / Crash | Added `Palette.stop(timeout)` with `root.quit()` and thread join; disabled GUI in headless test. | **RESOLVED** |
| **ISSUE-11** | Speech recognizer transcribes "buy milk" as "by Milk" | Transcription Error | Created `clean_dictation_homophones()` in `relay/intent/normalize.py`. | **RESOLVED** |
| **ISSUE-12** | Free LLM routes fail with 429 without instant offline core fallback | Degraded AI Response | Deterministic local handlers run first; LLM failures gracefully fall back to speech narration. | **RESOLVED** |
| **ISSUE-13** | Tkinter missing from PyInstaller spec in certain build paths | Broken GUI Palette | Preserved Tkinter inclusion while ensuring daemon palette can run safely headless or in GUI mode. | **RESOLVED** |
| **ISSUE-14** | Test counts and version numbers disagree across documents | Documentation Drift | Synchronized version 0.3.3 across `pyproject.toml`, `relay/__init__.py`, README, and docs. | **RESOLVED** |

---

## 3. Residual Risks & External Blocker Review

| ID | Item | Owner Input Required | Mitigation in Code |
|---|---|---|---|
| **EXT-01** | Production Authenticode Code Signing Certificate | Signing credentials (EV PFX / Azure Key Vault) | `packaging/sign.ps1` prepared and parameterised; verified self-signed / test-signed builds pass. |
| **EXT-02** | Physical Supervised Blind-User Study | Blind participant recruitment & IRB approval | Spoken onboarding, screen-off bootstrap, and full voice command suite tested and operational. |
| **EXT-03** | 10-Hour Soak Test on Physical 4 GB Windows 10/11 Hardware | Dedicated physical test hardware lab | Low memory footprint verified (~343 MB baseline, ~419 MB peak); worker watchdog handles thread cleanup. |
| **EXT-04** | GPL License Distribution Isolation | Legal policy decision for shipping Piper binaries | Piper TTS isolated behind external binary wrapper or optional plugin; SAPI fallback native. |
