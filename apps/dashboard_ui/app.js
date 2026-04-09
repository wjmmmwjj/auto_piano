const state = {
  songs: [],
  tasks: [],
  selectedSongPath: "",
  ui: {
    songSignature: "",
    logTaskId: "",
    logText: "",
    logMeta: "",
    logTitle: "",
    resultHtml: "",
    emptyLogShown: false,
    aiLogTaskId: "",
    aiLogText: "",
    aiLogMeta: "",
    aiLogTitle: "",
    aiResultHtml: "",
    emptyAiLogShown: false,
  },
};

const elements = {
  summaryPlayStatus: document.getElementById("summaryPlayStatus"),
  summarySong: document.getElementById("summarySong"),
  summarySongMeta: document.getElementById("summarySongMeta"),
  playerProgressFill: document.getElementById("playerProgressFill"),
  playerElapsed: document.getElementById("playerElapsed"),
  playerPercent: document.getElementById("playerPercent"),
  playerTotal: document.getElementById("playerTotal"),
  stopPlaybackButton: document.getElementById("stopPlaybackButton"),
  songSearch: document.getElementById("songSearch"),
  songList: document.getElementById("songList"),
  taskTitle: document.getElementById("taskTitle"),
  taskMeta: document.getElementById("taskMeta"),
  taskResultCard: document.getElementById("taskResultCard"),
  taskLogs: document.getElementById("taskLogs"),
  soundStatusText: document.getElementById("soundStatusText"),
  soundToggleButton: document.getElementById("soundToggleButton"),
  transcribeQuery: document.getElementById("transcribeQuery"),
  transcribeStatusText: document.getElementById("transcribeStatusText"),
  transcribeButton: document.getElementById("transcribeButton"),
  aiTaskTitle: document.getElementById("aiTaskTitle"),
  aiTaskMeta: document.getElementById("aiTaskMeta"),
  aiResultCard: document.getElementById("aiResultCard"),
  aiTaskLogs: document.getElementById("aiTaskLogs"),
  toastLayer: document.getElementById("toastLayer"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};

  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }

  return payload;
}

function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  elements.toastLayer.appendChild(toast);
  window.setTimeout(() => toast.remove(), 3200);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setText(element, nextValue) {
  if (element.textContent !== nextValue) {
    element.textContent = nextValue;
  }
}

function setHtml(element, nextValue) {
  if (element.innerHTML !== nextValue) {
    element.innerHTML = nextValue;
  }
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "--";
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remain = Math.round(seconds % 60);
  return `${minutes}m ${remain}s`;
}

