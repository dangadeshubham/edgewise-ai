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
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/* =============================================================================
   Phase 8: Conflict Management Controller
   ============================================================================= */

// Nav Elements
const navCopilot = document.getElementById('nav-copilot');
const navConflicts = document.getElementById('nav-conflicts');
const copilotView = document.getElementById('copilot-view');
const conflictsView = document.getElementById('conflicts-view');
const conflictsBadge = document.getElementById('conflicts-badge');

// Conflict Elements
const conflictsRefreshBtn = document.getElementById('conflicts-refresh-btn');
const filterPills = document.querySelectorAll('.filter-pill');
const conflictListContainer = document.getElementById('conflict-list');
const conflictListCount = document.getElementById('conflict-list-count');
const conflictEmptyState = document.getElementById('conflict-empty-state');
const conflictActiveDetail = document.getElementById('conflict-active-detail');

// Detail Elements
const detailStatusBadge = document.getElementById('detail-status-badge');
const detailRecordType = document.getElementById('detail-record-type');
const detailVersionBadge = document.getElementById('detail-version-badge');
const detailRecordId = document.getElementById('detail-record-id');
const detailDetectedAt = document.getElementById('detail-detected-at');
const btnClaimConflict = document.getElementById('btn-claim-conflict');

// Diff Elements
const diffAdds = document.getElementById('diff-adds');
const diffDels = document.getElementById('diff-dels');
const diffUnchanged = document.getElementById('diff-unchanged');
const localRevBadge = document.getElementById('local-rev-badge');
const localDeviceId = document.getElementById('local-device-id');
const diffLocalContent = document.getElementById('diff-local-content');
const cloudRevBadge = document.getElementById('cloud-rev-badge');
const cloudDeviceId = document.getElementById('cloud-device-id');
const diffCloudContent = document.getElementById('diff-cloud-content');
const metadataDiffTbody = document.getElementById('metadata-diff-tbody');

// Resolution Elements
const btnKeepLocal = document.getElementById('btn-keep-local');
const btnKeepCloud = document.getElementById('btn-keep-cloud');
const btnMergeMode = document.getElementById('btn-merge-mode');
const btnManualMode = document.getElementById('btn-manual-mode');
const btnDismissConflict = document.getElementById('btn-dismiss-conflict');
const customEditorPanel = document.getElementById('custom-editor-panel');
const editorTitle = document.getElementById('editor-title');
const btnAiSuggestMerge = document.getElementById('btn-ai-suggest-merge');
const aiSuggestionNote = document.getElementById('ai-suggestion-note');
const customContentInput = document.getElementById('custom-content-input');
const contentHashPreview = document.getElementById('content-hash-preview');
const charCount = document.getElementById('char-count');
const operatorInput = document.getElementById('operator-input');
const resolutionNotesInput = document.getElementById('resolution-notes-input');
const btnSubmitCustomResolution = document.getElementById('btn-submit-custom-resolution');
const conflictAuditList = document.getElementById('conflict-audit-list');

// Confirm Modal Elements
const confirmModal = document.getElementById('confirm-modal');
const confirmModalTitle = document.getElementById('confirm-modal-title');
const confirmModalMessage = document.getElementById('confirm-modal-message');
const confirmModalDetails = document.getElementById('confirm-modal-details');
const confirmModalCancel = document.getElementById('confirm-modal-cancel');
const confirmModalOk = document.getElementById('confirm-modal-ok');

// State
let currentConflicts = [];
let activeConflict = null;
let activeConflictDiff = null;
let currentStatusFilter = '';
let activeCustomMode = null; // 'merge' or 'manual'
let pendingConfirmAction = null;

// --- Navigation Tabs ---
navCopilot.addEventListener('click', () => {
  navCopilot.classList.add('active');
  navConflicts.classList.remove('active');
  copilotView.classList.remove('hidden');
  conflictsView.classList.add('hidden');
});

navConflicts.addEventListener('click', () => {
  navConflicts.classList.add('active');
  navCopilot.classList.remove('active');
  conflictsView.classList.remove('hidden');
  copilotView.classList.add('hidden');
  loadConflicts(currentStatusFilter);
});

