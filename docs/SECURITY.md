# RELAY — security & privacy

RELAY observes and operates a user's computer, so privacy and safety are core, not
add-ons. This documents the guarantees the code actually implements (with file
references) and the honest limits.

## Privacy (implemented)
- **Local by default.** No screenshots, audio, documents or activity are transmitted
  anywhere. Essential mode has no network dependency at all.
- **No screenshot retention.** Screen state (L1) lives in RAM and is replaced, not
  stored (`relay/perception/worker.py`). OCR captures are used and discarded.
- **Secret redaction in logs.** The logger drops password/OTP/token-shaped values
  (`relay/diagnostics/logging.py`).
- **Protected fields never read.** Password/OTP/PIN/CVV fields are detected and their
  values are never read aloud, logged, or stored (`relay/safety/policy.py::is_protected_field`,
  `relay/perception/uia.py`).
- **Memory refuses secrets.** The memory store rejects credential-shaped content
  (`relay/memory/store.py::looks_sensitive`); episodic capture is **opt-in** and off by
  default; deletion purges the FTS index too.
- **Per-user data.** Preferences/journal/memory live under `%LOCALAPPDATA%\RELAY`
  (`relay/config.py`).

## Safety (implemented)
- **Single permission chokepoint**, separate from any model: every action is classified
  and gated before the executor (`relay/safety/policy.py`, `relay/executor/executor.py`).
- **Accessible strong confirmation:** high-risk actions require an action-specific spoken
  phrase (never a bare "yes"); the most sensitive (purchase/install/security) require a
  keyboard/Windows-auth confirm and are declined by voice (`relay/accessibility/confirm.py`,
  `relay/session.py`). A demo: `relay --demo-confirm`.
- **Emergency stop** independent of any worker; flushes queued input and speech
  (`relay/core/emergency.py`).
- **No fabricated success:** actions are verified by re-observation; uncertain irreversible
  actions are never auto-repeated after a crash (`relay/verifier`, `relay/memory/reconcile.py`).
- **Untrusted content isolation:** text read from screens/pages/docs is data, never a
  command, and can't change permissions.
- **No force-closing apps / no destructive cleanup** (policy adopted after an early demo
  incident): RELAY never kills an app that may hold unsaved work.

## IPC (optional panel) — locked down
`relay/ipc/server.py`:
- Binds **loopback only** (127.0.0.1); Host header validated (anti DNS-rebind).
- **Per-session random token**, constant-time compared on every request.
- **Narrow command whitelist** (`handle`/`set_mode`/`onboard`/`ping`) routed through the
  same safety pipeline — **no raw click/type/coordinate automation is exposed**.
- Streams only a whitelist of state events.

## Windows boundaries (honest limits)
- Runs at the user's integrity level: it **cannot** drive elevated/admin apps or the UAC
  secure desktop, and does not try to. It says so rather than failing silently.
- No administrator privileges are requested by default.

## Not yet done (release gates)
- Code signing (needs a certificate) — see `docs/PACKAGING.md`.
- A formal external security review and pinned SBOM.
- Optional at-rest encryption of the preference DB via Windows DPAPI (design noted; not
  implemented — no passwords are stored there regardless).
