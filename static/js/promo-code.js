/**
 * Promo Code Module
 * Handles validation and application of promotional codes
 * 
 * @requires CSRF token
 * @requires bootstrap (for toast notifications)
 */

(function() {
    'use strict';

    // DOM Elements
    const elements = {
        applyBtn: null,
        promoInput: null,
        promoHidden: null,
        feedback: null,
        appliedPromo: null,
        appliedPromoCode: null,
        removePromoBtn: null,
        promoDiscountDiv: null,
        promoDiscountAmount: null,
        totalPriceSpan: null,
        subtotalSpan: null
    };

    let csrfToken = '';

    /**
     * Initialize promo code functionality
     */
    function init() {
        // Get CSRF token
        csrfToken = getCSRFToken();

        if (!csrfToken) {
            console.error('CSRF token not found - promo code operations will fail');
        }

        // Initialize DOM elements
        initializeElements();

        // Check if promo elements exist
        if (!elements.applyBtn && !elements.promoInput) {
            console.log('Promo code elements not found - skipping initialization');
            return;
        }

        // Attach event listeners
        attachEventListeners();

        console.log('Promo code module initialized');
    }

    /**
     * Get all DOM elements
     */
    function initializeElements() {
        elements.applyBtn = document.getElementById('applyPromo');
        elements.promoInput = document.getElementById('promoCodeInput');
        elements.promoHidden = document.getElementById('promoCodeHidden');
        elements.feedback = document.getElementById('promoFeedback');
        elements.appliedPromo = document.getElementById('appliedPromo');
        elements.appliedPromoCode = document.getElementById('appliedPromoCode');
        elements.removePromoBtn = document.getElementById('removePromo');
        elements.promoDiscountDiv = document.querySelector('.promo-discount');
        elements.promoDiscountAmount = document.getElementById('promo-discount-amount');
        elements.totalPriceSpan = document.getElementById('total-price');
        elements.subtotalSpan = document.getElementById('order-subtotal');
    }

    /**
     * Attach event listeners
     */
    function attachEventListeners() {
        // Apply promo code
        if (elements.applyBtn) {
            elements.applyBtn.addEventListener('click', handleApplyPromo);
        }

        // Remove promo code
        if (elements.removePromoBtn) {
            elements.removePromoBtn.addEventListener('click', handleRemovePromo);
        }

        // Enter key on input
        if (elements.promoInput) {
            elements.promoInput.addEventListener('keypress', function(event) {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    if (elements.applyBtn) {
                        elements.applyBtn.click();
                    }
                }
            });
        }
    }

    /**
     * Handle apply promo code
     */
    async function handleApplyPromo() {
        const code = (elements.promoInput?.value || '').trim();

        if (!code) {
            showToast('Please enter a promo code', 'warning');
            return;
        }

        const btn = elements.applyBtn;
        const originalHTML = btn.innerHTML;
        
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Applying...';

        // Hide previous feedback
        if (elements.feedback) {
            elements.feedback.classList.add('d-none');
        }

        try {
            const validateUrl = window.VALIDATE_PROMO_URL || '/orders/validate-promo/';
            
            const response = await fetch(validateUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': csrfToken
                },
                body: new URLSearchParams({
                    promo_code: code
                })
            });

            const data = await response.json();

            if (!data.success) {
                // Show error feedback
                if (elements.feedback) {
                    elements.feedback.textContent = data.message;
                    elements.feedback.className = 'small text-danger mt-2';
                    elements.feedback.classList.remove('d-none');
                }
                showToast(data.message, 'danger');
                return;
            }

            // Apply promo code
            applyPromoCode(code, data);

            showToast(
                `Promo code applied! ${data.discount_percentage}% discount`,
                'success'
            );

        } catch (error) {
            console.error('Error validating promo code:', error);
            showToast('Error validating promo code', 'danger');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-check me-1"></i> Apply';
        }
    }

    /**
     * Apply promo code to UI
     * @param {string} code - Promo code
     * @param {Object} data - Promo validation data
     */
    function applyPromoCode(code, data) {
        // Store promo code
        if (elements.promoHidden) {
            elements.promoHidden.value = code;
        }

        // Show applied promo
        if (elements.appliedPromoCode) {
            elements.appliedPromoCode.textContent = code;
        }
        
        if (elements.appliedPromo) {
            elements.appliedPromo.classList.remove('d-none');
        }

        // Clear input
        if (elements.promoInput) {
            elements.promoInput.value = '';
        }

        // Hide feedback
        if (elements.feedback) {
            elements.feedback.classList.add('d-none');
        }

        // Calculate and update prices
        updatePrices(data);
    }

    /**
     * Update prices with discount
     * @param {Object} data - Promo data containing discount_percentage
     */
    function updatePrices(data) {
        if (!elements.subtotalSpan || !elements.totalPriceSpan) {
            return;
        }

        const currentSubtotal = parseCurrency(elements.subtotalSpan.textContent);
        const discountPercentage = data.discount_percentage || 0;
        const discountAmount = (currentSubtotal * discountPercentage) / 100.0;
        const newTotal = Math.max(currentSubtotal - discountAmount, 0);

        // Update discount amount display
        if (elements.promoDiscountAmount) {
            elements.promoDiscountAmount.textContent = `-${formatCurrency(discountAmount)}`;
        }

        // Show discount row
        if (elements.promoDiscountDiv) {
            elements.promoDiscountDiv.classList.remove('d-none');
        }

        // Update total
        elements.totalPriceSpan.textContent = formatCurrency(newTotal);
    }

    /**
     * Handle remove promo code
     */
    function handleRemovePromo() {
        // Clear hidden input
        if (elements.promoHidden) {
            elements.promoHidden.value = '';
        }

        // Hide applied promo section
        if (elements.appliedPromo) {
            elements.appliedPromo.classList.add('d-none');
        }

        // Hide discount row
        if (elements.promoDiscountDiv) {
            elements.promoDiscountDiv.classList.add('d-none');
        }

        // Reset total to subtotal
        if (elements.subtotalSpan && elements.totalPriceSpan) {
            const currentSubtotal = parseCurrency(elements.subtotalSpan.textContent);
            elements.totalPriceSpan.textContent = formatCurrency(currentSubtotal);
        }

        showToast('Promo code removed', 'info');
    }

    // ========================================================================
    // Utility Functions
    // ========================================================================

    /**
     * Parse currency string to number
     * @param {string} text - Currency text (e.g., "D123.45")
     * @returns {number} Parsed number
     */
    function parseCurrency(text) {
        return parseFloat((text || '').replace(/[^\d.]/g, '')) || 0;
    }

    /**
     * Format number as currency
     * @param {number} amount - Amount to format
     * @returns {string} Formatted currency (e.g., "D123.45")
     */
    function formatCurrency(amount) {
        return `D${Number(amount).toFixed(2)}`;
    }

    /**
     * Get CSRF token from cookies or DOM
     * @returns {string} CSRF token
     */
    function getCSRFToken() {
        // Try window.getCSRFToken if available
        if (window.getCSRFToken && typeof window.getCSRFToken === 'function') {
            return window.getCSRFToken();
        }

        // Try to get from cookie
        let token = getCookie('csrftoken');
        
        // Fallback to hidden input
        if (!token) {
            const tokenInput = document.querySelector('[name=csrfmiddlewaretoken]');
            if (tokenInput) {
                token = tokenInput.value;
            }
        }
        
        return token || '';
    }

    /**
     * Get cookie value by name
     * @param {string} name - Cookie name
     * @returns {string|null} Cookie value
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
     * Show toast notification
     * @param {string} message - Message to display
     * @param {string} type - Toast type
     */
    function showToast(message, type) {
        if (window.showToast && typeof window.showToast === 'function') {
            window.showToast(message, type);
        } else {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
