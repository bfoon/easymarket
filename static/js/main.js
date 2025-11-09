// ==============================================
// UTILITIES
// ==============================================

// CSRF utilities (shared with cart.js style)
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
function getCSRFToken() {
  return (
    document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
    document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
    getCookie('csrftoken') ||
    ''
  );
}

// Simple debounce
function debounce(fn, wait = 250) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(null, args), wait);
  };
}

// Universal toast (lightweight; one-off DOM node)
function showToast(message, type = 'success', title = null) {
  const toast = document.createElement('div');
  toast.className = 'position-fixed shadow';
  toast.style.cssText = `
    top: 20px; right: 20px; z-index: 1055;
    min-width: 320px; max-width: 400px;
    border-radius: 12px; overflow: hidden;
    animation: slideInRight 0.25s ease;
  `;

  const bgColor = type === 'success' ? '#067d62'
                : type === 'error'   ? '#c0392b'
                : '#17a2b8';
  const iconClass = type === 'success' ? 'fa-check-circle'
                  : type === 'error'   ? 'fa-exclamation-circle'
                  : 'fa-info-circle';
  const headerText = title || (type === 'success' ? 'Success' : type === 'error' ? 'Error' : 'Info');

  toast.innerHTML = `
    <div class="toast-header d-flex align-items-center justify-content-between"
         style="background-color:${bgColor}; color:#fff; padding:0.75rem 1rem;">
      <div class="d-flex align-items-center">
        <i class="fas ${iconClass} me-2"></i>
        <strong>${headerText}</strong>
      </div>
      <button type="button" class="btn-close btn-close-white" style="margin-left:auto;"></button>
    </div>
    <div class="toast-body" style="background:#fff; color:#232f3e; font-size:0.95rem; padding:1rem;">
      ${message}
    </div>
  `;

  document.body.appendChild(toast);

  // Dismiss
  const closeBtn = toast.querySelector('.btn-close');
  closeBtn?.addEventListener('click', () => {
    toast.style.animation = 'slideOutRight 0.25s ease';
    setTimeout(() => toast.remove(), 250);
  });

  // Auto-remove
  setTimeout(() => {
    if (toast.parentElement) {
      toast.style.animation = 'slideOutRight 0.25s ease';
      setTimeout(() => toast.remove(), 250);
    }
  }, 5000);
}

// Update cart count in nav + bubble
function updateCartCount(count) {
  const countBadge = document.getElementById('cartCountBadge');
  if (countBadge) {
    countBadge.textContent = count;
    countBadge.style.display = count > 0 ? 'inline-block' : 'none';
    countBadge.style.transform = 'scale(1.3)';
    setTimeout(() => (countBadge.style.transform = 'scale(1)'), 180);
  }
  // If cart.js is loaded, sync its badge too
  if (window.cartManager?.updateCartBadge) {
    window.cartManager.updateCartBadge(Number(count || 0));
  }
}

// ==============================================
// SEARCH
// ==============================================

