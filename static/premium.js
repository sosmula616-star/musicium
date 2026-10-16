/**
 * Musicium premium UI helpers: splash screen, login animation, liquid-glass refraction.
 * Не зависит от app.js — только оформление.
 */
(function () {
  'use strict';

  var root = document.documentElement;

  // ---------- 1. Liquid-glass refraction (Chromium only) ----------
  function supportsRefraction() {
    var ua = navigator.userAgent || '';
    var isChromium = /Chrome\/|Chromium\//.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    return isChromium && !reduce;
  }

  if (supportsRefraction()) {
    var svgNS = 'http://www.w3.org/2000/svg';
    var holder = document.createElement('div');
    holder.setAttribute('aria-hidden', 'true');
    holder.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;pointer-events:none;';
    holder.innerHTML =
      '<svg xmlns="' + svgNS + '" width="0" height="0"><defs>' +
      '<filter id="lgRefract" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.006 0.010" numOctaves="2" seed="11" result="noise"/>' +
      '<feGaussianBlur in="noise" stdDeviation="2.2" result="soft"/>' +
      '<feDisplacementMap in="SourceGraphic" in2="soft" scale="22" xChannelSelector="R" yChannelSelector="G"/>' +
      '</filter></defs></svg>';
    document.body.appendChild(holder);
    root.classList.add('lg-refract');
  }

  // ---------- 2. Splash screen ----------
  var splash = document.getElementById('appSplash');
  var hint = document.getElementById('splashHint');
  var startedAt = Date.now();
  var MIN_VISIBLE = 1500;
  var MAX_VISIBLE = 6000;
  var hidden = false;

  function setHint(text) {
    if (hint) hint.textContent = text;
  }

  function hideSplash() {
    if (hidden || !splash) return;
    hidden = true;
    var wait = Math.max(0, MIN_VISIBLE - (Date.now() - startedAt));
    setTimeout(function () {
      splash.classList.add('is-done');
      root.classList.add('splash-done');
      setTimeout(function () { if (splash && splash.parentNode) splash.parentNode.removeChild(splash); }, 1000);
    }, wait);
  }

  if (splash) {
    var steps = [
      [350, 'Подключение…'],
      [1100, 'Загрузка плеера…'],
      [2100, 'Почти готово…']
    ];
    steps.forEach(function (s) { setTimeout(function () { if (!hidden) setHint(s[1]); }, s[0]); });

    var ready = function () {
      // даём app.js отрисовать первый экран
      setTimeout(hideSplash, 250);
    };
    if (document.readyState === 'complete') ready();
    else window.addEventListener('load', ready, { once: true });

    setTimeout(hideSplash, MAX_VISIBLE);
  }

  // ---------- 3. Login button loading state ----------
  var loginBtn = document.getElementById('btnDiscordLoginAction');
  if (loginBtn) {
    var label = loginBtn.querySelector('span');
    var original = label ? label.textContent : '';
    loginBtn.addEventListener('click', function () {
      loginBtn.classList.add('is-loading');
      if (label) label.textContent = 'Подключение к Discord…';
      setTimeout(function () {
        loginBtn.classList.remove('is-loading');
        if (label) label.textContent = original;
      }, 8000);
    });
  }
})();

