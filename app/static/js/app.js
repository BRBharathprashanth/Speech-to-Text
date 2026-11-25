(() => {
  "use strict";

  const bodyEl = document.body;
  const maxUploadMb = Number(bodyEl.dataset.maxUploadMb || "25");
  const maxSessionSeconds = Number(bodyEl.dataset.maxSessionSeconds || "600");
  const ALLOWED_EXTENSIONS = new Set(["wav", "mp3", "m4a", "flac", "ogg", "webm"]);

  // Elements
  const themeToggle = document.getElementById("theme-toggle");
  const appHealthPill = document.getElementById("app-health-pill");
  const appHealthText = document.getElementById("app-health-text");
  const dbHealthPill = document.getElementById("db-health-pill");
  const dbHealthText = document.getElementById("db-health-text");

  const statTotal = document.getElementById("stat-total");
  const statHindi = document.getElementById("stat-hindi");
  const statEnglish = document.getElementById("stat-english");
  const statMixed = document.getElementById("stat-mixed");
  const statOther = document.getElementById("stat-other");

  const btnStartRec = document.getElementById("btn-start-rec");
  const btnStopRec = document.getElementById("btn-stop-rec");
  const btnClearRec = document.getElementById("btn-clear-rec");
  const btnSaveRec = document.getElementById("btn-save-rec");
  const recIndicator = document.getElementById("rec-indicator");
  const recStateLabel = document.getElementById("rec-state-label");
  const recTimerEl = document.getElementById("rec-timer");
  const micPermBadge = document.getElementById("mic-permission-badge");
  const wsStatusBadge = document.getElementById("ws-status-badge");
  const liveLangBadge = document.getElementById("live-lang-badge");
  const liveStatusBanner = document.getElementById("live-processing-status");
  const committedTextEl = document.getElementById("committed-text");
  const partialTextEl = document.getElementById("partial-text");
  const livePlaceholderEl = document.getElementById("live-placeholder");
  const liveEditorEl = document.getElementById("live-transcript-editor");

  const uploadForm = document.getElementById("upload-form");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("audio-file-input");
  const selectedFileLabel = document.getElementById("selected-file-label");
  const btnUploadSubmit = document.getElementById("btn-upload-submit");
  const btnUploadClear = document.getElementById("btn-upload-clear");
  const uploadProgressWrap = document.getElementById("upload-progress-wrap");
  const uploadProgressBar = document.getElementById("upload-progress-bar");
  const uploadProgressText = document.getElementById("upload-progress-text");
  const uploadStatusBanner = document.getElementById("upload-status-banner");
  const uploadResultCard = document.getElementById("upload-result-card");
  const uploadResultMeta = document.getElementById("upload-result-meta");
  const uploadResultText = document.getElementById("upload-result-text");

  const searchInput = document.getElementById("search-input");
  const mixFilter = document.getElementById("mix-filter");
  const btnRefreshHistory = document.getElementById("btn-refresh-history");
  const historyLoading = document.getElementById("history-loading");
  const historyError = document.getElementById("history-error");
  const historyEmpty = document.getElementById("history-empty");
  const historyTableWrap = document.getElementById("history-table-wrap");
  const historyTbody = document.getElementById("history-tbody");
  const paginationSummary = document.getElementById("pagination-summary");
  const btnPrevPage = document.getElementById("btn-prev-page");
  const btnNextPage = document.getElementById("btn-next-page");
  const pageIndicator = document.getElementById("page-indicator");

  const detailModal = document.getElementById("detail-modal");
  const modalBackdrop = document.getElementById("modal-backdrop");
  const modalClose = document.getElementById("modal-close");
  const modalTitle = document.getElementById("modal-title");
  const modalMeta = document.getElementById("modal-meta");
  const modalViewBody = document.getElementById("modal-view-body");
  const modalEditTextarea = document.getElementById("modal-edit-textarea");
  const modalBtnCopy = document.getElementById("modal-btn-copy");
  const modalBtnEdit = document.getElementById("modal-btn-edit");
  const modalBtnSave = document.getElementById("modal-btn-save");
  const modalBtnCancel = document.getElementById("modal-btn-cancel");

  const deleteModal = document.getElementById("delete-modal");
  const deleteModalBackdrop = document.getElementById("delete-modal-backdrop");
  const deleteBtnCancel = document.getElementById("delete-btn-cancel");
  const deleteBtnConfirm = document.getElementById("delete-btn-confirm");
  const toastContainer = document.getElementById("toast-container");

  // State
  let currentPage = 1;
  const pageSize = 10;
  let searchDebounceTimer = null;
  let activeModalRecord = null;
  let pendingDeleteId = null;

  let isRecording = false;
  let isStopping = false;
  let currentSessionId = null;
  let lastSavedSessionId = null;
  let ws = null;
  let reconnectAttempts = 0;
  let reconnectTimer = null;
  let audioContext = null;
  let mediaStream = null;
  let workletNode = null;
  let scriptProcessor = null;
  let sourceNode = null;
  let timerInterval = null;
  let recordingStartedAt = 0;
  let committedBuffer = "";
  let partialBuffer = "";
  let detectedLiveLang = null;
  let finalTimeoutTimer = null; // Fallback timer for finalization

  // Helpers
  function clearFinalTimeout() {
    if (finalTimeoutTimer) {
      clearTimeout(finalTimeoutTimer);
      finalTimeoutTimer = null;
    }
  }

  function scheduleFinalTimeout(timeoutMs = 15000) {
    clearFinalTimeout();
    finalTimeoutTimer = setTimeout(() => {
      if (isStopping) {
        showToast("Finalization timed out. Recording stopped.", "error");
        forceStopLocalRecording();
      }
    }, timeoutMs);
  }

  function showToast(message, variant = "info") {
    const toast = document.createElement("div");
    toast.className = `toast ${variant === "success" ? "toast-success" : variant === "error" ? "toast-error" : ""}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  function setBanner(el, message, variant = "info") {
    if (!message) {
      el.classList.add("hidden");
      el.textContent = "";
      el.classList.remove("status-error", "status-success");
      return;
    }
    el.textContent = message;
    el.classList.remove("hidden", "status-error", "status-success");
    if (variant === "error") el.classList.add("status-error");
    if (variant === "success") el.classList.add("status-success");
  }

  function formatDuration(sec) {
    if (sec === null || sec === undefined || Number.isNaN(Number(sec))) return "—";
    return `${Number(sec).toFixed(1)}s`;
  }

  function formatTimestamp(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toISOString().replace("T", " ").slice(0, 19);
  }

  function generateSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return `sess-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
  }

  function makeBadge(text, extraClass = "") {
    const span = document.createElement("span");
    span.className = `badge ${extraClass}`.trim();
    span.textContent = text;
    return span;
  }

  // Theme
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("stt_theme", theme);
    themeToggle.textContent = theme === "dark" ? "Light Mode" : "Dark Mode";
  }

  const savedTheme = localStorage.getItem("stt_theme") ||
    (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(savedTheme);
  themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "light";
    applyTheme(current === "dark" ? "light" : "dark");
  });

  // Health polling
  async function refreshHealth() {
    try {
      const res = await fetch("/health");
      if (!res.ok) throw new Error("App health check failed");
      const data = await res.json();
      const modelState = data.model_status || "unknown";
      appHealthPill.className = "status-pill " + (modelState === "ready" ? "status-ok" : modelState === "error" ? "status-err" : "status-warn");
      appHealthText.textContent = `App OK • Model (${data.model_name}): ${modelState}`;
    } catch {
      appHealthPill.className = "status-pill status-err";
      appHealthText.textContent = "App unreachable";
    }

    try {
      const res = await fetch("/health/db");
      if (!res.ok) throw new Error("DB unavailable");
      dbHealthPill.className = "status-pill status-ok";
      dbHealthText.textContent = "DB: Connected";
    } catch {
      dbHealthPill.className = "status-pill status-err";
      dbHealthText.textContent = "DB: Disconnected";
    }
  }

  // Stats & History
  async function refreshStats() {
    try {
      const res = await fetch("/api/stats");
      if (!res.ok) return;
      const stats = await res.json();
      statTotal.textContent = String(stats.total ?? 0);
      statHindi.textContent = String(stats.hindi ?? 0);
      statEnglish.textContent = String(stats.english ?? 0);
      statMixed.textContent = String(stats.mixed ?? 0);
      statOther.textContent = String(stats.other ?? 0);
    } catch {
      // Keep previous stats on transient failure.
    }
  }

  async function loadHistory() {
    historyLoading.classList.remove("hidden");
    historyError.classList.add("hidden");
    historyEmpty.classList.add("hidden");

    const params = new URLSearchParams({
      page: String(currentPage),
      page_size: String(pageSize),
    });
    const q = searchInput.value.trim();
    const mix = mixFilter.value.trim();
    if (q) params.set("q", q);
    if (mix) params.set("script_mix", mix);

    try {
      const res = await fetch(`/api/transcriptions?${params.toString()}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to load transcription history.");
      }
      const data = await res.json();
      renderHistoryRows(data.items || []);
      const total = Number(data.total || 0);
      const totalPages = Number(data.total_pages || 1);
      paginationSummary.textContent = `Showing ${data.items.length} of ${total} record(s)`;
      pageIndicator.textContent = `Page ${data.page} / ${totalPages}`;
      btnPrevPage.disabled = data.page <= 1;
      btnNextPage.disabled = data.page >= totalPages;

      if (total === 0) {
        historyEmpty.classList.remove("hidden");
        historyTableWrap.classList.add("hidden");
      } else {
        historyTableWrap.classList.remove("hidden");
      }
    } catch (err) {
      setBanner(historyError, err.message || "Error loading history.", "error");
      historyTableWrap.classList.add("hidden");
    } finally {
      historyLoading.classList.add("hidden");
    }
  }

  function renderHistoryRows(items) {
    historyTbody.replaceChildren();
    for (const item of items) {
      const tr = document.createElement("tr");

      const tdId = document.createElement("td");
      tdId.textContent = String(item.id);
      tr.appendChild(tdId);

      const tdText = document.createElement("td");
      tdText.className = "preview-cell";
      const text = item.transcription_text || "";
      tdText.textContent = text.length > 140 ? `${text.slice(0, 140)}…` : text;
      tr.appendChild(tdText);

      const tdLang = document.createElement("td");
      tdLang.textContent = item.detected_language || "auto";
      tr.appendChild(tdLang);

      const tdMix = document.createElement("td");
      const mixSpan = document.createElement("span");
      const mix = item.script_mix || "other";
      mixSpan.className = `mix-badge mix-${mix}`;
      mixSpan.textContent = mix;
      tdMix.appendChild(mixSpan);
      tr.appendChild(tdMix);

      const tdDur = document.createElement("td");
      tdDur.textContent = formatDuration(item.audio_duration);
      tr.appendChild(tdDur);

      const tdCreated = document.createElement("td");
      tdCreated.textContent = formatTimestamp(item.created_at);
      tr.appendChild(tdCreated);

      const tdUpdated = document.createElement("td");
      tdUpdated.textContent = formatTimestamp(item.updated_at);
      tr.appendChild(tdUpdated);

      const tdActions = document.createElement("td");
      tdActions.className = "actions-cell";

      const btnView = document.createElement("button");
      btnView.type = "button";
      btnView.className = "btn btn-secondary btn-sm";
      btnView.textContent = "View";
      btnView.addEventListener("click", () => openDetailModal(item, false));

      const btnEdit = document.createElement("button");
      btnEdit.type = "button";
      btnEdit.className = "btn btn-primary btn-sm";
      btnEdit.textContent = "Edit";
      btnEdit.addEventListener("click", () => openDetailModal(item, true));

      const btnCopy = document.createElement("button");
      btnCopy.type = "button";
      btnCopy.className = "btn btn-secondary btn-sm";
      btnCopy.textContent = "Copy";
      btnCopy.addEventListener("click", () => copyText(item.transcription_text || ""));

      const btnDel = document.createElement("button");
      btnDel.type = "button";
      btnDel.className = "btn btn-danger btn-sm";
      btnDel.textContent = "Delete";
      btnDel.addEventListener("click", () => openDeleteModal(item.id));

      tdActions.append(btnView, btnEdit, btnCopy, btnDel);
      tr.appendChild(tdActions);
      historyTbody.appendChild(tr);
    }
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      showToast("Copied transcription to clipboard.", "success");
    } catch {
      showToast("Clipboard copy was blocked by the browser.", "error");
    }
  }

  // Detail / Edit Modal
  function openDetailModal(record, editMode) {
    activeModalRecord = record;
    modalTitle.textContent = `Transcription #${record.id}`;
    modalMeta.replaceChildren(
      makeBadge(`Lang: ${record.detected_language || "auto"}`),
      makeBadge(`Mix: ${record.script_mix || "other"}`),
      makeBadge(`Duration: ${formatDuration(record.audio_duration)}`),
      makeBadge(`Source: ${record.audio_filename || "manual"}`)
    );
    modalViewBody.textContent = record.transcription_text || "";
    modalEditTextarea.value = record.transcription_text || "";
    setModalEditMode(editMode);
    detailModal.classList.remove("hidden");
  }

  function setModalEditMode(editing) {
    modalViewBody.classList.toggle("hidden", editing);
    modalEditTextarea.classList.toggle("hidden", !editing);
    modalBtnEdit.classList.toggle("hidden", editing);
    modalBtnSave.classList.toggle("hidden", !editing);
    modalBtnCancel.classList.toggle("hidden", !editing);
  }

  function closeDetailModal() {
    detailModal.classList.add("hidden");
    activeModalRecord = null;
  }

  modalClose.addEventListener("click", closeDetailModal);
  modalBackdrop.addEventListener("click", closeDetailModal);
  modalBtnCopy.addEventListener("click", () => {
    if (activeModalRecord) copyText(modalEditTextarea.value || activeModalRecord.transcription_text || "");
  });
  modalBtnEdit.addEventListener("click", () => setModalEditMode(true));
  modalBtnCancel.addEventListener("click", () => {
    if (activeModalRecord) {
      modalEditTextarea.value = activeModalRecord.transcription_text || "";
      setModalEditMode(false);
    }
  });
  modalBtnSave.addEventListener("click", async () => {
    if (!activeModalRecord) return;
    const updatedText = modalEditTextarea.value.trim();
    if (!updatedText) {
      showToast("Transcription text cannot be empty.", "error");
      return;
    }
    modalBtnSave.disabled = true;
    try {
      const res = await fetch(`/api/transcriptions/${activeModalRecord.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcription_text: updatedText }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to update transcription.");
      }
      const updated = await res.json();
      activeModalRecord = updated;
      modalViewBody.textContent = updated.transcription_text;
      setModalEditMode(false);
      showToast("Transcription updated.", "success");
      await Promise.all([loadHistory(), refreshStats()]);
    } catch (err) {
      showToast(err.message || "Update failed.", "error");
    } finally {
      modalBtnSave.disabled = false;
    }
  });

  // Delete Modal
  function openDeleteModal(id) {
    pendingDeleteId = id;
    deleteModal.classList.remove("hidden");
  }

  function closeDeleteModal() {
    pendingDeleteId = null;
    deleteModal.classList.add("hidden");
  }

  deleteBtnCancel.addEventListener("click", closeDeleteModal);
  deleteModalBackdrop.addEventListener("click", closeDeleteModal);
  deleteBtnConfirm.addEventListener("click", async () => {
    if (!pendingDeleteId) return;
    deleteBtnConfirm.disabled = true;
    try {
      const res = await fetch(`/api/transcriptions/${pendingDeleteId}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to delete transcription.");
      }
      closeDeleteModal();
      showToast("Transcription deleted.", "success");
      await Promise.all([loadHistory(), refreshStats()]);
    } catch (err) {
      showToast(err.message || "Delete failed.", "error");
    } finally {
      deleteBtnConfirm.disabled = false;
    }
  });

  // Live Transcript Display
  function renderLiveTranscript() {
    committedTextEl.textContent = committedBuffer ? `${committedBuffer} ` : "";
    partialTextEl.textContent = partialBuffer || "";
    const hasText = Boolean(committedBuffer.trim() || partialBuffer.trim());
    livePlaceholderEl.classList.toggle("hidden", hasText);
    liveLangBadge.textContent = `Lang: ${detectedLiveLang || "Auto"}`;
  }

  function updateRecordingUI() {
    btnStartRec.disabled = isRecording || isStopping;
    btnStopRec.disabled = !isRecording || isStopping;
    recIndicator.className = "rec-indicator " + (isRecording ? "rec-active" : "rec-idle");
    recStateLabel.textContent = isStopping ? "Finalizing..." : isRecording ? "Recording" : "Idle";
  }

  function startTimer() {
    stopTimer();
    recordingStartedAt = Date.now();
    timerInterval = setInterval(() => {
      const elapsedSec = Math.floor((Date.now() - recordingStartedAt) / 1000);
      const mins = String(Math.floor(elapsedSec / 60)).padStart(2, "0");
      const secs = String(elapsedSec % 60).padStart(2, "0");
      recTimerEl.textContent = `${mins}:${secs}`;
      if (elapsedSec >= maxSessionSeconds && isRecording) {
        stopRecording();
      }
    }, 500);
  }

  function stopTimer() {
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
  }

  function downsampleFloat32ToInt16(inputBuffer, inputRate, targetRate = 16000) {
    if (inputRate === targetRate) {
      const out = new Int16Array(inputBuffer.length);
      for (let i = 0; i < inputBuffer.length; i++) {
        const s = Math.max(-1, Math.min(1, inputBuffer[i]));
        out[i] = s < 0 ? Math.round(s * 32768) : Math.round(s * 32767);
      }
      return out.buffer;
    }
    const ratio = inputRate / targetRate;
    const outLen = Math.floor(inputBuffer.length / ratio);
    const out = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const pos = i * ratio;
      const idx = Math.floor(pos);
      const frac = pos - idx;
      const s0 = inputBuffer[idx];
      const s1 = idx + 1 < inputBuffer.length ? inputBuffer[idx + 1] : s0;
      const sample = Math.max(-1, Math.min(1, s0 + (s1 - s0) * frac));
      out[i] = sample < 0 ? Math.round(sample * 32768) : Math.round(sample * 32767);
    }
    return out.buffer;
  }

  async function initAudioPipeline() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      micPermBadge.textContent = "Mic: Unsupported Browser";
      throw new Error("Microphone API is unavailable in this browser/context (HTTPS or localhost required).");
    }

    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    micPermBadge.textContent = "Mic: Granted";

    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioCtx();
    if (audioContext.state === "suspended") {
      await audioContext.resume();
    }
    sourceNode = audioContext.createMediaStreamSource(mediaStream);

    if (audioContext.audioWorklet) {
      await audioContext.audioWorklet.addModule("/static/js/pcm-worklet.js");
      workletNode = new AudioWorkletNode(audioContext, "pcm-capture-processor", {
        processorOptions: { targetSampleRate: 16000, chunkSizeSamples: 3200 },
      });
      workletNode.port.onmessage = (event) => {
        if (ws && ws.readyState === WebSocket.OPEN && isRecording) {
          ws.send(event.data);
        }
      };
      sourceNode.connect(workletNode);
      workletNode.connect(audioContext.destination);
    } else {
      // Fallback for older browsers without AudioWorklet.
      scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);
      scriptProcessor.onaudioprocess = (event) => {
        if (!ws || ws.readyState !== WebSocket.OPEN || !isRecording) return;
        const input = event.inputBuffer.getChannelData(0);
        const pcmBuffer = downsampleFloat32ToInt16(input, audioContext.sampleRate, 16000);
        ws.send(pcmBuffer);
      };
      sourceNode.connect(scriptProcessor);
      scriptProcessor.connect(audioContext.destination);
    }
  }

  function cleanupAudioPipeline() {
    if (workletNode) {
      try {
        workletNode.port.postMessage({ type: "stop" });
        workletNode.disconnect();
      } catch { /* ignore */ }
      workletNode = null;
    }
    if (scriptProcessor) {
      try {
        scriptProcessor.disconnect();
      } catch { /* ignore */ }
      scriptProcessor = null;
    }
    if (sourceNode) {
      try {
        sourceNode.disconnect();
      } catch { /* ignore */ }
      sourceNode = null;
    }
    if (mediaStream) {
      for (const track of mediaStream.getTracks()) track.stop();
      mediaStream = null;
    }
    if (audioContext) {
      audioContext.close().catch(() => {});
      audioContext = null;
    }
  }

  function connectWebSocket(isResume = false) {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${scheme}://${window.location.host}/ws/transcribe`;
    wsStatusBadge.textContent = isResume ? "WS: Reconnecting..." : "WS: Connecting...";
    ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      reconnectAttempts = 0;
      wsStatusBadge.textContent = "WS: Connected";
      ws.send(
        JSON.stringify({
          type: "start",
          session_id: currentSessionId,
          sample_rate: 16000,
          channels: 1,
          resume: isResume,
        })
      );
    };

    ws.onmessage = async (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }

      if (msg.type === "started" || msg.type === "resumed") {
        if (msg.type === "resumed" && msg.committed_text) {
          committedBuffer = msg.committed_text;
          renderLiveTranscript();
          setBanner(liveStatusBanner, "Reconnected to active server session.", "success");
        } else {
          setBanner(liveStatusBanner, "Listening... Speak in Hindi, English, or mixed Hinglish.");
        }
      } else if (msg.type === "session_lost") {
        setBanner(liveStatusBanner, msg.message || "Server session was lost. Please restart recording.", "error");
        showToast("Server session buffer lost; please start a new recording.", "error");
        forceStopLocalRecording();
      } else if (msg.type === "partial") {
        if (typeof msg.committed_text === "string") {
          committedBuffer = msg.committed_text;
        }
        partialBuffer = msg.text || "";
        if (msg.detected_language) detectedLiveLang = msg.detected_language;
        renderLiveTranscript();
      } else if (msg.type === "committed") {
        committedBuffer = msg.committed_text || committedBuffer;
        partialBuffer = "";
        if (msg.detected_language) detectedLiveLang = msg.detected_language;
        renderLiveTranscript();
      } else if (msg.type === "final") {
        clearFinalTimeout();
        isStopping = false;
        isRecording = false;
        stopTimer();
        cleanupAudioPipeline();
        committedBuffer = msg.text || "";
        partialBuffer = "";
        if (msg.detected_language) detectedLiveLang = msg.detected_language;
        renderLiveTranscript();
        liveEditorEl.value = committedBuffer;
        liveEditorEl.classList.toggle("hidden", !committedBuffer);
        lastSavedSessionId = msg.record_id ? currentSessionId : null;
        updateRecordingUI();

        if (msg.record_id) {
          setBanner(liveStatusBanner, `Saved transcription #${msg.record_id} (${formatDuration(msg.audio_duration)}).`, "success");
          showToast(`Saved live transcription #${msg.record_id}.`, "success");
          await Promise.all([loadHistory(), refreshStats()]);
        } else if (msg.error) {
          setBanner(liveStatusBanner, msg.error, "error");
        } else {
          setBanner(liveStatusBanner, msg.message || "No speech detected.");
        }
      } else if (msg.type === "error") {
        setBanner(liveStatusBanner, msg.message || "Streaming error.", "error");
        showToast(msg.message || "Streaming error.", "error");
        if (isRecording) {
          forceStopLocalRecording();
        }
      }
    };

    ws.onclose = () => {
      wsStatusBadge.textContent = "WS: Disconnected";
      if (isRecording && !isStopping) {
        scheduleReconnect();
      } else {
        isStopping = false;
        updateRecordingUI();
      }
    };

    ws.onerror = () => {
      wsStatusBadge.textContent = "WS: Error";
    };
  }

  function scheduleReconnect() {
    if (reconnectAttempts >= 4) {
      setBanner(
        liveStatusBanner,
        "WebSocket connection lost and could not reconnect. Please restart recording.",
        "error"
      );
      forceStopLocalRecording();
      return;
    }
    const delayMs = 500 * Math.pow(2, reconnectAttempts);
    reconnectAttempts += 1;
    setBanner(
      liveStatusBanner,
      `Connection lost. Reconnecting in ${(delayMs / 1000).toFixed(1)}s (attempt ${reconnectAttempts}/4)...`,
      "error"
    );
    reconnectTimer = setTimeout(() => {
      if (isRecording && !isStopping) {
        connectWebSocket(true);
      }
    }, delayMs);
  }

  function forceStopLocalRecording() {
    clearFinalTimeout();
    isRecording = false;
    isStopping = false;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    stopTimer();
    cleanupAudioPipeline();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.close();
    }
    updateRecordingUI();
  }

  async function startRecording() {
    if (isRecording) return;
    currentSessionId = generateSessionId();
    lastSavedSessionId = null;
    committedBuffer = "";
    partialBuffer = "";
    detectedLiveLang = null;
    liveEditorEl.value = "";
    liveEditorEl.classList.add("hidden");
    renderLiveTranscript();
    recTimerEl.textContent = "00:00";

    try {
      setBanner(liveStatusBanner, "Requesting microphone permission...");
      await initAudioPipeline();
      isRecording = true;
      isStopping = false;
      updateRecordingUI();
      startTimer();
      connectWebSocket(false);
    } catch (err) {
      micPermBadge.textContent = "Mic: Denied / Unavailable";
      setBanner(liveStatusBanner, err.message || "Could not start microphone capture.", "error");
      showToast(err.message || "Microphone access failed.", "error");
      cleanupAudioPipeline();
      isRecording = false;
      updateRecordingUI();
    }
  }

  function stopRecording() {
    if (!isRecording || isStopping) return;
    isStopping = true;
    updateRecordingUI();
    setBanner(liveStatusBanner, "Finalizing transcription with Faster-Whisper...");
    if (workletNode) {
      try {
        workletNode.port.postMessage({ type: "flush" });
      } catch { /* ignore */ }
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stop" }));
      scheduleFinalTimeout();
    } else {
      forceStopLocalRecording();
      setBanner(liveStatusBanner, "Disconnected before final pass could run.", "error");
    }
  }

  btnStartRec.addEventListener("click", startRecording);
  btnStopRec.addEventListener("click", stopRecording);

  btnClearRec.addEventListener("click", () => {
    if (isRecording) forceStopLocalRecording();
    committedBuffer = "";
    partialBuffer = "";
    detectedLiveLang = null;
    currentSessionId = null;
    lastSavedSessionId = null;
    liveEditorEl.value = "";
    liveEditorEl.classList.add("hidden");
    recTimerEl.textContent = "00:00";
    setBanner(liveStatusBanner, "");
    renderLiveTranscript();
  });

  btnSaveRec.addEventListener("click", async () => {
    const text = (liveEditorEl.classList.contains("hidden")
      ? `${committedBuffer} ${partialBuffer}`
      : liveEditorEl.value
    ).trim();
    if (!text) {
      showToast("There is no transcript text to save.", "error");
      return;
    }
    btnSaveRec.disabled = true;
    try {
      const payload = {
        transcription_text: text,
        detected_language: detectedLiveLang,
        audio_format: "pcm_s16le",
        transcription_status: "completed",
      };
      if (currentSessionId && currentSessionId !== lastSavedSessionId) {
        payload.session_id = currentSessionId;
      }
      const res = await fetch("/api/transcriptions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to save transcription.");
      }
      const saved = await res.json();
      lastSavedSessionId = saved.session_id || currentSessionId;
      showToast(`Saved record #${saved.id}.`, "success");
      await Promise.all([loadHistory(), refreshStats()]);
    } catch (err) {
      showToast(err.message || "Save failed.", "error");
    } finally {
      btnSaveRec.disabled = false;
    }
  });

  // Upload Panel
  function validateSelectedFile(file) {
    if (!file) return false;
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    if (!ALLOWED_EXTENSIONS.has(ext)) {
      setBanner(uploadStatusBanner, `Unsupported extension '.${ext}'. Allowed: WAV, MP3, M4A, FLAC, OGG, WebM.`, "error");
      return false;
    }
    if (file.size === 0) {
      setBanner(uploadStatusBanner, "Selected audio file is empty.", "error");
      return false;
    }
    if (file.size > maxUploadMb * 1024 * 1024) {
      setBanner(uploadStatusBanner, `File exceeds ${maxUploadMb} MB upload limit.`, "error");
      return false;
    }
    return true;
  }

  function handleFileSelection(file) {
    setBanner(uploadStatusBanner, "");
    uploadResultCard.classList.add("hidden");
    if (!file) {
      selectedFileLabel.textContent = "No file selected";
      btnUploadSubmit.disabled = true;
      return;
    }
    selectedFileLabel.textContent = `${file.name} (${(file.size / (1024 * 1024)).toFixed(2)} MB)`;
    btnUploadSubmit.disabled = !validateSelectedFile(file);
  }

  fileInput.addEventListener("change", () => {
    handleFileSelection(fileInput.files[0]);
  });

  ["dragenter", "dragover"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });

  dropzone.addEventListener("drop", (e) => {
    const files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length > 0) {
      fileInput.files = files;
      handleFileSelection(files[0]);
    }
  });

  btnUploadClear.addEventListener("click", () => {
    uploadForm.reset();
    selectedFileLabel.textContent = "No file selected";
    btnUploadSubmit.disabled = true;
    uploadProgressWrap.classList.add("hidden");
    uploadResultCard.classList.add("hidden");
    setBanner(uploadStatusBanner, "");
  });

  uploadForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const file = fileInput.files[0];
    if (!validateSelectedFile(file)) return;

    const formData = new FormData();
    formData.append("file", file);

    btnUploadSubmit.disabled = true;
    uploadProgressWrap.classList.remove("hidden");
    uploadProgressBar.style.width = "0%";
    uploadProgressText.textContent = "0%";
    uploadResultCard.classList.add("hidden");
    setBanner(uploadStatusBanner, "Uploading audio...");

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/transcribe", true);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const pct = Math.round((event.loaded / event.total) * 100);
        uploadProgressBar.style.width = `${pct}%`;
        uploadProgressText.textContent = `${pct}%`;
        if (pct === 100) {
          setBanner(uploadStatusBanner, "Converting & transcribing with Faster-Whisper...");
        }
      }
    };

    xhr.onload = async () => {
      btnUploadSubmit.disabled = false;
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText);
          const rec = data.record;
          uploadResultMeta.replaceChildren(
            makeBadge(`ID: #${rec.id}`),
            makeBadge(`Lang: ${rec.detected_language || "auto"}`),
            makeBadge(`Mix: ${rec.script_mix}`),
            makeBadge(`Audio: ${formatDuration(rec.audio_duration)}`),
            makeBadge(`Time: ${data.processing_time_sec}s`)
          );
          uploadResultText.textContent = rec.transcription_text;
          uploadResultCard.classList.remove("hidden");
          setBanner(uploadStatusBanner, `Transcription #${rec.id} completed and saved.`, "success");
          showToast(`Uploaded audio transcribed (#${rec.id}).`, "success");
          await Promise.all([loadHistory(), refreshStats()]);
        } catch {
          setBanner(uploadStatusBanner, "Invalid server response.", "error");
        }
      } else {
        let msg = "Upload transcription failed.";
        try {
          const err = JSON.parse(xhr.responseText);
          if (err.detail) msg = err.detail;
        } catch { /* ignore */ }
        setBanner(uploadStatusBanner, msg, "error");
        showToast(msg, "error");
      }
    };

    xhr.onerror = () => {
      btnUploadSubmit.disabled = false;
      setBanner(uploadStatusBanner, "Network error during audio upload.", "error");
      showToast("Network error during upload.", "error");
    };

    xhr.send(formData);
  });

  // Search, filter, pagination
  searchInput.addEventListener("input", () => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
      currentPage = 1;
      loadHistory();
    }, 300);
  });

  mixFilter.addEventListener("change", () => {
    currentPage = 1;
    loadHistory();
  });

  btnRefreshHistory.addEventListener("click", () => {
    loadHistory();
    refreshStats();
  });

  btnPrevPage.addEventListener("click", () => {
    if (currentPage > 1) {
      currentPage -= 1;
      loadHistory();
    }
  });

  btnNextPage.addEventListener("click", () => {
    currentPage += 1;
    loadHistory();
  });

  // Initial load
  refreshHealth();
  refreshStats();
  loadHistory();
  setInterval(refreshHealth, 10000);
})();
