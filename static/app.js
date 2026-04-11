/**
 * MyAnalyst — Frontend Application
 * Vanilla JS, no frameworks, no build step.
 *
 * Features:
 *  - Drag-and-drop file upload with progress
 *  - SSE streaming chat
 *  - Inline charts (downloadable)
 *  - Collapsible code blocks
 *  - Confidence badges
 *  - Cleaning reports
 *  - Session restore
 */

"use strict";

/* =====================================================================
   State
===================================================================== */
const state = {
  streaming: false,
  uploadingFiles: new Set(),
  loadedFiles: [],  // [{var_name, filename, rows, columns, health_score}]
};

/* =====================================================================
   DOM refs
===================================================================== */
const $ = id => document.getElementById(id);

const $messages     = $("messages");
const $emptyState   = $("empty-state");
const $input        = $("message-input");
const $sendBtn      = $("send-btn");
const $dropZone     = $("drop-zone");
const $fileInput    = $("file-input");
const $fileCards    = $("file-cards");
const $indicator    = $("files-indicator");
const $llmDot       = $("llm-dot");
const $llmLabel     = $("llm-label");
const $newSessionBtn    = $("new-session-btn");
const $suggestionChips  = $("suggestion-chips");
const $mobileFilesBtn   = $("mobile-files-btn");
const $mobileFilesBadge = $("mobile-files-badge");
const $fileArea         = document.querySelector("#file-area");
const $demoBar          = $("demo-bar");
const $demoModelText    = $("demo-model-text");
const $demoBarClose     = $("demo-bar-close");

/* =====================================================================
   Initialisation
===================================================================== */
document.addEventListener("DOMContentLoaded", () => {
  checkHealth();
  loadExistingFiles();
  loadChatHistory();
  bindEvents();

  // Poll health every 30s
  setInterval(checkHealth, 30_000);
});

function bindEvents() {
  // Drag-and-drop
  $dropZone.addEventListener("dragover",  e => { e.preventDefault(); $dropZone.classList.add("drag-over"); });
  $dropZone.addEventListener("dragleave", () => $dropZone.classList.remove("drag-over"));
  $dropZone.addEventListener("drop", e => {
    e.preventDefault();
    $dropZone.classList.remove("drag-over");
    [...e.dataTransfer.files].forEach(uploadFile);
  });
  $dropZone.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") $fileInput.click();
  });

  // File picker
  $fileInput.addEventListener("change", e => {
    [...e.target.files].forEach(uploadFile);
    $fileInput.value = "";   // reset so same file can be re-uploaded
  });

  // Chat input
  $input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  $input.addEventListener("input", autoResize);

  $sendBtn.addEventListener("click", sendMessage);

  // Suggestion chips
  document.querySelectorAll(".chip[data-q]").forEach(chip => {
    chip.addEventListener("click", () => {
      $input.value = chip.dataset.q;
      autoResize();
      sendMessage();
    });
  });

  // New session
  $newSessionBtn.addEventListener("click", confirmNewSession);

  // Demo bar dismiss
  if ($demoBarClose) {
    $demoBarClose.addEventListener("click", () => {
      $demoBar.classList.add("hidden");
      sessionStorage.setItem("demoDismissed", "1");
    });
  }

  // Mobile file area toggle
  $mobileFilesBtn.addEventListener("click", () => {
    $fileArea.classList.toggle("mobile-open");
  });

  // Close mobile file panel when tapping outside it
  document.addEventListener("click", e => {
    if (
      $fileArea.classList.contains("mobile-open") &&
      !$fileArea.contains(e.target) &&
      !$mobileFilesBtn.contains(e.target)
    ) {
      $fileArea.classList.remove("mobile-open");
    }
  });
}

