/**
 * Enhanced Message & Review System - FIXED VERSION
 * Professional chat and review functionality with real-time features
 */



'use strict';

// --- helpers: cookie + safe JSON
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
}

async function requireJson(response) {
  // Ensure server actually sent JSON; otherwise reveal a useful snippet.
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


// ===================================
// REVIEW SYSTEM MODULE
// ===================================
const ReviewSystem = {
    config: {
        productId: null,
        csrfToken: '',
        urls: {
            submit: '',
            delete: '',
            comment: '',
            load: ''
        },
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
        // Load from global variables if available
        if (window.PRODUCT_ID) this.config.productId = window.PRODUCT_ID;
        if (window.CSRF_TOKEN) this.config.csrfToken = window.CSRF_TOKEN;

        // Load URLs
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

    // ===================================
    // STAR RATING FUNCTIONALITY
    // ===================================
    bindStarRatingEvents() {
        const starContainer = document.querySelector('.star-rating, .temu-star-rating');
        if (!starContainer) return;

        const stars = starContainer.querySelectorAll('.star-btn, .temu-star-input');

        stars.forEach((star, index) => {
            const rating = parseInt(star.dataset.rating) || index + 1;

            // Click event
            star.addEventListener('click', (e) => {
                e.preventDefault();
                this.setRating(rating);
            });

            // Hover events
            star.addEventListener('mouseenter', () => {
                this.highlightStars(rating, true);
            });

            star.addEventListener('mouseleave', () => {
                this.highlightStars(this.state.selectedRating);
            });

            // Keyboard support
            star.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    this.setRating(rating);
                }
            });
        });

        // Reset highlighting when mouse leaves container
        starContainer.addEventListener('mouseleave', () => {
            this.highlightStars(this.state.selectedRating);
        });
    },

    setRating(rating) {
        this.state.selectedRating = rating;

        // Update hidden input
        const ratingInput = document.getElementById('rating-input') || document.getElementById('ratingValue');
        if (ratingInput) {
            ratingInput.value = rating;
        }

        // Update visual stars
        this.highlightStars(rating);

        // Show rating text
        this.showRatingText(rating);

        console.log('Rating set:', rating);
    },

    highlightStars(rating, isHover = false) {
        const stars = document.querySelectorAll('.star-btn, .temu-star-input');

        stars.forEach((star, index) => {
            const starRating = parseInt(star.dataset.rating) || index + 1;
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
        const texts = {
            1: 'Poor',
            2: 'Fair',
            3: 'Good',
            4: 'Very Good',
            5: 'Excellent'
        };

        let textElement = document.querySelector('.rating-text-display');
        if (!textElement) {
            textElement = document.createElement('div');
            textElement.className = 'rating-text-display mt-2 text-muted';

            const starContainer = document.querySelector('.star-rating, .temu-star-rating');
            if (starContainer) {
                starContainer.parentNode.insertBefore(textElement, starContainer.nextSibling);
            }
        }

        textElement.textContent = texts[rating] || '';
        textElement.style.opacity = rating > 0 ? '1' : '0';
    },

    // ===================================
    // REVIEW FORM FUNCTIONALITY
    // ===================================
    bindReviewFormEvents() {
        const reviewForm = document.getElementById('review-form') || document.getElementById('reviewForm');
        if (!reviewForm) return;

        reviewForm.addEventListener('submit', (e) => {
            e.preventDefault();
            this.submitReview(reviewForm);
        });

        // Real-time character count for comment
        const commentTextarea = reviewForm.querySelector('textarea[name="comment"]');
        if (commentTextarea) {
            this.setupCharacterCounter(commentTextarea);
        }

        // Form validation
        const inputs = reviewForm.querySelectorAll('input, textarea');
        inputs.forEach(input => {
            input.addEventListener('blur', () => {
                this.validateField(input);
            });
        });
    },

    setupCharacterCounter(textarea) {
        const maxLength = parseInt(textarea.getAttribute('maxlength')) || 1000;

        let counter = textarea.parentNode.querySelector('.character-counter');
        if (!counter) {
            counter = document.createElement('div');
            counter.className = 'character-counter text-muted small mt-1';
            textarea.parentNode.appendChild(counter);
        }

        const updateCounter = () => {
            const remaining = maxLength - textarea.value.length;
            counter.textContent = `${remaining} characters remaining`;
            counter.className = `character-counter small mt-1 ${remaining < 50 ? 'text-warning' : 'text-muted'}`;
        };

        textarea.addEventListener('input', updateCounter);
        updateCounter();
    },

    validateField(field) {
        const value = field.value.trim();
        let isValid = true;
        let message = '';

        // Rating validation
        if (field.name === 'rating' || field.id === 'rating-input') {
            isValid = value && parseInt(value) >= 1 && parseInt(value) <= 5;
            message = isValid ? '' : 'Please select a rating';
        }

        // Comment validation
        if (field.name === 'comment') {
            isValid = value.length >= 10;
            message = isValid ? '' : 'Comment must be at least 10 characters long';
        }

        this.showFieldValidation(field, isValid, message);
        return isValid;
    },

    showFieldValidation(field, isValid, message) {
        // Remove existing validation
        field.classList.remove('is-valid', 'is-invalid');
        const existingFeedback = field.parentNode.querySelector('.invalid-feedback, .valid-feedback');
        if (existingFeedback) {
            existingFeedback.remove();
        }

        if (message) {
            field.classList.add(isValid ? 'is-valid' : 'is-invalid');

            const feedback = document.createElement('div');
            feedback.className = isValid ? 'valid-feedback' : 'invalid-feedback';
            feedback.textContent = message;
            field.parentNode.appendChild(feedback);
        }
    },

    async submitReview(form) {
        if (this.config.isLoading) return;

        try {
            // Validate form
            if (!this.validateForm(form)) {
                this.showNotification('Please correct the errors below', 'error');
                return;
            }

            this.config.isLoading = true;
            this.setSubmitButtonLoading(true);

            const formData = new FormData(form);

            // Ensure product ID is included
            if (this.config.productId) {
                formData.set('product_id', this.config.productId);
            }

            const response = await this.fetchWithTimeout(this.config.urls.submit, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                this.handleReviewSubmitSuccess(data, form);
            } else {
                throw new Error(data.error || 'Failed to submit review');
            }

        } catch (error) {
            console.error('Submit review error:', error);
            this.showNotification(error.message || 'Error submitting review', 'error');
        } finally {
            this.config.isLoading = false;
            this.setSubmitButtonLoading(false);
        }
    },

    validateForm(form) {
        const inputs = form.querySelectorAll('input[required], textarea[required]');
        let isValid = true;

        inputs.forEach(input => {
            if (!this.validateField(input)) {
                isValid = false;
            }
        });

        // Special validation for rating
        if (this.state.selectedRating === 0) {
            this.showNotification('Please select a rating', 'warning');
            isValid = false;
        }

        return isValid;
    },

    handleReviewSubmitSuccess(data, form) {
        // Update statistics
        if (data.new_avg) this.state.averageRating = parseFloat(data.new_avg);
        if (data.total_reviews) this.state.reviewCount = parseInt(data.total_reviews);

        // Update UI elements
        this.updateRatingDisplay(data);

        // Reset form
        this.resetReviewForm(form);

        // Reload reviews
        this.loadReviews(1);

        // Show success message
        this.showNotification(data.message || 'Review submitted successfully!', 'success');

        // Scroll to reviews section
        setTimeout(() => {
            const reviewsSection = document.getElementById('reviews-container');
            if (reviewsSection) {
                reviewsSection.scrollIntoView({ behavior: 'smooth' });
            }
        }, 500);
    },

    resetReviewForm(form) {
        form.reset();
        this.state.selectedRating = 0;
        this.highlightStars(0);
        this.showRatingText(0);

        // Clear validation
        const validatedFields = form.querySelectorAll('.is-valid, .is-invalid');
        validatedFields.forEach(field => {
            field.classList.remove('is-valid', 'is-invalid');
        });

        const feedbacks = form.querySelectorAll('.invalid-feedback, .valid-feedback');
        feedbacks.forEach(feedback => feedback.remove());
    },

    setSubmitButtonLoading(isLoading) {
        const submitBtn = document.querySelector('#review-form button[type="submit"], #reviewForm button[type="submit"]');
        if (!submitBtn) return;

        const spinner = submitBtn.querySelector('.spinner-border, #submit-spinner');
        const text = submitBtn.querySelector('.submit-text') || submitBtn;

        if (isLoading) {
            submitBtn.disabled = true;
            if (spinner) spinner.classList.remove('d-none');
            if (text !== submitBtn) text.textContent = 'Submitting...';
        } else {
            submitBtn.disabled = false;
            if (spinner) spinner.classList.add('d-none');
            if (text !== submitBtn) text.textContent = 'Submit Review';
        }
    },

    // ===================================
    // REVIEW MANAGEMENT
    // ===================================
    bindReviewActionsEvents() {
        // Use event delegation for dynamic content
        document.addEventListener('click', (e) => {
            // Delete review
            if (e.target.matches('.delete-review-btn') || e.target.closest('.delete-review-btn')) {
                e.preventDefault();
                const button = e.target.closest('.delete-review-btn');
                const reviewId = button.dataset.reviewId;
                if (reviewId) {
                    this.confirmDeleteReview(reviewId, button);
                }
            }

            // Like review
            if (e.target.matches('.like-review-btn') || e.target.closest('.like-review-btn')) {
                e.preventDefault();
                const button = e.target.closest('.like-review-btn');
                const reviewId = button.dataset.reviewId;
                if (reviewId) {
                    this.toggleReviewLike(reviewId, button);
                }
            }

            // Report review
            if (e.target.matches('.report-review-btn') || e.target.closest('.report-review-btn')) {
                e.preventDefault();
                const button = e.target.closest('.report-review-btn');
                const reviewId = button.dataset.reviewId;
                if (reviewId) {
                    this.reportReview(reviewId);
                }
            }
        });
    },

    confirmDeleteReview(reviewId, button) {
        const confirmModal = this.createConfirmModal(
            'Delete Review',
            'Are you sure you want to delete this review? This action cannot be undone.',
            () => this.deleteReview(reviewId, button)
        );
        confirmModal.show();
    },

    async deleteReview(reviewId, button) {
        try {
            const response = await this.fetchWithTimeout(this.config.urls.delete, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': this.config.csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: `review_id=${reviewId}`
            });

            const data = await response.json();

            if (data.success) {
                // Remove review from DOM
                const reviewCard = button.closest('.review-card, .review-item');
                if (reviewCard) {
                    reviewCard.style.animation = 'fadeOut 0.3s ease';
                    setTimeout(() => reviewCard.remove(), 300);
                }

                // Update statistics
                this.updateRatingDisplay(data);

                this.showNotification(data.message || 'Review deleted successfully', 'success');
            } else {
                throw new Error(data.error || 'Failed to delete review');
            }

        } catch (error) {
            console.error('Delete review error:', error);
            this.showNotification(error.message || 'Error deleting review', 'error');
        }
    },

    async toggleReviewLike(reviewId, button) {
        try {
            const response = await this.fetchWithTimeout('/reviews/like/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': this.config.csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: `review_id=${reviewId}`
            });

            const data = await response.json();

            if (data.success) {
                // Update button state
                const icon = button.querySelector('i');
                const count = button.querySelector('.like-count');

                if (data.liked) {
                    icon.className = 'fas fa-thumbs-up';
                    button.classList.add('liked');
                } else {
                    icon.className = 'far fa-thumbs-up';
                    button.classList.remove('liked');
                }

                if (count) {
                    count.textContent = data.likes_count;
                }

                // Add animation
                button.style.transform = 'scale(1.1)';
                setTimeout(() => {
                    button.style.transform = 'scale(1)';
                }, 150);

            } else {
                throw new Error(data.error || 'Failed to update like');
            }

        } catch (error) {
            console.error('Like review error:', error);
            this.showNotification('Error updating like', 'error');
        }
    },

    reportReview(reviewId) {
        const modal = this.createReportModal(reviewId);
        modal.show();
    },

    // ===================================
    // REVIEW LOADING
    // ===================================
    bindLoadMoreEvents() {
        const loadMoreBtn = document.getElementById('load-more-reviews');
        if (loadMoreBtn) {
            loadMoreBtn.addEventListener('click', () => {
                this.loadMoreReviews();
            });
        }
    },

    async loadInitialReviews() {
        await this.loadReviews(1);
    },

    async loadReviews(page = 1) {
        if (this.config.isLoading) return;

        try {
            this.config.isLoading = true;

            if (page === 1) {
                this.showReviewsLoading();
            }

            const url = `${this.config.urls.load}?page=${page}`;
            const response = await this.fetchWithTimeout(url);

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                this.displayReviews(data, page);
                this.config.currentPage = page;
                this.config.hasMore = data.has_next;
                this.updateLoadMoreButton();
            } else {
                throw new Error(data.error || 'Failed to load reviews');
            }

        } catch (error) {
            console.error('Load reviews error:', error);
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
        const container = document.getElementById('reviews-container') || document.getElementById('reviewsList');
        if (!container) return;

        if (page === 1) {
            container.innerHTML = data.reviews_html || this.getEmptyReviewsHtml();
        } else {
            container.insertAdjacentHTML('beforeend', data.reviews_html || '');
        }

        // Initialize new review elements
        this.initializeNewReviewElements(container);
    },

    initializeNewReviewElements(container) {
        // Initialize any new interactive elements in the reviews
        const newReviews = container.querySelectorAll('.review-card:not([data-initialized])');
        newReviews.forEach(review => {
            review.setAttribute('data-initialized', 'true');

            // Add animation for new reviews
            if (this.config.currentPage > 1) {
                review.style.animation = 'fadeInUp 0.5s ease';
            }
        });
    },

    showReviewsLoading() {
        const container = document.getElementById('reviews-container') || document.getElementById('reviewsList');
        if (container) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading reviews...</span>
                    </div>
                    <p class="mt-3 text-muted">Loading reviews...</p>
                </div>
            `;
        }
    },

    showReviewsError() {
        const container = document.getElementById('reviews-container') || document.getElementById('reviewsList');
        if (container) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <div class="text-danger mb-3">
                        <i class="fas fa-exclamation-triangle fa-3x"></i>
                    </div>
                    <h5>Unable to load reviews</h5>
                    <p class="text-muted">Please try again later</p>
                    <button class="btn btn-outline-primary" onclick="location.reload()">
                        <i class="fas fa-redo"></i> Try Again
                    </button>
                </div>
            `;
        }
    },

    getEmptyReviewsHtml() {
        return `
            <div class="text-center py-5">
                <div class="text-muted mb-3">
                    <i class="fas fa-star fa-3x opacity-25"></i>
                </div>
                <h5>No reviews yet</h5>
                <p class="text-muted">Be the first to review this product!</p>
            </div>
        `;
    },

    updateLoadMoreButton() {
        const loadMoreBtn = document.getElementById('load-more-reviews');
        if (!loadMoreBtn) return;

        if (this.config.hasMore) {
            loadMoreBtn.style.display = 'block';
            loadMoreBtn.disabled = false;
            loadMoreBtn.innerHTML = '<span class="load-text">Load More Reviews</span>';
        } else {
            loadMoreBtn.style.display = 'none';
        }
    },

    updateRatingDisplay(data) {
        // Update overall rating
        if (data.stars_html) {
            const ratingStars = document.getElementById('rating-stars');
            if (ratingStars) ratingStars.innerHTML = data.stars_html;
        }

        if (data.new_avg) {
            const avgRating = document.getElementById('avg-rating');
            if (avgRating) avgRating.textContent = data.new_avg;
        }

        if (data.total_reviews !== undefined) {
            const totalReviews = document.getElementById('total-reviews');
            if (totalReviews) totalReviews.textContent = data.total_reviews;
        }
    },

    // ===================================
    // COMMENT FUNCTIONALITY
    // ===================================
    bindCommentEvents() {
        document.addEventListener('submit', (e) => {
            if (e.target.matches('.comment-form')) {
                e.preventDefault();
                this.submitComment(e.target);
            }
        });

        document.addEventListener('click', (e) => {
            // Toggle comment form
            if (e.target.matches('.reply-btn') || e.target.closest('.reply-btn')) {
                e.preventDefault();
                const button = e.target.closest('.reply-btn');
                const reviewId = button.dataset.reviewId;
                this.toggleCommentForm(reviewId);
            }

            // Delete comment
            if (e.target.matches('.delete-comment-btn') || e.target.closest('.delete-comment-btn')) {
                e.preventDefault();
                const button = e.target.closest('.delete-comment-btn');
                const commentId = button.dataset.commentId;
                this.deleteComment(commentId, button);
            }
        });
    },

    toggleCommentForm(reviewId) {
        let form = document.getElementById(`comment-form-${reviewId}`);

        if (!form) {
            form = this.createCommentForm(reviewId);
            const reviewCard = document.querySelector(`[data-review-id="${reviewId}"]`);
            if (reviewCard) {
                reviewCard.appendChild(form);
            }
        }

        form.style.display = form.style.display === 'none' ? 'block' : 'none';

        if (form.style.display === 'block') {
            const textarea = form.querySelector('textarea');
            if (textarea) {
                textarea.focus();
            }
        }
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
                <button type="button" class="btn btn-outline-secondary btn-sm" onclick="this.closest('.comment-form').style.display='none'">
                    Cancel
                </button>
            </div>
        `;

        return form;
    },

    async submitComment(form) {
        try {
            const formData = new FormData(form);

            const response = await this.fetchWithTimeout(this.config.urls.comment, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            const data = await response.json();

            if (data.success) {
                // Add comment to DOM
                const reviewId = formData.get('review_id');
                const commentsContainer = document.querySelector(`#comments-${reviewId}`);
                if (commentsContainer && data.comment_html) {
                    commentsContainer.insertAdjacentHTML('beforeend', data.comment_html);
                }

                // Reset and hide form
                form.reset();
                form.style.display = 'none';

                this.showNotification(data.message || 'Reply posted successfully', 'success');
            } else {
                throw new Error(data.error || 'Failed to post reply');
            }

        } catch (error) {
            console.error('Submit comment error:', error);
            this.showNotification(error.message || 'Error posting reply', 'error');
        }
    },

    // ===================================
    // KEYBOARD SUPPORT
    // ===================================
    bindKeyboardEvents() {
        document.addEventListener('keydown', (e) => {
            // ESC to close modals/forms
            if (e.key === 'Escape') {
                const activeCommentForms = document.querySelectorAll('.comment-form[style*="block"]');
                activeCommentForms.forEach(form => {
                    form.style.display = 'none';
                });
            }

            // Ctrl+Enter to submit review form
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                const activeElement = document.activeElement;
                if (activeElement.tagName === 'TEXTAREA') {
                    const form = activeElement.closest('#review-form, #reviewForm, .comment-form');
                    if (form) {
                        e.preventDefault();
                        form.dispatchEvent(new Event('submit'));
                    }
                }
            }
        });
    },

    // ===================================
    // UTILITY METHODS
    // ===================================
    createConfirmModal(title, message, onConfirm) {
        const modalId = 'confirmModal_' + Date.now();
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.id = modalId;
        modal.innerHTML = `
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${title}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p>${message}</p>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-danger confirm-btn">Delete</button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        const confirmBtn = modal.querySelector('.confirm-btn');
        confirmBtn.addEventListener('click', () => {
            onConfirm();
            const bootstrapModal = bootstrap.Modal.getInstance(modal);
            if (bootstrapModal) {
                bootstrapModal.hide();
            }
        });

        // Clean up when modal is hidden
        modal.addEventListener('hidden.bs.modal', () => {
            modal.remove();
        });

        return new bootstrap.Modal(modal);
    },

    createReportModal(reviewId) {
        const modalId = 'reportModal_' + Date.now();
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.id = modalId;
        modal.innerHTML = `
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Report Review</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <form class="report-form">
                        <div class="modal-body">
                            <input type="hidden" name="review_id" value="${reviewId}">
                            <input type="hidden" name="csrfmiddlewaretoken" value="${this.config.csrfToken}">
                            <div class="mb-3">
                                <label class="form-label">Reason for reporting</label>
                                <select name="reason" class="form-select" required>
                                    <option value="">Select a reason</option>
                                    <option value="spam">Spam</option>
                                    <option value="inappropriate">Inappropriate content</option>
                                    <option value="fake">Fake review</option>
                                    <option value="offensive">Offensive language</option>
                                    <option value="other">Other</option>
                                </select>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Additional details (optional)</label>
                                <textarea name="details" class="form-control" rows="3"
                                          placeholder="Provide more details about the issue..."></textarea>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="submit" class="btn btn-warning">Report Review</button>
                        </div>
                    </form>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // Handle form submission
        const form = modal.querySelector('.report-form');
        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            try {
                const formData = new FormData(form);
                const response = await this.fetchWithTimeout('/reviews/report/', {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });

                const data = await response.json();

                if (data.success) {
                    this.showNotification('Review reported successfully. Thank you for your feedback.', 'success');
                    const bootstrapModal = bootstrap.Modal.getInstance(modal);
                    if (bootstrapModal) {
                        bootstrapModal.hide();
                    }
                } else {
                    throw new Error(data.error || 'Failed to report review');
                }

            } catch (error) {
                console.error('Report review error:', error);
                this.showNotification('Error reporting review', 'error');
            }
        });

        // Clean up when modal is hidden
        modal.addEventListener('hidden.bs.modal', () => {
            modal.remove();
        });

        return new bootstrap.Modal(modal);
    },

    async fetchWithTimeout(url, options = {}, timeout = 10000) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            return response;
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                throw new Error('Request timeout');
            }
            throw error;
        }
    },

    showNotification(message, type = 'info') {
        // Use the global notification system if available
        if (window.EasyMarket && window.EasyMarket.showNotification) {
            window.EasyMarket.showNotification(message, type);
        } else if (window.showToast) {
            window.showToast(message, type);
        } else {
            // Fallback
            console.log(`${type.toUpperCase()}: ${message}`);
            alert(message);
        }
    }
};