/* ============================================================
   V8: левое меню, главная, горячие клавиши, анимации
   ============================================================ */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var root = document.documentElement;
  function toast(msg, type, icon) {
    if (typeof window.showToast === 'function') window.showToast(msg, type || 'info', icon || null);
  }
  function store() { return window.playerStore || null; }

  // ---------- 1. Плавающий индикатор активного пункта ----------
  var nav = document.querySelector('.ytm-nav');
  var indicator = $('sbIndicator');
  function moveIndicator() {
    if (!nav || !indicator) return;
    var active = nav.querySelector('.ytm-nav-item.active');
    if (!active || active.offsetParent === null) { indicator.classList.remove('ready'); return; }
    indicator.style.width = active.offsetWidth + 'px';
    indicator.style.height = active.offsetHeight + 'px';
    indicator.style.transform = 'translate(' + active.offsetLeft + 'px,' + active.offsetTop + 'px)';
    indicator.classList.add('ready');
  }
  if (nav && indicator) {
    new MutationObserver(function (list) {
      if (list.some(function (m) { return m.target !== indicator; })) moveIndicator();
    }).observe(nav, { attributes: true, subtree: true, attributeFilter: ['class'] });
    window.addEventListener('resize', moveIndicator);
    [200, 800, 1800].forEach(function (t) { setTimeout(moveIndicator, t); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(moveIndicator);
  }

  // ---------- 2. Сворачивание меню ----------
  var collapseBtn = $('sbCollapseBtn');
  try { if (localStorage.getItem('musicium_sb_collapsed') === '1') root.classList.add('sb-collapsed'); } catch (_) {}
  if (collapseBtn) {
    collapseBtn.addEventListener('click', function () {
      var on = root.classList.toggle('sb-collapsed');
      try { localStorage.setItem('musicium_sb_collapsed', on ? '1' : '0'); } catch (_) {}
      setTimeout(moveIndicator, 480);
    });
  }

  // ---------- 3. Мини-плеер в меню ----------
  var nowBox = $('sbNow');
  function syncNow(s) {
    if (!nowBox || !s) return;
    var t = s.current;
    $('sbNowTitle').textContent = t ? t.title : 'Ничего не играет';
    $('sbNowArtist').textContent = t ? t.artist : 'Выберите трек';
    var art = $('sbNowArt');
    var src = t && t.thumbnail ? t.thumbnail : '/static/activity_icon.jpg';
    if (art && art.getAttribute('data-src') !== src) {
      art.setAttribute('data-src', src);
      art.src = (typeof window.getSafeImageUrl === 'function') ? window.getSafeImageUrl(src) : src;
      art.onerror = function () { art.onerror = null; art.src = '/static/activity_icon.jpg'; };
    }
    nowBox.classList.toggle('is-playing', !!s.isPlaying);
    root.classList.toggle('is-playing', !!s.isPlaying && !!t);
    $('sbNowIcon').innerHTML = s.isPlaying
      ? '<path d="M6 5h4v14H6zm8 0h4v14h-4z"/>'
      : '<path d="M8 5v14l11-7z"/>';
    var pct = s.duration > 0 ? Math.min(100, Math.max(0, (s.elapsed / s.duration) * 100)) : 0;
    $('sbNowFill').style.width = pct + '%';
  }
  (function bindStore() {
    var st = store();
    if (st && typeof st.subscribe === 'function') st.subscribe(syncNow);
    else setTimeout(bindStore, 300);
  })();
  var toggleBtn = $('sbNowToggle');
  if (toggleBtn) toggleBtn.addEventListener('click', function () {
    var main = $('btnPlayPause');
    if (main) main.click();
  });

  // ---------- 4. Таймер сна ----------
  var sleepBtn = $('sbSleepBtn');
  var sleepLabel = $('sbSleepLabel');
  var SLEEP_STEPS = [0, 15, 30, 60];
  var sleepIdx = 0;
  var sleepEnd = 0;
  var sleepTimer = null;
  function renderSleep() {
    if (!sleepBtn) return;
    if (!sleepEnd) {
      sleepBtn.classList.remove('is-on');
      sleepLabel.textContent = 'Сон';
      return;
    }
    var left = Math.max(0, Math.round((sleepEnd - Date.now()) / 1000));
    var m = Math.floor(left / 60), s = left % 60;
    sleepBtn.classList.add('is-on');
    sleepLabel.textContent = m + ':' + (s < 10 ? '0' : '') + s;
  }
  function stopSleep() { clearInterval(sleepTimer); sleepTimer = null; sleepEnd = 0; renderSleep(); }
  function tickSleep() {
    if (Date.now() >= sleepEnd) {
      stopSleep(); sleepIdx = 0;
      var st = store();
      if (st && st.isPlaying && typeof st.pause === 'function') st.pause();
      toast('Таймер сна сработал — воспроизведение остановлено', 'info');
      return;
    }
    renderSleep();
  }
  if (sleepBtn) sleepBtn.addEventListener('click', function () {
    sleepIdx = (sleepIdx + 1) % SLEEP_STEPS.length;
    var minutes = SLEEP_STEPS[sleepIdx];
    clearInterval(sleepTimer);
    if (!minutes) { stopSleep(); toast('Таймер сна выключен', 'info'); return; }
    sleepEnd = Date.now() + minutes * 60000;
    sleepTimer = setInterval(tickSleep, 1000);
    renderSleep();
    toast('Музыка остановится через ' + minutes + ' мин', 'success');
  });

  // ---------- 5. Горячие клавиши ----------
  var keysModal = $('shortcutsModal');
  function openKeys() { if (keysModal) keysModal.style.display = 'flex'; }
  function closeKeys() { if (keysModal) keysModal.style.display = 'none'; }
  var keysBtn = $('sbKeysBtn');
  if (keysBtn) keysBtn.addEventListener('click', openKeys);
  var closeKeysBtn = $('closeShortcutsBtn');
  if (closeKeysBtn) closeKeysBtn.addEventListener('click', closeKeys);
  if (keysModal) keysModal.addEventListener('click', function (e) { if (e.target === keysModal) closeKeys(); });

  document.addEventListener('keydown', function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    var tag = (e.target.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target.isContentEditable) return;
    var k = e.key;
    if (k === 'Escape') { closeKeys(); return; }
    if (k === '?') { e.preventDefault(); openKeys(); }
    else if (k === '/') { e.preventDefault(); var n = $('navSearch'); if (n) n.click(); var i = $('searchInput'); if (i) i.focus(); }
    else if (k === 'm' || k === 'M' || k === 'ь' || k === 'Ь') { var mb = $('btnMute'); if (mb) mb.click(); }
    else if (k === 'l' || k === 'L' || k === 'д' || k === 'Д') { var lb = $('btnDockLyrics'); if (lb) lb.click(); }
    else if (k === 'h' || k === 'H' || k === 'р' || k === 'Р') { var hb = $('navHome'); if (hb) hb.click(); }
  });

  // ---------- 6. Главная: приветствие и плитки ----------
  var dash = $('homeDash');
  function greeting() {
    var h = new Date().getHours();
    if (h >= 5 && h < 12) return 'Доброе утро';
    if (h >= 12 && h < 18) return 'Добрый день';
    if (h >= 18 && h < 23) return 'Добрый вечер';
    return 'Доброй ночи';
  }
  function plural(n, a, b, c) {
    n = Math.abs(n) % 100; var d = n % 10;
    if (n > 10 && n < 20) return c;
    if (d > 1 && d < 5) return b;
    return d === 1 ? a : c;
  }
  function refreshDash() {
    if (!dash) return;
    var nameEl = $('userName');
    var name = nameEl ? nameEl.textContent.trim() : '';
    var bad = !name || /вход|login|польз/i.test(name);
    $('homeKicker').textContent = greeting();
    $('homeTitle').textContent = bad ? 'Что послушаем сегодня?' : name + ', что послушаем?';

    var liked = parseInt(($('likedCountText') || {}).textContent, 10) || 0;
    var hist = parseInt(($('historyCountText') || {}).textContent, 10) || 0;
    var q = parseInt(($('sidebarQueueCount') || {}).textContent, 10) || 0;
    $('tileLikedCount').textContent = liked + ' ' + plural(liked, 'трек', 'трека', 'треков');
    $('tileHistoryCount').textContent = hist + ' ' + plural(hist, 'трек', 'трека', 'треков');
    $('tileQueueCount').textContent = q ? (q + ' в очереди') : 'Пока пусто';

    // Показываем только на вкладке «Все»
    var chipAll = $('chipAll');
    var onAll = !chipAll || chipAll.classList.contains('active');
    dash.classList.toggle('is-hidden', !onAll);
  }
  if (dash) {
    dash.addEventListener('click', function (e) {
      var tile = e.target.closest('.home-tile');
      if (!tile) return;
      var target = $(tile.getAttribute('data-go'));
      if (target) target.click();
    });
    refreshDash();
    setInterval(refreshDash, 1500);
    var chips = $('categoryChipsBar');
    if (chips) new MutationObserver(refreshDash).observe(chips, { attributes: true, subtree: true, attributeFilter: ['class'] });
  }

  // ---------- 7. Появление карточек при прокрутке ----------
  if ('IntersectionObserver' in window && !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches)) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('rv-in'); io.unobserve(en.target); }
      });
    }, { rootMargin: '0px 0px -6% 0px', threshold: 0.05 });

    var SEL = '.home-tile, .live-card, .recent-card, .community-card, .square-card, .album-card, .chart-track-card, .track-card';
    function mark(scope) {
      var list = (scope || document).querySelectorAll(SEL);
      list.forEach(function (n) {
        if (n.__rv) return;
        n.__rv = true;
        var idx = 0, p = n.previousElementSibling;
        while (p && idx < 8) { idx++; p = p.previousElementSibling; }
        n.style.setProperty('--rv-i', Math.min(idx, 8));
        n.classList.add('rv');
        io.observe(n);
      });
    }
    var area = $('ytmContentArea') || document.body;
    mark(area);
    var pending = false;
    new MutationObserver(function () {
      if (pending) return;
      pending = true;
      requestAnimationFrame(function () { pending = false; mark(area); });
    }).observe(area, { childList: true, subtree: true });
  }
})();

