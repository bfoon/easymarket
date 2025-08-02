'use strict';

// Put this once near the top of your file
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
}

async function requireJson(response) {
  const ct = (response.headers.get('content-type') || '').toLowerCase();
  if (!ct.includes('application/json')) {
    const text = await response.text();
    // Throw with the first chunk so you can see what came back (login page, 403, etc.)
    throw new SyntaxError(
      `Non-JSON response (HTTP ${response.status}, ${ct}). First 300 chars:\n` +
      text.slice(0, 300)
    );
  }
  return response.json();
}


/* =========================================================
   Helpers & globals
========================================================= */
const slug = (s) => String(s || '').toLowerCase().trim().replace(/\s+/g, '-');

function getCSRFToken() {
  return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
}

function showToast(message, type = 'success', title = null) {
  const toast = document.createElement('div');
  toast.className = `position-fixed shadow`;
  toast.style.cssText = `
    top: 20px;
    right: 20px;
    z-index: 1055;
    min-width: 320px;
    max-width: 400px;
    border-radius: 12px;
    overflow: hidden;
    animation: slideInRight 0.25s ease;
  `;
  const bgColor = type === 'success' ? '#067d62' : type === 'error' ? '#c0392b' : '#0d6efd';
  const icon = type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle';
  const headerText = title || (type === 'success' ? 'Success' : type === 'error' ? 'Error' : 'Info');
  toast.innerHTML = `
    <div class="toast-header d-flex align-items-center justify-content-between" style="background:${bgColor};color:#fff;padding:.65rem .9rem;">
      <div class="d-flex align-items-center gap-2"><i class="fas ${icon}"></i><strong>${headerText}</strong></div>
      <button type="button" class="btn-close btn-close-white"></button>
    </div>
    <div class="toast-body" style="background:#fff;color:#232f3e;font-size:.95rem;padding:1rem;">${message}</div>
  `;
  document.body.appendChild(toast);
  toast.querySelector('.btn-close').addEventListener('click', () => {
    toast.style.animation = 'slideOutRight .25s ease';
    setTimeout(() => toast.remove(), 250);
  });
  setTimeout(() => {
    if (toast.parentElement) {
      toast.style.animation = 'slideOutRight .25s ease';
      setTimeout(() => toast.remove(), 250);
    }
  }, 4200);
}

function updateCartBadge(count) {
  const cartBadge = document.querySelector('.cart-count, .badge-cart, [data-cart-count], #cartCountBadge');
  if (cartBadge) {
    cartBadge.textContent = count;
    cartBadge.style.display = (+count > 0) ? 'inline-block' : 'none';
    cartBadge.style.transform = 'scale(1.25)';
    setTimeout(() => cartBadge.style.transform = 'scale(1)', 160);
  }
}

/* =========================================================
   Image Handler (Hover Zoom + Controls) — FIXED
========================================================= */
class ProductImageHandler {
  constructor() {
    this.img = document.getElementById('mainProductImage');
    this.container = this.img?.closest('.main-image-container') || null;

    // state
    this.isContainMode = false;
    this.zoomLevel = 1;
    this.minZoom = 1;
    this.maxZoom = 3;
    this.baseHoverScale = 1.8;   // scale used for hover
    this.hoverZoom = true;
    this.userZoom = false;       // true when user used wheel/button
    this._mouseInside = false;

    if (this.img && this.container) {
      this.setupOverlayControls();
      this.setupLoadHandlers();
      this.setupHoverZoom();
      this.setupWheelZoom();
      this.setupKeyboardShortcuts();
      this.setupTouch();
      this.applyScale();
    } else {
      console.warn('ProductImageHandler: main image or container not found.');
    }
  }

