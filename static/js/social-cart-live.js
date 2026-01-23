(function () {
  'use strict';

  // ----------------------------
  // Config
  // ----------------------------
  const EVENTS_POLL_MS = window.SOCIAL_LIVE_POLL_MS || 2500;
  const LIVE_POLL_MS   = window.SOCIAL_CART_LIVE_POLL_MS || 5000;

  // Cursor for /social-cart-events/
  let sinceId = 0;

  // timers
  let eventsTimer = null;
  let liveTimer = null;

  function showToast(msg, type) {
    if (window.showToast) return window.showToast(msg, type);
    console.log(`[${type || 'info'}] ${msg}`);
  }

  function getSocialId() {
    const el = document.getElementById('socialId');
    return el ? el.value : null;
  }

  // ----------------------------
  // Totals + status UI updates
  // ----------------------------
  function updateTotalsFromLive(data) {
    // item_count
    const itemCount = document.getElementById('item-count');
    if (itemCount && data.item_count != null) {
      itemCount.textContent = data.item_count;
    }

    // total (your endpoint returns total)
    const subtotalEl = document.getElementById('order-subtotal');
    if (subtotalEl && data.total != null) {
      // preserve currency symbol prefix already in DOM
      const currentText = subtotalEl.textContent || '';
      const symbolMatch = currentText.match(/^[^\d]*/);
      const symbol = symbolMatch ? symbolMatch[0] : '';
      // keep 2 decimals if backend returns raw number
      const totalStr = (typeof data.total === 'number') ? data.total.toFixed(2) : String(data.total);
      subtotalEl.textContent = symbol + totalStr;
    }

    // status badge
    if (data.status) {
      const statusBadge = document.querySelector('.social-cart-status-badge');
      if (statusBadge) {
        const current = (statusBadge.textContent || '').trim().toLowerCase();
        const next = String(data.status).trim().toLowerCase();
        if (current && current !== next) {
          statusBadge.textContent = data.status.charAt(0).toUpperCase() + data.status.slice(1);
          showToast(`Cart status changed to: ${data.status}`, 'info');
        } else if (!current) {
          statusBadge.textContent = data.status.charAt(0).toUpperCase() + data.status.slice(1);
        }
      }
    }
  }

  // ----------------------------
  // Activity feed rendering
  // ----------------------------
  function formatTimestamp(isoString) {
    try {
      const date = new Date(isoString);
      const now = new Date();
      const diff = now - date;

      if (diff < 60000) return 'just now';
      if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
      if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
      return date.toLocaleDateString();
    } catch (e) {
      return '';
    }
  }

  function iconForEvent(evtName) {
    // map backend "event" field to icons
    switch ((evtName || '').toLowerCase()) {
      case 'chat_message':
        return { icon: 'fa-comment-dots', color: 'text-primary' };
      case 'member_joined':
      case 'member_left':
      case 'cart_invite':
        return { icon: 'fa-user-plus', color: 'text-success' };
      case 'cart_scheduled':
        return { icon: 'fa-calendar-check', color: 'text-info' };
      case 'owner_live':
        return { icon: 'fa-broadcast-tower', color: 'text-warning' };
      case 'payment':
      case 'payment_update':
        return { icon: 'fa-dollar-sign', color: 'text-success' };
      default:
        return { icon: 'fa-circle', color: 'text-muted' };
    }
  }

  function renderEvent(ev) {
    const feed = document.getElementById('liveActivityFeed');
    if (!feed) return;

    // Clear placeholder only if it’s exactly the placeholder content you used
    if (feed.dataset.placeholderCleared !== '1') {
      feed.innerHTML = '';
      feed.dataset.placeholderCleared = '1';
    }

    const msg = ev.message || ev.event || 'Activity update';
    const who = ev.actor ? `@${ev.actor}` : '';
    const ts = ev.created_at ? formatTimestamp(ev.created_at) : '';

    const { icon, color } = iconForEvent(ev.event);

    const div = document.createElement('div');
    div.className = 'activity-item small py-2 border-bottom';

    div.innerHTML = `
      <i class="fas ${icon} me-2 ${color}"></i>
      <span class="text-muted">${msg} ${who ? `<span class="ms-1">${who}</span>` : ''}</span>
      ${ts ? `<small class="text-muted ms-2">${ts}</small>` : ''}
    `;

    feed.prepend(div);

    // cap at 50
    while (feed.children.length > 50) {
      feed.removeChild(feed.lastChild);
    }
  }

  // ----------------------------
  // Poll: EVENTS endpoint (activity feed)
  // expects: {success, events, last_id}
  // ----------------------------
  async function pollEvents() {
    const socialId = getSocialId();
    if (!socialId) return;

    const url = window.SOCIAL_CART_EVENTS_URL; // ✅ use your events endpoint
    if (!url) return;

    const qs = new URLSearchParams({ since_id: String(sinceId || 0) });

    const res = await fetch(`${url}?${qs.toString()}`, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin'
    });

    if (!res.ok) {
      console.warn('Events poll failed:', res.status);
      return;
    }

    const data = await res.json();
    if (!data.success) return;

    const events = Array.isArray(data.events) ? data.events : [];
    if (!events.length) return;

    // advance cursor
    if (data.last_id != null) sinceId = data.last_id;

    // render events (already ascending in backend)
    events.forEach(renderEvent);

    // toasts (avoid spam)
    if (events.length <= 3) {
      events.forEach(ev => showToast(ev.message || 'New update', 'info'));
    } else {
      showToast(`${events.length} new updates`, 'info');
    }
  }

  // ----------------------------
  // Poll: LIVE endpoint (totals/status)
  // expects: {success, active, total, item_count, status}
  // ----------------------------
  async function pollLive() {
    const socialId = getSocialId();
    if (!socialId) return;

    const url = window.SOCIAL_CART_LIVE_URL;
    if (!url) return;

    const qs = new URLSearchParams({ social_id: String(socialId) });

    const res = await fetch(`${url}?${qs.toString()}`, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin'
    });

    if (!res.ok) return;

    const data = await res.json();
    if (!data.success) return;
    if (!data.active) return;

    updateTotalsFromLive(data);
  }

  // ----------------------------
  // Start/Stop
  // ----------------------------
  function start() {
    if (eventsTimer || liveTimer) return;

    const socialId = getSocialId();
    if (!socialId) {
      console.log('No social cart ID - skipping live polling');
      return;
    }

    // Run immediately
    pollEvents().catch(() => {});
    pollLive().catch(() => {});

    // intervals
    eventsTimer = setInterval(() => pollEvents().catch(() => {}), EVENTS_POLL_MS);
    liveTimer = setInterval(() => pollLive().catch(() => {}), LIVE_POLL_MS);
  }

  function stop() {
    if (eventsTimer) {
      clearInterval(eventsTimer);
      eventsTimer = null;
    }
    if (liveTimer) {
      clearInterval(liveTimer);
      liveTimer = null;
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop();
    else start();
  });

  document.addEventListener('DOMContentLoaded', start);
  window.addEventListener('beforeunload', stop);

})();