// ===================================
// CHAT SYSTEM MODULE - FIXED VERSION
// ===================================
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

        // Don't auto-initialize WebSocket to avoid conflicts
        // this.initializeWebSocket();

        console.log('Chat System initialized');
    },

    loadConfiguration() {
        // Load from global variables if available
        if (window.CSRF_TOKEN) this.config.csrfToken = window.CSRF_TOKEN;

        // Extract recipient and product info from chat form
        const chatForm = document.getElementById('chatForm');
        if (chatForm) {
            const recipientInput = chatForm.querySelector('input[name="recipient_id"]');
            const productInput = chatForm.querySelector('input[name="product_id"]');

            if (recipientInput) this.config.recipientId = recipientInput.value;
            if (productInput) this.config.productId = productInput.value;
        }
    },

    bindEvents() {
        this.bindChatToggleEvents();
        this.bindMessageFormEvents();
        this.bindTypingEvents();
        this.bindVisibilityEvents();
    },

    bindChatToggleEvents() {
        // Remove all existing onclick handlers and bind new ones
        document.addEventListener('click', (e) => {
            // Chat toggle buttons
            if (e.target.matches('.temu-btn-chat') || e.target.closest('.temu-btn-chat')) {
                e.preventDefault();
                e.stopPropagation();
                this.toggleChat();
            }

            // Close chat button
            if (e.target.matches('.btn-close') && e.target.closest('#chatBox')) {
                e.preventDefault();
                e.stopPropagation();
                this.closeChat();
            }
        });
    },

    bindMessageFormEvents() {
        document.addEventListener('submit', (e) => {
            if (e.target.matches('#chatForm') || e.target.closest('#chatForm')) {
                e.preventDefault();
                this.sendMessage(e.target);
            }
        });

        // Enter to send message
        document.addEventListener('keypress', (e) => {
            if (e.target.matches('#chatForm input[name="message"]')) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    const form = e.target.closest('form');
                    if (form) {
                        this.sendMessage(form);
                    }
                }
            }
        });
    },

    bindTypingEvents() {
        document.addEventListener('input', (e) => {
            if (e.target.matches('#chatForm input[name="message"]')) {
                let typingTimer;

                if (!this.state.typing) {
                    this.state.typing = true;
                    this.sendTypingStatus(true);
                }

                clearTimeout(typingTimer);
                typingTimer = setTimeout(() => {
                    this.state.typing = false;
                    this.sendTypingStatus(false);
                }, 1000);
            }
        });
    },

    bindVisibilityEvents() {
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.state.lastActivity = Date.now();
            } else {
                // User returned, mark messages as read
                this.markMessagesAsRead();
            }
        });
    },

    toggleChat() {
        console.log('Toggle chat called, current visible:', this.state.chatBoxVisible);

        if (this.state.chatBoxVisible) {
            this.closeChat();
        } else {
            this.openChat();
        }
    },

    openChat() {
        console.log('Opening chat...');

        const chatWidget = document.getElementById('chatBox');
        if (!chatWidget) {
            console.error('Chat widget not found');
            return;
        }

        // Clear any existing animations
        chatWidget.style.animation = '';

        // Show the chat box
        chatWidget.classList.remove('d-none');
        this.state.chatBoxVisible = true;

        // Add slide-in animation
        chatWidget.style.animation = 'slideInUp 0.3s ease forwards';

        // Focus on message input after animation
        setTimeout(() => {
            const messageInput = chatWidget.querySelector('input[name="message"]');
            if (messageInput) {
                messageInput.focus();
            }
        }, 350);

        // Load recent messages
        this.loadRecentMessages();

        console.log('Chat opened successfully');
    },

    closeChat() {
        console.log('Closing chat...');

        const chatWidget = document.getElementById('chatBox');
        if (!chatWidget) {
            console.error('Chat widget not found');
            return;
        }

        // Add slide-out animation
        chatWidget.style.animation = 'slideOutDown 0.3s ease forwards';

        // Hide after animation completes
        setTimeout(() => {
            chatWidget.classList.add('d-none');
            chatWidget.style.animation = '';
            this.state.chatBoxVisible = false;
            console.log('Chat closed successfully');
        }, 300);
    },

    async sendMessage(form) {
        const messageInput = form.querySelector('input[name="message"]');
        const message = messageInput.value.trim();

        if (!message) return;

        console.log('Sending message:', message);

        try {
            // Add message to UI immediately (optimistic update)
            this.addMessageToUI(message, true);
            messageInput.value = '';

            // Send via HTTP (keeping it simple for now)
            await this.sendMessageViaHTTP(form, message);

        } catch (error) {
            console.error('Send message error:', error);
            this.showNotification('Failed to send message', 'error');

            // Remove optimistic message on error
            this.removeLastOptimisticMessage();
        }
    },

   async sendMessageViaHTTP(form, message) {
    const formData = new FormData(form);
    formData.set('message', message); // Ensure message is set

    const response = await fetch(form.action || '/chat/start_chat/', {
        method: 'POST',
        body: formData,
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            // IMPORTANT: include CSRF (use config or cookie fallback)
            'X-CSRFToken': this.config.csrfToken || getCookie('csrftoken')
        },
        redirect: 'follow'
    });

    if (!response.ok) {
        // You still might get an HTML error page; requireJson() will show it
        throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await requireJson(response); // <— guard parsing

    if (!data.success) {
        throw new Error(data.error || 'Failed to send message');
    }

    // Remove optimistic class from sent message
    const optimisticMessage = document.querySelector('.message-container.optimistic:last-child');
    if (optimisticMessage) {
        optimisticMessage.classList.remove('optimistic');
    }

    console.log('Message sent successfully');
},


    addMessageToUI(message, isOwn = false, timestamp = null) {
        const chatMessages = document.getElementById('chatMessages');
        if (!chatMessages) {
            console.error('Chat messages container not found');
            return;
        }

        const messageElement = document.createElement('div');
        messageElement.className = `message-container mb-3 ${isOwn ? 'text-end' : ''}`;

        const timeStr = timestamp ? new Date(timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();

        messageElement.innerHTML = `
            <div class="message p-2 rounded-4 d-inline-block ${isOwn ? 'bg-primary text-white' : 'bg-white'}">
                <small class="message-text">${this.escapeHtml(message)}</small><br>
                <small class="message-time opacity-75">${timeStr}</small>
            </div>
        `;

        // Add optimistic class for own messages
        if (isOwn) {
            messageElement.classList.add('optimistic');
        }

        chatMessages.appendChild(messageElement);
        this.scrollToBottom();

        // Animate new message
        messageElement.style.opacity = '0';
        messageElement.style.transform = 'translateY(20px)';

        requestAnimationFrame(() => {
            messageElement.style.transition = 'all 0.3s ease';
            messageElement.style.opacity = '1';
            messageElement.style.transform = 'translateY(0)';
        });
    },

    removeLastOptimisticMessage() {
        const chatMessages = document.getElementById('chatMessages');
        if (!chatMessages) return;

        const optimisticMessage = chatMessages.querySelector('.message-container.optimistic:last-child');
        if (optimisticMessage) {
            optimisticMessage.style.animation = 'fadeOut 0.3s ease';
            setTimeout(() => optimisticMessage.remove(), 300);
        }
    },

    scrollToBottom() {
        const chatMessages = document.getElementById('chatMessages');
        if (chatMessages) {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    },

    sendTypingStatus(isTyping) {
        // Placeholder for typing status
        console.log('Typing status:', isTyping);
    },

    async loadRecentMessages() {
        try {
            if (!this.config.recipientId) {
                console.log('No recipient ID, skipping message load');
                return;
            }

            const url = `${this.config.chatEndpoint}messages/?recipient_id=${this.config.recipientId}`;
            const response = await fetch(url, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                console.warn('Failed to load messages');
                return;
            }

            const data = await response.json();

            if (data.success && data.messages) {
                const chatMessages = document.getElementById('chatMessages');
                if (chatMessages) {
                    // Clear existing messages except product preview
                    const productPreview = chatMessages.querySelector('.product-preview');
                    chatMessages.innerHTML = '';
                    if (productPreview) {
                        chatMessages.appendChild(productPreview);
                    }

                    data.messages.forEach(msg => {
                        this.addMessageToUI(
                            msg.message,
                            msg.sender_id === this.config.currentUserId,
                            msg.timestamp
                        );
                    });
                }
            }

        } catch (error) {
            console.error('Load messages error:', error);
        }
    },

    markMessagesAsRead() {
        // Implementation to mark messages as read
        if (this.config.currentChatId) {
            fetch(`${this.config.chatEndpoint}mark-read/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': this.config.csrfToken
                },
                body: `chat_id=${this.config.currentChatId}`
            }).catch(error => {
                console.error('Mark read error:', error);
            });
        }
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    showNotification(message, type) {
        // Use global notification system
        if (window.EasyMarket && window.EasyMarket.showNotification) {
            window.EasyMarket.showNotification(message, type);
        } else if (window.showToast) {
            window.showToast(message, type);
        } else {
            console.log(`${type.toUpperCase()}: ${message}`);
        }
    }
};

// ===================================
// GLOBAL FUNCTIONS & INITIALIZATION
// ===================================

// Remove the old global functions that were causing conflicts
// window.toggleChatBox is now handled by the event system

// Add CSS animations if not already present
if (!document.getElementById('chat-animations')) {
    const style = document.createElement('style');
    style.id = 'chat-animations';
    style.textContent = `
        @keyframes fadeInUp {
            from {
                opacity: 0;
                transform: translateY(30px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @keyframes fadeOut {
            from { opacity: 1; }
            to { opacity: 0; }
        }

        @keyframes slideInUp {
            from {
                transform: translateY(100%);
                opacity: 0;
            }
            to {
                transform: translateY(0);
                opacity: 1;
            }
        }

        @keyframes slideOutDown {
            from {
                transform: translateY(0);
                opacity: 1;
            }
            to {
                transform: translateY(100%);
                opacity: 0;
            }
        }

        .message-container.optimistic {
            opacity: 0.7;
        }

        .typing-indicator {
            padding: 0.5rem;
            font-style: italic;
            color: #6c757d;
            animation: fadeInUp 0.3s ease;
        }

        .star-btn:hover,
        .temu-star-input:hover {
            transform: scale(1.1);
            transition: transform 0.2s ease;
        }

        .character-counter.text-warning {
            font-weight: 600;
        }

        .review-card {
            transition: all 0.3s ease;
        }

        .search-highlight {
            background-color: #fff3cd;
            color: #856404;
            padding: 0 2px;
            border-radius: 2px;
        }

        /* Fix for chat box positioning */
        .temu-floating-chat {
            position: fixed !important;
            z-index: 1050 !important;
        }
    `;
    document.head.appendChild(style);
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    console.log('Initializing Chat and Review systems...');

    // Initialize Review System
    ReviewSystem.init();

    // Initialize Chat System
    ChatSystem.init();

    console.log('Systems initialized successfully');
});

// Export modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ReviewSystem, ChatSystem };
}