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

  const BALL_NOTES = {
    ballBlue: 329.63,   // E4
    ballYellow: 392.00, // G4
    ballGreen: 440.00,  // A4
    ballRed: 523.25     // C5
  };

  function playChime(freq = 440) {
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
  const themeToggle = document.getElementById('themeToggle');
  const storedTheme = localStorage.getItem('relay_theme');
  const systemPrefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;

  let currentTheme = storedTheme || (systemPrefersDark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', currentTheme);

  if (themeToggle) {
    themeToggle.addEventListener('click', () => {
      currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
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

})();


// --------------------------------------------------------------------------
// 6. LiveWorld Subsystem Client Logic (SerpApi & Grounded Evidence UI)
// --------------------------------------------------------------------------
(function () {
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
  let currentActionTarget = '';

  // Toggle Evidence Drawer
  if (evidenceTrigger && evidenceDrawer) {
    evidenceTrigger.addEventListener('click', () => {
      evidenceDrawer.classList.add('open');
    });
  }

  if (closeDrawerBtn && evidenceDrawer) {
    closeDrawerBtn.addEventListener('click', () => {
      evidenceDrawer.classList.remove('open');
    });
  }

  // Handle Developer Disconnect / Reconnect Demo Toggle
  let isDisconnected = false;
  if (disconnectDemoBtn) {
    disconnectDemoBtn.addEventListener('click', () => {
      isDisconnected = !isDisconnected;
      const cmd = isDisconnected ? 'disconnect_live_world' : 'reconnect_live_world';

      // Send IPC request if running inside panel session
      const params = new URLSearchParams(window.location.search);
      const token = params.get('token');

      if (token) {
        fetch(`/command?token=${token}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: cmd, args: {} })
        }).catch(() => {});
      }

      // Local UI update
      if (isDisconnected) {
        if (disconnectBtnLabel) disconnectBtnLabel.textContent = 'Reconnect Live World';
        if (liveworldPulse) liveworldPulse.classList.add('offline');
        if (liveworldStatusTag) {
          liveworldStatusTag.textContent = 'OFFLINE';
          liveworldStatusTag.classList.add('offline');
        }
        if (liveworldOfflineBanner) liveworldOfflineBanner.classList.remove('hidden');
      } else {
        if (disconnectBtnLabel) disconnectBtnLabel.textContent = 'Disconnect Live World';
        if (liveworldPulse) liveworldPulse.classList.remove('offline');
        if (liveworldStatusTag) {
          liveworldStatusTag.textContent = 'ONLINE';
          liveworldStatusTag.classList.remove('offline');
        }
        if (liveworldOfflineBanner) liveworldOfflineBanner.classList.add('hidden');
      }
    });
  }

  // Open Plan Action Button
  if (openPlanBtn) {
    openPlanBtn.addEventListener('click', () => {
      if (currentActionTarget) {
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
      const url = item.url || '';
      const link = url ? `<a class="item-source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Open source</a>` : '';
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

    const evidenceItems = decision.provenance && decision.provenance.evidence_items;
    const evidenceCount = Array.isArray(evidenceItems) ? evidenceItems.length : (decision.evidenceIds || []).length;
    setText('evidenceCountLabel', evidenceCount ? `Verified from ${evidenceCount} cited live results` : 'No cited live evidence');
    renderEvidenceDrawer(evidenceItems);

    currentActionTarget = decision.action && decision.action.target ? decision.action.target : '';
    if (openPlanBtn) {
      openPlanBtn.disabled = !currentActionTarget;
      openPlanBtn.style.opacity = currentActionTarget ? '' : '0.5';
    }
  }

  // SSE Real-time Event Mirroring
  const params = new URLSearchParams(window.location.search);
  const token = params.get('token');
  if (token) {
    try {
      const sse = new EventSource(`/events?token=${token}`);
      sse.onmessage = function (e) {
        try {
          const payload = JSON.parse(e.data);
          const type = payload.type;
          const data = payload.data;

          if (type === 'liveworld.trace') {
            const stepStream = document.getElementById('actionTraceStream');
            if (stepStream && data.data) {
              const stepDiv = document.createElement('div');
              stepDiv.className = 'trace-step done';
              stepDiv.innerHTML = `<span class="step-icon">✓</span> [${data.stage}] ${data.type.replace('_', ' ')}`;
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
            const connected = Boolean(data.connected);
            isDisconnected = !connected;
            if (disconnectBtnLabel) disconnectBtnLabel.textContent = connected ? 'Disconnect Live World' : 'Reconnect Live World';
            if (liveworldPulse) liveworldPulse.classList.toggle('offline', !connected);
            if (liveworldStatusTag) {
              liveworldStatusTag.textContent = connected ? 'ONLINE' : 'OFFLINE';
              liveworldStatusTag.classList.toggle('offline', !connected);
            }
            if (liveworldOfflineBanner) liveworldOfflineBanner.classList.toggle('hidden', connected);
          }
        } catch (err) {}
      };
    } catch (e) {}
  }
})();
