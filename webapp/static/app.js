/**
 * Gosting Musicium — Frontend Application Logic
 * Pure Audio Discord Music Player & Activity Client
 */

// ── GLOBAL STATE ──────────────────────────────────────────
const state = {
  apiBase: (typeof window.MUSICBOT_API === "string" ? window.MUSICBOT_API : (window.location.origin || "")).replace(/\/$/, ""),
  selectedGuildId: null,
  activeChannelId: null,
  userId: null,
  isDiscordActivity: false,
  discordSdk: null,

  // Player state from server
  isPlaying: false,
  isPaused: false,
  volume: 0.5,
  loopMode: "none", // "none" | "track" | "queue"
  currentTrack: null,
  queue: [],
  elapsedSeconds: 0,
  totalSeconds: 0,

  // UI state
  activePlatformFilter: "all",
  searchResults: [],
  pollTimer: null,
  progressTicker: null,
  isAdmin: false,
  adminUserId: localStorage.getItem("gosting_admin_uid") || "",
};

// ── UTILITY HELPERS ───────────────────────────────────────
function formatSeconds(sec) {
  if (!sec || isNaN(sec) || sec < 0) return "0:00";
  sec = Math.floor(sec);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${s < 10 ? "0" : ""}${s}`;
}

function showToast(message, type = "info") {
  const container = document.getElementById("toastWrapper");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = "toast";
  const icon = type === "error" ? "❌" : type === "success" ? "✅" : "🎵";
  toast.innerHTML = `<span>${icon}</span><span>${message}</span>`;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 3200);
}

function getProxiedThumbnail(url) {
  if (!url) return "";
  if (url.startsWith("http")) {
    return `${state.apiBase}/api/thumb?url=${encodeURIComponent(url)}`;
  }
  return url;
}

// ── INITIALIZATION ────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  setupSearchInput();
  await initDiscordSdkIfAvailable();
  await loadGuilds();
  startStatePolling();
  startProgressInterpolation();

  if (state.adminUserId) {
    checkAdminStatus(state.adminUserId);
  }
});

// ── DISCORD SDK DETECTION ─────────────────────────────────
async function initDiscordSdkIfAvailable() {
  const urlParams = new URLSearchParams(window.location.search);
  const paramGuildId = urlParams.get("guild_id");
  const paramChannelId = urlParams.get("channel_id");
  if (paramGuildId) state.selectedGuildId = paramGuildId;
  if (paramChannelId) state.activeChannelId = paramChannelId;

  if (typeof DiscordSDK !== "undefined") {
    try {
      const frameId = urlParams.get("frame_id");
      if (frameId || window.location.origin.includes("discordsays.com")) {
        console.log("[Discord SDK] Initializing Embedded App SDK...");
        state.discordSdk = new DiscordSDK.DiscordSDK(window.DISCORD_CLIENT_ID || "1555020109507199066");
        await state.discordSdk.ready();
        state.isDiscordActivity = true;

        if (state.discordSdk.channelId) {
          state.activeChannelId = state.discordSdk.channelId;
        }
        if (state.discordSdk.guildId) {
          state.selectedGuildId = state.discordSdk.guildId;
        }
        console.log(`[Discord SDK] Connected: Guild ${state.selectedGuildId}, Channel ${state.activeChannelId}`);
      }
    } catch (err) {
      console.log("[Discord SDK] Activity context notice:", err.message);
    }
  }
}

// ── GUILD LIST & SELECTION ────────────────────────────────
let _loadGuildsTimer = null;
async function loadGuilds() {
  const select = document.getElementById("serverSelect");
  const dot = document.getElementById("serverStatusDot");

  try {
    const res = await fetch(`${state.apiBase}/api/guilds`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const guilds = data.guilds || [];

    if (guilds.length === 0) {
      select.innerHTML = '<option value="">Подключение к Discord...</option>';
      if (dot) dot.classList.add("offline");
      clearTimeout(_loadGuildsTimer);
      _loadGuildsTimer = setTimeout(loadGuilds, 2500);
      return;
    }

    if (dot) dot.classList.remove("offline");
    select.innerHTML = "";

    guilds.forEach((g) => {
      const opt = document.createElement("option");
      opt.value = g.id;
      const status = g.playing ? " ▶ Играет" : "";
      opt.textContent = `${g.name}${status}`;
      select.appendChild(opt);
    });

    if (state.selectedGuildId && guilds.some((g) => g.id === state.selectedGuildId)) {
      select.value = state.selectedGuildId;
    } else {
      state.selectedGuildId = guilds[0].id;
      select.value = guilds[0].id;
    }

    await fetchPlayerState();
  } catch (err) {
    console.warn("[Guilds] Connecting...", err.message);
    select.innerHTML = '<option value="">Подключение к боту...</option>';
    if (dot) dot.classList.add("offline");
    clearTimeout(_loadGuildsTimer);
    _loadGuildsTimer = setTimeout(loadGuilds, 3000);
  }
}

function onSelectGuild(guildId) {
  if (!guildId) return;
  state.selectedGuildId = guildId;
  fetchPlayerState();
}

// ── STATE POLLING & INTERPOLATION ─────────────────────────
function startStatePolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(() => {
    if (state.selectedGuildId) {
      fetchPlayerState();
    }
  }, 2200);
}

function startProgressInterpolation() {
  if (state.progressTicker) clearInterval(state.progressTicker);
  state.progressTicker = setInterval(() => {
    if (state.isPlaying && !state.isPaused && state.totalSeconds > 0) {
      state.elapsedSeconds = Math.min(state.elapsedSeconds + 1, state.totalSeconds);
      updateSeekbarUI();
    }
  }, 1000);
}

async function fetchPlayerState() {
  if (!state.selectedGuildId) return;
  try {
    const res = await fetch(`${state.apiBase}/api/player/${state.selectedGuildId}`);
    if (!res.ok) return;
    const data = await res.json();

    state.isPlaying = Boolean(data.playing);
    state.isPaused = Boolean(data.paused);
    state.volume = typeof data.volume === "number" ? data.volume : 0.5;
    state.loopMode = data.loop_mode || "none";
    state.currentTrack = data.current || null;
    state.queue = data.queue || [];
    state.elapsedSeconds = data.elapsed || 0;
    state.totalSeconds = state.currentTrack ? state.currentTrack.duration || 0 : 0;

    renderPlayerUI();
    renderQueueUI();
  } catch (err) {
    console.warn("[Player State] Poll error:", err);
  }
}

// ── RENDER PLAYER CENTERPIECE ─────────────────────────────
function renderPlayerUI() {
  const coverWrapper = document.getElementById("coverWrapper");
  const trackArtwork = document.getElementById("trackArtwork");
  const coverPlaceholder = document.getElementById("coverPlaceholder");
  const platformPill = document.getElementById("platformPill");
  const pillName = document.getElementById("pillName");
  const pillDot = document.getElementById("pillDot");

  const currentTitle = document.getElementById("currentTitle");
  const currentArtist = document.getElementById("currentArtist");
  const requesterTag = document.getElementById("requesterTag");
  const requesterName = document.getElementById("requesterName");

  const iconPlay = document.getElementById("iconPlay");
  const iconPause = document.getElementById("iconPause");
  const btnLoopMode = document.getElementById("btnLoopMode");
  const loopIndicator = document.getElementById("loopIndicator");

  const volumeSlider = document.getElementById("volumeSlider");
  const volumePercentText = document.getElementById("volumePercentText");

  // Play / Pause Icon
  if (state.isPlaying && !state.isPaused) {
    coverWrapper.classList.add("is-playing");
    iconPlay.style.display = "none";
    iconPause.style.display = "block";
  } else {
    coverWrapper.classList.remove("is-playing");
    iconPlay.style.display = "block";
    iconPause.style.display = "none";
  }

  // Track info
  if (state.currentTrack) {
    currentTitle.textContent = state.currentTrack.title || "Без названия";
    currentArtist.textContent = state.currentTrack.artist || "Неизвестный исполнитель";

    if (state.currentTrack.thumbnail) {
      trackArtwork.src = getProxiedThumbnail(state.currentTrack.thumbnail);
      trackArtwork.style.display = "block";
      coverPlaceholder.style.display = "none";
    } else {
      trackArtwork.style.display = "none";
      coverPlaceholder.style.display = "flex";
    }

    if (state.currentTrack.platform) {
      platformPill.style.display = "flex";
      pillName.textContent = state.currentTrack.platform;
      pillDot.style.background = state.currentTrack.platform_color || "#8b5cf6";
    } else {
      platformPill.style.display = "none";
    }

    if (state.currentTrack.requester) {
      requesterTag.style.display = "inline-block";
      requesterName.textContent = state.currentTrack.requester;
    } else {
      requesterTag.style.display = "none";
    }
  } else {
    currentTitle.textContent = "Ничего не играет";
    currentArtist.textContent = "Выберите песню из поиска";
    trackArtwork.style.display = "none";
    coverPlaceholder.style.display = "flex";
    platformPill.style.display = "none";
    requesterTag.style.display = "none";
  }

  // Loop mode styling
  btnLoopMode.classList.remove("active");
  loopIndicator.style.display = "none";
  if (state.loopMode === "track") {
    btnLoopMode.classList.add("active");
    btnLoopMode.title = "Повтор: Один трек";
    loopIndicator.style.display = "block";
  } else if (state.loopMode === "queue") {
    btnLoopMode.classList.add("active");
    btnLoopMode.title = "Повтор: Вся очередь";
    loopIndicator.style.display = "block";
  } else {
    btnLoopMode.title = "Повтор: Выкл";
  }

  // Volume slider sync (if not dragging)
  const volPct = Math.round(state.volume * 100);
  if (document.activeElement !== volumeSlider) {
    volumeSlider.value = volPct;
    volumePercentText.textContent = `${volPct}%`;
  }

  updateSeekbarUI();
}

function updateSeekbarUI() {
  const timeElapsed = document.getElementById("timeElapsed");
  const timeTotal = document.getElementById("timeTotal");
  const seekbarFill = document.getElementById("seekbarFill");
  const seekbarThumb = document.getElementById("seekbarThumb");

  timeElapsed.textContent = formatSeconds(state.elapsedSeconds);
  timeTotal.textContent = formatSeconds(state.totalSeconds);

  let pct = 0;
  if (state.totalSeconds > 0) {
    pct = Math.min(100, Math.max(0, (state.elapsedSeconds / state.totalSeconds) * 100));
  }

  seekbarFill.style.width = `${pct}%`;
  seekbarThumb.style.left = `${pct}%`;
}

// ── SEEKBAR INTERACTION ───────────────────────────────────
function onSeekbarClick(e) {
  if (!state.currentTrack || state.totalSeconds <= 0 || !state.selectedGuildId) return;

  const rect = e.currentTarget.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const ratio = Math.max(0, Math.min(1, clickX / rect.width));
  const targetSeconds = Math.floor(ratio * state.totalSeconds);

  state.elapsedSeconds = targetSeconds;
  updateSeekbarUI();

  fetch(`${state.apiBase}/api/player/${state.selectedGuildId}/seek`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seconds: targetSeconds }),
  })
    .then((r) => r.json())
    .catch((err) => console.error("[Seek] Error:", err));
}

// ── PLAYBACK COMMANDS ─────────────────────────────────────
async function cmdTogglePlayPause() {
  if (!state.selectedGuildId) return;
  const endpoint = state.isPlaying && !state.isPaused ? "pause" : "resume";

  try {
    const res = await fetch(`${state.apiBase}/api/player/${state.selectedGuildId}/${endpoint}`, {
      method: "POST",
    });
    const data = await res.json();
    if (data.ok) {
      state.isPlaying = endpoint === "resume";
      state.isPaused = endpoint === "pause";
      renderPlayerUI();
    }
  } catch (err) {
    showToast("Ошибка управления воспроизведением", "error");
  }
}

async function cmdSkipTrack() {
  if (!state.selectedGuildId) return;
  try {
    await fetch(`${state.apiBase}/api/player/${state.selectedGuildId}/skip`, { method: "POST" });
    showToast("Трек пропущен", "info");
    setTimeout(fetchPlayerState, 400);
  } catch (err) {
    showToast("Не удалось пропустить", "error");
  }
}

async function cmdPrevTrack() {
  if (!state.selectedGuildId) return;
  try {
    const res = await fetch(`${state.apiBase}/api/player/${state.selectedGuildId}/prev`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      showToast(data.error || "История пуста", "error");
    } else {
      showToast("Предыдущий трек", "info");
      setTimeout(fetchPlayerState, 400);
    }
  } catch (err) {
    showToast("Ошибка переключения", "error");
  }
}

async function cmdStopPlayer() {
  if (!state.selectedGuildId) return;
  try {
    await fetch(`${state.apiBase}/api/player/${state.selectedGuildId}/stop`, { method: "POST" });
    showToast("Воспроизведение остановлено", "info");
    state.isPlaying = false;
    state.isPaused = false;
    state.currentTrack = null;
    state.queue = [];
    renderPlayerUI();
    renderQueueUI();
  } catch (err) {
    showToast("Ошибка остановки", "error");
  }
}

async function cycleLoopMode() {
  if (!state.selectedGuildId) return;
  const nextMode = state.loopMode === "none" ? "track" : state.loopMode === "track" ? "queue" : "none";

  try {
    const res = await fetch(`${state.apiBase}/api/player/${state.selectedGuildId}/loop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: nextMode }),
    });
    const data = await res.json();
    if (data.ok) {
      state.loopMode = nextMode;
      renderPlayerUI();
      const labels = { none: "Повтор выключен", track: "Повтор одного трека", queue: "Повтор всей очереди" };
      showToast(labels[nextMode], "info");
    }
  } catch (err) {
    console.error("[Loop] Error:", err);
  }
}

