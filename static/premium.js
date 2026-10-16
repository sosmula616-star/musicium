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
