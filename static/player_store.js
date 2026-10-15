/**
 * Musicium Unified Player & Queue Store (player_store.js)
 * Manages player state (history, current, queue, autoplay),
 * Media Session API, hotkeys, drag-and-drop reordering, and smart similarity recommendation engine.
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
      isAutoplay: Boolean(isAutoplay)
    };
    return t;
  }

  function formatSeconds(sec) {
    const s = Math.max(0, Math.floor(sec || 0));
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return `${m}:${rem < 10 ? '0' : ''}${rem}`;
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
      this._retrySimilarCount = 0;
      this._retrySimilarTimer = null;
      this._tickerInterval = null;

      this._initMediaSession();
      this._initHotkeys();
      this._startTicker();

      // If autoplay is enabled and queue is empty, schedule initial similar tracks
      if (this.autoplay && this.queue.length <= 3) {
        setTimeout(() => this.loadSimilar(), 800);
      }
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

    // Play a track directly
    async play(track, { isManual = true, playNow = true, silent = false } = {}) {
      if (!track) return;
      const normalized = normalizeTrack(track, false);

      // If already playing this track, just ensure playback is active
      if (this.current && this.current.title === normalized.title && this.current.artist === normalized.artist) {
        if (!this.isPlaying) {
          this.resume();
        }
        return;
      }

      // Old current goes to history
      if (this.current) {
        this.history.unshift(this.current);
        if (this.history.length > MAX_HISTORY) {
          this.history.pop();
        }
      }

      // Remove from queue if it was queued
      this.queue = this.queue.filter(t => !this._isSameTrack(t, normalized));

      this.current = normalized;
      this.elapsed = 0;
      this.duration = parseDuration(normalized.duration_str || normalized.duration) || 210;
      this.isPlaying = true;

      this._announceTrackChange(this.current);
      this.notify('track_change', { track: this.current });

      // Check autoplay threshold
      if (this.autoplay && this.queue.length <= 3) {
        this.loadSimilar();
      }

      // Dispatch to bot/backend if available
      if (typeof window.dispatchBotPlayTrack === 'function') {
        try {
          await window.dispatchBotPlayTrack(this.current, playNow, silent);
        } catch (_) {}
      }
    }

    // Insert track at the beginning of the queue (next in line)
    playNext(track) {
      if (!track) return;
      const normalized = normalizeTrack(track, false);
      // Remove duplicate if already present in queue
      this.queue = this.queue.filter(t => !this._isSameTrack(t, normalized));

      this.queue.unshift(normalized);
      this.notify('queue_update', { action: 'playNext', track: normalized });

      if (typeof window.showToast === 'function') {
        window.showToast(`Будет сыграно следующим: ${normalized.title}`, 'success', 'fa-forward-step');
      }
    }

    // Enqueue track (manual tracks go before autoplay tracks)
    enqueue(track, { silent = false } = {}) {
      if (!track) return;
      const normalized = normalizeTrack(track, false);

      // If nothing is playing, play immediately
      if (!this.current) {
        return this.play(normalized, { isManual: true, playNow: true, silent });
      }

      // Avoid immediate duplicates in queue
      this.queue = this.queue.filter(t => !this._isSameTrack(t, normalized));

      // Find first autoplay track: manual tracks insert before autoplay
      const firstAutoplayIdx = this.queue.findIndex(t => t.isAutoplay);
      if (firstAutoplayIdx !== -1) {
        this.queue.splice(firstAutoplayIdx, 0, normalized);
      } else {
        this.queue.push(normalized);
      }

      this.notify('queue_update', { action: 'enqueue', track: normalized });

      if (!silent && typeof window.showToast === 'function') {
        window.showToast(`Добавлено в очередь: ${normalized.title}`, 'success', 'fa-plus');
      }

      // Dispatch enqueue to bot if needed
      if (typeof window.dispatchBotPlayTrack === 'function') {
        try {
          window.dispatchBotPlayTrack(normalized, false, true);
        } catch (_) {}
      }
    }

    // Advance to the next track
    async next() {
      if (this.queue.length > 0) {
        if (this.current) {
          this.history.unshift(this.current);
          if (this.history.length > MAX_HISTORY) {
            this.history.pop();
          }
        }
        const nextTrack = this.queue.shift();
        this.current = nextTrack;
        this.elapsed = 0;
        this.duration = parseDuration(nextTrack.duration_str || nextTrack.duration) || 210;
        this.isPlaying = true;

        this._announceTrackChange(this.current);
        this.notify('track_change', { track: this.current, direction: 'next' });

        if (this.autoplay && this.queue.length <= 3) {
          this.loadSimilar();
        }

        if (typeof window.dispatchBotPlayTrack === 'function') {
          try {
            await window.dispatchBotPlayTrack(this.current, true, true);
          } catch (_) {}
        }
      } else {
        // Queue empty
        if (this.autoplay) {
          await this.loadSimilar({ immediatePlay: true });
        } else {
          this.isPlaying = false;
          this.notify('queue_ended');
          if (typeof window.showToast === 'function') {
            window.showToast('Очередь воспроизведения завершена', 'info');
          }
        }
      }
    }

    // Previous track or rewind if elapsed > 3s
    async prev() {
      // If elapsed > 3s, restart current track
      if (this.elapsed > 3) {
        this.elapsed = 0;
        this.notify('seek', { seconds: 0 });
        if (typeof window.showToast === 'function') {
          window.showToast('Трек перезапущен', 'info', 'fa-backward-step');
        }
        if (typeof window.dispatchBotAction === 'function') {
          try {
            await window.dispatchBotAction('seek', { seconds: 0 });
          } catch (_) {}
        }
        return;
      }

      // Otherwise return to the last track from history
      if (this.history.length > 0) {
        if (this.current) {
          // Current returns to beginning of queue
          this.queue.unshift(this.current);
        }
        const prevTrack = this.history.shift();
        this.current = prevTrack;
        this.elapsed = 0;
        this.duration = parseDuration(prevTrack.duration_str || prevTrack.duration) || 210;
        this.isPlaying = true;

        this._announceTrackChange(this.current);
        this.notify('track_change', { track: this.current, direction: 'prev' });

        if (typeof window.dispatchBotPlayTrack === 'function') {
          try {
            await window.dispatchBotPlayTrack(this.current, true, true);
          } catch (_) {}
        }
      } else {
        this.elapsed = 0;
        this.notify('seek', { seconds: 0 });
      }
    }

    // Jump to specific track in queue: all preceding tracks move to history
    async jumpTo(index) {
      if (index < 0 || index >= this.queue.length) return;

      if (this.current) {
        this.history.unshift(this.current);
      }

      // All tracks before index go to history
      const skipped = this.queue.splice(0, index);
      for (let i = skipped.length - 1; i >= 0; i--) {
        this.history.unshift(skipped[i]);
      }
      if (this.history.length > MAX_HISTORY) {
        this.history = this.history.slice(0, MAX_HISTORY);
      }

      const chosen = this.queue.shift();
      this.current = chosen;
      this.elapsed = 0;
      this.duration = parseDuration(chosen.duration_str || chosen.duration) || 210;
      this.isPlaying = true;

      this._announceTrackChange(this.current);
      this.notify('track_change', { track: this.current, jumped: true });

      if (this.autoplay && this.queue.length <= 3) {
        this.loadSimilar();
      }

      if (typeof window.dispatchBotPlayTrack === 'function') {
        try {
          await window.dispatchBotPlayTrack(this.current, true, true);
        } catch (_) {}
      }
    }

    // Reorder tracks in queue (via Drag & Drop)
    reorder(fromIndex, toIndex) {
      if (fromIndex === toIndex || fromIndex < 0 || fromIndex >= this.queue.length || toIndex < 0 || toIndex >= this.queue.length) {
        return;
      }
      const [moved] = this.queue.splice(fromIndex, 1);
      this.queue.splice(toIndex, 0, moved);
      this.notify('queue_reorder', { fromIndex, toIndex });
    }

    // Remove single track from queue
    remove(index) {
      if (index < 0 || index >= this.queue.length) return;
      const [removed] = this.queue.splice(index, 1);
      this.notify('queue_remove', { index, track: removed });

      if (this.autoplay && this.queue.length <= 3) {
        this.loadSimilar();
      }
    }

    // Clear only manual tracks; if autoplay is on, reload similar tracks immediately
    clearManual() {
      // Keep only autoplay tracks, or wipe and reload fresh
      this.queue = [];
      this.notify('queue_clear');

      if (typeof window.showToast === 'function') {
        window.showToast('Очередь очищена', 'info');
      }

      if (this.autoplay) {
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
        // Remove autoplay tracks from queue
        const prevCount = this.queue.length;
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
        if (this.queue.length <= 3) {
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
      if (!this.current) {
        if (this.queue.length > 0) {
          this.next();
        } else {
          this.loadSimilar({ immediatePlay: true });
        }
        return;
      }
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

    // Background loader for similar tracks
    async loadSimilar({ immediatePlay = false } = {}) {
      if (this.isLoadingSimilar) return;
      this.isLoadingSimilar = true;
      this.notify('loading_similar_start');

      const seed = this.current || (this.history.length > 0 ? this.history[0] : null);

      try {
        let fetched = [];

        // 1. Try smart endpoint /api/similar
        if (seed) {
          const params = new URLSearchParams({
            title: seed.title || '',
            artist: seed.artist || '',
            source: seed.source || 'all',
            genre: seed.genre || '',
            limit: '10'
          });
          const resp = await fetch(`/api/similar?${params.toString()}`);
          if (resp.ok) {
            const data = await resp.json();
            if (data && Array.isArray(data.tracks) && data.tracks.length > 0) {
              fetched = data.tracks.map(t => normalizeTrack(t, true));
            }
          }
        }

        // 2. Fallback / supplementary: /api/recommendations or search
        if (fetched.length < 5) {
          const recResp = await fetch('/api/recommendations');
          if (recResp.ok) {
            const recData = await recResp.json();
            const pool = [
              ...(recData.curated || []),
              ...(recData.quick_picks || []),
              ...(recData.youtube_charts || []),
              ...(recData.soundcloud_charts || [])
            ];
            // Shuffle pool
            for (let i = pool.length - 1; i > 0; i--) {
              const j = Math.floor(Math.random() * (i + 1));
              [pool[i], pool[j]] = [pool[j], pool[i]];
            }
            const normalizedPool = pool.map(t => normalizeTrack(t, true));
            fetched.push(...normalizedPool);
          }
        }

        // Deduplication against current, queue, and last 20 history tracks
        const historyRecent = this.history.slice(0, 20);
        const uniqueSimilar = [];

        for (const cand of fetched) {
          if (!cand || !cand.title) continue;
          if (this.current && this._isSameTrack(this.current, cand)) continue;
          if (this.queue.some(q => this._isSameTrack(q, cand))) continue;
          if (historyRecent.some(h => this._isSameTrack(h, cand))) continue;
          if (uniqueSimilar.some(u => this._isSameTrack(u, cand))) continue;

          cand.isAutoplay = true;
          uniqueSimilar.push(cand);
          if (uniqueSimilar.length >= 8) break;
        }

        if (uniqueSimilar.length > 0) {
          this._retrySimilarCount = 0;

          if (immediatePlay && !this.current) {
            const first = uniqueSimilar.shift();
            this.current = first;
            this.queue.push(...uniqueSimilar);
            this.elapsed = 0;
            this.duration = parseDuration(first.duration_str || first.duration) || 210;
            this.isPlaying = true;
            this._announceTrackChange(this.current);
            this.notify('track_change', { track: this.current });
            if (typeof window.dispatchBotPlayTrack === 'function') {
              window.dispatchBotPlayTrack(this.current, true, true);
            }
          } else {
            this.queue.push(...uniqueSimilar);
            this.notify('queue_loaded_similar', { count: uniqueSimilar.length });
          }
        } else {
          throw new Error('No unique similar tracks found');
        }
      } catch (err) {
        console.warn('Auto-match recommendations error:', err);
        this._retrySimilarCount += 1;
        if (this._retrySimilarCount <= 3) {
          if (typeof window.showToast === 'function') {
            window.showToast('Подбор треков: повтор через 5 секунд...', 'info');
          }
          if (this._retrySimilarTimer) clearTimeout(this._retrySimilarTimer);
          this._retrySimilarTimer = setTimeout(() => {
            this.loadSimilar({ immediatePlay });
          }, 5000);
        }
      } finally {
        this.isLoadingSimilar = false;
        this.notify('loading_similar_end');
      }
    }

    // Synchronize with external Discord bot state (from /api/player or WebSocket)
    syncFromBackend(backendState) {
      if (!backendState) return;

      const hasTrack = Boolean(backendState.current_track || backendState.is_playing || backendState.is_paused);
      if (!hasTrack) {
        return;
      }

      const botTrack = normalizeTrack(backendState.current_track, false);
      if (botTrack) {
        if (!this.current || !this._isSameTrack(this.current, botTrack)) {
          if (this.current) {
            this.history.unshift(this.current);
            if (this.history.length > MAX_HISTORY) this.history.pop();
          }
          this.current = botTrack;
          this.elapsed = backendState.position || backendState.elapsed_seconds || 0;
          this.duration = parseDuration(botTrack.duration_str || botTrack.duration) || backendState.duration || 210;
          this.isPlaying = Boolean(backendState.is_playing && !backendState.is_paused);
          this.notify('backend_sync');
          return;
        }
      }

      this.isPlaying = Boolean(backendState.is_playing && !backendState.is_paused);
      if (backendState.position !== undefined) {
        this.elapsed = Number(backendState.position);
      } else if (backendState.elapsed_seconds !== undefined) {
        this.elapsed = Number(backendState.elapsed_seconds);
      }
      this.notify('backend_tick');
    }

    // Helper: test track equality by title/artist or url
    _isSameTrack(a, b) {
      if (!a || !b) return false;
      if (a.url && b.url && a.url === b.url) return true;
      const cleanTitleA = (a.title || '').trim().toLowerCase();
      const cleanTitleB = (b.title || '').trim().toLowerCase();
      const cleanArtistA = (a.artist || '').trim().toLowerCase();
      const cleanArtistB = (b.artist || '').trim().toLowerCase();
      return cleanTitleA === cleanTitleB && (!cleanArtistA || !cleanArtistB || cleanArtistA === cleanArtistB);
    }

    // Progress ticker
    _startTicker() {
      if (this._tickerInterval) clearInterval(this._tickerInterval);
      this._tickerInterval = setInterval(() => {
        if (this.isPlaying && this.current) {
          this.elapsed += 1;
          if (this.duration > 0 && this.elapsed >= this.duration) {
            // Track finished! Rule 4: queue -> current, old current -> history
            this.next();
            return;
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
        // Skip hotkeys if focused on input, textarea, or contenteditable
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
