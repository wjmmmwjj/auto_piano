/* Auto Piano Dashboard — Frontend Logic */

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

const el = {
  summaryPlayStatus: document.getElementById("summaryPlayStatus"),
  summarySong: document.getElementById("summarySong"),
  summarySongMeta: document.getElementById("summarySongMeta"),
  playerProgressFill: document.getElementById("playerProgressFill"),
  playerElapsed: document.getElementById("playerElapsed"),
  playerPercent: document.getElementById("playerPercent"),
  playerTotal: document.getElementById("playerTotal"),
  stopPlaybackButton: document.getElementById("stopPlaybackButton"),
  safeZeroButton: document.getElementById("safeZeroButton"),
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

/* ===== Helpers ===== */
async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json", ...(opts.headers || {}) }, ...opts });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(data.error || `Request failed: ${res.status}`);
  return data;
}

function toast(msg, type = "info") {
  const d = document.createElement("div");
  d.className = `toast ${type}`;
  
  let iconHtml = "";
  if (type === "success") {
    iconHtml = `<svg class="toast-icon success-icon"><use href="#icon-success"></use></svg>`;
  } else if (type === "error") {
    iconHtml = `<svg class="toast-icon error-icon"><use href="#icon-error"></use></svg>`;
  }
  
  d.innerHTML = `${iconHtml}<div class="toast-content">${msg}</div>`;
  el.toastLayer.appendChild(d);
  setTimeout(() => d.remove(), 4000);
}

function esc(v) {
  return String(v).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}

function setText(e, v) { if (e && e.textContent !== v) e.textContent = v; }
function setHtml(e, v) { if (e && e.innerHTML !== v) e.innerHTML = v; }

