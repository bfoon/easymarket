/**
 * Enhanced Message & Review System - FIXED SELECTORS + JSON + CSRF
 * - Chat open/close matches template classes: .btn-chat / .chat-close
 * - All AJAX expects JSON via requireJson() (clear error when HTML/redirect arrives)
 * - All POSTs send X-CSRFToken header (cookie fallback)
 */

'use strict';

/* ===================================
   Helpers
=================================== */
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
}

async function requireJson(response) {
  const ct = (response.headers.get('content-type') || '').toLowerCase();
  if (!ct.includes('application/json')) {
    const snippet = await response.text();
    throw new SyntaxError(
      `Non-JSON response (status ${response.status}, content-type: ${ct}). ` +
      `First 300 chars:\n${snippet.slice(0, 300)}`
    );
  }
  return response.json();
}

/* ===================================
   REVIEW SYSTEM
=================================== */
const ReviewSystem = {
  config: {
    productId: null,
    csrfToken: '',
    urls: { submit: '', delete: '', comment: '', load: '' },
    currentPage: 1,
    hasMore: true,
    isLoading: false
  },
  state: {
    selectedRating: 0,
    reviewCount: 0,
    averageRating: 0,
    userReview: null,
    loadedReviews: new Set()
  },

  init(config = {}) {
    this.config = { ...this.config, ...config };
    this.loadConfiguration();
    this.bindEvents();
    this.loadInitialReviews();
    console.log('Review System initialized for product:', this.config.productId);
  },

  loadConfiguration() {
    if (window.PRODUCT_ID) this.config.productId = window.PRODUCT_ID;
    if (window.CSRF_TOKEN) this.config.csrfToken = window.CSRF_TOKEN;
    if (window.REVIEWS_SUBMIT_URL) this.config.urls.submit = window.REVIEWS_SUBMIT_URL;
    if (window.REVIEWS_DELETE_URL) this.config.urls.delete = window.REVIEWS_DELETE_URL;
    if (window.REVIEWS_COMMENT_URL) this.config.urls.comment = window.REVIEWS_COMMENT_URL;
    if (window.REVIEWS_LIST_URL) this.config.urls.load = window.REVIEWS_LIST_URL;
  },

  bindEvents() {
    this.bindStarRatingEvents();
    this.bindReviewFormEvents();
    this.bindReviewActionsEvents();
    this.bindLoadMoreEvents();
    this.bindCommentEvents();
    this.bindKeyboardEvents();
  },

  /* ---------- Star rating ---------- */
  bindStarRatingEvents() {
    const starContainer = document.querySelector('.star-rating, .temu-star-rating');
    if (!starContainer) return;

    const stars = starContainer.querySelectorAll('.star-btn, .temu-star-input');
    stars.forEach((star, index) => {
      const rating = parseInt(star.dataset.rating) || index + 1;
      star.addEventListener('click', (e) => { e.preventDefault(); this.setRating(rating); });
      star.addEventListener('mouseenter', () => this.highlightStars(rating, true));
      star.addEventListener('mouseleave', () => this.highlightStars(this.state.selectedRating));
      star.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.setRating(rating); }
      });
    });

    starContainer.addEventListener('mouseleave', () => this.highlightStars(this.state.selectedRating));
  },

  setRating(r) {
    this.state.selectedRating = r;
    const ratingInput = document.getElementById('rating-input') || document.getElementById('ratingValue');
    if (ratingInput) ratingInput.value = r;
    this.highlightStars(r);
    this.showRatingText(r);
  },

  highlightStars(rating, isHover = false) {
    const stars = document.querySelectorAll('.star-btn, .temu-star-input');
    stars.forEach((star, idx) => {
      const starRating = parseInt(star.dataset.rating) || idx + 1;
      const icon = star.querySelector('i') || star;
      if (starRating <= rating) {
        icon.className = 'fas fa-star';
        star.classList.add(isHover ? 'hover' : 'active');
        if (!isHover) star.classList.remove('hover');
      } else {
        icon.className = 'far fa-star';
        star.classList.remove('active', 'hover');
      }
    });
  },

  showRatingText(rating) {
    const map = {1:'Poor',2:'Fair',3:'Good',4:'Very Good',5:'Excellent'};
    let el = document.querySelector('.rating-text-display');
    if (!el) {
      el = document.createElement('div');
      el.className = 'rating-text-display mt-2 text-muted';
      const starContainer = document.querySelector('.star-rating, .temu-star-rating');
      starContainer?.parentNode?.insertBefore(el, starContainer.nextSibling);
    }
    el.textContent = map[rating] || '';
    el.style.opacity = rating > 0 ? '1' : '0';
  },

  /* ---------- Review form ---------- */
  bindReviewFormEvents() {
    const form = document.getElementById('review-form') || document.getElementById('reviewForm');
    if (!form) return;
    form.addEventListener('submit', (e) => { e.preventDefault(); this.submitReview(form); });
    const txt = form.querySelector('textarea[name="comment"]');
    if (txt) this.setupCharacterCounter(txt);
    form.querySelectorAll('input, textarea').forEach(i => i.addEventListener('blur', () => this.validateField(i)));
  },

  setupCharacterCounter(textarea) {
    const max = parseInt(textarea.getAttribute('maxlength')) || 1000;
    let counter = textarea.parentNode.querySelector('.character-counter');
    if (!counter) {
      counter = document.createElement('div');
      counter.className = 'character-counter text-muted small mt-1';
      textarea.parentNode.appendChild(counter);
    }
    const update = () => {
      const remaining = max - textarea.value.length;
      counter.textContent = `${remaining} characters remaining`;
      counter.className = `character-counter small mt-1 ${remaining < 50 ? 'text-warning' : 'text-muted'}`;
    };
    textarea.addEventListener('input', update);
    update();
  },

  validateField(field) {
    const value = field.value.trim();
    let ok = true, msg = '';
    if (field.name === 'rating' || field.id === 'rating-input') {
      ok = value && (+value >= 1 && +value <= 5); msg = ok ? '' : 'Please select a rating';
    }
    if (field.name === 'comment') {
      ok = value.length >= 10; msg = ok ? '' : 'Comment must be at least 10 characters long';
    }
    this.showFieldValidation(field, ok, msg);
    return ok;
  },

  showFieldValidation(field, ok, msg) {
    field.classList.remove('is-valid', 'is-invalid');
    field.parentNode.querySelector('.invalid-feedback, .valid-feedback')?.remove();
    if (msg) {
      field.classList.add(ok ? 'is-valid' : 'is-invalid');
      const fb = document.createElement('div');
      fb.className = ok ? 'valid-feedback' : 'invalid-feedback';
      fb.textContent = msg;
      field.parentNode.appendChild(fb);
    }
  },

  async submitReview(form) {
    if (this.config.isLoading) return;
    try {
      if (!this.validateForm(form)) { this.showNotification('Please correct the errors below', 'error'); return; }
      this.config.isLoading = true;
      this.setSubmitButtonLoading(true);

      const fd = new FormData(form);
      if (this.config.productId) fd.set('product_id', this.config.productId);

      const res = await this.fetchWithTimeout(this.config.urls.submit, {
        method: 'POST',
        body: fd,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': this.config.csrfToken || getCookie('csrftoken'),
          'Accept': 'application/json'
        }
      });

      const data = await requireJson(res);
      if (data.success) this.handleReviewSubmitSuccess(data, form);
      else throw new Error(data.error || 'Failed to submit review');

    } catch (err) {
      console.error('Submit review error:', err);
      this.showNotification(err.message || 'Error submitting review', 'error');
    } finally {
      this.config.isLoading = false;
      this.setSubmitButtonLoading(false);
    }
  },

  validateForm(form) {
    let ok = true;
    form.querySelectorAll('input[required], textarea[required]').forEach(i => { if (!this.validateField(i)) ok = false; });
    if (this.state.selectedRating === 0) { this.showNotification('Please select a rating', 'warning'); ok = false; }
    return ok;
  },

  handleReviewSubmitSuccess(data, form) {
    if (data.new_avg) this.state.averageRating = parseFloat(data.new_avg);
    if (data.total_reviews) this.state.reviewCount = parseInt(data.total_reviews);
    this.updateRatingDisplay(data);
    this.resetReviewForm(form);
    this.loadReviews(1);
    this.showNotification(data.message || 'Review submitted successfully!', 'success');
    setTimeout(() => document.getElementById('reviews-container')?.scrollIntoView({ behavior: 'smooth' }), 500);
  },

  resetReviewForm(form) {
    form.reset();
    this.state.selectedRating = 0;
    this.highlightStars(0);
    this.showRatingText(0);
    form.querySelectorAll('.is-valid, .is-invalid').forEach(f => f.classList.remove('is-valid', 'is-invalid'));
    form.querySelectorAll('.invalid-feedback, .valid-feedback').forEach(fb => fb.remove());
  },

  setSubmitButtonLoading(loading) {
    const btn = document.querySelector('#review-form button[type="submit"], #reviewForm button[type="submit"]');
    if (!btn) return;
    const spinner = btn.querySelector('.spinner-border, #submit-spinner');
    const text = btn.querySelector('.submit-text') || btn;
    if (loading) {
      btn.disabled = true;
      spinner?.classList.remove('d-none');
      if (text !== btn) text.textContent = 'Submitting...';
    } else {
      btn.disabled = false;
      spinner?.classList.add('d-none');
      if (text !== btn) text.textContent = 'Submit Review';
    }
  },

  /* ---------- Review list & actions ---------- */
  bindReviewActionsEvents() {
    document.addEventListener('click', (e) => {
      if (e.target.matches('.delete-review-btn') || e.target.closest('.delete-review-btn')) {
        e.preventDefault();
        const btn = e.target.closest('.delete-review-btn');
        const id = btn.dataset.reviewId;
        if (id) this.confirmDeleteReview(id, btn);
      }
      if (e.target.matches('.like-review-btn') || e.target.closest('.like-review-btn')) {
        e.preventDefault();
        const btn = e.target.closest('.like-review-btn');
        const id = btn.dataset.reviewId;
        if (id) this.toggleReviewLike(id, btn);
      }
      if (e.target.matches('.report-review-btn') || e.target.closest('.report-review-btn')) {
        e.preventDefault();
        const btn = e.target.closest('.report-review-btn');
        const id = btn.dataset.reviewId;
        if (id) this.reportReview(id);
      }
    });
  },

  confirmDeleteReview(id, button) {
    const m = this.createConfirmModal(
      'Delete Review',
      'Are you sure you want to delete this review? This action cannot be undone.',
      () => this.deleteReview(id, button)
    );
    m.show();
  },

  async deleteReview(reviewId, button) {
    try {
      const res = await this.fetchWithTimeout(this.config.urls.delete, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': this.config.csrfToken || getCookie('csrftoken'),
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json'
        },
        body: `review_id=${encodeURIComponent(reviewId)}`
      });

      const data = await requireJson(res);

      if (data.success) {
        const card = button.closest('.review-card, .review-item');
        if (card) { card.style.animation = 'fadeOut .3s ease'; setTimeout(() => card.remove(), 300); }
        this.updateRatingDisplay(data);
        this.showNotification(data.message || 'Review deleted successfully', 'success');
      } else {
        throw new Error(data.error || 'Failed to delete review');
      }
    } catch (err) {
      console.error('Delete review error:', err);
      this.showNotification(err.message || 'Error deleting review', 'error');
    }
  },

  async toggleReviewLike(reviewId, button) {
    try {
      const res = await this.fetchWithTimeout('/reviews/like/', {
        method: 'POST',
        headers: {
          'Content-Type':'application/x-www-form-urlencoded',
          'X-CSRFToken': this.config.csrfToken || getCookie('csrftoken'),
          'X-Requested-With':'XMLHttpRequest',
          'Accept': 'application/json'
        },
        body: `review_id=${encodeURIComponent(reviewId)}`
      });

      const data = await requireJson(res);

      if (data.success) {
        const icon = button.querySelector('i'); const count = button.querySelector('.like-count');
        if (data.liked) { icon.className='fas fa-thumbs-up'; button.classList.add('liked'); }
        else { icon.className='far fa-thumbs-up'; button.classList.remove('liked'); }
        if (count) count.textContent = data.likes_count;
        button.style.transform='scale(1.1)'; setTimeout(()=>button.style.transform='scale(1)',150);
      } else {
        throw new Error(data.error || 'Failed to update like');
      }
    } catch (err) {
      console.error('Like review error:', err);
      this.showNotification('Error updating like', 'error');
    }
  },

  bindLoadMoreEvents() {
    const btn = document.getElementById('load-more-reviews');
    if (btn) btn.addEventListener('click', () => this.loadMoreReviews());
  },

  async loadInitialReviews() { await this.loadReviews(1); },

  async loadReviews(page = 1) {
    if (this.config.isLoading) return;
    try {
      this.config.isLoading = true;
      if (page === 1) this.showReviewsLoading();

      const res = await this.fetchWithTimeout(`${this.config.urls.load}?page=${page}`, {
        headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
      });

      const data = await requireJson(res);

      if (data.success) {
        this.displayReviews(data, page);
        this.config.currentPage = page;
        this.config.hasMore = data.has_next;
        this.updateLoadMoreButton();
      } else {
        throw new Error(data.error || 'Failed to load reviews');
      }
    } catch (err) {
      console.error('Load reviews error:', err);
      this.showReviewsError();
    } finally {
      this.config.isLoading = false;
    }
  },

  async loadMoreReviews() {
    if (!this.config.hasMore || this.config.isLoading) return;
    await this.loadReviews(this.config.currentPage + 1);
  },

  displayReviews(data, page) {
    const c = document.getElementById('reviews-container') || document.getElementById('reviewsList');
    if (!c) return;
    if (page === 1) c.innerHTML = data.reviews_html || this.getEmptyReviewsHtml();
    else c.insertAdjacentHTML('beforeend', data.reviews_html || '');
    this.initializeNewReviewElements(c);
  },

  initializeNewReviewElements(container) {
    const list = container.querySelectorAll('.review-card:not([data-initialized])');
    list.forEach(review => {
      review.setAttribute('data-initialized', 'true');
      if (this.config.currentPage > 1) review.style.animation = 'fadeInUp .5s ease';
    });
  },

  showReviewsLoading() {
    const c = document.getElementById('reviews-container') || document.getElementById('reviewsList');
    if (c) c.innerHTML = `
      <div class="text-center py-5">
        <div class="spinner-border text-primary" role="status">
          <span class="visually-hidden">Loading reviews...</span>
        </div>
        <p class="mt-3 text-muted">Loading reviews...</p>
      </div>`;
  },

  showReviewsError() {
    const c = document.getElementById('reviews-container') || document.getElementById('reviewsList');
    if (c) c.innerHTML = `
      <div class="text-center py-5">
        <div class="text-danger mb-3"><i class="fas fa-exclamation-triangle fa-3x"></i></div>
        <h5>Unable to load reviews</h5>
        <p class="text-muted">Please try again later</p>
        <button class="btn btn-outline-primary" onclick="location.reload()">
          <i class="fas fa-redo"></i> Try Again
        </button>
      </div>`;
  },

  getEmptyReviewsHtml() {
    return `
      <div class="text-center py-5">
        <div class="text-muted mb-3"><i class="fas fa-star fa-3x opacity-25"></i></div>
        <h5>No reviews yet</h5>
        <p class="text-muted">Be the first to review this product!</p>
      </div>`;
  },

  updateLoadMoreButton() {
    const btn = document.getElementById('load-more-reviews'); if (!btn) return;
    if (this.config.hasMore) { btn.style.display = 'block'; btn.disabled = false; btn.innerHTML = '<span class="load-text">Load More Reviews</span>'; }
    else btn.style.display = 'none';
  },

  updateRatingDisplay(data) {
    if (data.stars_html) { const rs = document.getElementById('rating-stars'); if (rs) rs.innerHTML = data.stars_html; }
    if (data.new_avg) { const avg = document.getElementById('avg-rating'); if (avg) avg.textContent = data.new_avg; }
    if (data.total_reviews !== undefined) { const tr = document.getElementById('total-reviews'); if (tr) tr.textContent = data.total_reviews; }
  },

  /* ---------- Comments on reviews ---------- */
  bindCommentEvents() {
    document.addEventListener('submit', (e) => {
      if (e.target.matches('.comment-form')) { e.preventDefault(); this.submitComment(e.target); }
    });
    document.addEventListener('click', (e) => {
      if (e.target.matches('.reply-btn') || e.target.closest('.reply-btn')) {
        e.preventDefault();
        const btn = e.target.closest('.reply-btn');
        const id = btn.dataset.reviewId;
        this.toggleCommentForm(id);
      }
      if (e.target.matches('.delete-comment-btn') || e.target.closest('.delete-comment-btn')) {
        e.preventDefault();
        const btn = e.target.closest('.delete-comment-btn');
        const id = btn.dataset.commentId;
        this.deleteComment(id, btn); // optional if you implement delete comment
      }
    });
  },

  toggleCommentForm(reviewId) {
    let form = document.getElementById(`comment-form-${reviewId}`);
    if (!form) {
      form = this.createCommentForm(reviewId);
      document.querySelector(`[data-review-id="${reviewId}"]`)?.appendChild(form);
    }
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
    if (form.style.display === 'block') form.querySelector('textarea')?.focus();
  },

  createCommentForm(reviewId) {
    const form = document.createElement('form');
    form.className = 'comment-form mt-3';
    form.id = `comment-form-${reviewId}`;
    form.style.display = 'none';
    form.innerHTML = `
      <input type="hidden" name="review_id" value="${reviewId}">
      <input type="hidden" name="csrfmiddlewaretoken" value="${this.config.csrfToken}">
      <div class="mb-3">
        <label class="form-label">Your Reply</label>
        <textarea name="comment" class="form-control" rows="3" required
                  placeholder="Write your reply..." maxlength="500"></textarea>
        <div class="form-text">Maximum 500 characters</div>
      </div>
      <div class="d-flex gap-2">
        <button type="submit" class="btn btn-primary btn-sm">
          <i class="fas fa-reply"></i> Reply
        </button>
        <button type="button" class="btn btn-outline-secondary btn-sm"
                onclick="this.closest('.comment-form').style.display='none'">
          Cancel
        </button>
      </div>`;
    return form;
  },

  async submitComment(form) {
    try {
      const fd = new FormData(form);
      const res = await this.fetchWithTimeout(this.config.urls.comment, {
        method: 'POST',
        body: fd,
        headers: {
          'X-Requested-With':'XMLHttpRequest',
          'X-CSRFToken': this.config.csrfToken || getCookie('csrftoken'),
          'Accept': 'application/json'
        },
        redirect: 'follow'
      });

      const data = await requireJson(res);

      if (data.success) {
        const reviewId = fd.get('review_id');
        const container = document.querySelector(`#comments-${reviewId}`);
        if (container && data.comment_html) container.insertAdjacentHTML('beforeend', data.comment_html);
        form.reset(); form.style.display = 'none';
        this.showNotification(data.message || 'Reply posted successfully', 'success');
      } else {
        throw new Error(data.error || 'Failed to post reply');
      }
    } catch (err) {
      console.error('Submit comment error:', err);
      this.showNotification(err.message || 'Error posting reply', 'error');
    }
  },

  bindKeyboardEvents() {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') document.querySelectorAll('.comment-form[style*="block"]').forEach(f => f.style.display='none');
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        const ae = document.activeElement;
        if (ae?.tagName === 'TEXTAREA') {
          const form = ae.closest('#review-form, #reviewForm, .comment-form');
          if (form) { e.preventDefault(); form.dispatchEvent(new Event('submit')); }
        }
      }
    });
  },

  async fetchWithTimeout(url, options = {}, timeout = 10000) {
    const controller = new AbortController();
    const to = setTimeout(() => controller.abort(), timeout);
    try {
      const res = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(to);
      return res;
    } catch (err) {
      clearTimeout(to);
      if (err.name === 'AbortError') throw new Error('Request timeout');
      throw err;
    }
  },

  showNotification(message, type = 'info') {
    if (window.EasyMarket?.showNotification) window.EasyMarket.showNotification(message, type);
    else if (window.showToast) window.showToast(message, type);
    else { console.log(`${type.toUpperCase()}: ${message}`); alert(message); }
  }
};