/* =====================================================================
   LLM Health check
===================================================================== */
async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (data.llm_ok) {
      $llmDot.className = "ok";
      if (data.llm_backend === "ollama") {
        $llmLabel.textContent = `Local · ${data.llm_model || "Ollama"}`;
      } else {
        const provider = (data.llm_provider || "API").toUpperCase();
        $llmLabel.textContent = `${data.llm_model || "Cloud"} · ${provider}`;
      }
    } else {
      $llmDot.className = "err";
      $llmLabel.textContent = "LLM offline";
    }

    // Demo bar — show once per session on cloud deployments
    if (data.is_demo && !sessionStorage.getItem("demoDismissed")) {
      const provider = (data.llm_provider || "API").toUpperCase();
      const model = data.llm_model || "AI model";
      if ($demoModelText) {
        $demoModelText.innerHTML = `Powered by <strong>${escHtml(model)}</strong> via ${escHtml(provider)} free tier`;
      }
      $demoBar.classList.remove("hidden");
    }
  } catch {
    $llmDot.className = "err";
    $llmLabel.textContent = "Server offline";
  }
}

/* =====================================================================
   File Upload
===================================================================== */
function uploadFile(file) {
  if (state.uploadingFiles.has(file.name)) return;
  state.uploadingFiles.add(file.name);

  const formData = new FormData();
  formData.append("file", file);

  // Show a temporary "uploading" card
  const tempCard = createTempCard(file.name);
  $fileCards.appendChild(tempCard);
  updateEmptyState();

  fetch("/upload", { method: "POST", body: formData })
    .then(res => res.json())
    .then(data => {
      state.uploadingFiles.delete(file.name);
      tempCard.remove();

      if (data.success) {
        const fileData = data.file;
        // Replace or add
        const existingIdx = state.loadedFiles.findIndex(
          f => f.filename === fileData.filename
        );
        if (existingIdx >= 0) {
          state.loadedFiles[existingIdx] = fileData;
        } else {
          state.loadedFiles.push(fileData);
        }
        renderFileCard(fileData);
        updateIndicator();
        updateEmptyState();
        if (data.file.replacing) {
          showToast(`Updated: ${file.name}`, "success");
        } else {
          showToast(`Loaded: ${file.name}`, "success");
        }
      } else {
        showToast(data.error || "Upload failed.", "error");
        updateEmptyState();
      }
    })
    .catch(err => {
      state.uploadingFiles.delete(file.name);
      tempCard.remove();
      showToast(`Upload error: ${err.message}`, "error");
      updateEmptyState();
    });
}

function createTempCard(filename) {
  const card = document.createElement("div");
  card.className = "file-card";
  card.style.opacity = "0.6";
  card.innerHTML = `
    <div class="file-card-header">
      <div class="file-name">${escHtml(filename)}</div>
    </div>
    <div class="file-meta" style="display:flex;align-items:center;gap:6px;margin-top:4px;">
      <div class="spinner"></div> Uploading…
    </div>
  `;
  return card;
}

