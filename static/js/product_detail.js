/**
 * Enhanced Product Detail Page JavaScript - COMPLETE FIXED VERSION
 * Handles image display, chat, reviews, and all product interactions
 */

'use strict';

// ===================================
// ENHANCED IMAGE HANDLER CLASS
// ===================================
class ProductImageHandler {
    constructor() {
        this.currentImage = null;
        this.isContainMode = false;
        this.isZoomed = false;
        this.zoomLevel = 1;
        this.init();
    }

    init() {
        this.setupImageControls();
        this.setupImageLoadHandling();
        this.setupKeyboardControls();
        this.setupTouchControls();
        
        console.log('Product Image Handler initialized');
    }

    setupImageControls() {
        // Add image control buttons to the overlay
        const mainImageContainer = document.querySelector('.main-image-container');
        if (!mainImageContainer) return;

        // Create image overlay if it doesn't exist
        let overlay = mainImageContainer.querySelector('.image-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'image-overlay';
            mainImageContainer.appendChild(overlay);
        }

        // Add control buttons
        overlay.innerHTML = `
            <div class="image-info">
                <small class="text-white">Hover to zoom</small>
            </div>
            <div class="image-controls">
                <button class="fit-toggle-btn" title="Toggle fit mode" aria-label="Toggle image fit mode">
                    <i class="fas fa-expand-arrows-alt"></i>
                </button>
                <button class="fullscreen-btn" title="View fullscreen" aria-label="View image in fullscreen">
                    <i class="fas fa-expand"></i>
                </button>
                <button class="zoom-btn" title="Zoom image" aria-label="Zoom image">
                    <i class="fas fa-search-plus"></i>
                </button>
            </div>
        `;

        // Bind button events
        this.bindControlEvents(overlay);
    }

