/* ─────────────────────────────────────────────────────────
   Discord Music Player — Main App Logic
   ───────────────────────────────────────────────────────── */

'use strict';

// ── CONFIG ────────────────────────────────────────────────
const isBrowser = typeof window !== 'undefined';
const API_BASE = isBrowser ? (window.MUSICBOT_API || window.location.origin) : '';
const POLL_INTERVAL = 2500; // ms

// Get guild and channel ID from URL params or Discord SDK
const urlParams = (isBrowser && window.location) ? new URLSearchParams(window.location.search) : new URLSearchParams();
let GUILD_ID = urlParams.get('guild') || urlParams.get('guild_id') || '';
let CHANNEL_ID = urlParams.get('channel_id') || '';

let discordSdk = null;
let publicGuilds = [];

async function initDiscordSdk() {
  if (typeof DiscordSDK !== 'undefined' && window.DiscordSDK.DiscordSDK) {
    try {
      const clientId = urlParams.get('client_id') || '1555020109507199066';
      discordSdk = new window.DiscordSDK.DiscordSDK(clientId);
      await discordSdk.ready();
      console.log('Discord Embedded App SDK initialized successfully');
      
      if (discordSdk.guildId) {
        GUILD_ID = discordSdk.guildId;
      }
      if (discordSdk.channelId) {
        CHANNEL_ID = discordSdk.channelId;
      }
    } catch (e) {
      console.warn('Discord SDK init warning (standalone mode):', e);
    }
  }
}

// Platform icons SVG
const PLATFORM_ICONS = {
  youtube: `<svg viewBox="0 0 24 24" fill="#FF0000" width="14" height="14"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>`,
  soundcloud: `<svg viewBox="0 0 24 24" fill="#FF5500" width="14" height="14"><path d="M1.175 12.225c-.15 0-.254.097-.264.25l-.44 2.568.44 2.568c.01.15.114.25.264.25.147 0 .25-.1.272-.25L1.69 15.04l-.24-2.568c-.022-.15-.125-.247-.272-.247zm2.195-.35c-.172 0-.303.13-.303.3v5.25c0 .17.13.3.303.3.17 0 .3-.13.3-.3V12.17c0-.17-.13-.296-.3-.296zm2.2-.8c-.2 0-.352.15-.352.35v6.25c0 .2.152.35.353.35.2 0 .35-.15.35-.35v-6.25c0-.2-.15-.35-.35-.35zm2.24.15c-.22 0-.395.175-.395.4v6c0 .22.175.4.395.4.22 0 .4-.18.4-.4v-6c0-.225-.18-.4-.4-.4zm2.27-.4c-.25 0-.44.19-.44.44v6.7c0 .25.19.44.44.44s.44-.19.44-.44v-6.7c0-.25-.19-.44-.44-.44zm2.24.45c-.27 0-.49.22-.49.49v5.7c0 .27.22.49.49.49.27 0 .49-.22.49-.49v-5.7c0-.27-.22-.49-.49-.49zm2.24-.35c-.3 0-.54.24-.54.54v6.2c0 .3.24.54.54.54.3 0 .54-.24.54-.54v-6.2c0-.3-.24-.54-.54-.54zm2.24.1c-.32 0-.58.26-.58.58v5.8c0 .32.26.58.58.58.32 0 .58-.26.58-.58v-5.8c0-.32-.26-.58-.58-.58zm2.24-.5c-.35 0-.63.28-.63.63v6.5c0 .35.28.63.63.63.35 0 .63-.28.63-.63v-6.5c0-.35-.28-.63-.63-.63z"/></svg>`,
};

// ── STATE ─────────────────────────────────────────────────
let state = {
  playing: false,
  paused: false,
  current: null,
  queue: [],
  queue_count: 0,
  history_count: 0,
  volume: 50,
  loop_mode: 'none',
};

let searchResults = [];
let searchFilter = 'all';
let adminUserId = null;
let adminGuilds = [];
let pollTimer = null;
let progressTimer = null;
let progressStartTime = 0;
let progressStartElapsed = 0;
let volumeDebounce = null;

// ── INIT ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await initDiscordSdk();
  createParticles();
  setupSearchInput();
  await loadGuilds();
  startPolling();
  updatePlayerUI();
});