  setupOverlayControls() {
    let overlay = this.container.querySelector('.image-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'image-overlay';
      // Defensive inline styles in case CSS file hasn't loaded yet
      overlay.style.position = 'absolute';
      overlay.style.inset = '0';
      overlay.style.zIndex = '3';
      overlay.style.display = 'flex';
      overlay.style.alignItems = 'flex-start';
      overlay.style.justifyContent = 'space-between';
      overlay.style.padding = '.5rem';
      overlay.style.pointerEvents = 'none';
      this.container.appendChild(overlay);
    }

    overlay.innerHTML = `
      <div class="image-info" style="pointer-events:auto;">
        <small class="text-white">Hover to zoom</small>
      </div>
      <div class="image-controls d-flex gap-2" style="pointer-events:auto;">
        <button class="fit-toggle-btn btn btn-sm btn-light" title="Toggle fit" aria-label="Toggle fit">
          <i class="fas fa-expand-arrows-alt"></i>
        </button>
        <button class="fullscreen-btn btn btn-sm btn-light" title="Fullscreen" aria-label="Fullscreen">
          <i class="fas fa-expand"></i>
        </button>
        <button class="zoom-btn btn btn-sm btn-light" title="Toggle zoom" aria-label="Toggle zoom">
          <i class="fas fa-search-plus"></i>
        </button>
      </div>
    `;

    // Ensure overlay positions correctly
    const cs = getComputedStyle(this.container);
    if (cs.position === 'static') this.container.style.position = 'relative';

    overlay.querySelector('.fit-toggle-btn')?.addEventListener('click', (e) => {
      e.stopPropagation();
      this.toggleFit();
    });
    overlay.querySelector('.fullscreen-btn')?.addEventListener('click', (e) => {
      e.stopPropagation();
      this.fullscreen();
    });
    overlay.querySelector('.zoom-btn')?.addEventListener('click', (e) => {
      e.stopPropagation();
      this.toggleZoomButton();
    });
  }

  setupLoadHandlers() {
    const onLoad = () => {
      if (!this.img.naturalWidth || !this.img.naturalHeight) return;
      const ar = this.img.naturalWidth / this.img.naturalHeight;
      this.setContain(ar < 0.75);
    };
    if (this.img.complete) onLoad();
    this.img.addEventListener('load', onLoad);
    this.img.addEventListener('error', () => {
      const wrap = this.img.closest('.image-wrapper');
      if (!wrap) return;
      wrap.innerHTML = `
        <div class="image-error d-flex flex-column align-items-center justify-content-center" style="height:400px;background:#f8f9fa;color:#999;">
          <i class="fas fa-image fa-2x mb-2"></i>
          <div>Image not available</div>
        </div>
      `;
    });
  }

  setupHoverZoom() {
    const enter = () => {
      this._mouseInside = true;
      if (this.hoverZoom && !this.userZoom && this.zoomLevel === 1) {
        this.zoomLevel = this.baseHoverScale;
      }
      this.applyScale();
    };

    const move = (e) => {
      if (!this._mouseInside) return;
      const rect = this.img.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;
      this.img.style.transformOrigin = `${x}% ${y}%`;
    };

    const leave = () => {
      this._mouseInside = false;
      if (this.hoverZoom && !this.userZoom) {
        this.zoomLevel = 1;
      }
      this.applyScale();
    };

    this.container.addEventListener('mouseenter', enter);
    this.container.addEventListener('mousemove', move);
    this.container.addEventListener('mouseleave', leave);
  }

  setupWheelZoom() {
    this.container.addEventListener('wheel', (e) => {
      if (Math.abs(e.deltaY) < Math.abs(e.deltaX)) return;
      e.preventDefault();

      this.userZoom = true;
      const delta = e.deltaY > 0 ? -0.2 : 0.2;
      this.zoomLevel = Math.min(this.maxZoom, Math.max(this.minZoom, +(this.zoomLevel + delta).toFixed(2)));
      if (this.zoomLevel === 1) this.userZoom = false;

      this.applyScale();
      this.updateZoomIcon();
    }, { passive: false });
  }

  setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      if (['INPUT','TEXTAREA'].includes(e.target?.tagName)) return;
      if (e.key.toLowerCase() === 'f') {
        e.preventDefault(); this.toggleFit();
      } else if (e.key.toLowerCase() === 'z') {
        e.preventDefault(); this.toggleZoomButton();
      } else if (e.key === 'Enter') {
        if (this.container.contains(document.activeElement) || document.activeElement === document.body) {
          e.preventDefault(); this.fullscreen();
        }
      }
    });
  }

  setupTouch() {
    let lastTap = 0;
    this.img.addEventListener('touchend', () => {
      const now = Date.now();
      if (now - lastTap < 300) {
        this.userZoom = this.zoomLevel === 1;
        this.zoomLevel = this.zoomLevel === 1 ? 2 : 1;
        if (this.zoomLevel === 1) this.userZoom = false;
        this.applyScale();
        this.updateZoomIcon();
      }
      lastTap = now;
    }, { passive: true });
  }

  applyScale() {
    if (!this.img) return;
    this.img.style.transform = `scale(${this.zoomLevel})`;
    if (this.zoomLevel > 1) {
      this.img.style.cursor = 'zoom-out';
    } else {
      this.img.style.cursor = this.hoverZoom ? 'zoom-in' : 'default';
    }
  }

  updateZoomIcon() {
    const icon = document.querySelector('.zoom-btn i');
    if (icon) icon.className = this.zoomLevel > 1 ? 'fas fa-search-minus' : 'fas fa-search-plus';
  }

  toggleZoomButton() {
    if (this.zoomLevel === 1) {
      this.userZoom = true;
      this.zoomLevel = 2;
    } else {
      this.zoomLevel = 1;
      this.userZoom = false;
    }
    this.applyScale();
    this.updateZoomIcon();
  }

  toggleFit() {
    this.setContain(!this.isContainMode);
  }

  setContain(enable) {
    this.isContainMode = enable;
    if (enable) this.img.classList.add('contain-mode'); else this.img.classList.remove('contain-mode');
    const i = document.querySelector('.fit-toggle-btn i');
    if (i) i.className = enable ? 'fas fa-compress-arrows-alt' : 'fas fa-expand-arrows-alt';
  }

  fullscreen() {
    if (!this.img) return;

    // Bootstrap modal if present
    if (window.bootstrap && typeof bootstrap.Modal === 'function') {
      const modal = document.createElement('div');
      modal.className = 'modal fade';
      modal.innerHTML = `
        <div class="modal-dialog modal-xl modal-dialog-centered">
          <div class="modal-content bg-dark">
            <div class="modal-header border-0">
              <h5 class="modal-title text-white">${this.img.alt || 'Product Image'}</h5>
              <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body p-0 text-center">
              <img src="${this.img.src}" alt="${this.img.alt}" class="img-fluid" style="max-height:80vh;object-fit:contain;">
            </div>
          </div>
        </div>`;
      document.body.appendChild(modal);
      const bsModal = new bootstrap.Modal(modal);
      bsModal.show();
      modal.addEventListener('hidden.bs.modal', () => modal.remove());
      return;
    }

    // Fallback: Native Fullscreen API
    const fsTarget = this.img;
    if (fsTarget.requestFullscreen) fsTarget.requestFullscreen().catch(() => {});
    else if (fsTarget.webkitRequestFullscreen) fsTarget.webkitRequestFullscreen();
    else if (fsTarget.msRequestFullscreen) fsTarget.msRequestFullscreen();
  }

  // used by thumbnails
  changeImage(newSrc, alt = '') {
    if (!this.img) return;
    const container = this.container;
    container?.classList.add('loading');

    if (!this.userZoom) this.zoomLevel = 1;
    this.applyScale(); this.updateZoomIcon();

    this.img.onload = () => container?.classList.remove('loading');
    this.img.src = newSrc;
    if (alt) this.img.alt = alt;
  }
}