/* ============================================================
   V11: плеер — подсказка времени, плавная смена трека, загрузка
   ============================================================ */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var dock = $('playerDock');
  var pill = $('capsuleCenterPill');
  var sbNow = $('sbNow');
  var title = $('dockTitle');

  function fmt(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    var m = Math.floor(sec / 60), s = sec % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  // ---------- 1. Подсказка времени при наведении на полосу ----------
  var track = $('progressTrack');
  var tip = $('progressTip');
  if (track && tip) {
    track.addEventListener('mousemove', function (e) {
      var st = window.playerStore;
      var dur = st && st.duration ? st.duration : 0;
      var r = track.getBoundingClientRect();
      var x = Math.min(Math.max(e.clientX - r.left, 0), r.width);
      tip.style.left = x + 'px';
      tip.textContent = dur ? fmt((x / r.width) * dur) : '—';
      track.classList.add('is-hover');
    });
    track.addEventListener('mouseleave', function () { track.classList.remove('is-hover'); });
  }

  // ---------- 2. Плавная смена трека ----------
  function swapAnim() {
    [pill, sbNow].forEach(function (n) {
      if (!n) return;
      n.classList.remove('track-swap');
      void n.offsetWidth; // перезапуск анимации
      n.classList.add('track-swap');
    });
  }
  if (title) {
    var last = title.textContent;
    new MutationObserver(function () {
      var now = title.textContent;
      if (now !== last) { last = now; swapAnim(); }
    }).observe(title, { childList: true, characterData: true, subtree: true });
  }

  // ---------- 3. Состояние «загрузка трека» и «ничего не играет» ----------
  var loadTimer = null;
  window.addEventListener('musicium:play-request', function (e) {
    var d = e.detail || {};
    if (!dock) return;
    if (d.phase === 'start') {
      if (d.silent && !d.playNow) return; // фоновая подгрузка автоподбора не мигает
      dock.classList.add('is-loading');
      clearTimeout(loadTimer);
      loadTimer = setTimeout(function () { dock.classList.remove('is-loading'); }, 40000);
    } else {
      // обновление плеера придёт следом; даём ему отрисоваться
      setTimeout(function () { dock.classList.remove('is-loading'); }, 600);
    }
  });
  function syncIdle() {
    if (!dock) return;
    var st = window.playerStore;
    dock.classList.toggle('is-idle', !(st && st.current));
  }
  (function bind() {
    var st = window.playerStore;
    if (st && st.subscribe) st.subscribe(function (s) {
      syncIdle();
      if (s.current && dock) dock.classList.remove('is-loading');
    });
    else setTimeout(bind, 300);
  })();

  // ---------- 4. Перемотка ±10 секунд: Shift + ← / → ----------
  document.addEventListener('keydown', function (e) {
    if (!e.shiftKey || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return;
    var tag = (e.target.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target.isContentEditable) return;
    var st = window.playerStore;
    if (!st || !st.current) return;
    e.preventDefault();
    e.stopImmediatePropagation(); // не даём player_store выполнить next()/prev()
    var delta = e.key === 'ArrowRight' ? 10 : -10;
    st.seek(Math.max(0, (st.elapsed || 0) + delta));
  }, true);
})();

