/**
 * Musicium Admin — заставка, анимации входа и журнал действий администраторов.
 * Работает поверх admin.html, не меняя его основной скрипт.
 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function token() {
    try {
      var q = new URLSearchParams(window.location.search).get('token');
      return q || localStorage.getItem('musicium_admin_token') || sessionStorage.getItem('musicium_admin_token') || '';
    } catch (_) { return ''; }
  }

  function api(url, opts) {
    opts = opts || {};
    var t = token();
    opts.headers = Object.assign({}, opts.headers || {}, t ? { Authorization: 'Bearer ' + t } : {});
    opts.credentials = 'include';
    return fetch(url, opts);
  }

  // ---------- Splash ----------
  var splash = $('adminSplash');
  var splashStart = Date.now();
  function hideSplash() {
    if (!splash) return;
    var el = splash;
    splash = null;
    setTimeout(function () {
      el.classList.add('is-done');
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 900);
    }, Math.max(0, 1300 - (Date.now() - splashStart)));
  }
  if (document.readyState === 'complete') setTimeout(hideSplash, 250);
  else window.addEventListener('load', function () { setTimeout(hideSplash, 250); }, { once: true });
  setTimeout(hideSplash, 5000);

  // ---------- Кнопки входа: состояние загрузки ----------
  ['authRequestCodeBtn', 'authVerifyPinBtn', 'authPasswordBtn', 'authDiscordBtn'].forEach(function (id) {
    var b = $(id);
    if (!b) return;
    b.addEventListener('click', function () {
      b.classList.add('is-loading');
      setTimeout(function () { b.classList.remove('is-loading'); }, 2600);
    });
  });

  // ---------- Журнал действий ----------
  var audit = { status: '', search: '', action: '', timer: null, entries: [], open: {} };
  var list = $('auditList');
  if (!list) return;

  var STATUS_LABEL = { 200: 'OK', 201: 'OK', 400: 'Ошибка', 401: 'Нет доступа', 403: 'Запрещено', 404: 'Не найдено', 429: 'Лимит', 500: 'Сбой' };

  function render() {
    var e = audit.entries.slice().reverse();
    var ok = audit.entries.filter(function (x) { return x.ok; }).length;
    $('auditStatTotal').textContent = audit.entries.length;
    $('auditStatOk').textContent = ok;
    $('auditStatErr').textContent = audit.entries.length - ok;
    var admins = {};
    audit.entries.forEach(function (x) { admins[x.admin_id || x.ip || '—'] = 1; });
    $('auditStatAdmins').textContent = Object.keys(admins).length;

    if (!e.length) {
      list.innerHTML = '<div class="audit-empty">Записей пока нет — действия администраторов появятся здесь.</div>';
      return;
    }
    list.innerHTML = '<div class="audit-row head"><span>Время</span><span>Статус</span><span>Действие</span><span>Администратор</span><span>IP</span><span></span></div>' +
      e.map(function (x) {
        var who = x.admin_name || x.admin_id || 'не определён';
        var det = JSON.stringify(x.details || {}, null, 2);
        var open = audit.open[x.id];
        return '<div class="audit-row' + (open ? ' open' : '') + '" data-id="' + x.id + '">' +
          '<span class="audit-time">' + esc(x.time) + '</span>' +
          '<span class="audit-badge-cell"><span class="audit-badge ' + (x.ok ? 'ok' : 'err') + '">' + esc(STATUS_LABEL[x.status] || x.status) + '</span></span>' +
          '<span class="audit-action">' + esc(x.action) + '<small>' + esc(x.message || x.path) + '</small></span>' +
          '<span class="audit-admin" title="' + esc(x.admin_id) + '">' + esc(who) + '</span>' +
          '<span class="audit-ip">' + esc(x.ip || '—') + '</span>' +
          '<span class="audit-chevron">▾</span></div>' +
          '<div class="audit-detail' + (open ? ' open' : '') + '" data-detail="' + x.id + '">' +
          esc(x.method + ' ' + x.path + ' → ' + x.status + ' · ' + (x.duration_ms || 0) + ' мс\n' + (det === '{}' ? 'Без параметров' : det)) + '</div>';
      }).join('');
  }

  list.addEventListener('click', function (ev) {
    var row = ev.target.closest('.audit-row[data-id]');
    if (!row) return;
    var id = row.getAttribute('data-id');
    audit.open[id] = !audit.open[id];
    row.classList.toggle('open', !!audit.open[id]);
    var d = list.querySelector('[data-detail="' + id + '"]');
    if (d) d.classList.toggle('open', !!audit.open[id]);
  });

  function load() {
    var q = '?limit=400' +
      (audit.status ? '&status=' + audit.status : '') +
      (audit.action ? '&action=' + encodeURIComponent(audit.action) : '') +
      (audit.search ? '&search=' + encodeURIComponent(audit.search) : '');
    return api('/api/admin/audit' + q).then(function (r) {
      if (r.status === 401) return null;
      return r.json();
    }).then(function (data) {
      if (!data) return;
      audit.entries = data.entries || [];
      var sel = $('auditActionSelect');
      if (sel && data.actions) {
        var cur = sel.value;
        sel.innerHTML = '<option value="">Все действия</option>' +
          data.actions.map(function (a) { return '<option value="' + esc(a) + '">' + esc(a) + '</option>'; }).join('');
        sel.value = cur;
      }
      render();
    }).catch(function () {});
  }

  document.querySelectorAll('.audit-filter').forEach(function (b) {
    b.addEventListener('click', function () {
      document.querySelectorAll('.audit-filter').forEach(function (x) { x.classList.remove('active'); });
      b.classList.add('active');
      audit.status = b.getAttribute('data-status') || '';
      load();
    });
  });

  var searchEl = $('auditSearchInput');
  var searchTimer = null;
  if (searchEl) searchEl.addEventListener('input', function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () { audit.search = searchEl.value.trim(); load(); }, 250);
  });
  var actionSel = $('auditActionSelect');
  if (actionSel) actionSel.addEventListener('change', function () { audit.action = actionSel.value; load(); });
  var refreshBtn = $('auditRefreshBtn');
  if (refreshBtn) refreshBtn.addEventListener('click', function () {
    refreshBtn.classList.add('is-loading');
    load().then(function () { setTimeout(function () { refreshBtn.classList.remove('is-loading'); }, 300); });
  });

  // Автообновление только пока открыта вкладка журнала
  function tick() {
    var tab = $('tab-audit');
    if (tab && tab.classList.contains('active') && !document.hidden) load();
  }
  document.querySelectorAll('.tab-btn').forEach(function (b) {
    b.addEventListener('click', function () {
      if (b.getAttribute('data-tab') === 'tab-audit') load();
    });
  });
  audit.timer = setInterval(tick, 5000);
})();

/* ============================================================
   Управление ботом
   ============================================================ */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  if (!$('tab-botctl')) return;

  function token() {
    try {
      var q = new URLSearchParams(window.location.search).get('token');
      return q || localStorage.getItem('musicium_admin_token') || sessionStorage.getItem('musicium_admin_token') || '';
    } catch (_) { return ''; }
  }
  function api(url, opts) {
    opts = opts || {};
    var t = token();
    opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {}, t ? { Authorization: 'Bearer ' + t } : {});
    opts.credentials = 'include';
    return fetch(url, opts).then(function (r) { return r.json().then(function (d) { d.__status = r.status; return d; }); });
  }
  function toast(msg, type) {
    var c = $('toastContainer');
    if (!c) return;
    var n = document.createElement('div');
    n.className = 'toast-item ' + (type || 'info');
    n.textContent = msg;
    c.appendChild(n);
    setTimeout(function () { n.style.opacity = '0'; n.style.transition = 'opacity .3s'; setTimeout(function () { n.remove(); }, 320); }, 3800);
  }
  function busy(btn, on) { if (btn) { btn.disabled = on; btn.classList.toggle('is-loading', on); } }

  var loaded = false;

  function diagRow(label, ok, text) {
    var cls = ok === null ? '' : (ok ? 'ok' : 'bad');
    return '<div class="bot-diag-row"><span>' + label + '</span><b class="' + cls + '">' + text + '</b></div>';
  }

  function render(d) {
    var p = d.players || {};
    $('botStatPlayers').textContent = p.total || 0;
    $('botStatPlaying').textContent = p.playing || 0;
    $('botStatVoice').textContent = p.voice_connections || 0;
    $('botStatQueued').textContent = p.queued_tracks || 0;
    $('botStatPing').textContent = (d.latency_ms || 0) + ' мс';
    $('botStatCache').textContent = (d.caches && d.caches.streams) || 0;

    if (!loaded) {
      var m = d.maintenance || {};
      $('botMaintToggle').checked = !!m.enabled;
      $('botMaintMessage').value = m.message || '';
      var pr = d.presence || {};
      $('botPresStatus').value = pr.status || 'online';
      $('botPresType').value = pr.activity_type || 'listening';
      $('botPresText').value = pr.text || '';
      loaded = true;
    }
    $('botMaintLabel').textContent = $('botMaintToggle').checked ? 'Включён' : 'Выключен';

    var g = d.diagnostics || {};
    $('botDiag').innerHTML =
      diagRow('Python', null, g.python || '—') +
      diagRow('discord.py', null, g.discord_py || '—') +
      diagRow('yt-dlp', !!g.yt_dlp, g.yt_dlp || 'не найден') +
      diagRow('FFmpeg', !!g.ffmpeg, g.ffmpeg ? 'найден' : 'не найден') +
      diagRow('Opus (голос)', !!g.opus, g.opus ? 'загружен' : 'не загружен') +
      diagRow('PyNaCl (голос)', !!g.nacl, g.nacl ? 'установлен' : 'НЕ установлен — голос не подключится') +
      diagRow('davey (шифрование DAVE)', !!g.davey, g.davey ? 'установлен' : 'НЕ установлен — Discord не пустит в голос') +
      diagRow('База данных', !!g.database, g.database ? 'подключена' : 'недоступна') +
      diagRow('Система', null, g.platform || '—');
  }

  function load() {
    return api('/api/admin/bot/overview').then(function (d) {
      if (d.__status === 401) return;
      render(d);
    }).catch(function () {});
  }

  function post(url, body, btn, okFallback) {
    busy(btn, true);
    return api(url, { method: 'POST', body: JSON.stringify(body || {}) }).then(function (d) {
      toast(d.ok ? (d.message || okFallback || 'Готово') : (d.error || d.message || 'Ошибка'), d.ok ? 'success' : 'error');
      busy(btn, false);
      load();
      return d;
    }).catch(function () { busy(btn, false); toast('Ошибка связи с сервером', 'error'); });
  }

  $('botMaintToggle').addEventListener('change', function () {
    $('botMaintLabel').textContent = this.checked ? 'Включён' : 'Выключен';
  });
  $('botMaintSave').addEventListener('click', function () {
    post('/api/admin/bot/maintenance', { enabled: $('botMaintToggle').checked, message: $('botMaintMessage').value }, this);
  });
  $('botPresSave').addEventListener('click', function () {
    post('/api/admin/bot/presence', { status: $('botPresStatus').value, activity_type: $('botPresType').value, text: $('botPresText').value }, this);
  });
  $('botActStopAll').addEventListener('click', function () {
    if (confirm('Остановить воспроизведение на всех серверах?')) post('/api/admin/bot/stop-all', {}, this);
  });
  $('botActDisconnectAll').addEventListener('click', function () {
    if (confirm('Отключить бота от всех голосовых каналов?')) post('/api/admin/bot/disconnect-all', {}, this);
  });
  $('clPublish').addEventListener('click', function () {
    var items = $('clItems').value.split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
    post('/api/admin/changelog', { version: $('clVersion').value, title: $('clTitle').value, items: items }, this).then(function (d) {
      if (d && d.ok) { $('clItems').value = ''; $('clTitle').value = ''; refreshLatest(); }
    });
  });

  function refreshLatest() {
    fetch('/api/changelog').then(function (r) { return r.json(); }).then(function (d) {
      $('clLatest').textContent = d.latest ? 'Последняя опубликованная версия: ' + d.latest : 'Записей пока нет';
    }).catch(function () {});
  }

  document.querySelectorAll('.tab-btn').forEach(function (b) {
    b.addEventListener('click', function () {
      if (b.getAttribute('data-tab') === 'tab-botctl') { load(); refreshLatest(); }
    });
  });
  setInterval(function () {
    var tab = $('tab-botctl');
    if (tab && tab.classList.contains('active') && !document.hidden) load();
  }, 6000);
})();
