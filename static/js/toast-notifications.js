/**
 * Toast Notifications Module
 * Global toast notification helper using Bootstrap 5
 * 
 * @requires bootstrap 5
 */

(function() {
    'use strict';

    /**
     * Show toast notification
     * @param {string} message - Message to display
     * @param {string} type - Toast type: 'success', 'danger', 'warning', 'info'
     * @param {number} delay - Auto-hide delay in milliseconds (default: 4000)
     */
    window.showToast = function(message, type = 'success', delay = 4000) {
        // Get or create toast element
        let toast = document.getElementById('cartToast');
        
        if (!toast) {
            toast = createToastElement();
        }

        // Get toast body
        const toastBody = toast.querySelector('.toast-body');
        
        if (!toastBody) {
            console.error('Toast body not found');
            return;
        }

        // Map toast types to Bootstrap background classes
        const bgClassMap = {
            'success': 'bg-success',
            'danger': 'bg-danger',
            'warning': 'bg-warning',
            'info': 'bg-info'
        };

        const bgClass = bgClassMap[type] || 'bg-success';

        // Update toast styling
        toast.className = `toast align-items-center text-white ${bgClass} border-0 shadow-lg`;
        
        // Update toast message
        toastBody.textContent = message;

        // Show toast using Bootstrap's Toast API
        if (typeof bootstrap !== 'undefined' && bootstrap.Toast) {
            const bsToast = new bootstrap.Toast(toast, {
                autohide: true,
                delay: delay
            });
            bsToast.show();
        } else {
            // Fallback: manual show/hide
            toast.style.display = 'block';
            toast.classList.add('show');
            
            setTimeout(() => {
                toast.classList.remove('show');
                setTimeout(() => {
                    toast.style.display = 'none';
                }, 150);
            }, delay);
        }
    };

    /**
     * Create toast element if it doesn't exist
     * @returns {HTMLElement} Toast element
     */
    function createToastElement() {
        // Create toast container
        let container = document.querySelector('.toast-container');
        
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            container.style.zIndex = '1060';
            document.body.appendChild(container);
        }

        // Create toast element
        const toast = document.createElement('div');
        toast.id = 'cartToast';
        toast.className = 'toast align-items-center text-white bg-success border-0 shadow-lg';
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');

        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body"></div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        `;

        container.appendChild(toast);
        
        return toast;
    }

    /**
     * Show success toast (convenience method)
     * @param {string} message - Message to display
     */
    window.showSuccessToast = function(message) {
        window.showToast(message, 'success');
    };

    /**
     * Show error toast (convenience method)
     * @param {string} message - Message to display
     */
    window.showErrorToast = function(message) {
        window.showToast(message, 'danger');
    };

    /**
     * Show warning toast (convenience method)
     * @param {string} message - Message to display
     */
    window.showWarningToast = function(message) {
        window.showToast(message, 'warning');
    };

    /**
     * Show info toast (convenience method)
     * @param {string} message - Message to display
     */
    window.showInfoToast = function(message) {
        window.showToast(message, 'info');
    };

    console.log('Toast notifications module loaded');

})();
