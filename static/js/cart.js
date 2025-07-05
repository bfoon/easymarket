/**
 * Cart Management JavaScript
 * Handles cart operations including quantity updates, item removal, and promo codes
 */

// Global variables
let csrfToken = null;

// Initialize cart functionality when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeCart();
});

/**
 * Initialize cart functionality
 */
function initializeCart() {
    // Get CSRF token
    csrfToken = getCSRFToken();

    if (!csrfToken) {
        console.error('CSRF token not found! Cart operations may fail.');
    }

    // Initialize event listeners
    initializeQuantityControls();
    initializeRemoveButtons();
    initializePromoCode();
    initializeInputValidation();
}

/**
 * Get CSRF token from various sources
 */
function getCSRFToken() {
    // Try multiple sources for CSRF token
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
           document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
           document.querySelector('input[name="csrfmiddlewaretoken"]')?.value ||
           getCookie('csrftoken');
}

/**
 * Get cookie value by name (for CSRF token)
 */
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

/**
 * Initialize quantity control buttons
 */
function initializeQuantityControls() {
    document.querySelectorAll('.quantity-btn').forEach(button => {
        button.addEventListener('click', function() {
            const action = this.dataset.action;
            const itemId = this.dataset.itemId;
            const productId = this.dataset.productId;
            const input = document.querySelector(`input[data-item-id="${itemId}"]`);
            let currentValue = parseInt(input.value) || 1;

            let newValue = currentValue;
            if (action === 'increase' && currentValue < 99) {
                newValue = currentValue + 1;
            } else if (action === 'decrease' && currentValue > 1) {
                newValue = currentValue - 1;
            }

            if (newValue !== currentValue) {
                input.value = newValue;
                updateCartItem(productId, itemId, newValue);
            }
        });
    });
}

/**
 * Initialize direct quantity input handling
 */
function initializeInputValidation() {
    document.querySelectorAll('.quantity-input').forEach(input => {
        // Store original value for reverting on error
        input.dataset.originalValue = input.value;

        // Handle focus event
        input.addEventListener('focus', function() {
            this.dataset.originalValue = this.value;
        });

        // Handle change event
        input.addEventListener('change', function() {
            const itemId = this.dataset.itemId;
            const productId = this.dataset.productId;
            let value = parseInt(this.value) || 1;

            // Validate input
            if (value < 1) value = 1;
            if (value > 99) value = 99;

            this.value = value;
            updateCartItem(productId, itemId, value);
        });

        // Prevent invalid input during typing
        input.addEventListener('input', function() {
            const value = this.value;
            if (value === '' || parseInt(value) < 1) {
                // Don't change immediately, wait for blur/change
            } else if (parseInt(value) > 99) {
                this.value = 99;
            }
        });
    });
}

/**
 * Initialize remove item buttons
 */
function initializeRemoveButtons() {
    document.querySelectorAll('.remove-item').forEach(button => {
        button.addEventListener('click', function() {
            const itemId = this.dataset.itemId;
            const productId = this.dataset.productId;

            if (confirm('Are you sure you want to remove this item from your cart?')) {
                removeCartItem(productId, itemId);
            }
        });
    });
}

/**
 * Initialize promo code functionality
 */
function initializePromoCode() {
    const applyButton = document.getElementById('applyPromo');
    const promoInput = document.getElementById('promoCode');

    if (applyButton) {
        applyButton.addEventListener('click', function() {
            const promoCode = promoInput?.value.trim();
            if (promoCode) {
                applyPromoCode(promoCode);
            } else {
                showToast('Please enter a promo code', 'error');
            }
        });
    }

    if (promoInput) {
        promoInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                applyButton?.click();
            }
        });
    }
}

/**
 * Update cart item quantity
 */
function updateCartItem(productId, itemId, quantity) {
    // Disable buttons during request
    const buttons = document.querySelectorAll(`[data-item-id="${itemId}"]`);
    buttons.forEach(btn => btn.disabled = true);

    // Get URLs from global variables or construct them
    const updateUrl = window.cartUrls?.updateQuantity || '/update-cart-quantity/';

    fetch(updateUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: `product_id=${productId}&quantity=${quantity}`
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            // Update quantity input
            const input = document.querySelector(`input[data-item-id="${itemId}"]`);
            if (input) {
                input.value = data.quantity;
                input.dataset.originalValue = data.quantity;
            }

            // Update subtotal for this item
            const subtotalEl = document.querySelector(`tr[data-item-id="${itemId}"] .subtotal`);
            if (subtotalEl) subtotalEl.textContent = `$${data.subtotal}`;

            // Update order summary
            updateOrderSummary(data);

            showToast('Cart updated successfully!');
        } else {
            showToast(data.message || 'Failed to update cart', 'error');
            revertInputValue(itemId);
        }
    })
    .catch(error => {
        console.error('Error updating cart:', error);
        showToast('Error updating cart. Please try again.', 'error');
        revertInputValue(itemId);
    })
    .finally(() => {
        // Re-enable buttons
        buttons.forEach(btn => btn.disabled = false);
    });
}

