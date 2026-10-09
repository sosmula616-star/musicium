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

  // Clean start for user playlists (no personal pre-filled playlists)
  let loadedCustom = loadJson('musicium_custom_playlists', []);
  if (Array.isArray(loadedCustom)) {
    loadedCustom = loadedCustom.filter(p => p && p.id !== 'pl_gta5' && p.name !== 'GTA 5');
  }
  saveJson('musicium_custom_playlists', loadedCustom);

  // Handle URL query parameters for Discord OAuth2 callback (?user_id=...&user_name=...&user_avatar=...)
  const queryUserId = urlParams.get('user_id');
  const queryUserName = urlParams.get('user_name');
  const queryUserAvatar = urlParams.get('user_avatar');

  if (queryUserId) {
    localStorage.setItem('music_user_id', queryUserId);
    if (queryUserName) localStorage.setItem('music_user_name', decodeURIComponent(queryUserName));
    if (queryUserAvatar) localStorage.setItem('music_user_avatar', decodeURIComponent(queryUserAvatar));
    if (urlParams.get('is_admin') === '1' || queryUserId === '410432175373156352') {
      localStorage.setItem('music_is_admin', 'true');
    }
    localStorage.setItem('music_authenticated', 'true');
    try {
      const cleanUrl = window.location.pathname + (initialGuildId ? `?guild_id=${initialGuildId}${initialChannelId ? `&channel_id=${initialChannelId}` : ''}` : '');
      window.history.replaceState({}, document.title, cleanUrl);
    } catch (_) {}
  }

  let storedUserId = localStorage.getItem('music_user_id') || '';
  const isRealUser = Boolean(storedUserId && !storedUserId.startsWith('user_'));

  // State
  const state = {
    userId: storedUserId,
    userName: localStorage.getItem('music_user_name') || 'Пользователь Discord',
    userAvatar: localStorage.getItem('music_user_avatar') || '/static/activity_icon.jpg',
    isAuthenticated: isRealUser,
    activeHomeFilter: 'all', // 'all' | 'youtube' | 'soundcloud' | 'albums'
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
    botVoice: null,
    player: null,
    ws: null,
    progressTimer: null,
    elapsed: 0,
    duration: 0,
    isPlaying: false,
    isMuted: false,
    savedVolume: 100,
    userExplicitVolume: loadJson('musicium_volume', null),
    searchTimeout: null,
    isScrubbing: false,
    isAdjustingVolume: false,
    lastUserVolumeChange: 0,
    lang: localStorage.getItem('musicium_lang') || 'ru',
    lastTracks: [],
    likedTracks: loadJson('musicium_liked_tracks', []),
    customPlaylists: loadedCustom,
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
      'sidebar.newPlaylist': 'Создать плейлист',
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
      'voice.serversTitle': 'Серверы и комнаты',
      'voice.currentRoom': 'Комната бота',
      'voice.botInRoom': 'Бот в комнате: {room}',
      'voice.botFree': 'Бот свободен (не в комнате)',
      'voice.disconnectBot': 'Отключить',
      'voice.connectBot': 'Подключить',
      'voice.moveBot': 'Переместить',
      'voice.youAreHere': 'Вы здесь',
      'voice.botIsHere': 'Бот здесь',
      'voice.allServers': 'Все серверы',
      'voice.selectServer': 'Выберите сервер',
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
      'home.quickPicks': 'Хиты SoundCloud & YouTube',
      'home.albums': 'Популярные альбомы',
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
      'voice.serversTitle': 'Servers & Rooms',
      'voice.currentRoom': 'Bot Voice Room',
      'voice.botInRoom': 'Bot in room: {room}',
      'voice.botFree': 'Bot is idle (not in room)',
      'voice.disconnectBot': 'Disconnect',
      'voice.connectBot': 'Connect',
      'voice.moveBot': 'Move',
      'voice.youAreHere': 'You are here',
      'voice.botIsHere': 'Bot is here',
      'voice.allServers': 'All servers',
      'voice.selectServer': 'Select server',
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
      'home.quickPicks': 'SoundCloud & YouTube Hits',
      'home.albums': 'Popular Albums',
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

  // Curated neutral hits from YouTube & SoundCloud
  let CURATED_RECOMMENDED = [
    { title: 'Blinding Lights', artist: 'The Weeknd', duration: 200, duration_str: '3:20', thumbnail: 'https://i.ytimg.com/vi/4NRXx6U8ABQ/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/watch?v=4NRXx6U8ABQ' },
    { title: 'Get Lucky', artist: 'Daft Punk ft. Pharrell Williams', duration: 248, duration_str: '4:08', thumbnail: 'https://i.ytimg.com/vi/5NV6Rdv1a3I/hqdefault.jpg', source: 'soundcloud', url: 'https://api.soundcloud.com/tracks/soundcloud%3Atracks%3A88335161' },
    { title: 'Starboy', artist: 'The Weeknd ft. Daft Punk', duration: 230, duration_str: '3:50', thumbnail: 'https://i.ytimg.com/vi/34Na4j8AVgA/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/watch?v=34Na4j8AVgA' },
    { title: 'Levitating', artist: 'Dua Lipa', duration: 203, duration_str: '3:23', thumbnail: 'https://i.ytimg.com/vi/TUVcZfQe-Kw/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/watch?v=TUVcZfQe-Kw' },
    { title: 'Believer', artist: 'Imagine Dragons', duration: 204, duration_str: '3:24', thumbnail: 'https://i.ytimg.com/vi/7wtfhZwyrcc/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/watch?v=7wtfhZwyrcc' },
    { title: 'Alone', artist: 'Marshmello', duration: 199, duration_str: '3:19', thumbnail: 'https://i.ytimg.com/vi/ALZHF5UqnU4/hqdefault.jpg', source: 'soundcloud', url: 'https://soundcloud.com/marshmellomusic/marshmello-alone' },
    { title: 'Faded', artist: 'Alan Walker', duration: 212, duration_str: '3:32', thumbnail: 'https://i.ytimg.com/vi/60ItHLz5WEA/hqdefault.jpg', source: 'soundcloud', url: 'https://soundcloud.com/alanwalker/faded' },
    { title: 'Bad Guy', artist: 'Billie Eilish', duration: 194, duration_str: '3:14', thumbnail: 'https://i.ytimg.com/vi/DyDfgMOUjCI/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/watch?v=DyDfgMOUjCI' },
    { title: 'Animals', artist: 'Martin Garrix', duration: 176, duration_str: '2:56', thumbnail: 'https://i.ytimg.com/vi/gCYcYZW45Uk/hqdefault.jpg', source: 'soundcloud', url: 'https://soundcloud.com/martingarrix/martin-garrix-animals' },
    { title: 'Stay', artist: 'The Kid LAROI & Justin Bieber', duration: 141, duration_str: '2:21', thumbnail: 'https://i.ytimg.com/vi/kTJczUoc268/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/watch?v=kTJczUoc268' },
    { title: 'Midnight City', artist: 'M83', duration: 243, duration_str: '4:03', thumbnail: 'https://i.ytimg.com/vi/dX3k_QDnzHE/hqdefault.jpg', source: 'youtube', url: 'https://music.youtube.com/watch?v=dX3k_QDnzHE' },
    { title: 'The Nights', artist: 'Avicii', duration: 176, duration_str: '2:56', thumbnail: 'https://i.ytimg.com/vi/UtF6Jej8yb4/hqdefault.jpg', source: 'soundcloud', url: 'https://soundcloud.com/aviciiofficial/the-nights' }
  ];

  let CURATED_QUICK_PICKS = [
    { title: 'Bangarang', artist: 'Skrillex', duration: 215, duration_str: '3:35', thumbnail: 'https://i.ytimg.com/vi/YJVmu6yttiw/hqdefault.jpg', source: 'soundcloud' },
    { title: 'First of the Year (Equinox)', artist: 'Skrillex', duration: 195, duration_str: '3:15', thumbnail: 'https://i.ytimg.com/vi/2cXDgFwE13g/hqdefault.jpg', source: 'soundcloud' },
    { title: 'Strobe', artist: 'deadmau5', duration: 637, duration_str: '10:37', thumbnail: 'https://i.ytimg.com/vi/tKi9Z-f6qX4/hqdefault.jpg', source: 'soundcloud' },
    { title: 'One More Time', artist: 'Daft Punk', duration: 320, duration_str: '5:20', thumbnail: 'https://i.ytimg.com/vi/FGBhQbmMxH8/hqdefault.jpg', source: 'youtube' },
    { title: 'Wake Me Up', artist: 'Avicii', duration: 247, duration_str: '4:07', thumbnail: 'https://i.ytimg.com/vi/IcrbM1l_BoI/hqdefault.jpg', source: 'youtube' },
    { title: 'Counting Stars', artist: 'OneRepublic', duration: 257, duration_str: '4:17', thumbnail: 'https://i.ytimg.com/vi/hT_nvWreIhg/hqdefault.jpg', source: 'youtube' }
  ];

  let YOUTUBE_CHARTS = [];
  let SOUNDCLOUD_CHARTS = [];
  let BEST_ALBUMS = [];
  let CURATED_ALBUMS = [];

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
      if (key) {
        const trans = t(key);
        if (trans && trans !== key) elem.textContent = trans;
      }
    });

    document.querySelectorAll('[data-i18n-placeholder]').forEach(elem => {
      const key = elem.getAttribute('data-i18n-placeholder');
      if (key) {
        const trans = t(key);
        if (trans && trans !== key) elem.placeholder = trans;
      }
    });

    document.querySelectorAll('[data-i18n-title]').forEach(elem => {
      const key = elem.getAttribute('data-i18n-title');
      if (key) {
        const trans = t(key);
        if (trans && trans !== key) elem.title = trans;
      }
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

    // Voice Widget (Streamlined Room & Listeners Status)
    voiceWidgetContainer: document.getElementById('voiceWidgetContainer'),
    voiceStatusPill: document.getElementById('voiceStatusPill'),
    voiceIndicator: document.getElementById('voiceIndicator'),
    voiceChannelName: document.getElementById('voiceChannelName'),
    voiceMembersCountBadge: document.getElementById('voiceMembersCountBadge'),
    voiceMembersDropdown: document.getElementById('voiceMembersDropdown'),
    voiceDropdownTitle: document.getElementById('voiceDropdownTitle'),
    voiceDropdownSub: document.getElementById('voiceDropdownSub'),
    voiceMembersList: document.getElementById('voiceMembersList'),
    refreshVoiceBtn: document.getElementById('refreshVoiceBtn'),

    // Profile & Auth
    userBadge: document.getElementById('userBadge'),
    userAvatar: document.getElementById('userAvatar'),
    userName: document.getElementById('userName'),
    userTag: document.getElementById('userTag'),
    authDiscordModal: document.getElementById('authDiscordModal'),
    btnDiscordLoginAction: document.getElementById('btnDiscordLoginAction'),
    btnContinueAsGuest: document.getElementById('btnContinueAsGuest'),

    // Home Shelves
    liveServersShelf: document.getElementById('liveServersShelf'),
    liveServersRow: document.getElementById('liveServersRow'),
    liveArrowLeft: document.getElementById('liveArrowLeft'),
    liveArrowRight: document.getElementById('liveArrowRight'),
    globalRecentShelf: document.getElementById('globalRecentShelf'),
    globalRecentRow: document.getElementById('globalRecentRow'),
    recentArrowLeft: document.getElementById('recentArrowLeft'),
    recentArrowRight: document.getElementById('recentArrowRight'),
    curatedTracksGrid: document.getElementById('curatedTracksGrid'),
    quickPicksRow: document.getElementById('quickPicksRow'),
    albumsRow: document.getElementById('albumsRow'),
    communityPlaylistsShelf: document.getElementById('communityPlaylistsShelf'),
    communityPlaylistsRow: document.getElementById('communityPlaylistsRow'),
    btnCreatePlHome: document.getElementById('btnCreatePlHome'),
    commArrowLeft: document.getElementById('commArrowLeft'),
    commArrowRight: document.getElementById('commArrowRight'),

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
    btnAddToPlCurrent: document.getElementById('btnAddToPlCurrent'),
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
    btnShowCreatePlInline: document.getElementById('btnShowCreatePlInline'),
    inlineCreatePlForm: document.getElementById('inlineCreatePlForm'),
    inlinePlNameInput: document.getElementById('inlinePlNameInput'),
    btnInlineCreateAndAdd: document.getElementById('btnInlineCreateAndAdd'),
    addToPlaylistList: document.getElementById('addToPlaylistList'),
    closeAddToPlaylistBtn: document.getElementById('closeAddToPlaylistBtn'),
    closeAddToPlaylistModalBtn: document.getElementById('closeAddToPlaylistModalBtn'),

    // Custom in-app confirmation modal (safe in Discord iframe sandbox)
    confirmActionModal: document.getElementById('confirmActionModal'),
    confirmModalTitle: document.getElementById('confirmModalTitle'),
    confirmModalDesc: document.getElementById('confirmModalDesc'),
    closeConfirmModalBtn: document.getElementById('closeConfirmModalBtn'),
    cancelConfirmModalBtn: document.getElementById('cancelConfirmModalBtn'),
    acceptConfirmModalBtn: document.getElementById('acceptConfirmModalBtn'),
  };

  // Safe in-app Confirmation Dialog Helper (replaces window.confirm which is blocked by iframe sandbox)
  let confirmActionCallback = null;
  function showConfirmModal({ title, message, confirmText = 'Подтвердить', confirmDanger = true, onConfirm }) {
    if (!el.confirmActionModal) {
      if (onConfirm) onConfirm();
      return;
    }
    if (el.confirmModalTitle) el.confirmModalTitle.textContent = title;
    if (el.confirmModalDesc) el.confirmModalDesc.textContent = message;
    if (el.acceptConfirmModalBtn) {
      el.acceptConfirmModalBtn.textContent = confirmText;
      el.acceptConfirmModalBtn.style.background = confirmDanger ? '#ef4444' : '#ff0000';
    }
    confirmActionCallback = onConfirm;
    el.confirmActionModal.style.display = 'flex';
  }

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

  // Parse mm:ss or hh:mm:ss string to numeric seconds
  function parseDurationStr(str) {
    if (!str || typeof str !== 'string') return 0;
    const parts = str.trim().split(':').map(Number);
    if (parts.some(isNaN)) return 0;
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    return 0;
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

  // Discord Embedded App SDK Init & OAuth Authorization
  async function initDiscordSdk(forceConsent = false) {
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
          prompt: forceConsent ? 'consent' : 'none',
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
            state.isAuthenticated = true;
            localStorage.setItem('music_authenticated', 'true');
            saveUser();
            if (el.authDiscordModal) el.authDiscordModal.style.display = 'none';
            showToast(`Вы авторизованы как ${state.userName}`, 'success', 'fa-user-check');
            return true;
          }
        }
      } catch (err) {
        console.warn('Discord SDK auth attempt:', err);
      }
    }

    // If not authenticated and not a real user ID: show modal prompt
    if (!state.isAuthenticated && (!state.userId || state.userId.startsWith('user_'))) {
      if (el.authDiscordModal) {
        el.authDiscordModal.style.display = 'flex';
      }
    }
    return false;
  }

  function saveUser() {
    localStorage.setItem('music_user_id', state.userId);
    localStorage.setItem('music_user_name', state.userName);
    localStorage.setItem('music_user_avatar', state.userAvatar);
    updateUserUI();
    if (typeof loadUserDataFromDB === 'function') {
      loadUserDataFromDB();
    }
  }

  function updateUserUI() {
    if (el.userName) el.userName.textContent = state.userName || t('user.defaultName');
    if (el.userTag) el.userTag.textContent = state.userId ? `ID: ${state.userId.slice(-6)}` : t('user.clickToSelect');
    if (el.userAvatar) {
      el.userAvatar.src = getSafeImageUrl(state.userAvatar);
      el.userAvatar.onerror = function() { this.src = '/static/activity_icon.jpg'; };
    }
    const isAdmin = (state.userId === '410432175373156352') || localStorage.getItem('music_is_admin') === 'true';
    const navAdmin = document.getElementById('navAdminBtn');
    if (navAdmin) navAdmin.style.display = isAdmin ? 'flex' : 'none';
    const headerAdmin = document.getElementById('headerAdminPill');
    if (headerAdmin) headerAdmin.style.display = isAdmin ? 'inline-flex' : 'none';
  }

  // Voice Channel Check & Channel Members Rendering
  async function checkUserVoice() {
    const guildQuery = state.guildId ? `&guild_id=${encodeURIComponent(state.guildId)}` : '';
    const chanQuery = state.channelId ? `&channel_id=${encodeURIComponent(state.channelId)}` : '';

    let voiceData = null;

    // 1. Check user voice directly if authenticated Discord ID
    if (state.userId && !state.userId.startsWith('user_')) {
      try {
        const resp = await fetch(`/api/user-voice?user_id=${encodeURIComponent(state.userId)}${guildQuery}${chanQuery}`);
        const data = await resp.json();
        if (data.in_voice || (data.bot_voice && data.bot_voice.channel_name)) {
          voiceData = data;
        }
      } catch (e) {
        console.error('Error checking user voice:', e);
      }
    }

    // 2. If not detected via user ID: check bot's active voice room
    if (!voiceData) {
      try {
        const botCheckResp = await fetch(`/api/user-voice?user_id=0${guildQuery}`);
        const botCheckData = await botCheckResp.json();
        if (botCheckData.bot_voice && botCheckData.bot_voice.channel_name) {
          voiceData = {
            in_voice: true,
            guild_id: botCheckData.bot_voice.guild_id,
            guild_name: botCheckData.bot_voice.guild_name,
            channel_id: botCheckData.bot_voice.channel_id,
            channel_name: botCheckData.bot_voice.channel_name,
            channel_members: botCheckData.bot_voice.channel_members || []
          };
        }
      } catch (_) {}
    }

    if (voiceData && (voiceData.in_voice || (voiceData.bot_voice && voiceData.bot_voice.channel_name))) {
      state.inVoice = true;
      state.guildId = voiceData.guild_id || (voiceData.bot_voice ? voiceData.bot_voice.guild_id : state.guildId);
      state.guildName = voiceData.guild_name || (voiceData.bot_voice ? voiceData.bot_voice.guild_name : state.guildName);
      state.channelId = voiceData.channel_id || (voiceData.bot_voice ? voiceData.bot_voice.channel_id : state.channelId);
      state.channelName = voiceData.channel_name || (voiceData.bot_voice ? voiceData.bot_voice.channel_name : state.channelName);
      state.channelMembers = voiceData.channel_members || (voiceData.bot_voice ? voiceData.bot_voice.channel_members : []) || [];

      const count = state.channelMembers.length;
      if (el.voiceIndicator) el.voiceIndicator.className = 'status-indicator connected';
      if (el.voiceChannelName) el.voiceChannelName.textContent = state.channelName;
      if (el.voiceMembersCountBadge) el.voiceMembersCountBadge.textContent = count;
      if (el.voiceStatusPill) el.voiceStatusPill.classList.add('active');

      if (el.voiceDropdownTitle) el.voiceDropdownTitle.textContent = `🔊 ${state.channelName}`;
      if (el.voiceDropdownSub) el.voiceDropdownSub.textContent = `${count} ${count === 1 ? 'слушатель' : (count >= 2 && count <= 4 ? 'слушателя' : 'слушателей')} в комнате:`;

      renderVoiceMembers(state.channelMembers);
      sendWsSubscribe();
    } else {
      state.inVoice = false;
      state.channelMembers = [];

      if (el.voiceIndicator) el.voiceIndicator.className = 'status-indicator';
      if (el.voiceChannelName) el.voiceChannelName.textContent = t('voice.notConnected');
      if (el.voiceMembersCountBadge) el.voiceMembersCountBadge.textContent = '0';
      if (el.voiceStatusPill) el.voiceStatusPill.classList.remove('active');

      if (el.voiceDropdownTitle) el.voiceDropdownTitle.textContent = 'Голосовой канал';
      if (el.voiceDropdownSub) el.voiceDropdownSub.textContent = 'Бот не подключен к голосовой комнате';

      renderVoiceMembers([]);
    }
  }

  // Room moving and cross-server switching are disabled per design (entry strictly via Activity)
  async function fetchGuilds() {}
  function renderVoiceRooms() {}

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

  // Live on other servers & Global Recent Tracks
  let liveFeedCache = [];
  let recentFeedCache = [];

  async function fetchFeedDiscovery() {
    try {
      const resp = await fetch('/api/feed/discovery');
      const data = await resp.json();
      if (data) {
        liveFeedCache = Array.isArray(data.live_now) ? data.live_now : [];
        renderLiveServers();
        recentFeedCache = Array.isArray(data.recent_history) ? data.recent_history : [];
        renderGlobalRecent();
      }
    } catch (e) {
      console.warn('Could not fetch /api/feed/discovery:', e);
    }
  }

  function renderLiveServers() {
    if (!el.liveServersRow) return;
    el.liveServersRow.innerHTML = '';

    if (!liveFeedCache || liveFeedCache.length === 0) {
      el.liveServersRow.innerHTML = `
        <div style="padding: 16px 20px; background: rgba(255,255,255,0.03); border: 1px dashed rgba(255,255,255,0.1); border-radius: 12px; display: flex; align-items: center; gap: 12px; color: #888; font-size: 13px; width: 100%;">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="#666"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>
          <span>В данный момент на серверах музыка не играет. Подключитесь к голосовому каналу и включите трек!</span>
        </div>
      `;
      return;
    }
    if (el.liveServersShelf) el.liveServersShelf.style.display = 'block';

    liveFeedCache.forEach(item => {
      const track = item.track || {};
      const card = document.createElement('div');
      card.className = 'live-card';
      const listeners = item.listeners_count || 1;
      const guildName = item.guild_name || 'Discord Сервер';
      const channelName = item.channel_name || 'Голосовой';
      const thumb = track.thumbnail || '/static/activity_icon.jpg';

      card.innerHTML = `
        <div class="live-card-server-bar">
          <span class="live-card-badge"><span class="live-dot-pulse" style="width:6px;height:6px;"></span> LIVE</span>
          <span class="live-card-listeners" title="Слушателей в канале">
            <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>
            ${listeners} в войсе
          </span>
        </div>
        <div class="live-card-thumb-wrap">
          <img src="${getSafeImageUrl(thumb)}" alt="${escapeHtml(track.title || '')}" class="live-card-thumb" loading="lazy" onerror="this.src='/static/activity_icon.jpg';">
          <div class="square-card-play-btn" title="Включить этот трек">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="#000"><path d="M8 5v14l11-7z"/></svg>
          </div>
        </div>
        <span class="live-card-title" title="${escapeHtml(track.title || 'Без названия')}">${escapeHtml(track.title || 'Без названия')}</span>
        <span class="live-card-artist" title="${escapeHtml(track.artist || '')}">${escapeHtml(track.artist || '')}</span>
        <div class="live-card-footer">
          <span class="live-card-server-name" title="${escapeHtml(guildName)} • ${escapeHtml(channelName)}">
            <svg viewBox="0 0 24 24" width="13" height="13" fill="#5865F2" style="vertical-align:middle;margin-right:4px;"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994.021-.041.001-.09-.041-.106a13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.929 1.793 8.18 1.793 12.061 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.893.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>
            ${escapeHtml(guildName)}
          </span>
          <span style="font-size:10px;color:#888;">${escapeHtml(track.duration_str || '')}</span>
        </div>
      `;

      const playBtn = card.querySelector('.square-card-play-btn');
      if (playBtn) {
        playBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (track.url || track.title) {
            playTrack(track, true);
          }
        });
      }

      el.liveServersRow.appendChild(card);
    });
  }

  function renderGlobalRecent() {
    if (!el.globalRecentRow) return;
    el.globalRecentRow.innerHTML = '';

    if (!recentFeedCache || recentFeedCache.length === 0) {
      el.globalRecentRow.innerHTML = `
        <div style="padding: 16px 20px; background: rgba(255,255,255,0.03); border: 1px dashed rgba(255,255,255,0.1); border-radius: 12px; display: flex; align-items: center; gap: 12px; color: #888; font-size: 13px; width: 100%;">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="#666"><path d="M13 3a9 9 0 0 0-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.954 8.954 0 0 0 13 21a9 9 0 0 0 0-18zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/></svg>
          <span>Здесь появятся недавние треки, которые слушают пользователи нашего бота.</span>
        </div>
      `;
      return;
    }
    if (el.globalRecentShelf) el.globalRecentShelf.style.display = 'block';

    recentFeedCache.forEach(track => {
      const card = document.createElement('div');
      card.className = 'recent-card';
      const thumb = track.thumbnail || '/static/activity_icon.jpg';
      const sourceIcon = track.source === 'soundcloud'
        ? '<svg viewBox="0 0 24 24" width="13" height="13" fill="#ff5500" style="vertical-align:middle;margin-right:3px;"><path d="M1.175 12.225c-.052 0-.095.044-.103.098l-.297 2.378.297 2.298c.008.056.051.098.103.098.053 0 .096-.042.102-.098l.333-2.298-.333-2.378c-.006-.054-.049-.098-.102-.098zm1.53-.873c-.066 0-.12.053-.128.12l-.248 3.251.248 3.098c.008.067.062.12.128.12.065 0 .118-.053.125-.12l.288-3.098-.288-3.251c-.007-.067-.06-.12-.125-.12zm1.583-.541c-.08 0-.145.064-.153.143l-.195 3.792.195 3.513c.008.08.073.144.153.144.079 0 .143-.064.15-.144l.235-3.513-.235-3.792c-.007-.079-.071-.143-.15-.143zm1.611-.318c-.094 0-.17.075-.178.167l-.147 4.11.147 3.702c.008.093.084.167.178.167.092 0 .167-.074.173-.167l.186-3.702-.186-4.11c-.006-.092-.081-.167-.173-.167zm1.62-.204c-.107 0-.193.085-.201.19l-.105 4.314.105 3.805c.008.105.094.19.201.19.105 0 .19-.085.195-.19l.142-3.805-.142-4.314c-.005-.105-.09-.19-.195-.19zm1.624-.045c-.119 0-.215.096-.222.213l-.066 4.359.066 3.829c.007.118.103.214.222.214.117 0 .211-.096.216-.214l.099-3.829-.099-4.359c-.005-.117-.099-.213-.216-.213zm1.625.045c-.131 0-.237.105-.242.234l-.034 4.314.034 3.804c.005.13.111.235.242.235.129 0 .232-.105.236-.235l.06-3.804-.06-4.314c-.004-.129-.107-.234-.236-.234zm7.227-3.415c-.297 0-.583.05-.851.144-.316-2.28-2.284-4.048-4.66-4.048-.737 0-1.433.17-2.052.472-.191.093-.284.286-.284.498v10.985c0 .285.232.516.518.516h7.329c2.195 0 3.975-1.78 3.975-3.975 0-2.196-1.78-3.976-3.975-3.976z"/></svg>'
        : '<svg viewBox="0 0 24 24" width="13" height="13" fill="#ff0000" style="vertical-align:middle;margin-right:3px;"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>';

      card.innerHTML = `
        <div class="recent-card-thumb-wrap">
          <img src="${getSafeImageUrl(thumb)}" alt="${escapeHtml(track.title || '')}" class="recent-card-thumb" loading="lazy" onerror="this.src='/static/activity_icon.jpg';">
          <div class="square-card-play-btn" title="Слушать">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="#000"><path d="M8 5v14l11-7z"/></svg>
          </div>
        </div>
        <span class="recent-card-title" title="${escapeHtml(track.title || 'Без названия')}">${escapeHtml(track.title || 'Без названия')}</span>
        <span class="recent-card-artist" title="${escapeHtml(track.artist || '')}">${escapeHtml(track.artist || '')}</span>
        <div class="recent-card-time">
          ${sourceIcon} <span>${escapeHtml(track.duration_str || '')}</span>
        </div>
      `;

      const playBtn = card.querySelector('.square-card-play-btn');
      if (playBtn) {
        playBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (track.url || track.title) {
            playTrack(track, true);
          }
        });
      }

      el.globalRecentRow.appendChild(card);
    });
  }

  // Render Home View (Screenshot 2: Curated 3-column + Square cards + Community Playlists)
  function renderHomeView() {
    // 0. Live Servers Row
    renderLiveServers();

    // 0.1 Global Recent Row
    renderGlobalRecent();

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

        const playBtn = row.querySelector('.compact-play-hover') || row.querySelector('.compact-thumb-wrap');
        if (playBtn) {
          playBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            playTrack(track, true);
          });
        }
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

    // 2. Square Cards Row: Хиты SoundCloud & YouTube
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
        const playBtn = card.querySelector('.square-card-play-btn');
        if (playBtn) {
          playBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            playTrack({
              title: item.title,
              artist: item.artist,
              thumbnail: item.thumbnail,
              source: item.source || 'youtube',
              url: item.url || `https://music.youtube.com/search?q=${encodeURIComponent(item.title + ' ' + item.artist)}`
            }, true);
          });
        }
        el.quickPicksRow.appendChild(card);
      });
    }

    // 3. User Community Playlists Shelf
    renderCommunityPlaylists();
  }

  // Community Playlists (Shared albums and leaderboard)
  let communityPlaylistsCache = [];
  async function fetchCommunityPlaylists() {
    try {
      const q = state.userId ? `?user_id=${encodeURIComponent(state.userId)}&sort=top` : '?sort=top';
      const resp = await fetch(`/api/community/playlists${q}`);
      const data = await resp.json();
      if (data && Array.isArray(data.playlists)) {
        communityPlaylistsCache = data.playlists;
        if (state.currentView === 'home') {
          renderCommunityPlaylists();
        }
      }
    } catch (e) {
      console.warn('Could not fetch community playlists:', e);
    }
  }

  function renderCommunityPlaylists() {
    if (!el.communityPlaylistsRow) return;
    el.communityPlaylistsRow.innerHTML = '';

    if (el.communityPlaylistsShelf) {
      el.communityPlaylistsShelf.style.display = 'block';
    }

    if (!communityPlaylistsCache || communityPlaylistsCache.length === 0) {
      const emptyCard = document.createElement('div');
      emptyCard.className = 'community-card';
      emptyCard.style.cssText = 'border: 1px dashed rgba(255,255,255,0.18); cursor: pointer; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 220px; text-align: center; padding: 24px; border-radius: 12px; background: rgba(255,255,255,0.02); flex: 0 0 220px;';
      emptyCard.innerHTML = `
        <div style="width: 48px; height: 48px; border-radius: 50%; background: rgba(255,0,0,0.15); display: flex; align-items: center; justify-content: center; color: #ff4d4d; font-size: 26px; margin-bottom: 12px; font-weight: 300;">+</div>
        <span style="font-weight: 600; font-size: 14px; color: #fff;">Создать плейлист</span>
        <span style="font-size: 12px; color: #888; margin-top: 4px; max-width: 170px;">Пока нет плейлистов сообщества. Создайте первый плейлист!</span>
      `;
      emptyCard.addEventListener('click', () => {
        openCreatePlaylistModal();
      });
      el.communityPlaylistsRow.appendChild(emptyCard);
      return;
    }

    if (el.communityPlaylistsShelf) {
      el.communityPlaylistsShelf.style.display = 'block';
    }

    communityPlaylistsCache.forEach((pl, index) => {
      const rank = index + 1;
      const card = document.createElement('div');
      card.className = 'community-card';
      const trackCount = pl.tracks ? pl.tracks.length : 0;
      const isLiked = Boolean(pl.is_liked);
      const likesCount = pl.likes_count || 0;
      const coverUrl = pl.cover || (pl.tracks && pl.tracks[0] ? pl.tracks[0].thumbnail : '/static/activity_icon.jpg');

      card.innerHTML = `
        <div class="community-card-thumb-wrap">
          <span class="community-rank-badge">#${rank}</span>
          <img src="${getSafeImageUrl(coverUrl)}" alt="${escapeHtml(pl.title)}" class="community-card-thumb" loading="lazy" onerror="this.src='/static/activity_icon.jpg';">
          <div class="square-card-play-btn" title="Слушать плейлист">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="#000"><path d="M8 5v14l11-7z"/></svg>
          </div>
        </div>
        <span class="community-card-title" title="${escapeHtml(pl.title)}">${escapeHtml(pl.title)}</span>
        <div class="community-author-row">
          <img src="${getSafeImageUrl(pl.author_avatar || '/static/activity_icon.jpg')}" class="community-author-avatar" onerror="this.src='/static/activity_icon.jpg';">
          <span class="community-author-name" title="${escapeHtml(pl.author_name || 'Пользователь')}">${escapeHtml(pl.author_name || 'Пользователь')}</span>
        </div>
        <div class="community-bottom-row">
          <span class="community-track-count">${trackCount} треков</span>
          <button class="community-like-btn ${isLiked ? 'liked' : ''}" title="${isLiked ? 'Убрать отметку' : 'Нравится плейлист'}">
            <svg viewBox="0 0 24 24"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
            <span class="likes-num">${likesCount}</span>
          </button>
        </div>
      `;

      // Play button on card thumb
      const playBtn = card.querySelector('.square-card-play-btn');
      playBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (pl.tracks && pl.tracks.length > 0) {
          for (let i = 0; i < pl.tracks.length; i++) {
            await playTrack(pl.tracks[i], i === 0);
          }
          showToast(`Воспроизведение плейлиста «${pl.title}»`, 'success');
        } else {
          showToast('В этом плейлисте пока нет треков', 'info');
        }
      });

      // Like button
      const likeBtn = card.querySelector('.community-like-btn');
      likeBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!state.userId) {
          showToast('Войдите через Discord, чтобы ставить лайки', 'warning');
          return;
        }
        try {
          const resp = await fetch(`/api/community/playlists/${encodeURIComponent(pl.id)}/like`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: state.userId })
          });
          const data = await resp.json();
          if (data && data.success) {
            pl.is_liked = data.liked;
            pl.likes_count = data.likes_count;
            if (data.liked) {
              likeBtn.classList.add('liked');
              showToast(`Плейлист «${pl.title}» добавлен в понравившиеся!`, 'success');
            } else {
              likeBtn.classList.remove('liked');
              showToast(`Отметка «Нравится» снята`, 'info');
            }
            likeBtn.querySelector('.likes-num').textContent = data.likes_count;
          }
        } catch (err) {
          console.warn('Like toggle failed:', err);
        }
      });

      // Click card -> Open playlist view
      card.addEventListener('click', () => {
        const existing = state.customPlaylists.find(p => String(p.id) === String(pl.id));
        if (!existing) {
          state.customPlaylists.push({
            id: String(pl.id),
            name: pl.title,
            author: pl.author_name || 'Пользователь',
            author_avatar: pl.author_avatar,
            cover: pl.cover,
            tracks: pl.tracks || []
          });
        }
        switchView('playlist', String(pl.id));
      });

      el.communityPlaylistsRow.appendChild(card);
    });
  }

  // Recommendations loader from server
  let recommendationsLoaded = false;
  async function fetchRecommendations() {
    if (recommendationsLoaded) return;
    try {
      const resp = await fetch('/api/recommendations');
      const data = await resp.json();
      if (data) {
        if (data.curated && data.curated.length) CURATED_RECOMMENDED = data.curated;
        if (data.quick_picks && data.quick_picks.length) CURATED_QUICK_PICKS = data.quick_picks;
        if (data.albums && data.albums.length) CURATED_ALBUMS = data.albums;
        recommendationsLoaded = true;
        if (state.currentView === 'home') renderHomeView();
      }
    } catch (e) {
      console.warn('Could not fetch /api/recommendations:', e);
    }
  }

  // Load User Data from PostgreSQL Database
  async function loadUserDataFromDB() {
    if (!state.userId) return;
    try {
      // 1. Liked Tracks
      const likedResp = await fetch(`/api/user/liked?user_id=${encodeURIComponent(state.userId)}`);
      const likedData = await likedResp.json();
      if (likedData && Array.isArray(likedData.tracks)) {
        if (likedData.tracks.length === 0 && state.likedTracks && state.likedTracks.length > 0) {
          // Sync existing local tracks into PostgreSQL
          for (const localTrk of state.likedTracks) {
            fetch('/api/user/liked', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ user_id: state.userId, track: localTrk, action: 'add' })
            }).catch(e => console.warn('Sync local liked track error:', e));
          }
        } else {
          state.likedTracks = likedData.tracks;
          saveJson('musicium_liked_tracks', state.likedTracks);
        }
        if (state.currentView === 'liked') renderLikedView();
        updateDockLikeBtn();
      }

      // 2. Playlists
      const plResp = await fetch(`/api/user/playlists?user_id=${encodeURIComponent(state.userId)}`);
      const plData = await plResp.json();
      if (plData && Array.isArray(plData.playlists)) {
        state.customPlaylists = plData.playlists.map(p => ({
          id: String(p.id),
          name: p.title,
          cover: p.cover,
          author: state.userName || 'Вы',
          tracks: p.tracks || []
        }));
        saveJson('musicium_custom_playlists', state.customPlaylists);
        renderSidebarPlaylists();
        if (state.currentView === 'playlist') renderPlaylistView(state.selectedPlaylistId);
      }

      // 3. History
      const histResp = await fetch(`/api/user/history?user_id=${encodeURIComponent(state.userId)}`);
      const histData = await histResp.json();
      if (histData && Array.isArray(histData.history)) {
        state.historyTracks = histData.history;
        saveJson('musicium_history_tracks', state.historyTracks);
        if (state.currentView === 'history') renderHistoryView();
      }
    } catch (err) {
      console.warn('Could not sync user data from PostgreSQL:', err);
    }
  }

  // User History helper
  function addToHistory(track) {
    if (!track) return;
    state.historyTracks = state.historyTracks.filter(t => t.url !== track.url && t.title !== track.title);
    state.historyTracks.unshift({
      title: track.title,
      artist: track.artist || 'Неизвестный исполнитель',
      thumbnail: track.thumbnail || '/static/activity_icon.jpg',
      duration_str: track.duration_str || '3:00',
      source: track.source || 'youtube',
      url: track.url || '',
      played_at: new Date().toISOString()
    });
    if (state.historyTracks.length > 50) state.historyTracks.pop();
    saveJson('musicium_history_tracks', state.historyTracks);
    if (state.userId) {
      fetch('/api/user/history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: state.userId, track: track })
      }).catch(() => {});
    }
    if (state.currentView === 'history') renderHistoryView();
  }

  // Liked Tracks Functions
  function isTrackLiked(track) {
    if (!track) return false;
    return state.likedTracks.some(t => (t.url && t.url === track.url) || (t.title === track.title && t.artist === track.artist));
  }

  function toggleLikeTrack(track) {
    if (!track) return;
    const isLiked = isTrackLiked(track);
    const idx = state.likedTracks.findIndex(t => (t.url && t.url === track.url) || (t.title === track.title && t.artist === track.artist));
    if (isLiked && idx >= 0) {
      state.likedTracks.splice(idx, 1);
      saveJson('musicium_liked_tracks', state.likedTracks);
      showToast(t('toast.likedRemoved'), 'info', 'fa-heart-crack');
      if (state.userId) {
        fetch('/api/user/liked', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: state.userId, track: track, action: 'remove' })
        })
        .then(r => r.json())
        .then(d => console.log('DB unliked track:', d))
        .catch(e => console.error('DB unlike failed:', e));
      }
    } else {
      const newTrack = {
        title: track.title,
        artist: track.artist || 'Неизвестный исполнитель',
        thumbnail: track.thumbnail || '/static/activity_icon.jpg',
        duration_str: track.duration_str || '3:00',
        source: track.source || 'youtube',
        url: track.url || `https://music.youtube.com/search?q=${encodeURIComponent(track.title + ' ' + (track.artist || ''))}`,
        added_at: Date.now()
      };
      state.likedTracks.unshift(newTrack);
      saveJson('musicium_liked_tracks', state.likedTracks);
      showToast(t('toast.likedAdded'), 'success', 'fa-heart');
      if (state.userId) {
        fetch('/api/user/liked', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: state.userId, track: newTrack, action: 'add' })
        })
        .then(r => r.json())
        .then(d => console.log('DB liked track saved:', d))
        .catch(e => console.error('DB like failed:', e));
      }
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
        const removed = pl.tracks.splice(index, 1)[0];
        saveJson('musicium_custom_playlists', state.customPlaylists);
        if (state.userId && removed && !isNaN(parseInt(pl.id, 10))) {
          fetch(`/api/user/playlists/${encodeURIComponent(pl.id)}/tracks`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ track_url: removed.url })
          }).catch(() => {});
        }
        showToast(t('toast.trackRemovedFromPlaylist'), 'info');
        renderPlaylistView(playlistId);
      });

      el.customPlaylistTracksContainer.appendChild(item);
    });
  }

  async function addTrackToCustomPlaylist(pl, track) {
    if (!pl.tracks) pl.tracks = [];
    const exists = pl.tracks.some(t => t.title === track.title && (t.artist === track.artist || (track.url && t.url === track.url)));
    if (exists) {
      showToast(t('toast.alreadyInPlaylist'), 'warning');
      return false;
    }
    const newTr = {
      title: track.title,
      artist: track.artist || 'Неизвестный исполнитель',
      thumbnail: track.thumbnail || '/static/activity_icon.jpg',
      duration_str: track.duration_str || '3:00',
      duration: track.duration || 0,
      source: track.source || 'youtube',
      url: track.url || `https://music.youtube.com/search?q=${encodeURIComponent(track.title + ' ' + (track.artist || ''))}`,
      added_at: Date.now()
    };
    pl.tracks.push(newTr);
    saveJson('musicium_custom_playlists', state.customPlaylists);
    if (state.userId && !isNaN(parseInt(pl.id, 10))) {
      fetch(`/api/user/playlists/${encodeURIComponent(pl.id)}/tracks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ track: newTr })
      }).catch(() => {});
    }
    showToast(t('toast.trackAddedToPlaylist', { name: pl.name }), 'success');
    renderSidebarPlaylists();
    return true;
  }

  function renderAddToPlaylistList() {
    if (!el.addToPlaylistList) return;
    el.addToPlaylistList.innerHTML = '';
    const track = state.trackToAddToPlaylist;
    if (!track) return;

    if (!state.customPlaylists || state.customPlaylists.length === 0) {
      el.addToPlaylistList.innerHTML = `
        <div style="padding: 16px 8px; text-align: center; color: #888; font-size: 13px;">
          <p style="margin: 0;">У вас пока нет плейлистов.<br>Нажмите «+ Создать новый плейлист» выше!</p>
        </div>
      `;
      return;
    }

    state.customPlaylists.forEach(pl => {
      const row = document.createElement('div');
      row.className = 'modal-playlist-select-item';
      const count = pl.tracks ? pl.tracks.length : 0;
      const alreadyIn = pl.tracks && pl.tracks.some(t => t.title === track.title && (t.artist === track.artist || (track.url && t.url === track.url)));

      row.innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;min-width:0;flex:1;">
          <div style="width:34px;height:34px;border-radius:6px;background:rgba(255,255,255,0.08);display:flex;align-items:center;justify-content:center;flex-shrink:0;">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>
          </div>
          <div style="min-width:0;flex:1;">
            <div style="font-weight:600;font-size:13px;color:#eee;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(pl.name)}</div>
            <div style="font-size:11px;color:#888;">${count} треков</div>
          </div>
        </div>
        <div>
          ${alreadyIn
            ? `<span style="font-size:12px;color:#10b981;font-weight:600;display:inline-flex;align-items:center;gap:4px;">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="#10b981"><path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z"/></svg> Добавлен
               </span>`
            : `<button class="btn-primary-yt btn-add-to-this-pl" style="height:32px;padding:0 12px;font-size:12px;">+ Добавить</button>`
          }
        </div>
      `;

      const addBtn = row.querySelector('.btn-add-to-this-pl');
      if (addBtn) {
        addBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const ok = await addTrackToCustomPlaylist(pl, track);
          if (ok) {
            renderAddToPlaylistList();
          }
        });
      }

      el.addToPlaylistList.appendChild(row);
    });
  }

  function openAddToPlaylistModal(track) {
    state.trackToAddToPlaylist = track;
    if (el.addToPlaylistTrackInfo) {
      const thumb = track.thumbnail || '/static/activity_icon.jpg';
      el.addToPlaylistTrackInfo.innerHTML = `
        <div style="display:flex;align-items:center;gap:12px;background:rgba(255,255,255,0.04);padding:10px 12px;border-radius:10px;margin-bottom:14px;border:1px solid rgba(255,255,255,0.06);">
          <img src="${getSafeImageUrl(thumb)}" style="width:44px;height:44px;border-radius:6px;object-fit:cover;" onerror="this.src='/static/activity_icon.jpg'">
          <div style="min-width:0;flex:1;">
            <div style="font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#fff;">${escapeHtml(track.title)}</div>
            <div style="font-size:12px;color:#aaa;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(track.artist || '')}</div>
          </div>
        </div>
      `;
    }

    if (el.inlineCreatePlForm) el.inlineCreatePlForm.style.display = 'none';
    if (el.btnShowCreatePlInline) el.btnShowCreatePlInline.style.display = 'flex';
    if (el.inlinePlNameInput) el.inlinePlNameInput.value = '';

    renderAddToPlaylistList();

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

  // Search tracks (only searches and renders results, never automatically plays)
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

      card.querySelector('.card-play-overlay').addEventListener('click', (e) => {
        e.stopPropagation();
        playTrack(track, true);
      });
      card.querySelector('.btn-play-now').addEventListener('click', (e) => {
        e.stopPropagation();
        playTrack(track, true);
      });
      card.querySelector('.btn-add-queue').addEventListener('click', (e) => {
        e.stopPropagation();
        playTrack(track, false);
      });
      card.querySelector('.btn-card-like').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleLikeTrack(track);
        renderTracks(state.lastTracks);
      });
      card.querySelector('.btn-card-add-pl').addEventListener('click', (e) => {
        e.stopPropagation();
        openAddToPlaylistModal(track);
      });

      el.tracksGrid.appendChild(card);
    });
  }

  // Send play request to backend
  async function playTrack(track, playNow = false) {
    if (!state.inVoice && !state.channelId) {
      await checkUserVoice();
      if (!state.inVoice && !state.channelId) {
        if (el.voiceWidgetContainer) {
          el.voiceWidgetContainer.classList.add('dropdown-open');
        }
        showToast('Вы должны находиться в голосовом канале на сервере, чтобы включить музыку!', 'warning', 'fa-triangle-exclamation');
        return;
      }
    }

    showToast(t('toast.request', { title: track.title }), 'info', 'fa-music');

    const effectiveGuildId = state.guildId;
    const effectiveChannelId = state.channelId;

    try {
      const explicitVol = (state.userExplicitVolume !== null) ? state.userExplicitVolume : (el.volumeSlider ? parseInt(el.volumeSlider.value) : 100);
      const resp = await fetch('/api/play', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: state.userId,
          guild_id: effectiveGuildId,
          channel_id: effectiveChannelId,
          track: track,
          play_now: playNow,
          volume: explicitVol,
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

      addToHistory(track);

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

  // Send player action (checks if user is in voice, except for volume setting)
  async function sendPlayerAction(action, payload = {}) {
    if (action !== 'volume' && !state.inVoice && !state.channelId) {
      await checkUserVoice();
      if (!state.inVoice && !state.channelId) {
        if (el.voiceWidgetContainer) {
          el.voiceWidgetContainer.classList.add('dropdown-open');
        }
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
          channel_id: state.channelId,
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

    // Volume sync (UI display only, NEVER fire network requests here)
    if (playerState && playerState.volume !== undefined && !state.isAdjustingVolume && (Date.now() - state.lastUserVolumeChange > 1200)) {
      let serverVol = Math.round(Number(playerState.volume));
      if (isNaN(serverVol)) serverVol = 100;
      const vol = Math.max(0, Math.min(200, serverVol));
      if (el.volumeSlider) el.volumeSlider.value = vol;
      if (el.volumeVal) el.volumeVal.textContent = `${vol}%`;
      updateVolumeIcon(vol);
      state.savedVolume = vol;
    }

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
      if (el.sidebarQueueCount) el.sidebarQueueCount.textContent = (playerState && playerState.queue) ? playerState.queue.length : '0';

      updateDockLikeBtn();
      if (state.currentView === 'queue') renderQueueView();
      return;
    }

    const track = playerState.current_track;
    state.isPlaying = !playerState.is_paused;
    
    // Resolve total duration from track, state, or duration_str
    let dur = 0;
    if (track && track.duration) dur = Number(track.duration);
    else if (playerState.duration) dur = Number(playerState.duration);
    else if (track && track.duration_str) dur = parseDurationStr(track.duration_str);
    else if (playerState.duration_str) dur = parseDurationStr(playerState.duration_str);
    state.duration = (dur > 0 && !isNaN(dur)) ? dur : 0;

    // Resolve elapsed playback position
    let elap = 0;
    if (playerState.elapsed_seconds !== undefined) elap = Number(playerState.elapsed_seconds);
    else if (playerState.position !== undefined) elap = Number(playerState.position);
    else elap = state.elapsed;
    state.elapsed = (elap >= 0 && !isNaN(elap)) ? elap : 0;

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
    if (el.timeDuration) {
      if (state.duration > 0) {
        el.timeDuration.textContent = formatTime(state.duration);
      } else if (state.player && state.player.current_track && state.player.current_track.duration_str) {
        el.timeDuration.textContent = state.player.current_track.duration_str;
      } else if (state.player && state.player.duration_str) {
        el.timeDuration.textContent = state.player.duration_str;
      } else {
        el.timeDuration.textContent = '00:00';
      }
    }
    if (el.progressFill) {
      if (state.duration > 0) {
        const pct = Math.min(100, Math.max(0, (state.elapsed / state.duration) * 100));
        el.progressFill.style.width = `${pct}%`;
      } else {
        el.progressFill.style.width = '0%';
      }
    }
  }

  function startProgressTicker() {
    stopProgressTicker();
    updateProgressBar();
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
      el.saveNewPlaylistBtn.addEventListener('click', async () => {
        const name = (el.newPlaylistTitleInput.value || '').trim();
        if (!name) return;
        let newId = 'pl_' + Date.now();
        if (state.userId) {
          try {
            const resp = await fetch('/api/user/playlists', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                user_id: state.userId,
                title: name,
                author_name: state.userName || 'Пользователь',
                author_avatar: state.userAvatar || '/static/activity_icon.jpg'
              })
            });
            const data = await resp.json();
            if (data.success && data.playlist) {
              newId = String(data.playlist.id);
            }
          } catch (e) {
            console.warn('Failed to create playlist in DB:', e);
          }
        }
        const newPl = {
          id: newId,
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
        fetchCommunityPlaylists();
      });
    }

    // Home Create Playlist button
    if (el.btnCreatePlHome) {
      el.btnCreatePlHome.addEventListener('click', () => {
        if (el.newPlaylistTitleInput) el.newPlaylistTitleInput.value = '';
        if (el.newPlaylistModal) el.newPlaylistModal.style.display = 'flex';
        if (el.newPlaylistTitleInput) el.newPlaylistTitleInput.focus();
      });
    }

    // Dock Add To Playlist button
    if (el.btnAddToPlCurrent) {
      el.btnAddToPlCurrent.addEventListener('click', () => {
        const cur = state.player && state.player.current_track;
        if (cur) {
          openAddToPlaylistModal(cur);
        } else {
          showToast('Сейчас ничего не играет', 'info');
        }
      });
    }

    // Add To Playlist Modal: Inline create playlist
    if (el.btnShowCreatePlInline) {
      el.btnShowCreatePlInline.addEventListener('click', () => {
        if (el.inlineCreatePlForm) {
          const isHidden = el.inlineCreatePlForm.style.display === 'none';
          el.inlineCreatePlForm.style.display = isHidden ? 'block' : 'none';
          if (isHidden && el.inlinePlNameInput) el.inlinePlNameInput.focus();
        }
      });
    }

    if (el.btnInlineCreateAndAdd) {
      el.btnInlineCreateAndAdd.addEventListener('click', async () => {
        const name = (el.inlinePlNameInput.value || '').trim();
        if (!name) {
          showToast('Введите название плейлиста', 'warning');
          return;
        }
        let newId = 'pl_' + Date.now();
        if (state.userId) {
          try {
            const resp = await fetch('/api/user/playlists', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                user_id: state.userId,
                title: name,
                author_name: state.userName || 'Пользователь',
                author_avatar: state.userAvatar || '/static/activity_icon.jpg'
              })
            });
            const data = await resp.json();
            if (data.success && data.playlist) {
              newId = String(data.playlist.id);
            }
          } catch (e) {
            console.warn('Failed to create playlist in DB:', e);
          }
        }
        const newPl = {
          id: newId,
          name: name,
          author: state.userName || 'Вы',
          tracks: []
        };
        state.customPlaylists.push(newPl);
        saveJson('musicium_custom_playlists', state.customPlaylists);
        showToast(t('toast.playlistCreated', { name }), 'success');
        renderSidebarPlaylists();
        fetchCommunityPlaylists();

        if (state.trackToAddToPlaylist) {
          await addTrackToCustomPlaylist(newPl, state.trackToAddToPlaylist);
        }

        if (el.inlinePlNameInput) el.inlinePlNameInput.value = '';
        if (el.inlineCreatePlForm) el.inlineCreatePlForm.style.display = 'none';
        renderAddToPlaylistList();
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

    // Custom Confirmation Modal events
    if (el.acceptConfirmModalBtn) {
      el.acceptConfirmModalBtn.addEventListener('click', () => {
        if (el.confirmActionModal) el.confirmActionModal.style.display = 'none';
        if (confirmActionCallback) {
          const cb = confirmActionCallback;
          confirmActionCallback = null;
          cb();
        }
      });
    }
    if (el.closeConfirmModalBtn) {
      el.closeConfirmModalBtn.addEventListener('click', () => {
        if (el.confirmActionModal) el.confirmActionModal.style.display = 'none';
        confirmActionCallback = null;
      });
    }
    if (el.cancelConfirmModalBtn) {
      el.cancelConfirmModalBtn.addEventListener('click', () => {
        if (el.confirmActionModal) el.confirmActionModal.style.display = 'none';
        confirmActionCallback = null;
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
        const plId = state.selectedPlaylistId;
        if (!plId) return;
        const pl = state.customPlaylists.find(p => p.id === plId);
        const name = pl ? pl.name : '';
        showConfirmModal({
          title: 'Удалить плейлист',
          message: `Удалить плейлист «${name}»? Это действие нельзя отменить.`,
          confirmText: 'Удалить',
          confirmDanger: true,
          onConfirm: async () => {
            state.customPlaylists = state.customPlaylists.filter(p => p.id !== plId);
            saveJson('musicium_custom_playlists', state.customPlaylists);
            if (state.userId && !isNaN(parseInt(plId, 10))) {
              fetch(`/api/user/playlists/${encodeURIComponent(plId)}?user_id=${encodeURIComponent(state.userId)}`, {
                method: 'DELETE'
              }).catch(() => {});
            }
            showToast(t('toast.playlistDeleted', { name }), 'info');
            renderSidebarPlaylists();
            switchView('home');
            fetchCommunityPlaylists();
          }
        });
      });
    }

    // History actions
    if (el.btnClearHistoryBtn) {
      el.btnClearHistoryBtn.addEventListener('click', () => {
        if (!state.historyTracks.length) {
          showToast('История прослушивания уже пуста', 'info');
          return;
        }
        showConfirmModal({
          title: 'Очистить историю',
          message: 'Вы действительно хотите удалить все треки из истории прослушивания?',
          confirmText: 'Очистить',
          confirmDanger: true,
          onConfirm: async () => {
            state.historyTracks = [];
            saveJson('musicium_history_tracks', []);
            if (state.userId) {
              fetch(`/api/user/history?user_id=${encodeURIComponent(state.userId)}`, {
                method: 'DELETE'
              }).catch(() => {});
            }
            showToast('История прослушивания очищена', 'info');
            renderHistoryView();
          }
        });
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

    // Live Servers Scroll Arrows
    if (el.liveArrowLeft && el.liveServersRow) {
      el.liveArrowLeft.addEventListener('click', () => {
        el.liveServersRow.scrollBy({ left: -360, behavior: 'smooth' });
      });
    }
    if (el.liveArrowRight && el.liveServersRow) {
      el.liveArrowRight.addEventListener('click', () => {
        el.liveServersRow.scrollBy({ left: 360, behavior: 'smooth' });
      });
    }

    // Global Recent Scroll Arrows
    if (el.recentArrowLeft && el.globalRecentRow) {
      el.recentArrowLeft.addEventListener('click', () => {
        el.globalRecentRow.scrollBy({ left: -360, behavior: 'smooth' });
      });
    }
    if (el.recentArrowRight && el.globalRecentRow) {
      el.recentArrowRight.addEventListener('click', () => {
        el.globalRecentRow.scrollBy({ left: 360, behavior: 'smooth' });
      });
    }

    // Community Shelf Scroll Arrows
    if (el.commArrowLeft && el.communityPlaylistsRow) {
      el.commArrowLeft.addEventListener('click', () => {
        el.communityPlaylistsRow.scrollBy({ left: -360, behavior: 'smooth' });
      });
    }
    if (el.commArrowRight && el.communityPlaylistsRow) {
      el.commArrowRight.addEventListener('click', () => {
        el.communityPlaylistsRow.scrollBy({ left: 360, behavior: 'smooth' });
      });
    }

    // Curated Shelf Scroll Arrows
    const shelfArrowLeft = document.getElementById('shelfArrowLeft');
    const shelfArrowRight = document.getElementById('shelfArrowRight');
    if (shelfArrowLeft && el.curatedTracksGrid) {
      shelfArrowLeft.addEventListener('click', () => {
        el.curatedTracksGrid.scrollBy({ left: -360, behavior: 'smooth' });
      });
    }
    if (shelfArrowRight && el.curatedTracksGrid) {
      shelfArrowRight.addEventListener('click', () => {
        el.curatedTracksGrid.scrollBy({ left: 360, behavior: 'smooth' });
      });
    }

    // Voice status widget hover intent & dropdown toggle
    let voiceHoverTimer = null;
    if (el.voiceWidgetContainer) {
      el.voiceWidgetContainer.addEventListener('mouseenter', () => {
        if (voiceHoverTimer) {
          clearTimeout(voiceHoverTimer);
          voiceHoverTimer = null;
        }
        el.voiceWidgetContainer.classList.add('dropdown-open');
      });

      el.voiceWidgetContainer.addEventListener('mouseleave', () => {
        if (voiceHoverTimer) clearTimeout(voiceHoverTimer);
        voiceHoverTimer = setTimeout(() => {
          el.voiceWidgetContainer.classList.remove('dropdown-open');
        }, 320);
      });
    }

    if (el.voiceStatusPill) {
      el.voiceStatusPill.addEventListener('click', (e) => {
        e.stopPropagation();
        if (voiceHoverTimer) {
          clearTimeout(voiceHoverTimer);
          voiceHoverTimer = null;
        }
        if (el.voiceWidgetContainer) {
          el.voiceWidgetContainer.classList.toggle('dropdown-open');
        }
        checkUserVoice();
      });
    }

    if (el.refreshVoiceBtn) {
      el.refreshVoiceBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await checkUserVoice();
        showToast(t('toast.channelRefreshed'), 'info', 'fa-arrows-rotate');
      });
    }

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
      if (el.voiceWidgetContainer && !el.voiceWidgetContainer.contains(e.target)) {
        el.voiceWidgetContainer.classList.remove('dropdown-open');
      }
    });

    // User badge: click opens auth modal if not authenticated, or shows status
    if (el.userBadge) {
      el.userBadge.addEventListener('click', () => {
        if (!state.isAuthenticated) {
          if (el.authDiscordModal) el.authDiscordModal.style.display = 'flex';
        } else {
          showToast(state.userName ? t('user.loggedInAs', { name: state.userName }) : t('user.profileActive'), 'info', 'fa-user');
        }
      });
    }

    // Discord Login Action buttons in modal
    if (el.btnDiscordLoginAction) {
      el.btnDiscordLoginAction.addEventListener('click', async () => {
        if (window.DiscordSDK) {
          const success = await initDiscordSdk(true);
          if (!success) {
            window.location.href = '/api/auth/discord';
          }
        } else {
          window.location.href = '/api/auth/discord';
        }
      });
    }

    if (el.btnContinueAsGuest) {
      el.btnContinueAsGuest.addEventListener('click', () => {
        if (el.authDiscordModal) el.authDiscordModal.style.display = 'none';
        if (!state.userId) {
          state.userId = 'user_' + Math.random().toString(36).substring(2, 12);
          saveUser();
        }
        showToast('Вы вошли как гость', 'info');
      });
    }

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
    el.volumeSlider.addEventListener('mousedown', () => {
      state.isAdjustingVolume = true;
      state.lastUserVolumeChange = Date.now();
    });
    el.volumeSlider.addEventListener('touchstart', () => {
      state.isAdjustingVolume = true;
      state.lastUserVolumeChange = Date.now();
    }, { passive: true });
    document.addEventListener('mouseup', () => {
      if (state.isAdjustingVolume) setTimeout(() => { state.isAdjustingVolume = false; }, 600);
    });
    document.addEventListener('touchend', () => {
      if (state.isAdjustingVolume) setTimeout(() => { state.isAdjustingVolume = false; }, 600);
    });

    el.volumeSlider.addEventListener('input', (e) => {
      const val = parseInt(e.target.value) || 0;
      el.volumeVal.textContent = `${val}%`;
      updateVolumeIcon(val);
      state.isMuted = (val === 0);
      state.isAdjustingVolume = true;
      state.userExplicitVolume = val;
      state.savedVolume = val;
      saveJson('musicium_volume', val);
      state.lastUserVolumeChange = Date.now();
      clearTimeout(volDebounce);
      volDebounce = setTimeout(() => {
        sendPlayerAction('volume', { value: val });
        setTimeout(() => { state.isAdjustingVolume = false; }, 600);
      }, 80);
    });

    el.volumeSlider.addEventListener('change', (e) => {
      const val = parseInt(e.target.value) || 0;
      state.userExplicitVolume = val;
      state.savedVolume = val;
      saveJson('musicium_volume', val);
      sendPlayerAction('volume', { value: val });
    });

    // Voice Widget: room selection removed (lockdown mode)

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

    // Restore saved volume preference if exists
    if (state.userExplicitVolume !== null) {
      const stored = Math.max(0, Math.min(200, state.userExplicitVolume));
      if (el.volumeSlider) el.volumeSlider.value = stored;
      if (el.volumeVal) el.volumeVal.textContent = `${stored}%`;
      updateVolumeIcon(stored);
    }

    updateUserUI();
    renderSidebarPlaylists();
    renderHomeView();
    attachEvents();
    fetchRecommendations();
    fetchCommunityPlaylists();
    fetchFeedDiscovery();
    loadUserDataFromDB();
    await initDiscordSdk();
    loadUserDataFromDB();
    await checkSystemStatus();
    await checkUserVoice();
    setupWebSocket();
    await fetchCurrentPlayer();

    // Periodic voice check every 10s, feed discovery every 25s
    setInterval(checkUserVoice, 10000);
    setInterval(fetchFeedDiscovery, 25000);
  }

  init();
})();
