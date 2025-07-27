class StoreFollowManager {
    constructor() {
        this.storeId = null;
        this.isFollowing = false;
        this.notificationCheckInterval = null;
        this.unreadCount = 0;

        this.init();
    }

    init() {
        // Get store ID from the page
        const followBtn = document.querySelector('.btn-follow');
        if (followBtn) {
            this.storeId = followBtn.dataset.storeId;
            this.loadFollowStatus();
        }

        // Initialize notification system
        this.initNotifications();

        // Set up periodic notification checking
        if (this.isUserAuthenticated()) {
            this.startNotificationPolling();
        }

        // Bind events
        this.bindEvents();
    }

    isUserAuthenticated() {
        // Check if user is authenticated (you can modify this based on your setup)
        return document.body.dataset.userAuthenticated === 'true' ||
               document.querySelector('meta[name="user-authenticated"]')?.content === 'true';
    }

    async loadFollowStatus() {
        try {
            const response = await fetch(`/api/follow-status/${this.storeId}/`);
            const data = await response.json();

            this.isFollowing = data.is_following;
            this.updateFollowButton();
            this.updateFollowersCount(data.followers_count);

        } catch (error) {
            console.error('Error loading follow status:', error);
        }
    }

    async toggleFollow() {
        if (!this.isUserAuthenticated()) {
            this.showLoginModal();
            return;
        }

        const followBtn = document.querySelector('.btn-follow');
        const originalText = followBtn.innerHTML;

        // Show loading state
        followBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span>Processing...</span>';
        followBtn.disabled = true;

        try {
            const response = await fetch(`/api/follow/${this.storeId}/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                }
            });

            const data = await response.json();

            if (data.success) {
                this.isFollowing = data.is_following;
                this.updateFollowButton();
                this.updateFollowersCount(data.followers_count);
                this.showToast('success', data.message);

                // Show notification preferences if just followed
                if (this.isFollowing) {
                    setTimeout(() => this.showNotificationPreferences(), 1000);
                }
            } else {
                this.showToast('error', data.message);
            }

        } catch (error) {
            console.error('Error toggling follow:', error);
            this.showToast('error', 'An error occurred. Please try again.');
        } finally {
            followBtn.innerHTML = originalText;
            followBtn.disabled = false;
            this.updateFollowButton();
        }
    }

    updateFollowButton() {
        const followBtn = document.querySelector('.btn-follow');
        const icon = followBtn.querySelector('i');
        const text = followBtn.querySelector('.btn-text');

        if (this.isFollowing) {
            followBtn.classList.remove('btn-outline-light');
            followBtn.classList.add('btn-success');
            icon.className = 'fas fa-check';
            text.textContent = 'Following';
            followBtn.setAttribute('aria-label', 'Unfollow store');
        } else {
            followBtn.classList.remove('btn-success');
            followBtn.classList.add('btn-outline-light');
            icon.className = 'fas fa-heart';
            text.textContent = 'Follow';
            followBtn.setAttribute('aria-label', 'Follow store');
        }
    }

    updateFollowersCount(count) {
        const countElement = document.querySelector('.followers-count');
        if (countElement) {
            countElement.textContent = count;
        }
    }

    showNotificationPreferences() {
        const modal = this.createNotificationPreferencesModal();
        document.body.appendChild(modal);
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();

        // Remove modal when hidden
        modal.addEventListener('hidden.bs.modal', () => {
            modal.remove();
        });
    }

    createNotificationPreferencesModal() {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Notification Preferences</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p class="mb-3">Choose what notifications you'd like to receive from this store:</p>
                        <div class="form-check mb-2">
                            <input class="form-check-input" type="checkbox" id="notifyNewProducts" checked>
                            <label class="form-check-label" for="notifyNewProducts">
                                <i class="fas fa-box text-primary me-2"></i>New Products
                            </label>
                        </div>
                        <div class="form-check mb-2">
                            <input class="form-check-input" type="checkbox" id="notifyPriceChanges" checked>
                            <label class="form-check-label" for="notifyPriceChanges">
                                <i class="fas fa-tag text-success me-2"></i>Price Changes
                            </label>
                        </div>
                        <div class="form-check mb-2">
                            <input class="form-check-input" type="checkbox" id="notifyDiscounts" checked>
                            <label class="form-check-label" for="notifyDiscounts">
                                <i class="fas fa-percent text-danger me-2"></i>Special Discounts
                            </label>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Skip</button>
                        <button type="button" class="btn btn-primary" onclick="storeFollowManager.saveNotificationPreferences(this)">
                            Save Preferences
                        </button>
                    </div>
                </div>
            </div>
        `;
        return modal;
    }

    async saveNotificationPreferences(button) {
        const modal = button.closest('.modal');
        const preferences = {
            notify_new_products: modal.querySelector('#notifyNewProducts').checked,
            notify_price_changes: modal.querySelector('#notifyPriceChanges').checked,
            notify_discounts: modal.querySelector('#notifyDiscounts').checked
        };

        try {
            const response = await fetch(`/api/notifications/preferences/${this.storeId}/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(preferences)
            });

            const data = await response.json();

            if (data.success) {
                this.showToast('success', 'Preferences saved successfully!');
                bootstrap.Modal.getInstance(modal).hide();
            } else {
                this.showToast('error', 'Failed to save preferences.');
            }

        } catch (error) {
            console.error('Error saving preferences:', error);
            this.showToast('error', 'An error occurred while saving preferences.');
        }
    }

    initNotifications() {
        this.createNotificationCenter();
        this.loadNotifications();
    }

    createNotificationCenter() {
        // Add notification bell to header if it doesn't exist
        const header = document.querySelector('.store-actions');
        if (header && this.isUserAuthenticated()) {
            const notificationBtn = document.createElement('button');
            notificationBtn.className = 'btn btn-outline-light btn-notifications position-relative';
            notificationBtn.innerHTML = `
                <i class="fas fa-bell"></i>
                <span class="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger notification-badge" style="display: none;">
                    0
                </span>
            `;
            notificationBtn.onclick = () => this.showNotificationPanel();
            header.appendChild(notificationBtn);
        }
    }

    async loadNotifications() {
        if (!this.isUserAuthenticated()) return;

        try {
            const response = await fetch('/api/notifications/');
            const data = await response.json();

            if (data.success) {
                this.unreadCount = data.unread_count;
                this.updateNotificationBadge();
            }

        } catch (error) {
            console.error('Error loading notifications:', error);
        }
    }

    updateNotificationBadge() {
        const badge = document.querySelector('.notification-badge');
        if (badge) {
            if (this.unreadCount > 0) {
                badge.textContent = this.unreadCount > 99 ? '99+' : this.unreadCount;
                badge.style.display = 'block';
            } else {
                badge.style.display = 'none';
            }
        }
    }

    async showNotificationPanel() {
        const modal = this.createNotificationModal();
        document.body.appendChild(modal);

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();

        // Load notifications
        await this.loadNotificationsList(modal);

        // Remove modal when hidden
        modal.addEventListener('hidden.bs.modal', () => {
            modal.remove();
        });
    }

    createNotificationModal() {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-bell me-2"></i>Notifications
                        </h5>
                        <div class="d-flex gap-2">
                            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="storeFollowManager.markAllAsRead()">
                                Mark All Read
                            </button>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                    </div>
                    <div class="modal-body p-0">
                        <div class="notifications-loading text-center p-4">
                            <i class="fas fa-spinner fa-spin"></i>
                            <p class="mt-2">Loading notifications...</p>
                        </div>
                        <div class="notifications-list" style="max-height: 400px; overflow-y: auto;"></div>
                    </div>
                </div>
            </div>
        `;
        return modal;
    }

    async loadNotificationsList(modal) {
        try {
            const response = await fetch('/api/notifications/');
            const data = await response.json();

            const loadingDiv = modal.querySelector('.notifications-loading');
            const listDiv = modal.querySelector('.notifications-list');

            loadingDiv.style.display = 'none';

            if (data.success && data.notifications.length > 0) {
                listDiv.innerHTML = data.notifications.map(notification =>
                    this.createNotificationItem(notification)
                ).join('');
            } else {
                listDiv.innerHTML = `
                    <div class="text-center p-4 text-muted">
                        <i class="fas fa-bell-slash fa-2x mb-2"></i>
                        <p>No notifications yet</p>
                    </div>
                `;
            }

        } catch (error) {
            console.error('Error loading notifications:', error);
            modal.querySelector('.notifications-loading').innerHTML = `
                <div class="text-danger">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>Error loading notifications</p>
                </div>
            `;
        }
    }

    createNotificationItem(notification) {
        const iconMap = {
            new_product: 'fas fa-box text-primary',
            price_decrease: 'fas fa-arrow-down text-success',
            price_increase: 'fas fa-arrow-up text-warning',
            discount: 'fas fa-percent text-danger',
            back_in_stock: 'fas fa-check-circle text-success'
        };

        const icon = iconMap[notification.type] || 'fas fa-bell text-info';
        const timeAgo = this.formatTimeAgo(new Date(notification.created_at));

        return `
            <div class="notification-item p-3 border-bottom ${notification.is_read ? '' : 'bg-light'}"
                 data-notification-id="${notification.id}">
                <div class="d-flex">
                    <div class="notification-icon me-3">
                        <i class="${icon}"></i>
                    </div>
                    <div class="notification-content flex-grow-1">
                        <h6 class="notification-title mb-1">${notification.title}</h6>
                        <p class="notification-message mb-1 text-muted small">${notification.message}</p>
                        <div class="d-flex justify-content-between align-items-center">
                            <small class="text-muted">
                                <i class="fas fa-store me-1"></i>${notification.store_name} • ${timeAgo}
                            </small>
                            ${!notification.is_read ? `
                                <button class="btn btn-sm btn-outline-primary"
                                        onclick="storeFollowManager.markAsRead(${notification.id}, this)">
                                    Mark Read
                                </button>
                            ` : ''}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    async markAsRead(notificationId, button) {
        try {
            const response = await fetch(`/api/notifications/${notificationId}/read/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                }
            });

            const data = await response.json();

            if (data.success) {
                const notificationItem = button.closest('.notification-item');
                notificationItem.classList.remove('bg-light');
                button.remove();

                this.unreadCount = data.unread_count;
                this.updateNotificationBadge();
            }

        } catch (error) {
            console.error('Error marking notification as read:', error);
        }
    }

    async markAllAsRead() {
        try {
            const response = await fetch('/api/notifications/mark-all-read/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                }
            });

            const data = await response.json();

            if (data.success) {
                // Update UI
                const notificationItems = document.querySelectorAll('.notification-item');
                notificationItems.forEach(item => {
                    item.classList.remove('bg-light');
                    const markReadBtn = item.querySelector('button');
                    if (markReadBtn) markReadBtn.remove();
                });

                this.unreadCount = 0;
                this.updateNotificationBadge();
                this.showToast('success', 'All notifications marked as read');
            }

        } catch (error) {
            console.error('Error marking all notifications as read:', error);
        }
    }

    startNotificationPolling() {
        // Check for new notifications every 30 seconds
        this.notificationCheckInterval = setInterval(() => {
            this.loadNotifications();
        }, 30000);
    }

    stopNotificationPolling() {
        if (this.notificationCheckInterval) {
            clearInterval(this.notificationCheckInterval);
        }
    }

    formatTimeAgo(date) {
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);

        if (seconds < 60) return 'just now';
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
        return `${Math.floor(seconds / 86400)}d ago`;
    }

    showLoginModal() {
        // You can customize this based on your login modal
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Login Required</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p>Please log in to follow stores and receive notifications.</p>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <a href="/login/" class="btn btn-primary">Login</a>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();

        modal.addEventListener('hidden.bs.modal', () => {
            modal.remove();
        });
    }

    showToast(type, message) {
        const toastId = type === 'success' ? 'successToast' : 'errorToast';
        const toast = document.getElementById(toastId);

        if (toast) {
            toast.querySelector('.toast-body').textContent = message;
            const bsToast = new bootstrap.Toast(toast);
            bsToast.show();
        }
    }

    getCSRFToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
               document.querySelector('meta[name="csrf-token"]')?.content ||
               '';
    }

    bindEvents() {
        // Bind follow button click
        const followBtn = document.querySelector('.btn-follow');
        if (followBtn) {
            followBtn.addEventListener('click', () => this.toggleFollow());
        }

        // Handle page unload
        window.addEventListener('beforeunload', () => {
            this.stopNotificationPolling();
        });
    }
}