/* ============================================================
   V12: меню действий трека и красивые плейсхолдеры обложек
   ============================================================ */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  function toast(msg, type) { if (typeof window.showToast === 'function') window.showToast(msg, type || 'info'); }

  // ---------- 1. Меню «•••» ----------
  var moreBtn = $('btnAddToPlCurrent');
  var menu = null;
  var bypass = false;

  var ICONS = {
    plus: '<path d="M14 10H2v2h12v-2zm0-4H2v2h12V6zm4 8v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zM2 16h8v-2H2v2z"/>',
    link: '<path d="M3.9 12a3.1 3.1 0 0 1 3.1-3.1h4V7H7a5 5 0 0 0 0 10h4v-1.9H7A3.1 3.1 0 0 1 3.9 12zM8 13h8v-2H8v2zm9-6h-4v1.9h4a3.1 3.1 0 0 1 0 6.2h-4V17h4a5 5 0 0 0 0-10z"/>',
    open: '<path d="M19 19H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/>',
    text: '<path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM6 9h12v2H6V9zm8 5H6v-2h8v2zm4-6H6V6h12v2z"/>',
    copy: '<path d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11v14z"/>',
    moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'
  };
  function item(key, label, id, disabled) {
    return '<button type="button" data-act="' + id + '"' + (disabled ? ' disabled' : '') +
      '><svg viewBox="0 0 24 24" fill="currentColor">' + ICONS[key] + '</svg><span>' + label + '</span></button>';
  }
  function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  function closeMenu() { if (menu) { menu.remove(); menu = null; } }

  function openMenu() {
    closeMenu();
    var st = window.playerStore;
    var cur = st && st.current;
    menu = document.createElement('div');
    menu.className = 'track-menu';
    menu.innerHTML =
      '<div class="track-menu-head"><b>' + esc(cur ? cur.title : 'Ничего не играет') + '</b><span>' + esc(cur ? cur.artist : 'Выберите трек, чтобы увидеть действия') + '</span></div>' +
      item('plus', 'Добавить в плейлист', 'playlist', !cur) +
      item('link', 'Копировать ссылку', 'copylink', !cur || !cur.url) +
      item('copy', 'Копировать название', 'copytitle', !cur) +
      item('open', 'Открыть в источнике', 'open', !cur || !cur.url) +
      item('text', 'Текст песни', 'lyrics', !cur) +
      item('moon', 'Таймер сна', 'sleep', false);
    document.body.appendChild(menu);
    var r = moreBtn.getBoundingClientRect();
    var w = menu.offsetWidth, h = menu.offsetHeight;
    var left = Math.min(Math.max(8, r.right - w), window.innerWidth - w - 8);
    var top = Math.max(8, r.top - h - 12);
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
  }

  function run(act) {
    var st = window.playerStore;
    var cur = st && st.current;
    if (act === 'playlist') { bypass = true; moreBtn.click(); bypass = false; }
    else if (act === 'copylink' && cur && cur.url) copy(cur.url, 'Ссылка скопирована');
    else if (act === 'copytitle' && cur) copy(cur.artist + ' — ' + cur.title, 'Название скопировано');
    else if (act === 'open' && cur && cur.url) openUrl(cur.url);
    else if (act === 'lyrics') { var l = $('btnDockLyrics'); if (l) l.click(); }
    else if (act === 'sleep') { var s = $('sbSleepBtn'); if (s) s.click(); }
  }
  function copy(text, okMsg) {
    var done = function () { toast(okMsg, 'success'); };
    // в iframe (Discord Activity) Clipboard API часто запрещён — запасной путь через execCommand
    var legacy = function () {
      try {
        var ta = document.createElement('textarea');
        ta.value = text; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;top:-100px;opacity:0';
        document.body.appendChild(ta); ta.select();
        var ok = document.execCommand('copy');
        ta.remove();
        if (ok) done(); else toast('Не удалось скопировать', 'error');
      } catch (_) { toast('Не удалось скопировать', 'error'); }
    };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, legacy);
    else legacy();
  }
  function openUrl(url) {
    var a = document.createElement('a');
    a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    document.body.appendChild(a); a.click(); a.remove();
  }

  if (moreBtn) {
    // перехватываем клик раньше старого обработчика (он только открывал «в плейлист»)
    moreBtn.addEventListener('click', function (e) {
      if (bypass) return;
      e.stopImmediatePropagation();
      e.preventDefault();
      if (menu) closeMenu(); else openMenu();
    }, true);
    document.addEventListener('click', function (e) {
      if (!menu) return;
      var b = e.target.closest && e.target.closest('.track-menu button');
      if (b) { var act = b.getAttribute('data-act'); closeMenu(); run(act); return; }
      if (!menu.contains(e.target) && e.target !== moreBtn) closeMenu();
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMenu(); });
    window.addEventListener('resize', closeMenu);
  }

  // ---------- 2. Плейсхолдеры обложек вместо логотипа ----------
  function hash(str) {
    var h = 0;
    for (var i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
    return Math.abs(h);
  }
  function placeholder(title) {
    var t = (title || 'Musicium').trim();
    var h = hash(t) % 360;
    var words = t.replace(/[^\p{L}\p{N} ]/gu, '').split(/\s+/).filter(Boolean);
    var letters = ((words[0] || '♪')[0] + (words[1] ? words[1][0] : '')).toUpperCase();
    var svg =
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">' +
      '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">' +
      '<stop offset="0" stop-color="hsl(' + h + ',48%,42%)"/><stop offset="1" stop-color="hsl(' + ((h + 50) % 360) + ',52%,16%)"/></linearGradient>' +
      '<radialGradient id="s" cx="0.2" cy="0.1" r="0.9"><stop offset="0" stop-color="#fff" stop-opacity="0.35"/><stop offset="0.6" stop-color="#fff" stop-opacity="0"/></radialGradient></defs>' +
      '<rect width="200" height="200" fill="url(#g)"/><rect width="200" height="200" fill="url(#s)"/>' +
      '<circle cx="100" cy="100" r="62" fill="none" stroke="#fff" stroke-opacity="0.14" stroke-width="2"/>' +
      '<circle cx="100" cy="100" r="30" fill="none" stroke="#fff" stroke-opacity="0.10" stroke-width="2"/>' +
      '<text x="100" y="118" text-anchor="middle" font-family="Outfit,Inter,sans-serif" font-size="56" font-weight="600" fill="#fff" fill-opacity="0.92">' +
      esc(letters) + '</text></svg>';
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }

  // ---------- 2b. Не загрузилась обложка → ищем на другой площадке (iTunes / Deezer) ----------
  var coverCache = {};
  function setCover(im, url) {
    im.src = url;
    var wrap = im.closest('.coverflow-thumb-wrap');
    if (wrap) wrap.style.setProperty('--cover', "url('" + url + "')");
  }
  function isCoverImg(im) { return /thumb|cover|art|poster/i.test(im.className || '') || !!im.closest(CARD_SEL); }
  // Название/исполнитель трека для поиска обложки: из data-атрибутов, alt или текста соседней строки
  function trackInfoFor(im) {
    var title = im.dataset.t || im.alt;
    var artist = im.dataset.a || '';
    if (!title) {
      var row = im.closest('.queue-item, .chart-item, .history-item, .track-card, .compact-card, .square-card, .recent-card, .live-card, li, tr, [class*="item"], [class*="row"]');
      var tEl = row && row.querySelector('[class*="title"]');
      var aEl = row && row.querySelector('[class*="artist"], [class*="author"], [class*="sub"]');
      title = tEl ? tEl.textContent.trim() : '';
      artist = aEl ? aEl.textContent.trim() : artist;
    }
    return { title: title, artist: artist };
  }

  // Обложка не загрузилась или вместо неё стоит логотип-заглушка: ищем на iTunes/Deezer, затем рисуем свою
  function recoverCover(im) {
    if (!im || im.dataset.fb === '2' || im.dataset.fbBusy) return;
    var info = trackInfoFor(im), title = info.title;
    if (!title || /^(cover|avatar|logo|musicium)$/i.test(title) || !isCoverImg(im) || /avatar/i.test(im.className || '')) return;
    var stage = im.dataset.fb ? 2 : 1;
    im.dataset.fb = String(stage);
    var finalFallback = function () { im.dataset.fb = '2'; delete im.dataset.fbBusy; im.classList.add('cover-ph'); im.src = placeholder(title); };
    if (stage === 2) return finalFallback();
    var q = new URLSearchParams({ title: title, artist: info.artist }).toString();
    var go = function (u) {
      delete im.dataset.fbBusy;
      if (!u) return finalFallback();
      setCover(im, '/api/proxy-image?url=' + encodeURIComponent(u));
    };
    im.dataset.fbBusy = '1';
    if (coverCache[q] !== undefined) return go(coverCache[q]);
    fetch('/api/cover?' + q).then(function (r) { return r.json(); })
      .then(function (d) { coverCache[q] = d && d.url || null; go(coverCache[q]); })
      .catch(finalFallback);
  }
  document.addEventListener('error', function (e) {
    if (e.target && e.target.tagName === 'IMG') recoverCover(e.target);
  }, true);

  var area = $('ytmContentArea');
  var CARD_SEL = '.album-thumb-wrap, .chart-thumb-wrap, .square-card, .recent-card, .live-card, .community-card, .track-card, .queue-item, .ytm-tracklist-container, .curated-compact-grid, .coverflow-card, .cap-art-wrap, .lyrics-header-thumb-wrap';
  var CARD = '.album-thumb-wrap, .chart-thumb-wrap, .square-card, .recent-card, .live-card, .community-card, .track-card, .queue-item, .ytm-tracklist-container, .curated-compact-grid, .coverflow-card';
  function fixImages(scope) {
    var imgs = (scope || document).querySelectorAll('img[src*="activity_icon"]');
    imgs.forEach(function (im) {
      if (im.classList.contains('cover-ph') || im.dataset.fb) return;
      recoverCover(im);
    });
  }
  if (area) {
    fixImages(area);
    var busy = false;
    new MutationObserver(function () {
      if (busy) return;
      busy = true;
      requestAnimationFrame(function () { busy = false; fixImages(area); });
    }).observe(area, { childList: true, subtree: true, attributes: true, attributeFilter: ['src'] });
  }
  var dockWrap = document.querySelector('.vision-coverflow-wrapper, #allQueueView');
  if (dockWrap) fixImages(dockWrap);
})();

