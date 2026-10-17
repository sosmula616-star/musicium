/* ============================================================
   Английский перевод для всего, что не покрыто словарём I18N в app.js:
   новые разделы, плитки главной, караоке, статусы, уведомления, подсказки.
   Работает поверх готового DOM: при языке EN подменяет русские тексты и атрибуты
   (title / placeholder / aria-label) и возвращает их обратно при переключении на RU.
   Новые элементы, которые рисует приложение, подхватываются через MutationObserver.
   ============================================================ */
(function () {
  'use strict';

  var RU_RE = /[А-Яа-яЁё]/;

  // ---------- Точные соответствия ----------
  var DICT = {
    // Навигация и меню
    'Главная': 'Home', 'Поиск': 'Search', 'Очередь': 'Queue', 'История': 'History', 'Любимое': 'Liked',
    'Админ-панель': 'Admin panel', 'Панель администратора': 'Admin panel', 'Создать плейлист': 'Create playlist',
    'Библиотека': 'Library', 'Меню': 'Menu', 'Понравившаяся музыка': 'Liked music', 'Создан автоматически': 'Created automatically',
    'Недавно играли': 'Recently played', 'История прослушанного': 'Listening history', 'Сон': 'Sleep',
    'Свернуть / развернуть меню': 'Collapse / expand menu', 'Что нового': "What's new", 'Горячие клавиши': 'Keyboard shortcuts',
    'Горячие клавиши (?)': 'Keyboard shortcuts (?)', 'Эта подсказка': 'This help', 'Пробел': 'Space', 'Перемотка ±10 сек': 'Seek ±10 sec',
    'Таймер сна: нажмите, чтобы выбрать 15 / 30 / 60 минут': 'Sleep timer: click to choose 15 / 30 / 60 minutes',
    'Таймер сна': 'Sleep timer', 'Таймер сна выключен': 'Sleep timer off',
    'Таймер сна сработал — воспроизведение остановлено': 'Sleep timer finished — playback stopped',
    // Главная
    'Добрый вечер': 'Good evening', 'Добрый день': 'Good afternoon', 'Доброе утро': 'Good morning', 'Доброй ночи': 'Good night',
    'Что послушаем сегодня?': 'What shall we listen to today?', 'Пока пусто': 'Nothing yet', 'Новый плейлист': 'New playlist',
    'Собрать свой микс': 'Build your own mix', 'Треки и альбомы': 'Tracks and albums', 'Плейлисты пользователей': 'User playlists',
    'Сейчас слушают на серверах': 'Listening now on servers', 'Недавние прослушивания': 'Recent plays',
    'Хиты SoundCloud & YouTube': 'SoundCloud & YouTube hits', 'Рекомендуем': 'Recommended', 'Предстоящие треки': 'Up next',
    'Далее в очереди': 'Up next', 'Автоподбор': 'Autoplay', 'Очистить очередь': 'Clear queue', 'Очистить': 'Clear',
    'Очистить историю': 'Clear history', 'Очередь воспроизведения': 'Playback queue',
    'Очередь воспроизведения пуста. Включите автоподбор или добавьте треки кнопкой «+ В очередь».':
      'The queue is empty. Turn on autoplay or add tracks with the “+ Queue” button.',
    'Автоподбор похожего трека': 'Similar-track autoplay',
    'Включить / отключить умный автоподбор похожих треков': 'Turn smart similar-track autoplay on / off',
    'Перетащите для смены порядка': 'Drag to reorder', 'Удалить из очереди': 'Remove from queue',
    '✦ Похоже': '✦ Similar', '♥ По вкусу': '♥ For you', '● В эфире': '● On air', 'История воспроизведения пуста': 'Playback history is empty',
    // Источники
    'Все': 'All', 'Альбомы': 'Albums', 'Все треки и рекомендации': 'All tracks and recommendations',
    'Топ чарты YouTube Music': 'YouTube Music top charts', 'Топ чарты SoundCloud': 'SoundCloud top charts',
    'Лучшие альбомы YouTube Music и SoundCloud': 'Best albums on YouTube Music and SoundCloud',
    'Audius — независимые артисты, полные треки': 'Audius — independent artists, full tracks',
    'Mixcloud — DJ-сеты и радиошоу': 'Mixcloud — DJ sets and radio shows',
    'Internet Archive — лайвы, нетлейблы, архивные записи': 'Internet Archive — live recordings, netlabels, archival audio',
    // Шапка
    'Где сейчас используется бот': 'Where the bot is used right now', 'Не подключен': 'Not connected',
    'Текущая голосовая комната и слушатели': 'Current voice room and listeners', 'Слушатели в комнате:': 'Listeners in the room:',
    'Сменить язык / Switch language': 'Switch language', 'Тема оформления visionOS': 'visionOS theme',
    'Ваш профиль Discord (нажмите для меню)': 'Your Discord profile (click for menu)', 'Выйти из профиля': 'Sign out',
    'Обновить статус': 'Refresh status', 'Голосовой канал': 'Voice channel', 'Вход через Discord': 'Sign in with Discord',
    'Войти через Discord': 'Sign in with Discord', 'Продолжить как гость (без сохранения)': 'Continue as guest (not saved)',
    'Вход...': 'Signing in...', 'Пользователь Discord': 'Discord user', 'Не авторизован': 'Not signed in',
    'Поиск треков, альбомов, исполнителей...': 'Search tracks, albums, artists...', 'Искать': 'Search', 'Найти': 'Search',
    'Результаты поиска': 'Search results', '0 найдено': '0 found', 'Ничего не найдено': 'Nothing found',
    'Ищем лучшую музыку на всех источниках...': 'Searching the best music across all sources...',
    // Плеер
    'Трек не выбран': 'No track selected', 'Выберите песню для воспроизведения': 'Pick a song to play',
    'Ничего не играет': 'Nothing is playing', 'Сейчас ничего не играет': 'Nothing is playing right now',
    'Выберите трек': 'Pick a track', 'Выберите трек, чтобы увидеть действия': 'Pick a track to see actions',
    'Воспроизведение': 'Playback', 'Воспроизведение / Пауза (Пробел)': 'Play / Pause (Space)', 'Пауза / воспроизведение': 'Play / pause',
    'Пауза': 'Pause', 'Играть': 'Play', 'Нравится': 'Like', 'Перемешать': 'Shuffle', 'Перемешать очередь': 'Shuffle queue',
    'Повтор': 'Repeat', 'Перемотка': 'Seek', 'Громкость': 'Volume', 'Выключить звук': 'Mute', 'Текущий трек': 'Current track',
    'Предыдущий': 'Previous', 'Следующий': 'Next', 'Предыдущий трек': 'Previous track', 'Следующий трек': 'Next track',
    'Предыдущий трек (←)': 'Previous track (←)', 'Следующий трек (→)': 'Next track (→)', 'Назад': 'Back', 'Вперед': 'Forward',
    'Текст песни': 'Lyrics', 'Текст песни и караоке (visionOS)': 'Lyrics & karaoke', 'Закрыть': 'Close',
    'Добавить в плейлист': 'Add to playlist', 'Добавить в плейлист / Действия': 'Add to playlist / Actions',
    'Копировать ссылку': 'Copy link', 'Копировать название': 'Copy title', 'Открыть в источнике': 'Open in source',
    'Ссылка скопирована': 'Link copied', 'Название скопировано': 'Title copied', 'Не удалось скопировать': 'Could not copy',
    'Загрузка плеера…': 'Loading player…', 'Подключение к Discord…': 'Connecting to Discord…', 'Подключение…': 'Connecting…',
    'Почти готово…': 'Almost ready…', 'Загрузка…': 'Loading…',
    // Караоке
    'Синхронно': 'Synced', 'Синхронизация текста песни...': 'Syncing lyrics...',
    'Текст для этого трека пока не найден.': 'Lyrics for this track were not found yet.',
    'Нажмите на строку — перемотка': 'Click a line to seek', 'Нажмите на любую строку для мгновенной перемотки': 'Click any line to seek',
    // Журнал обновлений
    'Записей пока нет.': 'No entries yet.', 'Новое': 'New',
    // Плейлисты и модалки
    'Выберите плейлист:': 'Choose a playlist:', 'Создать новый плейлист': 'Create a new playlist', 'Создать': 'Create',
    'Создать и добавить': 'Create and add', 'Название плейлиста': 'Playlist name', 'Название нового плейлиста': 'New playlist name',
    'Например: GTA 5, Драйв, Мой микс...': 'e.g. GTA 5, Drive, My mix...', 'Например: Мой микс...': 'e.g. My mix...',
    'Мой плейлист': 'My playlist', 'Пользовательский плейлист': 'User playlist', 'Создать свой плейлист': 'Create your own playlist',
    'Удалить плейлист': 'Delete playlist', 'Удалить': 'Delete', 'Подтвердить': 'Confirm', 'Подтверждение': 'Confirmation',
    'Вы уверены?': 'Are you sure?', 'Готово': 'Done', 'Включить всё': 'Play all', 'Слушать': 'Listen', 'Слушать трек': 'Play track',
    'Слушать альбом': 'Play album', 'Слушать плейлист': 'Play playlist', 'Слушать все': 'Play all', 'Слушать первый альбом': 'Play first album',
    'Добавить в очередь': 'Add to queue', 'Включить этот трек': 'Play this track', '+ Добавить': '+ Add',
    'Удалить из плейлиста': 'Remove from playlist', 'Удалить из понравившихся': 'Remove from liked', 'Убрать отметку': 'Unlike',
    'В этом плейлисте пока нет треков': 'There are no tracks in this playlist yet', 'Введите название плейлиста': 'Enter a playlist name',
    'Войдите через Discord, чтобы ставить лайки': 'Sign in with Discord to like tracks', 'Вы вошли как гость': 'You are signed in as a guest',
    'История прослушивания очищена': 'Listening history cleared', 'История прослушивания уже пуста': 'Listening history is already empty',
    'Вы вышли из профиля': 'You signed out', 'Неизвестный исполнитель': 'Unknown artist', 'Без названия': 'Untitled',
    'Нравится плейлист': 'Like playlist', 'Бот не подключен к голосовой комнате': 'The bot is not connected to a voice room',
    'Подгрузить ещё из SoundCloud': 'Load more from SoundCloud', 'Не удалось подгрузить треки SoundCloud': 'Could not load SoundCloud tracks',
    'Все доступные рекомендации SoundCloud загружены': 'All available SoundCloud recommendations are loaded',
    'В тренде': 'Trending', 'Официальный топ': 'Official top', 'Коллекция': 'Collection', 'Лучшие альбомы': 'Best albums',
    'Топ-чарты YouTube Music': 'YouTube Music top charts', 'Топ-чарты & Рекомендации SoundCloud': 'SoundCloud top charts & recommendations',
    'Включить топ-чарт': 'Play top chart', 'Все / В тренде': 'All / Trending', 'Discord Сервер': 'Discord server',
    'Голосовой': 'Voice', 'Слушателей в канале': 'Listeners in the channel', 'Вы': 'You',
    'Хаус & Клубная': 'House & Club', 'Хип-Хоп / Рэп': 'Hip-Hop / Rap', 'Электроника & EDM': 'Electronic & EDM',
    'Драм-н-бейс & Фонк': 'Drum & Bass & Phonk', 'Отметка «Нравится» снята': 'Like removed',
    // Подвал и прочее
    'Условия использования': 'Terms of Use', 'Политика конфиденциальности': 'Privacy Policy', 'Тех.поддержка': 'Support',
    'Музыка для вашего Discord-сервера': 'Music for your Discord server', 'Музыка остановится через ': 'Music will stop in ',
    'по обложке': 'by cover', 'Отмена': 'Cancel', 'Перейти в поиск': 'Go to search', 'На главную': 'Home', 'Русский': 'Russian',
    'Пока нет плейлистов сообщества. Создайте первый плейлист!': 'No community playlists yet. Create the first one!',
    'Здесь появятся недавние треки, которые слушают пользователи нашего бота.': 'Recent tracks played by our bot2019s users will appear here.',
    ' мин': ' min', 'играет на ': 'playing on ', 'Автоплейлист': 'Autoplaylist', 'Панель администратора ': 'Admin panel '
  };

  // ---------- Шаблоны с числами и именами ----------
  function plural(n, one, many) { return n === 1 ? one : many; }
  var PATTERNS = [
    [/^(\d+) трек(?:а|ов)?$/, function (m) { var n = +m[1]; return n + ' ' + plural(n, 'track', 'tracks'); }],
    [/^(\d+) шт\.$/, function (m) { return m[1] + ' pcs'; }],
    [/^(\d+) в очереди$/, function (m) { return m[1] + ' in queue'; }],
    [/^(\d+) ручн\. • (\d+) авто$/, function (m) { return m[1] + ' manual • ' + m[2] + ' auto'; }],
    [/^(.+), что послушаем\?$/, function (m) { return m[1] + ', what shall we listen to?'; }],
    [/^(\d+) сервер(?:а|ов)?$/, function (m) { var n = +m[1]; return n + ' ' + plural(n, 'server', 'servers'); }],
    [/^играет на (\d+)$/, function (m) { return 'playing on ' + m[1]; }],
    [/^(\d+) слушател(?:ь|я|ей)$/, function (m) { var n = +m[1]; return n + ' ' + plural(n, 'listener', 'listeners'); }],
    [/^Музыка остановится через (\d+) мин$/, function (m) { return 'Music will stop in ' + m[1] + ' min'; }],
    [/^(\d+) в очереди • /, null],
    [/^Вы авторизованы как (.+?)!?$/, function (m) { return 'You are signed in as ' + m[1]; }],
    [/^Введите запрос — поиск пойдёт по (.+)$/, function (m) { return 'Type a query — search will use ' + m[1]; }],
    [/^Включаем топ-чарт (.+) \((\d+) треков\)$/, function (m) { return 'Playing the ' + m[1] + ' top chart (' + m[2] + ' tracks)'; }],
    [/^Подгружено \+(\d+) треков из SoundCloud$/, function (m) { return 'Loaded +' + m[1] + ' tracks from SoundCloud'; }],
    [/^Воспроизведение плейлиста «(.+)» \((\d+) треков\)$/, function (m) { return 'Playing playlist «' + m[1] + '» (' + m[2] + ' tracks)'; }],
    [/^Воспроизведение понравившихся треков \((\d+) шт\.\)$/, function (m) { return 'Playing liked tracks (' + m[1] + ')'; }],
    [/^Плейлист «(.+)» добавлен в понравившиеся!$/, function (m) { return 'Playlist «' + m[1] + '» added to liked!'; }],
    [/^Перейти к (.+)$/, function (m) { return 'Jump to ' + m[1]; }],
    [/^Музыка остановится через (.+)$/, function (m) { return 'Music will stop in ' + m[1]; }]
  ].filter(function (p) { return p[1]; });

  function translate(raw) {
    var s = raw.trim();
    if (!s || !RU_RE.test(s)) return null;
    if (DICT[s] !== undefined) return DICT[s];
    // составные подписи вида «8 серверов · играет на 1 · 1 слушатель»
    if (s.indexOf(' · ') > -1) {
      var parts = s.split(' · '), out = [], ok = true;
      for (var i = 0; i < parts.length; i++) {
        var t = translate(parts[i]);
        if (t === null) { ok = false; break; }
        out.push(t);
      }
      if (ok) return out.join(' · ');
    }
    for (var j = 0; j < PATTERNS.length; j++) {
      var m = PATTERNS[j][0].exec(s);
      if (m) return PATTERNS[j][1](m);
    }
    return null;
  }

  // ---------- Применение к DOM ----------
  var ATTRS = ['title', 'placeholder', 'aria-label'];
  var textOrig = new WeakMap();   // text node -> { ru, en }
  var attrOrig = new WeakMap();   // element -> { attr: { ru, en } }
  var busy = false;

  function isEn() { return document.documentElement.getAttribute('data-lang') === 'en'; }

  function skipNode(node) {
    var p = node.parentElement;
    if (!p) return true;
    var tag = p.tagName;
    if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TEXTAREA') return true;
    return !!(p.closest && p.closest('.lang-ru, .lang-en, [data-no-i18n]'));
  }

  function applyText(node, en) {
    var rec = textOrig.get(node);
    if (en) {
      if (rec && node.data === rec.en) return;           // уже переведено
      var tr = translate(node.data);
      if (tr === null) return;
      var lead = node.data.match(/^\s*/)[0], trail = node.data.match(/\s*$/)[0];
      var ru = node.data;
      var enText = lead + tr + trail;
      textOrig.set(node, { ru: ru, en: enText });
      node.data = enText;
    } else if (rec && node.data === rec.en) {
      node.data = rec.ru;
      textOrig.delete(node);
    }
  }

  function applyAttrs(elem, en) {
    var store = attrOrig.get(elem);
    for (var i = 0; i < ATTRS.length; i++) {
      var a = ATTRS[i];
      if (!elem.hasAttribute(a)) continue;
      var val = elem.getAttribute(a);
      var rec = store && store[a];
      if (en) {
        if (rec && val === rec.en) continue;
        var tr = translate(val);
        if (tr === null) continue;
        if (!store) { store = {}; attrOrig.set(elem, store); }
        store[a] = { ru: val, en: tr };
        elem.setAttribute(a, tr);
      } else if (rec && val === rec.en) {
        elem.setAttribute(a, rec.ru);
        delete store[a];
      }
    }
  }

  function walk(root, en) {
    if (!root) return;
    if (root.nodeType === 3) { if (!skipNode(root)) applyText(root, en); return; }
    if (root.nodeType !== 1) return;
    if (root.closest && root.closest('.lang-ru, .lang-en, [data-no-i18n]')) return;
    var tag = root.tagName;
    if (tag === 'SCRIPT' || tag === 'STYLE') return;
    applyAttrs(root, en);
    var tw = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, null);
    var n = tw.nextNode();
    while (n) {
      if (n.nodeType === 3) { if (!skipNode(n)) applyText(n, en); }
      else if (n.nodeType === 1 && n.tagName !== 'SCRIPT' && n.tagName !== 'STYLE') applyAttrs(n, en);
      n = tw.nextNode();
    }
  }

  var queued = false;
  var pending = new Set();
  function flush() {
    queued = false;
    var en = isEn();
    busy = true;
    try {
      if (pending.has(document.body)) walk(document.body, en);
      else pending.forEach(function (node) { if (node.isConnected !== false) walk(node, en); });
    } finally { busy = false; pending.clear(); }
  }
  function schedule(node) {
    pending.add(node);
    if (!queued) { queued = true; setTimeout(flush, 30); }
  }

  function start() {
    schedule(document.body);
    new MutationObserver(function (muts) {
      if (busy) return;
      for (var i = 0; i < muts.length; i++) {
        var m = muts[i];
        if (m.type === 'childList') m.addedNodes.forEach(function (n) { schedule(n.nodeType === 1 || n.nodeType === 3 ? n : document.body); });
        else if (m.type === 'characterData') schedule(m.target);
        else if (m.type === 'attributes') schedule(m.target);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });

    // Переключение языка: перерисовываем всю страницу заново
    new MutationObserver(function () { schedule(document.body); })
      .observe(document.documentElement, { attributes: true, attributeFilter: ['data-lang'] });
  }

  window.musiciumTranslate = function (s) { return isEn() ? (translate(s) || s) : s; };

  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
