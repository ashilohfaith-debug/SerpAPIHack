# Research: Accessibility Architecture & WCAG 2.2 Standards

## 1. Overview & Core Mission
Accessibility in RELAY is not a post-hoc compliance audit; it is the core operating premise. The system serves blind and low-vision users who interact with Windows 10 & 11 primarily or exclusively through auditory feedback, speech input, and keyboard navigation.

## 2. Web Accessibility (WCAG 2.2 AA)
The web panel and simulator (`index.html`, `frontend/panel.html`) implement:
- **WCAG 2.2 SC 2.4.11 / 2.4.12 Focus Appearance & Not Obscured**: High-contrast 3px focus rings (`#00e5ff` / `#ffff00`) with at least 3:1 contrast against adjacent background colors.
- **WCAG 2.2 SC 2.5.8 Target Size (Minimum)**: All interactive buttons and click targets have a minimum dimension of 24×24 CSS pixels.
- **WCAG 2.2 SC 3.3.7 Redundant Entry**: Avoids re-asking for data previously submitted in the same session.
- **Screen Reader Announcements (`aria-live`)**:
  - Live state updates route through an announcer container: `<div id="srAnnouncer" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div>`.
  - Non-intrusive status updates use `polite`; urgent alerts or emergency stops use `assertive`.
- **Keyboard Navigation**:
  - Unbroken Tab order across all controls.
  - Skip links for fast navigation (`#main-content`, `#simulator`, `#commands`).
  - Escape closes modal states and dialogs with focus restored to the trigger.

## 3. Auditory Feedback & Earcon Soundscapes
Visual feedback is insufficient for non-sighted users. Auditory cues provide instant comprehension:
- **Procedural Web Audio / PCM Earcons**:
  - *Wake / Listen*: Ascending sine sweep (440 Hz -> 880 Hz, 120 ms).
  - *Verified Success*: Harmonic major chord (C5, E5, G5, 240 ms).
  - *Alert / Confirmation Needed*: Soft double-pulse (360 Hz, 100 ms each).
  - *Emergency Halt*: Rapid descending sawtooth drop (280 Hz -> 90 Hz, 200 ms).
  - *Click / Focus*: Short high-frequency tap (1000 Hz, 25 ms).

## 4. Hardware Awareness & Privacy Preservation
- **Headphone Auto-Routing**: Dynamic detection of 3.5mm, USB-C, and Bluetooth audio devices.
- **Private Content Shield**: If headphones are disconnected mid-reading, RELAY immediately pauses speech synthesis rather than broadcasting private document contents to the surrounding room.

## 5. Licensing & References
- W3C WCAG 2.2 Specification: https://www.w3.org/TR/WCAG22/
- WebAIM Guidelines: https://webaim.org/standards/wcag/checklist
