/**
 * RELAY — Minimalist Client Logic
 * Theme toggling (Dark/Light), interactive jumping logo balls, and smooth interactions
 */

(function () {
  'use strict';

  // --------------------------------------------------------------------------
  // 1. Audio Synthesis for Ball Jumps (Web Audio API)
  // --------------------------------------------------------------------------
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  let audioCtx = null;
  let audioEnabled = localStorage.getItem('relay_audio') !== 'off';

  const BALL_NOTES = {
    ballBlue: 329.63,   // E4
    ballYellow: 392.00, // G4
    ballGreen: 440.00,  // A4
    ballRed: 523.25     // C5
  };

  function playChime(freq = 440) {
    if (!audioEnabled) return;
    try {
      if (!audioCtx) {
        audioCtx = new AudioContext();
      }
      if (audioCtx.state === 'suspended') {
        audioCtx.resume();
      }
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, audioCtx.currentTime);

      gain.gain.setValueAtTime(0.08, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.25);

      osc.connect(gain);
      gain.connect(audioCtx.destination);

      osc.start();
      osc.stop(audioCtx.currentTime + 0.26);
    } catch (e) {
      // Audio autoplay restrictions or headless browsers
    }
  }

  // --------------------------------------------------------------------------
  // 2. Interactive Jumping Logo Balls
  // --------------------------------------------------------------------------
  const ballIds = ['ballBlue', 'ballYellow', 'ballGreen', 'ballRed'];

  function triggerBallJump(ballElement, freq) {
    if (!ballElement) return;
    ballElement.classList.remove('jumping');
    // Force reflow
    void ballElement.offsetWidth;
    ballElement.classList.add('jumping');
    playChime(freq);
    setTimeout(() => {
      ballElement.classList.remove('jumping');
    }, 600);
  }

  ballIds.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;

    el.addEventListener('mouseenter', () => {
      triggerBallJump(el, BALL_NOTES[id]);
    });

    el.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      triggerBallJump(el, BALL_NOTES[id]);
    });

    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        triggerBallJump(el, BALL_NOTES[id]);
      }
    });
  });

  // Wave jump when hovering the whole logo
  const logo = document.getElementById('logoInteractive');
  if (logo) {
    logo.addEventListener('click', (e) => {
      // Cascade jump all 4 balls sequentially
      ballIds.forEach((id, idx) => {
        setTimeout(() => {
          const el = document.getElementById(id);
          triggerBallJump(el, BALL_NOTES[id]);
        }, idx * 70);
      });
    });
  }

  // --------------------------------------------------------------------------
  // 3. Theme Toggle (Dark & Light Mode)
  // --------------------------------------------------------------------------
  const themeToggle = document.getElementById('themeToggle') || document.getElementById('themeToggleBtn');
  const storedTheme = localStorage.getItem('relay_theme');
  const systemPrefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;

  let currentTheme = storedTheme || (systemPrefersDark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', currentTheme);

  if (themeToggle) {
    themeToggle.addEventListener('click', () => {
      const themes = ['light', 'dark', 'high-contrast'];
      currentTheme = themes[(themes.indexOf(currentTheme) + 1) % themes.length];
      document.documentElement.setAttribute('data-theme', currentTheme);
      localStorage.setItem('relay_theme', currentTheme);
    });
  }

  // --------------------------------------------------------------------------
  // 4. Interactive Commands: Click to Copy
  // --------------------------------------------------------------------------
  const commandCards = document.querySelectorAll('.command-card');
  commandCards.forEach((card) => {
    card.addEventListener('click', () => {
      const voiceTextEl = card.querySelector('.cmd-voice');
      if (!voiceTextEl) return;
      const text = voiceTextEl.textContent.replace(/["']/g, '').trim();

      navigator.clipboard.writeText(text).then(() => {
        const catEl = card.querySelector('.cmd-category');
        if (catEl) {
          const original = catEl.textContent;
          catEl.textContent = '✓ Copied to clipboard!';
          catEl.style.color = '#00c853';
          setTimeout(() => {
            catEl.textContent = original;
            catEl.style.color = '';
          }, 1600);
        }
      }).catch(() => {});
    });
  });

  // --------------------------------------------------------------------------
  // 5. Active Navigation Spy on Scroll
  // --------------------------------------------------------------------------
  const sections = document.querySelectorAll('.screen-section');
  const navItems = document.querySelectorAll('.nav-menu .nav-item');

  function updateActiveNav() {
    let activeId = '';
    const scrollY = window.pageYOffset || document.documentElement.scrollTop;

    sections.forEach((sec) => {
      const top = sec.offsetTop - 120;
      const height = sec.offsetHeight;
      if (scrollY >= top && scrollY < top + height) {
        activeId = sec.getAttribute('id');
      }
    });

    navItems.forEach((link) => {
      link.classList.remove('active');
      if (activeId && link.getAttribute('href') === '#' + activeId) {
        link.classList.add('active');
      }
    });
  }

  window.addEventListener('scroll', updateActiveNav, { passive: true });
  updateActiveNav();

// --------------------------------------------------------------------------
// 6. LiveWorld Subsystem Client Logic (SerpApi & Grounded Evidence UI)
// --------------------------------------------------------------------------
  const evidenceTrigger = document.getElementById('evidenceTrigger');
  const evidenceDrawer = document.getElementById('evidenceDrawer');
  const closeDrawerBtn = document.getElementById('closeDrawerBtn');
  const disconnectDemoBtn = document.getElementById('disconnectDemoBtn');
  const disconnectBtnLabel = document.getElementById('disconnectBtnLabel');
  const liveworldPulse = document.getElementById('liveworldPulse');
  const liveworldStatusTag = document.getElementById('liveworldStatusTag');
  const liveworldOfflineBanner = document.getElementById('liveworldOfflineBanner');
  const openPlanBtn = document.getElementById('openPlanBtn');
  const evidenceDrawerBody = document.getElementById('evidenceDrawerBody');
  const transcriptSpeaker = document.getElementById('transcriptSpeaker');
  const mirrorTerminal = document.getElementById('mirrorTerminal');
  let currentActionTarget = '';
  let currentActionLabel = 'Open selected result';
  let drawerReturnFocus = null;
  let drawerBackground = [];

  function announce(message) {
    const announcer = document.getElementById('srAnnouncer');
    if (announcer) announcer.textContent = message;
  }

  const audioToggle = document.getElementById('soundToggleBtn');
  function updateAudioToggle() {
    if (!audioToggle) return;
    audioToggle.setAttribute('aria-pressed', String(audioEnabled));
    audioToggle.textContent = `Audio: ${audioEnabled ? 'ON' : 'OFF'}`;
  }
  if (audioToggle) audioToggle.addEventListener('click', () => {
    audioEnabled = !audioEnabled;
    localStorage.setItem('relay_audio', audioEnabled ? 'on' : 'off');
    updateAudioToggle();
  });
  updateAudioToggle();
  let textPercent = Math.max(80, Math.min(200, Number(localStorage.getItem('relay_text_size')) || 100));
  function updateTextSize() {
    document.documentElement.style.fontSize = `${16 * textPercent / 100}px`;
    const indicator = document.getElementById('fontSizeIndicator');
    if (indicator) indicator.textContent = `${textPercent}%`;
    for (const [id, disabled] of [['fontMinusBtn', textPercent <= 80], ['fontPlusBtn', textPercent >= 200]]) {
      const button = document.getElementById(id);
      if (button) button.disabled = disabled;
    }
    localStorage.setItem('relay_text_size', String(textPercent));
  }
  for (const [id, change] of [['fontMinusBtn', -10], ['fontPlusBtn', 10]]) {
    const button = document.getElementById(id);
    if (button) button.addEventListener('click', () => {
      textPercent = Math.max(80, Math.min(200, textPercent + change));
      updateTextSize();
    });
  }
  updateTextSize();
  document.querySelectorAll('.sound-card').forEach((card) => {
    const play = () => {
      if (!audioEnabled) return;
      try {
        if (!audioCtx) audioCtx = new AudioContext();
        if (audioCtx.state === 'suspended') audioCtx.resume();
        const start = audioCtx.currentTime;
        const tone = (frequency, offset, duration, endFrequency = frequency) => {
          const oscillator = audioCtx.createOscillator();
          const gain = audioCtx.createGain();
          oscillator.frequency.setValueAtTime(frequency, start + offset);
          oscillator.frequency.linearRampToValueAtTime(endFrequency, start + offset + duration);
          gain.gain.setValueAtTime(0.04, start + offset);
          gain.gain.exponentialRampToValueAtTime(0.001, start + offset + duration);
          oscillator.connect(gain);
          gain.connect(audioCtx.destination);
          oscillator.start(start + offset);
          oscillator.stop(start + offset + duration);
        };
        if (card.dataset.sound === 'listen') tone(440, 0, 0.3, 880);
        else if (card.dataset.sound === 'success') [523.25, 659.25, 783.99].forEach(frequency => tone(frequency, 0, 0.3));
        else if (card.dataset.sound === 'alert') [0, 0.18].forEach(offset => tone(360, offset, 0.12));
        else tone(280, 0, 0.38, 90);
      } catch (error) {
        announce('Audio cues are unavailable in this browser.');
      }
    };
    card.addEventListener('click', play);
    card.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); play(); }
    });
  });

  function applyLiveWorldStatus(connected) {
    isDisconnected = !connected;
    if (disconnectBtnLabel) {
      disconnectBtnLabel.textContent = connected ? 'Disconnect Live World' : 'Reconnect Live World';
    }
    if (liveworldPulse) liveworldPulse.classList.toggle('offline', !connected);
    if (liveworldStatusTag) {
      liveworldStatusTag.textContent = connected ? 'ONLINE' : 'OFFLINE';
      liveworldStatusTag.classList.toggle('offline', !connected);
    }
    if (liveworldOfflineBanner) liveworldOfflineBanner.classList.toggle('hidden', connected);
  }

  function appendMirrorEntry(kind, message) {
    if (!mirrorTerminal || !message) return;
    const entry = document.createElement('div');
    entry.className = `terminal-entry ${kind}`;
    entry.textContent = message;
    mirrorTerminal.appendChild(entry);
    mirrorTerminal.scrollTop = mirrorTerminal.scrollHeight;
  }

  function openEvidenceDrawer() {
    if (!evidenceDrawer) return;
    drawerReturnFocus = document.activeElement;
    drawerBackground = [];
    for (let branch = evidenceDrawer; branch && branch !== document.body; branch = branch.parentElement) {
      for (const sibling of branch.parentElement.children) {
        if (sibling === branch || sibling.id === 'srAnnouncer') continue;
        drawerBackground.push([sibling, sibling.inert]);
        sibling.inert = true;
      }
    }
    evidenceDrawer.inert = false;
    evidenceDrawer.classList.add('open');
    evidenceDrawer.setAttribute('aria-hidden', 'false');
    if (evidenceTrigger) evidenceTrigger.setAttribute('aria-expanded', 'true');
    if (closeDrawerBtn) closeDrawerBtn.focus();
  }

  function closeEvidenceDrawer() {
    if (!evidenceDrawer) return;
    evidenceDrawer.classList.remove('open');
    evidenceDrawer.setAttribute('aria-hidden', 'true');
    evidenceDrawer.inert = true;
    for (const [element, wasInert] of drawerBackground) element.inert = wasInert;
    drawerBackground = [];
    if (evidenceTrigger) evidenceTrigger.setAttribute('aria-expanded', 'false');
    if (drawerReturnFocus && typeof drawerReturnFocus.focus === 'function') drawerReturnFocus.focus();
  }

  if (evidenceTrigger && evidenceDrawer) {
    evidenceTrigger.addEventListener('click', () => {
      openEvidenceDrawer();
    });
  }

  if (closeDrawerBtn && evidenceDrawer) {
    closeDrawerBtn.addEventListener('click', () => {
      closeEvidenceDrawer();
    });
  }

  document.addEventListener('keydown', (event) => {
    if (!evidenceDrawer || evidenceDrawer.getAttribute('aria-hidden') === 'true') return;
    if (event.key === 'Escape') {
      event.preventDefault();
      closeEvidenceDrawer();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(evidenceDrawer.querySelectorAll('button, a[href], [tabindex]:not([tabindex="-1"])'));
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  let isDisconnected = false;
  if (disconnectDemoBtn) {
    disconnectDemoBtn.addEventListener('click', async () => {
      const cmd = isDisconnected ? 'reconnect_live_world' : 'disconnect_live_world';
      const params = new URLSearchParams(window.location.search);
      const token = params.get('token');

      if (token) {
        try {
          const response = await fetch(`/command?token=${token}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: cmd, args: {} })
          });
          const result = await response.json();
          applyLiveWorldStatus(Boolean(result.connected));
        } catch (error) {
          applyLiveWorldStatus(false);
        }
      } else {
        applyLiveWorldStatus(false);
      }
    });
  }

  if (openPlanBtn) {
    openPlanBtn.addEventListener('click', async () => {
      if (!currentActionTarget) return;
      const params = new URLSearchParams(window.location.search);
      const token = params.get('token');
      if (token) {
        try {
          const response = await fetch(`/command?token=${token}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: 'handle', args: { text: 'open selected result' } })
          });
          const result = await response.json();
          if (!response.ok || !result.ok) throw new Error('command failed');
          announce(`${currentActionLabel} opened in your browser.`);
        } catch (error) {
          announce('Relay could not open the selected result.');
        }
      } else {
        window.open(currentActionTarget, '_blank', 'noopener,noreferrer');
      }
    });
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value || '';
  }

  function formatEvidenceValue(item) {
    const bits = [];
    if (typeof item.price === 'number') bits.push(`₹${item.price.toLocaleString('en-IN')}`);
    if (typeof item.rating === 'number') bits.push(`${item.rating} ★`);
    if (item.reviewCount) bits.push(`${Number(item.reviewCount).toLocaleString('en-IN')} reviews`);
    if (item.departureTime) bits.push(item.departureTime);
    if (item.address) bits.push(item.address);
    return bits.join(' · ') || item.sourceName || item.engine;
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    })[ch]);
  }

  function safeWebUrl(value) {
    try {
      const url = new URL(value);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch (error) {
      return '';
    }
  }

  function renderEvidenceDrawer(items) {
    if (!evidenceDrawerBody) return;
    const evidence = Array.isArray(items) ? items : [];
    if (!evidence.length) {
      evidenceDrawerBody.innerHTML = '<div class="evidence-item-card"><div class="item-engine-badge">LIVE EVIDENCE</div><div class="item-title">No cited live evidence for this result.</div></div>';
      return;
    }
    evidenceDrawerBody.innerHTML = evidence.map((item) => {
      const title = escapeHtml(item.title || 'Untitled result');
      const engine = escapeHtml(String(item.engine || 'serpapi').replace(/_/g, ' ').toUpperCase());
      const val = escapeHtml(formatEvidenceValue(item));
      const snippet = escapeHtml(item.snippet || '');
      const url = safeWebUrl(item.url);
      const link = url ? `<a class="item-source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Open ${title}</a>` : '';
      return `<div class="evidence-item-card"><div class="item-engine-badge">${engine}</div><div class="item-title">${title}</div><div class="item-val-row">${val}</div><div class="item-snippet">${snippet}</div>${link}</div>`;
    }).join('');
  }

  function renderDecision(decision) {
    const rec = decision.recommendation || {};
    const flight = rec.flight || {};
    const stay = rec.stay || {};
    const dinner = rec.dinner || {};
    setText('resultLocation', rec.destination || 'LIVE RESULT');
    setText('resultBadge', rec.badge || 'Grounded result');
    const hasTripDetails = Boolean(flight.name || stay.name || dinner.name);
    setText('resultTitle', rec.title || '');
    setText('resultAnswer', decision.answer || '');
    document.getElementById('resultTitle').hidden = !rec.title;
    document.getElementById('resultAnswer').hidden = !decision.answer;
    for (const [id, present] of [
      ['flightResultRow', Boolean(rec.flight)],
      ['hotelResultRow', Boolean(rec.stay)],
      ['dinnerResultRow', Boolean(rec.dinner)],
      ['totalResultRow', Boolean(rec.flight && rec.stay)],
    ]) {
      document.getElementById(id).hidden = !present;
    }
    if (hasTripDetails) {
      setText('flightTitle', flight.name || 'No flight verified');
      setText('flightTimes', flight.time || '');
      setText('flightPrice', flight.price || '--');
      setText('hotelTitle', stay.name || 'No hotel verified');
      setText('hotelRating', stay.rating || '');
      setText('hotelPrice', stay.price || '--');
      setText('dinnerTitle', dinner.name || 'No dinner place verified');
      setText('dinnerDist', [dinner.rating, dinner.distance].filter(Boolean).join(' · '));
      setText('dinnerPrice', dinner.url ? 'Open' : '--');
      setText('totalPrice', rec.total_cost || '--');
      setText('savingsNote', rec.savings || 'Budget not fully verified');
    }

    const evidenceItems = Array.isArray(decision.evidence)
      ? decision.evidence
      : (decision.provenance && decision.provenance.evidence_items);
    const evidenceCount = Array.isArray(evidenceItems) ? evidenceItems.length : (decision.evidenceIds || []).length;
    setText('evidenceCountLabel', evidenceCount ? `Verified from ${evidenceCount} cited live results` : 'No cited live evidence');
    renderEvidenceDrawer(evidenceItems);

    currentActionTarget = safeWebUrl(decision.action && decision.action.target);
    currentActionLabel = decision.action && decision.action.label ? decision.action.label : 'Open selected result';
    if (openPlanBtn) {
      openPlanBtn.disabled = !currentActionTarget;
      openPlanBtn.querySelector('span').textContent = currentActionTarget ? `[ ${currentActionLabel} ]` : '[ No verified action ]';
    }
    announce(decision.answer || 'Live result updated.');
  }

  const params = new URLSearchParams(window.location.search);
  const token = params.get('token');
  setText('ipcPortLabel', `PORT ${location.port || '8765'}`);
  async function sendPanelCommand(text, button) {
    text = text.trim();
    if (!text) return;
    if (!token) { announce('Connect to the Relay panel before sending a command.'); return; }
    if (button) button.disabled = true;
    try {
      const response = await fetch(`/command?token=${encodeURIComponent(token)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({command: 'handle', args: {text}}),
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || 'The command did not complete.');
      appendMirrorEntry('voice', `[Request] ${text}`);
      announce(Array.isArray(result.results) && result.results.length ? result.results.join(' ') : 'Request sent to Relay.');
    } catch (error) {
      announce(`Unable to complete the request: ${error.message}`);
      appendMirrorEntry('error', `Unable to complete the request: ${error.message}`);
    } finally {
      if (button) button.disabled = false;
    }
  }
  for (const [formId, inputId] of [['liveCommandForm', 'liveCommandInput'], ['customCmdForm', 'customCmdInput']]) {
    const form = document.getElementById(formId);
    if (form) form.addEventListener('submit', (event) => {
      event.preventDefault();
      sendPanelCommand(document.getElementById(inputId).value, form.querySelector('button'));
    });
  }
  const mirrorInput = document.getElementById('mirrorCmdInput');
  const mirrorSend = document.getElementById('mirrorSendBtn');
  if (mirrorSend && mirrorInput) {
    mirrorSend.addEventListener('click', () => sendPanelCommand(mirrorInput.value, mirrorSend));
    mirrorInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); sendPanelCommand(mirrorInput.value, mirrorSend); }
    });
  }
  const examples = {
    screen: ['read the page', "what's on my screen"],
    everyday: ['what time is it', 'battery status'],
    hardware: ['where is sound going'],
    safety: ['emergency stop'],
    ai: ['Compare the latest AI coding agents'],
  };
  const categoryButtons = Array.from(document.querySelectorAll('.cat-btn'));
  const commandGrid = document.getElementById('commandCardsGrid');
  function chooseCategory(button) {
    for (const tab of categoryButtons) {
      const selected = tab === button;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      tab.classList.toggle('active', selected);
    }
    if (!commandGrid) return;
    commandGrid.replaceChildren();
    for (const command of examples[button.dataset.category] || []) {
      const action = document.createElement('button');
      action.type = 'button';
      action.className = 'btn-sharp-secondary';
      action.textContent = command;
      action.addEventListener('click', () => sendPanelCommand(command, action));
      commandGrid.appendChild(action);
    }
  }
  categoryButtons.forEach((button, index) => {
    button.addEventListener('click', () => chooseCategory(button));
    button.addEventListener('keydown', (event) => {
      const direction = {ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1}[event.key];
      if (direction || event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? categoryButtons.length - 1 : (index + direction + categoryButtons.length) % categoryButtons.length;
        chooseCategory(categoryButtons[next]);
        categoryButtons[next].focus();
      }
    });
  });
  if (categoryButtons.length) chooseCategory(categoryButtons[0]);
  const demoButton = document.getElementById('heroDemoBtn');
  if (demoButton) {
    demoButton.querySelector('span').textContent = 'Check the time';
    demoButton.addEventListener('click', () => sendPanelCommand('what time is it', demoButton));
  }
  if (token) {
    fetch(`/command?token=${token}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: 'get_live_world_status', args: {} })
    })
      .then((response) => response.json())
      .then((result) => applyLiveWorldStatus(Boolean(result.connected)))
      .catch(() => applyLiveWorldStatus(false));
    try {
      const sse = new EventSource(`/events?token=${token}`);
      let panelDisconnected = false;
      sse.onopen = () => {
        setText('ipcConnBadge', 'Connected');
        if (panelDisconnected) announce('The Relay panel connection is restored.');
        panelDisconnected = false;
      };
      sse.onerror = () => {
        setText('ipcConnBadge', 'Reconnecting');
        if (!panelDisconnected) announce('The Relay panel connection was interrupted. Reconnecting.');
        panelDisconnected = true;
      };
      sse.onmessage = function (e) {
        try {
          const payload = JSON.parse(e.data);
          const type = payload.type;
          const data = payload.data;

          if (type === 'voice.heard') {
            if (transcriptSpeaker) transcriptSpeaker.textContent = 'User:';
            setText('transcriptText', `"${data.text || ''}"`);
            appendMirrorEntry('voice', `[User] ${data.text || ''}`);
          } else if (type === 'narration.say') {
            if (transcriptSpeaker) transcriptSpeaker.textContent = 'Relay:';
            setText('transcriptText', `"${data.text || ''}"`);
            appendMirrorEntry('narration', `[Relay] ${data.text || ''}`);
          } else if (type === 'perception.change') {
            const context = data.summary || data.foreground_title || data.foreground_app || 'Screen changed';
            appendMirrorEntry('perception', `[Screen] ${context}`);
          } else if (type === 'liveworld.trace') {
            const stepStream = document.getElementById('actionTraceStream');
            if (stepStream && data.data) {
              const stepDiv = document.createElement('div');
              stepDiv.className = 'trace-step done';
              const icon = document.createElement('span');
              icon.className = 'step-icon';
              icon.setAttribute('aria-hidden', 'true');
              icon.textContent = '✓';
              stepDiv.appendChild(icon);
              stepDiv.appendChild(document.createTextNode(` [${data.stage}] ${String(data.type || '').replaceAll('_', ' ')}`));
              stepStream.appendChild(stepDiv);
            }
          } else if (type === 'liveworld.decision') {
            const transcript = document.getElementById('transcriptText');
            if (transcript && data.answer) {
              transcript.textContent = `"${data.answer}"`;
            }
            renderDecision(data);
          } else if (type === 'liveworld.telemetry') {
            const telemetry = document.getElementById('telemetryBar');
            if (telemetry) {
              telemetry.innerHTML = `<span class="telemetry-item">${data.totalSearches || 0} engines</span> · <span class="telemetry-item">${data.candidateCount || 0} candidates</span> · <span class="telemetry-item">${((data.totalLatencyMs || 0) / 1000).toFixed(1)}s total</span>`;
            }
          } else if (type === 'liveworld.status') {
            applyLiveWorldStatus(Boolean(data.connected));
          }
        } catch (err) {}
      };
    } catch (e) {}
  } else {
    applyLiveWorldStatus(false);
  }
})();