function highlightText(text, searchTerm) {
  if (!searchTerm) return text;
  try {
    const regex = new RegExp(`(${searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return text.replace(regex, '<span class="highlight">$1</span>');
  } catch {
    return text;
  }
}

function filterProducts() {
  const headerSearch = document.querySelector('.navbar .search-bar');
  const mobileSearch = document.getElementById('mobileSearchInput');
  const searchInput  = document.getElementById('searchInput');

  const searchTerm = (
    headerSearch?.value ||
    mobileSearch?.value ||
    searchInput?.value ||
    ''
  ).toLowerCase();

  const products = document.querySelectorAll('.product-item');
  let visibleCount = 0;

  products.forEach((product) => {
    const name = product.dataset.name?.toLowerCase() || '';
    const desc = product.querySelector('.card-text')?.textContent?.toLowerCase() || '';

    const match = searchTerm === '' || name.includes(searchTerm) || desc.includes(searchTerm);
    product.style.display = match ? '' : 'none';
    if (match) {
      visibleCount += 1;
      const titleEl = product.querySelector('.card-title');
      if (titleEl) {
        // Reset then highlight to avoid nested spans
        titleEl.textContent = product.dataset.name || titleEl.textContent;
        if (searchTerm) titleEl.innerHTML = highlightText(titleEl.textContent, searchTerm);
      }
    }
  });

  const countEl = document.querySelector('.container h2 + p');
  if (countEl) {
    countEl.textContent = `${visibleCount} product${visibleCount === 1 ? '' : 's'} found`;
  }
}

// ==============================================
// PRODUCT GRID
// ==============================================

function sortProducts(type) {
  const container = document.getElementById('productsContainer');
  if (!container) return;

  const products = Array.from(container.querySelectorAll('.product-item'));
  products.sort((a, b) => {
    const pa = parseFloat(a.dataset.price || '0');
    const pb = parseFloat(b.dataset.price || '0');
    const na = (a.dataset.name || '');
    const nb = (b.dataset.name || '');

    switch (type) {
      case 'price-low':  return pa - pb;
      case 'price-high': return pb - pa;
      case 'name':       return na.localeCompare(nb);
      default:           return 0;
    }
  });

  products.forEach((p) => container.appendChild(p));
}

function setViewMode(mode) {
  const container = document.getElementById('productsContainer');
  const gridBtn = document.getElementById('gridView');
  const listBtn = document.getElementById('listView');
  if (!container) return;

  if (mode === 'list') {
    container.classList.add('list-view');
    listBtn?.classList.add('active');
    gridBtn?.classList.remove('active');
  } else {
    container.classList.remove('list-view');
    gridBtn?.classList.add('active');
    listBtn?.classList.remove('active');
  }
}

// ==============================================
// QUICK VIEW (single, id-based)
// ==============================================

function quickView(productId) {
  const modalEl = document.getElementById('quickViewModal');
  const content = document.getElementById('quickViewContent');

  if (!modalEl || !content) return;

  if (window.bootstrap?.Modal) {
    new bootstrap.Modal(modalEl).show();
  } else {
    modalEl.style.display = 'block';
  }

  content.innerHTML = `
    <div class="text-center py-4">
      <div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>
    </div>
  `;

  fetch(`/product/${productId}/quick-view/`)
    .then((r) => {
      if (!r.ok) throw new Error('Failed to fetch product details');
      return r.text();
    })
    .then((html) => {
      content.innerHTML = html;

      // bind thumbs
      content.querySelectorAll('.quickview-thumb').forEach((thumb) => {
        thumb.addEventListener('click', () => {
          const full = thumb.dataset.full;
          const main = content.querySelector('#mainPreviewImage');
          if (main && full) main.src = full;

          content.querySelectorAll('.quickview-thumb').forEach((img) => img.classList.remove('border-primary'));
          thumb.classList.add('border-primary');
        });
      });
    })
    .catch(() => {
      content.innerHTML = `
        <div class="text-center p-4">
          <h5>Unable to load product details.</h5>
          <p>Please try again later.</p>
          <a href="/product/${productId}/" class="btn btn-primary">View Full Product</a>
        </div>
      `;
    });
}

// ==============================================
// CART – ADD TO CART (works with social cart server rules)
// ==============================================

function addToCart(productId, button) {
  if (!productId) return;

  const originalHTML = button?.innerHTML;

  // Gather selected features from radio/select groups with data-feature name
  const selectedFeatures = {};
  document.querySelectorAll('[data-feature]').forEach((group) => {
    const feature = group.getAttribute('data-feature');
    let value = null;

    // radios
    const chosenRadio = group.querySelector('input[type="radio"]:checked');
    if (chosenRadio) value = chosenRadio.value || chosenRadio.getAttribute('data-value');

    // selects
    const select = group.querySelector('select');
    if (!value && select) value = select.value;

    // fallback badge text
    if (!value) {
      const active = group.querySelector('.active,[aria-pressed="true"]');
      if (active) value = active.dataset.value || active.textContent?.trim();
    }

    if (feature && value) selectedFeatures[feature] = value;
  });

  const body = new URLSearchParams();
  body.append('features', JSON.stringify(selectedFeatures));

  if (button) {
    button.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Adding...';
    button.disabled = true;
  }

  fetch(`/add-to-cart/${productId}/`, {
    method: 'POST',
    headers: {
      'X-CSRFToken': getCSRFToken(),
      'Accept': 'application/json',
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-Requested-With': 'XMLHttpRequest',
    },
    body: body.toString(),
  })
    .then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        const msg = data?.error || data?.message || `HTTP ${r.status}`;
        throw new Error(msg);
      }
      return data;
    })
    .then((data) => {
      if (data.success) {
        if (button) {
          button.innerHTML = '<i class="fas fa-check me-1"></i> Added!';
          button.classList.remove('btn-outline-primary');
          button.classList.add('btn-success');
        }

        showToast(`${data.product_name || 'Item'} added to cart.`, 'success', 'Added to Cart');
        if (typeof data.cart_count !== 'undefined') updateCartCount(data.cart_count);
      } else {
        showToast(data.error || 'Failed to add to cart.', 'error');
      }
    })
    .catch((err) => {
      console.error('Add-to-cart error:', err);
      showToast(err.message || 'Error adding to cart.', 'error');
    })
    .finally(() => {
      if (button) {
        setTimeout(() => {
          button.innerHTML = originalHTML || '<i class="fas fa-cart-plus me-1"></i> Add to Cart';
          button.disabled = false;
          button.classList.remove('btn-success');
          button.classList.add('btn-outline-primary');
        }, 1200);
      }
    });
}

// ==============================================
// WISHLIST
// ==============================================

function addToWishlist(productId, button) {
  const heart = button?.querySelector('i') || button;
  if (!heart) return;
  const original = heart.className;

  fetch(`/wishlist/toggle/${productId}/`, {
    method: 'POST',
    headers: {
      'X-CSRFToken': getCSRFToken(),
      'X-Requested-With': 'XMLHttpRequest',
    },
  })
    .then(async (r) => {
      const isJSON = r.headers.get('content-type')?.includes('application/json');
      const data = isJSON ? await r.json() : {};
      if (!r.ok) throw new Error(data?.error || `HTTP ${r.status}`);
      return data;
    })
    .then((data) => {
      if (data.success) {
        if (data.status === 'added') {
          heart.classList.remove('far');
          heart.classList.add('fas', 'text-danger');
          showToast(data.message || 'Added to wishlist!', 'success');
        } else {
          heart.classList.remove('fas', 'text-danger');
          heart.classList.add('far');
          showToast(data.message || 'Removed from wishlist!', 'success');
        }
      } else {
        showToast(data.error || 'Unable to update wishlist.', 'error');
        heart.className = original;
      }
    })
    .catch((err) => {
      console.error('Wishlist error:', err);
      heart.className = original;
      showToast('An error occurred while updating your wishlist.', 'error');
    });
}

// ==============================================
// PAGINATION (stubbed)
// ==============================================

function loadMoreProducts() {
  const btn = document.getElementById('loadMoreBtn');
  if (!btn) return;
  const original = btn.innerHTML;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Loading...';
  btn.disabled = true;

  // Replace with real AJAX when backend route is ready
  setTimeout(() => {
    btn.innerHTML = original;
    btn.disabled = false;
  }, 1500);
}

// ==============================================
// SCROLL TO TOP
// ==============================================

function initScrollToTop() {
  const btn = document.getElementById('scrollToTopBtn');
  if (!btn) return;

  btn.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  window.addEventListener('scroll', () => {
    btn.style.display = window.pageYOffset > 300 ? 'block' : 'none';
  });
}

// ==============================================
/* INIT */
// ==============================================

document.addEventListener('DOMContentLoaded', () => {
  // Debounced search on multiple inputs
  const inputs = [
    document.querySelector('.navbar .search-bar'),
    document.getElementById('mobileSearchInput'),
    document.getElementById('searchInput'),
  ].filter(Boolean);

  const runFilter = debounce(() => filterProducts(), 200);

  inputs.forEach((el) => {
    el.addEventListener('input', () => {
      if (el.value.length >= 2 || el.value.length === 0) runFilter();
    });
  });

  // Click search buttons
  document.querySelectorAll('.navbar .btn-primary, .mobile-search-btn').forEach((btn) => {
    btn.addEventListener('click', filterProducts);
  });

  // Bootstrap tooltips (if available)
  if (window.bootstrap?.Tooltip) {
    const triggers = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"], [title]'));
    triggers.forEach((el) => new bootstrap.Tooltip(el));
  }

  // Scroll to top
  initScrollToTop();

  // Animations / helpers CSS
  const style = document.createElement('style');
  style.textContent = `
    @keyframes slideInRight { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    @keyframes slideOutRight { from { transform: translateX(0); opacity: 1; } to { transform: translateX(100%); opacity: 0; } }
    .highlight { background:#fff3cd; color:#856404; padding:0.1em 0.2em; border-radius:0.2em; }
    #scrollToTopBtn {
      display:none; position:fixed; bottom:20px; right:20px; z-index:1000;
      background:#007bff; color:#fff; border:none; border-radius:50%;
      width:50px; height:50px; cursor:pointer; box-shadow:0 2px 10px rgba(0,0,0,0.2);
      transition:all .3s ease;
    }
    #scrollToTopBtn:hover { background:#0056b3; transform: translateY(-2px); }
  `;
  document.head.appendChild(style);
});

// ==============================================
// EXPORTS
// ==============================================
window.filterProducts   = filterProducts;
window.sortProducts     = sortProducts;
window.setViewMode      = setViewMode;
window.quickView        = quickView;
window.addToCart        = addToCart;
window.addToWishlist    = addToWishlist;
window.loadMoreProducts = loadMoreProducts;
window.showToast        = showToast;
window.getCSRFToken     = getCSRFToken;
window.updateCartCount  = updateCartCount;
