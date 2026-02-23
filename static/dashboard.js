// HydraFlow Dashboard — vanilla JS client
// Extracted from templates/index.html (issue #24)

// State
const workers = {};       // {issueNum: {status, title, branch, transcript[]}}
const prs = [];           // [{pr, issue, branch, draft, url}]
const reviews = [];       // [{pr, verdict, summary}]
let selectedWorker = null;
let currentTab = 'transcript';

// WebSocket
const wsUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;
let ws = null;

function connect() {
  ws = new WebSocket(wsUrl);
  ws.onmessage = (e) => handleEvent(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 2000);
  ws.onerror = () => ws.close();
}
connect();

// Poll for human input requests
setInterval(async () => {
  try {
    const resp = await fetch('/api/human-input');
    const data = await resp.json();
    const banner = document.getElementById('human-input-banner');
    const keys = Object.keys(data);
    if (keys.length > 0) {
      const issueNum = keys[0];
      const question = data[issueNum];
      document.getElementById('human-input-question').textContent =
        `Issue #${issueNum}: ${question}`;
      document.getElementById('human-input-field').dataset.issue = issueNum;
      banner.classList.add('visible');
    } else {
      banner.classList.remove('visible');
    }
  } catch (e) { /* ignore */ }
}, 3000);

function submitHumanInput() {
  const field = document.getElementById('human-input-field');
  const issueNum = field.dataset.issue;
  const answer = field.value.trim();
  if (!answer || !issueNum) return;

  fetch(`/api/human-input/${issueNum}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answer }),
  });
  field.value = '';
  document.getElementById('human-input-banner').classList.remove('visible');
}

function handleEvent(event) {
  const { type, data, timestamp } = event;

  // Update event log
  addEventLog(type, data, timestamp);

  switch (type) {
    case 'batch_start':
      document.getElementById('batch-num').textContent = data.batch;
      break;

    case 'phase_change': {
      const badge = document.getElementById('phase-badge');
      badge.textContent = data.phase;
      badge.className = 'phase-badge ' + data.phase;
      break;
    }

    case 'worker_update':
      updateWorker(data.issue, data.status, data.worker);
      break;

    case 'transcript_line': {
      const issueNum = data.issue || data.pr;
      if (issueNum && workers[issueNum]) {
        workers[issueNum].transcript.push(data.line);
        if (selectedWorker === issueNum) {
          appendTranscriptLine(data.line);
        }
      }
      break;
    }

    case 'pr_created':
      prs.push(data);
      document.getElementById('prs-count').textContent = prs.length;
      updatePRTable();
      if (data.issue && workers[data.issue]) {
        workers[data.issue].pr = data;
      }
      break;

    case 'review_update':
      if (data.status === 'done') {
        reviews.push(data);
        updateReviewTable();
      }
      break;

    case 'merge_update':
      if (data.status === 'merge_requested') {
        const c = parseInt(document.getElementById('merged-count').textContent) + 1;
        document.getElementById('merged-count').textContent = c;
      }
      break;

    case 'batch_complete':
      document.getElementById('merged-count').textContent = data.merged || 0;
      break;
  }
}

function updateWorker(issueNum, status, workerId) {
  if (!workers[issueNum]) {
    workers[issueNum] = {
      status: status,
      worker: workerId,
      title: `Issue #${issueNum}`,
      branch: `agent/issue-${issueNum}`,
      transcript: [],
      pr: null,
    };
  }
  workers[issueNum].status = status;

  // Update counts
  const all = Object.values(workers);
  document.getElementById('workers-total').textContent = all.length;
  document.getElementById('workers-active').textContent =
    all.filter(w => w.status === 'running' || w.status === 'testing').length;

  renderWorkerList();
}

function renderWorkerList() {
  const container = document.getElementById('worker-list');
  const sorted = Object.entries(workers).sort((a, b) => a[0] - b[0]);
  container.innerHTML = sorted.map(([num, w]) => `
    <div class="worker-card ${selectedWorker == num ? 'active' : ''}"
         data-issue="${num}">
      <div class="worker-header">
        <span class="worker-issue">#${num}</span>
        <span class="worker-status ${escapeHtml(w.status)}">${escapeHtml(w.status)}</span>
      </div>
      <div class="worker-title">${escapeHtml(w.title)}</div>
      <div class="worker-meta">${escapeHtml(w.branch)} &middot; W${w.worker}</div>
    </div>
  `).join('');
}

function selectWorker(issueNum) {
  selectedWorker = issueNum;
  renderWorkerList();
  renderTranscript();
}