/* =========================================================
   Variant logic (Temu-like disabling)
========================================================= */
const VariantLogic = (() => {
  function getRequiredKeys() {
    const fromVariants = (window.PRODUCT_VARIANTS || []);
    if (fromVariants.length) {
      const s = new Set();
      fromVariants.forEach(v => Object.keys(v.features || {}).forEach(k => s.add(k)));
      return Array.from(s);
    }
    // fallback from DOM
    return Array.from(document.querySelectorAll('.feature-group .feature-options'))
      .map(g => g.getAttribute('data-feature'))
      .filter(Boolean);
  }

  function getSelection() {
    const sel = {};
    document.querySelectorAll('input.feature-input[type="radio"]:checked').forEach(r => sel[r.name] = r.value);
    return sel;
  }

  function isValueAllowed(featureKey, value, selection) {
    const variants = window.PRODUCT_VARIANTS || [];
    const partial = { ...selection, [featureKey]: value };
    return variants.some(v => {
      if (v.stock !== undefined && v.stock <= 0) return false;
      const feats = v.features || {};
      return Object.entries(partial).every(([k, val]) => feats[k] === val);
    });
  }

  function recomputeAvailability() {
    const selection = getSelection();
    const reqKeys = getRequiredKeys();
    const hasVariants = (window.PRODUCT_VARIANTS || []).length > 0 && reqKeys.length > 0;

    document.querySelectorAll('.feature-group .feature-options').forEach(group => {
      const key = group.getAttribute('data-feature');
      if (!key) return;

      group.querySelectorAll('input.feature-input[type="radio"]').forEach(input => {
        const label = input.closest('label, .feature-label-option') || input;
        if (!hasVariants) {
          input.disabled = false;
          label?.classList.remove('option-disabled');
          return;
        }
        const allowed = isValueAllowed(key, input.value, selection);
        input.disabled = !allowed;
        if (label) label.classList.toggle('option-disabled', !allowed);
        if (!allowed && input.checked) {
          input.checked = false;
        }
      });
    });
  }

  function selectionSummary() {
    const sel = getSelection();
    const display = document.getElementById('selectionDisplay');
    if (!display) return;
    if (Object.keys(sel).length === 0) {
      display.innerHTML = 'No selections made';
      return;
    }
    let html = '';
    Object.entries(sel).forEach(([k, v]) => {
      const name = k.charAt(0).toUpperCase() + k.slice(1);
      html += `<strong>${name}:</strong> ${v}<br>`;
    });
    display.innerHTML = html;
  }

  function syncFromImage(features) {
    if (!features || typeof features !== 'object') return;
    Object.entries(features).forEach(([k, v]) => {
      const id = `${k}_${slug(v)}`;
      const input = document.getElementById(id);
      if (input) {
        input.checked = true;
        input.dispatchEvent(new Event('change', { bubbles: true }));
        const fg = document.getElementById(`${k}FeatureGroup`);
        fg?.classList.add('highlighted');
        setTimeout(() => fg?.classList.remove('highlighted'), 900);
      }
    });
  }

  return { getRequiredKeys, getSelection, recomputeAvailability, selectionSummary, syncFromImage };
})();

/* =========================================================
   Thumbnails gallery (hooks image + features)
========================================================= */
class ThumbnailGallery {
  constructor(imageHandler) {
    this.imageHandler = imageHandler;
    this.gallery = document.querySelector('.thumbnail-gallery');
    if (!this.gallery) return;
    this.bind();
    this.setupWheelScroll();
    this.maybeAddNavArrows();
  }

  bind() {
    this.gallery.querySelectorAll('.thumbnail-item').forEach(btn => {
      btn.setAttribute('tabindex', '0');
      btn.addEventListener('click', () => this.select(btn));
      btn.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.select(btn); }
      });
    });
  }

  select(btn) {
    const newSrc = btn.dataset.image;
    let feats = {};
    try { feats = JSON.parse(btn.dataset.features || '{}'); } catch {}
    if (newSrc && this.imageHandler) this.imageHandler.changeImage(newSrc);

    this.gallery.querySelectorAll('.thumbnail-item').forEach(i => {
      i.classList.remove('active'); i.setAttribute('aria-selected', 'false');
    });
    btn.classList.add('active'); btn.setAttribute('aria-selected', 'true');

    if (Object.keys(feats).length) {
      VariantLogic.syncFromImage(feats);
    }
  }

  setupWheelScroll() {
    this.gallery.addEventListener('wheel', (e) => {
      if (Math.abs(e.deltaX) < Math.abs(e.deltaY)) {
        e.preventDefault();
        this.gallery.scrollBy({ left: e.deltaY > 0 ? 120 : -120, behavior: 'smooth' });
      }
    }, { passive: false });
  }

  maybeAddNavArrows() {
    const thumbs = this.gallery.querySelectorAll('.thumbnail-item');
    if (thumbs.length <= 5) return;
    const container = this.gallery.parentElement;
    const prevBtn = document.createElement('button');
    prevBtn.className = 'thumbnail-nav-btn prev-btn';
    prevBtn.innerHTML = '<i class="fas fa-chevron-left"></i>';
    prevBtn.setAttribute('aria-label', 'Previous images');
    const nextBtn = document.createElement('button');
    nextBtn.className = 'thumbnail-nav-btn next-btn';
    nextBtn.innerHTML = '<i class="fas fa-chevron-right"></i>';
    nextBtn.setAttribute('aria-label', 'Next images');
    container.style.position = 'relative';
    container.appendChild(prevBtn); container.appendChild(nextBtn);
    const style = document.createElement('style');
    style.textContent = `
      .thumbnail-nav-btn{position:absolute;top:50%;transform:translateY(-50%);background:rgba(255,255,255,.95);border:1px solid #dee2e6;border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:10}
      .thumbnail-nav-btn:hover{background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.15)}
      .prev-btn{left:-15px} .next-btn{right:-15px}
    `;
    document.head.appendChild(style);
    prevBtn.addEventListener('click', () => this.gallery.scrollBy({ left: -150, behavior: 'smooth' }));
    nextBtn.addEventListener('click', () => this.gallery.scrollBy({ left: 150, behavior: 'smooth' }));
  }
}