function renderFileCard(fileData) {
  // Remove any existing card for this file
  const existing = $fileCards.querySelector(`[data-filename="${CSS.escape(fileData.filename)}"]`);
  if (existing) existing.remove();

  const ext = fileData.file_type || "csv";
  const healthColor = fileData.health_color || "green";
  const score = fileData.health_score || 100;
  const issues = fileData.issues || [];

  const issueHtml = issues.slice(0, 4).map(iss => {
    const icon = iss.severity === "critical" ? "🔴" : iss.severity === "warning" ? "⚠" : "ℹ";
    return `<div>${icon} ${escHtml(iss.description)}</div>`;
  }).join("");

  // Downloads for each var_name
  const dlHtml = (fileData.var_names || []).map(vn =>
    `<span class="file-card-dl" data-var="${escHtml(vn)}" data-fmt="csv">⬇ CSV</span>
     <span class="file-card-dl" data-var="${escHtml(vn)}" data-fmt="xlsx"> / XLSX</span>`
  ).join(" ");

  const card = document.createElement("div");
  card.className = "file-card";
  card.setAttribute("role", "listitem");
  card.setAttribute("data-filename", fileData.filename);
  card.innerHTML = `
    <span class="health-dot health-${healthColor}" title="Health score: ${score}/100"></span>
    <div class="file-card-header">
      <span class="file-type-badge badge-${ext}">${ext.toUpperCase()}</span>
      <div>
        <div class="file-name">${escHtml(fileData.filename)}</div>
        <div class="file-meta">${(fileData.row_count||0).toLocaleString()} rows × ${fileData.column_count||0} cols</div>
      </div>
    </div>
    ${issues.length > 0 ? `<span class="file-card-expand" role="button" tabindex="0">▾ ${issues.length} issue${issues.length>1?'s':''}</span>` : ""}
    <div class="file-card-detail">
      ${issueHtml || "<em>No issues detected</em>"}
      <div style="margin-top:6px;color:#374151;font-weight:600">Health: ${score}/100</div>
    </div>
    <div style="margin-top:6px">${dlHtml}</div>
    <button class="file-card-delete" aria-label="Remove ${escHtml(fileData.filename)}" title="Remove">✕</button>
  `;

  // Expand toggle
  const expandBtn = card.querySelector(".file-card-expand");
  if (expandBtn) {
    const detail = card.querySelector(".file-card-detail");
    const toggle = () => {
      const open = detail.classList.toggle("open");
      expandBtn.textContent = `${open ? "▴" : "▾"} ${issues.length} issue${issues.length>1?'s':''}`;
    };
    expandBtn.addEventListener("click", toggle);
    expandBtn.addEventListener("keydown", e => { if (e.key==="Enter") toggle(); });
  }

  // Delete button
  card.querySelector(".file-card-delete").addEventListener("click", async () => {
    const varName = (fileData.var_names || [])[0];
    if (!varName) return;
    await deleteFile(varName, fileData.filename);
    card.remove();
  });

  // Download buttons
  card.querySelectorAll(".file-card-dl").forEach(btn => {
    btn.addEventListener("click", () => downloadFile(btn.dataset.var, btn.dataset.fmt));
  });

  $fileCards.appendChild(card);
}

async function deleteFile(varName, filename) {
  try {
    await fetch(`/files/${encodeURIComponent(varName)}`, { method: "DELETE" });
    state.loadedFiles = state.loadedFiles.filter(f => f.filename !== filename);
    updateIndicator();
    updateEmptyState();
    showToast(`Removed: ${filename}`, "success");
  } catch {
    showToast("Could not remove file.", "error");
  }
}

async function loadExistingFiles() {
  try {
    const res = await fetch("/files");
    const data = await res.json();
    if (data.files && data.files.length > 0) {
      state.loadedFiles = data.files;
      data.files.forEach(f => {
        // Reconstruct minimal file card data from /files response
        renderFileCard({
          filename: f.filename,
          file_type: f.filename.split(".").pop().toLowerCase(),
          var_names: [f.var_name],
          row_count: f.rows,
          column_count: f.columns,
          health_score: f.health_score,
          health_color: f.health_score >= 85 ? "green" : f.health_score >= 60 ? "yellow" : "red",
          issues: [],
        });
      });
      updateIndicator();
      updateEmptyState();
    }
  } catch {
    // Silently ignore — session may not be available
  }
}

