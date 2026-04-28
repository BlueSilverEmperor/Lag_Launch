/* ══════════════════════════════════════════════════════════════
   DAP — app.js  |  Full SPA Application Logic
   ══════════════════════════════════════════════════════════════ */

const API = '';   // same-origin — Flask serves both

/* ─── Animated Background ────────────────────────────────────── */
(function initBackground() {
  const canvas = document.getElementById('bg-canvas');
  const ctx    = canvas.getContext('2d');
  let W, H, particles = [];

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function spawnParticle() {
    return {
      x:  Math.random() * W,
      y:  Math.random() * H,
      vx: (Math.random() - 0.5) * 0.3,
      vy: (Math.random() - 0.5) * 0.3,
      r:  Math.random() * 1.5 + 0.3,
      a:  Math.random() * 0.5 + 0.1,
      color: Math.random() > 0.6 ? '#00d4ff' : '#7b5ea7',
    };
  }

  function initParticles() {
    particles = Array.from({ length: 120 }, spawnParticle);
  }

  function drawGrid() {
    ctx.strokeStyle = 'rgba(0, 212, 255, 0.025)';
    ctx.lineWidth   = 1;
    const step = 60;
    for (let x = 0; x < W; x += step) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (let y = 0; y < H; y += step) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }
  }

  function drawConnections() {
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 100) {
          ctx.strokeStyle = `rgba(0, 212, 255, ${0.06 * (1 - dist / 100)})`;
          ctx.lineWidth   = 0.5;
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.stroke();
        }
      }
    }
  }

  function animate() {
    ctx.clearRect(0, 0, W, H);
    drawGrid();
    drawConnections();

    ctx.save();
    particles.forEach(p => {
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0 || p.x > W) p.vx *= -1;
      if (p.y < 0 || p.y > H) p.vy *= -1;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = p.color;
      ctx.globalAlpha = p.a * 0.4;
      ctx.fill();
    });
    ctx.restore();

    requestAnimationFrame(animate);
  }

  window.addEventListener('resize', () => { resize(); });
  resize();
  initParticles();
  animate();
})();


/* ─── Toast ──────────────────────────────────────────────────── */
const Toast = {
  show(msg, type = 'info', duration = 4000) {
    const c   = document.getElementById('toast-container');
    const el  = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `<div class="toast-dot"></div><span>${msg}</span>`;
    c.appendChild(el);
    setTimeout(() => {
      el.style.transition = 'all 0.3s ease';
      el.style.opacity    = '0';
      el.style.transform  = 'translateX(30px)';
      setTimeout(() => el.remove(), 300);
    }, duration);
  },
};


/* ─── Router ─────────────────────────────────────────────────── */
const Router = {
  currentPage: 'dashboard',

  navigate(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

    const pageEl = document.getElementById(`page-${page}`);
    const navEl  = document.getElementById(`nav-${page}`);
    if (pageEl) pageEl.classList.add('active');
    if (navEl)  navEl.classList.add('active');

    this.currentPage = page;
    if (page === 'dashboard')  App.refreshAll();
    if (page === 'reports')    App.loadReports();
    if (page === 'autoingest') App.loadDiscoveryResults();
  },

  init() {
    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.addEventListener('click', () => this.navigate(btn.dataset.page));
    });
  },
};


