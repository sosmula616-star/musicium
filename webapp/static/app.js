/* ─────────────────────────────────────────────────────────
   Discord Music Player — Main App Logic
   ───────────────────────────────────────────────────────── */

'use strict';

// ── CONFIG ────────────────────────────────────────────────
// API_BASE — адрес твоего VDS с Flask-ботом
// Это единственная строка которую нужно поменять после деплоя!
const API_BASE = window.MUSICBOT_API || 'http://localhost:8080';
const POLL_INTERVAL = 2500; // ms

// Get guild ID from URL params
const urlParams = new URLSearchParams(window.location.search);
let GUILD_ID = urlParams.get('guild') || '';

// Platform icons SVG (inline)
const PLATFORM_ICONS = {
  youtube: `<svg viewBox="0 0 24 24" fill="#FF0000" width="14" height="14"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>`,
  soundcloud: `<svg viewBox="0 0 24 24" fill="#FF5500" width="14" height="14"><path d="M1.175 12.225c-.15 0-.254.097-.264.25l-.44 2.568.44 2.568c.01.15.114.25.264.25.147 0 .25-.1.272-.25L1.69 15.04l-.24-2.568c-.022-.15-.125-.247-.272-.247zm2.195-.35c-.172 0-.303.13-.303.3v5.25c0 .17.13.3.303.3.17 0 .3-.13.3-.3V12.17c0-.17-.13-.296-.3-.296zm2.2-.8c-.2 0-.352.15-.352.35v6.25c0 .2.152.35.353.35.2 0 .35-.15.35-.35v-6.25c0-.2-.15-.35-.35-.35zm2.24.15c-.22 0-.395.175-.395.4v6c0 .22.175.4.395.4.22 0 .4-.18.4-.4v-6c0-.225-.18-.4-.4-.4zm2.27-.4c-.25 0-.44.19-.44.44v6.7c0 .25.19.44.44.44s.44-.19.44-.44v-6.7c0-.25-.19-.44-.44-.44zm2.24.45c-.27 0-.49.22-.49.49v5.7c0 .27.22.49.49.49.27 0 .49-.22.49-.49v-5.7c0-.27-.22-.49-.49-.49zm2.24-.35c-.3 0-.54.24-.54.54v6.2c0 .3.24.54.54.54.3 0 .54-.24.54-.54v-6.2c0-.3-.24-.54-.54-.54zm2.24.1c-.32 0-.58.26-.58.58v5.8c0 .32.26.58.58.58.32 0 .58-.26.58-.58v-5.8c0-.32-.26-.58-.58-.58zm2.24-.5c-.35 0-.63.28-.63.63v6.5c0 .35.28.63.63.63.35 0 .63-.28.63-.63v-6.5c0-.35-.28-.63-.63-.63z"/></svg>`,
  spotify: `<svg viewBox="0 0 24 24" fill="#1DB954" width="14" height="14"><path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>`,
};

const PLATFORM_COLORS = {
  YouTube:    '#FF0000',
  SoundCloud: '#FF5500',
  Spotify:    '#1DB954',
};

// ── STATE ─────────────────────────────────────────────────
let state = {
  playing: false,
  paused: false,
  current: null,
  queue: [],
  queue_count: 0,
  volume: 50,
  loop_mode: 'none',
};

let searchResults = [];
let searchFilter = 'all';
let adminUserId = null;
let adminGuilds = [];
let pollTimer = null;
let progressTimer = null;
let localElapsed = 0;
let lastPollTime = 0;

// ── INIT ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  createParticles();
  setupSearchInput();
  startPolling();
  updatePlayerUI();
});

// ── BACKGROUND PARTICLES ──────────────────────────────────
function createParticles() {
  const container = document.getElementById('bgParticles');
  const colors = ['#a855f7', '#3b82f6', '#ec4899', '#8b5cf6'];
  for (let i = 0; i < 20; i++) {
    const p = document.createElement('div');
    p.className = 'particle';
    const size = Math.random() * 80 + 20;
    p.style.cssText = `
      width: ${size}px;
      height: ${size}px;
      left: ${Math.random() * 100}%;
      background: ${colors[Math.floor(Math.random() * colors.length)]};
      animation-duration: ${Math.random() * 20 + 15}s;
      animation-delay: -${Math.random() * 20}s;
      filter: blur(${size / 3}px);
    `;
    container.appendChild(p);
  }
}

