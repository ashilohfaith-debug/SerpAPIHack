/**
 * RELAY Web Experience & Interactive UIA Desktop Simulator
 * Accessibility-first, Dual Auditory/Visual Design, Live IPC Mirror
 */

(function () {
  'use strict';

  // --- 1. STATE & STORAGE ---
  const state = {
    theme: localStorage.getItem('relay_theme') || 'dark',
    fontSize: parseFloat(localStorage.getItem('relay_font_scale')) || 1.0,
    soundEnabled: localStorage.getItem('relay_sound_enabled') !== 'false',
    speechEnabled: localStorage.getItem('relay_speech_enabled') !== 'false',
    speechRate: parseFloat(localStorage.getItem('relay_speech_rate')) || 1.1,
    activeCategory: 'screen',
    isSpeaking: false,
    isListening: false,
    ipcConnected: false,
    activeApp: 'notepad', // notepad, chrome, explorer, settings
    stepIndex: 0,
  };

  // --- 2. ACCESSIBLE SCREEN-READER ANNOUNCER ---
  const announcer = document.getElementById('srAnnouncer');
  function announce(message, priority = 'polite') {
    if (!announcer) return;
    announcer.setAttribute('aria-live', priority);
    announcer.textContent = '';
    setTimeout(() => {
      announcer.textContent = message;
    }, 50);
  }

  // --- 3. WEB AUDIO SYNTHESIZER (RELAY EARCONS) ---
  let audioCtx = null;
  function getAudioCtx() {
    if (!audioCtx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) audioCtx = new AudioContext();
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
    return audioCtx;
  }

  const earcons = {
    // Upbeat ascending chirp (Wake / Talk start)
    listen() {
      if (!state.soundEnabled) return;
      const ctx = getAudioCtx();
      if (!ctx) return;
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(440, now);
      osc.frequency.exponentialRampToValueAtTime(880, now + 0.12);
      gain.gain.setValueAtTime(0.001, now);
      gain.gain.linearRampToValueAtTime(0.18, now + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.12);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.13);
    },

    // Harmonic major chord (Verified Success)
    success() {
      if (!state.soundEnabled) return;
      const ctx = getAudioCtx();
      if (!ctx) return;
      const now = ctx.currentTime;
      const notes = [523.25, 659.25, 783.99]; // C5, E5, G5
      notes.forEach((freq, idx) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(freq, now + idx * 0.04);
        gain.gain.setValueAtTime(0.001, now + idx * 0.04);
        gain.gain.linearRampToValueAtTime(0.12, now + idx * 0.04 + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.04 + 0.22);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + idx * 0.04);
        osc.stop(now + idx * 0.04 + 0.24);
      });
    },

    // Soft alert double-pulse (Confirmation needed)
    alert() {
      if (!state.soundEnabled) return;
      const ctx = getAudioCtx();
      if (!ctx) return;
      const now = ctx.currentTime;
      [0, 0.14].forEach((delay) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(360, now + delay);
        gain.gain.setValueAtTime(0.001, now + delay);
        gain.gain.linearRampToValueAtTime(0.15, now + delay + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, now + delay + 0.1);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + delay);
        osc.stop(now + delay + 0.11);
      });
    },

    // Decisive halting drop (Emergency Stop)
    halt() {
      if (!state.soundEnabled) return;
      const ctx = getAudioCtx();
      if (!ctx) return;
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(280, now);
      osc.frequency.exponentialRampToValueAtTime(90, now + 0.2);
      gain.gain.setValueAtTime(0.2, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.2);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.21);
    },

    // Short UI click
    click() {
      if (!state.soundEnabled) return;
      const ctx = getAudioCtx();
      if (!ctx) return;
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(1000, now);
      gain.gain.setValueAtTime(0.08, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.025);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.03);
    }
  };

  // --- 4. SPEECH SYNTHESIS (SPOKEN ANSWERS) ---
  function speak(text, callback) {
    if (!state.speechEnabled || !('speechSynthesis' in window)) {
      if (callback) callback();
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = state.speechRate;
    utterance.pitch = 1.0;

    // Pick best English voice (Piper / Indian English Sarvam preferred if found)
    const voices = window.speechSynthesis.getVoices();
    const preferredVoice = voices.find(v => v.lang.includes('en-IN')) ||
                           voices.find(v => v.lang.includes('en-US')) ||
                           voices.find(v => v.lang.startsWith('en'));
    if (preferredVoice) utterance.voice = preferredVoice;

    const waveformBox = document.getElementById('simWaveform');
    utterance.onstart = () => {
      state.isSpeaking = true;
      if (waveformBox) waveformBox.classList.add('active');
    };
    utterance.onend = utterance.onerror = () => {
      state.isSpeaking = false;
      if (waveformBox) waveformBox.classList.remove('active');
      if (callback) callback();
    };

    window.speechSynthesis.speak(utterance);
  }

  function stopSpeaking() {
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    state.isSpeaking = false;
    const waveformBox = document.getElementById('simWaveform');
    if (waveformBox) waveformBox.classList.remove('active');
  }

  // --- 5. COMMAND DATA SET & PRESETS ---
  const COMMAND_PRESETS = [
    {
      category: 'screen',
      text: "what's on my screen",
      desc: "Reads foreground window controls and focus through Windows UI Automation",
      app: 'notepad',
      focusSelector: '#simNotepadContent',
      spoken: "Notepad is open. Document notes.txt contains 24 words. Cursor is at line 3.",
      steps: [
        { label: "Speech In", detail: "faster-whisper transcribed audio in 180 ms" },
        { label: "Intent Match", detail: "Deterministic rule: ScreenNarration(depth=1)" },
        { label: "UI Automation", detail: "COM MTA thread queried root UIA element tree" },
        { label: "Verification", detail: "Confirmed active foreground window matches Notepad" },
        { label: "Narration", detail: "Spoken via Piper TTS en_US-ljspeech-medium" }
      ]
    },
    {
      category: 'screen',
      text: "read the page",
      desc: "Extracts headings and paragraphs sequentially with pause/resume support",
      app: 'chrome',
      focusSelector: '#chromeArticleP1',
      spoken: "Reading section: Assistive Tech on Windows 11. Screen readers and speech recognition enable full keyboardless navigation.",
      steps: [
        { label: "Speech In", detail: "faster-whisper heard 'read the page'" },
        { label: "Intent Match", detail: "ReadingIntent(target='page', start=0)" },
        { label: "UI Automation", detail: "Chromium Accessibility DOM tree queried via UIA" },
        { label: "Verification", detail: "Paragraph 1 highlighted and focus locked" },
        { label: "Narration", detail: "Sentence-by-sentence streaming playback" }
      ]
    },
    {
      category: 'everyday',
      text: "open Notepad, type hello world, then save",
      desc: "Multistep sequential chain: launch app, keystroke injection, and save verification",
      app: 'notepad',
      focusSelector: '#notepadSaveBtn',
      spoken: "Notepad opened. Typed hello world. Saved document to your Documents folder.",
      steps: [
        { label: "Speech In", detail: "faster-whisper captured multi-action utterance" },
        { label: "Planner", detail: "Parsed 3 sub-actions: [Launch, SendKeys, Save]" },
        { label: "Execution", detail: "Injected text via SendInput API and Ctrl+S" },
        { label: "Verification", detail: "Observed save dialog close and window title update" },
        { label: "Narration", detail: "Announced verified completion" }
      ]
    },
    {
      category: 'everyday',
      text: "switch to Chrome",
      desc: "Switches active foreground window safely without guessing",
      app: 'chrome',
      focusSelector: '#simChromeWindow',
      spoken: "Switched to Google Chrome. Wikipedia - Screen Reader article is focused.",
      steps: [
        { label: "Speech In", detail: "Transcribed 'switch to Chrome'" },
        { label: "Intent Match", detail: "WindowAction(action='switch', app='Chrome')" },
        { label: "Execution", detail: "SetForegroundWindow called with hwnd 0x004128" },
        { label: "Verification", detail: "GetForegroundWindow confirms Chrome has focus" },
        { label: "Narration", detail: "Announced foreground change" }
      ]
    },
    {
      category: 'hardware',
      text: "turn on Bluetooth",
      desc: "Interacts directly with Windows Settings controls without touching cursor",
      app: 'settings',
      focusSelector: '#btToggleSwitch',
      spoken: "Turned on Bluetooth. 2 paired audio devices are ready.",
      steps: [
        { label: "Speech In", detail: "Transcribed 'turn on Bluetooth'" },
        { label: "Intent Match", detail: "SystemSettings(category='bluetooth', state=True)" },
        { label: "UI Automation", detail: "Invoked UIA TogglePattern on Bluetooth switch" },
        { label: "Verification", detail: "Queried ToggleState: verified On" },
        { label: "Narration", detail: "Spoken status update" }
      ]
    },
    {
      category: 'safety',
      text: "delete this file",
      desc: "Demonstrates safety gate for irreversible actions with confirmation phrase",
      app: 'explorer',
      focusSelector: '#explorerSelectedItem',
      spoken: "Deleting report-draft.docx cannot be undone. To confirm, say confirm delete.",
      isAlert: true,
      steps: [
        { label: "Speech In", detail: "Transcribed 'delete this file'" },
        { label: "Safety Gate", detail: "Classified as DESTRUCTIVE action (Tier 3)" },
        { label: "Execution", detail: "Blocked execution; armed confirmation token" },
        { label: "Awaiting Voice", detail: "Strict match required: 'confirm delete' or 'cancel'" },
        { label: "Narration", detail: "Audible warning chime + spoken safety challenge" }
      ]
    },
    {
      category: 'ai',
      text: "explain what an index fund is",
      desc: "Routes to FreeLLMAPI router / Sarvam AI; streams spoken sentences with low latency",
      app: 'notepad',
      focusSelector: '#simDesktop',
      spoken: "An index fund is an investment portfolio designed to match the components and performance of a market benchmark, like the S&P 500 or NIFTY 50.",
      steps: [
        { label: "Speech In", detail: "faster-whisper captured conversational query" },
        { label: "Intent Match", detail: "Command not local -> routed to FreeLLMAPI /v1" },
        { label: "LLM Stream", detail: "TTFT 1.4s (auto:fast model, hedged route)" },
        { label: "TTS Pipeline", detail: "Sentence-boundary splitter streamed audio to Piper" },
        { label: "Narration", detail: "Playback started before full text completed" }
      ]
    }
  ];

  // --- 6. SIMULATOR LOGIC & DESKTOP RENDERING ---
  function setActiveApp(appKey) {
    state.activeApp = appKey;
    const windows = {
      notepad: document.getElementById('simNotepadWindow'),
      chrome: document.getElementById('simChromeWindow'),
      explorer: document.getElementById('simExplorerWindow'),
      settings: document.getElementById('simSettingsWindow'),
    };
    const taskbarIcons = {
      notepad: document.getElementById('tbNotepad'),
      chrome: document.getElementById('tbChrome'),
      explorer: document.getElementById('tbExplorer'),
      settings: document.getElementById('tbSettings'),
    };

    Object.keys(windows).forEach((key) => {
      const win = windows[key];
      const icon = taskbarIcons[key];
      if (win) {
        if (key === appKey) {
          win.classList.remove('inactive');
          win.classList.add('active');
        } else {
          win.classList.add('inactive');
          win.classList.remove('active');
        }
      }
      if (icon) {
        icon.classList.toggle('running', key === appKey);
      }
    });

    const activeAppBadge = document.getElementById('currentActiveApp');
    if (activeAppBadge) activeAppBadge.textContent = appKey.charAt(0).toUpperCase() + appKey.slice(1);
  }

  function positionFocusBox(targetSelector) {
    const focusBox = document.getElementById('simFocusBox');
    const desktop = document.getElementById('simDesktop');
    if (!focusBox || !desktop) return;

    if (!targetSelector || targetSelector === '#simDesktop') {
      focusBox.classList.remove('visible');
      return;
    }

    const targetEl = document.querySelector(targetSelector);
    if (!targetEl) {
      focusBox.classList.remove('visible');
      return;
    }

    const dRect = desktop.getBoundingClientRect();
    const tRect = targetEl.getBoundingClientRect();

    const top = tRect.top - dRect.top;
    const left = tRect.left - dRect.left;
    const width = tRect.width;
    const height = tRect.height;

    focusBox.style.top = `${top - 4}px`;
    focusBox.style.left = `${left - 4}px`;
    focusBox.style.width = `${width + 8}px`;
    focusBox.style.height = `${height + 8}px`;
    focusBox.classList.add('visible');
  }

  function updatePipelineStepper(steps) {
    const stepper = document.getElementById('pipelineStepper');
    if (!stepper) return;
    stepper.innerHTML = '';

    steps.forEach((step, idx) => {
      const card = document.createElement('div');
      card.className = `pipe-card ${idx === 0 ? 'active-step' : ''}`;
      card.id = `pipeStep-${idx}`;
      card.innerHTML = `
        <span class="pipe-badge">Step 0${idx + 1}</span>
        <h3>${step.label}</h3>
        <p>${step.detail}</p>
      `;
      stepper.appendChild(card);
    });
  }

  function animateStepper(stepCount, onComplete) {
    let current = 0;
    const interval = setInterval(() => {
      const prev = document.getElementById(`pipeStep-${current - 1}`);
      if (prev) prev.classList.remove('active-step');

      const next = document.getElementById(`pipeStep-${current}`);
      if (next) {
        next.classList.add('active-step');
        current++;
      } else {
        clearInterval(interval);
        if (onComplete) onComplete();
      }
    }, 380);
  }

  function executeCommand(cmd) {
    // 1. Play listening earcon
    earcons.listen();
    announce(`Executing command: ${cmd.text}`);

    // Update Banner Text
    const speechText = document.getElementById('simSpeechText');
    const voiceTag = document.getElementById('simVoiceTag');
    if (speechText) speechText.textContent = `Listening: "${cmd.text}"…`;
    if (voiceTag) voiceTag.textContent = "faster-whisper (transcribing)";

    // Update Pipeline
    updatePipelineStepper(cmd.steps);

    // Switch Desktop Active Window
    setActiveApp(cmd.app);

    // Animate Pipeline & Trigger UIA Focus
    animateStepper(cmd.steps.length, () => {
      positionFocusBox(cmd.focusSelector);

      const isSim = !state.ipcConnected;
      const simPrefix = isSim ? "[Demo Simulation] " : "";

      // Play success chime or alert earcon
      if (cmd.isAlert) {
        earcons.alert();
        if (voiceTag) voiceTag.textContent = `Safety Confirmation Required ${isSim ? "(Simulator)" : ""}`;
      } else {
        earcons.success();
        if (voiceTag) voiceTag.textContent = `RELAY Spoken Narration (Piper) ${isSim ? "(Simulator)" : ""}`;
      }

      // Display spoken answer
      if (speechText) speechText.textContent = `"${cmd.spoken}"`;
      announce(cmd.spoken, cmd.isAlert ? 'assertive' : 'polite');

      // Speak aloud through browser TTS with demonstration notice
      speak(cmd.spoken);

      // Log in Mirror Terminal
      addTerminalLog(
        cmd.isAlert ? `⚠️ SAFETY: ${simPrefix}${cmd.spoken}` : `🗣 ${simPrefix}${cmd.spoken}`,
        cmd.isAlert ? 'alert' : 'narration'
      );
    });
  }

  // --- 7. TERMINAL & IPC MIRROR ---
  function addTerminalLog(text, type = 'narration') {
    const terminal = document.getElementById('mirrorTerminal');
    if (!terminal) return;
    const entry = document.createElement('div');
    entry.className = `terminal-entry ${type}`;
    const time = new Date().toLocaleTimeString();
    entry.textContent = `[${time}] ${text}`;
    terminal.insertBefore(entry, terminal.firstChild);
    while (terminal.children.length > 80) terminal.removeChild(terminal.lastChild);
  }

  function setupIpcClient() {
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token') || '';
    const port = urlParams.get('port') || '8765';
    const connBadge = document.getElementById('ipcConnBadge');

    try {
      const es = new EventSource(`/events?token=${encodeURIComponent(token)}`);
      es.onopen = () => {
        state.ipcConnected = true;
        if (connBadge) {
          connBadge.textContent = "Daemon Connected";
          connBadge.className = "badge-pill badge-live";
        }
        addTerminalLog("Connected to local RELAY IPC daemon", "perception");
      };
      es.onerror = () => {
        state.ipcConnected = false;
        if (connBadge) {
          connBadge.textContent = "Simulator Mode";
          connBadge.className = "badge-pill";
          connBadge.style.background = "var(--bg-surface-elevated)";
          connBadge.style.color = "var(--text-secondary)";
        }
      };
      es.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          const d = msg.data || {};
          if (msg.type === 'narration.say' && d.text) {
            addTerminalLog(d.text, 'narration');
            speak(d.text);
          } else if (msg.type === 'perception.change' && d.foreground_app) {
            addTerminalLog(`Foreground: ${d.foreground_app}`, 'perception');
          }
        } catch (_) {}
      };
    } catch (_) {
      // Offline fallback
    }
  }

  // --- 8. ACCESSIBILITY CONTROLS (THEMES & FONT SCALE) ---
  function applyTheme(themeName) {
    state.theme = themeName;
    document.documentElement.setAttribute('data-theme', themeName);
    localStorage.setItem('relay_theme', themeName);
    announce(`Theme changed to ${themeName}`);
  }

  function setFontScale(scale) {
    state.fontSize = Math.min(2.0, Math.max(0.85, scale));
    document.documentElement.style.setProperty('--font-scale', state.fontSize);
    localStorage.setItem('relay_font_scale', state.fontSize);
    const indicator = document.getElementById('fontSizeIndicator');
    if (indicator) indicator.textContent = `${Math.round(state.fontSize * 100)}%`;
    announce(`Font size set to ${Math.round(state.fontSize * 100)} percent`);
  }

  // --- 9. EVENT LISTENERS & INITIALIZATION ---
  function renderCommandCards(category) {
    const container = document.getElementById('commandCardsGrid');
    if (!container) return;
    container.innerHTML = '';

    const filtered = COMMAND_PRESETS.filter(c => c.category === category);
    filtered.forEach((cmd) => {
      const card = document.createElement('div');
      card.className = 'cmd-card';
      card.innerHTML = `
        <div>
          <div class="cmd-voice-phrase">
            <svg class="cmd-voice-icon" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
              <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
            </svg>
            <span>"${cmd.text}"</span>
          </div>
          <p class="cmd-effect-desc" style="margin-top: 8px;">${cmd.desc}</p>
        </div>
        <button class="cmd-action-btn" type="button" aria-label="Simulate command: ${cmd.text}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <polygon points="5 3 19 12 5 21 5 3"/>
          </svg>
          <span>Run Simulation</span>
        </button>
      `;

      card.setAttribute('tabindex', '0');
      card.setAttribute('role', 'region');
      card.setAttribute('aria-label', `Voice command: ${cmd.text}`);

      const runBtn = card.querySelector('.cmd-action-btn');
      runBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        executeCommand(cmd);
      });

      card.addEventListener('keydown', (e) => {
        if (e.target === card && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          executeCommand(cmd);
        }
      });

      container.appendChild(card);
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    // 1. Initialize Themes & Font
    applyTheme(state.theme);
    setFontScale(state.fontSize);

    // 2. Render initial commands
    renderCommandCards(state.activeCategory);

    // 3. Category switching & Tab Accessibility with Roving Focus
    const catButtons = Array.from(document.querySelectorAll('.cat-btn'));
    function selectTab(btn, focus = true) {
      earcons.click();
      catButtons.forEach((b) => {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
        b.setAttribute('tabindex', '-1');
      });
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');
      btn.setAttribute('tabindex', '0');
      if (focus) btn.focus();
      state.activeCategory = btn.dataset.category;
      renderCommandCards(state.activeCategory);
      announce(`Selected category: ${btn.querySelector('span')?.textContent || state.activeCategory}`);
    }

    catButtons.forEach((btn, index) => {
      // Set initial roving tabindex
      if (btn.classList.contains('active')) {
        btn.setAttribute('tabindex', '0');
        btn.setAttribute('aria-selected', 'true');
      } else {
        btn.setAttribute('tabindex', '-1');
        btn.setAttribute('aria-selected', 'false');
      }

      btn.addEventListener('click', () => selectTab(btn, false));

      btn.addEventListener('keydown', (e) => {
        let nextIndex = null;
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
          e.preventDefault();
          nextIndex = (index + 1) % catButtons.length;
        } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
          e.preventDefault();
          nextIndex = (index - 1 + catButtons.length) % catButtons.length;
        } else if (e.key === 'Home') {
          e.preventDefault();
          nextIndex = 0;
        } else if (e.key === 'End') {
          e.preventDefault();
          nextIndex = catButtons.length - 1;
        }
        if (nextIndex !== null) {
          selectTab(catButtons[nextIndex], true);
        }
      });
    });

    // 4. Hero Primary CTA: Start Interactive Demo
    const heroDemoBtn = document.getElementById('heroDemoBtn');
    if (heroDemoBtn) {
      heroDemoBtn.addEventListener('click', () => {
        earcons.click();
        const firstCmd = COMMAND_PRESETS[0];
        executeCommand(firstCmd);
        const simEl = document.getElementById('simulator');
        if (simEl) simEl.scrollIntoView({ behavior: 'smooth' });
      });
    }

    // 5. Soundboard Earcon buttons (Click + Enter/Space Keyboard Activation)
    document.querySelectorAll('.sound-card').forEach((card) => {
      function playSound() {
        const soundType = card.dataset.sound;
        if (soundType && earcons[soundType]) {
          earcons[soundType]();
          announce(`Played ${soundType} earcon audio cue`);
        }
      }
      card.addEventListener('click', playSound);
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          playSound();
        }
      });
    });

    // 6. Custom Voice Command Input Form
    const customCmdForm = document.getElementById('customCmdForm');
    const customCmdInput = document.getElementById('customCmdInput');
    if (customCmdForm && customCmdInput) {
      customCmdForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const query = customCmdInput.value.trim();
        if (!query) return;

        // Find nearest matching preset or synthesize dynamic response
        const match = COMMAND_PRESETS.find(c => query.toLowerCase().includes(c.text.toLowerCase())) || {
          category: 'custom',
          text: query,
          desc: "Executed custom spoken command on Windows PC",
          app: 'notepad',
          focusSelector: '#simNotepadContent',
          spoken: `RELAY heard: ${query}. Executed action via Windows UI Automation.`,
          steps: [
            { label: "Speech In", detail: `faster-whisper transcribed '${query}'` },
            { label: "Intent Match", detail: "Parsed intent parameters and verified permissions" },
            { label: "Execution", detail: "Injected action via Windows Automation APIs" },
            { label: "Verification", detail: "Confirmed UI state change" },
            { label: "Narration", detail: "Spoken feedback to user" }
          ]
        };

        executeCommand(match);
        customCmdInput.value = '';
      });
    }

    // 7. Theme Toggle & High Contrast Mode
    const themeBtn = document.getElementById('themeToggleBtn');
    if (themeBtn) {
      themeBtn.addEventListener('click', () => {
        earcons.click();
        const nextTheme = state.theme === 'dark' ? 'high-contrast' : state.theme === 'high-contrast' ? 'light' : 'dark';
        applyTheme(nextTheme);
      });
    }

    // 8. Font Size Scaler Buttons
    const fontPlusBtn = document.getElementById('fontPlusBtn');
    const fontMinusBtn = document.getElementById('fontMinusBtn');
    if (fontPlusBtn) {
      fontPlusBtn.addEventListener('click', () => {
        earcons.click();
        setFontScale(state.fontSize + 0.15);
      });
    }
    if (fontMinusBtn) {
      fontMinusBtn.addEventListener('click', () => {
        earcons.click();
        setFontScale(state.fontSize - 0.15);
      });
    }

    // 9. Sound & Speech Toggle
    const soundToggleBtn = document.getElementById('soundToggleBtn');
    if (soundToggleBtn) {
      soundToggleBtn.addEventListener('click', () => {
        state.soundEnabled = !state.soundEnabled;
        localStorage.setItem('relay_sound_enabled', state.soundEnabled);
        soundToggleBtn.setAttribute('aria-pressed', state.soundEnabled);
        soundToggleBtn.classList.toggle('active', state.soundEnabled);
        if (state.soundEnabled) earcons.listen();
        announce(`Sound earcons ${state.soundEnabled ? 'enabled' : 'disabled'}`);
      });
    }

    // 10. Global Keyboard Shortcuts
    window.addEventListener('keydown', (e) => {
      // Ctrl+Alt+Space: Trigger voice demo
      if (e.ctrlKey && e.altKey && e.code === 'Space') {
        e.preventDefault();
        const randCmd = COMMAND_PRESETS[Math.floor(Math.random() * COMMAND_PRESETS.length)];
        executeCommand(randCmd);
      }
      // Ctrl+Alt+Period: Stop talking
      if (e.ctrlKey && e.altKey && e.code === 'Period') {
        e.preventDefault();
        stopSpeaking();
        earcons.click();
        announce("Speech paused");
      }
      // Ctrl+Alt+Backspace: Emergency stop
      if (e.ctrlKey && e.altKey && e.code === 'Backspace') {
        e.preventDefault();
        stopSpeaking();
        earcons.halt();
        announce("Emergency stop triggered. Everything halted.", "assertive");
      }
      // Alt+H: High contrast toggle
      if (e.altKey && (e.key === 'h' || e.key === 'H')) {
        e.preventDefault();
        applyTheme(state.theme === 'high-contrast' ? 'dark' : 'high-contrast');
      }
    });

    // 11. Connect IPC if running
    setupIpcClient();

    // 12. Set initial desktop state
    setActiveApp('notepad');
  });

})();
