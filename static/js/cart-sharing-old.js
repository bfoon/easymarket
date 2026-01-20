/**
 * Cart Sharing Module
 * Handles copying and sharing cart links via WhatsApp
 * 
 * @requires bootstrap (for toast notifications)
 * @requires Django CSRF token
 */

(function() {
    'use strict';

    // DOM elements
    let copyCartBtn = null;
    let whatsappShareBtn = null;
    let shareUrl = null;

    /**
     * Initialize cart sharing functionality
     */
    function init() {
        // Get DOM elements
        copyCartBtn = document.getElementById('copyCartBtn');
        whatsappShareBtn = document.getElementById('whatsappShareBtn');

        if (!copyCartBtn && !whatsappShareBtn) {
            console.log('Cart sharing buttons not found - skipping initialization');
            return;
        }

        // Fetch share URL
        fetchShareUrl();

        // Attach event listeners
        attachEventListeners();
    }

    /**
     * Fetch the share URL from server
     */
    function fetchShareUrl() {
        // Note: This URL will be injected by Django template
        const shareUrlEndpoint = window.CART_SHARE_URL || '/cart/share/';
        
        fetch(shareUrlEndpoint)
            .then(response => response.json())
            .then(data => {
                if (data.share_url) {
                    shareUrl = data.share_url;
                }
            })
            .catch(error => {
                console.warn('Share URL fetch failed:', error);
            });
    }

    /**
     * Attach event listeners to sharing buttons
     */
    function attachEventListeners() {
        if (copyCartBtn) {
            copyCartBtn.addEventListener('click', handleCopyClick);
        }

        if (whatsappShareBtn) {
            whatsappShareBtn.addEventListener('click', handleWhatsAppClick);
        }
    }

    /**
     * Handle copy to clipboard click
     */
    function handleCopyClick() {
        if (!shareUrl) {
            showToast('Generating share link, please wait...', 'info');
            return;
        }

        // Try modern clipboard API first
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(shareUrl)
                .then(() => {
                    showToast('Cart link copied!', 'success');
                })
                .catch(() => {
                    fallbackCopyText(shareUrl);
                });
        } else {
            fallbackCopyText(shareUrl);
        }
    }

    /**
     * Handle WhatsApp share click
     */
    function handleWhatsAppClick() {
        if (!shareUrl) {
            showToast('Generating share link, please wait...', 'info');
            return;
        }

        const message = encodeURIComponent(
            `🛒 Check out my cart on EasyMarket!\n\n${shareUrl}`
        );
        
        window.open(`https://wa.me/?text=${message}`, '_blank');
    }

    /**
     * Fallback method for copying text (for older browsers)
     * @param {string} text - Text to copy
     */
    function fallbackCopyText(text) {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        textarea.style.top = '0';
        textarea.style.left = '0';
        
        document.body.appendChild(textarea);
        textarea.select();
        textarea.setSelectionRange(0, 99999); // For mobile devices

        try {
            document.execCommand('copy');
            showToast('Cart link copied to clipboard!', 'success');
        } catch (err) {
            console.error('Fallback copy failed:', err);
            showToast('Please copy manually: ' + text, 'warning');
        }

        document.body.removeChild(textarea);
    }

    /**
     * Show toast notification
     * Falls back to console if showToast is not available
     * @param {string} message - Message to display
     * @param {string} type - Toast type (success, info, warning, danger)
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