function downloadFile(varName, fmt) {
  const a = document.createElement("a");
  a.href = `/download/${encodeURIComponent(varName)}?format=${fmt}`;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function updateIndicator() {
  const count = state.loadedFiles.length;
  const totalRows = state.loadedFiles.reduce((s, f) => s + (f.rows || f.row_count || 0), 0);
  if (count === 0) {
    $indicator.textContent = "No files loaded";
    $indicator.className = "";
    $mobileFilesBadge.textContent = "";
    $mobileFilesBadge.classList.remove("visible");
  } else {
    $indicator.textContent = `${count} file${count>1?"s":""} | ${totalRows.toLocaleString()} rows`;
    $indicator.className = "has-files";
    $mobileFilesBadge.textContent = count;
    $mobileFilesBadge.classList.add("visible");
  }
}

function updateEmptyState() {
  const hasMessages = $messages.querySelectorAll(".message-row").length > 0;
  const hasFiles    = state.loadedFiles.length > 0 || state.uploadingFiles.size > 0;

  if (hasMessages) {
    $emptyState.classList.add("hidden");
  } else if (hasFiles) {
    // Files loaded, no messages — show suggestions
    $emptyState.classList.remove("hidden");
    $suggestionChips.style.display = "flex";
  } else {
    $emptyState.classList.remove("hidden");
    $suggestionChips.style.display = "flex";
  }
}

/* =====================================================================
   Chat
===================================================================== */
function sendMessage() {
  const text = $input.value.trim();
  if (!text || state.streaming) return;

  $input.value = "";
  autoResize();
  renderUserMessage(text);
  $emptyState.classList.add("hidden");
  setStreaming(true);

  const row = createAIMessageRow();
  const bubble = row.querySelector(".message-bubble");
  $messages.appendChild(row);
  scrollToBottom();

  let textBuffer    = "";
  let chartHtml     = "";
  let codeHtml      = "";
  let badgeHtml     = "";
  let cleaningHtml  = "";
  let cursorEl      = null;

  // Add blinking cursor while streaming
  cursorEl = document.createElement("span");
  cursorEl.className = "streaming-cursor";
  bubble.appendChild(cursorEl);

  const es = new EventSource(`/chat/stream?message=${encodeURIComponent(text)}`);

  es.onmessage = e => {
    let data;
    try { data = JSON.parse(e.data); } catch { return; }

    switch (data.type) {
      case "text":
        textBuffer += data.content;
        // Remove cursor temporarily, update text, re-add cursor
        if (cursorEl && bubble.contains(cursorEl)) bubble.removeChild(cursorEl);
        setInnerText(bubble, textBuffer);
        bubble.appendChild(cursorEl);
        scrollToBottom();
        break;

      case "code":
        codeHtml = buildCodeBlock(data.content);
        break;

      case "chart":
        chartHtml = buildChartBlock(data.chart_id);
        break;

      case "cleaning":
        cleaningHtml = buildCleaningBlock(data.report);
        break;

      case "confidence":
        badgeHtml = buildConfidenceBadge(data.level, data.label);
        break;

      case "retry":
        {
          const retryDiv = document.createElement("div");
          retryDiv.className = "retry-indicator";
          retryDiv.innerHTML = `<div class="spinner"></div> Retrying (attempt ${data.attempt}/${data.max})…`;
          if (cursorEl && bubble.contains(cursorEl)) bubble.removeChild(cursorEl);
          bubble.appendChild(retryDiv);
          bubble.appendChild(cursorEl);
          scrollToBottom();
        }
        break;

      case "error":
        {
          const errDiv = document.createElement("div");
          const isRateLimit = data.content && (
            data.content.toLowerCase().includes("rate limit") ||
            data.content.includes("429")
          );
          if (isRateLimit) {
            errDiv.className = "error-message rate-limit-message";
            errDiv.innerHTML = `
              <strong>Demo under high load</strong><br>
              Multiple people are using this demo right now and we've hit the free-tier limit.
              This is a known limitation of the shared free demo — it runs on Groq's free API tier.
              Please wait 30–60 seconds and try again, or
              <a href="https://github.com/abhimanyurana1995/myAIanalyst" target="_blank" rel="noopener">
                run it locally on your own machine
              </a> for unlimited usage.
            `;
          } else {
            errDiv.className = "error-message";
            errDiv.textContent = data.content;
          }
          if (cursorEl && bubble.contains(cursorEl)) bubble.removeChild(cursorEl);
          bubble.appendChild(errDiv);
        }
        break;

      case "done":
        es.close();
        // Remove cursor
        if (cursorEl && bubble.contains(cursorEl)) bubble.removeChild(cursorEl);
        cursorEl = null;

        // Remove retry spinners
        bubble.querySelectorAll(".retry-indicator").forEach(el => el.remove());

        // Re-render prose
        setInnerText(bubble, textBuffer);

        // Append extra blocks
        if (codeHtml)     bubble.insertAdjacentHTML("beforeend", codeHtml);
        if (chartHtml)    bubble.insertAdjacentHTML("beforeend", chartHtml);
        if (cleaningHtml) bubble.insertAdjacentHTML("beforeend", cleaningHtml);
        if (badgeHtml)    bubble.insertAdjacentHTML("beforeend", badgeHtml);

        // Wire up code toggle
        bubble.querySelectorAll(".code-block-header").forEach(header => {
          header.addEventListener("click", () => {
            header.classList.toggle("open");
            header.nextElementSibling.classList.toggle("open");
          });
        });

        // Wire up chart download
        bubble.querySelectorAll(".chart-dl-btn").forEach(btn => {
          btn.addEventListener("click", () => {
            const img = btn.closest(".chart-wrapper").querySelector("img");
            if (!img) return;
            const a = document.createElement("a");
            a.href = img.src;
            a.download = btn.dataset.chartId || "chart.png";
            a.click();
          });
        });

        // Reload file list (cleaning may have changed row counts)
        if (cleaningHtml) loadExistingFiles();

        setStreaming(false);
        scrollToBottom();
        break;
    }
  };

  es.onerror = () => {
    es.close();
    if (cursorEl && bubble.contains(cursorEl)) bubble.removeChild(cursorEl);
    const errDiv = document.createElement("div");
    errDiv.className = "error-message";
    errDiv.textContent = "Connection lost. Please try again.";
    bubble.appendChild(errDiv);
    setStreaming(false);
    scrollToBottom();
  };
}

function renderUserMessage(text) {
  const row = document.createElement("div");
  row.className = "message-row user";
  row.setAttribute("role", "listitem");
  row.innerHTML = `
    <div class="message-avatar avatar-user" aria-hidden="true">You</div>
    <div class="message-bubble">${escHtml(text)}</div>
  `;
  $messages.appendChild(row);
  scrollToBottom();
}

function createAIMessageRow() {
  const row = document.createElement("div");
  row.className = "message-row ai";
  row.setAttribute("role", "listitem");
  row.innerHTML = `
    <div class="message-avatar avatar-ai" aria-hidden="true">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
      </svg>
    </div>
    <div class="message-bubble"></div>
  `;
  return row;
}

/**
 * Set text content with basic markdown-like rendering.
 * We keep it minimal — no full markdown parser, just the essentials.
 */
function setInnerText(el, text) {
  // Clean up any streaming cursor / retry indicators before setting text
  const cursor   = el.querySelector(".streaming-cursor");
  const retries  = [...el.querySelectorAll(".retry-indicator")];
  const errors   = [...el.querySelectorAll(".error-message")];

  el.innerHTML = renderMarkdown(text);

  // Re-append preserved elements
  if (cursor)          el.appendChild(cursor);
  retries.forEach(r => el.appendChild(r));
  errors.forEach(r  => el.appendChild(r));
}

function renderMarkdown(text) {
  if (!text) return "";
  // Basic: escape HTML, then convert common patterns
  let html = escHtml(text);
  // Bold: **text**
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // Code: `code`
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  // Bullet lists: lines starting with - or *
  html = html.replace(/^[•\-\*] (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>\n?)+/gs, "<ul>$&</ul>");
  // Numbered lists
  html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");
  // Paragraphs: double newline
  html = html.replace(/\n{2,}/g, "</p><p>");
  // Single newlines
  html = html.replace(/\n/g, "<br>");
  return `<p>${html}</p>`;
}

/* =====================================================================
   Block builders
===================================================================== */
function buildCodeBlock(code) {
  return `
    <div class="code-block-wrapper">
      <div class="code-block-header" role="button" tabindex="0" aria-expanded="false">
        <span class="lang-label">Python</span>
        <span class="code-toggle-icon">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
        </span>
      </div>
      <div class="code-block-body">
        <pre>${escHtml(code)}</pre>
      </div>
    </div>`;
}

function buildChartBlock(chartId) {
  const src = `/chart/${encodeURIComponent(chartId)}`;
  return `
    <div class="chart-wrapper">
      <img src="${src}" alt="Generated chart" loading="lazy" />
      <div class="chart-actions">
        <button class="chart-dl-btn" data-chart-id="${escHtml(chartId)}" aria-label="Download chart">
          ⬇ Download chart
        </button>
      </div>
    </div>`;
}

function buildCleaningBlock(report) {
  const rows = report.rows_changed ? ` (${report.rows_changed} rows affected)` : "";
  return `
    <div class="cleaning-report">
      <strong>✓ Data cleaned${rows}</strong>
      ${escHtml(report.summary || "")}
    </div>`;
}

function buildConfidenceBadge(level, label) {
  const cls = level === "computed" ? "badge-computed" : "badge-fallback";
  return `<div class="confidence-badge ${cls}" title="Answer confidence">${escHtml(label)}</div>`;
}

/* =====================================================================
   Chat history restore
===================================================================== */
async function loadChatHistory() {
  try {
    const res = await fetch("/chat/history");
    const data = await res.json();
    if (!data.history || data.history.length === 0) return;

    data.history.forEach(msg => {
      if (msg.role === "user") {
        renderUserMessage(msg.content);
      } else if (msg.role === "assistant") {
        const row = createAIMessageRow();
        const bubble = row.querySelector(".message-bubble");
        bubble.innerHTML = renderMarkdown(msg.content);
        if (msg.confidence === "computed") {
          bubble.insertAdjacentHTML("beforeend",
            buildConfidenceBadge("computed", "✓ Computed directly from your data"));
        } else if (msg.confidence === "fallback") {
          bubble.insertAdjacentHTML("beforeend",
            buildConfidenceBadge("fallback", "⚠ Could not compute — answer based on data summary"));
        }
        $messages.appendChild(row);
      }
    });

    if (data.history.length > 0) {
      $emptyState.classList.add("hidden");
      scrollToBottom();
    }
  } catch {
    // Ignore — fresh start
  }
}

/* =====================================================================
   Session management
===================================================================== */
async function confirmNewSession() {
  if (!confirm("Start a new session? This will clear all loaded files and conversation history.")) return;

  try {
    await fetch("/session/clear", { method: "POST" });
    state.loadedFiles = [];
    $fileCards.innerHTML = "";
    $messages.innerHTML = "";
    $messages.appendChild($emptyState);
    $emptyState.classList.remove("hidden");
    updateIndicator();
    showToast("Session cleared.", "success");
  } catch {
    showToast("Could not clear session.", "error");
  }
}

/* =====================================================================
   Utilities
===================================================================== */
function setStreaming(active) {
  state.streaming = active;
  $input.disabled  = active;
  $sendBtn.disabled = active;
  if (!active) $input.focus();
}

function scrollToBottom() {
  $messages.scrollTop = $messages.scrollHeight;
}

function autoResize() {
  $input.style.height = "auto";
  $input.style.height = Math.min($input.scrollHeight, 140) + "px";
}

function escHtml(str) {
  const el = document.createElement("div");
  el.appendChild(document.createTextNode(String(str || "")));
  return el.innerHTML;
}

function showToast(message, type = "") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.setAttribute("role", "alert");
  toast.textContent = message;
  $("toast-container").appendChild(toast);
  setTimeout(() => toast.remove(), 3800);
}
