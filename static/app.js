// Discord Music Player Mini App
(function() {
  'use strict';

  // Read URL query parameters passed by Discord Activity iframe or slash command
  const urlParams = new URLSearchParams(window.location.search);
  const initialGuildId = urlParams.get('guild_id') || null;
  const initialChannelId = urlParams.get('channel_id') || null;

  // State
  const state = {
    userId: localStorage.getItem('music_user_id') || '',
    userName: localStorage.getItem('music_user_name') || 'Пользователь Discord',
    userAvatar: localStorage.getItem('music_user_avatar') || '/static/activity_icon.jpg',
    currentSource: 'all',
    inVoice: false,
    guildId: initialGuildId,
    guildName: '',
    channelId: initialChannelId,
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
    isScrubbing: false,
    isAdjustingVolume: false,
    lang: localStorage.getItem('musicium_lang') || 'ru',
    lastTracks: [],
  };

  const SVG_ICONS = {
    play: '<svg viewBox="0 0 24 24" width="22" height="22" fill="#000"><path d="M8 5v14l11-7z"/></svg>',
    pause: '<svg viewBox="0 0 24 24" width="22" height="22" fill="#000"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>',
    skip: '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg>',
    prev: '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg>',
    volumeHigh: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>',
    volumeLow: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/></svg>',
    volumeMute: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/></svg>',
  };

  const I18N = {
    ru: {
      'app.miniBadge': 'Discord Mini App',
      'voice.searching': 'Поиск голосового канала...',
      'voice.notConnected': 'Не подключен',
      'voice.connected': 'Подключен',
      'voice.channelTitle': 'Статус голосового канала',
      'voice.refreshTitle': 'Обновить статус канала',
      'user.profileTitle': 'Ваш профиль Discord',
      'user.loggingIn': 'Вход...',
      'user.defaultName': 'Пользователь Discord',
      'user.clickToSelect': 'Нажмите для выбора',
      'user.loggedInAs': 'Вы вошли как: {name}',
      'user.profileActive': 'Discord профиль активен',
      'search.placeholder': 'Поиск треков, артистов или вставьте ссылку...',
      'search.clearTitle': 'Очистить поиск',
      'search.btn': 'Найти',
      'source.all': 'Все треки',
      'source.yt': 'YouTube Music',
      'source.sc': 'SoundCloud',
      'source.yt_albums': 'Альбомы YouTube',
      'source.albumYt': 'Альбом YouTube',
      'results.popular': 'Популярные рекомендации',
      'results.query': 'Результаты для «{query}»',
      'results.found': '{count} найдено',
      'results.tracksCount': '{count} треков',
      'results.loading': 'Ищем лучшую музыку на всех источниках...',
      'results.emptyTitle': 'Ничего не найдено',
      'results.emptyDesc': 'Попробуйте изменить поисковый запрос или выбрать другой источник',
      'track.play': 'Играть',
      'track.playNowTitle': 'Включить прямо сейчас',
      'track.addQueue': 'В очередь',
      'track.addQueueTitle': 'Добавить в конец очереди',
      'sidebar.queue': 'Очередь',
      'sidebar.history': 'История',
      'queue.title': 'Предстоящие треки',
      'queue.shuffle': 'Перемешать',
      'queue.shuffleTitle': 'Перемешать очередь',
      'queue.clear': 'Очистить',
      'queue.clearTitle': 'Очистить очередь',
      'queue.emptyTitle': 'Очередь пуста',
      'queue.emptySubtitle': 'Найдите трек и нажмите «+ В очередь»',
      'queue.removeTitle': 'Удалить из очереди',
      'history.title': 'Недавно играли',
      'history.emptyTitle': 'История пуста',
      'history.replayTitle': 'Включить снова',
      'player.noTrack': 'Трек не выбран',
      'player.selectSong': 'Выберите песню для воспроизведения',
      'player.queueFinished': 'Очередь завершена',
      'player.addNewTracks': 'Добавьте новые треки',
      'player.shuffleTitle': 'Перемешать',
      'player.prevTitle': 'Предыдущий / В начало',
      'player.playPauseTitle': 'Воспроизведение / Пауза',
      'player.nextTitle': 'Следующий трек',
      'player.voteSkipTitle': 'Голосовать за пропуск песни',
      'player.voteSkipLabel': 'Скип',
      'player.loopTitle': 'Повтор',
      'player.loopOff': 'Повтор: Выключен',
      'player.loopTrack': 'Повтор: Один трек',
      'player.loopQueue': 'Повтор: Вся очередь',
      'player.volumeTitle': 'Громкость',
      'player.stopTitle': 'Остановить и отключить бота',
      'player.stopLabel': 'Стоп',
      'modal.closeTitle': 'Закрыть',
      'toast.langSwitched': 'Язык интерфейса: Русский',
      'toast.channelRefreshed': 'Статус канала обновлен',
      'toast.voiceUpdated': 'Голосовой статус обновлен',
      'toast.queueShuffled': 'Очередь перемешана ({count} треков)',
      'toast.queueCleared': 'Очередь очищена',
      'toast.trackRemoved': 'Трек удален из очереди',
      'toast.trackSkipped': 'Трек пропущен!',
      'toast.voteRecorded': 'Голос учтён!',
      'toast.rewound': 'Перемотка в начало трека',
      'toast.stopped': 'Плеер остановлен, бот отключился от канала',
      'toast.searchError': 'Ошибка при поиске треков',
      'toast.networkError': 'Ошибка сетевого соединения с ботом',
      'toast.commandError': 'Ошибка отправки команды плееру',
      'toast.request': 'Запрос: {title}',
      'toast.nowPlaying': '🎶 Играет: {title} в канале {channel}',
      'toast.addedQueue': '➕ Добавлено в очередь: {title}',
      'toast.albumAdded': '💿 Альбом добавлен в очередь ({count} треков)',
      'toast.profileConnected': 'Подключен профиль: {name} ({channel})',
    },
    en: {
      'app.miniBadge': 'Discord Mini App',
      'voice.searching': 'Searching voice channel...',
      'voice.notConnected': 'Not connected',
      'voice.connected': 'Connected',
      'voice.channelTitle': 'Voice channel status',
      'voice.refreshTitle': 'Refresh channel status',
      'user.profileTitle': 'Your Discord profile',
      'user.loggingIn': 'Logging in...',
      'user.defaultName': 'Discord User',
      'user.clickToSelect': 'Click to select',
      'user.loggedInAs': 'Signed in as: {name}',
      'user.profileActive': 'Discord profile active',
      'search.placeholder': 'Search tracks, artists, or paste a link...',
      'search.clearTitle': 'Clear search',
      'search.btn': 'Search',
      'source.all': 'All tracks',
      'source.yt': 'YouTube Music',
      'source.sc': 'SoundCloud',
      'source.yt_albums': 'YouTube Albums',
      'source.albumYt': 'YouTube Album',
      'results.popular': 'Trending Recommendations',
      'results.query': 'Results for «{query}»',
      'results.found': '{count} found',
      'results.tracksCount': '{count} tracks',
      'results.loading': 'Searching the best music across all sources...',
      'results.emptyTitle': 'Nothing found',
      'results.emptyDesc': 'Try changing your search query or selecting another source',
      'track.play': 'Play',
      'track.playNowTitle': 'Play right now',
      'track.addQueue': 'Queue',
      'track.addQueueTitle': 'Add to end of queue',
      'sidebar.queue': 'Queue',
      'sidebar.history': 'History',
      'queue.title': 'Upcoming Tracks',
      'queue.shuffle': 'Shuffle',
      'queue.shuffleTitle': 'Shuffle queue',
      'queue.clear': 'Clear',
      'queue.clearTitle': 'Clear queue',
      'queue.emptyTitle': 'Queue is empty',
      'queue.emptySubtitle': 'Find a track and click «+ Queue»',
      'queue.removeTitle': 'Remove from queue',
      'history.title': 'Recently Played',
      'history.emptyTitle': 'History is empty',
      'history.replayTitle': 'Play again',
      'player.noTrack': 'No track selected',
      'player.selectSong': 'Choose a song to play',
      'player.queueFinished': 'Queue ended',
      'player.addNewTracks': 'Add new tracks',
      'player.shuffleTitle': 'Shuffle',
      'player.prevTitle': 'Previous / Restart',
      'player.playPauseTitle': 'Play / Pause',
      'player.nextTitle': 'Next track',
      'player.voteSkipTitle': 'Vote to skip song',
      'player.voteSkipLabel': 'Skip',
      'player.loopTitle': 'Repeat',
      'player.loopOff': 'Repeat: Off',
      'player.loopTrack': 'Repeat: Single track',
      'player.loopQueue': 'Repeat: Entire queue',
      'player.volumeTitle': 'Volume',
      'player.stopTitle': 'Stop and disconnect bot',
      'player.stopLabel': 'Stop',
      'modal.closeTitle': 'Close',
      'toast.langSwitched': 'Interface language: English',
      'toast.channelRefreshed': 'Channel status refreshed',
      'toast.voiceUpdated': 'Voice status updated',
      'toast.queueShuffled': 'Queue shuffled ({count} tracks)',
      'toast.queueCleared': 'Queue cleared',
      'toast.trackRemoved': 'Track removed from queue',
      'toast.trackSkipped': 'Track skipped!',
      'toast.voteRecorded': 'Vote recorded!',
      'toast.rewound': 'Rewound to start of track',
      'toast.stopped': 'Player stopped, bot disconnected',
      'toast.searchError': 'Error searching tracks',
      'toast.networkError': 'Network error connecting to bot',
      'toast.commandError': 'Error sending command to player',
      'toast.request': 'Request: {title}',
      'toast.nowPlaying': '🎶 Now playing: {title} in {channel}',
      'toast.addedQueue': '➕ Added to queue: {title}',
      'toast.albumAdded': '💿 Album added to queue ({count} tracks)',
      'toast.profileConnected': 'Profile connected: {name} ({channel})',
    }
  };

  function t(key, params = {}) {
    const lang = state.lang || 'ru';
    let text = (I18N[lang] && I18N[lang][key]) || (I18N['ru'] && I18N['ru'][key]) || key;
    for (const [k, v] of Object.entries(params)) {
      text = text.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v));
    }
    return text;
  }

  function setLanguage(lang, showNotification = false) {
    if (lang !== 'ru' && lang !== 'en') lang = 'ru';
    state.lang = lang;
    localStorage.setItem('musicium_lang', lang);
    document.documentElement.setAttribute('data-lang', lang);
    document.documentElement.setAttribute('lang', lang);

    const langBtnRu = document.getElementById('langBtnRu');
    const langBtnEn = document.getElementById('langBtnEn');
    if (langBtnRu && langBtnEn) {
      if (lang === 'ru') {
        langBtnRu.classList.add('active');
        langBtnEn.classList.remove('active');
      } else {
        langBtnRu.classList.remove('active');
        langBtnEn.classList.add('active');
      }
    }

    // Explicitly toggle display for all .lang-ru and .lang-en elements as a 100% guarantee
    document.querySelectorAll('.lang-ru').forEach(elem => {
      elem.style.setProperty('display', lang === 'ru' ? '' : 'none', 'important');
    });
    document.querySelectorAll('.lang-en').forEach(elem => {
      elem.style.setProperty('display', lang === 'en' ? '' : 'none', 'important');
    });

    document.querySelectorAll('[data-i18n]').forEach(elem => {
      const key = elem.getAttribute('data-i18n');
      if (key) {
        elem.textContent = t(key);
      }
    });

    document.querySelectorAll('[data-i18n-placeholder]').forEach(elem => {
      const key = elem.getAttribute('data-i18n-placeholder');
      if (key) {
        elem.placeholder = t(key);
      }
    });

    document.querySelectorAll('[data-i18n-title]').forEach(elem => {
      const key = elem.getAttribute('data-i18n-title');
      if (key) {
        elem.title = t(key);
      }
    });

    if (state.lastTracks && state.lastTracks.length > 0) {
      renderTracks(state.lastTracks);
    }
    if (state.player) {
      updatePlayerUI(state.player);
    } else {
      updatePlayerUI(null);
    }
    updateUserUI();

    if (showNotification) {
      showToast(t('toast.langSwitched'), 'info', 'fa-globe');
    }
  }

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
    // User Badge (Display only)
    userBadge: document.getElementById('userBadge'),
    userAvatar: document.getElementById('userAvatar'),
    userName: document.getElementById('userName'),
    userTag: document.getElementById('userTag'),
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
    dockArtDisc: document.getElementById('dockArtDisc'),
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
    volumeIconSvg: document.getElementById('volumeIconSvg'),
    volumeSlider: document.getElementById('volumeSlider'),
    volumeVal: document.getElementById('volumeVal'),
    toastContainer: document.getElementById('toastContainer'),
  };

  function updateVolumeIcon(vol) {
    if (!el.volumeIconSvg) return;
    if (vol <= 0) {
      el.volumeIconSvg.innerHTML = SVG_ICONS.volumeMute;
    } else if (vol <= 50) {
      el.volumeIconSvg.innerHTML = SVG_ICONS.volumeLow;
    } else {
      el.volumeIconSvg.innerHTML = SVG_ICONS.volumeHigh;
    }
  }

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
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    let iconSvg = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>';
    if (type === 'success') {
      iconSvg = '<svg viewBox="0 0 24 24" width="16" height="16" fill="#10b981"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>';
    } else if (type === 'error') {
      iconSvg = '<svg viewBox="0 0 24 24" width="16" height="16" fill="#ef4444"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>';
    }
    toast.innerHTML = `${iconSvg}<span>${message}</span>`;
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

        if (discordSdk.guildId) {
          state.guildId = discordSdk.guildId;
        }
        if (discordSdk.channelId) {
          state.channelId = discordSdk.channelId;
        }

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
    el.userName.textContent = state.userName || t('user.defaultName');
    el.userTag.textContent = state.userId ? `ID: ${state.userId.slice(-6)}` : t('user.clickToSelect');
    el.userAvatar.src = getSafeImageUrl(state.userAvatar);
    el.userAvatar.onerror = function() { this.src = '/static/activity_icon.jpg'; };
  }

  // Voice Channel Check
  async function checkUserVoice() {
    const guildQuery = state.guildId ? `&guild_id=${encodeURIComponent(state.guildId)}` : '';
    const chanQuery = state.channelId ? `&channel_id=${encodeURIComponent(state.channelId)}` : '';

    if (state.userId) {
      try {
        const resp = await fetch(`/api/user-voice?user_id=${encodeURIComponent(state.userId)}${guildQuery}${chanQuery}`);
        const data = await resp.json();
        if (data.in_voice) {
          state.inVoice = true;
          state.guildId = data.guild_id || state.guildId;
          state.guildName = data.guild_name || state.guildName;
          state.channelId = data.channel_id || state.channelId;
          state.channelName = data.channel_name || state.channelName;

          el.voiceIndicator.className = 'status-indicator connected';
          el.voiceLabel.textContent = state.guildName || t('voice.channelTitle');
          el.voiceChannelName.textContent = `🔊 ${state.channelName}`;
          el.voiceStatusPill.classList.add('active');
          sendWsSubscribe();
          return;
        }
      } catch (e) {
        console.error('Error checking user voice:', e);
      }
    }

    // If current user is not in voice, scan server voice channels
    state.inVoice = false;
    el.voiceIndicator.className = 'status-indicator';
    el.voiceLabel.textContent = state.guildName || t('voice.channelTitle');
    el.voiceChannelName.textContent = t('voice.notConnected');
    el.voiceStatusPill.classList.remove('active');

    try {
      const vuUrl = state.guildId ? `/api/voice-users?guild_id=${encodeURIComponent(state.guildId)}` : '/api/voice-users';
      const vuResp = await fetch(vuUrl);
      const vuData = await vuResp.json();
      if (vuData.voice_users && vuData.voice_users.length > 0) {
        // Only auto-pick if user has NO profile set at all
        if (!state.userId) {
          const u = vuData.voice_users[0];
          state.userId = u.id;
          state.userName = u.display_name;
          state.userAvatar = u.avatar;
          saveUser();
          showToast(t('toast.profileConnected', { name: u.display_name, channel: u.channel_name }), 'success');
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
          sendWsSubscribe();
        }
      }
    } catch (_) {}
  }

  // Check Bot status
  async function checkSystemStatus() {
    try {
      const resp = await fetch('/api/status');
      const data = await resp.json();
      if (el.yandexStatusDot) {
        if (data.yandex_configured) {
          el.yandexStatusDot.classList.add('active');
          el.yandexStatusDot.title = 'Яндекс.Музыка подключена';
        } else {
          el.yandexStatusDot.classList.remove('active');
          el.yandexStatusDot.title = 'Требуется YANDEX_MUSIC_TOKEN в .env';
        }
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
    el.resultsHeading.innerHTML = `<svg viewBox="0 0 24 24" width="20" height="20" fill="#00d2ff" style="display:inline-block;vertical-align:middle;margin-right:6px;"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg><span>${t('results.query', { query: escapeHtml(q) })}</span>`;

    try {
      const resp = await fetch(`/api/search?q=${encodeURIComponent(q)}&source=${state.currentSource}&limit=35`);
      const data = await resp.json();
      el.loadingState.style.display = 'none';

      if (data.notice) {
        showToast(data.notice, 'info');
      }

      if (!data.tracks || data.tracks.length === 0) {
        el.emptyState.style.display = 'flex';
        el.resultsCount.textContent = t('results.found', { count: 0 });
      } else {
        el.resultsCount.textContent = t('results.found', { count: data.tracks.length });
        renderTracks(data.tracks);
      }
    } catch (err) {
      el.loadingState.style.display = 'none';
      el.emptyState.style.display = 'flex';
      showToast(t('toast.searchError'), 'error');
    }
  }

  // Initial popular tracks
  async function loadRecommendations() {
    el.loadingState.style.display = 'flex';
    el.emptyState.style.display = 'none';
    el.tracksGrid.innerHTML = '';
    el.resultsHeading.innerHTML = `<svg class="section-title-svg" viewBox="0 0 24 24" width="20" height="20" fill="#ff4500" style="display:inline-block;vertical-align:middle;margin-right:6px;"><path d="M19.48 12.35c-1.57-4.08-7.16-4.3-5.81-10.23a10 10 0 0 0-4.67 2.68C6.33 7.42 5 11.23 5 14.18c0 4.14 3.03 7.82 7.22 7.82 4.19 0 7.78-3.68 7.78-7.82 0-.6-.09-1.22-.26-1.83h-.26zM12 20.5c-2.76 0-5-2.24-5-5 0-1.46.63-3.4 1.83-4.83.39 1.15 1.05 2.16 1.95 2.92.51.43 1.25.13 1.34-.53.2-1.51 1.01-2.84 2.15-3.69 1.07 1.48 1.73 3.32 1.73 5.13 0 3.31-1.79 6-4 6z"/></svg><span>${t('results.popular')}</span>`;

    try {
      const resp = await fetch(`/api/search?q=топ+хиты+2025&source=${state.currentSource}&limit=35`);
      const data = await resp.json();
      el.loadingState.style.display = 'none';
      if (data.tracks && data.tracks.length > 0) {
        el.resultsCount.textContent = t('results.tracksCount', { count: data.tracks.length });
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
    state.lastTracks = tracks;
    el.tracksGrid.innerHTML = '';
    tracks.forEach(track => {
      const card = document.createElement('div');
      card.className = 'track-card';
      
      const sourceClass = track.source || 'youtube';
      const sourceLabels = {
        youtube: 'YouTube',
        soundcloud: 'SoundCloud',
        yt_albums: t('source.albumYt'),
      };

      card.innerHTML = `
        <div class="card-top">
          <div class="card-thumb-wrapper">
            <img src="${getSafeImageUrl(track.thumbnail)}" alt="${escapeHtml(track.title)}" class="card-thumb" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null; this.src='/static/activity_icon.jpg';">
            <div class="card-play-overlay" title="${t('track.playNowTitle')}">
              <svg viewBox="0 0 24 24" width="22" height="22" fill="#ffffff"><path d="M8 5v14l11-7z"/></svg>
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
          <button class="btn-card-action btn-play-now" title="${t('track.playNowTitle')}">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M8 5v14l11-7z"/></svg> ${t('track.play')}
          </button>
          <button class="btn-card-action btn-add-queue" title="${t('track.addQueueTitle')}">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg> ${t('track.addQueue')}
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
      await checkUserVoice();
    }

    showToast(t('toast.request', { title: track.title }), 'info', 'fa-music');

    try {
      const resp = await fetch('/api/play', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: state.userId,
          guild_id: state.guildId,
          channel_id: state.channelId,
          track: track,
          play_now: playNow,
        })
      });

      const data = await resp.json();
      if (!data.success) {
        showToast(data.error || 'Error', 'error');
        return;
      }

      if (data.action === 'album_enqueued') {
        showToast(t('toast.albumAdded', { count: data.tracks_count }), 'success');
      } else if (data.action === 'started' || data.action === 'playing_now') {
        showToast(t('toast.nowPlaying', { title: track.title, channel: data.channel_name }), 'success');
      } else {
        showToast(t('toast.addedQueue', { title: track.title }), 'success');
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
      showToast(t('toast.networkError'), 'error');
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
      showToast(t('toast.commandError'), 'error');
      return null;
    }
  }

  // Vinyl Plate Spinning Animation Helper
  function setVinylSpinning(spinning) {
    const disc = el.dockArtDisc || document.getElementById('dockArtDisc');
    if (disc) {
      if (spinning) disc.classList.add('spinning');
      else disc.classList.remove('spinning');
    }
    if (el.dockArt) {
      if (spinning) el.dockArt.classList.add('spinning');
      else el.dockArt.classList.remove('spinning');
    }
    if (el.equalizerBars) {
      if (spinning) el.equalizerBars.classList.add('active');
      else el.equalizerBars.classList.remove('active');
    }
  }

  // Update Player UI from Player state
  function updatePlayerUI(playerState) {
    // Guild isolation guard: ignore updates from other servers
    if (state.guildId && playerState && playerState.guild_id && String(playerState.guild_id) !== String(state.guildId)) {
      return;
    }

    if (!playerState) {
      el.dockTitle.textContent = t('player.noTrack');
      el.dockTitle.removeAttribute('href');
      el.dockArtist.textContent = t('player.selectSong');
      el.dockSourceBadge.textContent = 'DISCORD';
      el.dockArt.src = '/static/activity_icon.jpg';
      setVinylSpinning(false);
      const playBtn = el.playIconSvg || el.btnPlayPause;
      if (playBtn) playBtn.innerHTML = SVG_ICONS.play;
      state.isPlaying = false;
      stopProgressTicker();
      updateQueueUI([]);
      updateVoteBadge(0, 1);
      return;
    }

    state.player = playerState;
    if (!state.guildId && playerState.guild_id) {
      state.guildId = playerState.guild_id;
    }

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
        setVinylSpinning(true);
        playBtn.innerHTML = SVG_ICONS.pause;
        startProgressTicker();
      } else {
        setVinylSpinning(false);
        playBtn.innerHTML = SVG_ICONS.play;
        stopProgressTicker();
      }
    } else {
      el.dockTitle.textContent = t('player.queueFinished');
      el.dockArtist.textContent = t('player.addNewTracks');
      setVinylSpinning(false);
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
    const loopSvg = '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z"/></svg>';
    if (playerState.loop_mode === 'track') {
      el.btnLoop.innerHTML = `${loopSvg}<span style="font-size:9px;position:absolute;margin-top:10px;font-weight:700">1</span>`;
      el.btnLoop.title = t('player.loopTrack');
    } else if (playerState.loop_mode === 'queue') {
      el.btnLoop.innerHTML = loopSvg;
      el.btnLoop.title = t('player.loopQueue');
    } else {
      el.btnLoop.innerHTML = loopSvg;
      el.btnLoop.title = t('player.loopOff');
    }

    // Update Volume UI
    if (!state.isAdjustingVolume) {
      const vol = playerState.volume !== undefined ? playerState.volume : 100;
      el.volumeSlider.value = vol;
      el.volumeVal.textContent = `${vol}%`;
      updateVolumeIcon(vol);
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
          <svg viewBox="0 0 24 24" width="48" height="48" fill="currentColor" opacity="0.3" style="display:block;margin:0 auto 10px;"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm0-12.5c-2.48 0-4.5 2.02-4.5 4.5s2.02 4.5 4.5 4.5 4.5-2.02 4.5-4.5-2.02-4.5-4.5-4.5zm0 6c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5z"/></svg>
          <p data-i18n="queue.emptyTitle">${t('queue.emptyTitle')}</p>
          <span data-i18n="queue.emptySubtitle">${t('queue.emptySubtitle')}</span>
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
        <button class="queue-item-remove" title="${t('queue.removeTitle')}" data-index="${idx}">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
        </button>
      `;

      item.querySelector('.queue-item-remove').addEventListener('click', async (e) => {
        e.stopPropagation();
        const res = await sendPlayerAction('remove', { index: idx });
        if (res && res.success) {
          showToast(t('toast.trackRemoved'), 'info');
        }
      });

      el.queueList.appendChild(item);
    });
  }

  function updateHistoryUI(history) {
    if (!history || history.length === 0) {
      el.historyList.innerHTML = `
        <div class="queue-empty">
          <svg viewBox="0 0 24 24" width="48" height="48" fill="currentColor" opacity="0.3" style="display:block;margin:0 auto 10px;"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>
          <p data-i18n="history.emptyTitle">${t('history.emptyTitle')}</p>
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
        <button class="btn-text-subtle" title="${t('history.replayTitle')}">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/></svg>
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
      if (state.isPlaying && state.duration > 0 && !state.isScrubbing) {
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

  // Subscribe helper for WebSocket
  function sendWsSubscribe() {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({
        action: 'subscribe',
        user_id: state.userId,
        guild_id: state.guildId
      }));
    }
  }

  // WebSocket Connection
  function setupWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      console.log('Connected to Music Player WebSocket');
      sendWsSubscribe();
    };

    state.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.event === 'player_update') {
          // Ignore events from other servers
          if (state.guildId && msg.data && msg.data.guild_id && String(msg.data.guild_id) !== String(state.guildId)) {
            return;
          }
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
      const q = state.guildId ? `guild_id=${encodeURIComponent(state.guildId)}` : `user_id=${encodeURIComponent(state.userId)}`;
      const resp = await fetch(`/api/player?${q}`);
      const data = await resp.json();
      if (data.player) {
        updatePlayerUI(data.player);
      }
    } catch (e) {
      console.error('Error fetching player:', e);
    }
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
      showToast(t('toast.channelRefreshed'), 'info');
    });

    el.voiceStatusPill.addEventListener('click', () => {
      checkUserVoice();
      showToast(t('toast.voiceUpdated'), 'info');
    });

    // User badge (Informational)
    el.userBadge.addEventListener('click', () => {
      showToast(state.userName ? t('user.loggedInAs', { name: state.userName }) : t('user.profileActive'), 'info', 'fa-user');
    });

    // Language switcher buttons
    const langBtnRu = document.getElementById('langBtnRu');
    const langBtnEn = document.getElementById('langBtnEn');
    if (langBtnRu) langBtnRu.addEventListener('click', () => setLanguage('ru', true));
    if (langBtnEn) langBtnEn.addEventListener('click', () => setLanguage('en', true));

    // Legal Documentation Modal & Tabs
    const legalModal = document.getElementById('legalModal');
    const openTermsBtn = document.getElementById('openTermsBtn');
    const openPrivacyBtn = document.getElementById('openPrivacyBtn');
    const closeLegalModalBtn = document.getElementById('closeLegalModalBtn');
    const closeLegalModalBtnBottom = document.getElementById('closeLegalModalBtnBottom');
    const tabTermsBtn = document.getElementById('tabTermsBtn');
    const tabPrivacyBtn = document.getElementById('tabPrivacyBtn');
    const termsDocPane = document.getElementById('termsDocPane');
    const privacyDocPane = document.getElementById('privacyDocPane');

    function showLegalTab(tab) {
      if (!legalModal) return;
      legalModal.style.display = 'flex';
      if (tab === 'privacy') {
        if (tabTermsBtn) tabTermsBtn.classList.remove('active');
        if (tabPrivacyBtn) tabPrivacyBtn.classList.add('active');
        if (termsDocPane) termsDocPane.style.display = 'none';
        if (privacyDocPane) privacyDocPane.style.display = 'block';
      } else {
        if (tabTermsBtn) tabTermsBtn.classList.add('active');
        if (tabPrivacyBtn) tabPrivacyBtn.classList.remove('active');
        if (termsDocPane) termsDocPane.style.display = 'block';
        if (privacyDocPane) privacyDocPane.style.display = 'none';
      }
    }

    function closeLegalModal() {
      if (legalModal) legalModal.style.display = 'none';
    }

    if (openTermsBtn) openTermsBtn.addEventListener('click', () => showLegalTab('terms'));
    if (openPrivacyBtn) openPrivacyBtn.addEventListener('click', () => showLegalTab('privacy'));
    if (closeLegalModalBtn) closeLegalModalBtn.addEventListener('click', closeLegalModal);
    if (closeLegalModalBtnBottom) closeLegalModalBtnBottom.addEventListener('click', closeLegalModal);
    if (tabTermsBtn) tabTermsBtn.addEventListener('click', () => showLegalTab('terms'));
    if (tabPrivacyBtn) tabPrivacyBtn.addEventListener('click', () => showLegalTab('privacy'));
    if (legalModal) {
      legalModal.addEventListener('click', (e) => {
        if (e.target === legalModal) closeLegalModal();
      });
    }

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
        showToast(t('toast.queueShuffled', { count: res.queue_size }), 'info', 'fa-shuffle');
      }
    });

    el.clearQueueBtn.addEventListener('click', async () => {
      const res = await sendPlayerAction('clear');
      if (res && res.success) {
        showToast(t('toast.queueCleared'), 'info', 'fa-trash-can');
      }
    });

    // Player Dock Controls:
    // Play/Pause
    el.btnPlayPause.addEventListener('click', async () => {
      const res = await sendPlayerAction('play_pause');
      if (res && res.success) {
        state.isPlaying = !res.is_paused;
        const playBtn = el.playIconSvg || el.btnPlayPause;
        if (state.isPlaying) {
          playBtn.innerHTML = SVG_ICONS.pause;
          setVinylSpinning(true);
          startProgressTicker();
        } else {
          playBtn.innerHTML = SVG_ICONS.play;
          setVinylSpinning(false);
          stopProgressTicker();
        }
      }
    });

    // Skip
    el.btnSkip.addEventListener('click', async () => {
      const res = await sendPlayerAction('skip', { forced: true });
      if (res && res.success) {
        showToast(t('toast.trackSkipped'), 'info', 'fa-forward-step');
      }
    });

    // Vote Skip
    el.btnVoteSkip.addEventListener('click', async () => {
      const res = await sendPlayerAction('vote_skip');
      if (res && res.success) {
        updateVoteBadge(res.votes, res.required);
        showToast(t('toast.voteRecorded'), 'info', 'fa-person-booth');
      }
    });

    // Previous / Restart track
    el.btnPrev.addEventListener('click', async () => {
      state.elapsed = 0;
      el.timeElapsed.textContent = '00:00';
      el.progressFill.style.width = '0%';
      await sendPlayerAction('seek', { seconds: 0 });
      showToast(t('toast.rewound'), 'info');
    });

    // Scrubber / Seek on Progress Bar (Click & Drag)
    function handleSeekFromEvent(e) {
      if (!state.duration || state.duration <= 0) return 0;
      const rect = el.progressTrack.getBoundingClientRect();
      const clientX = (e.touches && e.touches.length > 0) ? e.touches[0].clientX : (e.clientX !== undefined ? e.clientX : 0);
      const fraction = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      const targetSec = Math.floor(fraction * state.duration);
      state.elapsed = targetSec;
      el.timeElapsed.textContent = formatTime(targetSec);
      updateProgressBar();
      return targetSec;
    }

    el.progressTrack.addEventListener('mousedown', (e) => {
      if (!state.duration || state.duration <= 0) return;
      state.isScrubbing = true;
      el.progressTrack.classList.add('seeking');
      handleSeekFromEvent(e);
    });

    el.progressTrack.addEventListener('touchstart', (e) => {
      if (!state.duration || state.duration <= 0) return;
      state.isScrubbing = true;
      el.progressTrack.classList.add('seeking');
      handleSeekFromEvent(e);
    }, { passive: true });

    document.addEventListener('mousemove', (e) => {
      if (!state.isScrubbing) return;
      handleSeekFromEvent(e);
    });

    document.addEventListener('touchmove', (e) => {
      if (!state.isScrubbing) return;
      handleSeekFromEvent(e);
    }, { passive: true });

    document.addEventListener('mouseup', async (e) => {
      if (!state.isScrubbing) return;
      state.isScrubbing = false;
      el.progressTrack.classList.remove('seeking');
      const targetSec = handleSeekFromEvent(e);
      await sendPlayerAction('seek', { seconds: targetSec });
    });

    document.addEventListener('touchend', async (e) => {
      if (!state.isScrubbing) return;
      state.isScrubbing = false;
      el.progressTrack.classList.remove('seeking');
      await sendPlayerAction('seek', { seconds: state.elapsed });
    });

    // Loop
    el.btnLoop.addEventListener('click', async () => {
      const res = await sendPlayerAction('loop');
      if (res && res.success) {
        const modeLabels = { off: t('player.loopOff'), track: t('player.loopTrack'), queue: t('player.loopQueue') };
        showToast(modeLabels[res.loop_mode] || t('player.loopOff'), 'info', 'fa-repeat');
      }
    });

    // Shuffle dock button
    el.btnShuffle.addEventListener('click', async () => {
      const res = await sendPlayerAction('shuffle');
      if (res && res.success) {
        showToast(t('toast.queueShuffled', { count: res.queue_size }), 'info', 'fa-shuffle');
      }
    });

    // Stop
    el.btnStop.addEventListener('click', async () => {
      const res = await sendPlayerAction('stop');
      if (res && res.success) {
        showToast(t('toast.stopped'), 'info', 'fa-stop');
        updatePlayerUI(null);
      }
    });

    // Volume Slider
    let volDebounce = null;
    el.volumeSlider.addEventListener('mousedown', () => { state.isAdjustingVolume = true; });
    el.volumeSlider.addEventListener('touchstart', () => { state.isAdjustingVolume = true; }, { passive: true });
    document.addEventListener('mouseup', () => {
      if (state.isAdjustingVolume) {
        setTimeout(() => { state.isAdjustingVolume = false; }, 350);
      }
    });
    document.addEventListener('touchend', () => {
      if (state.isAdjustingVolume) {
        setTimeout(() => { state.isAdjustingVolume = false; }, 350);
      }
    });

    el.volumeSlider.addEventListener('input', (e) => {
      const val = parseInt(e.target.value) || 0;
      el.volumeVal.textContent = `${val}%`;
      updateVolumeIcon(val);
      state.isMuted = (val === 0);
      clearTimeout(volDebounce);
      volDebounce = setTimeout(() => {
        sendPlayerAction('volume', { value: val });
      }, 80);
    });

    // Mute toggle
    el.btnMute.addEventListener('click', () => {
      if (state.isMuted) {
        state.isMuted = false;
        const restoreVal = state.savedVolume > 0 ? state.savedVolume : 100;
        el.volumeSlider.value = restoreVal;
        el.volumeVal.textContent = `${restoreVal}%`;
        updateVolumeIcon(restoreVal);
        sendPlayerAction('volume', { value: restoreVal });
      } else {
        state.isMuted = true;
        state.savedVolume = parseInt(el.volumeSlider.value) || 100;
        el.volumeSlider.value = 0;
        el.volumeVal.textContent = '0%';
        updateVolumeIcon(0);
        sendPlayerAction('volume', { value: 0 });
      }
    });
  }

  // Boot
  async function init() {
    setLanguage(state.lang, false);
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