// ── BACKGROUND PARTICLES ──────────────────────────────────
function createParticles() {
  const container = document.getElementById('bgParticles');
  if (!container) return;
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

// ── GUILDS SELECTOR ───────────────────────────────────────
async function loadGuilds() {
  const select = document.getElementById('serverSelect');
  if (!select) return;

  try {
    const res = await fetch(`${API_BASE}/api/guilds`);
    const data = await res.json();
    publicGuilds = data.guilds || [];

    if (!publicGuilds.length) {
      select.innerHTML = '<option value="">Нет серверов</option>';
      return;
    }

    select.innerHTML = publicGuilds.map(g => `
      <option value="${g.id}" ${g.id === GUILD_ID ? 'selected' : ''}>
        ${g.playing ? '▶ ' : ''}${escapeHtml(g.name)}
      </option>
    `).join('');

    // If GUILD_ID is not set or not found in list, pick default
    if (!GUILD_ID || !publicGuilds.some(g => g.id === GUILD_ID)) {
      const activeGuild = publicGuilds.find(g => g.playing) || publicGuilds[0];
      GUILD_ID = activeGuild.id;
      select.value = GUILD_ID;
    }
  } catch (e) {
    console.error('Failed to load guilds:', e);
    select.innerHTML = '<option value="">Ошибка загрузки</option>';
  }
}

function selectGuild(guildId) {
  if (!guildId) return;
  GUILD_ID = guildId;
  const select = document.getElementById('serverSelect');
  if (select) select.value = guildId;

  if (window.history && window.history.pushState) {
    const newUrl = new URL(window.location);
    newUrl.searchParams.set('guild', guildId);
    window.history.pushState({}, '', newUrl);
  }

  showToast(`🌐 Переключено на сервер`, 'info');
  pollNow();
}

// ── SEARCH ────────────────────────────────────────────────
function setupSearchInput() {
  const input = document.getElementById('searchInput');
  if (!input) return;

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') doSearch();
  });

  let debounce;
  input.addEventListener('input', e => {
    const val = e.target.value.trim();
    if (val.startsWith('http')) {
      clearTimeout(debounce);
      debounce = setTimeout(() => doSearch(), 600);
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
      <span>Поиск треков...</span>
    </div>`;

  try {
    const res = await fetch(`${API_BASE}/api/search?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    searchResults = data.results || [];
    renderSearchResults();
  } catch (err) {
    resultsEl.innerHTML = `<div class="empty-state"><p>❌ Ошибка поиска</p></div>`;
    showToast('Ошибка при поиске', 'error');
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

  window.activeSearchResults = filtered;

  resultsEl.innerHTML = filtered.map((track, i) => `
    <div class="track-item" onclick="playTrackByIndex(${i})">
      ${track.thumbnail
        ? `<img class="track-thumb" src="${track.thumbnail}" alt="" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='flex'" loading="lazy">
           <div class="track-thumb-placeholder" style="display:none">🎵</div>`
        : `<div class="track-thumb-placeholder">🎵</div>`
      }
      <div class="track-meta">
        <div class="title">${escapeHtml(track.title)}</div>
        <div class="artist">${escapeHtml(track.artist || '')}</div>
        <div class="track-footer">
          <span class="platform-badge-small" style="background:${track.platform_color || '#999'}22;color:${track.platform_color || '#999'}">
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

function playTrackByIndex(index) {
  if (window.activeSearchResults && window.activeSearchResults[index]) {
    playTrack(window.activeSearchResults[index]);
  }
}

// ── PLAY TRACK FROM WEB ───────────────────────────────────
async function playTrack(track) {
  showToast(`⏳ Загрузка: ${track.title}...`, 'info');

  try {
    const res = await fetch(`${API_BASE}/api/play`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        guild_id: GUILD_ID ? parseInt(GUILD_ID) : 0,
        channel_id: CHANNEL_ID ? parseInt(CHANNEL_ID) : 0,
        track: track,
        user_id: adminUserId,
      }),
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`🎵 ${track.title} добавлена! (${data.channel || 'Голос'})`, 'success');
      if (data.guild_id) {
        GUILD_ID = data.guild_id;
        const select = document.getElementById('serverSelect');
        if (select) select.value = GUILD_ID;
      }
      pollNow();
    } else {
      showToast(data.error || 'Ошибка воспроизведения', 'error');
    }
  } catch (err) {
    showToast('Ошибка подключения к серверу', 'error');
  }
}

// ── PLAYER CONTROLS ───────────────────────────────────────
async function togglePlayPause() {
  if (!GUILD_ID) return;
  const isPlaying = state.playing && !state.paused;
  const endpoint = isPlaying ? 'pause' : 'resume';

  state.paused = isPlaying;
  state.playing = !isPlaying;
  updatePlayerUI();

  const data = await apiPost(`/api/player/${GUILD_ID}/${endpoint}`, {
    channel_id: CHANNEL_ID ? parseInt(CHANNEL_ID) : 0
  });
  if (data && data.state) {
    applyState(data.state);
  } else {
    pollNow();
  }
}

async function prevTrack() {
  if (!GUILD_ID) return;
  const data = await apiPost(`/api/player/${GUILD_ID}/prev`);
  if (data && data.ok) {
    showToast('⏮️ Предыдущий трек', 'info');
    if (data.state) applyState(data.state);
  } else {
    showToast(data?.error || 'Нет истории треков', 'error');
  }
}

async function skipTrack() {
  if (!GUILD_ID) return;
  const data = await apiPost(`/api/player/${GUILD_ID}/skip`);
  showToast('⏭️ Пропущено', 'info');
  if (data && data.state) applyState(data.state);
  pollNow();
}

async function stopPlayer() {
  if (!GUILD_ID) return;
  await apiPost(`/api/player/${GUILD_ID}/stop`);
  showToast('⏹️ Остановлено', 'info');
  state.playing = false;
  state.paused = false;
  state.current = null;
  state.queue = [];
  state.queue_count = 0;
  updatePlayerUI();
  updateQueueUI();
}

const loopModes = ['none', 'track', 'queue'];

async function toggleLoop() {
  let currentIndex = loopModes.indexOf(state.loop_mode || 'none');
  const nextMode = loopModes[(currentIndex + 1) % loopModes.length];

  state.loop_mode = nextMode;
  updateLoopBtn();

  const data = await apiPost(`/api/player/${GUILD_ID}/loop`, { mode: nextMode });
  const names = { none: 'Повтор выключен', track: '🔂 Повтор трека', queue: '🔁 Повтор очереди' };
  showToast(names[nextMode], 'info');
  if (data && data.state) applyState(data.state);
}

function updateLoopBtn() {
  const btn = document.getElementById('btnLoop');
  if (!btn) return;

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
  const volPct = Math.max(0, Math.min(100, parseInt(val, 10) || 0));
  const label = document.getElementById('volumeLabel');
  if (label) label.textContent = `${volPct}%`;
  state.volume = volPct / 100;

  clearTimeout(volumeDebounce);
  volumeDebounce = setTimeout(() => {
    if (!GUILD_ID) return;
    apiPost(`/api/player/${GUILD_ID}/volume`, { volume: state.volume });
  }, 150);
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
    console.error('API Error:', err);
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
    if (res.ok) {
      const newState = await res.json();
      applyState(newState);
    }
  } catch (err) {
    // silent fallback
  }
}

function applyState(newState) {
  const currentIdBefore = state.current?.id;
  state = { ...state, ...newState };

  if (state.volume !== undefined) {
    const volPct = Math.round((state.volume || 0.5) * 100);
    const slider = document.getElementById('volumeSlider');
    const label = document.getElementById('volumeLabel');
    if (slider && document.activeElement !== slider) {
      slider.value = volPct;
      if (label) label.textContent = `${volPct}%`;
    }
  }

  updatePlayerUI();
  updateQueueUI();

  const isPlaying = state.playing && !state.paused;
  if (isPlaying && !progressTimer) {
    startProgressTimer();
  } else if (!isPlaying && progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }

  if (state.current?.id !== currentIdBefore) {
    progressStartTime = Date.now();
    progressStartElapsed = 0;
  }
}

// ── PROGRESS TIMER ────────────────────────────────────────
function startProgressTimer() {
  if (progressTimer) clearInterval(progressTimer);
  progressStartTime = Date.now();

  progressTimer = setInterval(() => {
    if (!state.playing || state.paused) return;
    const elapsed = (Date.now() - progressStartTime) / 1000 + progressStartElapsed;
    const duration = state.current?.duration || 0;

    const fill = document.getElementById('progressFill');
    const thumb = document.getElementById('progressThumb');
    const timeElapsed = document.getElementById('timeElapsed');

    if (duration > 0) {
      const pct = Math.min((elapsed / duration) * 100, 100);
      if (fill) fill.style.width = `${pct}%`;
      if (thumb) thumb.style.left = `${pct}%`;
      if (timeElapsed) timeElapsed.textContent = formatTime(elapsed);
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

  if (playIcon && pauseIcon) {
    playIcon.style.display = isPlaying ? 'none' : 'block';
    pauseIcon.style.display = isPlaying ? 'block' : 'none';
  }

  if (albumArt) albumArt.classList.toggle('playing', isPlaying);
  if (albumGlow) albumGlow.classList.toggle('active', isPlaying);

  if (state.current) {
    document.getElementById('trackTitle').textContent = state.current.title || 'Unknown';
    document.getElementById('trackArtist').textContent = state.current.artist || 'Unknown';
    document.getElementById('timeDuration').textContent = state.current.duration_str || '0:00';

    if (state.current.thumbnail && albumArt) {
      const currentThumb = state.current.thumbnail;
      if (albumArt.getAttribute('data-loaded-thumb') !== currentThumb) {
        albumArt.setAttribute('data-loaded-thumb', currentThumb);
        const img = new Image();
        img.src = currentThumb;
        img.alt = 'Cover';
        img.className = 'album-art-img';
        img.onload = () => {
          albumArt.innerHTML = '';
          albumArt.appendChild(img);
        };
        img.onerror = () => {
          albumArt.innerHTML = `<div class="album-placeholder">
            <svg width="60" height="60" viewBox="0 0 24 24" fill="none">
              <path d="M9 18V5l12-2v13" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              <circle cx="6" cy="18" r="3" stroke="rgba(255,255,255,0.3)" stroke-width="1.5"/>
              <circle cx="18" cy="16" r="3" stroke="rgba(255,255,255,0.3)" stroke-width="1.5"/>
            </svg>
          </div>`;
        };
      }
    }

    const badge = document.getElementById('platformBadge');
    const badgeInner = document.getElementById('platformBadgeInner');
    if (badge && badgeInner && state.current.platform_icon) {
      badge.style.display = 'block';
      badgeInner.style.background = (state.current.platform_color || '#666') + '33';
      badgeInner.innerHTML = PLATFORM_ICONS[state.current.platform_icon] || '🎵';
    }

    if (state.current.platform_color && albumGlow) {
      albumGlow.style.background = `radial-gradient(ellipse, ${state.current.platform_color}44 0%, transparent 70%)`;
    }
  } else {
    document.getElementById('trackTitle').textContent = 'Ничего не играет';
    document.getElementById('trackArtist').textContent = 'Выбери трек для прослушивания';
    if (albumArt) {
      albumArt.innerHTML = `<div class="album-placeholder">
        <svg width="60" height="60" viewBox="0 0 24 24" fill="none">
          <path d="M9 18V5l12-2v13" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          <circle cx="6" cy="18" r="3" stroke="rgba(255,255,255,0.3)" stroke-width="1.5"/>
          <circle cx="18" cy="16" r="3" stroke="rgba(255,255,255,0.3)" stroke-width="1.5"/>
        </svg>
      </div>`;
    }
    const fill = document.getElementById('progressFill');
    const thumb = document.getElementById('progressThumb');
    if (fill) fill.style.width = '0%';
    if (thumb) thumb.style.left = '0%';
    document.getElementById('timeElapsed').textContent = '0:00';
    document.getElementById('timeDuration').textContent = '0:00';
    const badge = document.getElementById('platformBadge');
    if (badge) badge.style.display = 'none';
  }

  updateLoopBtn();
  updateYtEmbed();
}

function updateQueueUI() {
  const queueEl = document.getElementById('queueList');
  const countBadge = document.getElementById('queueCountBadge');
  if (!queueEl || !countBadge) return;

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
  const overlay = document.getElementById('adminOverlay');
  if (overlay) overlay.classList.toggle('open');
}

function closeAdmin(event) {
  if (event.target === document.getElementById('adminOverlay')) {
    closeAdminPanel();
  }
}

function closeAdminPanel() {
  const overlay = document.getElementById('adminOverlay');
  if (overlay) overlay.classList.remove('open');
}

async function adminLogin() {
  const input = document.getElementById('adminIdInput');
  const userId = input ? input.value.trim() : '';
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
  if (!container) return;
  container.innerHTML = '<div class="loading-spinner"></div>';

  try {
    const res = await fetch(`${API_BASE}/api/admin/guilds`, {
      headers: { 'X-User-Id': adminUserId },
    });
    const data = await res.json();
    adminGuilds = data.guilds || [];

    const sel = document.getElementById('adminChainGuildSelect');
    if (sel) {
      sel.innerHTML = '<option value="">Выбери сервер...</option>' +
        adminGuilds.map(g => `<option value="${g.id}">${escapeHtml(g.name)}</option>`).join('');
    }

    if (!adminGuilds.length) {
      container.innerHTML = '<div class="empty-state"><p>Нет доступных серверов</p></div>';
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
            ${guild.member_count} участников ${guild.has_player ? '· 🎵 Играет' : ''}
          </div>
          ${guild.player_state?.current
            ? `<div class="meta" style="color:var(--purple)">▶ ${escapeHtml(guild.player_state.current.title)}</div>`
            : ''}
        </div>
        <div class="guild-actions">
          ${guild.has_player ? `<button class="btn-danger" onclick="adminStopGuild('${guild.id}')">⏹ Стоп</button>` : ''}
          <button class="btn-primary" style="font-size:12px;padding:6px 12px" onclick="selectGuild('${guild.id}');closeAdminPanel();">Открыть</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = '<div class="empty-state"><p>Ошибка загрузки серверов</p></div>';
  }
}

async function loadAdminChains() {
  const select = document.getElementById('adminChainGuildSelect');
  const guildId = select ? select.value : '';
  const container = document.getElementById('adminChainsList');
  if (!container) return;

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
    container.innerHTML = '<div class="empty-state"><p>Ошибка загрузки цепочек</p></div>';
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

// ── YOUTUBE EMBED ─────────────────────────────────────────
let ytEmbedOpen = true;
let lastYtVideoId = null;

function extractYouTubeId(url) {
  if (!url) return null;
  const m = url.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|v\/))([\w-]{11})/);
  return m ? m[1] : null;
}

function updateYtEmbed() {
  const wrap = document.getElementById('ytEmbedWrap');
  const iframe = document.getElementById('ytIframe');
  if (!wrap || !iframe) return;

  const track = state.current;
  if (!track || track.platform !== 'YouTube') {
    wrap.style.display = 'none';
    iframe.src = '';
    lastYtVideoId = null;
    return;
  }

  const videoId = track.id || extractYouTubeId(track.url);
  if (!videoId) {
    wrap.style.display = 'none';
    return;
  }

  if (videoId !== lastYtVideoId) {
    lastYtVideoId = videoId;
    iframe.src = `https://www.youtube.com/embed/${videoId}?rel=0&modestbranding=1&mute=1&autoplay=1`;
    const iframeWrap = document.getElementById('ytIframeWrap');
    if (iframeWrap) iframeWrap.style.display = ytEmbedOpen ? 'block' : 'none';
  }

  wrap.style.display = 'block';
}

function toggleYtEmbed() {
  ytEmbedOpen = !ytEmbedOpen;
  const iframeWrap = document.getElementById('ytIframeWrap');
  const icon = document.getElementById('ytToggleIcon');
  if (iframeWrap) iframeWrap.style.display = ytEmbedOpen ? 'block' : 'none';
  if (icon) {
    icon.innerHTML = ytEmbedOpen
      ? '<polyline points="18 15 12 9 6 15"/>'
      : '<polyline points="6 9 12 15 18 9"/>';
  }
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
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}
