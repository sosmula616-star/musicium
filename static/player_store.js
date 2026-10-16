/**
 * Musicium Unified Player & Queue Store (player_store.js)
 * Authoritative synchronization with Discord bot player,
 * Media Session API, hotkeys, drag-and-drop reordering, and smart similarity recommendations.
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'musicium_player_store_v2';
  const MAX_HISTORY = 50;

  // Helper: safe JSON parsing
  function loadSavedState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) {
      console.warn('Failed to parse player store from localStorage:', e);
      return null;
    }
  }

  function saveState(state) {
    try {
      const toSave = {
        history: state.history.slice(0, MAX_HISTORY),
        queue: state.queue,
        autoplay: state.autoplay,
        current: state.current
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
    } catch (e) {
      console.warn('Failed to save player store to localStorage:', e);
    }
  }

  // Parse duration string "MM:SS" or "HH:MM:SS" into seconds
  function parseDuration(val) {
    if (typeof val === 'number') return val > 0 ? val : 0;
    if (!val || typeof val !== 'string') return 0;
    const parts = val.split(':').map(p => parseInt(p, 10));
    if (parts.some(isNaN)) return 0;
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    return 0;
  }

  function formatSeconds(sec) {
    const s = Math.max(0, Math.floor(sec || 0));
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return `${m}:${rem < 10 ? '0' : ''}${rem}`;
  }

  // Normalize track object ensuring standard fields
  function normalizeTrack(raw, isAutoplay = false) {
    if (!raw) return null;
    const t = {
      title: raw.title || 'Неизвестный трек',
      artist: raw.artist || raw.author || 'Неизвестный исполнитель',
      thumbnail: raw.thumbnail || raw.cover || '/static/activity_icon.jpg',
      duration_str: raw.duration_str || (raw.duration ? formatSeconds(raw.duration) : '3:30'),
      duration: raw.duration ? Number(raw.duration) : parseDuration(raw.duration_str || '3:30'),
      source: (raw.source || (raw.url && raw.url.includes('soundcloud') ? 'soundcloud' : 'youtube')).toLowerCase(),
      url: raw.url || '',
      id: raw.id || raw.track_id || '',
      genre: raw.genre || '',
      views: raw.views || '',
      plays: raw.plays || '',
      isAutoplay: Boolean(isAutoplay || raw.isAutoplay)
    };
    return t;
  }

  class PlayerStore {
    constructor() {
      const saved = loadSavedState() || {};

      this.history = Array.isArray(saved.history) ? saved.history.slice(0, MAX_HISTORY) : [];
      this.current = saved.current ? normalizeTrack(saved.current, false) : null;
      this.queue = Array.isArray(saved.queue) ? saved.queue.map(t => normalizeTrack(t, t.isAutoplay)) : [];
      this.autoplay = saved.autoplay !== undefined ? Boolean(saved.autoplay) : true;

      this.isPlaying = false;
      this.elapsed = 0;
      this.duration = this.current ? parseDuration(this.current.duration_str || this.current.duration) : 0;
      this.isLoadingSimilar = false;

      this._listeners = new Set();
      this._lastLoadSimilarTime = 0;
      this._isEnqueuingAutoplay = false;
      this._similarKey = null;      // трек, для которого уже подбирали похожие
      this._enqueuedKey = null;     // трек, для которого уже подавали автотрек боту
      this._tickerInterval = null;

      this._initMediaSession();
      this._initHotkeys();
      this._startTicker();
    }

    getState() {
      return {
        history: [...this.history],
        current: this.current ? { ...this.current } : null,
        queue: [...this.queue],
        autoplay: this.autoplay,
        isPlaying: this.isPlaying,
        elapsed: this.elapsed,
        duration: this.duration,
        isLoadingSimilar: this.isLoadingSimilar
      };
    }

    subscribe(fn) {
      if (typeof fn === 'function') {
        this._listeners.add(fn);
        fn(this.getState(), 'init');
      }
      return () => this._listeners.delete(fn);
    }

    notify(type = 'update', payload = null) {
      saveState(this);
      const stateSnapshot = this.getState();
      this._updateMediaSession();
      this._listeners.forEach(fn => {
        try {
          fn(stateSnapshot, type, payload);
        } catch (e) {
          console.error('Error in playerStore subscriber:', e);
        }
      });
      window.dispatchEvent(new CustomEvent('musicium:player-store-update', {
        detail: { state: stateSnapshot, type, payload }
      }));
    }

    // Play a track directly via bot
    async play(track, { isManual = true, playNow = true, silent = false } = {}) {
      if (!track) return;
      if (typeof window.dispatchBotPlayTrack === 'function') {
        try {
          await window.dispatchBotPlayTrack(track, playNow, silent);
        } catch (_) {}
      }
    }

    // Insert track at the beginning of the queue (next in line)
    async playNext(track) {
      if (!track) return;
      if (typeof window.dispatchBotPlayTrack === 'function') {
        try {
          await window.dispatchBotPlayTrack(track, false, false);
          const manualTracks = this.queue.filter(t => !t.isAutoplay);
          if (manualTracks.length > 1 && typeof window.dispatchBotAction === 'function') {
            await window.dispatchBotAction('reorder', { from_index: manualTracks.length - 1, to_index: 0 });
          }
        } catch (_) {}
      }
      if (typeof window.showToast === 'function') {
        window.showToast(`Будет сыграно следующим: ${track.title}`, 'success', 'fa-forward-step');
      }
    }

    // Enqueue track (adds to bot's queue)
    enqueue(track, { silent = false } = {}) {
      if (!track) return;
      if (typeof window.dispatchBotPlayTrack === 'function') {
        try {
          window.dispatchBotPlayTrack(track, false, silent);
        } catch (_) {}
      }
    }

    // Advance to the next track (sends skip action to bot)
    async next() {
      if (typeof window.dispatchBotAction === 'function') {
        try {
          const res = await window.dispatchBotAction('skip', { forced: true });
          if (res && res.success && typeof window.showToast === 'function') {
            window.showToast('Трек пропущен', 'info', 'fa-forward-step');
          }
        } catch (_) {}
      }
    }

    // Previous track or rewind if elapsed > 3s
    async prev() {
      if (this.elapsed > 3) {
        this.seek(0);
        if (typeof window.showToast === 'function') {
          window.showToast('Трек перезапущен', 'info', 'fa-backward-step');
        }
        return;
      }

      if (this.history.length > 0) {
        const prevTrack = this.history[0];
        if (typeof window.dispatchBotPlayTrack === 'function') {
          try {
            await window.dispatchBotPlayTrack(prevTrack, true, false);
          } catch (_) {}
        }
      } else {
        this.seek(0);
      }
    }

    // Jump to specific track in queue
    async jumpTo(index) {
      if (index < 0 || index >= this.queue.length) return;
      const chosen = this.queue[index];
      if (!chosen) return;

      if (typeof window.dispatchBotPlayTrack === 'function') {
        try {
          await window.dispatchBotPlayTrack(chosen, true, false);
        } catch (_) {}
      }
    }

    // Reorder tracks in queue (via Drag & Drop)
    async reorder(fromIndex, toIndex) {
      if (fromIndex === toIndex || fromIndex < 0 || fromIndex >= this.queue.length || toIndex < 0 || toIndex >= this.queue.length) {
        return;
      }
      const [moved] = this.queue.splice(fromIndex, 1);
      this.queue.splice(toIndex, 0, moved);
      this.notify('queue_reorder', { fromIndex, toIndex });

      const manualCount = this.queue.filter(t => !t.isAutoplay).length;
      if (fromIndex < manualCount && toIndex < manualCount) {
        if (typeof window.dispatchBotAction === 'function') {
          try {
            await window.dispatchBotAction('reorder', { from_index: fromIndex, to_index: toIndex });
          } catch (_) {}
        }
      }
    }

    // Remove single track from queue
    async remove(index) {
      if (index < 0 || index >= this.queue.length) return;
      const manualCount = this.queue.filter(t => !t.isAutoplay).length;
      const [removed] = this.queue.splice(index, 1);
      this.notify('queue_remove', { index, track: removed });

      if (index < manualCount) {
        if (typeof window.dispatchBotAction === 'function') {
          try {
            await window.dispatchBotAction('remove', { index });
          } catch (_) {}
        }
      }
    }

    // Clear only manual tracks from queue
    async clearManual() {
      this.queue = this.queue.filter(t => t.isAutoplay);
      this.notify('queue_clear');

      if (typeof window.dispatchBotAction === 'function') {
        try {
          await window.dispatchBotAction('clear');
        } catch (_) {}
      }
      if (typeof window.showToast === 'function') {
        window.showToast('Очередь очищена', 'info');
      }
      if (this.autoplay && this.queue.length <= 2) {
        this.loadSimilar();
      }
    }

    // Clear history
    clearHistory() {
      this.history = [];
      this.notify('history_clear');
      if (typeof window.showToast === 'function') {
        window.showToast('История воспроизведения очищена', 'info');
      }
    }

    // Toggle autoplay on/off
    setAutoplay(enabled) {
      this.autoplay = Boolean(enabled);
      if (!this.autoplay) {
        this.queue = this.queue.filter(t => !t.isAutoplay);
        this.notify('autoplay_change', { autoplay: false });
        if (typeof window.showToast === 'function') {
          window.showToast('Автоподбор отключён', 'info', 'fa-sparkles');
        }
      } else {
        this.notify('autoplay_change', { autoplay: true });
        if (typeof window.showToast === 'function') {
          window.showToast('Автоподбор похожих треков включён', 'success', 'fa-sparkles');
        }
        if (this.queue.length <= 2) {
          this.loadSimilar();
        }
      }
    }

    toggle() {
      if (this.isPlaying) {
        this.pause();
      } else {
        this.resume();
      }
    }

    pause() {
      this.isPlaying = false;
      this.notify('pause');
      if (typeof window.dispatchBotAction === 'function') {
        try {
          window.dispatchBotAction('pause');
        } catch (_) {}
      }
    }

    resume() {
      this.isPlaying = true;
      this.notify('resume');
      if (typeof window.dispatchBotAction === 'function') {
        try {
          window.dispatchBotAction('resume');
        } catch (_) {}
      }
    }

    seek(seconds) {
      this.elapsed = Math.max(0, Math.min(seconds, this.duration || seconds));
      this.notify('seek', { seconds: this.elapsed });
      if (typeof window.dispatchBotAction === 'function') {
        try {
          window.dispatchBotAction('seek', { seconds: this.elapsed });
        } catch (_) {}
      }
    }

    // Background loader for similar tracks (throttled, no recursive spam)
    async loadSimilar() {
      if (this.isLoadingSimilar || !this.autoplay) return;

      const now = Date.now();
      if (this._lastLoadSimilarTime && (now - this._lastLoadSimilarTime < 8000)) {
        return;
      }
      this._lastLoadSimilarTime = now;

      const seed = this.current || (this.history.length > 0 ? this.history[0] : null);
      if (!seed) return;
      this._similarKey = this._trackKey(this.current);

      this.isLoadingSimilar = true;
      this.notify('loading_similar_start');

      try {
        let fetched = [];

        // 1. Try smart endpoint /api/similar
        const params = new URLSearchParams({
          title: seed.title || '',
          artist: seed.artist || '',
          source: seed.source || 'all',
          genre: seed.genre || '',
          limit: '8'
        });
        const resp = await fetch(`/api/similar?${params.toString()}`);
        if (resp.ok) {
          const data = await resp.json();
          if (data && Array.isArray(data.tracks) && data.tracks.length > 0) {
            fetched = data.tracks.map(t => normalizeTrack(t, true));
          }
        }

        // Общие рекомендации с главной в очередь больше не подмешиваются:
        // автоподбор использует только /api/similar.

        // Deduplication against current, queue, and the whole history
        const historyRecent = this.history;
        const uniqueSimilar = [];

        for (const cand of fetched) {
          if (!cand || !cand.title) continue;
          if (this.current && this._isSameTrack(this.current, cand)) continue;
          if (this.queue.some(q => this._isSameTrack(q, cand))) continue;
          if (historyRecent.some(h => this._isSameTrack(h, cand))) continue;
          if (uniqueSimilar.some(u => this._isSameTrack(u, cand))) continue;

          cand.isAutoplay = true;
          uniqueSimilar.push(cand);
          if (uniqueSimilar.length >= 6) break;
        }

        if (uniqueSimilar.length > 0) {
          this.queue.push(...uniqueSimilar);
          this.notify('queue_loaded_similar', { count: uniqueSimilar.length });

          // Pre-enqueue 1st autoplay track to bot with play_now = false if bot queue has 0 tracks
          const botManualCount = this.queue.filter(t => !t.isAutoplay).length;
          const curKey = this._trackKey(this.current);
          if (this.autoplay && this.isPlaying && this.current && botManualCount === 0 &&
              !this._isEnqueuingAutoplay && this._enqueuedKey !== curKey) {
            this._isEnqueuingAutoplay = true;
            this._enqueuedKey = curKey;
            if (typeof window.dispatchBotPlayTrack === 'function') {
              window.dispatchBotPlayTrack(uniqueSimilar[0], false, true).finally(() => {
                setTimeout(() => { this._isEnqueuingAutoplay = false; }, 3000);
              });
            }
          }
        }
      } catch (err) {
        console.warn('Auto-match recommendations error:', err);
      } finally {
        this.isLoadingSimilar = false;
        this.notify('loading_similar_end');
      }
    }

    // Synchronize with authoritative Discord bot state (from /api/player or WebSocket)
    syncFromBackend(backendState) {
      if (!backendState) return;

      const botTrack = normalizeTrack(backendState.current_track, false);
      const isPlaying = Boolean(backendState.is_playing && !backendState.is_paused);
      const elapsed = Number(backendState.position !== undefined ? backendState.position : (backendState.elapsed_seconds || 0));
      const duration = Number(backendState.duration || (botTrack ? parseDuration(botTrack.duration_str || botTrack.duration) : 0));

      const rawQueue = Array.isArray(backendState.queue) ? backendState.queue : [];
      const botQueue = rawQueue.map(t => normalizeTrack(t, false));
      const rawHistory = Array.isArray(backendState.history) ? backendState.history : [];
      const botHistory = rawHistory.map(t => normalizeTrack(t, false));

      let trackChanged = false;
      let queueChanged = false;

      // 1. Current track change check
      if (!this._isSameTrack(this.current, botTrack)) {
        if (this.current) {
          this.history.unshift(this.current);
          if (this.history.length > MAX_HISTORY) this.history.pop();
        }
        this.current = botTrack;
        this.elapsed = elapsed;
        this.duration = duration;
        this.isPlaying = isPlaying;
        trackChanged = true;
      } else {
        this.elapsed = elapsed;
        if (duration > 0) this.duration = duration;
        this.isPlaying = isPlaying;
      }

      // 2. History sync from bot if available
      if (botHistory.length > 0) {
        const mergedHistory = [...botHistory];
        for (const h of this.history) {
          if (!mergedHistory.some(m => this._isSameTrack(m, h))) {
            mergedHistory.push(h);
          }
        }
        this.history = mergedHistory.slice(0, MAX_HISTORY);
      }

      // 3. Queue sync:
      // Manual tracks come directly from bot queue.
      // Autoplay suggestions follow at the end.
      const currentAutoplayTracks = this.autoplay
        ? this.queue.filter(t => t.isAutoplay && !botQueue.some(bq => this._isSameTrack(bq, t)))
        : [];

      const existingManual = this.queue.filter(t => !t.isAutoplay);
      const queueDiff = (existingManual.length !== botQueue.length) ||
        botQueue.some((bt, i) => !existingManual[i] || !this._isSameTrack(existingManual[i], bt));

      if (queueDiff || trackChanged) {
        queueChanged = true;
        this.queue = [...botQueue, ...currentAutoplayTracks];
      }

      // 4. Autoplay pre-enqueueing to Discord bot:
      // If queue has 0 manual tracks and bot is playing, feed next autoplay track to bot with play_now = false
      // Делается не более одного раза на каждый играющий трек.
      const curKey = this._trackKey(this.current);
      if (this.autoplay && this.isPlaying && this.current && botQueue.length === 0 &&
          !this._isEnqueuingAutoplay && this._enqueuedKey !== curKey) {
        const nextAuto = this.queue.find(t => t.isAutoplay);
        if (nextAuto) {
          this._isEnqueuingAutoplay = true;
          this._enqueuedKey = curKey;
          if (typeof window.dispatchBotPlayTrack === 'function') {
            window.dispatchBotPlayTrack(nextAuto, false, true).finally(() => {
              setTimeout(() => { this._isEnqueuingAutoplay = false; }, 3000);
            });
          }
        }
      }

      // Подбор похожих — один раз на трек и только если нет ни ручных, ни подобранных треков
      if (this.autoplay && this.current && !this.isLoadingSimilar && this._similarKey !== curKey &&
          botQueue.length === 0 && !this.queue.some(t => t.isAutoplay)) {
        this.loadSimilar();
      }

      if (trackChanged) {
        this._announceTrackChange(this.current);
        this.notify('track_change', { track: this.current });
      } else if (queueChanged) {
        this.notify('queue_update', { action: 'sync' });
      } else {
        // Micro position/playback update: does NOT rebuild queue DOM!
        this.notify('backend_tick', { elapsed: this.elapsed, duration: this.duration });
      }
    }

    _trackKey(t) {
      return t ? String(t.id || t.url || t.title || '') : '';
    }

    // Helper: test track equality by url or fuzzy title
    _isSameTrack(a, b) {
      if (!a && !b) return true;
      if (!a || !b) return false;
      if (a.id && b.id && String(a.id) === String(b.id)) return true;
      if (a.url && b.url && a.url === b.url) return true;
      const cleanTitleA = (a.title || '').trim().toLowerCase().replace(/[\(\[\{].*?[\)\]\}]/g, '').trim();
      const cleanTitleB = (b.title || '').trim().toLowerCase().replace(/[\(\[\{].*?[\)\]\}]/g, '').trim();
      return Boolean(cleanTitleA && cleanTitleB && cleanTitleA === cleanTitleB);
    }

    // Progress ticker (only updates visual progress, NEVER aborts or skips audio!)
    _startTicker() {
      if (this._tickerInterval) clearInterval(this._tickerInterval);
      this._tickerInterval = setInterval(() => {
        if (this.isPlaying && this.current) {
          if (this.duration > 0 && this.elapsed < this.duration) {
            this.elapsed += 1;
          }
          this.notify('tick', { elapsed: this.elapsed, duration: this.duration });
        }
      }, 1000);
    }

    // Accessibility: announce track change to screen readers
    _announceTrackChange(track) {
      if (!track) return;
      const el = document.getElementById('trackAnnouncer');
      if (el) {
        el.textContent = `Сейчас играет: ${track.title} — ${track.artist}`;
      }
    }

    // Media Session API
    _initMediaSession() {
      if (!('mediaSession' in navigator)) return;
      try {
        navigator.mediaSession.setActionHandler('play', () => this.resume());
        navigator.mediaSession.setActionHandler('pause', () => this.pause());
        navigator.mediaSession.setActionHandler('previoustrack', () => this.prev());
        navigator.mediaSession.setActionHandler('nexttrack', () => this.next());
        navigator.mediaSession.setActionHandler('seekto', (details) => {
          if (details.seekTime !== undefined) this.seek(details.seekTime);
        });
      } catch (e) {
        console.warn('MediaSession handler setup failed:', e);
      }
    }

    _updateMediaSession() {
      if (!('mediaSession' in navigator) || !this.current) return;
      try {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: this.current.title,
          artist: this.current.artist,
          album: 'Musicium Player',
          artwork: [
            { src: this.current.thumbnail, sizes: '512x512', type: 'image/jpeg' }
          ]
        });
        navigator.mediaSession.playbackState = this.isPlaying ? 'playing' : 'paused';
      } catch (_) {}
    }

    // Global keyboard hotkeys: Space, ArrowLeft, ArrowRight
    _initHotkeys() {
      document.addEventListener('keydown', (e) => {
        const tag = (e.target.tagName || '').toUpperCase();
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target.isContentEditable) {
          return;
        }

        if (e.code === 'Space') {
          e.preventDefault();
          this.toggle();
        } else if (e.code === 'ArrowRight') {
          e.preventDefault();
          this.next();
        } else if (e.code === 'ArrowLeft') {
          e.preventDefault();
          this.prev();
        }
      });
    }
  }

  // Export singleton instance
  window.playerStore = new PlayerStore();
})();