let volumeDebounce = null;
function onVolumeChange(val) {
  const volPct = parseInt(val, 10);
  document.getElementById("volumePercentText").textContent = `${volPct}%`;
  state.volume = volPct / 100;

  clearTimeout(volumeDebounce);
  volumeDebounce = setTimeout(() => {
    if (!state.selectedGuildId) return;
    fetch(`${state.apiBase}/api/player/${state.selectedGuildId}/volume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ volume: state.volume }),
    });
  }, 150);
}

function toggleMute() {
  const slider = document.getElementById("volumeSlider");
  if (state.volume > 0) {
    state._preMuteVol = state.volume;
    onVolumeChange(0);
    slider.value = 0;
  } else {
    const restore = state._preMuteVol || 0.5;
    onVolumeChange(Math.round(restore * 100));
    slider.value = Math.round(restore * 100);
  }
}

// ── SEARCH LOGIC ──────────────────────────────────────────
function setupSearchInput() {
  const input = document.getElementById("searchInput");
  const clearBtn = document.getElementById("btnClearSearch");

  input.addEventListener("input", () => {
    clearBtn.style.display = input.value.trim() ? "block" : "none";
  });
}

function clearSearch() {
  const input = document.getElementById("searchInput");
  input.value = "";
  document.getElementById("btnClearSearch").style.display = "none";
  input.focus();
}

function applyPlatformFilter(el, platform) {
  document.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
  el.classList.add("active");
  state.activePlatformFilter = platform;
  renderSearchResults();
}

async function triggerSearch() {
  const query = document.getElementById("searchInput").value.trim();
  if (!query) return;

  const container = document.getElementById("searchResultsContainer");
  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon-bubble">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin-icon">
          <circle cx="12" cy="12" r="10" stroke-opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10"/>
        </svg>
      </div>
      <p class="empty-title">Ищем треки...</p>
    </div>
  `;

  try {
    const res = await fetch(`${state.apiBase}/api/search?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    state.searchResults = data.results || [];
    renderSearchResults();
  } catch (err) {
    container.innerHTML = `
      <div class="empty-state">
        <p class="empty-title">Ошибка поиска</p>
        <p class="empty-desc">Проверьте соединение с сервером</p>
      </div>
    `;
  }
}

function renderSearchResults() {
  const container = document.getElementById("searchResultsContainer");
  const filtered = state.searchResults.filter((item) => {
    if (state.activePlatformFilter === "all") return true;
    return item.platform === state.activePlatformFilter;
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon-bubble">🔍</div>
        <p class="empty-title">Ничего не найдено</p>
        <p class="empty-desc">Попробуйте изменить поисковый запрос</p>
      </div>
    `;
    return;
  }

  container.innerHTML = "";
  filtered.forEach((track) => {
    const item = document.createElement("div");
    item.className = "result-item";

    const pClass = track.platform === "YouTube" ? "youtube" : "soundcloud";
    const thumbUrl = getProxiedThumbnail(track.thumbnail);

    item.innerHTML = `
      <div class="result-thumb-wrap">
        <img class="result-thumb" src="${thumbUrl}" alt="cover" loading="lazy" />
      </div>
      <div class="result-details">
        <div class="result-title" title="${escapeHtml(track.title)}">${escapeHtml(track.title)}</div>
        <div class="result-meta">
          <span class="platform-tag ${pClass}">${track.platform}</span>
          <span>•</span>
          <span>${track.duration_str || "N/A"}</span>
        </div>
      </div>
      <div class="result-actions">
        <button class="btn-action-mini play-direct" title="Включить сейчас">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="6 3 20 12 6 21 6 3"/>
          </svg>
        </button>
        <button class="btn-action-mini add-queue" title="Добавить в очередь">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
        </button>
      </div>
    `;

    item.querySelector(".play-direct").addEventListener("click", () => playTrackDirectly(track));
    item.querySelector(".add-queue").addEventListener("click", () => queueTrack(track));
    container.appendChild(item);
  });
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

// ── PLAY & QUEUE ACTIONS ──────────────────────────────────
async function playTrackDirectly(track) {
  if (!state.selectedGuildId) {
    showToast("Выберите сервер в шапке!", "error");
    return;
  }

  showToast(`Запуск: ${track.title}`, "info");

  try {
    const payload = {
      guild_id: state.selectedGuildId,
      channel_id: state.activeChannelId,
      track: track,
      user_id: state.userId,
    };

    const res = await fetch(`${state.apiBase}/api/play`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!res.ok) {
      showToast(data.error || "Не удалось запустить", "error");
    } else {
      showToast(`Играет: ${track.title}`, "success");
      setTimeout(fetchPlayerState, 600);
    }
  } catch (err) {
    showToast("Ошибка связи с ботом", "error");
  }
}

async function queueTrack(track) {
  await playTrackDirectly(track);
}

// ── RENDER QUEUE LIST ─────────────────────────────────────
function renderQueueUI() {
  const container = document.getElementById("queueContainer");
  const badge = document.getElementById("queueCountBadge");
  const mobileBadge = document.getElementById("mobileQueueBadge");

  const totalInQueue = state.queue.length;
  badge.textContent = totalInQueue;
  if (mobileBadge) mobileBadge.textContent = totalInQueue;

  if (totalInQueue === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon-bubble">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/>
          </svg>
        </div>
        <p class="empty-title">Очередь пуста</p>
        <p class="empty-desc">Добавьте треки из поиска, чтобы воспроизвести их один за другим</p>
      </div>
    `;
    return;
  }

  container.innerHTML = "";
  state.queue.forEach((track, idx) => {
    const item = document.createElement("div");
    item.className = "queue-item";
    const thumbUrl = getProxiedThumbnail(track.thumbnail);

    item.innerHTML = `
      <div class="queue-index">${idx + 1}</div>
      <div class="queue-thumb-wrap">
        <img class="queue-thumb" src="${thumbUrl}" alt="art" loading="lazy" />
      </div>
      <div class="queue-details">
        <div class="queue-title" title="${escapeHtml(track.title)}">${escapeHtml(track.title)}</div>
        <div class="queue-artist">${escapeHtml(track.artist)}</div>
        <div class="queue-meta">
          <span>${track.platform}</span>
          <span>•</span>
          <span>${track.duration_str || "N/A"}</span>
        </div>
      </div>
    `;
    container.appendChild(item);
  });
}

// ── MOBILE TAB SWITCHING ──────────────────────────────────
function switchMobileTab(targetPanelId) {
  document.querySelectorAll(".mobile-tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.target === targetPanelId);
  });

  document.querySelectorAll(".card-panel").forEach((panel) => {
    panel.classList.toggle("active-panel", panel.id === targetPanelId);
  });
}

// ── ADMIN MODAL & CONTROLS ────────────────────────────────
function openAdminModal() {
  document.getElementById("adminBackdrop").style.display = "flex";
  if (state.isAdmin) {
    showAdminDashboard();
  } else {
    document.getElementById("adminAuthPane").style.display = "block";
    document.getElementById("adminBodyPane").style.display = "none";
  }
}

function closeAdminModal() {
  document.getElementById("adminBackdrop").style.display = "none";
}

function closeAdminOnBackdrop(e) {
  if (e.target.id === "adminBackdrop") {
    closeAdminModal();
  }
}

async function checkAdminStatus(uid) {
  try {
    const res = await fetch(`${state.apiBase}/api/admin/check`, {
      headers: { "X-User-Id": uid },
    });
    const data = await res.json();
    if (data.is_admin) {
      state.isAdmin = true;
      state.adminUserId = uid;
      localStorage.setItem("gosting_admin_uid", uid);
    }
  } catch (e) {}
}

async function submitAdminAuth() {
  const uid = document.getElementById("adminUserIdInput").value.trim();
  const errEl = document.getElementById("adminAuthError");
  errEl.style.display = "none";

  if (!uid) return;

  try {
    const res = await fetch(`${state.apiBase}/api/admin/check`, {
      headers: { "X-User-Id": uid },
    });
    const data = await res.json();
    if (data.is_admin) {
      state.isAdmin = true;
      state.adminUserId = uid;
      localStorage.setItem("gosting_admin_uid", uid);
      showAdminDashboard();
    } else {
      errEl.style.display = "block";
    }
  } catch (err) {
    errEl.style.display = "block";
  }
}

function showAdminDashboard() {
  document.getElementById("adminAuthPane").style.display = "none";
  document.getElementById("adminBodyPane").style.display = "flex";
  loadAdminGuilds();
}

function switchAdminTab(tab) {
  document.getElementById("tabBtnGuilds").classList.toggle("active", tab === "guilds");
  document.getElementById("tabBtnChains").classList.toggle("active", tab === "chains");

  document.getElementById("adminTabContentGuilds").style.display = tab === "guilds" ? "block" : "none";
  document.getElementById("adminTabContentChains").style.display = tab === "chains" ? "block" : "none";

  if (tab === "guilds") {
    loadAdminGuilds();
  } else {
    loadAdminChainsDropdown();
  }
}

async function loadAdminGuilds() {
  const container = document.getElementById("adminGuildsList");
  container.innerHTML = '<div class="admin-loader">Загрузка серверов...</div>';

  try {
    const res = await fetch(`${state.apiBase}/api/admin/guilds`, {
      headers: { "X-User-Id": state.adminUserId },
    });
    const data = await res.json();
    const guilds = data.guilds || [];

    if (guilds.length === 0) {
      container.innerHTML = '<div class="empty-state"><p class="empty-desc">Нет серверов</p></div>';
      return;
    }

    container.innerHTML = "";
    guilds.forEach((g) => {
      const card = document.createElement("div");
      card.className = "admin-guild-card";
      card.innerHTML = `
        <div class="admin-guild-info">
          <img class="guild-icon-img" src="${g.icon || ''}" onerror="this.style.display='none'" />
          <div>
            <div class="guild-name">${escapeHtml(g.name)}</div>
            <div class="guild-members">Участников: ${g.member_count} • ${g.has_player ? "Плеер активен" : "Простой"}</div>
          </div>
        </div>
        ${
          g.has_player
            ? `<button class="btn-danger-mini" onclick="adminForceStop('${g.id}')">Остановить</button>`
            : ""
        }
      `;
      container.appendChild(card);
    });
  } catch (err) {
    container.innerHTML = '<div class="empty-state"><p class="empty-desc">Ошибка загрузки</p></div>';
  }
}

async function adminForceStop(guildId) {
  try {
    await fetch(`${state.apiBase}/api/admin/stop/${guildId}`, {
      method: "POST",
      headers: { "X-User-Id": state.adminUserId },
    });
    showToast("Плеер сервера остановлен", "info");
    loadAdminGuilds();
  } catch (err) {
    showToast("Ошибка остановки", "error");
  }
}

async function loadAdminChainsDropdown() {
  const select = document.getElementById("adminChainGuildSelect");
  try {
    const res = await fetch(`${state.apiBase}/api/guilds`);
    const data = await res.json();
    const guilds = data.guilds || [];

    select.innerHTML = '<option value="">Выберите сервер...</option>';
    guilds.forEach((g) => {
      const opt = document.createElement("option");
      opt.value = g.id;
      opt.textContent = g.name;
      select.appendChild(opt);
    });
  } catch (e) {}
}

async function loadChainsForSelectedGuild() {
  const guildId = document.getElementById("adminChainGuildSelect").value;
  const container = document.getElementById("adminChainsList");
  if (!guildId) {
    container.innerHTML = '<div class="empty-state"><p class="empty-desc">Выберите сервер</p></div>';
    return;
  }

  container.innerHTML = '<div class="admin-loader">Загрузка связок...</div>';
  try {
    const res = await fetch(`${state.apiBase}/api/admin/chains/${guildId}`, {
      headers: { "X-User-Id": state.adminUserId },
    });
    const data = await res.json();
    const chains = data.chains || [];

    if (chains.length === 0) {
      container.innerHTML = '<div class="empty-state"><p class="empty-desc">Нет активных связок на сервере</p></div>';
      return;
    }

    container.innerHTML = "";
    chains.forEach((ch) => {
      const item = document.createElement("div");
      item.className = "admin-guild-card";
      item.innerHTML = `
        <div>
          <strong>${escapeHtml(ch.follower_name)}</strong> ➜ <strong>${escapeHtml(ch.leader_name)}</strong>
        </div>
        <button class="btn-danger-mini" onclick="adminDeleteChain('${guildId}', '${ch.follower_id}')">Отвязать</button>
      `;
      container.appendChild(item);
    });
  } catch (err) {
    container.innerHTML = '<div class="empty-state"><p class="empty-desc">Ошибка загрузки связок</p></div>';
  }
}

async function adminDeleteChain(guildId, followerId) {
  try {
    await fetch(`${state.apiBase}/api/admin/chains/${guildId}`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
        "X-User-Id": state.adminUserId,
      },
      body: JSON.stringify({ follower_id: followerId }),
    });
    showToast("Связка удалена", "info");
    loadChainsForSelectedGuild();
  } catch (e) {
    showToast("Ошибка удаления связки", "error");
  }
}
