# Research: NVDA Screen Reader Architecture

## 1. Overview
NonVisual Desktop Access (NVDA) is an open-source, extensible screen reader for Windows developed by NV Access. Built primarily in Python with C++ native helpers, it provides non-visual interaction through synthetic speech and braille.

## 2. Architectural Blueprint
```
[Windows OS / Target Application]
       ↓ (WinEvents / UIA Events / In-process Hooks)
[nvdaHelper (C++)]
       ↓ (IPC / Shared Memory)
[eventHandler (Python)]
       ↓ (Central Thread-Safe Queue)
[NVDAObject Layer (UIA, IAccessible, Java, Web)]
       ↓ (appModules / treeInterceptor)
[Speech & Braille Managers]
       ↓ (Speech Dictionaries & Priority Policy)
[Synthesizer Drivers (OneCore, SAPI, Piper)]
```

## 3. Important Abstractions
- **`NVDAObject`**: The unified abstract representation of any accessible control. Normalizes disparate accessibility APIs (MSAA, IAccessible2, UI Automation) into standard attributes: `name`, `role`, `value`, `states`, `description`, `location`.
- **`appModules`**: Per-application customization scripts (e.g. `explorer.py`, `notepad.py`, `chrome.py`). When an application behaves idiosyncratically or violates accessibility standards, an `appModule` intercepts events and patches behavior without polluting the global engine.
- **`treeInterceptor` / Virtual Buffer**: Flattens complex, deeply nested web pages and PDFs into an indexed, linear textual buffer that the user can navigate with standard reading keystrokes.
- **`eventHandler`**: A queue-driven asynchronous event processor running on a dedicated thread, ensuring that slow speech synthesis never freezes Windows UI interactions.

## 4. Techniques Worth Adopting in RELAY
1. **Application-Specific Adapters**: RELAY adopts lightweight app adapters in `relay/skills.py` and `relay/perception/` for top user targets (File Explorer, Notepad, Chrome, Windows Settings).
2. **Instant Speech Interruption (Barge-In)**: Dropping buffered audio frames and signaling the TTS driver to halt immediately (<20 ms) when the user presses a talk key or speaks.
3. **Event Queue Decoupling**: Keeping UIA event callbacks completely separate from speech synthesis and executor execution to prevent COM deadlocks.

## 5. Techniques NOT Worth Adopting
1. **In-Process DLL Injection**: NVDA injects `nvdaHelperRemote.dll` into target process spaces to hook Windows messages (`SendMessage`/`SetWinEventHook`). RELAY operates strictly **out-of-process** via standard `UIAutomationClient` COM APIs to avoid antivirus false positives, process crashes, and privilege elevation issues.
2. **Legacy MSAA / IAccessible Support**: Windows 95/XP era accessibility APIs carry heavy legacy overhead. RELAY targets Windows 10 & 11 and relies on clean modern UI Automation.
3. **Monolithic Addon Ecosystem**: RELAY maintains an auditable, minimal dependency footprint without external third-party addon injection.

## 6. Licensing & Legal Constraints
- **License**: GNU General Public License v2 (GPL-2.0).
- **Rule for RELAY**: **NO NVDA source code may be copied, borrowed, or dynamically linked.** RELAY is MIT-licensed. Only independent conceptual design patterns (such as out-of-band app adapters and asynchronous event queues) are studied.
- Source Repository: https://github.com/nvaccess/nvda