/* =========================================================
   Cart / Buy-now (matches your Django view)
========================================================= */
function getSelectedFeaturesForCart() {
  const selected = {};
  document.querySelectorAll('input.feature-input[type="radio"]:checked').forEach(input => {
    if (input.name) selected[input.name] = input.value;
  });
  return selected;
}

function addToCart(productId, btn) {
  if (!productId) return;
  const original = btn?.innerHTML;

  (async () => {
    try {
      // Ensure all required features chosen (when variants exist)
      const selection = getSelectedFeaturesForCart();
      const req = VariantLogic.getRequiredKeys();
      if (req.length) {
        const missing = req.filter(k => !selection[k]);
        if (missing.length) {
          missing.forEach(k => {
            const fg = document.getElementById(`${k}FeatureGroup`);
            fg?.classList.add('highlighted');
            setTimeout(() => fg?.classList.remove('highlighted'), 900);
          });
          showToast(`Please select: ${missing.join(', ')}`, 'error');
          return;
        }
      }

      const qty = Math.max(1, Math.min(99, parseInt(document.getElementById('quantity')?.value || '1', 10) || 1));

      if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Adding...'; }

      const body = new URLSearchParams();
      body.append('quantity', String(qty));
      body.append('features', JSON.stringify(selection)); // <-- your view expects this
      body.append('csrfmiddlewaretoken', getCSRFToken()); // harmless with csrf_exempt

      const resp = await fetch(`/add-to-cart/${productId}/`, {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
          'Content-Type': 'application/x-www-form-urlencoded'
        },
        body: body.toString()
      });

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      if (data.success) {
        if (btn) {
          btn.innerHTML = '<i class="fas fa-check me-1"></i> Added!';
          btn.classList.remove('btn-outline-primary');
          btn.classList.add('btn-success');
        }
        updateCartBadge(data.cart_count ?? 0);
        showToast(data.message || 'Added to cart', 'success', 'Added to Cart');
        setTimeout(() => {
          if (btn) {
            btn.innerHTML = original || '<i class="fas fa-cart-plus me-1"></i> Add to Cart';
            btn.classList.remove('btn-success');
            btn.classList.add('btn-outline-primary');
            btn.disabled = false;
          }
        }, 1200);
      } else {
        const msg = data.message || data.error || 'Failed to add to cart.';
        showToast(msg, 'error');
        if (btn) { btn.innerHTML = original || '<i class="fas fa-cart-plus me-1"></i> Add to Cart'; btn.disabled = false; }
      }
    } catch (e) {
      console.error('addToCart error:', e);
      showToast('Error adding to cart.', 'error');
      if (btn) { btn.innerHTML = original || '<i class="fas fa-cart-plus me-1"></i> Add to Cart'; btn.disabled = false; }
    }
  })();
}