// ── SEARCH ────────────────────────────────────────────────
function setupSearchInput() {
  const input = document.getElementById('searchInput');
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') doSearch();
  });

  // Auto-search with debounce for URLs
  let debounce;
  input.addEventListener('input', e => {
    const val = e.target.value.trim();
    if (val.startsWith('http')) {
      clearTimeout(debounce);
      debounce = setTimeout(() => doSearch(), 800);
    }
  });
}

function setFilter(btn, platform) {
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  searchFilter = platform;
  renderSearchResults();
}

async function doSearch() {
  const query = document.getElementById('searchInput').value.trim();
  if (!query) return;

  const resultsEl = document.getElementById('searchResults');
  resultsEl.innerHTML = `
    <div class="search-loading">
      <div class="loading-spinner" style="width:20px;height:20px;border-width:2px;margin:0"></div>
      <span>Поиск...</span>
    </div>`;

  try {
    const res = await fetch(`${API_BASE}/api/search?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    searchResults = data.results || [];
    renderSearchResults();
  } catch (err) {
    resultsEl.innerHTML = `<div class="empty-state"><p>❌ Ошибка поиска</p></div>`;
    showToast('Ошибка поиска', 'error');
  }
}

function renderSearchResults() {
  const resultsEl = document.getElementById('searchResults');
  let filtered = searchResults;
  if (searchFilter !== 'all') {
    filtered = searchResults.filter(t => t.platform === searchFilter);
  }

  if (!filtered.length) {
    resultsEl.innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><p>Ничего не найдено</p></div>`;
    return;
  }

  resultsEl.innerHTML = filtered.map((track, i) => `
    <div class="track-item" onclick="playTrack(${JSON.stringify(track).replace(/"/g, '&quot;')})">
      ${track.thumbnail
        ? `<img class="track-thumb" src="${track.thumbnail}" alt="" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" loading="lazy">
           <div class="track-thumb-placeholder" style="display:none">🎵</div>`
        : `<div class="track-thumb-placeholder">🎵</div>`
      }
      <div class="track-meta">
        <div class="title">${escapeHtml(track.title)}</div>
        <div class="artist">${escapeHtml(track.artist || '')}</div>
        <div class="track-footer">
          <span class="platform-badge-small" style="background:${track.platform_color}22;color:${track.platform_color}">
            ${PLATFORM_ICONS[track.platform_icon] || ''}
            ${track.platform}
          </span>
          <span class="duration-label">${track.duration_str || ''}</span>
        </div>
      </div>
      <button class="track-add-btn" title="Добавить в очередь">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
      </button>
    </div>
  `).join('');
}

// ── PLAY TRACK FROM WEB ───────────────────────────────────
async function playTrack(track) {
  if (!GUILD_ID) {
    showToast('Guild ID не задан в URL (?guild=...)', 'error');
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/play`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        guild_id: parseInt(GUILD_ID),
        track,
        user_id: adminUserId,
      }),
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`🎵 ${track.title} добавлен в очередь`, 'success');
      pollNow();
    } else {
      showToast(data.error || 'Ошибка', 'error');
    }
  } catch (err) {
    showToast('Ошибка добавления трека', 'error');
  }
}

// ── PLAYER CONTROLS ───────────────────────────────────────
async function togglePlayPause() {
  if (!GUILD_ID) return;
  const endpoint = state.playing && !state.paused ? 'pause' : 'resume';
  await apiPost(`/api/player/${GUILD_ID}/${endpoint}`);
  pollNow();
}

async function skipTrack() {
  if (!GUILD_ID) return;
  await apiPost(`/api/player/${GUILD_ID}/skip`);
  showToast('⏭️ Пропущено', 'info');
  pollNow();
}

async function stopPlayer() {
  if (!GUILD_ID) return;
  await apiPost(`/api/player/${GUILD_ID}/stop`);
  showToast('⏹️ Остановлено', 'info');
  pollNow();
}

let loopModes = ['none', 'track', 'queue'];
let loopIndex = 0;

async function toggleLoop() {
  loopIndex = (loopIndex + 1) % loopModes.length;
  const mode = loopModes[loopIndex];
  await apiPost(`/api/player/${GUILD_ID}/loop`, { mode });
  state.loop_mode = mode;
  updateLoopBtn();
  const names = { none: 'Повтор выключен', track: '🔂 Повтор трека', queue: '🔁 Повтор очереди' };
  showToast(names[mode], 'info');
}

function updateLoopBtn() {
  const btn = document.getElementById('btnLoop');
  btn.classList.toggle('active', state.loop_mode !== 'none');
  if (state.loop_mode === 'track') {
    btn.title = 'Повтор трека';
    btn.style.color = 'var(--purple)';
  } else if (state.loop_mode === 'queue') {
    btn.title = 'Повтор очереди';
    btn.style.color = 'var(--blue)';
  } else {
    btn.title = 'Режим повтора';
    btn.style.color = '';
  }
}

function setVolume(val) {
  document.getElementById('volumeLabel').textContent = `${val}%`;
  if (!GUILD_ID) return;
  const volume = val / 100;
  apiPost(`/api/player/${GUILD_ID}/volume`, { volume });
}

async function apiPost(path, body = {}) {
  try {
    const res = await fetch(API_BASE + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return await res.json();
  } catch (err) {
    console.error('API error:', err);
    return null;
  }
}

// ── POLLING ───────────────────────────────────────────────
function startPolling() {
  pollNow();
  pollTimer = setInterval(pollNow, POLL_INTERVAL);
}

async function pollNow() {
  if (!GUILD_ID) return;
  try {
    const res = await fetch(`${API_BASE}/api/player/${GUILD_ID}`);
    const newState = await res.json();
    lastPollTime = Date.now();
    applyState(newState);
  } catch (err) {
    // silent
  }
}

function applyState(newState) {
  const wasPlaying = state.playing && !state.paused;
  state = { ...state, ...newState };

  updatePlayerUI();
  updateQueueUI();

  // Start/stop local progress timer
  const isPlaying = state.playing && !state.paused;
  if (isPlaying && !progressTimer) {
    startProgressTimer();
  } else if (!isPlaying && progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
}

// ── PROGRESS TIMER ────────────────────────────────────────
let progressStartTime = 0;
let progressStartElapsed = 0;

function startProgressTimer() {
  progressStartTime = Date.now();
  progressStartElapsed = 0;
  if (progressTimer) clearInterval(progressTimer);
  progressTimer = setInterval(() => {
    if (!state.playing || state.paused) return;
    const elapsed = (Date.now() - progressStartTime) / 1000 + progressStartElapsed;
    const duration = state.current?.duration || 0;
    if (duration > 0) {
      const pct = Math.min((elapsed / duration) * 100, 100);
      document.getElementById('progressFill').style.width = `${pct}%`;
      document.getElementById('progressThumb').style.left = `${pct}%`;
      document.getElementById('timeElapsed').textContent = formatTime(elapsed);
    }
  }, 500);
}

// ── UI UPDATES ────────────────────────────────────────────
function updatePlayerUI() {
  const playIcon = document.querySelector('.icon-play');
  const pauseIcon = document.querySelector('.icon-pause');
  const albumArt = document.getElementById('albumArt');
  const albumGlow = document.getElementById('albumGlow');

  const isPlaying = state.playing && !state.paused;

  // Play/Pause icon
  if (playIcon && pauseIcon) {
    playIcon.style.display  = isPlaying ? 'none'  : 'block';
    pauseIcon.style.display = isPlaying ? 'block' : 'none';
  }

  // Album spinning
  albumArt.classList.toggle('playing', isPlaying);
  albumGlow.classList.toggle('active', isPlaying);

  // Track info
  if (state.current) {
    document.getElementById('trackTitle').textContent  = state.current.title  || 'Unknown';
    document.getElementById('trackArtist').textContent = state.current.artist || '';

    // Album art image
    if (state.current.thumbnail) {
      albumArt.innerHTML = `<img src="${state.current.thumbnail}" alt="Album art" onerror="this.parentElement.innerHTML='<div class=album-placeholder>🎵</div>'">`;
    }

    // Platform badge
    const badge = document.getElementById('platformBadge');
    const badgeInner = document.getElementById('platformBadgeInner');
    if (state.current.platform_icon) {
      badge.style.display = 'block';
      badgeInner.style.background = (state.current.platform_color || '#666') + '33';
      badgeInner.innerHTML = PLATFORM_ICONS[state.current.platform_icon] || '🎵';
    } else {
      badge.style.display = 'none';
    }

    // Duration
    document.getElementById('timeDuration').textContent = state.current.duration_str || '0:00';

    // Restart progress on track change
    progressStartTime = Date.now();
    progressStartElapsed = 0;

    // Gradient glow matching album art color
    if (state.current.platform_color) {
      albumGlow.style.background = `radial-gradient(ellipse, ${state.current.platform_color}44 0%, transparent 70%)`;
    }
  } else {
    document.getElementById('trackTitle').textContent  = 'Ничего не играет';
    document.getElementById('trackArtist').textContent = 'Найди трек и начни слушать';
    albumArt.innerHTML = `<div class="album-placeholder">
      <svg width="60" height="60" viewBox="0 0 24 24" fill="none">
        <path d="M9 18V5l12-2v13" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="6" cy="18" r="3" stroke="rgba(255,255,255,0.3)" stroke-width="1.5"/>
        <circle cx="18" cy="16" r="3" stroke="rgba(255,255,255,0.3)" stroke-width="1.5"/>
      </svg>
    </div>`;
    document.getElementById('progressFill').style.width = '0%';
    document.getElementById('progressThumb').style.left = '0%';
    document.getElementById('timeElapsed').textContent = '0:00';
    document.getElementById('timeDuration').textContent = '0:00';
    document.getElementById('platformBadge').style.display = 'none';
  }

  // Loop button state
  if (state.loop_mode) {
    loopIndex = loopModes.indexOf(state.loop_mode);
    if (loopIndex < 0) loopIndex = 0;
    updateLoopBtn();
  }
}

function updateQueueUI() {
  const queueEl = document.getElementById('queueList');
  const countBadge = document.getElementById('queueCountBadge');
  countBadge.textContent = state.queue_count || 0;

  if (!state.queue || !state.queue.length) {
    queueEl.innerHTML = `<div class="empty-state"><div class="empty-icon">📭</div><p>Очередь пуста</p></div>`;
    return;
  }

  queueEl.innerHTML = state.queue.map((track, i) => `
    <div class="queue-item">
      <span class="queue-num">${i + 1}</span>
      ${track.thumbnail
        ? `<img class="queue-thumb" src="${track.thumbnail}" alt="" loading="lazy">`
        : `<div class="queue-thumb" style="display:flex;align-items:center;justify-content:center;font-size:16px">🎵</div>`
      }
      <div class="queue-meta">
        <div class="title">${escapeHtml(track.title)}</div>
        <div class="artist">${escapeHtml(track.artist || '')}</div>
      </div>
      <div class="queue-platform-dot" style="background:${track.platform_color || '#666'}"></div>
    </div>
  `).join('');
}

// ── ADMIN PANEL ───────────────────────────────────────────
function toggleAdmin() {
  document.getElementById('adminOverlay').classList.toggle('open');
}

function closeAdmin(event) {
  if (event.target === document.getElementById('adminOverlay')) {
    closeAdminPanel();
  }
}

function closeAdminPanel() {
  document.getElementById('adminOverlay').classList.remove('open');
}

async function adminLogin() {
  const input = document.getElementById('adminIdInput');
  const userId = input.value.trim();
  if (!userId || isNaN(userId)) {
    document.getElementById('adminError').style.display = 'block';
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/admin/check`, {
      headers: { 'X-User-Id': userId },
    });
    const data = await res.json();

    if (data.is_admin) {
      adminUserId = userId;
      document.getElementById('adminLoginForm').style.display = 'none';
      document.getElementById('adminDashboard').style.display = 'block';
      document.getElementById('adminError').style.display = 'none';
      loadAdminGuilds();
    } else {
      document.getElementById('adminError').style.display = 'block';
    }
  } catch {
    document.getElementById('adminError').style.display = 'block';
  }
}

