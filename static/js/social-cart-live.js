(function () {
  'use strict';

  let sinceId = 0;
  let polling = null;

  function getCSRFToken() {
    if (window.getCSRFToken && typeof window.getCSRFToken === 'function') return window.getCSRFToken();
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    const input = document.querySelector('[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  function showToast(msg, type) {
    if (window.showToast) return window.showToast(msg, type);
    console.log(`[${type}] ${msg}`);
  }

  function getSocialId() {
    const el = document.getElementById('socialId');
    return el ? el.value : null;
  }

  function updateTotals(data) {
    // Update item count
    const itemCount = document.getElementById('item-count');
    if (itemCount && data.item_count != null) {
      itemCount.textContent = data.item_count;
    }

    // Update subtotal if provided
    const subtotalEl = document.getElementById('order-subtotal');
    if (subtotalEl && data.cart_total != null) {
      // Preserve currency symbol
      const currentText = subtotalEl.textContent;
      const symbolMatch = currentText.match(/^[^\d]*/);
      const symbol = symbolMatch ? symbolMatch[0] : '';
      subtotalEl.textContent = symbol + data.cart_total;
    }
  }

  function renderActivity(activity) {
    const feed = document.getElementById('liveActivityFeed');
    if (!feed) return;

    // Clear "Loading activity..." placeholder if present
    if (feed.querySelector('small')) {
      feed.innerHTML = '';
    }

    const msg = activity.message || activity.event || 'Activity update';

    // Create activity item
    const div = document.createElement('div');
    div.className = 'activity-item small py-2 border-bottom';

    // Add icon based on type
    let icon = 'fa-circle';
    let iconColor = 'text-primary';

    if (activity.type === 'member') {
      icon = 'fa-user-plus';
      iconColor = 'text-success';
    } else if (activity.type === 'payment') {
      icon = 'fa-dollar-sign';
      iconColor = 'text-info';
    }

    div.innerHTML = `
      <i class="fas ${icon} me-2 ${iconColor}"></i>
      <span class="text-muted">${msg}</span>
      ${activity.ts ? `<small class="text-muted ms-2">${formatTimestamp(activity.ts)}</small>` : ''}
    `;

    feed.prepend(div);

    // Keep feed manageable (last 50 items)
    while (feed.children.length > 50) {
      feed.removeChild(feed.lastChild);
    }
  }

  function formatTimestamp(isoString) {
    try {
      const date = new Date(isoString);
      const now = new Date();
      const diff = now - date;

      // Less than 1 minute
      if (diff < 60000) {
        return 'just now';
      }
      // Less than 1 hour
      if (diff < 3600000) {
        const mins = Math.floor(diff / 60000);
        return `${mins}m ago`;
      }
      // Less than 24 hours
      if (diff < 86400000) {
        const hours = Math.floor(diff / 3600000);
        return `${hours}h ago`;
      }
      // Older - show date
      return date.toLocaleDateString();
    } catch (e) {
      return '';
    }
  }

  async function poll() {
    const socialId = getSocialId();
    if (!socialId) return;

    const url = window.SOCIAL_CART_LIVE_URL;
    if (!url) return;

    try {
      const qs = new URLSearchParams({
        social_id: socialId,
        since: String(sinceId || 0)
      });

      const res = await fetch(`${url}?${qs.toString()}`, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin'
      });

      if (!res.ok) {
        console.warn('Live poll failed:', res.status);
        return;
      }

      const data = await res.json();

      if (!data.success) {
        console.warn('Live poll unsuccessful:', data.message);
        return;
      }

      // Update totals
      updateTotals(data);

      // Process new activities
      if (Array.isArray(data.activities) && data.activities.length) {
        // Update cursor to latest activity ID
        if (data.latest_id) {
          sinceId = data.latest_id;
        }

        // Render each activity (they come sorted by ID ascending)
        data.activities.forEach(activity => {
          renderActivity(activity);

          // Show toast for new activities (limit to avoid spam)
          if (data.activities.length <= 3) {
            const msg = activity.message || 'New activity';
            showToast(msg, 'info');
          }
        });

        // If many activities, just show a summary toast
        if (data.activities.length > 3) {
          showToast(`${data.activities.length} new updates in cart`, 'info');
        }
      }

      // Update social cart status if changed
      if (data.social_status) {
        const statusBadge = document.querySelector('.social-cart-status-badge');
        if (statusBadge && statusBadge.textContent.toLowerCase() !== data.social_status.toLowerCase()) {
          statusBadge.textContent = data.social_status.charAt(0).toUpperCase() + data.social_status.slice(1);
          showToast(`Cart status changed to: ${data.social_status}`, 'info');
        }
      }

    } catch (error) {
      console.error('Live poll error:', error);
      // Don't show errors to user - just log them
    }
  }

  function start() {
    if (polling) return;

    const socialId = getSocialId();
    if (!socialId) {
      console.log('No social cart ID - skipping live polling');
      return;
    }

    console.log('Starting live activity polling');

    // Initial poll
    poll();

    // Set up interval
    const pollInterval = window.SOCIAL_LIVE_POLL_MS || 2500;
    polling = setInterval(() => {
      poll().catch(() => {});
    }, pollInterval);
  }

  function stop() {
    if (polling) {
      console.log('Stopping live activity polling');
      clearInterval(polling);
      polling = null;
    }
  }

  // Pause polling when tab is hidden
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stop();
    } else {
      start();
    }
  });

  // Start polling when page loads
  document.addEventListener('DOMContentLoaded', () => {
    start();
  });

  // Stop polling when page unloads
  window.addEventListener('beforeunload', () => {
    stop();
  });

})();