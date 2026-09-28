/**
 * EDGEWISE AI — Edge Copilot Frontend Script (Phase 5: Offline-First)
 *
 * Connected to live FastAPI endpoints:
 *   - POST /api/copilot/query
 *   - GET  /health
 *   - GET  /system/connectivity
 *   - GET  /api/documents/{id}
 *
 * Shows real system status: ONLINE / OFFLINE / DEGRADED
 * Shows individual dependency states.
 * Does NOT imply cloud synchronization occurred.
 */

const API_BASE = window.location.origin;

// DOM Elements
const copilotForm = document.getElementById('copilot-form');
const queryInput = document.getElementById('query-input');
const submitBtn = document.getElementById('submit-btn');
const loadingState = document.getElementById('loading-state');
const errorState = document.getElementById('error-state');
const errorTitle = document.getElementById('error-title');
const errorMessage = document.getElementById('error-message');
const resultsArea = document.getElementById('results-area');
const insufficientBanner = document.getElementById('insufficient-evidence-banner');
const answerContent = document.getElementById('answer-content');
const modelBadge = document.getElementById('model-badge');
const modeBadge = document.getElementById('mode-badge');
const sourcesGrid = document.getElementById('sources-grid');
const sourceCount = document.getElementById('source-count');

// Metric Elements
const metricTotal = document.getElementById('metric-total');
const metricEmbed = document.getElementById('metric-embed');
const metricRetrieval = document.getElementById('metric-retrieval');
const metricLlm = document.getElementById('metric-llm');

// Status Elements
const statusBtn = document.getElementById('system-status-btn');
const statusDot = document.getElementById('status-dot');
const statusLabel = document.getElementById('status-label');
const statusPanel = document.getElementById('system-status-panel');
const panelAppMode = document.getElementById('panel-app-mode');
const panelLastCheck = document.getElementById('panel-last-check');

// Modal Elements
const docModal = document.getElementById('doc-modal');
const modalDocTitle = document.getElementById('modal-doc-title');
const modalJson = document.getElementById('modal-json');
const modalCloseBtn = document.getElementById('modal-close-btn');

// --- System Status Panel Toggle ---
statusBtn.addEventListener('click', () => {
  statusPanel.classList.toggle('hidden');
});

// Close panel when clicking outside
document.addEventListener('click', (e) => {
  if (!statusPanel.contains(e.target) && !statusBtn.contains(e.target)) {
    statusPanel.classList.add('hidden');
  }
});

// --- Connectivity Check ---
async function checkConnectivity() {
  try {
    const res = await fetch(`${API_BASE}/system/connectivity`);
    if (res.ok) {
      const data = await res.json();
      updateSystemStatus(data);
    } else {
      setStatusOffline('API Error');
    }
  } catch (err) {
    setStatusOffline('API Disconnected');
  }
}

function updateSystemStatus(data) {
  const state = data.state || 'unknown';
  const mode = data.application_mode || 'unknown';

  // Update top-level indicator
  statusDot.className = 'status-dot';
  if (state === 'online') {
    statusDot.classList.add('online');
    statusLabel.textContent = 'All Systems Online';
  } else if (state === 'offline') {
    statusDot.classList.add('offline');
    statusLabel.textContent = 'Local AI Available';
  } else if (state === 'degraded') {
    statusDot.classList.add('degraded');
    statusLabel.textContent = 'Degraded — Check Dependencies';
  } else {
    statusDot.classList.add('offline');
    statusLabel.textContent = state.toUpperCase();
  }

  // Update panel
  panelAppMode.textContent = `Mode: ${mode.toUpperCase()}`;
  panelAppMode.className = `panel-app-mode mode-${mode}`;

  // Update individual dependencies
  updateDependencyRow('sqlite', data.sqlite);
  updateDependencyRow('qdrant-edge', data.qdrant_edge);
  updateDependencyRow('ollama', data.ollama);
  updateDependencyRow('internet', data.internet);
  updateDependencyRow('qdrant-server', data.qdrant_server);

  // Last check
  if (data.last_check) {
    const dt = new Date(data.last_check);
    panelLastCheck.textContent = `Last check: ${dt.toLocaleTimeString()}`;
  }
}

function updateDependencyRow(depId, statusStr) {
  const el = document.getElementById(`dep-${depId}-status`);
  if (!el) return;
  const status = statusStr || 'unknown';
  el.textContent = status;
  el.className = 'dep-status';
  if (status === 'available') {
    el.classList.add('dep-available');
  } else if (status === 'unavailable') {
    el.classList.add('dep-unavailable');
  } else if (status === 'degraded') {
    el.classList.add('dep-degraded');
  } else {
    el.classList.add('dep-unknown');
  }
}

function setStatusOffline(message) {
  statusDot.className = 'status-dot offline';
  statusLabel.textContent = message;
}

// Initial connectivity check + periodic poll
checkConnectivity();
setInterval(checkConnectivity, 15000);

