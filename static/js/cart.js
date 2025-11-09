/**
 * Cart Management JavaScript – Fixed & Hardened
 * - Quantity updates
 * - Item removal (session + db, with social-cart permissions on server)
 * - Order summary + badge refresh
 */

let csrfToken = null;

document.addEventListener('DOMContentLoaded', function () {
  initializeCart();
});

/* -------------------- Init -------------------- */
function initializeCart() {
  csrfToken = getCSRFToken();
  if (!csrfToken) {
    console.warn('CSRF token not found; cart operations may fail.');
  }

  initializeQuantityControls();
  initializeInputValidation();
  initializeRemoveButtons();
}

/* -------------------- CSRF helpers -------------------- */
function getCSRFToken() {
  return (
    document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
    document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
    getCookie('csrftoken')
  );
}

function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === name + '=') {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

/* -------------------- Quantity controls -------------------- */
function initializeQuantityControls() {
  document.querySelectorAll('.quantity-btn').forEach((button) => {
    button.addEventListener('click', function (e) {
      e.preventDefault();
      const action = this.dataset.action; // 'increase' | 'decrease'
      const itemId = this.dataset.itemId;
      const productId = this.dataset.productId;

      // IMPORTANT: match your HTML wrapper
      const input = this.closest('.quantity-control')?.querySelector('.quantity-input');
      if (!input) {
        console.error('Quantity input not found for item', itemId);
        return;
      }

      let current = parseInt(input.value) || 1;
      let next = current;

      if (action === 'increase' && current < 99) next = current + 1;
      if (action === 'decrease' && current > 1) next = current - 1;

      if (next !== current) {
        input.value = next;
        updateCartItem(itemId, productId, next);
      }
    });
  });
}

/* -------------------- Direct input validation -------------------- */
function initializeInputValidation() {
  document.querySelectorAll('.quantity-input').forEach((input) => {
    input.dataset.originalValue = input.value;

    input.addEventListener('focus', function () {
      this.dataset.originalValue = this.value;
    });

    input.addEventListener('input', function () {
      // hard clamp to 99 on-the-fly
      const v = this.value;
      if (v !== '' && parseInt(v) > 99) this.value = 99;
    });

    input.addEventListener('change', function () {
      const itemId = this.dataset.itemId;
      const productId = this.dataset.productId;

      let value = parseInt(this.value) || 1;
      if (value < 1) value = 1;
      if (value > 99) value = 99;
      this.value = value;

      if (value !== parseInt(this.dataset.originalValue)) {
        updateCartItem(itemId, productId, value);
      }
    });
  });
}

/* -------------------- Remove buttons -------------------- */
function initializeRemoveButtons() {
  document.querySelectorAll('.remove-item').forEach((button) => {
    button.addEventListener('click', function (e) {
      e.preventDefault();

      const itemId = this.dataset.itemId;           // CartItem ID (db)
      const productId = this.dataset.productId;     // Product ID (optional)
      const itemType = this.dataset.itemType || 'db';   // 'db' | 'session'
      const removeId = this.dataset.removeId || itemId; // session key or CartItem.id

      if (!removeId) {
        showToast('Missing item identifier', 'error');
        return;
      }

      if (confirm('Remove this item from your cart?')) {
        removeCartItem({ itemId, productId, itemType, removeId });
      }
    });
  });
}

/* -------------------- Update cart item -------------------- */
function updateCartItem(itemId, productId, quantity) {
  const buttons = document.querySelectorAll(`[data-item-id="${itemId}"]`);
  buttons.forEach((b) => (b.disabled = true));

  const body = new URLSearchParams();
  body.append('cart_item_id', itemId);
  body.append('product_id', productId || '');
  body.append('quantity', quantity);

  fetch('/update-cart-quantity/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-CSRFToken': csrfToken,
      'X-Requested-With': 'XMLHttpRequest',
    },
    body: body.toString(),
  })
    .then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        const msg = data?.message || `HTTP ${r.status}`;
        throw new Error(msg);
      }
      return data;
    })
    .then((data) => {
      if (data.success) {
        // reflect server truth
        const input = document.querySelector(`input.quantity-input[data-item-id="${itemId}"]`);
        if (input && typeof data.quantity !== 'undefined') {
          input.value = data.quantity;
          input.dataset.originalValue = String(data.quantity);
        }

        const subtotalEl = document.querySelector(`tr[data-item-id="${itemId}"] .subtotal`);
        if (subtotalEl && typeof data.subtotal !== 'undefined') {
          subtotalEl.textContent = `D${data.subtotal}`;
        }

        updateOrderSummary(data);
        showToast('Cart updated successfully!', 'success');
      } else {
        showToast(data.message || 'Failed to update cart', 'error');
        revertInputValue(itemId);
      }
    })
    .catch((err) => {
      console.error('Update error:', err);
      showToast(err.message || 'Error updating cart. Please try again.', 'error');
      revertInputValue(itemId);
    })
    .finally(() => {
      buttons.forEach((b) => (b.disabled = false));
    });
}