function showAdminTab(btn, tab) {
  document.querySelectorAll('.admin-tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('adminTabGuilds').style.display = tab === 'guilds' ? '' : 'none';
  document.getElementById('adminTabChains').style.display = tab === 'chains' ? '' : 'none';
  if (tab === 'guilds') loadAdminGuilds();
}

async function loadAdminGuilds() {
  const container = document.getElementById('adminGuildsList');
  container.innerHTML = '<div class="loading-spinner"></div>';

  try {
    const res = await fetch(`${API_BASE}/api/admin/guilds`, {
      headers: { 'X-User-Id': adminUserId },
    });
    const data = await res.json();
    adminGuilds = data.guilds || [];

    // Populate chain guild select
    const sel = document.getElementById('adminChainGuildSelect');
    sel.innerHTML = '<option value="">Выбери сервер...</option>' +
      adminGuilds.map(g => `<option value="${g.id}">${g.name}</option>`).join('');

    if (!adminGuilds.length) {
      container.innerHTML = '<div class="empty-state"><p>Нет серверов</p></div>';
      return;
    }

    container.innerHTML = adminGuilds.map(guild => `
      <div class="admin-guild-card">
        ${guild.icon
          ? `<img class="guild-icon" src="${guild.icon}" alt="">`
          : `<div class="guild-icon-placeholder">${guild.name[0].toUpperCase()}</div>`
        }
        <div class="guild-info">
          <div class="name">${escapeHtml(guild.name)}</div>
          <div class="meta">
            ${guild.member_count} участников
            ${guild.has_player ? '· 🎵 играет' : ''}
          </div>
          ${guild.player_state?.current
            ? `<div class="meta" style="color:var(--purple)">▶ ${escapeHtml(guild.player_state.current.title)}</div>`
            : ''}
        </div>
        <div class="guild-actions">
          ${guild.has_player ? `<button class="btn-danger" onclick="adminStopGuild('${guild.id}')">⏹ Стоп</button>` : ''}
          <button class="btn-primary" style="font-size:12px;padding:6px 12px" onclick="selectGuild('${guild.id}')">Открыть</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = '<div class="empty-state"><p>Ошибка загрузки</p></div>';
  }
}

async function loadAdminChains() {
  const guildId = document.getElementById('adminChainGuildSelect').value;
  const container = document.getElementById('adminChainsList');

  if (!guildId) {
    container.innerHTML = '<div class="empty-state"><p>Выбери сервер</p></div>';
    return;
  }

  container.innerHTML = '<div class="loading-spinner"></div>';

  try {
    const res = await fetch(`${API_BASE}/api/admin/chains/${guildId}`, {
      headers: { 'X-User-Id': adminUserId },
    });
    const data = await res.json();
    const chains = data.chains || [];

    if (!chains.length) {
      container.innerHTML = '<div class="empty-state"><p>Нет активных цепочек</p></div>';
      return;
    }

    container.innerHTML = chains.map(c => `
      <div class="chain-card">
        <div class="chain-names">
          <strong>${escapeHtml(c.follower_name)}</strong>
          <span class="chain-arrow">→</span>
          <strong>${escapeHtml(c.leader_name)}</strong>
        </div>
        <button class="btn-danger" onclick="removeChain('${guildId}','${c.follower_id}')">
          🔓 Убрать
        </button>
      </div>
    `).join('');
  } catch {
    container.innerHTML = '<div class="empty-state"><p>Ошибка загрузки</p></div>';
  }
}

async function removeChain(guildId, followerId) {
  await fetch(`${API_BASE}/api/admin/chains/${guildId}`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': adminUserId,
    },
    body: JSON.stringify({ follower_id: followerId }),
  });
  showToast('🔓 Цепочка удалена', 'success');
  loadAdminChains();
}

async function adminStopGuild(guildId) {
  await fetch(`${API_BASE}/api/admin/stop/${guildId}`, {
    method: 'POST',
    headers: { 'X-User-Id': adminUserId },
  });
  showToast('⏹️ Плеер остановлен', 'info');
  loadAdminGuilds();
}

function selectGuild(guildId) {
  GUILD_ID = guildId;
  window.history.pushState({}, '', `?guild=${guildId}`);
  closeAdminPanel();
  pollNow();
  showToast(`🔄 Переключено на сервер`, 'info');
}

// ── UTILS ─────────────────────────────────────────────────
function formatTime(secs) {
  secs = Math.floor(secs || 0);
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function showToast(msg, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'none';
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}