// --- Prompt Chips ---
document.querySelectorAll('.chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    const q = chip.getAttribute('data-query');
    if (q) {
      queryInput.value = q;
      copilotForm.dispatchEvent(new Event('submit'));
    }
  });
});

// --- Query Submission ---
copilotForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const query = queryInput.value.trim();
  if (!query) return;

  // UI state: loading
  submitBtn.disabled = true;
  loadingState.classList.remove('hidden');
  errorState.classList.add('hidden');
  resultsArea.classList.add('hidden');

  try {
    const res = await fetch(`${API_BASE}/api/copilot/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: query, max_sources: 5 }),
    });

    const data = await res.json();

    if (!res.ok) {
      showError(
        `Error (${res.status})`,
        data.detail || data.error || 'Failed to execute Copilot query.'
      );
      return;
    }

    renderResults(data);
  } catch (err) {
    showError(
      'Network / Server Error',
      'Could not reach local EDGEWISE AI backend. Verify server is running on port 8000.'
    );
  } finally {
    submitBtn.disabled = false;
    loadingState.classList.add('hidden');
  }
});

// --- Render Results ---
function renderResults(data) {
  resultsArea.classList.remove('hidden');

  // Insufficient evidence banner
  if (data.insufficient_evidence) {
    insufficientBanner.classList.remove('hidden');
  } else {
    insufficientBanner.classList.add('hidden');
  }

  // Answer & Model
  answerContent.textContent = data.answer;
  modelBadge.textContent = `model: ${data.model_used || 'edge-llm'}`;

  // Mode badge — always "LOCAL AI" in Phase 5
  if (data.offline_mode) {
    modeBadge.textContent = 'LOCAL AI';
    modeBadge.className = 'badge-mode mode-local';
  } else {
    modeBadge.textContent = 'LOCAL AI';
    modeBadge.className = 'badge-mode mode-local';
  }

  // Metrics
  metricTotal.textContent = `${Math.round(data.total_latency_ms)}ms`;
  metricEmbed.textContent = `${Math.round(data.embedding_latency_ms)}ms`;
  metricRetrieval.textContent = `${Math.round(data.retrieval_latency_ms)}ms`;
  metricLlm.textContent = `${Math.round(data.generation_latency_ms)}ms`;

  // Sources
  const sources = data.sources || [];
  sourceCount.textContent = sources.length;
  sourcesGrid.innerHTML = '';

  if (sources.length === 0) {
    sourcesGrid.innerHTML = '<div class="empty-sources">No citations retrieved.</div>';
    return;
  }

  sources.forEach((src) => {
    const card = document.createElement('div');
    card.className = 'source-card';

    // Page string
    let pageStr = 'Page N/A';
    if (src.page_start != null && src.page_end != null) {
      pageStr = src.page_start === src.page_end
        ? `Page ${src.page_start}`
        : `Pages ${src.page_start}–${src.page_end}`;
    }

    // Score
    const scoreVal = typeof src.score === 'number' ? src.score.toFixed(4) : src.score;

    card.innerHTML = `
      <div class="source-top">
        <div class="source-title" title="${src.filename || 'unknown'}">${src.document_title || src.filename}</div>
        <span class="source-score" title="Vector retrieval similarity score">Score: ${scoreVal}</span>
      </div>
      <div class="source-meta">
        <span>📄 ${src.filename}</span>
        <span>📑 ${pageStr}</span>
      </div>
      <div class="source-snippet">"${escapeHtml(src.content_preview || '')}"</div>
      <div class="source-action">
        <button class="btn-inspect" data-docid="${src.document_id}">Inspect Document Trace</button>
      </div>
    `;

    // Modal inspect listener
    const inspectBtn = card.querySelector('.btn-inspect');
    inspectBtn.addEventListener('click', () => inspectDocument(src.document_id));

    sourcesGrid.appendChild(card);
  });
}

// --- Inspect Document Metadata Modal ---
async function inspectDocument(docId) {
  if (!docId) return;
  modalDocTitle.textContent = `Document Trace: ${docId}`;
  modalJson.textContent = 'Loading metadata from SQLite...';
  docModal.classList.remove('hidden');

  try {
    const res = await fetch(`${API_BASE}/api/documents/${docId}`);
    if (res.ok) {
      const docData = await res.json();
      modalJson.textContent = JSON.stringify(docData, null, 2);
    } else {
      modalJson.textContent = `Error: Document not found (${res.status})`;
    }
  } catch (err) {
    modalJson.textContent = `Error fetching document: ${err.message}`;
  }
}

modalCloseBtn.addEventListener('click', () => docModal.classList.add('hidden'));
docModal.querySelector('.modal-backdrop').addEventListener('click', () => docModal.classList.add('hidden'));

// --- Error Helper ---
function showError(title, msg) {
  errorTitle.textContent = title;
  errorMessage.textContent = msg;
  errorState.classList.remove('hidden');
}

// --- Utility: Escape HTML ---
function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