/* ===================================
   CHAT SYSTEM
=================================== */
const ChatSystem = {
  config: {
    chatEndpoint: '/chat/',
    wsEndpoint: null,
    csrfToken: '',
    currentChatId: null,
    recipientId: null,
    productId: null,
    currentUserId: null
  },
  state: {
    socket: null,
    isConnected: false,
    messageQueue: [],
    typing: false,
    lastActivity: Date.now(),
    chatBoxVisible: false
  },

  init(config = {}) {
    this.config = { ...this.config, ...config };
    this.loadConfiguration();
    this.bindEvents();
    console.log('Chat System initialized');
  },

  loadConfiguration() {
    if (window.CSRF_TOKEN) this.config.csrfToken = window.CSRF_TOKEN;
    const chatForm = document.getElementById('chatForm');
    if (chatForm) {
      const r = chatForm.querySelector('input[name="recipient_id"]');
      const p = chatForm.querySelector('input[name="product_id"]');
      if (r) this.config.recipientId = r.value;
      if (p) this.config.productId = p.value;
    }
  },

  bindEvents() {
    this.bindChatToggleEvents();
    this.bindMessageFormEvents();
    this.bindTypingEvents();
    this.bindVisibilityEvents();
  },

  // Supports .btn-chat, .temu-btn-chat and [data-action="open-chat"] / close-chat
  bindChatToggleEvents() {
    document.addEventListener('click', (e) => {
      // Open
      if (
        e.target.matches('.btn-chat') || e.target.closest('.btn-chat') ||
        e.target.matches('.temu-btn-chat') || e.target.closest('.temu-btn-chat') ||
        e.target.matches('[data-action="open-chat"]') || e.target.closest('[data-action="open-chat"]')
      ) {
        e.preventDefault(); e.stopPropagation(); this.openChat(); return;
      }
      // Close (inside #chatBox only)
      if (
        (e.target.matches('.chat-close') && e.target.closest('#chatBox')) ||
        (e.target.matches('.btn-close') && e.target.closest('#chatBox')) ||
        (e.target.matches('[data-action="close-chat"]') && e.target.closest('#chatBox')) ||
        (e.target.closest('#chatBox .chat-close')) ||
        (e.target.closest('#chatBox .btn-close'))
      ) {
        e.preventDefault(); e.stopPropagation(); this.closeChat(); return;
      }
    });

    // Keyboard accessibility for openers
    document.addEventListener('keydown', (e) => {
      const opener = e.target.closest('.btn-chat, .temu-btn-chat, [data-action="open-chat"]');
      if (opener && (e.key === 'Enter' || e.code === 'Space')) {
        e.preventDefault(); this.openChat();
      }
    });
  },

  bindMessageFormEvents() {
    document.addEventListener('submit', (e) => {
      if (e.target.matches('#chatForm') || e.target.closest('#chatForm')) {
        e.preventDefault(); this.sendMessage(e.target);
      }
    });
    document.addEventListener('keypress', (e) => {
      if (e.target.matches('#chatForm input[name="message"]')) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          const form = e.target.closest('form'); if (form) this.sendMessage(form);
        }
      }
    });
  },

  bindTypingEvents() {
    let typingTimer;
    document.addEventListener('input', (e) => {
      if (e.target.matches('#chatForm input[name="message"]')) {
        if (!this.state.typing) { this.state.typing = true; this.sendTypingStatus(true); }
        clearTimeout(typingTimer);
        typingTimer = setTimeout(() => { this.state.typing = false; this.sendTypingStatus(false); }, 1000);
      }
    });
  },

  bindVisibilityEvents() {
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) this.state.lastActivity = Date.now();
      else this.markMessagesAsRead();
    });
  },

  toggleChat() { this.state.chatBoxVisible ? this.closeChat() : this.openChat(); },

  openChat() {
    const chatWidget = document.getElementById('chatBox');
    if (!chatWidget) { console.error('Chat widget not found'); return; }
    chatWidget.style.animation = '';
    chatWidget.classList.remove('d-none');
    this.state.chatBoxVisible = true;
    chatWidget.style.animation = 'slideInUp 0.3s ease forwards';
    setTimeout(() => chatWidget.querySelector('input[name="message"]')?.focus(), 350);
    this.loadRecentMessages();
  },

  closeChat() {
    const chatWidget = document.getElementById('chatBox');
    if (!chatWidget) { console.error('Chat widget not found'); return; }
    chatWidget.style.animation = 'slideOutDown 0.3s ease forwards';
    setTimeout(() => {
      chatWidget.classList.add('d-none');
      chatWidget.style.animation = '';
      this.state.chatBoxVisible = false;
    }, 300);
  },

  async sendMessage(form) {
    const input = form.querySelector('input[name="message"]');
    const message = input.value.trim();
    if (!message) return;

    // Optimistic UI
    this.addMessageToUI(message, true);
    input.value = '';

    try {
      await this.sendMessageViaHTTP(form, message);
    } catch (err) {
      console.error('Send message error:', err);
      this.showNotification('Failed to send message', 'error');
      this.removeLastOptimisticMessage();
    }
  },

  async sendMessageViaHTTP(form, message) {
    const fd = new FormData(form);
    fd.set('message', message);
    const response = await fetch(form.action || '/chat/start_chat/', {
      method: 'POST',
      body: fd,
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': this.config.csrfToken || getCookie('csrftoken'),
        'Accept': 'application/json'
      },
      redirect: 'follow'
    });
    const data = await requireJson(response);
    if (!data.success) throw new Error(data.error || 'Failed to send message');

    // Mark optimistic message as confirmed
    const optimistic = document.querySelector('#chatMessages .message-container.optimistic:last-child');
    optimistic?.classList.remove('optimistic');
  },

  addMessageToUI(message, isOwn = false, timestamp = null) {
    const list = document.getElementById('chatMessages'); if (!list) return;
    const el = document.createElement('div');
    el.className = `message-container mb-3 ${isOwn ? 'text-end' : ''}`;
    const timeStr = timestamp ? new Date(timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
    el.innerHTML = `
      <div class="message p-2 rounded-4 d-inline-block ${isOwn ? 'bg-primary text-white' : 'bg-white'}">
        <small class="message-text">${this.escapeHtml(message)}</small><br>
        <small class="message-time opacity-75">${timeStr}</small>
      </div>`;
    if (isOwn) el.classList.add('optimistic');
    list.appendChild(el);
    this.scrollToBottom();

    el.style.opacity = '0'; el.style.transform = 'translateY(20px)';
    requestAnimationFrame(() => {
      el.style.transition = 'all .3s ease';
      el.style.opacity = '1';
      el.style.transform = 'translateY(0)';
    });
  },

  removeLastOptimisticMessage() {
    const list = document.getElementById('chatMessages'); if (!list) return;
    const el = list.querySelector('.message-container.optimistic:last-child');
    if (el) { el.style.animation = 'fadeOut .3s ease'; setTimeout(() => el.remove(), 300); }
  },

  scrollToBottom() {
    const list = document.getElementById('chatMessages');
    if (list) list.scrollTop = list.scrollHeight;
  },

  sendTypingStatus(isTyping) {
    // Hook for WebSocket typing indicator (placeholder)
    console.log('Typing status:', isTyping);
  },

  async loadRecentMessages() {
    try {
      if (!this.config.recipientId) return;
      const url = `${this.config.chatEndpoint}messages/?recipient_id=${encodeURIComponent(this.config.recipientId)}`;
      const res = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' }});
      const data = await requireJson(res);
      if (data.success && data.messages) {
        const list = document.getElementById('chatMessages'); if (!list) return;

        // Preserve product preview
        const preview = list.querySelector('.product-preview');
        list.innerHTML = '';
        if (preview) list.appendChild(preview);

        data.messages.forEach(m => this.addMessageToUI(m.message, m.sender_id === this.config.currentUserId, m.timestamp));
      }
    } catch (err) {
      console.error('Load messages error:', err);
      // Non-blocking
    }
  },

  markMessagesAsRead() {
    if (this.config.currentChatId) {
      fetch(`${this.config.chatEndpoint}mark-read/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': this.config.csrfToken || getCookie('csrftoken'),
          'Accept': 'application/json'
        },
        body: `chat_id=${encodeURIComponent(this.config.currentChatId)}`
      }).catch(err => console.error('Mark read error:', err));
    }
  },

  escapeHtml(text) { const div = document.createElement('div'); div.textContent = text; return div.innerHTML; },

  showNotification(message, type) {
    if (window.EasyMarket?.showNotification) window.EasyMarket.showNotification(message, type);
    else if (window.showToast) window.showToast(message, type);
    else console.log(`${type?.toUpperCase() || 'INFO'}: ${message}`);
  }
};

/* ===================================
   Animations (inject once)
=================================== */
if (!document.getElementById('chat-animations')) {
  const style = document.createElement('style');
  style.id = 'chat-animations';
  style.textContent = `
    @keyframes fadeInUp { from {opacity:0; transform:translateY(30px);} to {opacity:1; transform:translateY(0);} }
    @keyframes fadeOut { from {opacity:1;} to {opacity:0;} }
    @keyframes slideInUp { from {transform:translateY(100%); opacity:0;} to {transform:translateY(0); opacity:1;} }
    @keyframes slideOutDown { from {transform:translateY(0); opacity:1;} to {transform:translateY(100%); opacity:0;} }
    .message-container.optimistic { opacity: .7; }
    .typing-indicator { padding: .5rem; font-style: italic; color:#6c757d; animation: fadeInUp .3s ease; }
    .review-card { transition: all .3s ease; }
    .temu-floating-chat { position: fixed !important; z-index: 1050 !important; }
  `;
  document.head.appendChild(style);
}

/* ===================================
   Init + Global helpers
=================================== */
document.addEventListener('DOMContentLoaded', () => {
  console.log('Initializing Chat and Review systems...');
  ReviewSystem.init();
  ChatSystem.init();
  // Optional: expose manual triggers
  window.openChat = () => ChatSystem.openChat();
  window.closeChat = () => ChatSystem.closeChat();
  console.log('Systems initialized successfully');
});

// Node/CommonJS export (optional)
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { ReviewSystem, ChatSystem };
}
