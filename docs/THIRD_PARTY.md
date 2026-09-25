# Third-party dependencies & license review

RELAY is MIT-licensed. Every runtime dependency below is a **permissive** license
(MIT / BSD / Apache-2.0 / PSF / HPND) — none are copyleft — so they are compatible
with RELAY's MIT distribution. No GPL or unlicensed code is linked or bundled.

## Runtime dependencies (Essential mode)
| Package | Purpose | License |
|---|---|---|
| faster-whisper | STT (tiny.en int8) | MIT |
| ctranslate2 | STT inference engine | MIT |
| onnxruntime | Piper / RapidOCR backend | MIT |
| piper-tts | offline TTS | MIT |
| webrtcvad-wheels | voice activity detection | BSD-3 (WebRTC) |
| sounddevice | mic/speaker I/O | MIT |
| soundfile | audio file I/O | BSD-3 |
| numpy | audio buffers | BSD-3 |
| pywin32 | SAPI TTS fallback + Win32 | PSF-2.0 |
| uiautomation | Windows UI Automation | Apache-2.0 *(verify at release)* |
| comtypes | COM bridge for UIA | MIT |
| rapidocr-onnxruntime | on-demand OCR | Apache-2.0 |
| pillow | image handling for OCR | HPND (MIT-style) |
| mss | screen capture for OCR | MIT |
| pyautogui | keyboard/mouse fallback input | BSD-3 |
| pyperclip | clipboard for reliable text entry | BSD-3 |
| psutil | process/app + perf measurement | BSD-3 |
| tokenizers / huggingface_hub | pulled by faster-whisper | Apache-2.0 |

Dev/packaging only: pytest, ruff, pyinstaller (all permissive).

## Model weights
| Model | License | Note |
|---|---|---|
| Whisper tiny.en (via faster-whisper) | MIT | OpenAI Whisper weights, MIT |
| RapidOCR ONNX det/rec | Apache-2.0 | ships in the package |
| Piper voice `en_US-lessac-medium` | **verify at release** | Piper code is MIT; individual voice datasets vary — confirm the chosen voice's license before redistribution |

## Reference projects (audited, see NOTICE)
- **screen-use** (MIT), **clacky** (MIT) — small components/patterns adapted, with attribution in `NOTICE`.
- **shorka** (no license) — design reference only, reimplemented from scratch; no source copied.
- **VisionAssistantPro** (GPL-2.0) — engineering/accessibility lessons only; **no code reused or linked**, so no copyleft obligation attaches to RELAY.

## Action items before public release
1. Confirm the Piper voice's redistribution license (or ship a voice with a clear permissive/CC license).
2. Verify `uiautomation`'s exact license string in its distribution metadata.
3. Generate a full pinned SBOM (`uv pip freeze`) and attach it to the release.
