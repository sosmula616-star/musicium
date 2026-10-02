// Discord Music Player Mini App
(function() {
  'use strict';

  // State
  const state = {
    userId: localStorage.getItem('music_user_id') || '',
    userName: localStorage.getItem('music_user_name') || 'Пользователь Discord',
    userAvatar: localStorage.getItem('music_user_avatar') || '/static/activity_icon.jpg',
    currentSource: 'all',
    inVoice: false,
    guildId: null,
    guildName: '',
    channelId: null,
    channelName: '',
    player: null,
    ws: null,
    progressTimer: null,
    elapsed: 0,
    duration: 0,
    isPlaying: false,
    isMuted: false,
    savedVolume: 100,
    searchTimeout: null,
  };

  const SVG_ICONS = {
    play: '<svg viewBox="0 0 24 24" width="22" height="22" fill="#000"><path d="M8 5v14l11-7z"/></svg>',
    pause: '<svg viewBox="0 0 24 24" width="22" height="22" fill="#000"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>',
    skip: '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg>',
    prev: '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg>',
    volumeHigh: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>',
    volumeMute: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/></svg>',
  };

  // DOM Elements
  const el = {
    searchInput: document.getElementById('searchInput'),
    searchClearBtn: document.getElementById('searchClearBtn'),
    searchSubmitBtn: document.getElementById('searchSubmitBtn'),
    sourceChips: document.querySelectorAll('.source-chip'),
    tracksGrid: document.getElementById('tracksGrid'),
    loadingState: document.getElementById('loadingState'),
    emptyState: document.getElementById('emptyState'),
    resultsHeading: document.getElementById('resultsHeading'),
    resultsCount: document.getElementById('resultsCount'),
    notificationBar: document.getElementById('notificationBar'),
    notifText: document.getElementById('notifText'),
    notifClose: document.getElementById('notifClose'),
    yandexStatusDot: document.getElementById('yandexStatusDot'),
    // Voice Status
    voiceStatusPill: document.getElementById('voiceStatusPill'),
    voiceIndicator: document.getElementById('voiceIndicator'),
    voiceLabel: document.getElementById('voiceLabel'),
    voiceChannelName: document.getElementById('voiceChannelName'),
    refreshVoiceBtn: document.getElementById('refreshVoiceBtn'),
    // User Badge
    userBadge: document.getElementById('userBadge'),
    userAvatar: document.getElementById('userAvatar'),
    userName: document.getElementById('userName'),
    userTag: document.getElementById('userTag'),
    // Modal
    userModal: document.getElementById('userModal'),
    closeUserModalBtn: document.getElementById('closeUserModalBtn'),
    voiceUsersList: document.getElementById('voiceUsersList'),
    manualUserIdInput: document.getElementById('manualUserIdInput'),
    saveManualIdBtn: document.getElementById('saveManualIdBtn'),
    // Sidebar
    sidebarTabs: document.querySelectorAll('.sidebar-tab'),
    queuePanel: document.getElementById('queuePanel'),
    historyPanel: document.getElementById('historyPanel'),
    queueCount: document.getElementById('queueCount'),
    queueList: document.getElementById('queueList'),
    historyList: document.getElementById('historyList'),
    shuffleQueueBtn: document.getElementById('shuffleQueueBtn'),
    clearQueueBtn: document.getElementById('clearQueueBtn'),
    // Player Dock
    dockArt: document.getElementById('dockArt'),
    dockTitle: document.getElementById('dockTitle'),
    dockArtist: document.getElementById('dockArtist'),
    dockSourceBadge: document.getElementById('dockSourceBadge'),
    equalizerBars: document.getElementById('equalizerBars'),
    btnPlayPause: document.getElementById('btnPlayPause'),
    playIcon: document.getElementById('playIcon'),
    playIconSvg: document.getElementById('playIconSvg'),
    btnPrev: document.getElementById('btnPrev'),
    btnSkip: document.getElementById('btnSkip'),
    btnVoteSkip: document.getElementById('btnVoteSkip'),
    voteSkipLabel: document.getElementById('voteSkipLabel'),
    voteCountBadge: document.getElementById('voteCountBadge'),
    btnLoop: document.getElementById('btnLoop'),
    btnShuffle: document.getElementById('btnShuffle'),
    btnStop: document.getElementById('btnStop'),
    timeElapsed: document.getElementById('timeElapsed'),
    timeDuration: document.getElementById('timeDuration'),
    progressTrack: document.getElementById('progressTrack'),
    progressFill: document.getElementById('progressFill'),
    btnMute: document.getElementById('btnMute'),
    volumeIcon: document.getElementById('volumeIcon'),
    volumeSlider: document.getElementById('volumeSlider'),
    volumeVal: document.getElementById('volumeVal'),
    toastContainer: document.getElementById('toastContainer'),
  };

  // Format seconds to mm:ss
  function formatTime(seconds) {
    if (!seconds || isNaN(seconds) || seconds <= 0) return '00:00';
    const s = Math.floor(seconds);
    const m = Math.floor(s / 60);
    const rem = s % 60;
    const h = Math.floor(m / 60);
    if (h > 0) {
      const minRem = m % 60;
      return `${h}:${minRem < 10 ? '0' : ''}${minRem}:${rem < 10 ? '0' : ''}${rem}`;
    }
    return `${m < 10 ? '0' : ''}${m}:${rem < 10 ? '0' : ''}${rem}`;
  }

  // Toast Notification
  function showToast(message, type = 'info', icon = null) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const defaultIcon = type === 'success' ? 'fa-circle-check' : (type === 'error' ? 'fa-circle-exclamation' : 'fa-info-circle');
    toast.innerHTML = `<i class="fa-solid ${icon || defaultIcon}"></i><span>${message}</span>`;
    el.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(40px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  // Initialize Discord Embedded App SDK if available
  async function initDiscordSdk() {
    if (window.DiscordSDK) {
      try {
        const discordSdk = new window.DiscordSDK.DiscordSDK('1555020109507199066');
        await discordSdk.ready();
        // Request authorization if inside Activity
        const { code } = await discordSdk.commands.authorize({
          client_id: '1555020109507199066',
          response_type: 'code',
          state: '',
          prompt: 'none',
          scope: ['identify', 'guilds', 'rpc.voice.read'],
        });

        // Exchange code for token
        const resp = await fetch('/api/token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code })
        });
        const tokenData = await resp.json();
        if (tokenData.access_token) {
          // Authenticate SDK
          const auth = await discordSdk.commands.authenticate({ access_token: tokenData.access_token });
          if (auth && auth.user) {
            state.userId = auth.user.id;
            state.userName = auth.user.global_name || auth.user.username;
            state.userAvatar = auth.user.avatar ? `https://cdn.discordapp.com/avatars/${auth.user.id}/${auth.user.avatar}.png` : state.userAvatar;
            saveUser();
          }
        }
      } catch (err) {
        console.log('Running in browser or Discord SDK standalone mode:', err);
      }
    }
    updateUserUI();
  }

  function getSafeImageUrl(url) {
    if (!url) return '/static/activity_icon.jpg';
    if (url.startsWith('/static/')) return url;
    return `/api/proxy-image?url=${encodeURIComponent(url)}`;
  }

  function saveUser() {
    localStorage.setItem('music_user_id', state.userId);
    localStorage.setItem('music_user_name', state.userName);
    localStorage.setItem('music_user_avatar', state.userAvatar);
    updateUserUI();
  }

  function updateUserUI() {
    el.userName.textContent = state.userName || 'Пользователь Discord';
    el.userTag.textContent = state.userId ? `ID: ${state.userId.slice(-6)}` : 'Нажмите для выбора';
    el.userAvatar.src = getSafeImageUrl(state.userAvatar);
    el.userAvatar.onerror = function() { this.src = '/static/activity_icon.jpg'; };
  }

  // Voice Channel Check
  async function checkUserVoice() {
    if (state.userId) {
      try {
        const resp = await fetch(`/api/user-voice?user_id=${state.userId}`);
        const data = await resp.json();
        if (data.in_voice) {
          state.inVoice = true;
          state.guildId = data.guild_id;
          state.guildName = data.guild_name;
          state.channelId = data.channel_id;
          state.channelName = data.channel_name;

          el.voiceIndicator.className = 'status-indicator connected';
          el.voiceLabel.textContent = data.guild_name;
          el.voiceChannelName.textContent = `🔊 ${data.channel_name}`;
          el.voiceStatusPill.classList.add('active');
          return;
        }
      } catch (e) {
        console.error('Error checking user voice:', e);
      }
    }

    // If current user is not in voice, scan server voice channels
    state.inVoice = false;
    el.voiceIndicator.className = 'status-indicator';
    el.voiceLabel.textContent = 'Голосовой канал';
    el.voiceChannelName.textContent = 'Не подключен';
    el.voiceStatusPill.classList.remove('active');

    try {
      const vuResp = await fetch('/api/voice-users');
      const vuData = await vuResp.json();
      if (vuData.voice_users && vuData.voice_users.length > 0) {
        // If there's an active person in voice and user is unset or not matching
        if (!state.userId || vuData.voice_users.length === 1) {
          const u = vuData.voice_users[0];
          state.userId = u.id;
          state.userName = u.display_name;
          state.userAvatar = u.avatar;
          saveUser();
          showToast(`Подключен профиль: ${u.display_name} (${u.channel_name})`, 'success');
          // Update status with channel info
          state.inVoice = true;
          state.guildId = u.guild_id;
          state.guildName = u.guild_name;
          state.channelId = u.channel_id;
          state.channelName = u.channel_name;
          el.voiceIndicator.className = 'status-indicator connected';
          el.voiceLabel.textContent = u.guild_name;
          el.voiceChannelName.textContent = `🔊 ${u.channel_name}`;
          el.voiceStatusPill.classList.add('active');
        }
      }
    } catch (_) {}
  }

  // Check Bot & Yandex status
  async function checkSystemStatus() {
    try {
      const resp = await fetch('/api/status');
      const data = await resp.json();
      if (data.yandex_configured) {
        el.yandexStatusDot.classList.add('active');
        el.yandexStatusDot.title = 'Яндекс.Музыка подключена';
      } else {
        el.yandexStatusDot.classList.remove('active');
        el.yandexStatusDot.title = 'Требуется YANDEX_MUSIC_TOKEN в .env';
      }
    } catch (e) {
      console.error('Status check error:', e);
    }
  }

  // Search tracks
  async function performSearch(query = null) {
    const q = query !== null ? query : el.searchInput.value.trim();
    if (!q) {
      loadRecommendations();
      return;
    }

    el.loadingState.style.display = 'flex';
    el.emptyState.style.display = 'none';
    el.tracksGrid.innerHTML = '';
    el.resultsHeading.innerHTML = `<i class="fa-solid fa-magnifying-glass text-accent"></i><span>Результаты для «${q}»</span>`;

    try {
      const resp = await fetch(`/api/search?q=${encodeURIComponent(q)}&source=${state.currentSource}`);
      const data = await resp.json();
      el.loadingState.style.display = 'none';

      if (data.notice) {
        showToast(data.notice, 'info');
      }

      if (!data.tracks || data.tracks.length === 0) {
        el.emptyState.style.display = 'flex';
        el.resultsCount.textContent = '0 найдено';
      } else {
        el.resultsCount.textContent = `${data.tracks.length} найдено`;
        renderTracks(data.tracks);
      }
    } catch (err) {
      el.loadingState.style.display = 'none';
      el.emptyState.style.display = 'flex';
      showToast('Ошибка при поиске треков', 'error');
    }
  }

  // Initial popular tracks
  async function loadRecommendations() {
    el.loadingState.style.display = 'flex';
    el.emptyState.style.display = 'none';
    el.tracksGrid.innerHTML = '';
    el.resultsHeading.innerHTML = `<i class="fa-solid fa-fire text-accent"></i><span>Популярные рекомендации</span>`;

    try {
      const resp = await fetch(`/api/search?q=top+music+hits+2025&source=${state.currentSource}`);
      const data = await resp.json();
      el.loadingState.style.display = 'none';
      if (data.tracks && data.tracks.length > 0) {
        el.resultsCount.textContent = `${data.tracks.length} треков`;
        renderTracks(data.tracks);
      } else {
        el.emptyState.style.display = 'flex';
      }
    } catch (e) {
      el.loadingState.style.display = 'none';
    }
  }

  // Render Track Cards
  function renderTracks(tracks) {
    el.tracksGrid.innerHTML = '';
    tracks.forEach(track => {
      const card = document.createElement('div');
      card.className = 'track-card';
      
      const sourceClass = track.source || 'youtube';
      const sourceLabels = {
        youtube: 'YouTube',
        soundcloud: 'SoundCloud',
        yandex: 'Яндекс.Музыка'
      };

      card.innerHTML = `
        <div class="card-top">
          <div class="card-thumb-wrapper">
            <img src="${getSafeImageUrl(track.thumbnail)}" alt="${escapeHtml(track.title)}" class="card-thumb" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null; this.src='/static/activity_icon.jpg';">
            <div class="card-play-overlay" title="Включить сейчас">
              <i class="fa-solid fa-play"></i>
            </div>
          </div>
          <div class="card-details">
            <a href="${track.url}" target="_blank" class="card-title" title="${escapeHtml(track.title)}">
              ${escapeHtml(track.title)}
            </a>
            <span class="card-artist" title="${escapeHtml(track.artist)}">${escapeHtml(track.artist)}</span>
            <div class="card-meta-row">
              <span class="source-tag ${sourceClass}">${sourceLabels[track.source] || track.source}</span>
              <span class="card-duration">${track.duration_str}</span>
            </div>
          </div>
        </div>
        <div class="card-actions">
          <button class="btn-card-action btn-play-now" title="Включить прямо сейчас">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M8 5v14l11-7z"/></svg> Играть
          </button>
          <button class="btn-card-action btn-add-queue" title="Добавить в конец очереди">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg> В очередь
          </button>
        </div>
      `;

      // Quick play on overlay click
      card.querySelector('.card-play-overlay').addEventListener('click', () => {
        playTrack(track, true);
      });

      // Play now button
      card.querySelector('.btn-play-now').addEventListener('click', () => {
        playTrack(track, true);
      });

      // Add to queue button
      card.querySelector('.btn-add-queue').addEventListener('click', () => {
        playTrack(track, false);
      });

      el.tracksGrid.appendChild(card);
    });
  }

  // Send play request to backend
  async function playTrack(track, playNow = false) {
    if (!state.userId) {
      openUserModal();
      showToast('Пожалуйста, выберите ваш профиль Discord', 'info');
      return;
    }

    showToast(`Запрос: ${track.title}`, 'info', 'fa-music');

    try {
      const resp = await fetch('/api/play', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: state.userId,
          track: track,
          play_now: playNow,
        })
      });

      const data = await resp.json();
      if (!data.success) {
        showToast(data.error || 'Ошибка при воспроизведении', 'error');
        // If not in voice, prompt to select active voice user or join
        if (data.error && data.error.includes('голосовом канале')) {
          openUserModal();
        }
        return;
      }

      if (data.action === 'started' || data.action === 'playing_now') {
        showToast(`🎶 Играет: ${track.title} в канале ${data.channel_name}`, 'success');
      } else {
        showToast(`➕ Добавлено в очередь: ${track.title}`, 'success');
      }

      // Immediately sync player state and queue
      if (data.player) {
        updatePlayerUI(data.player);
      } else {
        await fetchCurrentPlayer();
      }

      // Refresh voice status immediately
      checkUserVoice();

    } catch (err) {
      showToast('Ошибка сетевого соединения с ботом', 'error');
    }
  }

  // Send player action (pause, skip, vote_skip, volume, loop, shuffle, stop)
  async function sendPlayerAction(action, payload = {}) {
    try {
      const resp = await fetch('/api/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: action,
          user_id: state.userId,
          guild_id: state.guildId,
          ...payload
        })
      });
      const data = await resp.json();
      if (data && data.player) {
        updatePlayerUI(data.player);
      } else {
        await fetchCurrentPlayer();
      }
      return data;
    } catch (e) {
      showToast('Ошибка отправки команды плееру', 'error');
      return null;
    }
  }

  // Update Player UI from Player state
  function updatePlayerUI(playerState) {
    if (!playerState) {
      el.dockTitle.textContent = 'Трек не выбран';
      el.dockTitle.removeAttribute('href');
      el.dockArtist.textContent = 'Выберите песню для воспроизведения';
      el.dockSourceBadge.textContent = 'DISCORD';
      el.dockArt.src = 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=500&auto=format&fit=crop&q=60';
      el.dockArt.classList.remove('spinning');
      el.equalizerBars.classList.remove('active');
      el.playIcon.className = 'fa-solid fa-play';
      state.isPlaying = false;
      stopProgressTicker();
      updateQueueUI([]);
      updateVoteBadge(0, 1);
      return;
    }

    state.player = playerState;
    state.guildId = playerState.guild_id;

    const track = playerState.current_track;
    state.isPlaying = playerState.is_playing && !playerState.is_paused;

    // Update track metadata
    if (track) {
      el.dockTitle.textContent = track.title;
      el.dockTitle.href = track.url;
      el.dockArtist.textContent = track.artist;
      el.dockSourceBadge.textContent = (track.source || 'DISCORD').toUpperCase();
      el.dockArt.src = getSafeImageUrl(track.thumbnail);
      el.dockArt.onerror = function() { this.src = '/static/activity_icon.jpg'; };

      state.duration = track.duration || 0;
      state.elapsed = playerState.elapsed_seconds || 0;

      el.timeDuration.textContent = track.duration_str;
      el.timeElapsed.textContent = formatTime(state.elapsed);

      updateProgressBar();

      const playBtn = el.playIconSvg || el.btnPlayPause;
      if (state.isPlaying) {
        el.dockArt.classList.add('spinning');
        el.equalizerBars.classList.add('active');
        playBtn.innerHTML = SVG_ICONS.pause;
        startProgressTicker();
      } else {
        el.dockArt.classList.remove('spinning');
        el.equalizerBars.classList.remove('active');
        playBtn.innerHTML = SVG_ICONS.play;
        stopProgressTicker();
      }
    } else {
      el.dockTitle.textContent = 'Очередь завершена';
      el.dockArtist.textContent = 'Добавьте новые треки';
      el.dockArt.classList.remove('spinning');
      el.equalizerBars.classList.remove('active');
      const playBtn = el.playIconSvg || el.btnPlayPause;
      playBtn.innerHTML = SVG_ICONS.play;
      state.isPlaying = false;
      stopProgressTicker();
      el.timeElapsed.textContent = '00:00';
      el.timeDuration.textContent = '00:00';
      el.progressFill.style.width = '0%';
    }

    // Update Vote Skip count
    const votes = playerState.votes ? playerState.votes.count : 0;
    const req = playerState.votes ? playerState.votes.required : 1;
    updateVoteBadge(votes, req);

    // Update Loop button
    el.btnLoop.className = `control-btn btn-sm ${playerState.loop_mode !== 'off' ? 'active' : ''}`;
    if (playerState.loop_mode === 'track') {
      el.btnLoop.innerHTML = '<i class="fa-solid fa-repeat"></i><span style="font-size:9px;position:absolute;margin-top:10px">1</span>';
      el.btnLoop.title = 'Повтор: Один трек';
    } else if (playerState.loop_mode === 'queue') {
      el.btnLoop.innerHTML = '<i class="fa-solid fa-repeat"></i>';
      el.btnLoop.title = 'Повтор: Вся очередь';
    } else {
      el.btnLoop.innerHTML = '<i class="fa-solid fa-repeat"></i>';
      el.btnLoop.title = 'Повтор: Выключен';
    }

    // Update Volume UI
    if (!el.volumeSlider.matches(':active')) {
      el.volumeSlider.value = playerState.volume || 100;
      el.volumeVal.textContent = `${playerState.volume || 100}%`;
    }

    // Update Queue & History
    updateQueueUI(playerState.queue || []);
    updateHistoryUI(playerState.history || []);
  }

  function updateVoteBadge(count, required) {
    el.voteCountBadge.textContent = `${count}/${required}`;
    if (count > 0) {
      el.btnVoteSkip.style.borderColor = 'var(--accent-blurple)';
      el.btnVoteSkip.style.background = 'rgba(88, 101, 242, 0.35)';
    } else {
      el.btnVoteSkip.style.borderColor = '';
      el.btnVoteSkip.style.background = '';
    }
  }

  function updateQueueUI(queue) {
    el.queueCount.textContent = queue.length;
    if (queue.length === 0) {
      el.queueList.innerHTML = `
        <div class="queue-empty">
          <i class="fa-solid fa-compact-disc"></i>
          <p>Очередь пуста</p>
          <span>Найдите трек и нажмите «+ В очередь»</span>
        </div>
      `;
      return;
    }

    el.queueList.innerHTML = '';
    queue.forEach((track, idx) => {
      const item = document.createElement('div');
      item.className = 'queue-item';
      item.innerHTML = `
        <span class="queue-item-index">${idx + 1}</span>
        <img src="${getSafeImageUrl(track.thumbnail)}" alt="" class="queue-item-thumb" referrerpolicy="no-referrer" onerror="this.onerror=null; this.src='/static/activity_icon.jpg';">
        <div class="queue-item-info">
          <div class="queue-item-title">${escapeHtml(track.title)}</div>
          <div class="queue-item-sub">${escapeHtml(track.artist)} • ${track.duration_str}</div>
        </div>
        <button class="queue-item-remove" title="Удалить из очереди" data-index="${idx}">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
        </button>
      `;

      item.querySelector('.queue-item-remove').addEventListener('click', async (e) => {
        e.stopPropagation();
        const res = await sendPlayerAction('remove', { index: idx });
        if (res && res.success) {
          showToast('Трек удален из очереди', 'info');
        }
      });

      el.queueList.appendChild(item);
    });
  }

  function updateHistoryUI(history) {
    if (!history || history.length === 0) {
      el.historyList.innerHTML = `
        <div class="queue-empty">
          <i class="fa-regular fa-clock"></i>
          <p>История пуста</p>
        </div>
      `;
      return;
    }

    el.historyList.innerHTML = '';
    history.forEach((track) => {
      const item = document.createElement('div');
      item.className = 'queue-item';
      item.innerHTML = `
        <img src="${getSafeImageUrl(track.thumbnail)}" alt="" class="queue-item-thumb" referrerpolicy="no-referrer" onerror="this.onerror=null; this.src='/static/activity_icon.jpg';">
        <div class="queue-item-info">
          <div class="queue-item-title">${escapeHtml(track.title)}</div>
          <div class="queue-item-sub">${escapeHtml(track.artist)} • ${track.duration_str}</div>
        </div>
        <button class="btn-text-subtle" title="Включить снова">
          <i class="fa-solid fa-rotate-right"></i>
        </button>
      `;
      item.querySelector('button').addEventListener('click', () => {
        playTrack(track, true);
      });
      el.historyList.appendChild(item);
    });
  }

  // Progress Bar Ticker
  function startProgressTicker() {
    stopProgressTicker();
    state.progressTimer = setInterval(() => {
      if (state.isPlaying && state.duration > 0) {
        state.elapsed += 1;
        if (state.elapsed > state.duration) {
          state.elapsed = state.duration;
        }
        el.timeElapsed.textContent = formatTime(state.elapsed);
        updateProgressBar();
      }
    }, 1000);
  }

  function stopProgressTicker() {
    if (state.progressTimer) {
      clearInterval(state.progressTimer);
      state.progressTimer = null;
    }
  }

  function updateProgressBar() {
    if (state.duration <= 0) {
      el.progressFill.style.width = '0%';
      return;
    }
    const percent = Math.min(100, Math.max(0, (state.elapsed / state.duration) * 100));
    el.progressFill.style.width = `${percent}%`;
  }

  // WebSocket Connection
  function setupWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      console.log('Connected to Music Player WebSocket');
      // Request initial player state
      state.ws.send(JSON.stringify({
        action: 'get_state',
        user_id: state.userId,
        guild_id: state.guildId
      }));
    };

    state.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.event === 'player_update') {
          updatePlayerUI(msg.data);
        }
      } catch (e) {
        console.error('WS parse error:', e);
      }
    };

    state.ws.onclose = () => {
      console.log('WS disconnected, reconnecting in 3s...');
      setTimeout(setupWebSocket, 3000);
    };
  }

  // Initial fetch of player state
  async function fetchCurrentPlayer() {
    try {
      const resp = await fetch(`/api/player?user_id=${state.userId}`);
      const data = await resp.json();
      if (data.player) {
        updatePlayerUI(data.player);
      }
    } catch (e) {
      console.error('Error fetching player:', e);
    }
  }

  // Open / Close User Selector Modal
  async function openUserModal() {
    el.userModal.style.display = 'flex';
    el.manualUserIdInput.value = state.userId;
    el.voiceUsersList.innerHTML = '<div class="loading-state-sm"><i class="fa-solid fa-spinner fa-spin"></i> Сканирование голосовых каналов...</div>';

    try {
      const resp = await fetch('/api/voice-users');
      const data = await resp.json();
      if (!data.voice_users || data.voice_users.length === 0) {
        el.voiceUsersList.innerHTML = `
          <div style="padding:16px;text-align:center;color:var(--text-muted);font-size:13px">
            В голосовых каналах бот никого не обнаружил.<br>Зайдите в голосовой канал Discord и нажмите «Обновить»!
          </div>
        `;
      } else {
        el.voiceUsersList.innerHTML = '';
        data.voice_users.forEach(u => {
          const card = document.createElement('div');
          card.className = 'voice-user-card';
          card.innerHTML = `
            <img src="${getSafeImageUrl(u.avatar)}" alt="${escapeHtml(u.display_name)}" referrerpolicy="no-referrer" onerror="this.onerror=null; this.src='/static/activity_icon.jpg';">
            <div class="voice-user-meta">
              <div class="voice-user-name">${escapeHtml(u.display_name)}</div>
              <div class="voice-user-channel"><i class="fa-solid fa-volume-high"></i> ${escapeHtml(u.channel_name)} (${escapeHtml(u.guild_name)})</div>
            </div>
          `;
          card.addEventListener('click', () => {
            state.userId = u.id;
            state.userName = u.display_name;
            state.userAvatar = u.avatar;
            saveUser();
            checkUserVoice();
            fetchCurrentPlayer();
            closeUserModal();
            showToast(`Выбран профиль: ${u.display_name}`, 'success');
          });
          el.voiceUsersList.appendChild(card);
        });
      }
    } catch (err) {
      el.voiceUsersList.innerHTML = '<div style="color:var(--accent-red);padding:10px">Ошибка загрузки пользователей</div>';
    }
  }

  function closeUserModal() {
    el.userModal.style.display = 'none';
  }

  // Utility to escape HTML
  function escapeHtml(text) {
    if (!text) return '';
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // Attach Event Listeners
  function attachEvents() {
    // Search input
    el.searchInput.addEventListener('input', () => {
      el.searchClearBtn.style.display = el.searchInput.value ? 'block' : 'none';
      clearTimeout(state.searchTimeout);
      state.searchTimeout = setTimeout(() => {
        if (el.searchInput.value.trim().length >= 3) {
          performSearch();
        }
      }, 500);
    });

    el.searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        clearTimeout(state.searchTimeout);
        performSearch();
      }
    });

    el.searchSubmitBtn.addEventListener('click', () => {
      performSearch();
    });

    el.searchClearBtn.addEventListener('click', () => {
      el.searchInput.value = '';
      el.searchClearBtn.style.display = 'none';
      loadRecommendations();
    });

    // Source chips
    el.sourceChips.forEach(chip => {
      chip.addEventListener('click', () => {
        el.sourceChips.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        state.currentSource = chip.dataset.source;
        performSearch();
      });
    });

    // Voice refresh
    el.refreshVoiceBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      checkUserVoice();
      showToast('Статус канала обновлен', 'info');
    });

    el.voiceStatusPill.addEventListener('click', () => {
      checkUserVoice();
      openUserModal();
    });

    // User badge
    el.userBadge.addEventListener('click', openUserModal);
    el.closeUserModalBtn.addEventListener('click', closeUserModal);
    el.userModal.addEventListener('click', (e) => {
      if (e.target === el.userModal) closeUserModal();
    });

    el.saveManualIdBtn.addEventListener('click', () => {
      const val = el.manualUserIdInput.value.trim();
      if (val) {
        state.userId = val;
        state.userName = `User ${val.slice(-4)}`;
        saveUser();
        checkUserVoice();
        fetchCurrentPlayer();
        closeUserModal();
        showToast(`Discord ID сохранен: ${val}`, 'success');
      }
    });

    // Sidebar tab switching
    el.sidebarTabs.forEach(tab => {
      tab.addEventListener('click', () => {
        el.sidebarTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const target = tab.dataset.tab;
        if (target === 'queue') {
          el.queuePanel.style.display = 'block';
          el.historyPanel.style.display = 'none';
        } else {
          el.queuePanel.style.display = 'none';
          el.historyPanel.style.display = 'block';
        }
      });
    });

    // Shuffle & Clear queue
    el.shuffleQueueBtn.addEventListener('click', async () => {
      const res = await sendPlayerAction('shuffle');
      if (res && res.success) {
        showToast(`Очередь перемешана (${res.queue_size} треков)`, 'info', 'fa-shuffle');
      }
    });

    el.clearQueueBtn.addEventListener('click', async () => {
      const res = await sendPlayerAction('clear');
      if (res && res.success) {
        showToast('Очередь очищена', 'info', 'fa-trash-can');
      }
    });

    // Player Dock Controls:
    // Play/Pause
    el.btnPlayPause.addEventListener('click', async () => {
      const res = await sendPlayerAction('play_pause');
      if (res && res.success) {
        state.isPlaying = !res.is_paused;
        if (state.isPlaying) {
          el.playIcon.className = 'fa-solid fa-pause';
          el.dockArt.classList.add('spinning');
          el.equalizerBars.classList.add('active');
          startProgressTicker();
        } else {
          el.playIcon.className = 'fa-solid fa-play';
          el.dockArt.classList.remove('spinning');
          el.equalizerBars.classList.remove('active');
          stopProgressTicker();
        }
      }
    });

    // Skip
    el.btnSkip.addEventListener('click', async () => {
      const res = await sendPlayerAction('skip', { forced: true });
      if (res && res.success) {
        showToast(res.message || 'Трек пропущен!', 'info', 'fa-forward-step');
      }
    });

    // Vote Skip
    el.btnVoteSkip.addEventListener('click', async () => {
      const res = await sendPlayerAction('vote_skip');
      if (res && res.success) {
        updateVoteBadge(res.votes, res.required);
        showToast(res.message || 'Голос учтён!', 'info', 'fa-person-booth');
      }
    });

    // Previous / Restart
    el.btnPrev.addEventListener('click', () => {
      state.elapsed = 0;
      el.timeElapsed.textContent = '00:00';
      el.progressFill.style.width = '0%';
      showToast('Перемотка в начало трека', 'info');
    });

    // Loop
    el.btnLoop.addEventListener('click', async () => {
      const res = await sendPlayerAction('loop');
      if (res && res.success) {
        const modeLabels = { off: 'Выключен', track: 'Повтор трека', queue: 'Повтор очереди' };
        showToast(`Режим повтора: ${modeLabels[res.loop_mode]}`, 'info', 'fa-repeat');
      }
    });

    // Shuffle dock button
    el.btnShuffle.addEventListener('click', async () => {
      const res = await sendPlayerAction('shuffle');
      if (res && res.success) {
        showToast(`Очередь перемешана (${res.queue_size} треков)`, 'info', 'fa-shuffle');
      }
    });

    // Stop
    el.btnStop.addEventListener('click', async () => {
      const res = await sendPlayerAction('stop');
      if (res && res.success) {
        showToast('Плеер остановлен, бот отключился от канала', 'info', 'fa-stop');
        updatePlayerUI(null);
      }
    });

    // Volume Slider
    el.volumeSlider.addEventListener('input', (e) => {
      const val = parseInt(e.target.value);
      el.volumeVal.textContent = `${val}%`;
      sendPlayerAction('volume', { value: val });
    });

    // Mute toggle
    el.btnMute.addEventListener('click', () => {
      if (state.isMuted) {
        state.isMuted = false;
        el.volumeSlider.value = state.savedVolume;
        el.volumeVal.textContent = `${state.savedVolume}%`;
        el.volumeIcon.className = 'fa-solid fa-volume-high';
        sendPlayerAction('volume', { value: state.savedVolume });
      } else {
        state.isMuted = true;
        state.savedVolume = parseInt(el.volumeSlider.value) || 100;
        el.volumeSlider.value = 0;
        el.volumeVal.textContent = '0%';
        el.volumeIcon.className = 'fa-solid fa-volume-xmark';
        sendPlayerAction('volume', { value: 0 });
      }
    });
  }

  // Boot
  async function init() {
    updateUserUI();
    attachEvents();
    await initDiscordSdk();
    await checkSystemStatus();
    await checkUserVoice();
    setupWebSocket();
    await fetchCurrentPlayer();
    loadRecommendations();

    // Periodic voice check every 15s
    setInterval(checkUserVoice, 15000);
  }

  init();
})();