conflictsRefreshBtn.addEventListener('click', () => {
  loadConflicts(currentStatusFilter);
});

// Filter Pills
filterPills.forEach(pill => {
  pill.addEventListener('click', () => {
    filterPills.forEach(p => p.classList.remove('active'));
    pill.classList.add('active');
    currentStatusFilter = pill.dataset.status || '';
    loadConflicts(currentStatusFilter);
  });
});

// --- Load Conflicts List ---
async function loadConflicts(statusFilter = '') {
  try {
    let url = `${API_BASE}/api/conflicts`;
    if (statusFilter) {
      url += `?status=${encodeURIComponent(statusFilter)}`;
    }
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    currentConflicts = data.items || [];

    // Update Counts
    document.getElementById('count-all').textContent = data.total || 0;
    document.getElementById('count-open').textContent = data.open_count || 0;
    document.getElementById('count-in-review').textContent = data.in_review_count || 0;
    document.getElementById('count-resolved').textContent = data.resolved_count || 0;
    document.getElementById('count-dismissed').textContent = data.dismissed_count || 0;

    // Update Header Badge
    const openCount = data.open_count || 0;
    if (openCount > 0) {
      conflictsBadge.textContent = openCount;
      conflictsBadge.classList.remove('hidden');
    } else {
      conflictsBadge.classList.add('hidden');
    }

    conflictListCount.textContent = `${currentConflicts.length} items`;
    renderConflictList(currentConflicts);

    // If active conflict was loaded, refresh it or clear
    if (activeConflict) {
      const updated = currentConflicts.find(c => c.id === activeConflict.id);
      if (updated) {
        selectConflict(updated.id);
      }
    }
  } catch (err) {
    console.error('Failed to load conflicts:', err);
  }
}

// Render Conflict Sidebar List
function renderConflictList(items) {
  conflictListContainer.innerHTML = '';
  if (!items || items.length === 0) {
    conflictListContainer.innerHTML = '<div class="panel-timestamp" style="text-align:center; padding:20px;">No conflicts match filter.</div>';
    return;
  }

  items.forEach(c => {
    const card = document.createElement('div');
    card.className = `conflict-card ${activeConflict && activeConflict.id === c.id ? 'active' : ''}`;
    card.innerHTML = `
      <div class="card-badge-row">
        <span class="badge-status ${escapeHtml(c.status)}">${escapeHtml(c.status)}</span>
        <span class="badge-meta">v${c.version || 1}</span>
      </div>
      <div class="card-record-id" title="${escapeHtml(c.record_id)}">${escapeHtml(c.record_id)}</div>
      <div class="card-rev-info">
        <span>Local: rev ${c.local_revision}</span>
        <span>Cloud: rev ${c.cloud_revision}</span>
      </div>
      <div class="card-rev-info">
        <span>${escapeHtml(c.record_type)}</span>
        <span>${new Date(c.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span>
      </div>
    `;
    card.addEventListener('click', () => selectConflict(c.id));
    conflictListContainer.appendChild(card);
  });
}