/* ─── Donut Chart ────────────────────────────────────────────── */
const Donut = {
  draw(canvasId, pct, color = '#00d4ff') {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const cx  = canvas.width  / 2;
    const cy  = canvas.height / 2;
    const R   = 64;
    const W   = 12;
    const startAngle = -Math.PI / 2;
    const endAngle   = startAngle + (pct / 100) * (Math.PI * 2);

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Track
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth   = W;
    ctx.stroke();

    if (pct > 0) {
      // Gradient fill
      const grad = ctx.createLinearGradient(cx - R, cy, cx + R, cy);
      grad.addColorStop(0, color);
      grad.addColorStop(1, '#7b5ea7');

      ctx.beginPath();
      ctx.arc(cx, cy, R, startAngle, endAngle);
      ctx.strokeStyle = grad;
      ctx.lineWidth   = W;
      ctx.lineCap     = 'round';
      ctx.stroke();

      // Glow
      ctx.beginPath();
      ctx.arc(cx, cy, R, startAngle, endAngle);
      ctx.strokeStyle = color;
      ctx.lineWidth   = W / 2;
      ctx.globalAlpha = 0.25;
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
  },

  animate(canvasId, targetPct, color, labelId) {
    let current = 0;
    const step  = targetPct / 40;
    const label = document.getElementById(labelId);
    const tick  = () => {
      if (current >= targetPct) { current = targetPct; }
      this.draw(canvasId, current, color);
      if (label) label.textContent = `${current.toFixed(1)}%`;
      if (current < targetPct) { current += step; requestAnimationFrame(tick); }
    };
    tick();
  },
};


/* ─── SSE Job Stream ─────────────────────────────────────────── */
function streamJob(jobId, handlers) {
  const es = new EventSource(`${API}/api/stream/${jobId}`);
  es.onmessage = e => {
    const ev = JSON.parse(e.data);
    handlers[ev.type]?.(ev);
    handlers['*']?.(ev);
  };
  es.onerror = () => { es.close(); handlers['close']?.(); };
  return es;
}


/* ─── Log helpers ────────────────────────────────────────────── */
function appendLog(containerId, msg, type = 'info') {
  const el = document.getElementById(containerId);
  if (!el) return;

  // Clear placeholder on first entry
  const ph = el.querySelector('.log-placeholder');
  if (ph) ph.remove();

  const line      = document.createElement('div');
  line.className  = `log-line ${type}`;
  const now       = new Date().toLocaleTimeString('en-US', { hour12: false });
  line.textContent = `[${now}] ${msg}`;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

function clearLog(containerId) {
  const el = document.getElementById(containerId);
  if (el) el.innerHTML = '<div class="log-placeholder">Starting…</div>';
}


/* ─── Flag helpers ───────────────────────────────────────────── */
function flagChip(status) {
  const map = {
    'CONFIRMED INFRINGEMENT': ['flag-confirmed', '🚨 Confirmed'],
    'SUSPECTED INFRINGEMENT': ['flag-confirmed', '🛡️ Suspected'],
    'SIMILAR CONTENT':        ['flag-suspected', '⚠️ Similar'],
    'SUSPECTED COPY':          ['flag-suspected', '⚠️ Suspected'],
    'CLEAR':                   ['flag-clear',     '✅ Clear'],
  };
  const [cls, label] = map[status] || ['flag-clear', status];
  return `<span class="flag-chip ${cls}">${label}</span>`;
}

function dhChip(d, sim) {
  if (sim !== undefined && sim !== null) {
      const cls = sim >= 0.9 ? 'dh-low' : sim >= 0.8 ? 'dh-mid' : 'dh-high';
      return `<span class="dh-chip ${cls}" title="Cosine Similarity">${(sim * 100).toFixed(0)}%</span>`;
  }
  if (d === null || d === undefined || d > 250) return `<span class="dh-chip dh-high">—</span>`;
  const cls = d < 4 ? 'dh-low' : d < 8 ? 'dh-mid' : 'dh-high';
  return `<span class="dh-chip ${cls}">${d}</span>`;
}

function scoreColor(pct) {
  if (pct >= 80) return '#ff4757';
  if (pct >= 40) return '#ffa502';
  return '#2ed573';
}

function timeAgo(iso) {
  const diff = (Date.now() - new Date(iso)) / 1000;
  if (diff < 60)   return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
  return `${Math.floor(diff/3600)}h ago`;
}


/* ─── Main App ───────────────────────────────────────────────── */
const App = {

  // ── Dashboard ─────────────────────────────────────────────────

  async refreshDB() {
    try {
      const { clips } = await fetch(`${API}/api/db`).then(r => r.json());
      const el = document.getElementById('db-clips-list');
      if (!clips.length) {
        el.innerHTML = '<div class="empty-state">No clips ingested yet.</div>';
        return;
      }
      el.innerHTML = clips.map(c => `
        <div class="clip-row">
          <div class="clip-name">${c.name}</div>
          <div class="clip-frames">${c.frames} frames</div>
        </div>
      `).join('');
    } catch {}
  },

  async refreshStatus() {
    try {
      const ai = await fetch(`${API}/api/ai_status`).then(r => r.json());
      
      // 1. Gemini
      const gDot = document.getElementById('gemini-dot');
      const gLab = document.getElementById('gemini-label');
      if (gDot && gLab) {
        if (ai.gemini === 'ready') {
          gDot.classList.add('active');
          gLab.textContent = 'Gemini 1.5 Online';
        } else {
          gDot.classList.remove('active');
          gLab.textContent = 'Gemini Local Fallback';
        }
      }

      // 2. YOLO
      const yDot = document.getElementById('yolo-dot');
      const yLab = document.getElementById('yolo-label');
      if (yDot && yLab) {
        if (ai.yolo === 'ready') {
          yDot.classList.add('active');
          yLab.textContent = 'YOLOv8 Precise';
        } else {
          yDot.classList.remove('active');
          yLab.textContent = 'YOLOv8 Unavailable';
        }
      }

      // 3. Jobs Status (already fetched in the 'ai' call above)
      const active = ai.active_jobs || 0;
      const jDot = document.getElementById('jobs-count-dot');
      const jLab = document.getElementById('v-jobs-header');
      if (jDot) {
        if (active > 0) jDot.classList.add('active');
        else jDot.classList.remove('active');
      }
      if (jLab) jLab.textContent = `${active} Jobs`;

      // 4. Update recent jobs list if we are on dashboard
      if (Router.currentPage === 'dashboard') {
          this.renderJobsList(ai.recent_jobs || []);
      }

    } catch (e) { console.warn("Status fail", e); }
  },

  renderJobsList(jobs) {
    const el = document.getElementById('recent-jobs-list');
    if (!el) return;
    if (!jobs.length) {
      el.innerHTML = '<div class="empty-state">No jobs run yet.</div>';
      return;
    }
    el.innerHTML = jobs.slice(0, 12).map(j => `
      <div class="job-row">
        <span class="job-type">${j.type}</span>
        <span class="job-name">${j.id.slice(0, 8)}…</span>
        <span class="job-status ${j.status}">${j.status}</span>
        <span class="job-time">${timeAgo(j.created_at)}</span>
      </div>
    `).join('');
  },

  async refreshStats() {
    try {
      const s = await fetch(`${API}/api/stats`).then(r => r.json());
      const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val !== undefined ? val : '—';
      };
      setVal('v-clips',   s.clips);
      setVal('v-frames',  s.frames);
      setVal('v-reports', s.reports);
      setVal('v-jobs',    s.jobs);
    } catch (e) { console.warn("Stats fail", e); }
  },

  async refreshAll() {
    await Promise.all([
      this.refreshStatus(),
      this.refreshStats(), 
      this.refreshDB(), 
      this.updateTargetClips(),
      this.loadDiscoveryResults()
    ]);
    const badge = document.getElementById('badge-reports');
    const count = document.getElementById('v-reports').textContent;
    badge.textContent = count === '—' ? '' : count;
  },

  async clearDB() {
    if (!confirm('Clear the entire hash database? This cannot be undone.')) return;
    await fetch(`${API}/api/db`, { method: 'DELETE' });
    Toast.show('Hash database cleared.', 'info');
    this.refreshAll();
  },


  // ── Ingest ────────────────────────────────────────────────────

  async startIngest() {
    const dir       = document.getElementById('ingest-dir').value.trim();
    const interval  = parseFloat(document.getElementById('ingest-interval').value);
    const overwrite = document.getElementById('ingest-overwrite').checked;
    const proactive = document.getElementById('ingest-proactive').checked;

    if (!dir) { Toast.show('Please enter a clips directory path.', 'error'); return; }

    const btn = document.getElementById('btn-ingest');
    btn.disabled = true;
    btn.textContent = 'Ingesting…';
    clearLog('ingest-log');

    const pw  = document.getElementById('ingest-progress-wrap');
    const pb  = document.getElementById('ingest-progress-bar');
    const pl  = document.getElementById('ingest-progress-label');
    pw.style.display = 'flex';
    pb.style.width   = '0%';
    pl.textContent   = '0%';

    try {
      const { job_id } = await fetch(`${API}/api/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: dir, interval, overwrite, proactive_search: proactive }),
      }).then(r => r.json());

      let total = 1;

      streamJob(job_id, {
        start:    ev => { total = ev.total; appendLog('ingest-log', ev.message, 'phase'); },
        info:     ev => { appendLog('ingest-log', ev.message, 'info'); },
        hashing:  ev => { appendLog('ingest-log', ev.message, 'info'); },
        progress: ev => {
          const pct = Math.round((ev.index / total) * 100);
          pb.style.width  = `${pct}%`;
          pl.textContent  = `${pct}%`;
          const t = ev.skipped ? 'warning' : 'success';
          appendLog('ingest-log', ev.message, t);
        },
        discovered: ev => {
          appendLog('ingest-log', ev.message, ev.item.risk_level === 'high' ? 'error' : 'success');
        },
        warning:  ev => appendLog('ingest-log', ev.message, 'warning'),
        error:    ev => {
          appendLog('ingest-log', '✗ ' + ev.message, 'error');
          Toast.show(ev.message, 'error');
          btn.disabled = false;
          btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2"/><polyline points="8,12 12,8 16,12"/><line x1="12" y1="8" x2="12" y2="20"/></svg> Start Ingestion';
        },
        done: ev => {
          pb.style.width  = '100%';
          pl.textContent  = '100%';
          appendLog('ingest-log', `✓ ${ev.message}`, 'done');
          Toast.show(`Ingestion complete — ${ev.result.ingested} clip(s) processed.`, 'success');
          btn.disabled = false;
          btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2"/><polyline points="8,12 12,8 16,12"/><line x1="12" y1="8" x2="12" y2="20"/></svg> Start Ingestion';
          this.refreshAll();
        },
      });
    } catch (e) {
      Toast.show('Failed to start ingestion job.', 'error');
      btn.disabled = false;
      btn.textContent = 'Start Ingestion';
    }
  },


  // ── Scan ──────────────────────────────────────────────────────

  async startScan() {
    const path      = document.getElementById('scan-path').value.trim();
    const threshold = parseInt(document.getElementById('scan-threshold').value);
    const interval  = parseFloat(document.getElementById('scan-interval').value);
    const run_yolo  = document.getElementById('scan-yolo').checked;
    const target_clip = document.getElementById('scan-target').value;

    if (!path) { Toast.show('Please enter a suspect video path.', 'error'); return; }

    const btn = document.getElementById('btn-scan');
    btn.disabled = true;
    btn.textContent = 'Scanning…';
    clearLog('scan-log');

    // Reset phase badges
    ['phase-1','phase-2','phase-3','phase-4'].forEach(id => {
      const el = document.getElementById(id);
      el.className = 'phase-badge';
    });

    // Hide previous results
    document.getElementById('scan-results').style.display = 'none';

    try {
      const { job_id } = await fetch(`${API}/api/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_path: path, threshold, interval, run_yolo, target_clip }),
      }).then(r => r.json());

      streamJob(job_id, {
        start:   ev => appendLog('scan-log', ev.message, 'phase'),
        phase:   ev => {
          appendLog('scan-log', ev.message, 'phase');
          this._activatePhase(ev.phase);
        },
        hashed:          ev => appendLog('scan-log', ev.message, 'info'),
        detection_done:  ev => {
          appendLog('scan-log', ev.message, 'success');
          this._donePhase(2);
        },
        compliance_done: ev => {
          const type = ev.status === 'AUTHORIZED' ? 'success' : 'error';
          appendLog('scan-log', `AI Policy Analysis: ${ev.status}`, 'phase');
          appendLog('scan-log', `Reason: ${ev.reason}`, type);
          this._donePhase(1);
        },
        warning:   ev => appendLog('scan-log', ev.message, 'warning'),
        yolo_frame: ev => {
          const icon = ev.logo ? '🚨' : '✓';
          appendLog('scan-log', `${icon} YOLO @ ${ev.timestamp.toFixed(1)}s — ${ev.message.split('—')[1]?.trim() || ''}`, 'yolo');
        },
        error: ev => {
          appendLog('scan-log', '✗ ' + ev.message, 'error');
          Toast.show(ev.message, 'error');
          btn.disabled = false; btn.textContent = 'Start Scan';
        },
        done: ev => {
          this._donePhase(3);
          this._donePhase(4);
          appendLog('scan-log', `✓ ${ev.message}`, 'done');
          Toast.show('Scan complete!', 'success');
          btn.disabled = false;
          btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> Start Scan';
          this._renderResults(ev.result);
          this.refreshAll();
        },
      });
    } catch (e) {
      Toast.show('Failed to start scan job.', 'error');
      btn.disabled = false; btn.textContent = 'Start Scan';
    }
  },

  _activatePhase(n) {
    const el = document.getElementById(`phase-${n}`);
    if (el) el.className = 'phase-badge active';
  },
  _donePhase(n) {
    const el = document.getElementById(`phase-${n}`);
    if (el) el.className = 'phase-badge done';
  },

  _renderResults(data) {
    const wrap = document.getElementById('scan-results');
    wrap.style.display = 'block';

    const pct   = data.similarity_percentage;
    const color = scoreColor(pct);

    // Verdict
    document.getElementById('verdict-text').textContent = data.verdict;
    
    let complianceHtml = '';
    if (data.compliance_status) {
        const cls = data.compliance_status === 'AUTHORIZED' ? 'flag-clear' : 'flag-confirmed';
        complianceHtml = `
            <div class="compliance-card mt-3">
                <div class="comp-head">
                    <span class="flag-chip ${cls}">AI: ${data.compliance_status}</span>
                    <span class="comp-pub">${data.publisher || 'Unknown Publisher'}</span>
                </div>
                <div class="comp-reason">${data.compliance_reason || ''}</div>
                ${data.topics ? `<div class="comp-topics">${data.topics.map(t => `<span>#${t}</span>`).join(' ')}</div>` : ''}
            </div>
        `;
    }

    document.getElementById('verdict-meta').innerHTML = `
      <div class="verdict-chips">
        <span class="verdict-chip">${data.matched_frames} / ${data.total_frames_checked} frames matched</span>
        <span class="verdict-chip">${data.logo_confirmations} logo confirmation(s)</span>
      </div>
      ${complianceHtml}
    `;

    // Verdict card border
    const vc = document.getElementById('verdict-card');
    vc.style.borderColor = color + '50';

    // Donut
    document.getElementById('donut-pct').textContent = '0%';
    Donut.animate('donut-chart', pct, color, 'donut-pct');

    // Frame table
    const tbody = document.getElementById('frame-tbody');
    tbody.innerHTML = data.frames.map(f => {
      const rowCls = f.flag_status === 'CONFIRMED INFRINGEMENT' ? 'row-confirmed' :
                     f.is_match ? 'row-match' : '';
      const logo   = f.logo_detected
        ? `<span class="flag-chip flag-confirmed">YES ${f.logo_confidence ? (f.logo_confidence*100).toFixed(0)+'%' : ''}</span>`
        : `<span style="color:var(--text-dim)">—</span>`;

      return `
        <tr class="${rowCls}">
          <td>${f.suspect_time_fmt}</td>
          <td>${dhChip(f.hamming_distance, f.similarity_score)}</td>
          <td>${f.is_match ? '✓' : '—'}</td>
          <td>${f.matched_clip || '—'}</td>
          <td>${logo}</td>
          <td>${flagChip(f.flag_status)}</td>
        </tr>
      `;
    }).join('');
  },


  // ── Auto Ingest ────────────────────────────────────────────────
  async startAutoIngest() {
    const topic = document.getElementById('ai-topic').value.trim();
    const auto_scan = document.getElementById('ai-autoscan').checked;

    if (!topic) { Toast.show('Please enter a search topic.', 'error'); return; }

    const btn = document.getElementById('btn-autoingest');
    btn.disabled = true;
    btn.textContent = 'Discovering…';
    clearLog('ai-log');

    document.getElementById('ai-results').style.display = 'none';
    const tbody = document.getElementById('ai-tbody');
    tbody.innerHTML = '';

    try {
      const { job_id } = await fetch(`${API}/api/auto_ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, auto_scan }),
      }).then(r => r.json());

      streamJob(job_id, {
        start:       ev => appendLog('ai-log', ev.message, 'phase'),
        phase:       ev => appendLog('ai-log', ev.message, 'phase'),
        info:        ev => appendLog('ai-log', ev.message, 'info'),
        warning:     ev => appendLog('ai-log', ev.message, 'warning'),
        discovered:  ev => {
          appendLog('ai-log', ev.message, ev.item.risk_level === 'high' ? 'error' : 'success');
          
          // Add to table live
          const riskCls = ev.item.risk_level === 'high' ? 'dh-high' : ev.item.risk_level === 'low' ? 'dh-low' : 'dh-mid';
          const rRow = document.createElement('tr');
          rRow.innerHTML = `
            <td>${ev.item.platform}</td>
            <td>${ev.item.uploader}</td>
            <td style="max-width: 250px; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
              ${ev.item.title}
            </td>
            <td><span class="dh-chip ${riskCls}">${ev.item.risk_level.toUpperCase()}</span></td>
            <td><a href="${ev.item.url}" target="_blank" style="color:var(--accent)">Link</a></td>
          `;
          tbody.appendChild(rRow);
          document.getElementById('ai-results').style.display = 'block';
        },
        error: ev => {
          appendLog('ai-log', '✗ ' + ev.message, 'error');
          Toast.show(ev.message, 'error');
          btn.disabled = false; btn.textContent = 'Start Discovery';
        },
        done: ev => {
          appendLog('ai-log', `✓ ${ev.message}`, 'done');
          Toast.show('Discovery complete!', 'success');
          btn.disabled = false;
          btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /><circle cx="12" cy="12" r="3" /></svg> Start Discovery';
          this.refreshAll();
        },
      });
    } catch (e) {
      Toast.show('Failed to start auto discovery job.', 'error');
      btn.disabled = false; btn.textContent = 'Start Discovery';
    }
  },

  async loadDiscoveryResults() {
    const tbody = document.getElementById('ai-tbody');
    try {
      const results = await fetch(`${API}/api/discovery/results`).then(r => r.json());
      if (results.length > 0) {
          document.getElementById('ai-results').style.display = 'block';
          
          // Group by source_clip
          const grouped = results.reduce((acc, item) => {
              const src = item.source_clip || "Manual / Legacy Scan";
              if (!acc[src]) acc[src] = [];
              acc[src].push(item);
              return acc;
          }, {});

          let finalHtml = '';
          for (const [source, items] of Object.entries(grouped)) {
              // Group Header
              finalHtml += `
                <tr class="group-header">
                  <td colspan="5" style="background: rgba(255,255,255,0.03); font-weight: 600; padding: 12px; border-bottom: 1px solid var(--border); color: var(--accent);">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" style="vertical-align: middle; margin-right: 6px;">
                      <polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
                    </svg>
                    Source Clip: ${source}
                  </td>
                </tr>
              `;
              // Items
              finalHtml += items.map(item => {
                  const riskCls = item.risk_level === 'high' ? 'dh-high' : item.risk_level === 'low' ? 'dh-low' : 'dh-mid';
                  return `
                    <tr>
                      <td>${item.platform}</td>
                      <td>${item.uploader}</td>
                      <td style="max-width: 250px; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
                        ${item.title}
                      </td>
                      <td><span class="dh-chip ${riskCls}">${item.risk_level.toUpperCase()}</span></td>
                      <td><a href="${item.url}" target="_blank" style="color:var(--accent)">Link</a></td>
                    </tr>
                  `;
              }).join('');
          }
          tbody.innerHTML = finalHtml;
      }
    } catch (e) {
      console.error("Error loading discovery results:", e);
    }
  },

  // ── Reports ───────────────────────────────────────────────────

  async clearReports() {
    if (!confirm('Are you sure you want to delete ALL scan reports? This cannot be undone.')) return;
    try {
      await fetch(`${API}/api/reports`, { method: 'DELETE' });
      Toast.show('All reports cleared.', 'info');
      this.loadReports();
      this.refreshStatus();
    } catch (e) {
      Toast.show('Failed to clear reports.', 'error');
    }
  },

  async loadReports() {
    const grid = document.getElementById('reports-grid');
    grid.innerHTML = '<div class="empty-state" style="padding:3rem">Loading…</div>';
    try {
      const reports = await fetch(`${API}/api/reports`).then(r => r.json());
      if (!reports.length) {
        grid.innerHTML = '<div class="empty-state" style="padding:3rem">No reports yet. Run a scan to generate one.</div>';
        return;
      }

      grid.innerHTML = reports.map(r => {
        const pct   = r.similarity;
        const color = scoreColor(pct);
        const date  = r.generated ? new Date(r.generated).toLocaleString() : '';
        return `
          <div class="report-card" data-filename="${r.filename.replace(/"/g, '&quot;')}" onclick="App.openReport(this.getAttribute('data-filename'))">
            <div class="report-card-title">${r.suspect}</div>
            <div class="report-card-verdict">${r.verdict}</div>
            <div class="report-card-meta">
              <div class="report-score-bar">
                <div class="report-score-fill" style="width:${pct}%; background:${color}"></div>
              </div>
              <span class="report-score-val" style="color:${color}">${pct}%</span>
            </div>
            <div class="report-date">${date}</div>
          </div>
        `;
      }).join('');
    } catch {
      grid.innerHTML = '<div class="empty-state" style="padding:3rem">Failed to load reports.</div>';
    }
  },

  async openReport(filename) {
    const modal = document.getElementById('report-modal');
    const body  = document.getElementById('modal-body');
    const title = document.getElementById('modal-title');

    body.innerHTML = '<div class="empty-state">Loading…</div>';
    modal.style.display = 'flex';

    try {
      const data = await fetch(`${API}/api/reports/${encodeURIComponent(filename)}`).then(r => r.json());
      title.textContent = data.suspect_video;
      const pct   = data.similarity_percentage;
      const color = scoreColor(pct);
      const logo  = data.logo_confirmations;

      let complianceHtml = '';
      if (data.compliance_status) {
          const cls = data.compliance_status === 'AUTHORIZED' ? 'flag-clear' : 'flag-confirmed';
          complianceHtml = `
            <div class="compliance-card" style="margin-bottom:20px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 15px;">
                <div style="display:flex; justify-content:between; align-items:center; margin-bottom:10px;">
                    <span class="flag-chip ${cls}">AI: ${data.compliance_status}</span>
                    <span style="font-size:13px; color:var(--text-dim); margin-left:auto;">${data.publisher}</span>
                </div>
                <div style="font-size:14px; color:var(--text); line-height:1.5; margin-bottom:10px;">${data.compliance_reason}</div>
                ${data.topics ? `<div style="display:flex; gap:8px; flex-wrap:wrap;">${data.topics.map(t => `<span style="font-size:11px; color:var(--accent); background:rgba(0,212,255,0.1); padding:2px 8px; border-radius:10px;">#${t}</span>`).join('')}</div>` : ''}
            </div>
          `;
      }

      body.innerHTML = `
        ${complianceHtml}
        <div class="verdict-meta" style="margin-bottom:16px;gap:10px;display:flex;flex-wrap:wrap;align-items:center;">
          <span class="verdict-chip">Similarity: <strong style="color:${color}">${pct}%</strong></span>
          <span class="verdict-chip">Frames: ${data.matched_frames}/${data.total_frames_checked}</span>
          <span class="verdict-chip">Logo confirms: ${logo}</span>
          <span class="verdict-chip">${new Date(data.generated_at).toLocaleString()}</span>
          
          <div style="margin-left:auto; display:flex; gap:8px;">
            <button class="btn btn-primary btn-sm" data-filename="${filename.replace(/"/g, '&quot;')}" onclick="App.analyzeReport(this.getAttribute('data-filename'))" id="btn-analyze" style="background:var(--purple); color:#fff; border:none;">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" style="margin-right:6px"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
              Deep AI Analysis
            </button>
            <a href="${API}/api/reports/${encodeURIComponent(filename)}/dmca" class="btn-action">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14" style="vertical-align:middle;"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              DMCA Notice
            </a>
          </div>
        </div>
        <div id="analysis-container"></div>
        <div style="font-size:15px;font-weight:700;color:${color};margin-bottom:20px;">${data.verdict}</div>
        <div class="table-wrap">
          <table class="frame-table">
            <thead>
              <tr>
                <th>Time</th><th>D<sub>H</sub></th><th>Match</th>
                <th>Matched Clip</th><th>Logo</th><th>Flag</th>
              </tr>
            </thead>
            <tbody>
              ${data.frames.map(f => {
                const rowCls = f.flag_status === 'CONFIRMED INFRINGEMENT' ? 'row-confirmed' :
                               f.is_match ? 'row-match' : '';
                const logo   = f.logo_detected
                  ? `<span class="flag-chip flag-confirmed">YES</span>`
                  : `<span style="color:var(--text-dim)">—</span>`;
                return `
                  <tr class="${rowCls}">
                    <td>${f.suspect_time_fmt}</td>
                    <td>${dhChip(f.hamming_distance, f.similarity_score)}</td>
                    <td>${f.is_match ? '✓' : '—'}</td>
                    <td>${f.matched_clip || '—'}</td>
                    <td>${logo}</td>
                    <td>${flagChip(f.flag_status)}</td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      `;
    } catch {
      body.innerHTML = '<div class="empty-state">Failed to load report.</div>';
    }
  },

  async analyzeReport(filename) {
    const btn = document.getElementById('btn-analyze');
    const container = document.getElementById('analysis-container');
    
    btn.disabled = true;
    btn.textContent = 'Analyzing...';
    container.innerHTML = '<div class="empty-state">Gemini is processing the report evidence...</div>';

    try {
      const response = await fetch(`${API}/api/reports/${encodeURIComponent(filename)}/analyze`, { method: 'POST' });
      if (!response.ok) {
          const errData = await response.json();
          throw new Error(errData.error || `Server error ${response.status}`);
      }
      const res = await response.json();
      
      container.innerHTML = `
        <div class="analysis-box">
          <div class="analysis-header">
            <div class="analysis-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
              AI Insights
            </div>
            <div class="analysis-model">Powered by ${res.model}</div>
          </div>
          <div class="analysis-text">${res.analysis}</div>
        </div>
      `;
      btn.style.display = 'none';
      Toast.show('AI Analysis Complete', 'success');
    } catch (e) {
      console.error('Analysis error:', e);
      Toast.show(`AI analysis failed: ${e.message}`, 'error');
      btn.disabled = false;
      btn.textContent = 'Deep AI Analysis';
      container.innerHTML = `<div class="empty-state" style="color:var(--red)">Analysis failed: ${e.message}. Please try again later.</div>`;
    }
  },

  closeModal(event) {
    if (!event || event.target === document.getElementById('report-modal')) {
      document.getElementById('report-modal').style.display = 'none';
    }
  },

  // ── Init ──────────────────────────────────────────────────────

  init() {
    Router.init();

    // Slider labels
    const ingestSlider   = document.getElementById('ingest-interval');
    const ingestLabel    = document.getElementById('ingest-interval-val');
    const scanThSlider   = document.getElementById('scan-threshold');
    const scanThLabel    = document.getElementById('scan-threshold-val');
    const scanIntSlider  = document.getElementById('scan-interval');
    const scanIntLabel   = document.getElementById('scan-interval-val');

    ingestSlider.addEventListener('input',  () => ingestLabel.textContent   = `${ingestSlider.value}s`);
    scanThSlider.addEventListener('input',  () => scanThLabel.textContent   = scanThSlider.value);
    scanIntSlider.addEventListener('input', () => scanIntLabel.textContent  = `${scanIntSlider.value}s`);

    // Keyboard: Escape to close modal, and Quick Nav
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') this.closeModal({ target: document.getElementById('report-modal') });
      
      // Alt + 1-5 for quick navigation
      if (e.altKey && e.key === '1') Router.navigate('dashboard');
      if (e.altKey && e.key === '2') Router.navigate('ingest');
      if (e.altKey && e.key === '3') Router.navigate('autoingest');
      if (e.altKey && e.key === '4') Router.navigate('scan');
      if (e.altKey && e.key === '5') Router.navigate('reports');
    });

    // Auto-refresh dashboard every 10s
    setInterval(() => {
      if (Router.currentPage === 'dashboard') this.refreshAll();
    }, 10000);

    // Initial load
    const savedCollapsed = localStorage.getItem('dap_sidebar_collapsed') === 'true';
    if (savedCollapsed) document.getElementById('sidebar').classList.add('collapsed');

    this.refreshAll();
  },

  async updateTargetClips() {
    const el = document.getElementById('scan-target');
    if (!el) return;
    try {
      const { clips } = await fetch(`${API}/api/db`).then(r => r.json());
      const currentSelection = el.value;
      
      let html = '<option value="">Compare with all clips (Global DB)</option>';
      clips.forEach(c => {
        html += `<option value="${c.name}">${c.name}</option>`;
      });
      el.innerHTML = html;
      el.value = currentSelection;
    } catch (e) {
      console.warn('Failed to update target clips dropdown');
    }
  },

  toggleSidebar() {
    const sb = document.getElementById('sidebar');
    sb.classList.toggle('collapsed');
    const isCollapsed = sb.classList.contains('collapsed');
    localStorage.setItem('dap_sidebar_collapsed', isCollapsed);
  }
};

document.addEventListener('DOMContentLoaded', () => App.init());