    bindControlEvents(overlay) {
        const fitToggleBtn = overlay.querySelector('.fit-toggle-btn');
        const fullscreenBtn = overlay.querySelector('.fullscreen-btn');
        const zoomBtn = overlay.querySelector('.zoom-btn');

        if (fitToggleBtn) {
            fitToggleBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleFitMode();
            });
        }

        if (fullscreenBtn) {
            fullscreenBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.openFullscreen();
            });
        }

        if (zoomBtn) {
            zoomBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleZoom();
            });
        }
    }

    setupImageLoadHandling() {
        const mainImage = document.getElementById('mainProductImage');
        if (!mainImage) return;

        this.currentImage = mainImage;

        // Handle image loading states
        mainImage.addEventListener('load', () => {
            this.handleImageLoad(mainImage);
        });

        mainImage.addEventListener('error', () => {
            this.handleImageError(mainImage);
        });

        // Initial setup for current image
        if (mainImage.complete) {
            this.handleImageLoad(mainImage);
        }
    }

    handleImageLoad(img) {
        const container = img.closest('.main-image-container');
        if (!container) return;

        // Remove loading state
        container.classList.remove('loading');

        // Determine optimal display mode based on image dimensions
        const aspectRatio = img.naturalWidth / img.naturalHeight;
        
        // If image is very tall (portrait), use contain mode by default
        if (aspectRatio < 0.75) {
            this.setContainMode(true);
        } else {
            this.setContainMode(false);
        }

        // Update fit toggle button icon
        this.updateFitToggleIcon();
    }

    handleImageError(img) {
        const container = img.closest('.image-wrapper');
        if (!container) return;

        container.innerHTML = `
            <div class="image-error">
                <i class="fas fa-image"></i>
                <div>Image not available</div>
                <small>Unable to load image</small>
            </div>
        `;
    }

    toggleFitMode() {
        this.setContainMode(!this.isContainMode);
        this.updateFitToggleIcon();
        
        // Show feedback
        this.showFeedback(this.isContainMode ? 'Fit to container' : 'Fill container');
    }

    setContainMode(enable) {
        const mainImage = document.getElementById('mainProductImage');
        if (!mainImage) return;

        this.isContainMode = enable;

        if (enable) {
            mainImage.classList.add('contain-mode');
        } else {
            mainImage.classList.remove('contain-mode');
        }
    }

    updateFitToggleIcon() {
        const fitToggleBtn = document.querySelector('.fit-toggle-btn i');
        if (!fitToggleBtn) return;

        if (this.isContainMode) {
            fitToggleBtn.className = 'fas fa-compress-arrows-alt';
        } else {
            fitToggleBtn.className = 'fas fa-expand-arrows-alt';
        }
    }

    toggleZoom() {
        const mainImage = document.getElementById('mainProductImage');
        if (!mainImage) return;

        this.isZoomed = !this.isZoomed;

        if (this.isZoomed) {
            mainImage.style.transform = 'scale(1.5)';
            mainImage.style.cursor = 'zoom-out';
            this.showFeedback('Zoomed in');
        } else {
            mainImage.style.transform = 'scale(1)';
            mainImage.style.cursor = 'zoom-in';
            this.showFeedback('Zoomed out');
        }

        // Update zoom button icon
        const zoomBtn = document.querySelector('.zoom-btn i');
        if (zoomBtn) {
            zoomBtn.className = this.isZoomed ? 'fas fa-search-minus' : 'fas fa-search-plus';
        }
    }

    openFullscreen() {
        const mainImage = document.getElementById('mainProductImage');
        if (!mainImage) return;

        // Create fullscreen modal
        const modal = this.createFullscreenModal(mainImage.src, mainImage.alt);
        document.body.appendChild(modal);

        // Show modal
        const bootstrapModal = new bootstrap.Modal(modal);
        bootstrapModal.show();

        // Clean up when modal is hidden
        modal.addEventListener('hidden.bs.modal', () => {
            modal.remove();
        });
    }

    createFullscreenModal(src, alt) {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-xl modal-dialog-centered">
                <div class="modal-content bg-dark">
                    <div class="modal-header border-0">
                        <h5 class="modal-title text-white">${alt || 'Product Image'}</h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body p-0 text-center">
                        <img src="${src}" alt="${alt}" class="img-fluid" style="max-height: 80vh; object-fit: contain;">
                    </div>
                </div>
            </div>
        `;
        return modal;
    }

    setupKeyboardControls() {
        document.addEventListener('keydown', (e) => {
            // Only handle if image area is focused or no input is focused
            const activeElement = document.activeElement;
            if (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA') {
                return;
            }

            switch (e.key) {
                case 'f':
                case 'F':
                    if (!e.ctrlKey && !e.metaKey) {
                        e.preventDefault();
                        this.toggleFitMode();
                    }
                    break;
                case 'z':
                case 'Z':
                    if (!e.ctrlKey && !e.metaKey) {
                        e.preventDefault();
                        this.toggleZoom();
                    }
                    break;
                case 'Enter':
                    if (e.target.closest('.main-image-container')) {
                        e.preventDefault();
                        this.openFullscreen();
                    }
                    break;
            }
        });
    }

    setupTouchControls() {
        const mainImage = document.getElementById('mainProductImage');
        if (!mainImage) return;

        let touchStartTime = 0;

        mainImage.addEventListener('touchstart', (e) => {
            touchStartTime = Date.now();
        });

        mainImage.addEventListener('touchend', (e) => {
            const touchDuration = Date.now() - touchStartTime;
            
            // Double tap to zoom (touch duration < 300ms)
            if (touchDuration < 300) {
                e.preventDefault();
                this.toggleZoom();
            }
        });
    }

    showFeedback(message) {
        // Create or update feedback element
        let feedback = document.querySelector('.image-feedback');
        
        if (!feedback) {
            feedback = document.createElement('div');
            feedback.className = 'image-feedback position-fixed';
            feedback.style.cssText = `
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                background: rgba(0,0,0,0.8);
                color: white;
                padding: 0.5rem 1rem;
                border-radius: 20px;
                font-size: 0.9rem;
                z-index: 1060;
                pointer-events: none;
                opacity: 0;
                transition: opacity 0.3s ease;
            `;
            document.body.appendChild(feedback);
        }

        feedback.textContent = message;
        feedback.style.opacity = '1';

        // Hide after 1.5 seconds
        setTimeout(() => {
            feedback.style.opacity = '0';
        }, 1500);
    }

    // Enhanced image changing with better loading states
    changeImage(thumbnail, imageUrl) {
        const mainImage = document.getElementById('mainProductImage');
        if (!mainImage) return;

        // Show loading state
        const container = mainImage.closest('.main-image-container');
        if (container) {
            container.classList.add('loading');
        }

        // Reset zoom state
        this.isZoomed = false;
        mainImage.style.transform = 'scale(1)';
        mainImage.style.cursor = 'zoom-in';

        // Update zoom button icon
        const zoomBtn = document.querySelector('.zoom-btn i');
        if (zoomBtn) {
            zoomBtn.className = 'fas fa-search-plus';
        }

        // Change image source
        mainImage.src = imageUrl;

        // Update active thumbnail
        document.querySelectorAll('.thumbnail-item').forEach(item => {
            item.classList.remove('active');
            item.setAttribute('aria-selected', 'false');
        });
        if (thumbnail) {
            thumbnail.classList.add('active');
            thumbnail.setAttribute('aria-selected', 'true');
        }
    }
}

// ===================================
// THUMBNAIL GALLERY CLASS
// ===================================
class ThumbnailGallery {
    constructor() {
        this.init();
    }

    init() {
        this.setupThumbnailNavigation();
        this.setupInfiniteScroll();
    }

    setupThumbnailNavigation() {
        const gallery = document.querySelector('.thumbnail-gallery');
        if (!gallery) return;

        // Add navigation arrows if there are many thumbnails
        const thumbnails = gallery.querySelectorAll('.thumbnail-item');
        if (thumbnails.length > 5) {
            this.addNavigationArrows(gallery);
        }

        // Setup thumbnail click handlers
        thumbnails.forEach((thumbnail, index) => {
            thumbnail.addEventListener('click', () => {
                this.selectThumbnail(thumbnail, index);
            });

            // Keyboard support
            thumbnail.addEventListener('keydown', (e) => {
                this.handleKeyboardNavigation(e, thumbnails, index);
            });

            // Make thumbnails focusable
            thumbnail.setAttribute('tabindex', '0');
        });
    }

    handleKeyboardNavigation(e, thumbnails, currentIndex) {
        let targetIndex = currentIndex;
        
        switch(e.key) {
            case 'ArrowLeft':
                e.preventDefault();
                targetIndex = currentIndex > 0 ? currentIndex - 1 : thumbnails.length - 1;
                break;
            case 'ArrowRight':
                e.preventDefault();
                targetIndex = currentIndex < thumbnails.length - 1 ? currentIndex + 1 : 0;
                break;
            case 'Home':
                e.preventDefault();
                targetIndex = 0;
                break;
            case 'End':
                e.preventDefault();
                targetIndex = thumbnails.length - 1;
                break;
            case 'Enter':
            case ' ':
                e.preventDefault();
                this.selectThumbnail(thumbnails[currentIndex], currentIndex);
                return;
            default:
                return;
        }
        
        thumbnails[targetIndex].focus();
        this.selectThumbnail(thumbnails[targetIndex], targetIndex);
    }

    addNavigationArrows(gallery) {
        const container = gallery.parentElement;
        
        const prevBtn = document.createElement('button');
        prevBtn.className = 'thumbnail-nav-btn prev-btn';
        prevBtn.innerHTML = '<i class="fas fa-chevron-left"></i>';
        prevBtn.setAttribute('aria-label', 'Previous images');

        const nextBtn = document.createElement('button');
        nextBtn.className = 'thumbnail-nav-btn next-btn';
        nextBtn.innerHTML = '<i class="fas fa-chevron-right"></i>';
        nextBtn.setAttribute('aria-label', 'Next images');

        container.style.position = 'relative';
        container.appendChild(prevBtn);
        container.appendChild(nextBtn);

        // Add navigation styles
        const style = document.createElement('style');
        style.textContent = `
            .thumbnail-nav-btn {
                position: absolute;
                top: 50%;
                transform: translateY(-50%);
                background: rgba(255,255,255,0.9);
                border: 1px solid #dee2e6;
                border-radius: 50%;
                width: 30px;
                height: 30px;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                z-index: 10;
                transition: all 0.3s ease;
            }
            .thumbnail-nav-btn:hover {
                background: white;
                box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            }
            .prev-btn { left: -15px; }
            .next-btn { right: -15px; }
        `;
        document.head.appendChild(style);

        // Bind navigation events
        prevBtn.addEventListener('click', () => {
            gallery.scrollBy({ left: -150, behavior: 'smooth' });
        });

        nextBtn.addEventListener('click', () => {
            gallery.scrollBy({ left: 150, behavior: 'smooth' });
        });
    }

    selectThumbnail(thumbnail, index) {
        const imageUrl = thumbnail.dataset.image;
        if (!imageUrl) return;

        // Use enhanced image changing
        if (window.imageHandler) {
            window.imageHandler.changeImage(thumbnail, imageUrl);
        }

        // Handle features if they exist
        if (window.changeMainImageWithFeatures) {
            window.changeMainImageWithFeatures(thumbnail);
        }

        // Scroll thumbnail into view if needed
        thumbnail.scrollIntoView({
            behavior: 'smooth',
            block: 'nearest',
            inline: 'center'
        });
    }

    setupInfiniteScroll() {
        // Add smooth scrolling for thumbnail gallery
        const gallery = document.querySelector('.thumbnail-gallery');
        if (!gallery) return;

        gallery.addEventListener('wheel', (e) => {
            // Allow horizontal scrolling with mouse wheel
            if (Math.abs(e.deltaX) < Math.abs(e.deltaY)) {
                e.preventDefault();
                gallery.scrollBy({
                    left: e.deltaY > 0 ? 100 : -100,
                    behavior: 'smooth'
                });
            }
        });
    }
}

// ===================================
// CHAT SYSTEM - FIXED VERSION
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
        // Use event delegation for chat buttons
        document.addEventListener('click', (e) => {
            // Chat toggle buttons
            if (e.target.matches('.btn-chat') || e.target.closest('.btn-chat')) {
                e.preventDefault();
                e.stopPropagation();
                this.toggleChat();
            }
            
            // Close chat button
            if (e.target.matches('.chat-close') || e.target.closest('.chat-close')) {
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

            // Send via HTTP
            await this.sendMessageViaHTTP(form, message);

        } catch (error) {
            console.error('Send message error:', error);
            this.showNotification('Failed to send message', 'error');
            this.removeLastOptimisticMessage();
        }
    },

    async sendMessageViaHTTP(form, message) {
        const formData = new FormData(form);
        formData.set('message', message);

        const response = await fetch(form.action || '/chat/start_chat/', {
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
        if (window.showToast) {
            window.showToast(message, type);
        } else {
            console.log(`${type.toUpperCase()}: ${message}`);
        }
    }
};

// ===================================
// REVIEW SYSTEM
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
        this.bindLoadMoreEvents();
    },

    bindStarRatingEvents() {
        const starContainer = document.querySelector('.star-rating');
        if (!starContainer) return;

        const stars = starContainer.querySelectorAll('.star-btn');

        stars.forEach((star, index) => {
            const rating = parseInt(star.dataset.rating) || index + 1;

            star.addEventListener('click', (e) => {
                e.preventDefault();
                this.setRating(rating);
            });

            star.addEventListener('mouseenter', () => {
                this.highlightStars(rating, true);
            });

            star.addEventListener('mouseleave', () => {
                this.highlightStars(this.state.selectedRating);
            });
        });

        starContainer.addEventListener('mouseleave', () => {
            this.highlightStars(this.state.selectedRating);
        });
    },

    setRating(rating) {
        this.state.selectedRating = rating;

        const ratingInput = document.getElementById('rating-input');
        if (ratingInput) {
            ratingInput.value = rating;
        }

        this.highlightStars(rating);
        console.log('Rating set:', rating);
    },

    highlightStars(rating, isHover = false) {
        const stars = document.querySelectorAll('.star-btn');

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

    bindReviewFormEvents() {
        const reviewForm = document.getElementById('review-form');
        if (!reviewForm) return;

        reviewForm.addEventListener('submit', (e) => {
            e.preventDefault();
            this.submitReview(reviewForm);
        });
    },

    async submitReview(form) {
        if (this.config.isLoading) return;

        try {
            if (this.state.selectedRating === 0) {
                this.showNotification('Please select a rating', 'warning');
                return;
            }

            this.config.isLoading = true;
            this.setSubmitButtonLoading(true);

            const formData = new FormData(form);
            if (this.config.productId) {
                formData.set('product_id', this.config.productId);
            }

            const response = await fetch(this.config.urls.submit, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

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

    handleReviewSubmitSuccess(data, form) {
        this.resetReviewForm(form);
        this.loadReviews(1);
        this.showNotification(data.message || 'Review submitted successfully!', 'success');

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
    },

    setSubmitButtonLoading(isLoading) {
        const submitBtn = document.querySelector('#review-form button[type="submit"]');
        if (!submitBtn) return;

        const spinner = submitBtn.querySelector('.spinner-border');
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
            const response = await fetch(url);

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
        const container = document.getElementById('reviews-container');
        if (!container) return;

        if (page === 1) {
            container.innerHTML = data.reviews_html || this.getEmptyReviewsHtml();
        } else {
            container.insertAdjacentHTML('beforeend', data.reviews_html || '');
        }
    },

    showReviewsLoading() {
        const container = document.getElementById('reviews-container');
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
        const container = document.getElementById('reviews-container');
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

    showNotification(message, type) {
        if (window.showToast) {
            window.showToast(message, type);
        } else {
            console.log(`${type.toUpperCase()}: ${message}`);
        }
    }
};

// ===================================
// PRODUCT FUNCTIONS
// ===================================

function buyNow(productId) {
    const selectedFeatures = {};
    document.querySelectorAll('input[type="radio"]:checked').forEach(input => {
        selectedFeatures[input.name] = input.value;
    });

    const quantityInput = document.getElementById('quantity');
    const quantity = quantityInput ? parseInt(quantityInput.value) : 1;

    document.getElementById('buyNowProduct').value = productId;
    document.getElementById('buyNowQuantity').value = quantity;

    const form = document.getElementById('buyNowForm');
    const existingFeatureInputs = form.querySelectorAll('input[name^="feature_"]');
    existingFeatureInputs.forEach(input => input.remove());

    Object.entries(selectedFeatures).forEach(([feature, value]) => {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = `feature_${feature}`;
        input.value = value;
        form.appendChild(input);
    });

    form.submit();
}

function updateCartBadge(count) {
    const cartBadge = document.querySelector('.cart-count, .badge-cart, [data-cart-count]');
    if (cartBadge) {
        cartBadge.textContent = count;
    }
}

function changeQuantity(change) {
    const quantityInput = document.getElementById('quantity');
    if (quantityInput) {
        const currentValue = parseInt(quantityInput.value);
        const newValue = currentValue + change;
        const min = parseInt(quantityInput.min);
        const max = parseInt(quantityInput.max);

        if (newValue >= min && newValue <= max) {
            quantityInput.value = newValue;
        }
    }
}

// Enhanced image changing with feature sync
function changeMainImageWithFeatures(thumbnail) {
    const imageUrl = thumbnail.dataset.image;
    let featuresData = {};

    try {
        const featuresStr = thumbnail.dataset.features || '{}';
        featuresData = JSON.parse(featuresStr);
    } catch (e) {
        console.warn('Invalid JSON in thumbnail data-features:', thumbnail.dataset.features);
        featuresData = {};
    }

    // Use enhanced image handler if available
    if (window.imageHandler) {
        window.imageHandler.changeImage(thumbnail, imageUrl);
    } else {
        // Fallback for basic image changing
        const mainImage = document.getElementById('mainProductImage');
        if (mainImage && imageUrl) {
            const container = mainImage.closest('.main-image-container');
            if (container) container.classList.add('loading');

            mainImage.onload = function() {
                if (container) container.classList.remove('loading');
            };

            mainImage.src = imageUrl;
            mainImage.alt = generateAltText(featuresData);
        }

        // Update active thumbnail
        document.querySelectorAll('.thumbnail-item').forEach(item => {
            item.classList.remove('active');
            item.setAttribute('aria-selected', 'false');
        });
        thumbnail.classList.add('active');
        thumbnail.setAttribute('aria-selected', 'true');
    }

    // Update features based on image data
    if (Object.keys(featuresData).length > 0) {
        updateFeaturesFromImage(featuresData);
        showSyncIndicators(featuresData);
    }

    updateSelectionDisplay();
}

function generateAltText(featuresData) {
    const productName = document.querySelector('.product-title')?.textContent || 'Product';
    const featureStrings = Object.entries(featuresData).map(([key, value]) => `${value} ${key}`);
    return featureStrings.length > 0 ? `${productName} - ${featureStrings.join(', ')}` : productName;
}

function updateFeaturesFromImage(featuresData) {
    Object.keys(featuresData).forEach(featureName => {
        const featureValue = featuresData[featureName];
        const normalizedFeatureName = featureName.toLowerCase().replace(/\s+/g, '');
        const normalizedFeatureValue = featureValue.toLowerCase().replace(/\s+/g, '-');
        const radioInput = document.getElementById(`${normalizedFeatureName}_${normalizedFeatureValue}`);

        if (radioInput) {
            radioInput.checked = true;
            radioInput.dispatchEvent(new Event('change', { bubbles: true }));

            const featureGroup = document.getElementById(`${normalizedFeatureName}FeatureGroup`);
            if (featureGroup) {
                featureGroup.classList.add('highlighted');
                setTimeout(() => featureGroup.classList.remove('highlighted'), 1000);
            }
        }
    });
}

function showSyncIndicators(featuresData) {
    document.querySelectorAll('.feature-sync-indicator').forEach(indicator => {
        indicator.classList.remove('active');
    });

    Object.keys(featuresData).forEach(featureName => {
        const normalizedFeatureName = featureName.toLowerCase().replace(/\s+/g, '');
        const indicator = document.getElementById(`${normalizedFeatureName}SyncIndicator`);

        if (indicator) {
            indicator.classList.add('active');
            setTimeout(() => indicator.classList.remove('active'), 2000);
        }
    });
}

function updateSelectionDisplay() {
    const displayElement = document.getElementById('selectionDisplay');
    if (!displayElement) return;

    const selections = {};
    document.querySelectorAll('input[type="radio"]:checked').forEach(input => {
        const featureName = input.name;
        const featureValue = input.value;
        const featureLabel = input.nextElementSibling?.querySelector('.color-name, span:last-child')?.textContent?.trim() || featureValue;
        selections[featureName] = featureLabel;
    });

    let html = '';
    Object.entries(selections).forEach(([name, value]) => {
        const displayName = name.charAt(0).toUpperCase() + name.slice(1);
        html += `<strong>${displayName}:</strong> ${value}<br>`;
    });
    displayElement.innerHTML = html || 'No selections made';
}

// Wishlist functionality
function toggleWishlist(productId) {
    const btn = document.getElementById(`wishlistBtn-${productId}`);
    const icon = document.getElementById(`wishlistIcon-${productId}`);

    fetch(`/wishlist/toggle/${productId}/`, {
        method: 'GET',
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (data.status === 'added') {
                icon.classList.remove('far');
                icon.classList.add('fas', 'text-danger');
            } else if (data.status === 'removed') {
                icon.classList.remove('fas', 'text-danger');
                icon.classList.add('far');
            }
        } else {
            alert(data.error || "Something went wrong.");
        }
    })
    .catch(error => {
        console.error('Wishlist toggle failed:', error);
        alert("An error occurred while updating your wishlist.");
    });
}

// Utility functions
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast('Link copied to clipboard!', 'success');
    }).catch(err => {
        console.error('Failed to copy: ', err);
        showToast('Failed to copy link', 'error');
    });
}

function showToast(message, type = 'info') {
    // Create toast element
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type === 'success' ? 'success' : type === 'error' ? 'danger' : 'primary'} border-0`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');

    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;

    // Add to container
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        document.body.appendChild(container);
    }

    container.appendChild(toast);

    // Show toast
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();

    // Remove from DOM after hiding
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}

// ===================================
// INITIALIZATION
// ===================================

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    console.log('Initializing Product Detail Systems...');
    
    // Initialize Image Handler
    window.imageHandler = new ProductImageHandler();
    
    // Initialize Thumbnail Gallery
    window.thumbnailGallery = new ThumbnailGallery();
    
    // Initialize Chat System
    ChatSystem.init();
    
    // Initialize Review System
    ReviewSystem.init();
    
    // Initialize feature change listeners
    document.querySelectorAll('input[type="radio"]').forEach(input => {
        input.addEventListener('change', updateSelectionDisplay);
    });
    
    // Initialize selection display
    updateSelectionDisplay();
    
    console.log('All systems initialized successfully');
});

// Add CSS animations if not already present
if (!document.getElementById('product-animations')) {
    const style = document.createElement('style');
    style.id = 'product-animations';
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

        .star-btn:hover {
            transform: scale(1.1);
            transition: transform 0.2s ease;
        }

        .chat-widget {
            position: fixed !important;
            z-index: 1050 !important;
        }
    `;
    document.head.appendChild(style);
}