function buyNow(productId) {
  const selected = getSelectedFeaturesForCart();
  const req = VariantLogic.getRequiredKeys();
  if (req.length) {
    const missing = req.filter(k => !selected[k]);
    if (missing.length) {
      missing.forEach(k => {
        const fg = document.getElementById(`${k}FeatureGroup`);
        fg?.classList.add('highlighted');
        setTimeout(() => fg?.classList.remove('highlighted'), 900);
      });
      showToast(`Please select: ${missing.join(', ')}`, 'error');
      return;
    }
  }
  const quantityInput = document.getElementById('quantity');
  const qty = Math.max(1, Math.min(99, parseInt(quantityInput?.value || '1', 10) || 1));

  const form = document.getElementById('buyNowForm');
  if (!form) return;

  // cleanup old
  form.querySelectorAll('input[name="features"], input[name="quantity"], input[name="product"]').forEach(n => n.remove());

  const f = document.createElement('input');
  f.type = 'hidden'; f.name = 'features'; f.value = JSON.stringify(selected);
  form.appendChild(f);

  const q = document.createElement('input');
  q.type = 'hidden'; q.name = 'quantity'; q.value = String(qty);
  form.appendChild(q);

  const p = document.createElement('input');
  p.type = 'hidden'; p.name = 'product'; p.value = String(productId);
  form.appendChild(p);

  form.submit();
}

/* =========================================================
   Misc utilities
========================================================= */
function changeQuantity(change) {
  const quantityInput = document.getElementById('quantity');
  if (quantityInput) {
    const curr = parseInt(quantityInput.value || '1', 10) || 1;
    const min = parseInt(quantityInput.min || '1', 10) || 1;
    const max = parseInt(quantityInput.max || '99', 10) || 99;
    const next = Math.max(min, Math.min(max, curr + change));
    quantityInput.value = next;
  }
}

function toggleWishlist(productId) {
  const icon = document.getElementById(`wishlistIcon-${productId}`);
  fetch(`/wishlist/toggle/${productId}/`, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCSRFToken(), 'X-Requested-With': 'XMLHttpRequest' }
  }).then(r => r.json()).then(data => {
    if (data.success) {
      if (data.status === 'added') { icon?.classList.remove('far'); icon?.classList.add('fas', 'text-danger'); }
      else { icon?.classList.remove('fas', 'text-danger'); icon?.classList.add('far'); }
      showToast(data.message || 'Wishlist updated', 'success');
    } else {
      showToast(data.error || 'Something went wrong.', 'error');
    }
  }).catch(err => {
    console.error(err); showToast('Error updating wishlist', 'error');
  });
}

/* =========================================================
   Image <-> Feature sync (thumbnails hook)
========================================================= */
function changeMainImageWithFeatures(thumbnail) {
  const imageUrl = thumbnail.dataset.image;
  let features = {};
  try { features = JSON.parse(thumbnail.dataset.features || '{}'); } catch {}

  if (window.imageHandler && imageUrl) window.imageHandler.changeImage(imageUrl);

  document.querySelectorAll('.thumbnail-item').forEach(item => {
    item.classList.remove('active'); item.setAttribute('aria-selected', 'false');
  });
  thumbnail.classList.add('active'); thumbnail.setAttribute('aria-selected', 'true');

  if (Object.keys(features).length) VariantLogic.syncFromImage(features);
}

/* =========================================================
   Init
========================================================= */
document.addEventListener('DOMContentLoaded', () => {
  // small animation + states
  const style = document.createElement('style');
  style.textContent = `
    @keyframes slideInRight{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
    @keyframes slideOutRight{from{transform:translateX(0);opacity:1}to{transform:translateX(100%);opacity:0}}
    .option-disabled{opacity:.45;filter:grayscale(.6);pointer-events:none}
    .feature-group.highlighted{outline:2px dashed var(--bs-primary,#0d6efd);outline-offset:4px}
  `;
  document.head.appendChild(style);

  // Image Handler
  window.imageHandler = new ProductImageHandler();

  // Thumbnails
  window.thumbnailGallery = new ThumbnailGallery(window.imageHandler);

  // Feature change listeners
  document.querySelectorAll('input.feature-input[type="radio"]').forEach(input => {
    input.addEventListener('change', () => {
      VariantLogic.recomputeAvailability();
      VariantLogic.selectionSummary();
    });
  });

  // Initial availability + summary
  VariantLogic.recomputeAvailability();
  VariantLogic.selectionSummary();

  // Expose globals for template buttons
  window.addToCart = addToCart;
  window.buyNow = buyNow;
  window.changeQuantity = changeQuantity;
  window.toggleWishlist = toggleWishlist;
  window.changeMainImageWithFeatures = changeMainImageWithFeatures;

  console.log('Product detail JS initialized');
});