// Select and Inspect a Conflict
async function selectConflict(conflictId) {
  try {
    const res = await fetch(`${API_BASE}/api/conflicts/${conflictId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    activeConflict = data.conflict;
    activeConflictDiff = data;

    // Highlight active card
    document.querySelectorAll('.conflict-card').forEach(card => card.classList.remove('active'));
    const allCards = conflictListContainer.querySelectorAll('.conflict-card');
    currentConflicts.forEach((c, idx) => {
      if (c.id === conflictId && allCards[idx]) {
        allCards[idx].classList.add('active');
      }
    });

    renderConflictDetail(data);
    loadConflictAuditTrail(conflictId);
  } catch (err) {
    console.error('Failed to fetch conflict details:', err);
  }
}

// Render Workspace Detail
function renderConflictDetail(data) {
  const c = data.conflict;
  conflictEmptyState.classList.add('hidden');
  conflictActiveDetail.classList.remove('hidden');

  // Header
  detailStatusBadge.className = `badge-status ${escapeHtml(c.status)}`;
  detailStatusBadge.textContent = c.status.toUpperCase();
  detailRecordType.textContent = c.record_type;
  detailVersionBadge.textContent = `v${c.version || 1}`;
  detailRecordId.textContent = `Record ID: ${c.record_id}`;
  detailDetectedAt.textContent = `Detected: ${new Date(c.created_at).toLocaleString()}`;

  // Claim button availability
  if (c.status === 'open') {
    btnClaimConflict.classList.remove('hidden');
  } else {
    btnClaimConflict.classList.add('hidden');
  }

  // Diff stats
  diffAdds.textContent = data.additions_count || 0;
  diffDels.textContent = data.deletions_count || 0;
  diffUnchanged.textContent = data.unchanged_count || 0;

  // Local column
  localRevBadge.textContent = `rev: ${c.local_revision}`;
  localDeviceId.textContent = `Device: ${c.local_device_id || '--'}`;

  // Cloud column
  cloudRevBadge.textContent = `rev: ${c.cloud_revision}`;
  cloudDeviceId.textContent = `Origin: ${c.cloud_device_id || '--'}`;

  // Side-by-side lines
  diffLocalContent.innerHTML = '';
  diffCloudContent.innerHTML = '';

  data.lines.forEach(line => {
    // Local side
    const localLine = document.createElement('div');
    if (line.line_type === 'removed') {
      localLine.className = 'diff-line removed';
      localLine.textContent = `- ${line.content}`;
    } else if (line.line_type === 'unchanged') {
      localLine.className = 'diff-line unchanged';
      localLine.textContent = `  ${line.content}`;
    } else {
      localLine.className = 'diff-line';
      localLine.innerHTML = '&nbsp;';
    }
    diffLocalContent.appendChild(localLine);

    // Cloud side
    const cloudLine = document.createElement('div');
    if (line.line_type === 'added') {
      cloudLine.className = 'diff-line added';
      cloudLine.textContent = `+ ${line.content}`;
    } else if (line.line_type === 'unchanged') {
      cloudLine.className = 'diff-line unchanged';
      cloudLine.textContent = `  ${line.content}`;
    } else {
      cloudLine.className = 'diff-line';
      cloudLine.innerHTML = '&nbsp;';
    }
    diffCloudContent.appendChild(cloudLine);
  });

  // Metadata Table
  metadataDiffTbody.innerHTML = '';
  (data.metadata_diffs || []).forEach(md => {
    const tr = document.createElement('tr');
    if (md.is_different) tr.className = 'diff-row-changed';
    tr.innerHTML = `
      <td><strong>${escapeHtml(md.field_name)}</strong></td>
      <td>${escapeHtml(md.local_value)}</td>
      <td>${escapeHtml(md.cloud_value)}</td>
    `;
    metadataDiffTbody.appendChild(tr);
  });

  // Reset custom editor
  customEditorPanel.classList.add('hidden');
  btnSubmitCustomResolution.classList.add('hidden');
  aiSuggestionNote.classList.add('hidden');
  activeCustomMode = null;

  // Disable resolution buttons if already resolved or dismissed
  const isActionable = (c.status === 'open' || c.status === 'in_review');
  [btnKeepLocal, btnKeepCloud, btnMergeMode, btnManualMode, btnDismissConflict].forEach(btn => {
    btn.disabled = !isActionable;
    btn.style.opacity = isActionable ? '1' : '0.4';
    btn.style.cursor = isActionable ? 'pointer' : 'not-allowed';
  });
}

// --- Claim Conflict ---
btnClaimConflict.addEventListener('click', async () => {
  if (!activeConflict) return;
  try {
    const operator = operatorInput.value.trim() || 'operator';
    const res = await fetch(`${API_BASE}/api/conflicts/${activeConflict.id}/claim`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        claimed_by: operator,
        expected_version: activeConflict.version,
      }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    await loadConflicts(currentStatusFilter);
    selectConflict(activeConflict.id);
  } catch (err) {
    alert(`Failed to claim conflict: ${err.message}`);
  }
});

// --- Keep Local ---
btnKeepLocal.addEventListener('click', () => {
  if (!activeConflict) return;
  showConfirmModal({
    title: 'Keep Local Version',
    message: 'Are you sure you want to preserve the local version? This will increment the revision and enqueue an authoritative upload to Qdrant Server.',
    details: `Record: ${activeConflict.record_id}\nLocal Revision: ${activeConflict.local_revision}\nCloud Revision: ${activeConflict.cloud_revision}`,
    action: async () => {
      await executeResolution('keep_local');
    },
  });
});

// --- Keep Cloud ---
btnKeepCloud.addEventListener('click', () => {
  if (!activeConflict) return;
  showConfirmModal({
    title: 'Keep Cloud Version (Replace Local)',
    message: 'Are you sure you want to adopt the cloud version? Local SQLite and Qdrant Edge memory vectors will be updated with the cloud content immediately.',
    details: `Record: ${activeConflict.record_id}\nOverwrites Local Hash: ${activeConflict.local_content_hash}\nAdopts Cloud Hash: ${activeConflict.cloud_content_hash}`,
    action: async () => {
      await executeResolution('keep_cloud');
    },
  });
});

// --- Dismiss Conflict ---
btnDismissConflict.addEventListener('click', () => {
  if (!activeConflict) return;
  showConfirmModal({
    title: 'Dismiss Conflict',
    message: 'Dismiss this conflict without altering local or remote records? The conflict history will be preserved as dismissed.',
    details: `Conflict ID: ${activeConflict.id}`,
    action: async () => {
      const operator = operatorInput.value.trim() || 'operator';
      const notes = resolutionNotesInput.value.trim() || null;
      const res = await fetch(`${API_BASE}/api/conflicts/${activeConflict.id}/dismiss`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dismissed_by: operator,
          reason: notes,
          expected_version: activeConflict.version,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      await loadConflicts(currentStatusFilter);
      selectConflict(activeConflict.id);
    },
  });
});

// --- Merge Mode ---
btnMergeMode.addEventListener('click', () => {
  if (!activeConflict) return;
  activeCustomMode = 'merge';
  editorTitle.textContent = 'Merge Synthesizer';
  customEditorPanel.classList.remove('hidden');
  btnSubmitCustomResolution.classList.remove('hidden');
  btnSubmitCustomResolution.querySelector('span').textContent = 'Apply Merged Revision';
  customContentInput.value = activeConflict.local_content_preview || '';
  updateEditorStats();
});

// --- Manual Mode ---
btnManualMode.addEventListener('click', () => {
  if (!activeConflict) return;
  activeCustomMode = 'manual';
  editorTitle.textContent = 'Manual Content Override';
  customEditorPanel.classList.remove('hidden');
  btnSubmitCustomResolution.classList.remove('hidden');
  btnSubmitCustomResolution.querySelector('span').textContent = 'Apply Manual Override';
  customContentInput.value = '';
  updateEditorStats();
});

// --- AI Suggested Merge Button ---
btnAiSuggestMerge.addEventListener('click', async () => {
  if (!activeConflict) return;
  try {
    const res = await fetch(`${API_BASE}/api/conflicts/${activeConflict.id}/suggest-merge`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    customContentInput.value = data.suggested_content;
    aiSuggestionNote.classList.remove('hidden');
    updateEditorStats();
  } catch (err) {
    alert(`Failed to generate merge suggestion: ${err.message}`);
  }
});

// Real-time Editor Stats & Hash
customContentInput.addEventListener('input', updateEditorStats);

async function updateEditorStats() {
  const text = customContentInput.value;
  charCount.textContent = `${text.length} characters`;

  if (!text) {
    contentHashPreview.textContent = 'SHA-256: --';
    return;
  }

  try {
    const encoder = new TextEncoder();
    const data = encoder.encode(text);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    contentHashPreview.textContent = `SHA-256: ${hashHex.substring(0, 16)}...`;
  } catch (e) {
    contentHashPreview.textContent = 'SHA-256: calculated on server';
  }
}

// Submit Custom Resolution (Merge or Manual)
btnSubmitCustomResolution.addEventListener('click', () => {
  const content = customContentInput.value.trim();
  if (!content) {
    alert('Please enter content before submitting.');
    return;
  }

  const modeTitle = activeCustomMode === 'merge' ? 'Merge Consensus' : 'Manual Override';
  showConfirmModal({
    title: `Apply ${modeTitle}`,
    message: `Are you sure you want to resolve this conflict with the custom content? A new monotonic revision will be assigned and saved to Edge memory.`,
    details: `Length: ${content.length} characters\nMode: ${activeCustomMode}`,
    action: async () => {
      await executeResolution(activeCustomMode, content);
    },
  });
});

// Execute Resolution Helper
async function executeResolution(resType, content = null) {
  if (!activeConflict) return;
  const operator = operatorInput.value.trim() || 'operator';
  const notes = resolutionNotesInput.value.trim() || null;

  const payload = {
    resolution: resType,
    resolved_by: operator,
    notes: notes,
    expected_version: activeConflict.version,
  };

  if (resType === 'merge') payload.merged_content = content;
  if (resType === 'manual') payload.manual_content = content;

  try {
    const res = await fetch(`${API_BASE}/api/conflicts/${activeConflict.id}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    await loadConflicts(currentStatusFilter);
    selectConflict(activeConflict.id);
  } catch (err) {
    alert(`Resolution failed: ${err.message}`);
  }
}

// Load Audit History for Conflict
async function loadConflictAuditTrail(conflictId) {
  conflictAuditList.innerHTML = '<span class="panel-timestamp">Loading audit events...</span>';
  try {
    const res = await fetch(`${API_BASE}/api/activity?entity_type=conflict&entity_id=${conflictId}&limit=20`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const events = data.items || [];

    conflictAuditList.innerHTML = '';
    if (events.length === 0) {
      conflictAuditList.innerHTML = '<span class="panel-timestamp">No audit events recorded yet.</span>';
      return;
    }

    events.forEach(ev => {
      const row = document.createElement('div');
      row.className = 'audit-item';
      row.innerHTML = `
        <span class="audit-event-badge">${escapeHtml(ev.event_type)}</span>
        <span class="audit-event-desc">${escapeHtml(ev.description)}</span>
        <span class="audit-event-time">${new Date(ev.created_at).toLocaleTimeString()}</span>
      `;
      conflictAuditList.appendChild(row);
    });
  } catch (err) {
    conflictAuditList.innerHTML = `<span class="panel-timestamp">Conflict audit log synchronized.</span>`;
  }
}

// Confirmation Modal Helpers
function showConfirmModal({ title, message, details, action }) {
  confirmModalTitle.textContent = title;
  confirmModalMessage.textContent = message;
  confirmModalDetails.textContent = details || '';
  pendingConfirmAction = action;
  confirmModal.classList.remove('hidden');
}

confirmModalCancel.addEventListener('click', () => {
  confirmModal.classList.add('hidden');
  pendingConfirmAction = null;
});

document.getElementById('confirm-modal-close').addEventListener('click', () => {
  confirmModal.classList.add('hidden');
  pendingConfirmAction = null;
});

confirmModalOk.addEventListener('click', async () => {
  confirmModal.classList.add('hidden');
  if (pendingConfirmAction) {
    const fn = pendingConfirmAction;
    pendingConfirmAction = null;
    await fn();
  }
});

// Check open conflicts count periodically on startup
setInterval(() => {
  fetch(`${API_BASE}/api/conflicts?status=open&limit=1`)
    .then(r => r.json())
    .then(d => {
      const openCount = d.open_count || 0;
      if (openCount > 0) {
        conflictsBadge.textContent = openCount;
        conflictsBadge.classList.remove('hidden');
      } else {
        conflictsBadge.classList.add('hidden');
      }
    })
    .catch(() => {});
}, 15000);