function fmtDur(s) {
  if (!Number.isFinite(s) || s < 0) return "--";
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s/60)}m ${Math.round(s%60)}s`;
}

function fmtClock(s) {
  const t = Math.max(0, Math.floor(s || 0));
  return `${String(Math.floor(t/60)).padStart(2,"0")}:${String(t%60).padStart(2,"0")}`;
}

function fmtTime(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString("zh-TW", { month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit" });
}

function formatDetailedTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const YYYY = d.getFullYear();
  const MM = String(d.getMonth() + 1).padStart(2, "0");
  const DD = String(d.getDate()).padStart(2, "0");
  const HH = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `[${YYYY}-${MM}-${DD} ${HH}:${mm}:${ss}]`;
}

function isActive(s) { return s === "running" || s === "stopping"; }
function nearBottom(e, t = 28) { return e.scrollHeight - e.scrollTop - e.clientHeight <= t; }
function curSong() { return state.songs.find(s => s.path === state.selectedSongPath) || null; }
function activeTask(k) { return state.tasks.find(t => t.kind === k && isActive(t.status)) || null; }
function latestTask(k) { return [...state.tasks].filter(t => t.kind === k).sort((a,b) => b.started_at - a.started_at)[0] || null; }
function playbackTask() { return activeTask("playback"); }

function mainLogTask() {
  const running = state.tasks.filter(t => t.kind !== "transcribe").filter(t => isActive(t.status)).sort((a,b) => b.started_at - a.started_at);
  if (running.length) return running[0];
  return [...state.tasks].filter(t => t.kind !== "transcribe").sort((a,b) => b.started_at - a.started_at)[0] || null;
}

function getTaskDisplayName(t) {
  if (t.kind === "safezero") return "全部按鍵歸零";
  if (t.kind === "playback") return `播放 ${t.metadata?.song_name || "未知歌曲"}`;
  if (t.kind === "sound") return "聲音橋接功能";
  if (t.kind === "transcribe") {
    let q = t.metadata?.query || "未知來源";
    if (q.length > 25) q = q.substring(0, 25) + "...";
    return `AI 轉譜 (${q})`;
  }
  return t.title;
}

function compressLogs(lines) {
  const res = [];
  for (const line of lines) {
    if (line.includes("Progress:")) {
      const trimmed = line.trim();
      const prefixMatch = trimmed.match(/^Progress:\s+(\w+)/);
      if (prefixMatch) {
        const prefix = prefixMatch[0];
        if (res.length > 0 && res[res.length - 1].trim().startsWith(prefix)) {
          res[res.length - 1] = line;
          continue;
        }
      } else if (res.length > 0 && res[res.length - 1].trim().startsWith("Progress:")) {
        res[res.length - 1] = line;
        continue;
      }
    }
    res.push(line);
  }
  return res;
}

function aiLogTask() { return activeTask("transcribe") || latestTask("transcribe"); }
function playbackPath() { return playbackTask()?.metadata?.song_path || ""; }

function songSig() {
  const pp = playbackPath();
  const kw = el.songSearch.value.trim().toLowerCase();
  const base = state.songs.map(s => `${s.path}|${s.modified_at}`).join("::");
  return `${kw}__${state.selectedSongPath}__${pp}__${base}`;
}

/* ===== Render: Player ===== */
function renderPlayer() {
  const pb = playbackTask();
  const sel = curSong();
  const sz = activeTask("safezero");

  if (!pb) {
    setText(el.summaryPlayStatus, "待機中");
    setText(el.summarySong, sel ? sel.name : "尚未選擇歌曲");
    setText(el.summarySongMeta, sel ? "已選取" : "");
    el.playerProgressFill.style.width = "0%";
    setText(el.playerElapsed, "00:00");
    setText(el.playerPercent, "0%");
    setText(el.playerTotal, "00:00");
    el.stopPlaybackButton.disabled = true;
    setText(el.stopPlaybackButton, "停止播放");
    el.safeZeroButton.disabled = !!sz;
    setText(el.safeZeroButton, sz ? "歸零中..." : "全部按鍵歸零");
    return;
  }

  const total = Number(pb.metadata?.total_duration_sec || 0);
  const elapsed = total > 0 ? Math.min(total, pb.duration_sec) : pb.duration_sec;
  const pct = total > 0 ? Math.min(100, (elapsed / total) * 100) : 0;

  setText(el.summaryPlayStatus, pb.status === "stopping" ? "停止中" : "播放中");
  setText(el.summarySong, pb.metadata?.song_name || pb.title || "未知歌曲");
  setText(el.summarySongMeta, total > 0 ? `${fmtClock(elapsed)} / ${fmtClock(total)}` : `${fmtDur(pb.duration_sec)}`);
  el.playerProgressFill.style.width = `${pct}%`;
  setText(el.playerElapsed, fmtClock(elapsed));
  setText(el.playerPercent, total > 0 ? `${Math.round(pct)}%` : "...");
  setText(el.playerTotal, total > 0 ? fmtClock(total) : "--:--");
  el.stopPlaybackButton.disabled = pb.status === "stopping";
  setText(el.stopPlaybackButton, pb.status === "stopping" ? "停止中..." : "停止播放");
  el.safeZeroButton.disabled = true;
  setText(el.safeZeroButton, "全部按鍵歸零");
}

/* ===== Render: Songs ===== */
function renderSongs(force = false) {
  const sig = songSig();
  if (!force && state.ui.songSignature === sig) return;
  const kw = el.songSearch.value.trim().toLowerCase();
  const pp = playbackPath();
  const filtered = state.songs.filter(s => s.name.toLowerCase().includes(kw));

  if (!filtered.length) {
    el.songList.innerHTML = '<div class="empty-state">找不到符合條件的歌曲。</div>';
    state.ui.songSignature = sig;
    return;
  }

  el.songList.innerHTML = filtered.map(s => {
    const isSel = s.path === state.selectedSongPath;
    const isPlay = s.path === pp;
    return `
      <article class="song-item${isSel ? " is-selected" : ""}${isPlay ? " is-playing" : ""}" data-song-path="${esc(s.path)}">
        <div class="song-main">
          <div class="song-topline">
            <div class="song-name">${esc(s.name)}</div>
            ${isPlay ? '<span class="song-badge">播放中</span>' : ""}
          </div>
          <div class="song-meta">${esc(s.relative_path)} · ${esc(fmtTime(s.modified_at))}</div>
        </div>
        <button class="mini-button song-play" type="button" data-play-song="${esc(s.path)}" ${isPlay ? "disabled" : ""}>
          ${isPlay ? "播放中" : "播放"}
        </button>
      </article>`;
  }).join("");
  state.ui.songSignature = sig;
}

/* ===== Render: Sound ===== */
function renderSound() {
  const st = activeTask("sound");
  const on = Boolean(st);
  setText(el.soundStatusText, on ? `開啟 · ${fmtDur(st.duration_sec)}` : "已關閉");
  setText(el.soundToggleButton, on ? "關閉聲音" : "開啟聲音");
  el.soundToggleButton.className = on ? "btn btn-danger" : "btn btn-primary";
}

/* ===== Render: Transcribe ===== */
function renderTranscribe() {
  const tt = activeTask("transcribe");
  const on = Boolean(tt);
  setText(el.transcribeStatusText, on ? `執行中 · ${fmtDur(tt.duration_sec)}` : "準備好開始轉譜。");
  setText(el.transcribeButton, on ? "停止轉譜" : "開始轉譜");
  el.transcribeButton.className = on ? "btn btn-danger" : "btn btn-primary";
  el.transcribeQuery.disabled = on;
}

/* ===== Render: Result HTML ===== */
function buildResult(task) {
  return "";
}

/* ===== Render: Logs ===== */
function renderLogs() {
  const allTasks = [...state.tasks].sort((a,b) => a.started_at - b.started_at);
  
  if (!allTasks.length) {
    if (!state.ui.emptyLogShown) {
      setText(el.taskTitle, "執行日誌");
      setText(el.taskMeta, "等待任務...");
      setText(el.taskLogs, "就緒。");
      el.taskResultCard.classList.add("hidden");
      el.taskResultCard.innerHTML = "";
      state.ui.logTaskId = ""; state.ui.logText = "就緒。"; state.ui.resultHtml = "";
      state.ui.emptyLogShown = true;
    }
    return;
  }
  state.ui.emptyLogShown = false;
  
  const events = [];
  for (const t of allTasks) {
    const titleObj = getTaskDisplayName(t);
    events.push(`${formatDetailedTime(t.started_at)} 開始：${titleObj}`);
    if (t.ended_at) {
      let statusStr = t.status === "completed" ? "完成" : (t.status === "failed" ? "失敗" : "中斷");
      events.push(`${formatDetailedTime(t.ended_at)} ${titleObj}${statusStr}`);
    } else if (t.status === "stopping") {
      events.push(`${formatDetailedTime(Date.now() / 1000)} 正在停止：${titleObj}...`);
    } else {
      // If running and it's transcribe, could optionally show progress 
      // but the user only asked for start and stop.
    }
  }

  const logText = events.join("\n") || "沒有輸出。";
  const activeCount = allTasks.filter(t => isActive(t.status)).length;
  const meta = activeCount > 0 ? `有 ${activeCount} 個任務正在執行` : "所有任務已結束";

  if (state.ui.logTitle !== "執行日誌") { setText(el.taskTitle, "執行日誌"); state.ui.logTitle = "執行日誌"; }
  if (state.ui.logMeta !== meta) { setText(el.taskMeta, meta); state.ui.logMeta = meta; }
  
  if (state.ui.logText !== logText) {
    const stick = nearBottom(el.taskLogs);
    setText(el.taskLogs, logText);
    if (stick) el.taskLogs.scrollTop = el.taskLogs.scrollHeight;
    state.ui.logText = logText;
  }
  
  const mainTasksOnly = allTasks.filter(t => t.kind !== "transcribe");
  const lastMainTask = mainTasksOnly[mainTasksOnly.length - 1];
  const rh = buildResult(lastMainTask);
  if (state.ui.resultHtml !== rh) {
    if (rh) { setHtml(el.taskResultCard, rh); el.taskResultCard.classList.remove("hidden"); }
    else { el.taskResultCard.classList.add("hidden"); el.taskResultCard.innerHTML = ""; }
    state.ui.resultHtml = rh;
  }
}

/* ===== Render: AI Logs ===== */
function renderAiLogs() {
  const task = aiLogTask();
  if (!task) {
    if (!state.ui.emptyAiLogShown) {
      setText(el.aiTaskTitle, "AI 日誌");
      setText(el.aiTaskMeta, "尚未有 AI 任務。");
      setText(el.aiTaskLogs, "等待 AI 輸出...");
      el.aiResultCard.classList.add("hidden");
      el.aiResultCard.innerHTML = "";
      state.ui.aiLogTaskId = ""; state.ui.aiLogText = "等待 AI 輸出...";
      state.ui.aiResultHtml = ""; state.ui.emptyAiLogShown = true;
    }
    return;
  }
  state.ui.emptyAiLogShown = false;
  const title = isActive(task.status) ? "AI 即時轉寫" : "最近一次 AI 任務";
  const meta = `${task.status} · ${fmtTime(task.started_at)} · ${fmtDur(task.duration_sec)}`;
  const rawLogs = task.logs || task.log_tail || [];
  const logText = compressLogs(rawLogs).join("\n") || "沒有 AI 輸出。";

  if (state.ui.aiLogTitle !== title) { setText(el.aiTaskTitle, title); state.ui.aiLogTitle = title; }
  if (state.ui.aiLogMeta !== meta) { setText(el.aiTaskMeta, meta); state.ui.aiLogMeta = meta; }
  if (state.ui.aiLogTaskId !== task.id || state.ui.aiLogText !== logText) {
    const stick = state.ui.aiLogTaskId !== task.id || nearBottom(el.aiTaskLogs);
    setText(el.aiTaskLogs, logText);
    if (stick) el.aiTaskLogs.scrollTop = el.aiTaskLogs.scrollHeight;
    state.ui.aiLogTaskId = task.id; state.ui.aiLogText = logText;
  }
  const rh = buildResult(task);
  if (state.ui.aiResultHtml !== rh) {
    if (rh) { setHtml(el.aiResultCard, rh); el.aiResultCard.classList.remove("hidden"); }
    else { el.aiResultCard.classList.add("hidden"); el.aiResultCard.innerHTML = ""; }
    state.ui.aiResultHtml = rh;
  }
}

function renderAll() {
  renderPlayer(); renderSongs(); renderSound(); renderTranscribe(); renderLogs(); renderAiLogs();
}

/* ===== Data Fetching ===== */
async function refreshSongs() {
  const d = await api("/api/songs");
  state.songs = d.songs || [];
  if (!state.selectedSongPath && state.songs.length) state.selectedSongPath = state.songs[0].path;
  if (state.selectedSongPath && !state.songs.some(s => s.path === state.selectedSongPath)) state.selectedSongPath = state.songs[0]?.path || "";
  renderSongs(true); renderPlayer();
}

async function refreshTasks() {
  const prev = playbackPath();
  const d = await api("/api/tasks");
  state.tasks = d.tasks || [];

  const targets = [mainLogTask(), aiLogTask()].filter(Boolean).reduce((m,t) => { m.set(t.id,t); return m; }, new Map());
  for (const t of targets.values()) {
    try { const det = await api(`/api/tasks/${t.id}`); const i = state.tasks.findIndex(x => x.id === det.id); if (i >= 0) state.tasks[i] = det; } catch(e) { console.warn(e); }
  }
  renderAll();
  if (prev !== playbackPath()) renderSongs(true);
}

async function refreshAll() { await Promise.all([refreshSongs(), refreshTasks()]); }

async function createTask(path, payload, msg) {
  await api(path, { method: "POST", body: JSON.stringify(payload || {}) });
  toast(msg, "success");
  await refreshTasks();
}

function requireSongPath(p) { const v = (p||"").trim(); if (!v) { toast("請先選取一首歌。", "error"); return ""; } return v; }

async function withErr(fn, fallback) { try { await fn(); } catch(e) { toast(`${fallback}: ${e.message}`, "error"); } }

async function stopAndWait(id, timeout = 12000) {
  await api(`/api/tasks/${id}/stop`, { method: "POST", body: JSON.stringify({}) });
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const d = await api(`/api/tasks/${id}`);
    if (!isActive(d.status)) { await refreshTasks(); return d; }
    await new Promise(r => setTimeout(r, 350));
  }
  throw new Error("停止任務逾時");
}

async function startPlayback(path) {
  const sp = requireSongPath(path);
  if (!sp) return;
  const cur = playbackTask();
  if (cur && cur.metadata?.song_path === sp) { toast("歌曲已經在播放中。", "error"); return; }
  if (cur) { toast("正在切換歌曲...", "success"); await stopAndWait(cur.id); }
  await createTask("/api/tasks/playback", { song_path: sp }, "已開始播放歌曲");
}

/* ===== Events ===== */
function bindEvents() {
  el.songSearch.addEventListener("input", () => renderSongs(true));

  el.songList.addEventListener("click", e => {
    const pb = e.target.closest("[data-play-song]");
    if (pb) {
      const sp = pb.dataset.playSong || "";
      state.selectedSongPath = sp;
      renderSongs(true); renderPlayer();
      withErr(() => startPlayback(sp), "播放失敗");
      return;
    }
    const item = e.target.closest("[data-song-path]");
    if (item) { state.selectedSongPath = item.dataset.songPath || ""; renderSongs(true); renderPlayer(); }
  });

  el.stopPlaybackButton.addEventListener("click", () => withErr(async () => {
    const pb = playbackTask();
    if (!pb) return;
    await api(`/api/tasks/${pb.id}/stop`, { method: "POST", body: JSON.stringify({}) });
    toast("正在停止播放", "success");
    await refreshTasks();
  }, "停止失敗"));

  el.safeZeroButton.addEventListener("click", () => withErr(async () => {
    if (activeTask("safezero")) return;
    await createTask("/api/tasks/safezero", {}, "已發送按鍵歸零指令");
  }, "歸零失敗"));

  el.soundToggleButton.addEventListener("click", () => withErr(async () => {
    const st = activeTask("sound");
    if (st) {
      await api(`/api/tasks/${st.id}/stop`, { method: "POST", body: JSON.stringify({}) });
      toast("已送出關閉聲音指令", "success");
      await refreshTasks();
      return;
    }
    await createTask("/api/tasks/sound", { backend: "auto" }, "聲音橋接已啟動");
  }, "操作失敗"));

  el.transcribeButton.addEventListener("click", () => withErr(async () => {
    const tt = activeTask("transcribe");
    if (tt) {
      await api(`/api/tasks/${tt.id}/stop`, { method: "POST", body: JSON.stringify({}) });
      toast("已送出停止指令", "success");
      await refreshTasks();
      return;
    }
    const q = el.transcribeQuery.value.trim();
    if (!q) { toast("請輸入歌曲名稱或 YouTube 網址。", "error"); return; }
    await createTask("/api/tasks/transcribe", { query: q, mode: "auto" }, "已開始 AI 自動轉譜");
    el.transcribeQuery.value = "";
  }, "轉譜發佈失敗"));
}

/* ===== Init ===== */
async function init() {
  bindEvents();
  renderAll();
  await withErr(refreshAll, "Dashboard load failed");
  setInterval(() => withErr(refreshTasks, "Task refresh failed"), 2200);
  setInterval(() => withErr(refreshSongs, "Song refresh failed"), 12000);
}

init();