// Global function for backward compatibility with existing template
function toggleFavorite(storeId) {
    if (window.storeFollowManager) {
        window.storeFollowManager.toggleFollow();
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    window.storeFollowManager = new StoreFollowManager();
});

// Also initialize if page is already loaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        if (!window.storeFollowManager) {
            window.storeFollowManager = new StoreFollowManager();
        }
    });
} else {
    if (!window.storeFollowManager) {
        window.storeFollowManager = new StoreFollowManager();
    }
}class StoreFollowManager {
    constructor() {
        this.storeId = null;
        this.isFollowing = false;
        this.notificationCheckInterval = null;
        this.unreadCount = 0;

        this.init();
    }

    init() {
        // Get store ID from the page
        const followBtn = document.querySelector('.btn-follow');
        if (followBtn) {
            this.storeId = followBtn.dataset.storeId;
            this.loadFollowStatus();
        }

        // Initialize notification system
        this.initNotifications();

        // Set up periodic notification checking
        if (this.isUserAuthenticated()) {
            this.startNotificationPolling();
        }

        // Bind events
        this.bindEvents();
    }

    isUserAuthenticated() {
        // Check if user is authenticated (you can modify this based on your setup)
        return document.body.dataset.userAuthenticated === 'true' ||
               document.querySelector('meta[name="user-authenticated"]')?.content === 'true';
    }

    async loadFollowStatus() {
        try {
            const response = await fetch(`/api/follow-status/${this.storeId}/`);
            const data = await response.json();

            this.isFollowing = data.is_following;
            this.updateFollowButton();
            this.updateFollowersCount(data.followers_count);

        } catch (error) {
            console.error('Error loading follow status:', error);
        }
    }

    async toggleFollow() {
        if (!this.isUserAuthenticated()) {
            this.showLoginModal();
            return;
        }

        const followBtn = document.querySelector('.btn-follow');
        const originalText = followBtn.innerHTML;

        // Show loading state
        followBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span>Processing...</span>';
        followBtn.disabled = true;

        try {
            const response = await fetch(`/api/follow/${this.storeId}/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                }
            });

            const data = await response.json();

            if (data.success) {
                this.isFollowing = data.is_following;
                this.updateFollowButton();
                this.updateFollowersCount(data.followers_count);
                this.showToast('success', data.message);

                // Show notification preferences if just followed
                if (this.isFollowing) {
                    setTimeout(() => this.showNotificationPreferences(), 1000);
                }
            } else {
                this.showToast('error', data.message);
            }

        } catch (error) {
            console.error('Error toggling follow:', error);
            this.showToast('error', 'An error occurred. Please try again.');
        } finally {
            followBtn.innerHTML = originalText;
            followBtn.disabled = false;
            this.updateFollowButton();
        }
    }

    updateFollowButton() {
        const followBtn = document.querySelector('.btn-follow');
        const icon = followBtn.querySelector('i');
        const text = followBtn.querySelector('.btn-text');

        if (this.isFollowing) {
            followBtn.classList.remove('btn-outline-light');
            followBtn.classList.add('btn-success');
            icon.className = 'fas fa-check';
            text.textContent = 'Following';
            followBtn.setAttribute('aria-label', 'Unfollow store');
        } else {
            followBtn.classList.remove('btn-success');
            followBtn.classList.add('btn-outline-light');
            icon.className = 'fas fa-heart';
            text.textContent = 'Follow';
            followBtn.setAttribute('aria-label', 'Follow store');
        }
    }

    updateFollowersCount(count) {
        const countElement = document.querySelector('.followers-count');
        if (countElement) {
            countElement.textContent = count;
        }
    }

    showNotificationPreferences() {
        const modal = this.createNotificationPreferencesModal();
        document.body.appendChild(modal);
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();

        // Remove modal when hidden
        modal.addEventListener('hidden.bs.modal', () => {
            modal.remove();
        });
    }

    createNotificationPreferencesModal() {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Notification Preferences</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p class="mb-3">Choose what notifications you'd like to receive from this store:</p>
                        <div class="form-check mb-2">
                            <input class="form-check-input" type="checkbox" id="notifyNewProducts" checked>
                            <label class="form-check-label" for="notifyNewProducts">
                                <i class="fas fa-box text-primary me-2"></i>New Products
                            </label>
                        </div>
                        <div class="form-check mb-2">
                            <input class="form-check-input" type="checkbox" id="notifyPriceChanges" checked>
                            <label class="form-check-label" for="notifyPriceChanges">
                                <i class="fas fa-tag text-success me-2"></i>Price Changes
                            </label>
                        </div>
                        <div class="form-check mb-2">
                            <input class="form-check-input" type="checkbox" id="notifyDiscounts" checked>
                            <label class="form-check-label" for="notifyDiscounts">
                                <i class="fas fa-percent text-danger me-2"></i>Special Discounts
                            </label>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Skip</button>
                        <button type="button" class="btn btn-primary" onclick="storeFollowManager.saveNotificationPreferences(this)">
                            Save Preferences
                        </button>
                    </div>
                </div>
            </div>
        `;
        return modal;
    }

    async saveNotificationPreferences(button) {
        const modal = button.closest('.modal');
        const preferences = {
            notify_new_products: modal.querySelector('#notifyNewProducts').checked,
            notify_price_changes: modal.querySelector('#notifyPriceChanges').checked,
            notify_discounts: modal.querySelector('#notifyDiscounts').checked
        };

        try {
            const response = await fetch(`/api/notifications/preferences/${this.storeId}/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(preferences)
            });

            const data = await response.json();

            if (data.success) {
                this.showToast('success', 'Preferences saved successfully!');
                bootstrap.Modal.getInstance(modal).hide();
            } else {
                this.showToast('error', 'Failed to save preferences.');
            }

        } catch (error) {
            console.error('Error saving preferences:', error);
            this.showToast('error', 'An error occurred while saving preferences.');
        }
    }

    initNotifications() {
        this.createNotificationCenter();
        this.loadNotifications();
    }

    createNotificationCenter() {
        // Add notification bell to header if it doesn't exist
        const header = document.querySelector('.store-actions');
        if (header && this.isUserAuthenticated()) {
            const notificationBtn = document.createElement('button');
            notificationBtn.className = 'btn btn-outline-light btn-notifications position-relative';
            notificationBtn.innerHTML = `
                <i class="fas fa-bell"></i>
                <span class="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger notification-badge" style="display: none;">
                    0
                </span>
            `;
            notificationBtn.onclick = () => this.showNotificationPanel();
            header.appendChild(notificationBtn);
        }
    }

    async loadNotifications() {
        if (!this.isUserAuthenticated()) return;

        try {
            const response = await fetch('/api/notifications/');
            const data = await response.json();

            if (data.success) {
                this.unreadCount = data.unread_count;
                this.updateNotificationBadge();
            }

        } catch (error) {
            console.error('Error loading notifications:', error);
        }
    }

    updateNotificationBadge() {
        const badge = document.querySelector('.notification-badge');
        if (badge) {
            if (this.unreadCount > 0) {
                badge.textContent = this.unreadCount > 99 ? '99+' : this.unreadCount;
                badge.style.display = 'block';
            } else {
                badge.style.display = 'none';
            }
        }
    }

    async showNotificationPanel() {
        const modal = this.createNotificationModal();
        document.body.appendChild(modal);

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();

        // Load notifications
        await this.loadNotificationsList(modal);

        // Remove modal when hidden
        modal.addEventListener('hidden.bs.modal', () => {
            modal.remove();
        });
    }

    createNotificationModal() {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-bell me-2"></i>Notifications
                        </h5>
                        <div class="d-flex gap-2">
                            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="storeFollowManager.markAllAsRead()">
                                Mark All Read
                            </button>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                    </div>
                    <div class="modal-body p-0">
                        <div class="notifications-loading text-center p-4">
                            <i class="fas fa-spinner fa-spin"></i>
                            <p class="mt-2">Loading notifications...</p>
                        </div>
                        <div class="notifications-list" style="max-height: 400px; overflow-y: auto;"></div>
                    </div>
                </div>
            </div>
        `;
        return modal;
    }

    async loadNotificationsList(modal) {
        try {
            const response = await fetch('/api/notifications/');
            const data = await response.json();

            const loadingDiv = modal.querySelector('.notifications-loading');
            const listDiv = modal.querySelector('.notifications-list');

            loadingDiv.style.display = 'none';

            if (data.success && data.notifications.length > 0) {
                listDiv.innerHTML = data.notifications.map(notification =>
                    this.createNotificationItem(notification)
                ).join('');
            } else {
                listDiv.innerHTML = `
                    <div class="text-center p-4 text-muted">
                        <i class="fas fa-bell-slash fa-2x mb-2"></i>
                        <p>No notifications yet</p>
                    </div>
                `;
            }

        } catch (error) {
            console.error('Error loading notifications:', error);
            modal.querySelector('.notifications-loading').innerHTML = `
                <div class="text-danger">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>Error loading notifications</p>
                </div>
            `;
        }
    }

    createNotificationItem(notification) {
        const iconMap = {
            new_product: 'fas fa-box text-primary',
            price_decrease: 'fas fa-arrow-down text-success',
            price_increase: 'fas fa-arrow-up text-warning',
            discount: 'fas fa-percent text-danger',
            back_in_stock: 'fas fa-check-circle text-success'
        };

        const icon = iconMap[notification.type] || 'fas fa-bell text-info';
        const timeAgo = this.formatTimeAgo(new Date(notification.created_at));

        return `
            <div class="notification-item p-3 border-bottom ${notification.is_read ? '' : 'bg-light'}"
                 data-notification-id="${notification.id}">
                <div class="d-flex">
                    <div class="notification-icon me-3">
                        <i class="${icon}"></i>
                    </div>
                    <div class="notification-content flex-grow-1">
                        <h6 class="notification-title mb-1">${notification.title}</h6>
                        <p class="notification-message mb-1 text-muted small">${notification.message}</p>
                        <div class="d-flex justify-content-between align-items-center">
                            <small class="text-muted">
                                <i class="fas fa-store me-1"></i>${notification.store_name} • ${timeAgo}
                            </small>
                            ${!notification.is_read ? `
                                <button class="btn btn-sm btn-outline-primary"
                                        onclick="storeFollowManager.markAsRead(${notification.id}, this)">
                                    Mark Read
                                </button>
                            ` : ''}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    async markAsRead(notificationId, button) {
        try {
            const response = await fetch(`/api/notifications/${notificationId}/read/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                }
            });

            const data = await response.json();

            if (data.success) {
                const notificationItem = button.closest('.notification-item');
                notificationItem.classList.remove('bg-light');
                button.remove();

                this.unreadCount = data.unread_count;
                this.updateNotificationBadge();
            }

        } catch (error) {
            console.error('Error marking notification as read:', error);
        }
    }

    async markAllAsRead() {
        try {
            const response = await fetch('/api/notifications/mark-all-read/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                }
            });

            const data = await response.json();

            if (data.success) {
                // Update UI
                const notificationItems = document.querySelectorAll('.notification-item');
                notificationItems.forEach(item => {
                    item.classList.remove('bg-light');
                    const markReadBtn = item.querySelector('button');
                    if (markReadBtn) markReadBtn.remove();
                });

                this.unreadCount = 0;
                this.updateNotificationBadge();
                this.showToast('success', 'All notifications marked as read');
            }

        } catch (error) {
            console.error('Error marking all notifications as read:', error);
        }
    }

    startNotificationPolling() {
        // Check for new notifications every 30 seconds
        this.notificationCheckInterval = setInterval(() => {
            this.loadNotifications();
        }, 30000);
    }

    stopNotificationPolling() {
        if (this.notificationCheckInterval) {
            clearInterval(this.notificationCheckInterval);
        }
    }

    formatTimeAgo(date) {
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);

        if (seconds < 60) return 'just now';
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
        return `${Math.floor(seconds / 86400)}d ago`;
    }

    showLoginModal() {
        // You can customize this based on your login modal
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Login Required</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p>Please log in to follow stores and receive notifications.</p>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <a href="/login/" class="btn btn-primary">Login</a>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();

        modal.addEventListener('hidden.bs.modal', () => {
            modal.remove();
        });
    }

    showToast(type, message) {
        const toastId = type === 'success' ? 'successToast' : 'errorToast';
        const toast = document.getElementById(toastId);

        if (toast) {
            toast.querySelector('.toast-body').textContent = message;
            const bsToast = new bootstrap.Toast(toast);
            bsToast.show();
        }
    }

    getCSRFToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
               document.querySelector('meta[name="csrf-token"]')?.content ||
               '';
    }

    bindEvents() {
        // Bind follow button click
        const followBtn = document.querySelector('.btn-follow');
        if (followBtn) {
            followBtn.addEventListener('click', () => this.toggleFollow());
        }

        // Handle page unload
        window.addEventListener('beforeunload', () => {
            this.stopNotificationPolling();
        });
    }
}

// Global function for backward compatibility with existing template
function toggleFavorite(storeId) {
    if (window.storeFollowManager) {
        window.storeFollowManager.toggleFollow();
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    window.storeFollowManager = new StoreFollowManager();
});

// Also initialize if page is already loaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        if (!window.storeFollowManager) {
            window.storeFollowManager = new StoreFollowManager();
        }
    });
} else {
    if (!window.storeFollowManager) {
        window.storeFollowManager = new StoreFollowManager();
    }
}