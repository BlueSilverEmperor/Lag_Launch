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

    particles.forEach(p => {
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0 || p.x > W) p.vx *= -1;
      if (p.y < 0 || p.y > H) p.vy *= -1;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = p.color.replace(')', `, ${p.a})`).replace('rgb', 'rgba').replace(/^#/, 'rgba(').replace(/(..)(..)(..)/, (_, r, g, b) => `${parseInt(r,16)}, ${parseInt(g,16)}, ${parseInt(b,16)},`);
      // Simplified: just use fillStyle with hex + alpha via globalAlpha
      ctx.globalAlpha = p.a;
      ctx.fillStyle   = p.color;
      ctx.fill();
      ctx.globalAlpha = 1;
    });

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
    if (page === 'dashboard') App.refreshAll();
    if (page === 'reports')   App.loadReports();
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
    'SUSPECTED COPY':          ['flag-suspected', '⚠️ Suspected'],
    'CLEAR':                   ['flag-clear',     '✅ Clear'],
  };
  const [cls, label] = map[status] || ['flag-clear', status];
  return `<span class="flag-chip ${cls}">${label}</span>`;
}

function dhChip(d) {
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

  async refreshStatus() {
    try {
      const s = await fetch(`${API}/api/status`).then(r => r.json());
      document.getElementById('v-clips').textContent   = s.db_clips;
      document.getElementById('v-frames').textContent  = s.total_frames.toLocaleString();
      document.getElementById('v-reports').textContent = s.report_count;
      document.getElementById('v-jobs').textContent    = s.running_jobs;

      // YOLO status dot
      const dot   = document.getElementById('yolo-dot');
      const label = document.getElementById('yolo-label');
      if (s.yolo_available) {
        dot.classList.add('active');
        label.textContent = 'YOLOv8 Ready';
      } else {
        dot.classList.add('error');
        label.textContent = 'YOLOv8 Missing';
      }
    } catch (e) {
      Toast.show('Cannot reach server — is server.py running?', 'error');
    }
  },

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

  async refreshJobs() {
    try {
      const jobs = await fetch(`${API}/api/jobs`).then(r => r.json());
      const el   = document.getElementById('recent-jobs-list');
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
    } catch {}
  },

  async refreshAll() {
    await Promise.all([
      this.refreshStatus(), 
      this.refreshDB(), 
      this.refreshJobs(),
      this.updateTargetClips()
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
        body: JSON.stringify({ source: dir, interval, overwrite }),
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
    ['phase-2','phase-3','phase-4'].forEach(id => {
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
    document.getElementById('verdict-meta').innerHTML = `
      <span class="verdict-chip">${data.matched_frames} / ${data.total_frames_checked} frames matched</span>
      <span class="verdict-chip">${data.logo_confirmations} logo confirmation(s)</span>
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
          <td>${dhChip(f.hamming_distance)}</td>
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

  // ── Reports ───────────────────────────────────────────────────

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
          <div class="report-card" onclick="App.openReport('${r.filename}')">
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
      const data = await fetch(`${API}/api/reports/${filename}`).then(r => r.json());
      title.textContent = data.suspect_video;
      const pct   = data.similarity_percentage;
      const color = scoreColor(pct);
      const logo  = data.logo_confirmations;

      body.innerHTML = `
        <div class="verdict-meta" style="margin-bottom:16px;gap:10px;display:flex;flex-wrap:wrap;">
          <span class="verdict-chip">Similarity: <strong style="color:${color}">${pct}%</strong></span>
          <span class="verdict-chip">Frames: ${data.matched_frames}/${data.total_frames_checked}</span>
          <span class="verdict-chip">Logo confirms: ${logo}</span>
          <span class="verdict-chip">${new Date(data.generated_at).toLocaleString()}</span>
        </div>
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
                    <td>${dhChip(f.hamming_distance)}</td>
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

    // Keyboard: Escape to close modal
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') this.closeModal({ target: document.getElementById('report-modal') });
    });

    // Auto-refresh dashboard every 10s
    setInterval(() => {
      if (Router.currentPage === 'dashboard') this.refreshAll();
    }, 10000);

    // Initial load
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
  }
};

document.addEventListener('DOMContentLoaded', () => App.init());