/* ============================================================
   Журнал обновлений для всех пользователей («Что нового»)
   ============================================================ */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var modal = $('changelogModal');
  var btn = $('sbNewsBtn');
  var dot = $('newsDot');
  var list = $('changelogList');
  if (!modal || !list) return;

  var KEY = 'musicium_seen_changelog';
  var latest = null;
  var entries = [];

  function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function seen() { try { return localStorage.getItem(KEY); } catch (_) { return null; } }
  function markSeen() { try { if (latest) localStorage.setItem(KEY, latest); } catch (_) {} if (dot) dot.classList.remove('on'); }
  function fmtDate(iso) {
    try { return new Date(iso + 'T00:00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }); }
    catch (_) { return iso || ''; }
  }

  function render() {
    if (!entries.length) { list.innerHTML = '<div class="changelog-empty">Записей пока нет.</div>'; return; }
    var prev = seen();
    list.innerHTML = entries.map(function (e, i) {
      var isNew = i === 0 && prev !== e.version;
      return '<article class="changelog-entry' + (isNew ? ' is-new' : '') + '">' +
        '<header><span class="changelog-ver">v' + esc(e.version) + '</span>' +
        (isNew ? '<span class="changelog-badge">Новое</span>' : '') +
        '<span class="changelog-date">' + esc(fmtDate(e.date)) + '</span></header>' +
        '<h4>' + esc(e.title) + '</h4>' +
        '<ul>' + (e.items || []).map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') + '</ul></article>';
    }).join('');
  }

  function open() { render(); modal.style.display = 'flex'; markSeen(); }
  function close() { modal.style.display = 'none'; }

  if (btn) btn.addEventListener('click', open);
  var closeBtn = $('closeChangelogBtn');
  if (closeBtn) closeBtn.addEventListener('click', close);
  modal.addEventListener('click', function (e) { if (e.target === modal) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && modal.style.display !== 'none') close(); });

  fetch('/api/changelog').then(function (r) { return r.json(); }).then(function (d) {
    entries = d.entries || [];
    latest = d.latest || null;
    if (!latest) return;
    var prev = seen();
    if (prev !== latest && dot) dot.classList.add('on');
    // вернувшемуся пользователю показываем окно один раз после загрузки; новичку — только точку
    if (prev && prev !== latest) {
      setTimeout(function () {
        var auth = $('authDiscordModal');
        var busyModal = document.querySelector('.custom-modal-overlay:not(#changelogModal)');
        var authVisible = auth && auth.style.display !== 'none';
        var otherOpen = busyModal && busyModal.style.display !== 'none' && busyModal !== auth;
        if (!authVisible && !otherOpen) open();
      }, 3500);
    }
  }).catch(function () {});
})();

/* ============================================================
   V17: индикатор «где бот используется» в шапке
   ============================================================ */
(function () {
  'use strict';
  var pill = document.getElementById('botOnlinePill');
  var text = document.getElementById('botOnlineText');
  if (!pill || !text) return;

  function plural(n, a, b, c) {
    n = Math.abs(n) % 100; var d = n % 10;
    if (n > 10 && n < 20) return c;
    if (d > 1 && d < 5) return b;
    return d === 1 ? a : c;
  }
  function refresh() {
    fetch('/api/status').then(function (r) { return r.json(); }).then(function (d) {
      if (!d || !d.online) { pill.style.display = 'none'; return; }
      var g = d.guilds_count || 0, p = d.playing_servers || 0, l = d.listeners || 0;
      var parts = [g + ' ' + plural(g, 'сервер', 'сервера', 'серверов')];
      if (p) parts.push('играет на ' + p);
      if (l) parts.push(l + ' ' + plural(l, 'слушатель', 'слушателя', 'слушателей'));
      text.textContent = parts.join(' · ');
      pill.classList.toggle('is-live', p > 0);
      pill.style.display = '';
    }).catch(function () { pill.style.display = 'none'; });
  }
  refresh();
  setInterval(refresh, 20000);
})();
