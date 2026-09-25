# RELAY — release acceptance

This maps RELAY's core promises to **how each is verified** and its **honest status**.
"Verified offline" means an automated check runs it with no network and no risk to the
desktop (`scripts/acceptance.py` and the `pytest` suite). "Needs hardware/people" means
the check is real and designed but requires a clean machine, NVDA, target hardware, or
blind users — it cannot be faithfully substituted here, and saying otherwise would be
fabricating a result.

## Run the offline suite
```
uv run python scripts/acceptance.py      # cross-cutting acceptance checks
uv run pytest -m "not integration"       # full unit/behaviour suite
```
The demos are the human-facing version of the same behaviours:
`relay --demo-confirm`, `--demo-memory`, `--voice-selftest`, `--capabilities`,
`--observe`.

## Acceptance matrix

| # | Requirement | How it's verified | Status |
|---|---|---|---|
| 1 | **Transparent operator, not an autonomous agent** — acts only on command, narrates every action before acting, reports every task-relevant change, idles between tasks | TransparentRunner announce→act→verify→narrate; wake-gated loop only acts on "relay …"; unit tests `test_runner*`, `test_p12` (wake gating); demo `--observe` | Verified offline |
| 2 | **Every change is announced** (announce-before + change-delta after) | `relay/narration/delta.py`, runner tests | Verified offline |
| 3 | **Voice operates everything**; UI is optional and never required | Voice loop + Session dispatch; panel is a read-mostly IPC client | Verified offline (synthetic voice); **real-mic field test needs people** |
| 4 | **Offline voice round-trip** (Piper TTS → faster-whisper STT) | `scripts/acceptance.py::check_voice_roundtrip_offline`, `test_stt_roundtrip` | Verified offline |
| 5 | **High-risk actions need an action-specific spoken phrase**, never a bare "yes"; most sensitive require keyboard/Windows-auth | `check_confirmation_safety`, `test_confirm*`; demo `--demo-confirm` | Verified offline |
| 6 | **Emergency stop** independent of workers | `relay/core/emergency.py`, `test_emergency` | Verified offline |
| 7 | **No fabricated success** — verify by re-observation; never auto-repeat an uncertain irreversible action after a crash | `relay/verifier`, `relay/memory/reconcile.py`, `check_memory_persist_and_reconcile`, `test_reconcile` | Verified offline |
| 8 | **Five-layer memory persists** across restart; refuses secrets; episodic is opt-in | `check_memory_persist_and_reconcile`, `test_memory*`, `test_store_sensitive` | Verified offline |
| 9 | **Never force-closes apps / no destructive cleanup** (post-incident policy) | No `taskkill` anywhere; `docs/SECURITY.md`; grep-clean | Verified offline |
| 10 | **Secrets never read/logged/stored**; protected fields skipped | `is_protected_field`, logger redaction, `test_policy`, `test_logging_redaction` | Verified offline |
| 11 | **Optional panel IPC is locked down** (loopback, token, whitelist) | `check_ipc_auth`, `test_ipc*` | Verified offline |
| 12 | **Honest capability matrix** (what RELAY can/can't drive) | `check_capabilities`, `relay/workflows.py`, demo `--capabilities` | Verified offline |
| 13 | **Single instance** drives the desktop; second launch exits cleanly | `test_p12` single-instance; `relay --start` guard | Verified offline |
| 14 | **Memory footprint** fits a 4 GB machine (idle ~35 MB; Essential peak ~330–406 MB; survived a 1 GB cap) | `scripts/bench_perf.py` (measured, not estimated) | Measured on this machine; **4 GB-hardware latency cert needs that hardware** |
| 15 | **Runs offline end-to-end from a packaged build on a clean machine** | `packaging/relay.spec` + `build.ps1`; `docs/PACKAGING.md` clean-VM test | **Needs a clean VM** — build spec written, not yet built/run |
| 16 | **Coexists with NVDA** (doesn't fight the screen reader) | `relay/accessibility/coexist.py` (designed) | **Needs NVDA installed** — untested |
| 17 | **Usable by blind users** for real tasks | Supervised sessions with target users | **Needs people** — not yet done |
| 18 | **Signed installer**, SmartScreen-clean | code-sign + MSIX/Inno per `docs/PACKAGING.md` | **Needs a certificate** |

## What "done" honestly means today
Rows 1–13 are automated and green offline; row 14 is really measured on this machine.
Rows 15–18 are the real-world release gates that require a clean VM, NVDA, target
hardware, a code-signing certificate, and blind users. They are specified and scripted
as far as possible without those resources, and are explicitly **not** claimed as passed.
Nothing in this suite fabricates a result it did not actually observe.