/**
 * Remove item from cart
 */
function removeCartItem(productId, itemId) {
    const row = document.querySelector(`tr[data-item-id="${itemId}"]`);
    const removeUrl = window.cartUrls?.removeItem || '/remove-cart-item/';

    fetch(removeUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: `product_id=${productId}`
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            // Remove the row with animation
            if (row) {
                row.style.transition = 'opacity 0.3s ease';
                row.style.opacity = '0';
                setTimeout(() => {
                    row.remove();
                    // Check if cart is empty
                    if (document.querySelectorAll('.cart-item').length === 0) {
                        location.reload(); // Reload to show empty cart message
                    }
                }, 300);
            }

            // Update order summary
            updateOrderSummary(data);

            showToast('Item removed from cart!');
        } else {
            showToast(data.message || 'Failed to remove item', 'error');
        }
    })
    .catch(error => {
        console.error('Error removing item:', error);
        showToast('Error removing item. Please try again.', 'error');
    });
}

/**
 * Apply promo code
 */
function applyPromoCode(code) {
    const applyUrl = window.cartUrls?.applyPromo || '/apply-promo-code/';

    fetch(applyUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: `promo_code=${encodeURIComponent(code)}`
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            updateOrderSummary(data);
            showToast(`Promo code applied! You saved $${data.discount}`);
            document.getElementById('promoCode').value = '';
        } else {
            showToast(data.message || 'Invalid promo code', 'error');
        }
    })
    .catch(error => {
        console.error('Error applying promo code:', error);
        showToast('Error applying promo code. Please try again.', 'error');
    });
}

/**
 * Update order summary with new data
 */
function updateOrderSummary(data) {
    // Update item count
    const itemCountEl = document.getElementById('item-count');
    if (itemCountEl && data.item_count !== undefined) {
        itemCountEl.textContent = data.item_count;
    }

    // Update subtotal
    const subtotalEl = document.getElementById('order-subtotal');
    if (subtotalEl && data.total_price !== undefined) {
        subtotalEl.textContent = `$${data.total_price}`;
    }

    // Update total
    const totalEl = document.getElementById('total-price');
    if (totalEl && data.final_total !== undefined) {
        totalEl.textContent = `$${data.final_total}`;
    } else if (totalEl && data.total_price !== undefined) {
        totalEl.textContent = `$${data.total_price}`;
    }

    // Update tax if provided
    const taxEl = document.getElementById('tax-amount');
    if (taxEl && data.tax_amount !== undefined) {
        taxEl.textContent = `$${data.tax_amount}`;
    }

    // Update cart badge in header
    updateCartBadge(data.item_count);
}

/**
 * Update cart badge in navigation
 */
function updateCartBadge(itemCount) {
    const badges = document.querySelectorAll('.cart-badge, .badge[data-cart-count]');
    badges.forEach(badge => {
        if (badge && itemCount !== undefined) {
            if (itemCount > 0) {
                badge.textContent = itemCount;
                badge.style.display = 'inline';
            } else {
                badge.style.display = 'none';
            }
        }
    });

    // Update cart count text
    const countTexts = document.querySelectorAll('[data-cart-count-text]');
    countTexts.forEach(element => {
        if (element && itemCount !== undefined) {
            const itemText = itemCount === 1 ? 'item' : 'items';
            element.textContent = `${itemCount} ${itemText}`;
        }
    });
}

/**
 * Revert input value to original on error
 */
function revertInputValue(itemId) {
    const input = document.querySelector(`input[data-item-id="${itemId}"]`);
    if (input) {
        input.value = input.dataset.originalValue || 1;
    }
}

/**
 * Show toast notification
 */
function showToast(message, type = 'success') {
    const toast = document.getElementById('cartToast');

    if (toast) {
        const toastBody = toast.querySelector('.toast-body');

        // Update message
        if (toastBody) toastBody.textContent = message;

        // Update toast color based on type
        toast.className = `toast align-items-center text-white border-0 ${type === 'error' ? 'bg-danger' : 'bg-success'}`;

        // Show toast
        if (typeof bootstrap !== 'undefined') {
            const bsToast = new bootstrap.Toast(toast);
            bsToast.show();
        } else {
            // Fallback if Bootstrap JS is not loaded
            toast.style.display = 'block';
            setTimeout(() => {
                toast.style.display = 'none';
            }, 3000);
        }
    } else {
        // Fallback: create a simple alert
        console.log(`${type.toUpperCase()}: ${message}`);
        // You could create a custom toast here if needed
    }
}

/**
 * Utility function to refresh CSRF token if needed
 */
function refreshCSRFToken() {
    csrfToken = getCSRFToken();
    return csrfToken;
}

// Export functions for global access if needed
window.cartManager = {
    updateCartItem,
    removeCartItem,
    applyPromoCode,
    updateOrderSummary,
    updateCartBadge,
    showToast,
    refreshCSRFToken,
    getCSRFToken
};