function formatClock(seconds) {
  const safe = Math.max(0, Math.floor(seconds || 0));
  const minutes = Math.floor(safe / 60);
  const remain = safe % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}`;
}

function formatTime(timestamp) {
  if (!timestamp) {
    return "未知時間";
  }
  return new Date(timestamp * 1000).toLocaleString("zh-TW", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function isActiveStatus(status) {
  return status === "running" || status === "stopping";
}

function isNearBottom(element, threshold = 28) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= threshold;
}

function currentSong() {
  return state.songs.find((song) => song.path === state.selectedSongPath) || null;
}

function activeTask(kind) {
  return state.tasks.find((task) => task.kind === kind && isActiveStatus(task.status)) || null;
}

function latestTaskByKind(kind) {
  return [...state.tasks]
    .filter((task) => task.kind === kind)
    .sort((a, b) => b.started_at - a.started_at)[0] || null;
}

function currentPlaybackTask() {
  return activeTask("playback");
}

function currentMainLogTask() {
  const running = state.tasks
    .filter((task) => task.kind !== "transcribe")
    .filter((task) => isActiveStatus(task.status))
    .sort((a, b) => b.started_at - a.started_at);

  if (running.length) {
    return running[0];
  }

  return [...state.tasks]
    .filter((task) => task.kind !== "transcribe")
    .sort((a, b) => b.started_at - a.started_at)[0] || null;
}

function currentAiLogTask() {
  return activeTask("transcribe") || latestTaskByKind("transcribe");
}

function currentPlaybackSongPath() {
  const playbackTask = currentPlaybackTask();
  return playbackTask?.metadata?.song_path || "";
}

function buildSongSignature() {
  const playingPath = currentPlaybackSongPath();
  const keyword = elements.songSearch.value.trim().toLowerCase();
  const base = state.songs.map((song) => `${song.path}|${song.modified_at}`).join("::");
  return `${keyword}__${state.selectedSongPath}__${playingPath}__${base}`;
}

function renderPlayer() {
  const playbackTask = currentPlaybackTask();
  const selectedSong = currentSong();

  if (!playbackTask) {
    setText(elements.summaryPlayStatus, "待機中");
    setText(elements.summarySong, selectedSong ? selectedSong.name : "尚未播放歌曲");
    setText(
      elements.summarySongMeta,
      selectedSong ? "已選取，按左側播放即可開始" : "從左側歌單挑一首歌後開始播放",
    );
    elements.playerProgressFill.style.width = "0%";
    setText(elements.playerElapsed, "00:00");
    setText(elements.playerPercent, "0%");
    setText(elements.playerTotal, "00:00");
    elements.stopPlaybackButton.disabled = true;
    setText(elements.stopPlaybackButton, "停止播放");
    return;
  }

  const total = Number(playbackTask.metadata?.total_duration_sec || 0);
  const elapsed = total > 0 ? Math.min(total, playbackTask.duration_sec) : playbackTask.duration_sec;
  const percent = total > 0 ? Math.min(100, (elapsed / total) * 100) : 0;

  setText(elements.summaryPlayStatus, playbackTask.status === "stopping" ? "停止播放中" : "目前播放");
  setText(elements.summarySong, playbackTask.metadata?.song_name || playbackTask.title || "未命名歌曲");
  setText(
    elements.summarySongMeta,
    total > 0 ? `${formatClock(elapsed)} / ${formatClock(total)}` : `已播放 ${formatDuration(playbackTask.duration_sec)}`,
  );
  elements.playerProgressFill.style.width = `${percent}%`;
  setText(elements.playerElapsed, formatClock(elapsed));
  setText(elements.playerPercent, total > 0 ? `${Math.round(percent)}%` : "估算中");
  setText(elements.playerTotal, total > 0 ? formatClock(total) : "--:--");
  elements.stopPlaybackButton.disabled = playbackTask.status === "stopping";
  setText(elements.stopPlaybackButton, playbackTask.status === "stopping" ? "停止中..." : "停止播放");
}

function renderSongs(force = false) {
  const signature = buildSongSignature();
  if (!force && state.ui.songSignature === signature) {
    return;
  }

  const keyword = elements.songSearch.value.trim().toLowerCase();
  const playingPath = currentPlaybackSongPath();
  const filtered = state.songs.filter((song) => song.name.toLowerCase().includes(keyword));

  if (!filtered.length) {
    elements.songList.innerHTML = '<div class="empty-state">找不到符合條件的歌曲。</div>';
    state.ui.songSignature = signature;
    return;
  }

  elements.songList.innerHTML = filtered
    .map((song) => {
      const isSelected = song.path === state.selectedSongPath;
      const isPlaying = song.path === playingPath;
      return `
        <article class="song-item${isSelected ? " is-selected" : ""}${isPlaying ? " is-playing" : ""}" data-song-path="${escapeHtml(song.path)}">
          <div class="song-main">
            <div class="song-topline">
              <div class="song-name">${escapeHtml(song.name)}</div>
              ${isPlaying ? '<span class="song-badge">播放中</span>' : ""}
            </div>
            <div class="song-meta">${escapeHtml(song.relative_path)} · ${escapeHtml(formatTime(song.modified_at))}</div>
          </div>
          <button class="mini-button song-play" type="button" data-play-song="${escapeHtml(song.path)}" ${isPlaying ? "disabled" : ""}>
            ${isPlaying ? "播放中" : "播放"}
          </button>
        </article>
      `;
    })
    .join("");

  state.ui.songSignature = signature;
}

function renderSound() {
  const soundTask = activeTask("sound");
  const isRunning = Boolean(soundTask);

  setText(
    elements.soundStatusText,
    isRunning ? `已開啟，持續 ${formatDuration(soundTask.duration_sec)}` : "目前已關閉",
  );
  setText(elements.soundToggleButton, isRunning ? "關閉聲音" : "開啟聲音");
  elements.soundToggleButton.className = isRunning ? "danger-button" : "primary-button";
}

function renderTranscribe() {
  const transcribeTask = activeTask("transcribe");
  const isRunning = Boolean(transcribeTask);

  setText(
    elements.transcribeStatusText,
    isRunning ? `Auto 轉譜進行中，已執行 ${formatDuration(transcribeTask.duration_sec)}` : "固定使用 Auto 模式，只要貼上來源後開始轉譜。",
  );
  setText(elements.transcribeButton, isRunning ? "停止轉譜" : "開始轉譜");
  elements.transcribeButton.className = isRunning ? "danger-button" : "primary-button";
  elements.transcribeQuery.disabled = isRunning;
}

function buildResultHtml(task) {
  if (!task?.result || !Object.keys(task.result).length) {
    return "";
  }

  const lines = [];
  if (task.result.song_name) {
    lines.push(`歌曲：${escapeHtml(task.result.song_name)}`);
  }
  if (task.result.provider_name) {
    lines.push(`轉譜來源：${escapeHtml(task.result.provider_name)}`);
  }
  if (task.result.score_path) {
    lines.push(`輸出檔案：${escapeHtml(task.result.score_path)}`);
  }
  if (task.result.youtube_url) {
    lines.push(`影片來源：${escapeHtml(task.result.youtube_url)}`);
  }

  if (!lines.length) {
    return "";
  }

  return `<strong>任務結果</strong><br>${lines.join("<br>")}`;
}

function renderLogs() {
  const task = currentMainLogTask();

  if (!task) {
    if (!state.ui.emptyLogShown) {
      setText(elements.taskTitle, "目前沒有任務");
      setText(elements.taskMeta, "開始播放或開啟聲音後，這裡會顯示主流程日誌。");
      setText(elements.taskLogs, "等待新的任務輸出...");
      elements.taskResultCard.classList.add("hidden");
      elements.taskResultCard.innerHTML = "";
      state.ui.logTaskId = "";
      state.ui.logText = "等待新的任務輸出...";
      state.ui.logMeta = elements.taskMeta.textContent;
      state.ui.logTitle = elements.taskTitle.textContent;
      state.ui.resultHtml = "";
      state.ui.emptyLogShown = true;
    }
    return;
  }

  state.ui.emptyLogShown = false;

  const nextTitle = task.title;
  const nextMeta = `${task.kind} · ${task.status} · ${formatTime(task.started_at)} · ${formatDuration(task.duration_sec)}`;
  const nextLogText = (task.logs || task.log_tail || []).join("\n") || "目前沒有新的日誌輸出。";

  if (state.ui.logTitle !== nextTitle) {
    setText(elements.taskTitle, nextTitle);
    state.ui.logTitle = nextTitle;
  }

  if (state.ui.logMeta !== nextMeta) {
    setText(elements.taskMeta, nextMeta);
    state.ui.logMeta = nextMeta;
  }

  if (state.ui.logTaskId !== task.id || state.ui.logText !== nextLogText) {
    const shouldStick = state.ui.logTaskId !== task.id || isNearBottom(elements.taskLogs);
    const previousBottomOffset = elements.taskLogs.scrollHeight - elements.taskLogs.scrollTop;
    setText(elements.taskLogs, nextLogText);

    if (shouldStick) {
      elements.taskLogs.scrollTop = elements.taskLogs.scrollHeight;
    } else {
      elements.taskLogs.scrollTop = Math.max(0, elements.taskLogs.scrollHeight - previousBottomOffset);
    }

    state.ui.logTaskId = task.id;
    state.ui.logText = nextLogText;
  }

  const nextResultHtml = buildResultHtml(task);

  if (state.ui.resultHtml !== nextResultHtml) {
    if (nextResultHtml) {
      setHtml(elements.taskResultCard, nextResultHtml);
      elements.taskResultCard.classList.remove("hidden");
    } else {
      elements.taskResultCard.classList.add("hidden");
      elements.taskResultCard.innerHTML = "";
    }
    state.ui.resultHtml = nextResultHtml;
  }
}

function renderAiLogs() {
  const task = currentAiLogTask();

  if (!task) {
    if (!state.ui.emptyAiLogShown) {
      setText(elements.aiTaskTitle, "AI 日誌");
      setText(elements.aiTaskMeta, "尚未開始 AI 轉譜任務。");
      setText(elements.aiTaskLogs, "等待 AI 任務輸出...");
      elements.aiResultCard.classList.add("hidden");
      elements.aiResultCard.innerHTML = "";
      state.ui.aiLogTaskId = "";
      state.ui.aiLogText = "等待 AI 任務輸出...";
      state.ui.aiLogMeta = elements.aiTaskMeta.textContent;
      state.ui.aiLogTitle = elements.aiTaskTitle.textContent;
      state.ui.aiResultHtml = "";
      state.ui.emptyAiLogShown = true;
    }
    return;
  }

  state.ui.emptyAiLogShown = false;

  const nextTitle = task.status === "running" || task.status === "stopping" ? "AI 即時日誌" : "最近一次 AI 任務";
  const nextMeta = `${task.status} · ${formatTime(task.started_at)} · ${formatDuration(task.duration_sec)}`;
  const nextLogText = (task.logs || task.log_tail || []).join("\n") || "目前沒有新的 AI 日誌輸出。";

  if (state.ui.aiLogTitle !== nextTitle) {
    setText(elements.aiTaskTitle, nextTitle);
    state.ui.aiLogTitle = nextTitle;
  }

  if (state.ui.aiLogMeta !== nextMeta) {
    setText(elements.aiTaskMeta, nextMeta);
    state.ui.aiLogMeta = nextMeta;
  }

  if (state.ui.aiLogTaskId !== task.id || state.ui.aiLogText !== nextLogText) {
    const shouldStick = state.ui.aiLogTaskId !== task.id || isNearBottom(elements.aiTaskLogs);
    const previousBottomOffset = elements.aiTaskLogs.scrollHeight - elements.aiTaskLogs.scrollTop;
    setText(elements.aiTaskLogs, nextLogText);

    if (shouldStick) {
      elements.aiTaskLogs.scrollTop = elements.aiTaskLogs.scrollHeight;
    } else {
      elements.aiTaskLogs.scrollTop = Math.max(0, elements.aiTaskLogs.scrollHeight - previousBottomOffset);
    }

    state.ui.aiLogTaskId = task.id;
    state.ui.aiLogText = nextLogText;
  }

  const nextResultHtml = buildResultHtml(task);
  if (state.ui.aiResultHtml !== nextResultHtml) {
    if (nextResultHtml) {
      setHtml(elements.aiResultCard, nextResultHtml);
      elements.aiResultCard.classList.remove("hidden");
    } else {
      elements.aiResultCard.classList.add("hidden");
      elements.aiResultCard.innerHTML = "";
    }
    state.ui.aiResultHtml = nextResultHtml;
  }
}

function renderStaticSections() {
  renderPlayer();
  renderSongs();
  renderSound();
  renderTranscribe();
  renderLogs();
  renderAiLogs();
}

async function refreshSongs() {
  const payload = await api("/api/songs");
  state.songs = payload.songs || [];

  if (!state.selectedSongPath && state.songs.length) {
    state.selectedSongPath = state.songs[0].path;
  }

  if (state.selectedSongPath && !state.songs.some((song) => song.path === state.selectedSongPath)) {
    state.selectedSongPath = state.songs[0]?.path || "";
  }

  renderSongs(true);
  renderPlayer();
}

async function refreshTasks() {
  const previousPlayingPath = currentPlaybackSongPath();

  const payload = await api("/api/tasks");
  state.tasks = payload.tasks || [];

  const detailTargets = [currentMainLogTask(), currentAiLogTask()]
    .filter(Boolean)
    .reduce((map, task) => {
      map.set(task.id, task);
      return map;
    }, new Map());

  for (const task of detailTargets.values()) {
    try {
      const detail = await api(`/api/tasks/${task.id}`);
      const index = state.tasks.findIndex((item) => item.id === detail.id);
      if (index >= 0) {
        state.tasks[index] = detail;
      }
    } catch (error) {
      console.warn(error);
    }
  }

  renderPlayer();
  renderSound();
  renderTranscribe();
  renderLogs();
  renderAiLogs();

  if (previousPlayingPath !== currentPlaybackSongPath()) {
    renderSongs(true);
  }
}

async function refreshAll() {
  await Promise.all([refreshSongs(), refreshTasks()]);
}

async function createTask(path, payload, successMessage) {
  await api(path, {
    method: "POST",
    body: JSON.stringify(payload || {}),
  });
  showToast(successMessage, "success");
  await refreshTasks();
}

function requireSongPath(songPath) {
  const value = (songPath || "").trim();
  if (!value) {
    showToast("請先選一首歌。", "error");
    return "";
  }
  return value;
}

async function withErrorToast(action, fallbackMessage) {
  try {
    await action();
  } catch (error) {
    showToast(`${fallbackMessage}：${error.message}`, "error");
  }
}

async function stopTaskAndWait(taskId, timeoutMs = 12000) {
  await api(`/api/tasks/${taskId}/stop`, {
    method: "POST",
    body: JSON.stringify({}),
  });

  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const detail = await api(`/api/tasks/${taskId}`);
    if (!isActiveStatus(detail.status)) {
      await refreshTasks();
      return detail;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 350));
  }

  throw new Error("停止任務逾時");
}

async function startPlayback(songPath) {
  const safeSongPath = requireSongPath(songPath);
  if (!safeSongPath) {
    return;
  }

  const runningPlayback = currentPlaybackTask();
  if (runningPlayback && runningPlayback.metadata?.song_path === safeSongPath) {
    showToast("這首歌正在播放中。");
    return;
  }

  if (runningPlayback) {
    showToast("正在切換歌曲...", "success");
    await stopTaskAndWait(runningPlayback.id);
  }

  await createTask("/api/tasks/playback", {
    song_path: safeSongPath,
  }, "已開始播放");
}

function bindEvents() {
  elements.songSearch.addEventListener("input", () => renderSongs(true));

  elements.songList.addEventListener("click", (event) => {
    const playButton = event.target.closest("[data-play-song]");
    if (playButton) {
      const songPath = playButton.dataset.playSong || "";
      state.selectedSongPath = songPath;
      renderSongs(true);
      renderPlayer();
      withErrorToast(() => startPlayback(songPath), "播放歌曲失敗");
      return;
    }

    const item = event.target.closest("[data-song-path]");
    if (!item) {
      return;
    }

    state.selectedSongPath = item.dataset.songPath || "";
    renderSongs(true);
    renderPlayer();
  });

  elements.stopPlaybackButton.addEventListener("click", () => withErrorToast(async () => {
    const playbackTask = currentPlaybackTask();
    if (!playbackTask) {
      return;
    }
    await api(`/api/tasks/${playbackTask.id}/stop`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    showToast("正在停止播放", "success");
    await refreshTasks();
  }, "停止播放失敗"));

  elements.soundToggleButton.addEventListener("click", () => withErrorToast(async () => {
    const soundTask = activeTask("sound");
    if (soundTask) {
      await api(`/api/tasks/${soundTask.id}/stop`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      showToast("已送出關閉聲音指令", "success");
      await refreshTasks();
      return;
    }

    await createTask("/api/tasks/sound", {
      backend: "auto",
    }, "聲音橋接已啟動");
  }, "切換聲音失敗"));

  elements.transcribeButton.addEventListener("click", () => withErrorToast(async () => {
    const transcribeTask = activeTask("transcribe");
    if (transcribeTask) {
      await api(`/api/tasks/${transcribeTask.id}/stop`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      showToast("已送出停止轉譜指令", "success");
      await refreshTasks();
      return;
    }

    const query = elements.transcribeQuery.value.trim();
    if (!query) {
      showToast("請輸入歌名或 YouTube 連結。", "error");
      return;
    }

    await createTask("/api/tasks/transcribe", {
      query,
      mode: "auto",
    }, "已開始 AI 轉譜");
  }, "AI 轉譜失敗"));
}

async function init() {
  bindEvents();
  renderStaticSections();
  await withErrorToast(refreshAll, "載入 Dashboard 失敗");
  window.setInterval(() => withErrorToast(refreshTasks, "更新任務失敗"), 2200);
  window.setInterval(() => withErrorToast(refreshSongs, "更新歌單失敗"), 12000);
}

init();
