// Discord Music Player Mini App • YouTube Music Edition
(function() {
  'use strict';

  // Read URL query parameters passed by Discord Activity iframe or slash command
  const urlParams = new URLSearchParams(window.location.search);
  const initialGuildId = urlParams.get('guild_id') || null;
  const initialChannelId = urlParams.get('channel_id') || null;

  // Safe JSON storage helper
  function loadJson(key, defaultVal) {
    try {
      const data = localStorage.getItem(key);
      return data ? JSON.parse(data) : defaultVal;
    } catch (_) {
      return defaultVal;
    }
  }

  function saveJson(key, val) {
    try {
      localStorage.setItem(key, JSON.stringify(val));
    } catch (_) {}
  }

  // Initial custom playlists if none exist (matching Screenshot 2: GTA 5)
  const defaultPlaylists = [
    {
      id: 'pl_gta5',
      name: 'GTA 5',
      author: 'Benzo',
      tracks: [
        {
          title: 'Passengers & Pilots',
          artist: 'Big Baby Tape',
          duration_str: '2:15',
          thumbnail: 'https://i.ytimg.com/vi/aL3XGq4JgT4/hqdefault.jpg',
          source: 'youtube',
          url: 'https://music.youtube.com/search?q=Big+Baby+Tape+Passengers+Pilots'
        },
        {
          title: 'Malo 2.0',
          artist: 'ЕГОР КРИД, OG Buda, Toxi$',
          duration_str: '2:38',
          thumbnail: 'https://i.ytimg.com/vi/X_6Yq3Zp1Mo/hqdefault.jpg',
          source: 'youtube',
          url: 'https://music.youtube.com/search?q=Егор+Крид+OG+Buda+Toxi$+Malo+2.0'
        },
        {
          title: 'Overseas',
          artist: 'D-Block Europe & Central Cee',
          duration_str: '3:42',
          thumbnail: 'https://i.ytimg.com/vi/v5uL7Y92Z6g/hqdefault.jpg',
          source: 'youtube',
          url: 'https://music.youtube.com/search?q=D-Block+Europe+Overseas'
        }
      ]
    }
  ];

  // State
  const state = {
    userId: localStorage.getItem('music_user_id') || '',
    userName: localStorage.getItem('music_user_name') || 'Пользователь Discord',
    userAvatar: localStorage.getItem('music_user_avatar') || '/static/activity_icon.jpg',
    currentSource: 'all',
    currentView: 'home', // 'home' | 'search' | 'liked' | 'playlist' | 'history' | 'queue'
    selectedPlaylistId: null,
    trackToAddToPlaylist: null,
    inVoice: false,
    guildId: initialGuildId,
    guildName: '',
    channelId: initialChannelId,
    channelName: '',
    channelMembers: [],
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
    likedTracks: loadJson('musicium_liked_tracks', []),
    customPlaylists: loadJson('musicium_custom_playlists', defaultPlaylists),
    historyTracks: loadJson('musicium_history_tracks', []),
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
      'nav.home': 'Главная',
      'nav.search': 'Поиск',
      'nav.queue': 'Очередь',
      'sidebar.newPlaylist': 'Новый',
      'sidebar.liked': 'Понравившаяся музыка',
      'sidebar.autoCreated': 'Создан автоматически',
      'sidebar.history': 'История',
      'sidebar.recentlyPlayed': 'Недавно играли',
      'voice.searching': 'Поиск канала...',
      'voice.notConnected': 'Не подключен',
      'voice.connected': 'Подключен',
      'voice.channelTitle': 'Статус голосового канала',
      'voice.refreshTitle': 'Обновить статус канала',
      'voice.membersTitle': 'Участники в канале',
      'voice.dropdownEmpty': 'Подключитесь к голосовому каналу Discord, чтобы слушать и управлять ботом',
      'voice.mustBeInVoice': 'Управлять ботом могут только участники голосового канала!',
      'user.profileTitle': 'Ваш профиль Discord',
      'user.loggingIn': 'Вход...',
      'user.defaultName': 'Пользователь Discord',
      'user.clickToSelect': 'Нажмите для выбора',
      'user.loggedInAs': 'Вы вошли как: {name}',
      'user.profileActive': 'Discord профиль активен',
      'search.placeholder': 'Поиск треков, альбомов, исполнителей...',
      'search.clearTitle': 'Очистить поиск',
      'search.btn': 'Найти',
      'source.all': 'Все',
      'source.yt': 'YouTube Music',
      'source.sc': 'SoundCloud',
      'source.yt_albums': 'Альбомы',
      'source.albumYt': 'Альбом YouTube',
      'home.recommended': 'Рекомендуем',
      'home.longTimeNoListen': 'Вы давно не слушали',
      'home.albumsForYou': 'Альбомы для вас',
      'results.searchTitle': 'Результаты поиска',
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
      'track.addToPlaylist': 'В плейлист',
      'track.like': 'Нравится',
      'sidebar.queue': 'Очередь',
      'queue.title': 'Предстоящие треки',
      'queue.kicker': 'Текущий сеанс',
      'queue.shuffle': 'Перемешать',
      'queue.shuffleTitle': 'Перемешать очередь',
      'queue.clear': 'Очистить',
      'queue.clearTitle': 'Очистить очередь',
      'queue.emptyTitle': 'Очередь пуста',
      'queue.emptySubtitle': 'Найдите трек и нажмите «+ В очередь»',
      'queue.removeTitle': 'Удалить из очереди',
      'history.title': 'История прослушанного',
      'history.clear': 'Очистить историю',
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
      'playlist.modalTitle': 'Новый плейлист',
      'playlist.nameLabel': 'Название плейлиста',
      'playlist.cancel': 'Отмена',
      'playlist.create': 'Создать',
      'playlist.playAll': 'Включить всё',
      'playlist.delete': 'Удалить плейлист',
      'playlist.kicker': 'Пользовательский плейлист',
      'playlist.addModalTitle': 'Добавить в плейлист',
      'playlist.done': 'Готово',
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
      'toast.likedAdded': '❤️ Добавлено в «Понравившиеся»',
      'toast.likedRemoved': 'Удалено из «Понравившихся»',
      'toast.playlistCreated': 'Плейлист «{name}» создан!',
      'toast.playlistDeleted': 'Плейлист удален',
      'toast.trackAddedToPlaylist': 'Трек добавлен в «{name}»',
      'toast.trackRemovedFromPlaylist': 'Трек удален из плейлиста',
      'toast.alreadyInPlaylist': 'Этот трек уже есть в плейлисте',
    },
    en: {
      'app.miniBadge': 'Discord Mini App',
      'nav.home': 'Home',
      'nav.search': 'Search',
      'nav.queue': 'Queue',
      'sidebar.newPlaylist': 'New',
      'sidebar.liked': 'Liked Music',
      'sidebar.autoCreated': 'Auto-created',
      'sidebar.history': 'History',
      'sidebar.recentlyPlayed': 'Recently played',
      'voice.searching': 'Searching channel...',
      'voice.notConnected': 'Not connected',
      'voice.connected': 'Connected',
      'voice.channelTitle': 'Voice channel status',
      'voice.refreshTitle': 'Refresh channel status',
      'voice.membersTitle': 'Channel Members',
      'voice.dropdownEmpty': 'Connect to a Discord voice channel to listen and control the bot',
      'voice.mustBeInVoice': 'Only members in the voice channel can control the bot!',
      'user.profileTitle': 'Your Discord profile',
      'user.loggingIn': 'Logging in...',
      'user.defaultName': 'Discord User',
      'user.clickToSelect': 'Click to select',
      'user.loggedInAs': 'Signed in as: {name}',
      'user.profileActive': 'Discord profile active',
      'search.placeholder': 'Search tracks, albums, artists...',
      'search.clearTitle': 'Clear search',
      'search.btn': 'Search',
      'source.all': 'All',
      'source.yt': 'YouTube Music',
      'source.sc': 'SoundCloud',
      'source.yt_albums': 'Albums',
      'source.albumYt': 'YouTube Album',
      'home.recommended': 'Recommended',
      'home.longTimeNoListen': 'Listen again',
      'home.albumsForYou': 'Albums for you',
      'results.searchTitle': 'Search Results',
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
      'track.addToPlaylist': 'To playlist',
      'track.like': 'Like',
      'sidebar.queue': 'Queue',
      'queue.title': 'Upcoming Tracks',
      'queue.kicker': 'Active session',
      'queue.shuffle': 'Shuffle',
      'queue.shuffleTitle': 'Shuffle queue',
      'queue.clear': 'Clear',
      'queue.clearTitle': 'Clear queue',
      'queue.emptyTitle': 'Queue is empty',
      'queue.emptySubtitle': 'Find a track and click «+ Queue»',
      'queue.removeTitle': 'Remove from queue',
      'history.title': 'Listening History',
      'history.clear': 'Clear history',
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
      'playlist.modalTitle': 'New Playlist',
      'playlist.nameLabel': 'Playlist Name',
      'playlist.cancel': 'Cancel',
      'playlist.create': 'Create',
      'playlist.playAll': 'Play all',
      'playlist.delete': 'Delete playlist',
      'playlist.kicker': 'User playlist',
      'playlist.addModalTitle': 'Add to Playlist',
      'playlist.done': 'Done',
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
      'toast.likedAdded': '❤️ Added to Liked Music',
      'toast.likedRemoved': 'Removed from Liked Music',
      'toast.playlistCreated': 'Playlist «{name}» created!',
      'toast.playlistDeleted': 'Playlist deleted',
      'toast.trackAddedToPlaylist': 'Track added to «{name}»',
      'toast.trackRemovedFromPlaylist': 'Track removed from playlist',
      'toast.alreadyInPlaylist': 'This track is already in the playlist',
    }
  };

  // Curated items from Screenshot 2
  const CURATED_RECOMMENDED = [
    { title: 'Passengers & Pilots', artist: 'Big Baby Tape', duration_str: '2:15', thumbnail: 'https://i.ytimg.com/vi/aL3XGq4JgT4/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/search?q=Big+Baby+Tape+Passengers+Pilots' },
    { title: 'Ova', artist: 'Lyov и Xudo', duration_str: '3:04', thumbnail: 'https://i.ytimg.com/vi/qfV0N_9mS2Y/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/search?q=Lyov+Xudo+Ova' },
    { title: 'Slimed Out', artist: 'Mamba Cinco и Zahsosaa', duration_str: '2:40', thumbnail: 'https://i.ytimg.com/vi/fJ9m_X6gI8k/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/search?q=Mamba+Cinco+Slimed+Out' },
    { title: 'Malo 2.0', artist: 'ЕГОР КРИД, OG Buda, Toxi$', duration_str: '2:38', thumbnail: 'https://i.ytimg.com/vi/X_6Yq3Zp1Mo/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/search?q=Егор+Крид+OG+Buda+Toxi$+Malo+2.0' },
    { title: 'Venom (Music From The Motion Picture)', artist: 'Eminem', duration_str: '4:29', thumbnail: 'https://i.ytimg.com/vi/8CdcCD5V-d8/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/search?q=Eminem+Venom' },
    { title: 'Spasi L', artist: 'Dav', duration_str: '2:52', thumbnail: 'https://i.ytimg.com/vi/pZ5NsG3JB2M/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/search?q=Dav+Spasi+L' },
    { title: 'Alors on danse (Radio Edit)', artist: 'Stromae', duration_str: '3:28', thumbnail: 'https://i.ytimg.com/vi/VHoT4N43jK8/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/search?q=Stromae+Alors+on+danse' },
    { title: 'Overseas', artist: 'D-Block Europe & Central Cee', duration_str: '3:42', thumbnail: 'https://i.ytimg.com/vi/v5uL7Y92Z6g/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/search?q=D-Block+Europe+Overseas' },
    { title: 'Държавен Кючек', artist: 'Leo Band', duration_str: '3:15', thumbnail: 'https://i.ytimg.com/vi/6p3pW2K7jQ8/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/search?q=Leo+Band+Държавен+Кючек' },
    { title: 'Party Funk', artist: 'Young Madz & MC Zudo Bo', duration_str: '2:12', thumbnail: 'https://i.ytimg.com/vi/9B6g0s-W8yI/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/search?q=Young+Madz+Party+Funk' },
    { title: 'Pour It Up', artist: 'Rihanna', duration_str: '2:41', thumbnail: 'https://i.ytimg.com/vi/ehcVomMexkY/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/search?q=Rihanna+Pour+It+Up' },
    { title: 'Layli', artist: 'Jamshid Ximmatov', duration_str: '3:30', thumbnail: 'https://i.ytimg.com/vi/FjIThTV2-Dg/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/search?q=Jamshid+Ximmatov+Layli' }
  ];

  const CURATED_QUICK_PICKS = [
    { title: 'ДИНАСТИЯ', artist: 'VILLIAN и madk1d', thumbnail: 'https://i.ytimg.com/vi/w7ejDZ8SWv8/hqdefault.jpg', source: 'youtube' },
    { title: 'Caramelldansen (Speedy Mixes)', artist: 'Caramella Girls', thumbnail: 'https://i.ytimg.com/vi/A67ZkAd1wmI/hqdefault.jpg', source: 'youtube' },
    { title: 'все хотят меня', artist: 'gotlib', thumbnail: 'https://i.ytimg.com/vi/y81Wz8f9jEU/hqdefault.jpg', source: 'youtube' },
    { title: 'Там ревели горы', artist: 'Miyagi & Эндшпиль', thumbnail: 'https://i.ytimg.com/vi/q_VnS1Y97Jc/hqdefault.jpg', source: 'youtube' },
    { title: 'Sweater Weather', artist: 'The Neighbourhood', thumbnail: 'https://i.ytimg.com/vi/GCdwKhTtNNw/hqdefault.jpg', source: 'youtube' },
    { title: 'Где прошла ты', artist: 'Кравц & Гио Пика', thumbnail: 'https://i.ytimg.com/vi/7_Zp_Lw38yY/hqdefault.jpg', source: 'youtube' }
  ];

  const CURATED_ALBUMS = [
    { title: 'Viva La Vida', artist: 'SODA LUV', subtitle: 'Альбом • SODA LUV', thumbnail: 'https://i.ytimg.com/vi/p8m8g1w_J4A/hqdefault.jpg', source: 'yt_albums' },
    { title: 'АРТЁМ', artist: 'SLAVA MARLOW', subtitle: 'EP • SLAVA MARLOW', thumbnail: 'https://i.ytimg.com/vi/9xG2b3q5w6Y/hqdefault.jpg', source: 'yt_albums' },
    { title: 'SODA LUV', artist: 'SODA LUV', subtitle: 'Альбом • SODA LUV', thumbnail: 'https://i.ytimg.com/vi/8CdcCD5V-d8/hqdefault.jpg', source: 'yt_albums' },
    { title: "BOYS DON'T CRY", artist: 'GONE.Fludd', subtitle: 'Альбом • GONE.Fludd', thumbnail: 'https://i.ytimg.com/vi/6p3pW2K7jQ8/hqdefault.jpg', source: 'yt_albums' },
    { title: 'DUMMY BOY', artist: '6ix9ine', subtitle: 'Альбом • 6ix9ine', thumbnail: 'https://i.ytimg.com/vi/fJ9m_X6gI8k/hqdefault.jpg', source: 'yt_albums' },
    { title: 'Whenever You Need Somebody', artist: 'Rick Astley', subtitle: 'Альбом • Rick Astley', thumbnail: 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg', source: 'yt_albums' }
  ];

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

    document.querySelectorAll('.lang-ru').forEach(elem => {
      elem.style.setProperty('display', lang === 'ru' ? '' : 'none', 'important');
    });
    document.querySelectorAll('.lang-en').forEach(elem => {
      elem.style.setProperty('display', lang === 'en' ? '' : 'none', 'important');
    });

    document.querySelectorAll('[data-i18n]').forEach(elem => {
      const key = elem.getAttribute('data-i18n');
      if (key) elem.textContent = t(key);
    });

    document.querySelectorAll('[data-i18n-placeholder]').forEach(elem => {
      const key = elem.getAttribute('data-i18n-placeholder');
      if (key) elem.placeholder = t(key);
    });

    document.querySelectorAll('[data-i18n-title]').forEach(elem => {
      const key = elem.getAttribute('data-i18n-title');
      if (key) elem.title = t(key);
    });

    if (state.lastTracks && state.lastTracks.length > 0) {
      renderTracks(state.lastTracks);
    }
    renderHomeView();
    renderSidebarPlaylists();
    updateUserUI();

    if (showNotification) {
      showToast(t('toast.langSwitched'), 'info', 'fa-globe');
    }
  }

  // DOM Elements Cache
  const el = {
    // Views
    viewHome: document.getElementById('viewHome'),
    viewSearch: document.getElementById('viewSearch'),
    viewLiked: document.getElementById('viewLiked'),
    viewPlaylist: document.getElementById('viewPlaylist'),
    viewHistory: document.getElementById('viewHistory'),
    viewQueue: document.getElementById('viewQueue'),

    // Nav
    navHome: document.getElementById('navHome'),
    navSearch: document.getElementById('navSearch'),
    navQueue: document.getElementById('navQueue'),
    navLiked: document.getElementById('navLiked'),
    navHistory: document.getElementById('navHistory'),
    brandLogoHome: document.getElementById('brandLogoHome'),
    btnNewPlaylist: document.getElementById('btnNewPlaylist'),
    customPlaylistsList: document.getElementById('customPlaylistsList'),
    sidebarQueueCount: document.getElementById('sidebarQueueCount'),

    // Search
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

    // Voice Widget (Requirement 2)
    voiceWidgetContainer: document.getElementById('voiceWidgetContainer'),
    voiceStatusPill: document.getElementById('voiceStatusPill'),
    voiceIndicator: document.getElementById('voiceIndicator'),
    voiceChannelName: document.getElementById('voiceChannelName'),
    voiceMembersCountBadge: document.getElementById('voiceMembersCountBadge'),
    voiceMembersDropdown: document.getElementById('voiceMembersDropdown'),
    dropdownMembersCount: document.getElementById('dropdownMembersCount'),
    voiceMembersList: document.getElementById('voiceMembersList'),
    refreshVoiceBtn: document.getElementById('refreshVoiceBtn'),

    // Profile
    userBadge: document.getElementById('userBadge'),
    userAvatar: document.getElementById('userAvatar'),
    userName: document.getElementById('userName'),
    userTag: document.getElementById('userTag'),

    // Home Shelves
    curatedTracksGrid: document.getElementById('curatedTracksGrid'),
    quickPicksRow: document.getElementById('quickPicksRow'),
    albumsRow: document.getElementById('albumsRow'),

    // Liked View
    likedTracksContainer: document.getElementById('likedTracksContainer'),
    likedCountText: document.getElementById('likedCountText'),
    btnPlayAllLiked: document.getElementById('btnPlayAllLiked'),

    // Playlist View
    currentPlaylistTitle: document.getElementById('currentPlaylistTitle'),
    playlistCountText: document.getElementById('playlistCountText'),
    btnPlayAllPlaylist: document.getElementById('btnPlayAllPlaylist'),
    btnDeleteCurrentPlaylist: document.getElementById('btnDeleteCurrentPlaylist'),
    customPlaylistTracksContainer: document.getElementById('customPlaylistTracksContainer'),

    // History View
    historyTracksContainer: document.getElementById('historyTracksContainer'),
    historyCountText: document.getElementById('historyCountText'),
    btnClearHistoryBtn: document.getElementById('btnClearHistoryBtn'),

    // Queue View
    queueList: document.getElementById('queueList'),
    queueMetaCount: document.getElementById('queueMetaCount'),
    shuffleQueueBtn: document.getElementById('shuffleQueueBtn'),
    clearQueueBtn: document.getElementById('clearQueueBtn'),

    // Player Dock
    dockArt: document.getElementById('dockArt'),
    dockTitle: document.getElementById('dockTitle'),
    dockArtist: document.getElementById('dockArtist'),
    dockSourceBadge: document.getElementById('dockSourceBadge'),
    equalizerBars: document.getElementById('equalizerBars'),
    btnLikeCurrent: document.getElementById('btnLikeCurrent'),
    btnPlayPause: document.getElementById('btnPlayPause'),
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
    btnToggleQueue: document.getElementById('btnToggleQueue'),
    toastContainer: document.getElementById('toastContainer'),

    // Modals
    newPlaylistModal: document.getElementById('newPlaylistModal'),
    newPlaylistTitleInput: document.getElementById('newPlaylistTitleInput'),
    saveNewPlaylistBtn: document.getElementById('saveNewPlaylistBtn'),
    cancelNewPlaylistBtn: document.getElementById('cancelNewPlaylistBtn'),
    closeNewPlaylistBtn: document.getElementById('closeNewPlaylistBtn'),
    addToPlaylistModal: document.getElementById('addToPlaylistModal'),
    addToPlaylistTrackInfo: document.getElementById('addToPlaylistTrackInfo'),
    addToPlaylistList: document.getElementById('addToPlaylistList'),
    closeAddToPlaylistBtn: document.getElementById('closeAddToPlaylistBtn'),
    closeAddToPlaylistModalBtn: document.getElementById('closeAddToPlaylistModalBtn'),
  };

  // Safe Image URL Proxy Helper
  function getSafeImageUrl(url) {
    if (!url) return '/static/activity_icon.jpg';
    if (url.startsWith('/') || url.startsWith('data:')) return url;
    return `/api/proxy-image?url=${encodeURIComponent(url)}`;
  }

  // Format seconds to mm:ss
  function formatTime(sec) {
    if (!sec || isNaN(sec) || sec < 0) return '00:00';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }

  // Toast Notifications
  function showToast(message, type = 'info', iconClass = null) {
    const container = el.toastContainer;
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    let iconHtml = '';
    if (iconClass) {
      iconHtml = `<i class="fa-solid ${iconClass} toast-icon"></i>`;
    } else if (type === 'success') {
      iconHtml = `<svg viewBox="0 0 24 24" width="16" height="16" fill="#2ba640" class="toast-icon"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>`;
    } else if (type === 'error' || type === 'warning') {
      iconHtml = `<svg viewBox="0 0 24 24" width="16" height="16" fill="#ff0000" class="toast-icon"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>`;
    } else {
      iconHtml = `<svg viewBox="0 0 24 24" width="16" height="16" fill="#aaaaaa" class="toast-icon"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>`;
    }

    toast.innerHTML = `${iconHtml}<span class="toast-text">${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
      toast.classList.add('show');
    }, 10);

    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 300);
    }, 3500);
  }

  // Discord Embedded App SDK Init
  async function initDiscordSdk() {
    if (window.DiscordSDK) {
      try {
        const discordSdk = new window.DiscordSDK.DiscordSDK();
        await discordSdk.ready();

        if (discordSdk.guildId) state.guildId = discordSdk.guildId;
        if (discordSdk.channelId) state.channelId = discordSdk.channelId;

        const { code } = await discordSdk.commands.authorize({
          client_id: '1555020109507199066',
          response_type: 'code',
          state: '',
          prompt: 'none',
          scope: ['identify', 'guilds', 'rpc.voice.read'],
        });

        const resp = await fetch('/api/token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code })
        });
        const tokenData = await resp.json();

        if (tokenData.access_token) {
          const auth = await discordSdk.commands.authenticate({ access_token: tokenData.access_token });
          if (auth && auth.user) {
            state.userId = auth.user.id;
            state.userName = auth.user.global_name || auth.user.username;
            state.userAvatar = auth.user.avatar
              ? `https://cdn.discordapp.com/avatars/${auth.user.id}/${auth.user.avatar}.png`
              : '/static/activity_icon.jpg';
            saveUser();
          }
        }
      } catch (err) {
        console.warn('Discord SDK running in standalone/web browser mode:', err);
      }
    }
  }

  function saveUser() {
    localStorage.setItem('music_user_id', state.userId);
    localStorage.setItem('music_user_name', state.userName);
    localStorage.setItem('music_user_avatar', state.userAvatar);
    updateUserUI();
  }

  function updateUserUI() {
    if (el.userName) el.userName.textContent = state.userName || t('user.defaultName');
    if (el.userTag) el.userTag.textContent = state.userId ? `ID: ${state.userId.slice(-6)}` : t('user.clickToSelect');
    if (el.userAvatar) {
      el.userAvatar.src = getSafeImageUrl(state.userAvatar);
      el.userAvatar.onerror = function() { this.src = '/static/activity_icon.jpg'; };
    }
  }

  // Voice Channel Check & Channel Members Rendering (Requirement 2)
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
          state.channelMembers = data.channel_members || [];

          if (el.voiceIndicator) el.voiceIndicator.className = 'status-indicator connected';
          if (el.voiceChannelName) el.voiceChannelName.textContent = state.channelName;
          if (el.voiceMembersCountBadge) el.voiceMembersCountBadge.textContent = state.channelMembers.length;
          if (el.dropdownMembersCount) el.dropdownMembersCount.textContent = state.channelMembers.length;
          if (el.voiceStatusPill) el.voiceStatusPill.classList.add('active');

          renderVoiceMembers(state.channelMembers);
          sendWsSubscribe();
          return;
        }
      } catch (e) {
        console.error('Error checking user voice:', e);
      }
    }

    // If not in voice, scan voice users on server
    state.inVoice = false;
    state.channelMembers = [];
    if (el.voiceIndicator) el.voiceIndicator.className = 'status-indicator';
    if (el.voiceChannelName) el.voiceChannelName.textContent = t('voice.notConnected');
    if (el.voiceMembersCountBadge) el.voiceMembersCountBadge.textContent = '0';
    if (el.dropdownMembersCount) el.dropdownMembersCount.textContent = '0';
    if (el.voiceStatusPill) el.voiceStatusPill.classList.remove('active');
    renderVoiceMembers([]);

    try {
      const vuUrl = state.guildId ? `/api/voice-users?guild_id=${encodeURIComponent(state.guildId)}` : '/api/voice-users';
      const vuResp = await fetch(vuUrl);
      const vuData = await vuResp.json();
      if (vuData.voice_users && vuData.voice_users.length > 0 && !state.userId) {
        const u = vuData.voice_users[0];
        state.userId = u.id;
        state.userName = u.display_name;
        state.userAvatar = u.avatar;
        saveUser();
        showToast(t('toast.profileConnected', { name: u.display_name, channel: u.channel_name }), 'success');
        checkUserVoice();
      }
    } catch (_) {}
  }

  function renderVoiceMembers(members) {
    if (!el.voiceMembersList) return;
    if (!members || members.length === 0) {
      el.voiceMembersList.innerHTML = `<div class="dropdown-empty-state"><p>${t('voice.dropdownEmpty')}</p></div>`;
      return;
    }
    el.voiceMembersList.innerHTML = '';
    members.forEach(m => {
      const isBot = Boolean(m.bot);
      const isMe = String(m.id) === String(state.userId);
      const row = document.createElement('div');
      row.className = 'voice-member-item';
      row.innerHTML = `
        <img src="${getSafeImageUrl(m.avatar || '/static/activity_icon.jpg')}" class="voice-member-avatar" onerror="this.src='/static/activity_icon.jpg'">
        <div class="voice-member-info">
          <span class="voice-member-name">${escapeHtml(m.display_name || m.name)}</span>
          <div class="voice-member-badges">
            ${isBot ? '<span class="badge-tag badge-bot">BOT</span>' : ''}
            ${isMe ? '<span class="badge-tag badge-you">ВЫ</span>' : ''}
          </div>
        </div>
      `;
      el.voiceMembersList.appendChild(row);
    });
  }

  // Check Bot System Status
  async function checkSystemStatus() {
    try {
      await fetch('/api/status');
    } catch (e) {
      console.error('Status check error:', e);
    }
  }

  // Switch View Router
  function switchView(viewName, playlistId = null) {
    state.currentView = viewName;
    state.selectedPlaylistId = playlistId;

    // Nav active states
    document.querySelectorAll('.ytm-nav-item, .ytm-playlist-item').forEach(item => {
      item.classList.remove('active');
    });

    if (viewName === 'home' && el.navHome) el.navHome.classList.add('active');
    else if (viewName === 'search' && el.navSearch) el.navSearch.classList.add('active');
    else if (viewName === 'queue' && el.navQueue) el.navQueue.classList.add('active');
    else if (viewName === 'liked' && el.navLiked) el.navLiked.classList.add('active');
    else if (viewName === 'history' && el.navHistory) el.navHistory.classList.add('active');
    else if (viewName === 'playlist' && playlistId) {
      const plBtn = document.querySelector(`.ytm-playlist-item[data-playlist-id="${playlistId}"]`);
      if (plBtn) plBtn.classList.add('active');
    }

    // View panels toggle
    const views = [el.viewHome, el.viewSearch, el.viewLiked, el.viewPlaylist, el.viewHistory, el.viewQueue];
    views.forEach(v => {
      if (v) v.style.display = 'none';
    });

    if (viewName === 'home' && el.viewHome) {
      el.viewHome.style.display = 'block';
      renderHomeView();
    } else if (viewName === 'search' && el.viewSearch) {
      el.viewSearch.style.display = 'block';
    } else if (viewName === 'liked' && el.viewLiked) {
      el.viewLiked.style.display = 'block';
      renderLikedView();
    } else if (viewName === 'playlist' && el.viewPlaylist) {
      el.viewPlaylist.style.display = 'block';
      renderPlaylistView(playlistId);
    } else if (viewName === 'history' && el.viewHistory) {
      el.viewHistory.style.display = 'block';
      renderHistoryView();
    } else if (viewName === 'queue' && el.viewQueue) {
      el.viewQueue.style.display = 'block';
      renderQueueView();
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // Render Home View (Screenshot 2: Curated 3-column + Square cards + Albums)
  function renderHomeView() {
    // 1. Curated 3-column Grid
    if (el.curatedTracksGrid) {
      el.curatedTracksGrid.innerHTML = '';
      CURATED_RECOMMENDED.forEach(track => {
        const isLiked = isTrackLiked(track);
        const row = document.createElement('div');
        row.className = 'compact-track-row';
        row.innerHTML = `
          <div class="compact-thumb-wrap">
            <img src="${getSafeImageUrl(track.thumbnail)}" alt="${escapeHtml(track.title)}" class="compact-thumb" loading="lazy" onerror="this.src='/static/activity_icon.jpg';">
            <div class="compact-play-hover" title="${t('track.playNowTitle')}">
              <svg viewBox="0 0 24 24" width="20" height="20" fill="#ffffff"><path d="M8 5v14l11-7z"/></svg>
            </div>
          </div>
          <div class="compact-info">
            <span class="compact-title" title="${escapeHtml(track.title)}">${escapeHtml(track.title)}</span>
            <span class="compact-artist" title="${escapeHtml(track.artist)}">${escapeHtml(track.artist)} • ${track.duration_str}</span>
          </div>
          <div class="compact-actions">
            <button class="btn-compact-action ${isLiked ? 'liked' : ''} btn-like-track" title="${t('track.like')}">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
            </button>
            <button class="btn-compact-action btn-add-pl" title="${t('track.addToPlaylist')}">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M14 10H2v2h12v-2zm0-4H2v2h12V6zm4 8v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zM2 16h8v-2H2v2z"/></svg>
            </button>
          </div>
        `;

        row.querySelector('.compact-thumb-wrap').addEventListener('click', () => {
          playTrack(track, true);
        });
        row.querySelector('.compact-info').addEventListener('click', () => {
          playTrack(track, true);
        });
        row.querySelector('.btn-like-track').addEventListener('click', (e) => {
          e.stopPropagation();
          toggleLikeTrack(track);
          renderHomeView();
        });
        row.querySelector('.btn-add-pl').addEventListener('click', (e) => {
          e.stopPropagation();
          openAddToPlaylistModal(track);
        });

        el.curatedTracksGrid.appendChild(row);
      });
    }

    // 2. Square Cards Row: Вы давно не слушали
    if (el.quickPicksRow) {
      el.quickPicksRow.innerHTML = '';
      CURATED_QUICK_PICKS.forEach(item => {
        const card = document.createElement('div');
        card.className = 'square-card';
        card.innerHTML = `
          <div class="square-card-thumb-wrap">
            <img src="${getSafeImageUrl(item.thumbnail)}" alt="${escapeHtml(item.title)}" class="square-card-thumb" loading="lazy" onerror="this.src='/static/activity_icon.jpg';">
            <div class="square-card-play-btn" title="${t('track.playNowTitle')}">
              <svg viewBox="0 0 24 24" width="22" height="22" fill="#000"><path d="M8 5v14l11-7z"/></svg>
            </div>
          </div>
          <span class="square-card-title">${escapeHtml(item.title)}</span>
          <span class="square-card-sub">${escapeHtml(item.artist)}</span>
        `;
        card.addEventListener('click', () => {
          playTrack({
            title: item.title,
            artist: item.artist,
            thumbnail: item.thumbnail,
            source: 'youtube',
            url: `https://music.youtube.com/search?q=${encodeURIComponent(item.title + ' ' + item.artist)}`
          }, true);
        });
        el.quickPicksRow.appendChild(card);
      });
    }

    // 3. Square Cards Row: Альбомы для вас
    if (el.albumsRow) {
      el.albumsRow.innerHTML = '';
      CURATED_ALBUMS.forEach(item => {
        const card = document.createElement('div');
        card.className = 'square-card';
        card.innerHTML = `
          <div class="square-card-thumb-wrap">
            <img src="${getSafeImageUrl(item.thumbnail)}" alt="${escapeHtml(item.title)}" class="square-card-thumb" loading="lazy" onerror="this.src='/static/activity_icon.jpg';">
            <div class="square-card-play-btn" title="${t('track.playNowTitle')}">
              <svg viewBox="0 0 24 24" width="22" height="22" fill="#000"><path d="M8 5v14l11-7z"/></svg>
            </div>
          </div>
          <span class="square-card-title">${escapeHtml(item.title)}</span>
          <span class="square-card-sub">${escapeHtml(item.subtitle || item.artist)}</span>
        `;
        card.addEventListener('click', () => {
          switchView('search');
          if (el.searchInput) el.searchInput.value = item.title;
          performSearch(item.title);
        });
        el.albumsRow.appendChild(card);
      });
    }
  }

  // Liked Tracks Functions
  function isTrackLiked(track) {
    if (!track) return false;
    return state.likedTracks.some(t => (t.url && t.url === track.url) || (t.title === track.title && t.artist === track.artist));
  }

  function toggleLikeTrack(track) {
    if (!track) return;
    const idx = state.likedTracks.findIndex(t => (t.url && t.url === track.url) || (t.title === track.title && t.artist === track.artist));
    if (idx >= 0) {
      state.likedTracks.splice(idx, 1);
      saveJson('musicium_liked_tracks', state.likedTracks);
      showToast(t('toast.likedRemoved'), 'info', 'fa-heart-crack');
    } else {
      state.likedTracks.unshift({
        title: track.title,
        artist: track.artist || 'Неизвестный исполнитель',
        thumbnail: track.thumbnail || '/static/activity_icon.jpg',
        duration_str: track.duration_str || '3:00',
        source: track.source || 'youtube',
        url: track.url || `https://music.youtube.com/search?q=${encodeURIComponent(track.title + ' ' + (track.artist || ''))}`,
        added_at: Date.now()
      });
      saveJson('musicium_liked_tracks', state.likedTracks);
      showToast(t('toast.likedAdded'), 'success', 'fa-heart');
    }
    updateDockLikeBtn();
    if (state.currentView === 'liked') renderLikedView();
  }

  function updateDockLikeBtn() {
    if (!el.btnLikeCurrent) return;
    const cur = state.player ? state.player.current_track : null;
    if (cur && isTrackLiked(cur)) {
      el.btnLikeCurrent.classList.add('active');
    } else {
      el.btnLikeCurrent.classList.remove('active');
    }
  }

  function renderLikedView() {
    if (!el.likedTracksContainer) return;
    if (el.likedCountText) el.likedCountText.textContent = `${state.likedTracks.length} треков`;
    el.likedTracksContainer.innerHTML = '';

    if (state.likedTracks.length === 0) {
      el.likedTracksContainer.innerHTML = `
        <div class="dropdown-empty-state" style="padding: 40px 0;">
          <p style="font-size: 15px; color: #aaaaaa;">В понравившихся пока нет треков. Нажмите ❤️ на любом треке, чтобы сохранить его сюда.</p>
        </div>
      `;
      return;
    }

    state.likedTracks.forEach((track, index) => {
      const item = document.createElement('div');
      item.className = 'ytm-track-item';
      item.innerHTML = `
        <span class="track-index">${index + 1}</span>
        <img src="${getSafeImageUrl(track.thumbnail)}" alt="${escapeHtml(track.title)}" class="track-thumb" onerror="this.src='/static/activity_icon.jpg';">
        <div class="track-info-col">
          <span class="track-name" title="${escapeHtml(track.title)}">${escapeHtml(track.title)}</span>
          <span class="track-author" title="${escapeHtml(track.artist)}">${escapeHtml(track.artist)}</span>
        </div>
        <span class="track-duration-col">${track.duration_str || ''}</span>
        <div class="track-item-actions">
          <button class="btn-compact-action liked btn-like-remove" title="Удалить из понравившихся">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
          </button>
          <button class="btn-compact-action btn-play-track" title="${t('track.playNowTitle')}">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
          </button>
          <button class="btn-compact-action btn-add-q" title="${t('track.addQueueTitle')}">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
          </button>
        </div>
      `;

      item.querySelector('.btn-like-remove').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleLikeTrack(track);
      });
      item.querySelector('.btn-play-track').addEventListener('click', (e) => {
        e.stopPropagation();
        playTrack(track, true);
      });
      item.querySelector('.btn-add-q').addEventListener('click', (e) => {
        e.stopPropagation();
        playTrack(track, false);
      });
      item.addEventListener('click', () => {
        playTrack(track, true);
      });

      el.likedTracksContainer.appendChild(item);
    });
  }

  // Custom Playlists Functions
  function renderSidebarPlaylists() {
    if (!el.customPlaylistsList) return;
    el.customPlaylistsList.innerHTML = '';

    state.customPlaylists.forEach(pl => {
      const item = document.createElement('div');
      item.className = `ytm-playlist-item ${state.currentView === 'playlist' && state.selectedPlaylistId === pl.id ? 'active' : ''}`;
      item.dataset.playlistId = pl.id;
      item.setAttribute('role', 'button');
      item.innerHTML = `
        <div class="ytm-playlist-icon">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>
        </div>
        <div class="ytm-playlist-meta">
          <span class="ytm-playlist-name">${escapeHtml(pl.name)}</span>
          <span class="ytm-playlist-sub">${escapeHtml(pl.author || 'Вы')}</span>
        </div>
      `;
      item.addEventListener('click', () => {
        switchView('playlist', pl.id);
      });
      el.customPlaylistsList.appendChild(item);
    });
  }

  function renderPlaylistView(playlistId) {
    const pl = state.customPlaylists.find(p => p.id === playlistId);
    if (!pl) {
      switchView('home');
      return;
    }

    if (el.currentPlaylistTitle) el.currentPlaylistTitle.textContent = pl.name;
    if (el.playlistCountText) el.playlistCountText.textContent = `${pl.tracks ? pl.tracks.length : 0} треков • ${pl.author || 'Вы'}`;
    if (!el.customPlaylistTracksContainer) return;
    el.customPlaylistTracksContainer.innerHTML = '';

    if (!pl.tracks || pl.tracks.length === 0) {
      el.customPlaylistTracksContainer.innerHTML = `
        <div class="dropdown-empty-state" style="padding: 40px 0;">
          <p style="font-size: 15px; color: #aaaaaa;">В этом плейлисте пока нет треков. Найдите трек и нажмите «В плейлист», чтобы добавить его.</p>
        </div>
      `;
      return;
    }

    pl.tracks.forEach((track, index) => {
      const item = document.createElement('div');
      item.className = 'ytm-track-item';
      item.innerHTML = `
        <span class="track-index">${index + 1}</span>
        <img src="${getSafeImageUrl(track.thumbnail)}" alt="${escapeHtml(track.title)}" class="track-thumb" onerror="this.src='/static/activity_icon.jpg';">
        <div class="track-info-col">
          <span class="track-name" title="${escapeHtml(track.title)}">${escapeHtml(track.title)}</span>
          <span class="track-author" title="${escapeHtml(track.artist)}">${escapeHtml(track.artist)}</span>
        </div>
        <span class="track-duration-col">${track.duration_str || ''}</span>
        <div class="track-item-actions">
          <button class="btn-compact-action btn-play-track" title="${t('track.playNowTitle')}">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
          </button>
          <button class="btn-compact-action btn-remove-pl" title="Удалить из плейлиста">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="#ef4444"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
          </button>
        </div>
      `;

      item.querySelector('.btn-play-track').addEventListener('click', (e) => {
        e.stopPropagation();
        playTrack(track, true);
      });
      item.querySelector('.btn-remove-pl').addEventListener('click', (e) => {
        e.stopPropagation();
        pl.tracks.splice(index, 1);
        saveJson('musicium_custom_playlists', state.customPlaylists);
        showToast(t('toast.trackRemovedFromPlaylist'), 'info');
        renderPlaylistView(playlistId);
      });
      item.addEventListener('click', () => {
        playTrack(track, true);
      });

      el.customPlaylistTracksContainer.appendChild(item);
    });
  }

  function openAddToPlaylistModal(track) {
    state.trackToAddToPlaylist = track;
    if (el.addToPlaylistTrackInfo) {
      el.addToPlaylistTrackInfo.innerHTML = `<strong>${escapeHtml(track.title)}</strong><br><span style="color:#aaa;font-size:12px;">${escapeHtml(track.artist || '')}</span>`;
    }
    if (el.addToPlaylistList) {
      el.addToPlaylistList.innerHTML = '';
      state.customPlaylists.forEach(pl => {
        const row = document.createElement('div');
        row.className = 'modal-playlist-select-item';
        row.innerHTML = `
          <span>📁 ${escapeHtml(pl.name)} (${pl.tracks ? pl.tracks.length : 0})</span>
          <button class="btn-primary-yt" style="height:30px;padding:0 12px;font-size:12px;">+ Добавить</button>
        `;
        row.querySelector('button').addEventListener('click', () => {
          if (!pl.tracks) pl.tracks = [];
          const exists = pl.tracks.some(t => t.title === track.title && t.artist === track.artist);
          if (exists) {
            showToast(t('toast.alreadyInPlaylist'), 'warning');
            return;
          }
          pl.tracks.push({
            title: track.title,
            artist: track.artist || 'Неизвестный исполнитель',
            thumbnail: track.thumbnail || '/static/activity_icon.jpg',
            duration_str: track.duration_str || '3:00',
            source: track.source || 'youtube',
            url: track.url || `https://music.youtube.com/search?q=${encodeURIComponent(track.title + ' ' + (track.artist || ''))}`,
            added_at: Date.now()
          });
          saveJson('musicium_custom_playlists', state.customPlaylists);
          showToast(t('toast.trackAddedToPlaylist', { name: pl.name }), 'success');
          if (el.addToPlaylistModal) el.addToPlaylistModal.style.display = 'none';
          renderSidebarPlaylists();
        });
        el.addToPlaylistList.appendChild(row);
      });
    }
    if (el.addToPlaylistModal) el.addToPlaylistModal.style.display = 'flex';
  }

  // History View
  function renderHistoryView() {
    if (!el.historyTracksContainer) return;
    if (el.historyCountText) el.historyCountText.textContent = `${state.historyTracks.length} треков`;
    el.historyTracksContainer.innerHTML = '';

    if (state.historyTracks.length === 0) {
      el.historyTracksContainer.innerHTML = `
        <div class="dropdown-empty-state" style="padding: 40px 0;">
          <p style="font-size: 15px; color: #aaaaaa;">История прослушивания пуста. Воспроизведенные песни появятся здесь.</p>
        </div>
      `;
      return;
    }

    state.historyTracks.forEach((track, index) => {
      const item = document.createElement('div');
      item.className = 'ytm-track-item';
      item.innerHTML = `
        <span class="track-index">${index + 1}</span>
        <img src="${getSafeImageUrl(track.thumbnail)}" alt="${escapeHtml(track.title)}" class="track-thumb" onerror="this.src='/static/activity_icon.jpg';">
        <div class="track-info-col">
          <span class="track-name" title="${escapeHtml(track.title)}">${escapeHtml(track.title)}</span>
          <span class="track-author" title="${escapeHtml(track.artist)}">${escapeHtml(track.artist)}</span>
        </div>
        <div class="track-item-actions">
          <button class="btn-compact-action btn-play-track" title="${t('track.playNowTitle')}">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
          </button>
          <button class="btn-compact-action btn-add-q" title="${t('track.addQueueTitle')}">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
          </button>
        </div>
      `;
      item.querySelector('.btn-play-track').addEventListener('click', (e) => {
        e.stopPropagation();
        playTrack(track, true);
      });
      item.querySelector('.btn-add-q').addEventListener('click', (e) => {
        e.stopPropagation();
        playTrack(track, false);
      });
      item.addEventListener('click', () => {
        playTrack(track, true);
      });
      el.historyTracksContainer.appendChild(item);
    });
  }

  // Queue View
  function renderQueueView() {
    const queue = (state.player && state.player.queue) ? state.player.queue : [];
    if (el.sidebarQueueCount) el.sidebarQueueCount.textContent = queue.length;
    if (el.queueMetaCount) el.queueMetaCount.textContent = `${queue.length} в очереди`;
    if (!el.queueList) return;
    el.queueList.innerHTML = '';

    if (queue.length === 0) {
      el.queueList.innerHTML = `
        <div class="dropdown-empty-state" style="padding: 40px 0;">
          <p style="font-size: 15px; color: #aaaaaa;">Очередь воспроизведения пуста. Найдите трек и нажмите «+ В очередь».</p>
        </div>
      `;
      return;
    }

    queue.forEach((track, index) => {
      const item = document.createElement('div');
      item.className = 'ytm-track-item';
      item.innerHTML = `
        <span class="track-index">${index + 1}</span>
        <img src="${getSafeImageUrl(track.thumbnail)}" alt="${escapeHtml(track.title)}" class="track-thumb" onerror="this.src='/static/activity_icon.jpg';">
        <div class="track-info-col">
          <span class="track-name" title="${escapeHtml(track.title)}">${escapeHtml(track.title)}</span>
          <span class="track-author" title="${escapeHtml(track.artist)}">${escapeHtml(track.artist)}</span>
        </div>
        <span class="track-duration-col">${track.duration_str || ''}</span>
        <div class="track-item-actions">
          <button class="btn-compact-action btn-remove-q" title="${t('queue.removeTitle')}">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="#ef4444"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
          </button>
        </div>
      `;
      item.querySelector('.btn-remove-q').addEventListener('click', async (e) => {
        e.stopPropagation();
        await sendPlayerAction('remove', { index });
      });
      el.queueList.appendChild(item);
    });
  }

  // Search tracks
  async function performSearch(query = null) {
    const q = query !== null ? query : el.searchInput.value.trim();
    if (!q) {
      switchView('home');
      return;
    }

    switchView('search');
    el.loadingState.style.display = 'flex';
    el.emptyState.style.display = 'none';
    el.tracksGrid.innerHTML = '';
    el.resultsHeading.innerHTML = `<svg viewBox="0 0 24 24" width="20" height="20" fill="#ff0000" style="display:inline-block;vertical-align:middle;margin-right:6px;"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg><span>${t('results.query', { query: escapeHtml(q) })}</span>`;

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

  // Render Tracks in Search Grid
  function renderTracks(tracks) {
    state.lastTracks = tracks;
    el.tracksGrid.innerHTML = '';
    tracks.forEach(track => {
      const card = document.createElement('div');
      card.className = 'track-card';
      const isLiked = isTrackLiked(track);

      card.innerHTML = `
        <div class="card-top">
          <div class="card-thumb-wrapper">
            <img src="${getSafeImageUrl(track.thumbnail)}" alt="${escapeHtml(track.title)}" class="card-thumb" loading="lazy" onerror="this.src='/static/activity_icon.jpg';">
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
              <span class="source-tag ${track.source || 'youtube'}">${track.source || 'YouTube'}</span>
              <span class="card-duration">${track.duration_str || ''}</span>
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
          <button class="btn-card-action ${isLiked ? 'liked' : ''} btn-card-like" title="${t('track.like')}">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
          </button>
          <button class="btn-card-action btn-card-add-pl" title="${t('track.addToPlaylist')}">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M14 10H2v2h12v-2zm0-4H2v2h12V6zm4 8v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zM2 16h8v-2H2v2z"/></svg>
          </button>
        </div>
      `;

      card.querySelector('.card-play-overlay').addEventListener('click', () => {
        playTrack(track, true);
      });
      card.querySelector('.btn-play-now').addEventListener('click', () => {
        playTrack(track, true);
      });
      card.querySelector('.btn-add-queue').addEventListener('click', () => {
        playTrack(track, false);
      });
      card.querySelector('.btn-card-like').addEventListener('click', () => {
        toggleLikeTrack(track);
        renderTracks(state.lastTracks);
      });
      card.querySelector('.btn-card-add-pl').addEventListener('click', () => {
        openAddToPlaylistModal(track);
      });

      el.tracksGrid.appendChild(card);
    });
  }

  // Send play request to backend (Requirement 2: Only users in voice channel can control)
  async function playTrack(track, playNow = false) {
    if (!state.inVoice) {
      await checkUserVoice();
      if (!state.inVoice) {
        showToast(t('voice.mustBeInVoice'), 'warning', 'fa-triangle-exclamation');
        return;
      }
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
        showToast(data.error || 'Error', 'warning');
        return;
      }

      if (data.action === 'album_enqueued') {
        showToast(t('toast.albumAdded', { count: data.tracks_count }), 'success');
      } else if (data.action === 'started' || data.action === 'playing_now') {
        showToast(t('toast.nowPlaying', { title: track.title, channel: data.channel_name }), 'success');
      } else {
        showToast(t('toast.addedQueue', { title: track.title }), 'success');
      }

      if (data.player) {
        updatePlayerUI(data.player);
      } else {
        await fetchCurrentPlayer();
      }

      checkUserVoice();
    } catch (err) {
      showToast(t('toast.networkError'), 'error');
    }
  }

  // Send player action (Requirement 2: Voice Channel check)
  async function sendPlayerAction(action, payload = {}) {
    if (!state.inVoice) {
      await checkUserVoice();
      if (!state.inVoice) {
        showToast(t('voice.mustBeInVoice'), 'warning', 'fa-triangle-exclamation');
        return null;
      }
    }

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
      if (!data.success && data.error) {
        showToast(data.error, 'warning');
      }
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

  // Update Player UI from Player state
  function updatePlayerUI(playerState) {
    if (state.guildId && playerState && playerState.guild_id && String(playerState.guild_id) !== String(state.guildId)) {
      return;
    }

    state.player = playerState;

    if (!playerState || !playerState.is_playing) {
      state.isPlaying = false;
      state.duration = 0;
      state.elapsed = 0;
      stopProgressTicker();

      if (el.dockArt) el.dockArt.src = '/static/activity_icon.jpg';
      if (el.dockTitle) {
        el.dockTitle.textContent = t('player.noTrack');
        el.dockTitle.removeAttribute('href');
      }
      if (el.dockArtist) el.dockArtist.textContent = t('player.selectSong');
      if (el.dockSourceBadge) el.dockSourceBadge.textContent = 'DISCORD';
      if (el.playIconSvg) el.playIconSvg.innerHTML = SVG_ICONS.play;
      if (el.equalizerBars) el.equalizerBars.classList.remove('active');
      if (el.timeElapsed) el.timeElapsed.textContent = '00:00';
      if (el.timeDuration) el.timeDuration.textContent = '00:00';
      if (el.progressFill) el.progressFill.style.width = '0%';
      if (el.sidebarQueueCount) el.sidebarQueueCount.textContent = '0';

      updateDockLikeBtn();
      if (state.currentView === 'queue') renderQueueView();
      return;
    }

    const track = playerState.current_track;
    state.isPlaying = !playerState.is_paused;
    state.duration = playerState.duration || 0;
    state.elapsed = playerState.position || 0;

    // Track playback history
    if (track && (!state.historyTracks.length || state.historyTracks[0].title !== track.title)) {
      state.historyTracks.unshift({
        title: track.title,
        artist: track.artist || 'Неизвестный исполнитель',
        thumbnail: track.thumbnail || '/static/activity_icon.jpg',
        duration_str: track.duration_str || '3:00',
        source: track.source || 'youtube',
        url: track.url,
        played_at: Date.now()
      });
      if (state.historyTracks.length > 50) state.historyTracks.pop();
      saveJson('musicium_history_tracks', state.historyTracks);
      if (state.currentView === 'history') renderHistoryView();
    }

    if (track) {
      if (el.dockArt) {
        el.dockArt.src = getSafeImageUrl(track.thumbnail);
        el.dockArt.onerror = function() { this.src = '/static/activity_icon.jpg'; };
      }
      if (el.dockTitle) {
        el.dockTitle.textContent = track.title;
        if (track.url) el.dockTitle.href = track.url;
      }
      if (el.dockArtist) el.dockArtist.textContent = track.artist || 'YouTube Music';
      if (el.dockSourceBadge) {
        el.dockSourceBadge.textContent = (track.source || 'YT').toUpperCase();
        el.dockSourceBadge.className = `dock-source-badge ${track.source || 'youtube'}`;
      }
    }

    if (el.playIconSvg) {
      el.playIconSvg.innerHTML = state.isPlaying ? SVG_ICONS.pause : SVG_ICONS.play;
    }
    if (el.equalizerBars) {
      if (state.isPlaying) el.equalizerBars.classList.add('active');
      else el.equalizerBars.classList.remove('active');
    }

    if (el.btnLoop) {
      const mode = playerState.loop_mode || 'off';
      el.btnLoop.className = `control-btn btn-sm ${mode !== 'off' ? 'active' : ''}`;
    }

    if (playerState.volume !== undefined && !state.isAdjustingVolume) {
      const vol = Math.round(playerState.volume * 100);
      if (el.volumeSlider) el.volumeSlider.value = vol;
      if (el.volumeVal) el.volumeVal.textContent = `${vol}%`;
      updateVolumeIcon(vol);
    }

    if (el.sidebarQueueCount) {
      el.sidebarQueueCount.textContent = playerState.queue ? playerState.queue.length : '0';
    }

    updateVoteBadge(playerState.votes, playerState.votes_required);
    updateDockLikeBtn();

    if (!state.isScrubbing) {
      updateProgressBar();
    }

    if (state.isPlaying) startProgressTicker();
    else stopProgressTicker();

    if (state.currentView === 'queue') renderQueueView();
  }

  function updateVoteBadge(votes, required) {
    if (!el.voteCountBadge) return;
    if (votes !== undefined && required !== undefined) {
      el.voteCountBadge.textContent = `${votes}/${required}`;
    }
  }

  function updateProgressBar() {
    if (el.timeElapsed) el.timeElapsed.textContent = formatTime(state.elapsed);
    if (el.timeDuration) el.timeDuration.textContent = formatTime(state.duration);
    if (el.progressFill && state.duration > 0) {
      const pct = Math.min(100, Math.max(0, (state.elapsed / state.duration) * 100));
      el.progressFill.style.width = `${pct}%`;
    }
  }

  function startProgressTicker() {
    stopProgressTicker();
    state.progressTimer = setInterval(() => {
      if (state.isPlaying && !state.isScrubbing) {
        state.elapsed += 1;
        if (state.duration > 0 && state.elapsed > state.duration) {
          state.elapsed = state.duration;
        }
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

  function sendWsSubscribe() {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({
        action: 'subscribe',
        user_id: state.userId,
        guild_id: state.guildId
      }));
    }
  }

  function setupWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      sendWsSubscribe();
    };

    state.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.event === 'player_update') {
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
      setTimeout(setupWebSocket, 3000);
    };
  }

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

  function escapeHtml(text) {
    if (!text) return '';
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // Attach Event Listeners
  function attachEvents() {
    // Navigation routing
    if (el.navHome) el.navHome.addEventListener('click', () => switchView('home'));
    if (el.brandLogoHome) el.brandLogoHome.addEventListener('click', () => switchView('home'));
    if (el.navSearch) el.navSearch.addEventListener('click', () => {
      switchView('search');
      if (el.searchInput) el.searchInput.focus();
    });
    if (el.navQueue) el.navQueue.addEventListener('click', () => switchView('queue'));
    if (el.navLiked) el.navLiked.addEventListener('click', () => switchView('liked'));
    if (el.navHistory) el.navHistory.addEventListener('click', () => switchView('history'));
    if (el.btnToggleQueue) el.btnToggleQueue.addEventListener('click', () => {
      if (state.currentView === 'queue') switchView('home');
      else switchView('queue');
    });

    // New Playlist Modal
    if (el.btnNewPlaylist) {
      el.btnNewPlaylist.addEventListener('click', () => {
        if (el.newPlaylistTitleInput) el.newPlaylistTitleInput.value = '';
        if (el.newPlaylistModal) el.newPlaylistModal.style.display = 'flex';
        if (el.newPlaylistTitleInput) el.newPlaylistTitleInput.focus();
      });
    }

    if (el.closeNewPlaylistBtn) {
      el.closeNewPlaylistBtn.addEventListener('click', () => {
        if (el.newPlaylistModal) el.newPlaylistModal.style.display = 'none';
      });
    }

    if (el.cancelNewPlaylistBtn) {
      el.cancelNewPlaylistBtn.addEventListener('click', () => {
        if (el.newPlaylistModal) el.newPlaylistModal.style.display = 'none';
      });
    }

    if (el.saveNewPlaylistBtn) {
      el.saveNewPlaylistBtn.addEventListener('click', () => {
        const name = (el.newPlaylistTitleInput.value || '').trim();
        if (!name) return;
        const newPl = {
          id: 'pl_' + Date.now(),
          name: name,
          author: state.userName || 'Вы',
          tracks: []
        };
        state.customPlaylists.push(newPl);
        saveJson('musicium_custom_playlists', state.customPlaylists);
        showToast(t('toast.playlistCreated', { name }), 'success');
        if (el.newPlaylistModal) el.newPlaylistModal.style.display = 'none';
        renderSidebarPlaylists();
        switchView('playlist', newPl.id);
      });
    }

    // Add To Playlist Modal close
    if (el.closeAddToPlaylistBtn) {
      el.closeAddToPlaylistBtn.addEventListener('click', () => {
        if (el.addToPlaylistModal) el.addToPlaylistModal.style.display = 'none';
      });
    }
    if (el.closeAddToPlaylistModalBtn) {
      el.closeAddToPlaylistModalBtn.addEventListener('click', () => {
        if (el.addToPlaylistModal) el.addToPlaylistModal.style.display = 'none';
      });
    }

    // Liked View actions
    if (el.btnPlayAllLiked) {
      el.btnPlayAllLiked.addEventListener('click', async () => {
        if (!state.likedTracks.length) return;
        for (let i = 0; i < state.likedTracks.length; i++) {
          await playTrack(state.likedTracks[i], i === 0);
        }
      });
    }

    // Current Playlist actions
    if (el.btnPlayAllPlaylist) {
      el.btnPlayAllPlaylist.addEventListener('click', async () => {
        const pl = state.customPlaylists.find(p => p.id === state.selectedPlaylistId);
        if (!pl || !pl.tracks || !pl.tracks.length) return;
        for (let i = 0; i < pl.tracks.length; i++) {
          await playTrack(pl.tracks[i], i === 0);
        }
      });
    }

    if (el.btnDeleteCurrentPlaylist) {
      el.btnDeleteCurrentPlaylist.addEventListener('click', () => {
        const idx = state.customPlaylists.findIndex(p => p.id === state.selectedPlaylistId);
        if (idx >= 0) {
          state.customPlaylists.splice(idx, 1);
          saveJson('musicium_custom_playlists', state.customPlaylists);
          showToast(t('toast.playlistDeleted'), 'info');
          renderSidebarPlaylists();
          switchView('home');
        }
      });
    }

    // History actions
    if (el.btnClearHistoryBtn) {
      el.btnClearHistoryBtn.addEventListener('click', () => {
        state.historyTracks = [];
        saveJson('musicium_history_tracks', []);
        renderHistoryView();
      });
    }

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
      switchView('home');
    });

    // Source chips
    el.sourceChips.forEach(chip => {
      chip.addEventListener('click', () => {
        el.sourceChips.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        state.currentSource = chip.dataset.source;
        if (el.searchInput.value.trim()) {
          performSearch();
        }
      });
    });

    // Mood chips (like Screenshot 2)
    document.querySelectorAll('.mood-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        document.querySelectorAll('.mood-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        const moodQuery = chip.dataset.mood;
        if (el.searchInput) el.searchInput.value = moodQuery;
        performSearch(moodQuery);
      });
    });

    // Voice status widget click & dropdown toggle (Requirement 2)
    el.voiceStatusPill.addEventListener('click', (e) => {
      if (el.voiceWidgetContainer) {
        el.voiceWidgetContainer.classList.toggle('dropdown-open');
      }
      checkUserVoice();
    });

    if (el.refreshVoiceBtn) {
      el.refreshVoiceBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        checkUserVoice();
        showToast(t('toast.channelRefreshed'), 'info');
      });
    }

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
      if (el.voiceWidgetContainer && !el.voiceWidgetContainer.contains(e.target)) {
        el.voiceWidgetContainer.classList.remove('dropdown-open');
      }
    });

    // User badge
    el.userBadge.addEventListener('click', () => {
      showToast(state.userName ? t('user.loggedInAs', { name: state.userName }) : t('user.profileActive'), 'info', 'fa-user');
    });

    // Language switcher buttons
    const langBtnRu = document.getElementById('langBtnRu');
    const langBtnEn = document.getElementById('langBtnEn');
    if (langBtnRu) langBtnRu.addEventListener('click', () => setLanguage('ru', true));
    if (langBtnEn) langBtnEn.addEventListener('click', () => setLanguage('en', true));

    // Legal modal
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

    // Queue shuffle & clear
    if (el.shuffleQueueBtn) {
      el.shuffleQueueBtn.addEventListener('click', async () => {
        const res = await sendPlayerAction('shuffle');
        if (res && res.success) {
          showToast(t('toast.queueShuffled', { count: res.queue_size }), 'info', 'fa-shuffle');
        }
      });
    }

    if (el.clearQueueBtn) {
      el.clearQueueBtn.addEventListener('click', async () => {
        const res = await sendPlayerAction('clear');
        if (res && res.success) {
          showToast(t('toast.queueCleared'), 'info', 'fa-trash-can');
        }
      });
    }

    // Player Dock Controls (Requirement 2: only voice channel users can control)
    if (el.btnLikeCurrent) {
      el.btnLikeCurrent.addEventListener('click', () => {
        const cur = state.player ? state.player.current_track : null;
        if (cur) toggleLikeTrack(cur);
      });
    }

    el.btnPlayPause.addEventListener('click', async () => {
      const res = await sendPlayerAction('play_pause');
      if (res && res.success) {
        state.isPlaying = !res.is_paused;
        if (el.playIconSvg) el.playIconSvg.innerHTML = state.isPlaying ? SVG_ICONS.pause : SVG_ICONS.play;
        if (state.isPlaying) {
          startProgressTicker();
          if (el.equalizerBars) el.equalizerBars.classList.add('active');
        } else {
          stopProgressTicker();
          if (el.equalizerBars) el.equalizerBars.classList.remove('active');
        }
      }
    });

    el.btnSkip.addEventListener('click', async () => {
      const res = await sendPlayerAction('skip', { forced: true });
      if (res && res.success) {
        showToast(t('toast.trackSkipped'), 'info', 'fa-forward-step');
      }
    });

    el.btnVoteSkip.addEventListener('click', async () => {
      const res = await sendPlayerAction('vote_skip');
      if (res && res.success) {
        updateVoteBadge(res.votes, res.required);
        showToast(t('toast.voteRecorded'), 'info', 'fa-person-booth');
      }
    });

    el.btnPrev.addEventListener('click', async () => {
      state.elapsed = 0;
      el.timeElapsed.textContent = '00:00';
      el.progressFill.style.width = '0%';
      await sendPlayerAction('seek', { seconds: 0 });
      showToast(t('toast.rewound'), 'info');
    });

    // Scrubber / Seek on Progress Bar
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
      if (state.isAdjustingVolume) setTimeout(() => { state.isAdjustingVolume = false; }, 350);
    });
    document.addEventListener('touchend', () => {
      if (state.isAdjustingVolume) setTimeout(() => { state.isAdjustingVolume = false; }, 350);
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
    renderSidebarPlaylists();
    renderHomeView();
    attachEvents();
    await initDiscordSdk();
    await checkSystemStatus();
    await checkUserVoice();
    setupWebSocket();
    await fetchCurrentPlayer();

    // Periodic voice check every 12s
    setInterval(checkUserVoice, 12000);
  }

  init();
})();