function renderTranscript() {
  const el = document.getElementById('tab-transcript');
  if (!selectedWorker || !workers[selectedWorker]) {
    el.innerHTML = '<div class="empty-state">Select a worker to view its transcript</div>';
    return;
  }
  const lines = workers[selectedWorker].transcript;
  el.innerHTML = lines.map(l =>
    `<div class="transcript-line">${escapeHtml(l)}</div>`
  ).join('');
  el.scrollTop = el.scrollHeight;
}

function appendTranscriptLine(line) {
  if (currentTab !== 'transcript') return;
  const el = document.getElementById('tab-transcript');
  const div = document.createElement('div');
  div.className = 'transcript-line new';
  div.textContent = line;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

function updatePRTable() {
  const tbody = document.getElementById('pr-tbody');
  tbody.innerHTML = prs.map(p => `
    <tr>
      <td><a href="${escapeHtml(p.url || '#')}" target="_blank" style="color:var(--accent)">#${p.pr}</a></td>
      <td>#${p.issue}</td>
      <td>${escapeHtml(p.branch)}</td>
      <td>${p.draft ? '📝 Draft' : '✅ Ready'}</td>
    </tr>
  `).join('');
}

function updateReviewTable() {
  const tbody = document.getElementById('review-tbody');
  tbody.innerHTML = reviews.map(r => {
    const colors = { approve: 'var(--green)', 'request-changes': 'var(--red)', comment: 'var(--yellow)' };
    const verdictStr = escapeHtml(r.verdict || '');
    return `
      <tr>
        <td>#${r.pr}</td>
        <td style="color:${colors[r.verdict] || 'inherit'}">${verdictStr}</td>
        <td>${escapeHtml(r.summary || '')}</td>
      </tr>
    `;
  }).join('');
}

function addEventLog(type, data, timestamp) {
  const el = document.getElementById('event-log');
  const time = new Date(timestamp).toLocaleTimeString();
  const summary = escapeHtml(eventSummary(type, data));
  const safeType = escapeHtml(type);
  const div = document.createElement('div');
  div.className = 'event-item';
  div.innerHTML = `<span class="event-time">${escapeHtml(time)}</span>` +
    `<span class="event-type ${safeType}">${safeType.replace('_', ' ')}</span>` +
    `<span>${summary}</span>`;
  el.prepend(div);

  // Also add to timeline tab
  const tl = document.getElementById('timeline-content');
  const tlDiv = div.cloneNode(true);
  tl.prepend(tlDiv);

  // Keep event log manageable
  while (el.children.length > 200) el.lastChild.remove();
}

function eventSummary(type, data) {
  switch (type) {
    case 'batch_start': return `Batch ${data.batch} started`;
    case 'phase_change': return String(data.phase);
    case 'worker_update': return `#${data.issue} → ${String(data.status)}`;
    case 'transcript_line': return `#${data.issue || data.pr}`;
    case 'pr_created': return `PR #${data.pr} for #${data.issue}${data.draft ? ' (draft)' : ''}`;
    case 'review_update': return `PR #${data.pr} → ${String(data.verdict || data.status)}`;
    case 'merge_update': return `PR #${data.pr} ${String(data.status)}`;
    case 'batch_complete': return `${data.merged} merged, ${data.implemented} implemented`;
    case 'error': return String(data.message || 'Error');
    default: return JSON.stringify(data).slice(0, 80);
  }
}

function switchTab(name, evt) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.main > [id^="tab-"]').forEach(t => t.style.display = 'none');
  evt.target.classList.add('active');
  document.getElementById(`tab-${name}`).style.display = '';
  currentTab = name;
  if (name === 'transcript') renderTranscript();
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// --- Event listeners (replacing inline onclick handlers) ---
document.addEventListener('DOMContentLoaded', function() {
  // Tab switching via data-tab attributes
  document.querySelectorAll('.tab[data-tab]').forEach(function(tab) {
    tab.addEventListener('click', function(evt) {
      switchTab(this.dataset.tab, evt);
    });
  });

  // Human input submit button
  var submitBtn = document.getElementById('human-input-submit');
  if (submitBtn) {
    submitBtn.addEventListener('click', submitHumanInput);
  }

  // Worker card selection via event delegation
  var workerList = document.getElementById('worker-list');
  if (workerList) {
    workerList.addEventListener('click', function(e) {
      var card = e.target.closest('.worker-card');
      if (card && card.dataset.issue) {
        selectWorker(Number(card.dataset.issue));
      }
    });
  }
});
