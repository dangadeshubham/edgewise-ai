/**
 * EDGEWISE AI — Edge Copilot Frontend Script
 * Connected to live FastAPI endpoints:
 *   - POST /api/copilot/query
 *   - GET  /health
 *   - GET  /api/documents/{id}
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
const sourcesGrid = document.getElementById('sources-grid');
const sourceCount = document.getElementById('source-count');

// Metric Elements
const metricTotal = document.getElementById('metric-total');
const metricEmbed = document.getElementById('metric-embed');
const metricRetrieval = document.getElementById('metric-retrieval');
const metricLlm = document.getElementById('metric-llm');

// Connectivity Elements
const connectivityBadge = document.getElementById('connectivity-badge');
const connectivityLabel = document.getElementById('connectivity-label');
const ollamaBadge = document.getElementById('ollama-badge');
const ollamaLabel = document.getElementById('ollama-label');

// Modal Elements
const docModal = document.getElementById('doc-modal');
const modalDocTitle = document.getElementById('modal-doc-title');
const modalJson = document.getElementById('modal-json');
const modalCloseBtn = document.getElementById('modal-close-btn');

// --- Health Polling ---
async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (res.ok) {
      const data = await res.json();
      const deps = data.dependencies || {};

      // Ollama check
      const ollama = deps.ollama || {};
      if (ollama.status === 'healthy' || ollama.model_available) {
        ollamaBadge.className = 'status-indicator ollama-ready';
        ollamaLabel.textContent = `OLLAMA (${ollama.model || 'READY'})`;
      } else {
        ollamaBadge.className = 'status-indicator error';
        ollamaLabel.textContent = 'OLLAMA UNAVAILABLE';
      }

      // SQLite & Qdrant Edge check
      const db = deps.database || {};
      const edge = deps.qdrant_edge || {};
      if (db.status === 'healthy' && edge.status === 'healthy') {
        connectivityBadge.className = 'status-indicator online';
        connectivityLabel.textContent = 'LOCAL EDGE ACTIVE';
      } else {
        connectivityBadge.className = 'status-indicator error';
        connectivityLabel.textContent = 'LOCAL STORAGE ERROR';
      }
    } else {
      connectivityBadge.className = 'status-indicator error';
      connectivityLabel.textContent = 'NODE OFFLINE';
    }
  } catch (err) {
    connectivityBadge.className = 'status-indicator error';
    connectivityLabel.textContent = 'API DISCONNECTED';
  }
}

// Initial health check + periodic poll
checkHealth();
setInterval(checkHealth, 15000);

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