/* -------------------- Remove cart item (session + db) -------------------- */
function removeCartItem({ itemId, productId, itemType = 'db', removeId }) {
  const row = document.querySelector(`tr[data-item-id="${itemId}"]`) ||
              document.querySelector(`tr[data-remove-id="${removeId}"]`) ||
              document.querySelector(`tr[data-product-id="${productId}"]`);

  const buttons = row ? row.querySelectorAll('button') : [];
  buttons.forEach((b) => (b.disabled = true));

  const body = new URLSearchParams();
  body.append('item_type', itemType); // 'db' or 'session'
  body.append('remove_id', removeId);
  if (productId) body.append('product_id', productId);

  fetch('/remove-cart-item/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-CSRFToken': csrfToken,
      'X-Requested-With': 'XMLHttpRequest',
    },
    body: body.toString(),
  })
    .then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        const msg = data?.message || `HTTP ${r.status}`;
        throw new Error(msg);
      }
      return data;
    })
    .then((data) => {
      if (data.success) {
        // animate then remove row if we have it
        if (row) {
          row.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
          row.style.opacity = '0';
          row.style.transform = 'translateX(-12px)';

          setTimeout(() => {
            row.remove();

            const remaining = document.querySelectorAll('.cart-item').length;
            if (remaining === 0) {
              showToast('Cart is now empty. Refreshing…', 'info');
              setTimeout(() => location.reload(), 800);
            } else {
              updateOrderSummary(data);
              showToast('Item removed from cart!', 'success');
            }
          }, 250);
        } else {
          // No row (possibly removed elsewhere) — just update summary
          updateOrderSummary(data);
          showToast('Item removed from cart!', 'success');
        }
      } else {
        buttons.forEach((b) => (b.disabled = false));
        showToast(data.message || 'Failed to remove item', 'error');
      }
    })
    .catch((err) => {
      console.error('Remove error:', err);
      buttons.forEach((b) => (b.disabled = false));
      showToast(err.message || 'Error removing item. Please try again.', 'error');
    });
}

/* -------------------- Order summary & badges -------------------- */
function updateOrderSummary(data) {
  // item count (server may return cart_count or item_count)
  const itemCount =
    (typeof data.item_count !== 'undefined' && data.item_count) ??
    (typeof data.cart_count !== 'undefined' && data.cart_count);

  const itemCountEl = document.getElementById('item-count');
  if (itemCountEl && itemCount != null) {
    itemCountEl.textContent = itemCount;
  }

  const subtotalEl = document.getElementById('order-subtotal');
  if (subtotalEl && typeof data.total_price !== 'undefined') {
    subtotalEl.textContent = `D${data.total_price}`;
  }

  const totalEl = document.getElementById('total-price');
  if (totalEl) {
    const total =
      (typeof data.final_total !== 'undefined' && data.final_total) ??
      (typeof data.total_price !== 'undefined' && data.total_price);
    if (total != null) totalEl.textContent = `D${total}`;
  }

  const taxEl = document.getElementById('tax-amount');
  if (taxEl && typeof data.tax_amount !== 'undefined') {
    taxEl.textContent = `D${data.tax_amount}`;
  }

  if (itemCount != null) {
    updateCartBadge(itemCount);
  }
}

function updateCartBadge(itemCount) {
  const badges = document.querySelectorAll('.cart-badge, .badge[data-cart-count], #cartCountBadge');
  badges.forEach((badge) => {
    if (!badge) return;
    if (itemCount > 0) {
      badge.textContent = itemCount;
      badge.style.display = 'inline-block';
    } else {
      badge.style.display = 'none';
    }
  });
}

/* -------------------- Utilities -------------------- */
function revertInputValue(itemId) {
  const input = document.querySelector(`input.quantity-input[data-item-id="${itemId}"]`);
  if (input) {
    input.value = input.dataset.originalValue || 1;
  }
}

function showToast(message, type = 'success') {
  const toast = document.getElementById('cartToast');
  if (!toast) {
    if (type === 'error') alert(`Error: ${message}`);
    else console.log(`[Toast] ${type}: ${message}`);
    return;
  }

  const toastBody = toast.querySelector('.toast-body');
  if (toastBody) toastBody.textContent = message;

  const bgClass =
    type === 'error' ? 'bg-danger' :
    type === 'warning' ? 'bg-warning' :
    type === 'info' ? 'bg-info' : 'bg-success';

  toast.className = `toast align-items-center text-white border-0 shadow-lg ${bgClass}`;

  if (window.bootstrap?.Toast) {
    new bootstrap.Toast(toast, { autohide: true, delay: 4000 }).show();
  } else {
    toast.style.display = 'block';
    setTimeout(() => (toast.style.display = 'none'), 4000);
  }
}

/* Expose for other scripts if needed */
window.cartManager = {
  updateCartItem,
  removeCartItem,
  updateOrderSummary,
  updateCartBadge,
  showToast,
  getCSRFToken,
};
window.showToast = showToast;
